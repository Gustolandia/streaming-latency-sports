#!/usr/bin/env python3
"""
analyze_span_symmetry.py
Is the negative-span distribution symmetric, about what, and is its shape predictable?

Why this exists. A co-author looked at the pooled span histogram and asked about an apparent
symmetry. The pooled answer is confounded -- 74 conditions share that histogram -- so this
script asks the question per condition, and then asks the sharper question underneath it.

The identity that makes the sharper question possible. Every joined event gives

    S = t_recv - t_ack        the span that goes negative
    D = t_recv - t_send       delivery, never negative
    A = t_ack  - t_send       ack lag, never negative

and S = D - A exactly, per event, because the send stamp cancels. D and A are both observable
and both nonnegative. So the whole shape of S -- the negative lobe included -- is predicted by
the joint behaviour of two well-behaved distributions, and the one modelling question is
whether D and A are close enough to independent within a condition for the convolution
P(S) = P(D) * P(-A) to reproduce what is observed.

If it does: the negative spans are not an anomaly ON the distribution, they ARE the
distribution -- the exact population that two independent nonnegative delays must produce in
their difference. And any correction procedure can work from D and A directly.

What is computed per condition:

    median and a symmetry centre for S, D, A. The centre minimises a mirrored-mass score
    (0 = perfectly symmetric); the score at the best centre says how symmetric the
    distribution can be made by any choice of centre.

    the independence prediction: S_hat = D convolved with -A on the shared 50 us grid, and
    the distance between S_hat and S (total variation), plus predicted-vs-observed negative
    fraction and predicted-vs-observed centre.

    the decomposition of the pooled asymmetry: mean within-condition score against the
    pooled score, so the between-condition share is a number rather than a suspicion.

Output: docs/results/span_symmetry.csv, one row per condition, plus a printed summary.

CLI:
    python scripts/analyze_span_symmetry.py
"""
import csv
import json
import os

IN_JSON = os.path.join("docs", "results", "span_by_condition.json")
OUT_CSV = os.path.join("docs", "results", "span_symmetry.csv")

STEP = 50  # us, the committed bin width


def load():
    with open(IN_JSON, encoding="utf-8") as fh:
        return json.load(fh)


def to_series(acc, bin_lo_us):
    """{bin_index: count} -> sorted [(low_edge_us, count)]."""
    return sorted((bin_lo_us + int(k) * STEP, v) for k, v in acc["bins"].items())


def median_us(series, n):
    cum = 0
    for lo, c in series:
        cum += c
        if cum >= 0.5 * n:
            return lo
    return series[-1][0] if series else 0.0


