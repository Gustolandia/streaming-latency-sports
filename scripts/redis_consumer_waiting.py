#!/usr/bin/env python3
"""
redis_consumer_waiting.py -- a Redis consumer that keeps its next requests waiting at the broker:
the remedy plan version 47 tests for a pull consumer's turnaround.

A pull consumer lets its own thread's delays into the kernel-timed latency through its next
request: a message that reaches the broker while no request is waiting leaves only with that
request. Block U (freeze 43, docs/results/under_load/README.md) confirmed it for redis-py's
consumer, which sends its next XREADGROUP only after it has handled the last reply; under load the
slowest of those turnarounds were mostly its thread waiting for a core. Redis's protocol allows a
remedy. XREADGROUP with ">" moves the group's position on the server as each request runs, and a
blocked client's later commands wait in its query buffer and run as soon as it is unblocked. So
this consumer keeps --depth requests outstanding, and sends one more the moment a reply is read,
before any of it is handled: while the thread works, or waits for a core, the broker holds a
request to answer.

It opens two connections, each a raw socket with its own RESP2 client (scripts/resp_wire.py):

  measuring  XREADGROUP GROUP <group> <consumer> COUNT <n> BLOCK <ms> STREAMS <stream> > and
             nothing else, each request sent by its own call and answered in order. With
             --one-reply-reads each read takes exactly one reply, its end found with MSG_PEEK,
             so that the kernel's receive timestamp of a read is one reply's alone; without it,
             reads of up to 64 KiB, as redis-py makes them.
  second     the group's creation; every XACK, in batches of --ack-batch, each sent without
             waiting for its reply; and, at the end, XPENDING, which says whether any entry
             delivered to this consumer was left unacknowledged.

It writes the files and the columns scripts/redis_consumer.py writes, each entry's id taken from
the reply, and logs its CONFIG and OK lines in that script's words, so that the reader and the
integrity rule read either consumer's runs alike; its CONFIG line also names the depth, the reads
and both connections' local ports. The socket timestamps (scripts/so_timestamps.py) and the
collector switch and scheduler counters (scripts/client_quiet.py) work as in the other clients.
"""
import argparse
import collections
import csv
import errno
import json
import socket
import time
from pathlib import Path

import client_quiet
import law_clock
import resp_wire
import so_timestamps
import thread_record

#: What a buffered read asks for: redis-py's own reads (socket_read_size).
READ_BYTES = 65536
#: The most a peek looks at, and the most of an unfinished reply a one-reply read leaves in the
#: kernel while it waits for the rest. A reply waited for whole must fit in the connection's
#: receive window, which the kernel does not widen for bytes that are only peeked at, and Linux
#: opens a TCP connection with a 128 KiB receive buffer (tcp_rmem) and offers about half of it as
#: window. A longer reply, or one whose bulk string still owed would take it past this, is read in
#: parts, each part within the reply, and counted.
PEEK_BYTES = 32768
#: Seconds: how long a connection may take to open, and how long the end of a run waits for what
#: the broker still owes.
CONNECT_S = 10.0
CLOSING_S = 5.0
#: The outputs are flushed every this many rows, as scripts/redis_consumer.py flushes them.
FLUSH_EVERY = 2000
#: What a peek that waits in the kernel (MSG_PEEK | MSG_WAITALL) raises where the system cannot
#: wait so. 23 Oct 2026: on Windows 11 that peek failed with WSAEOPNOTSUPP (10045, which Python
#: names EOPNOTSUPP there); on Linux 6.18 (WSL) it waited 0.2 s for the bytes asked for and
#: returned exactly them.
UNSUPPORTED = (errno.EOPNOTSUPP, errno.EINVAL)
#: The replies that carry no entry: the nil array a BLOCK that timed out gives, and an empty array.
EMPTY = (b"*-1\r\n", b"*0\r\n")


def now_ns():
    """Wall-clock epoch ns, as every client stamps: the producer's stamps and the kernel's socket
    timestamps are on the same clock."""
    return time.time_ns()


