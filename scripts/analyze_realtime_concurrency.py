#!/usr/bin/env python3
"""
analyze_realtime_concurrency.py
Aggregate the *fair* (pipelined, non-saturating) concurrency sweep into the tables the
manuscript needs.

The earlier 120x runs were confounded by a load-generator asymmetry: the Kafka producer ran
synchronous (acks=all, max_inflight=1), blocking on a broker round-trip per event, while the
Redis producer dispatched asynchronously. That inflated Kafka's *producer scheduling lag*
(not its broker latency). The fair sweep pipelines the Kafka producer (--max-inflight) and
replays at a modest speed so neither pipeline saturates, making TTI an apples-to-apples
end-to-end latency.

We report three layers per (backend, config, N):
  * tti_ms          - end-to-end (t_output - t_prod_sched); identical definition both backends
  * transport_ms    - broker-side delivery (measured slightly differently per backend; see paper)
  * sched_lag_ms    - producer scheduling lag (should stay small if unsaturated)

Config (single vs cluster) is inferred from each run's meta.json bootstrap/port, because the
concurrency run-id does not encode it.

CLI:
    python scripts/analyze_realtime_concurrency.py --runs-dir runs \
        --speedup 10 --out docs/results/realtime_concurrency
"""
import argparse
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd


def infer_config(meta):
    """single vs cluster from a run's meta.json (bootstrap for kafka, port for redis)."""
    backend = meta.get("backend", "")
    if backend == "kafka":
        bs = str(meta.get("bootstrap", ""))
        if ":19092" in bs:
            return "single"
        if re.search(r":(9092|9093|9094)\b", bs):
            return "cluster"
    elif backend == "redis":
        port = int(meta.get("redis", {}).get("port", meta.get("port", 0)) or 0)
        if port == 16379 or port == 6379:
            return "single"
        if port in (7000, 7001, 7002):
            return "cluster"
    return "unknown"


def load_meta(run_dir):
    try:
        return json.load(open(run_dir / "meta.json", encoding="utf-8-sig"))
    except (ValueError, OSError):
        return None


def load_tti(run_dir):
    try:
        return json.load(open(run_dir / "tti_summary.json", encoding="utf-8-sig"))
    except (ValueError, OSError):
        return None


def collect(runs_dir, speedup, min_max_t_sim=0.0):
    """Return a DataFrame, one row per (concurrency) run that matches the target speedup
    (and, if min_max_t_sim>0, whose meta max_t_sim is at least that -- used to select the
    full-match runs from windowed runs that share a timestamp prefix)."""
    rows = []
    for run_dir in sorted(Path(runs_dir).glob("concurrency_n*_*_feed*_rep*")):
        if not run_dir.is_dir():
            continue
        m = re.search(r"concurrency_n(\d+)_\d{8}_\d{6}_(kafka|redis)_feed\d+_rep\d+$", run_dir.name)
        if not m:
            continue
        meta = load_meta(run_dir)
        tti = load_tti(run_dir)
        if meta is None or tti is None:
            continue
        if speedup is not None and int(round(float(meta.get("speedup", -1)))) != int(speedup):
            continue
        if min_max_t_sim > 0 and float(meta.get("max_t_sim", 0) or 0) < min_max_t_sim:
            continue
        n = int(m.group(1))
        backend = m.group(2)
        config = infer_config(meta)

        def p(block, key):
            return (tti.get(block) or {}).get(key)

        rows.append({
            "run_id": run_dir.name, "backend": backend, "config": config, "n": n,
            "tti_p50": p("tti_ms", "p50"), "tti_p95": p("tti_ms", "p95"),
            "transport_p50": p("transport_ms", "p50"), "transport_p95": p("transport_ms", "p95"),
            "schedlag_p50": p("producer_sched_lag_ms", "p50"),
            "n_matched": tti.get("n_matched"),
        })
    return pd.DataFrame(rows)


def summarize(df):
    """Median across feeds and reps for each (backend, config, N)."""
    metrics = ["tti_p50", "tti_p95", "transport_p50", "transport_p95", "schedlag_p50"]
    agg = (df.groupby(["backend", "config", "n"])[metrics]
             .median()
             .reset_index()
             .sort_values(["config", "backend", "n"]))
    counts = df.groupby(["backend", "config", "n"]).size().reset_index(name="n_runs")
    return agg.merge(counts, on=["backend", "config", "n"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Aggregate the fair concurrency sweep")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--speedup", type=float, default=10.0,
                    help="Only include runs whose meta speedup matches this (None to include all)")
    ap.add_argument("--out", default="docs/results/realtime_concurrency")
    ap.add_argument("--min-max-t-sim", type=float, default=0.0,
                    help="Only include runs whose meta max_t_sim >= this (e.g. 9000 to select "
                         "full-match runs). 0 disables.")
    args = ap.parse_args(argv)

    speedup = None if args.speedup < 0 else args.speedup
    df = collect(args.runs_dir, speedup, args.min_max_t_sim)
    if df.empty:
        print(f"No concurrency runs at speedup={speedup} under {args.runs_dir}")
        return 1

    summary = summarize(df)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "realtime_concurrency_by_run.csv", index=False)
    summary.to_csv(out_dir / "realtime_concurrency_summary.csv", index=False)
    print(f"Collected {len(df)} runs at speedup={speedup}; "
          f"configs={sorted(df['config'].unique())}, N={sorted(df['n'].unique())}")
    print(summary.to_string(index=False))
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
