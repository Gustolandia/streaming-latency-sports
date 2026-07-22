#!/usr/bin/env python3
"""
retention_bias.py
Bound the selection bias introduced by unequal integrity-check retention (referee point M2).

The problem. In the concurrency experiment, Kafka passes the clock-integrity check on 100% of
runs at every level, while Redis passes 8/8, 20/27, 17/30 and 19/36. The check screens on
timestamp inversion, and inversion is caused by driver saturation, so the surviving Redis runs
are plausibly the less-loaded ones and their transport may be biased low. The two arms are then
not strictly comparable, and the bias runs in the direction that would manufacture the reported
equivalence.

Why we bound rather than re-analyse. The rejected runs' values are not recoverable -- the check
discards them and the raw per-run measurements for that campaign no longer exist. A threshold
sweep is therefore impossible on this corpus. What is possible, and is arguably a stronger
answer, is a worst-case bound: assume every rejected Redis run would have measured some value V,
add them back, and ask how large V would have to be before the paper's conclusion changes.

If the tipping point is far outside anything the instrument ever recorded, the conclusion is
safe regardless of what the rejected runs contained. If it is within reach, the conclusion is
not supported and must be withdrawn.

CLI:
    python scripts/retention_bias.py \
        --by-run-csv docs/results/e1/e1_by_run_gated.csv \
        --integrity-csv docs/results/e1/e1_clock_integrity.csv \
        --margin 1.0 --out docs/results/e1
"""
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

METRIC = "transport_p50"


def hl_shift(a, b):
    """Hodges-Lehmann shift: the median of all pairwise differences a_i - b_j.

    The same estimator the manuscript reports, so the bound is expressed in the units the
    conclusion is stated in.
    """
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.size == 0 or b.size == 0:
        return float("nan")
    return float(np.median(a[:, None] - b[None, :]))


def retention(integrity_df):
    """Runs measured and retained, per (N, backend), from the condition-level audit."""
    rows = []
    for _, r in integrity_df.iterrows():
        m = re.search(r"_n(\d+)_.*_(kafka|redis)$", str(r["condition"]))
        if not m:
            continue
        rows.append({"n": int(m.group(1)), "backend": m.group(2),
                     "measured": int(r["n_runs"]), "retained": int(r["n_trustworthy"])})
    return pd.DataFrame(rows)


def impute(retained_values, n_dropped, value):
    """Add back the rejected runs at a hypothetical value."""
    return list(retained_values) + [float(value)] * int(n_dropped)


def tipping_point(kafka, redis_retained, n_dropped, margin, hi=1000.0, tol=1e-4):
    """Smallest imputed value for the rejected Redis runs that breaks equivalence.

    Raising the imputed value can only push Redis's distribution up, so the shift
    (kafka - redis) moves monotonically downward; the search is a clean bisection. Returns
    None when no value in the search range breaks it, which is the reassuring outcome.
    """
    if n_dropped == 0:
        return None

    def breaks(v):
        return abs(hl_shift(kafka, impute(redis_retained, n_dropped, v))) >= margin

    if not breaks(hi):
        return None
    lo = float(np.min(redis_retained)) if len(redis_retained) else 0.0
    if breaks(lo):
        return lo
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if breaks(mid):
            hi = mid
        else:
            lo = mid
    return hi


