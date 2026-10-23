"""Tests for scripts/rabbitmq_producer.py, the plan's messages published to RabbitMQ with publisher
confirms, and for scripts/run_rabbitmq_trial.sh, the trial runner that starts both clients.

pika is not installed here. Its asynchronous adapter is stood in for by a loop in its shape -- timers,
and the broker's answers arriving at their own times -- on a clock of the test's own, so that when
each message left and when each confirm came can be asserted exactly. The trial runner is run in
bash, as the other runners' tests run them (tests/unit/test_azure_kit.py), with each client stood
in for by a stub that writes down how it was called."""
import csv
import gc
import itertools
import json
import os
import subprocess
import sys
import threading
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests"))

import rabbitmq_consumer  # noqa: E402
import rabbitmq_producer as rp  # noqa: E402
from posix_shell import bash  # noqa: E402

RUN = "r47"
#: Binary fractions of a second, so that the test's clock adds them without rounding.
TRIP = 2.0 ** -12
PLAN = [(0, 11, "constant-000001", 0, 0.0), (1, 11, "constant-000002", 0, 0.125),
        (2, 11, "constant-000003", 1, 0.25), (3, 12, "constant-000004", 1, 0.375)]


class Clock(object):
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Loop(object):
    """pika's IOLoop as the producer turns it: poll sends what the channel buffered, waits for the
    earlier of the next timer and the next answer from the broker, and runs the answers that have
    come; process_timeouts fires the timers that are due."""

    def __init__(self, world):
        self.world = world
        self.timers = []
        self.active = False

    def activate_poller(self):
        self.active = True

    def call_later(self, delay, callback):
        assert delay >= 0, "pika refuses a negative delay"
        timer = [self.world.clock.now + delay, callback]
        self.timers.append(timer)
        return timer

    def remove_timeout(self, timer):
        timer[1] = None

    def poll(self):
        w = self.world
        assert self.active, "pika's poller is activated before the loop is turned"
        w.polls += 1
        w.flush()
        due = [t[0] for t in self.timers if t[1] is not None] + [a[0] for a in w.arrivals]
        if due:
            w.clock.now = max(w.clock.now, min(due))
        ready = sorted(a for a in w.arrivals if a[0] <= w.clock.now)
        w.arrivals = [a for a in w.arrivals if a[0] > w.clock.now]
        for _when, _seq, callback in ready:
            callback()

    def process_timeouts(self):
        for timer in list(self.timers):
            if timer[1] is not None and timer[0] <= self.world.clock.now:
                callback, timer[1] = timer[1], None
                callback()
        self.timers = [t for t in self.timers if t[1] is not None]


