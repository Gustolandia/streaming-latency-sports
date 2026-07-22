"""Tests for scripts/staleness_budget.py - target 100% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from staleness_budget import (  # noqa: E402
    budget,
    sweep,
    annotation_for_share,
    compare_backends,
    main,
)


class TestBudget:
    def test_shares_sum_to_one(self):
        b = budget(annotation_s=15.0, transport_ms=1.3, inference_ms=0.7)
        assert b["annotation_share"] + b["transport_share"] + 0.7 / b["total_ms"] == \
            pytest.approx(1.0)

    def test_transport_is_negligible_at_realistic_annotation(self):
        # 1.3 ms against 15 s: infrastructure owns under a hundredth of a percent
        b = budget(15.0, 1.3)
        assert b["transport_share_pct"] < 0.01

    def test_transport_dominates_when_annotation_is_tiny(self):
        b = budget(0.0005, 100.0)
        assert b["transport_share"] > 0.5

    def test_zero_total_guarded(self):
        assert budget(0.0, 0.0, 0.0) is None


class TestSweep:
    def test_spans_the_range(self):
        s = sweep(1.3, lo_s=1.0, hi_s=30.0, n=10)
        assert len(s) == 10
        assert s["annotation_s"].min() == pytest.approx(1.0)
        assert s["annotation_s"].max() == pytest.approx(30.0)

    def test_transport_share_decreases_with_annotation(self):
        s = sweep(1.3, lo_s=1.0, hi_s=30.0, n=8)
        assert s["transport_share"].is_monotonic_decreasing

    @pytest.mark.parametrize("lo,hi,n", [(0, 30, 10), (1, 0, 10), (1, 30, 0)])
    def test_invalid_ranges(self, lo, hi, n):
        assert sweep(1.3, lo_s=lo, hi_s=hi, n=n).empty


class TestAnnotationForShare:
    def test_inverts_the_budget(self):
        a = annotation_for_share(transport_ms=1.3, target_share=0.10)
        b = budget(a, 1.3)
        assert b["transport_share"] == pytest.approx(0.10, rel=1e-6)

    def test_answer_is_absurdly_small_for_real_transport(self):
        # For transport to own even 1% of the budget, annotation would have to be ~0.13 s -
        # far faster than any human coding pipeline. That is the structural argument.
        assert annotation_for_share(1.3, 0.01) < 0.2

    def test_clamps_at_zero_when_inference_dominates(self):
        assert annotation_for_share(1.0, 0.5, inference_ms=1000.0) == 0.0

    @pytest.mark.parametrize("share", [0.0, 1.0, -0.1, 1.5])
    def test_invalid_share(self, share):
        assert np.isnan(annotation_for_share(1.3, share))

    def test_zero_transport(self):
        assert np.isnan(annotation_for_share(0.0, 0.1))


class TestCompareBackends:
    def test_prices_the_choice(self):
        df = compare_backends({"kafka": 1.0, "redis": 2.3}, annotation_s=15.0)
        assert len(df) == 2
        assert df["backend_spread_ms"].iloc[0] == pytest.approx(1.3)
        # choosing a backend is worth well under a hundredth of a percent of staleness
        assert df["diff_share_pct"].iloc[0] < 0.01

    def test_single_backend_has_no_spread(self):
        df = compare_backends({"kafka": 1.0})
        assert "diff_share_pct" not in df.columns

    def test_empty(self):
        assert compare_backends({}).empty


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        out = temp_dir / "b"
        rc = main(["--transport-ms", "1.3", "--out", str(out)])
        assert rc == 0
        assert (out / "annotation_sweep.csv").exists()
        cap = capsys.readouterr().out
        assert "vendor CLAIM" in cap, "annotation figures must be labelled as claims"
        assert "transport share at typical" in cap

    def test_backend_comparison_written(self, temp_dir, capsys):
        out = temp_dir / "b"
        rc = main(["--transport-ms", "1.0", "--transport-alt-ms", "2.3", "--out", str(out)])
        assert rc == 0
        assert (out / "backend_comparison.csv").exists()
        assert "backend choice is worth" in capsys.readouterr().out

    def test_invalid_range_returns_1(self, temp_dir, capsys):
        rc = main(["--transport-ms", "1.3", "--annotation-lo", "0",
                   "--out", str(temp_dir / "b")])
        assert rc == 1
        assert "Invalid annotation range" in capsys.readouterr().out