class Closed(ConnectionError):
    """The broker closed a connection: a read found its end."""


def connect(host, port):
    """A TCP connection to the broker, blocking, so that a peek can wait in the kernel, and with
    TCP_NODELAY, as redis-py sets it, so that requests sent one behind another do not wait for the
    broker to acknowledge the last.

    socket.create_connection makes its socket from socket.socket as the socket module holds it at
    the call. Once so_timestamps.start() has run, that is its TimestampingSocket, which asks the
    kernel for timestamps at the connection's first send or read, the connection being up by then
    and its peer the port the run named: so each connection made here is in the run's ledger and
    journal."""
    try:
        sock = socket.create_connection((host, port), CONNECT_S)
    except OSError as exc:
        raise SystemExit("redis_consumer_waiting: cannot reach the broker at %s:%d: %s"
                         % (host, port, exc))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(None)
    return sock


class Wire(object):
    """One connection to the broker, and the bytes read from it that are not yet a whole reply."""

    def __init__(self, sock, name):
        self.sock = sock
        self.name = name
        self.buffer = bytearray()

    def port(self):
        """The connection's local port, by which a capture or the journal names it."""
        return self.sock.getsockname()[1]

    def buffered(self):
        """The next reply, from reads of up to READ_BYTES: a read may take more than one reply, or
        part of one, as redis-py's reads do."""
        framer = resp_wire.Framer()
        while True:
            end = framer.end(self.buffer, len(self.buffer))
            if end is not None:
                data = bytes(self.buffer[:end])
                del self.buffer[:end]
                return data
            chunk = self.sock.recv(READ_BYTES)
            if not chunk:
                raise Closed("the broker closed the %s connection" % self.name)
            self.buffer += chunk


class Measuring(Wire):
    """The measuring connection: requests all alike, and replies read one at a time, whole."""

    def __init__(self, sock, one_reply):
        Wire.__init__(self, sock, "measuring")
        self.one_reply = one_reply
        self.view = bytearray(PEEK_BYTES)
        self.wait_in_peek = True
        self.replies = self.parted = self.reads = 0

    def reply(self):
        """The next reply's bytes, whole."""
        data = self.one_whole() if self.one_reply else self.buffered()
        self.replies += 1
        return data

    def one_whole(self):
        """The next reply, read by exactly one read wherever it can be: a peek shows what is
        queued, the framer finds the reply's end in it, and exactly that many bytes are read.

        23 Oct 2026: the kernel's receive timestamp of a read is that of the last packet the read
        took (scripts/so_timestamps.py), so a buffered read that takes one reply's end and the
        next reply's start times the first by the second's packet. A peek takes nothing and is
        not timestamped, and the read that follows stops at the reply's last byte.

        While the reply is unfinished, every byte queued is its own, so where waiting in the
        kernel for the rest cannot be done, or could outgrow the window (PEEK_BYTES), what is
        queued is read and kept, and the reply is finished by later reads, each still within it,
        the framer going on over what was kept and what is queued; the reply is counted in
        `parted`."""
        framer = resp_wire.Framer()
        got = bytearray()
        self.reads = 0
        while True:
            n = self.sock.recv_into(self.view, len(self.view), socket.MSG_PEEK)
            if not n:
                raise Closed("the broker closed the measuring connection")
            end = framer.end(got + self.view[:n] if got else self.view, len(got) + n)
            if end is not None:
                got += self._take(end - len(got))
                break
            if not got and framer.least <= len(self.view) and self._wait(framer.least):
                continue
            got += self._take(n)
        if self.reads > 1:
            self.parted += 1
        return bytes(got)

    def _wait(self, need):
        """Whether `need` bytes are queued now, waited for in the kernel and left unread: False
        where the system cannot wait so (and it is not asked again), or where the wait ended short,
        as it does when the connection closes."""
        if not self.wait_in_peek:
            return False
        try:
            got = self.sock.recv_into(self.view, need, socket.MSG_PEEK | socket.MSG_WAITALL)
        except OSError as exc:
            if exc.errno not in UNSUPPORTED:
                raise
            self.wait_in_peek = False
            return False
        return got >= need

    def _take(self, size):
        """The `size` bytes a peek showed queued, read, each read counted."""
        data = self.sock.recv(size)
        self.reads += 1
        while len(data) < size:
            more = self.sock.recv(size - len(data))
            self.reads += 1
            if not more:
                raise Closed("the broker closed the measuring connection")
            data += more
        return data


