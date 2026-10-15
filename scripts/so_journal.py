#!/usr/bin/env python3
"""
so_journal.py -- what the clients' journals say about each message: when the kernel received its
acknowledgment, which of the consumer's requests delivered it, and how many packets each read
drained. Freeze 41 (plan version 44, docs/results/order_scope/DESIGN.md).

scripts/so_timestamps.py --so-journal writes, for each broker connection a client opens, every byte
it sent and read, one row per read (the stream offset after it and the kernel's receive timestamp
of the packet that completed it), and every transmit timestamp with the offset of its send call's
last byte. Nothing in the journal says which bytes were an acknowledgment or a request; the
broker's own wire format does, and it is read here.

  Kafka   every request and response is a frame prefixed by its size. A request names its API
          (0 produce, 1 fetch) and carries a correlation id, which its response repeats. A
          message's acknowledgment is the produce response whose correlation id is that of the
          produce request that carried the message, and the fetch request that delivered it is
          the one whose response carried it.
  Redis   commands and replies are RESP values, and a connection answers its commands in order.
          The acknowledgment of the XADD that carried a message is the reply with the same index
          on that connection, and the XREAD that delivered it is the command whose reply carried it.

A message is found in the bytes by its event id, as scripts/full_fix.py finds it in the captures.
The same id carried again by a later request or reply is a retry or a redelivery, and the first is
kept.

Every function here reads files or bytes and returns values; scripts/order_scope.py judges.
"""
import bisect
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import recv_wait as rw  # noqa: E402

#: Kafka's API keys for the two requests read here.
PRODUCE, FETCH = 0, 1


class Conn(object):
    """One journaled connection: its bytes each way, its reads and its transmit timestamps."""

    def __init__(self, index, local_port, peer_host, peer_port, out, inb, reads, keys):
        self.index = index
        self.local_port = local_port
        self.peer_host = peer_host
        self.peer_port = peer_port
        self.out = out
        self.inb = inb
        self.reads = reads
        self.read_ends = [end for end, _, _ in reads]
        self.keys = keys
        self.key_offsets = [key for key, _ in keys]


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load(stem):
    """{conn index: Conn} for one client's journal; {} when the run wrote none."""
    reads, keys = {}, {}
    for r in _rows(stem + "_reads.csv"):
        reads.setdefault(int(r["conn"]), []).append(
            (int(r["end"]), int(r["bytes"]), int(r["ns"]) if r["ns"] else None))
    for r in _rows(stem + "_txkeys.csv"):
        keys.setdefault(int(r["conn"]), []).append((int(r["key"]), int(r["ns"])))
    conns = {}
    for r in _rows(stem + "_streams.csv"):
        i = int(r["conn"])
        data = {}
        for way in ("out", "in"):
            path = "%s_conn%d_%s.bin" % (stem, i, way)
            with open(path, "rb") as fh:
                data[way] = fh.read()
        conns[i] = Conn(i, r["local_port"], r["peer_host"], int(r["peer_port"]), data["out"],
                        data["in"], reads.get(i, []), sorted(keys.get(i, [])))
    return conns


def rx_at(conn, offset):
    """The receive timestamp of the read that delivered the byte at `offset`; None if no read did,
    or the read came without one."""
    i = bisect.bisect_right(conn.read_ends, offset)
    return conn.reads[i][2] if i < len(conn.reads) else None


def tx_at(conn, offset):
    """The transmit timestamp of the send call that carried the byte at `offset`: the first key at
    or after it, as so_timestamps.Ledger.transmit_times reckons; None if no key covers it."""
    i = bisect.bisect_left(conn.key_offsets, offset)
    return conn.keys[i][1] if i < len(conn.keys) else None


# --- the brokers' wire formats --------------------------------------------------------------------

def kafka_frames(data):
    """[(start, end)] for each size-prefixed frame wholly inside `data`, in order. A stream cut off
    in the middle of a frame ends at the last whole one."""
    frames, pos = [], 0
    while pos + 4 <= len(data):
        size = struct.unpack(">i", data[pos:pos + 4])[0]
        if size < 0 or pos + 4 + size > len(data):
            break
        frames.append((pos, pos + 4 + size))
        pos += 4 + size
    return frames


def kafka_requests(data):
    """[(start, end, api key, correlation id)] for each request frame a client wrote."""
    return [(s, e) + struct.unpack(">h2xi", data[s + 4:s + 12])
            for s, e in kafka_frames(data) if e - s >= 12]


def kafka_responses(data):
    """{correlation id: (start, end)} for each response frame a client read; the first, if one
    repeats."""
    found = {}
    for s, e in kafka_frames(data):
        if e - s >= 8:
            found.setdefault(struct.unpack(">i", data[s + 4:s + 8])[0], (s, e))
    return found


def _resp_end(data, pos):
    """Where the RESP value that starts at `pos` ends; None if `data` holds only part of it."""
    if pos >= len(data):
        return None
    line = data.find(b"\r\n", pos)
    if line < 0:
        return None
    kind, head, after = data[pos:pos + 1], data[pos + 1:line], line + 2
    if kind in (b"+", b"-", b":"):
        return after
    if kind == b"$":
        n = int(head)
        if n < 0:
            return after
        return after + n + 2 if after + n + 2 <= len(data) else None
    if kind == b"*":
        n = int(head)
        for _ in range(max(n, 0)):
            after = _resp_end(data, after)
            if after is None:
                return None
        return after
    raise ValueError("not a RESP value at offset %d: %r" % (pos, data[pos:pos + 16]))


