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

  wilson()      score interval for a binomial proportion. Not Wald: at the real-time arms'
                rates the normal approximation's coverage falls well short of nominal and its
                interval is shifted low -- at the smallest arm, 10 of 2,985, Wald gives
                [0.0013, 0.0054] against Wilson's [0.0018, 0.0062]. Round 46 checked the
                sharper claim this docstring used to make, that Wald puts the lower bound
                below zero, and it is false on every arm the paper reports: that needs k <= 3
                at n = 2,985 and the smallest count published is 10. Wilson is still the right
                estimator, for coverage rather than for range.

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


def ratio_ci(k_a, n_a, k_b, n_b, z=Z_975):
    """Confidence interval for the ratio p_a / p_b, by Katz's log method. Returns (lo, hi).

    `ratio_z` already answers "do these two arms differ"; it does not answer "by how much,
    and how well is that pinned down", which is what the manuscript actually quotes when it
    says a manipulation collapses a rate 39x. A factor published without an interval invites
    the reader to treat the point estimate as the finding, and for the real-time arms the
    interval is wide -- the collapsed arm has ten events -- so the omission flattered us.

    The interval is symmetric in the log, which is the right scale for a ratio: it cannot
    reach zero or cross into a reversal, and it reproduces the asymmetry a reader expects
    around a large factor. The standard error is the usual delta-method one,
    sqrt((1-p_a)/k_a + (1-p_b)/k_b), which is undefined when either arm has no events -- an
    arm that never fired bounds the ratio on one side only, and we raise rather than return
    an interval that would read as though it had been estimated.
    """
    for k, n in ((k_a, n_a), (k_b, n_b)):
        if n <= 0:
            raise ValueError("n must be positive")
        if k <= 0:
            raise ValueError("Katz's method needs a non-zero count in both arms")
    p_a, p_b = k_a / n_a, k_b / n_b
    se = math.sqrt((1 - p_a) / k_a + (1 - p_b) / k_b)
    centre = math.log(p_a / p_b)
    return math.exp(centre - z * se), math.exp(centre + z * se)


def fisher_ci(rho, n, z=Z_975):
    """Confidence interval for a correlation, via Fisher's z transform. Returns (lo, hi).

    Wilson's interval is for a proportion and does not transfer to a correlation: r is
    bounded on both sides and its sampling distribution is skewed everywhere except zero.
    Fisher's transform is the standard fix and costs one line, which is why the audit
    flagged its absence rather than excusing it.
    """
    if n < 4:
        raise ValueError("Fisher's interval needs n >= 4")
    if not -1.0 < rho < 1.0:
        raise ValueError("rho must lie strictly inside (-1, 1)")
    zeta = 0.5 * math.log((1 + rho) / (1 - rho))
    half = z / math.sqrt(n - 3)
    return math.tanh(zeta - half), math.tanh(zeta + half)


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


def _median(values):
    """Median of an already-sorted sequence; 0.0 for an empty one.

    Local rather than `statistics.median` so that an arm with no replicates recorded returns
    a number the caller can format instead of raising, which is what every other field in
    `spread_cells` does with missing data.
    """
    n = len(values)
    if not n:
        return 0.0
    mid = n // 2
    return values[mid] if n % 2 else (values[mid - 1] + values[mid]) / 2.0


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
            # The null's own central 90%, so a reader can see how far an arm can fall by
            # chance instead of judging distance from a line. Absent in ledgers written
            # before round 43, and optional for that reason.
            "d_null_lo": float(r["D_null_lo"]) if r.get("D_null_lo") else None,
            "d_null_hi": float(r["D_null_hi"]) if r.get("D_null_hi") else None,
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


