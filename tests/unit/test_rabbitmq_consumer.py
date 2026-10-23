"""Tests for scripts/rabbitmq_consumer.py: the run's messages pushed by RabbitMQ, acknowledged by
hand, and written as the Redis consumer writes them, and the probe on a second channel of the
consumer's connection.

pika is not installed here. A broker in pika's blocking shape stands in for it, holding back any
delivery beyond the consumer's prefetch count still unacknowledged, as RabbitMQ does, with the
loop and the asynchronous channel under pika's blocking ones as far as the probe uses them. The
last tests go further: a consumer whose pika makes and drives its socket as pika 1.3.2 does,
through a real connection to a broker that speaks AMQP 0-9-1, with the socket timestamps on; what
their journal kept is then read back with scripts/amqp_frames.py."""
import csv
import gc
import json
import os
import select
import socket
import struct
import sys
import threading
import time
import types
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import amqp_frames as af  # noqa: E402
import client_quiet  # noqa: E402
import rabbitmq_consumer as rc  # noqa: E402
import so_timestamps  # noqa: E402

RUN = "r47"


class Clock(object):
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def message(eid, run=RUN, message_id=None):
    """A message as the producer sends it: its event id as message-id, the payload as JSON."""
    body = json.dumps({"run_id": run, "match_id": 7, "event_id": eid, "t_sim_seconds": 3,
                       "t_emit_offset_s": 0.25, "t_emit_planned_ns": 123, "s3_uid": "7:" + eid,
                       "s3_rev": 1, "s3_is_correction": False}, separators=(",", ":"))
    return (eid if message_id is None else message_id), body.encode("utf-8")


#: How long the broker takes to answer a probe, in s: a binary fraction, so that the test's clock
#: adds it without rounding.
TRIP = 2.0 ** -12


class Broker(object):
    """RabbitMQ as one consumer meets it through pika's blocking adapter: each wait delivers the
    queue's messages while fewer than the prefetch count are unacknowledged, 0 holding back none,
    and an empty wait lets its time limit pass, firing on the way the loop's timers and the
    broker's answers as they fall due. A probe is answered `trip` after it was sent; a broker may
    never answer, or close the probe's channel in place of answering its `close_probes_at`-th."""

    def __init__(self, messages, clock, trip=TRIP, answer=True, close_probes_at=None):
        self.queue = list(messages)
        self.clock = clock
        self.events = []
        self.prefetch = None
        self.callback = None
        self.unacked = set()
        self.tag = 0
        self.poller_at_connect = None
        self.trip, self.answer, self.close_probes_at = trip, answer, close_probes_at
        self.timers, self.arrivals = [], []
        self.consumed_on, self.acked_on = None, set()
        self.armed_at_close = None
        self.pika = types.SimpleNamespace(
            adapters=types.SimpleNamespace(select_connection=types.SimpleNamespace(
                SELECT_TYPE=None)),
            URLParameters=lambda uri: ("parameters", uri),
            BlockingConnection=self.connect)

    def connect(self, parameters):
        self.poller_at_connect = self.pika.adapters.select_connection.SELECT_TYPE
        self.events.append(("connect", parameters[1]))
        self.connection = Connection(self)
        return self.connection

    def run(self, until):
        """Fire, in their order, the loop's timers and the broker's answers that fall due by
        `until`, moving the clock to each and then to `until`."""
        while True:
            due = [t for t in self.timers + self.arrivals if t[1] is not None and t[0] <= until]
            if not due:
                break
            first = min(due, key=lambda t: t[0])
            callback, first[1] = first[1], None
            self.clock.now = max(self.clock.now, first[0])
            callback()
        self.clock.now = max(self.clock.now, until)


class Loop(object):
    """The loop under pika's blocking connection (BlockingConnection._impl.ioloop), as far as the
    probe uses it: timers, which the waits fire as they pass them."""

    def __init__(self, broker):
        self.broker = broker

    def call_later(self, delay, callback):
        assert delay >= 0, "pika refuses a negative delay"
        timer = [self.broker.clock.now + delay, callback]
        self.broker.timers.append(timer)
        return timer

    def remove_timeout(self, timer):
        timer[1] = None


class Connection(object):
    def __init__(self, broker):
        self.broker = broker
        self.channels = []
        self._impl = types.SimpleNamespace(ioloop=Loop(broker))

    def channel(self):
        """The next channel, numbered from 1 as pika numbers them."""
        made = Channel(self.broker, len(self.channels) + 1)
        self.channels.append(made)
        self.broker.events.append(("channel", made.channel_number))
        return made

    def process_data_events(self, time_limit):
        b = self.broker
        b.events.append(("wait", time_limit))
        credit = len(b.queue) if not b.prefetch else max(0, b.prefetch - len(b.unacked))
        batch = b.queue[:credit] if b.callback else []
        del b.queue[:len(batch)]
        b.run(b.clock.now if batch else b.clock.now + time_limit)
        for message_id, body in batch:
            b.tag += 1
            b.unacked.add(b.tag)
            b.events.append(("deliver", b.tag, gc.isenabled()))
            b.callback(self.channels[b.consumed_on - 1],
                       types.SimpleNamespace(delivery_tag=b.tag),
                       types.SimpleNamespace(message_id=message_id), body)

    def close(self):
        """As pika closes it: each channel's close waits for the answer to its last request, and
        the connection's for the channels'."""
        b = self.broker
        b.armed_at_close = sum(1 for t in b.timers if t[1] is not None)
        b.run(max([b.clock.now] + [a[0] for a in b.arrivals if a[1] is not None]))
        b.events.append(("close",))


