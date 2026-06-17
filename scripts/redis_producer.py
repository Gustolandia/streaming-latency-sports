#!/usr/bin/env python3
import argparse, csv, json, time, threading, heapq
from concurrent.futures import ThreadPoolExecutor
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
    # Wall-clock epoch nanoseconds. MUST be time.time_ns() (not perf_counter_ns):
    # producer and consumer run as SEPARATE processes, and perf_counter's reference
    # point is process-relative, so cross-process subtraction injects each process's
    # launch offset into TTI/transport. time.time_ns() shares one epoch across
    # processes on the same host, so consumer_ts - producer_ts is a valid latency.
    return time.time_ns()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="sb:events")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--cluster-mode", action="store_true",
                    help="Enable Redis cluster mode")
    ap.add_argument("--node-count", type=int, default=1, choices=[1, 3],
                    help="Number of Redis nodes (1=single, 3=cluster)")
    ap.add_argument("--speedup", type=float, default=120.0)
    ap.add_argument("--max-t-sim", type=int, default=600)
    ap.add_argument(
        "--send-workers",
        type=int,
        default=16,
        help="Concurrent XADD dispatch workers. >1 makes sends non-blocking so the "
             "producer keeps the emission schedule (avoids load-generator saturation "
             "at high speedup). 1 = legacy synchronous behavior.",
    )

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

    # Redis connection - support both single node and cluster mode
    if args.cluster_mode or args.node_count == 3:
        # Cluster mode: connect to all 3 nodes via localhost with mapped ports
        # Lazy import to avoid issues when redis is mocked in tests
        try:
            from redis.cluster import RedisCluster, ClusterNode
            
            # Address remap function to map Docker internal IPs to localhost
            # Docker redis-net uses 172.20.0.0/16
            def address_remap(node):
                # Each cluster port is published to the same host port
                # (7000:7000, 7001:7001, 7002:7002), so map any internal node
                # address to localhost keeping its port. Robust to Docker IP
                # reassignment / stale cluster topology.
                return ('127.0.0.1', node[1])
            
            # Use localhost with the mapped host ports
            # sbl_redis1 -> localhost:7000, sbl_redis2 -> localhost:7001, sbl_redis3 -> localhost:7002
            startup_nodes = [
                ClusterNode(host='localhost', port=7000),
                ClusterNode(host='localhost', port=7001),
                ClusterNode(host='localhost', port=7002),
            ]
            r = RedisCluster(
                startup_nodes=startup_nodes,
                decode_responses=True,
                # Disable full coverage requirement for flexibility
                require_full_coverage=False,
                # Apply address remapping to redirect Docker IPs to localhost
                address_remap=address_remap
            )
        except (ImportError, ModuleNotFoundError):
            # Fallback for when redis is mocked in tests
            r = redis.Redis(host=args.host, port=args.port, decode_responses=True)
    else:
        # Single node mode
        r = redis.Redis(host=args.host, port=args.port, decode_responses=True)

    # Producer time origins:
    # - t0_mono: time.monotonic() reference used for sleep scheduling
    # - t0_wall_ns: time.time_ns() wall-clock epoch used to compute planned emit ns;
    #   shared epoch with the consumer process so TTI is a valid cross-process latency
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
        if args.cluster_mode or args.node_count == 3:
            # Lazy import to avoid issues when redis is mocked in tests
            try:
                from redis.cluster import RedisCluster, ClusterNode
                
                # Address remap function to map Docker internal IPs to localhost
                def address_remap(node):
                    # Map any internal node address to localhost, keeping its
                    # port (host publishes 7000/7001/7002 identically).
                    return ('127.0.0.1', node[1])
                
                startup_nodes = [
                    ClusterNode(host='localhost', port=7000),
                    ClusterNode(host='localhost', port=7001),
                    ClusterNode(host='localhost', port=7002),
                ]
                r_corr = RedisCluster(startup_nodes=startup_nodes, decode_responses=True, require_full_coverage=False, address_remap=address_remap)
            except (ImportError, ModuleNotFoundError):
                # Fallback for when redis is mocked in tests
                r_corr = redis.Redis(host=args.host, port=args.port, decode_responses=True)
        else:
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

    # Non-blocking base-event dispatch pool so the producer keeps the emission
    # schedule even when per-XADD round-trips are slower than the scheduled gap.
    base_rows = []
    base_lock = threading.Lock()
    base_err = []

    def _send_base(idx, event_id, match_id, t_sim, t_emit_offset_s, t_prod_sched_ns, payload):
        try:
            send_ns = now_ns()
            redis_id = r.xadd(args.stream, {"value": payload})
            ack_ns = now_ns()
            row = {
                "run_id": args.run_id, "backend": "redis", "stream": args.stream,
                "event_id": event_id, "match_id": match_id, "t_sim_seconds": t_sim,
                "t_emit_offset_s": t_emit_offset_s, "t_prod_sched_ns": t_prod_sched_ns,
                "t_prod_send_ns": send_ns, "t_broker_ack_ns": ack_ns, "redis_id": redis_id,
            }
            with base_lock:
                base_rows.append((idx, row))
        except Exception as e:  # noqa: BLE001
            with base_lock:
                base_err.append(repr(e))

    send_pool = ThreadPoolExecutor(max_workers=max(1, args.send_workers))

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

            # Non-blocking dispatch: hand the XADD to the worker pool and continue,
            # so the main loop stays on schedule. Send/ack times are stamped in the
            # worker (valid transport latency), rows written in order after draining.
            payload = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
            send_pool.submit(
                _send_base, i, event_id, match_id, t_sim, t_emit_offset_s,
                t_prod_sched_ns, payload,
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

        # drain base-event dispatch pool and write rows in original plan order
        send_pool.shutdown(wait=True)
        if base_err:
            raise RuntimeError(f"Redis base send errors (first 5): {base_err[:5]}")
        for _idx, row in sorted(base_rows, key=lambda kv: kv[0]):
            w.writerow(row)
        sent = len(base_rows)

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
