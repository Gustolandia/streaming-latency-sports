#!/usr/bin/env python3
"""
fit_two_state.py
Fit the load dependence of the inversion rate, and discriminate the candidate mechanisms.

docs/two_state_model.md states the two-state model in its simplified form

    P(inversion | rho) = p(rho) * S                                        (SIMPLE)

with S fixed, and offers no account of how the rate depends on load. It cannot: with p left
free, that form has NO CONTENT on the rho axis, because any monotone rate curve can be written
as p(rho)*S by setting p = rate/S. Its content is on the threshold axis, which is where
analyze_separability.py tests it and where it passed. Anyone reading the simplified equation as
a load model is reading a tautology, and this script exists partly to say so: the paper has
already withdrawn one functional form for being unfalsifiable and must not adopt another.

Given a parametric p (a power law in rho) the simple form does become testable, and it fits our
ladder poorly. But that is a statement about the parameterisation, not about two states.

The repair is identifiable rather than invented because it is forced by a result already in
hand. The separability test works on STANDARDISED thresholds z = c / sigma, so it had already
divided the sigma growth out before comparing conditions. Restoring it:

    an inversion is Delta < -T_true: the residual must exceed the true transport T_true.
    In standardised units that threshold is z = T_true / sigma(rho).
    sigma grows 5x across our ladder, so the threshold MOVES TOWARD ZERO as load rises.

    P(inversion | rho) = p(rho) * S( T_true / sigma(rho) )                 (CORRECTED)

Both factors rise with load, which is why the rate can grow faster than either alone. This is
the same two-moving-parameter structure that H10 supported and H9 (a one-parameter scale family)
rejected, so the correction is forced by results already in hand rather than chosen to fit.

WHAT THIS SCRIPT DOES NOT ESTABLISH. The fit is exploratory: six conditions, three free
parameters, and the functional form was chosen after seeing the data. It is also not a
like-for-like contest, and the output says so: the corrected model reads sigma and mu from each
condition, while `exp(k rho)` and `(rho/(1-rho))^k` are given rho alone. Winning on R^2 while
consuming two measured covariates the comparators never see is not evidence of being right. The
model earns its place only if the pre-registered prediction below survives new data, which is
why the prediction is emitted whether or not the fit succeeds.

CLI:
    python scripts/fit_two_state.py --conditions docs/results/model/collapse_conditions.csv \
        --out docs/results/model
"""
import argparse
import csv
import math
from pathlib import Path

import numpy as np

SATURATED_RHO = 0.999   # utilisation pinned at the ceiling: achieved rho is not resolved there
MIN_CONDITIONS = 4      # below this, three free parameters are not identifiable
SIGMA_CARRIES_RATIO = 2.0   # freezing sigma must at least double the residual to credit it


def load_conditions(path):
    """Read the condition ladder, dropping cells whose utilisation is pinned at saturation.

    Those cells are the reason the knee sweep exists: whole-core stressors drive measured
    utilisation to 1.000 regardless of the true offered load, so their rho carries no
    information and fitting on them would place several points at one abscissa.
    """
    rows, dropped = [], 0
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rec = {"condition": r["condition"], "rho": float(r["rho"]),
                       "inversion": float(r["inversion"]),
                       "sigma": float(r["sigma_core"]), "mu": float(r["mu"])}
            except (KeyError, ValueError, TypeError):
                continue
            if rec["rho"] < SATURATED_RHO and rec["inversion"] > 0 and rec["sigma"] > 0:
                rows.append(rec)
            else:
                dropped += 1
    rows.sort(key=lambda x: x["rho"])
    return rows, dropped


def r2_log(pred, obs):
    """R^2 in log space.

    The rates span sixty-fold, so a least-squares fit on raw values would be decided almost
    entirely by the single largest point and would report agreement that is not there at the
    bottom of the ladder.
    """
    pred = np.maximum(np.asarray(pred, dtype=float), 1e-12)
    lo = np.log(np.asarray(obs, dtype=float))
    denom = float(np.sum((lo - lo.mean()) ** 2))
    if denom <= 0:
        return float("nan")
    return float(1 - np.sum((lo - np.log(pred)) ** 2) / denom)


