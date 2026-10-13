"""Freeze 38's predictions for Google's Pub/Sub load test (D41-4): T2-l, its controller throwing on a
median in bucket 0, and T4-l, its printed range one bucket below a floor known in advance.

The runs are shaped as cloud/azure/tools.sh leaves them: a T2 control folder, one folder per offset
and the T4 folder, each with its reading.json as tool_readings.read_pubsub_loadtest writes it.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import block_v41 as bv  # noqa: E402

#: Bucket bounds as its controller prints them: [1.5^(n-1), 1.5^n).
B7, B8, B9 = [11.390625, 17.0859375], [17.0859375, 25.62890625], [25.62890625, 38.443359375]
B17, B18 = [656.8408203125, 985.26123046875], [985.26123046875, 1477.891845703125]
PUBLISHED = {"p50": [7.59375, 11.390625], "p99": B7}
CONTROL = {"ranges": {"subscriber": {"p50": B8, "p99": B9}, "publisher": PUBLISHED},
           "thrown": 0, "wrote_csv": True, "exit": 0, "missing": None, "kept": 120, "sent": 120}
CRASHED = {"ranges": {"subscriber": {}, "publisher": PUBLISHED}, "thrown": 1, "wrote_csv": False,
           "exit": 124, "missing": None, "kept": None, "sent": None}
AHEAD = {"ranges": {"subscriber": {"p50": B17, "p99": B17}, "publisher": PUBLISHED},
         "thrown": 0, "wrote_csv": True, "exit": 0, "missing": None, "kept": 120, "sent": 120}


def _run(root, folder, name, reading):
    path = root / folder / name
    path.mkdir(parents=True)
    if reading is not None:
        (path / "reading.json").write_text(json.dumps(reading), encoding="utf-8")
    return path


def _block(root, rounds=("1", "2"), control=None, moved=None, ahead=None, with_ahead=True):
    for rnd in rounds:
        folder = "tools_v41" if rnd == "1" else "tools_v41_round%s" % rnd
        _run(root, folder, "t2-pubsub-loadtest-control", control or CONTROL)
        for offset in ("26_629", "28_629"):
            _run(root, folder, "t2-pubsub-loadtest-%sms" % offset, moved or CRASHED)
        if with_ahead:
            _run(root, folder, "t4-pubsub-loadtest", ahead or AHEAD)
        # Another tool's runs in the same folder are not this one's.
        _run(root, folder, "t2-quiver-4_000ms", CONTROL)


ROUNDS = [("1", "tools_v41"), ("2", "tools_v41_round2")]


def _judge(root, rounds=ROUNDS):
    return bv.judge(bv.block_rows(str(root), rounds), [rnd for rnd, _ in rounds])


class TestTheRows:
    def test_each_run_becomes_a_row_with_its_offset(self, tmp_path):
        _block(tmp_path)
        rows = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert [(r["run"], r["offset_ms"]) for r in rows] == [
            ("control", ""), ("offset", "26.629"), ("offset", "28.629"), ("ahead", "-1000")]
        assert (rows[0]["sub_p50_low"], rows[0]["sub_p50_high"], rows[0]["sub_p99_high"]) == (
            B8[0], B8[1], B9[1])
        assert (rows[0]["pub_p50_low"], rows[0]["pub_p50_high"]) == tuple(PUBLISHED["p50"])
        assert (rows[0]["wrote_csv"], rows[0]["exit"], rows[0]["kept"]) == (True, 0, 120)
        assert rows[1]["sub_p50_high"] == "" and rows[1]["thrown"] == 1 and rows[1]["exit"] == 124
        assert rows[3]["sub_p50_high"] == B17[1]

    def test_a_run_without_its_reading_keeps_its_place_empty(self, tmp_path):
        _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-control", None)
        (row,) = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert row["sub_p50_high"] == "" and row["exit"] == "" and row["thrown"] == ""

    def test_a_round_whose_folder_is_missing_has_no_rows(self, tmp_path):
        assert bv.block_rows(str(tmp_path), ROUNDS) == []


class TestT2l:
    def test_it_holds_where_every_offset_run_threw_and_every_control_printed(self, tmp_path):
        _block(tmp_path)
        found = _judge(tmp_path)["T2-l"]
        assert found["verdict"] == "holds" and found["held_in_rounds"] == ["1", "2"]

    @pytest.mark.parametrize("fault", [
        {"ranges": {"subscriber": {"p50": [0.0, 1.0]}, "publisher": PUBLISHED}},
        {"thrown": 0},
        {"wrote_csv": True},
        {"exit": 0},
    ], ids=["printed a subscriber median", "threw nothing", "wrote its csv", "exited with 0"])
    def test_an_offset_run_that_did_not_end_as_predicted_fails_it(self, tmp_path, fault):
        _block(tmp_path, moved=dict(CRASHED, **fault))
        found = _judge(tmp_path)["T2-l"]
        assert found["verdict"] == "fails" and found["failed_in_rounds"] == ["1", "2"]

    @pytest.mark.parametrize("fault", [
        {"ranges": {"subscriber": {}, "publisher": PUBLISHED}},
        {"wrote_csv": False},
        {"exit": 1},
    ], ids=["printed no subscriber median", "wrote no csv", "exited otherwise than 0"])
    def test_a_control_that_did_not_end_as_predicted_fails_it(self, tmp_path, fault):
        _block(tmp_path, control=dict(CONTROL, **fault))
        assert _judge(tmp_path)["T2-l"]["verdict"] == "fails"

    def test_a_round_without_its_control_is_not_judged(self, tmp_path):
        _block(tmp_path, rounds=("1",))
        _run(tmp_path, "tools_v41_round2", "t2-pubsub-loadtest-26_629ms", CRASHED)
        found = _judge(tmp_path)["T2-l"]
        assert found["verdict"] == "undecided" and found["not_judged_in_rounds"] == ["2"]

    def test_a_round_whose_runs_left_no_reading_is_not_judged(self, tmp_path):
        _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-control", CONTROL)
        _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-26_629ms", None)
        found = _judge(tmp_path, ROUNDS[:1])["T2-l"]
        assert found["verdict"] == "undecided" and found["not_judged_in_rounds"] == ["1"]

    def test_a_round_with_a_control_and_no_offset_is_not_judged(self, tmp_path):
        _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-control", CONTROL)
        assert _judge(tmp_path, ROUNDS[:1])["T2-l"]["verdict"] == "undecided"


class TestT4l:
    def test_it_holds_where_every_printed_range_lay_below_a_second(self, tmp_path):
        _block(tmp_path)
        found = _judge(tmp_path)["T4-l"]
        assert found["verdict"] == "holds" and found["held_in_rounds"] == ["1", "2"]

    def test_a_range_reaching_past_a_second_fails_it(self, tmp_path):
        """A controller that labelled each bucket by the values in it would print [985, 1478) for a
        latency raised past a second, its top above the floor."""
        _block(tmp_path, ahead=dict(AHEAD, ranges={"subscriber": {"p50": B18}}))
        assert _judge(tmp_path)["T4-l"]["verdict"] == "fails"

    def test_a_run_that_printed_no_subscriber_range_is_not_judged(self, tmp_path):
        _block(tmp_path, ahead=dict(AHEAD, ranges={"subscriber": {}}))
        assert _judge(tmp_path)["T4-l"]["verdict"] == "undecided"

    def test_a_round_without_its_run_is_not_judged(self, tmp_path):
        _block(tmp_path, with_ahead=False)
        found = _judge(tmp_path)["T4-l"]
        assert found["verdict"] == "undecided" and found["not_judged_in_rounds"] == ["1", "2"]


class TestThePilotsRuns:
    """The fourth pilot's runs, read by tool_readings as tools.sh reads them, and judged as the
    block's will be: T2-l and T4-l hold on them, the shape of a real reading included."""

    FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tools_f38"

    def _reading(self, name):
        import tool_readings as tr
        return tr.read_tool("pubsub-loadtest", (self.FIXTURES / name).read_text(encoding="utf-8"))

    def test_both_hold_on_them(self, tmp_path):
        _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-control",
             self._reading("pubsub-loadtest_t2_control.txt"))
        for offset in ("26_629", "28_629"):
            _run(tmp_path, "tools_v41", "t2-pubsub-loadtest-%sms" % offset,
                 self._reading("pubsub-loadtest_t2_offset.txt"))
        _run(tmp_path, "tools_v41", "t4-pubsub-loadtest", self._reading("pubsub-loadtest_t4_ahead.txt"))
        found = _judge(tmp_path, ROUNDS[:1])
        assert found["T2-l"]["verdict"] == "holds" and found["T4-l"]["verdict"] == "holds"


class TestMain:
    def test_it_writes_the_table_and_the_verdicts(self, tmp_path, capsys):
        _block(tmp_path)
        out, verdicts = tmp_path / "out" / "v41.csv", tmp_path / "out" / "v41_verdicts.json"
        assert bv.main(["--root", str(tmp_path), "--rounds", "1:tools_v41,2:tools_v41_round2",
                        "--out", str(out), "--verdicts", str(verdicts)]) == 0
        with out.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 8 and list(rows[0]) == list(bv.FIELDS)
        found = json.loads(verdicts.read_text(encoding="utf-8"))
        assert found["T2-l"]["verdict"] == "holds" and found["T4-l"]["verdict"] == "holds"
        assert "T2-l  pubsub-loadtest  holds" in capsys.readouterr().out

    def test_no_runs_is_said_and_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "v41.csv"
        assert bv.main(["--root", str(tmp_path), "--out", str(out),
                        "--verdicts", str(tmp_path / "v.json")]) == 1
        assert not out.exists() and "no T2 or T4 runs" in capsys.readouterr().out
