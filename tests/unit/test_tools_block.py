"""Tests for tools_block: the tools block's judged runs, folded into two committed tables.

The paper's sentences about the tools run are counts over these tables, so the fold has to take
each round's verdicts from the folder the write-up names -- round 1's from the re-judging under
freeze 21, not from the first judge's output beside the runs -- and has to keep an undecided run
as undecided rather than as whatever its judge leaned towards. Since freeze 31 it also judges
every T2 run again, beside the verdict the run was given, and it may do that only from inputs
that reproduce the verdict the run was given.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import tool_negatives as tn  # noqa: E402
import tools_block as tb  # noqa: E402

#: The five columns freeze 31's re-judging adds to a T2 row.
REJUDGED = ("sent", "kept", "verdict_31", "clocks", "clocks_why")


def _step(folder, tool, slope, figure="p50", crossings=1, smallest=None):
    folder.mkdir(parents=True, exist_ok=True)
    step = {"slope": {"figure": figure, "crossings": crossings, "slope": slope,
                      "measured_the_path": slope is not None}}
    if smallest is not None:
        step["smallest_reported_ms"] = smallest
    (folder / ("t1-%s-step.json" % tool)).write_text(json.dumps(step), encoding="utf-8")


def _verdict(folder, run, offset, behaviour, decided=True, standing=None):
    d = folder / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.json").write_text(json.dumps(
        {"offset_ms": offset, "behaviour": behaviour if decided else None, "decided": decided,
         "still_standing": standing}), encoding="utf-8")


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _reading(tool, avg, p50, low, kept=3000, step=0.001):
    """A reading in the shape tool_readings writes for an HTTP load generator, every figure it
    prints and the step each is printed in, as vegeta's of 25 September have them."""
    return {"kept": kept, "tool": tool, "unit": None, "step_ms": step,
            "reported_ms": {"avg": avg, "max": avg + 3.5, "min": low, "p50": p50,
                            "p99": avg + 0.79},
            "steps_ms": {"avg": 1e-06, "max": 0.001, "min": 1e-06, "p50": 1e-06, "p99": step}}


#: T1's ten steps, spelled as tools.sh names their folders.
DELAYS = (("0", 0.0), ("0_1", 0.1), ("0_2", 0.2), ("0_3", 0.3), ("0_5", 0.5), ("0_7", 0.7),
          ("0_9", 0.9), ("1_1", 1.1), ("1_5", 1.5), ("2_0", 2.0))


def _world(runs, tool="vegeta", run="t2-vegeta-1_816ms"):
    """One round of a tool timing a round trip, as tools.sh leaves it: T1's staircase with our
    reference's trips at its zero step and the step it measured, and T2's control and one offset
    run, with the offset measured at the clock, the count it was asked to send and its exit code.

    Shaped on vegeta's round 2 of 25 September: trips near 0.77 ms, figures that follow the delay
    with a few hundredths of scatter, and an offset run whose figures moved 0.03 ms under a clock
    moved back 1.825."""
    for spelled, delay in DELAYS:
        wobble = 0.02 if int(delay * 10) % 2 else -0.02
        _json(runs / ("t1-%s-%sms" % (tool, spelled)) / "reading.json",
              _reading(tool, 0.794 + delay + wobble, 0.774 + delay + wobble,
                       0.610 + delay - wobble))
    _json(runs / ("t1-%s-0ms" % tool) / "reference_trips.json",
          {"client": "http_reference.py",
           "trips_ms": [2.319396] + [0.74 + 0.0001 * (i % 100) for i in range(2999)]})
    _step(runs, tool, 1.0037, smallest=0.1)
    _json(runs / ("t2-%s-control" % tool) / "reading.json",
          _reading(tool, 0.794384, 0.773625, 0.610007, step=0.01))
    _json(runs / run / "reading.json", _reading(tool, 0.767465, 0.747461, 0.596541))
    _json(runs / run / "offset_measured.json",
          {"asked_ms": 1.816, "measured_ms": 1.8249, "spelling": "the system clock stepped"})
    (runs / run / "asked_to_send.txt").write_text("3000\n", encoding="utf-8")
    (runs / run / "exit_code.txt").write_text("0\n", encoding="utf-8")
    _verdict(runs, run, 1.8249, tn.ONE_CLOCK, standing=[tn.ONE_CLOCK])
    return runs


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
        assert {k: rows[0][k] for k in ("round", "tool", "offset_ms", "verdict", "standing")} == {
            "round": "1", "tool": "vegeta", "offset_ms": "3.8217",
            "verdict": "times against one clock", "standing": "times against one clock"}
        assert rows[1]["verdict"] == tb.UNDECIDED
        assert rows[1]["standing"] == "drops the negatives; times against one clock"

    def test_a_run_that_left_no_reading_is_not_judged_again(self, tmp_path):
        """A verdict with nothing beside it to reconstruct the judgement from keeps its row, with
        the re-judged columns empty rather than filled from nothing."""
        _verdict(tmp_path, "t2-vegeta-3_822ms", 3.8217, "times against one clock")
        (row,) = tb.t2_rows("1", str(tmp_path))
        assert set(row) == set(tb.T2_FIELDS)
        assert all(row[k] == "" for k in REJUDGED)

    def test_the_controls_and_misnamed_folders_carry_no_verdict(self, tmp_path):
        _verdict(tmp_path, "t2-hey-control", 0.0, "times against one clock")
        _verdict(tmp_path, "t2-hey-ms", 0.0, "times against one clock")
        _verdict(tmp_path, "t2-hey-2ms", 2.0, "times against one clock", standing=None)
        rows = tb.t2_rows("3", str(tmp_path))
        assert [(r["tool"], r["standing"]) for r in rows] == [("hey", "")]


