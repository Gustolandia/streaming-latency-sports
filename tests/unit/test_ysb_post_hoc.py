"""The Yahoo Streaming Benchmark read after its runs: why its figure ran ahead of T1's delay,
and what its clock-moved runs fit.

The processor writes every campaign's window once a second, one campaign after another, and each
write of a window Redis already holds waits for four replies, each of which crossed the delay. So
the writes of one window for successive campaigns grow further apart with the delay. These tests
hold the reading of that gap to files shaped as the generator's collection writes them: every
campaign's windows newest first, one value a line, the window's last write less its start in whole
milliseconds; two of them are runs of freeze 33, copied unchanged from the collected block. The
clock-moved runs are read from the judge's verdict.json and the control's reading.json, and one of
each, from freeze 33's first round, is kept here unchanged too.
"""
import json
import csv
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import ysb_post_hoc as yf  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "ysb"


def _campaigns(*windows):
    """A collection's values for campaigns given as their windows, newest first."""
    return [v for campaign in windows for v in campaign]


def _real(name):
    return [int(v) for v in (FIXTURES / name).read_text(encoding="utf-8").split()]


def _hundred(gap_ms):
    """A hundred campaigns, each with an open window and one closed window, whose closed
    window's writes for successive campaigns are gap_ms apart."""
    return _campaigns(*([0, 10000 + gap_ms * i] for i in range(100)))


class TestTheDelayFromTheFolder:
    def test_a_staircase_folder_names_its_delay(self):
        assert yf.added_ms("t1-ysb-0_3ms") == 0.3
        assert yf.added_ms("t1-ysb-2_0ms") == 2.0
        assert yf.added_ms("t1-ysb-0ms") == 0.0

    def test_other_files_and_folders_are_not_staircase_runs(self):
        assert yf.added_ms("t1-ysb-step.json") is None
        assert yf.added_ms("t2-ysb-control") is None
        assert yf.added_ms("t1-pkb-0_3ms") is None


class TestTheGap:
    def test_the_steps_between_one_windows_writes_give_the_gap(self):
        """Three campaigns, two windows each: the older window's writes are 3 and 5 ms apart."""
        got = yf.gap(_campaigns([5000, 10000], [5100, 10003], [5200, 10008]), campaigns=3)
        assert got == (1, 2, 4.0)

    def test_the_newest_window_is_left_out(self):
        """It may still have been open when collected: its steps, here 1 ms, count for nothing."""
        got = yf.gap(_campaigns([5000, 10000, 20000], [5001, 10010, 20010], [5002, 10020, 20020]),
                     campaigns=3)
        assert got == (2, 4, 10.0)

    def test_a_step_at_the_cut_is_not_one_write_to_the_next(self):
        got = yf.gap(_campaigns([5000, 10000], [5000, 10002], [5000, 10042]), campaigns=3,
                     cut_ms=40)
        assert got == (1, 1, 2.0)

    def test_a_run_not_a_whole_multiple_of_the_campaigns_cannot_be_split(self):
        assert yf.gap([5000, 10000, 5100, 10003, 10008], campaigns=3) is None

    def test_a_run_with_no_values_has_no_gap(self):
        assert yf.gap([], campaigns=3) is None

    def test_a_run_with_only_the_newest_window_has_no_gap(self):
        assert yf.gap([5000, 5100, 5200], campaigns=3) is None

    def test_a_window_whose_writes_are_all_far_apart_has_no_gap(self):
        assert yf.gap(_campaigns([5000, 9000], [5000, 10000], [5000, 11000]), campaigns=3) is None

    def test_a_run_of_freeze_33_at_two_milliseconds(self):
        """Round 2's largest step: 1,300 values, twelve closed windows, writes 11 ms apart."""
        assert yf.gap(_real("round2_2_0ms_updated.txt")) == (12, 1055, 11.0)

    def test_a_run_of_freeze_33_one_campaign_short_of_a_window(self):
        """Round 1 at 0.1 ms wrote 1,281 values: some campaign's window is missing, and which
        one the file cannot say."""
        assert yf.gap(_real("round1_0_1ms_updated.txt")) is None


def _write_run(root, folder, step, values):
    path = root / folder / step
    path.mkdir(parents=True)
    (path / "updated.txt").write_text("\n".join(str(v) for v in values) + "\n", encoding="utf-8")


