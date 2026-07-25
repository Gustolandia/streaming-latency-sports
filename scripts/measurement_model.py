#!/usr/bin/env python3
"""
measurement_model.py
Fit and test the model of cross-process latency measurement failure (see
docs/measurement_model.md).

The model. Measured transport is the true transport plus the asymmetry in how long each side
took to read its clock:

    T_measured = T_true + Delta,     Delta = delta_recv - delta_ack

so an inversion (negative measured transport) occurs exactly when Delta < -T_true, and

    P(inversion) = F_Delta(-T_true)

Two consequences are testable without ever observing Delta directly:

  H1  inversion probability is monotonically decreasing in T_true. A benchmark measuring a small
      quantity is more fragile than one measuring a large quantity on the same hardware under
      the same load.
  H2  inversion probability follows scheduler waiting time, which under an M/G/1 model grows as
      rho/(1-rho). That predicts a knee near saturation, not a linear ramp.

This module provides the estimators for both, plus the recovery step that turns a set of
(T_true, inversion rate) pairs into an estimate of F_Delta -- an instrument-quality measure that
needs no reference clock.

CLI:
    python scripts/measurement_model.py --effect-size-csv <csv> --utilisation-csv <csv> \
        --out docs/results/model
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- H1
def recover_delta_quantiles(t_true_ms, inversion_rate):
    """Recover points on the CDF of -Delta from (T_true, inversion rate) pairs.

    P(inversion at T) = P(Delta < -T) = F_Delta(-T). So each measured inversion rate at a known
    T_true is one point of the distribution, read off without a reference clock: the rate *is*
    the quantile. Returned sorted by T_true.
    """
    pairs = sorted(zip(np.asarray(t_true_ms, float), np.asarray(inversion_rate, float)))
    return pd.DataFrame(
        {"t_true_ms": [p[0] for p in pairs],
         "inversion_rate": [p[1] for p in pairs],
         # The quantile of the |Delta| distribution that T_true sits at.
         "delta_exceeds_t_prob": [p[1] for p in pairs]})


def monotone_decreasing(values, tolerance=0.0):
    """True if the sequence never increases by more than `tolerance`.

    H1's falsifiable form: inversion rate must not rise as the measured quantity grows. A small
    tolerance absorbs sampling noise without admitting a genuine upward trend.
    """
    v = list(values)
    return all(b - a <= tolerance for a, b in zip(v, v[1:]))


def spearman(x, y):
    """Rank correlation, computed directly so the module has no scipy dependency."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size < 2 or np.all(x == x[0]) or np.all(y == y[0]):
        return float("nan")

    def ranks(a):
        order = a.argsort()
        r = np.empty(len(a), float)
        r[order] = np.arange(1, len(a) + 1)
        # Average tied ranks so ties do not create a spurious ordering.
        for v in np.unique(a):
            m = a == v
            if m.sum() > 1:
                r[m] = r[m].mean()
        return r

    rx, ry = ranks(x), ranks(y)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    denom = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / denom) if denom else float("nan")


def check_h1(df, t_col="t_true_ms", rate_col="inversion_rate", tolerance=0.02):
    """H1: inversion rate decreases with the true latency being measured."""
    d = df.sort_values(t_col)
    rho = spearman(d[t_col], d[rate_col])
    return {
        "hypothesis": "H1 effect-size rule",
        "n_points": int(len(d)),
        "spearman": rho,
        "monotone_decreasing": bool(monotone_decreasing(d[rate_col], tolerance)),
        # A negative rank correlation is the direction H1 predicts.
        "supported": bool(len(d) >= 3 and not np.isnan(rho) and rho < 0),
    }


