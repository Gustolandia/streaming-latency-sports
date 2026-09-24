"""Our own AMQP client, the reference rabbitmq-perftest had never had.

A scripted broker in pika's blocking shape stands in for RabbitMQ, so nothing needs installing
here: pika is imported only when the client really runs, on the driver.
"""
import io
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import amqp_reference as ar  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1e9)


class Broker:
    """Delivers each publish, counted from 0, after `trip_ms`; `drop` delivers nothing, so the
    timer fires; `stale` first redelivers the message before it."""

    def __init__(self, clock, trip_ms=1.0, drop=(), stale=()):
        self.clock, self.trip, self.drop, self.stale = clock, trip_ms, set(drop), set(stale)
        self.callback, self.pending, self.timers, self.published, self.closed = None, [], [], 0, 0
        self.last = None

    def connect(self):
        return Connection(self)


class Connection:
    def __init__(self, broker):
        self.broker = broker

    def channel(self):
        return Channel(self.broker)

    def call_later(self, delay, callback):
        timer = (delay, callback)
        self.broker.timers.append(timer)
        return timer

    def remove_timeout(self, timer):
        self.broker.timers.remove(timer)

    def process_data_events(self, time_limit=None):
        broker = self.broker
        assert time_limit is None, "it blocks until something happens"
        if broker.pending:
            body = broker.pending.pop(0)
            broker.clock.now += int(broker.trip * 1e6)
            broker.callback(None, None, None, body)
        else:
            delay, callback = broker.timers[-1]
            broker.clock.now += int(delay * 1e9)
            callback()

    def close(self):
        self.broker.closed += 1


class Channel:
    def __init__(self, broker):
        self.broker = broker

    def queue_declare(self, queue, exclusive, auto_delete):
        assert exclusive and auto_delete, "a queue of our own, gone when we are"
        return types.SimpleNamespace(method=types.SimpleNamespace(queue="amq.gen-ours"))

    def basic_consume(self, queue, on_message_callback, auto_ack):
        self.broker.callback = on_message_callback

    def basic_publish(self, exchange, routing_key, body):
        broker, n = self.broker, self.broker.published
        broker.published += 1
        assert routing_key == "amq.gen-ours" and len(body) == 512
        if n in broker.stale and broker.last is not None:
            broker.pending.append(broker.last)
        if n not in broker.drop:
            broker.pending.append(body)
        broker.last = body


def run(rate=10.0, seconds=1.0, warmup_s=0.0, **options):
    clock = Clock()
    broker = Broker(clock, **options)
    found = ar.trips("amqp://guest:guest@broker:5672", rate, seconds, warmup_s, clock=clock,
                     sleep=clock.sleep, connect=broker.connect)
    return found, broker


class TestTheTrips:

    def test_each_trip_is_from_publish_to_delivery(self):
        (found, sent, lost), broker = run(trip_ms=1.5)
        assert sent == 10 and lost == 0 and found[0] == pytest.approx(1.5)
        assert broker.closed == 2, "both connections are closed"

    def test_the_warm_up_is_timed_and_set_aside(self):
        (found, sent, _), _ = run(warmup_s=0.5)
        assert sent == 10 and len(found) == 5

    def test_a_message_that_never_arrives_is_lost_once_its_timer_fires(self):
        (found, _, lost), broker = run(drop={4})
        assert lost == 1 and len(found) == 9 and broker.timers == [], "every timer removed"

    def test_one_delivered_again_late_is_not_read_as_the_next(self):
        (found, _, lost), _ = run(stale={6})
        assert lost == 0 and len(found) == 10


class TestTheClient:

    def test_it_is_pika_and_only_when_it_runs(self, monkeypatch):
        """The tests need nothing installed; the driver has pika, pinned by tools.sh install."""
        fake = types.ModuleType("pika")
        fake.URLParameters = lambda uri: ("parameters", uri)
        fake.BlockingConnection = lambda parameters: ("connection", parameters)
        monkeypatch.setitem(sys.modules, "pika", fake)
        connect = ar._pika_connect("amqp://guest:guest@broker:5672")
        assert connect() == ("connection", ("parameters", "amqp://guest:guest@broker:5672"))


class TestTheCommand:

    def command(self, tmp_path, **options):
        clock = Clock()
        broker = Broker(clock, **options)
        out, said = tmp_path / "ref.json", io.StringIO()
        code = ar.main(["--uri", "amqp://guest:guest@broker:5672", "--seconds", "1", "--rate",
                        "10", "--warmup-s", "0", "--out", str(out)], said, connect=broker.connect,
                       clock=clock, sleep=clock.sleep)
        return code, said.getvalue(), json.loads(out.read_text(encoding="utf-8"))

    def test_it_writes_the_trips_and_never_the_password(self, tmp_path):
        code, said, written = self.command(tmp_path, trip_ms=2.0)
        assert code == 0 and "median 2.000 ms" in said
        assert written["target"] == "broker:5672" and "guest" not in json.dumps(written)

    def test_a_run_with_no_trip_leaves_with_one(self, tmp_path):
        code, said, written = self.command(tmp_path, drop=set(range(10)))
        assert code == 1 and "no trip was timed" in said and written["lost"] == 10
