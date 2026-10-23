#!/usr/bin/env python3
"""
rabbitmq_producer.py -- the plan's messages published to a RabbitMQ queue of the run's own, each
confirmed by the broker, as scripts/redis_producer.py sends them to Redis.

The plan is read as the Redis producer reads it: the rows at or before --max-t-sim, in the order of
their simulated time and row, each sent at its offset over --speedup after the start, with the same
JSON payload. Each message goes to the default exchange with the queue's name as its routing key,
transient, its event id in the AMQP message-id property: a reader of the wire knows it by that
property and the confirm number below, never by its payload (scripts/amqp_frames.py).

The channel asks for publisher confirms, so the broker numbers the publishes from 1 in their order
and confirms each with a basic.ack carrying its number, or with multiple set every publish up to it
(rabbitmq.com/docs/confirms). producer.csv carries the Redis producer's columns, the queue's name
under `stream` and, in place of `redis_id`, each publish's confirm number as `delivery_tag`;
t_broker_ack_ns is the wall clock as the confirm that covered the message was read.

pika's asynchronous adapter runs on this thread alone, its loop turned here: each publish leaves at
its planned time, and each confirm is stamped in the turn that reads it.
"""
import argparse
import csv
import json
import time
from pathlib import Path

import pandas as pd

import law_clock
import thread_record
import so_timestamps
import client_quiet
import rabbitmq_consumer as rabbit

TRANSIENT = 1
ANSWER_S = 30.0


def now_ns():
    """Wall-clock epoch nanoseconds, time.time_ns, as the other clients stamp: one epoch with the
    consumer's process, so that a difference of the two is a latency."""
    return time.time_ns()


def _nothing():
    """A timer's callback: the timer is there to bound pika's wait, and does nothing itself."""


def read_plan(path, max_t_sim):
    """[(event id, match id, simulated second, emission offset in s)], as the Redis producer reads
    the plan: the rows at or before max_t_sim, by simulated time and then row, the sort stable."""
    plan = pd.read_csv(path)
    plan = plan[plan["t_sim_seconds"] <= max_t_sim].copy()
    plan = plan.sort_values(["t_sim_seconds", "row_idx"], kind="mergesort").reset_index(drop=True)
    return [(str(e), int(m), int(t), float(o)) for e, m, t, o in zip(
        plan["event_id"], plan["match_id"], plan["t_sim_seconds"], plan["t_emit_offset_s"])]


