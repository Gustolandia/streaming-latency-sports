#!/usr/bin/env python3
"""
analyze_backlog.py
Distinguish a fixed delivery cost from a growing backlog.

Adding network delay can hurt a consumer in two very different ways. If the consumer merely
pays the delay once per event, per-event latency rises but stays *flat* across a run. If the
consumer's drain rate falls below the arrival rate, a queue builds and latency *grows* as the
run proceeds -- the magnitude then reflects the backlog, not the delay.

This script measures that by splitting each run's events into quartiles of scheduled emission
time and reporting the ratio of the last quartile's mean latency to the first's. A ratio near
1 means a stable, fixed cost; a ratio well above 1 means the consumer is falling behind. It is
the diagnostic behind the round-trip-bound consumption hypothesis in the manuscript.

CLI:
    python scripts/analyze_backlog.py --runs-dir runs --run-glob 'concurrency_n5_2026*_*_rep1' \
        --label netem_d20 --out docs/results/backlog
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def run_latencies(run_dir):
    """Per-event latency (ms) ordered by scheduled emission; None if the run is unreadable."""
    run_dir = Path(run_dir)
    pf, cf = run_dir / "producer.csv", run_dir / "consumer.csv"
    if not (pf.exists() and cf.exists()):
        return None
    try:
        prod = pd.read_csv(pf)[["event_id", "t_prod_sched_ns"]]
        cons = pd.read_csv(cf)[["event_id", "t_output_ns"]]
    except (ValueError, OSError, KeyError):
        return None
    m = prod.merge(cons, on="event_id", how="inner")
    if m.empty:
        return None
    m = m.sort_values("t_prod_sched_ns")
    return ((m["t_output_ns"] - m["t_prod_sched_ns"]) / 1e6).values


def growth_ratio(latencies, quantiles=4):
    """Mean latency of the final quantile divided by the first.

    ~1 means a stable fixed cost; >1 means a backlog accumulating through the run.
    """
    if latencies is None or len(latencies) < quantiles:
        return None
    parts = np.array_split(np.asarray(latencies, dtype=float), quantiles)
    first, last = float(parts[0].mean()), float(parts[-1].mean())
    if first <= 0:
        return None
    return {"first_mean_ms": first, "last_mean_ms": last, "growth": last / first,
            "n_events": int(len(latencies))}


def analyze(runs_dir, run_glob, quantiles=4):
    rows = []
    for run_dir in sorted(Path(runs_dir).glob(run_glob)):
        if not run_dir.is_dir():
            continue
        g = growth_ratio(run_latencies(run_dir), quantiles)
        if g is None:
            continue
        name = run_dir.name
        g.update({"run_id": name,
                  "backend": "kafka" if "kafka" in name else "redis" if "redis" in name else "?"})
        rows.append(g)
    return pd.DataFrame(rows)


def summarize(df):
    if df.empty:
        return df
    return (df.groupby("backend")[["first_mean_ms", "last_mean_ms", "growth"]]
              .median().reset_index())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Backlog growth diagnostic")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--run-glob", required=True)
    ap.add_argument("--quantiles", type=int, default=4)
    ap.add_argument("--label", default="backlog")
    ap.add_argument("--out", default="docs/results/backlog")
    args = ap.parse_args(argv)

    df = analyze(args.runs_dir, args.run_glob, args.quantiles)
    if df.empty:
        print(f"No usable runs matched {args.run_glob}")
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / f"{args.label}_by_run.csv", index=False)
    summary = summarize(df)
    summary.to_csv(out_dir / f"{args.label}_summary.csv", index=False)
    print(f"== {args.label}: latency growth across a run (last quartile / first) ==")
    print(summary.to_string(index=False))
    print("growth ~1 => stable fixed cost; >1 => consumer falling behind (backlog)")
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