def resp_items(data):
    """[(start, end)] for each whole RESP value in `data`, in order."""
    items, pos = [], 0
    while pos < len(data):
        end = _resp_end(data, pos)
        if end is None:
            break
        items.append((pos, end))
        pos = end
    return items


def ids_in(data, start, end):
    """The event ids whose every byte lies in data[start:end], once each, in order."""
    seen, found = set(), []
    for m in rw.EVENT_ID.finditer(data, start, end):
        eid = m.group(0).decode("ascii")
        if eid not in seen:
            seen.add(eid)
            found.append(eid)
    return found


# --- per message ----------------------------------------------------------------------------------

def _pairs(conn, backend, out_kind):
    """[(ids the client's item carried, end of that item, end of the broker's answer)] on one
    connection, for the producer's acknowledgments (out_kind "ack") or the consumer's requests
    (out_kind "req"). For an acknowledgment the ids are in what the client wrote; for a request
    they are in what the broker answered."""
    found = []
    if backend == "kafka":
        api = PRODUCE if out_kind == "ack" else FETCH
        answers = kafka_responses(conn.inb)
        for s, e, key, corr in kafka_requests(conn.out):
            if key != api or corr not in answers:
                continue
            rs, re_ = answers[corr]
            ids = ids_in(conn.out, s, e) if out_kind == "ack" else ids_in(conn.inb, rs, re_)
            found.append((ids, e, re_))
        return found
    commands, replies = resp_items(conn.out), resp_items(conn.inb)
    for (s, e), (rs, re_) in zip(commands, replies):
        ids = ids_in(conn.out, s, e) if out_kind == "ack" else ids_in(conn.inb, rs, re_)
        found.append((ids, e, re_))
    return found


def acknowledgments(conns, backend):
    """{event id: the kernel's receive timestamp of the read that completed its acknowledgment}."""
    found = {}
    for conn in conns.values():
        for ids, _, answer_end in _pairs(conn, backend, "ack"):
            ns = rx_at(conn, answer_end - 1)
            for eid in ids:
                found.setdefault(eid, ns)
    return found


def requests(conns, backend):
    """{event id: the kernel's transmit timestamp of the consumer's request it was delivered in
    answer to}: the send call that carried that request's last byte."""
    found = {}
    for conn in conns.values():
        for ids, request_end, _ in _pairs(conn, backend, "req"):
            ns = tx_at(conn, request_end - 1)
            for eid in ids:
                found.setdefault(eid, ns)
    return found


# --- the captures, for checking the journal and counting packets ----------------------------------

def incoming_segments(pcap, peer_host, peer_port, local_host):
    """{local port: sorted [(start, end, ns)]}: each connection's payload from the broker, at the
    stream offset the client reads it at, the first time each range was seen. Offsets count from
    the connection's first data segment, which is the client's first byte read when the capture
    began before the connection did."""
    conns = {}
    for ns, linktype, frame in rw.read_pcap(pcap):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None or seg[0] != peer_host or seg[1] != local_host or seg[2] != peer_port \
                or not seg[5]:
            continue
        conns.setdefault(str(seg[3]), []).append((ns, seg[4], seg[5]))
    found = {}
    for port, packets in conns.items():
        base = packets[0][1]
        first = {}
        for ns, seq, payload in packets:
            start = (seq - base) & 0xFFFFFFFF
            first.setdefault(start, (start + len(payload), ns))
        found[port] = sorted((s, e, ns) for s, (e, ns) in first.items())
    return found


def seen_at(segments, offset):
    """The capture's timestamp of the first segment that carried the byte at `offset`; None if
    the capture holds none."""
    starts = [s for s, _, _ in segments]
    i = bisect.bisect_right(starts, offset) - 1
    if i >= 0 and segments[i][0] <= offset < segments[i][1]:
        return segments[i][2]
    return None


def packets_per_read(conn, segments):
    """[how many of the connection's incoming segments each read drained, in read order]."""
    counts, j, before = [], 0, 0
    for end in conn.read_ends:
        while j < len(segments) and segments[j][1] <= before:
            j += 1
        k = j
        n = 0
        while k < len(segments) and segments[k][0] < end:
            n += 1
            k += 1
        counts.append(n)
        before = end
    return counts


def acknowledgment_checks(conns, backend, segments):
    """[(the journal's receive timestamp, the capture's) for each acknowledgment], on connections
    the capture holds, so the journal can be held to the capture."""
    pairs = []
    for conn in conns.values():
        segs = segments.get(str(conn.local_port))
        if not segs:
            continue
        for ids, _, answer_end in _pairs(conn, backend, "ack"):
            if ids:
                journal, capture = rx_at(conn, answer_end - 1), seen_at(segs, answer_end - 1)
                if journal is not None and capture is not None:
                    pairs.append((journal, capture))
    return pairs
