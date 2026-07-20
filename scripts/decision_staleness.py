#!/usr/bin/env python3
"""
Decision-staleness: translate streaming *delivery latency* into *in-play decision error*.

This is the paper's bridge between streaming infrastructure and sports analytics. A goal (or
red card) shifts the in-play win-probability (scripts/win_probability.py). If the event is
delivered to the consumer with latency L, the consumer's win-probability is stale for L
seconds by the magnitude of that shift. Following the Age-of-Information view of staleness
cost, we define a run's decision-staleness as

    cost = sum over decisive events of  TV_shift_i  *  latency_i

where TV_shift_i = 0.5 * (|dP_win| + |dP_draw| + |dP_loss|) is the probability mass the
forecast moved at event i, and latency_i is that event's delivery latency (TTI). Units:
probability-seconds of stale decision per match.

CLI:
    python scripts/decision_staleness.py --runs-dir runs --pattern 'batch9_20260617_*' \
        --events-dir data/raw/statsbomb/<sha>/events [--out docs/results/decision_staleness]
"""
import argparse
import glob
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

import win_probability as wp


def infer_config(run_dir, name):
    """single vs cluster. Prefer the run-name marker; fall back to meta.json bootstrap/port
    (concurrency run-ids do not encode the config the way batch9 run-ids do)."""
    if "cluster" in name:
        return "cluster"
    if "single" in name:
        return "single"
    try:
        meta = json.load(open(Path(run_dir) / "meta.json", encoding="utf-8-sig"))
    except (ValueError, OSError):
        return "?"
    backend = meta.get("backend", "")
    if backend == "kafka":
        bs = str(meta.get("bootstrap", ""))
        if ":19092" in bs:
            return "single"
        if re.search(r":(9092|9093|9094)\b", bs):
            return "cluster"
    elif backend == "redis":
        port = int((meta.get("redis") or {}).get("port", meta.get("port", 0)) or 0)
        if port in (16379, 6379):
            return "single"
        if port in (7000, 7001, 7002):
            return "cluster"
    return "?"


def parse_n(name):
    """Concurrency level N from a run-id (e.g. ..._n5_... -> 5); default 1 if absent."""
    m = re.search(r"n(\d+)", name)
    return int(m.group(1)) if m else 1


def run_max_t_sim(run_dir):
    """Read meta.json max_t_sim for a run; 0 if unreadable. Used to separate full-match runs
    from windowed runs that share a timestamp prefix."""
    try:
        meta = json.load(open(Path(run_dir) / "meta.json", encoding="utf-8-sig"))
    except (ValueError, OSError):
        return 0.0
    try:
        return float(meta.get("max_t_sim", 0))
    except (TypeError, ValueError):
        return 0.0


def goal_decision_shifts(events, team_rate=wp.DEFAULT_TEAM_RATE):
    """Map each goal event_id -> TV win-probability shift it caused, for one match."""
    home, away, goals, reds, match_len = wp.parse_match(events)
    if not match_len:  # pragma: no cover - parse_match floors match_len at MATCH_SECONDS (>0)
        return {}
    # ordered goal events with their event_id
    goal_seq = []
    for e in events:
        et = e.get("type", {}).get("name")
        team = e.get("team", {}).get("name")
        t = wp.clock_seconds(e.get("minute", 0), e.get("second", 0))
        if et == "Shot" and e.get("shot", {}).get("outcome", {}).get("name") == "Goal":
            goal_seq.append((e.get("id"), t, team))
        elif et == "Own Goal Against":
            goal_seq.append((e.get("id"), t, away if team == home else home))

    shifts = {}
    h, a = 0, 0
    for eid, t, team in goal_seq:
        frac_rem = max(0.0, (match_len - t) / match_len)
        before = wp.win_probability(h - a, frac_rem, team_rate)
        if team == home:
            h += 1
        else:
            a += 1
        after = wp.win_probability(h - a, frac_rem, team_rate)
        tv = 0.5 * sum(abs(b - c) for b, c in zip(before, after))
        if eid is not None:
            shifts[eid] = tv
    return shifts


def build_goal_shifts(events_dir, team_rate=wp.DEFAULT_TEAM_RATE):
    """All goal event_id -> TV shift, across every match JSON in events_dir."""
    shifts = {}
    for f in sorted(glob.glob(os.path.join(events_dir, "*.json"))):
        try:
            events = json.load(open(f, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if isinstance(events, list) and events:
            shifts.update(goal_decision_shifts(events, team_rate))
    return shifts


def run_decision_cost(run_dir, goal_shifts):
    """For one run, join delivered events to goal shifts and accumulate staleness cost.
    Returns (cost_prob_seconds, n_decisive_delivered, mean_latency_ms) or None."""
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
    cost, n, lat = 0.0, 0, []
    for _, r in m.iterrows():
        tv = goal_shifts.get(str(r["event_id"]))
        if tv is None:
            continue
        latency_s = (r["t_output_ns"] - r["t_prod_sched_ns"]) / 1e9
        if latency_s < 0:
            latency_s = 0.0
        cost += tv * latency_s
        lat.append(latency_s * 1000.0)
        n += 1
    return cost, n, (float(np.mean(lat)) if lat else 0.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Decision-staleness: latency -> win-probability error")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="batch9_20260617_*")
    ap.add_argument("--events-dir", required=True)
    ap.add_argument("--out", default="docs/results/decision_staleness")
    ap.add_argument("--min-max-t-sim", type=float, default=0.0,
                    help="Only include runs whose meta max_t_sim is >= this (used to select "
                         "full-match runs from same-timestamp windowed runs). 0 disables.")
    args = ap.parse_args(argv)

    goal_shifts = build_goal_shifts(args.events_dir)
    if not goal_shifts:
        print(f"No goal shifts derived from {args.events_dir}")
        return 1

    rows = []
    for run_dir in sorted(Path(args.runs_dir).glob(args.pattern)):
        if not run_dir.is_dir():
            continue
        if args.min_max_t_sim > 0 and run_max_t_sim(run_dir) < args.min_max_t_sim:
            continue
        res = run_decision_cost(run_dir, goal_shifts)
        if res is None:
            continue
        cost, n, mean_lat = res
        name = run_dir.name
        backend = "kafka" if "kafka" in name else "redis" if "redis" in name else "?"
        config = infer_config(run_dir, name)
        rows.append({"run_id": name, "backend": backend, "config": config,
                     "n_concurrency": parse_n(name),
                     "decision_staleness_prob_s": cost, "n_decisive": n,
                     "mean_decisive_latency_ms": mean_lat})

    if not rows:
        print(f"No runs matched {args.pattern} in {args.runs_dir}")
        return 1

    df = pd.DataFrame(rows)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "decision_staleness_by_run.csv", index=False)
    metrics = ["decision_staleness_prob_s", "mean_decisive_latency_ms", "n_decisive"]
    by = df.groupby(["backend", "config"])[metrics].mean()
    by.to_csv(out_dir / "decision_staleness_by_backend_config.csv")
    by_n = df.groupby(["backend", "config", "n_concurrency"])[metrics].mean()
    by_n.to_csv(out_dir / "decision_staleness_by_backend_config_n.csv")
    print(f"Analyzed {len(df)} runs; {int(df['n_decisive'].sum())} decisive deliveries total.")
    print(by.to_string())
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
