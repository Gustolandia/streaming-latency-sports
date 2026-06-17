import argparse, csv, json, time, threading, heapq
import pandas as pd
from pathlib import Path
from kafka import KafkaProducer

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass


def now_ns() -> int:
    # perf_counter_ns() is monotonic and high-resolution (good for timing comparisons)
    return time.perf_counter_ns()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3],
                    help="Number of Kafka brokers (1=single, 3=cluster)")
    ap.add_argument("--speedup", type=float, default=120.0, help="120 = 120x faster than real-time")
    ap.add_argument("--max-t-sim", type=int, default=600, help="only replay events with t_sim_seconds <= this")

    # --- S3 knobs (no behavior change unless enabled) ---
    ap.add_argument(
        "--s3-mode",
        default="none",
        choices=["none", "baseline", "corrections"],
        help="S3: add envelope fields; optionally emit correction messages",
    )
    ap.add_argument(
        "--corrections-every-k",
        type=int,
        default=0,
        help="S3 corrections: every k-th event (0 disables)",
    )
    ap.add_argument(
        "--correction-delay-s",
        type=float,
        default=0.0,
        help="S3 corrections: wall delay after base planned emit time (seconds)",
    )

    # --- sensitivity knobs (defaults match your CURRENT behavior) ---
    ap.add_argument("--acks", default="all", choices=["0", "1", "all"])
    ap.add_argument("--linger-ms", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=None, help="bytes; if omitted, use client default")
    ap.add_argument("--compression-type", default=None, choices=["gzip", "snappy", "lz4", "zstd"])
    ap.add_argument("--max-inflight", type=int, default=1, help="1 matches sync-send; >1 enables more in-flight requests")

    args = ap.parse_args()

    plan = pd.read_csv(args.plan_csv)
    plan = plan[plan["t_sim_seconds"] <= args.max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    acks_val = args.acks
    if acks_val in ("0", "1"):
        acks_val = int(acks_val)

    # Multi-broker support: use different bootstrap servers based on broker count
    if args.broker_count == 3:
        bootstrap_servers = args.bootstrap if args.bootstrap else "kafka1:29092,kafka2:29092,kafka3:29092"
    else:
        bootstrap_servers = args.bootstrap if args.bootstrap else "localhost:9092"

    producer_kwargs = dict(
        bootstrap_servers=bootstrap_servers,
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

    # Producer time origins:
    # - t0_mono: time.monotonic() reference used for sleep scheduling
    # - t0_wall_ns: perf_counter_ns() reference used to compute planned emit ns in the same monotonic domain
    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

    ack_ns = {}
    ack_lock = threading.Lock()
    errors = []
    err_lock = threading.Lock()
    pending = []

    def on_ack(event_id: str):
        with ack_lock:
            ack_ns[event_id] = now_ns()

    def on_err(event_id: str, exc: Exception):
        with err_lock:
            errors.append((event_id, repr(exc)))

    # ---- S3 corrections scheduler (optional) ----
    corr_enabled = (
        args.s3_mode == "corrections"
        and int(args.corrections_every_k) > 0
        and float(args.correction_delay_s) >= 0.0  # Allow zero delay
    )

    # heap entries: (target_mono, seq, corr_event_id, corr_msg, corr_sched_ns, match_id, t_sim, t_emit_offset_s)
    jobs_cv = threading.Condition()
    jobs_heap = []
    jobs_seq = 0
    jobs_done = False

    corr_rows = []

    def corr_worker():
        nonlocal jobs_done
        while True:
            with jobs_cv:
                while not jobs_heap and not jobs_done:
                    jobs_cv.wait()
                if jobs_done and not jobs_heap:
                    return

                target_mono, _seq, corr_event_id, corr_msg, corr_sched_ns, match_id, t_sim, t_emit_offset_s = jobs_heap[0]
                now_m = time.monotonic()
                if target_mono > now_m:
                    jobs_cv.wait(timeout=target_mono - now_m)
                    continue

                heapq.heappop(jobs_heap)

            # Send outside lock
            t_prod_send_ns = now_ns()
            fut = producer.send(args.topic, key=corr_event_id, value=corr_msg)
            fut.add_callback(lambda _meta, eid=corr_event_id: on_ack(eid))
            fut.add_errback(lambda exc, eid=corr_event_id: on_err(eid, exc))
            fut.get(timeout=30)

            corr_rows.append(
                {
                    "run_id": args.run_id,
                    "backend": "kafka",
                    "topic": args.topic,
                    "event_id": corr_event_id,
                    "match_id": match_id,
                    "t_sim_seconds": t_sim,
                    "t_emit_offset_s": t_emit_offset_s,
                    "t_prod_sched_ns": corr_sched_ns,
                    "t_prod_send_ns": t_prod_send_ns,
                    "t_broker_ack_ns": None,
                }
            )

    t_corr = None
    if corr_enabled:
        t_corr = threading.Thread(target=corr_worker, daemon=True)
        t_corr.start()

    # ---- main send loop ----
    rows = []
    for i, r in plan.iterrows():
        event_id = str(r["event_id"])
        match_id = int(r["match_id"])
        t_sim = int(r["t_sim_seconds"])
        t_emit_offset_s = float(r["t_emit_offset_s"])

        # schedule base event
        target_mono = t0_mono + (t_emit_offset_s / args.speedup)
        sleep_s = target_mono - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)

        t_prod_sched_ns = t0_wall_ns + int((t_emit_offset_s / args.speedup) * 1e9)
        t_prod_send_ns = now_ns()

        # stable S3 linkage id (does not change existing event_id semantics)
        s3_uid = f"{match_id}:{event_id}"

        msg = {
            "run_id": args.run_id,
            "match_id": match_id,
            "event_id": event_id,
            "t_sim_seconds": t_sim,
            "t_emit_offset_s": t_emit_offset_s,
            # S3 additions (always present; harmless for S2/S1 consumers that ignore unknown keys)
            "t_emit_planned_ns": t_prod_sched_ns,
            "s3_uid": s3_uid,
            "s3_rev": 1,
            "s3_is_correction": False,
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

        rows.append(
            {
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
            }
        )

        # schedule correction (S3) deterministically by row index (every k-th base event)
        if corr_enabled and ((i + 1) % int(args.corrections_every_k) == 0):
            corr_event_id = f"{event_id}__rev2"
            corr_sched_ns = t_prod_sched_ns + int(float(args.correction_delay_s) * 1e9)
            corr_target_mono = target_mono + float(args.correction_delay_s)

            corr_msg = {
                "run_id": args.run_id,
                "match_id": match_id,
                "event_id": corr_event_id,
                "t_sim_seconds": t_sim,
                "t_emit_offset_s": t_emit_offset_s,
                "t_emit_planned_ns": corr_sched_ns,
                "s3_uid": s3_uid,
                "s3_rev": 2,
                "s3_is_correction": True,
                "s3_correction_delay_s": float(args.correction_delay_s),
            }

            with jobs_cv:
                jobs_seq += 1
                heapq.heappush(
                    jobs_heap,
                    (corr_target_mono, jobs_seq, corr_event_id, corr_msg, corr_sched_ns, match_id, t_sim, t_emit_offset_s),
                )
                jobs_cv.notify()

    # wait for any in-flight base sends
    for fut in pending:
        fut.get(timeout=30)

    # finish corrections (if enabled)
    if corr_enabled:
        with jobs_cv:
            jobs_done = True
            jobs_cv.notify_all()
        assert t_corr is not None
        t_corr.join()
        rows.extend(corr_rows)

    producer.flush()

    with err_lock:
        if errors:
            raise RuntimeError(f"Kafka producer errors (first 5): {errors[:5]}")

    with ack_lock:
        for row in rows:
            row["t_broker_ack_ns"] = ack_ns.get(row["event_id"])

    # Output CSV schema is unchanged (we keep the original columns)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "run_id",
                "backend",
                "topic",
                "event_id",
                "match_id",
                "t_sim_seconds",
                "t_emit_offset_s",
                "t_prod_sched_ns",
                "t_prod_send_ns",
                "t_broker_ack_ns",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"OK kafka producer: wrote {len(rows)} rows -> {out_path}")


if __name__ == "__main__":
    main()
