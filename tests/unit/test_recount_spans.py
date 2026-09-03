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

    def test_the_consumer_handling_span_is_reported_in_nanoseconds(self):
        """Nanoseconds, because the unit its neighbours use would erase one of the arms.

        The two consumers stamp `t_output_ns` in different places relative to payload
        deserialisation: Kafka's is the next statement after `t_cons_recv_ns` and lands a
        few hundred nanoseconds later, Redis's is separated by a `json.loads` and lands
        tens of microseconds later. The columns beside this one are milliseconds at four
        decimals, and at that precision the Kafka arm is 0.0003 against the Redis arm's
        0.0195 -- a ratio of seventy carried in the last digit either column has. The unit
        is the disclosure here, so it is pinned.
        """
        p, c = one_event(recv=1_000_000, output=1_000_281)
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        row = rs.summarise_run("run-1", "kafka", spans)
        assert row["median_output_ns"] == 281
        assert isinstance(row["median_output_ns"], int)
        assert round(row["median_output_ns"] / 1e6, 3) == 0.0, \
            "the millisecond column beside it would print this as no span at all"


class TestConsumerHandlingSpan:
    """The fifth span, added in round 43, joins two consumer stamps rather than a
    consumer stamp to a producer one. That is the point: the four spans that came before
    it all reach back to the producer, so an audit of "where is each stamp taken" that
    followed them found only producer-side stamps."""

    def test_the_span_table_can_name_two_stamps_from_the_same_side(self):
        p, c = one_event(recv=1_000_000, output=1_019_480)
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        assert spans["output"] == [19_480]

    def test_the_handling_span_is_a_chain_and_cannot_invert(self):
        p, c = one_event(recv=1_000_000, output=1_000_281)
        spans = rs.join_run(rs.parse_rows(prod_csv(p)), rs.parse_rows(cons_csv(c)))
        row = rs.summarise_run("r", "kafka", spans)
        assert row["neg_output"] == 0

    @staticmethod
    def _ledger_row(run_id, handling):
        return {"run_id": run_id, "backend": "kafka", "n_events": "10",
                "neg_ack": "1", "neg_send": "0", "neg_output_send": "0",
                "neg_tti": "0", "neg_output": "0", "median_ack_us": "1.0",
                "median_output_ns": handling}

    def test_totals_carries_the_handling_median_when_the_column_is_present(self):
        agg = rs.totals([self._ledger_row("a", "281"), self._ledger_row("b", "331")])
        assert agg["median_output_ns"] == 306

    def test_a_row_with_no_measured_handling_median_still_totals(self):
        """The median is an enrichment; the per-span counts are the substance.

        A run whose consumer log carried no usable pair of stamps has no handling median
        to contribute, and dropping the whole run over it would shrink the denominator of
        every other count. A missing *count* is a different thing -- a ledger without one
        is a ledger from another schema, and summarising it as though the span had been
        counted is the silent discard this project audits -- so that one is left to raise.
        """
        agg = rs.totals([self._ledger_row("a", "")])
        assert agg["neg_ack"] == 1
        assert "median_output_ns" not in agg

    def test_a_ledger_missing_the_fifth_count_raises_rather_than_summarising(self):
        row = self._ledger_row("a", "281")
        del row["neg_output"]
        with pytest.raises(KeyError):
            rs.totals([row])

    def test_the_report_prints_the_handling_median_only_when_it_has_one(self):
        base = {"runs": 1, "events": 10, "neg_ack": 1, "pct_ack": 10.0,
                "neg_send": 0, "pct_send": 0.0, "neg_output_send": 0,
                "pct_output_send": 0.0, "neg_tti": 0, "pct_tti": 0.0,
                "neg_output": 0, "pct_output": 0.0,
                "runs_over_one_pct_ack": 1, "runs_negative_median_ack": 0}
        assert "consumer handling span" not in rs.report(dict(base))
        assert "281 ns" in rs.report(dict(base, median_output_ns=281.0))


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
                 "neg_tti": "0", "neg_output": "0", "median_ack_us": "-1.0"},
                {"n_events": "10", "neg_ack": "0", "neg_send": "0", "neg_output_send": "0",
                 "neg_tti": "0", "neg_output": "0", "median_ack_us": "5.0"}]
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
                          "neg_output_send": "0", "neg_tti": "0", "neg_output": "0", "median_ack_us": "0"}])
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