class TestJudgedAgainUnderFreeze31:
    """D34-3: every T2 run judged again under freeze 31, from what the run left, beside its
    verdict -- and only after the same inputs have given back the verdict it was given."""

    def test_a_run_on_one_clock_keeps_its_verdict_and_is_answered_one(self, tmp_path):
        (row,) = tb.t2_rows("2", str(_world(tmp_path)))
        assert (row["verdict"], row["verdict_31"]) == (tn.ONE_CLOCK, tn.ONE_CLOCK)
        assert (row["sent"], row["kept"], row["clocks"]) == ("3000", "3000", "one")
        assert row["clocks_why"].startswith(
            "its figures stayed within a quarter of the 1.825 ms offset")

    def test_inputs_that_do_not_give_back_the_verdict_stop_the_fold(self, tmp_path):
        """A reconstruction is only a re-judging if it reproduces the judgement first."""
        runs = _world(tmp_path)
        _verdict(runs, "t2-vegeta-1_816ms", 1.8249, "keeps every value")
        with pytest.raises(ValueError, match="judged again under freeze 21 gives "
                                             "times against one clock, not the keeps every"):
            tb.t2_rows("2", str(runs))

    def test_a_run_from_before_the_counts_were_written_is_held_to_the_defaults(self, tmp_path):
        """Round 1 of the eleven wrote no count, exit code or measured shift beside its runs."""
        runs = _world(tmp_path)
        for name in ("asked_to_send.txt", "exit_code.txt", "offset_measured.json"):
            (runs / "t2-vegeta-1_816ms" / name).unlink()
        (row,) = tb.t2_rows("1", str(runs))
        assert row["sent"] == str(tb.SENT_DEFAULT) and row["clocks"] == "one"
        assert "1.816 ms offset" in row["clocks_why"], "the offset asked for, none measured"

    def test_a_run_whose_reference_is_missing_is_not_judged_again(self, tmp_path):
        runs = _world(tmp_path)
        (runs / "t1-vegeta-0ms" / "reference_trips.json").unlink()
        (row,) = tb.t2_rows("2", str(runs))
        assert row["verdict"] == tn.ONE_CLOCK
        assert all(row[k] == "" for k in REJUDGED)

    def test_a_tool_that_gives_no_count_leaves_its_kept_empty(self, tmp_path):
        runs = _world(tmp_path)
        reading = json.loads((runs / "t2-vegeta-1_816ms" / "reading.json").read_text("utf-8"))
        reading["kept"] = None
        _json(runs / "t2-vegeta-1_816ms" / "reading.json", reading)
        (row,) = tb.t2_rows("2", str(runs))
        assert (row["kept"], row["clocks"]) == ("", "one")


class _Judge:
    """tool_negatives' judge and clock question, replaced by ones that record what they were
    given and answer as told: the wiring is tested here, the rules in test_tool_negatives."""

    def __init__(self, monkeypatch, given=tn.ONE_CLOCK, corrected=tn.ONE_CLOCK):
        self.calls, self.asked = [], []
        self.answers = {tn.FREEZE_21: given, tn.FREEZE_31: corrected}
        monkeypatch.setattr(tn, "what_it_did", self.what_it_did)
        monkeypatch.setattr(tn, "clocks", self.clocks)

    def what_it_did(self, reading, trips, asked, rule=tn.FREEZE_21, **inputs):
        self.calls.append(dict(inputs, asked=asked, rule=rule, trips=len(trips)))
        return {"decided": True, "behaviour": self.answers[rule]}

    def clocks(self, reading, control, offset_ms, sent=None):
        self.asked.append((offset_ms, sent, control))
        return "two", "said so"


