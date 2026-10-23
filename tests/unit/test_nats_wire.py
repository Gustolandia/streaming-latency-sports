"""Tests for scripts/nats_wire.py: the NATS protocol's frames, byte for byte as nats-server writes
them; the splitter; the JetStream requests and answers; the acknowledgment subject in both its
forms; and Link, over a socket that stands in for the kernel, in both of its ways of reading.

FakeServer, below the tests' constants, is a NATS server with JetStream for the clients' tests too
(test_nats_producer.py and test_nats_consumer.py import it). It reads what a client writes as a
server reads it, with a parser of this file's own rather than nats_wire's, and answers with frames
shaped as nats-server writes them: INFO with its JSON; publish acknowledgments; messages delivered
to the oldest request waiting, on the subscription that takes the request's reply subject but under
the subject the message was published to, with their $JS.ACK reply subjects; status messages under
the reply subject of the request they answer; and a PONG for each PING, behind whatever the
connection has already been sent. Time passes for a client only while its reads wait. No network is
used."""
import json
import os
import socket
import struct
import sys
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import nats_wire as nw  # noqa: E402
import so_timestamps as so  # noqa: E402

T0 = 1792710000 * 10**9
INBOX = "_INBOX.4f1c2b7a9e3d5c8b1a0f6e"

#: A greeting as nats-server 2.15 writes one.
INFO = (b'INFO {"server_id":"NCTVHFB5RXTDZQKQCLO7Q2JZ5VEPUXDOAAQYQBSXW5EQ2QSEZ5RK7MAI",'
        b'"server_name":"sbl-broker","version":"2.15.1","proto":1,"git_commit":"5b2c1ee",'
        b'"go":"go1.25.3","host":"0.0.0.0","port":4222,"headers":true,"max_payload":1048576,'
        b'"jetstream":true,"client_id":12,"client_ip":"10.1.1.10"}\r\n')
#: The producer's message, as nats_producer.py writes it: 214 bytes.
PAYLOAD = (b'{"run_id":"r1","match_id":3795506,"event_id":"constant-000001","t_sim_seconds":0,'
           b'"t_emit_offset_s":0.0,"t_emit_planned_ns":1792710000000000000,'
           b'"s3_uid":"3795506:constant-000001","s3_rev":1,"s3_is_correction":false}')
#: That message delivered for a pull request, as nats-server writes it: on subscription 2, the one
#: that takes the requests' reply subjects (INBOX.*), but under the subject the message was
#: published to, so that it names no request. Its acknowledgment subject is in the older,
#: nine-token form: delivered once, stream sequence 42, consumer sequence 40, 3 left after it.
SUBJECT = "sbl.SBL_r1"
ACK_V1 = "$JS.ACK.SBL_r1.sbl-r1.1.42.40.1792710000123456789.3"
DELIVERED = (b"MSG sbl.SBL_r1 2 "
             b"$JS.ACK.SBL_r1.sbl-r1.1.42.40.1792710000123456789.3 214\r\n" + PAYLOAD + b"\r\n")
#: Pull request 18 expired: the status comes under its reply subject, and has none of its own.
TIMEOUT_408 = (b"HMSG _INBOX.4f1c2b7a9e3d5c8b1a0f6e.18 2 81 81\r\n"
               b"NATS/1.0 408 Request Timeout\r\nNats-Pending-Messages: 1\r\n"
               b"Nats-Pending-Bytes: 0\r\n\r\n\r\n")
#: A publish's acknowledgment: the stream took it as its 42nd message.
PUB_ACK = b'MSG _INBOX.0c9d8e7f6a5b4c3d2e1f00.5 2 28\r\n{"stream":"SBL_r1","seq":42}\r\n'
#: No one listens on the subject a request was published to.
NO_RESPONDERS = b"HMSG _INBOX.0c9d8e7f6a5b4c3d2e1f00.6 2 16 16\r\nNATS/1.0 503\r\n\r\n\r\n"
#: An idle heartbeat under pull request 19's reply subject: it ends nothing.
HEARTBEAT_100 = (b"HMSG _INBOX.4f1c2b7a9e3d5c8b1a0f6e.19 2 31 31\r\n"
                 b"NATS/1.0 100 Idle Heartbeat\r\n\r\n\r\n")
#: A message that was published with a header of its own, delivered: no status.
WITH_HEADERS = (b"HMSG sbl.SBL_r1 2 "
                b"$JS.ACK.SBL_r1.sbl-r1.1.43.41.1792710000223456789.2 42 256\r\n"
                b"NATS/1.0\r\nNats-Msg-Id: constant-000001\r\n\r\n" + PAYLOAD + b"\r\n")


# --- a NATS server with JetStream, for these tests and the clients' ----------------------------

def client_frames(buf):
    """What a client wrote, cut into whole frames the way a server reads them: ([(raw, op, words,
    payload)], the bytes left over)."""
    frames = []
    while True:
        end = buf.find(b"\r\n")
        if end < 0:
            return frames, buf
        words = buf[:end].split()
        op = words[0].upper() if words else b""
        total, payload = end + 2, b""
        if op in (b"PUB", b"HPUB"):
            size = int(words[-1])
            total = end + 2 + size + 2
            if len(buf) < total:
                return frames, buf
            assert buf[total - 2:total] == b"\r\n", "a publish whose size is wrong"
            payload = buf[end + 2:end + 2 + size]
        frames.append((buf[:total], op, words, payload))
        buf = buf[total:]


def matches(pattern, subject):
    """Whether a subscription's subject takes `subject`: '*' takes one token, '>' the rest."""
    want, got = pattern.split("."), subject.split(".")
    for i, token in enumerate(want):
        if token == ">":
            return len(got) > i
        if i >= len(got) or token not in ("*", got[i]):
            return False
    return len(got) == len(want)


