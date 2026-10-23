#!/usr/bin/env python3
"""
nats_consumer.py -- the consumer of block N's NATS JetStream runs: a durable pull consumer that
keeps --depth pull requests waiting at the broker, and writes consumer.csv and consumer_events.csv
with the columns scripts/redis_consumer.py writes, the stream sequence in place of Redis's entry id.

A pull consumer whose thread is slow sends its next request late, and a message that reaches the
broker while no request waits there sits until one comes: the client's own delay then enters W,
what reaches its kernel. Requests kept waiting take the thread out of W, and block N tests that for
NATS at --depth 1 and 256.

  The requests. --depth requests, each for one message with a long expiry (--expires-s), are sent
  before the first read. On each delivered message, and on each request that ends without one
  (408 Request Timeout, when it expires), another is sent before the message is handled, so the
  number waiting falls below the depth only for the time of that one write. The durable consumer
  is made with max_waiting four times the depth, and never below 512.

  Which request a message answered. nats-server delivers a message on the subscription that takes
  the requests' reply subjects, but under the subject the message was published to: a delivery is
  known by that subscription and its reply subject under $JS.ACK, and names no request. The server
  serves a consumer's requests for one message oldest first, and sends its deliveries and statuses
  in the order it dispatches them, so each delivery answered the oldest request still waiting. A
  status comes under the reply subject of the request it answers. One that names a request not
  waiting would mean the messages had not answered the requests oldest first, and the run stops.

  Two connections. The pull requests go out on the receive connection and the messages come back
  on it. The acknowledgments (+ACK, published to each message's reply subject) go on the second,
  with the requests that make the stream and the durable consumer, so that the receive connection
  carries nothing but the requests, the messages, the probes and its own housekeeping (CONNECT,
  SUB, PING and PONG). The second is read, without waiting, once a second, for the server's PINGs.

  The probes. Every --probe-ms milliseconds (100 unless given; 0 sends none) a PING goes out on the
  receive connection, and the PONG that answers it is read like any other frame: after the messages
  the server had already sent on the connection, which is intended. A PONG cannot have waited for
  a message, so a reader of a capture takes the least probe round trip as the connection's floor,
  and the largest as the check that its one-way delays stayed under 10 ms. A PONG is neither a
  message nor a status, and answers no request. A probe goes out only once the frame read before it
  is handled, after any replacement that frame called for; and each read of the receive connection
  waits at most one interval, so that no probe is more than one interval late.

  The message's id. Each message's reply subject, $JS.ACK...., names its stream sequence, and that
  is the message's id in both CSVs and in a reader's hands. The payload's run_id decides whether a
  message is this run's (others are acknowledged and not written), and its event_id and the
  producer's other envelope fields are copied into their columns as redis_consumer.py copies them;
  no request, acknowledgment, match or stamp depends on the payload. A message delivered a second
  time (an acknowledgment lost, and the message sent again) is acknowledged and not written again.

  --one-reply-reads. Each read of the receive connection takes exactly one frame, a PONG as much as
  a message, found by a look at the bytes waiting that takes none of them (MSG_PEEK) and
  scripts/nats_wire.py's splitter, so that each read's kernel timestamp (scripts/so_timestamps.py)
  is one frame's own. The shim passes a peek through untouched and journals only the read that
  takes the bytes, with that read's timestamp: each row of the journal's reads is then one frame.

t_consume_ns is time.time_ns(), CLOCK_REALTIME, taken as the read that brought the message
returns, before the replacement request; t_output_ns once the message has been read and found to
be this run's, as in redis_consumer.py.
"""
import argparse
import collections
import csv
import json
import socket
import time
from pathlib import Path

import law_clock
import thread_record
import so_timestamps
import client_quiet
import nats_wire

#: The subscription the pull requests are answered on.
PULL_SID = 2
#: How often the acknowledgments' connection is read for the server's PINGs.
SERVICE_S = 1.0
#: How often, in ms, a probe goes out on the receive connection unless --probe-ms says otherwise.
PROBE_MS = 100
#: The statuses that end a request without a message, each answered by another request: the
#: request expired, or had no messages, or, on a cluster, the consumer's leader changed (409
#: Leadership Change). A heartbeat ends nothing; any other status is a request refused, which
#: the run does not survive.
ENDED = (nats_wire.REQUEST_TIMEOUT, nats_wire.NO_MESSAGES)
LEADERSHIP_CHANGE = "Leadership Change"


def now_ns() -> int:
    # Wall-clock epoch ns (time.time_ns), NOT perf_counter_ns: must share one epoch with the
    # producer process so consumer_ts - producer_ts is a valid latency.
    return time.time_ns()