class TestWhatTheJudgeIsGiven:

    def test_the_corrected_verdict_is_asked_for_by_name_and_reported_beside_the_given(
            self, tmp_path, monkeypatch):
        judge = _Judge(monkeypatch, given=tn.ONE_CLOCK, corrected=tb.UNDECIDED)
        (row,) = tb.t2_rows("1", str(_world(tmp_path)))
        assert [c["rule"] for c in judge.calls] == [tn.FREEZE_21, tn.FREEZE_31]
        assert (row["verdict"], row["verdict_31"], row["clocks"]) == (
            tn.ONE_CLOCK, tb.UNDECIDED, "two")

    def test_each_input_comes_from_the_file_the_run_left_it_in(self, tmp_path, monkeypatch):
        judge = _Judge(monkeypatch)
        tb.t2_rows("2", str(_world(tmp_path)))
        got = judge.calls[0]
        assert (got["asked"], got["shift_ms"], got["sent"], got["exit_code"]) == (
            1.816, 1.8249, 3000, 0)
        assert got["step_ms"] == 0.1, "the step T1 measured, not the one the tool prints in"
        assert got["control"]["reported_ms"]["avg"] == 0.794384
        assert got["plain"]["reported_ms"]["avg"] == pytest.approx(0.774)
        assert set(got["noise"]) == {"avg", "min"} and got["trips"] == 3000
        assert judge.asked == [(1.8249, 3000, got["control"])]

    def test_without_a_measured_step_it_is_the_step_the_tool_prints_in(self, tmp_path,
                                                                         monkeypatch):
        judge = _Judge(monkeypatch)
        runs = _world(tmp_path)
        _step(runs, "vegeta", 1.0037)
        tb.t2_rows("2", str(runs))
        assert judge.calls[0]["step_ms"] == 0.001

    def test_with_neither_step_nor_staircase_it_has_no_step(self, tmp_path, monkeypatch):
        judge = _Judge(monkeypatch)
        runs = _world(tmp_path)
        (runs / "t1-vegeta-step.json").unlink()
        (runs / "t1-vegeta-0ms" / "reading.json").unlink()
        tb.t2_rows("2", str(runs))
        assert judge.calls[0]["step_ms"] is None and judge.calls[0]["plain"] is None


