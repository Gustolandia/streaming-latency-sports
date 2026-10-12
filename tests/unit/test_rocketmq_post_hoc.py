"""RocketMQ's benchmark in freeze 36's block, read after its runs: which runs waited in the broker
for their queue, and how its staircase rose without them.

The runs are shaped as cloud/azure/tools.sh leaves them: one folder per stage with its reading, and
the T1 zero step's reference run as a log beside it.
"""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import rocketmq_post_hoc as rp  # noqa: E402
import tool_readings  # noqa: E402


def _reading(b2c, s2c, top=14.0, reports=1, sent=3000):
    return {"tool": "rocketmq-benchmark", "reported_ms": {"avg": b2c, "max": top},
            "s2c_avg_ms": s2c, "reports": reports, "sent": sent}


def _run(root, folder, name, reading):
    path = root / folder / name
    path.mkdir(parents=True)
    if reading is not None:
        (path / "reading.json").write_text(json.dumps(reading), encoding="utf-8")
    return path


def _reference(root, folder, b2c):
    """A reference run's log, as the Consumer prints its report and the Producer its count."""
    line = ("Current Time: 2026-10-11 22:59:16,304 | Consume TPS: 462 | AVG(B2C) RT(ms): %.3f | "
            "AVG(S2C) RT(ms): %.3f | MAX(B2C) RT(ms): 892 | MAX(S2C) RT(ms): 886 | Consume Fail: 0"
            % (b2c, b2c - 0.1))
    path = root / folder / "t1-rocketmq-benchmark-0ms"
    path.mkdir(parents=True, exist_ok=True)
    (path / "reference.log").write_text(line + "\n[Complete] Send Total: 3000 | x\n", encoding="utf-8")


def _staircase(root, folder, waited=(), slope=2.0):
    for added in (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.1, 1.5, 2.0):
        name = "t1-rocketmq-benchmark-%sms" % ("%g" % added).replace(".", "_")
        b2c = 20000.0 if added in waited else 1.3 + slope * added
        _run(root, folder, name, _reading(b2c, b2c - 0.3))


class TestTheRuns:
    def test_every_stage_and_the_reference_are_read(self, tmp_path):
        _staircase(tmp_path, "tools_v39", waited=(0.2,))
        _run(tmp_path, "tools_v39", "t2-rocketmq-benchmark-control", _reading(1.4, 1.1))
        _run(tmp_path, "tools_v39", "t3-rocketmq-benchmark-l0-firstno", _reading(1.5, 1.2))
        _run(tmp_path, "tools_v39", "t1-artemis-perf-0ms", _reading(1.0, 1.0))
        _reference(tmp_path, "tools_v39", 138.897)
        rows = rp.runs(str(tmp_path), (("1", "tools_v39"),))
        assert [r["stage"] for r in rows].count("t1") == 10
        assert {r["stage"] for r in rows} == {"t1", "t2", "t3", "reference"}
        waited = [r for r in rows if r["waited"] is True]
        assert [(r["stage"], r["added_ms"]) for r in waited] == [("t1", "0.2"), ("reference", "")]
        assert waited[1]["b2c_avg_ms"] == pytest.approx(138.897)

    def test_a_reading_without_figures_keeps_its_place_empty(self, tmp_path):
        _run(tmp_path, "tools_v39", "t4-rocketmq-benchmark", {"tool": "rocketmq-benchmark"})
        (row,) = rp.runs(str(tmp_path), (("1", "tools_v39"),))
        assert (row["b2c_avg_ms"], row["waited"], row["reports"]) == ("", "", "")

    def test_a_round_without_its_folder_has_no_rows(self, tmp_path):
        assert rp.runs(str(tmp_path), (("1", "tools_v39"),)) == []


class TestTheSlopes:
    def test_the_waits_set_the_slope_and_the_rest_rise_as_they_rose(self, tmp_path):
        _staircase(tmp_path, "tools_v39", waited=(0.2, 2.0))
        _staircase(tmp_path, "tools_v39_round2")
        rows = rp.runs(str(tmp_path), (("1", "tools_v39"), ("2", "tools_v39_round2")))
        one, two = rp.slopes(rows)
        assert (one["steps"], one["waited"]) == (10, 2) and one["slope_all"] > 1000
        assert one["slope_b2c"] == pytest.approx(2.0) and one["slope_s2c"] == pytest.approx(2.0)
        assert two["waited"] == 0 and two["slope_all"] == pytest.approx(two["slope_b2c"])

    def test_too_few_steps_give_no_slope(self, tmp_path):
        _run(tmp_path, "tools_v39", "t1-rocketmq-benchmark-0ms", _reading(1.3, None))
        (only,) = rp.slopes(rp.runs(str(tmp_path), (("1", "tools_v39"),)))
        assert only["slope_all"] is None and only["slope_s2c"] is None


class TestTheCommand:
    def test_it_writes_both_tables(self, tmp_path, capsys, monkeypatch):
        _staircase(tmp_path, "tools_v39", waited=(0.2,))
        _reference(tmp_path, "tools_v39", 1.8)
        monkeypatch.setattr(rp, "ROUNDS", (("1", "tools_v39"),))
        out, slopes = tmp_path / "o" / "runs.csv", tmp_path / "o" / "t1.csv"
        assert rp.main(["--root", str(tmp_path), "--runs", str(out), "--slopes", str(slopes)]) == 0
        with open(out, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 11 and tuple(rows[0]) == rp.RUN_FIELDS
        zero = [r for r in rows if r["run"] == "t1-rocketmq-benchmark-0ms"][0]
        assert zero["b2c_avg_ms"] == "1.3000" and rows[-1]["stage"] == "reference"
        with open(slopes, encoding="utf-8", newline="") as fh:
            (table,) = list(csv.DictReader(fh))
        assert table["waited"] == "1" and table["slope_b2c"] == "2.0000"
        assert "11 runs, 1 waited in the broker" in capsys.readouterr().out

    def test_it_says_so_where_there_are_no_runs(self, tmp_path, capsys):
        assert rp.main(["--root", str(tmp_path), "--runs", str(tmp_path / "a.csv"),
                        "--slopes", str(tmp_path / "b.csv")]) == 1
        assert "no runs of rocketmq-benchmark" in capsys.readouterr().out


def test_its_reader_is_the_one_the_block_used():
    assert rp.tool_readings is tool_readings and rp.TOOL in tool_readings.READERS