def stamp(ns):
    """struct scm_timestamping: the software time first, then two empty ones."""
    return so.TIMESPEC.pack(ns // 10**9, ns % 10**9) + bytes(2 * so.TIMESPEC.size)


class FakeSocket(object):
    """A client's end of one connection, and the kernel behind it: the bytes from the server wait in
    segments, each a packet with its receive time. A read takes what is there as TCP does, or with
    MSG_PEEK looks without taking, with MSG_WAITALL waits for all it asked for, with MSG_DONTWAIT
    does not wait at all; one that would wait gives the server a turn (FakeServer.waited), and then
    passes as SO_RCVTIMEO lets it."""

    def __init__(self, server, address, wait=0.002):
        self.server = server
        self.address = address
        self.wait = wait
        self.cv = threading.Condition()
        self.segments = []
        self.written = b""
        self.frames = []
        self.reads = []
        self.attempts = []
        self.options = []
        self.timeout = "unset"
        self.subs = {}
        self.connect_options = None
        self.pongs = 0
        self.cap = None
        self.fail_send = None
        self.gone = False
        self.closed = False
        #: Every packet fed, as (first byte's offset, offset past its last byte, receive time),
        #: and every byte.
        self.packets = []
        self.fed = 0
        self.history = b""

    def feed(self, data, split=()):
        """Bytes from the server, in one packet or cut into several at `split`."""
        with self.cv:
            cuts = [0] + [c for c in split if 0 < c < len(data)] + [len(data)]
            for a, b in zip(cuts, cuts[1:]):
                if b > a:
                    self.server.ns += 1000
                    self.segments.append([data[a:b], self.server.ns])
                    self.packets.append((self.fed, self.fed + b - a, self.server.ns))
                    self.fed += b - a
                    self.history += data[a:b]
            self.cv.notify_all()

    def queued(self):
        with self.cv:
            return sum(len(segment[0]) for segment in self.segments)

    def settimeout(self, value):
        self.timeout = value

    def setsockopt(self, level, option, value):
        self.options.append((level, option, value))

    def read_wait_ns(self):
        """How long a read waits in the kernel when nothing comes: the socket's SO_RCVTIMEO, and a
        moment more, as a read that times out returns just after its timeout; Link's own wait
        where none was set."""
        waits = [value for level, option, value in self.options
                 if (level, option) == (socket.SOL_SOCKET, socket.SO_RCVTIMEO)]
        seconds, micros = struct.unpack("ll", waits[-1]) if waits else (0, int(nw.WAIT_S * 1e6))
        return seconds * 10**9 + micros * 1000 + 1000

    def close(self):
        self.closed = True

    def sendall(self, data, flags=0):
        if self.fail_send is not None and self.fail_send(bytes(data)):
            raise BrokenPipeError(32, "Broken pipe")
        with self.server.lock:
            frames, self.written = client_frames(self.written + bytes(data))
            for raw, op, words, payload in frames:
                self.frames.append(raw)
                self.server.handle(self, raw, op, words, payload)

    def recv(self, bufsize, flags=0):
        return self._take(bufsize, flags)[0]

    def recvmsg(self, bufsize, ancbufsize=0, flags=0):
        data, ns = self._take(bufsize, flags)
        return (data, [] if ns is None else [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, stamp(ns))],
                0, None)

    def _take(self, bufsize, flags):
        self.attempts.append((bufsize, flags))
        peek = bool(flags & socket.MSG_PEEK)
        want = bufsize if peek and flags & socket.MSG_WAITALL else 1
        if not flags & nw.MSG_DONTWAIT and self.queued() < want and not self.gone:
            with self.cv:
                self.cv.wait_for(lambda: self.queued() >= want or self.gone, self.wait)
            if self.queued() < want and not self.gone:
                self.server.waited(self)
        with self.cv:
            limit = bufsize if peek or self.cap is None else min(bufsize, self.cap)
            data, ns = b"", None
            for segment in self.segments:
                if len(data) >= limit:
                    break
                data, ns = data + segment[0][:limit - len(data)], segment[1]
            if not data and not self.gone:
                raise BlockingIOError(11, "Resource temporarily unavailable")
            if not peek:
                self.cap = None
                left = len(data)
                while left:
                    head = self.segments[0]
                    if len(head[0]) <= left:
                        left -= len(head[0])
                        self.segments.pop(0)
                    else:
                        head[0] = head[0][left:]
                        left = 0
            self.reads.append((bufsize, flags, len(data)))
            return data, ns

    def taken(self):
        """The sizes of the reads that took bytes, in order."""
        return [n for _, flags, n in self.reads if not flags & socket.MSG_PEEK]