class Acks(Wire):
    """The second connection: the group's creation, the acknowledgments, and the closing check.

    23 Oct 2026: in freeze 42's pilot, Redis's acknowledgment batches, sent on the consumer's one
    connection, fell outside the turnaround, and their messages filled 85-95% of the thread-free
    latency's tail (docs/results/under_load/README.md). Here no acknowledgment is sent on the
    measuring connection, and none is waited for."""

    def __init__(self, sock, stream, group, batch):
        Wire.__init__(self, sock, "second")
        self.stream, self.group, self.batch = stream, group, max(1, batch)
        self.ids = []
        self.sent = self.batches = self.answered = self.acked = 0
        self.refused = []

    def owed(self):
        """XACK replies not yet read."""
        return self.batches - self.answered

    def call(self, *args):
        """Send one command and read its reply, the XACK replies owed before it read first: a
        connection answers in order."""
        self.sock.sendall(resp_wire.command(*args))
        while self.owed():
            self._noted(self.buffered())
        return resp_wire.decode(self.buffered())

    def create_group(self):
        """XGROUP CREATE <stream> <group> 0-0 MKSTREAM, as scripts/redis_consumer.py makes it. A
        group that exists already (BUSYGROUP) is the one this run reads; any other error stops
        the run, for the requests would fail on it."""
        reply = self.call("XGROUP", "CREATE", self.stream, self.group, "0-0", "MKSTREAM")
        if isinstance(reply, resp_wire.ReplyError) and not str(reply).startswith("BUSYGROUP"):
            raise SystemExit("redis_consumer_waiting: the broker refused the group: %s" % reply)

    def add(self, redis_id):
        """One entry to acknowledge; a full batch is sent."""
        self.ids.append(redis_id)
        if len(self.ids) >= self.batch:
            self.flush()

    def flush(self):
        """The entries held, acknowledged by one XACK sent without waiting for its reply; the
        replies already in are read first, without waiting either."""
        if not self.ids:
            return
        self.collect()
        self.sock.sendall(resp_wire.command("XACK", self.stream, self.group, *self.ids))
        self.batches += 1
        self.sent += len(self.ids)
        self.ids = []

    def collect(self):
        """The XACK replies that have come in, read without waiting for any."""
        self.sock.settimeout(0.0)
        try:
            while self.owed():
                self._noted(self.buffered())
        except BlockingIOError:
            pass
        finally:
            self.sock.settimeout(None)

    def _noted(self, data):
        """One XACK reply: how many of its batch the broker found pending, and removed."""
        value = resp_wire.decode(data)
        self.answered += 1
        if isinstance(value, int):
            self.acked += value
        else:
            self.refused.append(str(value))

    def finish(self):
        """At the end: the last batch sent, every reply owed read, and the group's pending entries
        counted by XPENDING, waiting at most CLOSING_S for each read. An entry delivered to this
        consumer and never acknowledged is one it never read. Returns (that count, or None and
        why it is not known)."""
        try:
            self.flush()
            self.sock.settimeout(CLOSING_S)
            reply = self.call("XPENDING", self.stream, self.group)
        except (OSError, resp_wire.ProtocolError) as exc:
            return None, "unknown, no answer (%s: %s)" % (type(exc).__name__, exc)
        if isinstance(reply, list) and reply and isinstance(reply[0], int):
            return reply[0], ""
        return None, "unknown, XPENDING answered %r" % (reply,)


