#!/usr/bin/env python3
"""
equivalence_tests.py
Two One-Sided Tests (TOST) for the paper's central *negative* claim.

A non-significant Mann-Whitney result only says we failed to detect a difference; it is not
evidence that none exists. TOST inverts the burden of proof: it tests

    H0: |mu_kafka - mu_redis| >= delta      (a difference at least as large as the margin)
    H1: |mu_kafka - mu_redis| <  delta      (the backends are equivalent for practical purposes)

Rejecting H0 lets us state equivalence positively. Equivalently -- and more readably -- the
90% confidence interval of the difference must lie entirely inside (-delta, +delta); we report
both. The margin must be pre-specified on domain grounds, not fitted: we use one broadcast
video frame (40 ms at 25 fps) for latency, and the staleness a maximal event (TV shift 1.0)
accrues over one frame (0.04 probability-seconds) for decision-staleness.

CLI:
    python scripts/equivalence_tests.py --by-run <by_run.csv> --value-col tti_p50 \
        --n-col n --margin 40 --config single --label tti --out docs/results/equivalence
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Pre-specified, domain-justified margins (see module docstring).
FRAME_MS = 1000.0 / 25.0            # one broadcast frame at 25 fps = 40 ms
DEFAULT_MARGIN_MS = FRAME_MS
DEFAULT_MARGIN_PROB_S = FRAME_MS / 1000.0 * 1.0   # one frame at the maximum possible TV shift


def welch_ci(a, b, conf=0.90):
    """Mean difference (a-b) with a Welch confidence interval; returns (diff, lo, hi, df)."""
    na, nb = len(a), len(b)
    ma, mb = float(np.mean(a)), float(np.mean(b))
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    se = np.sqrt(va / na + vb / nb)
    if se == 0:
        return ma - mb, ma - mb, ma - mb, float(na + nb - 2)
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    crit = stats.t.ppf(0.5 + conf / 2.0, df)
    diff = ma - mb
    return diff, diff - crit * se, diff + crit * se, float(df)


def tost(a, b, margin):
    """TOST for equivalence within +/- margin.

    Returns dict with the mean difference, its 90% CI, the two one-sided p-values, the overall
    TOST p (their max) and whether equivalence is established at alpha=0.05.
    """
    na, nb = len(a), len(b)
    ma, mb = float(np.mean(a)), float(np.mean(b))
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    se = np.sqrt(va / na + vb / nb)
    diff, lo, hi, df = welch_ci(a, b)
    if se == 0:
        # identical, zero-variance samples: equivalent iff the difference is inside the margin
        p_lower = p_upper = 0.0 if abs(diff) < margin else 1.0
    else:
        # H0_lower: diff <= -margin  ;  H0_upper: diff >= +margin
        p_lower = 1.0 - stats.t.cdf((diff + margin) / se, df)
        p_upper = stats.t.cdf((diff - margin) / se, df)
    p_tost = float(max(p_lower, p_upper))
    return {"n_kafka": na, "n_redis": nb, "mean_kafka": ma, "mean_redis": mb,
            "mean_diff": diff, "ci90_lo": lo, "ci90_hi": hi,
            "p_tost": p_tost, "equivalent": bool(p_tost < 0.05)}


def equivalence_by_n(df, value_col, n_col, margin):
    """Run TOST per concurrency level; skip cells too small to estimate variance."""
    rows = []
    for n in sorted(df[n_col].dropna().unique()):
        sub = df[df[n_col] == n]
        a = sub[sub["backend"] == "kafka"][value_col].dropna().values
        b = sub[sub["backend"] == "redis"][value_col].dropna().values
        if len(a) < 2 or len(b) < 2:
            continue
        res = {"n": int(n), "margin": float(margin)}
        res.update(tost(a, b, margin))
        rows.append(res)
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="TOST equivalence tests for the fair corpus")
    ap.add_argument("--by-run", required=True)
    ap.add_argument("--value-col", required=True)
    ap.add_argument("--n-col", default="n")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN_MS,
                    help=f"equivalence margin in the value column's units "
                         f"(default {DEFAULT_MARGIN_MS} = one 25fps frame in ms)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--label", default="metric")
    ap.add_argument("--out", default="docs/results/equivalence")
    args = ap.parse_args(argv)

    try:
        df = pd.read_csv(args.by_run)
    except (OSError, ValueError):
        print(f"Could not read {args.by_run}")
        return 1
    if args.value_col not in df.columns or "backend" not in df.columns or args.n_col not in df.columns:
        print(f"{args.by_run} missing required columns")
        return 1
    if args.config and "config" in df.columns:
        df = df[df["config"] == args.config]

    out = equivalence_by_n(df, args.value_col, args.n_col, args.margin)
    if out.empty:
        print(f"Not enough data in {args.by_run} for TOST")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / f"{args.label}_tost.csv", index=False)
    print(f"== {args.label}: TOST equivalence (margin +/-{args.margin:g}) ==")
    print(out.to_string(index=False))
    n_eq = int(out["equivalent"].sum())
    print(f"Equivalence established in {n_eq}/{len(out)} concurrency levels; wrote {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