class FakeServer(object):
    """nats-server with JetStream, as far as block N's clients use it. Each connection is a
    FakeSocket; streams keep their messages and durable consumers their waiting pull requests.
    A message is delivered to the oldest request waiting for it (with `newest_first`, to the
    newest: a server that is not nats-server, for a test), routed by the request's reply subject
    to the subscription that takes it, whose sid it carries, but written under the stream's
    subject, as nats-server writes a delivery under the subject the message was published to (each
    stream here takes one subject). A status comes under the reply subject of the request it
    answers. A request beyond the consumer's max_waiting is refused with 409 Exceeded MaxWaiting,
    and a PING is answered with a PONG behind whatever the connection has already been sent.
    `events` are run one at a time whenever a client's read finds nothing, as if time had passed:
    a test scripts with them what happens while a client waits. Time passes only then: clock(), a
    client's monotonic clock, moves on by each such wait."""

    def __init__(self, version="2.15.1", headers=True, ack_tokens=9, greeting=None, hold_acks=0,
                 strict_create=False, coalesce=False, newest_first=False):
        self.lock = threading.RLock()
        self.version = version
        self.headers = headers
        self.ack_tokens = ack_tokens
        self.greeting = greeting
        self.hold_acks = hold_acks
        self.strict_create = strict_create
        self.coalesce = coalesce
        self.newest_first = newest_first
        self.held = []
        self.sockets = []
        self.streams = {}
        self.events = []
        self.acks = []
        self.requests = []
        self.seen = []
        self.on_request = None
        #: For a test: the next delivered frame cut into two packets at this byte; a verdict on
        #: each publish to a stream ("error" answers it with an error, "drop" with nothing); and
        #: what happens just after each.
        self.split_next = None
        self.verdict = None
        self.after_publish = None
        self.ns = T0
        #: The time the clients' reads have waited, in ns.
        self.elapsed_ns = 0

    def info(self, client_id):
        info = {"server_id": "NCTVHFB5RXTDZQKQCLO7Q2JZ5VEPUXDOAAQYQBSXW5EQ2QSEZ5RK7MAI",
                "server_name": "sbl-broker", "version": self.version, "proto": 1,
                "git_commit": "5b2c1ee", "go": "go1.25.3", "host": "0.0.0.0", "port": 4222,
                "headers": self.headers, "max_payload": 1048576, "jetstream": True,
                "client_id": client_id, "client_ip": "10.1.1.10"}
        return b"INFO " + json.dumps(info, separators=(",", ":")).encode() + b"\r\n"

    def connect(self, address, timeout=None):
        sock = FakeSocket(self, address)
        with self.lock:
            self.sockets.append(sock)
            sock.feed(self.greeting if self.greeting is not None
                      else self.info(len(self.sockets)))
        return sock

    def waited(self, sock):
        """A client found nothing to read and waited its read's timeout: the time passes, and the
        next event runs."""
        with self.lock:
            self.elapsed_ns += sock.read_wait_ns()
            if self.events:
                self.events.pop(0)(self)

    def clock(self):
        """A client's monotonic clock, in seconds: the time its reads have waited."""
        return self.elapsed_ns / 1e9

    # -- what a client said
    def handle(self, sock, raw, op, words, payload):
        if op == b"CONNECT":
            sock.connect_options = json.loads(raw[len(b"CONNECT "):-2])
        elif op == b"PING":
            sock.feed(b"PONG\r\n")
        elif op == b"PONG":
            sock.pongs += 1
        elif op == b"SUB":
            sock.subs[words[-1].decode()] = words[1].decode()
        elif op == b"PUB":
            reply = words[2].decode() if len(words) == 4 else None
            self.publish(sock, words[1].decode(), reply, payload)

    def publish(self, sock, subject, reply, payload):
        if subject.startswith("$JS.API."):
            self.api(subject[len("$JS.API."):].split("."), reply, payload)
        elif subject.startswith("$JS.ACK."):
            self.acks.append((sock, subject, payload))
            self.seen.append(("ack", subject))
        else:
            name = self.stream_on(subject)
            if name is None:
                if reply:
                    self.status(reply, 503, "")
                return
            verdict = self.verdict(payload) if self.verdict is not None else None
            if verdict == "error":
                self.pub_ack(reply, b'{"error":{"code":503,"err_code":10077,"description":'
                             b'"maximum messages exceeded"},"stream":"%s","seq":0}' % name.encode())
            else:
                stream = self.streams[name]
                stream["messages"].append(payload)
                self.seen.append(("stored", len(stream["messages"])))
                if reply and verdict != "drop":
                    self.pub_ack(reply, b'{"stream":"%s","seq":%d}'
                                 % (name.encode(), len(stream["messages"])))
                self.deliver(name)
            if self.after_publish is not None:
                self.after_publish(self, sock)

    def stream_on(self, subject):
        for name, stream in self.streams.items():
            if subject in stream["config"]["subjects"]:
                return name
        return None

    def api(self, path, reply, payload):
        kind = "%s.%s" % tuple(path[:2])
        if kind == "CONSUMER.MSG":
            self.requests.append(reply)
            self.seen.append(("request", reply))
            if self.on_request is not None:
                self.on_request(reply)
            consumer = self.streams[path[3]]["consumers"][path[4]]
            if len(consumer["waiting"]) >= consumer["config"]["max_waiting"]:
                # As nats-server: a request the wait queue has no room for is refused at once.
                self.status(reply, 409, "Exceeded MaxWaiting")
                return
            consumer["waiting"].append(reply)
            self.deliver(path[3])
            return
        if kind == "STREAM.CREATE":
            answer = self.create_stream(path[2], json.loads(payload))
        elif kind == "STREAM.INFO":
            answer = (self.stream_answer(path[2], "info", False) if path[2] in self.streams
                      else self.error("info", 404, 10059, "stream not found"))
        elif kind == "STREAM.DELETE":
            self.streams.pop(path[2], None)
            answer = {"type": "io.nats.jetstream.api.v1.stream_delete_response", "success": True}
        else:
            answer = self.create_consumer(path[2], path[3], json.loads(payload))
        self.answer(reply, json.dumps(answer, separators=(",", ":")).encode())

    def create_stream(self, name, config):
        for other, stream in self.streams.items():
            if other != name and set(stream["config"]["subjects"]) & set(config["subjects"]):
                return self.error("create", 400, 10065, "subjects overlap with an existing stream")
        existing = self.streams.get(name)
        if existing is not None:
            same = (existing["config"]["subjects"] == config["subjects"]
                    and existing["config"]["storage"] == config["storage"])
            if self.strict_create or not same:
                return self.error("create", 400, 10058,
                                  "stream name already in use with a different configuration")
            return self.stream_answer(name, "create", False)
        full = {"name": name, "subjects": config["subjects"], "retention": "limits",
                "max_consumers": -1, "max_msgs": -1, "max_bytes": -1, "max_age": 0,
                "max_msgs_per_subject": -1, "max_msg_size": -1, "discard": "old",
                "storage": config["storage"], "num_replicas": config["num_replicas"],
                "duplicate_window": 120000000000, "compression": "none", "sealed": False,
                "deny_delete": False, "deny_purge": False, "allow_rollup_hdrs": False,
                "allow_direct": False, "mirror_direct": False, "consumer_limits": {}}
        self.streams[name] = {"config": full, "messages": [], "consumers": {}}
        return self.stream_answer(name, "create", True)

    def stream_answer(self, name, kind, created):
        stream = self.streams[name]
        return {"type": "io.nats.jetstream.api.v1.stream_%s_response" % kind,
                "config": stream["config"], "created": "2026-10-23T00:00:00.000000000Z",
                "state": {"messages": len(stream["messages"]), "bytes": 0,
                          "first_seq": 1, "last_seq": len(stream["messages"]),
                          "consumer_count": len(stream["consumers"])},
                "did_create": created, "ts": "2026-10-23T00:00:00.000000000Z"}

    def error(self, kind, code, err_code, description):
        return {"type": "io.nats.jetstream.api.v1.stream_%s_response" % kind,
                "error": {"code": code, "err_code": err_code, "description": description}}

    def create_consumer(self, stream, name, request):
        consumers = self.streams[stream]["consumers"]
        if name not in consumers:
            consumers[name] = {"config": request["config"], "waiting": [], "next": 0, "cseq": 0}
        return {"type": "io.nats.jetstream.api.v1.consumer_create_response",
                "stream_name": stream, "name": name, "created": "2026-10-23T00:00:00.000000000Z",
                "config": dict(request["config"], name=name, ack_wait=30000000000,
                               max_deliver=-1, num_replicas=0),
                "delivered": {"consumer_seq": 0, "stream_seq": 0},
                "ack_floor": {"consumer_seq": 0, "stream_seq": 0},
                "num_ack_pending": 0, "num_redelivered": 0, "num_waiting": 0,
                "num_pending": len(self.streams[stream]["messages"]),
                "ts": "2026-10-23T00:00:00.000000000Z"}

    # -- what the server sends
    def route(self, subject):
        for sock in self.sockets:
            for sid, pattern in sock.subs.items():
                if matches(pattern, subject):
                    return sock, sid
        raise AssertionError("no one subscribes to %s" % subject)

    def answer(self, reply, payload):
        sock, sid = self.route(reply)
        sock.feed(b"MSG %s %s %d\r\n%s\r\n" % (reply.encode(), sid.encode(), len(payload), payload))

    def pub_ack(self, reply, payload):
        self.held.append((reply, payload))
        if len(self.held) >= self.hold_acks:
            self.release()

    def release(self):
        """The acknowledgments held back, sent last first: a client must match them by their reply
        subjects, not by their order."""
        held, self.held = self.held, []
        for reply, payload in reversed(held):
            self.answer(reply, payload)

    def status(self, reply, code, description, fields=()):
        block = (b"NATS/1.0 %d%s\r\n" % (code, (" " + description).encode() if description else b"")
                 + b"".join(b"%s: %s\r\n" % (k.encode(), v.encode()) for k, v in fields) + b"\r\n")
        sock, sid = self.route(reply)
        sock.feed(b"HMSG %s %s %d %d\r\n%s\r\n" % (reply.encode(), sid.encode(), len(block),
                                                     len(block), block))

    def ack_subject(self, stream, consumer, delivered, seq, cseq, pending):
        tail = "%s.%s.%d.%d.%d.%d.%d" % (stream, consumer, delivered, seq, cseq,
                                          T0 + seq * 1000, pending)
        if self.ack_tokens == 9:
            return "$JS.ACK." + tail
        if self.ack_tokens == 11:
            return "$JS.ACK._.ShJBUMLJFlgLb7Z8f7bAwh." + tail
        return "$JS.ACK.hub.ShJBUMLJFlgLb7Z8f7bAwh.%s.Ab3dE5" % tail

    def deliver(self, name):
        """Each waiting request, oldest first, given the next message it has not had."""
        stream = self.streams[name]
        for consumer_name, consumer in stream["consumers"].items():
            out = {}
            while consumer["waiting"] and consumer["next"] < len(stream["messages"]):
                reply = consumer["waiting"].pop(-1 if self.newest_first else 0)
                consumer["next"] += 1
                consumer["cseq"] += 1
                frame = self.message(name, consumer_name, reply, consumer["next"],
                                     consumer["cseq"], 1,
                                     len(stream["messages"]) - consumer["next"])
                out.setdefault(frame[0], []).append(frame[1])
            for sock, frames in out.items():
                if self.coalesce:
                    frames = [b"".join(frames)]
                for frame in frames:
                    split, self.split_next = self.split_next, None
                    sock.feed(frame, () if split is None else (split,))

    def message(self, stream, consumer, reply, seq, cseq, delivered, pending):
        """Message `seq` delivered for the request whose reply subject is `reply`, as nats-server
        writes it: on the subscription that takes the reply subject, but under the subject the
        message was published to, the stream's, and so naming no request."""
        payload = self.streams[stream]["messages"][seq - 1]
        sock, sid = self.route(reply)
        subject = self.streams[stream]["config"]["subjects"][0]
        ack = self.ack_subject(stream, consumer, delivered, seq, cseq, pending)
        return sock, b"MSG %s %s %s %d\r\n%s\r\n" % (subject.encode(), sid.encode(), ack.encode(),
                                                     len(payload), payload)

    # -- what a test makes happen
    def store(self, stream, *payloads):
        """Messages published to the stream by someone else, and then delivered together: with
        `coalesce`, those for one connection in one packet."""
        messages = self.streams[stream]["messages"]
        for payload in payloads:
            messages.append(payload)
            self.seen.append(("stored", len(messages)))
        self.deliver(stream)

    def waiting(self, stream):
        return [r for c in self.streams[stream]["consumers"].values() for r in c["waiting"]]

    def end_requests(self, stream, count, code=408, description="Request Timeout", ends=True,
                     at=0):
        """`count` requests waiting, from the `at`-th oldest on, each answered by a status under
        its reply subject, and ended by it if `ends`."""
        consumer = list(self.streams[stream]["consumers"].values())[0]
        for _ in range(count):
            reply = consumer["waiting"][at]
            if ends:
                consumer["waiting"].pop(at)
            fields = ((("Nats-Pending-Messages", "1"), ("Nats-Pending-Bytes", "0"))
                      if code == 408 else ())
            self.status(reply, code, description, fields)

    def redeliver(self, stream, seq):
        """Message `seq` delivered again, to the first request waiting."""
        name, consumer = list(self.streams[stream]["consumers"].items())[0]
        reply = consumer["waiting"].pop(0)
        sock, frame = self.message(stream, name, reply, seq, consumer["cseq"] + 1, 2, 0)
        consumer["cseq"] += 1
        sock.feed(frame)