class World(object):
    """The broker and pika's asynchronous adapter as the producer meets them. Each publish is
    confirmed `trip(n)` after it left, alone or, every `multiple` publishes, all of them at once;
    `nack` are refused, `lose` never confirmed. A world may refuse the connection, close the
    channel at the declaration, never confirm the select, or close the connection after a number
    of publishes."""

    def __init__(self, trip=lambda n: TRIP, multiple=None, nack=(), lose=(), open_error=None,
                 channel_error=None, never_ready=False, close_after=None):
        self.clock = Clock()
        self.trip, self.multiple, self.nack, self.lose = trip, multiple, set(nack), set(lose)
        self.open_error, self.channel_error = open_error, channel_error
        self.never_ready, self.close_after = never_ready, close_after
        self.arrivals, self.buffered, self.published, self.declared = [], [], [], []
        self.seq = itertools.count()
        self.polls = 0
        self.poller_at_loop = self.loop = self.connection = None
        self.pika = types.SimpleNamespace(
            adapters=types.SimpleNamespace(select_connection=types.SimpleNamespace(
                SELECT_TYPE=None, IOLoop=self.make_loop)),
            URLParameters=lambda uri: ("parameters", uri),
            SelectConnection=self.connect,
            BasicProperties=lambda **kw: types.SimpleNamespace(**kw))

    def make_loop(self):
        self.poller_at_loop = self.pika.adapters.select_connection.SELECT_TYPE
        self.loop = Loop(self)
        return self.loop

    def connect(self, parameters, on_open_callback, on_open_error_callback, on_close_callback,
                custom_ioloop):
        assert custom_ioloop is self.loop and self.loop.active
        self.parameters = parameters
        self.connection = Connection(self, on_open_callback, on_open_error_callback,
                                     on_close_callback)
        return self.connection

    def arrive(self, delay, callback):
        self.arrivals.append((self.clock.now + delay, next(self.seq), callback))

    def flush(self):
        for item in self.buffered:
            self.published.append((self.clock.now,) + item)
            n = len(self.published)
            if n == self.close_after:
                self.arrive(TRIP / 2, lambda: self.connection.closed("the broker went away"))
            if n in self.lose:
                continue
            if n in self.nack:
                self.arrive(self.trip(n), self.confirm("Basic.Nack", n, False))
            elif self.multiple is None:
                self.arrive(self.trip(n), self.confirm("Basic.Ack", n, False))
            elif n % self.multiple == 0:
                self.arrive(self.trip(n), self.confirm("Basic.Ack", n, True))
        self.buffered = []

    def confirm(self, name, n, multiple):
        frame = types.SimpleNamespace(method=types.SimpleNamespace(
            NAME=name, delivery_tag=n, multiple=multiple))
        return lambda: self.channel.on_confirm(frame)


class Connection(object):
    def __init__(self, world, on_open, on_open_error, on_close):
        self.world, self.on_close = world, on_close
        if world.open_error:
            world.arrive(0.001, lambda: on_open_error(self, world.open_error))
        else:
            world.arrive(0.001, lambda: on_open(self))

    def channel(self, on_open_callback):
        self.world.channel = Channel(self.world)
        self.world.arrive(0.001, lambda: on_open_callback(self.world.channel))

    def closed(self, reason):
        self.on_close(self, reason)

    def close(self):
        self.world.declared.append("close")
        channel = self.world.channel
        self.world.arrive(0.001, lambda: channel.on_close(channel, "closed with the connection"))
        self.world.arrive(0.002, lambda: self.closed("closed by the client"))


class Channel(object):
    def __init__(self, world):
        self.world = world
        self.on_close = self.on_confirm = None

    def add_on_close_callback(self, callback):
        self.on_close = callback

    def queue_declare(self, queue, durable, arguments, callback):
        self.world.declared.append((queue, durable, arguments))
        if self.world.channel_error:
            self.world.arrive(0.001, lambda: self.on_close(self, self.world.channel_error))
        else:
            self.world.arrive(0.001, lambda: callback("declare-ok"))

    def confirm_delivery(self, ack_nack_callback, callback):
        self.on_confirm = ack_nack_callback
        if not self.world.never_ready:
            self.world.arrive(0.001, lambda: callback("select-ok"))

    def basic_publish(self, exchange, routing_key, body, properties):
        self.world.buffered.append((exchange, routing_key, body, properties))


def write_plan(path, plan=PLAN):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row_idx", "match_id", "event_id", "t_sim_seconds", "t_emit_offset_s"])
        w.writerows(plan)
    return path


def run(tmp_path, monkeypatch, world=None, plan=PLAN, extra=()):
    world = world or World()
    monkeypatch.setattr(rp, "now_ns", lambda: int(round(world.clock.now * 1e9)))
    out = tmp_path / "producer.csv"
    rp.main(["--run-id", RUN, "--plan-csv", str(write_plan(tmp_path / "plan.csv", plan)),
             "--out", str(out), "--speedup", "1"] + list(extra), pika=world.pika,
            clock=world.clock)
    return world, out


def rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestTheFileIsTheRedisProducersWithTheConfirmNumber:

    def test_its_columns_and_rows(self, tmp_path, monkeypatch):
        _, out = run(tmp_path, monkeypatch)
        with open(out, newline="", encoding="utf-8") as fh:
            assert next(csv.reader(fh)) == [
                "run_id", "backend", "stream", "event_id", "match_id", "t_sim_seconds",
                "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns",
                "delivery_tag"]
        found = rows(out)
        assert [(r["event_id"], r["delivery_tag"], r["backend"], r["stream"]) for r in found] == [
            ("constant-00000%d" % n, str(n), "rabbitmq", "sb-events-r47") for n in (1, 2, 3, 4)]
        assert [(r["match_id"], r["t_sim_seconds"], r["t_emit_offset_s"]) for r in found] == [
            ("11", "0", "0.0"), ("11", "0", "0.125"), ("11", "1", "0.25"), ("12", "1", "0.375")]

    def test_each_leaves_at_its_planned_time_and_is_confirmed_a_trip_later(self, tmp_path,
                                                                           monkeypatch):
        world, out = run(tmp_path, monkeypatch)
        found = rows(out)
        start = int(found[0]["t_prod_sched_ns"])
        assert [int(r["t_prod_sched_ns"]) - start for r in found] == [0, 125000000, 250000000,
                                                                      375000000]
        assert all(r["t_prod_send_ns"] == r["t_prod_sched_ns"] for r in found)
        assert [int(r["t_broker_ack_ns"]) - int(r["t_prod_send_ns"]) for r in found] == \
            [int(round(TRIP * 1e9))] * 4, "stamped in the turn that read the confirm"
        assert [round(p[0] * 1e9) for p in world.published] == [int(r["t_prod_send_ns"])
                                                                for r in found]

    def test_a_message_due_in_the_past_leaves_at_once(self, tmp_path, monkeypatch):
        late = [(0, 11, "constant-000001", 0, 0.0), (1, 11, "constant-000002", 0, 0.0)]
        world, out = run(tmp_path, monkeypatch, plan=late)
        assert world.published[0][0] == world.published[1][0]

    def test_the_plan_is_read_as_the_redis_producer_reads_it(self, tmp_path, monkeypatch):
        mixed = [(5, 11, "constant-000005", 2, 0.5), (2, 11, "constant-000002", 1, 0.25),
                 (1, 11, "constant-000001", 1, 0.125), (9, 11, "constant-000009", 900, 9.0)]
        _, out = run(tmp_path, monkeypatch, plan=mixed, extra=["--max-t-sim", "600"])
        assert [r["event_id"] for r in rows(out)] == ["constant-000001", "constant-000002",
                                                      "constant-000005"]


class TestTheMessages:

    def test_each_goes_to_the_queue_transient_with_its_event_id_as_message_id(self, tmp_path,
                                                                             monkeypatch):
        world, _ = run(tmp_path, monkeypatch)
        assert [(p[1], p[2]) for p in world.published] == [("", "sb-events-r47")] * 4
        assert [p[4].message_id for p in world.published] == ["constant-00000%d" % n
                                                              for n in (1, 2, 3, 4)]
        assert {p[4].delivery_mode for p in world.published} == {1}

    def test_the_payload_is_the_redis_producers_field_for_field(self, tmp_path, monkeypatch):
        world, out = run(tmp_path, monkeypatch, extra=["--pad-bytes", "3"])
        sent = []
        mock = MagicMock()
        mock.xadd.side_effect = lambda stream, fields: sent.append(fields["value"]) or "1-0"
        import redis_producer
        argv = ["rp", "--run-id", RUN, "--plan-csv", str(tmp_path / "plan.csv"), "--out",
                str(tmp_path / "redis_producer.csv"), "--speedup", "1000", "--pad-bytes", "3",
                "--send-workers", "1"]
        with patch.object(sys, "argv", argv), patch("redis_producer.redis.Redis",
                                                   return_value=mock):
            redis_producer.main()
        ours = [json.loads(p[3].decode("utf-8")) for p in world.published]
        theirs = [json.loads(value) for value in sent]
        assert [list(m) for m in ours] == [list(m) for m in theirs], "the same fields in order"
        for mine, other, row in zip(ours, theirs, rows(out)):
            assert mine.pop("t_emit_planned_ns") == int(row["t_prod_sched_ns"])
            other.pop("t_emit_planned_ns")
            assert mine == other and mine["pad"] == "xxx"
        assert world.published[0][3].startswith(b'{"run_id":"r47","match_id":11,')

    def test_the_queue_is_declared_as_the_consumer_declares_it(self, tmp_path, monkeypatch):
        world, _ = run(tmp_path, monkeypatch, extra=["--queue", "mine"])
        assert world.declared[0] == ("mine", True, rabbitmq_consumer.QUEUE_ARGUMENTS)
        assert [p[2] for p in world.published] == ["mine"] * 4


