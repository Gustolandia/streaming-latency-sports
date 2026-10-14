#!/usr/bin/env python3
"""
so_timestamps.py -- the kernel's own transmit and receive timestamps, read by a benchmark client on
its own sockets through SO_TIMESTAMPING, the form freeze 40's block F2 tests.

F1 (freeze 39) timed each message between the kernel's timestamps read from packet captures. A
tool would ask the kernel for the same timestamps on its own sockets instead. install() replaces
socket.socket in the client's process with a subclass, before the client library opens its
connections. On each TCP connection to one of the given ports it turns the option on at the first
send or read, once the connection is up, so that byte offsets count from the first byte sent:

  transmit  the kernel's software timestamp of each send call, returned on the socket's error
            queue with the byte offset of the call's last byte (OPT_ID). A message is timed by the
            first timestamp whose offset is at or after its event id's last byte: the send call
            that carried it out.
  receive   the kernel's software timestamp returned with each read: that of the last packet the
            read consumed. A message is timed by the read that delivered its event id's last byte.

The error queue is drained on every send and read and when the socket closes: while it holds a
timestamp the socket reports itself readable, and a client waiting on it would spin. Each event id
is found in the bytes as scripts/full_fix.py finds it in the captures: an id carried twice within
one record is timed by its later carrying, and the same id seen further on is another message's.

    import so_timestamps
    ledger = so_timestamps.install([9092])
    ...  # the client runs
    ledger.write("runs/<run>/producer_so.csv")

Every call into the operating system goes through a module-level function, so the tests can stand
in for a kernel this module cannot reach on every system the suite runs on.
"""
import bisect
import csv
import json
import os
import re
import socket
import struct
import threading

#: <asm-generic/socket.h> and <linux/net_tstamp.h>. On a 64-bit system the original option already
#: carries 64-bit times.
SO_TIMESTAMPING = 37
SCM_TIMESTAMPING = SO_TIMESTAMPING
SOF_TIMESTAMPING_TX_SOFTWARE = 1 << 1
SOF_TIMESTAMPING_RX_SOFTWARE = 1 << 3
SOF_TIMESTAMPING_SOFTWARE = 1 << 4
SOF_TIMESTAMPING_OPT_ID = 1 << 7
SOF_TIMESTAMPING_TX_SCHED = 1 << 8
SOF_TIMESTAMPING_OPT_TSONLY = 1 << 11
#: Where the kernel takes the transmit timestamp: as the driver hands the packet to the card
#: ("software"), or as the packet enters the queue in front of the driver ("sched").
TRANSMIT = {"software": SOF_TIMESTAMPING_TX_SOFTWARE, "sched": SOF_TIMESTAMPING_TX_SCHED}
#: struct sock_extended_err, the control message beside each transmit timestamp.
SOL_IP, IP_RECVERR, SOL_IPV6, IPV6_RECVERR = 0, 11, 41, 25
SO_EE_ORIGIN_TIMESTAMPING = 4
SCM_TSTAMP = {"software": 0, "sched": 1}
EXTENDED_ERR = struct.Struct("=IBBBBII")
#: struct timespec on a 64-bit system; struct scm_timestamping holds three, the first software.
TIMESPEC = struct.Struct("=qq")
MSG_ERRQUEUE, MSG_DONTWAIT, MSG_PEEK = 0x2000, 0x40, 0x2
ANCILLARY = 512

#: As scripts/recv_wait.py and scripts/full_fix.py find an event id, and how far apart two carryings
#: of one id may lie and still be one message's.
EVENT_ID = re.compile(rb"constant-\d{6}")
JOINT = 64
SAME_RECORD = 2048


# --- the operating system, one call each, for the tests to stand in for ------------------------

#: The socket class as it was before install() replaced it, so that each call below reaches the
#: system's own method and not the replacement's.
_BASE = socket.socket

def _getpeername(sock):
    return _BASE.getpeername(sock)


