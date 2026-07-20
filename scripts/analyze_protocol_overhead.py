#!/usr/bin/env python3
"""
Issue 3 - Protocol overhead & true message-size analysis.

The original benchmark logged neither serialized message size nor
serialization/deserialization timing. This script closes that fairness gap by
reconstructing the JSON event payload from a run's producer.csv (the same
envelope the producers emit) and measuring, per event:
  * true serialized message size in bytes (len(json.dumps(event)))
  * serialization time   (json.dumps)
  * deserialization time (json.loads)

Aggregated p50/p95/mean are written per run / per backend.

CLI:
    python scripts/analyze_protocol_overhead.py [--runs-dir runs] [--pattern 'batch*'] \
        [--iterations 50] [--out docs/results/protocol_overhead]
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Columns that form the message envelope (everything else is benchmark bookkeeping).
ENVELOPE_COLS = [
    "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
    "t_prod_sched_ns", "s3_uid", "s3_rev", "s3_is_correction",
]


def event_payload(row, columns=None):
    """Reconstruct the JSON-serializable event dict from a producer.csv row."""
    cols = columns or ENVELOPE_COLS
    payload = {}
    for c in cols:
        if c in row and pd.notna(row[c]):
            val = row[c]
            payload[c] = val.item() if hasattr(val, "item") else val
    return payload


def measure_event(payload, iterations=50):
    """Measure serialized size and (de)serialization time for one payload."""
    iterations = max(1, iterations)
    text = json.dumps(payload)
    size = len(text.encode("utf-8"))

    t0 = time.perf_counter_ns()
    for _ in range(iterations):
        json.dumps(payload)
    ser_ns = (time.perf_counter_ns() - t0) / iterations

    t0 = time.perf_counter_ns()
    for _ in range(iterations):
        json.loads(text)
    deser_ns = (time.perf_counter_ns() - t0) / iterations

    return {"size_bytes": size, "serialize_ns": ser_ns, "deserialize_ns": deser_ns}


def _agg(values):
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return {"p50": float("nan"), "p95": float("nan"), "mean": float("nan")}
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "mean": float(arr.mean()),
    }


def analyze_run(producer_csv, iterations=50, sample=None):
    """Analyze one producer.csv; returns per-metric aggregates, or None if unusable."""
    producer_csv = Path(producer_csv)
    if not producer_csv.exists():
        return None
    try:
        df = pd.read_csv(producer_csv)
    except (ValueError, OSError):
        return None
    if df.empty:
        return None
    if sample is not None and sample < len(df):
        df = df.head(sample)

    cols = [c for c in ENVELOPE_COLS if c in df.columns]
    sizes, ser, deser = [], [], []
    for _, row in df.iterrows():
        m = measure_event(event_payload(row, cols), iterations)
        sizes.append(m["size_bytes"])
        ser.append(m["serialize_ns"])
        deser.append(m["deserialize_ns"])

    return {
        "n_events": len(df),
        "message_size_bytes": _agg(sizes),
        "serialize_ns": _agg(ser),
        "deserialize_ns": _agg(deser),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Protocol overhead & message-size analysis (Issue 3)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="batch*")
    ap.add_argument("--iterations", type=int, default=50)
    ap.add_argument("--sample", type=int, default=500,
                    help="Max events per run to measure (for speed)")
    ap.add_argument("--out", default="docs/results/protocol_overhead")
    args = ap.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    rows = []
    for run_dir in sorted(runs_dir.glob(args.pattern)):
        if not run_dir.is_dir():
            continue
        res = analyze_run(run_dir / "producer.csv", args.iterations, args.sample)
        if res is None:
            continue
        backend = "kafka" if "kafka" in run_dir.name else "redis" if "redis" in run_dir.name else "unknown"
        rows.append({
            "run_id": run_dir.name,
            "backend": backend,
            "n_events": res["n_events"],
            "msg_size_p50": res["message_size_bytes"]["p50"],
            "serialize_ns_p50": res["serialize_ns"]["p50"],
            "deserialize_ns_p50": res["deserialize_ns"]["p50"],
        })

    if not rows:
        print(f"No usable runs matched {args.pattern} in {runs_dir}")
        return 1

    df = pd.DataFrame(rows)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "protocol_overhead_by_run.csv", index=False)
    by_backend = df.groupby("backend")[["msg_size_p50", "serialize_ns_p50", "deserialize_ns_p50"]].mean()
    by_backend.to_csv(out_dir / "protocol_overhead_by_backend.csv")

    print(f"Analyzed {len(df)} runs. Mean by backend:")
    print(by_backend.to_string())
    print(f"Wrote results to {out_dir}/")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
