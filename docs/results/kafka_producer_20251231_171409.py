import argparse, csv, json, time, threading
from pathlib import Path
import pandas as pd
from kafka import KafkaProducer

def now_ns() -> int:
    return time.perf_counter_ns()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--speedup", type=float, default=120.0, help="120 = 120x faster than real-time")
    ap.add_argument("--max-t-sim", type=int, default=600, help="only replay events with t_sim_seconds <= this")

    # --- sensitivity knobs (defaults match your CURRENT behavior) ---
    ap.add_argument("--acks", default="all", choices=["0","1","all"])
    ap.add_argument("--linger-ms", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=None, help="bytes; if omitted, use client default")
    ap.add_argument("--compression-type", default=None, choices=["gzip","snappy","lz4","zstd"])
    ap.add_argument("--max-inflight", type=int, default=1, help="1 matches current sync-send behavior; >1 enables more in-flight requests")

    args = ap.parse_args()

    plan = pd.read_csv(args.plan_csv)
    plan = plan[plan["t_sim_seconds"] <= args.max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    acks_val = args.acks
    if acks_val in ("0", "1"):
        acks_val = int(acks_val)

    producer_kwargs = dict(
        bootstrap_servers=[args.bootstrap],
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        acks=acks_val,
        linger_ms=args.linger_ms,
        max_in_flight_requests_per_connection=max(1, int(args.max_inflight)),
    )
    if args.batch_size is not None:
        producer_kwargs["batch_size"] = int(args.batch_size)
    if args.compression_type is not None:
        producer_kwargs["compression_type"] = args.compression_type

    producer = KafkaProducer(**producer_kwargs)

    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

    ack_ns = {}
    ack_lock = threading.Lock()
    errors = []
    err_lock = threading.Lock()

    rows = []
    pending = []  # list of futures

    def on_ack(event_id: str):
        with ack_lock:
            ack_ns[event_id] = now_ns()

    def on_err(event_id: str, exc: Exception):
        with err_lock:
            errors.append((event_id, repr(exc)))

    sent = 0
    for _, r in plan.iterrows():
        event_id = str(r["event_id"])
        match_id = int(r["match_id"])
        t_sim = int(r["t_sim_seconds"])
        t_emit_offset_s = float(r["t_emit_offset_s"])

        target_mono = t0_mono + (t_emit_offset_s / args.speedup)
        sleep_s = target_mono - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)

        t_prod_sched_ns = t0_wall_ns + int((t_emit_offset_s / args.speedup) * 1e9)
        t_prod_send_ns = now_ns()

        msg = {
            "run_id": args.run_id,
            "match_id": match_id,
            "event_id": event_id,
            "t_sim_seconds": t_sim,
            "t_emit_offset_s": t_emit_offset_s,
        }

        fut = producer.send(args.topic, key=event_id, value=msg)
        fut.add_callback(lambda _meta, eid=event_id: on_ack(eid))
        fut.add_errback(lambda exc, eid=event_id: on_err(eid, exc))

        if args.max_inflight <= 1:
            fut.get(timeout=30)
        else:
            pending.append(fut)
            if len(pending) >= args.max_inflight:
                pending.pop(0).get(timeout=30)

        rows.append({
            "run_id": args.run_id,
            "backend": "kafka",
            "topic": args.topic,
            "event_id": event_id,
            "match_id": match_id,
            "t_sim_seconds": t_sim,
            "t_emit_offset_s": t_emit_offset_s,
            "t_prod_sched_ns": t_prod_sched_ns,
            "t_prod_send_ns": t_prod_send_ns,
            "t_broker_ack_ns": None,
        })
        sent += 1

    for fut in pending:
        fut.get(timeout=30)
    producer.flush()

    with err_lock:
        if errors:
            raise RuntimeError(f"Kafka producer errors (first 5): {errors[:5]}")

    with ack_lock:
        for row in rows:
            row["t_broker_ack_ns"] = ack_ns.get(row["event_id"])

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id","backend","topic","event_id","match_id",
            "t_sim_seconds","t_emit_offset_s",
            "t_prod_sched_ns","t_prod_send_ns","t_broker_ack_ns",
        ])
        w.writeheader()
        w.writerows(rows)

    print(f"OK kafka producer: wrote {sent} rows -> {out_path}")

if __name__ == "__main__":
    main()
