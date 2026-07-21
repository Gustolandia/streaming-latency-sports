"""Tests for scripts/analyze_backlog.py - target >=95% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_backlog import run_latencies, growth_ratio, analyze, summarize, main


def _run(tmp, name, latencies_ms):
    """A run whose per-event latency follows the given sequence."""
    d = tmp / name
    d.mkdir(parents=True)
    n = len(latencies_ms)
    sched = [i * 1_000_000 for i in range(n)]            # 1 ms apart
    out = [s + int(l * 1e6) for s, l in zip(sched, latencies_ms)]
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n)],
                  "t_prod_sched_ns": sched}).to_csv(d / "producer.csv", index=False)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n)],
                  "t_output_ns": out}).to_csv(d / "consumer.csv", index=False)
    return d


class TestRunLatencies:
    def test_orders_by_scheduled_time(self, temp_dir):
        d = _run(temp_dir, "r", [5.0] * 8)
        lat = run_latencies(d)
        assert len(lat) == 8 and np.allclose(lat, 5.0)

    def test_missing_files(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert run_latencies(d) is None

    def test_bad_schema(self, temp_dir):
        d = temp_dir / "bad"
        d.mkdir()
        (d / "producer.csv").write_text("x\n1\n")
        (d / "consumer.csv").write_text("x\n1\n")
        assert run_latencies(d) is None

    def test_no_overlapping_events(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        pd.DataFrame({"event_id": ["a"], "t_prod_sched_ns": [0]}).to_csv(d / "producer.csv", index=False)
        pd.DataFrame({"event_id": ["b"], "t_output_ns": [1]}).to_csv(d / "consumer.csv", index=False)
        assert run_latencies(d) is None


class TestGrowthRatio:
    def test_flat_latency_gives_ratio_near_one(self):
        g = growth_ratio([10.0] * 40)
        assert g["growth"] == pytest.approx(1.0)

    def test_growing_latency_detected(self):
        # linearly increasing latency = classic backlog signature
        g = growth_ratio(list(np.linspace(10, 110, 40)))
        assert g["growth"] > 3

    def test_too_few_events(self):
        assert growth_ratio([1.0, 2.0]) is None

    def test_none_input(self):
        assert growth_ratio(None) is None

    def test_zero_first_quartile_guarded(self):
        assert growth_ratio([0.0] * 10 + [5.0] * 10) is None


class TestAnalyzeAndSummarize:
    def test_labels_backends_and_summarizes(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "c_kafka_feed1_rep1", [10.0] * 40)                       # flat
        _run(runs, "c_redis_feed1_rep1", list(np.linspace(10, 200, 40)))    # growing
        df = analyze(runs, "c_*")
        assert set(df["backend"]) == {"kafka", "redis"}
        s = summarize(df).set_index("backend")
        assert s.loc["kafka", "growth"] == pytest.approx(1.0, abs=0.05)
        assert s.loc["redis", "growth"] > 3

    def test_skips_unusable_and_nondirs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        (runs / "c_file").write_text("x")
        (runs / "c_empty_kafka").mkdir()
        _run(runs, "c_ok_kafka_feed1_rep1", [10.0] * 40)
        assert len(analyze(runs, "c_*")) == 1

    def test_summarize_empty(self):
        assert summarize(pd.DataFrame()).empty


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _run(runs, "c_redis_feed1_rep1", list(np.linspace(10, 200, 40)))
        out = temp_dir / "bk"
        rc = main(["--runs-dir", str(runs), "--run-glob", "c_*", "--label", "d20",
                   "--out", str(out)])
        assert rc == 0
        assert (out / "d20_by_run.csv").exists() and (out / "d20_summary.csv").exists()

    def test_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--run-glob", "zzz*"]) == 1