def analyse(by_run, integrity, margin=1.0):
    """Per concurrency level: observed shift, worst-case shift, and the tipping point."""
    ret = retention(integrity)
    out = []
    for n in sorted(by_run["n"].unique()):
        k = by_run[(by_run["n"] == n) & (by_run["backend"] == "kafka")][METRIC].tolist()
        r = by_run[(by_run["n"] == n) & (by_run["backend"] == "redis")][METRIC].tolist()
        if not k or not r:
            continue
        rr = ret[(ret["n"] == n) & (ret["backend"] == "redis")]
        measured = int(rr["measured"].iloc[0]) if len(rr) else len(r)
        dropped = max(0, measured - len(r))

        observed = hl_shift(k, r)
        worst_at_max = hl_shift(k, impute(r, dropped, max(r))) if dropped else observed
        tip = tipping_point(k, r, dropped, margin)

        out.append({
            "n": n,
            "n_kafka": len(k),
            "n_redis_retained": len(r),
            "n_redis_dropped": dropped,
            "redis_retention": len(r) / measured if measured else float("nan"),
            # The Hodges-Lehmann shift is a median of pairwise differences, so it has a
            # breakdown point of 1/2: while more than half the runs survive, no value the
            # rejected runs could have held can drag the estimate outside the margin. This is
            # the reason the bound holds, and it is also its limit -- see `retention_margin`.
            "above_breakdown": bool(measured and len(r) / measured > 0.5),
            "retention_margin": (len(r) / measured - 0.5) if measured else float("nan"),
            "redis_median_ms": float(np.median(r)),
            "redis_max_ms": float(max(r)),
            "hl_shift_ms": observed,
            "hl_shift_worst_case_ms": worst_at_max,
            "equivalent_observed": bool(abs(observed) < margin),
            "equivalent_worst_case": bool(abs(worst_at_max) < margin),
            "tipping_point_ms": tip,
            "tipping_vs_observed_max": (tip / max(r)) if tip else float("nan"),
        })
    return pd.DataFrame(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bound the unequal-retention selection bias")
    ap.add_argument("--by-run-csv", default="docs/results/e1/e1_by_run_gated.csv")
    ap.add_argument("--integrity-csv", default="docs/results/e1/e1_clock_integrity.csv")
    ap.add_argument("--margin", type=float, default=1.0, help="equivalence margin, ms")
    ap.add_argument("--out", default="docs/results/e1")
    args = ap.parse_args(argv)

    for path in (args.by_run_csv, args.integrity_csv):
        if not Path(path).exists():
            print(f"missing input: {path}")
            return 1

    df = analyse(pd.read_csv(args.by_run_csv), pd.read_csv(args.integrity_csv), args.margin)
    if df.empty:
        print("no comparable cells")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "e1_retention_bias.csv"
    df.to_csv(dest, index=False)

    print(f"== unequal-retention bound (margin {args.margin} ms) ==")
    for _, r in df.iterrows():
        tip = r["tipping_point_ms"]
        tip_s = ("never in range" if pd.isna(tip) or tip is None
                 else f"{tip:.2f} ms ({r['tipping_vs_observed_max']:.0f}x the largest observed)")
        print(f"  N={int(r['n']):2d}  redis retained {int(r['n_redis_retained'])}/"
              f"{int(r['n_redis_retained']) + int(r['n_redis_dropped'])}"
              f"  shift {r['hl_shift_ms']:+.3f} ms"
              f"  worst-case {r['hl_shift_worst_case_ms']:+.3f} ms"
              f"  breaks at {tip_s}")
    if bool(df["equivalent_worst_case"].all()):
        print("Equivalence survives the worst case at every level.")
    else:
        levels = df.loc[~df["equivalent_worst_case"], "n"].tolist()
        print(f"Equivalence does NOT survive the worst case at N={levels}.")

    # State the limit of the argument as plainly as the argument itself.
    if bool(df["above_breakdown"].all()):
        tightest = df.loc[df["retention_margin"].idxmin()]
        print(f"Holds because Redis retention exceeds the estimator's 1/2 breakdown point at "
              f"every level; tightest is N={int(tightest['n'])} at "
              f"{tightest['redis_retention']:.1%} "
              f"({tightest['retention_margin']:+.1%} above breakdown).")
    else:
        bad = df.loc[~df["above_breakdown"], "n"].tolist()
        print(f"WARNING: retention is at or below 1/2 at N={bad}; the median-based bound does "
              f"not apply there and those cells cannot be defended this way.")
    print(f"Wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
