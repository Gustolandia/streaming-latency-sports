"""Tests for scripts/recount_spans.py.

The script exists to settle a question the manuscript got wrong for two versions: whether
the negatives in the corpus are a physical impossibility or a late acknowledgement stamp.
Its answer depends entirely on subtracting the right pair of columns, so the tests are
built around that: every span is checked independently, and a run that is negative on the
acknowledgement span and clean on the send span must be reported as exactly that.
"""
import csv
import io
import json
import os
import sys
import tarfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import recount_spans as rs  # noqa: E402


def prod_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["run_id", "backend", "event_id",
                                        "t_prod_sched_ns", "t_prod_send_ns",
                                        "t_broker_ack_ns"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def cons_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["run_id", "backend", "event_id",
                                        "t_cons_recv_ns", "t_output_ns"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def one_event(sched=0, send=100, ack=900, recv=500, output=600, eid="e1"):
    """A single event. The defaults are the corpus's shape: the acknowledgement lands
    after the consumer already has the record, so the ack span is negative (500-900)
    while the send span is positive (500-100)."""
    return (
        [{"run_id": "r", "backend": "kafka", "event_id": eid, "t_prod_sched_ns": sched,
          "t_prod_send_ns": send, "t_broker_ack_ns": ack}],
        [{"run_id": "r", "backend": "kafka", "event_id": eid,
          "t_cons_recv_ns": recv, "t_output_ns": output}],
    )


class TestJoin:
    def test_the_two_spans_disagree_in_sign_on_a_late_acknowledgement(self):
        p, c = one_event()
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        assert spans["ack"] == [-400]
        assert spans["send"] == [400]
        assert spans["output_send"] == [500]
        assert spans["tti"] == [600]

    def test_events_only_on_one_side_are_not_joined(self):
        p, _ = one_event(eid="a")
        _, c = one_event(eid="b")
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        assert spans["ack"] == []

    def test_a_producer_row_with_an_unparsable_stamp_is_skipped(self):
        p, c = one_event()
        p[0]["t_broker_ack_ns"] = "not-a-number"
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        assert spans["ack"] == []

    def test_a_consumer_row_with_an_unparsable_stamp_is_skipped(self):
        p, c = one_event()
        c[0]["t_output_ns"] = ""
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        assert spans["ack"] == []

    def test_a_producer_row_missing_a_column_entirely_is_skipped(self):
        rows = list(csv.DictReader(io.StringIO("event_id\ne1\n")))
        spans = rs.join_run(rows, rs.parse_rows(cons_csv(one_event()[1])))
        assert spans["ack"] == []

    def test_a_consumer_row_without_an_event_id_is_skipped(self):
        p, _ = one_event()
        rows = list(csv.DictReader(io.StringIO("t_cons_recv_ns\n5\n")))
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rows)
        assert spans["ack"] == []


class TestSummariseRun:
    def test_counts_and_microsecond_conversions(self):
        p, c = one_event(send=0, ack=2_000_000, recv=1_000_000, output=1_000_000)
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        row = rs.summarise_run("run-1", "kafka", spans)
        assert row["n_events"] == 1
        assert row["neg_ack"] == 1 and row["neg_send"] == 0
        assert row["min_ack_us"] == -1000.0
        assert row["median_send_us"] == 1000.0

    def test_a_run_with_nothing_joined_yields_no_row(self):
        assert rs.summarise_run("r", "kafka", {n: [] for n, _, _ in rs.SPANS}) is None


class TestBackend:
    def test_meta_json_wins(self):
        assert rs._backend_of(json.dumps({"backend": "redis"}).encode(), []) == "redis"

    def test_unparsable_meta_falls_back_to_the_producer_log(self):
        assert rs._backend_of(b"{not json", [{"backend": "kafka"}]) == "kafka"

    def test_absent_meta_falls_back_to_the_producer_log(self):
        assert rs._backend_of(None, [{"backend": "kafka"}]) == "kafka"

    def test_absent_meta_and_no_rows_gives_empty(self):
        assert rs._backend_of(None, []) == ""


class TestEmit:
    def _collected(self, **over):
        p, c = one_event()
        base = {"producer": prod_csv(p), "consumer": cons_csv(c),
                "meta": json.dumps({"backend": "kafka"}).encode()}
        base.update(over)
        return {"run-1": base}

    def test_a_good_run_produces_a_row(self):
        rows, skipped = [], []
        rs._emit(self._collected(), rows, skipped)
        assert len(rows) == 1 and skipped == []

    @pytest.mark.parametrize("drop,reason", [("producer", "missing producer.csv"),
                                             ("consumer", "missing consumer.csv")])
    def test_a_missing_file_is_recorded_not_silently_dropped(self, drop, reason):
        c = self._collected()
        del c["run-1"][drop]
        rows, skipped = [], []
        rs._emit(c, rows, skipped)
        assert rows == [] and skipped == [("run-1", reason)]

    def test_an_empty_file_is_recorded(self):
        rows, skipped = [], []
        rs._emit(self._collected(producer=prod_csv([])), rows, skipped)
        assert rows == [] and "empty" in skipped[0][1]

    def test_a_run_whose_events_do_not_join_is_recorded(self):
        _, c = one_event(eid="other")
        rows, skipped = [], []
        rs._emit(self._collected(consumer=cons_csv(c)), rows, skipped)
        assert rows == [] and skipped == [("run-1", "no joined events")]


class TestScanners:
    def _tree(self, tmp_path, run_id="run-1"):
        d = tmp_path / "runs" / run_id
        d.mkdir(parents=True)
        p, c = one_event()
        (d / "producer.csv").write_bytes(prod_csv(p))
        (d / "consumer.csv").write_bytes(cons_csv(c))
        (d / "meta.json").write_text(json.dumps({"backend": "kafka"}))
        return tmp_path / "runs"

    def test_scan_dir(self, tmp_path):
        rows, skipped = rs.scan_dir(str(self._tree(tmp_path)))
        assert len(rows) == 1 and rows[0]["neg_ack"] == 1 and rows[0]["neg_send"] == 0

    def test_scan_dir_ignores_stray_files(self, tmp_path):
        root = self._tree(tmp_path)
        (root / "notes.txt").write_text("x")
        rows, _ = rs.scan_dir(str(root))
        assert len(rows) == 1

    def test_scan_dir_skips_a_run_directory_with_no_recognised_files(self, tmp_path):
        root = self._tree(tmp_path)
        (root / "empty-run").mkdir()
        rows, skipped = rs.scan_dir(str(root))
        assert len(rows) == 1 and skipped == []

    def test_scan_archive_reads_members_without_unpacking(self, tmp_path):
        root = self._tree(tmp_path)
        tgz = tmp_path / "runs.tgz"
        with tarfile.open(tgz, "w:gz") as tf:
            tf.add(str(root), arcname="runs")
            info = tarfile.TarInfo("runs/ignored-dir")
            info.type = tarfile.DIRTYPE
            tf.addfile(info)
            stray = tarfile.TarInfo("elsewhere/file.csv")
            stray.size = 1
            tf.addfile(stray, io.BytesIO(b"x"))
            other = tarfile.TarInfo("runs/run-1/other.txt")
            other.size = 1
            tf.addfile(other, io.BytesIO(b"x"))
        rows, _ = rs.scan_archive(str(tgz))
        assert len(rows) == 1 and rows[0]["run_id"] == "run-1"


class TestTotalsAndReport:
    def test_totals_sum_and_percent(self):
        rows = [{"n_events": "10", "neg_ack": "2", "neg_send": "0", "neg_output_send": "0",
                 "neg_tti": "0", "median_ack_us": "-1.0"},
                {"n_events": "10", "neg_ack": "0", "neg_send": "0", "neg_output_send": "0",
                 "neg_tti": "0", "median_ack_us": "5.0"}]
        agg = rs.totals(rows)
        assert agg["runs"] == 2 and agg["events"] == 20
        assert agg["neg_ack"] == 2 and agg["pct_ack"] == pytest.approx(10.0)
        assert agg["runs_over_one_pct_ack"] == 1
        assert agg["runs_negative_median_ack"] == 1

    def test_totals_of_nothing_does_not_divide_by_zero(self):
        agg = rs.totals([])
        assert agg["events"] == 0 and agg["pct_ack"] == 0.0

    def test_a_run_with_no_events_is_not_counted_as_over_one_percent(self):
        agg = rs.totals([{"n_events": "0", "neg_ack": "0", "neg_send": "0",
                          "neg_output_send": "0", "neg_tti": "0", "median_ack_us": "0"}])
        assert agg["runs_over_one_pct_ack"] == 0

    def test_report_names_every_span(self):
        text = rs.report(rs.totals([]))
        for label in ("ack-referenced", "send-referenced", "send-to-output", "TTI"):
            assert label in text


class TestRoundTrip:
    def test_write_then_read(self, tmp_path):
        p, c = one_event()
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        out = tmp_path / "sub" / "recount.csv"
        rs.write_csv([rs.summarise_run("run-1", "kafka", spans)], str(out))
        back = rs.read_csv(str(out))
        assert back[0]["run_id"] == "run-1" and back[0]["neg_ack"] == "1"

    def test_rows_are_written_in_run_id_order(self, tmp_path):
        p, c = one_event()
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        rows = [rs.summarise_run(r, "kafka", spans) for r in ("b", "a")]
        out = tmp_path / "recount.csv"
        rs.write_csv(rows, str(out))
        assert [r["run_id"] for r in rs.read_csv(str(out))] == ["a", "b"]


class TestCLI:
    def _tree(self, tmp_path):
        d = tmp_path / "runs" / "run-1"
        d.mkdir(parents=True)
        p, c = one_event()
        (d / "producer.csv").write_bytes(prod_csv(p))
        (d / "consumer.csv").write_bytes(cons_csv(c))
        return tmp_path / "runs"

    def test_runs_dir_writes_the_csv(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rc = rs.main(["--runs-dir", str(self._tree(tmp_path)), "--out", str(out)])
        assert rc == 0 and out.exists()
        assert "send-referenced  negatives 0" in capsys.readouterr().out

    def test_missing_runs_dir_fails(self, tmp_path, capsys):
        rc = rs.main(["--runs-dir", str(tmp_path / "nope")])
        assert rc == 1 and "missing" in capsys.readouterr().out

    def test_missing_archive_fails(self, tmp_path, capsys):
        rc = rs.main(["--archive", str(tmp_path / "nope.tgz")])
        assert rc == 1 and "missing" in capsys.readouterr().out

    def test_archive_path(self, tmp_path, capsys):
        root = self._tree(tmp_path)
        tgz = tmp_path / "runs.tgz"
        with tarfile.open(tgz, "w:gz") as tf:
            tf.add(str(root), arcname="runs")
        out = tmp_path / "out.csv"
        rc = rs.main(["--archive", str(tgz), "--out", str(out)])
        assert rc == 0 and "1 runs" in capsys.readouterr().out

    def test_a_corpus_that_joins_nothing_refuses_to_write(self, tmp_path, capsys):
        d = tmp_path / "runs" / "run-1"
        d.mkdir(parents=True)
        (d / "producer.csv").write_bytes(prod_csv([]))
        (d / "consumer.csv").write_bytes(cons_csv([]))
        rc = rs.main(["--runs-dir", str(tmp_path / "runs"), "--out", str(tmp_path / "o.csv")])
        assert rc == 1 and "refusing" in capsys.readouterr().out

    def test_summary_reads_the_committed_csv(self, tmp_path, capsys):
        out = tmp_path / "out.csv"
        rs.main(["--runs-dir", str(self._tree(tmp_path)), "--out", str(out)])
        capsys.readouterr()
        rc = rs.main(["--summary", "--out", str(out)])
        assert rc == 0 and "runs 1" in capsys.readouterr().out

    def test_summary_without_a_csv_fails(self, tmp_path, capsys):
        rc = rs.main(["--summary", "--out", str(tmp_path / "nope.csv")])
        assert rc == 1 and "missing" in capsys.readouterr().out


class TestCommittedArtefact:
    """The committed CSV is what the manuscript's macros derive from, so it is the thing
    that must hold the finding, not a number retyped from a chat log."""

    def test_the_committed_recount_shows_the_split(self):
        path = os.path.join("docs", "results", "span_recount.csv")
        if not os.path.exists(path):
            pytest.skip("recount artefact not present")
        agg = rs.totals(rs.read_csv(path))
        assert agg["neg_ack"] > 0, "the acknowledgement-referenced span must show negatives"
        assert agg["neg_send"] == 0, "the send-referenced span must be clean"
        assert agg["neg_tti"] == 0, "TTI must be clean"
        assert agg["events"] > 100000
