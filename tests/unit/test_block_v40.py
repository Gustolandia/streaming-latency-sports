"""Freeze 37's prediction for Quiver (D40-4): T2-q, its summary wrapped by an unsigned subtraction.

The runs are shaped as cloud/azure/tools.sh leaves them: a T2 control folder and one folder per
offset, each with its reading.json.
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import block_v40 as bv  # noqa: E402

TOP = float(2 ** 64)
QUIET = {"below_zero": 0, "received": 3000, "sent": 3000, "wrapped": [],
         "reported_ms": {"avg": 1.4, "p50": 1.0, "max": 9.0}}
MOVED = {"below_zero": 2400, "received": 3000, "sent": 3000, "wrapped": ["avg", "max", "p50"],
         "reported_ms": {"avg": 1.47e19, "p50": TOP, "max": TOP}}


def _run(root, folder, name, reading):
    path = root / folder / name
    path.mkdir(parents=True)
    if reading is not None:
        (path / "reading.json").write_text(json.dumps(reading), encoding="utf-8")
    return path


def _block(root, rounds=("1", "2"), control=None, moved=None):
    for rnd in rounds:
        folder = "tools_v40" if rnd == "1" else "tools_v40_round%s" % rnd
        _run(root, folder, "t2-quiver-control", control or QUIET)
        for offset in ("2_000", "4_000"):
            _run(root, folder, "t2-quiver-%sms" % offset, moved or MOVED)
        # Another tool's runs in the same folder are not Quiver's.
        _run(root, folder, "t2-pravega-benchmark-4_000ms", QUIET)


ROUNDS = [("1", "tools_v40"), ("2", "tools_v40_round2")]


class TestTheRows:
    def test_each_run_becomes_a_row_with_its_offset(self, tmp_path):
        _block(tmp_path)
        rows = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert [(r["run"], r["offset_ms"]) for r in rows] == [
            ("control", ""), ("offset", "2.000"), ("offset", "4.000")]
        assert (rows[1]["below_zero"], rows[1]["max"], rows[1]["wrapped"]) == (2400, TOP, "avg+max+p50")
        assert rows[0]["wrapped"] == "" and rows[0]["sent"] == 3000

    def test_a_run_without_its_reading_keeps_its_place_empty(self, tmp_path):
        _run(tmp_path, "tools_v40", "t2-quiver-control", None)
        (row,) = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert row["below_zero"] == "" and row["max"] == "" and row["sent"] == ""

    def test_a_round_whose_folder_is_missing_has_no_rows(self, tmp_path):
        assert bv.block_rows(str(tmp_path), ROUNDS) == []


class TestTheVerdict:
    def test_it_holds_where_every_round_shows_it(self, tmp_path):
        _block(tmp_path)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-q"]["verdict"] == "holds"
        assert found["T2-q"]["held_in_rounds"] == ["1", "2"]

    def test_it_fails_where_a_value_below_zero_did_not_wrap_the_maximum(self, tmp_path):
        """A tool that kept its sign would leave its maximum a trip, and its average with it."""
        signed = dict(MOVED, reported_ms={"avg": -1.2, "p50": -1.0, "max": 7.0}, wrapped=[])
        _block(tmp_path, moved=signed)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-q"]["verdict"] == "fails"

    def test_it_fails_where_the_control_was_not_quiet(self, tmp_path):
        noisy = dict(QUIET, below_zero=3)
        _block(tmp_path, control=noisy)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-q"]["verdict"] == "fails" and found["T2-q"]["failed_in_rounds"] == ["1", "2"]

    def test_a_control_that_stalled_still_holds(self, tmp_path):
        """As in the third pilot: transfers held up for 17 s lift the control's maximum and average
        to seconds with nothing below zero; only a wrapped figure fails it (D40-4)."""
        stalled = dict(QUIET, reported_ms={"avg": 1488.6, "p50": 2.0, "max": 17304.0})
        _block(tmp_path, control=stalled)
        assert bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["T2-q"]["verdict"] == "holds"

    def test_it_fails_where_the_control_wrapped(self, tmp_path):
        wrapped = dict(QUIET, reported_ms={"avg": 1.2, "p50": 1.0, "max": TOP})
        _block(tmp_path, control=wrapped)
        assert bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["T2-q"]["verdict"] == "fails"

    def test_it_fails_where_the_offsets_made_nothing_below_zero(self, tmp_path):
        _block(tmp_path, moved=dict(MOVED, below_zero=0))
        assert bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])["T2-q"]["verdict"] == "fails"

    def test_a_round_that_cannot_judge_it_leaves_it_undecided(self, tmp_path):
        _block(tmp_path, rounds=("1",))
        _run(tmp_path, "tools_v40_round2", "t2-quiver-control", QUIET)
        _run(tmp_path, "tools_v40_round2", "t2-quiver-2_000ms", dict(MOVED, below_zero=None))
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2", "3"])
        assert found["T2-q"]["verdict"] == "undecided"
        assert found["T2-q"]["not_judged_in_rounds"] == ["2", "3"]

    def test_a_control_with_no_offsets_beside_it_judges_nothing(self, tmp_path):
        _run(tmp_path, "tools_v40", "t2-quiver-control", QUIET)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS[:1]), ["1"])
        assert found["T2-q"]["not_judged_in_rounds"] == ["1"]


class TestTheCommand:
    def test_it_writes_the_rows_and_the_verdict(self, tmp_path, capsys):
        _block(tmp_path)
        out, verdicts = tmp_path / "out" / "v40.csv", tmp_path / "out" / "v40_verdicts.json"
        assert bv.main(["--root", str(tmp_path), "--rounds", "1:tools_v40,2:tools_v40_round2",
                        "--out", str(out), "--verdicts", str(verdicts)]) == 0
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 6 and tuple(rows[0]) == bv.FIELDS
        assert json.loads(verdicts.read_text(encoding="utf-8"))["T2-q"]["verdict"] == "holds"
        assert "T2-q  quiver   holds" in capsys.readouterr().out

    def test_it_says_so_where_there_are_no_runs(self, tmp_path, capsys):
        assert bv.main(["--root", str(tmp_path), "--out", str(tmp_path / "a.csv"),
                        "--verdicts", str(tmp_path / "a.json")]) == 1
        assert "no T2 runs of Quiver" in capsys.readouterr().out