class Channel(object):
    def __init__(self, broker, number):
        self.broker, self.channel_number = broker, number
        self._impl = Asynchronous(broker, number)

    def queue_declare(self, queue, durable, arguments):
        self.broker.events.append(("declare", queue, durable, arguments))

    def basic_qos(self, prefetch_count, global_qos):
        self.broker.prefetch = prefetch_count
        self.broker.events.append(("qos", prefetch_count, global_qos))

    def basic_consume(self, queue, on_message_callback, auto_ack):
        self.broker.callback = on_message_callback
        self.broker.consumed_on = self.channel_number
        self.broker.events.append(("consume", queue, auto_ack, gc.isenabled()))

    def basic_ack(self, delivery_tag, multiple):
        b = self.broker
        b.acked_on.add(self.channel_number)
        b.events.append(("ack", delivery_tag, multiple))
        covered = set(t for t in b.unacked if t <= delivery_tag) if multiple else {delivery_tag}
        assert covered <= b.unacked and covered, "RabbitMQ closes a channel for an unknown tag"
        b.unacked -= covered


class Asynchronous(object):
    """The asynchronous channel under a blocking one (BlockingChannel._impl), as far as the probe
    uses it: a passive queue.declare sent at once, and answered in a later turn of the loop. As
    pika does, it refuses a request on a channel that is not open; it also refuses one sent while
    the channel's last is unanswered, which pika would hold back and send late."""

    def __init__(self, broker, number):
        self.broker, self.number = broker, number
        self.is_open = True
        self.asked = 0
        self.waiting = False

    def queue_declare(self, queue, passive, callback):
        b = self.broker
        assert self.is_open, "pika raises ChannelWrongStateError on a channel that is not open"
        assert not self.waiting, "pika would send this only once the last was answered"
        self.asked += 1
        self.waiting = True
        b.events.append(("probe", self.number, queue, passive, b.clock.now))
        if self.asked == b.close_probes_at:
            b.arrivals.append([b.clock.now + b.trip, self.closed])
        elif b.answer:
            b.arrivals.append([b.clock.now + b.trip, lambda: self.answered(queue, callback)])

    def answered(self, queue, callback):
        self.waiting = False
        self.broker.events.append(("probe-ok", self.number, self.broker.clock.now))
        callback(types.SimpleNamespace(method=types.SimpleNamespace(
            queue=queue, message_count=len(self.broker.queue), consumer_count=1)))

    def closed(self):
        """channel.close from the broker, as RabbitMQ sends one where the queue has gone."""
        self.is_open = False
        self.broker.events.append(("probe-channel-closed", self.number, self.broker.clock.now))


def run(tmp_path, messages, *extra, broker=None, idle="2"):
    clock = Clock()
    broker = broker or Broker(messages, clock)
    out = tmp_path / "consumer.csv"
    rc.main(["--run-id", RUN, "--out", str(out), "--idle-seconds", idle] + list(extra),
            pika=broker.pika, clock=broker.clock)
    return broker, out


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def columns(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh))


def of(broker, kind):
    return [e for e in broker.events if e[0] == kind]


class TestTheFilesAreTheRedisConsumersWithRabbitMQsIds:

    def test_the_two_files_and_their_columns(self, tmp_path):
        _, out = run(tmp_path, [message("constant-000001"), message("constant-000002")])
        assert columns(out) == ["run_id", "backend", "stream", "event_id", "match_id",
                                "t_sim_seconds", "t_cons_recv_ns", "t_output_ns", "delivery_tag"]
        events = tmp_path / "consumer_events.csv"
        assert columns(events) == ["run_id", "backend", "stream", "message_id", "delivery_tag",
                                   "t_consume_ns", "event_id", "match_id", "t_sim_seconds",
                                   "t_emit_offset_s", "t_emit_planned_ns", "s3_uid", "s3_rev",
                                   "s3_is_correction"]
        written, logged = rows(out), rows(events)
        assert [(r["event_id"], r["delivery_tag"], r["stream"], r["backend"]) for r in written] \
            == [("constant-000001", "1", "sb-events-r47", "rabbitmq"),
                ("constant-000002", "2", "sb-events-r47", "rabbitmq")]
        assert [(r["message_id"], r["delivery_tag"], r["s3_uid"], r["t_emit_planned_ns"])
                for r in logged] == [("constant-000001", "1", "7:constant-000001", "123"),
                                     ("constant-000002", "2", "7:constant-000002", "123")]
        assert all(r["t_consume_ns"] == w["t_cons_recv_ns"] for r, w in zip(logged, written)), \
            "one reading of the clock under two names"
        assert all(int(w["t_output_ns"]) >= int(w["t_cons_recv_ns"]) for w in written)

    def test_the_message_id_comes_from_the_properties_and_never_the_payload(self, tmp_path):
        _, out = run(tmp_path, [message("constant-000001", message_id="constant-999999")])
        logged = rows(tmp_path / "consumer_events.csv")
        assert (logged[0]["message_id"], logged[0]["event_id"]) == ("constant-999999",
                                                                    "constant-000001")

    def test_another_runs_message_is_acknowledged_alone_and_not_written(self, tmp_path):
        broker, out = run(tmp_path, [message("constant-000001", run="old"),
                                     message("constant-000002")], "--prefetch", "1")
        assert [r["event_id"] for r in rows(out)] == ["constant-000002"]
        assert of(broker, "ack") == [("ack", 1, False), ("ack", 2, False)], \
            "its credit came back, so the next message still came"

    def test_it_says_what_it_wrote_and_how_it_ran(self, tmp_path, capsys):
        run(tmp_path, [message("constant-000001")], "--uri",
            "amqp://guest:secret@10.2.1.21:5672", "--prefetch", "1000", "--ack-batch", "50")
        said = capsys.readouterr().out
        assert ("CONFIG effective prefetch=1000 ack_batch=50 ack_multiple=True probe_ms=100 "
                "probe_channel=2 poller=select queue=sb-events-r47 broker=10.2.1.21:5672 "
                "so_connections=None client=python clock_resolution_ns=") in said
        assert "secret" not in said and "guest" not in said
        assert "OK rabbitmq consumer: wrote 1 rows -> " in said
        assert said.count("OK rabbitmq consumer: wrote 1 rows") == 2

    def test_the_files_are_flushed_every_2000_rows(self, tmp_path):
        _, out = run(tmp_path, [message("constant-%06d" % i) for i in range(2001)],
                     "--prefetch", "0")
        assert len(rows(out)) == 2001