class TestTheBlock:
    def test_a_rounds_rows_follow_the_delay_and_skip_what_is_not_a_staircase_run(self, tmp_path):
        _write_run(tmp_path, "r", "t1-ysb-2_0ms", _hundred(11))
        _write_run(tmp_path, "r", "t1-ysb-0ms", _hundred(3))
        _write_run(tmp_path, "r", "t1-ysb-0_5ms", [10000] * 99)
        (tmp_path / "r" / "t1-ysb-1_1ms").mkdir()
        _write_run(tmp_path, "r", "t2-ysb-control", [10000] * 200)
        (tmp_path / "r" / "t1-ysb-step.json").write_text("{}", encoding="utf-8")
        rows = yf.flush_rows("2", str(tmp_path / "r"))
        assert rows == [
            {"round": "2", "added_ms": "0.0", "values": 200, "windows": 1, "steps": 99,
             "gap_ms": "3.0"},
            {"round": "2", "added_ms": "0.5", "values": 99, "windows": "", "steps": "",
             "gap_ms": ""},
            {"round": "2", "added_ms": "2.0", "values": 200, "windows": 1, "steps": 99,
             "gap_ms": "11.0"}]

    def test_a_round_whose_folder_is_absent_adds_nothing(self, tmp_path):
        _write_run(tmp_path, "tools_v36", "t1-ysb-0ms", [10000] * 100)
        rows = yf.block_rows(str(tmp_path), yf.flush_rows)
        assert [r["round"] for r in rows] == ["1"]


class TestTheSlopes:
    def _rows(self, *points):
        return [{"round": r, "added_ms": "%.1f" % x, "gap_ms": "" if y is None else "%.1f" % y}
                for r, x, y in points]

    def test_each_rounds_slope_is_fitted_over_the_runs_it_could_split(self):
        got = yf.slopes(self._rows(("1", 0.0, 3.0), ("1", 1.0, 7.0), ("1", 2.0, 11.0),
                                   ("1", 1.5, None), ("2", 0.0, 3.0), ("2", 2.0, 10.0)))
        assert got == {"1": pytest.approx(4.0), "2": pytest.approx(3.5)}

    def test_a_round_with_one_delay_has_no_slope(self):
        assert yf.slopes(self._rows(("1", 0.0, 3.0), ("1", 0.0, 4.0), ("1", 2.0, None))) == {}


def _verdict(offset, sent, kept, avg, reference, predicted, predicted_avg):
    """A verdict.json as tool_negatives.py writes it, with the fields the fit reads."""
    return {"offset_ms": offset, "sent": sent, "count_reported": kept, "reported_avg_ms": avg,
            "reference_trips": reference,
            "expected": {"drops the negatives": {"count": predicted, "avg_ms": predicted_avg},
                         "keeps every value": {"count": reference, "avg_ms": avg - offset}}}


def _write_json(root, folder, run, name, obj):
    path = root / folder / run
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(obj), encoding="utf-8")


class TestTheFit:
    def test_a_rounds_control_comes_first_then_its_moved_runs_by_offset(self, tmp_path):
        _write_json(tmp_path, "r", "t2-ysb-423_500ms", "verdict.json",
                    _verdict(423.5062, 1200, 578, 311.7, 1300, 645, 303.0))
        _write_json(tmp_path, "r", "t2-ysb-421_500ms", "verdict.json",
                    _verdict(421.4983, 1297, 600, 341.07, 1300, 649, 303.2288))
        _write_json(tmp_path, "r", "t2-ysb-control", "reading.json",
                    {"received": 1300, "kept": 989, "reported_ms": {"avg": 520.24}})
        _write_json(tmp_path, "r", "t2-pkb-421_500ms", "verdict.json", {})
        _write_json(tmp_path, "r", "t1-ysb-0ms", "reading.json", {})
        (tmp_path / "r" / "t2-ysb-unread").mkdir()
        assert yf.fit_rows("1", str(tmp_path / "r")) == [
            {"round": "1", "offset_ms": "0", "sent": 1300, "kept": 989, "avg_ms": "520.2",
             "reference": "", "predicted_kept": "", "predicted_avg_ms": ""},
            {"round": "1", "offset_ms": "421.4983", "sent": 1297, "kept": 600, "avg_ms": "341.1",
             "reference": 1300, "predicted_kept": 649, "predicted_avg_ms": "303.2"},
            {"round": "1", "offset_ms": "423.5062", "sent": 1200, "kept": 578, "avg_ms": "311.7",
             "reference": 1300, "predicted_kept": 645, "predicted_avg_ms": "303.0"}]

    def test_a_round_without_a_control_has_only_its_moved_runs(self, tmp_path):
        _write_json(tmp_path, "r", "t2-ysb-421_500ms", "verdict.json",
                    _verdict(421.4983, 1297, 600, 341.07, 1300, 649, 303.2288))
        assert [r["offset_ms"] for r in yf.fit_rows("1", str(tmp_path / "r"))] == ["421.4983"]

    def test_the_runs_of_freeze_33_kept_here(self):
        """Round 1's control and first clock-moved run, as the block wrote them."""
        rows = yf.fit_rows("1", str(FIXTURES / "round1"))
        assert rows == [
            {"round": "1", "offset_ms": "0", "sent": 1300, "kept": 989, "avg_ms": "520.2",
             "reference": "", "predicted_kept": "", "predicted_avg_ms": ""},
            {"round": "1", "offset_ms": "421.4983", "sent": 1297, "kept": 600, "avg_ms": "341.1",
             "reference": 1300, "predicted_kept": 649, "predicted_avg_ms": "303.2"}]

    def test_the_committed_fit_table_holds_the_runs_kept_here(self):
        with (REPO / "docs" / "results" / "tools" / "ysb_t2_fit.csv").open(
                encoding="utf-8", newline="") as fh:
            committed = [r for r in csv.DictReader(fh) if r["round"] == "1"]
        kept = {r["offset_ms"]: {k: str(v) for k, v in r.items()}
                for r in yf.fit_rows("1", str(FIXTURES / "round1"))}
        assert [r for r in committed if r["offset_ms"] in kept] == list(kept.values())


