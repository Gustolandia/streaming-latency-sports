#!/usr/bin/env python3
import argparse, csv, json, time
from pathlib import Path
from kafka import KafkaConsumer

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass


def now_ns() -> int:
    # Wall-clock epoch ns (time.time_ns), NOT perf_counter_ns: must share one epoch
    # with the producer process so consumer_ts - producer_ts is a valid latency.
    return time.time_ns()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3],
                    help="Number of Kafka brokers (1=single, 3=cluster)")
    ap.add_argument("--group", default=None)
    ap.add_argument("--idle-seconds", type=int, default=15)

    # --- sensitivity knobs (defaults match current behavior) ---
    ap.add_argument("--consumer-timeout-ms", type=int, default=1000)
    ap.add_argument("--poll-timeout-ms", type=int, default=1000, help="e.g. 50")
    ap.add_argument("--max-poll-records", type=int, default=None)

    args = ap.parse_args()

    group_id = args.group or f"sb-consumer-{args.run_id}"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- S3: consumer event log (for staleness + correction metrics) ---
    # Contract used by scripts/build_paper_s3_outputs.sh + scripts/compute_s3_metrics.py
    events_path = Path("runs") / args.run_id / "consumer_events.csv"
    events_path.parent.mkdir(parents=True, exist_ok=True)

    # Multi-broker support: use different bootstrap servers based on broker count
    if args.broker_count == 3:
        bootstrap_servers = args.bootstrap if args.bootstrap else "kafka1:29092,kafka2:29092,kafka3:29092"
    else:
        bootstrap_servers = args.bootstrap if args.bootstrap else "localhost:9092"

    consumer = KafkaConsumer(
        args.topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        consumer_timeout_ms=args.consumer_timeout_ms,
    )

    last_msg = time.monotonic()
    n = 0
    events_n = 0

    with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
        "w", newline="", encoding="utf-8"
    ) as f_events:
        # Existing (S2-compatible) output
        w = csv.DictWriter(
            f_out,
            fieldnames=[
                "run_id",
                "backend",
                "topic",
                "event_id",
                "match_id",
                "t_sim_seconds",
                "t_cons_recv_ns",
                "t_output_ns",
            ],
        )
        w.writeheader()

        # New (S3) consumer event log
        ew = csv.DictWriter(
            f_events,
            fieldnames=[
                "run_id",
                "backend",
                "topic",
                "partition",
                "offset",
                "t_consume_ns",
                "event_id",
                "match_id",
                "t_sim_seconds",
                "t_emit_offset_s",
                "t_emit_planned_ns",
                "s3_uid",
                "s3_rev",
                "s3_is_correction",
            ],
        )
        ew.writeheader()

        while True:
            poll_kwargs = dict(timeout_ms=args.poll_timeout_ms)
            if args.max_poll_records is not None:
                poll_kwargs["max_records"] = args.max_poll_records

            records = consumer.poll(**poll_kwargs)

            if not records:
                if (time.monotonic() - last_msg) >= args.idle_seconds:
                    break
                continue

            for _tp, msgs in records.items():
                for msg in msgs:
                    v = msg.value
                    if v.get("run_id") != args.run_id:
                        continue

                    last_msg = time.monotonic()

                    # Single timestamp used for S3 log; keep existing fields too.
                    t_consume_ns = now_ns()
                    t_cons_recv_ns = t_consume_ns
                    t_output_ns = now_ns()

                    # S2-compatible output row
                    w.writerow(
                        {
                            "run_id": v.get("run_id"),
                            "backend": "kafka",
                            "topic": args.topic,
                            "event_id": v.get("event_id"),
                            "match_id": v.get("match_id"),
                            "t_sim_seconds": v.get("t_sim_seconds"),
                            "t_cons_recv_ns": t_cons_recv_ns,
                            "t_output_ns": t_output_ns,
                        }
                    )

                    # S3 consumer event log row (fields may be absent for older messages; that is OK)
                    ew.writerow(
                        {
                            "run_id": v.get("run_id"),
                            "backend": "kafka",
                            "topic": getattr(msg, "topic", args.topic),
                            "partition": getattr(msg, "partition", None),
                            "offset": getattr(msg, "offset", None),
                            "t_consume_ns": t_consume_ns,
                            "event_id": v.get("event_id"),
                            "match_id": v.get("match_id"),
                            "t_sim_seconds": v.get("t_sim_seconds"),
                            "t_emit_offset_s": v.get("t_emit_offset_s"),
                            "t_emit_planned_ns": v.get("t_emit_planned_ns"),
                            "s3_uid": v.get("s3_uid"),
                            "s3_rev": v.get("s3_rev"),
                            "s3_is_correction": v.get("s3_is_correction"),
                        }
                    )

                    n += 1
                    events_n += 1
                    if events_n % 2000 == 0:
                        f_events.flush()
                        f_out.flush()

    consumer.close()
    print(f"OK kafka consumer: wrote {n} rows -> {out_path}")
    print(f"OK kafka consumer: wrote {events_n} rows -> {events_path}")


if __name__ == "__main__":
    main()
