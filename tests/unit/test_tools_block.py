"""Tests for tools_block: the tools block's judged runs, folded into two committed tables.

The paper's sentences about the eleven tools are counts over these tables, so the fold has to
take each round's verdicts from the folder the write-up names -- round 1's from the re-judging
under freeze 21, not from the first judge's output beside the runs -- and has to keep an
undecided run as undecided rather than as whatever its judge leaned towards.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import tools_block as tb  # noqa: E402


def _step(folder, tool, slope, figure="p50", crossings=1):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ("t1-%s-step.json" % tool)).write_text(json.dumps(
        {"slope": {"figure": figure, "crossings": crossings, "slope": slope,
                   "measured_the_path": slope is not None}}), encoding="utf-8")


def _verdict(folder, run, offset, behaviour, decided=True, standing=None):
    d = folder / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.json").write_text(json.dumps(
        {"offset_ms": offset, "behaviour": behaviour if decided else None, "decided": decided,
         "still_standing": standing}), encoding="utf-8")


class TestT1:

    def test_one_row_per_tool_with_its_interval_and_slope(self, tmp_path):
        _step(tmp_path, "wrk2", 1.00842711)
        _step(tmp_path, "kafka-end-to-end", 2.0283, crossings=2)
        rows = tb.t1_rows("1", str(tmp_path))
        assert [r["tool"] for r in rows] == ["kafka-end-to-end", "wrk2"]
        assert rows[1] == {"round": "1", "tool": "wrk2", "trip": "round trip", "figure": "p50",
                           "crossings": 1, "slope": "1.0084"}
        assert rows[0]["trip"] == "in one process" and rows[0]["crossings"] == 2

    def test_a_staircase_read_again_replaces_the_first_reading(self, tmp_path):
        """hey's percentiles were never read in round 1; its slope comes from the re-read."""
        _step(tmp_path / "runs", "hey", 1.054, figure="avg")
        _step(tmp_path / "again", "hey", 1.0377)
        again = {"hey": str(tmp_path / "again" / "t1-hey-step.json")}
        (row,) = tb.t1_rows("1", str(tmp_path / "runs"), again)
        assert (row["figure"], row["slope"]) == ("p50", "1.0377")

    def test_a_staircase_with_no_slope_keeps_the_row_and_leaves_the_slope_empty(self, tmp_path):
        _step(tmp_path, "k6", None)
        (row,) = tb.t1_rows("2", str(tmp_path))
        assert row["slope"] == ""

    def test_a_tool_the_plan_never_read_stops_the_fold(self, tmp_path):
        """Its interval is unknown, and printing a row without one would hide that."""
        _step(tmp_path, "jmeter", 1.0)
        with pytest.raises(KeyError):
            tb.t1_rows("1", str(tmp_path))


class TestT2:

    def test_a_decided_run_records_its_behaviour_and_an_undecided_one_says_so(self, tmp_path):
        _verdict(tmp_path, "t2-vegeta-3_822ms", 3.8217, "times against one clock",
                 standing=["times against one clock"])
        _verdict(tmp_path, "t2-wrk2-1_827ms", 1.834, None, decided=False,
                 standing=["drops the negatives", "times against one clock"])
        rows = tb.t2_rows("1", str(tmp_path))
        assert rows[0] == {"round": "1", "tool": "vegeta", "offset_ms": "3.8217",
                           "verdict": "times against one clock",
                           "standing": "times against one clock"}
        assert rows[1]["verdict"] == tb.UNDECIDED
        assert rows[1]["standing"] == "drops the negatives; times against one clock"

    def test_the_controls_and_misnamed_folders_carry_no_verdict(self, tmp_path):
        _verdict(tmp_path, "t2-hey-control", 0.0, "times against one clock")
        _verdict(tmp_path, "t2-hey-ms", 0.0, "times against one clock")
        _verdict(tmp_path, "t2-hey-2ms", 2.0, "times against one clock", standing=None)
        rows = tb.t2_rows("3", str(tmp_path))
        assert [(r["tool"], r["standing"]) for r in rows] == [("hey", "")]


class TestCollect:

    def test_round_one_takes_its_verdicts_from_the_rejudging_and_hey_from_the_reread(self,
                                                                                    tmp_path):
        rounds = (("1", "snap/tools", "rejudged", {"hey": "reread"}),
                  ("2", "snap/tools_round2", None, {}))
        _step(tmp_path / "snap" / "tools", "hey", 1.054, figure="avg")
        _step(tmp_path / "reread", "hey", 1.0377)
        _verdict(tmp_path / "snap" / "tools", "t2-hey-1_805ms", 1.81, None, decided=False)
        _verdict(tmp_path / "rejudged", "t2-hey-1_805ms", 1.8141, "times against one clock")
        _step(tmp_path / "snap" / "tools_round2", "hey", 1.0)
        _verdict(tmp_path / "snap" / "tools_round2", "t2-hey-1_84ms", 1.84,
                 "times against one clock")
        t1, t2 = tb.collect(str(tmp_path), rounds)
        assert [(r["round"], r["slope"]) for r in t1] == [("1", "1.0377"), ("2", "1.0000")]
        assert [(r["round"], r["verdict"]) for r in t2] == [
            ("1", "times against one clock"), ("2", "times against one clock")]


class TestMain:

    def test_it_writes_both_tables(self, tmp_path, monkeypatch, capsys):
        rounds = (("1", "r1", None, {}),)
        monkeypatch.setattr(tb, "ROUNDS", rounds)
        _step(tmp_path / "in" / "r1", "k6", 1.0111)
        _verdict(tmp_path / "in" / "r1", "t2-k6-3_821ms", 3.8309, "times against one clock")
        out = tmp_path / "out"
        assert tb.main(["--collected", str(tmp_path / "in"), "--out", str(out)]) == 0
        with (out / "tools_t1.csv").open(encoding="utf-8") as fh:
            assert list(csv.DictReader(fh))[0]["slope"] == "1.0111"
        with (out / "tools_t2.csv").open(encoding="utf-8") as fh:
            assert list(csv.DictReader(fh))[0]["offset_ms"] == "3.8309"
        assert "1 T1 rows and 1 T2 rows from 1 rounds" in capsys.readouterr().out

    def test_a_folder_with_no_judged_runs_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "out"
        assert tb.main(["--collected", str(tmp_path / "nothing"), "--out", str(out)]) == 1
        assert "no judged tool runs" in capsys.readouterr().out
        assert not out.exists()

    def test_the_committed_tables_are_what_the_paper_reads(self):
        """Eleven tools, four rounds, two offsets each: the shape Section V-F describes."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "docs" / "results" / "tools" / "tools_t1.csv").open(encoding="utf-8") as fh:
            t1 = list(csv.DictReader(fh))
        with (repo / "docs" / "results" / "tools" / "tools_t2.csv").open(encoding="utf-8") as fh:
            t2 = list(csv.DictReader(fh))
        assert len({r["tool"] for r in t1}) == 11 and len({r["round"] for r in t1}) == 4
        assert len(t1) == 44 and len(t2) == 88
        #: Every tool in the tables has the interval the plan read for it; the five freeze 30
        #: adds have theirs already, read before any of their runs.
        assert set(r["tool"] for r in t1) <= set(tb.TRIPS)
        assert set(tb.TRIPS) - set(r["tool"] for r in t1) == {
            "omb", "pulsar-perf", "emqtt-bench", "ycsb", "nats-bench"}
