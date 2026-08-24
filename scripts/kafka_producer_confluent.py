#!/usr/bin/env python3
"""
kafka_producer_confluent.py
A drop-in alternative to kafka_producer.py that uses confluent-kafka (librdkafka) instead of
kafka-python, for the client-attribution experiment (M1).

Why this exists. On the multi-host testbed at true real-time replay, Kafka's end-to-end TTI is
~105 ms, of which ~103 ms is producer scheduling lag -- the interval between an event's planned
emission and the producer issuing the send. The same code at 10x replay shows ~0.2-1 ms. That
offset is upstream of the broker, so it is either a property of the client library, a
configuration we failed to find, or a property of our replay loop. The manuscript could not
distinguish those, which made its headline practical recommendation rest on an unexplained
constant.

Running the identical experiment against a second, independently implemented client separates
"Kafka" from "kafka-python". The timestamp semantics here are deliberately identical to
kafka_producer.py:

    t_prod_sched_ns  planned emission, derived from the shared wall-clock origin
    t_prod_send_ns   stamped immediately before the send call
    t_broker_ack_ns  stamped inside the delivery callback

and the output CSV schema is byte-compatible, so every downstream analysis works unchanged.

One design note. confluent-kafka serves delivery callbacks from poll(), whereas kafka-python
runs a background sender thread. To keep acknowledgement timestamps comparable rather than
batched at flush time, this script runs its own poll thread. Without it the ack timestamps
would be an artefact of when we happened to call poll.
"""
import argparse
import csv
import json
import threading
import time
from pathlib import Path

import pandas as pd

try:
    from confluent_kafka import Producer
except ImportError:  # pragma: no cover - exercised only where the library is absent
    Producer = None


def now_ns() -> int:
    """Wall-clock epoch nanoseconds; must match kafka_producer.py exactly.

    Producer and consumer are separate processes, so the epoch has to be shared. See the
    note in kafka_producer.py on why perf_counter_ns is wrong here.
    """
    return time.time_ns()


def build_config(args):
    """Map our CLI onto librdkafka configuration keys.

    The names differ from kafka-python's but the semantics are the same, which is the point:
    if the 103 ms offset is a client artefact it should not survive a change of client at
    equivalent settings.
    """
    conf = {
        "bootstrap.servers": args.bootstrap,
        "acks": args.acks,
        "linger.ms": args.linger_ms,
        "max.in.flight.requests.per.connection": max(1, int(args.max_inflight)),
    }
    if args.batch_size is not None:
        conf["batch.size"] = int(args.batch_size)
    if args.compression_type is not None:
        conf["compression.type"] = args.compression_type
    return conf


def load_plan(plan_csv, max_t_sim):
    plan = pd.read_csv(plan_csv)
    plan = plan[plan["t_sim_seconds"] <= max_t_sim].copy()
    return plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="Kafka producer using confluent-kafka")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--topic", default="sb-events")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3])
    ap.add_argument("--speedup", type=float, default=120.0)
    ap.add_argument("--max-t-sim", type=int, default=600)
    ap.add_argument("--acks", default="all", choices=["0", "1", "all"])
    ap.add_argument("--linger-ms", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=None)
    ap.add_argument("--compression-type", default=None,
                    choices=["gzip", "snappy", "lz4", "zstd"])
    ap.add_argument("--max-inflight", type=int, default=1)
    ap.add_argument("--trace-loop", default=None,
                    help="write per-event loop timing here (see kafka_producer.py --trace-loop)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if Producer is None:
        print("confluent-kafka is not installed; install it or use scripts/kafka_producer.py")
        return 2

    plan = load_plan(args.plan_csv, args.max_t_sim)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    producer = Producer(build_config(args))

    ack_ns = {}
    ack_lock = threading.Lock()
    errors = []

    def on_delivery(err, msg):
        if err is not None:
            errors.append(repr(err))
            return
        with ack_lock:
            ack_ns[msg.key().decode("utf-8")] = now_ns()

    # Serve delivery callbacks promptly so ack timestamps mean what they say.
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            producer.poll(0.01)

    poller = threading.Thread(target=pump, daemon=True)
    poller.start()

    # Same two origins as kafka_producer.py: monotonic drives the sleep schedule, wall clock
    # defines the planned emission times the consumer will be compared against.
    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

    rows, trace = [], []
    for _, r in plan.iterrows():
        event_id = str(r["event_id"])
        t_emit_offset_s = float(r["t_emit_offset_s"])

        target_mono = t0_mono + (t_emit_offset_s / args.speedup)
        sleep_s = target_mono - time.monotonic()
        if sleep_s > 0:
            time.sleep(sleep_s)
        t_wake = now_ns()

        t_prod_sched_ns = t0_wall_ns + int((t_emit_offset_s / args.speedup) * 1e9)
        t_prod_send_ns = now_ns()

        msg = {
            "run_id": args.run_id,
            "match_id": int(r["match_id"]),
            "event_id": event_id,
            "t_sim_seconds": int(r["t_sim_seconds"]),
            "t_emit_offset_s": t_emit_offset_s,
            "t_emit_planned_ns": t_prod_sched_ns,
            "s3_uid": f"{int(r['match_id'])}:{event_id}",
            "s3_rev": 1,
            "s3_is_correction": False,
        }
        producer.produce(
            args.topic,
            key=event_id.encode("utf-8"),
            value=json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            on_delivery=on_delivery,
        )
        t_after_produce = now_ns()

        rows.append({
            "run_id": args.run_id, "backend": "kafka", "topic": args.topic,
            "event_id": event_id, "match_id": int(r["match_id"]),
            "t_sim_seconds": int(r["t_sim_seconds"]), "t_emit_offset_s": t_emit_offset_s,
            "t_prod_sched_ns": t_prod_sched_ns, "t_prod_send_ns": t_prod_send_ns,
            "t_broker_ack_ns": None,
        })
        if args.trace_loop:
            trace.append({
                "event_id": event_id, "client": "confluent",
                "t_target_ns": t_prod_sched_ns, "t_wake_ns": t_wake,
                "t_send_ns": t_prod_send_ns, "t_after_produce_ns": t_after_produce,
                "wake_late_ms": (t_wake - t_prod_sched_ns) / 1e6,
                "produce_ms": (t_after_produce - t_prod_send_ns) / 1e6,
            })

    producer.flush(30)
    stop.set()
    poller.join(timeout=5)

    if errors:
        raise RuntimeError(f"confluent-kafka delivery errors (first 5): {errors[:5]}")

    with ack_lock:
        for row in rows:
            row["t_broker_ack_ns"] = ack_ns.get(row["event_id"])

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
            "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns"])
        w.writeheader()
        w.writerows(rows)

    if args.trace_loop:
        # Namespaced by run id for the same reason as kafka_producer.py: concurrent feeds are
        # separate processes and would otherwise overwrite one another.
        tp = Path(args.trace_loop)
        tp = tp.with_name(f"{tp.stem}_{args.run_id}{tp.suffix}")
        tp.parent.mkdir(parents=True, exist_ok=True)
        with tp.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(trace[0].keys()) if trace else ["event_id"])
            w.writeheader()
            w.writerows(trace)

    print(f"OK confluent producer: wrote {len(rows)} rows -> {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
