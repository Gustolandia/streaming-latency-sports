#!/usr/bin/env python3
import argparse, csv, json, time, threading, heapq
from pathlib import Path

import pandas as pd
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
    # perf_counter_ns() is monotonic and high-resolution (good for timing comparisons)
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
        help="S3 corrections: every k-th base event (0 disables)",
    )
    ap.add_argument(
        "--correction-delay-s",
        type=float,
        default=0.0,
        help="S3 corrections: wall delay after base planned emit time (seconds)",
    )

    args = ap.parse_args()

    plan = pd.read_csv(args.plan_csv)
    plan = plan[plan["t_sim_seconds"] <= args.max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Base producer connection
    r = redis.Redis(host=args.host, port=args.port, decode_responses=True)

    # Producer time origins:
    # - t0_mono: time.monotonic() reference used for sleep scheduling
    # - t0_wall_ns: perf_counter_ns() reference used to compute planned emit ns in the same monotonic domain
    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

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
    corr_err = []
    corr_err_lock = threading.Lock()

    def corr_worker():
        # Separate connection for thread safety
        r_corr = redis.Redis(host=args.host, port=args.port, decode_responses=True)

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
            try:
                t_prod_send_ns = now_ns()
                redis_id = r_corr.xadd(
                    args.stream,
                    {"value": json.dumps(corr_msg, separators=(",", ":"), ensure_ascii=False)},
                )
                t_broker_ack_ns = now_ns()

                corr_rows.append(
                    {
                        "run_id": args.run_id,
                        "backend": "redis",
                        "stream": args.stream,
                        "event_id": corr_event_id,
                        "match_id": match_id,
                        "t_sim_seconds": t_sim,
                        "t_emit_offset_s": t_emit_offset_s,
                        "t_prod_sched_ns": corr_sched_ns,
                        "t_prod_send_ns": t_prod_send_ns,
                        "t_broker_ack_ns": t_broker_ack_ns,
                        "redis_id": redis_id,
                    }
                )
            except Exception as e:
                with corr_err_lock:
                    corr_err.append(repr(e))

    t_corr = None
    if corr_enabled:
        t_corr = threading.Thread(target=corr_worker, daemon=True)
        t_corr.start()

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "run_id",
                "backend",
                "stream",
                "event_id",
                "match_id",
                "t_sim_seconds",
                "t_emit_offset_s",
                "t_prod_sched_ns",
                "t_prod_send_ns",
                "t_broker_ack_ns",
                "redis_id",
            ],
        )
        w.writeheader()

        sent = 0
        for i, rrow in plan.iterrows():
            event_id = str(rrow["event_id"])
            match_id = int(rrow["match_id"])
            t_sim = int(rrow["t_sim_seconds"])
            t_emit_offset_s = float(rrow["t_emit_offset_s"])

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
                # S3 additions (always present; harmless if ignored)
                "t_emit_planned_ns": t_prod_sched_ns,
                "s3_uid": s3_uid,
                "s3_rev": 1,
                "s3_is_correction": False,
            }

            # XADD acts like our "ack" for MVP purposes
            redis_id = r.xadd(
                args.stream,
                {"value": json.dumps(msg, separators=(",", ":"), ensure_ascii=False)},
            )
            t_broker_ack_ns = now_ns()

            w.writerow(
                {
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
                }
            )
            sent += 1

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
                    # S3 linkage + correction semantics
                    "t_emit_planned_ns": corr_sched_ns,
                    "s3_uid": s3_uid,             # links back to base event
                    "s3_rev": 2,
                    "s3_is_correction": True,
                    "s3_base_event_id": event_id, # optional, helps debugging
                }

                with jobs_cv:
                    seq = jobs_seq
                    jobs_seq += 1
                    heapq.heappush(
                        jobs_heap,
                        (
                            corr_target_mono,
                            seq,
                            corr_event_id,
                            corr_msg,
                            corr_sched_ns,
                            match_id,
                            t_sim,
                            t_emit_offset_s,
                        ),
                    )
                    jobs_cv.notify()

        # finish corrections
        if corr_enabled:
            with jobs_cv:
                jobs_done = True
                jobs_cv.notify_all()
            t_corr.join()

            with corr_err_lock:
                if corr_err:
                    raise RuntimeError(f"Redis correction worker errors (first 5): {corr_err[:5]}")

            # write correction rows (same CSV schema)
            for row in corr_rows:
                w.writerow(row)

    print(f"OK redis producer: wrote {sent} base rows -> {out_path}")
    if corr_enabled:
        print(f"OK redis producer: wrote {len(corr_rows)} correction rows -> {out_path}")


if __name__ == "__main__":
    main()