class TestTheBrokerTheQueueAndTheCredit:

    def test_the_queue_is_the_runs_own_declared_as_the_producer_declares_it(self, tmp_path):
        broker, _ = run(tmp_path, [])
        assert of(broker, "declare") == [("declare", "sb-events-r47", True,
                                          {"x-queue-type": "classic", "x-expires": 600000})]
        broker, _ = run(tmp_path, [], "--queue", "mine")
        assert of(broker, "declare")[0][1] == "mine" and of(broker, "consume")[0][1] == "mine"

    def test_the_prefetch_is_set_for_this_consumer_before_it_subscribes(self, tmp_path):
        broker, _ = run(tmp_path, [message("constant-000001")], "--prefetch", "1000")
        kinds = [e[0] for e in broker.events]
        assert kinds.index("qos") < kinds.index("consume")
        assert of(broker, "qos") == [("qos", 1000, False)], "per consumer: global unset"
        assert of(broker, "consume")[0][2] is False, "acknowledged by hand"

    def test_pika_is_given_the_select_poller_before_it_connects(self, tmp_path):
        broker, _ = run(tmp_path, [], "--uri", "amqp://guest:guest@broker:5673")
        assert broker.poller_at_connect == "select"
        assert broker.events[0] == ("connect", "amqp://guest:guest@broker:5673")

    def test_at_prefetch_1_each_message_waits_for_the_ack_of_the_one_before(self, tmp_path):
        broker, _ = run(tmp_path, [message("constant-%06d" % i) for i in range(3)],
                        "--prefetch", "1")
        moves = [e[:2] for e in broker.events if e[0] in ("wait", "deliver", "ack")][:9]
        assert moves == [("wait", 1.0), ("deliver", 1), ("ack", 1), ("wait", 1.0),
                         ("deliver", 2), ("ack", 2), ("wait", 1.0), ("deliver", 3), ("ack", 3)]

    def test_at_prefetch_1000_a_credit_is_always_waiting(self, tmp_path):
        for prefetch in ("1000", "0"):
            broker, _ = run(tmp_path, [message("constant-%06d" % i) for i in range(3)],
                            "--prefetch", prefetch)
            moves = [e[:2] for e in broker.events if e[0] in ("wait", "deliver")][:4]
            assert moves == [("wait", 1.0), ("deliver", 1), ("deliver", 2), ("deliver", 3)]

    def test_it_stops_once_no_message_came_for_the_idle_seconds(self, tmp_path):
        broker, _ = run(tmp_path, [message("constant-000001")], "--block-ms", "500")
        waits = of(broker, "wait")
        assert waits == [("wait", 0.5)] * 5, "one wait with the message, then 2 s of empty ones"
        assert broker.events[-1] == ("close",)