def sigma_ablation(rows):
    """Does the MEASURED sigma carry the load dependence, or is it along for the ride?

    This is the test that decides whether the corrected form has content, and it exists because
    the obvious argument against the simple form does not work. One might think a bounded p
    cannot supply the observed 35-fold growth. It can: the ceiling is 1/p(lo), and p(lo) is only
    bounded below by zero, so a steep enough p(rho) reaches any multiple. Worse, with p left
    free the simple form is not falsifiable on the rho axis at all -- ANY monotone rate curve
    can be written as p(rho)*S by defining p = rate/S. Its content lies on the threshold axis,
    which is where analyze_separability.py tests it.

    So the corrected form cannot earn its place by fitting better; it earns it only if the
    independently measured sigma is what makes it fit. Refit the same functional form with sigma
    frozen at its mean, leaving everything else free. If the frozen fit is as good, sigma is
    decorative and the correction is just extra freedom.

    The statistic is the RESIDUAL RATIO, not the R^2 gap. R^2 is the wrong scale here: p(rho)
    dominates the log variance, so even a sigma that matters cannot move R^2 by much, and a
    threshold on the gap would clear the model of a charge it was never tested on. The ratio
    (1 - r2_frozen) / (1 - r2_measured) asks the question directly -- by what factor does
    freezing sigma inflate the unexplained residual? Above 1 sigma is helping; below 1 the
    frozen model is actually the better one.

    Returns (r2_with_measured_sigma, r2_with_frozen_sigma, residual_ratio).
    """
    frozen = [dict(r, sigma=float(np.mean([x["sigma"] for x in rows]))) for r in rows]
    r2_m = fit_corrected(rows)["r2_log"]
    r2_f = fit_corrected(frozen)["r2_log"]
    denom = 1.0 - r2_m
    ratio = float("inf") if denom <= 0 else (1.0 - r2_f) / denom
    return r2_m, r2_f, ratio


def fit_corrected(rows):
    """P = (1-p)*C0 + p*S(mu/(a*sigma)), p = rho^C, S exponential. Grid search in log space."""
    rho = np.array([r["rho"] for r in rows])
    inv = np.array([r["inversion"] for r in rows])
    sig = np.array([r["sigma"] for r in rows])
    mu = np.array([r["mu"] for r in rows])
    best = (-np.inf, None)
    for C in np.arange(0.25, 12.01, 0.25):
        p = rho ** C
        for a in np.geomspace(0.05, 20.0, 80):
            S = np.exp(-mu / (a * sig))
            for C0 in np.geomspace(1e-4, 1e-2, 40):
                r2 = r2_log((1 - p) * C0 + p * S, inv)
                if r2 > best[0]:
                    best = (r2, {"C": float(C), "a": float(a), "C0": float(C0)})
    r2, par = best
    p = rho ** par["C"]
    S = np.exp(-mu / (par["a"] * sig))
    par.update({"r2_log": r2, "p": p.tolist(), "S": S.tolist(),
                "pred": ((1 - p) * par["C0"] + p * S).tolist()})
    return par


def fit_simple(rows):
    """The SIMPLE form: P = (1-p)*C0 + p*S with S a fixed constant. Same parameter count."""
    rho = np.array([r["rho"] for r in rows])
    inv = np.array([r["inversion"] for r in rows])
    best = (-np.inf, None)
    for C in np.arange(0.25, 12.01, 0.25):
        p = rho ** C
        for C0 in np.geomspace(1e-4, 2e-2, 60):
            num = inv - (1 - p) * C0
            if np.any(num <= 0):
                continue
            S = math.exp(float(np.mean(np.log(num) - np.log(np.maximum(p, 1e-12)))))
            if not 0 < S <= 1:
                continue
            r2 = r2_log((1 - p) * C0 + p * S, inv)
            if r2 > best[0]:
                best = (r2, {"C": float(C), "C0": float(C0), "S": S})
    if best[1] is None:
        return {"r2_log": float("nan"), "C": float("nan"), "C0": float("nan"), "S": float("nan")}
    best[1]["r2_log"] = best[0]
    return best[1]


