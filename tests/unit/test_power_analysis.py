"""Tests for scripts/power_analysis.py - target >=95% coverage."""
import json
from pathlib import Path

import numpy as np
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

import power_analysis
from power_analysis import (
    achieved_power,
    required_sample_size,
    analyze_power,
    main,
)


class TestAchievedPower:
    def test_zero_when_tiny_sample(self):
        assert achieved_power(0.5, 1) == 0.0

    def test_zero_effect(self):
        assert achieved_power(0.0, 100) == 0.0

    def test_power_increases_with_n(self):
        assert achieved_power(0.5, 100) > achieved_power(0.5, 10)

    def test_power_in_unit_interval(self):
        p = achieved_power(0.8, 50)
        assert 0.0 <= p <= 1.0


class TestRequiredSampleSize:
    def test_zero_effect_infinite(self):
        assert required_sample_size(0.0) == float("inf")

    def test_smaller_effect_needs_more(self):
        assert required_sample_size(0.2) > required_sample_size(0.8)

    def test_returns_int(self):
        assert isinstance(required_sample_size(0.5), int)


class TestAnalyzePower:
    def test_structure(self):
        rep = analyze_power(20)
        assert rep["n_per_group"] == 20
        assert set(rep["by_effect_size"]) == {"small", "medium", "large"}
        for r in rep["by_effect_size"].values():
            assert "required_n_per_group" in r
            assert "achieved_power_at_n" in r
            assert "adequately_powered" in r

    def test_custom_effect_sizes(self):
        rep = analyze_power(30, effect_sizes={"tiny": 0.1})
        assert list(rep["by_effect_size"]) == ["tiny"]

    def test_large_n_adequately_powered_for_medium(self):
        rep = analyze_power(500)
        assert rep["by_effect_size"]["medium"]["adequately_powered"] is True


class TestFallback:
    def test_normal_approx_matches_when_forced(self, monkeypatch):
        # Force the fallback path and confirm it returns sane values
        monkeypatch.setattr(power_analysis, "_HAVE_SM", False)
        assert 0.0 <= achieved_power(0.5, 40) <= 1.0
        assert required_sample_size(0.5) > 0


class TestMain:
    def test_main_writes_output(self, temp_dir, capsys):
        out = temp_dir / "power.json"
        rc = main(["--n", "20", "--out", str(out)])
        assert rc == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["n_per_group"] == 20
        captured = capsys.readouterr()
        assert "Power analysis" in captured.out

    def test_main_custom_params(self, temp_dir):
        out = temp_dir / "sub" / "power.json"
        rc = main(["--n", "64", "--alpha", "0.01", "--power", "0.9", "--out", str(out)])
        assert rc == 0
        assert out.exists()