# --- the frames a client writes ---------------------------------------------------------------

class TestTheFramesAClientWrites:

    def test_connect_asks_for_headers_and_no_responders(self):
        frame = nw.connect("sbl-nats-consumer")
        assert frame.startswith(b"CONNECT {") and frame.endswith(b"}\r\n")
        options = json.loads(frame[len(b"CONNECT "):-2])
        assert options["headers"] is True and options["no_responders"] is True
        assert options["verbose"] is False and options["name"] == "sbl-nats-consumer"
        assert options["lang"] == "python" and options["protocol"] == 1

    def test_a_publish_with_a_reply_subject_and_without(self):
        assert nw.pub("sbl.r1", b"hello", INBOX + ".5") == (
            b"PUB sbl.r1 _INBOX.4f1c2b7a9e3d5c8b1a0f6e.5 5\r\nhello\r\n")
        assert nw.pub("sbl.r1", b"") == b"PUB sbl.r1 0\r\n\r\n"

    def test_a_publish_with_headers_counts_them_in_both_sizes(self):
        headers = b"NATS/1.0\r\nNats-Msg-Id: 7\r\n\r\n"
        assert nw.hpub("sbl.r1", headers, b"hi", "r.1") == (
            b"HPUB sbl.r1 r.1 28 30\r\n" + headers + b"hi\r\n")
        assert nw.hpub("sbl.r1", headers, b"") == b"HPUB sbl.r1 28 28\r\n" + headers + b"\r\n"

    def test_a_header_block_with_a_status_and_fields_and_without_either(self):
        assert nw.header_block([("Nats-Pending-Messages", "1"), ("Nats-Pending-Bytes", "0")],
                               (408, "Request Timeout")) == TIMEOUT_408.split(b"\r\n", 1)[1][:81]
        assert nw.header_block(status=(503, "")) == b"NATS/1.0 503\r\n\r\n"
        assert nw.header_block() == b"NATS/1.0\r\n\r\n"

    def test_a_subscription_and_its_end_with_and_without_their_optional_words(self):
        assert nw.sub(INBOX + ".*", 2) == b"SUB _INBOX.4f1c2b7a9e3d5c8b1a0f6e.* 2\r\n"
        assert nw.sub("sbl.r1", 3, "workers") == b"SUB sbl.r1 workers 3\r\n"
        assert nw.unsub(2) == b"UNSUB 2\r\n" and nw.unsub(2, 10) == b"UNSUB 2 10\r\n"


# --- where a frame ends ------------------------------------------------------------------------

SERVER_FRAMES = [INFO, b"PING\r\n", b"PONG\r\n", b"+OK\r\n",
                 b"-ERR 'Unknown Protocol Operation'\r\n", DELIVERED, TIMEOUT_408, PUB_ACK,
                 NO_RESPONDERS, HEARTBEAT_100, WITH_HEADERS]


class TestWhereAFrameEnds:

    @pytest.mark.parametrize("frame", SERVER_FRAMES, ids=lambda f: f[:12].decode())
    def test_every_server_frame_is_measured_to_its_last_byte(self, frame):
        assert nw.frame_length(frame) == len(frame)
        assert nw.frame_length(frame + b"PING\r\n") == len(frame), "and no further"

    def test_the_sizes_on_the_lines_are_the_payloads(self):
        assert len(PAYLOAD) == 214 and len(DELIVERED) == DELIVERED.index(b"\r\n") + 2 + 214 + 2
        assert TIMEOUT_408.count(b"\r\n") == 6 and len(TIMEOUT_408.split(b"\r\n", 1)[1]) == 83

    def test_a_frame_not_all_here_is_none_whether_its_line_or_its_payload_is_short(self):
        line = DELIVERED.index(b"\r\n") + 2
        for cut in range(len(DELIVERED)):
            assert nw.frame_length(DELIVERED[:cut]) is None
            assert nw.frame_size(DELIVERED[:cut]) == (len(DELIVERED) if cut >= line else None)

    def test_frames_are_walked_from_an_offset(self):
        joined = b"".join(SERVER_FRAMES)
        at, found = 0, []
        while at < len(joined):
            n = nw.frame_length(joined, at)
            found.append(joined[at:at + n])
            at += n
        assert found == SERVER_FRAMES
        assert nw.frame_size(joined, len(INFO)) == 6

    def test_the_clients_own_frames_are_measured_too(self):
        for frame in (nw.connect("c"), nw.pub("s", b"abc", "r"),
                      nw.hpub("s", nw.header_block(), b"x"), nw.sub("s", 1), nw.unsub(1),
                      nw.PING, nw.PONG):
            assert nw.frame_length(frame) == len(frame)

    def test_lower_case_operations_and_an_empty_line_are_read(self):
        assert nw.frame_length(b"msg a 1 2\r\nhi\r\n") == 15
        assert nw.frame_length(b"\r\nPING\r\n") == 2

    @pytest.mark.parametrize("frame", [b"MSG a 1 x\r\n", b"MSG a 1 -5\r\n", b"MSG\r\n",
                                       b"HMSG a 1 2 two\r\n"])
    def test_a_size_that_is_not_a_number_is_refused(self, frame):
        with pytest.raises(nw.ProtocolError):
            nw.frame_length(frame)

    def test_a_payload_not_ended_where_its_size_says_is_refused(self):
        with pytest.raises(nw.ProtocolError):
            nw.frame_length(b"MSG a 1 2\r\nhiX\r\n")

    def test_a_line_with_no_end_is_refused_once_it_is_longer_than_any_line(self):
        assert nw.frame_length(b"x" * nw.MAX_CONTROL_LINE) is None
        with pytest.raises(nw.ProtocolError):
            nw.frame_length(b"x" * (nw.MAX_CONTROL_LINE + 1))


