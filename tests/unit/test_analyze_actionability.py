"""Tests for scripts/analyze_actionability.py - target >=95% coverage."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_actionability import (
    actionability_from_rates,
    load_run_actionability,
    production_comparison,
    write_production_markdown,
    main,
    SPORTS_USE_CASES,
)


class TestActionabilityFromRates:
    def test_basic_conversion(self):
        rates = {"100": 1.0, "500": 0.5, "1000": 0.0}
        out = actionability_from_rates(rates)
        assert out["betting"] == 0.0          # 100% missed -> 0% under
        assert out["coaching"] == 50.0        # 50% missed -> 50% under
        assert out["broadcast"] == 100.0      # 0% missed -> 100% under

    def test_missing_window_is_nan(self):
        out = actionability_from_rates({"100": 0.0})
        assert out["betting"] == 100.0
        assert np.isnan(out["fan_app"])       # 5000 not provided

    def test_none_value_is_nan(self):
        out = actionability_from_rates({"100": None})
        assert np.isnan(out["betting"])

    def test_custom_use_cases(self):
        out = actionability_from_rates({"250": 0.2}, use_cases={"alert": 250})
        assert out["alert"] == pytest.approx(80.0)


def _make_run(runs, name, rates):
    d = runs / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "tti_summary.json", "w") as f:
        json.dump({"tti_ms": {"missed_window_rate": rates}}, f)
    return d


class TestLoadRunActionability:
    def test_load_kafka_cluster(self, temp_dir):
        runs = temp_dir / "runs"
        _make_run(runs, "batch2_kafka_cluster_s1_n5_rep1", {"100": 1.0, "500": 0.8})
        row = load_run_actionability(runs / "batch2_kafka_cluster_s1_n5_rep1")
        assert row["backend"] == "kafka"
        assert row["config"] == "cluster"
        assert row["pct_under_betting"] == 0.0

    def test_load_redis_single(self, temp_dir):
        runs = temp_dir / "runs"
        _make_run(runs, "batch1_redis_single_s2_n10_rep2", {"100": 0.0})
        row = load_run_actionability(runs / "batch1_redis_single_s2_n10_rep2")
        assert row["backend"] == "redis" and row["config"] == "single"

    def test_missing_tti(self, temp_dir):
        (temp_dir / "r").mkdir()
        assert load_run_actionability(temp_dir / "r") is None

    def test_malformed_tti(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "tti_summary.json").write_text("{bad")
        assert load_run_actionability(d) is None

    def test_no_missed_window_rate(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        (d / "tti_summary.json").write_text(json.dumps({"tti_ms": {"p50": 1.0}}))
        assert load_run_actionability(d) is None

    def test_unknown_backend_config(self, temp_dir):
        runs = temp_dir / "runs"
        _make_run(runs, "weird_run", {"100": 0.5})
        row = load_run_actionability(runs / "weird_run")
        assert row["backend"] == "unknown" and row["config"] == "n/a"


class TestProductionComparison:
    def _df(self):
        return pd.DataFrame([
            {"backend": "kafka", "pct_under_betting": 0.0, "pct_under_coaching": 10.0,
             "pct_under_broadcast": 20.0, "pct_under_fan_app": 50.0},
            {"backend": "redis", "pct_under_betting": 5.0, "pct_under_coaching": 30.0,
             "pct_under_broadcast": 40.0, "pct_under_fan_app": 70.0},
        ])

    def test_has_all_systems(self):
        prod = production_comparison(self._df())
        assert set(prod["system"]) == {"Hawk-Eye", "Second Spectrum", "Opta Sports", "StatsBomb"}

    def test_backend_columns(self):
        prod = production_comparison(self._df())
        assert "kafka_pct_meeting" in prod.columns
        assert "redis_pct_meeting" in prod.columns

    def test_budget_without_mapped_case(self):
        # Second Spectrum (200ms) has no exact use-case window -> no per-backend value
        prod = production_comparison(self._df())
        ss = prod[prod["system"] == "Second Spectrum"].iloc[0]
        assert "kafka_pct_meeting" not in ss or pd.isna(ss.get("kafka_pct_meeting", np.nan))


class TestWriteMarkdown:
    def test_writes_table(self, temp_dir):
        df = pd.DataFrame([
            {"backend": "kafka", "pct_under_betting": 0.0, "pct_under_coaching": 10.0,
             "pct_under_broadcast": 20.0, "pct_under_fan_app": 50.0},
            {"backend": "redis", "pct_under_betting": 5.0, "pct_under_coaching": 30.0,
             "pct_under_broadcast": 40.0, "pct_under_fan_app": 70.0},
        ])
        prod = production_comparison(df)
        out = temp_dir / "prod.md"
        write_production_markdown(prod, out)
        text = out.read_text()
        assert "Production-System Latency Comparison" in text
        assert "Opta Sports" in text


class TestMain:
    def test_main_writes_outputs(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _make_run(runs, "batch1_kafka_single_s1_n5_rep1", {"100": 1.0, "500": 0.8, "1000": 0.7, "5000": 0.3})
        _make_run(runs, "batch1_redis_single_s1_n5_rep1", {"100": 0.9, "500": 0.5, "1000": 0.3, "5000": 0.1})
        out = temp_dir / "out"
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*", "--out", str(out)])
        assert rc == 0
        assert (out / "actionability_by_run.csv").exists()
        assert (out / "actionability_by_backend.csv").exists()
        assert (out / "production_comparison.md").exists()

    def test_main_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*"])
        assert rc == 1