def main(argv=None, dial=socket.create_connection, clock=time.monotonic):
    ap = argparse.ArgumentParser(description="Block N's NATS JetStream pull consumer")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="SBL_EVENTS", type=nats_wire.checked_name)
    ap.add_argument("--subject", default=None, type=nats_wire.checked_subject,
                    help="the subject the stream takes, if this client creates it; "
                         "sbl.<stream> unless named")
    ap.add_argument("--durable", default=None, type=nats_wire.checked_name,
                    help="the durable consumer's name; sbl-<run id> unless named")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=nats_wire.PORT)
    ap.add_argument("--storage", default="file", choices=nats_wire.STORAGE,
                    help="where the stream keeps its messages, if this client creates it")
    ap.add_argument("--depth", type=int, default=1,
                    help="pull requests kept waiting at the broker, each for one message")
    ap.add_argument("--expires-s", type=float, default=30.0,
                    help="how long each pull request waits at the broker before it expires")
    ap.add_argument("--one-reply-reads", action="store_true",
                    help="take exactly one frame with each read of the receive connection")
    ap.add_argument("--probe-ms", type=int, default=PROBE_MS,
                    help="send PING on the receive connection this often, in ms, and read each "
                         "PONG: the round trips a reader takes the connection's floor from; "
                         "0 sends none")
    ap.add_argument("--idle-seconds", type=int, default=15)
    ap.add_argument("--delete-stream", action="store_true",
                    help="delete the stream, and its consumer with it, once the run is over")
    # D28-1: the thread that stamps each arrival, and both clocks, for a recording of waits.
    ap.add_argument("--thread-record", action="store_true",
                    help="write which thread stamped the arrivals, and both clocks, beside the CSV")

    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    args = ap.parse_args(argv)
    if args.depth < 1:
        ap.error("--depth is at least 1")
    if args.probe_ms < 0:
        ap.error("--probe-ms is 0, for no probes, or more")
    record = thread_record.ThreadRecord() if args.thread_record else None
    # F2 (freeze 40): the kernel's own timestamps on the broker's connections, if asked
    # for, before any connection is opened.
    so = so_timestamps.start(args, args.port)

    subject = args.subject or nats_wire.default_subject(args.stream)
    durable = args.durable or nats_wire.safe_name("sbl-" + args.run_id)
    max_waiting = nats_wire.max_waiting_for(args.depth)
    probe_s = args.probe_ms / 1000.0
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Sibling of --out, as in redis_consumer.py.
    events_path = Path(args.out).with_name(Path(args.out).stem + "_events.csv")
    events_path.parent.mkdir(parents=True, exist_ok=True)

    # The receive connection first, then the acknowledgments', which makes the stream and the
    # durable consumer if they are absent; then the requests' subscription. A read of the receive
    # connection waits at most one probe interval, so that a probe falling due is not held back.
    receive = nats_wire.Link.open(dial, args.host, args.port, "sbl-nats-consumer",
                                  one_reply=args.one_reply_reads,
                                  wait_s=min(nats_wire.WAIT_S, probe_s or nats_wire.WAIT_S))
    acks = nats_wire.Link.open(dial, args.host, args.port, "sbl-nats-consumer-acks")
    nats_wire.ensure_stream(acks, args.stream, subject, args.storage)
    nats_wire.ensure_consumer(acks, args.stream, durable, max_waiting=max_waiting)
    pulls = nats_wire.new_inbox()
    pulls_dot = pulls + "."
    receive.write(nats_wire.sub(pulls + ".*", PULL_SID))
    next_subject, next_payload = nats_wire.pull_request(args.stream, durable,
                                                        int(args.expires_s * 1e9))

    # Freeze 43, as in redis_consumer.py: asked for, the collector goes off here, once the client
    # has its connections, its stream and its consumer, and before any request is sent.
    quiet = client_quiet.start(args)

    asked = 0
    # The requests sent and not yet answered, by reply subject, oldest first: a delivered message
    # answered the first of them, a status the one it names.
    waiting = collections.deque()
    ended = {}
    redelivered = 0
    n = 0
    events_n = 0
    probes = 0
    pongs = 0

    def ask():
        """One pull request on the receive connection, this thread's scheduler counters sampled
        just before it. Each has a reply subject of its own, so that a status that answers it
        names it; a message delivered for it names none, and is matched to it by the order the
        requests were sent in."""
        nonlocal asked
        asked += 1
        reply = "%s%d" % (pulls_dot, asked)
        waiting.append(reply)
        client_quiet.sample(quiet)
        receive.write(nats_wire.pub(next_subject, next_payload, reply))

    with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
        "w", newline="", encoding="utf-8"
    ) as f_events:
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
                "stream_seq",
            ],
        )
        w.writeheader()

        ew = csv.DictWriter(
            f_events,
            fieldnames=[
                "run_id",
                "backend",
                "stream",
                "stream_seq",
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

        # Manipulation check, recorded in every run's consumer.log: the depth, the read and the
        # probes the run had, as the client applied them.
        print(f"CONFIG effective depth={args.depth} expires_ms={int(args.expires_s * 1000)} "
              f"one_reply_reads={int(args.one_reply_reads)} probe_ms={args.probe_ms} "
              f"max_waiting={max_waiting} max_ack_pending={nats_wire.MAX_ACK_PENDING} "
              f"storage={args.storage} stream={args.stream} subject={subject} durable={durable} "
              f"server_version={receive.info.get('version')} client=python "
              f"clock_resolution_ns={law_clock.demand_usable_resolution('the NATS consumer')}",
              flush=True)

        # One row per read of the receive connection, as redis_consumer.py keeps one per
        # XREADGROUP: when it began, how long it took, and whether it brought a message.
        read_trace = []
        for _ in range(args.depth):
            ask()
        last_msg = clock()
        serviced = probed = last_msg
        while True:
            t_read0 = now_ns()
            frame = receive.next_frame()
            t_got = now_ns()
            # A message comes on the requests' subscription with a reply subject under $JS.ACK,
            # whatever its subject; a status under the reply subject of the request it answers.
            # A PONG, a probe's answer, is neither.
            delivered = frame is not None and nats_wire.is_delivery(frame, PULL_SID)
            code = (nats_wire.request_status(frame, pulls_dot)
                    if frame is not None and not delivered else None)
            read_trace.append((t_read0, t_got - t_read0, int(delivered)))

            if delivered:
                t_consume_ns = t_got
                t_cons_recv_ns = t_consume_ns
                if record is not None:
                    record.note("stamps_receive")
                # The replacement goes out before the message is handled; the message answered
                # the oldest request waiting.
                ask()
                waiting.popleft()
                meta = nats_wire.ack_metadata(frame.reply)
                msg = json.loads(frame.payload)
                # Another run's message is acknowledged and not written, as in redis_consumer.py.
                this_run = msg.get("run_id") == args.run_id
                if this_run and meta.delivered > 1:
                    redelivered += 1
                elif this_run:
                    t_output_ns = now_ns()
                    w.writerow({
                        "run_id": args.run_id,
                        "backend": "nats",
                        "stream": meta.stream,
                        "event_id": msg.get("event_id"),
                        "match_id": msg.get("match_id"),
                        "t_sim_seconds": msg.get("t_sim_seconds"),
                        "t_cons_recv_ns": t_cons_recv_ns,
                        "t_output_ns": t_output_ns,
                        "stream_seq": meta.stream_seq,
                    })
                    # S3 consumer event log (envelope keys may be absent; that's OK)
                    ew.writerow({
                        "run_id": args.run_id,
                        "backend": "nats",
                        "stream": meta.stream,
                        "stream_seq": meta.stream_seq,
                        "t_consume_ns": t_consume_ns,
                        "event_id": msg.get("event_id"),
                        "match_id": msg.get("match_id"),
                        "t_sim_seconds": msg.get("t_sim_seconds"),
                        "t_emit_offset_s": msg.get("t_emit_offset_s"),
                        "t_emit_planned_ns": msg.get("t_emit_planned_ns"),
                        "s3_uid": msg.get("s3_uid"),
                        "s3_rev": msg.get("s3_rev"),
                        "s3_is_correction": msg.get("s3_is_correction"),
                    })
                    n += 1
                    events_n += 1
                    if events_n % 2000 == 0:
                        f_events.flush()
                        f_out.flush()
                acks.write(nats_wire.ack(frame.reply))
                last_msg = clock()
            elif code is not None:
                if code[0] in ENDED or code == (nats_wire.CONFLICT, LEADERSHIP_CHANGE):
                    # The request its subject names is over: another goes in its place before
                    # anything else.
                    ask()
                    if frame.subject not in waiting:
                        raise RuntimeError(
                            "a status %d %s for pull request %s, which was not waiting: the "
                            "messages have not answered the requests oldest first, or one was "
                            "answered twice" % (code + (frame.subject[len(pulls_dot):],)))
                    waiting.remove(frame.subject)
                    ended[code[0]] = ended.get(code[0], 0) + 1
                elif code[0] != nats_wire.HEARTBEAT:
                    raise RuntimeError("the server refused or ended a pull request: %d %s" % code)
            elif frame is not None and frame.op == "PONG":
                pongs += 1

            now = clock()
            if now - serviced >= SERVICE_S:
                acks.service()
                serviced = now
            if not delivered and now - last_msg >= args.idle_seconds:
                break
            if probe_s and now - probed >= probe_s:
                # Only now, with the frame handled and any replacement it called for sent.
                receive.write(nats_wire.PING)
                probes += 1
                probed = now

    if args.delete_stream:
        nats_wire.api(acks, *nats_wire.stream_delete(args.stream))
    receive.close()
    acks.close()
    _rt = Path(args.out).with_name(Path(args.out).stem + '_readtrace.csv')
    with _rt.open('w', newline='', encoding='utf-8') as _f:
        _w = csv.writer(_f)
        _w.writerow(['t_read_start_ns', 'read_duration_ns', 'n_messages'])
        _w.writerows(read_trace)
    if record is not None:
        record.write(thread_record.beside(out_path))
    so_timestamps.finish(so, args)
    client_quiet.finish(quiet, args)
    print(f"OK nats consumer: {asked} pull requests sent, "
          f"{sum(ended.values())} ended without a message and replaced {sorted(ended.items())}, "
          f"{redelivered} redeliveries not written"
          f"{', stream deleted' if args.delete_stream else ''}")
    print(f"OK nats consumer: {probes} probes sent on the receive connection, {pongs} PONGs read")
    print(f"OK nats consumer: wrote {n} rows -> {out_path}")
    print(f"OK nats consumer: wrote {events_n} rows -> {events_path}")


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
