"""Tests for scripts/make_worked_example.py - target >=95% branch coverage."""
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_worked_example import (
    pick_headline_goal,
    staleness_cost,
    plot_worked_example,
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
    # A late *go-ahead* goal is what really moves win probability. (A late goal that merely
    # extends an existing lead barely moves it -- the leader was already winning.)
    return [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
            _goal(10, 0, "A", "early"),        # 1-0 A
            _goal(50, 0, "B", "equalizer"),    # 1-1
            _goal(88, 0, "B", "late")]         # 1-2 B goes ahead late -> largest shift


class TestPickGoal:
    def test_picks_largest_shift(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "m.json").write_text(json.dumps(_match()))
        g = pick_headline_goal(d)
        assert g["event_id"] == "late"          # late go-ahead goal shifts WP most
        assert 0 < g["tv_shift"] <= 1
        assert g["scorer"] == "B"
        assert g["p_after"] < g["p_before"]     # away scored -> home win prob falls

    def test_own_goal_credited_to_opponent(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        ev = [_ev(0, 0, "A", "Starting XI", eid="x"), _ev(0, 1, "B", "Starting XI", eid="y"),
              _ev(80, 0, "A", "Own Goal Against", eid="og")]
        (d / "m.json").write_text(json.dumps(ev))
        g = pick_headline_goal(d)
        assert g["event_id"] == "og" and g["scorer"] == "B"

    def test_skips_bad_empty_and_goalless(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "bad.json").write_text("{nope")
        (d / "empty.json").write_text("[]")
        (d / "notlist.json").write_text("{}")
        (d / "goalless.json").write_text(json.dumps([_ev(0, 0, "A"), _ev(0, 1, "B")]))
        assert pick_headline_goal(d) is None

    def test_goal_without_id_skipped(self, temp_dir):
        # one identified goal (so shifts is non-empty) plus one with no id, which must be
        # skipped rather than crash or be selected
        d = temp_dir / "events"
        d.mkdir()
        ev = [_ev(0, 0, "A", "Starting XI", eid="s"), _ev(0, 1, "B", "Starting XI", eid="t"),
              _goal(20, 0, "A", "has_id"), _goal(70, 0, "B", None)]
        (d / "m.json").write_text(json.dumps(ev))
        g = pick_headline_goal(d)
        assert g is not None and g["event_id"] == "has_id"


class TestStalenessCost:
    def test_cost_is_shift_times_seconds(self):
        assert staleness_cost(0.3, 2000) == pytest.approx(0.6)
        assert staleness_cost(0.0, 5000) == 0.0


class TestPlot:
    def test_writes_figure(self, temp_dir):
        goal = {"p_before": 0.4, "p_after": 0.8, "minute": 88, "tv_shift": 0.55,
                "dist_before": [0.4, 0.3, 0.3], "dist_after": [0.8, 0.15, 0.05]}
        out = temp_dir / "figs"
        plot_worked_example(goal, {"kafka": 100.0, "redis": 1500.0}, out)
        assert (out / "worked_example.png").exists()
        assert (out / "worked_example.pdf").exists()

    def test_writes_figure_without_distributions(self, temp_dir):
        # falls back to the win-probability pair when the full forecast isn't supplied
        goal = {"p_before": 0.4, "p_after": 0.8, "minute": 88, "tv_shift": 0.55}
        out = temp_dir / "figs2"
        plot_worked_example(goal, {"kafka": 100.0}, out)
        assert (out / "worked_example.png").exists()


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        d = temp_dir / "events"
        d.mkdir()
        (d / "m.json").write_text(json.dumps(_match()))
        out = temp_dir / "figs"
        rc = main(["--events-dir", str(d), "--kafka-latency-ms", "100",
                   "--redis-latency-ms", "2000", "--out", str(out)])
        assert rc == 0
        assert (out / "worked_example.png").exists()
        data = json.loads((out / "worked_example.json").read_text())
        # redis is 20x later here, so it must contribute 20x the staleness
        assert data["staleness_prob_s"]["redis"] == pytest.approx(
            20 * data["staleness_prob_s"]["kafka"])

    def test_no_goals(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "m.json").write_text(json.dumps([_ev(0, 0, "A"), _ev(0, 1, "B")]))
        assert main(["--events-dir", str(d)]) == 1