class Run(object):
    """One run's two output files and its counts."""

    def __init__(self, args, record, acks, f_out, f_events):
        self.args, self.record, self.acks = args, record, acks
        self.f_out, self.f_events = f_out, f_events
        # Existing (S2-compatible-ish) output rowset, as scripts/redis_consumer.py writes it.
        self.w = csv.DictWriter(f_out, fieldnames=[
            "run_id",
            "backend",
            "stream",
            "event_id",
            "match_id",
            "t_sim_seconds",
            "t_cons_recv_ns",
            "t_output_ns",
            "redis_id",
        ])
        self.w.writeheader()
        # The (S3) consumer event log, as scripts/redis_consumer.py writes it.
        self.ew = csv.DictWriter(f_events, fieldnames=[
            "run_id",
            "backend",
            "stream",
            "redis_id",
            "t_consume_ns",
            "event_id",
            "match_id",
            "t_sim_seconds",
            "t_emit_offset_s",
            "t_emit_planned_ns",
            "s3_uid",
            "s3_rev",
            "s3_is_correction",
        ])
        self.ew.writeheader()
        self.n = self.foreign = self.gone = 0

    def handle(self, found):
        """The entries one reply delivered, each as scripts/redis_consumer.py handles one: stamped,
        its payload parsed, kept only if it is this run's, and acknowledged. The payload gives the
        run filter and the columns copied from it; the entry's id is the broker's own, from the
        reply."""
        for stream_name, redis_id, fields in found:
            if fields is None:
                # An entry the stream no longer held when it was read: nothing to write.
                self.gone += 1
                self.acks.add(redis_id)
                continue
            t_consume_ns = now_ns()
            t_cons_recv_ns = t_consume_ns
            if self.record is not None:
                self.record.note("stamps_receive")
            msg = json.loads(fields["value"])

            # Filter to this run_id (prevents cross-run contamination when stream/group has old
            # data). Acknowledged in the batch, as every other entry: on the second connection an
            # acknowledgment costs the measuring connection nothing.
            if msg.get("run_id") != self.args.run_id:
                self.foreign += 1
                self.acks.add(redis_id)
                continue

            t_output_ns = now_ns()
            self.w.writerow({
                "run_id": self.args.run_id,
                "backend": "redis",
                "stream": stream_name,
                "event_id": msg.get("event_id"),
                "match_id": msg.get("match_id"),
                "t_sim_seconds": msg.get("t_sim_seconds"),
                "t_cons_recv_ns": t_cons_recv_ns,
                "t_output_ns": t_output_ns,
                "redis_id": redis_id,
            })
            self.ew.writerow({
                "run_id": self.args.run_id,
                "backend": "redis",
                "stream": stream_name,
                "redis_id": redis_id,
                "t_consume_ns": t_consume_ns,
                "event_id": msg.get("event_id"),
                "match_id": msg.get("match_id"),
                "t_sim_seconds": msg.get("t_sim_seconds"),
                "t_emit_offset_s": msg.get("t_emit_offset_s"),
                "t_emit_planned_ns": msg.get("t_emit_planned_ns"),
                "s3_uid": msg.get("s3_uid"),
                "s3_rev": msg.get("s3_rev"),
                "s3_is_correction": msg.get("s3_is_correction"),
            })
            self.n += 1
            if self.n % FLUSH_EVERY == 0:
                self.f_events.flush()
                self.f_out.flush()
            self.acks.add(redis_id)


def read_entries(data):
    """The entries of one reply on the measuring connection; an error reply stops the run."""
    try:
        return resp_wire.entries(resp_wire.decode(data))
    except resp_wire.ReplyError as exc:
        raise SystemExit("redis_consumer_waiting: the broker answered XREADGROUP with an error: %s"
                         % exc)


def answered(asked):
    """The send time of the request a reply answers: the oldest one outstanding."""
    if not asked:
        raise resp_wire.ProtocolError("a reply came with no request outstanding")
    return asked.popleft()


