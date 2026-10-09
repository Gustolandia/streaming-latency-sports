"""Our own MQTT client, the reference emqtt-bench is read against (freeze 30, D33-6).

A scripted broker stands in for Mosquitto: it speaks MQTT 3.1.1's packets, delivers every publish
to the subscribed connection, and can refuse, drop, delay, interleave or hang up on cue.
"""
import io
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import mqtt_reference as mr  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += int(seconds * 1e9)


def packets(data):
    """The packets in what a client wrote, as (first byte, body)."""
    found = []
    while data:
        first, at, size, shift = data[0], 1, 0, 0
        while True:
            digit = data[at]
            at += 1
            size += (digit & 0x7F) << shift
            shift += 7
            if not digit & 0x80:
                break
        found.append((first, data[at:at + size]))
        data = data[at + size:]
    return found


class Broker:
    """An MQTT broker on a clock. Options name the publishes, counted from 0, it treats oddly:
    `drop` never delivers, `stale` first redelivers the one before, `noise` sends another kind of
    packet first, `hang_up` closes the subscriber. `refuse` answers CONNECT with a non-zero code,
    `suback_late` sends a stray packet before the SUBACK."""

    def __init__(self, clock, trip_ms=1.0, drop=(), stale=(), noise=(), hang_up=(), refuse=False,
                 suback_late=False, chunk=65536):
        self.clock, self.trip = clock, trip_ms
        self.drop, self.stale, self.noise, self.hang_up = set(drop), set(stale), set(noise), \
            set(hang_up)
        self.refuse, self.suback_late, self.chunk = refuse, suback_late, chunk
        self.subscriber, self.published, self.last, self.connects = None, 0, None, []

    def connect(self, address, timeout):
        return Socket(self)


class Socket:
    def __init__(self, broker):
        self.broker, self.inbox, self.gone, self.closed = broker, bytearray(), False, False

    def sendall(self, data):
        broker = self.broker
        for first, body in packets(bytes(data)):
            kind = first & 0xF0
            if kind == 0x10:
                broker.connects.append(body)
                self.inbox += bytes([0x20, 2, 0, 5 if broker.refuse else 0])
            elif kind == 0x80:
                broker.subscriber = self
                if broker.suback_late:
                    self.inbox += bytes([0xD0, 0])
                self.inbox += bytes([0x90, 3]) + body[:2] + bytes([0])
            elif kind == 0x30:
                (name,) = struct.unpack("!H", body[:2])
                self.deliver(body[2 + name:], body[:2 + name])

    def deliver(self, payload, topic):
        broker, n = self.broker, self.broker.published
        broker.published += 1
        sub = broker.subscriber
        broker.clock.now += int(broker.trip * 1e6)
        if n in broker.hang_up:
            sub.gone = True
            return
        if n in broker.noise:
            sub.inbox += bytes([0xD0, 0])
        if n in broker.stale and broker.last is not None:
            sub.inbox += mr._packet(0x30, topic + broker.last)
        if n not in broker.drop:
            sub.inbox += mr._packet(0x30, topic + payload)
        broker.last = payload

    def recv(self, size):
        if self.gone:
            return b""
        if not self.inbox:
            raise socket.timeout("timed out")
        take = min(size, self.broker.chunk)
        chunk = bytes(self.inbox[:take])
        del self.inbox[:take]
        return chunk

    def close(self):
        self.closed = True


def run(rate=10.0, seconds=1.0, warmup_s=0.0, **options):
    clock = Clock()
    broker = Broker(clock, **options)
    found = mr.trips("broker", 1883, rate, seconds, warmup_s, clock=clock, sleep=clock.sleep,
                     connect=broker.connect)
    return found, broker


class TestThePackets:

    @pytest.mark.parametrize("n,encoded", [(0, b"\x00"), (127, b"\x7f"), (128, b"\x80\x01"),
                                           (16383, b"\xff\x7f"), (16384, b"\x80\x80\x01")])
    def test_the_remaining_length_is_seven_bits_a_byte(self, n, encoded):
        assert mr._length(n) == encoded

    def test_it_connects_with_a_clean_session_and_no_keep_alive(self):
        (_, _, _), broker = run()
        name, rest = broker.connects[0][:6], broker.connects[0][6:]
        assert name == b"\x00\x04MQTT" and rest[:4] == b"\x04\x02\x00\x00", \
            "level 4, clean session, keep-alive off so the listening side is never cut off"


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
        (found, _, lost), _ = run(stale={4})
        assert lost == 0 and len(found) == 10

    def test_a_packet_that_is_not_a_publish_is_passed_over(self):
        (found, _, lost), _ = run(noise={6})
        assert lost == 0 and len(found) == 10

    def test_a_broker_that_hangs_up_is_a_loss(self):
        (_, _, lost), _ = run(hang_up={9})
        assert lost == 1

    def test_a_message_read_in_pieces_is_read_whole(self):
        (found, _, lost), _ = run(chunk=100)
        assert lost == 0 and len(found) == 10

    def test_packets_before_the_suback_are_passed_over(self):
        (_, _, lost), _ = run(suback_late=True)
        assert lost == 0

    def test_a_broker_that_will_not_let_the_client_in_is_refused(self):
        with pytest.raises(OSError, match="did not let the client in"):
            run(refuse=True)


class TestTheCommand:

    def command(self, tmp_path, **options):
        clock = Clock()
        broker = Broker(clock, **options)
        out, said = tmp_path / "ref.json", io.StringIO()
        code = mr.main(["--host", "broker", "--seconds", "1", "--rate", "10", "--warmup-s", "0",
                        "--out", str(out)], said, clock=clock, sleep=clock.sleep,
                       connect=broker.connect)
        return code, said.getvalue(), json.loads(out.read_text(encoding="utf-8"))

    def test_it_writes_the_trips_and_says_how_many(self, tmp_path):
        code, said, written = self.command(tmp_path, trip_ms=2.0)
        assert code == 0 and "median 2.000 ms" in said
        assert written["target"] == "mqtt://broker:1883" and len(written["trips_ms"]) == 10

    def test_a_run_with_no_trip_leaves_with_one(self, tmp_path):
        code, said, written = self.command(tmp_path, drop=set(range(10)))
        assert code == 1 and "no trip was timed" in said and written["lost"] == 10