def _setsockopt(sock, flags):
    _BASE.setsockopt(sock, socket.SOL_SOCKET, SO_TIMESTAMPING, flags)


def _send(sock, data, flags):
    return _BASE.send(sock, data, flags)


def _sendall(sock, data, flags):
    return _BASE.sendall(sock, data, flags)


def _recv(sock, bufsize, flags):
    return _BASE.recv(sock, bufsize, flags)


def _recv_into(sock, buffer, nbytes, flags):
    return _BASE.recv_into(sock, buffer, nbytes, flags)


def _recvmsg(sock, bufsize, ancbufsize, flags):
    return _BASE.recvmsg(sock, bufsize, ancbufsize, flags)


def _recvmsg_into(sock, buffers, ancbufsize, flags):
    return _BASE.recvmsg_into(sock, buffers, ancbufsize, flags)


def _close(sock):
    _BASE.close(sock)


def _queued(sock):
    """Whether anything waits on the socket's error queue, asked without waiting. poll() reports
    POLLERR for it whatever events are asked for. A read of the queue cannot be made non-blocking
    by MSG_DONTWAIT alone: on a socket with a timeout, as kafka-python sets one while it sends,
    Python first waits for the socket to become readable, and the pilot's first Kafka client lost
    every request that way (14 October)."""
    import select
    poller = select.poll()
    poller.register(sock.fileno(), 0)
    return any(events & select.POLLERR for _, events in poller.poll(0))


# --- reading the kernel's control messages ------------------------------------------------------

def software_ns(ancillary):
    """The software timestamp, in ns, from a read's control messages; None without one."""
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == SCM_TIMESTAMPING and len(data) >= TIMESPEC.size:
            sec, nsec = TIMESPEC.unpack_from(data, 0)
            return sec * 1000000000 + nsec
    return None


def transmit_key(ancillary, where="software"):
    """The byte offset a transmit timestamp of the asked-for kind carries; None otherwise."""
    for level, kind, data in ancillary:
        if (level, kind) in ((SOL_IP, IP_RECVERR), (SOL_IPV6, IPV6_RECVERR)) \
                and len(data) >= EXTENDED_ERR.size:
            _errno, origin, _type, _code, _pad, info, key = EXTENDED_ERR.unpack_from(data, 0)
            if origin == SO_EE_ORIGIN_TIMESTAMPING and info == SCM_TSTAMP[where]:
                return key
    return None


def carried(chunk, tail, start):
    """[(event id, stream offset of its last byte)] for each id that ends in `chunk`, which begins
    at stream offset `start`; `tail` is the end of the stream before it, so that an id straddling
    two sends or two reads is found."""
    joined = tail + chunk
    return [(m.group(0).decode("ascii"), start - len(tail) + m.end() - 1)
            for m in EVENT_ID.finditer(joined) if m.end() > len(tail)]


def one_message(times):
    """A message's time from [(last byte offset, ns)] for each carrying of its id: the latest of
    those within SAME_RECORD of the first, as full_fix.departure_times rules."""
    first = min(offset for offset, _ in times)
    found = [ns for offset, ns in times if offset - first <= SAME_RECORD and ns is not None]
    return max(found) if found else None


class _Stream(object):
    """One connection's offsets, its transmit timestamps by key, and the ids it carried."""

    def __init__(self, sock):
        self.sock = sock
        self.sent = self.read = 0
        self.tail_sent = self.tail_read = b""
        self.keys = {}
        self.sends = []
        self.closed = False