def fit_comparator(rows, shape, k_grid):
    """floor + scale*shape(rho, k): the pure-rho curve fits, given rho and nothing else."""
    rho = np.array([r["rho"] for r in rows])
    inv = np.array([r["inversion"] for r in rows])
    best = (-np.inf, None)
    for k in k_grid:
        s = np.asarray(shape(rho, k), dtype=float)
        if not np.all(np.isfinite(s)) or np.any(s <= 0):
            continue
        for floor in np.geomspace(1e-4, 1e-2, 40):
            num = inv - floor
            if np.any(num <= 0):
                continue
            scale = math.exp(float(np.mean(np.log(num) - np.log(s))))
            r2 = r2_log(floor + scale * s, inv)
            if r2 > best[0]:
                best = (r2, {"k": float(k), "floor": float(floor), "scale": scale})
    if best[1] is None:
        return {"r2_log": float("nan"), "k": float("nan")}
    best[1]["r2_log"] = best[0]
    return best[1]


def predictions(rows, corrected, targets=(0.90, 0.95, 0.99)):
    """Pre-registered multipliers on the inversion rate, relative to the top resolved point.

    The corrected model needs sigma(rho), which is measured rather than modelled, so it is
    reported as a BRACKET rather than a point: the lower edge freezes sigma at its last measured
    value, the upper edge lets S saturate at 1. Quoting a single number would imply a
    extrapolation of sigma we have not earned.
    """
    rho = np.array([r["rho"] for r in rows])
    base = rows[-1]
    p_b = base["rho"] ** corrected["C"]
    S_b = math.exp(-base["mu"] / (corrected["a"] * base["sigma"]))
    denom = (1 - p_b) * corrected["C0"] + p_b * S_b
    mg1_b = base["rho"] / (1 - base["rho"])
    out = []
    for t in targets:
        p = t ** corrected["C"]
        lo = ((1 - p) * corrected["C0"] + p * S_b) / denom
        hi = ((1 - p) * corrected["C0"] + p * 1.0) / denom
        out.append({"rho": t, "two_state_lo": lo, "two_state_hi": hi,
                    "mg1": (t / (1 - t)) / mg1_b})
    return out, float(rho[-1])


