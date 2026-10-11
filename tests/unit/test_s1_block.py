"""S1: what each tool's own figures show when the wall clock steps back under it (freeze 34).

The runs are shaped as cloud/azure/tools.sh's `s1` leaves them: a control folder and a stepped
folder per tool and round, each with the tool's reading.json, and the stepped one with the
stepper's steps.csv and clock_step.py's measurements, a bare offset in milliseconds on the last
line.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import s1_block as sb  # noqa: E402

STEP_FIELDS = ("i", "asked_mono_ns", "wall_before_ns", "wall_after_ns", "direction", "step_ns")
WALL = 1_791_716_341_695_778_645


def _steps(path, n=3, step_ms=20, landed_ms=None):
    """n back steps of step_ms, each landing landed_ms (by default exactly) back."""
    landed = step_ms if landed_ms is None else landed_ms
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(STEP_FIELDS)
        for i in range(n):
            before = WALL + i * 200_000_000
            w.writerow((i, i * 200_000_000, before, before - int(landed * 1e6), "back",
                        int(step_ms * 1e6)))


def _run(root, folder, tool, run, reading, steps=True, after="-0.6", landed_ms=None):
    path = root / folder / ("s1-%s-%s" % (tool, run))
    path.mkdir(parents=True)
    if reading is not None:
        (path / "reading.json").write_text(json.dumps(reading), encoding="utf-8")
    if run == "stepped" and steps:
        _steps(path / "steps.csv", landed_ms=landed_ms)
    if run == "stepped" and after is not None:
        (path / "clock_after.json").write_text(after + "\n", encoding="utf-8")
    return path


#: Each tool's reading, without and with what its prediction looks for.
QUIET = {
    "pkb": {"samples_ms": [21.0, 19.0], "reported_ms": {"p50": 20.0, "p99": 21.0}},
    "strimzi-canary": {"logged_negative": 0, "reported_ms": {"p50": 1.0, "p99": 1.0}},
    "stream-perftest-one": {"kept": 2810, "received": 2810, "reported_ms": {"p50": 1.0}},
    "xinfra-monitor": {"pinned_below_ms": [], "received": 4529, "reported_ms": {"p99": 2.0}},
    "kafka-end-to-end": {"reported_ms": {"p50": 1.0, "p99": 2.0}},
}
STEPPED = {
    "pkb": {"samples_ms": [21.0, -29.0], "reported_ms": {"p50": 20.0, "p99": 21.0}},
    "strimzi-canary": {"logged_negative": 3, "reported_ms": {"p50": 1.0, "p99": 1.0}},
    "stream-perftest-one": {"kept": 2795, "received": 2811, "reported_ms": {"p50": 1.0}},
    "xinfra-monitor": {"pinned_below_ms": [-19.0], "received": 4543, "reported_ms": {"p99": 2.0}},
    "kafka-end-to-end": {"reported_ms": {"p50": 1.0, "p99": 3.0}},
}


def _block(root, rounds=("1", "2"), stepped=None):
    for rnd in rounds:
        folder = "tools_v37" if rnd == "1" else "tools_v37_round%s" % rnd
        for tool in sb.TOOLS:
            _run(root, folder, tool, "control", QUIET[tool])
            _run(root, folder, tool, "stepped", (stepped or STEPPED)[tool])


ROUNDS = [("1", "tools_v37"), ("2", "tools_v37_round2")]


class TestWhatEachToolShows:
    @pytest.mark.parametrize("tool, want", [("pkb", 1), ("strimzi-canary", 3),
                                            ("stream-perftest-one", 16), ("xinfra-monitor", 1)])
    def test_the_values_below_zero_each_tool_shows(self, tool, want):
        assert sb.below_zero(tool, STEPPED[tool]) == want

    def test_the_control_tool_shows_none_by_design(self):
        assert sb.below_zero("kafka-end-to-end", STEPPED["kafka-end-to-end"]) is None

    @pytest.mark.parametrize("tool, reading", [("pkb", {"reported_ms": {}}),
                                               ("stream-perftest-one", {"kept": 3}),
                                               ("xinfra-monitor", {"received": 4}),
                                               ("strimzi-canary", {})])
    def test_a_reading_without_the_number_shows_nothing(self, tool, reading):
        assert sb.below_zero(tool, reading) is None


class TestTheSteps:
    def test_steps_made_counts_them_and_adds_up_how_far_back(self, tmp_path):
        _steps(tmp_path / "steps.csv", n=4, step_ms=20)
        assert sb.steps_made(str(tmp_path / "steps.csv")) == (4, 80.0, True)

    def test_a_step_that_landed_far_from_the_one_asked_for_is_not_landed(self, tmp_path):
        _steps(tmp_path / "steps.csv", n=2, step_ms=20, landed_ms=30)
        assert sb.steps_made(str(tmp_path / "steps.csv"))[2] is False

    def test_a_forward_step_counts_but_adds_nothing_back(self, tmp_path):
        p = tmp_path / "steps.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(STEP_FIELDS)
            w.writerow((0, 0, WALL, WALL + 20_000_000, "forward", 20_000_000))
        assert sb.steps_made(str(p)) == (1, 0.0, True)

    def test_no_log_is_no_steps(self, tmp_path):
        assert sb.steps_made(str(tmp_path / "none.csv")) == (0, 0.0, False)

    def test_the_clock_is_read_off_the_last_line(self, tmp_path):
        p = tmp_path / "clock_after.json"
        p.write_text("# measured against /dev/ptp_hyperv\n-0.633718\n", encoding="utf-8")
        assert sb._clock_ms(str(p)) == pytest.approx(-0.633718)

    @pytest.mark.parametrize("text", [None, "", "not a number\n"])
    def test_a_clock_not_measured_is_none(self, tmp_path, text):
        p = tmp_path / "clock_after.json"
        if text is not None:
            p.write_text(text, encoding="utf-8")
        assert sb._clock_ms(str(p)) is None


class TestTheBlock:
    def test_every_prediction_holds_where_every_round_shows_it(self, tmp_path):
        _block(tmp_path)
        verdicts = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert {t: v["verdict"] for t, v in verdicts.items()} == {t: "holds" for t in sb.TOOLS}

    def test_a_stepped_run_showing_nothing_fails_its_prediction(self, tmp_path):
        stepped = dict(STEPPED, **{"strimzi-canary": QUIET["strimzi-canary"]})
        _block(tmp_path, stepped=stepped)
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["strimzi-canary"]
        assert got["verdict"] == "fails" and got["failed_in_rounds"] == ["1", "2"]

    def test_a_control_showing_it_too_fails_the_prediction(self, tmp_path):
        _block(tmp_path)
        p = tmp_path / "tools_v37" / "s1-pkb-control" / "reading.json"
        p.write_text(json.dumps(STEPPED["pkb"]), encoding="utf-8")
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["pkb"]
        assert got["verdict"] == "fails" and got["failed_in_rounds"] == ["1"]

    def test_the_control_tool_moving_by_more_than_a_step_fails(self, tmp_path):
        stepped = dict(STEPPED, **{"kafka-end-to-end": {"reported_ms": {"p50": 1.0, "p99": 4.0}}})
        _block(tmp_path, stepped=stepped)
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["kafka-end-to-end"]
        assert got["verdict"] == "fails"

    def test_a_round_whose_clock_was_not_put_back_is_not_judged(self, tmp_path):
        _block(tmp_path, rounds=("1",))
        folder = tmp_path / "tools_v37_round2"
        for tool in sb.TOOLS:
            _run(tmp_path, "tools_v37_round2", tool, "control", QUIET[tool])
            _run(tmp_path, "tools_v37_round2", tool, "stepped", STEPPED[tool], after="-7.5")
        rows = sb.block_rows(str(tmp_path), ROUNDS)
        assert all(r["instrument_ok"] is False for r in rows
                   if r["round"] == "2" and r["run"] == "stepped")
        got = sb.judge(rows, ["1", "2"])["pkb"]
        assert got["verdict"] == "undecided" and got["not_judged_in_rounds"] == ["2"]
        assert folder.exists()

    def test_a_round_that_never_ran_is_not_judged(self, tmp_path):
        _block(tmp_path, rounds=("1",))
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["xinfra-monitor"]
        assert got["verdict"] == "undecided" and got["not_judged_in_rounds"] == ["2"]

    def test_a_run_without_its_number_is_not_judged(self, tmp_path):
        stepped = dict(STEPPED, **{"xinfra-monitor": {"received": 4543}})
        _block(tmp_path, stepped=stepped)
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["xinfra-monitor"]
        assert got["verdict"] == "undecided"

    def test_a_control_tool_without_its_figures_is_not_judged(self, tmp_path):
        stepped = dict(STEPPED, **{"kafka-end-to-end": {"reported_ms": {"p50": 1.0}}})
        _block(tmp_path, stepped=stepped)
        got = sb.judge(sb.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["kafka-end-to-end"]
        assert got["verdict"] == "undecided"

    def test_a_stepped_run_with_no_steps_written_is_not_judged(self, tmp_path):
        _run(tmp_path, "tools_v37", "pkb", "control", QUIET["pkb"])
        _run(tmp_path, "tools_v37", "pkb", "stepped", STEPPED["pkb"], steps=False)
        rows = sb.block_rows(str(tmp_path), ROUNDS[:1])
        assert [r["instrument_ok"] for r in rows if r["run"] == "stepped"] == [False]

    def test_a_run_with_no_reading_keeps_its_place_with_nothing_read(self, tmp_path):
        _run(tmp_path, "tools_v37", "pkb", "control", None)
        (row,) = sb.block_rows(str(tmp_path), ROUNDS[:1])
        assert row["below_zero"] == "" and row["p50"] == "" and row["kept"] == ""


class TestMain:
    def test_it_writes_the_table_and_the_verdicts(self, tmp_path, capsys):
        _block(tmp_path / "azure")
        out, verdicts = tmp_path / "o" / "s1.csv", tmp_path / "o" / "s1_verdicts.json"
        assert sb.main(["--root", str(tmp_path / "azure"), "--rounds",
                        "1:tools_v37,2:tools_v37_round2", "--out", str(out),
                        "--verdicts", str(verdicts)]) == 0
        with out.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 20 and out.read_bytes().count(b"\r") == 0
        assert json.loads(verdicts.read_text(encoding="utf-8"))["pkb"]["verdict"] == "holds"
        assert "kafka-end-to-end     holds" in capsys.readouterr().out

    def test_a_root_with_no_runs_writes_nothing(self, tmp_path, capsys):
        out, verdicts = tmp_path / "s1.csv", tmp_path / "v.json"
        assert sb.main(["--root", str(tmp_path), "--out", str(out),
                        "--verdicts", str(verdicts)]) == 1
        assert not out.exists() and "no S1 runs" in capsys.readouterr().out
