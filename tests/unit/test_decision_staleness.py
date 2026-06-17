"""Tests for scripts/decision_staleness.py - target >=95% coverage."""
import json
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from decision_staleness import (
    goal_decision_shifts,
    build_goal_shifts,
    run_decision_cost,
    main,
)


def _ev(minute, second, team, etype="Pass", eid=None, **extra):
    e = {"minute": minute, "second": second, "team": {"name": team},
         "type": {"name": etype}, "id": eid}
    e.update(extra)
    return e


def _goal(minute, second, team, eid):
    return _ev(minute, second, team, "Shot", eid=eid,
               shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.5})


def _match():
    return [
        _ev(0, 0, "A", "Starting XI", eid="s1"),
        _ev(0, 1, "B", "Starting XI", eid="s2"),
        _goal(10, 0, "A", "g1"),
        _goal(80, 0, "B", "g2"),
    ]


class TestGoalShifts:
    def test_shifts_for_goals(self):
        shifts = goal_decision_shifts(_match())
        assert set(shifts) == {"g1", "g2"}
        assert all(0 < v <= 1 for v in shifts.values())

    def test_late_goal_bigger_shift(self):
        # a goal at 80' (little time to respond) shifts WP more than one at 10'
        shifts = goal_decision_shifts(_match())
        assert shifts["g2"] > shifts["g1"]

    def test_own_goal_counted(self):
        ev = [_ev(0, 0, "A", "Starting XI", eid="x"), _ev(0, 1, "B", "Starting XI", eid="y"),
              _ev(20, 0, "A", "Own Goal Against", eid="og")]
        shifts = goal_decision_shifts(ev)
        assert "og" in shifts and shifts["og"] > 0

    def test_empty_match(self):
        assert goal_decision_shifts([]) == {}


class TestBuildGoalShifts:
    def test_across_files(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "1.json").write_text(json.dumps(_match()))
        (d / "bad.json").write_text("{nope")
        (d / "empty.json").write_text("[]")
        shifts = build_goal_shifts(d)
        assert "g1" in shifts and "g2" in shifts

    def test_empty_dir(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        assert build_goal_shifts(d) == {}


def _run_dir(tmp, name, rows):
    """rows: list of (event_id, sched_ns, output_ns)."""
    d = tmp / name
    d.mkdir(parents=True)
    pd.DataFrame([{"event_id": e, "t_prod_sched_ns": s} for e, s, _ in rows]).to_csv(d / "producer.csv", index=False)
    pd.DataFrame([{"event_id": e, "t_output_ns": o} for e, _, o in rows]).to_csv(d / "consumer.csv", index=False)
    return d


class TestRunDecisionCost:
    def test_cost_accumulates_for_goals(self, temp_dir):
        shifts = {"g1": 0.2, "g2": 0.5}
        # g1 delivered 1s late, g2 2s late; non-goal e3 ignored
        d = _run_dir(temp_dir, "batch9_kafka_single_x",
                     [("g1", 0, 1_000_000_000), ("g2", 0, 2_000_000_000), ("e3", 0, 5_000_000_000)])
        cost, n, mean_lat = run_decision_cost(d, shifts)
        assert n == 2
        assert cost == pytest.approx(0.2 * 1.0 + 0.5 * 2.0)
        assert mean_lat == pytest.approx(1500.0)

    def test_negative_latency_clamped(self, temp_dir):
        d = _run_dir(temp_dir, "r", [("g1", 1_000_000_000, 500_000_000)])
        cost, n, _ = run_decision_cost(d, {"g1": 0.3})
        assert n == 1 and cost == 0.0

    def test_missing_files(self, temp_dir):
        (temp_dir / "empty").mkdir()
        assert run_decision_cost(temp_dir / "empty", {"g1": 0.2}) is None

    def test_bad_schema(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "producer.csv").write_text("wrong\n1\n")
        (d / "consumer.csv").write_text("wrong\n1\n")
        assert run_decision_cost(d, {"g1": 0.2}) is None


class TestMain:
    def test_main_end_to_end(self, temp_dir, capsys):
        ev = temp_dir / "events"
        ev.mkdir()
        (ev / "m.json").write_text(json.dumps(_match()))
        runs = temp_dir / "runs"
        _run_dir(runs, "batch9_20260617_kafka_single_s1_n1_rep1",
                 [("g1", 0, 1_000_000_000), ("g2", 0, 2_000_000_000)])
        _run_dir(runs, "batch9_20260617_redis_cluster_s1_n1_rep1",
                 [("g1", 0, 3_000_000_000), ("g2", 0, 4_000_000_000)])
        out = temp_dir / "ds"
        rc = main(["--runs-dir", str(runs), "--pattern", "batch9_*",
                   "--events-dir", str(ev), "--out", str(out)])
        assert rc == 0
        assert (out / "decision_staleness_by_run.csv").exists()
        assert (out / "decision_staleness_by_backend_config.csv").exists()

    def test_main_no_shifts(self, temp_dir):
        ev = temp_dir / "events"
        ev.mkdir()
        (ev / "m.json").write_text("[]")
        assert main(["--events-dir", str(ev), "--runs-dir", str(temp_dir)]) == 1

    def test_main_no_runs(self, temp_dir):
        ev = temp_dir / "events"
        ev.mkdir()
        (ev / "m.json").write_text(json.dumps(_match()))
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--pattern", "zzz*", "--events-dir", str(ev)]) == 1