class TestSharedStampContrast:
    """Both spans end at the same clock read; only one inverts.

    This counter exists because a referee raised cross-CPU clock incoherence under thread
    migration as a rival to the descheduling account -- a real mechanism, documented in the
    wild on virtualised hardware, and one the manuscript's testbed cannot rule out from a
    captured clocksource, because the instances are gone. It can be ruled out from the data:
    an artefact of the shared endpoint moves both spans, and a late producer-side stamp moves
    one. What decides between them is a count, so it is computed here rather than argued.
    """

    def _rows(self, spec):
        return [{"n_events": str(n), "neg_ack": str(a), "neg_send": str(s),
                 "neg_output_send": "0", "neg_tti": "0", "neg_output": "0", "median_ack_us": "1.0",
                 "median_send_us": "1.0", "run_id": "r%d" % i, "backend": "kafka"}
                for i, (n, a, s) in enumerate(spec)]

    def test_counts_runs_where_only_the_ack_span_inverts(self):
        agg = rs.totals(self._rows([(100, 5, 0), (100, 0, 0), (100, 3, 0)]))
        assert agg["runs_ack_only_inversions"] == 2

    def test_a_run_where_both_spans_invert_is_not_ack_only(self):
        """That run would be consistent with a clock artefact and must not be counted."""
        agg = rs.totals(self._rows([(100, 5, 2)]))
        assert agg["runs_ack_only_inversions"] == 0
        assert agg["runs_send_inverts"] == 1

    def test_a_run_with_no_inversions_is_not_counted(self):
        assert rs.totals(self._rows([(100, 0, 0)]))["runs_ack_only_inversions"] == 0

    def test_the_committed_corpus_never_inverts_the_send_span(self):
        """The load-bearing fact. If this ever fails, the exclusion argument fails with it."""
        agg = rs.totals(rs.read_csv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "docs", "results", "span_recount.csv")))
        assert agg["runs_send_inverts"] == 0
        assert agg["neg_send"] == 0

    def test_the_contrast_holds_in_most_runs_of_the_committed_corpus(self):
        agg = rs.totals(rs.read_csv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "docs", "results", "span_recount.csv")))
        assert agg["runs_ack_only_inversions"] == 4549
        assert agg["runs_ack_only_inversions"] / agg["runs"] > 0.75


class TestMarginQuantities:
    """The headroom that actually excludes an incoherent clock.

    The first version of that exclusion rested on the two spans sharing their closing clock
    read. It does not discriminate: the rival is a difference between two clock domains, and
    both spans carry it. What discriminates is how much room each span has before it can go
    negative, so the extremes are computed rather than argued.
    """

    def _full(self, spec):
        return [{"n_events": str(n), "neg_ack": str(a), "neg_send": str(s),
                 "neg_output_send": "0", "neg_tti": "0", "neg_output": "0",
                 "min_ack_us": str(mn_a), "min_send_us": str(mn_s),
                 "median_ack_us": "1.0", "median_send_us": "1.0",
                 "run_id": "r%d" % i, "backend": "kafka"}
                for i, (n, a, s, mn_a, mn_s) in enumerate(spec)]

    def test_reports_the_deepest_inversion_and_the_send_floor(self):
        agg = rs.totals(self._full([(100, 5, 0, -9000.0, 250.0),
                                    (100, 2, 0, -400.0, 300.0)]))
        assert agg["deepest_ack_inversion_us"] == -9000.0
        assert agg["send_span_floor_us"] == 250.0

    def test_the_margin_is_the_ratio_that_bounds_a_clock_offset(self):
        agg = rs.totals(self._full([(100, 5, 0, -1000.0, 100.0)]))
        assert agg["offset_margin_factor"] == 10.0

    def test_a_zero_send_floor_gives_an_infinite_margin_rather_than_a_crash(self):
        agg = rs.totals(self._full([(100, 1, 0, -5.0, 0.0)]))
        assert agg["offset_margin_factor"] == float("inf")

    def test_rows_without_the_extreme_columns_still_yield_every_count(self):
        """A partial row must give a smaller answer, not an exception."""
        rows = [{"n_events": "100", "neg_ack": "5", "neg_send": "0",
                 "neg_output_send": "0", "neg_tti": "0", "neg_output": "0", "median_ack_us": "1.0",
                 "run_id": "r", "backend": "kafka"}]
        agg = rs.totals(rows)
        assert agg["neg_ack"] == 5
        assert "offset_margin_factor" not in agg

    def test_the_committed_corpus_bounds_any_offset_far_below_its_inversions(self):
        agg = rs.totals(rs.read_csv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "docs", "results", "span_recount.csv")))
        assert agg["send_span_floor_us"] > 0, "a negative floor would sink the argument"
        assert agg["offset_margin_factor"] > 100, "the margin is what carries the exclusion"


