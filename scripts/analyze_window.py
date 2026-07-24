#!/usr/bin/env python3
"""
analyze_window.py
Test whether the ~103 ms Kafka producer offset is a per-event constant or a per-run start-up
cost that a short observation window mistakes for one.

The E1 corpus behind the paper's original headline matched a median of seven events per run.
Those events are the match's opening burst, emitted immediately after producer start, and
Kafka's first send pays metadata fetch and topic creation while Redis's XADD does not. If that
is the mechanism, the MEDIAN scheduling lag must fall as the window grows and steady-state
events dilute the one-off cost, while the MAXIMUM stays near 103 ms because the cost is still
paid once. If instead the offset is a genuine per-event constant, the median stays put.

Reads the per-run tti_summary.json written by each trial, so the verdict does not depend on the
loop trace.

CLI:
    python scripts/analyze_window.py --window-dir docs/results/window --runs-dir runs
"""
import argparse
import glob
import json
import os
import re
import statistics as st
from pathlib import Path


def condition_timestamp(cond_dir):
    """The run-id timestamp the trials of one window condition share."""
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def window_stats(cond_dir, runs_dir, backend):
    """Median scheduling lag, its max, and events per run, pooled over a condition's runs."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return None
    lags, maxes, events = [], [], []
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
        summary = os.path.join(run, "tti_summary.json")
        if not os.path.exists(summary):
            continue
        try:
            with open(summary, encoding="utf-8") as fh:
                d = json.load(fh)
            lag = d.get("producer_sched_lag_ms", {})
            if "p50" in lag:
                lags.append(float(lag["p50"]))
                maxes.append(float(lag.get("max", lag["p50"])))
                events.append(int(d.get("n_matched", 0)))
        except (ValueError, KeyError, OSError):
            continue
    if not lags:
        return None
    return {
        "runs": len(lags),
        "events_per_run": int(st.median(events)) if events else 0,
        "schedlag_p50": st.median(lags),
        "schedlag_max": max(maxes),
    }


def verdict(rows, drop_factor=5.0):
    """Per-event constant, or per-run start-up cost?

    A start-up cost predicts the median falls sharply as the window grows while the maximum
    stays high. A per-event constant predicts the median is flat.
    """
    ordered = sorted(rows, key=lambda r: r["window_s"])
    if len(ordered) < 2:
        return "INCONCLUSIVE", "need at least two windows"
    first, last = ordered[0], ordered[-1]
    if last["schedlag_p50"] <= 0:
        return "INCONCLUSIVE", "zero median at the widest window"
    drop = first["schedlag_p50"] / last["schedlag_p50"]
    if drop >= drop_factor:
        return ("START-UP COST",
                f"median falls {drop:.0f}x from the {first['window_s']:g}s window "
                f"({first['schedlag_p50']:.1f} ms over {first['events_per_run']} events) to the "
                f"{last['window_s']:g}s window ({last['schedlag_p50']:.2f} ms over "
                f"{last['events_per_run']} events), while the maximum stays at "
                f"{last['schedlag_max']:.0f} ms: the cost is paid once per run, not per event")
    return ("PER-EVENT CONSTANT",
            f"median only changes {drop:.1f}x across the window range, so the offset is not "
            f"explained by dilution of a one-off cost")


def collect(window_dir, runs_dir, backend="kafka"):
    rows = []
    for cond in sorted(glob.glob(os.path.join(window_dir, "w*"))):
        if not os.path.isdir(cond):
            continue
        m = re.search(r"w(\d+)$", os.path.basename(cond))
        s = window_stats(cond, runs_dir, backend)
        if m and s:
            s["window_s"] = float(m.group(1))
            rows.append(s)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Window sweep: start-up cost or per-event constant?")
    ap.add_argument("--window-dir", default="docs/results/window")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="docs/results/window/window_sweep.csv")
    args = ap.parse_args(argv)

    if not Path(args.window_dir).is_dir():
        print(f"missing window directory: {args.window_dir}")
        return 1

    for backend in ("kafka", "redis"):
        rows = collect(args.window_dir, args.runs_dir, backend)
        if not rows:
            print(f"== {backend}: no data ==")
            continue
        print(f"== {backend}: scheduling lag against observation window ==")
        for r in sorted(rows, key=lambda x: x["window_s"]):
            print(f"  window {r['window_s']:5.0f}s  runs={r['runs']}  "
                  f"events/run={r['events_per_run']:4d}  "
                  f"schedlag p50={r['schedlag_p50']:8.2f} ms  max={r['schedlag_max']:8.1f} ms")
        if backend == "kafka":
            tag, why = verdict(rows)
            print(f"\n== VERDICT: {tag} ==\n  {why}\n")
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            import csv
            with out.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=["window_s", "runs", "events_per_run",
                                                   "schedlag_p50", "schedlag_max"])
                w.writeheader()
                w.writerows(sorted(rows, key=lambda x: x["window_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
