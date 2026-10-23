"""Tests for scripts/redis_consumer_waiting.py: the consumer that keeps requests waiting at Redis.

A broker is built here, on this machine's loopback, that answers the commands the consumer sends as
Redis 7 does. A request that finds no entry blocks, and the requests queued behind it wait in the
connection's query buffer until it is answered, by an entry or by its BLOCK running out with the
nil array; once the client has ended its connection, a request that would block is dropped with
everything queued behind it (Redis 7.2's blocked.c and networking.c: a blocked client's query
buffer is accumulated and processed once it is unblocked, and a client whose connection has ended
is freed). The broker records when each request arrived and each reply left, and how many
requests were waiting when each entry came.

Every test runs on Windows and on Linux. Where the shim needs what only Linux's kernel gives
(SO_TIMESTAMPING, recvmsg), the kernel's side is stood in for as tests/unit/test_so_timestamps.py
stands in for it; and one test runs the consumer on a real Linux kernel, through WSL on Windows,
with nothing stood in for.
"""
import ast
import collections
import csv
import errno
import gc
import inspect
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import client_quiet  # noqa: E402
import m0_read  # noqa: E402
import redis_consumer_waiting as rcw  # noqa: E402
import resp_wire as rw  # noqa: E402
import run_integrity  # noqa: E402
import so_journal  # noqa: E402
import so_timestamps as so  # noqa: E402
import under_load  # noqa: E402
from posix_shell import linux_bash, linux_path  # noqa: E402

#: The socket class as it was before any test installed the shim (scripts/so_timestamps.py keeps
#: it): the broker's own sockets are made from it, so the shim, which replaces socket.socket,
#: never sees them.
PLAIN_SOCKET = so._BASE

#: The first bytes of every request the consumer sends on its measuring connection.
REQUEST = b"*11\r\n$10\r\nXREADGROUP\r\n"


# --- the broker ----------------------------------------------------------------------------------
# Only the standard library below: the test on a real kernel ships this source to Linux.

def bulk(data):
    """A bulk string."""
    return b"$%d\r\n%s\r\n" % (len(data), data)


def encode_read(stream, taken):
    """XREADGROUP's reply in RESP2 for the entries taken: the nil array for none, and an entry the
    stream no longer holds with the nil array for its fields."""
    if not taken:
        return b"*-1\r\n"
    out = [b"*1\r\n*2\r\n", bulk(stream), b"*%d\r\n" % len(taken)]
    for eid, fields in taken:
        if fields is None:
            out.append(b"*2\r\n" + bulk(eid) + b"*-1\r\n")
            continue
        out.append(b"*2\r\n" + bulk(eid) + b"*%d\r\n" % len(fields))
        out.extend(bulk(f) for f in fields)
    return b"".join(out)


def split_commands(buf):
    """Every whole command at the front of `buf`, each an array of bulk strings, taken out of it."""
    found = []
    while buf.startswith(b"*"):
        line = buf.find(b"\r\n")
        if line < 0:
            break
        pos, args = line + 2, []
        for _ in range(int(buf[1:line])):
            line = buf.find(b"\r\n", pos)
            if line < 0:
                return found
            start = line + 2
            end = start + int(buf[pos + 1:line])
            if len(buf) < end + 2:
                return found
            args.append(bytes(buf[start:end]))
            pos = end + 2
        found.append(args)
        del buf[:pos]
    return found


def message(i, run_id="r47"):
    """The producer's JSON for message i, with every field scripts/redis_producer.py sends."""
    return json.dumps({"run_id": run_id, "match_id": 3890000 + i, "event_id": "constant-%06d" % i,
                       "t_sim_seconds": i * 0.5, "t_emit_offset_s": i * 0.5,
                       "t_emit_planned_ns": 1790000000000000000 + i,
                       "s3_uid": "%d:constant-%06d" % (3890000 + i, i), "s3_rev": 1,
                       "s3_is_correction": False}, separators=(",", ":"))