def harness_cells(path=os.path.join("external", "harness_results.csv")):
    """The independent Python harness, split by topology.

    The manuscript quoted "1.5 million samples" twice, once for each topology, and the
    artefact holds neither figure: it is 905,040 on one clock and 905,040 across two, zero
    negatives in each. A hand-typed round number in a paper about miscounted samples is the
    one defect this project cannot afford, so both totals are read from the ledger.
    """
    rows = _rows(*path.split(os.sep))
    out = {}
    for key in (False, True):
        cells = [r for r in rows if (r["cross_host"].strip().lower() == "true") is key]
        if not cells:
            continue
        out["cross_host" if key else "one_clock"] = {
            "runs": len(cells),
            "sent": sum(int(r["sent"]) for r in cells),
            "kept": sum(int(r["kept"]) for r in cells),
            "negatives": sum(int(r["discarded_negative"]) for r in cells),
        }
    return out


def harness_arm_spreads(path=os.path.join("external", "harness_results.csv")):
    """Retention spread per rate arm, one clock against two, from the same ledger.

    The manuscript said cross-host retention "wandered from 13.4 to 27.0%" over four
    replicates "where the same arm on one clock held to 0.8 points". Both numbers were
    typed. Recomputed here the arm runs 13.4 to 26.9, and its one-clock twin holds to 1.0
    points rather than 0.8 -- the second is what three of its four replicates span, so the
    sentence had been written against a ledger with one row fewer and never revisited.

    Neither correction touches the claim, which is that the cross-host arm wanders by an
    order of magnitude more than the co-located one. That is the usual shape of this defect:
    the argument survives and the digits do not, and a reader checking the digits finds the
    paper wrong about its own data.

    Returns {rate_hz: {"one_clock": (lo, hi), "cross_host": (lo, hi)}} for arms measured in
    both topologies, so the comparison is always like with like.
    """
    rows = _rows(*path.split(os.sep))
    per = {}
    for r in rows:
        try:
            rate = int(r["rate_hz"])
            kept = int(r["kept"])
            seen = kept + int(r["discarded_zero"]) + int(r["discarded_negative"])
        except (KeyError, TypeError, ValueError):
            continue
        if seen <= 0:
            continue
        key = "cross_host" if r["cross_host"].strip().lower() == "true" else "one_clock"
        per.setdefault(rate, {}).setdefault(key, []).append(100.0 * kept / seen)
    out = {}
    for rate, groups in per.items():
        if {"one_clock", "cross_host"} <= set(groups):
            out[rate] = {k: (min(v), max(v)) for k, v in groups.items()}
    return out


#: Above this denominator the phase set is dense enough that the grid imposes no structure,
#: and the arm is reported as effectively continuous rather than given a cell.
INCOMMENSURATE_Q = 64