class TestTheAcknowledgments:

    def test_each_is_acknowledged_alone_once_its_rows_are_written(self, tmp_path, monkeypatch):
        order = []
        real = csv.DictWriter.writerow
        monkeypatch.setattr(csv.DictWriter, "writerow",
                            lambda self, row: order.append("row") or real(self, row))
        broker = Broker([message("constant-000001"), message("constant-000002")], Clock())
        acked = Channel.basic_ack
        monkeypatch.setattr(Channel, "basic_ack",
                            lambda self, **kw: order.append("ack") or acked(self, **kw))
        run(tmp_path, [], "--ack-each", broker=broker)
        assert order[-6:] == ["row", "row", "ack", "row", "row", "ack"]
        assert of(broker, "ack") == [("ack", 1, False), ("ack", 2, False)]

    def test_in_batches_with_multiple_and_the_rest_when_none_comes(self, tmp_path):
        broker, out = run(tmp_path, [message("constant-%06d" % i) for i in range(5)],
                          "--prefetch", "0", "--ack-batch", "2")
        assert of(broker, "ack") == [("ack", 2, True), ("ack", 4, True), ("ack", 5, True)]
        assert broker.unacked == set() and len(rows(out)) == 5

    @pytest.mark.parametrize("extra,said", [
        (["--prefetch", "-1"], "--prefetch is a count of messages, 0 for no limit, not -1"),
        (["--ack-batch", "0"], "--ack-batch is at least 1, not 0"),
        (["--prefetch", "1", "--ack-batch", "2"], "--ack-batch 2 is more than the 1 "
                                                  "unacknowledged messages --prefetch lets"),
        (["--ack-each", "--ack-batch", "2"], "not allowed with argument"),
        (["--probe-ms", "-1"], "--probe-ms is the time between probes in ms, 0 for none, not -1"),
    ])
    def test_a_setting_that_could_not_run_as_written_is_refused(self, tmp_path, capsys, extra,
                                                                said):
        with pytest.raises(SystemExit):
            run(tmp_path, [], *extra)
        assert said in capsys.readouterr().err

    def test_a_batch_up_to_the_prefetch_runs(self, tmp_path):
        broker, _ = run(tmp_path, [message("constant-%06d" % i) for i in range(4)],
                        "--prefetch", "2", "--ack-batch", "2")
        assert of(broker, "ack") == [("ack", 2, True), ("ack", 4, True)]


class TestTheProbe:
    """--probe-ms: a passive queue.declare of the queue on a second channel of the connection, sent
    and answered in the loop's own turns."""

    def test_on_a_second_channel_every_probe_ms_a_passive_declare_of_the_queue(self, tmp_path):
        broker, _ = run(tmp_path, [message("constant-000001")], "--probe-ms", "250")
        assert of(broker, "channel") == [("channel", 1), ("channel", 2)]
        assert (broker.consumed_on, broker.acked_on) == (1, {1}), "the first channel consumes"
        probes = of(broker, "probe")
        assert set(p[1:4] for p in probes) == {(2, "sb-events-r47", True)}, \
            "every probe on the second channel, none on the consuming one"
        sent = [p[4] for p in probes]
        assert sent == [100.0 + 0.25 * k for k in range(1, 9)], "every 250 ms from the subscription"
        assert [e[2] for e in of(broker, "probe-ok")] == [t + TRIP for t in sent]

    def test_the_deliveries_the_acknowledgments_and_the_waits_are_those_without_it(self, tmp_path):
        def run_with(probe_ms):
            broker, out = run(tmp_path, [message("constant-%06d" % i) for i in range(5)],
                              "--prefetch", "2", "--ack-batch", "2", "--probe-ms", probe_ms)
            moves = [e for e in broker.events if e[0] not in ("channel", "probe", "probe-ok")]
            written = [(r["event_id"], r["delivery_tag"]) for r in rows(out)]
            return moves, written, len(of(broker, "probe"))
        probed, plain = run_with("125"), run_with("0")
        assert probed[:2] == plain[:2] and (probed[2], plain[2]) == (16, 0)
        assert [e for e in plain[0] if e[0] == "ack"] == [("ack", 2, True), ("ack", 4, True),
                                                          ("ack", 5, True)], \
            "a batch's remainder is acknowledged after an empty wait, probes or none"

    def test_none_is_sent_while_the_last_is_unanswered(self, tmp_path, capsys):
        broker = Broker([message("constant-000001")], Clock(), answer=False)
        run(tmp_path, [], "--probe-ms", "250", broker=broker)
        assert [p[4] for p in of(broker, "probe")] == [100.25]
        assert ("OK rabbitmq consumer: 1 probes on channel 2, 0 answered, 7 not sent while one "
                "was unanswered") in capsys.readouterr().out

    def test_a_probe_channel_the_broker_closes_ends_the_probes_and_nothing_else(self, tmp_path,
                                                                               capsys):
        broker = Broker([message("constant-000001"), message("constant-000002")], Clock(),
                        close_probes_at=3)
        _, out = run(tmp_path, [], "--probe-ms", "250", broker=broker)
        assert [p[4] for p in of(broker, "probe")] == [100.25, 100.5, 100.75]
        assert of(broker, "probe-channel-closed") == [("probe-channel-closed", 2, 100.75 + TRIP)]
        assert len(rows(out)) == 2 and of(broker, "ack") == [("ack", 1, False), ("ack", 2, False)]
        assert broker.armed_at_close == 0
        assert ("OK rabbitmq consumer: 3 probes on channel 2, 2 answered, 0 not sent while one "
                "was unanswered") in capsys.readouterr().out

    def test_its_timer_is_gone_before_the_connection_closes_and_each_is_answered(self, tmp_path,
                                                                                capsys):
        broker, _ = run(tmp_path, [message("constant-000001")])
        assert broker.armed_at_close == 0 and broker.events[-1] == ("close",)
        answered = len(of(broker, "probe-ok"))
        assert answered == len(of(broker, "probe")) > 0
        assert ("OK rabbitmq consumer: %d probes on channel 2, %d answered, 0 not sent while one "
                "was unanswered" % (answered, answered)) in capsys.readouterr().out

    def test_at_0_no_channel_is_opened_and_none_is_sent(self, tmp_path, capsys):
        broker, _ = run(tmp_path, [message("constant-000001")], "--probe-ms", "0")
        assert of(broker, "channel") == [("channel", 1)] and of(broker, "probe") == []
        assert broker.timers == []
        said = capsys.readouterr().out
        assert " probe_ms=0 probe_channel=None " in said and "probes on channel" not in said


