"""Tests for scripts/span_histogram.py.

The script exists so the distribution can be drawn without the 800 MB archive: fixed bins,
committed CSV, and a millisecond-grid tally that applies the benchmark's own guard to our
events. The tests are built around the two properties everything downstream leans on: the
bin edges are fixed rather than data-derived, and the millisecond tally is a truncation of
absolute stamps, not a rounding of the true value.
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

import span_histogram as sh  # noqa: E402


def prod_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["event_id", "t_prod_sched_ns", "t_prod_send_ns",
                                        "t_broker_ack_ns"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def cons_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["event_id", "t_cons_recv_ns", "t_output_ns"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def event(eid="e1", sched=0, send=1_000_000, ack=1_600_000, recv=2_200_000, out=2_400_000):
    p = {"event_id": eid, "t_prod_sched_ns": sched, "t_prod_send_ns": send,
         "t_broker_ack_ns": ack}
    c = {"event_id": eid, "t_cons_recv_ns": recv, "t_output_ns": out}
    return p, c


class TestBins:
    def test_the_grid_is_fixed_and_symmetric_about_zero(self):
        assert sh.bin_index(0) == sh.n_bins() // 2
        assert sh.bin_low_us(sh.bin_index(0)) == 0

    def test_values_outside_the_window_have_no_bin(self):
        assert sh.bin_index(sh.BIN_HI_US) is None
        assert sh.bin_index(sh.BIN_LO_US - 1) is None

    def test_the_window_edges_are_inside_and_outside_respectively(self):
        assert sh.bin_index(sh.BIN_LO_US) == 0
        assert sh.bin_index(sh.BIN_HI_US - 1) == sh.n_bins() - 1


class TestAddEvent:
    def test_a_negative_span_is_counted_as_negative(self):
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", -1000, 1_000_000, 1_001_000)
        assert acc["neg"]["ack"] == 1 and acc["zero"]["ack"] == 0

    def test_an_exact_zero_is_counted_as_zero_not_negative(self):
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", 0, 1_000_000, 1_000_000)
        assert acc["zero"]["ack"] == 1 and acc["neg"]["ack"] == 0

    def test_a_value_below_the_window_lands_in_underflow(self):
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", (sh.BIN_LO_US - 1) * 1000, 0, -(sh.BIN_LO_US - 1) * 1000)
        assert acc["under"]["ack"] == 1

    def test_a_value_above_the_window_lands_in_overflow(self):
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", (sh.BIN_HI_US + 1) * 1000, (sh.BIN_HI_US + 1) * 1000, 0)
        assert acc["over"]["ack"] == 1

    def test_the_millisecond_tally_truncates_stamps_not_the_difference(self):
        """recv at 2.2 ms, ref at 1.6 ms: the true difference is 0.6 ms, but the truncated
        stamps read 2 and 1, so the instrument holds 1 ms -- not 0. Rounding the difference
        would be a kinder instrument than the one being modelled."""
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", 600_000, 2_200_000, 1_600_000)
        assert acc["ms"]["ack"] == {1: 1}

    def test_a_sub_tick_pair_in_one_tick_computes_to_zero(self):
        acc = sh.new_accumulator()
        sh.add_event(acc, "ack", 400_000, 1_900_000, 1_500_000)
        assert acc["ms"]["ack"] == {0: 1}

    def test_the_millisecond_cap_folds_extremes_into_overflow_keys(self):
        acc = sh.new_accumulator()
        big = (sh.MS_CAP + 5) * 1_000_000
        sh.add_event(acc, "ack", big, big, 0)
        sh.add_event(acc, "ack", -big, 0, big)
        assert acc["ms"]["ack"] == {sh.MS_CAP + 1: 1, -sh.MS_CAP - 1: 1}


class TestConsumeRun:
    def test_all_four_spans_are_tallied_per_event(self):
        acc = sh.new_accumulator()
        p, c = event()
        n = sh.consume_run(acc, [p], [c])
        assert n == 1
        assert all(acc["n"][name] == 1 for name in ("ack", "send", "output_send", "tti"))

    def test_a_consumer_row_with_no_matching_producer_is_dropped(self):
        acc = sh.new_accumulator()
        p, c = event()
        c2 = dict(c, event_id="ghost")
        assert sh.consume_run(acc, [p], [c2]) == 0

    def test_a_mangled_producer_row_is_skipped_not_fatal(self):
        acc = sh.new_accumulator()
        p, c = event()
        bad = dict(p, t_broker_ack_ns="not-a-number")
        assert sh.consume_run(acc, [bad], [c]) == 0

    def test_a_mangled_consumer_row_is_skipped_not_fatal(self):
        acc = sh.new_accumulator()
        p, c = event()
        bad = dict(c, t_cons_recv_ns="")
        assert sh.consume_run(acc, [p], [bad]) == 0


class TestFlush:
    def test_a_run_missing_its_consumer_half_contributes_nothing(self):
        acc = sh.new_accumulator()
        p, _ = event()
        assert sh._flush(acc, {"producer": prod_csv([p])}) is False

    def test_an_empty_producer_file_contributes_nothing(self):
        acc = sh.new_accumulator()
        _, c = event()
        assert sh._flush(acc, {"producer": prod_csv([]), "consumer": cons_csv([c])}) is False

    def test_a_run_whose_events_never_join_contributes_nothing(self):
        acc = sh.new_accumulator()
        p, c = event()
        c = dict(c, event_id="other")
        assert sh._flush(acc, {"producer": prod_csv([p]), "consumer": cons_csv([c])}) is False

    def test_a_joined_run_bumps_the_run_and_event_counts(self):
        acc = sh.new_accumulator()
        p, c = event()
        assert sh._flush(acc, {"producer": prod_csv([p]), "consumer": cons_csv([c])}) is True
        assert acc["runs"] == 1 and acc["events"] == 1


def make_archive(path, runs, extra_member=None):
    with tarfile.open(path, "w:gz") as tf:
        def put(name, body):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
        for run_id, (prods, conss) in runs.items():
            put("runs/%s/producer.csv" % run_id, prod_csv(prods))
            put("runs/%s/consumer.csv" % run_id, cons_csv(conss))
            put("runs/%s/meta.json" % run_id, b"{}")     # ignored by name filter
        put("not-runs/stray.csv", b"x")                   # wrong prefix
        put("runs", b"")                                  # too few parts
        if extra_member:
            tf.addfile(tarfile.TarInfo(extra_member))     # a directory-like member


class TestScanArchive:
    def test_runs_are_flushed_and_counted(self, tmp_path):
        p, c = event()
        path = tmp_path / "a.tgz"
        make_archive(str(path), {"r1": ([p], [c]), "r2": ([p], [c])})
        acc = sh.scan_archive(str(path), progress=1)
        assert acc["runs"] == 2 and acc["events"] == 2

    def test_non_file_members_and_foreign_names_are_ignored(self, tmp_path):
        p, c = event()
        path = tmp_path / "a.tgz"
        with tarfile.open(str(path), "w:gz") as tf:
            d = tarfile.TarInfo("runs/rd")
            d.type = tarfile.DIRTYPE
            tf.addfile(d)
            for name, body in (("runs/r1/producer.csv", prod_csv([p])),
                               ("runs/r1/consumer.csv", cons_csv([c])),
                               ("runs/r1/notes.txt", b"ignored")):
                info = tarfile.TarInfo(name)
                info.size = len(body)
                tf.addfile(info, io.BytesIO(body))
        acc = sh.scan_archive(str(path), progress=0)
        assert acc["runs"] == 1

    def test_a_member_the_tar_cannot_open_is_skipped(self, tmp_path, monkeypatch):
        p, c = event()
        path = tmp_path / "a.tgz"
        make_archive(str(path), {"r1": ([p], [c])})
        real = tarfile.TarFile.extractfile

        def declines_producers(self, member):
            if "producer" in member.name:
                return None
            return real(self, member)
        monkeypatch.setattr(tarfile.TarFile, "extractfile", declines_producers)
        acc = sh.scan_archive(str(path))
        assert acc["runs"] == 0

    def test_a_run_split_by_the_stream_end_is_flushed_from_pending(self, tmp_path):
        """Only one half arrives (consumer missing entirely): the trailing flush loop must
        still run, and contribute nothing."""
        p, _ = event()
        path = tmp_path / "a.tgz"
        with tarfile.open(str(path), "w:gz") as tf:
            body = prod_csv([p])
            info = tarfile.TarInfo("runs/r1/producer.csv")
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))
        acc = sh.scan_archive(str(path))
        assert acc["runs"] == 0


class TestScanDir:
    def test_an_unpacked_tree_counts_like_the_archive(self, tmp_path):
        p, c = event()
        run = tmp_path / "r1"
        run.mkdir()
        (run / "producer.csv").write_bytes(prod_csv([p]))
        (run / "consumer.csv").write_bytes(cons_csv([c]))
        (tmp_path / "loose.txt").write_text("not a run dir")
        acc = sh.scan_dir(str(tmp_path))
        assert acc["runs"] == 1

    def test_a_run_dir_missing_a_half_is_skipped(self, tmp_path):
        p, _ = event()
        run = tmp_path / "r1"
        run.mkdir()
        (run / "producer.csv").write_bytes(prod_csv([p]))
        acc = sh.scan_dir(str(tmp_path))
        assert acc["runs"] == 0


class TestCounts:
    def _acc(self):
        acc = sh.new_accumulator()
        p1, c1 = event(eid="a")                            # positive span
        p2, c2 = event(eid="b", ack=2_600_000)             # negative span, same ms tick
        p3, c3 = event(eid="c", ack=3_600_000)             # negative span, later ms tick
        sh._flush(acc, {"producer": prod_csv([p1, p2, p3]),
                        "consumer": cons_csv([c1, c2, c3])})
        return acc

    def test_discard_and_nan_shrink_the_sample_and_the_rest_do_not(self):
        c = sh.strategy_counts(self._acc(), "ack")
        assert c["retained_discard"] == c["retained_nan"] == c["total"] - c["non_positive"]
        assert c["retained_zero"] == c["retained_unit"] == c["retained_keep"] == c["total"]

    def test_an_empty_span_reports_a_zero_fraction_rather_than_dividing(self):
        acc = sh.new_accumulator()
        assert sh.strategy_counts(acc, "ack")["reported_fraction_discard"] == 0.0

    def test_the_ms_rule_keeps_only_strictly_positive_ticks(self):
        m = sh.ms_retention(self._acc(), "ack")
        assert m["kept"] + m["dropped"] == m["total"]
        assert m["below_zero"] >= 1

    def test_the_ms_rule_on_an_empty_span_is_zero_not_an_error(self):
        acc = sh.new_accumulator()
        assert sh.ms_retention(acc, "ack")["retention"] == 0.0


class TestOutputs:
    def test_csv_holds_only_occupied_bins_plus_the_two_overflow_rows(self, tmp_path):
        acc = self_acc = TestCounts()._acc()
        out = tmp_path / "h.csv"
        sh.write_csv(acc, str(out))
        rows = list(csv.reader(open(out)))
        assert rows[-2][0] == "UNDERFLOW" and rows[-1][0] == "OVERFLOW"
        assert 2 < len(rows) < 20        # sparse, not 4000 rows

    def test_csv_with_a_bare_filename_writes_in_place(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sh.write_csv(sh.new_accumulator(), "bare.csv")
        assert (tmp_path / "bare.csv").exists()

    def test_stats_json_round_trips_and_reports(self, tmp_path, capsys):
        acc = TestCounts()._acc()
        out = tmp_path / "s.json"
        sh.write_stats(acc, str(out))
        stats = json.load(open(out))
        sh.report(stats)
        text = capsys.readouterr().out
        assert "ack" in text and "ms-grid" in text

    def test_report_skips_a_span_with_no_events(self, capsys):
        acc = sh.new_accumulator()
        acc["n"]["ack"] = 0
        payload = {"runs": 0, "events": 0,
                   "spans": {"ack": {"counts": sh.strategy_counts(acc, "ack"),
                                     "ms_rule": sh.ms_retention(acc, "ack"),
                                     "ms_table": {}}}}
        sh.report(payload)
        assert "ack" not in capsys.readouterr().out.replace("runs", "")

    def test_stats_with_a_bare_filename_writes_in_place(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        sh.write_stats(sh.new_accumulator(), "bare.json")
        assert (tmp_path / "bare.json").exists()


class TestMain:
    def test_archive_mode_writes_both_artefacts(self, tmp_path, capsys):
        p, c = event()
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {"r1": ([p], [c])})
        out = tmp_path / "h.csv"
        stats = tmp_path / "s.json"
        rc = sh.main(["--archive", str(arc), "--out", str(out), "--stats", str(stats)])
        assert rc == 0 and out.exists() and stats.exists()
        assert "wrote" in capsys.readouterr().out

    def test_the_bare_archive_flag_falls_back_to_the_default_path(self, tmp_path,
                                                                  monkeypatch, capsys):
        p, c = event()
        arc = tmp_path / "cloud_archive"
        arc.mkdir()
        make_archive(str(arc / "sbl_runs.tgz"), {"r1": ([p], [c])})
        monkeypatch.chdir(tmp_path)
        rc = sh.main(["--archive"])
        assert rc == 0

    def test_runs_dir_mode(self, tmp_path):
        p, c = event()
        run = tmp_path / "runs" / "r1"
        run.mkdir(parents=True)
        (run / "producer.csv").write_bytes(prod_csv([p]))
        (run / "consumer.csv").write_bytes(cons_csv([c]))
        rc = sh.main(["--runs-dir", str(tmp_path / "runs"),
                      "--out", str(tmp_path / "h.csv"),
                      "--stats", str(tmp_path / "s.json")])
        assert rc == 0

    def test_summary_mode_reads_the_committed_stats(self, tmp_path, capsys):
        p, c = event()
        arc = tmp_path / "a.tgz"
        make_archive(str(arc), {"r1": ([p], [c])})
        stats = tmp_path / "s.json"
        sh.main(["--archive", str(arc), "--out", str(tmp_path / "h.csv"),
                 "--stats", str(stats)])
        capsys.readouterr()
        rc = sh.main(["--summary", "--stats", str(stats)])
        assert rc == 0
        assert "events" in capsys.readouterr().out
