"""Our own NATS client, the reference nats-latency had never had.

A scripted server stands in for NATS: it speaks the same lines, delivers every publish to the
subscribed connection, and can drop, delay, ping, err or hang up on cue.
"""
import io
import json
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import nats_reference as nr  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1e9)


class Server:
    """A NATS server on a clock. Options name the publishes, counted from 0, it treats oddly:
    `drop` never delivers, `stale` first redelivers the one before, `ping` pings first, `err`
    answers with -ERR, `hang_up` closes the subscriber, `cut` sends the MSG line and closes
    before the body. `closed` hangs up on every connection before its greeting."""

    def __init__(self, clock, trip_ms=1.0, drop=(), stale=(), ping=(), err=(), hang_up=(),
                 cut=(), noise=(), greeting=b"INFO {}\r\n", ok_first=False, chunk=65536,
                 closed=False):
        self.clock, self.trip, self.noise = clock, trip_ms, set(noise)
        self.drop, self.stale, self.ping, self.err = set(drop), set(stale), set(ping), set(err)
        self.hang_up, self.cut = set(hang_up), set(cut)
        self.greeting, self.ok_first, self.chunk, self.closed = greeting, ok_first, chunk, closed
        self.subscriber, self.published, self.pongs, self.last = None, 0, 0, None

    def connect(self, address, timeout):
        sock = Socket(self)
        sock.gone = self.closed
        return sock


class Socket:
    def __init__(self, server):
        self.server, self.inbox = server, bytearray(server.greeting)
        self.closed = self.gone = self.gone_when_empty = False

    def sendall(self, data):
        server = self.server
        while data:
            line, _, data = data.partition(b"\r\n")
            if line.startswith(b"SUB "):
                server.subscriber = self
            elif line == b"PING":
                self.inbox += (b"+OK\r\n" if server.ok_first else b"") + b"PONG\r\n"
            elif line == b"PONG":
                server.pongs += 1
            elif line.startswith(b"PUB "):
                size = int(line.split()[-1])
                body, data = data[:size], data[size + 2:]
                self.deliver(body)

    def deliver(self, body):
        server, n = self.server, self.server.published
        server.published += 1
        sub = server.subscriber
        server.clock.now += int(server.trip * 1e6)
        header = b"MSG sbl.reference 1 %d\r\n" % len(body)
        if n in server.hang_up:
            sub.gone = True
        elif n in server.cut:
            sub.inbox += header
            sub.gone_when_empty = True
        elif n in server.err:
            sub.inbox += b"-ERR 'Authorization Violation'\r\n"
        else:
            if n in server.ping:
                sub.inbox += b"PING\r\n"
            if n in server.noise:
                sub.inbox += b"+OK\r\n"
            if n in server.stale and server.last is not None:
                sub.inbox += b"MSG sbl.reference 1 %d\r\n%s\r\n" % (len(server.last), server.last)
            if n not in server.drop:
                sub.inbox += header + body + b"\r\n"
        server.last = body

    def recv(self, size):
        if self.gone or (self.gone_when_empty and not self.inbox):
            return b""
        if not self.inbox:
            raise socket.timeout("timed out")
        take = min(size, self.server.chunk)
        chunk = bytes(self.inbox[:take])
        del self.inbox[:take]
        return chunk

    def close(self):
        self.closed = True


def run(rate=10.0, seconds=1.0, warmup_s=0.0, **options):
    clock = Clock()
    server = Server(clock, **options)
    found = nr.trips("broker", 4222, rate, seconds, warmup_s, clock=clock, sleep=clock.sleep,
                     connect=server.connect)
    return found, server


class TestTheTrips:

    def test_each_trip_is_from_publish_to_read_back(self):
        (found, sent, lost), _ = run(trip_ms=1.25)
        assert sent == 10 and lost == 0 and found[0] == pytest.approx(1.25)

    def test_the_warm_up_is_timed_and_set_aside(self):
        (found, sent, _), _ = run(warmup_s=0.5)
        assert sent == 10 and len(found) == 5

    def test_a_message_that_never_comes_back_is_lost_not_a_trip(self):
        (found, _, lost), _ = run(drop={3})
        assert lost == 1 and len(found) == 9

    def test_one_that_comes_back_late_is_passed_over_rather_than_read_as_the_next(self):
        """Read as the next message's, every trip after it would be one message out."""
        (found, _, lost), _ = run(stale={4})
        assert lost == 0 and len(found) == 10

    def test_the_servers_ping_is_answered(self):
        (_, _, lost), server = run(ping={2})
        assert server.pongs == 1 and lost == 0

    def test_a_line_that_is_none_of_the_others_is_passed_over(self):
        (found, _, lost), _ = run(noise={6})
        assert lost == 0 and len(found) == 10

    def test_an_error_from_the_server_is_a_loss(self):
        (_, _, lost), _ = run(err={5})
        assert lost == 1

    def test_a_server_that_hangs_up_is_a_loss(self):
        (_, _, lost), _ = run(hang_up={9})
        assert lost == 1

    def test_a_body_cut_short_by_a_hang_up_is_a_loss(self):
        (_, _, lost), _ = run(cut={9})
        assert lost == 1

    def test_a_message_read_in_pieces_is_read_whole(self):
        (found, _, lost), _ = run(chunk=100)
        assert lost == 0 and len(found) == 10

    def test_lines_before_the_subscription_is_confirmed_are_passed_over(self):
        (_, _, lost), _ = run(ok_first=True)
        assert lost == 0

    def test_a_server_that_is_not_nats_is_refused(self):
        with pytest.raises(OSError):
            run(greeting=b"HTTP/1.1 400 Bad Request\r\n")

    def test_a_server_that_hangs_up_before_its_greeting_is_refused(self):
        with pytest.raises(OSError):
            run(closed=True)


class TestTheCommand:

    def command(self, tmp_path, **options):
        clock = Clock()
        server = Server(clock, **options)
        out, said = tmp_path / "ref.json", io.StringIO()
        code = nr.main(["--host", "broker", "--seconds", "1", "--rate", "10", "--warmup-s", "0",
                        "--out", str(out)], said, clock=clock, sleep=clock.sleep,
                       connect=server.connect)
        return code, said.getvalue(), json.loads(out.read_text(encoding="utf-8"))

    def test_it_writes_the_trips_and_says_how_many(self, tmp_path):
        code, said, written = self.command(tmp_path, trip_ms=2.0)
        assert code == 0 and "median 2.000 ms" in said
        assert written["target"] == "nats://broker:4222" and len(written["trips_ms"]) == 10

    def test_a_run_with_no_trip_leaves_with_one(self, tmp_path):
        code, said, written = self.command(tmp_path, drop=set(range(10)))
        assert code == 1 and "no trip was timed" in said and written["lost"] == 10
