#!/usr/bin/env python3
import argparse, csv, json, time
from pathlib import Path
import redis

# Enable coverage for subprocess execution if COVERAGE_PROCESS_START is set
try:
    import os
    if os.environ.get('COVERAGE_PROCESS_START'):
        import coverage
        coverage.process_start()
except Exception:
    pass


def now_ns() -> int:
    return time.perf_counter_ns()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="sb:events")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--group", default=None)
    ap.add_argument("--consumer", default=None)
    ap.add_argument("--idle-seconds", type=int, default=15)

    # optional knobs (kept simple / backward compatible)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--block-ms", type=int, default=1000)

    args = ap.parse_args()

    # Use per-run group default to prevent cross-run contamination
    group_id = args.group or f"sb-group-{args.run_id}"
    
    consumer_name = args.consumer or f"c-{args.run_id}"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # --- S3: consumer event log (for staleness + correction metrics) ---
    # Contract used by scripts/build_paper_s3_outputs.sh + scripts/compute_s3_metrics.py
    events_path = Path("runs") / args.run_id / "consumer_events.csv"
    events_path.parent.mkdir(parents=True, exist_ok=True)

    r = redis.Redis(host=args.host, port=args.port, decode_responses=True)

    # create group if needed
    try:
        r.xgroup_create(args.stream, group_id, id="0-0", mkstream=True)
    except Exception:
        pass  # group likely exists

    last_msg = time.monotonic()
    n = 0
    events_n = 0

    with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
        "w", newline="", encoding="utf-8"
    ) as f_events:
        # Existing (S2-compatible-ish) output rowset (kept exactly like your original)
        w = csv.DictWriter(
            f_out,
            fieldnames=[
                "run_id",
                "backend",
                "stream",
                "event_id",
                "match_id",
                "t_sim_seconds",
                "t_cons_recv_ns",
                "t_output_ns",
                "redis_id",
            ],
        )
        w.writeheader()

        # New (S3) consumer event log (close to Kafka schema + redis_id extra)
        ew = csv.DictWriter(
            f_events,
            fieldnames=[
                "run_id",
                "backend",
                "stream",
                "redis_id",
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
            resp = r.xreadgroup(
                groupname=group_id,
                consumername=consumer_name,
                streams={args.stream: ">"},
                count=args.count,
                block=args.block_ms,
            )

            if not resp:
                if (time.monotonic() - last_msg) >= args.idle_seconds:
                    break
                continue

            last_msg = time.monotonic()

            for stream_name, messages in resp:
                for redis_id, fields in messages:
                    # Note: decode_responses=True => fields are already str->str
                    t_consume_ns = now_ns()
                    t_cons_recv_ns = t_consume_ns
                    msg = json.loads(fields["value"])

                    # Filter to this run_id (prevents cross-run contamination when stream/group has old data)
                    if msg.get("run_id") != args.run_id:
                        r.xack(args.stream, group_id, redis_id)
                        continue

                    t_output_ns = now_ns()

                    # Existing output
                    w.writerow(
                        {
                            "run_id": args.run_id,
                            "backend": "redis",
                            "stream": stream_name,
                            "event_id": msg.get("event_id"),
                            "match_id": msg.get("match_id"),
                            "t_sim_seconds": msg.get("t_sim_seconds"),
                            "t_cons_recv_ns": t_cons_recv_ns,
                            "t_output_ns": t_output_ns,
                            "redis_id": redis_id,
                        }
                    )

                    # S3 consumer event log (envelope keys may be absent; that's OK)
                    ew.writerow(
                        {
                            "run_id": args.run_id,
                            "backend": "redis",
                            "stream": stream_name,
                            "redis_id": redis_id,
                            "t_consume_ns": t_consume_ns,
                            "event_id": msg.get("event_id"),
                            "match_id": msg.get("match_id"),
                            "t_sim_seconds": msg.get("t_sim_seconds"),
                            "t_emit_offset_s": msg.get("t_emit_offset_s"),
                            "t_emit_planned_ns": msg.get("t_emit_planned_ns"),
                            "s3_uid": msg.get("s3_uid"),
                            "s3_rev": msg.get("s3_rev"),
                            "s3_is_correction": msg.get("s3_is_correction"),
                        }
                    )

                    n += 1
                    events_n += 1
                    if events_n % 2000 == 0:
                        f_events.flush()
                        f_out.flush()

                    # ack the message
                    r.xack(args.stream, group_id, redis_id)

    print(f"OK redis consumer: wrote {n} rows -> {out_path}")
    print(f"OK redis consumer: wrote {events_n} rows -> {events_path}")


if __name__ == "__main__":
    main()