# --- what a frame says -------------------------------------------------------------------------

class TestWhatAFrameSays:

    def test_a_delivered_message(self):
        frame = nw.parse_frame(DELIVERED)
        assert frame == nw.Frame("MSG", SUBJECT, "2", ACK_V1, b"", PAYLOAD)
        assert nw.status(frame) is None

    def test_a_publish_acknowledgment_has_no_reply_subject(self):
        frame = nw.parse_frame(PUB_ACK)
        assert (frame.subject, frame.sid, frame.reply) == ("_INBOX.0c9d8e7f6a5b4c3d2e1f00.5", "2",
                                                          None)
        assert nw.pub_ack(frame.payload) == ("SBL_r1", 42, False)

    def test_a_status_message_is_headers_alone(self):
        frame = nw.parse_frame(TIMEOUT_408)
        assert frame.op == "HMSG" and frame.reply is None and frame.payload == b""
        assert nw.status(frame) == (408, "Request Timeout")
        assert nw.parse_headers(frame.headers) == (408, "Request Timeout", {
            "Nats-Pending-Messages": "1", "Nats-Pending-Bytes": "0"})
        assert nw.status(nw.parse_frame(NO_RESPONDERS)) == (503, "")
        assert nw.status(nw.parse_frame(HEARTBEAT_100)) == (100, "Idle Heartbeat")

    def test_a_message_with_headers_of_its_own_is_no_status(self):
        frame = nw.parse_frame(WITH_HEADERS)
        assert nw.status(frame) is None and frame.payload == PAYLOAD
        assert nw.parse_headers(frame.headers)[2] == {"Nats-Msg-Id": "constant-000001"}
        assert frame.reply.startswith("$JS.ACK.")

    def test_publishes_as_a_capture_reader_sees_them(self):
        assert nw.parse_frame(nw.pub("sbl.r1", b"abc", "_INBOX.x.3")) == nw.Frame(
            "PUB", "sbl.r1", None, "_INBOX.x.3", b"", b"abc")
        assert nw.parse_frame(nw.pub("sbl.r1", b"abc")).reply is None
        headers = nw.header_block([("K", "v")])
        assert nw.parse_frame(nw.hpub("s", headers, b"p", "r")) == nw.Frame(
            "HPUB", "s", None, "r", headers, b"p")
        assert nw.parse_frame(nw.hpub("s", headers, b"p")).reply is None

    def test_frames_without_a_payload_keep_what_follows_their_operation(self):
        info = nw.parse_frame(INFO)
        assert info.op == "INFO" and json.loads(info.payload)["version"] == "2.15.1"
        assert nw.parse_frame(b"-ERR 'Stale Connection'\r\n").payload == b"'Stale Connection'"
        assert nw.parse_frame(b"PING\r\n") == nw.Frame("PING", None, None, None, b"", b"")
        assert nw.parse_frame(b"\r\n").op == ""

    @pytest.mark.parametrize("frame", [b"MSG a 3\r\nabc\r\n", b"MSG a 1 r x 3\r\nabc\r\n",
                                       b"PUB 3\r\nabc\r\n", b"HPUB a b c 2 3\r\nabc\r\n"])
    def test_a_frame_with_the_wrong_number_of_arguments_is_refused(self, frame):
        with pytest.raises(nw.ProtocolError):
            nw.parse_frame(frame)

    def test_headers_longer_than_the_frame_are_refused(self):
        with pytest.raises(nw.ProtocolError):
            nw.parse_frame(b"HMSG a 1 50 10\r\n0123456789\r\n")

    def test_a_header_block_that_is_not_one_is_refused(self):
        with pytest.raises(nw.ProtocolError):
            nw.parse_headers(b"HTTP/1.1 200 OK\r\n\r\n")

    def test_a_header_line_without_a_colon_is_passed_over(self):
        assert nw.parse_headers(b"NATS/1.0\r\nnot a field\r\nK: v\r\n\r\n") == (None, "",
                                                                               {"K": "v"})


class TestWhichFramesAnswerPullRequests:
    """A delivery is known by the subscription it comes on and its reply subject under $JS.ACK,
    whatever its subject, for nats-server writes it under the subject the message was published
    to; a status by the request's reply subject it comes under; and a PONG is neither."""

    def test_a_delivery_is_known_by_its_subscription_and_its_reply_subject(self):
        for raw in (DELIVERED, WITH_HEADERS):
            frame = nw.parse_frame(raw)
            assert nw.is_delivery(frame, 2) and nw.is_delivery(frame, "2")
            assert frame.subject == SUBJECT, "it names no request"
            assert nw.request_status(frame, INBOX + ".") is None
        assert not nw.is_delivery(nw.parse_frame(DELIVERED), 3), "another subscription's"

    def test_its_subject_plays_no_part_and_its_reply_subject_does(self):
        under_an_inbox = DELIVERED.replace(SUBJECT.encode(), INBOX.encode() + b".9", 1)
        assert nw.is_delivery(nw.parse_frame(under_an_inbox), 2)
        # A publish's acknowledgment comes on such a subscription too, with no reply subject.
        assert not nw.is_delivery(nw.parse_frame(PUB_ACK), 2)
        assert not nw.is_delivery(nw.parse_frame(b"MSG sbl.SBL_r1 2 _INBOX.x.1 2\r\nhi\r\n"), 2)

    def test_a_status_is_known_by_the_reply_subject_it_comes_under(self):
        prefix, other = INBOX + ".", "_INBOX.0c9d8e7f6a5b4c3d2e1f00."
        assert nw.request_status(nw.parse_frame(TIMEOUT_408), prefix) == (408, "Request Timeout")
        assert nw.request_status(nw.parse_frame(HEARTBEAT_100), prefix) == (100, "Idle Heartbeat")
        assert nw.request_status(nw.parse_frame(TIMEOUT_408), other) is None, "another's requests"
        assert not nw.is_delivery(nw.parse_frame(TIMEOUT_408), 2), "a status has no reply subject"
        assert nw.request_status(nw.parse_frame(PUB_ACK), other) is None, "an answer, no status"

    def test_a_pong_is_neither(self):
        pong = nw.parse_frame(nw.PONG)
        assert pong == nw.Frame("PONG", None, None, None, b"", b"")
        assert not nw.is_delivery(pong, 2) and nw.request_status(pong, INBOX + ".") is None
        assert nw.request_status(nw.parse_frame(INFO), INBOX + ".") is None


# --- JetStream ---------------------------------------------------------------------------------