class TestTheConfirms:

    def test_one_with_multiple_covers_every_publish_up_to_its_number(self, tmp_path,
                                                                     monkeypatch):
        world, out = run(tmp_path, monkeypatch, world=World(multiple=2))
        acked = [int(r["t_broker_ack_ns"]) for r in rows(out)]
        assert acked[0] == acked[1] < acked[2] == acked[3]
        assert acked[1] == int(round((world.published[1][0] + TRIP) * 1e9))

    def test_confirms_out_of_order_are_each_kept(self, tmp_path, monkeypatch):
        slow_first = World(trip=lambda n: 0.25 if n == 1 else TRIP)
        world, out = run(tmp_path, monkeypatch, world=slow_first)
        found = rows(out)
        assert int(found[0]["t_broker_ack_ns"]) > int(found[1]["t_broker_ack_ns"])
        assert int(found[0]["t_broker_ack_ns"]) == int(round((world.published[0][0] + 0.25)
                                                             * 1e9))

    def test_a_refused_publish_fails_the_run(self, tmp_path, monkeypatch):
        with pytest.raises(RuntimeError, match=r"refused 1 publishes with basic.nack \(first 5 "
                                               r"numbers: \[2\]\)"):
            run(tmp_path, monkeypatch, world=World(nack={2}))
        assert not (tmp_path / "producer.csv").exists()

    def test_a_publish_never_confirmed_fails_the_run(self, tmp_path, monkeypatch):
        world = World(lose={3})
        with pytest.raises(RuntimeError, match=r"1 publishes had no confirm within 30 s "
                                               r"\(first 5 numbers: \[3\]\)"):
            run(tmp_path, monkeypatch, world=world)
        assert "close" in world.declared, "the connection is closed first"

    def test_the_connection_lost_in_the_run_fails_it(self, tmp_path, monkeypatch):
        world = World(close_after=2)
        with pytest.raises(RuntimeError, match="the connection closed: 'the broker went away'"):
            run(tmp_path, monkeypatch, world=world)
        assert "close" not in world.declared, "a closed connection is not closed again"