def spread_cells(path=os.path.join("external", "phase_quantisation.csv")):
    """Every arm of the spread law, with both classes re-derived rather than read.

    This replaces a table that was typed. It was a good table -- round 45 checked all nine
    commensurate rows against the ledger and every one held -- and it was gated cell by cell
    by the test suite, which is why it never drifted. What it could not do was answer the
    sentence it exists to support. "All nine arms match, seven full, two flat" is a claim
    about *agreement*, and the typed table printed the prediction and the measured spread but
    never the measured class, so the one column that would let a reader see the nine matches
    was the one column missing. The suite applied the half-cell rule on the reader's behalf
    and the reader had to trust that it had.

    Both classifications come out of the geometry here, not out of the ledger's stored
    `predicted_full` and `observed_full`:

      position   distance from the nearest vertex against the cell *half*-width, so 0 sits
                 on a grid point and 1 sits midway between two. Predicted full above 0.5.
      spread     the replicate range. Measured full above half the cell width.

    Incommensurate arms carry no cell, so they carry no position and no class; they are
    returned with `commensurate` false and a spread, which is all the table prints for them.

    Ordered commensurate-first by ascending q -- the order the argument runs in, since q is
    what decides the prediction -- then by descending rate within a q.
    """
    from fractions import Fraction
    rows = _rows(*path.split(os.sep))
    out = []
    for r in rows:
        try:
            rate = int(r["rate_hz"])
            spread = float(r["spread_pts"])
            n = int(r["n"])
        except (KeyError, TypeError, ValueError):
            continue
        ratio = Fraction(1000, rate)
        commensurate = r.get("commensurate", "").strip().lower() == "true"
        # The replicates themselves, because several of the supplement's paragraphs narrate
        # them one by one and every one of those narrations had gone stale by round 46.
        values = sorted(float(v) for v in (r.get("retentions") or "").split())
        cell = {
            "rate_hz": rate,
            "p": ratio.numerator,
            "q": ratio.denominator,
            "n": n,
            "spread": spread,
            "commensurate": commensurate,
            "retentions": values,
            "median": _median(values),
        }
        if not commensurate:
            cell.update({"cell_width": None, "position": None,
                         "predicted": None, "observed": None, "agrees": None})
            out.append(cell)
            continue
        try:
            width = float(r["cell_width_pts"])
            distance = float(r["grid_distance_pts"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0:
            continue
        position = min(1.0, distance / (width / 2.0))
        predicted_full = position > 0.5
        observed_full = spread > width / 2.0
        cell.update({
            "cell_width": width,
            "position": position,
            "predicted": "full" if predicted_full else "flat",
            "observed": "full" if observed_full else "flat",
            "agrees": predicted_full == observed_full,
        })
        out.append(cell)
    return sorted(out, key=lambda c: (not c["commensurate"], c["q"], -c["rate_hz"]))


def occupancy_bounds(path=os.path.join("model", "occupancy_law.csv")):
    """The floor and ceiling of the inversion rate, as the two-state model bounds them.

    Read because the manuscript turned the ceiling into a statement about occupancy: "two
    events in three are still stamped unpreempted" is not what a rate ceiling of 0.37 says.
    Under the two-state model an event can be stamped by a preempted thread and still not invert,
    whenever the stall is shorter than the interval being measured.
    """
    out = {}
    for r in _rows(*path.split(os.sep)):
        for part in r["detail"].split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    out[k.strip()] = float(v)
                except ValueError:
                    pass
    return out


def load_growth(path=os.path.join("model", "collapse_conditions.csv"),
                idle="ea3/bg0", knee="ea3/bg7"):
    """Idle-to-knee growth in the fitted core width and in the inversion rate.

    The manuscript described the second of these as "the mass beyond one millisecond",
    which is not the quantity the artefact holds. It is the inversion rate: the mass of the
    stamping asymmetry beyond -T_true, at the T_true of that campaign.
    """
    rows = {r["condition"]: r for r in _rows(*path.split(os.sep))}
    if idle not in rows or knee not in rows:
        return {}
    a, b = rows[idle], rows[knee]
    return {
        "core_idle": float(a["sigma_core"]), "core_knee": float(b["sigma_core"]),
        "core_growth": float(b["sigma_core"]) / float(a["sigma_core"]),
        "inv_idle": float(a["inversion"]), "inv_knee": float(b["inversion"]),
        "inv_growth": float(b["inversion"]) / float(a["inversion"]),
        "rho_knee": float(b["rho"]),
    }


def observer_effect(traced=os.path.join("model", "runq_tail.csv"),
                    untraced=os.path.join("model", "ea9_notrace", "untraced_control.csv"),
                    condition="l88_base"):
    """The tracer's own effect on the rate it is used to predict.

    A BPF probe on every context switch is not free, and the campaign measured what it
    costs by running the same cell untraced. The manuscript never reported the comparison,
    which is an omission in a paper whose subject is instruments that change what they
    measure.
    """
    tr = {r["tag"]: r for r in _rows(*traced.split(os.sep))}
    un = {r["condition"]: r for r in _rows(*untraced.split(os.sep))}
    if condition not in tr or condition not in un:
        return {}
    t, u = tr[condition], un[condition]
    n_t, n_u = int(t["n_events"]), int(u["n_events"])
    k_t = round(float(t["inversion"]) * n_t)
    k_u = int(u["n_inversions"])
    z, _ = ratio_z(k_u, n_u, k_t, n_t)
    return {"traced": k_t / n_t, "untraced": k_u / n_u, "n": n_t, "z": z,
            "ratio": (k_u / n_u) / (k_t / n_t)}


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


def geometry_rho(phase="ea6"):
    """The utilisation both k=6 arms reached, which is the whole point of the pair.

    `geometry_cells` drops this column because the interval arithmetic does not need it. The
    experiment map does: its cell says the two arms differ "at rho 0.7531", and that number
    was typed. Raises if the two arms disagree, because a pair that did not reach the same
    utilisation is not the comparison the figure claims.
    """
    rows = {r["condition"]: r for r in _rows("model", phase, "knee_resolution.csv")}
    got = {round(float(rows[c]["rho"]), 6) for c in ("k6_conc", "k6_spread") if c in rows}
    if len(got) != 1:
        raise ValueError("k6 arms disagree on rho in %s: %s" % (phase, sorted(got)))
    return got.pop()


def payload_fit(phase=None):
    """OLS of log(inversion rate) on log(transport), the paper's effective span exponent."""
    parts = ("model", "ttrue_sweep.csv") if phase is None else ("model", phase, "ttrue_sweep.csv")
    rows = _rows(*parts)
    xs = [math.log(float(r["transport_ms"])) for r in rows]
    ys = [math.log(float(r["inversion"])) for r in rows]
    return ols_slope(xs, ys)


def payload_points(phase=None):
    """How many levels the payload fit rests on. Four.

    R-squared on four points with two fitted parameters has two residual degrees of freedom,
    so 0.990 is very nearly arithmetic rather than evidence, and it sits beside an exponent
    interval of 0.234-0.443 -- close to a factor of two. Emitted so the goodness-of-fit and
    the thing that limits it cannot be quoted apart; a gate enforces the pairing.
    """
    parts = ("model", "ttrue_sweep.csv") if phase is None else ("model", phase, "ttrue_sweep.csv")
    return len(_rows(*parts))


def payload_span(phase=None):
    """The endpoints of the payload sweep: how far transport moved, and what followed.

    One function because the alternative was five hand-typed copies and a sixth computed
    inside the figure. Section V-C printed the transport ratio to one decimal, three other
    sentences printed it rounded to an integer, and `make_result_figures` recomputed
    `round(xs[-1] / xs[0])` for its own annotation --- six readings of one CSV, none of them
    reading each other. Every one of them was correct, which is exactly why it survived
    thirty-three rounds: nothing was wrong, so nothing failed.

    `\\tailSlope`, the other number in that same figure annotation, was emitted two rounds
    earlier for precisely this reason, with a comment saying the ledger emits it "so they
    cannot drift apart again". This is its neighbour finally getting the same treatment.

    Returns the ratio of largest to smallest transport, the factor by which the negative-span
    rate falls across that span, and the utilisation spread over the four levels --- the three
    numbers Section V-C quotes in one sentence.
    """
    parts = ("model", "ttrue_sweep.csv") if phase is None else ("model", phase, "ttrue_sweep.csv")
    rows = _rows(*parts)
    t = [float(r["transport_ms"]) for r in rows]
    inv = [float(r["inversion"]) for r in rows]
    rho = [float(r["rho"]) for r in rows]
    # The rate-fall ratio is a ratio of two PROPORTIONS, and the sweep file carries the
    # denominators (`n_events`), so its interval is available here and was simply never
    # taken. The transport factor next to it is a ratio of two times with no within-level
    # replication in this file, so it gets no interval from here -- a distinction the audit
    # had collapsed into one "needs data" note for all four payload quantities.
    n = [int(r["n_events"]) for r in rows]
    hi_i, lo_i = inv.index(max(inv)), inv.index(min(inv))
    out = {"transport_factor": max(t) / min(t),
           "rate_fall": max(inv) / min(inv),
           "rho_spread": max(rho) - min(rho),
           "levels": len(rows)}
    k_hi, k_lo = round(inv[hi_i] * n[hi_i]), round(inv[lo_i] * n[lo_i])
    if k_hi > 0 and k_lo > 0:
        out["rate_fall_ci"] = ratio_ci(k_hi, n[hi_i], k_lo, n[lo_i])
    return out


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


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
