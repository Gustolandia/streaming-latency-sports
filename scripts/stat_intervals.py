#!/usr/bin/env python3
"""
stat_intervals.py
Interval estimates for the numbers the manuscript states as evidence.

Why this exists. Every proportion in the paper is a count over a known denominator, and
every ratio between two of them is an effect size. A reviewer is entitled to ask what the
uncertainty on each is, and the answer has to be recomputed from the artefact rather than
typed, for the same reason the campaign counts are (see emit_paper_numbers.py). The paper
previously asserted "disjoint Wilson intervals" without printing them; this module prints
them.

Three estimators, chosen for what they assume:

  wilson()      score interval for a binomial proportion. Not Wald: at the real-time arm's
                rate (about 3 in 1000) the normal approximation puts the lower bound below
                zero, which is not a possible value for a rate. Wilson stays inside [0,1]
                and is the standard recommendation for small p.

  ratio_z()     two-proportion z for the ratio between two cells. The manipulation claims
                are "this factor is real", so the test is on the difference of the two
                proportions with a pooled variance, and the paper quotes the factor beside
                it.

  ols_slope()   least squares on four points with a Student-t interval at n-2 = 2 degrees
                of freedom. Four points is four points: the interval is wide and the paper
                says so rather than hiding it behind R^2.

CLI:
    python scripts/stat_intervals.py            # print every interval the paper quotes
"""
import argparse
import csv
import math
import os
import sys

RESULTS = os.path.join("docs", "results")

# Student-t two-sided 97.5% quantiles, by degrees of freedom. Only the small df we use are
# tabulated: importing scipy for four numbers would add a dependency to a repository whose
# reproducibility claim rests on being installable.
T_975 = {1: 12.706205, 2: 4.302653, 3: 3.182446, 4: 2.776445}
Z_975 = 1.959964


def wilson(k, n, z=Z_975):
    """Wilson score interval for k successes in n trials. Returns (lo, hi)."""
    if n <= 0:
        raise ValueError("n must be positive")
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def ratio_z(k_a, n_a, k_b, n_b):
    """Two-proportion z for cell B against cell A, with the pooled-variance denominator.

    Returns (z, ratio) where ratio is p_a / p_b -- the manuscript quotes the collapse as a
    factor, so the caller gets both the test statistic and the factor it belongs to.
    """
    p_a, p_b = k_a / n_a, k_b / n_b
    pooled = (k_a + k_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        raise ValueError("degenerate cells: pooled variance is zero")
    z = (p_a - p_b) / se
    ratio = float("inf") if p_b == 0 else p_a / p_b
    return z, ratio


def ols_slope(xs, ys):
    """Least squares of ys on xs. Returns (slope, intercept, r2, slope_lo, slope_hi).

    The interval is Student-t at n-2 degrees of freedom, which for the payload sweep is 2.
    """
    n = len(xs)
    if n < 3:
        raise ValueError("need at least three points for a slope interval")
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = my - slope * mx
    fitted = [intercept + slope * x for x in xs]
    sse = sum((y - f) ** 2 for y, f in zip(ys, fitted))
    sst = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - sse / sst if sst else float("nan")
    se_slope = math.sqrt((sse / (n - 2)) / sxx) if n > 2 else float("nan")
    t = T_975.get(n - 2, 1.96)
    return slope, intercept, r2, slope - t * se_slope, slope + t * se_slope


def holm(pvalues):
    """Holm's step-down adjustment. Returns adjusted p-values in the input order.

    The manuscript's grid table said "Holm-corrected" in its caption while printing raw
    permutation p-values, and one arm changed verdict between the two. Stating a correction
    and displaying the uncorrected number is the same class of error the paper documents
    elsewhere, so the correction is computed here and the table is generated from the
    result rather than transcribed.

    Adjusted value for the i-th smallest of m is (m - i) + 1 times the raw value, made
    non-decreasing along the sorted order and capped at one. The monotone step is what
    makes the adjusted values a coherent set: without it a larger raw p could adjust to a
    smaller value than a stricter neighbour.
    """
    m = len(pvalues)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvalues[i])
    out = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        adjusted = pvalues[idx] * (m - rank)
        running = max(running, adjusted)
        out[idx] = min(1.0, running)
    return out