class TestJetStreamsRequests:

    def test_the_stream_is_created_on_its_subject_with_one_replica(self):
        subject, payload = nw.stream_create("SBL_r1", ["sbl.r1"], "memory")
        assert subject == "$JS.API.STREAM.CREATE.SBL_r1"
        assert json.loads(payload) == {"name": "SBL_r1", "subjects": ["sbl.r1"],
                                       "retention": "limits", "storage": "memory",
                                       "num_replicas": 1, "discard": "old"}
        assert json.loads(nw.stream_create("S", ["s"])[1])["storage"] == "file"

    def test_a_stream_is_kept_on_file_or_in_memory_and_nowhere_else(self):
        with pytest.raises(ValueError):
            nw.stream_create("S", ["s"], "disk")

    def test_the_streams_info_and_its_deletion(self):
        assert nw.stream_info("S") == ("$JS.API.STREAM.INFO.S", b"")
        assert nw.stream_delete("S") == ("$JS.API.STREAM.DELETE.S", b"")

    def test_the_durable_pull_consumer(self):
        subject, payload = nw.consumer_create("SBL_r1", "sbl-r1")
        assert subject == "$JS.API.CONSUMER.CREATE.SBL_r1.sbl-r1"
        request = json.loads(payload)
        assert request["stream_name"] == "SBL_r1"
        assert request["config"] == {"durable_name": "sbl-r1", "deliver_policy": "all",
                                     "ack_policy": "explicit", "replay_policy": "instant",
                                     "max_ack_pending": 1000000, "max_waiting": 512}
        assert nw.MAX_WAITING >= 128

    def test_max_waiting_is_four_times_the_depth_and_never_below_the_servers_default(self):
        assert [nw.max_waiting_for(d) for d in (1, 64, 128, 129, 256)] == [512, 512, 512, 516, 1024]
        assert all(nw.max_waiting_for(d) >= 2 * d for d in range(1, 4097)), "twice the depth"
        request = json.loads(nw.consumer_create("S", "d", max_waiting=nw.max_waiting_for(256))[1])
        assert request["config"]["max_waiting"] == 1024

    def test_a_pull_request_is_for_one_message_and_expires_in_nanoseconds(self):
        assert nw.pull_request("SBL_r1", "sbl-r1", 30e9) == (
            "$JS.API.CONSUMER.MSG.NEXT.SBL_r1.sbl-r1", b'{"batch":1,"expires":30000000000}')

    def test_an_acknowledgment_is_plus_ack_published_to_the_reply_subject(self):
        assert nw.ack(ACK_V1) == b"PUB " + ACK_V1.encode() + b" 4\r\n+ACK\r\n"


class TestJetStreamsAnswers:

    def test_an_answer_is_its_json(self):
        assert nw.api_reply(b'{"type":"x","did_create":true}') == {"type": "x",
                                                                    "did_create": True}

    def test_an_error_is_raised_with_its_codes(self):
        with pytest.raises(nw.JetStreamError) as caught:
            nw.api_reply(b'{"error":{"code":400,"err_code":10058,"description":"stream name '
                         b'already in use with a different configuration"}}')
        assert (caught.value.code, caught.value.err_code) == (400, 10058)
        assert "already in use" in caught.value.description and "10058" in str(caught.value)

    @pytest.mark.parametrize("payload", [b"not json", b"[1, 2]", b"\xff\xfe"])
    def test_an_answer_that_is_not_a_json_object_is_refused(self, payload):
        with pytest.raises(nw.ProtocolError):
            nw.api_reply(payload)

    def test_publish_acknowledgments(self):
        assert nw.pub_ack(b'{"stream":"S","seq":7,"duplicate":true}') == ("S", 7, True)
        assert nw.pub_ack(b'{"stream":"S","domain":"hub","seq":8}') == ("S", 8, False)
        with pytest.raises(nw.JetStreamError):
            nw.pub_ack(b'{"error":{"code":503,"err_code":10077,"description":"maximum messages '
                       b'exceeded"},"stream":"S","seq":0}')
        for payload in (b'{"stream":"S"}', b'{"stream":"S","seq":"x"}', b'{"seq":1}'):
            with pytest.raises(nw.ProtocolError):
                nw.pub_ack(payload)


class TestTheAcknowledgmentSubject:
    """Checked against the official clients' own readers: nats.go's internal/parser (the token
    positions from 2, nine tokens or at least eleven) and nats.py's Msg.Metadata."""

    def test_the_older_nine_token_form(self):
        assert nw.ack_metadata(ACK_V1) == nw.AckMeta("", "", "SBL_r1", "sbl-r1", 1, 42, 40,
                                                     1792710000123456789, 3)

    def test_the_newer_form_with_no_domain_and_the_accounts_hash(self):
        meta = nw.ack_metadata("$JS.ACK._.ShJBUMLJFlgLb7Z8f7bAwh.SBL_r1.sbl-r1.2.42.41.17.0")
        assert (meta.domain, meta.account_hash, meta.stream, meta.consumer) == (
            "", "ShJBUMLJFlgLb7Z8f7bAwh", "SBL_r1", "sbl-r1")
        assert (meta.delivered, meta.stream_seq, meta.consumer_seq, meta.timestamp_ns,
                meta.pending) == (2, 42, 41, 17, 0)

    def test_the_newer_form_with_a_domain_and_a_token_after_it(self):
        meta = nw.ack_metadata("$JS.ACK.hub.AcCt.S.C.1.5.4.99.6.Ab3dE5")
        assert meta == nw.AckMeta("hub", "AcCt", "S", "C", 1, 5, 4, 99, 6)

    @pytest.mark.parametrize("subject", [
        None, "", "$JS.ACK.S.C.1.2.3.4", "$JS.ACK._.h.S.C.1.2.3.4",
        "$JS.NAK.S.C.1.2.3.4.5", "JS.ACK.S.C.1.2.3.4.5", "$JS.ACK.S.C.1.x.3.4.5",
        "$JS.ACK.S.C.1.-2.3.4.5", "$JS.ACK.S.C.1.%s.3.4.5" % chr(0x663)])
    def test_what_is_not_an_acknowledgment_subject_is_refused(self, subject):
        with pytest.raises(nw.ProtocolError):
            nw.ack_metadata(subject)


class TestNames:

    def test_a_name_made_from_a_run_id_is_one_jetstream_takes(self):
        assert nw.safe_name("law_q1.7 a/b*c>d") == "law_q1_7_a_b_c_d"
        assert nw.checked_name(nw.safe_name("x.y z")) == "x_y_z"

    @pytest.mark.parametrize("name", ["", "a.b", "a b", "a*", "a>", "a/b", "a\\b", "a\x01b",
                                      "a\tb"])
    def test_a_name_jetstream_refuses_is_refused_here(self, name):
        with pytest.raises(ValueError):
            nw.checked_name(name)

    def test_subjects(self):
        assert nw.checked_subject("sbl.law_q1.20261023") == "sbl.law_q1.20261023"
        for bad in ("", "a..b", ".a", "a.", "a.*", "a.>", "a b", "a*b"):
            with pytest.raises(ValueError):
                nw.checked_subject(bad)
        assert nw.default_subject("SBL_r1") == "sbl.SBL_r1"

    def test_an_inbox_is_unique_to_its_connection(self):
        assert nw.new_inbox(lambda n: bytes(range(n))) == "_INBOX.000102030405060708090a"
        assert nw.new_inbox() != nw.new_inbox() and len(nw.new_inbox()) == 29

    def test_the_read_timeout_is_a_struct_timeval(self):
        assert nw.timeval(0.25) == struct.pack("ll", 0, 250000)
        assert nw.timeval(2) == struct.pack("ll", 2, 0)


# --- one connection ----------------------------------------------------------------------------

def opened(server=None, one_reply=False, **options):
    server = server or FakeServer(**options)
    link = nw.Link.open(server.connect, "broker", 4222, "test", one_reply=one_reply, waits=3)
    return server, link, server.sockets[-1]