def consume(args, measuring, acks, quiet, run, request, trace):
    """--depth requests, then one more the moment each reply is read, until a reply comes with no
    message for --idle-seconds. Each reply's row in the read trace is its request's send time, the
    time from then until the reply was read, and its entries. Returns the send times of the
    requests left outstanding."""
    asked = collections.deque()

    def ask():
        # Freeze 43: this thread's scheduler counters just before each request, then the
        # request's own time, the read trace's start for its reply.
        client_quiet.sample(quiet)
        asked.append(now_ns())
        measuring.sock.sendall(request)

    for _ in range(args.depth):
        ask()
    last_msg = time.monotonic()
    while True:
        data = measuring.reply()
        t_read = now_ns()
        t_asked = answered(asked)
        if data in EMPTY:
            trace.append((t_asked, t_read - t_asked, 0))
            if time.monotonic() - last_msg >= args.idle_seconds:
                return asked
            ask()
            acks.flush()
            continue
        # 23 Oct 2026: block U found that redis-py's consumer leaves the broker with no request
        # waiting during its turnaround, and under load at normal priority its thread spent 32-49%
        # of that time waiting for a core (the setups' medians at 500 and 2,000 messages a
        # second). So the next request goes the moment a reply is read, before any of it is
        # handled, and with --depth above one a request is waiting at the broker even then.
        ask()
        found = read_entries(data)
        trace.append((t_asked, t_read - t_asked, len(found)))
        if found:
            last_msg = time.monotonic()
        run.handle(found)


def close_measuring(measuring, asked, run, trace):
    """The end, with no more requests to send: the connection's sending half is shut, and what the
    broker still sends is read until it closes the connection in answer, the entries any reply
    carries handled as the loop handles them. Redis frees a client whose connection has ended, the
    request it was blocked in and those queued behind it with it, so no entry is delivered to them
    once it has closed the connection. Returns (requests outstanding at the stop, replies read
    now, whether the broker closed the connection within CLOSING_S)."""
    outstanding, replies, closed = len(asked), 0, True
    try:
        # A connection the broker has already ended cannot be shut, and has nothing to read.
        measuring.sock.shutdown(socket.SHUT_WR)
        measuring.sock.settimeout(CLOSING_S)
        while True:
            # Read through the shim, which drains the error queue first: a socket with a timeout
            # whose error queue holds a timestamp is reported readable, and a peek would spin.
            data = measuring.buffered()
            t_read = now_ns()
            t_asked = answered(asked)
            found = read_entries(data)
            trace.append((t_asked, t_read - t_asked, len(found)))
            run.handle(found)
            replies += 1
    except socket.timeout:
        closed = False
    except OSError:
        pass
    measuring.sock.close()
    return outstanding, replies, closed


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--stream", default="sb:events")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=6379)
    ap.add_argument("--group", default=None)
    ap.add_argument("--consumer", default=None)
    ap.add_argument("--idle-seconds", type=float, default=15)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--block-ms", type=int, default=1000)
    ap.add_argument("--ack-batch", type=int, default=200,
                    help="XACK this many entries at a time, on the second connection")
    ap.add_argument("--depth", type=int, default=1,
                    help="XREADGROUP requests kept outstanding on the measuring connection")
    ap.add_argument("--one-reply-reads", action="store_true",
                    help="on the measuring connection, each read takes exactly one reply")
    # D28-1: the thread that stamps each arrival, and both clocks, for a recording of waits.
    ap.add_argument("--thread-record", action="store_true",
                    help="write which thread stamped the arrivals, and both clocks, beside the CSV")
    # scripts/run_redis_trial.sh hands every Redis consumer these three; this one reads one node.
    ap.add_argument("--node-count", type=int, default=1, choices=[1, 3])
    ap.add_argument("--cluster-mode", action="store_true")
    ap.add_argument("--cluster-nodes", default="")
    so_timestamps.add_arguments(ap)
    client_quiet.add_arguments(ap)
    args = ap.parse_args(argv)
    if args.cluster_mode or args.cluster_nodes or args.node_count != 1:
        ap.error("the waiting consumer reads one Redis node; a cluster is "
                 "scripts/redis_consumer.py's")
    if min(args.depth, args.count, args.block_ms) < 1:
        ap.error("--depth, --count and --block-ms must each be at least 1: with BLOCK 0 a request "
                 "waits for ever, and the idle stop would never be reached")
    return args


