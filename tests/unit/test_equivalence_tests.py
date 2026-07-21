"""Tests for scripts/equivalence_tests.py - target >=95% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from equivalence_tests import (
    welch_ci,
    tost,
    equivalence_by_n,
    main,
)


class TestWelchCI:
    def test_ci_brackets_difference(self):
        rng = np.random.default_rng(0)
        a = rng.normal(10, 1, 40)
        b = rng.normal(10, 1, 40)
        diff, lo, hi, df = welch_ci(a, b)
        assert lo < diff < hi and df > 0

    def test_zero_variance_degenerate(self):
        diff, lo, hi, df = welch_ci([5.0, 5.0], [3.0, 3.0])
        assert diff == lo == hi == 2.0


class TestTost:
    def test_equivalent_when_samples_agree(self):
        rng = np.random.default_rng(1)
        a = rng.normal(10, 0.5, 40)
        b = rng.normal(10, 0.5, 40)
        r = tost(a, b, margin=2.0)          # true diff ~0, margin generous
        assert r["equivalent"] is True and r["p_tost"] < 0.05
        assert -2.0 < r["ci90_lo"] and r["ci90_hi"] < 2.0

    def test_not_equivalent_when_far_apart(self):
        rng = np.random.default_rng(2)
        a = rng.normal(10, 0.5, 40)
        b = rng.normal(20, 0.5, 40)         # difference far exceeds the margin
        r = tost(a, b, margin=1.0)
        assert r["equivalent"] is False and r["p_tost"] > 0.05

    def test_underpowered_is_not_equivalent(self):
        # wide spread, tiny n -> cannot establish equivalence even though means match
        r = tost([1.0, 20.0, 40.0], [2.0, 19.0, 41.0], margin=0.5)
        assert r["equivalent"] is False

    def test_zero_variance_inside_margin(self):
        r = tost([5.0, 5.0], [5.0, 5.0], margin=1.0)
        assert r["equivalent"] is True

    def test_zero_variance_outside_margin(self):
        r = tost([5.0, 5.0], [1.0, 1.0], margin=1.0)
        assert r["equivalent"] is False


class TestByN:
    def _df(self):
        rng = np.random.default_rng(3)
        rows = []
        for n in (1, 5):
            for _ in range(20):
                rows.append({"backend": "kafka", "n": n, "v": rng.normal(10, 0.5)})
                rows.append({"backend": "redis", "n": n, "v": rng.normal(10, 0.5)})
        return pd.DataFrame(rows)

    def test_runs_each_level(self):
        out = equivalence_by_n(self._df(), "v", "n", margin=2.0)
        assert set(out["n"]) == {1, 5}
        assert out["equivalent"].all()

    def test_skips_small_cells(self):
        df = pd.DataFrame([{"backend": "kafka", "n": 9, "v": 1.0},
                           {"backend": "redis", "n": 9, "v": 1.1}])
        assert equivalence_by_n(df, "v", "n", margin=1.0).empty


class TestMain:
    def _write(self, path):
        rng = np.random.default_rng(4)
        rows = []
        for n in (1, 5):
            for _ in range(20):
                rows.append({"backend": "kafka", "config": "single", "n": n, "v": rng.normal(10, .5)})
                rows.append({"backend": "redis", "config": "single", "n": n, "v": rng.normal(10, .5)})
                rows.append({"backend": "kafka", "config": "cluster", "n": n, "v": 99.0})
        pd.DataFrame(rows).to_csv(path, index=False)

    def test_end_to_end_with_config_filter(self, temp_dir, capsys):
        csv = temp_dir / "by_run.csv"
        self._write(csv)
        out = temp_dir / "eq"
        rc = main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n",
                   "--margin", "2", "--config", "single", "--label", "tti", "--out", str(out)])
        assert rc == 0
        res = pd.read_csv(out / "tti_tost.csv")
        assert res["equivalent"].all()

    def test_missing_file(self, temp_dir):
        assert main(["--by-run", str(temp_dir / "nope.csv"), "--value-col", "v"]) == 1

    def test_missing_columns(self, temp_dir):
        csv = temp_dir / "bad.csv"
        pd.DataFrame({"backend": ["kafka"], "n": [1]}).to_csv(csv, index=False)
        assert main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n"]) == 1

    def test_insufficient_data(self, temp_dir):
        csv = temp_dir / "thin.csv"
        pd.DataFrame({"backend": ["kafka", "redis"], "n": [9, 9], "v": [1.0, 1.1]}).to_csv(csv, index=False)
        assert main(["--by-run", str(csv), "--value-col", "v", "--n-col", "n"]) == 1
