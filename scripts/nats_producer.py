#!/usr/bin/env python3
"""
nats_producer.py -- the producer of block N's NATS JetStream runs: the plan's events published at
the plan's pace, each to the stream's subject with a reply subject of its own, so that JetStream
answers each publish with its acknowledgment; and producer.csv written with the columns
scripts/redis_producer.py writes, the acknowledgment's stream sequence in place of Redis's entry id.

The plan is read, paced at --speedup, and given its correction jobs (--s3-mode corrections) as in
redis_producer.py, and the message is the same JSON.

Sends never wait for acknowledgments: the design is a reader thread. The main loop writes each
publish and goes on to the next event. One thread reads the connection, which every acknowledgment
comes back on, each to the reply subject its publish named; the reply subject's last token, a
number given to each publish, matches the two, and the order the answers come in plays no part.
The thread stamps t_broker_ack_ns as the read that completed the acknowledgment returns, and takes
the stream sequence from it. t_prod_send_ns is stamped just before the write. Every write on the
connection, the publishes and the reader's answers to the server's PINGs, goes out under one lock,
so that no frame is written inside another; the reader takes the lock only to answer a PING.

No NATS library is used (scripts/nats_wire.py), so the socket-timestamp shim and the collector
switch apply as they do to the Redis clients: the shim replaces socket.socket before the connection
is opened.
"""
import argparse
import csv
import heapq
import itertools
import json
import socket
import threading
import time
from pathlib import Path

import pandas as pd

import law_clock
import thread_record
import so_timestamps
import client_quiet
import nats_wire

#: The subscription the acknowledgments come back on.
ACK_SID = 2


def now_ns() -> int:
    # Wall-clock epoch nanoseconds, time.time_ns(), as in redis_producer.py: the consumer is
    # another process, and only the wall clock shares one epoch across processes on one host.
    return time.time_ns()


def acknowledged(frame, subject):
    """The stream sequence an acknowledgment gives. A status message in its place is an error:
    503, no responders, where no stream takes the subject."""
    code = nats_wire.status(frame)
    if code is not None:
        raise nats_wire.JetStreamError(code[0], None,
                                       code[1] or "no stream takes subject %s" % subject)
    return nats_wire.pub_ack(frame.payload)[1]


