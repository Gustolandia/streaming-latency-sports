"""Tests for scripts/fit_two_state.py - target >=95% branch coverage.

This script decides between mechanisms, so the tests that matter are the ones that can make it
report the wrong winner. Data is synthesised from each model's defining equation, so a fit that
merely looks agreeable cannot pass: the corrected-form test builds data from the corrected form
and the comparator test builds data from an exponential, and each must be recognised.
"""
import csv
import math
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from fit_two_state import (  # noqa: E402
    load_conditions,
    r2_log,
    sigma_ablation,
    fit_corrected,
    fit_simple,
    fit_comparator,
    predictions,
    verdict,
    main,
)

FIELDS = ["condition", "rho", "n_events", "n_runs", "mu", "sigma_core", "inversion",
          "runs_z_median"]


def _write(tmp, rows, name="collapse_conditions.csv"):
    """Serialise loaded-shape rows back to the on-disk column names."""
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            out = {f: 0 for f in FIELDS}
            out.update({"condition": r["condition"], "rho": r["rho"], "mu": r["mu"],
                        "sigma_core": r["sigma"], "inversion": r["inversion"],
                        "n_events": 2985, "n_runs": 25, "runs_z_median": -5.0})
            w.writerow(out)
    return p


def _row(rho, inv, sigma=0.2, mu=0.6, cond="c"):
    """A row in the shape load_conditions() returns, which is what the fit functions take."""
    return {"condition": cond, "rho": rho, "inversion": inv, "sigma": sigma, "mu": mu}


def _corrected_ladder(C=7.5, a=5.9, C0=0.004, n=7):
    """Data generated FROM the corrected model, with sigma growing as load rises."""
    rows = []
    for rho in np.linspace(0.05, 0.93, n):
        sigma = 0.12 * (1 + 6 * rho ** 6)      # the sigma growth the correction relies on
        mu = 0.55
        p = rho ** C
        inv = (1 - p) * C0 + p * math.exp(-mu / (a * sigma))
        rows.append(_row(round(float(rho), 4), float(inv), round(float(sigma), 4), mu))
    return rows