# --------------------------------------------------------------------------- H2
def mg1_waiting(rho, scale=1.0):
    """Mean waiting time under an M/G/1-style queue, up to a scale factor.

    Returns infinity at or above saturation, which is the behaviour that produces the predicted
    knee rather than a linear ramp.
    """
    rho = np.asarray(rho, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = scale * rho / (1.0 - rho)
    return np.where(rho >= 1.0, np.inf, w)


def fit_mg1(rho, inversion_rate):
    """Fit the M/G/1 shape against a family of alternatives, not just a straight line.

    H2 is a claim about *shape*. Comparing rho/(1-rho) only against a LINE is a weak test: any
    convex increasing function beats a line on data that turns upward near saturation, so a win
    there is close to guaranteed and says little about queueing specifically. A referee made
    exactly this objection, and it is correct.

    We therefore also fit two convex alternatives that a non-queueing mechanism could produce --
    a power law rho^k (shape without a pole) and an exponential exp(k*rho) -- each with its
    exponent fitted, and report every R^2. The honest claim is only as strong as the margin over
    the BEST alternative, so `mg1_better` now means "beats all of them", and `best_alternative`
    names the runner-up so the margin can be read directly.

    Saturated points are excluded throughout: at rho >= 1 the M/G/1 predictor is infinite, and
    including them would let the pole win by construction.
    """
    rho = np.asarray(rho, float)
    y = np.asarray(inversion_rate, float)
    ok = (rho < 1.0) & np.isfinite(y) & (rho > 0.0)
    nan = float("nan")
    if ok.sum() < 3:
        return {"scale": nan, "r2_mg1": nan, "r2_linear": nan, "r2_power": nan,
                "r2_exponential": nan, "power_k": nan, "exp_k": nan,
                "best_alternative": None, "r2_best_alternative": nan, "mg1_better": False}

    r, yy = rho[ok], y[ok]

    def r2(pred):
        ss_res = ((yy - pred) ** 2).sum()
        ss_tot = ((yy - yy.mean()) ** 2).sum()
        return float(1 - ss_res / ss_tot) if ss_tot else nan

    def scaled(basis):
        """Least-squares scale for a one-parameter shape through the origin."""
        denom = (basis ** 2).sum()
        s = float((basis * yy).sum() / denom) if denom else nan
        return s, r2(s * basis)

    x_q = mg1_waiting(r)
    scale, r2_q = scaled(x_q)
    _, r2_l = scaled(r)

    # Power law rho^k: fit k on the log-log slope, then the scale by least squares.
    pos = yy > 0
    if pos.sum() >= 2 and np.ptp(np.log(r[pos])) > 0:
        lx, ly = np.log(r[pos]), np.log(yy[pos])
        power_k = float(((lx - lx.mean()) * (ly - ly.mean())).sum() / ((lx - lx.mean()) ** 2).sum())
        _, r2_p = scaled(r ** power_k)
    else:
        power_k, r2_p = nan, nan

    # Exponential exp(k*rho): fit k on the log-linear slope, then the scale by least squares.
    if pos.sum() >= 2 and np.ptp(r[pos]) > 0:
        ly = np.log(yy[pos])
        rp = r[pos]
        exp_k = float(((rp - rp.mean()) * (ly - ly.mean())).sum() / ((rp - rp.mean()) ** 2).sum())
        _, r2_e = scaled(np.exp(exp_k * r))
    else:
        exp_k, r2_e = nan, nan

    alts = {"linear": r2_l, "power": r2_p, "exponential": r2_e}
    usable = {k: v for k, v in alts.items() if not np.isnan(v)}
    best_name = max(usable, key=usable.get) if usable else None
    best_r2 = usable[best_name] if best_name else nan

    return {"scale": scale, "r2_mg1": r2_q, "r2_linear": r2_l, "r2_power": r2_p,
            "r2_exponential": r2_e, "power_k": power_k, "exp_k": exp_k,
            "best_alternative": best_name, "r2_best_alternative": best_r2,
            # Beats every alternative, not merely the weakest one.
            "mg1_better": bool(not np.isnan(r2_q) and (best_name is None or r2_q > best_r2))}


def check_h2(df, rho_col="rho", rate_col="inversion_rate"):
    """H2: inversion rate follows scheduler waiting time, with a knee near saturation.

    Two verdicts, deliberately separated.

    `supported` is the PRE-REGISTERED criterion: R^2(M/G/1) > R^2(linear) with a positive rank
    correlation. We do not change a pre-registered rule after seeing the data, so this is
    reported exactly as it was specified.

    `form_discriminated` is a post-hoc robustness check the pre-registration did not require and
    which a referee rightly asked for: does the M/G/1 form also beat a *fair* convex alternative
    (a fitted power law, a fitted exponential)? Beating only a straight line is close to
    guaranteed for any function that turns upward near saturation. Where this is False, the
    honest reading is that the data supports superlinear growth with a knee but cannot single out
    queueing theory as the mechanism.
    """
    fit = fit_mg1(df[rho_col], df[rate_col])
    rho = spearman(df[rho_col], df[rate_col])
    pre_registered = bool(not np.isnan(fit["r2_mg1"]) and not np.isnan(fit["r2_linear"])
                          and fit["r2_mg1"] > fit["r2_linear"]
                          and not np.isnan(rho) and rho > 0)
    return {
        "hypothesis": "H2 utilisation rule",
        "n_points": int(len(df)),
        "spearman": rho,
        **fit,
        "supported": pre_registered,
        "form_discriminated": bool(fit["mg1_better"]),
    }


def runs_test_z(signs):
    """H8, the clustering rule. Wald-Wolfowitz runs test on a sequence of inversion signs.

    If timestamp inversions came from independent clock quantisation, their signs would be an
    i.i.d. sequence and the number of runs would match the independence expectation (z ~ 0). If
    instead a single descheduling event makes a *run* of consecutive events wake late together --
    the scheduling mechanism this paper argues for -- inversions cluster and there are fewer runs
    than expected, giving z << 0.

    `signs` is a per-event sequence in emission order; entries <= 0 are inversions, > 0 are not.
    Zeros are dropped. Returns z, or None if either class is too small to test.
    """
    s = [1 if x > 0 else -1 for x in signs]
    n1 = sum(1 for x in s if x > 0)
    n2 = len(s) - n1
    if n1 < 2 or n2 < 2:
        return None
    runs = 1 + sum(1 for a, b in zip(s, s[1:]) if a != b)
    n = n1 + n2
    mu = 1.0 + 2.0 * n1 * n2 / n
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n * n * (n - 1.0))
    return float((runs - mu) / (var ** 0.5)) if var > 0 else None