def payload(run_id, event_id, match_id, t_sim, t_emit_offset_s, t_emit_planned_ns, pad_bytes):
    """The Redis producer's message, field for field, as UTF-8 JSON."""
    msg = {
        "run_id": run_id,
        "match_id": match_id,
        "event_id": event_id,
        "t_sim_seconds": t_sim,
        "t_emit_offset_s": t_emit_offset_s,
        "t_emit_planned_ns": t_emit_planned_ns,
        "s3_uid": f"{match_id}:{event_id}",
        "s3_rev": 1,
        "s3_is_correction": False,
    }
    if pad_bytes > 0:
        msg["pad"] = "x" * pad_bytes
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class Publisher(object):
    """A connection, its channel in confirm mode, and the confirms as they are read: pika's
    asynchronous adapter, its loop turned by this thread alone.

    23 Oct 2026: not pika's blocking channel, which in confirm mode returns from each publish only
    once that publish's own confirm has come (pika 1.3.2, adapters/blocking_connection.py), a round
    trip per message. Block U's pilot found each TCP connection on the testbed with its own delay,
    about 330, 500, 590 or 655 us, and at 2,000 messages a second one is due every 500 us. The loop
    is made, its poller activated and the connection opened on it as pika's blocking adapter makes
    its own, and turned with the same two calls, poll and process_timeouts."""

    def __init__(self, pika, uri, queue, clock=time.monotonic, record=None):
        self.pika, self.queue, self.clock, self.record = pika, queue, clock, record
        self.channel = None
        self.ready = self.closing = self.closed = False
        self.failed = None
        self.number = 0
        self.lowest = 1
        self.waiting = {}
        self.acked = {}
        self.refused = []
        self.loop = pika.adapters.select_connection.IOLoop()
        self.loop.activate_poller()
        self.connection = pika.SelectConnection(
            parameters=pika.URLParameters(uri), on_open_callback=self._opened,
            on_open_error_callback=self._open_failed, on_close_callback=self._closed,
            custom_ioloop=self.loop)

    # --- pika's callbacks, each run inside a turn of the loop -----------------------------------

    def _opened(self, connection):
        connection.channel(on_open_callback=self._channel_opened)

    def _open_failed(self, _connection, error):
        self.failed = "the connection could not be opened: %r" % (error,)

    def _closed(self, _connection, reason):
        self.closed = True
        if not self.closing:
            self.failed = self.failed or "the connection closed: %r" % (reason,)

    def _channel_opened(self, channel):
        self.channel = channel
        channel.add_on_close_callback(self._channel_closed)
        rabbit.declare(channel, self.queue, callback=self._declared)

    def _channel_closed(self, _channel, reason):
        if not self.closing:
            self.failed = self.failed or "the channel closed: %r" % (reason,)

    def _declared(self, _frame):
        self.channel.confirm_delivery(ack_nack_callback=self._confirmed, callback=self._selected)

    def _selected(self, _frame):
        self.ready = True

    def _confirmed(self, frame):
        """A basic.ack or basic.nack: the wall clock now, for every publish it covers."""
        ns = now_ns()
        if self.record is not None:
            self.record.note("stamps_ack")
        method = frame.method
        refused = method.NAME == "Basic.Nack"
        numbers = range(self.lowest, method.delivery_tag + 1) if method.multiple \
            else (method.delivery_tag,)
        for number in numbers:
            index = self.waiting.pop(number, None)
            if index is None:
                continue
            if refused:
                self.refused.append(number)
            else:
                self.acked[index] = ns
        while self.lowest <= self.number and self.lowest not in self.waiting:
            self.lowest += 1

    # --- the loop -------------------------------------------------------------------------------

    def turn(self, wait):
        """One pass of pika's loop, waiting at most `wait` seconds for the socket: what is buffered
        is sent, what arrived is read and its callbacks run, and the timers that are due fire."""
        timer = self.loop.call_later(max(0.0, wait), _nothing)
        self.loop.poll()
        self.loop.process_timeouts()
        self.loop.remove_timeout(timer)

    def serve(self, until, done=lambda: False):
        """Turn the loop until done() holds or the monotonic clock reaches `until`; whether done()
        held."""
        while not done():
            left = until - self.clock()
            if left <= 0:
                return False
            self.turn(left)
        return True

    def open(self, seconds=ANSWER_S):
        """Turn the loop until the channel is open in confirm mode on the declared queue; a stop
        where the broker refused or did not answer within `seconds`."""
        if not self.serve(self.clock() + seconds, lambda: self.ready or self.failed is not None):
            raise SystemExit("the RabbitMQ producer: no channel in confirm mode within %g s"
                             % seconds)
        if self.failed is not None:
            raise SystemExit("the RabbitMQ producer: %s" % self.failed)

    def publish(self, body, message_id, index):
        """Publish one message, transient (delivery mode 1) with its event id as its message-id,
        send it at once, and return its confirm number."""
        self.channel.basic_publish(
            exchange="", routing_key=self.queue, body=body,
            properties=self.pika.BasicProperties(message_id=message_id, delivery_mode=TRANSIENT))
        self.number += 1
        self.waiting[self.number] = index
        self.turn(0)
        return self.number

    def finish(self, seconds=ANSWER_S):
        """Wait up to `seconds` for the confirms still owed, close the connection, and raise where a
        publish was refused or went unconfirmed, or the connection failed."""
        self.serve(self.clock() + seconds, lambda: not self.waiting or self.failed is not None)
        failed, refused, missing = self.failed, sorted(self.refused), sorted(self.waiting)
        if not self.closed:
            self.closing = True
            self.connection.close()
            self.serve(self.clock() + seconds, lambda: self.closed)
        if failed is not None:
            raise RuntimeError("the RabbitMQ producer: %s" % failed)
        if refused:
            raise RuntimeError("RabbitMQ refused %d publishes with basic.nack (first 5 numbers: %s)"
                               % (len(refused), refused[:5]))
        if missing:
            raise RuntimeError("%d publishes had no confirm within %g s (first 5 numbers: %s)"
                               % (len(missing), seconds, missing[:5]))