@pytest.fixture
def collector_restored():
    """--gc-off switches this process's collector off and freezes what it holds; it is put back."""
    enabled, callbacks = gc.isenabled(), list(gc.callbacks)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.unfreeze()
        if enabled:
            gc.enable()


def _seek_and_read(fd, size, offset):
    """os.pread where the system has none (Windows): a seek and a read do the same here."""
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


@pytest.mark.usefixtures("collector_restored")
class TestTheCollectorAndTheThreadsCounters:

    def test_the_collector_goes_off_once_connected_and_before_any_message(self, tmp_path):
        gc.enable()
        broker, _ = run(tmp_path, [message("constant-000001")], "--gc-off", "--gc-log",
                        str(tmp_path / "consumer_gc.json"))
        assert of(broker, "consume")[0][3] is False and of(broker, "deliver")[0][2] is False
        logged = json.loads((tmp_path / "consumer_gc.json").read_text(encoding="utf-8"))
        assert logged["gc_off"] is True and logged["collections"] == []

    def test_the_counters_are_sampled_just_before_each_acknowledgment(self, tmp_path,
                                                                       monkeypatch):
        counters = tmp_path / "schedstat"
        counters.write_bytes(b"1000 200 3\n")
        monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(counters))
        order = []
        pread = getattr(os, "pread", _seek_and_read)
        monkeypatch.setattr(os, "pread", lambda *a: order.append("sample") or pread(*a),
                            raising=False)
        broker = Broker([message("constant-000001"), message("constant-000002", run="old")],
                        Clock())
        acked = Channel.basic_ack
        monkeypatch.setattr(Channel, "basic_ack",
                            lambda self, **kw: order.append("ack") or acked(self, **kw))
        run(tmp_path, [], "--schedstat", str(tmp_path / "consumer_schedstat.csv"), broker=broker)
        assert order == ["sample", "ack", "sample", "ack"], "another run's ack is sampled too"
        assert len(rows(tmp_path / "consumer_schedstat.csv")) == 2

    def test_the_thread_that_stamps_is_named_when_asked(self, tmp_path):
        run(tmp_path, [message("constant-000001")], "--thread-record")
        record = json.loads((tmp_path / "consumer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"] == {"stamps_receive": [threading.get_native_id()]}
        os.remove(tmp_path / "consumer_threads.json")
        run(tmp_path, [message("constant-000001")])
        assert not (tmp_path / "consumer_threads.json").exists()


class TestWhatBothClientsShare:

    def test_the_brokers_port_and_address(self):
        assert rc.broker_port("amqp://guest:guest@10.2.1.21") == 5672
        assert rc.broker_port("amqps://guest:guest@10.2.1.21") == 5671
        assert rc.broker_port("amqp://guest:guest@10.2.1.21:5673/%2F") == 5673
        assert rc.broker_address("amqp://guest:secret@10.2.1.21/%2F") == "10.2.1.21:5672"
        assert rc.queue_name("x") == "sb-events-x"

    def test_pika_is_imported_only_when_a_client_runs(self, monkeypatch):
        fake = types.ModuleType("pika")
        monkeypatch.setitem(sys.modules, "pika", fake)
        assert rc.load_pika() is fake

    def test_the_declaration_takes_a_callback_and_hands_out_a_copy(self):
        made = []
        channel = types.SimpleNamespace(queue_declare=lambda **kw: made.append(kw) or "ok")
        assert rc.declare(channel, "q", callback=print) == "ok"
        assert made == [{"queue": "q", "durable": True, "arguments": rc.QUEUE_ARGUMENTS,
                         "callback": print}]
        assert made[0]["arguments"] is not rc.QUEUE_ARGUMENTS

    def test_the_shim_check(self):
        assert rc.check_shim(None, 5672, "x") is None
        seen = types.SimpleNamespace(counts={"connections": 1, "refused": 0})
        assert rc.check_shim(seen, 5672, "x") == 1
        refused = types.SimpleNamespace(counts={"connections": 0, "refused": 1})
        assert rc.check_shim(refused, 5672, "x") == 0, "a kernel that refused is its summary's"
        unseen = types.SimpleNamespace(counts={"connections": 0, "refused": 0})
        with pytest.raises(SystemExit, match="saw no connection to port 5672"):
            rc.check_shim(unseen, 5672, "the RabbitMQ consumer")


# --- a real connection, with pika's socket and the socket timestamps ---------------------------

def method(channel, class_id, method_id, arguments=b""):
    payload = struct.pack(">HH", class_id, method_id) + arguments
    return struct.pack(">BHI", af.METHOD, channel, len(payload)) + payload + b"\xce"


def shortstr(text):
    return struct.pack(">B", len(text)) + text.encode("ascii")


def delivery(tag, queue, message_id, body):
    """basic.deliver, its content header (message-id, transient) and its body, as RabbitMQ sends
    them."""
    deliver = method(1, 60, 60, shortstr("ctag1.a") + struct.pack(">QB", tag, 0) + shortstr("")
                     + shortstr(queue))
    properties = struct.pack(">HHQH", 60, 0, len(body), 0x1080) + b"\x01" + shortstr(message_id)
    head = struct.pack(">BHI", af.HEADER, 1, len(properties)) + properties + b"\xce"
    return deliver + head + struct.pack(">BHI", af.BODY, 1, len(body)) + body + b"\xce"


class PikaShapedSocket(object):
    """A socket made and driven as pika 1.3.2 makes and drives its own: made through socket.socket
    from getaddrinfo's record at connect time, TCP_NODELAY set, non-blocking, connected and its
    completion read from SO_ERROR (adapters/utils/connection_workflow.py, AMQPConnector.start, and
    io_services_utils.py, _AsyncSocketConnector); then written with send() and read with
    recv(4096) (_AsyncTransportBase._produce and _consume), a read that would block being nothing
    read, as pika's _on_socket_readable takes it. On Linux a transmit timestamp waiting on the
    error queue makes the socket readable with no data: the socket timestamps drain the queue, and
    the read would block."""

    def __init__(self, host, port, make=None):
        family, kind, proto, _name, address = socket.getaddrinfo(
            host, port, 0, socket.SOCK_STREAM, socket.IPPROTO_TCP)[0]
        self.sock = (make or socket.socket)(family, kind, proto)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.setblocking(False)
        try:
            self.sock.connect(address)
        except BlockingIOError:
            pass
        select.select([], [self.sock], [], 10)
        assert self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0

    def write(self, data):
        while data:
            select.select([], [self.sock], [], 10)
            data = data[self.sock.send(data):]

    def read(self, seconds):
        if not select.select([self.sock], [], [], seconds)[0]:
            return b""
        try:
            return self.sock.recv(4096)
        except BlockingIOError:
            return b""

    def close(self):
        self.sock.close()


class WireChannel(object):
    """A channel of a WireConnection: the calls the consumer makes on a blocking channel, written
    as frames on its own number, and under it the asynchronous channel the probe goes out on, as
    pika's blocking channel keeps one (BlockingChannel._impl)."""

    def __init__(self, connection, number):
        self.connection, self.channel_number = connection, number
        self._impl = WireAsynchronous(connection, number)

    def queue_declare(self, queue, durable, arguments):
        self.connection.queue = queue

    def basic_qos(self, prefetch_count, global_qos):
        self.connection.wire.write(method(self.channel_number, 60, 10,
                                          struct.pack(">IHB", 0, prefetch_count, global_qos)))

    def basic_consume(self, queue, on_message_callback, auto_ack):
        self.connection.consumer = (self, on_message_callback)
        self.connection.wire.write(method(
            self.channel_number, 60, 20, struct.pack(">H", 0) + shortstr(queue)
            + shortstr("ctag1.a") + struct.pack(">B", 0) + b"\0\0\0\0"))

    def basic_ack(self, delivery_tag, multiple):
        self.connection.wire.write(method(self.channel_number, 60, 80,
                                          struct.pack(">QB", delivery_tag, multiple)))


class WireAsynchronous(object):
    """pika.channel.Channel as the probe uses it: a passive queue.declare written at once, its
    reply handed to the callback in the turn of the loop that reads it."""

    def __init__(self, connection, number):
        self.connection, self.number = connection, number
        self.is_open = True

    def queue_declare(self, queue, passive, callback):
        self.connection.waiting[self.number] = callback
        self.connection.wire.write(method(self.number, 50, 10, struct.pack(">H", 0)
                                          + shortstr(queue) + struct.pack(">B", passive)
                                          + b"\0\0\0\0"))


class WireConnection(object):
    """pika's blocking connection as far as the consumer uses it, speaking AMQP through a
    PikaShapedSocket: the protocol header, then qos, consume and each ack as frames, and the
    broker's deliveries read back into the consumer's callback. Under it, as pika keeps them
    (BlockingConnection._impl.ioloop), the loop's timers, fired in its turns: a second channel is
    opened on the wire as pika opens one, and each reply a request waits for is handed to it once,
    in the turn that reads it."""

    make = None
    greeted = True
    REPLIES = ("channel.open-ok", "queue.declare-ok")

    def __init__(self, parameters):
        address = urlsplit(parameters[1])
        self.wire = PikaShapedSocket(address.hostname, address.port, self.make)
        self.wire.write(af.PROTOCOL_HEADER)
        self.buffer = b""
        while self.greeted and not list(af.read(self.buffer)):
            self.buffer += self.wire.read(10)
        self.buffer = b""
        self.base = self.taken = 0
        self.consumer = None
        self.channels, self.timers, self.waiting = [], [], {}
        self._impl = types.SimpleNamespace(ioloop=self)

    def channel(self):
        """Channel 1 taken as open, as before; another opened with channel.open, and handed out
        once its channel.open-ok has been read."""
        made = WireChannel(self, len(self.channels) + 1)
        self.channels.append(made)
        if made.channel_number > 1:
            opened = []
            self.waiting[made.channel_number] = opened.append
            self.wire.write(method(made.channel_number, 20, 10, shortstr("")))
            deadline = time.monotonic() + 10
            while not opened and time.monotonic() < deadline:
                self.turn(deadline - time.monotonic())
            assert opened, "the broker never opened channel %d" % made.channel_number
        return made

    def call_later(self, delay, callback):
        timer = [time.monotonic() + delay, callback]
        self.timers.append(timer)
        return timer

    def remove_timeout(self, timer):
        timer[1] = None

    def turn(self, seconds):
        """One turn of the loop: what came within `seconds`, or by the next timer, read; each reply
        a request waits for handed to it, once; and the timers that are due fired."""
        due = [t[0] - time.monotonic() for t in self.timers if t[1] is not None]
        self.buffer += self.wire.read(max(0.0, min([seconds] + due)))
        for item in af.read(self.buffer):
            if isinstance(item, af.Method) and item.name in self.REPLIES \
                    and self.base + item.start >= self.taken:
                self.taken = self.base + item.end
                self.waiting.pop(item.channel)(item)
        now = time.monotonic()
        for timer in [t for t in self.timers if t[1] is not None and t[0] <= now]:
            callback, timer[1] = timer[1], None
            callback()
        self.timers = [t for t in self.timers if t[1] is not None]

    def process_data_events(self, time_limit):
        """As pika's: back once a message is in hand or the time limit has passed; the loop turns
        on the way, and neither its timers nor the replies it hands over end the wait."""
        deadline = time.monotonic() + time_limit
        complete = []
        while not complete and time.monotonic() < deadline:
            self.turn(deadline - time.monotonic())
            complete = af.messages(af.read(self.buffer))
        handed = [(m.delivery_tag, m.message_id, m.body(self.buffer)) for m in complete]
        if complete:
            self.base += complete[-1].end
            self.buffer = self.buffer[complete[-1].end:]
        channel, callback = self.consumer
        for tag, message_id, body in handed:
            callback(channel, types.SimpleNamespace(delivery_tag=tag),
                     types.SimpleNamespace(message_id=message_id), body)

    def close(self):
        """As pika closes it: a channel's close waits for the reply to its last request, and then
        the socket goes."""
        deadline = time.monotonic() + 10
        while self.waiting and time.monotonic() < deadline:
            self.turn(deadline - time.monotonic())
        self.wire.close()


class MiniBroker(threading.Thread):
    """A broker with just enough AMQP 0-9-1 for one consumer, holding its deliveries to the
    consumer's prefetch count unacknowledged, as RabbitMQ does, and answering channel.open and
    each queue.declare on the channel it came on, as RabbitMQ answers them."""

    def __init__(self, listener, queue, messages):
        super(MiniBroker, self).__init__(daemon=True)
        self.listener, self.queue, self.pending = listener, queue, list(messages)
        self.error = None
        self.declared = []

    def run(self):
        try:
            self.serve()
        except Exception as exc:  # noqa: BLE001 - reported by the test that started it
            self.error = exc

    def serve(self):
        conn, _ = self.listener.accept()
        with conn:
            conn.settimeout(10)
            data = b""
            while len(data) < len(af.PROTOCOL_HEADER):
                data += conn.recv(64)
            assert data[:len(af.PROTOCOL_HEADER)] == af.PROTOCOL_HEADER
            data = data[len(af.PROTOCOL_HEADER):]
            conn.sendall(method(0, 10, 10, b"\x00\x09"))
            prefetch, subscribed, sent, acked = None, False, 0, set()
            while True:
                while subscribed and self.pending and (not prefetch or sent - len(acked) < prefetch):
                    sent += 1
                    message_id, body = self.pending.pop(0)
                    conn.sendall(delivery(sent, self.queue, message_id, body))
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
                items = list(af.read(data))
                if items:
                    data = data[items[-1].end:]
                for item in items:
                    if item.name == "basic.qos":
                        prefetch = item.fields["prefetch_count"]
                    elif item.name == "basic.consume":
                        subscribed = True
                    elif item.name == "basic.ack":
                        tag = item.fields["delivery_tag"]
                        acked.update(range(1, tag + 1) if item.fields["multiple"] else (tag,))
                    elif item.name == "channel.open":
                        conn.sendall(method(item.channel, 20, 11, struct.pack(">I", 0)))
                    elif item.name == "queue.declare":
                        self.declared.append((item.channel, item.fields["passive"]))
                        conn.sendall(method(item.channel, 50, 11, shortstr(item.fields["queue"])
                                            + struct.pack(">II", len(self.pending), subscribed)))


def stand_in_for_linux(monkeypatch):
    """The three calls Windows cannot make for SO_TIMESTAMPING, answered as Linux answers them on
    this connection: the option taken, no transmit timestamp waiting, and each read stamped."""
    monkeypatch.setattr(so_timestamps, "_setsockopt", lambda sock, flags: None)
    monkeypatch.setattr(so_timestamps, "_queued", lambda sock: False)
    stamp = so_timestamps.TIMESPEC.pack(1791900000, 5) + bytes(2 * so_timestamps.TIMESPEC.size)

    def recvmsg(sock, bufsize, ancbufsize, flags):
        data = so_timestamps._BASE.recv(sock, bufsize, flags)
        return data, [(socket.SOL_SOCKET, so_timestamps.SCM_TIMESTAMPING, stamp)], 0, None
    monkeypatch.setattr(so_timestamps, "_recvmsg", recvmsg)


@pytest.fixture
def listener(monkeypatch):
    """A broker's listening socket, made before the shim replaces socket.socket, and socket.socket
    put back once the test is done."""
    monkeypatch.setattr(socket, "socket", socket.socket)
    stand_in_for_linux(monkeypatch)
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    yield lsock
    lsock.close()


def wire_pika(connection):
    return types.SimpleNamespace(
        adapters=types.SimpleNamespace(select_connection=types.SimpleNamespace(SELECT_TYPE=None)),
        URLParameters=lambda uri: ("parameters", uri), BlockingConnection=connection)


class TestTheSocketTimestampsSeePikasSocket:

    def test_the_shim_takes_the_connection_and_its_journal_pairs_each_delivery(
            self, tmp_path, listener, capsys):
        port = listener.getsockname()[1]
        ids = ["constant-%06d" % i for i in (1, 2, 3)]
        broker = MiniBroker(listener, "sb-events-r47", [message(eid) for eid in ids])
        broker.start()
        stem = tmp_path / "consumer_journal"
        rc.main(["--run-id", RUN, "--out", str(tmp_path / "consumer.csv"), "--uri",
                 "amqp://guest:guest@127.0.0.1:%d" % port, "--prefetch", "1",
                 "--idle-seconds", "1", "--block-ms", "300",
                 "--so-timestamps", str(tmp_path / "consumer_so.csv"), "--so-journal", str(stem)],
                pika=wire_pika(WireConnection))
        broker.join(10)
        assert broker.error is None and not broker.is_alive()
        said = capsys.readouterr().out
        assert "so_connections=1 " in said
        summary = json.loads((tmp_path / "consumer_so_summary.json").read_text(encoding="utf-8"))
        assert (summary["connections"], summary["refused"], summary["ids_read"]) == (1, 0, 3)
        out = (tmp_path / "consumer_journal_conn0_out.bin").read_bytes()
        inb = (tmp_path / "consumer_journal_conn0_in.bin").read_bytes()
        sent, read_ = list(af.read(out)), list(af.read(inb))
        delivered = af.deliveries(read_)
        assert [delivered[k].message_id for k in sorted(delivered)] == ids
        released = af.released(delivered, af.acks(sent), af.prefetch_counts(sent))
        assert [released[k] and released[k].fields["delivery_tag"] for k in sorted(delivered)] \
            == [None, 1, 2], "at prefetch 1 each delivery waited for the ack of the one before"
        assert [r["message_id"] for r in rows(tmp_path / "consumer_events.csv")] == ids

    def test_its_probes_ride_their_own_channel_and_pair_with_their_replies_alone(
            self, tmp_path, listener, capsys):
        """At prefetch 1,000, where no acknowledgment is answered, the probes are the connection's
        round trips: in its journal each pairs with its reply, and no reply is taken for anything
        else."""
        port = listener.getsockname()[1]
        ids = ["constant-%06d" % i for i in (1, 2, 3)]
        broker = MiniBroker(listener, "sb-events-r47", [message(eid) for eid in ids])
        broker.start()
        stem = tmp_path / "consumer_journal"
        rc.main(["--run-id", RUN, "--out", str(tmp_path / "consumer.csv"), "--uri",
                 "amqp://guest:guest@127.0.0.1:%d" % port, "--prefetch", "1000",
                 "--idle-seconds", "1", "--block-ms", "300", "--probe-ms", "50",
                 "--so-timestamps", str(tmp_path / "consumer_so.csv"), "--so-journal", str(stem)],
                pika=wire_pika(WireConnection))
        broker.join(10)
        assert broker.error is None and not broker.is_alive()
        out = (tmp_path / "consumer_journal_conn0_out.bin").read_bytes()
        inb = (tmp_path / "consumer_journal_conn0_in.bin").read_bytes()
        sent, read_ = list(af.read(out)), list(af.read(inb))
        probed = af.probes(sent, read_)
        assert len(probed) >= 5 and broker.declared == [(2, True)] * len(probed)
        assert [(p.channel, p.number) for p in probed] == [(2, n) for n in
                                                           range(1, len(probed) + 1)]
        assert all(p.reply is not None and p.reply.fields["queue"] == "sb-events-r47"
                   for p in probed)
        for p in probed:
            assert out[p.last_out] == af.FRAME_END and inb[p.first_in] == af.METHOD
            assert inb[p.last_in] == af.FRAME_END and p.first_in < p.last_in
        delivered = af.deliveries(read_)
        assert [delivered[k].message_id for k in sorted(delivered)] == ids, "no reply a delivery"
        assert [a.fields["delivery_tag"] for a in af.acks(sent)] == [1, 2, 3], "and no probe an ack"
        said = capsys.readouterr().out
        assert " probe_ms=50 probe_channel=2 " in said
        assert "OK rabbitmq consumer: %d probes on channel 2, %d answered, " % (
            len(probed), len(probed)) in said

    def test_a_socket_made_from_a_class_held_before_the_shim_stops_the_run(
            self, tmp_path, listener):
        port = listener.getsockname()[1]
        held = socket.socket

        class Early(WireConnection):
            make = held
            greeted = False

        with pytest.raises(SystemExit, match="saw no connection to port %d" % port):
            rc.main(["--run-id", RUN, "--out", str(tmp_path / "consumer.csv"), "--uri",
                     "amqp://guest:guest@127.0.0.1:%d" % port,
                     "--so-timestamps", str(tmp_path / "consumer_so.csv")],
                    pika=wire_pika(Early))