class TestOpeningALink:

    def test_it_reads_info_says_connect_and_waits_for_the_pong(self):
        server, link, sock = opened()
        assert link.info["version"] == "2.15.1" and link.info["headers"] is True
        assert sock.frames[0].startswith(b"CONNECT {") and sock.frames[1] == b"PING\r\n"
        assert sock.connect_options["no_responders"] is True
        assert sock.timeout is None, "a blocking socket, so that a read waits in the kernel"
        assert (socket.SOL_SOCKET, socket.SO_RCVTIMEO, nw.timeval(nw.WAIT_S)) in sock.options
        assert (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) in sock.options

    def test_a_server_without_headers_is_refused(self):
        with pytest.raises(nw.ProtocolError, match="headers"):
            opened(headers=False)

    def test_a_server_that_is_not_nats_is_refused(self):
        with pytest.raises(nw.ProtocolError, match="not a NATS server"):
            opened(greeting=b"HTTP/1.1 400 Bad Request\r\n")

    def test_a_server_that_never_greets_is_given_up_on(self):
        with pytest.raises(nw.NoReply):
            opened(greeting=b"")

    def test_its_reads_wait_as_long_as_asked(self):
        server = FakeServer(greeting=b"")
        with pytest.raises(nw.NoReply, match="no greeting from broker:4222 in 3 waits of 0.10 s"):
            nw.Link.open(server.connect, "broker", 4222, "test", waits=3, wait_s=0.1)
        assert (socket.SOL_SOCKET, socket.SO_RCVTIMEO, nw.timeval(0.1)) in server.sockets[0].options
        assert server.clock() == pytest.approx(0.3, abs=1e-5), "three waits of 0.1 s passed"

    def test_a_server_that_hangs_up_is_closed(self):
        server = FakeServer(greeting=b"")
        server.events.append(lambda s: setattr(s.sockets[0], "gone", True))
        with pytest.raises(nw.Closed):
            opened(server)

    def test_an_err_is_raised(self):
        with pytest.raises(nw.ServerError, match="Authorization Violation"):
            opened(greeting=b"-ERR 'Authorization Violation'\r\n")


class TestPlainReads:

    def test_pings_are_answered_oks_passed_over_and_frames_cut_from_what_has_come(self):
        server, link, sock = opened()
        sock.feed(b"PING\r\n+OK\r\n" + DELIVERED + TIMEOUT_408)
        assert link.next_frame().reply == ACK_V1
        assert sock.frames[-1] == b"PONG\r\n"
        assert nw.status(link.next_frame()) == (408, "Request Timeout")
        assert sock.taken()[-1] == len(b"PING\r\n+OK\r\n" + DELIVERED + TIMEOUT_408), "one read"
        assert link.next_frame() is None, "the wait passed with nothing"

    def test_a_frame_read_in_pieces_is_read_whole(self):
        server, link, sock = opened()
        sock.feed(DELIVERED[:100])
        server.events.append(lambda s: sock.feed(DELIVERED[100:]))
        assert link.next_frame().payload == PAYLOAD
        assert sock.taken()[-2:] == [100, len(DELIVERED) - 100]


