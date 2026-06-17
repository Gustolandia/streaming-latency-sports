"""Tests for scripts/statistical_analysis.py - target >=95% coverage."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from statistical_analysis import (
    cohens_d,
    hedges_g,
    interpret_effect,
    confidence_interval,
    check_normality,
    check_equal_variance,
    compare_two_groups,
    holm_bonferroni,
    load_run_metrics,
    run_family,
    main,
)


class TestEffectSizes:
    def test_cohens_d_positive(self):
        a = [10, 12, 11, 13, 10, 12]
        b = [5, 6, 5, 7, 6, 5]
        assert cohens_d(a, b) > 0

    def test_cohens_d_too_few(self):
        assert np.isnan(cohens_d([1], [2]))

    def test_cohens_d_zero_pooled(self):
        # identical constant groups -> pooled sd 0 -> defined as 0
        assert cohens_d([5, 5, 5], [5, 5, 5]) == 0.0

    def test_hedges_g_smaller_than_d(self):
        a = [10, 12, 11, 13]
        b = [5, 6, 5, 7]
        assert abs(hedges_g(a, b)) < abs(cohens_d(a, b))

    def test_hedges_g_too_few(self):
        assert np.isnan(hedges_g([1], [2]))

    @pytest.mark.parametrize("d,label", [
        (0.1, "negligible"), (0.3, "small"), (0.6, "medium"), (1.2, "large"),
    ])
    def test_interpret_effect(self, d, label):
        assert interpret_effect(d) == label

    def test_interpret_effect_nan(self):
        assert interpret_effect(float("nan")) == "undefined"


class TestConfidenceInterval:
    def test_ci_basic(self):
        low, high = confidence_interval([10, 12, 11, 13, 9, 14])
        assert low < high

    def test_ci_too_few(self):
        low, high = confidence_interval([5])
        assert np.isnan(low) and np.isnan(high)


class TestAssumptionChecks:
    def test_normality_few_points_true(self):
        assert check_normality([1, 2]) is True

    def test_normality_normal_data(self):
        rng = np.random.default_rng(0)
        assert check_normality(rng.normal(0, 1, 200)) is True

    def test_normality_skewed_data(self):
        rng = np.random.default_rng(1)
        assert check_normality(rng.exponential(1.0, 200)) is False

    def test_equal_variance_true(self):
        rng = np.random.default_rng(2)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        assert check_equal_variance(a, b) is True

    def test_equal_variance_few_points(self):
        assert check_equal_variance([1], [2, 3]) is True

    def test_equal_variance_unequal(self):
        rng = np.random.default_rng(3)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 10, 100)
        assert check_equal_variance(a, b) is False


class TestCompareTwoGroups:
    def test_nonparametric_selected_for_skewed(self):
        rng = np.random.default_rng(4)
        a = rng.exponential(1.0, 50)
        b = rng.exponential(2.0, 50)
        res = compare_two_groups(a, b, "exp")
        assert res["test"] == "Mann-Whitney U"
        assert res["label"] == "exp"
        assert "cohens_d" in res and "hedges_g" in res

    def test_parametric_selected_for_normal(self):
        rng = np.random.default_rng(5)
        a = rng.normal(10, 1, 80)
        b = rng.normal(10, 1, 80)
        res = compare_two_groups(a, b, "norm")
        assert res["test"] in ("Student t-test", "Welch t-test")

    def test_welch_when_unequal_variance(self):
        rng = np.random.default_rng(6)
        a = rng.normal(10, 1, 80)
        b = rng.normal(10, 8, 80)
        res = compare_two_groups(a, b)
        # normal but unequal variance -> Welch
        assert res["test"] == "Welch t-test"


class TestHolmBonferroni:
    def test_empty(self):
        assert holm_bonferroni([]) == []

    def test_known_ordering(self):
        res = holm_bonferroni([0.01, 0.04, 0.03], alpha=0.05)
        # smallest p=0.01 * 3 = 0.03 < 0.05 -> reject
        assert res[0]["reject"] is True
        # adjusted values are monotone in rank
        assert res[0]["p_adjusted"] <= res[2]["p_adjusted"] or res[0]["p_adjusted"] <= res[1]["p_adjusted"]

    def test_all_large_not_rejected(self):
        res = holm_bonferroni([0.4, 0.6, 0.8])
        assert all(not r["reject"] for r in res)

    def test_adjusted_capped_at_one(self):
        res = holm_bonferroni([0.9, 0.95])
        assert all(r["p_adjusted"] <= 1.0 for r in res)


def _make_run(run_dir, name, p50, p95=None):
    d = run_dir / name
    d.mkdir(parents=True, exist_ok=True)
    block = {"p50": p50}
    if p95 is not None:
        block["p95"] = p95
    with open(d / "tti_summary.json", "w") as f:
        json.dump({"tti_ms": block}, f)
    return d


class TestLoadRunMetrics:
    def test_load_parses_run_id(self, temp_dir):
        runs = temp_dir / "runs"
        _make_run(runs, "batch1_20260615_kafka_single_s1_n5_rep1", 100.0, 200.0)
        _make_run(runs, "batch2_20260615_redis_cluster_s2_n10_rep2", 50.0, 90.0)
        df = load_run_metrics(runs, "batch*")
        assert len(df) == 2
        assert set(df["backend"]) == {"kafka", "redis"}
        assert df[df["backend"] == "kafka"].iloc[0]["config"] == "single"

    def test_load_skips_missing_and_bad(self, temp_dir):
        runs = temp_dir / "runs"
        # dir without tti_summary
        (runs / "batch1_nope").mkdir(parents=True)
        # malformed tti_summary
        bad = runs / "batch1_20260615_kafka_single_s1_n5_rep9"
        bad.mkdir(parents=True)
        (bad / "tti_summary.json").write_text("{invalid")
        df = load_run_metrics(runs, "batch*")
        assert df.empty

    def test_load_unparseable_name(self, temp_dir):
        runs = temp_dir / "runs"
        _make_run(runs, "batchX_weird_name", 100.0)
        df = load_run_metrics(runs, "batch*")
        assert df.iloc[0]["backend"] is None


class TestRunFamily:
    def _df(self):
        rows = []
        rng = np.random.default_rng(7)
        for cfg in ("single", "cluster"):
            for _ in range(5):
                rows.append({"backend": "kafka", "config": cfg, "p50": float(rng.normal(100, 5))})
                rows.append({"backend": "redis", "config": cfg, "p50": float(rng.normal(60, 5))})
        return pd.DataFrame(rows)

    def test_run_family_corrects(self):
        comps = run_family(self._df())
        assert len(comps) >= 1
        assert all("p_adjusted" in c and "reject_after_correction" in c for c in comps)

    def test_run_family_no_backend(self):
        df = pd.DataFrame({"p50": [1.0, 2.0, 3.0]})
        assert run_family(df) == []


class TestMain:
    def test_main_writes_outputs(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        rng = np.random.default_rng(8)
        for i in range(5):
            _make_run(runs, f"batch1_20260615_kafka_single_s1_n5_rep{i}", float(rng.normal(100, 5)))
            _make_run(runs, f"batch1_20260615_redis_single_s1_n5_rep{i}", float(rng.normal(60, 5)))
        out = temp_dir / "out"
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*", "--out", str(out)])
        assert rc == 0
        assert (out / "statistical_analysis.json").exists()
        assert (out / "statistical_analysis.csv").exists()

    def test_main_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*"])
        assert rc == 1
