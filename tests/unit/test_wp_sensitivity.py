"""Tests for scripts/wp_sensitivity.py - target >=95% branch coverage."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wp_sensitivity import (
    collect_run_latencies,
    staleness_for_rate,
    sweep,
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
    return [_ev(0, 0, "A", "Starting XI", eid="s1"), _ev(0, 1, "B", "Starting XI", eid="s2"),
            _goal(20, 0, "A", "g1"), _goal(80, 0, "B", "g2")]


def _events_dir(tmp):
    d = tmp / "events"
    d.mkdir()
    (d / "m.json").write_text(json.dumps(_match()))
    return d


def _run(tmp, name, rows, max_t_sim=9000):
    d = tmp / name
    d.mkdir(parents=True)
    pd.DataFrame([{"event_id": e, "t_prod_sched_ns": s} for e, s, _ in rows]).to_csv(d / "producer.csv", index=False)
    pd.DataFrame([{"event_id": e, "t_output_ns": o} for e, _, o in rows]).to_csv(d / "consumer.csv", index=False)
    (d / "meta.json").write_text(json.dumps({"backend": "kafka", "max_t_sim": max_t_sim}))
    return d


class TestCollect:
    def test_collects_only_decisive_events(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n1_kafka_feed1_rep1",
             [("g1", 0, 1_000_000_000), ("other", 0, 9_000_000_000)])
        got = collect_run_latencies(runs, "concurrency_n*", {"g1", "g2"})
        assert len(got) == 1
        assert set(got[0]["latencies"]) == {"g1"}      # non-decisive event excluded
        assert got[0]["latencies"]["g1"] == pytest.approx(1.0)
        assert got[0]["backend"] == "kafka"

    def test_skips_missing_csvs_and_nondirs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        (runs / "concurrency_n1_file").write_text("x")     # not a dir
        (runs / "concurrency_n1_empty_kafka").mkdir()      # no csvs
        _run(runs, "concurrency_n1_ok_kafka_feed1_rep1", [("g1", 0, 1_000_000_000)])
        assert len(collect_run_latencies(runs, "concurrency_n*", {"g1"})) == 1

    def test_skips_runs_without_decisive_events(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n1_kafka_feed1_rep1", [("nothing", 0, 1_000_000_000)])
        assert collect_run_latencies(runs, "concurrency_n*", {"g1"}) == []

    def test_min_max_t_sim_filter(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n1_kafka_a_rep1", [("g1", 0, 1_000_000_000)], max_t_sim=600)
        assert collect_run_latencies(runs, "concurrency_n*", {"g1"}, min_max_t_sim=9000) == []

    def test_bad_schema_skipped(self, temp_dir):
        runs = temp_dir / "runs"
        d = runs / "concurrency_n1_kafka_bad_rep1"
        d.mkdir(parents=True)
        (d / "producer.csv").write_text("wrong\n1\n")
        (d / "consumer.csv").write_text("wrong\n1\n")
        assert collect_run_latencies(runs, "concurrency_n*", {"g1"}) == []


class TestStaleness:
    def test_reweights_by_shifts(self):
        runs = [{"run_id": "r", "backend": "kafka", "n_concurrency": 1,
                 "latencies": {"g1": 2.0, "g2": 1.0}}]
        df = staleness_for_rate(runs, {"g1": 0.5, "g2": 0.25})
        assert df.iloc[0]["decision_staleness_prob_s"] == pytest.approx(0.5 * 2 + 0.25 * 1)

    def test_unknown_event_contributes_zero(self):
        runs = [{"run_id": "r", "backend": "kafka", "n_concurrency": 1, "latencies": {"x": 5.0}}]
        assert staleness_for_rate(runs, {"g1": 0.5}).iloc[0]["decision_staleness_prob_s"] == 0.0


class TestSweep:
    def test_difference_stays_small_across_rates(self, temp_dir):
        ev = _events_dir(temp_dir)
        runs = [{"run_id": "k", "backend": "kafka", "n_concurrency": 1, "latencies": {"g1": 0.01}},
                {"run_id": "r", "backend": "redis", "n_concurrency": 1, "latencies": {"g1": 0.01}}]
        out = sweep(ev, runs, [1.0, 1.3, 1.6], grid_seconds=300)
        assert len(out) == 3
        # identical latencies -> the backends must agree at every model setting
        assert out["difference"].abs().max() == pytest.approx(0.0, abs=1e-12)
        assert out["ece"].notna().all()

    def test_missing_backend_gives_nan(self, temp_dir):
        ev = _events_dir(temp_dir)
        runs = [{"run_id": "k", "backend": "kafka", "n_concurrency": 1, "latencies": {"g1": 0.01}}]
        out = sweep(ev, runs, [1.3], grid_seconds=300)
        assert pd.isna(out.iloc[0]["difference"])


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        ev = _events_dir(temp_dir)
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n1_kafka_feed1_rep1", [("g1", 0, 10_000_000)])
        _run(runs, "concurrency_n1_redis_feed1_rep1", [("g1", 0, 10_000_000)])
        out = temp_dir / "sens"
        rc = main(["--runs-dir", str(runs), "--pattern", "concurrency_n*",
                   "--events-dir", str(ev), "--rates", "1.0", "1.3", "--out", str(out)])
        assert rc == 0
        res = pd.read_csv(out / "wp_sensitivity.csv")
        assert len(res) == 2

    def test_no_shifts(self, temp_dir):
        ev = temp_dir / "empty"
        ev.mkdir()
        (ev / "m.json").write_text("[]")
        assert main(["--events-dir", str(ev), "--runs-dir", str(temp_dir)]) == 1

    def test_no_runs(self, temp_dir):
        ev = _events_dir(temp_dir)
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--pattern", "zzz*", "--events-dir", str(ev)]) == 1
