#!/usr/bin/env python3
"""
grid_membership_test.py -- the inference the broken median could not supply (referee M4).

The paper shows replicate medians cannot converge on a two-point support, and the registered
branch-count binomial (P1) presupposed branch-classifiable replicates that smeared arms do not
have. This is the replacement, pre-specified in full:

STATISTIC. For each commensurate arm, D = mean over replicates of the distance to the nearest
grid vertex, divided by the cell width 100/q. D near 0 means the arm sits on its grid; D near
the arm's theta-to-vertex distance means the grid is invisible.

NULL. The continuum: replicates are Normal(theta_local, sigma), with theta_local the arm's
rate-local continuous value and sigma the pooled replicate SD of the incommensurate arms --
both measured, neither fitted to the arm under test. Monte Carlo (default 20,000 arms of the
observed n) gives the null distribution of D; the p-value is one-sided,
P(D_null <= D_observed), because grid membership makes distances small.

Arms whose theta sits on a vertex (the degenerate case) have D_null ~ 0 too, so the test is
reported but has no power there; the report says so per arm rather than hiding it.

BRANCH WEIGHTS. Where every replicate lies within 3 points of a vertex, the arm is
branch-classifiable and the upper-branch weight gets an exact Clopper-Pearson 95% interval.

RESIDUALS (referee Q4). Per-arm mean retention minus theta_local, with the Spearman rank
correlation of |residual| against the numerator p -- the kernel account predicts a positive
association; its absence would count against that account.

CLI:
    python scripts/grid_membership_test.py --ledger docs/results/external_campaigns_index.csv
"""
import argparse
import csv
import math
import os
import random
from fractions import Fraction

RATE_CAMPAIGNS = ("rate_phase", "rate_phase2", "rate_q", "ultimate")
MAX_MEANINGFUL_Q = 64
CLASSIFIABLE_PTS = 3.0
MC_ARMS = 20000


def load_arms(path, campaigns=RATE_CAMPAIGNS):
    by = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if (r.get("campaign") not in campaigns or r.get("valid") != "1"
                    or r.get("count_source") != "shutdown_hook"):
                continue
            try:
                kept = int(r.get("kept") or 0)
                zero = int(r.get("discarded_zero") or 0)
                rate = int(r.get("level") or 0)
            except (TypeError, ValueError):
                continue
            if kept + zero > 0 and rate > 0:
                by.setdefault(rate, []).append(100.0 * kept / (kept + zero))
    return {k: sorted(v) for k, v in by.items()}


def q_of(rate):
    return (Fraction(1000, 1) / Fraction(rate)).denominator


def p_of(rate):
    return (Fraction(1000, 1) / Fraction(rate)).numerator


