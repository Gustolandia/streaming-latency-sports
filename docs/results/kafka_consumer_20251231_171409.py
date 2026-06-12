import argparse, csv, json, time
from pathlib import Path
from kafka import KafkaConsumer

def now_ns() -> int:
    return time.perf_counter_ns()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--group", default=None)
    ap.add_argument("--idle-seconds", type=int, default=15)

    # --- sensitivity knobs (defaults match your CURRENT behavior) ---
    ap.add_argument("--consumer-timeout-ms", type=int, default=1000)
    ap.add_argument("--poll-timeout-ms", type=int, default=1000, help="LOW-POLL sensitivity: e.g. 50")
    ap.add_argument("--max-poll-records", type=int, default=None)

    args = ap.parse_args()

    group_id = args.group or f"sb-consumer-{args.run_id}"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    consumer = KafkaConsumer(
        args.topic,
        bootstrap_servers=[args.bootstrap],
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        consumer_timeout_ms=args.consumer_timeout_ms,
    )

    last_msg = time.monotonic()
    n = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id","backend","topic","event_id","match_id",
            "t_sim_seconds","t_cons_recv_ns","t_output_ns"
        ])
        w.writeheader()

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

                    # IMPORTANT: only keep messages from *this* run
                    if v.get("run_id") != args.run_id:
                        continue

                    last_msg = time.monotonic()
                    t_cons_recv_ns = now_ns()
                    t_output_ns = now_ns()

                    w.writerow({
                        "run_id": v.get("run_id"),
                        "backend": "kafka",
                        "topic": args.topic,
                        "event_id": v.get("event_id"),
                        "match_id": v.get("match_id"),
                        "t_sim_seconds": v.get("t_sim_seconds"),
                        "t_cons_recv_ns": t_cons_recv_ns,
                        "t_output_ns": t_output_ns,
                    })
                    n += 1

    consumer.close()
    print(f"OK kafka consumer: wrote {n} rows -> {out_path}")

if __name__ == "__main__":
    main()
