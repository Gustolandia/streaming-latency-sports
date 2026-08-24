"""Tests for scripts/check_knee_prediction.py - target >=95% branch coverage.

This scores a prediction the paper has a stake in, so the tests are built around the ways it
could flatter that prediction: data generated from each competing model must produce the verdict
belonging to THAT model, and the case where both fail must be reachable.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_knee_prediction import (  # noqa: E402
    load_prediction,
    load_observed,
    pick_base,
    score,
    verdict,
    main,
)

# The values fit_two_state.py committed before the sweep ran.
PRED = [{"rho": 0.90, "two_state_lo": 1.21, "two_state_hi": 1.51, "mg1": 1.26},
        {"rho": 0.95, "two_state_lo": 1.80, "two_state_hi": 2.25, "mg1": 2.65},
        {"rho": 0.99, "two_state_lo": 2.45, "two_state_hi": 3.07, "mg1": 13.82}]


def _write_pred(tmp, rows=None, name="pred.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rho", "two_state_lo", "two_state_hi", "mg1"])
        w.writeheader()
        w.writerows(rows if rows is not None else PRED)
    return p


def _write_obs(tmp, rows, name="obs.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["condition", "rho", "inversion"])
        w.writeheader()
        for rho, inv in rows:
            w.writerow({"condition": f"l{int(rho*100)}", "rho": rho, "inversion": inv})
    return p


def _obs_from(multipliers, base_inv=0.224):
    """Observed ladder with a base near 0.88 and the given multipliers at 0.90/0.95/0.99."""
    out = [(0.8812, base_inv)]
    for rho, m in zip((0.9204, 0.9501, 0.9900), multipliers):
        out.append((rho, base_inv * m))
    return out


class TestLoading:
    def test_prediction_rows_are_sorted(self, temp_dir):
        rows = load_prediction(str(_write_pred(temp_dir, list(reversed(PRED)))))
        assert [r["rho"] for r in rows] == [0.90, 0.95, 0.99]

    def test_malformed_prediction_rows_skipped(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_text("rho,two_state_lo,two_state_hi,mg1\nx,y,z,w\n", encoding="utf-8")
        assert load_prediction(str(p)) == []

    def test_observed_drops_saturated_and_empty_cells(self, temp_dir):
        p = _write_obs(temp_dir, [(0.88, 0.22), (1.0, 0.31), (0.95, 0.0), (0.92, 0.26)])
        rows = load_observed(str(p))
        assert [r["rho"] for r in rows] == [0.88, 0.92]

    def test_malformed_observed_rows_skipped(self, temp_dir):
        p = temp_dir / "bad2.csv"
        p.write_text("condition,rho,inversion\na,notanumber,0.2\n", encoding="utf-8")
        assert load_observed(str(p)) == []


class TestPickBase:
    def test_chooses_the_condition_nearest_the_anchor(self):
        obs = [{"rho": 0.75, "inversion": 0.07}, {"rho": 0.8812, "inversion": 0.22},
               {"rho": 0.95, "inversion": 0.4}]
        assert pick_base(obs)["rho"] == 0.8812

    def test_empty_input_gives_none(self):
        assert pick_base([]) is None


class TestScore:
    def test_marks_conditions_the_sweep_never_reached(self, temp_dir):
        """0.9204 is within tolerance of the 0.90 prediction; 0.95 and 0.99 are not reached."""
        pred = load_prediction(str(_write_pred(temp_dir)))
        obs = load_observed(str(_write_obs(temp_dir, [(0.8812, 0.22), (0.9204, 0.28)])))
        rows = score(pred, obs, pick_base(obs))
        assert rows[0]["reached"] and not rows[1]["reached"] and not rows[2]["reached"]
        assert rows[0]["observed_rho"] == 0.9204, "it must report the rho actually measured"

    def test_a_sweep_with_only_the_base_reaches_nothing(self, temp_dir):
        """Excluding the base can empty the candidate set; that must not divide by nothing."""
        pred = load_prediction(str(_write_pred(temp_dir)))
        obs = load_observed(str(_write_obs(temp_dir, [(0.8812, 0.22)])))
        rows = score(pred, obs, pick_base(obs))
        assert all(not r["reached"] for r in rows)
        assert not verdict(rows)["decided"]

    def test_multiplier_is_relative_to_the_base(self, temp_dir):
        pred = load_prediction(str(_write_pred(temp_dir)))
        obs = load_observed(str(_write_obs(temp_dir, _obs_from([1.3, 2.0, 2.8]))))
        rows = score(pred, obs, pick_base(obs))
        assert rows[0]["observed_mult"] == pytest.approx(1.3, rel=1e-6)
        assert all(r["in_two_state"] for r in rows)


class TestVerdict:
    def _v(self, temp_dir, multipliers):
        pred = load_prediction(str(_write_pred(temp_dir)))
        obs = load_observed(str(_write_obs(temp_dir, _obs_from(multipliers))))
        return verdict(score(pred, obs, pick_base(obs)))

    def test_bounded_growth_supports_two_state_and_refutes_mg1(self, temp_dir):
        v = self._v(temp_dir, [1.3, 2.0, 2.8])
        assert v["two_state_held"] and not v["mg1_held"]

    def test_divergent_growth_supports_mg1_and_refutes_two_state(self, temp_dir):
        """Data built from rho/(1-rho) must produce the verdict against our own model."""
        v = self._v(temp_dir, [1.26, 2.65, 13.82])
        assert v["mg1_held"] and not v["two_state_held"]

    def test_neither_holding_is_reachable(self, temp_dir):
        v = self._v(temp_dir, [6.0, 7.0, 8.0])
        assert not v["two_state_held"] and not v["mg1_held"] and v["decided"]

    def test_undecided_when_nothing_was_reached(self, temp_dir):
        pred = load_prediction(str(_write_pred(temp_dir)))
        obs = load_observed(str(_write_obs(temp_dir, [(0.70, 0.07), (0.80, 0.10)])))
        assert not verdict(score(pred, obs, pick_base(obs)))["decided"]


class TestMain:
    def _run(self, temp_dir, capsys, multipliers, obs=None):
        p = _write_pred(temp_dir)
        o = _write_obs(temp_dir, obs if obs is not None else _obs_from(multipliers))
        rc = main(["--prediction", str(p), "--observed", str(o), "--out", str(temp_dir / "o")])
        return rc, capsys.readouterr().out

    def test_reports_the_bounded_prediction_holding(self, temp_dir, capsys):
        rc, out = self._run(temp_dir, capsys, [1.3, 2.0, 2.8])
        assert rc == 0
        assert "bounded prediction held" in out
        assert "does NOT separate the two-state account from a fitted exponential" in out
        rows = list(csv.DictReader(open(temp_dir / "o" / "knee_prediction_check.csv")))
        assert len(rows) == 3 and rows[0]["in_two_state"] == "True"

    def test_reports_our_own_model_being_contradicted(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, [1.26, 2.65, 13.82])
        assert "must be withdrawn there" in out

    def test_reports_both_failing(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, [6.0, 7.0, 8.0])
        assert "NEITHER prediction held" in out

    def test_reports_both_surviving(self, temp_dir, capsys):
        """The bands overlap at rho=0.90 (two-state 1.21-1.51, M/G/1 1.26), so one condition
        there satisfies both and the script must concede rather than pick a winner."""
        obs = [(0.8812, 0.224), (0.9204, 0.224 * 1.30)]
        _, out = self._run(temp_dir, capsys, None, obs=obs)
        assert "did not separate them" in out

    def test_warns_when_the_base_is_re_anchored(self, temp_dir, capsys):
        obs = [(0.70, 0.07), (0.9204, 0.28), (0.9501, 0.4), (0.99, 0.5)]
        _, out = self._run(temp_dir, capsys, None, obs=obs)
        assert "re-anchored" in out

    def test_notes_conditions_not_reached(self, temp_dir, capsys):
        obs = [(0.8812, 0.224), (0.9204, 0.29)]
        _, out = self._run(temp_dir, capsys, None, obs=obs)
        assert "not reached" in out

    def test_missing_prediction_file(self, temp_dir, capsys):
        o = _write_obs(temp_dir, [(0.88, 0.2)])
        assert main(["--prediction", str(temp_dir / "no.csv"), "--observed", str(o)]) == 1
        assert "missing input" in capsys.readouterr().out

    def test_missing_observed_file(self, temp_dir, capsys):
        p = _write_pred(temp_dir)
        assert main(["--prediction", str(p), "--observed", str(temp_dir / "no.csv")]) == 1
        assert "missing input" in capsys.readouterr().out

    def test_empty_usable_rows(self, temp_dir, capsys):
        p = _write_pred(temp_dir)
        o = _write_obs(temp_dir, [(1.0, 0.3)])
        assert main(["--prediction", str(p), "--observed", str(o),
                     "--out", str(temp_dir / "o")]) == 1
        assert "no usable rows" in capsys.readouterr().out


class TestASweepThatReachedNoPredictedCondition:

    def test_it_is_undecided_rather_than_scored_on_nothing(self, temp_dir, capsys):
        """Both predictions can be scored only where the sweep actually went.

        A ladder that stopped below the first predicted utilisation supports neither model,
        and a verdict computed over zero conditions would report 0/0 as a comparison.
        """
        obs = _write_obs(temp_dir, [(0.20, 0.01), (0.30, 0.02)])
        assert main(["--prediction", str(_write_pred(temp_dir)),
                     "--observed", str(obs),
                     "--out", str(temp_dir / "o")]) in (0, 1)
        out = capsys.readouterr().out
        assert "UNDECIDED" in out
        assert "reached none of the predicted conditions" in out