class TestTheRecordedCall:
    """Round 1 of the eleven was judged again on 25 September by calls recorded beside each
    verdict, and its verdicts are judged again from those same calls."""

    def test_each_flag_is_read_with_its_value_and_backslashes_become_slashes(self, tmp_path):
        _json(tmp_path / "call.json",
              ["C:\\x\\tool_negatives.py", "judge", "--reading", "runs\\t2-k6-1_821ms\\r.json",
               "--offset-ms", "1.821", "--out", "o.json"])
        assert tb._recorded_call(str(tmp_path / "call.json")) == {
            "reading": "runs/t2-k6-1_821ms/r.json", "offset-ms": "1.821", "out": "o.json"}

    def test_a_round_judged_without_recorded_calls_has_none(self, tmp_path):
        assert tb._recorded_call(str(tmp_path / "call.json")) is None

    def test_a_run_is_judged_again_from_the_call_its_verdict_came_from(self, tmp_path):
        """The call names a reading the runs folder does not hold, so a row that comes back
        judged can only have been judged from the call."""
        runs = _world(tmp_path / "runs")
        moved = tmp_path / "read_again" / "reading.json"
        moved.parent.mkdir()
        (runs / "t2-vegeta-1_816ms" / "reading.json").replace(moved)
        verdicts = tmp_path / "rejudged"
        _verdict(verdicts, "t2-vegeta-1_816ms", 1.8249, tn.ONE_CLOCK)
        zero = runs / "t1-vegeta-0ms"
        _json(verdicts / "t2-vegeta-1_816ms" / "call.json", [
            "scripts/tool_negatives.py", "judge", "--reading", str(moved),
            "--reference", str(zero / "reference_trips.json"), "--offset-ms", "1.816",
            "--plain", str(zero / "reading.json"), "--step-ms", "0.1", "--shift-ms", "1.8249",
            "--control", str(runs / "t2-vegeta-control" / "reading.json"),
            "--staircase", str(runs), "--tool", "vegeta", "--sent", "3000", "--exit-code", "0",
            "--out", str(verdicts / "t2-vegeta-1_816ms" / "verdict.json")])
        (row,) = tb.t2_rows("1", str(verdicts), str(runs))
        assert (row["verdict_31"], row["clocks"], row["sent"]) == (tn.ONE_CLOCK, "one", "3000")

    def test_a_call_that_names_no_step_shift_count_or_controls_is_judged_without_them(
            self, tmp_path, monkeypatch):
        judge = _Judge(monkeypatch)
        runs = _world(tmp_path / "runs")
        verdicts = tmp_path / "rejudged"
        _verdict(verdicts, "t2-vegeta-1_816ms", 1.8249, tn.ONE_CLOCK)
        _json(verdicts / "t2-vegeta-1_816ms" / "call.json", [
            "scripts/tool_negatives.py", "judge",
            "--reading", str(runs / "t2-vegeta-1_816ms" / "reading.json"),
            "--reference", str(runs / "t1-vegeta-0ms" / "reference_trips.json"),
            "--offset-ms", "1.816", "--staircase", str(runs), "--tool", "vegeta"])
        (row,) = tb.t2_rows("1", str(verdicts), str(runs))
        got = judge.calls[0]
        assert (got["sent"], got["exit_code"], got["step_ms"], got["shift_ms"]) == (
            None, 0, None, None)
        assert got["control"] is None and got["plain"] is None
        assert judge.asked == [(1.816, None, None)] and row["sent"] == ""


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

    def test_a_round_is_judged_again_from_its_runs_where_its_verdicts_lie_elsewhere(self,
                                                                                    tmp_path):
        _world(tmp_path / "snap" / "tools")
        _verdict(tmp_path / "rejudged", "t2-vegeta-1_816ms", 1.8249, tn.ONE_CLOCK)
        _, (row,) = tb.collect(str(tmp_path), (("1", "snap/tools", "rejudged", {}),))
        assert row["clocks"] == "one"

    def test_freeze_30s_block_is_folded_beside_the_first(self):
        assert [r[0] for r in tb.ROUNDS_V33] == ["1", "2", "3", "4"]
        assert all(r[1].startswith("v33_20261010T075920Z/") for r in tb.ROUNDS_V33)


class TestMain:

    def test_it_writes_both_tables(self, tmp_path, monkeypatch, capsys):
        rounds = (("1", "r1", None, {}),)
        monkeypatch.setattr(tb, "ROUNDS", rounds)
        monkeypatch.setattr(tb, "ROUNDS_V33", ())
        _step(tmp_path / "in" / "r1", "k6", 1.0111)
        _verdict(tmp_path / "in" / "r1", "t2-k6-3_821ms", 3.8309, "times against one clock")
        out = tmp_path / "out"
        assert tb.main(["--collected", str(tmp_path / "in"), "--out", str(out)]) == 0
        with (out / "tools_t1.csv").open(encoding="utf-8") as fh:
            assert list(csv.DictReader(fh))[0]["slope"] == "1.0111"
        with (out / "tools_t2.csv").open(encoding="utf-8") as fh:
            row = list(csv.DictReader(fh))[0]
        assert row["offset_ms"] == "3.8309" and tuple(row) == tb.T2_FIELDS
        assert "1 T1 rows and 1 T2 rows from 1 rounds" in capsys.readouterr().out

    def test_a_folder_with_no_judged_runs_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "out"
        assert tb.main(["--collected", str(tmp_path / "nothing"), "--out", str(out)]) == 1
        assert "no judged tool runs" in capsys.readouterr().out
        assert not out.exists()

    def test_the_committed_tables_are_what_the_paper_reads(self):
        """Sixteen tools, four rounds, two offsets each, every T2 run judged again: the shape
        Section V-B and the supplement's S5 describe."""
        repo = Path(__file__).resolve().parents[2]
        with (repo / "docs" / "results" / "tools" / "tools_t1.csv").open(encoding="utf-8") as fh:
            t1 = list(csv.DictReader(fh))
        with (repo / "docs" / "results" / "tools" / "tools_t2.csv").open(encoding="utf-8") as fh:
            t2 = list(csv.DictReader(fh))
        assert len({r["tool"] for r in t1}) == 16 and len({r["round"] for r in t1}) == 4
        assert len(t1) == 64 and len(t2) == 128
        #: Every tool in the tables has the interval the plan read for it before any run, and
        #: every tool the plan read was run.
        assert {r["tool"] for r in t1} == set(tb.TRIPS)
        assert all(r["clocks"] in ("one", "two", "undecided") and r["verdict_31"] for r in t2)