def grid_cells(path=os.path.join("external", "grid_membership.csv")):
    """The grid-membership arms, with the Holm adjustment applied and a derived verdict.

    The verdict is derived rather than stored because the stored one disagreed with the
    correction the caption claimed. Three outcomes, and the middle one is the honest
    addition:

      flat (coincident)  the arm has no power: when T_true/tau sits on a grid vertex, the
                         grid prediction and the continuum prediction are the same number
                         and no test can separate them. Not evidence either way.
      grid               powered, and rejects the continuum null after correction.
      not resolved       powered, rejects before correction and not after. Reported as
                         neither support nor refutation, which is what it is.
    """
    rows = _rows(*path.split(os.sep))
    adjusted = holm([float(r["p_value"]) for r in rows])
    out = []
    for r, p_adj in zip(rows, adjusted):
        powered = r["powered"].strip().lower() == "true"
        if not powered:
            verdict = "flat (coincident)"
        elif p_adj < 0.05:
            verdict = "grid"
        else:
            verdict = "not resolved"
        out.append({
            "rate_hz": int(r["rate_hz"]),
            "p": int(r["p"]),
            "q": int(r["q"]),
            "n": int(r["n"]),
            "d_observed": float(r["D_observed"]),
            "d_null": float(r["D_null_center"]),
            "p_raw": float(r["p_value"]),
            "p_holm": p_adj,
            "powered": powered,
            "verdict": verdict,
        })
    return out


def spearman(xs, ys):
    """Rank correlation, ties averaged. Pure standard library, like everything here."""
    n = len(xs)
    if n < 2:
        return float("nan")

    def ranks(values):
        order = sorted(range(n), key=lambda i: values[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            shared = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = shared
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def retention_cells(path=os.path.join("external", "omb_retention.csv")):
    """Instrumented cells for which the benchmark's own summary was captured.

    The manuscript quoted "the 49 runs on an unsaturated path", a denominator no partition
    of this artefact reproduces. What the artefact does support is stated instead, and it
    is the stronger claim: the cells that report a millisecond-grid median, and the
    retention range across them.
    """
    rows = _rows(*path.split(os.sep))
    return [{"campaign": r["campaign"], "cell": r["cell"],
             "retention_pct": float(r["retention_pct"]),
             "p50_ms": float(r["omb_p50_ms"]),
             "pub_p50_ms": float(r["pub_lat_p50_ms"]),
             "kept": int(r["kept"])} for r in rows]


def _rows(*parts):
    with open(os.path.join(RESULTS, *parts), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def priority_cells(path=os.path.join("model", "stamping_priority.csv")):
    """The real-time-priority pairs: (level, k_base, n_base, k_rt, n_rt)."""
    out = []
    for r in _rows(*path.split(os.sep)):
        n_b, n_r = int(r["n_base"]), int(r["n_rt"])
        out.append((r["level"],
                    round(float(r["inv_base"]) * n_b), n_b,
                    round(float(r["inv_rt"]) * n_r), n_r))
    return out


def geometry_cells(phase="ea6"):
    """The equal-utilisation geometry pair at k=6, as (condition, k, n)."""
    rows = {r["condition"]: r for r in _rows("model", phase, "knee_resolution.csv")}
    return [(c, int(rows[c]["n_inversions"]), int(rows[c]["n_events"]))
            for c in ("k6_conc", "k6_spread") if c in rows]


def payload_fit(phase=None):
    """OLS of log(inversion rate) on log(transport), the paper's effective span exponent."""
    parts = ("model", "ttrue_sweep.csv") if phase is None else ("model", phase, "ttrue_sweep.csv")
    rows = _rows(*parts)
    xs = [math.log(float(r["transport_ms"])) for r in rows]
    ys = [math.log(float(r["inversion"])) for r in rows]
    return ols_slope(xs, ys)


def report():
    lines = []
    lines.append("Real-time priority on the stamping threads (Wilson 95%):")
    for level, kb, nb, kr, nr in priority_cells():
        lo_b, hi_b = wilson(kb, nb)
        lo_r, hi_r = wilson(kr, nr)
        z, ratio = ratio_z(kb, nb, kr, nr)
        lines.append("  %-4s ordinary %.4f [%.4f, %.4f]  real-time %.4f [%.4f, %.4f]  "
                     "factor %.1fx  z=%.1f  disjoint=%s"
                     % (level, kb / nb, lo_b, hi_b, kr / nr, lo_r, hi_r, ratio, z,
                        hi_r < lo_b))
    for phase, label in (("ea6", "original"), ("ea6b", "replication")):
        cells = geometry_cells(phase)
        if len(cells) != 2:
            continue
        (_, kc, nc), (_, ks, ns) = cells
        lo_c, hi_c = wilson(kc, nc)
        lo_s, hi_s = wilson(ks, ns)
        z, ratio = ratio_z(ks, ns, kc, nc)
        lines.append("Geometry k=6, %s (Wilson 95%%): concentrated %.4f [%.4f, %.4f]  "
                     "spread %.4f [%.4f, %.4f]  factor %.2fx  z=%.1f"
                     % (label, kc / nc, lo_c, hi_c, ks / ns, lo_s, hi_s, ratio, z))
    slope, intercept, r2, lo, hi = payload_fit()
    lines.append("Payload sweep, log-log OLS (n=4, t at 2 df): slope %.4f [%.4f, %.4f]  "
                 "exponent %.3f  R2 %.4f  prefactor %.3f"
                 % (slope, lo, hi, -slope, r2, math.exp(intercept)))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Interval estimates for the paper's evidence")
    ap.parse_args(argv)
    print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
