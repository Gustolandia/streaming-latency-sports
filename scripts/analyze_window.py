#!/usr/bin/env python3
"""
analyze_window.py
Test whether the ~103 ms Kafka producer offset is a per-event constant or a per-run start-up
cost that a short observation window mistakes for one.

The E1 corpus behind the paper's original headline matched a median of seven events per run.
Those events are the match's opening burst, emitted immediately after producer start, and
Kafka's first send pays metadata fetch and topic creation while Redis's XADD does not.

The verdict is decided on the NUMBER of affected events per run, not on the median. A per-run
start-up cost predicts that number is fixed however long the run gets; a per-event constant
predicts it grows with the run. The median cannot separate the two on its own, because how much
of the cost the median sees depends entirely on how many events the run contains -- which is
exactly the trap the original result fell into.

Reads the per-run tti_summary.json for the percentiles and the per-event loop traces for the
counts, so the reported medians and the verdict come from independent instrumentation.

CLI:
    python scripts/analyze_window.py --window-dir docs/results/window --runs-dir runs
"""
import argparse
import csv
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


def trace_stats(window_dir, window_s, backend="kafka", threshold_ms=50.0):
    """Per-run counts of affected events, read from the per-event loop traces.

    Two columns matter. `produce_ms` is how long the send call itself blocked: the first send
    pays metadata fetch and topic creation. `wake_late_ms` is how late the loop woke for an
    event: while the single-threaded loop sits inside that first blocking send, every event due
    in the meantime wakes late by roughly the same amount. The first is the cause, the second is
    what the paper measured.
    """
    pat = os.path.join(window_dir, f"trace_w{int(window_s)}_*_{backend}_*.csv")
    runs = []
    for path in sorted(glob.glob(pat)):
        wake, produce = [], []
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    try:
                        wake.append(float(r["wake_late_ms"]))
                        produce.append(float(r["produce_ms"]))
                    except (KeyError, TypeError, ValueError):
                        continue
        except OSError:
            continue
        if wake:
            runs.append((len(wake),
                         sum(1 for x in wake if x > threshold_ms),
                         sum(1 for x in produce if x > threshold_ms)))
    if not runs:
        return None
    return {
        "trace_runs": len(runs),
        "trace_events": int(st.median([r[0] for r in runs])),
        "slow_wake": st.median([r[1] for r in runs]),
        "slow_produce": st.median([r[2] for r in runs]),
    }


def verdict(rows, growth_factor=2.0, tolerance=1.5):
    """Per-event constant, or per-run start-up cost?

    Decided on the count of affected events. If the run grows by a factor and the count does not
    follow, the cost is paid per run; if the count grows with it, every event pays.
    """
    usable = [r for r in sorted(rows, key=lambda r: r["window_s"]) if r.get("slow_wake")]
    if len(usable) < 2:
        return "INCONCLUSIVE", "need at least two windows with per-event traces"
    first, last = usable[0], usable[-1]
    grew = last["trace_events"] / first["trace_events"]
    if grew < growth_factor:
        return "INCONCLUSIVE", (f"the run only grew {grew:.1f}x between the narrowest and widest "
                                f"window, too little to separate the two explanations")
    scaled = last["slow_wake"] / first["slow_wake"]
    common = (f"events per run grew {grew:.1f}x ({first['trace_events']} to "
              f"{last['trace_events']}) while the number waking more than 50 ms late went "
              f"{first['slow_wake']:.0f} to {last['slow_wake']:.0f}")
    if scaled <= tolerance:
        return ("START-UP COST",
                f"{common}: the count is fixed, so the cost is paid once per run and the share "
                f"of events paying it falls from {first['slow_wake'] / first['trace_events']:.1%}"
                f" to {last['slow_wake'] / last['trace_events']:.1%}")
    if scaled >= grew / tolerance:
        return ("PER-EVENT CONSTANT",
                f"{common}: the count grows with the run, so every event pays")
    return ("INCONCLUSIVE",
            f"{common}: the count grows, but neither in proportion nor flat")


def collect(window_dir, runs_dir, backend="kafka"):
    rows = []
    for cond in sorted(glob.glob(os.path.join(window_dir, "w*"))):
        if not os.path.isdir(cond):
            continue
        m = re.search(r"w(\d+)$", os.path.basename(cond))
        s = window_stats(cond, runs_dir, backend)
        if m and s:
            s["window_s"] = float(m.group(1))
            # None, not zero. A backend with no loop trace has not been measured to have no
            # late events -- it has not been measured at all, and printing 0 there would
            # manufacture a finding out of missing instrumentation. redis_producer.py was
            # untraced when this sweep ran, and the first draft of this table duly reported
            # Redis as having zero blocking sends, which was not something anyone had observed.
            s.update(trace_stats(window_dir, s["window_s"], backend)
                     or {"trace_runs": 0, "trace_events": None,
                         "slow_wake": None, "slow_produce": None})
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
            counted = (f"events >50 ms late={r['slow_wake']:4.1f}  "
                       f"blocking sends={r['slow_produce']:4.1f}"
                       if r["slow_wake"] is not None else "(no loop trace)")
            print(f"  window {r['window_s']:5.0f}s  runs={r['runs']}  "
                  f"events/run={r['events_per_run']:4d}  "
                  f"schedlag p50={r['schedlag_p50']:8.2f} ms  max={r['schedlag_max']:8.1f} ms  "
                  f"{counted}")
        if backend == "kafka":
            tag, why = verdict(rows)
            print(f"\n== VERDICT: {tag} ==\n  {why}\n")
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=["window_s", "runs", "events_per_run",
                                                   "schedlag_p50", "schedlag_max",
                                                   "trace_runs", "trace_events",
                                                   "slow_wake", "slow_produce"])
                w.writeheader()
                w.writerows(sorted(rows, key=lambda x: x["window_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
