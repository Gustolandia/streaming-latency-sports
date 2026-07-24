"""Tests for scripts/measurement_model.py - target 100% branch coverage."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from measurement_model import (  # noqa: E402
    recover_delta_quantiles,
    monotone_decreasing,
    spearman,
    mg1_waiting,
    fit_mg1,
    runs_test_z,
    check_h1,
    check_h2,
    _load,
    main,
)


class TestSpearman:
    def test_perfect_positive(self):
        assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)

    def test_perfect_negative(self):
        assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_is_rank_based_not_linear(self):
        """A monotone but wildly non-linear relation still gives 1."""
        assert spearman([1, 2, 3, 4], [1, 10, 1000, 100000]) == pytest.approx(1.0)

    def test_handles_ties_by_averaging_ranks(self):
        assert -1.0 <= spearman([1, 2, 2, 3], [1, 2, 2, 3]) <= 1.0

    @pytest.mark.parametrize("x,y", [
        ([1], [1]),                    # too few points
        ([1, 1, 1], [1, 2, 3]),        # constant x
        ([1, 2, 3], [5, 5, 5]),        # constant y
    ])
    def test_degenerate_is_nan(self, x, y):
        assert np.isnan(spearman(x, y))


class TestMonotoneDecreasing:
    def test_strictly_decreasing(self):
        assert monotone_decreasing([0.5, 0.3, 0.1])

    def test_increasing_is_rejected(self):
        assert not monotone_decreasing([0.1, 0.3])

    def test_tolerance_absorbs_noise(self):
        assert monotone_decreasing([0.30, 0.31], tolerance=0.02)
        assert not monotone_decreasing([0.30, 0.40], tolerance=0.02)

    def test_single_point_is_trivially_monotone(self):
        assert monotone_decreasing([0.5])


class TestMg1Waiting:
    def test_grows_without_bound_towards_saturation(self):
        w = mg1_waiting([0.1, 0.5, 0.9, 0.99])
        assert list(w) == sorted(w)
        assert w[-1] > 10 * w[0]

    def test_saturation_is_infinite(self):
        assert np.isinf(mg1_waiting([1.0])[0])
        assert np.isinf(mg1_waiting([1.5])[0])

    def test_scale_is_linear(self):
        assert mg1_waiting([0.5], scale=2.0)[0] == pytest.approx(2 * mg1_waiting([0.5])[0])


class TestFitMg1:
    def test_recognises_its_own_shape(self):
        rho = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        y = 0.01 * mg1_waiting(rho)
        fit = fit_mg1(rho, y)
        assert fit["mg1_better"]
        assert fit["r2_mg1"] > 0.99
        assert fit["scale"] == pytest.approx(0.01, rel=1e-6)

    def test_prefers_linear_when_the_data_is_linear(self):
        rho = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        fit = fit_mg1(rho, 0.5 * rho)
        assert not fit["mg1_better"]

    def test_too_few_usable_points(self):
        fit = fit_mg1([0.5, 0.6], [0.1, 0.2])
        assert np.isnan(fit["scale"]) and not fit["mg1_better"]

    def test_saturated_points_are_excluded(self):
        """rho >= 1 gives infinite predicted waiting and cannot be fitted."""
        fit = fit_mg1([1.0, 1.2], [0.5, 0.6])
        assert not fit["mg1_better"]


class TestH1:
    def _frame(self, rates):
        return pd.DataFrame({"t_true_ms": [0.2, 1.0, 5.0, 20.0, 50.0], "inversion_rate": rates})

    def test_supported_when_inversions_fall_with_effect_size(self):
        r = check_h1(self._frame([0.60, 0.35, 0.10, 0.01, 0.00]))
        assert r["supported"] and r["monotone_decreasing"]
        assert r["spearman"] < 0

    def test_not_supported_when_flat(self):
        r = check_h1(self._frame([0.2] * 5))
        assert not r["supported"]

    def test_not_supported_when_rising(self):
        r = check_h1(self._frame([0.0, 0.1, 0.2, 0.3, 0.4]))
        assert not r["supported"]

    def test_too_few_points_is_not_supported(self):
        df = pd.DataFrame({"t_true_ms": [1.0, 2.0], "inversion_rate": [0.5, 0.1]})
        assert not check_h1(df)["supported"]


class TestH2:
    def test_supported_for_a_queueing_shaped_curve(self):
        rho = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        df = pd.DataFrame({"rho": rho, "inversion_rate": 0.02 * mg1_waiting(rho)})
        r = check_h2(df)
        assert r["supported"] and r["mg1_better"] and r["spearman"] > 0

    def test_not_supported_for_a_linear_curve(self):
        rho = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        assert not check_h2(pd.DataFrame({"rho": rho, "inversion_rate": 0.5 * rho}))["supported"]


class TestRecoverDeltaQuantiles:
    def test_reads_the_cdf_off_the_inversion_rates(self):
        out = recover_delta_quantiles([5.0, 0.2, 1.0], [0.10, 0.60, 0.35])
        assert list(out["t_true_ms"]) == [0.2, 1.0, 5.0], "must be sorted by T_true"
        assert list(out["delta_exceeds_t_prob"]) == [0.60, 0.35, 0.10]


class TestRunsTestZ:
    """H8: inversions cluster in time (z << 0), the signature of a shared descheduling event."""

    def test_perfectly_clustered_is_strongly_negative(self):
        # all inversions first, then all non-inversions: the fewest possible runs
        signs = [-1] * 20 + [1] * 20
        z = runs_test_z(signs)
        assert z is not None and z < -5

    def test_alternating_is_strongly_positive(self):
        signs = [-1, 1] * 20                            # the most possible runs
        assert runs_test_z(signs) > 5

    def test_independent_is_near_zero(self):
        rng = np.random.default_rng(0)
        signs = [1 if x > 0.5 else -1 for x in rng.random(2000)]
        z = runs_test_z(signs)
        assert abs(z) < 3, "an i.i.d. sequence should not look clustered"

    def test_zeros_count_as_inversions(self):
        # zero transport is not a positive value, so it is on the inversion side
        assert runs_test_z([0, 0, 1, 1]) is not None

    def test_none_when_a_class_is_too_small(self):
        assert runs_test_z([1, 1, 1, 1, -1]) is None   # only one inversion
        assert runs_test_z([]) is None


class TestLoad:
    def test_missing_path_is_none(self, temp_dir):
        assert _load(temp_dir / "nope.csv") is None

    def test_none_path_is_none(self):
        assert _load(None) is None

    def test_existing_file_loads(self, temp_dir):
        p = temp_dir / "x.csv"
        pd.DataFrame({"a": [1]}).to_csv(p, index=False)
        assert len(_load(p)) == 1


class TestMain:
    def _eb(self, tmp):
        p = tmp / "eb.csv"
        pd.DataFrame({"t_true_ms": [0.2, 1.0, 5.0, 20.0, 50.0],
                      "inversion_rate": [0.6, 0.35, 0.1, 0.01, 0.0]}).to_csv(p, index=False)
        return p

    def _ea(self, tmp):
        rho = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
        p = tmp / "ea.csv"
        pd.DataFrame({"rho": rho, "inversion_rate": 0.02 * mg1_waiting(rho)}).to_csv(p, index=False)
        return p

    def test_both_hypotheses(self, temp_dir, capsys):
        rc = main(["--effect-size-csv", str(self._eb(temp_dir)),
                   "--utilisation-csv", str(self._ea(temp_dir)),
                   "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "H1 effect-size rule: SUPPORTED" in out
        assert "H2 utilisation rule: SUPPORTED" in out
        assert "R^2 M/G/1" in out
        saved = json.loads((temp_dir / "model" / "model_fit.json").read_text())
        assert "recovered_delta_cdf" in saved and len(saved["recovered_delta_cdf"]) == 5

    def test_effect_size_only(self, temp_dir, capsys):
        assert main(["--effect-size-csv", str(self._eb(temp_dir)),
                     "--out", str(temp_dir / "m")]) == 0
        out = capsys.readouterr().out
        assert "H1" in out and "H2" not in out

    def test_utilisation_only(self, temp_dir, capsys):
        assert main(["--utilisation-csv", str(self._ea(temp_dir)),
                     "--out", str(temp_dir / "m")]) == 0
        assert "H2" in capsys.readouterr().out

    def test_no_inputs(self, temp_dir, capsys):
        assert main(["--out", str(temp_dir / "m")]) == 1
        assert "nothing to fit" in capsys.readouterr().out

    def test_reports_an_unsupported_hypothesis_honestly(self, temp_dir, capsys):
        p = temp_dir / "flat.csv"
        pd.DataFrame({"t_true_ms": [0.2, 1.0, 5.0],
                      "inversion_rate": [0.2, 0.2, 0.2]}).to_csv(p, index=False)
        assert main(["--effect-size-csv", str(p), "--out", str(temp_dir / "m")]) == 0
        assert "NOT SUPPORTED" in capsys.readouterr().out
