#!/usr/bin/env python3
"""
fair_statistics.py
Formal significance tests behind the fair-corpus claims (README/manuscript):

  * Per concurrency level N: Mann-Whitney U comparing Kafka vs Redis, with a rank-biserial
    effect size and Holm-Bonferroni correction across the N-family. This backs "parity at N=1"
    (not significant) and "divergence under concurrency" (significant, Redis higher).
  * Kruskal-Wallis across N, per backend: does the metric change with concurrency at all?

Runs on the per-run CSVs emitted by analyze_realtime_concurrency.py (tti_p50) and
decision_staleness.py (decision_staleness_prob_s), so it needs no run access.

CLI:
    python scripts/fair_statistics.py --by-run docs/results/realtime_concurrency_fullmatch/realtime_concurrency_by_run.csv \
        --value-col tti_p50 --n-col n --label tti --out docs/results/fair_statistics
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def holm_bonferroni(pvals):
    """Return Holm-Bonferroni adjusted p-values, preserving input order."""
    pvals = list(pvals)
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        val = (m - rank) * pvals[idx]
        running = max(running, val)
        adj[idx] = min(1.0, running)
    return adj


def rank_biserial(kafka, redis, u):
    """Rank-biserial effect size from the Mann-Whitney U of the Kafka group.
    r > 0 means Kafka ranks higher (slower); r < 0 means Redis ranks higher."""
    n1, n2 = len(kafka), len(redis)
    if n1 == 0 or n2 == 0:
        return float("nan")
    return 1.0 - (2.0 * u) / (n1 * n2)


def per_n_tests(df, value_col, n_col):
    """Mann-Whitney Kafka vs Redis at each N; Holm-Bonferroni across the N-family."""
    rows = []
    for n in sorted(df[n_col].dropna().unique()):
        sub = df[df[n_col] == n]
        k = sub[sub["backend"] == "kafka"][value_col].dropna().values
        r = sub[sub["backend"] == "redis"][value_col].dropna().values
        if len(k) < 2 or len(r) < 2:
            continue
        try:
            u, p = stats.mannwhitneyu(k, r, alternative="two-sided")
        except ValueError:
            # e.g. all values identical -> undefined
            u, p = float("nan"), 1.0
        rows.append({
            "n": int(n), "kafka_median": float(np.median(k)), "redis_median": float(np.median(r)),
            "n_kafka": len(k), "n_redis": len(r), "U": float(u), "p": float(p),
            "rank_biserial": rank_biserial(k, r, u),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["p_holm"] = holm_bonferroni(out["p"].tolist())
        out["significant"] = out["p_holm"] < 0.05
    return out


def kruskal_across_n(df, value_col, n_col):
    """Kruskal-Wallis across N, per backend: is there any concurrency effect?"""
    rows = []
    for backend in ("kafka", "redis"):
        groups = []
        for n in sorted(df[n_col].dropna().unique()):
            vals = df[(df["backend"] == backend) & (df[n_col] == n)][value_col].dropna().values
            if len(vals) >= 2:
                groups.append(vals)
        if len(groups) >= 2:
            try:
                h, p = stats.kruskal(*groups)
            except ValueError:
                h, p = float("nan"), 1.0
            rows.append({"backend": backend, "n_groups": len(groups), "H": float(h), "p": float(p),
                         "significant": p < 0.05})
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Formal stats for the fair corpus")
    ap.add_argument("--by-run", required=True, help="per-run CSV with backend + value + N columns")
    ap.add_argument("--value-col", required=True)
    ap.add_argument("--n-col", default="n")
    ap.add_argument("--config", default=None,
                    help="If set and a 'config' column exists, keep only this config (e.g. single).")
    ap.add_argument("--label", default="metric")
    ap.add_argument("--out", default="docs/results/fair_statistics")
    args = ap.parse_args(argv)

    try:
        df = pd.read_csv(args.by_run)
    except (OSError, ValueError):
        print(f"Could not read {args.by_run}")
        return 1
    if args.value_col not in df.columns or "backend" not in df.columns or args.n_col not in df.columns:
        print(f"{args.by_run} missing required columns (backend/{args.value_col}/{args.n_col})")
        return 1
    if args.config and "config" in df.columns:
        df = df[df["config"] == args.config]

    per_n = per_n_tests(df, args.value_col, args.n_col)
    across = kruskal_across_n(df, args.value_col, args.n_col)
    if per_n.empty:
        print(f"Not enough data in {args.by_run} for per-N tests")
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    per_n.to_csv(out_dir / f"{args.label}_kafka_vs_redis_by_n.csv", index=False)
    across.to_csv(out_dir / f"{args.label}_kruskal_across_n.csv", index=False)
    print(f"== {args.label}: Kafka vs Redis by N (Holm-Bonferroni) ==")
    print(per_n.to_string(index=False))
    print(f"== {args.label}: Kruskal-Wallis across N ==")
    print(across.to_string(index=False))
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