def main(argv=None, pika=None, clock=time.monotonic):
    ap = argparse.ArgumentParser(
        description="The plan's messages, published to RabbitMQ with publisher confirms")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--plan-csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--uri", default=rabbit.DEFAULT_URI,
                    help="amqp://user:password@host:port[/vhost]")
    ap.add_argument("--queue", default=None, help="the run's own queue; sb-events-<run id> unless "
                                                  "named")
    ap.add_argument("--speedup", type=float, default=120.0)
    ap.add_argument("--max-t-sim", type=int, default=600)
    ap.add_argument("--pad-bytes", type=int, default=0,
                    help="pad each message with this many filler bytes, as the other producers do; "
                         "0 (default) leaves the payload untouched")
    ap.add_argument("--thread-record", action="store_true",
                    help="write which threads stamped what, and both clocks, beside the CSV")
    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    args = ap.parse_args(argv)
    record = thread_record.ThreadRecord() if args.thread_record else None
    port = rabbit.broker_port(args.uri)
    so = so_timestamps.start(args, port)
    resolution = law_clock.demand_usable_resolution("the RabbitMQ producer")
    plan = read_plan(args.plan_csv, args.max_t_sim)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    queue = args.queue or rabbit.queue_name(args.run_id)

    pika = pika or rabbit.load_pika()
    poller = rabbit.use_select(pika)
    publisher = Publisher(pika, args.uri, queue, clock, record)
    publisher.open()
    sockets = rabbit.check_shim(so, port, "the RabbitMQ producer")
    print("CONFIG effective confirms=asynchronous poller=%s queue=%s broker=%s so_connections=%s "
          "client=python clock_resolution_ns=%d"
          % (poller, queue, rabbit.broker_address(args.uri), sockets, resolution), flush=True)
    # 23 Oct 2026: as in the other clients since freeze 43, whose pilot found the clients' pauses
    # to be CPython's full collections, the collector goes off where the run asks once the client
    # is connected and before t0, so that its one collection delays no message's schedule.
    quiet = client_quiet.start(args)

    t0_wall_ns = now_ns()
    t0_mono = clock()
    sent = []
    for index, (event_id, match_id, t_sim, t_emit_offset_s) in enumerate(plan):
        due_s = t_emit_offset_s / args.speedup
        t_prod_sched_ns = t0_wall_ns + int(due_s * 1e9)
        body = payload(args.run_id, event_id, match_id, t_sim, t_emit_offset_s, t_prod_sched_ns,
                       args.pad_bytes)
        publisher.serve(t0_mono + due_s)
        t_prod_send_ns = now_ns()
        if record is not None:
            record.note("stamps_send")
        number = publisher.publish(body, event_id, index)
        sent.append((event_id, match_id, t_sim, t_emit_offset_s, t_prod_sched_ns, t_prod_send_ns,
                     number))
    publisher.finish()

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "run_id", "backend", "stream", "event_id", "match_id", "t_sim_seconds",
            "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns",
            "delivery_tag"])
        w.writeheader()
        for index, (event_id, match_id, t_sim, t_emit_offset_s, t_prod_sched_ns, t_prod_send_ns,
                    number) in enumerate(sent):
            w.writerow({
                "run_id": args.run_id, "backend": "rabbitmq", "stream": queue,
                "event_id": event_id, "match_id": match_id, "t_sim_seconds": t_sim,
                "t_emit_offset_s": t_emit_offset_s, "t_prod_sched_ns": t_prod_sched_ns,
                "t_prod_send_ns": t_prod_send_ns, "t_broker_ack_ns": publisher.acked[index],
                "delivery_tag": number,
            })

    if record is not None:
        record.write(thread_record.beside(out_path))
    so_timestamps.finish(so, args)
    client_quiet.finish(quiet, args)
    print("OK rabbitmq producer: wrote %d rows -> %s" % (len(sent), out_path))


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
