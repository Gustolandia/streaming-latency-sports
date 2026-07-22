#!/usr/bin/env python3
"""
diagnose_tail.py
Locate a fixed latency mode in a run's per-event trace, and decide whether it is a start-up
artifact rather than steady-state behaviour.

Why this exists. Across every cloud concurrency level, Kafka's TTI p95 sat at 99-105 ms while
its median moved 1.8 -> 7.2 ms. A p95 pinned at the same value regardless of load is not
load-dependent behaviour; it is a fixed cost paid by a small fraction of events. That matters
because the equivalence tests operate on MEANS: a 100 ms mode in ~5% of observations adds ~5 ms
to every Kafka mean, and several reported differences are 0.3-3 ms. Until the mode is
identified and handled, no mean-based equivalence claim can be trusted.

The script answers three questions from the run artifacts alone:
  1. Is there a distinct high-latency mode, or just a heavy tail?
  2. Are the affected events concentrated at the START of the run (metadata fetch, consumer
     group join, first-poll rebalance) or spread through it (steady-state behaviour)?
  3. What does excluding a warm-up prefix do to the mean, the median, and the tail?

Question 2 is the decisive one. A start-up artifact is legitimately excludable under a
pre-registered warm-up rule; a mode spread evenly through the run is real and must be reported.

CLI:
    python scripts/diagnose_tail.py --run-dir runs/<run> --threshold-ms 50 --warmup 20
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def load_trace(run_dir):
    """Per-event latency in ms, ordered by scheduled emission; None if unreadable."""
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
    m = m.sort_values("t_prod_sched_ns").reset_index(drop=True)
    m["latency_ms"] = (m["t_output_ns"] - m["t_prod_sched_ns"]) / 1e6
    m["ordinal"] = np.arange(len(m))
    return m[["event_id", "ordinal", "latency_ms"]]


def mode_share(trace, threshold_ms):
    """Fraction of events above the threshold, and where they sit in the run."""
    if trace is None or trace.empty:
        return None
    hi = trace[trace["latency_ms"] >= threshold_ms]
    n = len(trace)
    return {
        "n_events": int(n),
        "n_above": int(len(hi)),
        "share_above": len(hi) / n,
        "median_ordinal_above": float(hi["ordinal"].median()) if len(hi) else float("nan"),
        "max_ordinal_above": int(hi["ordinal"].max()) if len(hi) else -1,
        # If every slow event lies in the first few percent of the run, it is start-up cost.
        "above_within_first_5pct": float((hi["ordinal"] < 0.05 * n).mean()) if len(hi) else 0.0,
    }


def warmup_effect(trace, warmup_events):
    """What excluding the first `warmup_events` does to mean, median and p95.

    Reported together deliberately: if the mean moves a lot while the median barely moves, the
    excluded events were a tail artifact rather than a shift in the underlying distribution.
    """
    if trace is None or trace.empty:
        return None
    full = trace["latency_ms"].values
    kept = trace[trace["ordinal"] >= warmup_events]["latency_ms"].values
    if len(kept) == 0:
        return None

    def stats(a):
        return (float(np.mean(a)), float(np.median(a)), float(np.percentile(a, 95)))

    fm, fmed, f95 = stats(full)
    km, kmed, k95 = stats(kept)
    return {
        "warmup_events": int(warmup_events),
        "n_full": int(len(full)), "n_kept": int(len(kept)),
        "mean_full": fm, "mean_kept": km, "mean_delta": km - fm,
        "median_full": fmed, "median_kept": kmed, "median_delta": kmed - fmed,
        "p95_full": f95, "p95_kept": k95, "p95_delta": k95 - f95,
    }


def classify(share):
    """Call the mode a start-up artifact only on evidence, not on convenience."""
    if share is None:
        return "no-data"
    if share["n_above"] == 0:
        return "no-mode"
    if share["above_within_first_5pct"] >= 0.9:
        return "startup-artifact"
    if share["above_within_first_5pct"] <= 0.2:
        return "steady-state"
    return "mixed"


def analyze(run_dirs, threshold_ms, warmup_events):
    rows = []
    for d in run_dirs:
        trace = load_trace(d)
        if trace is None:
            continue
        share = mode_share(trace, threshold_ms)
        eff = warmup_effect(trace, warmup_events)
        row = {"run_id": Path(d).name, "verdict": classify(share)}
        row.update(share or {})
        row.update(eff or {})
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Locate and classify a fixed latency mode")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--run-glob", default=None, help="glob under --runs-dir")
    ap.add_argument("--run-dir", action="append", default=[], help="explicit run dir(s)")
    ap.add_argument("--threshold-ms", type=float, default=50.0)
    ap.add_argument("--warmup", type=int, default=20, help="events to exclude as warm-up")
    ap.add_argument("--out", default="docs/results/tail")
    args = ap.parse_args(argv)

    dirs = list(args.run_dir)
    if args.run_glob:
        dirs += [str(p) for p in sorted(Path(args.runs_dir).glob(args.run_glob)) if p.is_dir()]
    if not dirs:
        print("No run directories selected")
        return 1

    df = analyze(dirs, args.threshold_ms, args.warmup)
    if df.empty:
        print("No readable runs")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "tail_diagnosis.csv", index=False)

    print(f"== fixed-mode diagnosis (threshold {args.threshold_ms:g} ms, "
          f"warm-up {args.warmup} events) ==")
    cols = ["run_id", "verdict", "n_events", "n_above", "share_above",
            "above_within_first_5pct", "mean_full", "mean_kept", "median_full", "median_kept"]
    print(df[[c for c in cols if c in df.columns]].to_string(index=False))
    print("\nverdicts:", dict(df["verdict"].value_counts()))
    print("startup-artifact => a pre-registered warm-up exclusion is defensible; "
          "steady-state => the mode is real and must be reported.")
    print(f"Wrote {out}/tail_diagnosis.csv")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
