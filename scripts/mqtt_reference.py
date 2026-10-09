"""Our own MQTT client: the reference emqtt-bench's figures are read against (freeze 30, D33-6).

emqtt-bench publishes from one process and subscribes from another, through one broker, and times
the interval between. T2 takes its offsets from a reference's median trip and predicts from its
trips, so emqtt-bench needs one, and the study's own program speaks Kafka and Redis only. This is
that reference, arranged as the tool arranges itself: two connections to the same broker, a
subscription on one and a publish on the other, each message timed on the monotonic clock from
being written to being read back, paced at the rate the tool runs at.

MQTT 3.1.1 is plain enough to write here, as NATS was: CONNECT and its CONNACK, SUBSCRIBE and its
SUBACK, and PUBLISH at QoS 0, which is what the tool is run at. Keep-alive is off, so the broker
never closes the listening connection for its silence. No library is needed, which keeps the
reference free of anything a library does between the socket and the clock.
"""
import argparse
import json
import socket
import statistics
import struct
import sys
import time

TOPIC = "sbl/reference"


def _length(n):
    """MQTT's remaining length: seven bits a byte, the high bit saying another follows."""
    out = bytearray()
    while True:
        n, digit = divmod(n, 128)
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _string(text):
    raw = text.encode()
    return struct.pack("!H", len(raw)) + raw


def _packet(kind, body):
    return bytes([kind]) + _length(len(body)) + body


def _read(sock, held, size):
    """Exactly `size` bytes, from what is held and then from the socket."""
    while len(held[0]) < size:
        chunk = sock.recv(65536)
        if not chunk:
            raise OSError("the broker closed the connection")
        held[0] += chunk
    out, held[0] = held[0][:size], held[0][size:]
    return out


def _next_packet(sock, held):
    """One packet, as (its type, its body)."""
    kind = _read(sock, held, 1)[0]
    size, shift = 0, 0
    while True:
        digit = _read(sock, held, 1)[0]
        size += (digit & 0x7F) << shift
        shift += 7
        if not digit & 0x80:
            break
    return kind & 0xF0, _read(sock, held, size)


def _open(connect, host, port, client_id):
    """A connection the broker has let in: CONNECT with a clean session and no keep-alive."""
    sock = connect((host, port), timeout=5)
    held = [b""]
    sock.sendall(_packet(0x10, _string("MQTT") + bytes([4, 0x02]) + struct.pack("!H", 0)
                         + _string(client_id)))
    kind, body = _next_packet(sock, held)
    if kind != 0x20 or len(body) != 2 or body[1] != 0:
        raise OSError("the broker did not let the client in: %r" % (bytes([kind]) + body,))
    return sock, held


def _next_message(sock, held):
    """The next PUBLISH's payload, passing over anything else the broker sends."""
    while True:
        kind, body = _next_packet(sock, held)
        if kind == 0x30:
            (name,) = struct.unpack("!H", body[:2])
            return body[2 + name:]


def trips(host, port=1883, rate=50.0, seconds=130.0, warmup_s=30.0, size=512,
          clock=time.perf_counter_ns, sleep=time.sleep, connect=socket.create_connection):
    """Paced publishes read back on the second connection, as (trips in ms, sent, lost)."""
    pub, _ = _open(connect, host, port, "sbl-reference-pub")
    sub, held = _open(connect, host, port, "sbl-reference-sub")
    sub.sendall(_packet(0x82, struct.pack("!H", 1) + _string(TOPIC) + bytes([0])))
    while _next_packet(sub, held)[0] != 0x90:   # the subscription is in place once SUBACK is back
        pass
    start, period_ns, n = clock(), int(1e9 / rate), 0
    found, lost = [], 0
    while True:
        #: The schedule decides when to stop, as in the NATS reference: a message due at the end
        #: of the run is one past it, and the rate asked for is what is sent.
        due = start + n * period_ns
        if due - start >= seconds * 1e9:
            break
        now = clock()
        if due > now:
            sleep((due - now) / 1e9)
        body = (b"%d " % n).ljust(size, b"x")
        began = clock()
        pub.sendall(_packet(0x30, _string(TOPIC) + body))
        #: Read until this message comes back, so one that arrives late is passed over rather
        #: than read as the next one's.
        back = b""
        try:
            while back.split(b" ", 1)[0] != b"%d" % n:
                back = _next_message(sub, held)
        except (OSError, ValueError):
            back = b""
        ended = clock()
        if not back:
            lost += 1
        elif began - start >= warmup_s * 1e9:
            found.append((ended - began) / 1e6)
        n += 1
    pub.close()
    sub.close()
    return found, n, lost


def main(argv=None, out=None, clock=time.perf_counter_ns, sleep=time.sleep,
         connect=socket.create_connection):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Our own MQTT client, as the reference for T1 and T2")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=130.0)
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    found, sent, lost = trips(args.host, args.port, args.rate, args.seconds, args.warmup_s,
                              clock=clock, sleep=sleep, connect=connect)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"client": "mqtt_reference.py", "trips_ms": found, "sent": sent,
                   "lost": lost, "target": "mqtt://%s:%d" % (args.host, args.port)}, fh)
    if not found:
        print("no trip was timed: %d sent, %d lost" % (sent, lost), file=out)
        return 1
    print("%d trips timed of %d sent, %d lost; median %.3f ms"
          % (len(found), sent, lost, statistics.median(found)), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