class TestLoadConditions:
    def test_drops_saturated_cells(self, temp_dir):
        rows = [_row(0.5, 0.01), _row(1.0, 0.3), _row(0.9, 0.2)]
        got, dropped = load_conditions(str(_write(temp_dir, rows)))
        assert dropped == 1 and all(r["rho"] < 0.999 for r in got)

    def test_sorted_by_rho(self, temp_dir):
        got, _ = load_conditions(str(_write(temp_dir, [_row(0.9, 0.2), _row(0.1, 0.01)])))
        assert [r["rho"] for r in got] == [0.1, 0.9]

    def test_drops_zero_inversion_and_zero_sigma(self, temp_dir):
        rows = [_row(0.5, 0.0), _row(0.6, 0.02, sigma=0.0), _row(0.7, 0.05)]
        got, dropped = load_conditions(str(_write(temp_dir, rows)))
        assert dropped == 2 and len(got) == 1

    def test_malformed_rows_skipped(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_text(",".join(FIELDS) + "\nc,notanumber,1,1,x,y,z,0\n", encoding="utf-8")
        got, _ = load_conditions(str(p))
        assert got == []

    def test_missing_column_skipped(self, temp_dir):
        p = temp_dir / "short.csv"
        p.write_text("condition,rho\nc,0.5\n", encoding="utf-8")
        assert load_conditions(str(p))[0] == []


class TestR2Log:
    def test_perfect_fit_is_one(self):
        obs = [0.01, 0.05, 0.2]
        assert r2_log(obs, obs) == pytest.approx(1.0)

    def test_degenerate_observations_give_nan(self):
        """All-equal observations have zero log variance; R^2 is undefined, not 1."""
        assert math.isnan(r2_log([0.1, 0.1], [0.1, 0.1]))

    def test_worse_than_mean_is_negative(self):
        assert r2_log([1.0, 1.0, 1.0], [0.01, 0.05, 0.2]) < 0

    def test_nonpositive_predictions_are_clamped_not_crashed(self):
        assert math.isfinite(r2_log([0.0, 0.05, 0.2], [0.01, 0.05, 0.2]))


class TestSigmaAblation:
    """The ablation exists to detect an identifiability trap, so it is tested on both sides.

    On our real ladder sigma rises monotonically with rho. When two regressors move together,
    no fit can attribute the effect to one of them, and the corrected form's apparent lead over
    exp(k rho) is not evidence for the mechanism. The ablation must SAY so rather than reward
    the extra columns -- and it must still detect sigma when sigma genuinely varies on its own.
    """

    def test_detects_sigma_when_it_moves_independently_of_rho(self):
        """sigma oscillating against rho: the two are now separable and freezing it must cost.

        Sixteen points, not six: with three free parameters a six-point fit can very nearly
        interpolate any smooth curve, so the frozen model scores well whatever sigma does. That
        is a power limit of the ablation, and it applies to the real six-condition ladder too.
        """
        C, a, C0 = 4.0, 5.9, 0.004
        rows = []
        for i, rho in enumerate(np.linspace(0.2, 0.93, 16)):
            sg = 0.5 if i % 2 == 0 else 0.15      # alternating, so no function of rho tracks it
            p = float(rho) ** C
            rows.append(_row(round(float(rho), 4),
                             (1 - p) * C0 + p * math.exp(-0.55 / (a * sg)), sg, 0.55))
        _, _, ratio = sigma_ablation(rows)
        assert ratio > 2.0, "an independently varying sigma must be detectable"

    def test_reports_no_gain_when_sigma_is_collinear_with_rho(self):
        """The real ladder: sigma rises with rho, so it cannot be credited separately.

        These are the measured values from docs/results/model/collapse_conditions.csv. Freezing
        sigma FITS BETTER here (ratio below 1), which is the finding this script exists to
        report -- the corrected form's higher R^2 is bought with columns, not mechanism.
        """
        rows = [_row(0.0025, 0.00369, 0.1255, 0.5239), _row(0.2525, 0.00402, 0.1377, 0.5373),
                _row(0.5037, 0.00637, 0.1795, 0.6782), _row(0.6284, 0.02446, 0.1813, 0.6634),
                _row(0.7531, 0.07638, 0.2384, 0.7265), _row(0.8775, 0.22379, 0.6314, 0.8392)]
        _, _, ratio = sigma_ablation(rows)
        assert ratio < 1.0

    def test_sigma_is_decorative_when_it_never_varied(self):
        """Constant sigma cannot carry anything, so the ablation must report no loss."""
        rows = [_row(r, 0.004 + 0.00003 * math.exp(10.25 * r), sigma=0.2)
                for r in (0.1, 0.3, 0.5, 0.63, 0.75, 0.88)]
        meas, frozen, ratio = sigma_ablation(rows)
        assert meas == pytest.approx(frozen) and ratio == pytest.approx(1.0)


class TestFits:
    def test_simple_form_can_track_fast_growth_when_unanchored(self):
        """A steep power-law p reaches any multiple, so 35x growth alone does NOT refute it.

        This is the test that killed the first version of this script, which claimed a bounded
        p could not supply 35x. It can: the ceiling is 1/p(lo) and p(lo) may be tiny. The simple
        form only fails once the low-load floor anchors the bottom of the ladder.
        """
        rows = [_row(0.50, 0.0064), _row(0.63, 0.0245), _row(0.75, 0.0764), _row(0.88, 0.2238)]
        assert fit_simple(rows)["r2_log"] > 0.99

    def test_simple_form_fails_once_the_floor_anchors_the_bottom(self):
        rows = [_row(0.0025, 0.00369), _row(0.2525, 0.00402), _row(0.50, 0.0064),
                _row(0.63, 0.0245), _row(0.75, 0.0764), _row(0.88, 0.2238)]
        assert fit_simple(rows)["r2_log"] < 0.9

    def test_simple_form_fits_when_growth_is_within_reach(self):
        C, C0, S = 3.0, 0.004, 0.5
        rows = [_row(r, (1 - r ** C) * C0 + r ** C * S)
                for r in (0.2, 0.4, 0.6, 0.75, 0.88)]
        assert fit_simple(rows)["r2_log"] > 0.95

    def test_simple_returns_nan_when_no_parameterisation_is_feasible(self):
        """Every candidate S exceeds 1 here, so the fit must report failure, not a number."""
        rows = [_row(r, 0.999) for r in (0.05, 0.1, 0.15, 0.2)]
        assert math.isnan(fit_simple(rows)["r2_log"])

    def test_corrected_form_recovers_data_built_from_it(self):
        assert fit_corrected(_corrected_ladder())["r2_log"] > 0.98

    def test_corrected_fit_exposes_both_factors(self):
        f = fit_corrected(_corrected_ladder())
        assert len(f["p"]) == len(f["S"]) == len(f["pred"])
        assert f["p"][-1] > f["p"][0] and f["S"][-1] > f["S"][0], "both factors rise with load"

    def test_comparator_recovers_an_exponential(self):
        rows = [_row(r, 0.004 + 0.00003 * math.exp(10.25 * r))
                for r in (0.1, 0.3, 0.5, 0.63, 0.75, 0.88)]
        assert fit_comparator(rows, lambda x, k: np.exp(k * x),
                             np.arange(0.5, 20.01, 0.25))["r2_log"] > 0.99

    def test_comparator_reports_failure_when_no_floor_fits(self):
        """Every observation below the smallest floor leaves no admissible parameterisation."""
        rows = [_row(r, 1e-6) for r in (0.2, 0.5, 0.8)]
        assert math.isnan(fit_comparator(rows, lambda x, k: np.exp(k * x),
                                         np.arange(0.5, 5.01, 0.5))["r2_log"])

    def test_comparator_skips_nonfinite_shapes(self):
        """(rho/(1-rho))^k is infinite at rho=1; those k must be skipped, not fitted."""
        rows = [_row(r, 0.004 + 0.01 * (r / (1 - r))) for r in (0.2, 0.5, 0.75, 0.9)]
        out = fit_comparator(rows, lambda x, k: (x / (1 - x)) ** k, np.arange(0.25, 3.01, 0.25))
        assert math.isfinite(out["r2_log"])


class TestPredictions:
    def test_bracket_contains_the_frozen_sigma_case(self):
        rows = _corrected_ladder()
        preds, base = predictions(rows, fit_corrected(rows))
        assert base == rows[-1]["rho"]
        for p in preds:
            assert p["two_state_lo"] <= p["two_state_hi"]

    def test_mg1_diverges_faster_than_two_state(self):
        rows = _corrected_ladder()
        preds, _ = predictions(rows, fit_corrected(rows))
        top = [p for p in preds if p["rho"] == 0.99][0]
        assert top["mg1"] > top["two_state_hi"], "the discriminating gap must exist at rho=0.99"


class TestVerdict:
    def test_prefers_corrected_when_it_leads_and_sigma_carries(self):
        v = verdict({"r2_log": 0.65}, {"r2_log": 0.99},
                    {"exp": {"r2_log": 0.98}, "mg1": {"r2_log": 0.88}}, sigma_carries=True)
        assert v["simple_parametric_worse"] and v["corrected_preferred"]
        assert v["best_comparator"] == "exp"

    def test_leading_is_not_enough_without_sigma(self):
        """A higher R^2 bought with two extra covariates must not count as a win."""
        v = verdict({"r2_log": 0.65}, {"r2_log": 0.99}, {"exp": {"r2_log": 0.98}},
                    sigma_carries=False)
        assert v["corrected_beats_comparators"] and not v["corrected_preferred"]

    def test_corrected_can_lose(self):
        """The verdict must be able to go against the model the script is named for."""
        v = verdict({"r2_log": 0.90}, {"r2_log": 0.91}, {"exp": {"r2_log": 0.99}})
        assert not v["corrected_beats_comparators"] and not v["simple_parametric_worse"]
        assert v["margin"] < 0


class TestMain:
    def test_end_to_end_on_corrected_data(self, temp_dir, capsys):
        p = _write(temp_dir, _corrected_ladder())
        assert main(["--conditions", str(p), "--out", str(temp_dir / "o")]) == 0
        out = capsys.readouterr().out
        assert "PRE-REGISTERED prediction" in out
        models = {r["model"] for r in csv.DictReader(open(temp_dir / "o" / "two_state_fit.csv"))}
        assert {"two_state_simple", "two_state_corrected"} <= models
        preds = list(csv.DictReader(open(temp_dir / "o" / "two_state_prediction.csv")))
        assert [r["rho"] for r in preds] == ["0.90", "0.95", "0.99"]

    def test_reports_structural_failure_of_the_simple_form(self, temp_dir, capsys):
        rows = [_row(0.05, 0.0037), _row(0.25, 0.0040), _row(0.50, 0.0064, 0.18),
                _row(0.63, 0.0245, 0.18), _row(0.75, 0.0764, 0.24), _row(0.88, 0.2238, 0.63)]
        main(["--conditions", str(_write(temp_dir, rows)), "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert "NOT separately identifiable" in out
        assert "fits materially worse" in out

    def test_reports_when_the_corrected_form_does_not_lead(self, temp_dir, capsys):
        """Data built from a pure exponential in rho, with sigma held constant so the
        correction has nothing to work with. The script must concede."""
        rows = [_row(r, 0.004 + 0.00003 * math.exp(10.25 * r), sigma=0.2)
                for r in (0.1, 0.3, 0.5, 0.63, 0.75, 0.88)]
        main(["--conditions", str(_write(temp_dir, rows)), "--out", str(temp_dir / "o")])
        assert "CORRECTED FORM DOES NOT LEAD" in capsys.readouterr().out

    def test_missing_file(self, temp_dir, capsys):
        assert main(["--conditions", str(temp_dir / "nope.csv")]) == 1
        assert "missing conditions file" in capsys.readouterr().out

    def test_too_few_conditions(self, temp_dir, capsys):
        p = _write(temp_dir, [_row(0.5, 0.01), _row(0.8, 0.05)])
        assert main(["--conditions", str(p), "--out", str(temp_dir / "o")]) == 1
        assert "insufficient conditions" in capsys.readouterr().out