class TestMain:
    def _block(self, root):
        _write_run(root, "tools_v36", "t1-ysb-0ms", _hundred(3))
        _write_run(root, "tools_v36", "t1-ysb-2_0ms", _hundred(11))
        _write_run(root, "tools_v36_round2", "t1-ysb-0ms", [10000] * 99)
        _write_json(root, "tools_v36", "t2-ysb-421_500ms", "verdict.json",
                    _verdict(421.4983, 1297, 600, 341.07, 1300, 649, 303.2288))

    def test_it_writes_both_tables_and_says_what_it_read(self, tmp_path, capsys):
        root = tmp_path / "azure"
        self._block(root)
        flush, fit = tmp_path / "out" / "ysb_flush.csv", tmp_path / "out" / "ysb_t2_fit.csv"
        assert yf.main(["--root", str(root), "--flush", str(flush), "--fit", str(fit)]) == 0
        with flush.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert [(r["round"], r["added_ms"], r["gap_ms"]) for r in rows] == [
            ("1", "0.0", "3.0"), ("1", "2.0", "11.0"), ("2", "0.0", "")]
        with fit.open(encoding="utf-8", newline="") as fh:
            assert [r["offset_ms"] for r in csv.DictReader(fh)] == ["421.4983"]
        out = capsys.readouterr().out
        assert "2 of 3 staircase runs split into windows" in out
        assert "1 clock-moved runs read against 'drops the negatives'" in out
        assert flush.read_bytes().count(b"\r") == 0 and fit.read_bytes().count(b"\r") == 0

    def test_a_root_with_no_runs_writes_nothing(self, tmp_path, capsys):
        flush, fit = tmp_path / "ysb_flush.csv", tmp_path / "ysb_t2_fit.csv"
        assert yf.main(["--root", str(tmp_path), "--flush", str(flush), "--fit", str(fit)]) == 1
        assert not flush.exists() and not fit.exists()
        assert "no YSB staircase or clock-moved runs" in capsys.readouterr().out

    def test_a_block_with_a_staircase_and_no_clock_moved_run_writes_nothing(self, tmp_path):
        _write_run(tmp_path, "tools_v36", "t1-ysb-0ms", _hundred(3))
        flush, fit = tmp_path / "ysb_flush.csv", tmp_path / "ysb_t2_fit.csv"
        assert yf.main(["--root", str(tmp_path), "--flush", str(flush), "--fit", str(fit)]) == 1
        assert not flush.exists()

    def test_the_committed_table_holds_the_two_runs_kept_here(self):
        """The committed table is folded from the collected block, which the repository does not
        carry; two of its runs are kept here, and the table must say what they say."""
        with (REPO / "docs" / "results" / "tools" / "ysb_flush.csv").open(
                encoding="utf-8", newline="") as fh:
            rows = {(r["round"], r["added_ms"]): r for r in csv.DictReader(fh)}
        windows, steps, median = yf.gap(_real("round2_2_0ms_updated.txt"))
        assert (rows[("2", "2.0")]["windows"], rows[("2", "2.0")]["steps"],
                rows[("2", "2.0")]["gap_ms"]) == (str(windows), str(steps), "%.1f" % median)
        assert rows[("1", "0.1")]["gap_ms"] == "" and rows[("1", "0.1")]["values"] == "1281"