def main(argv=None, dial=socket.create_connection):
    ap = argparse.ArgumentParser(description="Block N's NATS JetStream producer")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="SBL_EVENTS", type=nats_wire.checked_name)
    ap.add_argument("--subject", default=None, type=nats_wire.checked_subject,
                    help="the subject the stream takes and the producer publishes to; "
                         "sbl.<stream> unless named")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=nats_wire.PORT)
    ap.add_argument("--storage", default="file", choices=nats_wire.STORAGE,
                    help="where the stream keeps its messages, if this client creates it")
    ap.add_argument("--speedup", type=float, default=120.0)
    ap.add_argument("--max-t-sim", type=int, default=600)
    # As in redis_producer.py: pad the payload to lengthen the true transport.
    ap.add_argument("--pad-bytes", type=int, default=0,
                    help="pad each message with this many filler bytes to lengthen true "
                         "transport; 0 (default) leaves the payload untouched")
    ap.add_argument("--ack-wait-s", type=float, default=30.0,
                    help="how long the producer waits, after its last publish, for the "
                         "acknowledgments still out; a run missing any after it fails")

    # --- S3 knobs, as in redis_producer.py (no behaviour change unless enabled) ---
    ap.add_argument("--s3-mode", default="none", choices=["none", "baseline", "corrections"],
                    help="S3: add envelope fields; optionally emit correction messages")
    ap.add_argument("--corrections-every-k", type=int, default=0,
                    help="S3 corrections: every k-th base event (0 disables)")
    ap.add_argument("--correction-delay-s", type=float, default=0.0,
                    help="S3 corrections: wall delay after base planned emit time (seconds)")
    # As redis_producer.py's --trace-loop. produce_ms is the time the write of the publish held
    # the emission loop: the quantity comparable to Kafka's produce() return.
    ap.add_argument("--trace-loop", default=None,
                    help="write per-event loop timing to this CSV (diagnostic; off by default)")
    # D28-1: the main loop stamps the sends and the reader thread the acknowledgments.
    ap.add_argument("--thread-record", action="store_true",
                    help="write which threads stamped what, and both clocks, beside the CSV")

    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    args = ap.parse_args(argv)
    record = thread_record.ThreadRecord() if args.thread_record else None
    # F2 (freeze 40): the kernel's own timestamps on the broker's connection, if asked for,
    # before the connection is opened.
    so = so_timestamps.start(args, args.port)

    # The same bar as the other clients: see law_clock.py.
    print(f"CONFIG effective client=python "
          f"clock_resolution_ns={law_clock.demand_usable_resolution('the NATS producer')}",
          flush=True)

    plan = pd.read_csv(args.plan_csv)
    plan = plan[plan["t_sim_seconds"] <= args.max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subject = args.subject or nats_wire.default_subject(args.stream)

    # One connection. The stream is made sure of first, so that a publish never finds no stream
    # to take it whichever client starts first; then the acknowledgments' subscription.
    link = nats_wire.Link.open(dial, args.host, args.port, "sbl-nats-producer")
    nats_wire.ensure_stream(link, args.stream, subject, args.storage)
    inbox = nats_wire.new_inbox()
    inbox_dot = inbox + "."
    link.send(nats_wire.sub(inbox + ".*", ACK_SID))
    print(f"CONFIG effective server_version={link.info.get('version')} "
          f"jetstream={int(bool(link.info.get('jetstream')))} storage={args.storage} "
          f"stream={args.stream} subject={subject}", flush=True)

    # Freeze 43, as in redis_producer.py: the collector, if asked, goes off here, with the
    # connection made and before t0, so that its one collection delays no message's schedule.
    quiet = client_quiet.start(args)

    # Every publish waiting for its acknowledgment, by its reply token: (kind, row).
    pending = {}
    acks_cv = threading.Condition()
    errors = {"base": [], "correction": []}
    failed = []
    stop = threading.Event()
    tokens = itertools.count(1)

    def publish(kind, row, payload):
        """Write one publish: its frame made and its row registered under its reply token, then
        the send stamped and at once the write, all under the connection's lock."""
        with link.lock:
            token = str(next(tokens))
            data = nats_wire.pub(subject, payload, inbox_dot + token)
            with acks_cv:
                pending[token] = (kind, row)
            row["t_prod_send_ns"] = now_ns()
            link.write(data)
        if record is not None:
            record.note("stamps_send")

    def read_acks():
        """Every acknowledgment, matched to its publish by its reply token, and stamped as the
        read that completed it returns. A connection that fails ends the thread and the run."""
        while not stop.is_set():
            try:
                frame = link.next_frame()
            except (OSError, ValueError) as exc:
                with acks_cv:
                    failed.append(repr(exc))
                    acks_cv.notify_all()
                return
            if frame is None:
                continue
            t_ack_ns = now_ns()
            if not (frame.subject or "").startswith(inbox_dot):
                continue
            try:
                seq, error = acknowledged(frame, subject), None
            except (nats_wire.JetStreamError, nats_wire.ProtocolError) as exc:
                seq, error = None, repr(exc)
            with acks_cv:
                # An answer to nothing pending (none is ever sent twice) is passed over.
                kind, row = pending.pop(frame.subject[len(inbox_dot):], (None, None))
                if error is not None and kind is not None:
                    errors[kind].append(error)
                elif row is not None:
                    row["t_broker_ack_ns"] = t_ack_ns
                    row["stream_seq"] = seq
                acks_cv.notify_all()
            if record is not None:
                record.note("stamps_ack")

    reader = threading.Thread(target=read_acks, name="sbl-nats-acks", daemon=True)
    reader.start()

    # Producer time origins, as in redis_producer.py:
    # - t0_mono: time.monotonic() reference used for sleep scheduling
    # - t0_wall_ns: time.time_ns() wall-clock epoch used to compute planned emit ns
    t0_wall_ns = now_ns()
    t0_mono = time.monotonic()

    # ---- S3 corrections scheduler (optional) ----
    corr_enabled = (
        args.s3_mode == "corrections"
        and int(args.corrections_every_k) > 0
        and float(args.correction_delay_s) >= 0.0  # Allow zero delay
    )

    # heap entries: (target_mono, seq, corr_msg, row)
    jobs_cv = threading.Condition()
    jobs_heap = []
    jobs_seq = 0
    jobs_done = False

    corr_rows = []
    corr_err = []

    def corr_worker():
        # The corrections publish on the producer's own connection, under its lock, and their
        # acknowledgments come back through the same reader.
        while True:
            with jobs_cv:
                while not jobs_heap and not jobs_done:
                    jobs_cv.wait()

                if jobs_done and not jobs_heap:
                    return

                target_mono, _seq, corr_msg, row = jobs_heap[0]
                now_m = time.monotonic()
                if target_mono > now_m:
                    jobs_cv.wait(timeout=target_mono - now_m)
                    continue

                heapq.heappop(jobs_heap)

            # Send outside lock
            try:
                corr_rows.append(row)
                publish("correction", row,
                        json.dumps(corr_msg, separators=(",", ":"),
                                   ensure_ascii=False).encode("utf-8"))
            except Exception as e:  # noqa: BLE001
                corr_err.append(repr(e))

    t_corr = None
    if corr_enabled:
        t_corr = threading.Thread(target=corr_worker, daemon=True)
        t_corr.start()

    trace = []
    base_rows = []
    fieldnames = ["run_id", "backend", "stream", "event_id", "match_id", "t_sim_seconds",
                  "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns",
                  "stream_seq"]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
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
            t_wake_ns = now_ns()

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
            if args.pad_bytes > 0:
                # Constant filler, not random: compression would otherwise vary the wire size
                # between runs and the manipulation would not be the one described.
                msg["pad"] = "x" * args.pad_bytes

            # The write goes out now and the loop goes on: the acknowledgment is the reader's.
            payload = json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            row = {
                "run_id": args.run_id, "backend": "nats", "stream": args.stream,
                "event_id": event_id, "match_id": match_id, "t_sim_seconds": t_sim,
                "t_emit_offset_s": t_emit_offset_s, "t_prod_sched_ns": t_prod_sched_ns,
                "t_prod_send_ns": None, "t_broker_ack_ns": None, "stream_seq": None,
            }
            base_rows.append(row)
            publish("base", row, payload)
            sent += 1

            if args.trace_loop:
                t_after_produce_ns = now_ns()
                trace.append({
                    "event_id": event_id,
                    "client": "nats-wire",
                    "t_target_ns": t_prod_sched_ns,
                    "t_wake_ns": t_wake_ns,
                    "t_send_ns": row["t_prod_send_ns"],
                    "t_after_produce_ns": t_after_produce_ns,
                    "wake_late_ms": (t_wake_ns - t_prod_sched_ns) / 1e6,
                    "produce_ms": (t_after_produce_ns - row["t_prod_send_ns"]) / 1e6,
                })

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
                    "s3_base_event_id": event_id,  # optional, helps debugging
                }
                corr_row = dict(row, event_id=corr_event_id, t_prod_sched_ns=corr_sched_ns,
                                t_prod_send_ns=None, t_broker_ack_ns=None, stream_seq=None)

                with jobs_cv:
                    seq = jobs_seq
                    jobs_seq += 1
                    heapq.heappush(jobs_heap, (corr_target_mono, seq, corr_msg, corr_row))
                    jobs_cv.notify()

        # The corrections still due are sent before the acknowledgments are waited for.
        if corr_enabled:
            with jobs_cv:
                jobs_done = True
                jobs_cv.notify_all()
            t_corr.join()

        # Every acknowledgment in, or the wait given up; then the reader stops.
        deadline = time.monotonic() + args.ack_wait_s
        with acks_cv:
            while pending and not failed and time.monotonic() < deadline:
                acks_cv.wait(timeout=nats_wire.WAIT_S)
        stop.set()
        reader.join()
        if failed:
            raise RuntimeError(f"NATS acknowledgment reader failed: {failed[0]}")
        if errors["base"]:
            raise RuntimeError(f"NATS base send errors (first 5): {errors['base'][:5]}")
        missing = [row["event_id"] for kind, row in pending.values() if kind == "base"]
        if missing:
            raise RuntimeError(f"NATS publishes never acknowledged within {args.ack_wait_s} s: "
                               f"{len(missing)} (first 5): {missing[:5]}")
        for row in base_rows:
            w.writerow(row)
        sent = len(base_rows)

        # finish corrections
        if corr_enabled:
            corr_err += errors["correction"]
            corr_err += [f"never acknowledged: {row['event_id']}"
                         for kind, row in pending.values() if kind == "correction"]
            if corr_err:
                raise RuntimeError(f"NATS correction worker errors (first 5): {corr_err[:5]}")

            # write correction rows (same CSV schema)
            for row in corr_rows:
                w.writerow(row)

    link.close()
    if args.trace_loop:
        # Namespaced by run id, as in redis_producer.py: at N>1 every feed is its own producer
        # process and they would otherwise race to write the same file.
        tp = Path(args.trace_loop)
        tp = tp.with_name(f"{tp.stem}_{args.run_id}{tp.suffix}")
        tp.parent.mkdir(parents=True, exist_ok=True)
        with tp.open("w", newline="", encoding="utf-8") as f:
            tw = csv.DictWriter(f, fieldnames=list(trace[0].keys()) if trace else ["event_id"])
            tw.writeheader()
            tw.writerows(trace)
        print(f"OK loop trace: wrote {len(trace)} rows -> {tp}")

    if record is not None:
        record.write(thread_record.beside(out_path))
    so_timestamps.finish(so, args)
    client_quiet.finish(quiet, args)
    print(f"OK nats producer: wrote {sent} base rows -> {out_path}")
    if corr_enabled:
        print(f"OK nats producer: wrote {len(corr_rows)} correction rows -> {out_path}")


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