def main(argv=None):
    args = parse_args(argv)
    record = thread_record.ThreadRecord() if args.thread_record else None
    # F2 (freeze 40): the kernel's own timestamps on the broker's connections, if asked for, the
    # socket class replaced before either connection is made.
    so = so_timestamps.start(args, args.port)

    # Use per-run group default to prevent cross-run contamination
    group = args.group or "sb-group-%s" % args.run_id
    consumer = args.consumer or "c-%s" % args.run_id
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events_path = out_path.with_name(out_path.stem + "_events.csv")
    request = resp_wire.command("XREADGROUP", "GROUP", group, consumer, "COUNT", args.count,
                                "BLOCK", args.block_ms, "STREAMS", args.stream, ">")
    trace = []
    try:
        measuring = Measuring(connect(args.host, args.port), args.one_reply_reads)
        acks = Acks(connect(args.host, args.port), args.stream, group, args.ack_batch)
        acks.create_group()
        # Freeze 43 (22 Oct 2026): asked for, the collector goes off once both connections and
        # the group exist and before any request is sent.
        quiet = client_quiet.start(args)
        with out_path.open("w", newline="", encoding="utf-8") as f_out, events_path.open(
                "w", newline="", encoding="utf-8") as f_events:
            run = Run(args, record, acks, f_out, f_events)
            # The manipulation check, in scripts/redis_consumer.py's words and order first, so that
            # the integrity rule and the readers find ack_batch, count and block_ms as they do
            # there, then what this consumer adds: its depth, its reads and its two connections.
            print("CONFIG effective ack_batch=%d count=%d block_ms=%d cluster=False client=python "
                  "clock_resolution_ns=%d consumer=waiting depth=%d reads=%s "
                  "acks=second-connection measuring_port=%d ack_port=%d"
                  % (acks.batch, args.count, args.block_ms,
                     law_clock.demand_usable_resolution("the waiting Redis consumer"),
                     args.depth, "one-reply" if args.one_reply_reads else "buffered",
                     measuring.port(), acks.port()), flush=True)
            asked = consume(args, measuring, acks, quiet, run, request, trace)
            outstanding, closing, closed = close_measuring(measuring, asked, run, trace)
        pending, why = acks.finish()
        acks.sock.close()
    except ConnectionError as exc:
        raise SystemExit("redis_consumer_waiting: the connection to the broker was lost: %s"
                         % (exc,))
    except resp_wire.ProtocolError as exc:
        raise SystemExit("redis_consumer_waiting: the broker's bytes are not RESP2: %s" % exc)

    with out_path.with_name(out_path.stem + "_readtrace.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["t_read_start_ns", "read_duration_ns", "n_messages"])
        writer.writerows(trace)
    if record is not None:
        record.write(thread_record.beside(out_path))
    so_timestamps.finish(so, args)
    client_quiet.finish(quiet, args)
    print("OK reads: %d replies on the measuring connection, %d of them read in more than one "
          "read; reads=%s, waits in the kernel=%s"
          % (measuring.replies, measuring.parted,
             "one-reply" if args.one_reply_reads else "buffered",
             "yes" if measuring.wait_in_peek else "no"), flush=True)
    print("OK closing: %d requests outstanding at the stop, %d answered as the connection closed, "
          "%s" % (outstanding, closing, "closed by the broker" if closed else
                  "abandoned: the broker had not closed it after %g s" % CLOSING_S), flush=True)
    print("OK acks: %d entries in %d XACK batches on the second connection, %d acknowledged, "
          "%d batches refused; pending in the group at the end: %s"
          % (acks.sent, acks.batches, acks.acked, len(acks.refused),
             why if pending is None else pending), flush=True)
    print("OK entries: %d written, %d of other runs, %d no longer in the stream"
          % (run.n, run.foreign, run.gone), flush=True)
    print("OK redis consumer: wrote %d rows -> %s" % (run.n, out_path))
    print("OK redis consumer: wrote %d rows -> %s" % (run.n, events_path))


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    main()
