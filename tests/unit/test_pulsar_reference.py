"""Our own Pulsar client, the reference pulsar-perf is read against (freeze 30, D33-6).

A scripted library stands in for pulsar-client: a producer whose sends reach the consumer after a
trip on the test's clock, and a consumer that can be made to lose, repeat or never see a message.
"""
import io
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import pulsar_reference as pr  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1e9)


class Timeout(Exception):
    """What the library raises when a receive gives up."""


class Message:
    def __init__(self, body):
        self.body = body

    def data(self):
        return self.body


class Library:
    """The library, on a clock. Options name the sends, counted from 0: `drop` never arrives,
    `stale` is preceded by the one before, `broken` raises an OSError on receive."""

    InitialPosition = types.SimpleNamespace(Latest="latest")

    def __init__(self, clock, trip_ms=1.0, drop=(), stale=(), broken=(), timeout=Timeout):
        self.clock, self.trip = clock, trip_ms
        self.drop, self.stale, self.broken = set(drop), set(stale), set(broken)
        self.Timeout = timeout
        self.queue, self.sent, self.last, self.closed, self.acked = [], 0, None, [], 0
        self.opened = {}

    def __call__(self, url):
        self.opened["url"] = url
        return self, self

    # the client
    def subscribe(self, topic, name, initial_position):
        self.opened.update(topic=topic, subscription=name, position=initial_position)
        return self

    def create_producer(self, topic, batching_enabled):
        self.opened["batching"] = batching_enabled
        return self

    def close(self):
        self.closed.append(True)

    # the producer
    def send_async(self, body, callback):
        n = self.sent
        self.sent += 1
        callback("ok", n)
        self.clock.now += int(self.trip * 1e6)
        if n in self.stale and self.last is not None:
            self.queue.append(self.last)
        if n in self.broken:
            self.queue.append(OSError("connection reset"))
        elif n not in self.drop:
            self.queue.append(body)
        self.last = body

    # the consumer
    def receive(self, timeout_millis):
        if not self.queue:
            raise self.Timeout("no message within %d ms" % timeout_millis)
        got = self.queue.pop(0)
        if isinstance(got, Exception):
            raise got
        return Message(got)

    def acknowledge(self, message):
        self.acked += 1


def run(rate=10.0, seconds=1.0, warmup_s=0.0, **options):
    clock = Clock()
    library = Library(clock, **options)
    found = pr.trips("pulsar://broker:6650", rate, seconds, warmup_s, clock=clock,
                     sleep=clock.sleep, library=library, stamp=lambda: 42)
    return found, library


class TestTheTrips:

    def test_each_trip_is_from_the_send_to_the_read_back(self):
        (found, sent, lost), _ = run(trip_ms=1.25)
        assert sent == 10 and lost == 0 and found[0] == pytest.approx(1.25)

    def test_it_reads_from_the_latest_message_on_a_topic_of_its_own_without_batching(self):
        _, library = run()
        assert library.opened == {"url": "pulsar://broker:6650",
                                  "topic": "persistent://public/default/sbl-reference-42",
                                  "subscription": "sbl-reference", "position": "latest",
                                  "batching": False}
        assert library.acked == 10 and len(library.closed) == 3

    def test_the_warm_up_is_timed_and_set_aside(self):
        (found, sent, _), _ = run(warmup_s=0.5)
        assert sent == 10 and len(found) == 5

    def test_a_message_that_never_comes_back_is_lost_not_a_trip(self):
        (found, _, lost), _ = run(drop={3})
        assert lost == 1 and len(found) == 9

    def test_one_that_comes_back_late_is_passed_over_rather_than_read_as_the_next(self):
        (found, _, lost), _ = run(stale={4})
        assert lost == 0 and len(found) == 10

    def test_a_connection_that_fails_under_a_receive_is_a_loss(self):
        (_, _, lost), _ = run(broken={7})
        assert lost == 1

    def test_a_library_without_its_own_timeout_class_still_loses_rather_than_falls_over(self):
        """The class is asked for; where the module has none, a timeout is an OSError."""
        clock = Clock()
        library = Library(clock, drop={2}, timeout=TimeoutError)
        module = types.SimpleNamespace(InitialPosition=Library.InitialPosition)
        found = pr.trips("pulsar://b:6650", 10.0, 1.0, 0.0, clock=clock, sleep=clock.sleep,
                         library=lambda url: (module, library), stamp=lambda: 1)
        assert found[2] == 1, "the one dropped is lost, and the run goes on"


class TestTheLibrary:

    def test_the_library_is_imported_where_it_is_used(self, monkeypatch):
        made = []
        fake = types.ModuleType("pulsar")
        fake.Client = lambda url: made.append(url) or "a client"
        monkeypatch.setitem(sys.modules, "pulsar", fake)
        module, client = pr._library("pulsar://b:6650")
        assert module is fake and client == "a client" and made == ["pulsar://b:6650"]

    def test_the_acknowledgement_is_not_waited_for(self):
        assert pr._ignore("ok", 1) is None


class TestTheCommand:

    def command(self, tmp_path, **options):
        clock = Clock()
        library = Library(clock, **options)
        out, said = tmp_path / "ref.json", io.StringIO()
        code = pr.main(["--url", "pulsar://broker:6650", "--seconds", "1", "--rate", "10",
                        "--warmup-s", "0", "--out", str(out)], said, clock=clock,
                       sleep=clock.sleep, library=library, stamp=lambda: 7)
        return code, said.getvalue(), json.loads(out.read_text(encoding="utf-8"))

    def test_it_writes_the_trips_and_says_how_many(self, tmp_path):
        code, said, written = self.command(tmp_path, trip_ms=2.0)
        assert code == 0 and "median 2.000 ms" in said
        assert written["target"] == "pulsar://broker:6650" and len(written["trips_ms"]) == 10
        assert written["client"] == "pulsar_reference.py"

    def test_a_run_with_no_trip_leaves_with_one(self, tmp_path):
        code, said, written = self.command(tmp_path, drop=set(range(10)))
        assert code == 1 and "no trip was timed" in said and written["lost"] == 10