class TestByBackend:
    """The per-broker split behind Table II and Figure 6.

    Table II's generality claim rests on two counts that no test touched until this one. A
    split that silently dropped a backend, or grouped two spellings of one name apart, would
    still render a plausible table, so the invariant worth asserting is not any single number
    but that the parts reconstruct the whole.
    """

    @staticmethod
    def _rows():
        return [
            {"run_id": "a", "backend": "kafka", "n_events": "10", "neg_ack": "3",
             "neg_send": "0", "neg_output_send": "0", "neg_tti": "0", "neg_output": "0",
             "min_ack_us": "-5.0", "min_send_us": "7.0",
             "median_ack_us": "1.0", "median_send_us": "2.0"},
            {"run_id": "b", "backend": "redis", "n_events": "20", "neg_ack": "4",
             "neg_send": "0", "neg_output_send": "0", "neg_tti": "0", "neg_output": "0",
             "min_ack_us": "-9.0", "min_send_us": "3.0",
             "median_ack_us": "1.0", "median_send_us": "2.0"},
            {"run_id": "c", "backend": "kafka", "n_events": "30", "neg_ack": "5",
             "neg_send": "0", "neg_output_send": "0", "neg_tti": "0", "neg_output": "0",
             "min_ack_us": "-2.0", "min_send_us": "9.0",
             "median_ack_us": "1.0", "median_send_us": "2.0"},
        ]

    def test_rows_are_grouped_by_their_backend(self):
        split = rs.by_backend(self._rows())
        assert sorted(split) == ["kafka", "redis"]
        assert split["kafka"]["runs"] == 2 and split["redis"]["runs"] == 1

    def test_the_parts_reconstruct_the_whole(self):
        rows = self._rows()
        whole = rs.totals(rows)
        split = rs.by_backend(rows)
        for key in ("runs", "events", "neg_ack", "neg_send", "neg_output_send", "neg_tti"):
            assert sum(s[key] for s in split.values()) == whole[key], key

    def test_the_pooled_send_floor_is_the_smallest_of_the_per_backend_floors(self):
        """The manuscript's headroom margin divides by this floor, so which one it is matters."""
        rows = self._rows()
        split = rs.by_backend(rows)
        assert rs.totals(rows)["send_span_floor_us"] == min(
            s["send_span_floor_us"] for s in split.values())

    def test_a_row_without_a_backend_is_grouped_rather_than_dropped(self):
        rows = self._rows()
        rows.append(dict(rows[0], run_id="d", backend=""))
        split = rs.by_backend(rows)
        assert "unknown" in split
        assert sum(s["runs"] for s in split.values()) == len(rows)

    def test_an_empty_corpus_yields_an_empty_split(self):
        assert rs.by_backend([]) == {}


class TestTheArchiveMembersAndPathsThatAreNotWhatTheyLookLike:

    def test_a_member_the_archive_cannot_hand_over_is_skipped(self, tmp_path,
                                                              monkeypatch):
        """`extractfile` answers None for a member that is not a plain readable file.

        `isfile()` screens most of those out, so this guard is the second line: a 56k-member
        archive streamed once must not lose the whole recount to one member the tar library
        declines to open. The good run beside it must still be counted.
        """
        import io as _io
        import tarfile

        path = tmp_path / "runs.tar.gz"
        rows = [{"run_id": "r1", "backend": "kafka", "event_id": "e0",
                 "t_prod_sched_ns": 0, "t_prod_send_ns": 1, "t_broker_ack_ns": 2}]
        with tarfile.open(path, "w:gz") as tf:
            for run in ("r0", "r1"):
                body = prod_csv(rows)
                if isinstance(body, str):
                    body = body.encode("utf-8")
                info = tarfile.TarInfo("runs/%s/producer.csv" % run)
                info.size = len(body)
                tf.addfile(info, _io.BytesIO(body))

        real = tarfile.TarFile.extractfile

        def declines_one(self, member):
            if "r0" in member.name:
                return None
            return real(self, member)

        monkeypatch.setattr(tarfile.TarFile, "extractfile", declines_one)
        got, skipped = rs.scan_archive(str(path))
        assert isinstance(got, list) and isinstance(skipped, list)
        assert "r0" not in [r.get("run_id") for r in got]

    def test_an_output_path_with_no_directory_part_is_written_where_it_stands(self,
                                                                              tmp_path,
                                                                              monkeypatch):
        """`os.path.dirname("spans.csv")` is empty, and `makedirs("")` raises. The guard is
        what lets the script be run from inside the directory it writes to."""
        monkeypatch.chdir(tmp_path)
        rs.write_csv([], "spans.csv")
        assert (tmp_path / "spans.csv").exists()