def theta_local(arms):
    """Rate-local continuous value: linear fit through the incommensurate medians.

    chain17b showed the trend plateaus above ~700/s, so the fit is used inside the fitted range
    and the nearest measured incommensurate median outside it.
    """
    pts = []
    for rate, v in arms.items():
        if q_of(rate) > MAX_MEANINGFUL_Q and len(v) >= 2:
            med = v[len(v) // 2] if len(v) % 2 else 0.5 * (v[len(v) // 2 - 1] + v[len(v) // 2])
            pts.append((rate, med))
    pts.sort()
    if len(pts) < 2:
        return None, pts
    xs, ys = zip(*pts)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx

    def theta(rate):
        # Clamped to the fitted range at the fit's own endpoint values: chain17b showed the
        # trend plateaus, so extrapolation is refuted, and clamping at the fit keeps theta
        # continuous at the boundary.
        return a + b * min(max(rate, xs[0]), xs[-1])
    return theta, pts


def incommensurate_sd(arms):
    """Pooled within-arm SD of the incommensurate arms: the continuum's replicate noise."""
    devs = []
    for rate, v in arms.items():
        if q_of(rate) > MAX_MEANINGFUL_Q and len(v) >= 2:
            m = sum(v) / len(v)
            devs.extend((x - m) for x in v)
    if len(devs) < 2:
        return None
    return math.sqrt(sum(d * d for d in devs) / (len(devs) - 1))


def vertex_distance(x, q):
    return min(abs(x - 100.0 * i / q) for i in range(q + 1))


def arm_statistic(values, q):
    return sum(vertex_distance(x, q) for x in values) / len(values) / (100.0 / q)


def mc_pvalue(n, q, theta_pct, sigma, observed, iters=MC_ARMS, seed=7):
    rng = random.Random(seed)
    hits = 0
    for _ in range(iters):
        vals = [min(100.0, max(0.0, rng.gauss(theta_pct, sigma))) for _ in range(n)]
        if arm_statistic(vals, q) <= observed:
            hits += 1
    return (hits + 1) / (iters + 1)


def clopper_pearson(k, n, alpha=0.05):
    """Exact binomial CI via the beta-quantile identity, bisected -- no scipy dependency."""
    def beta_ppf(prob, a, b):
        lo, hi = 0.0, 1.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            if _beta_cdf(mid, a, b) < prob:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _betacf(a, b, x):
        # Lentz continued fraction for the regularised incomplete beta (NR 6.4 form).
        qab, qap, qam = a + b, a + 1.0, a - 1.0
        c, d = 1.0, 1.0 - qab * x / qap
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        h = d
        for m in range(1, 200):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1.0 + aa / (c if abs(c) > 1e-30 else 1e-30)
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
            c = 1.0 + aa / (c if abs(c) > 1e-30 else 1e-30)
            de = d * c
            h *= de
            if abs(de - 1.0) < 1e-12:
                break
        return h

    def _beta_cdf(x, a, b):
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
        bt = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta)
        if x < (a + 1.0) / (a + b + 2.0):
            return bt * _betacf(a, b, x) / a
        return 1.0 - bt * _betacf(b, a, 1.0 - x) / b

    lo = 0.0 if k == 0 else beta_ppf(alpha / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta_ppf(1 - alpha / 2, k + 1, n - k)
    return lo, hi


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1
            for k2 in range(i, j + 1):
                rk[order[k2]] = avg
            i = j + 1
        return rk
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def analyse(arms, iters=MC_ARMS):
    theta, inc_pts = theta_local(arms)
    sigma = incommensurate_sd(arms)
    if theta is None or sigma is None:
        return None
    rows = []
    for rate in sorted(arms, reverse=True):
        q = q_of(rate)
        if q > MAX_MEANINGFUL_Q or len(arms[rate]) < 2:
            continue
        v = arms[rate]
        th = theta(rate)
        d_obs = arm_statistic(v, q)
        pval = mc_pvalue(len(v), q, th, sigma, d_obs, iters=iters)
        null_center = vertex_distance(th, q) / (100.0 / q)
        powered = null_center > 2 * sigma / (100.0 / q)
        row = {
            "rate_hz": rate, "p": p_of(rate), "q": q, "n": len(v),
            "theta_local_pct": round(th, 2), "D_observed": round(d_obs, 4),
            "D_null_center": round(null_center, 4),
            "p_value": round(pval, 5), "powered": powered,
            "mean_residual_pts": round(sum(v) / len(v) - th, 2),
        }
        near = [x for x in v if vertex_distance(x, q) <= CLASSIFIABLE_PTS]
        if len(near) == len(v) and q >= 1:
            upper_vertex = 100.0 * math.ceil(q * th / 100.0 * 1.0) / q  # nearest vertex above th
            k = sum(1 for x in v if x > th)
            lo, hi = clopper_pearson(k, len(v))
            row.update({"branch_classifiable": True, "upper_weight": round(k / len(v), 3),
                        "upper_ci_lo": round(lo, 3), "upper_ci_hi": round(hi, 3)})
        else:
            row.update({"branch_classifiable": False, "upper_weight": "",
                        "upper_ci_lo": "", "upper_ci_hi": ""})
        rows.append(row)
    resid = [(abs(r["mean_residual_pts"]), r["p"]) for r in rows]
    rho = spearman([a for a, _ in resid], [b for _, b in resid]) if len(resid) >= 3 else None
    return {"rows": rows, "sigma_pts": round(sigma, 2), "inc_points": inc_pts,
            "spearman_absresid_vs_p": None if rho is None else round(rho, 3)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Grid-membership inference for commensurate arms")
    ap.add_argument("--ledger", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--iters", type=int, default=MC_ARMS)
    args = ap.parse_args(argv)
    if not os.path.exists(args.ledger):
        print("missing: %s" % args.ledger)
        return 1
    arms = load_arms(args.ledger)
    res = analyse(arms, iters=args.iters)
    if res is None:
        print("not enough incommensurate arms to define the null")
        return 1
    print("null: Normal(theta_local, sigma=%.2f pts); one-sided MC p, %d arms per test"
          % (res["sigma_pts"], args.iters))
    print("%6s %3s %3s %2s %8s %8s %8s %9s %7s %s" % (
        "rate", "p", "q", "n", "theta", "D_obs", "D_null", "p_value", "power", "resid"))
    for r in res["rows"]:
        print("%5d/s %3d %3d %2d %7.2f%% %8.4f %8.4f %9.5f %7s %+6.2f" % (
            r["rate_hz"], r["p"], r["q"], r["n"], r["theta_local_pct"], r["D_observed"],
            r["D_null_center"], r["p_value"], "yes" if r["powered"] else "NO",
            r["mean_residual_pts"]))
    if res["spearman_absresid_vs_p"] is not None:
        print("Spearman |mean residual| vs p: %.3f" % res["spearman_absresid_vs_p"])
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(res["rows"][0].keys()))
            w.writeheader()
            w.writerows(res["rows"])
        print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
