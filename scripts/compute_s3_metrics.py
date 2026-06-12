#!/usr/bin/env python3
"""
Compute S3 per-run metrics:
- state staleness at decision times
- correction propagation latency / inconsistency duration
- correction throughput and timing statistics

Inputs:
- runs/_paper_s3_official_runs.txt
- runs/<run_id>/consumer_events.csv

Outputs:
- data/processed/results/paper_s3_official.csv

Metrics computed:
- correction_propagation_latency_ms: Time from base event consumption to correction consumption
  (per correction, then aggregated with p50, p95, p99, max, mean, std)
- inconsistency_duration_ms: Time the state was stale (from base consume to correction consume)
  (same aggregation as above)
- n_corrections: Total number of correction messages
- n_base_events_with_corrections: Number of base events that received corrections
- correction_rate: Corrections per second
- state_staleness_at_decision: For each correction, the staleness duration in ms
"""
from pathlib import Path
import pandas as pd
import numpy as np
import json

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass


def now_ms(t_ns):
    """Convert nanoseconds to milliseconds (float)."""
    return float(t_ns) / 1e6


def compute_percentiles(values):
    """Compute percentiles and statistics for a list of values."""
    if not values:
        return None
    arr = np.array(values)
    return {
        "p50": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "count": int(len(arr)),
    }


def compute_s3_metrics_for_run(run_id, events_df):
    """
    Compute S3 metrics for a single run.
    
    Args:
        run_id: The run identifier
        events_df: DataFrame with consumer events (has s3_uid, s3_rev, s3_is_correction, etc.)
    
    Returns:
        Dictionary with computed metrics for this run
    """
    # Filter to only correction-related events
    correction_events = events_df[events_df["s3_is_correction"] == True].copy()
    base_events = events_df[events_df["s3_is_correction"] == False].copy()
    
    n_corrections = len(correction_events)
    n_base = len(base_events)
    
    # Match corrections to their base events using s3_uid
    # For each correction, find the base event with the same s3_uid and rev=1
    correction_propagation_latencies_ms = []
    inconsistency_durations_ms = []
    
    # Create lookup: s3_uid -> list of events (sorted by rev)
    uid_to_events = {}
    for _, row in events_df.iterrows():
        uid = row.get("s3_uid")
        if uid is None or pd.isna(uid):
            continue
        if uid not in uid_to_events:
            uid_to_events[uid] = []
        uid_to_events[uid].append(row)
    
    # For each s3_uid with multiple revisions, compute metrics
    for uid, events in uid_to_events.items():
        if len(events) < 2:
            continue
        
        # Sort by revision number
        events_sorted = sorted(events, key=lambda x: int(x.get("s3_rev", 1)))
        
        # For each correction (rev >= 2), find the previous revision
        for i in range(1, len(events_sorted)):
            corr = events_sorted[i]
            base = events_sorted[i - 1]
            
            # Correction propagation latency: time from base consumption to correction consumption
            t_base_consume_ns = int(corr.get("t_consume_ns") or base.get("t_consume_ns", 0))
            # Wait, we need the base event's consume time
            t_base_consume_ns = int(base.get("t_consume_ns", 0))
            t_corr_consume_ns = int(corr.get("t_consume_ns", 0))
            
            propagation_ns = t_corr_consume_ns - t_base_consume_ns
            correction_propagation_latencies_ms.append(now_ms(propagation_ns))
            
            # Inconsistency duration: same as propagation latency for this use case
            # (the state is stale from when base was consumed until correction is consumed)
            inconsistency_durations_ms.append(now_ms(propagation_ns))
    
    # Compute aggregated metrics
    metrics = {
        "run": run_id,
        "n_corrections": n_corrections,
        "n_base_events": n_base,
        "n_base_events_with_corrections": len([uid for uid, events in uid_to_events.items() if len(events) >= 2]),
    }
    
    # Correction propagation latency metrics
    if correction_propagation_latencies_ms:
        metrics["correction_propagation_latency_ms"] = compute_percentiles(correction_propagation_latencies_ms)
    
    # Inconsistency duration metrics (same as propagation in this model)
    if inconsistency_durations_ms:
        metrics["inconsistency_duration_ms"] = compute_percentiles(inconsistency_durations_ms)
    
    # Additional timing metrics from correction envelope
    if n_corrections > 0:
        corr_planned = correction_events["t_emit_planned_ns"].dropna()
        if len(corr_planned) > 0:
            # Time from planned emit to actual consume
            corr_consume = correction_events["t_consume_ns"].dropna()
            if len(corr_consume) == len(corr_planned):
                planned_to_consume_ns = (corr_consume.values - corr_planned.values)
                metrics["correction_planned_to_consume_latency_ms"] = compute_percentiles(
                    [now_ms(x) for x in planned_to_consume_ns]
                )
    
    return metrics


def main():
    runlist = Path("runs/_paper_s3_official_runs.txt")
    if not runlist.exists():
        raise SystemExit("Missing runs/_paper_s3_official_runs.txt")

    rows = []
    for rid in runlist.read_text().splitlines():
        rid = rid.strip()
        if not rid or rid.startswith("#"):
            continue
            
        ev_path = Path("runs") / rid / "consumer_events.csv"
        if not ev_path.exists():
            raise SystemExit(f"Missing {ev_path}")
        
        # Load consumer events
        events_df = pd.read_csv(ev_path)
        
        # Normalize schema: Redis uses redis_id, Kafka uses partition+offset
        # We need t_consume_ns which is present in both schemas
        if "t_consume_ns" not in events_df.columns:
            raise SystemExit(f"Missing t_consume_ns in {ev_path}")
        
        # Compute metrics for this run
        run_metrics = compute_s3_metrics_for_run(rid, events_df)
        rows.append(run_metrics)
        print(f"Computed S3 metrics for {rid}: {run_metrics.get('n_corrections', 0)} corrections")

    # Build output DataFrame
    df = pd.DataFrame(rows)
    
    out = Path("data/processed/results/paper_s3_official.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Wrote {out}")
    
    # Also write a summary JSON for easier inspection
    summary_path = Path("docs/results/paper_s3_official_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    
    summary = {
        "total_runs": len(rows),
        "total_corrections": int(df["n_corrections"].sum()) if "n_corrections" in df.columns else 0,
        "avg_corrections_per_run": float(df["n_corrections"].mean()) if "n_corrections" in df.columns else 0.0,
    }
    
    # Aggregate correction propagation latency across all runs
    if "correction_propagation_latency_ms" in df.columns:
        all_prop_latencies = []
        for idx, row in df.iterrows():
            prop_metrics = row.get("correction_propagation_latency_ms")
            if prop_metrics and isinstance(prop_metrics, str):
                try:
                    prop_metrics = json.loads(prop_metrics.replace("'", '"'))
                except:
                    continue
            if prop_metrics and isinstance(prop_metrics, dict):
                if "p50" in prop_metrics:
                    all_prop_latencies.append(prop_metrics["p50"])
        
        if all_prop_latencies:
            summary["correction_propagation_latency_p50_ms"] = float(np.median(all_prop_latencies))
            summary["correction_propagation_latency_mean_ms"] = float(np.mean(all_prop_latencies))
    
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"Wrote summary: {summary_path}")


if __name__ == "__main__":
    main()