def verdict(simple, corrected, comparators, sigma_carries=True):
    """Which structure survives, stated so that the corrected model can still lose.

    The ablation gates the conclusion: without measured sigma doing real work, a higher R^2 is
    just the reward for reading two more columns, and the model is not preferred.
    """
    best_cmp = max(comparators.items(), key=lambda kv: kv[1]["r2_log"])
    beats = corrected["r2_log"] > best_cmp[1]["r2_log"]
    return {
        "simple_parametric_worse": simple["r2_log"] < corrected["r2_log"] - 0.05,
        "sigma_carries": bool(sigma_carries),
        "corrected_beats_comparators": bool(beats),
        "corrected_preferred": bool(beats and sigma_carries),
        "best_comparator": best_cmp[0],
        "best_comparator_r2": best_cmp[1]["r2_log"],
        "margin": corrected["r2_log"] - best_cmp[1]["r2_log"],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conditions", default="docs/results/model/collapse_conditions.csv")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.conditions).exists():
        print(f"missing conditions file: {args.conditions}")
        return 1
    rows, dropped = load_conditions(args.conditions)
    print(f"loaded {len(rows)} resolved conditions ({dropped} dropped: rho pinned at saturation)")
    if len(rows) < MIN_CONDITIONS:
        print(f"insufficient conditions: need {MIN_CONDITIONS}, have {len(rows)}")
        return 1

    simple = fit_simple(rows)
    corrected = fit_corrected(rows)

    r2_meas, r2_frozen, ratio = sigma_ablation(rows)
    print("\n== ablation: is the measured sigma doing the work? ==")
    print(f"  same form, sigma measured per condition: {r2_meas:7.4f}")
    print(f"  same form, sigma frozen at its mean:     {r2_frozen:7.4f}")
    print(f"  residual inflation from freezing sigma:  {ratio:7.2f}x")
    sigma_carries = ratio > SIGMA_CARRIES_RATIO
    if sigma_carries:
        print("=> the independently measured sigma carries the load dependence;")
        print("   the correction is not merely extra freedom.")
    else:
        print("=> sigma is NOT separately identifiable here. On this ladder sigma rises")
        print("   monotonically with rho, so the two move together and no fit can credit")
        print("   one over the other. The corrected form's lead is extra freedom, not")
        print("   evidence. Breaking that collinearity needs an experiment, not a fit.")
    comparators = {
        "exp(k rho)": fit_comparator(rows, lambda r, k: np.exp(k * r),
                                     np.arange(0.5, 20.01, 0.25)),
        "(rho/(1-rho))^k": fit_comparator(rows, lambda r, k: (r / (1 - r)) ** k,
                                          np.arange(0.25, 6.01, 0.25)),
    }

    print("\n== fits (R^2 in log space, three free parameters each) ==")
    print(f"  two-state SIMPLE     P = (1-p)C0 + pS          {simple['r2_log']:7.4f}"
          f"   [p as rho^C; free p is untestable]")
    print(f"  two-state CORRECTED  P = (1-p)C0 + pS(mu/asig) {corrected['r2_log']:7.4f}"
          f"   [also reads sigma, mu]")
    for name, c in comparators.items():
        print(f"  comparator {name:20s}                {c['r2_log']:7.4f}   [reads rho only]")

    v = verdict(simple, corrected, comparators, sigma_carries)
    print("\n== verdict ==")
    if v["simple_parametric_worse"]:
        print("SIMPLE FORM, with p a power law in rho, fits materially worse.")
        print("  (With p unconstrained it is not testable on this axis at all.)")
    if v["corrected_preferred"]:
        print(f"CORRECTED FORM PREFERRED: leads by {v['margin']:.4f} R^2 over "
              f"{v['best_comparator']},")
        print("  and the ablation shows the measured sigma is what earns the lead.")
        print("  It still reads two covariates the comparators do not, and the form was")
        print("  chosen after seeing these data, so this is a reason to test it on new")
        print("  data, not a reason to believe it.")
    elif v["corrected_beats_comparators"]:
        print(f"CORRECTED FORM LEADS by {v['margin']:.4f} R^2 over {v['best_comparator']},")
        print("  but the ablation says sigma is not carrying it, so the lead is extra")
        print("  freedom rather than mechanism. Not preferred.")
    else:
        print(f"CORRECTED FORM DOES NOT LEAD: {v['best_comparator']} fits as well or better")

    preds, base_rho = predictions(rows, corrected)
    print(f"\n== PRE-REGISTERED prediction for the knee sweep (base rho = {base_rho:.4f}) ==")
    print("multiplier on the inversion rate relative to that point:")
    for p in preds:
        print(f"  rho={p['rho']:.2f}   two-state x{p['two_state_lo']:5.2f}-{p['two_state_hi']:.2f}"
              f"   M/G/1 x{p['mg1']:7.2f}")
    print("\nThe two-state rate is bounded (P <= 1) and must bend over; M/G/1 diverges.")
    print("Note the honest limit of this test: the two-state bracket and exp(k rho) largely")
    print("overlap, so the knee data can separate M/G/1 from both, but not those two from")
    print("each other. What the two-state model adds there is a mechanism for why an")
    print("exponential fits at all, not a better curve.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "two_state_fit.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "r2_log", "params", "covariates"])
        w.writerow(["two_state_simple", f"{simple['r2_log']:.4f}",
                    f"C={simple['C']:.2f};C0={simple['C0']:.5f};S={simple['S']:.4f}", "rho"])
        w.writerow(["two_state_corrected", f"{corrected['r2_log']:.4f}",
                    f"C={corrected['C']:.2f};a={corrected['a']:.3f};C0={corrected['C0']:.5f}",
                    "rho;sigma;mu"])
        for name, c in comparators.items():
            w.writerow([name, f"{c['r2_log']:.4f}", f"k={c['k']:.2f}", "rho"])
    with (out / "two_state_prediction.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rho", "two_state_lo", "two_state_hi", "mg1"])
        w.writeheader()
        for p in preds:
            w.writerow({k: (f"{p[k]:.4f}" if k != "rho" else f"{p[k]:.2f}") for k in p})
    print(f"\nwrote {out/'two_state_fit.csv'} and {out/'two_state_prediction.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