class Ledger(object):
    """Everything the process's timestamping sockets saw, and the counts that say how complete it
    is. Shared by the client library's threads."""

    def __init__(self, where="software"):
        self.where = where
        self.flags = (TRANSMIT[where] | SOF_TIMESTAMPING_RX_SOFTWARE | SOF_TIMESTAMPING_SOFTWARE
                      | SOF_TIMESTAMPING_OPT_ID | SOF_TIMESTAMPING_OPT_TSONLY)
        self.lock = threading.Lock()
        self.streams = []
        self.reads = {}
        self.counts = {"connections": 0, "refused": 0, "transmit_timestamps": 0,
                       "other_queue_entries": 0, "reads": 0, "reads_without_timestamp": 0}

    def count(self, name, by=1):
        with self.lock:
            self.counts[name] += by

    def sent(self, stream, chunk):
        with self.lock:
            stream.sends += carried(chunk, stream.tail_sent, stream.sent)
            stream.sent += len(chunk)
            stream.tail_sent = (stream.tail_sent + chunk)[-JOINT:]

    def read(self, stream, chunk, ns):
        with self.lock:
            self.counts["reads"] += 1
            if ns is None:
                self.counts["reads_without_timestamp"] += 1
            for eid, offset in carried(chunk, stream.tail_read, stream.read):
                self.reads.setdefault(eid, []).append((offset, ns))
            stream.read += len(chunk)
            stream.tail_read = (stream.tail_read + chunk)[-JOINT:]

    def transmit_times(self):
        """{event id: the transmit timestamp of the send call that carried it out}, for every id
        a send carried; None where no timestamp covers its last byte."""
        with self.lock:
            marks = {}
            for stream in self.streams:
                keys = sorted(stream.keys)
                for eid, offset in stream.sends:
                    i = bisect.bisect_left(keys, offset)
                    ns = stream.keys[keys[i]] if i < len(keys) else None
                    marks.setdefault(eid, []).append((offset, ns))
        return dict((eid, one_message(times)) for eid, times in marks.items())

    def receive_times(self):
        """{event id: the receive timestamp of the read that delivered it}."""
        with self.lock:
            reads = dict(self.reads)
        return dict((eid, one_message(times)) for eid, times in reads.items())

    def write(self, path):
        """One row per event id and direction, and the counts beside them in a summary."""
        for stream in list(self.streams):
            if not stream.closed:
                _drain(stream.sock, stream, self)
        rows = [(eid, "tx", ns) for eid, ns in sorted(self.transmit_times().items())]
        rows += [(eid, "rx", ns) for eid, ns in sorted(self.receive_times().items())]
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["event_id", "direction", "ns"])
            w.writerows((eid, way, "" if ns is None else ns) for eid, way, ns in rows)
        # A packet that enters two device queues, as on a virtual card that hands it on to a
        # physical one, is timestamped at each; the first is kept, so the keys count the sends.
        summary = dict(self.counts, transmit=self.where,
                       transmit_keys=sum(len(stream.keys) for stream in self.streams),
                       ids_sent=sum(1 for _, way, _ in rows if way == "tx"),
                       ids_sent_untimed=sum(1 for _, way, ns in rows if way == "tx" and ns is None),
                       ids_read=sum(1 for _, way, _ in rows if way == "rx"),
                       ids_read_untimed=sum(1 for _, way, ns in rows if way == "rx" and ns is None))
        with open(os.path.splitext(path)[0] + "_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
            fh.write("\n")
        return summary


def _drain(sock, stream, ledger):
    """Every transmit timestamp waiting on the socket's error queue, into the stream's keys."""
    while _queued(sock):
        try:
            _data, ancillary, _flags, _addr = _recvmsg(sock, 0, ANCILLARY,
                                                       MSG_ERRQUEUE | MSG_DONTWAIT)
        except OSError:
            # A socket error rather than a timestamp, or a socket already shut: nothing to read.
            return
        ns, key = software_ns(ancillary), transmit_key(ancillary, ledger.where)
        if ns is None or key is None:
            ledger.count("other_queue_entries")
            continue
        with ledger.lock:
            stream.keys.setdefault(key, ns)
            ledger.counts["transmit_timestamps"] += 1


class TimestampingSocket(_BASE):
    """socket.socket, with the kernel's timestamps asked for on connections to the given ports."""

    _ports = ()
    _ledger = None

    def _sbl_stream(self):
        """This connection's stream once timestamping is on, else None. Decided at the first send
        or read made once the connection is up, and only then remembered."""
        state = self.__dict__.get("_sbl_state")
        if state is not None:
            return state or None
        try:
            peer = _getpeername(self)
        except OSError:
            # Not connected yet: decide at a later call.
            return None
        if self.type != socket.SOCK_STREAM or not isinstance(peer, tuple) \
                or peer[1] not in self._ports:
            self._sbl_state = False
            return None
        ledger = self._ledger
        try:
            _setsockopt(self, ledger.flags)
        except OSError:
            ledger.count("refused")
            self._sbl_state = False
            return None
        stream = _Stream(self)
        with ledger.lock:
            ledger.streams.append(stream)
            ledger.counts["connections"] += 1
        self._sbl_state = stream
        return stream

    def send(self, data, flags=0):
        stream = self._sbl_stream()
        if stream is None:
            return _send(self, data, flags)
        _drain(self, stream, self._ledger)
        n = _send(self, data, flags)
        self._ledger.sent(stream, bytes(memoryview(data)[:n]))
        return n

    def sendall(self, data, flags=0):
        stream = self._sbl_stream()
        if stream is None:
            return _sendall(self, data, flags)
        _drain(self, stream, self._ledger)
        result = _sendall(self, data, flags)
        self._ledger.sent(stream, bytes(memoryview(data)))
        return result

    def recv(self, bufsize, flags=0):
        stream = self._sbl_stream()
        if stream is None or flags & MSG_PEEK:
            return _recv(self, bufsize, flags)
        _drain(self, stream, self._ledger)
        data, ancillary, _flags, _addr = _recvmsg(self, bufsize, ANCILLARY, flags)
        self._ledger.read(stream, data, software_ns(ancillary))
        return data

    def recv_into(self, buffer, nbytes=0, flags=0):
        stream = self._sbl_stream()
        if stream is None or flags & MSG_PEEK:
            return _recv_into(self, buffer, nbytes, flags)
        _drain(self, stream, self._ledger)
        view = memoryview(buffer)
        if nbytes:
            view = view[:nbytes]
        n, ancillary, _flags, _addr = _recvmsg_into(self, [view], ANCILLARY, flags)
        self._ledger.read(stream, bytes(view[:n]), software_ns(ancillary))
        return n

    def close(self):
        state = self.__dict__.get("_sbl_state")
        if state:
            _drain(self, state, self._ledger)
            state.closed = True
        _close(self)


def install(ports, where="software"):
    """Replace socket.socket in this process with TimestampingSocket, timestamping connections to
    `ports`, the transmit timestamp taken where `where` says. Returns the ledger to write."""
    ledger = Ledger(where)
    TimestampingSocket._ports = tuple(int(p) for p in ports)
    TimestampingSocket._ledger = ledger
    socket.socket = TimestampingSocket
    return ledger


# --- the three lines each client adds -----------------------------------------------------------

def add_arguments(ap):
    """The clients' two switches, the same in all four."""
    ap.add_argument("--so-timestamps", default=None,
                    help="F2: read the kernel's own timestamps on the broker's connections "
                         "through SO_TIMESTAMPING, and write them to this CSV")
    ap.add_argument("--so-transmit", default="software", choices=sorted(TRANSMIT),
                    help="where the kernel takes the transmit timestamp")


def port_of(address, default):
    """The port of "host:port", or `default` where the address names none."""
    host, _, port = str(address).split(",")[0].rpartition(":")
    return int(port) if host and port.isdigit() else default


def start(args, port):
    """The ledger, with the socket class replaced, when the run asked for it; else None."""
    return install([port], args.so_transmit) if args.so_timestamps else None


def finish(ledger, args):
    """Write what the ledger saw, where the run asked, and say so in the client's log."""
    if ledger is not None:
        summary = ledger.write(args.so_timestamps)
        print("OK socket timestamps: %d ids sent, %d read, %d transmit timestamps -> %s"
              % (summary["ids_sent"], summary["ids_read"], summary["transmit_timestamps"],
                 args.so_timestamps), flush=True)
