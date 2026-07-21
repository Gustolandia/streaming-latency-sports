#!/usr/bin/env python3
"""
wp_sensitivity.py
Is the decision-staleness conclusion an artefact of our win-probability proxy?

The proxy has one free parameter (the per-team scoring rate). A reviewer is entitled to ask
whether a different -- or better -- model would change the finding. This script sweeps that
parameter and reports, for each setting, both the model's calibration and the Kafka-vs-Redis
decision-staleness difference.

The structural argument is that it cannot change the comparison: both backends are scored
against the *same* model, so the model scales both sides of the difference. This script
demonstrates that empirically rather than asserting it.

Efficiency note: delivery latencies are a property of the runs, not of the model. We therefore
extract each run's decisive-event latencies once and re-weight them by the shifts implied by
each parameter setting, instead of re-reading the run CSVs per setting.

CLI:
    python scripts/wp_sensitivity.py --runs-dir runs --pattern 'concurrency_n*_20260721_*' \
        --events-dir data/raw/statsbomb/<sha>/events --out docs/results/wp_sensitivity
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import win_probability as wp
import decision_staleness as ds
import wp_calibration as wpc

DEFAULT_RATES = [1.0, 1.15, 1.3, 1.45, 1.6]


def collect_run_latencies(runs_dir, pattern, goal_ids, min_max_t_sim=0.0):
    """Per run: {event_id: latency_seconds} for delivered decisive events, plus run metadata.

    Latencies are model-independent, so this is done once and reused for every parameter.
    """
    out = []
    for run_dir in sorted(Path(runs_dir).glob(pattern)):
        if not run_dir.is_dir():
            continue
        if min_max_t_sim > 0 and ds.run_max_t_sim(run_dir) < min_max_t_sim:
            continue
        pf, cf = run_dir / "producer.csv", run_dir / "consumer.csv"
        if not (pf.exists() and cf.exists()):
            continue
        try:
            prod = pd.read_csv(pf)[["event_id", "t_prod_sched_ns"]]
            cons = pd.read_csv(cf)[["event_id", "t_output_ns"]]
        except (ValueError, OSError, KeyError):
            continue
        m = prod.merge(cons, on="event_id", how="inner")
        m["event_id"] = m["event_id"].astype(str)
        m = m[m["event_id"].isin(goal_ids)]
        if m.empty:
            continue
        lat = ((m["t_output_ns"] - m["t_prod_sched_ns"]) / 1e9).clip(lower=0)
        name = run_dir.name
        out.append({
            "run_id": name,
            "backend": "kafka" if "kafka" in name else "redis" if "redis" in name else "?",
            "n_concurrency": ds.parse_n(name),
            "latencies": dict(zip(m["event_id"], lat)),
        })
    return out


def staleness_for_rate(run_latencies, shifts):
    """Decision-staleness per run under one set of event shifts."""
    rows = []
    for r in run_latencies:
        cost = sum(shifts.get(eid, 0.0) * sec for eid, sec in r["latencies"].items())
        rows.append({"run_id": r["run_id"], "backend": r["backend"],
                     "n_concurrency": r["n_concurrency"], "decision_staleness_prob_s": cost})
    return pd.DataFrame(rows)


def sweep(events_dir, run_latencies, rates, grid_seconds=60):
    """For each scoring rate: calibration (ECE) and the Kafka-vs-Redis staleness difference."""
    rows = []
    for rate in rates:
        shifts = ds.build_goal_shifts(events_dir, team_rate=rate)
        df = staleness_for_rate(run_latencies, shifts)
        k = df[df["backend"] == "kafka"]["decision_staleness_prob_s"]
        r = df[df["backend"] == "redis"]["decision_staleness_prob_s"]
        pairs = wpc.collect_calibration_pairs(events_dir, team_rate=rate, grid_seconds=grid_seconds)
        ece = wpc.expected_calibration_error(wpc.reliability_bins(pairs), len(pairs))
        rows.append({
            "team_rate": rate,
            "ece": ece,
            "mean_shift": float(np.mean(list(shifts.values()))) if shifts else float("nan"),
            "kafka_mean_staleness": float(k.mean()) if len(k) else float("nan"),
            "redis_mean_staleness": float(r.mean()) if len(r) else float("nan"),
            "difference": float(k.mean() - r.mean()) if len(k) and len(r) else float("nan"),
        })
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Win-probability model sensitivity")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="concurrency_n*")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--min-max-t-sim", type=float, default=0.0)
    ap.add_argument("--rates", type=float, nargs="*", default=DEFAULT_RATES)
    ap.add_argument("--out", default="docs/results/wp_sensitivity")
    args = ap.parse_args(argv)

    base_shifts = ds.build_goal_shifts(args.events_dir)
    if not base_shifts:
        print(f"No goal shifts from {args.events_dir}")
        return 1
    run_latencies = collect_run_latencies(args.runs_dir, args.pattern, set(base_shifts),
                                          args.min_max_t_sim)
    if not run_latencies:
        print(f"No runs with decisive deliveries matched {args.pattern}")
        return 1

    out = sweep(args.events_dir, run_latencies, list(args.rates))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / "wp_sensitivity.csv", index=False)
    (out_dir / "wp_sensitivity.json").write_text(
        json.dumps({"n_runs": len(run_latencies), "rates": list(args.rates)}, indent=2),
        encoding="utf-8")
    print(f"Sensitivity over {len(run_latencies)} runs:")
    print(out.to_string(index=False))
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