class FakeConn(object):
    """One client connection to the broker: a thread frames each command into the connection's
    query buffer as it arrives, and another runs them in order."""

    def __init__(self, server, sock):
        self.server, self.sock = server, sock
        self.port = sock.getpeername()[1]
        self.queue = collections.deque()
        self.ended = False
        self.names = []
        self.log = []
        self.asked = self.answered = 0

    def start(self):
        for target in (self._read, self._run):
            threading.Thread(target=target, daemon=True).start()

    def _read(self):
        buf = bytearray()
        while True:
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            with self.server.lock:
                if not data:
                    self.ended = True
                    self.server.lock.notify_all()
                    return
                buf += data
                for args in split_commands(buf):
                    name = args[0].upper()
                    self.names.append(name)
                    self.queue.append(args)
                    if name == b"XREADGROUP":
                        self.log.append(("ask", self.asked, time.perf_counter()))
                        self.asked += 1
                self.server.lock.notify_all()

    def _run(self):
        lock = self.server.lock
        while True:
            with lock:
                while not self.queue and not self.ended:
                    lock.wait()
                if not self.queue:
                    break
                done = self._execute(self.queue.popleft())
            if done is None:
                # A request that would wait, on a connection its client has ended: Redis frees the
                # client, and drops the request and every command queued behind it.
                break
            if not self._write(*done):
                return
        time.sleep(self.server.linger)
        self.close()

    def _execute(self, args):
        server = self.server
        name = args[0].upper()
        if name == b"XREADGROUP":
            return self._read_group(args)
        if name == b"XGROUP":
            if server.group_reply is not None:
                return server.group_reply, [], []
            if args[3] in server.groups:
                return b"-BUSYGROUP Consumer Group name already exists\r\n", [], []
            server.groups[args[3]] = {"next": 0, "pending": {}}
            return b"+OK\r\n", [], []
        if name == b"XACK":
            server.acks.append(args[3:])
            pending = server.groups[args[2]]["pending"]
            gone = [eid for eid in args[3:] if pending.pop(eid, None) is not None]
            return b":%d\r\n" % len(gone), [], []
        if name == b"XPENDING":
            pending = server.groups[args[2]]["pending"]
            if not pending:
                return b"*4\r\n:0\r\n$-1\r\n$-1\r\n*-1\r\n", [], []
            ids = sorted(pending)
            return (b"*4\r\n:%d\r\n" % len(ids) + bulk(ids[0]) + bulk(ids[-1]) + b"*1\r\n*2\r\n"
                    + bulk(b"c") + bulk(b"%d" % len(ids))), [], []
        return b"-ERR unknown command\r\n", [], []

    def _take(self, state, count, consumer):
        taken = self.server.entries[state["next"]:state["next"] + count]
        state["next"] += len(taken)
        for eid, _ in taken:
            state["pending"][eid] = consumer
        return taken

    def _read_group(self, args):
        server = self.server
        words = [a.upper() for a in args]
        group, consumer = args[2], args[3]
        count = int(args[words.index(b"COUNT") + 1])
        block_s = int(args[words.index(b"BLOCK") + 1]) / 1000.0
        stream = args[words.index(b"STREAMS") + 1]
        index = server.reads
        server.reads += 1
        if index in server.instead:
            return server.instead.pop(index), [index], []
        state = server.groups[group]
        deadline = time.monotonic() + block_s
        while state["next"] >= len(server.entries):
            if self.ended:
                return None
            left = deadline - time.monotonic()
            if left <= 0:
                return b"*-1\r\n", [index], []
            server.lock.wait(left)
        taken = self._take(state, count, consumer)
        reply, indices, eids = encode_read(stream, taken), [index], [eid for eid, _ in taken]
        if (server.pairs and self.queue and self.queue[0][0].upper() == b"XREADGROUP"
                and state["next"] < len(server.entries)):
            # As Redis answers the next request queued behind one it has just answered, before it
            # writes either: both replies leave in one write.
            self.queue.popleft()
            more = self._take(state, count, consumer)
            reply += encode_read(stream, more)
            indices.append(server.reads)
            server.reads += 1
            eids += [eid for eid, _ in more]
        return reply, indices, eids

    def _write(self, reply, indices, eids):
        server = self.server
        try:
            if indices and server.parts is not None and len(reply) > server.parts[0]:
                cut, pause = server.parts
                self.sock.sendall(reply[:cut])
                time.sleep(pause)
                self.sock.sendall(reply[cut:])
            else:
                self.sock.sendall(reply)
        except OSError:
            return False
        now = time.perf_counter()
        with server.lock:
            server.paired += len(indices) > 1
            for index in indices:
                self.answered += 1
                self.log.append(("reply", index, now))
            for eid in eids:
                server.delivered[eid] = now
            server.lock.notify_all()
        for index in indices:
            if server.after_reply is not None:
                server.after_reply(self, index)
            if server.drop_after == index:
                self.close()
                return False
        return True

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class FakeRedis(object):
    """A stand-in for Redis 7 on the loopback, for the commands the waiting consumer sends."""

    FIRST_MS = 1790000000000

    def __init__(self):
        self.lock = threading.Condition()
        self.entries, self.groups, self.conns, self.acks = [], {}, [], []
        self.added, self.delivered, self.waiting = {}, {}, {}
        self.reads = self.paired = 0
        self.instead = {}            # {XREADGROUP index: the bytes to answer it with instead}
        self.parts = None            # (bytes, seconds): a longer reply sent in two writes
        self.pairs = False           # a reply with entries and the next one, in one write
        self.after_reply = None      # called with (connection, XREADGROUP index) once written
        self.drop_after = None       # the XREADGROUP index after whose reply the connection ends
        self.linger = 0.0            # seconds a connection its client ended is kept open
        self.group_reply = None      # what XGROUP CREATE answers instead
        self.stopped = False
        self.listener = PLAIN_SOCKET(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while not self.stopped:
            try:
                fd, _ = self.listener._accept()
            except socket.timeout:
                continue
            except OSError:
                return
            sock = PLAIN_SOCKET(socket.AF_INET, socket.SOCK_STREAM, 0, fileno=fd)
            sock.setblocking(True)
            conn = FakeConn(self, sock)
            with self.lock:
                self.conns.append(conn)
            conn.start()

    def add(self, *payloads):
        """Entries, as XADD makes them, all at once; their ids. A payload of None is an entry the
        stream no longer holds when it is read."""
        ids = []
        with self.lock:
            for payload in payloads:
                eid = b"%d-0" % (self.FIRST_MS + len(self.entries))
                fields = None if payload is None else [b"value", payload.encode("utf-8")]
                self.entries.append((eid, fields))
                self.added[eid] = time.perf_counter()
                self.waiting[eid] = sum(c.asked - c.answered for c in self.conns)
                ids.append(eid.decode("ascii"))
            self.lock.notify_all()
        return ids

    def asking(self):
        """The connections that asked for entries."""
        with self.lock:
            return [c for c in self.conns if b"XREADGROUP" in c.names]

    def others(self):
        with self.lock:
            return [c for c in self.conns if b"XREADGROUP" not in c.names]

    def wait_for(self, test, timeout=10.0):
        deadline = time.monotonic() + timeout
        with self.lock:
            while not test():
                left = deadline - time.monotonic()
                assert left > 0, "the broker waited in vain"
                self.lock.wait(left)

    def stop(self):
        self.stopped = True
        self.listener.close()
        for conn in list(self.conns):
            conn.close()


# --- helpers -------------------------------------------------------------------------------------

@pytest.fixture
def broker():
    fake = FakeRedis()
    try:
        yield fake
    finally:
        fake.stop()


def consume(tmp_path, broker, *extra):
    """The consumer's main(), against the broker, stopping at the first reply with no message."""
    out = tmp_path / "consumer.csv"
    rcw.main(["--run-id", "r47", "--out", str(out), "--host", "127.0.0.1",
              "--port", str(broker.port), "--stream", "s47", "--group", "g47",
              "--block-ms", "100", "--idle-seconds", "0"] + list(extra))
    return out


def rows_of(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def said(capsys):
    return capsys.readouterr().out


def stamp(ns):
    """struct scm_timestamping: the software time first, then two empty ones."""
    return so.TIMESPEC.pack(ns // 10**9, ns % 10**9) + bytes(2 * so.TIMESPEC.size)


@pytest.fixture
def kernel(monkeypatch):
    """The kernel's side of SO_TIMESTAMPING, stood in for as tests/unit/test_so_timestamps.py stands
    in for it, so that the shim runs where the system has neither the option nor recvmsg
    (Windows): the option is taken, the error queue stays empty, and each read through the shim is
    the socket's own read with a receive timestamp, the wall clock as it read. socket.socket is
    put back afterwards."""
    monkeypatch.setattr(socket, "socket", socket.socket)
    taken = []
    monkeypatch.setattr(so, "_setsockopt", lambda sock, flags: taken.append((sock, flags)))
    monkeypatch.setattr(so, "_queued", lambda sock: False)

    def recvmsg(sock, bufsize, ancbufsize, flags):
        data = so._BASE.recv(sock, bufsize, flags)
        return data, [(socket.SOL_SOCKET, so.SCM_TIMESTAMPING, stamp(time.time_ns()))], 0, None

    monkeypatch.setattr(so, "_recvmsg", recvmsg)
    return taken


def within_replies(conn):
    """Whether every read of a journaled connection lies within one reply, and every reply's last
    byte ends a read: what --one-reply-reads promises the reader."""
    ends = [end for _, end in so_journal.resp_items(conn.inb)]
    reads = [end for end, n, _ in conn.reads if n]
    before = 0
    for end in reads:
        if any(before < e < end for e in ends):
            return False
        before = end
    return set(ends) <= set(reads)


def the_measuring_one(conns):
    (measuring,) = [c for c in conns.values() if c.out.startswith(REQUEST)]
    return measuring


@pytest.fixture
def collector_restored():
    """--gc-off switches this process's collector off and freezes every object in it, and the rest
    of the suite runs here too: the collector is put back as it was."""
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


# --- the switches --------------------------------------------------------------------------------

class TestTheSwitches:
    def test_the_defaults(self):
        args = rcw.parse_args(["--run-id", "r", "--out", "o.csv"])
        assert (args.depth, args.ack_batch, args.count, args.block_ms, args.idle_seconds,
                args.one_reply_reads, args.node_count) == (1, 200, 200, 1000, 15, False, 1)

    @pytest.mark.parametrize("extra", [["--cluster-mode"], ["--node-count", "3"],
                                       ["--cluster-nodes", "10.0.1.1:7000"]])
    def test_the_kits_cluster_flags_are_refused(self, extra, capsys):
        """scripts/run_redis_trial.sh hands every Redis consumer --node-count; a cluster is the
        other consumer's."""
        with pytest.raises(SystemExit):
            rcw.parse_args(["--run-id", "r", "--out", "o.csv"] + extra)
        assert "reads one Redis node" in capsys.readouterr().err

    @pytest.mark.parametrize("extra", [["--depth", "0"], ["--count", "0"], ["--block-ms", "0"]])
    def test_nothing_below_one_and_no_block_for_ever(self, extra, capsys):
        with pytest.raises(SystemExit):
            rcw.parse_args(["--run-id", "r", "--out", "o.csv", "--node-count", "1"] + extra)
        assert "at least 1" in capsys.readouterr().err


# --- the pipeline --------------------------------------------------------------------------------

class TestThePipeline:
    def test_depth_one_keeps_one_request_outstanding_and_asks_again_on_every_reply(
            self, broker, tmp_path, capsys):
        ids = broker.add(*[message(i) for i in range(1, 6)])
        out = consume(tmp_path, broker, "--count", "2")
        (conn,) = broker.asking()
        asks = [t for kind, _, t in conn.log if kind == "ask"]
        replies = [t for kind, _, t in conn.log if kind == "reply"]
        assert len(replies) == 4, "two, two, one, and the nil array that stops it"
        assert len(asks) == 4, "the reply that stops it is not asked after"
        assert all(asks[k + 1] > replies[k] for k in range(3)), "each ask after the last reply"
        assert [r["redis_id"] for r in rows_of(out)] == ids
        trace = rows_of(tmp_path / "consumer_readtrace.csv")
        assert [r["n_messages"] for r in trace] == ["2", "2", "1", "0"]
        assert "OK closing: 0 requests outstanding at the stop" in said(capsys)

    def test_depth_three_sends_three_and_one_more_for_each_reply(self, broker, tmp_path, capsys):
        broker.add(*[message(i) for i in range(1, 6)])
        out = consume(tmp_path, broker, "--depth", "3", "--count", "1")
        (conn,) = broker.asking()
        asks = [t for kind, _, t in conn.log if kind == "ask"]
        replies = [t for kind, _, t in conn.log if kind == "reply"]
        assert len(replies) == 6 and len(asks) == 3 + 5
        # Request k + 3 can only leave once reply k is read: the pipeline is filled again by one
        # request for each reply.
        assert all(asks[k + 3] > replies[k] for k in range(5))
        assert conn.asked - conn.answered == 2, "two left outstanding at the stop"
        assert len(rows_of(out)) == 5
        text = said(capsys)
        assert "consumer=waiting depth=3 reads=buffered" in text
        assert ("OK closing: 2 requests outstanding at the stop, 0 answered as the connection "
                "closed, closed by the broker") in text

    def test_the_next_request_goes_before_any_of_a_reply_is_handled(self, broker, tmp_path,
                                                                    monkeypatch):
        events = []
        sample, loads, reply = client_quiet.sample, json.loads, rcw.Measuring.reply
        monkeypatch.setattr(client_quiet, "sample", lambda q: events.append("ask") or sample(q))
        monkeypatch.setattr(json, "loads", lambda text: events.append("handle") or loads(text))
        monkeypatch.setattr(rcw.Measuring, "reply",
                            lambda self: events.append("reply") or reply(self))
        broker.add(message(1), message(2), message(3))
        consume(tmp_path, broker, "--count", "2")
        assert events == ["ask", "reply", "ask", "handle", "handle", "reply", "ask", "handle",
                          "reply"]

    @pytest.mark.parametrize("depth,waiting", [(1, 0), (2, 1)])
    def test_a_message_that_comes_during_a_turnaround_finds_a_request_waiting_only_with_depth(
            self, broker, tmp_path, monkeypatch, depth, waiting):
        """The thread stopped for 0.3 s just before its first new request, as a thread waiting for
        a core is stopped, and a message comes the moment the reply before it has left."""
        sample, calls, second = client_quiet.sample, [], []

        def slow(quiet):
            calls.append(1)
            if len(calls) == depth + 1:
                time.sleep(0.3)
            sample(quiet)

        monkeypatch.setattr(client_quiet, "sample", slow)
        broker.after_reply = lambda conn, index: index == 0 and second.extend(
            broker.add(message(2)))

        def first():
            broker.wait_for(lambda: sum(c.asked for c in broker.conns) >= depth)
            broker.add(message(1))

        threading.Thread(target=first, daemon=True).start()
        out = consume(tmp_path, broker, "--depth", str(depth), "--idle-seconds", "0.5")
        eid = second[0].encode("ascii")
        assert broker.waiting[eid] == waiting
        held = broker.delivered[eid] - broker.added[eid]
        assert (held > 0.25) if depth == 1 else (held < 0.2), held
        assert [r["event_id"] for r in rows_of(out)] == ["constant-000001", "constant-000002"]


# --- the reads -----------------------------------------------------------------------------------

class QueueSocket(object):
    """The measuring connection's socket, stood in for: the kernel's receive queue, the parts of
    replies still to arrive (one each time a read would otherwise wait), and how a peek that waits
    (MSG_WAITALL) is answered: "wait", as Linux answers it; "unsupported", as Windows does;
    "short", a wait that ended early; "reset", a connection reset."""

    def __init__(self, arriving, waitall="wait", short=None, lost_after=None):
        self.queue = bytearray()
        self.arriving = [bytes(a) for a in arriving]
        self.waitall, self.short, self.lost_after = waitall, short, lost_after
        self.reads, self.waits = [], 0

    def _arrive(self):
        if self.arriving:
            self.queue += self.arriving.pop(0)

    def recv_into(self, buffer, nbytes, flags):
        assert flags & socket.MSG_PEEK
        if flags & socket.MSG_WAITALL:
            self.waits += 1
            if self.waitall == "unsupported":
                raise OSError(errno.EOPNOTSUPP, "not supported")
            if self.waitall == "reset":
                raise ConnectionResetError(errno.ECONNRESET, "reset")
            while self.waitall == "wait" and len(self.queue) < nbytes and self.arriving:
                self._arrive()
        elif not self.queue:
            self._arrive()
        n = min(nbytes, len(self.queue))
        buffer[:n] = self.queue[:n]
        return n

    def recv(self, size):
        if len(self.reads) == self.lost_after:
            return b""
        if not self.queue:
            self._arrive()
        n = min(size, len(self.queue), self.short or size)
        data = bytes(self.queue[:n])
        del self.queue[:n]
        self.reads.append(data)
        return data


A = b"*1\r\n*2\r\n$3\r\ns47\r\n*1\r\n*2\r\n$15\r\n1790000000000-0\r\n*2\r\n$5\r\nvalue\r\n$8\r\n" \
    b"{\"a\":11}\r\n"
B = b"*-1\r\n"


class TestOneReplyReads:
    def test_a_whole_reply_is_one_read_and_the_next_stays_queued(self):
        sock = QueueSocket([A + B])
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == A and sock.reads == [A] and bytes(sock.queue) == B
        assert reads.reply() == B and sock.reads == [A, B]
        assert (sock.waits, reads.parted, reads.replies) == (0, 0, 2)

    def test_a_reply_that_comes_in_parts_is_waited_for_in_the_kernel_and_read_once(self):
        sock = QueueSocket([A[:10], A[10:40], A[40:] + B])
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == A and sock.reads == [A]
        assert sock.waits >= 1 and reads.parted == 0 and reads.wait_in_peek

    def test_where_the_kernel_cannot_wait_the_reply_is_read_in_parts_each_within_it(self):
        sock = QueueSocket([A[:10], A[10:] + B[:2], B[2:]], waitall="unsupported")
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == A and sock.reads == [A[:10], A[10:]]
        assert reads.parted == 1 and not reads.wait_in_peek
        # The next reply's first line cut after two bytes: what was read of it is kept and
        # framed again with the rest.
        assert reads.reply() == B and sock.reads[2:] == [B[:2], B[2:]]
        assert sock.waits == 1, "and the kernel is not asked to wait again"
        assert reads.parted == 2

    def test_a_wait_that_ends_short_reads_what_came(self):
        sock = QueueSocket([A[:10], A[10:]], waitall="short")
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == A and sock.reads == [A[:10], A[10:]]
        assert reads.wait_in_peek, "a short wait is not a system that cannot wait"

    def test_a_wait_that_fails_otherwise_is_raised(self):
        reads = rcw.Measuring(QueueSocket([A[:10], A[10:]], waitall="reset"), True)
        with pytest.raises(ConnectionResetError):
            reads.reply()

    def test_a_reply_longer_than_a_peek_is_read_in_parts_without_waiting(self, monkeypatch):
        monkeypatch.setattr(rcw, "PEEK_BYTES", 16)
        sock = QueueSocket([A])
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == A and sock.waits == 0
        assert b"".join(sock.reads) == A and len(sock.reads) == -(-len(A) // 16)
        assert all(len(r) <= 16 for r in sock.reads) and reads.parted == 1

    def test_a_bulk_string_still_owed_past_a_peek_is_not_waited_for(self, monkeypatch):
        monkeypatch.setattr(rcw, "PEEK_BYTES", 64)
        big = b"*1\r\n$200\r\n" + b"x" * 200 + b"\r\n"
        sock = QueueSocket([big[:30], big[30:]])
        reads = rcw.Measuring(sock, True)
        assert reads.reply() == big and sock.waits == 0 and sock.reads[0] == big[:30]

    def test_a_short_read_is_finished_and_an_end_inside_it_is_the_connections_end(self):
        sock = QueueSocket([A], short=7)
        assert rcw.Measuring(sock, True).reply() == A and len(sock.reads) > 1
        with pytest.raises(rcw.Closed):
            rcw.Measuring(QueueSocket([A], short=7, lost_after=2), True).reply()

    def test_a_peek_at_the_end_is_the_connections_end(self):
        with pytest.raises(rcw.Closed, match="measuring"):
            rcw.Measuring(QueueSocket([]), True).reply()


class TestBufferedReads:
    def test_a_read_takes_what_has_come_and_the_replies_are_cut_from_it(self):
        sock = QueueSocket([A + B[:2], B[2:]])
        reads = rcw.Measuring(sock, False)
        assert reads.reply() == A and sock.reads == [A + B[:2]]
        assert reads.reply() == B and sock.reads == [A + B[:2], B[2:]]

    def test_an_end_is_the_connections_end(self):
        with pytest.raises(rcw.Closed, match="measuring"):
            rcw.Measuring(QueueSocket([A[:5]]), False).reply()


class TestReadsOnTheWire:
    """The same through real sockets, read by the journal's own reader."""

    def test_one_reply_reads_take_one_reply_each_where_two_left_in_one_write(
            self, broker, kernel, tmp_path, capsys):
        broker.pairs = True
        threading.Thread(target=lambda: (
            broker.wait_for(lambda: sum(c.asked for c in broker.conns) >= 2),
            broker.add(*[message(i) for i in range(1, 7)])), daemon=True).start()
        consume(tmp_path, broker, "--depth", "2", "--count", "1", "--one-reply-reads",
                "--idle-seconds", "0.3", "--so-timestamps", str(tmp_path / "consumer_so.csv"),
                "--so-journal", str(tmp_path / "consumer_journal"))
        assert broker.paired >= 1, "two replies did leave in one write"
        conn = the_measuring_one(so_journal.load(str(tmp_path / "consumer_journal")))
        ends = [end for _, end in so_journal.resp_items(conn.inb)]
        assert [end for end, n, _ in conn.reads if n] == ends, "one read, one reply"
        assert "0 of them read in more than one read; reads=one-reply" in said(capsys)

    def test_buffered_reads_let_one_read_take_two_replies(self, broker, kernel, tmp_path):
        """What --one-reply-reads is for: the read's receive timestamp would be the second reply's
        last packet's, for both."""
        broker.pairs = True
        threading.Thread(target=lambda: (
            broker.wait_for(lambda: sum(c.asked for c in broker.conns) >= 2),
            broker.add(*[message(i) for i in range(1, 7)])), daemon=True).start()
        consume(tmp_path, broker, "--depth", "2", "--count", "1", "--idle-seconds", "0.3",
                "--so-timestamps", str(tmp_path / "consumer_so.csv"),
                "--so-journal", str(tmp_path / "consumer_journal"))
        assert broker.paired >= 1
        conn = the_measuring_one(so_journal.load(str(tmp_path / "consumer_journal")))
        ends = [end for _, end in so_journal.resp_items(conn.inb)]
        reads = [end for end, n, _ in conn.reads if n]
        assert len(reads) < len(ends) and set(reads) < set(ends)

    def test_a_reply_that_comes_in_two_writes_is_read_within_itself(self, broker, kernel,
                                                                     tmp_path, capsys):
        """Waited for in the kernel where the system can (Linux), and read in parts where it
        cannot (Windows); either way no read holds bytes of two replies."""
        broker.parts = (40, 0.05)
        broker.add(*[message(i) for i in range(1, 4)])
        consume(tmp_path, broker, "--depth", "2", "--count", "1", "--one-reply-reads",
                "--so-timestamps", str(tmp_path / "consumer_so.csv"),
                "--so-journal", str(tmp_path / "consumer_journal"))
        conn = the_measuring_one(so_journal.load(str(tmp_path / "consumer_journal")))
        assert within_replies(conn)
        text = said(capsys)
        line = [ln for ln in text.splitlines() if ln.startswith("OK reads:")][0]
        parted = int(line.split(", ")[1].split()[0])
        assert parted == 0 if line.endswith("waits in the kernel=yes") else parted >= 1


# --- the acknowledgments -------------------------------------------------------------------------

class AckSocket(object):
    """The second connection's socket, stood in for: what the broker has sent, and what was sent."""

    def __init__(self, incoming=b""):
        self.incoming = bytearray(incoming)
        self.sent, self.timeouts = [], []
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value
        self.timeouts.append(value)

    def sendall(self, data):
        self.sent.append(bytes(data))

    def recv(self, size):
        if not self.incoming:
            if self.timeout == 0.0:
                raise BlockingIOError(errno.EAGAIN, "nothing yet")
            raise socket.timeout("timed out")
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data


class TestTheAcknowledgments:
    def test_each_batch_goes_without_waiting_and_replies_are_read_as_they_come(self):
        sock = AckSocket()
        acks = rcw.Acks(sock, "s47", "g47", 1)
        acks.add("1-0")
        acks.add("2-0")
        sock.incoming += b":1\r\n:1\r\n"
        acks.add("3-0")
        assert (acks.batches, acks.answered, acks.acked, acks.sent) == (3, 2, 2, 3)
        assert sock.sent == [rw.command("XACK", "s47", "g47", i) for i in ("1-0", "2-0", "3-0")]
        assert sock.timeouts == [0.0, None] * 3, "never a read that waits"

    def test_at_the_end_the_owed_replies_and_the_pending_count_are_read(self):
        sock = AckSocket()
        acks = rcw.Acks(sock, "s47", "g47", 0)
        assert acks.batch == 1, "a batch of 0 is one of 1, as scripts/redis_consumer.py reads it"
        acks.batch = 200
        acks.add("1-0")
        acks.add("2-0")
        sock.incoming += b"-ERR no such key\r\n*4\r\n:0\r\n$-1\r\n$-1\r\n*-1\r\n"
        assert acks.finish() == (0, "")
        assert acks.refused == ["ERR no such key"] and acks.acked == 0
        assert sock.sent == [rw.command("XACK", "s47", "g47", "1-0", "2-0"),
                             rw.command("XPENDING", "s47", "g47")]
        assert sock.timeouts[-1] == rcw.CLOSING_S

    @pytest.mark.parametrize("incoming,why", [(b"", "timed out"), (b"?x\r\n", "ProtocolError"),
                                              (b"-NOGROUP gone\r\n", "XPENDING answered")])
    def test_a_pending_count_that_cannot_be_had_is_unknown_and_not_waited_for(self, incoming,
                                                                            why):
        pending, reason = rcw.Acks(AckSocket(incoming), "s47", "g47", 200).finish()
        assert pending is None and reason.startswith("unknown") and why in reason

    @pytest.mark.parametrize("reply", [b"+OK\r\n",
                                       b"-BUSYGROUP Consumer Group name already exists\r\n"])
    def test_a_new_group_or_this_runs_own_is_read(self, reply):
        sock = AckSocket(reply)
        rcw.Acks(sock, "s47", "g47", 1).create_group()
        assert sock.sent == [rw.command("XGROUP", "CREATE", "s47", "g47", "0-0", "MKSTREAM")]

    def test_any_other_refusal_of_the_group_stops_the_run(self):
        with pytest.raises(SystemExit, match="refused the group: WRONGTYPE"):
            rcw.Acks(AckSocket(b"-WRONGTYPE wrong kind\r\n"), "s47", "g47", 1).create_group()

    def test_on_the_wire_the_batches_go_on_the_second_connection_and_none_on_the_measuring_one(
            self, broker, tmp_path, capsys):
        ids = broker.add(*[message(i) for i in range(1, 6)])
        consume(tmp_path, broker, "--ack-batch", "2", "--count", "5")
        (conn,) = broker.asking()
        assert set(conn.names) == {b"XREADGROUP"}
        (second,) = broker.others()
        assert second.names == [b"XGROUP", b"XACK", b"XACK", b"XACK", b"XPENDING"]
        assert [[i.decode("ascii") for i in a] for a in broker.acks] == [ids[:2], ids[2:4], ids[4:]]
        assert ("OK acks: 5 entries in 3 XACK batches on the second connection, 5 acknowledged, "
                "0 batches refused; pending in the group at the end: 0") in said(capsys)

    def test_a_group_that_exists_is_this_runs_and_the_flushes_come_every_so_many_rows(
            self, broker, tmp_path, monkeypatch):
        monkeypatch.setattr(rcw, "FLUSH_EVERY", 2)
        broker.groups[b"g47"] = {"next": 0, "pending": {}}
        broker.add(*[message(i) for i in range(1, 4)])
        assert len(rows_of(consume(tmp_path, broker))) == 3


# --- what the replies carry ----------------------------------------------------------------------

class TestWhatTheRepliesCarry:
    def test_the_rows_are_the_entries_by_the_brokers_own_ids_and_the_payloads_columns(
            self, broker, tmp_path):
        ids = broker.add(message(1), message(2))
        out = consume(tmp_path, broker, "--count", "1")
        rows, events = rows_of(out), rows_of(tmp_path / "consumer_events.csv")
        assert [r["redis_id"] for r in rows] == [r["redis_id"] for r in events] == ids
        assert [r["event_id"] for r in rows] == ["constant-000001", "constant-000002"]
        sent = json.loads(message(2))
        for name in ("match_id", "t_sim_seconds", "t_emit_offset_s", "t_emit_planned_ns", "s3_uid",
                     "s3_rev", "s3_is_correction"):
            assert events[1][name] == str(sent[name]), name
        assert rows[0]["stream"] == "s47" and rows[0]["backend"] == "redis"
        assert rows[0]["t_cons_recv_ns"] == events[0]["t_consume_ns"]
        assert int(rows[0]["t_output_ns"]) >= int(rows[0]["t_cons_recv_ns"])

    def test_an_entry_of_another_run_or_one_the_stream_lost_is_acknowledged_not_written(
            self, broker, tmp_path, capsys):
        broker.add(message(1, run_id="other"), None, message(2))
        out = consume(tmp_path, broker)
        assert [r["event_id"] for r in rows_of(out)] == ["constant-000002"]
        text = said(capsys)
        assert "OK entries: 1 written, 1 of other runs, 1 no longer in the stream" in text
        assert "3 acknowledged" in text and "pending in the group at the end: 0" in text

    @pytest.mark.parametrize("reads", [[], ["--one-reply-reads"]])
    def test_a_reply_with_no_entry_is_no_message(self, broker, tmp_path, reads):
        broker.instead = {0: b"*-1\r\n", 1: b"*1\r\n*2\r\n$3\r\ns47\r\n*0\r\n"}
        broker.add(message(1))
        out = consume(tmp_path, broker, "--idle-seconds", "1", "--block-ms", "50", *reads)
        assert len(rows_of(out)) == 1
        trace = rows_of(tmp_path / "consumer_readtrace.csv")
        assert [r["n_messages"] for r in trace[:3]] == ["0", "0", "1"]

    @pytest.mark.parametrize("reply,why", [
        (b"?garbage\r\n", "not RESP2"),
        (b":5\r\n", "not RESP2"),
        (b"*1\r\n*2\r\n$3\r\ns47\r\n:7\r\n", "not RESP2"),
        (b"-ERR boom\r\n", "answered XREADGROUP with an error: ERR boom"),
    ])
    def test_a_reply_that_is_not_one_to_xreadgroup_stops_the_run(self, broker, tmp_path, reply,
                                                                 why):
        broker.instead = {0: reply}
        with pytest.raises(SystemExit, match=why):
            consume(tmp_path, broker)

    def test_a_reply_with_no_request_outstanding_is_not_one(self):
        with pytest.raises(rw.ProtocolError):
            rcw.answered(collections.deque())

    @pytest.mark.parametrize("reads", [[], ["--one-reply-reads"]])
    def test_a_connection_lost_stops_the_run(self, broker, tmp_path, reads):
        broker.drop_after = 0
        broker.add(message(1))
        with pytest.raises(SystemExit, match="connection to the broker was lost"):
            consume(tmp_path, broker, "--idle-seconds", "5", *reads)

    def test_no_broker_stops_the_run(self, tmp_path):
        free = PLAIN_SOCKET(socket.AF_INET, socket.SOCK_STREAM)
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
        free.close()
        with pytest.raises(SystemExit, match="cannot reach the broker at 127.0.0.1:%d" % port):
            rcw.main(["--run-id", "r47", "--out", str(tmp_path / "c.csv"), "--host", "127.0.0.1",
                      "--port", str(port)])

    def test_a_refused_group_stops_the_run(self, broker, tmp_path):
        broker.group_reply = b"-WRONGTYPE Operation against a key holding the wrong kind\r\n"
        with pytest.raises(SystemExit, match="refused the group"):
            consume(tmp_path, broker)


# --- the end -------------------------------------------------------------------------------------

class TestTheEnd:
    def test_with_no_message_it_stops_after_idle_seconds(self, broker, tmp_path, capsys):
        began = time.monotonic()
        consume(tmp_path, broker, "--idle-seconds", "0.35", "--depth", "3")
        took = time.monotonic() - began
        assert 0.35 <= took < 5.0, took
        trace = rows_of(tmp_path / "consumer_readtrace.csv")
        assert len(trace) >= 3 and {r["n_messages"] for r in trace} == {"0"}
        assert ("OK closing: 2 requests outstanding at the stop, 0 answered as the connection "
                "closed, closed by the broker") in said(capsys)
        (conn,) = broker.asking()
        assert conn.asked == conn.answered + 2

    def test_at_depth_64_the_63_left_at_the_stop_go_with_the_connection(self, broker, tmp_path,
                                                                          capsys):
        """The remedy's own depth: the requests still outstanding at the stop are dropped by the
        broker as the connection closes, not waited out one BLOCK after another, 6.3 s here."""
        broker.add(*[message(i) for i in range(1, 11)])
        began = time.monotonic()
        out = consume(tmp_path, broker, "--depth", "64", "--count", "1", "--one-reply-reads")
        assert time.monotonic() - began < 5.0
        assert len(rows_of(out)) == 10
        (conn,) = broker.asking()
        assert (conn.asked, conn.answered) == (64 + 10, 11)
        assert ("OK closing: 63 requests outstanding at the stop, 0 answered as the connection "
                "closed, closed by the broker") in said(capsys)

    def test_a_message_keeps_it_going(self, broker, tmp_path):
        timer = threading.Timer(0.25, lambda: broker.add(message(1)))
        began = time.monotonic()
        timer.start()
        out = consume(tmp_path, broker, "--idle-seconds", "0.35")
        assert time.monotonic() - began >= 0.6
        assert len(rows_of(out)) == 1

    def test_an_entry_that_comes_as_it_stops_is_still_read_and_written(self, broker, tmp_path,
                                                                     capsys):
        """The request outstanding at the stop is answered before the broker drops the client:
        its entry is handled and acknowledged, and nothing is left pending."""
        broker.add(message(1))
        broker.after_reply = lambda conn, index: index == 1 and broker.add(message(2))
        out = consume(tmp_path, broker, "--depth", "2")
        assert [r["event_id"] for r in rows_of(out)] == ["constant-000001", "constant-000002"]
        text = said(capsys)
        assert ("OK closing: 1 requests outstanding at the stop, 1 answered as the connection "
                "closed, closed by the broker") in text
        assert "pending in the group at the end: 0" in text

    def test_a_broker_that_does_not_close_is_left_after_closing_s(self, broker, tmp_path,
                                                                 monkeypatch, capsys):
        monkeypatch.setattr(rcw, "CLOSING_S", 0.3)
        broker.linger = 2.0
        began = time.monotonic()
        consume(tmp_path, broker)
        assert time.monotonic() - began < 2.0, "not waited for"
        assert "abandoned: the broker had not closed it after 0.3 s" in said(capsys)

    def test_a_connection_already_ended_is_not_shut_again(self):
        class Gone(object):
            closed = False

            def shutdown(self, how):
                raise OSError(errno.ENOTCONN, "not connected")

            def close(self):
                self.closed = True

        measuring = rcw.Measuring(Gone(), False)
        assert rcw.close_measuring(measuring, collections.deque([1, 2]), None, []) == (2, 0, True)
        assert measuring.sock.closed


# --- the instruments -----------------------------------------------------------------------------

@pytest.fixture
def counters(tmp_path, monkeypatch):
    """A file in the place of /proc/thread-self/schedstat, and os.pread wherever it is missing."""
    path = tmp_path / "schedstat"
    path.write_bytes(b"1000 200 3\n")
    monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(path))
    monkeypatch.setattr(os, "pread", getattr(os, "pread", _seek_and_read), raising=False)
    return path


class TestTheInstruments:
    def test_the_shim_sees_both_raw_sockets_and_journals_the_measuring_connection(
            self, broker, kernel, tmp_path, capsys):
        """socket.socket replaced before either connection is made, as the other clients have it:
        each is a TimestampingSocket, connected to the run's port, timestamping turned on at its
        first send, and every byte and read journaled; the measuring one carries only requests for
        entries, each paired with its reply as the reader pairs them."""
        broker.add(*[message(i) for i in range(1, 4)])
        stem = tmp_path / "consumer_journal"
        consume(tmp_path, broker, "--depth", "2", "--count", "1", "--one-reply-reads",
                "--so-timestamps", str(tmp_path / "consumer_so.csv"), "--so-journal", str(stem))
        ledger = so.TimestampingSocket._ledger
        assert len(kernel) == 2 and {flags for _, flags in kernel} == {ledger.flags}
        assert all(isinstance(sock, so.TimestampingSocket) for sock, _ in kernel)
        assert so.TimestampingSocket._ports == (broker.port,)
        conns = so_journal.load(str(stem))
        assert sorted(c.peer_port for c in conns.values()) == [broker.port] * 2
        conn = the_measuring_one(conns)
        pairs = under_load.requests_on(conn, "redis")
        assert len(pairs) == 4 and all(asks for _, _, _, asks in pairs)
        sent = so_journal.resp_items(conn.out)
        assert len(sent) == 2 + 3 and len({conn.out[s:e] for s, e in sent}) == 1, "all alike"
        assert [end for end, n, _ in conn.reads if n] == [
            e for _, e in so_journal.resp_items(conn.inb)]
        assert all(ns is not None for _, n, ns in conn.reads if n)
        (second,) = [c for c in conns.values() if c is not conn]
        names = [under_load.command_name(second.out, s)
                 for s, _ in so_journal.resp_items(second.out)]
        assert names == [b"XGROUP", b"XACK", b"XPENDING"]
        received = [r for r in rows_of(tmp_path / "consumer_so.csv") if r["direction"] == "rx"]
        assert [r["event_id"] for r in received] == ["constant-%06d" % i for i in (1, 2, 3)]
        assert all(r["ns"] for r in received)
        summary = json.loads((tmp_path / "consumer_so_summary.json").read_text(encoding="utf-8"))
        assert (summary["connections"], summary["journal_connections"]) == (2, 2)
        text = said(capsys)
        assert "OK socket timestamps: 0 ids sent, 3 read" in text
        assert "measuring_port=%s ack_port=%s" % (conn.local_port, second.local_port) in text

    def test_the_collector_goes_off_before_the_first_request_and_the_counters_are_read_before_each(
            self, broker, tmp_path, monkeypatch, counters, collector_restored, capsys):
        events, real = [], socket.socket.sendall

        def sendall(sock, data, *flags):
            if bytes(data[:len(REQUEST)]) == REQUEST:
                events.append(("send", gc.isenabled()))
            return real(sock, data, *flags)

        pread, clock = os.pread, rcw.now_ns
        monkeypatch.setattr(socket.socket, "sendall", sendall)
        monkeypatch.setattr(os, "pread", lambda *a: events.append(("sample", gc.isenabled()))
                            or pread(*a))
        monkeypatch.setattr(rcw, "now_ns", lambda: events.append(("clock", None)) or clock())
        gc.enable()
        broker.add(*[message(i) for i in (1, 2, 3)])
        consume(tmp_path, broker, "--depth", "2", "--count", "1", "--gc-off",
                "--gc-log", str(tmp_path / "consumer_gc.json"),
                "--schedstat", str(tmp_path / "consumer_schedstat.csv"))
        sends = [i for i, (kind, _) in enumerate(events) if kind == "send"]
        assert len(sends) == 2 + 3
        assert all([kind for kind, _ in events[i - 2:i]] == ["sample", "clock"] for i in sends)
        assert {on for kind, on in events if kind in ("send", "sample")} == {False}
        assert len(rows_of(tmp_path / "consumer_schedstat.csv")) == 5
        logged = json.loads((tmp_path / "consumer_gc.json").read_text(encoding="utf-8"))
        assert logged["gc_off"] is True and logged["collections"] == []
        text = said(capsys)
        assert "OK schedstat: 5 samples" in text and "OK collector: off" in text

    def test_with_no_switch_it_writes_the_three_files_alone(self, broker, tmp_path, capsys):
        broker.add(message(1))
        consume(tmp_path, broker)
        assert sorted(p.name for p in tmp_path.iterdir()) == [
            "consumer.csv", "consumer_events.csv", "consumer_readtrace.csv"]
        text = said(capsys)
        assert "OK collector" not in text and "OK schedstat" not in text
        assert "OK socket timestamps" not in text

    def test_the_thread_that_stamps_arrivals_is_named_when_asked(self, broker, tmp_path):
        broker.add(message(1))
        consume(tmp_path, broker, "--thread-record")
        record = json.loads((tmp_path / "consumer_threads.json").read_text(encoding="utf-8"))
        assert record["roles"] == {"stamps_receive": [threading.get_native_id()]}


# --- the same as the other Redis consumer --------------------------------------------------------

class TestReadAsTheOtherRedisConsumerIsRead:
    def test_the_files_and_their_columns_are_redis_consumers(self, broker, tmp_path, monkeypatch):
        import redis_consumer
        theirs, ours = tmp_path / "theirs", tmp_path / "ours"
        mock = MagicMock()
        mock.xgroup_create.side_effect = Exception("Group exists")
        mock.xreadgroup.side_effect = [[("s47", [("1-0", {"value": message(1)})])], None]
        monkeypatch.setattr(sys, "argv", ["rc", "--run-id", "r47", "--out",
                                          str(theirs / "consumer.csv"), "--idle-seconds", "0"])
        with patch("redis_consumer.redis.Redis", return_value=mock):
            with patch("redis_consumer.time.monotonic", side_effect=lambda: 100.0):
                redis_consumer.main()
        broker.add(message(1))
        ours.mkdir()
        consume(ours, broker)
        assert sorted(p.name for p in theirs.iterdir()) == sorted(p.name for p in ours.iterdir())
        for name in ("consumer.csv", "consumer_events.csv", "consumer_readtrace.csv"):
            with open(theirs / name, encoding="utf-8") as a:
                with open(ours / name, encoding="utf-8") as b:
                    assert a.readline() == b.readline(), name
        mine, other = rows_of(ours / "consumer_events.csv"), rows_of(theirs / "consumer_events.csv")
        same = [k for k in other[0] if k not in ("redis_id", "t_consume_ns")]
        assert [mine[0][k] for k in same] == [other[0][k] for k in same]

    def test_the_integrity_rule_and_m0s_reader_find_its_settings(self, broker, tmp_path, capsys):
        broker.add(message(1))
        consume(tmp_path, broker)
        log = said(capsys)
        (tmp_path / "consumer.log").write_text(log, encoding="utf-8")
        check = run_integrity.client_check(str(tmp_path), "redis")
        assert check["ok"] and check["value"] == 200
        assert m0_read.REDIS_CONFIG.search(log).groups() == ("200", "200", "100")
        assert "OK redis consumer: wrote 1 rows -> %s" % (tmp_path / "consumer.csv") in log

    def test_it_parses_as_python_39(self):
        source = (ROOT / "scripts" / "redis_consumer_waiting.py").read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 9))


# --- on a real kernel ----------------------------------------------------------------------------

#: The run on Linux: the broker above, every reply that carries an entry sent in two writes 50 ms
#: apart, and the consumer with nothing stood in for.
DRIVER = r'''

def main(work):
    broker = FakeRedis()
    broker.parts = (40, 0.05)

    def feed():
        # After the kernel has turned receive timestamps on, which it does a moment after the
        # first socket asks for them.
        time.sleep(0.3)
        for i in range(1, 7):
            broker.add(message(i))
            time.sleep(0.02)

    threading.Thread(target=feed, daemon=True).start()
    import redis_consumer_waiting
    redis_consumer_waiting.main([
        "--run-id", "r47", "--out", os.path.join(work, "consumer.csv"), "--host", "127.0.0.1",
        "--port", str(broker.port), "--stream", "s47", "--group", "g47", "--block-ms", "100",
        "--idle-seconds", "0.6", "--depth", "3", "--count", "1", "--one-reply-reads",
        "--so-timestamps", os.path.join(work, "consumer_so.csv"),
        "--so-journal", os.path.join(work, "consumer_journal"),
        "--schedstat", os.path.join(work, "consumer_schedstat.csv")])
    broker.stop()


main(sys.argv[1])
'''


def test_on_a_real_linux_kernel_the_raw_socket_is_timestamped_and_each_read_is_one_reply(tmp_path):
    """Not a made-up world: on Linux (through WSL on Windows), the consumer runs with the shim as a
    run has it, SO_TIMESTAMPING asked of the kernel and recvmsg reading its timestamps, against the
    broker above, each reply that carries an entry arriving in two writes 50 ms apart. The kernel
    waits inside the peek for the rest of each, so every read is one whole reply, and every read
    that delivered an entry carries the kernel's receive timestamp, on the clock of the
    consumer's own stamps."""
    program = ("import collections, json, os, socket, sys, threading, time\n"
               "import so_timestamps\nPLAIN_SOCKET = so_timestamps._BASE\n\n\n"
               + "\n\n".join(inspect.getsource(obj) for obj in (
                   bulk, encode_read, split_commands, message, FakeConn, FakeRedis)) + DRIVER)
    # open() and not Path.write_text, whose newline= Python 3.9 does not take.
    with open(tmp_path / "linux_run.py", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(program)
    work = linux_path(tmp_path)
    done = linux_bash('cd "%s" && PYTHONPATH="$REPO/scripts" python3 linux_run.py "%s"'
                      % (work, work), timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "waits in the kernel=yes" in done.stdout and \
        "0 of them read in more than one read" in done.stdout, done.stdout
    rows = rows_of(tmp_path / "consumer.csv")
    assert [r["event_id"] for r in rows] == ["constant-%06d" % i for i in range(1, 7)]
    conns = so_journal.load(str(tmp_path / "consumer_journal"))
    assert len(conns) == 2
    conn = the_measuring_one(conns)
    replies = so_journal.resp_items(conn.inb)
    assert [end for end, n, _ in conn.reads if n] == [e for _, e in replies]
    stamped = dict((r["redis_id"], int(r["t_cons_recv_ns"])) for r in rows)
    carried = 0
    for (start, end), (request_start, request_end) in zip(replies, so_journal.resp_items(conn.out)):
        found = rw.entries(rw.decode(conn.inb[start:end]))
        if not found:
            continue
        carried += 1
        received = so_journal.rx_at(conn, end - 1)
        assert received is not None, "the read that delivered an entry is timestamped"
        assert so_journal.tx_at(conn, request_end - 1) is not None
        for _, redis_id, _ in found:
            assert 0 <= stamped[redis_id] - received < 10**9
    assert carried == 6
    summary = json.loads((tmp_path / "consumer_so_summary.json").read_text(encoding="utf-8"))
    assert summary["connections"] == 2 and summary["refused"] == 0
    assert summary["ids_read"] == 6 and summary["ids_read_untimed"] == 0
    assert len(rows_of(tmp_path / "consumer_schedstat.csv")) == len(so_journal.resp_items(conn.out))
