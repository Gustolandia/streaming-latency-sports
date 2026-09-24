"""Our own NATS client: the reference nats-latency's figures are read against.

nats-latency publishes on one connection and receives on another, from one server, and times the
interval between. We had no NATS client of our own, so it had no reference, and T2 -- which takes
its offsets from the reference's median trip and predicts from its trips -- could not be asked of
it. This is that reference, arranged as the tool arranges itself: two connections to the same
server, a subscription on one and a publish on the other, each message timed on the monotonic
clock from being written to being read back, paced at the rate the tool runs at.

NATS speaks a line protocol plain enough to write here: INFO on connect, CONNECT, SUB, PUB, and
MSG back; a server's PING is answered with PONG. No library is needed, which keeps the reference
free of anything a library does between the socket and the clock.
"""
import argparse
import json
import socket
import statistics
import sys
import time

SUBJECT = "sbl.reference"


def _line(sock, held):
    """One protocol line, ending CRLF, from what is held and then from the socket."""
    while b"\r\n" not in held[0]:
        chunk = sock.recv(65536)
        if not chunk:
            raise OSError("the server closed the connection")
        held[0] += chunk
    line, held[0] = held[0].split(b"\r\n", 1)
    return line


def _payload(sock, held, size):
    """A message body of `size` bytes and the CRLF after it."""
    while len(held[0]) < size + 2:
        chunk = sock.recv(65536)
        if not chunk:
            raise OSError("the server closed the connection")
        held[0] += chunk
    body, held[0] = held[0][:size], held[0][size + 2:]
    return body


def _open(connect, host, port):
    """A connection that has read the server's INFO and said CONNECT."""
    sock = connect((host, port), timeout=5)
    held = [b""]
    greeting = _line(sock, held)
    if not greeting.startswith(b"INFO"):
        raise OSError("no NATS greeting: %r" % greeting[:40])
    sock.sendall(b'CONNECT {"verbose":false,"pedantic":false}\r\n')
    return sock, held


def _next_message(sock, held):
    """The next MSG's body, answering any PING on the way."""
    while True:
        line = _line(sock, held)
        if line == b"PING":
            sock.sendall(b"PONG\r\n")
            continue
        if line.startswith(b"MSG "):
            return _payload(sock, held, int(line.split()[-1]))
        if line.startswith(b"-ERR"):
            raise OSError("the server said %r" % line[:80])


def trips(host, port=4222, rate=50.0, seconds=130.0, warmup_s=30.0, size=512,
          clock=time.perf_counter_ns, sleep=time.sleep, connect=socket.create_connection):
    """Paced publishes read back on the second connection, as (trips in ms, sent, lost)."""
    pub, _ = _open(connect, host, port)
    sub, held = _open(connect, host, port)
    sub.sendall(b"SUB %s 1\r\nPING\r\n" % SUBJECT.encode())
    while _line(sub, held) != b"PONG":     # the subscription is in place once the PONG is back
        pass
    start, period_ns, n = clock(), int(1e9 / rate), 0
    found, lost = [], 0
    while True:
        #: The schedule decides when to stop, not the clock after the last answer: a message due
        #: at the end of the run is one past it, and the rate asked for is what is sent.
        due = start + n * period_ns
        if due - start >= seconds * 1e9:
            break
        now = clock()
        if due > now:
            sleep((due - now) / 1e9)
        body = (b"%d " % n).ljust(size, b"x")
        began = clock()
        pub.sendall(b"PUB %s %d\r\n%s\r\n" % (SUBJECT.encode(), size, body))
        #: Read until this message comes back. One that arrives after its own wait gave up would
        #: otherwise be read as the next one's, and every trip after it would be one message out.
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
    ap = argparse.ArgumentParser(description="Our own NATS client, as the reference for T1 and T2")
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=4222)
    ap.add_argument("--rate", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=130.0)
    ap.add_argument("--warmup-s", type=float, default=30.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    found, sent, lost = trips(args.host, args.port, args.rate, args.seconds, args.warmup_s,
                              clock=clock, sleep=sleep, connect=connect)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"client": "nats_reference.py", "trips_ms": found, "sent": sent,
                   "lost": lost, "target": "nats://%s:%d" % (args.host, args.port)}, fh)
    if not found:
        print("no trip was timed: %d sent, %d lost" % (sent, lost), file=out)
        return 1
    print("%d trips timed of %d sent, %d lost; median %.3f ms"
          % (len(found), sent, lost, statistics.median(found)), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
