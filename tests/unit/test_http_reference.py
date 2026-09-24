"""Our own HTTP client, the reference the four HTTP tools had never had.

The real thing talks to nginx on the broker. Here a scripted connection and a clock that only
moves when told stand in, so every trip is known before it is timed.
"""
import http.client
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import http_reference as hr  # noqa: E402


class Clock:
    """Nanoseconds that move only when a request takes time or the client sleeps."""

    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1e9)


class Answer:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def read(self):
        return self.body


class Server:
    """What each request gets back, in order, and how long each takes on the clock."""

    def __init__(self, clock, script):
        self.clock, self.script, self.opened, self.closed = clock, list(script), 0, 0

    def connect(self, host, port, timeout):
        self.opened += 1
        server = self

        class Connection:
            def request(self, method, path):
                server.method, server.path = method, path

            def getresponse(self):
                kind, ms = server.script.pop(0) if server.script else ("ok", 1.0)
                server.clock.now += int(ms * 1e6)
                if kind == "drop":
                    raise http.client.RemoteDisconnected("gone")
                if kind == "short":
                    return Answer(200, b"x" * 100)
                return Answer(200 if kind == "ok" else 503, b"x" * hr.PAGE_BYTES)

            def close(self):
                server.closed += 1

        return Connection()


def run(script, rate=10.0, seconds=1.0, warmup_s=0.0):
    clock = Clock()
    server = Server(clock, script)
    found = hr.trips("broker", 8080, "/", rate, seconds, warmup_s, clock=clock,
                     sleep=clock.sleep, connect=server.connect)
    return found, server


class TestTheTrips:

    def test_each_trip_is_the_time_from_request_to_whole_page(self):
        (found, sent, failed), server = run([("ok", 1.5)] * 10)
        assert found[0] == pytest.approx(1.5) and failed == 0
        assert server.method == "GET" and server.path == "/"

    def test_it_is_paced_at_the_rate_asked_for_over_the_time_asked_for(self):
        (found, sent, _), _ = run([("ok", 1.0)] * 20, rate=10.0, seconds=1.0)
        assert sent == 10, "ten a second for a second"

    def test_the_warm_up_is_timed_and_set_aside(self):
        (found, sent, _), _ = run([("ok", 1.0)] * 20, rate=10.0, seconds=1.0, warmup_s=0.5)
        assert sent == 10 and len(found) == 5

    def test_a_failed_status_is_counted_and_not_a_trip(self):
        (found, sent, failed), _ = run([("ok", 1.0), ("503", 1.0)] + [("ok", 1.0)] * 8)
        assert failed == 1 and len(found) == sent - 1

    def test_a_page_short_of_the_fixed_size_is_not_a_trip_either(self):
        """The tools are timed against the 512-byte page; a different body is a different trip."""
        (found, _, failed), _ = run([("short", 1.0)] + [("ok", 1.0)] * 9)
        assert failed == 1

    def test_a_dropped_connection_is_counted_and_a_new_one_opened(self):
        (found, _, failed), server = run([("drop", 1.0)] + [("ok", 1.0)] * 9)
        assert failed == 1 and server.opened == 2 and server.closed >= 1

    def test_a_slow_answer_does_not_push_the_next_request_back(self):
        """Open loop: the schedule is kept from the start, not from the last answer."""
        (found, sent, _), _ = run([("ok", 250.0)] + [("ok", 1.0)] * 20, rate=10.0, seconds=1.0)
        assert sent == 10


class TestTheCommand:

    def command(self, tmp_path, script):
        clock = Clock()
        server = Server(clock, script)
        out, said = tmp_path / "ref.json", io.StringIO()
        code = hr.main(["--host", "broker", "--seconds", "1", "--rate", "10", "--warmup-s", "0",
                        "--out", str(out)], said, clock=clock, sleep=clock.sleep,
                       connect=server.connect)
        return code, said.getvalue(), json.loads(out.read_text(encoding="utf-8"))

    def test_it_writes_the_trips_and_says_how_many(self, tmp_path):
        code, said, written = self.command(tmp_path, [("ok", 2.0)] * 10)
        assert code == 0 and "median 2.000 ms" in said
        assert written["trips_ms"] and written["target"] == "http://broker:8080/"

    def test_a_run_with_no_trip_leaves_with_one(self, tmp_path):
        code, said, written = self.command(tmp_path, [("503", 1.0)] * 10)
        assert code == 1 and "no trip was timed" in said and written["failed"] == 10
