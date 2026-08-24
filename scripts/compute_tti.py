#!/usr/bin/env python3
"""
Compute Time-to-Insight (TTI) metrics from producer and consumer CSV files.

Inputs:
- producer.csv: Output from kafka_producer.py or redis_producer.py
- consumer.csv: Output from kafka_consumer.py or redis_consumer.py

Output:
- tti_summary.json: Aggregated metrics (percentiles, max, missed window rates)

TTI = Time-to-Insight = t_output_ns - t_prod_sched_ns
Transport Latency = t_cons_recv_ns - t_prod_send_ns (or t_broker_ack_ns if available)
Producer Scheduling Lag = t_prod_send_ns - t_prod_sched_ns

Missed Window Rate: Fraction of events where TTI > window_threshold

Actionability Windows: 100ms, 250ms, 500ms, 1000ms, 2000ms, 5000ms
"""

import argparse
import csv
import json
from pathlib import Path
import numpy as np

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


def compute_metrics(tti_values_ms, transport_values_ms, schedlag_values_ms):
    """Compute percentiles and max for a set of values."""
    def stats(values):
        arr = np.array(values)
        return {
            "p50": float(np.median(arr)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(np.max(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
        }

    def missed_window_rate(values, window_ms):
        """Compute fraction of values exceeding window."""
        arr = np.array(values)
        return float(np.sum(arr > window_ms) / len(arr))

    result = {}

    # TTI metrics
    if tti_values_ms:
        result["tti_ms"] = stats(tti_values_ms)
        result["tti_ms"]["missed_window_rate"] = {}
        for window in [100, 250, 500, 1000, 2000, 5000]:
            result["tti_ms"]["missed_window_rate"][str(window)] = missed_window_rate(
                tti_values_ms, window
            )

    # Transport latency metrics
    if transport_values_ms:
        result["transport_ms"] = stats(transport_values_ms)

    # Producer scheduling lag metrics
    if schedlag_values_ms:
        result["producer_sched_lag_ms"] = stats(schedlag_values_ms)
        result["producer_sched_lag_ms"]["missed_window_rate"] = {}
        for window in [100, 250, 500, 1000, 2000, 5000]:
            result["producer_sched_lag_ms"]["missed_window_rate"][str(window)] = missed_window_rate(
                schedlag_values_ms, window
            )

    return result


def main():
    ap = argparse.ArgumentParser(
        description="Compute TTI metrics from producer and consumer CSV files"
    )
    ap.add_argument(
        "--producer", required=True, help="Path to producer CSV file"
    )
    ap.add_argument(
        "--consumer", required=True, help="Path to consumer CSV file"
    )
    ap.add_argument(
        "--out", required=True, help="Path to output JSON file"
    )
    args = ap.parse_args()

    producer_path = Path(args.producer)
    consumer_path = Path(args.consumer)
    out_path = Path(args.out)

    # Load producer data
    # Schema: run_id,backend,topic/stream,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns[,redis_id]
    producer_rows = {}
    with open(producer_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            event_id = row["event_id"]
            producer_rows[event_id] = {
                "event_id": event_id,
                "t_prod_sched_ns": int(row["t_prod_sched_ns"]),
                "t_prod_send_ns": int(row["t_prod_send_ns"]),
                "t_broker_ack_ns": (
                    int(row["t_broker_ack_ns"])
                    if row["t_broker_ack_ns"] and row["t_broker_ack_ns"] != "None"
                    else None
                ),
            }

    # Load consumer data
    # Schema: run_id,backend,topic/stream,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns[,redis_id]
    consumer_rows = {}
    with open(consumer_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            event_id = row["event_id"]
            consumer_rows[event_id] = {
                "event_id": event_id,
                "t_cons_recv_ns": int(row["t_cons_recv_ns"]),
                "t_output_ns": int(row["t_output_ns"]),
            }

    # Match events and compute metrics
    n_produced = len(producer_rows)
    n_consumed = len(consumer_rows)

    tti_values_ms = []
    transport_values_ms = []
    schedlag_values_ms = []
    n_matched = 0

    for event_id, prod in producer_rows.items():
        if event_id in consumer_rows:
            cons = consumer_rows[event_id]
            n_matched += 1

            # TTI = t_output_ns - t_prod_sched_ns
            tti_ns = cons["t_output_ns"] - prod["t_prod_sched_ns"]
            tti_values_ms.append(now_ms(tti_ns))

            # Transport latency = t_cons_recv_ns - t_broker_ack_ns (if available) or t_prod_send_ns
            if prod["t_broker_ack_ns"] is not None:
                transport_ns = cons["t_cons_recv_ns"] - prod["t_broker_ack_ns"]
            else:
                transport_ns = cons["t_cons_recv_ns"] - prod["t_prod_send_ns"]
            transport_values_ms.append(now_ms(transport_ns))

            # Producer scheduling lag = t_prod_send_ns - t_prod_sched_ns
            schedlag_ns = prod["t_prod_send_ns"] - prod["t_prod_sched_ns"]
            schedlag_values_ms.append(now_ms(schedlag_ns))

    # Compute aggregated metrics
    metrics = compute_metrics(tti_values_ms, transport_values_ms, schedlag_values_ms)

    # Build output
    result = {
        "n_produced": n_produced,
        "n_consumed": n_consumed,
        "n_matched": n_matched,
    }
    result.update(metrics)

    # Write output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Computed TTI metrics: {n_matched}/{n_produced} events matched")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