class TestTheConnection:

    def test_pika_is_given_the_select_poller_and_its_loop_activated_first(self, tmp_path,
                                                                          monkeypatch):
        world, _ = run(tmp_path, monkeypatch, extra=["--uri", "amqp://guest:guest@broker:5673"])
        assert world.poller_at_loop == "select"
        assert world.parameters == ("parameters", "amqp://guest:guest@broker:5673")
        assert world.declared[-1] == "close"

    @pytest.mark.parametrize("world,said", [
        (lambda: World(open_error="refused"), "the connection could not be opened: 'refused'"),
        (lambda: World(channel_error="PRECONDITION_FAILED"),
         "the channel closed: 'PRECONDITION_FAILED'"),
        (lambda: World(never_ready=True), "no channel in confirm mode within 30 s"),
    ])
    def test_a_broker_that_refuses_or_never_answers_stops_it(self, tmp_path, monkeypatch, world,
                                                            said):
        with pytest.raises(SystemExit, match=said):
            run(tmp_path, monkeypatch, world=world())

    def test_it_says_how_it_ran_and_what_it_wrote(self, tmp_path, monkeypatch, capsys):
        run(tmp_path, monkeypatch, extra=["--uri", "amqp://guest:secret@10.2.1.21:5672"])
        said = capsys.readouterr().out
        assert ("CONFIG effective confirms=asynchronous poller=select queue=sb-events-r47 "
                "broker=10.2.1.21:5672 so_connections=None client=python "
                "clock_resolution_ns=") in said
        assert "secret" not in said
        assert "OK rabbitmq producer: wrote 4 rows -> " in said

    def test_the_socket_timestamps_start_before_it_connects_and_must_see_it(self, tmp_path,
                                                                           monkeypatch):
        import so_timestamps
        started = []

        class Ledger(object):
            counts = {"connections": 0, "refused": 0}

        def start(args, port):
            started.append((port, world.connection))
            return Ledger()

        world = World()
        monkeypatch.setattr(so_timestamps, "start", start)
        with pytest.raises(SystemExit, match="the RabbitMQ producer: the socket timestamps saw no "
                                             "connection to port 5673"):
            run(tmp_path, monkeypatch, world=world,
                extra=["--uri", "amqp://guest:guest@broker:5673", "--so-timestamps",
                       str(tmp_path / "producer_so.csv")])
        assert started == [(5673, None)], "before any connection was made"


@pytest.fixture
def collector_restored():
    enabled, callbacks = gc.isenabled(), list(gc.callbacks)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.unfreeze()
        if enabled:
            gc.enable()


@pytest.mark.usefixtures("collector_restored")
class TestTheCollectorAndTheThreads:

    def test_the_collector_goes_off_once_connected_and_before_the_first_publish(
            self, tmp_path, monkeypatch):
        gc.enable()
        seen = []
        world = World()
        real = Channel.basic_publish
        monkeypatch.setattr(Channel, "basic_publish",
                            lambda self, **kw: seen.append(gc.isenabled()) or real(self, **kw))
        run(tmp_path, monkeypatch, world=world,
            extra=["--gc-off", "--gc-log", str(tmp_path / "producer_gc.json")])
        assert seen == [False] * 4
        logged = json.loads((tmp_path / "producer_gc.json").read_text(encoding="utf-8"))
        assert logged["gc_off"] is True

    def test_this_thread_stamps_both_send_and_confirm(self, tmp_path, monkeypatch):
        run(tmp_path, monkeypatch, extra=["--thread-record"])
        record = json.loads((tmp_path / "producer_threads.json").read_text(encoding="utf-8"))
        me = [threading.get_native_id()]
        assert record["roles"] == {"stamps_ack": me, "stamps_send": me}


class TestTheLoopIsTurnedSparingly:

    def test_a_turn_waits_no_longer_than_asked_and_never_less_than_nothing(self):
        world = World()
        publisher = rp.Publisher(world.pika, "amqp://guest:guest@b", "q", world.clock)
        publisher.turn(-1.0)
        assert world.loop.timers == [] and world.clock.now == 100.0
        assert publisher.serve(world.clock.now + 1.0) is False
        assert world.clock.now == pytest.approx(101.0, abs=1e-9) and publisher.ready
        assert publisher.serve(world.clock.now + 1.0, lambda: True) is True


class TestTheConfirmBookkeeping:

    @staticmethod
    def confirm(tag, multiple):
        return types.SimpleNamespace(method=types.SimpleNamespace(
            NAME="Basic.Ack", delivery_tag=tag, multiple=multiple))

    def test_a_confirm_covering_numbers_already_confirmed_passes_them_by(self):
        world = World()
        publisher = rp.Publisher(world.pika, "amqp://guest:guest@b", "q", world.clock)
        publisher.number, publisher.waiting = 3, {1: 0, 2: 1, 3: 2}
        publisher._confirmed(self.confirm(2, False))
        assert publisher.lowest == 1 and sorted(publisher.waiting) == [1, 3]
        publisher._confirmed(self.confirm(3, True))
        assert publisher.waiting == {} and sorted(publisher.acked) == [0, 1, 2]
        assert publisher.lowest == 4
        stamps = dict(publisher.acked)
        publisher._confirmed(self.confirm(3, False))
        assert publisher.acked == stamps, "a confirm repeated changes nothing"
        assert all(isinstance(ns, int) for ns in stamps.values()), "the wall clock, in ns"


