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
    infer_config,
    parse_n,
    run_max_t_sim,
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

    def test_goal_without_event_id_skipped(self):
        # a goal whose event has no id is not added to the shift map (branch eid is None)
        ev = [_ev(0, 0, "A", "Starting XI", eid="s"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _goal(30, 0, "A", eid=None), _goal(40, 0, "B", eid="g")]
        shifts = goal_decision_shifts(ev)
        assert "g" in shifts and None not in shifts

    def test_own_goal_counted(self):
        ev = [_ev(0, 0, "A", "Starting XI", eid="x"), _ev(0, 1, "B", "Starting XI", eid="y"),
              _ev(20, 0, "A", "Own Goal Against", eid="og")]
        shifts = goal_decision_shifts(ev)
        assert "og" in shifts and shifts["og"] > 0

    def test_empty_match(self):
        assert goal_decision_shifts([]) == {}

    def test_red_card_is_decisive(self):
        # a dismissal moves the forecast (the WP model conditions on red-card differential),
        # so it must contribute staleness like a goal does
        ev = [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _ev(60, 0, "B", "Bad Behaviour", eid="red1",
                  bad_behaviour={"card": {"name": "Red Card"}})]
        shifts = goal_decision_shifts(ev)
        assert "red1" in shifts and shifts["red1"] > 0

    def test_second_yellow_counts_as_dismissal(self):
        ev = [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _ev(70, 0, "A", "Bad Behaviour", eid="sy",
                  bad_behaviour={"card": {"name": "Second Yellow"}})]
        assert goal_decision_shifts(ev)["sy"] > 0

    def test_yellow_card_is_not_decisive(self):
        ev = [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _ev(30, 0, "A", "Bad Behaviour", eid="yellow",
                  bad_behaviour={"card": {"name": "Yellow Card"}})]
        assert goal_decision_shifts(ev) == {}

    def test_red_cards_can_be_disabled(self):
        ev = [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _ev(60, 0, "B", "Bad Behaviour", eid="red1",
                  bad_behaviour={"card": {"name": "Red Card"}})]
        assert goal_decision_shifts(ev, include_red_cards=False) == {}

    def test_red_card_state_carries_into_later_goal(self):
        # the goal's shift must be evaluated with the dismissal already in the game state
        ev = [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
              _ev(40, 0, "B", "Bad Behaviour", eid="red1",
                  bad_behaviour={"card": {"name": "Red Card"}}),
              _goal(50, 0, "A", "g_after_red")]
        shifts = goal_decision_shifts(ev)
        assert set(shifts) == {"red1", "g_after_red"}
        assert all(v > 0 for v in shifts.values())


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


class TestInferConfigAndN:
    def test_config_from_name(self, temp_dir):
        assert infer_config(temp_dir, "batch9_kafka_cluster_s1_n1_rep1") == "cluster"
        assert infer_config(temp_dir, "batch9_redis_single_s1_n1_rep1") == "single"

    def _meta_run(self, temp_dir, name, meta):
        d = temp_dir / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps(meta))
        return d

    def test_config_from_meta_kafka(self, temp_dir):
        d = self._meta_run(temp_dir, "concurrency_n5_x_kafka_feed1_rep1",
                           {"backend": "kafka", "bootstrap": "localhost:19092"})
        assert infer_config(d, d.name) == "single"
        d2 = self._meta_run(temp_dir, "concurrency_n5_y_kafka_feed1_rep1",
                            {"backend": "kafka", "bootstrap": "localhost:9092"})
        assert infer_config(d2, d2.name) == "cluster"

    def test_config_from_meta_redis(self, temp_dir):
        d = self._meta_run(temp_dir, "concurrency_n5_x_redis_feed1_rep1",
                           {"backend": "redis", "redis": {"port": 16379}})
        assert infer_config(d, d.name) == "single"
        d2 = self._meta_run(temp_dir, "concurrency_n5_y_redis_feed1_rep1",
                            {"backend": "redis", "port": 7001})
        assert infer_config(d2, d2.name) == "cluster"

    def test_config_unknown_when_no_meta(self, temp_dir):
        d = temp_dir / "concurrency_n5_z_kafka_feed1_rep1"
        d.mkdir()
        assert infer_config(d, d.name) == "?"

    def test_config_unknown_weird_meta(self, temp_dir):
        d = self._meta_run(temp_dir, "concurrency_n5_w_kafka_feed1_rep1",
                           {"backend": "kafka", "bootstrap": "weird:5000"})
        assert infer_config(d, d.name) == "?"
        d2 = self._meta_run(temp_dir, "concurrency_n5_q_redis_feed1_rep1",
                            {"backend": "redis", "port": 9999})
        assert infer_config(d2, d2.name) == "?"

    def test_config_unknown_other_backend(self, temp_dir):
        # meta present but backend is neither kafka nor redis (branch 52->58)
        d = self._meta_run(temp_dir, "concurrency_n5_o_feed1_rep1", {"backend": "other"})
        assert infer_config(d, d.name) == "?"

    def test_parse_n(self):
        assert parse_n("concurrency_n20_x_kafka_feed1_rep1") == 20
        assert parse_n("batch9_kafka_single_s1_n1_rep1") == 1
        assert parse_n("no_concurrency_marker_here") == 1

    def test_run_max_t_sim(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"max_t_sim": 9000}))
        assert run_max_t_sim(d) == 9000.0
        empty = temp_dir / "e"
        empty.mkdir()
        assert run_max_t_sim(empty) == 0.0  # no meta
        bad = temp_dir / "b"
        bad.mkdir()
        (bad / "meta.json").write_text(json.dumps({"max_t_sim": "oops"}))
        assert run_max_t_sim(bad) == 0.0  # non-numeric


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
        assert (out / "decision_staleness_by_backend_config_n.csv").exists()

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

    def test_main_min_max_t_sim_filter(self, temp_dir):
        # full-match run (max_t_sim=9000) kept; windowed run (600) filtered out.
        ev = temp_dir / "events"
        ev.mkdir()
        (ev / "m.json").write_text(json.dumps(_match()))
        runs = temp_dir / "runs"
        full = _run_dir(runs, "concurrency_n1_x_kafka_feed1_rep1",
                        [("g1", 0, 1_000_000_000), ("g2", 0, 2_000_000_000)])
        (full / "meta.json").write_text(json.dumps({"backend": "kafka",
                                                     "bootstrap": "localhost:19092",
                                                     "max_t_sim": 9000}))
        windowed = _run_dir(runs, "concurrency_n1_y_kafka_feed1_rep1",
                            [("g1", 0, 9_000_000_000)])
        (windowed / "meta.json").write_text(json.dumps({"backend": "kafka",
                                                         "bootstrap": "localhost:19092",
                                                         "max_t_sim": 600}))
        out = temp_dir / "o"
        rc = main(["--runs-dir", str(runs), "--pattern", "concurrency_*",
                   "--events-dir", str(ev), "--out", str(out), "--min-max-t-sim", "9000"])
        assert rc == 0
        import pandas as _pd
        by_run = _pd.read_csv(out / "decision_staleness_by_run.csv")
        assert list(by_run["run_id"]) == ["concurrency_n1_x_kafka_feed1_rep1"]

    def test_main_skips_nondir_and_incomplete_runs(self, temp_dir):
        # a file matching the pattern (skipped, 155) and a run dir with no CSVs (None -> 158),
        # plus one valid run so main still succeeds.
        ev = temp_dir / "events"
        ev.mkdir()
        (ev / "m.json").write_text(json.dumps(_match()))
        runs = temp_dir / "runs"
        runs.mkdir()
        (runs / "batch9_file_marker").write_text("not a dir")  # matches batch9_* pattern
        (runs / "batch9_incomplete_kafka_single").mkdir()       # no producer/consumer -> None
        _run_dir(runs, "batch9_ok_kafka_single",
                 [("g1", 0, 1_000_000_000), ("g2", 0, 2_000_000_000)])
        rc = main(["--runs-dir", str(runs), "--pattern", "batch9_*",
                   "--events-dir", str(ev), "--out", str(temp_dir / "o")])
        assert rc == 0