def asym_score(counts, centre_us, half_width_us=10_000):
    """Mirrored-mass score about a centre. 0 = symmetric, 1 = fully one-sided."""
    num = den = 0.0
    steps = int(half_width_us // STEP)
    for i in range(steps):
        lo_l = centre_us - (i + 1) * STEP
        lo_r = centre_us + i * STEP
        left = counts.get(lo_l, 0)
        right = counts.get(lo_r, 0)
        num += abs(left - right)
        den += left + right
    return (num / den) if den else None


def best_centre(series, n, med):
    """Scan centres on the bin grid around the median; return (centre, score)."""
    counts = dict(series)
    best = (med, 1.1)
    for c in range(int(med) - 3000, int(med) + 3001, STEP):
        s = asym_score(counts, c)
        if s is not None and s < best[1]:
            best = (c, s)
    return best


def convolve_diff(d_series, a_series, n_d, n_a):
    """P(S) for S = D - A under independence, on the 50 us grid. Sparse, exact on the grid."""
    out = {}
    for lo_d, cd in d_series:
        pd = cd / n_d
        for lo_a, ca in a_series:
            s = lo_d - lo_a
            out[s] = out.get(s, 0.0) + pd * (ca / n_a)
    return out


def tv_distance(p, q_series, n_q):
    """Total variation between predicted dict p and observed series (normalised)."""
    q = {lo: c / n_q for lo, c in q_series}
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def neg_fraction(dist):
    if isinstance(dist, dict):
        return sum(v for k, v in dist.items() if k < 0)
    return None


def moments(series, n):
    """Binned mean and variance, bin centres, within the window."""
    if not n:
        return 0.0, 0.0
    m = sum((lo + STEP / 2.0) * c for lo, c in series) / n
    v = sum(((lo + STEP / 2.0) - m) ** 2 * c for lo, c in series) / n
    return m, v


def main():
    data = load()
    bin_lo = data["bin_lo_us"]
    rows = []
    pooled_S = {}
    pooled_n = 0

    for cond, q in sorted(data["conditions"].items()):
        S, D, A = q["S"], q["D"], q["A"]
        nS = S["n"] - S["under"] - S["over"]
        nD = D["n"] - D["under"] - D["over"]
        nA = A["n"] - A["under"] - A["over"]
        if nS < 2000:            # too small for shape statements
            continue
        sS = to_series(S, bin_lo)
        sD = to_series(D, bin_lo)
        sA = to_series(A, bin_lo)
        for lo, c in sS:
            pooled_S[lo] = pooled_S.get(lo, 0) + c
        pooled_n += nS

        medS = median_us(sS, nS)
        medD = median_us(sD, nD)
        medA = median_us(sA, nA)
        cS, scoreS = best_centre(sS, nS, medS)
        cD, scoreD = best_centre(sD, nD, medD)
        counts = dict(sS)
        score0 = asym_score(counts, 0)

        # implied within-event correlation between D and A, from the variance identity
        # Var(S) = Var(D) + Var(A) - 2 rho sd(D) sd(A). Everything on the right is observed.
        _mS, vS = moments(sS, nS)
        _mD, vD = moments(sD, nD)
        _mA, vA = moments(sA, nA)
        rho = ((vD + vA - vS) / (2.0 * (vD * vA) ** 0.5)) if vD > 0 and vA > 0 else float("nan")

        pred = convolve_diff(sD, sA, nD, nA)
        tv = tv_distance(pred, sS, nS)
        neg_obs = sum(c for lo, c in sS if lo < 0) / nS
        neg_pred = neg_fraction(pred)

        rows.append({
            "condition": cond, "n_events": nS,
            "median_S_us": medS, "centre_S_us": cS, "score_S": round(scoreS, 4),
            "score_S_at_zero": round(score0, 4) if score0 is not None else "",
            "score_D": round(scoreD, 4),
            "median_D_us": medD, "median_A_us": medA,
            "medD_minus_medA_us": medD - medA,
            "neg_frac_obs": round(neg_obs, 5),
            "neg_frac_pred_indep": round(neg_pred, 5),
            "tv_pred_vs_obs": round(tv, 4),
            "rho_DA": round(rho, 4),
            # the remedy under test: recover delivery's median from the corrupted span plus a
            # purely producer-side quantity. Error in us; med(D) is the ground truth.
            "recovered_medD_us": cS + medA,
            "recovery_err_us": (cS + medA) - medD,
        })

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ---- summary ----
    import statistics as st
    scores = [r["score_S"] for r in rows]
    scores0 = [r["score_S_at_zero"] for r in rows if r["score_S_at_zero"] != ""]
    tvs = [r["tv_pred_vs_obs"] for r in rows]
    dc = [r["centre_S_us"] - r["medD_minus_medA_us"] for r in rows]
    dm = [r["centre_S_us"] - r["median_S_us"] for r in rows]
    ratio = [r["neg_frac_pred_indep"] / r["neg_frac_obs"]
             for r in rows if r["neg_frac_obs"] > 0.001]

    pooled_series = sorted(pooled_S.items())
    pooled_med = median_us(pooled_series, pooled_n)
    pooled_c, pooled_score = best_centre(pooled_series, pooled_n, pooled_med)

    print("conditions analysed        %d  (>= 2000 events each)" % len(rows))
    print("")
    print("WITHIN-CONDITION SYMMETRY of S (0 = symmetric)")
    if len(scores) >= 4:
        print("  best-centre score:  median %.3f   IQR [%.3f, %.3f]"
              % (st.median(scores), st.quantiles(scores, n=4)[0],
                 st.quantiles(scores, n=4)[2]))
    else:
        print("  best-centre score:  median %.3f  (n=%d, no IQR)"
              % (st.median(scores), len(scores)))
    print("  score about zero:   median %.3f" % st.median(scores0))
    print("  pooled-corpus best score %.3f at %+d us  (vs within-condition median above)"
          % (pooled_score, pooled_c))
    print("")
    print("CENTRE OF SYMMETRY vs THE DECOMPOSITION")
    if len(dc) >= 4:
        print("  centre(S) - [med(D) - med(A)]:  median %+d us   IQR [%+d, %+d]"
              % (st.median(dc), st.quantiles(dc, n=4)[0], st.quantiles(dc, n=4)[2]))
    else:
        print("  centre(S) - [med(D) - med(A)]:  median %+d us" % st.median(dc))
    print("  centre(S) - median(S):          median %+d us" % st.median(dm))
    print("")
    print("INDEPENDENCE CONVOLUTION  S_hat = D * (-A)")
    if len(tvs) >= 4:
        print("  total-variation distance:  median %.3f   IQR [%.3f, %.3f]"
              % (st.median(tvs), st.quantiles(tvs, n=4)[0], st.quantiles(tvs, n=4)[2]))
    else:
        print("  total-variation distance:  median %.3f" % st.median(tvs))
    if len(ratio) >= 4:
        print("  predicted/observed negative fraction:  median %.2f   IQR [%.2f, %.2f]  (n=%d)"
              % (st.median(ratio), st.quantiles(ratio, n=4)[0], st.quantiles(ratio, n=4)[2],
                 len(ratio)))
    else:
        print("  predicted/observed negative fraction: not estimable (n=%d)" % len(ratio))
    print("")
    rhos = [r["rho_DA"] for r in rows if r["rho_DA"] == r["rho_DA"]]
    print("WITHIN-EVENT CORRELATION rho(D, A) implied by the variance identity")
    if len(rhos) >= 4:
        print("  median %.3f   IQR [%.3f, %.3f]"
              % (st.median(rhos), st.quantiles(rhos, n=4)[0], st.quantiles(rhos, n=4)[2]))
    else:
        # every condition can be a point mass in a synthetic corpus; the identity then has
        # no variance to work with and the honest summary line says so
        print("  not estimable (fewer than 4 conditions with finite variance)")
    print("")
    print("THE REMEDY UNDER TEST: med(D) ~ centre(S) + med(A)")

    def _remedy(subset, label):
        if len(subset) < 3:
            print("  %-22s (only %d conditions, skipped)" % (label, len(subset)))
            return
        errs = [r["recovery_err_us"] for r in subset]
        rel = [100.0 * abs(r["recovery_err_us"]) / r["median_D_us"]
               for r in subset if r["median_D_us"] > 0]
        print("  %-22s n=%-3d  err median %+d us  IQR [%+d, %+d]   |err| median %.1f%% of med(D)"
              % (label, len(subset), st.median(errs),
                 st.quantiles(errs, n=4)[0], st.quantiles(errs, n=4)[2], st.median(rel)))

    # The split that decides whether this becomes a VI-B rule: a remedy for already-collected
    # data earns its keep on the population the gate rejects, so it is scored there separately.
    _remedy(rows, "all conditions")
    _remedy([r for r in rows if r["condition"].endswith("#pass")], "gate-passing runs")
    _remedy([r for r in rows if r["condition"].endswith("#fail")], "gate-failing runs")
    print("")
    print("wrote %s" % OUT_CSV)


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