# --- the trial runner -------------------------------------------------------------------------

RUNNER = REPO / "scripts" / "run_rabbitmq_trial.sh"


def _write(path, text):
    """A file as Linux writes one, with no carriage return on any platform; returns its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def trial(tmp_path, *arguments, **env):
    """The runner in a scratch folder: its Python stands in for each client by writing down how it
    was called, except where it runs the runner's record of the run from stdin, and each wrap
    writes down how it was called and then runs what it wraps. The consumer runs in the background,
    so the calls are read by what they start, not by their order. (The calls, meta.json, and the
    record's text.)"""
    work = tmp_path / "work"
    stubs, calls = work / "bin", work / "calls.txt"
    python = Path(sys.executable).as_posix()
    for name, body in (
            ("py", 'if [ "$1" = - ]; then exec "%s" "$@"; fi\necho "python $*" >> "$CALLS"\n'
             % python),
            ("schedwrap", 'echo "schedwrap $*" >> "$CALLS"\nexec "$@"\n'),
            ("conswrap", 'echo "conswrap $*" >> "$CALLS"\nexec "$@"\n'),
            ("prodwrap", 'echo "prodwrap $*" >> "$CALLS"\nexec "$@"\n'),
            ("sleep", 'echo "sleep $*" >> "$CALLS"\n')):
        os.chmod(_write(stubs / name, "#!/bin/sh\n" + body), 0o755)
    given = {"PYTHON": (stubs / "py").as_posix(), "CALLS": calls.as_posix(),
             "SBL_SCHED_WRAP": "", "SBL_CONSUMER_WRAP": "", "SBL_PRODUCER_WRAP": ""}
    given.update(env)
    done = bash([RUNNER.as_posix(), "r001", "plan.csv"] + list(arguments), cwd=work,
                path_first=[stubs], extra_env=given, capture_output=True, text=True,
                stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    meta_text = (work / "runs" / "r001" / "meta.json").read_text(encoding="utf-8")
    return calls.read_text(encoding="utf-8").splitlines(), json.loads(meta_text), meta_text


needs_bash = pytest.mark.shell


@needs_bash
class TestTheTrialRunner:

    def test_the_flags_reach_each_client_and_the_record_holds_no_password(self, tmp_path):
        calls, meta, text = trial(
            tmp_path, "2", "70", "-URI", "amqp://guest:secret@10.2.1.21:5672", "-QUEUE", "q1",
            "-PREFETCH", "1000", "-PRODUCER_EXTRA", "--gc-off --pad-bytes 3",
            "-CONSUMER_EXTRA", "--ack-batch 10 --prefetch 5", "-IDLE_SECONDS", "15",
            "-UNKNOWN", "ignored")
        assert sorted(calls) == sorted([
            "python scripts/rabbitmq_consumer.py --run-id r001 --out runs/r001/consumer.csv "
            "--uri amqp://guest:secret@10.2.1.21:5672 --queue q1 --idle-seconds 15 "
            "--ack-batch 10 --prefetch 5 --prefetch 1000",
            "sleep 2",
            "python scripts/rabbitmq_producer.py --run-id r001 --plan-csv plan.csv "
            "--out runs/r001/producer.csv --uri amqp://guest:secret@10.2.1.21:5672 --queue q1 "
            "--speedup 2 --max-t-sim 70 --gc-off --pad-bytes 3",
            "python scripts/compute_tti.py --producer runs/r001/producer.csv --consumer "
            "runs/r001/consumer.csv --out runs/r001/tti_summary.json"]), \
            "the runner's own -PREFETCH last, so that it wins"
        assert calls[-1].startswith("python scripts/compute_tti.py"), "once the consumer is done"
        assert meta["backend"] == "rabbitmq" and (meta["speedup"], meta["max_t_sim"]) == (2.0, 70)
        assert meta["rabbitmq"] == {"broker": "10.2.1.21:5672", "vhost": "/", "queue": "q1",
                                    "prefetch": 1000}
        assert "secret" not in text
        assert set(meta["code_sha256"]) == {
            "scripts/run_rabbitmq_trial.sh", "scripts/rabbitmq_producer.py",
            "scripts/rabbitmq_consumer.py", "scripts/amqp_frames.py", "scripts/compute_tti.py"}

    def test_with_no_flags_the_run_has_its_own_queue_and_the_consumers_prefetch(self, tmp_path):
        calls, meta, _ = trial(tmp_path)
        assert ("python scripts/rabbitmq_consumer.py --run-id r001 --out runs/r001/consumer.csv "
                "--uri amqp://guest:guest@localhost:5672 --queue sb-events-r001 "
                "--idle-seconds 30") in calls
        producer = [c for c in calls if "rabbitmq_producer.py" in c]
        assert len(producer) == 1
        assert producer[0].endswith("--queue sb-events-r001 --speedup 120 --max-t-sim 600")
        assert meta["rabbitmq"] == {"broker": "localhost:5672", "vhost": "/",
                                    "queue": "sb-events-r001", "prefetch": None}

    def test_the_three_wraps_and_the_options_and_where_each_lands(self, tmp_path):
        calls, meta, _ = trial(
            tmp_path, "-URI", "amqps://u:p@broker/%2Fsbl", SBL_SCHED_WRAP="schedwrap",
            SBL_CONSUMER_WRAP="conswrap", SBL_PRODUCER_WRAP="prodwrap",
            RABBITMQ_CONSUMER_OPTS="--block-ms 50", RABBITMQ_PRODUCER_OPTS="--thread-record")
        py = (tmp_path / "work" / "bin" / "py").as_posix()
        consumer = [c for c in calls if "rabbitmq_consumer.py" in c]
        producer = [c for c in calls if "rabbitmq_producer.py" in c]
        assert consumer[0].startswith("schedwrap conswrap %s scripts/rabbitmq_consumer.py "
                                      "--block-ms 50 --run-id r001" % py)
        assert consumer[1].startswith("conswrap %s scripts/rabbitmq_consumer.py" % py)
        assert producer[0].startswith("schedwrap prodwrap %s scripts/rabbitmq_producer.py "
                                      "--thread-record --run-id r001" % py)
        assert not [c for c in consumer if "prodwrap" in c]
        assert not [c for c in producer if "conswrap" in c]
        assert meta["env"] == {"RABBITMQ_PRODUCER_OPTS": "--thread-record",
                               "RABBITMQ_CONSUMER_OPTS": "--block-ms 50",
                               "SBL_SCHED_WRAP": "schedwrap", "SBL_CONSUMER_WRAP": "conswrap",
                               "SBL_PRODUCER_WRAP": "prodwrap"}
        assert meta["rabbitmq"]["broker"] == "broker:5671" and meta["rabbitmq"]["vhost"] == "/sbl"

    def test_it_is_written_as_the_other_runners_are(self):
        text = RUNNER.read_bytes().decode("utf-8")
        assert "\r" not in text and text.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        assert 'PRODUCER_WRAP="${SBL_PRODUCER_WRAP:-}"' in text
        assert '"SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")' in text
        wrapped = [line.strip() for line in text.splitlines()
                   if "$PRODUCER_WRAP" in line and not line.lstrip().startswith("#")]
        assert wrapped and all(line.startswith("$SCHED_WRAP $PRODUCER_WRAP ") for line in wrapped)
        assert bash(["-n", RUNNER.as_posix()]).returncode == 0