class TestTheStatsmodelsPath:
    """The exact branch, which no environment in this project takes.

    statsmodels is not a dependency here and is not installed on the build machine or in CI,
    so every power number the project reports comes from the normal approximation. The exact
    branch is still live code for anyone who has statsmodels, and an untested live branch that
    only strangers execute is the worst kind: it fails on their machine, not ours.

    Two things are pinned. The plumbing -- that the right test is asked for, two-sided and
    balanced -- and, separately and more usefully, that the approximation we actually use
    agrees with the exact answer.
    """

    class FakeAnalysis:
        def __init__(self):
            self.power_calls = []
            self.solve_calls = []

        def power(self, **kw):
            self.power_calls.append(kw)
            return 0.9123456

        def solve_power(self, **kw):
            self.solve_calls.append(kw)
            return 33.2

    def _install(self, monkeypatch):
        fake = self.FakeAnalysis()
        monkeypatch.setattr(power_analysis, "_ANALYSIS", fake)
        monkeypatch.setattr(power_analysis, "_HAVE_SM", True)
        return fake

    def test_achieved_power_asks_for_a_balanced_two_sided_test(self, monkeypatch):
        fake = self._install(monkeypatch)
        assert power_analysis.achieved_power(0.5, 20, alpha=0.01) == pytest.approx(0.9123456)
        call = fake.power_calls[0]
        assert call == {"effect_size": 0.5, "nobs1": 20, "alpha": 0.01,
                        "ratio": 1.0, "alternative": "two-sided"}

    def test_required_sample_size_rounds_up_to_a_whole_subject(self, monkeypatch):
        """33.2 subjects per group is 34. Rounding down would under-power the design."""
        self._install(monkeypatch)
        n = power_analysis.required_sample_size(0.5)
        assert n == 34
        assert isinstance(n, int)

    def test_required_sample_size_uses_the_magnitude_of_the_effect(self, monkeypatch):
        """A negative d is the same design with the groups swapped, not an easier one."""
        fake = self._install(monkeypatch)
        power_analysis.required_sample_size(-0.5)
        assert fake.solve_calls[0]["effect_size"] == 0.5
        assert fake.solve_calls[0]["alternative"] == "two-sided"
        assert fake.solve_calls[0]["ratio"] == 1.0

    def test_the_short_circuits_run_before_the_backend_is_consulted(self, monkeypatch):
        fake = self._install(monkeypatch)
        assert power_analysis.achieved_power(0.0, 20) == 0.0
        assert power_analysis.achieved_power(0.5, 1) == 0.0
        assert power_analysis.required_sample_size(0.0) == float("inf")
        assert fake.power_calls == [] and fake.solve_calls == []

    def test_the_report_names_the_backend_it_used(self, monkeypatch):
        """Which engine produced a power number is part of the number."""
        assert power_analysis.analyze_power(20)["backend"] == "normal-approx"
        self._install(monkeypatch)
        assert power_analysis.analyze_power(20)["backend"] == "statsmodels"


class TestTheApproximationTheProjectActuallyUses:
    """Every power figure this project reports comes from the normal approximation.

    That makes its accuracy a property of the results, not an implementation detail. The exact
    two-sample t-test power is the survival function of a non-central t, which scipy has, so
    the comparison needs no extra dependency.
    """

    @staticmethod
    def _exact(d, n, alpha=0.05):
        from scipy import stats as st
        df = 2 * n - 2
        ncp = d * np.sqrt(n / 2.0)
        crit = st.t.ppf(1 - alpha / 2, df)
        return (st.nct.sf(crit, df, ncp) + st.nct.cdf(-crit, df, ncp))

    @pytest.mark.parametrize("d,n", [(0.2, 200), (0.5, 64), (0.8, 26), (0.5, 200), (1.2, 20)])
    def test_it_tracks_the_exact_non_central_t_closely(self, d, n):
        got = power_analysis.achieved_power(d, n)
        assert got == pytest.approx(self._exact(d, n), abs=0.02)

    def test_it_stays_honest_at_the_small_samples_this_project_runs(self, ):
        """The campaigns are tens of runs, not thousands, which is where a normal
        approximation is least comfortable; 5 points is the tolerable error there."""
        for n in (5, 8, 12, 20):
            got = power_analysis.achieved_power(0.8, n)
            assert got == pytest.approx(self._exact(0.8, n), abs=0.05)

    def test_the_required_sample_size_is_within_one_subject_of_the_conventional_answer(self):
        """d=0.5 at 80% power is 64 per group in every textbook."""
        assert abs(power_analysis.required_sample_size(0.5) - 64) <= 1

    def test_a_large_effect_needs_the_conventional_twenty_six(self):
        assert abs(power_analysis.required_sample_size(0.8) - 26) <= 1

    def test_power_at_the_solved_sample_size_lands_on_the_target(self):
        """The two functions must be inverses of each other, or one of them is wrong."""
        for d in (0.2, 0.5, 0.8):
            n = power_analysis.required_sample_size(d)
            assert power_analysis.achieved_power(d, n) == pytest.approx(0.8, abs=0.03)