# --------------------------------------------------------------------------- driver
def _load(path):
    p = Path(path) if path else None
    return pd.read_csv(p) if p and p.exists() else None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fit and test the measurement-failure model")
    ap.add_argument("--effect-size-csv",
                    help="columns: t_true_ms, inversion_rate (experiment E-B)")
    ap.add_argument("--utilisation-csv",
                    help="columns: rho, inversion_rate (experiment E-A)")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    results = {}
    eb = _load(args.effect_size_csv)
    if eb is not None:
        results["h1"] = check_h1(eb)
        results["recovered_delta_cdf"] = recover_delta_quantiles(
            eb["t_true_ms"], eb["inversion_rate"]).to_dict(orient="records")
    ea = _load(args.utilisation_csv)
    if ea is not None:
        results["h2"] = check_h2(ea)

    if not results:
        print("no inputs found; nothing to fit")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_fit.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    for key in ("h1", "h2"):
        if key in results:
            r = results[key]
            verdict = "SUPPORTED" if r["supported"] else "NOT SUPPORTED"
            print(f"{r['hypothesis']}: {verdict} "
                  f"(spearman {r['spearman']:.3f}, n={r['n_points']})")
            if key == "h2":
                print(f"   shape: R^2 M/G/1 {r['r2_mg1']:.3f} vs linear {r['r2_linear']:.3f}")
    print(f"Wrote {out / 'model_fit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
