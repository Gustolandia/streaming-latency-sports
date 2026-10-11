"""Freeze 36's three tool predictions (D39-4): T2-a for Artemis's perf client, T2-r for RocketMQ's
benchmark, T4-b for BookKeeper's benchmark.

The runs are shaped as cloud/azure/tools.sh leaves them: a T2 control folder and one folder per
offset for each two-process tool, and BookKeeper's T4 folder, each with its reading.json and the
count the run was asked to send.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import block_v39 as bv  # noqa: E402


def _run(root, folder, name, reading, sent=3000):
    path = root / folder / name
    path.mkdir(parents=True)
    if reading is not None:
        (path / "reading.json").write_text(json.dumps(reading), encoding="utf-8")
    if sent is not None:
        (path / "asked_to_send.txt").write_text("%d\n" % sent, encoding="utf-8")
    return path


ARTEMIS_QUIET = {"refused": 0, "received": 3000, "kept": 3000, "result": "success",
                 "reported_ms": {"avg": 0.61, "p50": 0.6}}
ARTEMIS_MOVED = {"refused": 2950, "received": 5950, "kept": 3000, "result": "success",
                 "reported_ms": {"avg": 0.9, "p50": 0.8}}
ROCKET_QUIET = {"reported_ms": {"avg": 1.2, "max": 9.0}, "report_rows": [[300, 1.2, 9]]}
ROCKET_MOVED = {"reported_ms": {"avg": -1.4, "max": 0.0}, "report_rows": [[300, -1.4, 0]]}


def _block(root, rounds=("1", "2"), artemis=None, rocket=None, t4_p50=21.3):
    for rnd in rounds:
        folder = "tools_v39" if rnd == "1" else "tools_v39_round%s" % rnd
        _run(root, folder, "t2-artemis-perf-control", ARTEMIS_QUIET)
        _run(root, folder, "t2-rocketmq-benchmark-control", ROCKET_QUIET)
        for offset in ("1_612", "3_612"):
            _run(root, folder, "t2-artemis-perf-%sms" % offset, artemis or ARTEMIS_MOVED)
            _run(root, folder, "t2-rocketmq-benchmark-%sms" % offset, rocket or ROCKET_MOVED)
        _run(root, folder, "t4-bookkeeper-benchmark",
             {"reported_ms": {"p50": t4_p50, "avg": t4_p50}})


ROUNDS = [("1", "tools_v39"), ("2", "tools_v39_round2")]


class TestTheRows:
    def test_each_run_becomes_a_row_with_its_offset(self, tmp_path):
        _block(tmp_path)
        rows = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert [(r["tool"], r["run"], r["offset_ms"]) for r in rows] == [
            ("artemis-perf", "control", ""), ("artemis-perf", "offset", "1.612"),
            ("artemis-perf", "offset", "3.612"), ("rocketmq-benchmark", "control", ""),
            ("rocketmq-benchmark", "offset", "1.612"), ("rocketmq-benchmark", "offset", "3.612"),
            ("bookkeeper-benchmark", "t4", "")]
        moved = rows[4]
        assert (moved["avg"], moved["negative_reports"], moved["zero_max_on_negative"]) == (-1.4, 1, True)
        assert rows[1]["sent"] == 3000 and rows[1]["refused"] == 2950

    def test_a_run_without_its_reading_or_its_count_keeps_its_place_empty(self, tmp_path):
        _run(tmp_path, "tools_v39", "t2-artemis-perf-control", None, sent=None)
        (row,) = bv.block_rows(str(tmp_path), ROUNDS[:1])
        assert row["refused"] == "" and row["sent"] == "" and row["negative_reports"] == ""

    def test_a_round_whose_folder_is_missing_has_no_rows(self, tmp_path):
        assert bv.block_rows(str(tmp_path), ROUNDS) == []


class TestTheVerdicts:
    def test_every_prediction_holds_where_every_round_shows_it(self, tmp_path):
        _block(tmp_path)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert {k: v["verdict"] for k, v in found.items()} == {
            "T2-a": "holds", "T2-r": "holds", "T4-b": "holds"}
        assert found["T2-a"]["held_in_rounds"] == ["1", "2"]

    @pytest.mark.parametrize("change", [
        {"refused": 0}, {"received": 3000}, {"result": "fail"}])
    def test_artemis_moved_without_its_refusals_or_its_redeliveries_fails(self, tmp_path, change):
        _block(tmp_path, artemis=dict(ARTEMIS_MOVED, **change))
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-a"]["verdict"] == "fails"

    def test_artemis_refusing_in_its_control_fails(self, tmp_path):
        _block(tmp_path)
        noisy = tmp_path / "tools_v39" / "t2-artemis-perf-control" / "reading.json"
        noisy.write_text(json.dumps(dict(ARTEMIS_QUIET, refused=3)), encoding="utf-8")
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-a"]["failed_in_rounds"] == ["1"]

    def test_rocketmq_that_did_not_fall_by_half_the_offset_fails(self, tmp_path):
        _block(tmp_path, rocket={"reported_ms": {"avg": 0.9, "max": 4.0}, "report_rows": [[300, 0.9, 4]]})
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T2-r"]["verdict"] == "fails"

    def test_rocketmqs_maximum_is_shown_and_not_judged(self, tmp_path):
        """As the pilot printed it: a maximum of 11 beside an average of -3.09."""
        _block(tmp_path, rocket={"reported_ms": {"avg": -3.09, "max": 11.0},
                                 "report_rows": [[294, -3.09, 11]]})
        rows = bv.block_rows(str(tmp_path), ROUNDS)
        moved = [r for r in rows if r["tool"] == "rocketmq-benchmark" and r["run"] == "offset"][0]
        assert (moved["max"], moved["zero_max_on_negative"]) == (11.0, False)
        assert bv.judge(rows, ["1", "2"])["T2-r"]["verdict"] == "holds"

    def test_bookkeeper_at_the_paths_own_latency_fails(self, tmp_path):
        _block(tmp_path, t4_p50=1.4)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert found["T4-b"]["verdict"] == "fails"

    def test_runs_without_what_each_reads_leave_it_undecided(self, tmp_path):
        _block(tmp_path, artemis={"refused": 1, "reported_ms": {}}, t4_p50=None,
               rocket={"reported_ms": {}, "report_rows": []})
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert {k: v["verdict"] for k, v in found.items()} == {
            "T2-a": "undecided", "T2-r": "undecided", "T4-b": "undecided"}

    def test_a_round_with_no_runs_is_not_judged(self, tmp_path):
        _block(tmp_path, rounds=("1",))
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS), ["1", "2"])
        assert all(v["not_judged_in_rounds"] == ["2"] for v in found.values())

    def test_offsets_without_a_control_are_not_judged(self, tmp_path):
        _run(tmp_path, "tools_v39", "t2-artemis-perf-1_612ms", ARTEMIS_MOVED)
        found = bv.judge(bv.block_rows(str(tmp_path), ROUNDS[:1]), ["1"])
        assert found["T2-a"]["verdict"] == "undecided"


class TestMain:
    def test_it_writes_the_table_and_the_verdicts(self, tmp_path, capsys):
        _block(tmp_path / "azure")
        out, verdicts = tmp_path / "o" / "v39.csv", tmp_path / "o" / "v39_verdicts.json"
        assert bv.main(["--root", str(tmp_path / "azure"), "--rounds",
                        "1:tools_v39,2:tools_v39_round2", "--out", str(out),
                        "--verdicts", str(verdicts)]) == 0
        with out.open(encoding="utf-8", newline="") as fh:
            assert len(list(csv.DictReader(fh))) == 14
        assert out.read_bytes().count(b"\r") == 0
        assert json.loads(verdicts.read_text(encoding="utf-8"))["T4-b"]["verdict"] == "holds"
        assert "T2-r  rocketmq-benchmark     holds" in capsys.readouterr().out

    def test_a_root_with_no_runs_writes_nothing(self, tmp_path, capsys):
        out, verdicts = tmp_path / "v.csv", tmp_path / "v.json"
        assert bv.main(["--root", str(tmp_path), "--out", str(out), "--verdicts", str(verdicts)]) == 1
        assert not out.exists() and "no runs of freeze 36" in capsys.readouterr().out
