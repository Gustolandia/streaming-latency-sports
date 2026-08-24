"""Tests for scripts/fair_statistics.py - target >=95% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from fair_statistics import (
    holm_bonferroni,
    rank_biserial,
    per_n_tests,
    kruskal_across_n,
    main,
)


class TestHolmBonferroni:
    def test_monotone_and_bounded(self):
        adj = holm_bonferroni([0.01, 0.04, 0.03])
        assert all(0 <= a <= 1 for a in adj)
        # smallest raw p gets multiplied by m=3
        assert adj[0] == pytest.approx(0.03)

    def test_clamped_to_one(self):
        assert holm_bonferroni([0.9, 0.8]) == [1.0, 1.0]


class TestRankBiserial:
    def test_empty_group_nan(self):
        assert np.isnan(rank_biserial([], [1, 2], 0))

    def test_direction(self):
        # Kafka all higher -> U (of kafka) = n1*n2 -> r = -1
        assert rank_biserial([10, 11], [1, 2], 4) == pytest.approx(-1.0)


def _df():
    rows = []
    # N=1: parity (heavily overlapping, non-identical) ; N=5: Redis clearly higher (separated)
    for i in range(8):
        rows.append({"backend": "kafka", "n": 1, "v": 10 + i})
        rows.append({"backend": "redis", "n": 1, "v": 10 + i + 0.5})
        rows.append({"backend": "kafka", "n": 5, "v": 10 + i})
        rows.append({"backend": "redis", "n": 5, "v": 500 + i})
    return pd.DataFrame(rows)


class TestPerN:
    def test_parity_vs_divergence(self):
        out = per_n_tests(_df(), "v", "n")
        r1 = out[out["n"] == 1].iloc[0]
        r5 = out[out["n"] == 5].iloc[0]
        assert not bool(r1["significant"])      # N=1 parity
        assert bool(r5["significant"])           # N=5 diverges
        assert r5["redis_median"] > r5["kafka_median"]

    def test_skips_small_groups(self):
        df = pd.DataFrame([{"backend": "kafka", "n": 9, "v": 1},
                           {"backend": "redis", "n": 9, "v": 2}])  # <2 each -> skipped
        assert per_n_tests(df, "v", "n").empty

    def test_mannwhitney_nan_return_normalized(self, monkeypatch):
        # newer scipy returns nan rather than raising; p must normalize to 1.0
        import fair_statistics as fs
        monkeypatch.setattr(fs.stats, "mannwhitneyu",
                            lambda *a, **k: (float("nan"), float("nan")))
        out = per_n_tests(_df(), "v", "n")
        assert (out["p"] == 1.0).all()
        assert not out["significant"].any()

    def test_mannwhitney_valueerror_branch(self, monkeypatch):
        # older scipy raises ValueError on all-tied input; guard maps it to p=1.0, U=nan
        import fair_statistics as fs

        def _raise(*a, **k):
            raise ValueError("all identical")

        monkeypatch.setattr(fs.stats, "mannwhitneyu", _raise)
        out = per_n_tests(_df(), "v", "n")
        assert (out["p"] == 1.0).all()
        assert out["U"].isna().all()


class TestKruskal:
    def test_detects_n_effect(self):
        out = kruskal_across_n(_df(), "v", "n")
        # redis has a big N-effect (10s vs 500s)
        assert bool(out[out["backend"] == "redis"].iloc[0]["significant"])

    def test_kruskal_nan_return_normalized(self, monkeypatch):
        # newer scipy returns nan rather than raising; p must normalize to 1.0
        import fair_statistics as fs
        monkeypatch.setattr(fs.stats, "kruskal",
                            lambda *a, **k: (float("nan"), float("nan")))
        out = kruskal_across_n(_df(), "v", "n")
        assert (out["p"] == 1.0).all()
        assert not out["significant"].any()

    def test_too_few_groups(self):
        df = pd.DataFrame([{"backend": "kafka", "n": 1, "v": i} for i in range(3)])  # 1 N-group
        assert kruskal_across_n(df, "v", "n").empty

    def test_all_tied_input_is_not_significant(self):
        # All-tied input is undefined for Kruskal-Wallis: older scipy raises ValueError,
        # newer scipy returns nan. Either way we must report p=1.0 (no evidence).
        df = pd.DataFrame([{"backend": "kafka", "n": n, "v": 5.0}
                           for n in (1, 5) for _ in range(3)])
        out = kruskal_across_n(df, "v", "n")
        assert out.iloc[0]["p"] == 1.0
        assert not bool(out.iloc[0]["significant"])

    def test_reports_median_trend_beside_pvalue(self):
        # A significant p with a trivial effect must be distinguishable from a large one:
        # the magnitude columns are what separate them.
        df = pd.DataFrame(
            [{"backend": "kafka", "n": n, "v": v}
             for n, vals in ((1, (1.00, 1.01, 0.99)), (10, (1.00, 1.02, 1.01)))
             for v in vals])
        row = kruskal_across_n(df, "v", "n").iloc[0]
        assert row["medians"] == "N=1:1; N=10:1.01"
        assert row["median_first"] == pytest.approx(1.00)
        assert row["median_last"] == pytest.approx(1.01)
        assert row["ratio_last_first"] == pytest.approx(1.01)

    def test_ratio_guards_zero_baseline(self):
        df = pd.DataFrame(
            [{"backend": "kafka", "n": n, "v": v}
             for n, vals in ((1, (0.0, 0.0, 0.0)), (10, (5.0, 6.0, 7.0)))
             for v in vals])
        row = kruskal_across_n(df, "v", "n").iloc[0]
        assert row["median_first"] == 0.0
        assert np.isnan(row["ratio_last_first"])


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        csv = temp_dir / "by_run.csv"
        _df().to_csv(csv, index=False)
        out = temp_dir / "stats"
        rc = main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n",
                   "--label", "tti", "--out", str(out)])
        assert rc == 0
        assert (out / "tti_kafka_vs_redis_by_n.csv").exists()
        assert (out / "tti_kruskal_across_n.csv").exists()

    def test_missing_file(self, temp_dir):
        assert main(["--by-run", str(temp_dir / "nope.csv"), "--value-col", "v"]) == 1

    def test_missing_columns(self, temp_dir):
        csv = temp_dir / "bad.csv"
        pd.DataFrame({"backend": ["kafka"], "n": [1]}).to_csv(csv, index=False)
        assert main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n"]) == 1

    def test_config_filter(self, temp_dir):
        # only the 'single' rows should feed the tests
        df = _df()
        df["config"] = "single"
        cluster = _df()
        cluster["config"] = "cluster"
        cluster["v"] = 1.0  # would break separation if not filtered out
        full = pd.concat([df, cluster], ignore_index=True)
        csv = temp_dir / "cfg.csv"
        full.to_csv(csv, index=False)
        out = temp_dir / "s"
        rc = main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n",
                   "--config", "single", "--out", str(out)])
        assert rc == 0
        per_n = pd.read_csv(out / "metric_kafka_vs_redis_by_n.csv")
        # single-only: N=5 still separates (redis higher), so significant
        assert bool(per_n[per_n["n"] == 5].iloc[0]["significant"])

    def test_insufficient_data(self, temp_dir):
        csv = temp_dir / "thin.csv"
        pd.DataFrame({"backend": ["kafka", "redis"], "n": [9, 9], "v": [1, 2]}).to_csv(csv, index=False)
        assert main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n"]) == 1


class TestOlderScipyRaisesWhereNewerScipyReturnsNaN:
    """Two scipy generations disagree about all-tied input, and both must give "no evidence".

    Kruskal-Wallis on groups whose values are all identical has no variance to work with.
    Older scipy raises ValueError; newer scipy returns nan. Either way the honest reading is
    that the data show no concurrency effect -- and an uncaught exception here would abort a
    whole campaign's statistics over a degenerate cell.
    """

    def test_a_raising_scipy_is_read_as_no_evidence(self, monkeypatch):
        import fair_statistics as fs
        import pandas as pd

        def raiser(*groups):
            raise ValueError("All numbers are identical in kruskal")

        monkeypatch.setattr(fs.stats, "kruskal", raiser)
        df = pd.DataFrame({"backend": ["kafka"] * 6,
                           "n": [1, 1, 1, 2, 2, 2],
                           "v": [5.0] * 6})
        out = kruskal_across_n(df, "v", "n")
        assert len(out) == 1
        row = out.iloc[0]
        assert row["p"] == 1.0, "no variance is no evidence, not a significant result"
        assert row["significant"] is False or not row["significant"]
        assert not np.isfinite(row["H"]), "there is no statistic to report either"
