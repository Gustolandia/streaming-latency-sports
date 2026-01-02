import argparse, csv, json, time
from pathlib import Path
import pandas as pd
import redis

def now_ns() -> int:
    return time.perf_counter_ns()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="sb:events")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--speedup", type=float, default=120.0)
    ap.add_argument("--max-t-sim", type=int, default=600)
    args = ap.parse_args()

    plan = pd.read_csv(args.plan_csv)
    plan = plan[plan["t_sim_seconds"] <= args.max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    r = redis.Redis(host=args.host, port=args.port, decode_responses=True)

    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id","backend","stream","event_id","match_id",
            "t_sim_seconds","t_emit_offset_s",
            "t_prod_sched_ns","t_prod_send_ns","t_broker_ack_ns",
            "redis_id"
        ])
        w.writeheader()

        sent = 0
        for _, rrow in plan.iterrows():
            event_id = str(rrow["event_id"])
            match_id = int(rrow["match_id"])
            t_sim = int(rrow["t_sim_seconds"])
            t_emit_offset_s = float(rrow["t_emit_offset_s"])

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

            # XADD acts like our "ack" for MVP purposes
            redis_id = r.xadd(args.stream, {"value": json.dumps(msg, separators=(",", ":"))})
            t_broker_ack_ns = now_ns()

            w.writerow({
                "run_id": args.run_id,
                "backend": "redis",
                "stream": args.stream,
                "event_id": event_id,
                "match_id": match_id,
                "t_sim_seconds": t_sim,
                "t_emit_offset_s": t_emit_offset_s,
                "t_prod_sched_ns": t_prod_sched_ns,
                "t_prod_send_ns": t_prod_send_ns,
                "t_broker_ack_ns": t_broker_ack_ns,
                "redis_id": redis_id,
            })
            sent += 1

    print(f"OK redis producer: wrote {sent} rows -> {out_path}")

if __name__ == "__main__":
    main()
