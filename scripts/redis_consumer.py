import argparse, csv, json, time
from pathlib import Path
import redis

def now_ns() -> int:
    return time.perf_counter_ns()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="sb:events")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--group", default="sb-group")
    ap.add_argument("--consumer", default=None)
    ap.add_argument("--idle-seconds", type=int, default=15)
    args = ap.parse_args()

    consumer_name = args.consumer or f"c-{args.run_id}"
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    r = redis.Redis(host=args.host, port=args.port, decode_responses=True)

    # create group if needed
    try:
        r.xgroup_create(args.stream, args.group, id="0-0", mkstream=True)
    except Exception:
        pass  # group likely exists

    last_msg = time.monotonic()
    n = 0

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id","backend","stream","event_id","match_id",
            "t_sim_seconds","t_cons_recv_ns","t_output_ns","redis_id"
        ])
        w.writeheader()

        while True:
            resp = r.xreadgroup(
                groupname=args.group,
                consumername=consumer_name,
                streams={args.stream: ">"},
                count=200,
                block=1000,
            )

            if not resp:
                if (time.monotonic() - last_msg) >= args.idle_seconds:
                    break
                continue

            last_msg = time.monotonic()

            for stream_name, messages in resp:
                for redis_id, fields in messages:
                    t_cons_recv_ns = now_ns()
                    msg = json.loads(fields["value"])
                    t_output_ns = now_ns()

                    w.writerow({
                        "run_id": args.run_id,
                        "backend": "redis",
                        "stream": stream_name,
                        "event_id": msg.get("event_id"),
                        "match_id": msg.get("match_id"),
                        "t_sim_seconds": msg.get("t_sim_seconds"),
                        "t_cons_recv_ns": t_cons_recv_ns,
                        "t_output_ns": t_output_ns,
                        "redis_id": redis_id,
                    })
                    n += 1

                    # ack the message
                    r.xack(args.stream, args.group, redis_id)

    print(f"OK redis consumer: wrote {n} rows -> {out_path}")

if __name__ == "__main__":
    main()
