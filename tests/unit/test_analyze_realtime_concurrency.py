"""Tests for scripts/analyze_realtime_concurrency.py - target >=95% coverage."""
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_realtime_concurrency import (
    infer_config,
    load_meta,
    load_tti,
    collect,
    summarize,
    main,
)


def _write_run(runs_dir, n, backend, feed, rep, *, speedup=10, config="single",
               tti_p50=16.0, transport_p50=1.0, schedlag_p50=10.0, matched=4400,
               write_meta=True, write_tti=True, ts="20260617_220000", max_t_sim=600):
    d = runs_dir / f"concurrency_n{n}_{ts}_{backend}_feed{feed}_rep{rep}"
    d.mkdir(parents=True, exist_ok=True)
    if write_meta:
        meta = {"backend": backend, "speedup": speedup, "max_t_sim": max_t_sim}
        if backend == "kafka":
            meta["bootstrap"] = "localhost:19092" if config == "single" else "localhost:9092"
        else:
            meta["redis"] = {"port": 16379 if config == "single" else 7000}
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if write_tti:
        tti = {
            "n_matched": matched,
            "tti_ms": {"p50": tti_p50, "p95": tti_p50 * 2},
            "transport_ms": {"p50": transport_p50, "p95": transport_p50 * 2},
            "producer_sched_lag_ms": {"p50": schedlag_p50},
        }
        (d / "tti_summary.json").write_text(json.dumps(tti), encoding="utf-8")
    return d


class TestInferConfig:
    def test_kafka_single(self):
        assert infer_config({"backend": "kafka", "bootstrap": "localhost:19092"}) == "single"

    def test_kafka_cluster(self):
        assert infer_config({"backend": "kafka", "bootstrap": "localhost:9092"}) == "cluster"

    def test_redis_single(self):
        assert infer_config({"backend": "redis", "redis": {"port": 16379}}) == "single"

    def test_redis_cluster(self):
        assert infer_config({"backend": "redis", "port": 7001}) == "cluster"

    def test_unknown(self):
        assert infer_config({"backend": "kafka", "bootstrap": "weird:5000"}) == "unknown"
        assert infer_config({"backend": "other"}) == "unknown"

    def test_redis_unknown_port(self):
        # redis on a port that's neither single nor cluster -> unknown (branch 49->51)
        assert infer_config({"backend": "redis", "port": 9999}) == "unknown"


class TestLoaders:
    def test_load_meta_ok_and_bad(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "meta.json").write_text('{"backend":"kafka"}')
        assert load_meta(d)["backend"] == "kafka"
        empty = temp_dir / "empty"
        empty.mkdir()
        assert load_meta(empty) is None

    def test_load_tti_bad(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "tti_summary.json").write_text("{nope")
        assert load_tti(d) is None


class TestCollect:
    def test_filters_by_speedup(self, temp_dir):
        runs = temp_dir / "runs"
        _write_run(runs, 5, "kafka", 1, 1, speedup=10)
        _write_run(runs, 5, "kafka", 1, 1, speedup=120, ts="20260101_000000")
        df = collect(runs, speedup=10)
        assert len(df) == 1 and df.iloc[0]["backend"] == "kafka"

    def test_skips_runs_missing_files(self, temp_dir):
        runs = temp_dir / "runs"
        _write_run(runs, 1, "kafka", 1, 1, write_tti=False)  # no tti -> skipped
        _write_run(runs, 1, "redis", 1, 1)
        df = collect(runs, speedup=10)
        assert len(df) == 1 and df.iloc[0]["backend"] == "redis"

    def test_ignores_non_concurrency_dirs(self, temp_dir):
        runs = temp_dir / "runs"
        (runs / "batch9_20260617_kafka_single_s1_n1_rep1").mkdir(parents=True)
        _write_run(runs, 10, "redis", 2, 3, config="cluster")
        df = collect(runs, speedup=10)
        assert len(df) == 1 and df.iloc[0]["config"] == "cluster" and df.iloc[0]["n"] == 10

    def test_skips_non_directory_match(self, temp_dir):
        # a *file* matching the glob is skipped (branch at 'not is_dir')
        runs = temp_dir / "runs"
        runs.mkdir()
        (runs / "concurrency_n5_20260617_220000_kafka_feed1_rep1").write_text("not a dir")
        _write_run(runs, 5, "redis", 1, 1)
        df = collect(runs, speedup=10)
        assert len(df) == 1 and df.iloc[0]["backend"] == "redis"

    def test_skips_glob_match_failing_regex(self, temp_dir):
        # dir matches the glob but not the strict timestamped regex -> skipped (branch at 'not m')
        runs = temp_dir / "runs"
        runs.mkdir()
        (runs / "concurrency_nX_badts_kafka_feed1_rep1").mkdir()
        _write_run(runs, 10, "kafka", 1, 1)
        df = collect(runs, speedup=10)
        assert len(df) == 1 and df.iloc[0]["n"] == 10

    def test_speedup_none_includes_all(self, temp_dir):
        runs = temp_dir / "runs"
        _write_run(runs, 5, "kafka", 1, 1, speedup=10)
        _write_run(runs, 5, "kafka", 2, 1, speedup=120, ts="20260101_000000")
        df = collect(runs, speedup=None)
        assert len(df) == 2

    def test_min_max_t_sim_filter(self, temp_dir):
        runs = temp_dir / "runs"
        _write_run(runs, 5, "kafka", 1, 1, max_t_sim=9000)   # full-match -> kept
        _write_run(runs, 5, "kafka", 2, 1, max_t_sim=600)    # windowed  -> dropped
        df = collect(runs, speedup=10, min_max_t_sim=9000)
        assert len(df) == 1 and df.iloc[0]["run_id"].endswith("feed1_rep1")


class TestSummarize:
    def test_medians_and_counts(self, temp_dir):
        runs = temp_dir / "runs"
        _write_run(runs, 5, "kafka", 1, 1, tti_p50=10)
        _write_run(runs, 5, "kafka", 2, 1, tti_p50=20)
        df = collect(runs, speedup=10)
        s = summarize(df)
        row = s[(s["backend"] == "kafka") & (s["n"] == 5)].iloc[0]
        assert row["tti_p50"] == 15.0  # median of 10, 20
        assert row["n_runs"] == 2


class TestMain:
    def test_main_end_to_end(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        for fb in (1, 2):
            _write_run(runs, 5, "kafka", fb, 1, config="single")
            _write_run(runs, 5, "redis", fb, 1, config="cluster", tti_p50=40)
        out = temp_dir / "out"
        rc = main(["--runs-dir", str(runs), "--speedup", "10", "--out", str(out)])
        assert rc == 0
        assert (out / "realtime_concurrency_by_run.csv").exists()
        assert (out / "realtime_concurrency_summary.csv").exists()

    def test_main_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--speedup", "10"]) == 1