class TestOneReplyReads:

    def test_each_read_takes_exactly_one_frame(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED + TIMEOUT_408 + PUB_ACK)
        before = len(sock.taken())
        assert [link.next_frame().op for _ in range(3)] == ["MSG", "HMSG", "MSG"]
        assert sock.taken()[before:] == [len(DELIVERED), len(TIMEOUT_408), len(PUB_ACK)]
        assert link.next_frame() is None

    def test_a_frame_whose_rest_is_late_is_waited_for_by_a_peek_for_all_of_it(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED[:100])
        server.events.append(lambda s: sock.feed(DELIVERED[100:]))
        assert link.next_frame().payload == PAYLOAD
        waited = [r for r in sock.reads if r[1] == socket.MSG_PEEK | socket.MSG_WAITALL]
        assert waited == [(len(DELIVERED), socket.MSG_PEEK | socket.MSG_WAITALL, len(DELIVERED))]
        assert sock.taken()[-1] == len(DELIVERED)

    def test_a_line_cut_short_is_waited_for_a_byte_more_at_a_time(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED[:10])
        server.events.append(lambda s: sock.feed(DELIVERED[10:]))
        assert link.next_frame().payload == PAYLOAD
        waits = [r[0] for r in sock.reads if r[1] & socket.MSG_WAITALL]
        assert waits == [11], "one byte more was waited for, and then all that had come seen"
        assert sock.taken()[-1] == len(DELIVERED)

    def test_a_stalled_frame_is_taken_and_finished_by_reads_that_stop_at_its_end(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED[:100])
        assert link.next_frame() is None, "the wait passed with the frame still incomplete"
        assert sock.taken()[-1] == 100, "what had come was taken"
        sock.feed(DELIVERED[100:] + PUB_ACK)
        assert link.next_frame().payload == PAYLOAD
        assert sock.taken()[-1] == len(DELIVERED) - 100, "the rest of it, and nothing past it"
        assert link.next_frame().subject == "_INBOX.0c9d8e7f6a5b4c3d2e1f00.5"
        assert sock.taken()[-1] == len(PUB_ACK)

    def test_a_line_stalled_part_way_is_finished_a_byte_at_a_time(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(b"PI")
        assert link.next_frame() is None
        sock.feed(b"NG\r\n" + PUB_ACK)
        assert link.next_frame().subject == "_INBOX.0c9d8e7f6a5b4c3d2e1f00.5"
        assert sock.frames[-1] == b"PONG\r\n"

    def test_a_pong_is_one_frame_and_what_came_with_it_another(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(nw.PONG + DELIVERED)
        before = len(sock.taken())
        assert link.next_frame().op == "PONG" and link.next_frame().reply == ACK_V1
        assert sock.taken()[before:] == [len(nw.PONG), len(DELIVERED)]

    def test_a_pong_cut_short_is_waited_for_and_taken_alone(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(b"PO")
        server.events.append(lambda s: sock.feed(b"NG\r\n" + DELIVERED))
        assert link.next_frame().op == "PONG"
        assert sock.taken()[-1] == len(nw.PONG), "the PONG alone, though the message came with it"
        assert link.next_frame().reply == ACK_V1

    def test_a_read_that_brings_less_than_its_peek_saw_is_finished(self):
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED)
        sock.cap = 50
        assert link.next_frame().payload == PAYLOAD
        line = DELIVERED.index(b"\r\n") + 2
        expected = [50] + [1] * (line - 50) + [len(DELIVERED) - line]
        assert sock.taken()[-len(expected):] == expected, (
            "the rest of its line a byte at a time, then the payload, and nothing past the frame")

    def test_a_hang_up_with_nothing_or_part_of_a_frame_come_is_closed(self):
        server, link, sock = opened(one_reply=True)
        sock.gone = True
        with pytest.raises(nw.Closed):
            link.next_frame()
        server, link, sock = opened(one_reply=True)
        sock.feed(DELIVERED[:100])
        sock.gone = True
        with pytest.raises(nw.Closed):
            link.next_frame()


class TestRequestsAndService:

    def test_a_request_subscribes_once_and_its_reply_is_found_among_other_frames(self):
        server, link, sock = opened()
        server.streams["S"] = {"config": {"subjects": ["s"], "storage": "file"}, "messages": [],
                               "consumers": {}}
        sock.feed(PUB_ACK)
        frame = link.request(*nw.stream_info("S"))
        assert json.loads(frame.payload)["type"] == "io.nats.jetstream.api.v1.stream_info_response"
        assert link.request(*nw.stream_delete("S")).subject.endswith(".2")
        assert [f for f in sock.frames if f.startswith(b"SUB ")] == [
            b"SUB " + link.inbox.encode() + b".* 1\r\n"]

    def test_a_request_with_no_answer_is_given_up_on(self):
        server, link, sock = opened()
        with pytest.raises(nw.NoReply):
            link.request("$JS.ACK.S.C.1.1.1.1.0", nw.ACK, waits=2)

    def test_service_answers_pings_without_waiting_and_passes_the_rest_over(self):
        server, link, sock = opened()
        link.service()
        assert sock.attempts[-1] == (nw.READ_BYTES, nw.MSG_DONTWAIT), "nothing waited for"
        sock.feed(b"PING\r\n+OK\r\nPONG\r\nPI")
        link.service()
        assert sock.frames[-1] == b"PONG\r\n" and link.held[link.at:] == b"PI"
        sock.feed(b"NG\r\n")
        link.service()
        assert sock.frames[-2:] == [b"PONG\r\n", b"PONG\r\n"]

    def test_service_raises_an_err_and_a_hang_up(self):
        server, link, sock = opened()
        sock.feed(b"-ERR 'Stale Connection'\r\n")
        with pytest.raises(nw.ServerError):
            link.service()
        sock.gone = True
        with pytest.raises(nw.Closed):
            link.service()

    def test_writes_with_and_without_the_lock_and_the_close(self):
        server, link, sock = opened()
        link.write(nw.PING)
        link.send(nw.PING)
        assert sock.frames[-2:] == [b"PING\r\n", b"PING\r\n"]
        link.close()
        assert sock.closed


class TestTheScriptedServerWritesWhatNatsServerWrites:
    """The clients' tests are worth what FakeServer is worth: these hold it to nats-server's own
    frames and order."""

    @staticmethod
    def pulling(depth=2, **options):
        """A connection with a durable consumer whose max_waiting is 3, and `depth` requests
        waiting, their reply subjects INBOX.1, INBOX.2 ... on subscription 7."""
        server, link, sock = opened(**options)
        nw.ensure_stream(link, "SBL_r1", "sbl.r1")
        nw.ensure_consumer(link, "SBL_r1", "sbl-r1", max_waiting=3)
        link.write(nw.sub(INBOX + ".*", 7))
        subject, payload = nw.pull_request("SBL_r1", "sbl-r1", 30e9)
        for j in range(1, depth + 1):
            link.write(nw.pub(subject, payload, "%s.%d" % (INBOX, j)))
        return server, link, sock

    def test_a_delivery_comes_under_the_streams_subject_on_the_requests_subscription(self):
        server, link, sock = self.pulling()
        server.store("SBL_r1", b"one")
        frame = link.next_frame()
        assert (frame.op, frame.subject, frame.sid) == ("MSG", "sbl.r1", "7")
        assert frame.reply.startswith("$JS.ACK.SBL_r1.sbl-r1.1.1.1.") and frame.payload == b"one"
        assert server.waiting("SBL_r1") == [INBOX + ".2"], "the oldest request was served"

    def test_a_status_comes_under_the_reply_subject_of_the_request_it_ends(self):
        server, link, sock = self.pulling()
        server.end_requests("SBL_r1", 1, at=1)
        frame = link.next_frame()
        assert (frame.op, frame.subject, frame.sid, frame.reply) == ("HMSG", INBOX + ".2", "7",
                                                                    None)
        assert nw.status(frame) == (408, "Request Timeout")
        assert server.waiting("SBL_r1") == [INBOX + ".1"]

    def test_a_server_that_is_not_nats_server_can_serve_the_newest_first(self):
        server, link, sock = self.pulling(newest_first=True)
        server.store("SBL_r1", b"one")
        assert server.waiting("SBL_r1") == [INBOX + ".1"]

    def test_a_pong_comes_behind_what_the_connection_was_already_sent(self):
        server, link, sock = self.pulling()
        server.store("SBL_r1", b"one", b"two")
        link.write(nw.PING)
        assert [link.next_frame().op for _ in range(3)] == ["MSG", "MSG", "PONG"]

    def test_a_request_beyond_max_waiting_is_refused(self):
        server, link, sock = self.pulling(depth=4)
        assert len(server.waiting("SBL_r1")) == 3
        frame = link.next_frame()
        assert frame.subject == INBOX + ".4" and nw.status(frame) == (409, "Exceeded MaxWaiting")

    def test_time_passes_only_while_a_read_waits(self):
        server, link, sock = opened()
        sock.feed(nw.PONG)
        assert link.next_frame().op == "PONG" and server.clock() == 0, "nothing was waited for"
        assert link.next_frame() is None
        assert server.clock() == pytest.approx(nw.WAIT_S, abs=1e-5), "one read's wait"


class TestTheRequestsBothClientsMake:

    def test_a_status_where_an_answer_was_due_is_an_error(self):
        server, link, sock = opened()
        with pytest.raises(nw.JetStreamError, match="nats-server -js") as caught:
            nw.api(link, "sbl.nowhere", b"")
        assert caught.value.code == 503

    def test_a_status_with_a_description_says_it(self, monkeypatch):
        server, link, sock = opened()
        monkeypatch.setattr(server, "api", lambda path, reply, payload: server.status(
            reply, 409, "Consumer Deleted"))
        with pytest.raises(nw.JetStreamError, match="Consumer Deleted"):
            nw.api(link, *nw.stream_info("S"))

    def test_the_stream_is_created_and_taken_again_as_it_is(self):
        server, link, sock = opened()
        first = nw.ensure_stream(link, "SBL_r1", "sbl.r1")
        again = nw.ensure_stream(link, "SBL_r1", "sbl.r1")
        assert first["did_create"] is True and again["did_create"] is False
        assert server.streams["SBL_r1"]["config"]["storage"] == "file"
        consumer = nw.ensure_consumer(link, "SBL_r1", "sbl-r1")
        assert consumer["config"]["max_waiting"] == 512 and consumer["name"] == "sbl-r1"

    def test_one_that_exists_with_other_settings_is_taken_if_it_is_kept_the_same_way(self):
        server, link, sock = opened(strict_create=True)
        nw.ensure_stream(link, "SBL_r1", "sbl.r1", "memory")
        info = nw.ensure_stream(link, "SBL_r1", "sbl.r1", "memory")
        assert info["type"] == "io.nats.jetstream.api.v1.stream_info_response"

    def test_one_kept_another_way_or_on_another_subject_is_refused(self):
        server, link, sock = opened()
        nw.ensure_stream(link, "SBL_r1", "sbl.r1")
        with pytest.raises(nw.JetStreamError, match="exists on"):
            nw.ensure_stream(link, "SBL_r1", "sbl.r1", "memory")
        with pytest.raises(nw.JetStreamError, match="exists on"):
            nw.ensure_stream(link, "SBL_r1", "sbl.other")

    def test_any_other_error_is_raised_as_it_came(self):
        server, link, sock = opened()
        nw.ensure_stream(link, "SBL_r1", "sbl.r1")
        with pytest.raises(nw.JetStreamError) as caught:
            nw.ensure_stream(link, "SBL_r2", "sbl.r1")
        assert caught.value.err_code == 10065
