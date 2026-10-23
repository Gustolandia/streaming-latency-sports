#!/usr/bin/env python3
"""
client_wire.py -- every message's kernel timestamps on the client machine, read from the client
host's own packet captures with no change to the client, each message named by the broker's own
id: Kafka's topic, partition and offset, Redis's stream and entry id.

Per message, on the client host's clock:

  t_depart  the capture time of the packet that carried the last byte of its record in the produce
            request (Kafka), or of its XADD command (Redis): the moment the message left the
            producer's host, whatever became of the packets before it;
  t_ack     when the last byte of the produce response or the XADD reply that acknowledged it
            could first be read: once that byte and every byte before it had arrived;
  t_arrive  when the last byte of its record in the fetch response, or of its entry in the
            XREADGROUP or XREAD reply, could first be read on the consumer's host;

and which of the consumer's requests delivered it. And, per consumer connection, every request in
order with its answer: the request's departure, the capture time of the packet carrying its last
byte; its answer's arrival, when the answer's last byte could first be read; the request's kind;
and the broker's ids its answer carried. From these a later reading can ask, for each message,
whether a request was waiting at the broker when the message arrived there.

A message is matched by the broker's id alone, never by what it carries. Kafka's ids come from the
frames themselves (scripts/kafka_wire.py): a produce request's record is the base offset its
produce response gives the batch, plus the record's offset delta; a fetch response's record is its
batch's offset plus its delta. Requests and answers are paired by correlation id, and each
request's API key and version are read from its own header. Redis answers a connection's commands
in order, so the XADD whose reply gave an entry its id is the command with the same index, and the
XREADGROUP or XREAD that delivered an entry is the one that reply answered. Replies are read as
RESP2 or as RESP3, whose maps, sets, pushes and attributes RESP2 has none of. The event id in the
payload (recv_wait.EVENT_ID) is read beside the broker's id, only as a check of the matching.

A byte sent more than once keeps the time it first left, and a message carried more than once, by
a retried produce request or a later fetch, keeps its first carrying, the one timed first, as the
journal's reader (scripts/so_journal.py) and the broker capture's (scripts/under_load.py) keep it.
Each direction of a connection is reassembled by recv_wait.Stream and counts its bytes from its
opening where the capture holds the SYN. A client port is taken to be one connection for the
length of a capture.

CLI:
    python scripts/client_wire.py --run FOLDER --driver IP --broker IP --receiver IP \
        --out-messages CSV --out-exchanges CSV [--port PORT]
"""
import argparse
import bisect
import csv
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kafka_wire as kw  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_journal as sj  # noqa: E402

#: TCP's SYN flag, in the flags byte thirteen bytes into the TCP header.
SYN = 0x02

#: The Redis commands that ask for messages. The consumer's connection also carries others, its
#: acknowledgments (XACK) among them, which carry none.
ASKS = ("XREAD", "XREADGROUP")

#: An entry id as Redis writes it: milliseconds, a dash, and a sequence number.
ENTRY_ID = re.compile(rb"(\d+)-(\d+)")

#: RESP's kinds of value, by their first byte. One-line values: RESP2's simple string, error and
#: integer, and RESP3's null, boolean, double and big number. Values carried as a length and that
#: many bytes: bulk strings, and RESP3's bulk errors and verbatim strings. Collections: arrays, and
#: RESP3's sets, maps, pushes and attributes, a map and an attribute holding two values an entry.
LINE_KINDS = b"+-:_#,("
BLOB_KINDS = b"$!="
COLLECTION_KINDS = b"*~%>|"
PAIRED_KINDS = b"%|"
ARRAY, MAP, BULK, PUSH, ATTRIBUTE, NULL = (ord(c) for c in "*%$>|_")

#: How each kind of broker id is written in an exchange's list of the ids its answer carried.
KAFKA_ID, REDIS_ID = "%s:%d:%d", "%s:%d-%d"

#: The columns of the two tables the command line writes. A message's row: its broker id; the
#: event ids its produce request (eid_sent) and the answer that delivered it (eid_got) carry; its
#: three times, in ns; the producer's connection (its client port) and its request there, a
#: produce request's correlation id or the XADD's index among the connection's commands; the
#: consumer's connection and the index of the delivering request among its exchanges; and where
#: its last byte lies in each connection's stream. An exchange's row: the consumer connection,
#: the request's index, its kind, its version and correlation id (Kafka only), its departure, its
#: answer's arrival (empty where none was captured), and the broker ids the answer carried.
KEY_FIELDS = {"kafka": ("topic", "partition", "offset"), "redis": ("stream", "redis_id")}
MESSAGE_FIELDS = ("eid_sent", "eid_got", "t_depart", "t_ack", "t_arrive", "producer_port",
                  "request", "consumer_port", "exchange", "sent_byte", "got_byte")
EXCHANGE_FIELDS = ("consumer_port", "exchange", "kind", "version", "corr", "t_req", "t_ans",
                   "carried", "ids")

#: What the reader counts as it goes, beside the messages: frames that did not read, record
#: batches, those a CRC failed or a fetch cut short, compressed ones, transaction markers, and the
#: produce requests and XADD commands that gave no message an id.
COUNTS = ("unreadable", "batches", "crc_failed", "cut", "compressed", "control",
          "produce_requests", "produce_unanswered", "produce_unkeyed", "xadd", "xadd_unkeyed")


# --- the captures ---------------------------------------------------------------------------------

class Sent(object):
    """When each byte of one direction of a connection first left the host: pieces of the stream,
    each the bytes one packet carried that no packet had carried before, with that packet's capture
    time. A byte sent again keeps the time it first left."""

    def __init__(self):
        self.starts, self.ends, self.times = [], [], []

    def add(self, ns, start, end):
        """Take a packet that carried the stream's bytes [start, end) at `ns`."""
        if not self.ends or start >= self.ends[-1]:
            self._put(len(self.starts), start, end, ns)
            return
        # Bytes carried again, or a gap the capture missed being filled: walk the pieces the
        # packet overlaps and put down only what lies between them.
        i = bisect.bisect_right(self.ends, start)
        while start < end:
            if i < len(self.starts) and self.starts[i] <= start:
                start = self.ends[i]
            else:
                stop = end if i == len(self.starts) else min(end, self.starts[i])
                self._put(i, start, stop, ns)
                start = stop
            i += 1

    def _put(self, i, start, end, ns):
        self.starts.insert(i, start)
        self.ends.insert(i, end)
        self.times.insert(i, ns)

    def at(self, offset):
        """When the byte at `offset` first left; None if no packet the capture holds carried it."""
        i = bisect.bisect_right(self.starts, offset) - 1
        return self.times[i] if i >= 0 and offset < self.ends[i] else None


class Conn(object):
    """One TCP connection between a client and the broker's port, as one capture saw it: what the
    client sent (`out`, with `sent`, when each of its bytes first left) and what the broker sent
    back (`inb`), each reassembled in order by recv_wait.Stream; how many of its two directions the
    capture saw open; each direction's bytes once the capture is read (`out_data`, `in_data`), and
    how many bytes at their ends no whole frame holds (`unframed`)."""

    def __init__(self, port):
        self.port = port
        self.out, self.inb, self.sent = rw.Stream(), rw.Stream(), Sent()
        self.opened = 0
        self.out_data = self.in_data = b""
        self.exchanges, self.unframed = [], 0


def connections(pcap, broker, port, client):
    """{client port: Conn} for every connection between the `client` host and the broker's `port`
    that one capture holds; {} where there is no capture. A direction whose SYN the capture holds
    counts its bytes from the one after it, so that a first data packet captured out of order is
    not taken for the start; the others count from their first data packet, as recv_wait.Stream
    does."""
    conns = {}
    if not os.path.exists(pcap):
        return conns
    for ns, linktype, frame in rw.read_pcap(pcap):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None:
            continue
        src, dst, sport, dport, seq, payload = seg
        if (src, dst, dport) == (client, broker, port):
            local, outgoing = sport, True
        elif (src, dst, sport) == (broker, client, port):
            local, outgoing = dport, False
        else:
            continue
        conn = conns.get(local)
        if conn is None:
            conn = conns[local] = Conn(local)
        stream = conn.out if outgoing else conn.inb
        if ip[(ip[0] & 0x0F) * 4 + 13] & SYN and stream.base is None:
            stream.base = (seq + 1) & 0xFFFFFFFF
            conn.opened += 1
        if payload:
            stream.add(ns, seq, payload)
            if outgoing:
                start = stream.offset(seq)
                conn.sent.add(ns, start, start + len(payload))
    for conn in conns.values():
        conn.out_data, conn.in_data = bytes(conn.out.data), bytes(conn.inb.data)
    return conns


def event_id(data, start, end):
    """The first event id wholly inside data[start:end], or None: the payload's own name for the
    message, read only to check the matching."""
    m = rw.EVENT_ID.search(data, start, end)
    return m.group(0).decode("ascii") if m else None


def _keep(found, key, value):
    """Keep a message's first carrying: the one timed earliest (value[1]), and one the capture
    timed before one it could not."""
    held = found.get(key)
    if held is None or (value[1] is not None and (held[1] is None or value[1] < held[1])):
        found[key] = value


def _read(counts, parse, *args):
    """parse(*args), or None, counted, where the frame does not read as its wire format says."""
    try:
        return parse(*args)
    except kw.WireError as exc:
        counts["unreadable"] += 1
        counts["first_unreadable"] = counts["first_unreadable"] or str(exc)
        return None


def _exchange(conn, index, kind, version, corr, request_end, answer_end, carried, written):
    """One consumer exchange's row: the request's departure, the packet carrying its last byte;
    its answer's arrival, when the answer's last byte could first be read (None where the capture
    holds no answer); and the broker's ids the answer carried."""
    return {"consumer_port": conn.port, "exchange": index, "kind": kind, "version": version,
            "corr": corr, "t_req": conn.sent.at(request_end - 1),
            "t_ans": None if answer_end is None else conn.inb.readable(answer_end - 1),
            "carried": len(carried), "ids": ";".join(written % key for key in carried)}


# --- Kafka ----------------------------------------------------------------------------------------

def _unframed(data, frames):
    return len(data) - (frames[-1][1] if frames else 0)


def kafka_exchanges(conn):
    """[(request start, request end, API key, version, correlation id, answer start, answer end)]
    for each request the client wrote on one connection, in order, its answer paired by
    correlation id; the answer's offsets are None where the capture holds none. Sets how many bytes
    at the two streams' ends no whole frame holds."""
    out, inb = conn.out_data, conn.in_data
    conn.unframed = (_unframed(out, sj.kafka_frames(out)) + _unframed(inb, sj.kafka_frames(inb)))
    answers = sj.kafka_responses(inb)
    return [(s, e, key, struct.unpack_from(">h", out, s + 6)[0], corr)
            + answers.get(corr, (None, None)) for s, e, key, corr in sj.kafka_requests(out)]


def kafka_topic_ids(conns, counts):
    """{topic id: name} from every metadata response on the given connections, for the frames that
    name topics by id alone."""
    names = {}
    for conn in conns:
        for _, _, key, version, _, rs, re_ in conn.exchanges:
            if key == kw.METADATA and rs is not None:
                names.update(_read(counts, kw.metadata_topics, conn.in_data, rs, re_, version)
                             or {})
    return names


def _name(names, topic, tid):
    """A topic's name: its own where the frame names it, else the one its id was given, else the
    id itself."""
    return topic if tid is None else names.get(tid, tid)


def _batches(counts, data, span):
    """The batches of a records field whose records stand for messages: whole, their CRC-32C
    held, and not a transaction's marker; each of the others counted."""
    got = None if span is None else _read(counts, kw.record_batches, data, span[0], span[1])
    if got is None:
        return []
    batches, cut = got
    counts["batches"] += len(batches)
    counts["cut"] += bool(cut)
    kept = []
    for b in batches:
        counts["crc_failed"] += not b.crc_ok
        counts["compressed"] += bool(b.codec)
        counts["control"] += b.control
        if b.crc_ok and not b.control:
            kept.append(b)
    return kept


def kafka_produced(conns, names, counts):
    """{(topic, partition, offset): (event id, t_depart, t_ack, client port, correlation id,
    byte)} for every record the producer's produce requests carried and the broker acknowledged
    with an offset, its first carrying kept; `byte` is where the record's last byte lies in its
    connection's stream."""
    found = {}
    for port, conn in sorted(conns.items()):
        for s, e, key, version, corr, rs, re_ in conn.exchanges:
            if key != kw.PRODUCE:
                continue
            counts["produce_requests"] += 1
            if rs is None:
                counts["produce_unanswered"] += 1
                continue
            parts = _read(counts, kw.produce_request, conn.out_data, s, e, version)
            answer = _read(counts, kw.produce_response, conn.in_data, rs, re_, version)
            if parts is None or answer is None:
                continue
            bases = dict(((_name(names, t, tid), p), base if error == 0 else None)
                         for t, tid, p, error, base in answer)
            t_ack = conn.inb.readable(re_ - 1)
            for t, tid, p, span in parts:
                topic = _name(names, t, tid)
                base = bases.get((topic, p))
                for b in _batches(counts, conn.out_data, span):
                    if base is None:
                        counts["produce_unkeyed"] += len(b.records)
                        continue
                    for delta, at, end in b.records:
                        _keep(found, (topic, p, base + delta),
                              (event_id(conn.out_data, at, end), conn.sent.at(end - 1), t_ack,
                               port, corr, end - 1))
                    # The broker writes a partition's batches one after another.
                    base += b.last_delta + 1
    return found


def kafka_consumed(conns, names, counts):
    """({(topic, partition, offset): (event id, t_arrive, client port, exchange, byte)} for every
    record the consumer's fetch responses carried, its first carrying kept, and [one row per
    exchange] for every request on every consumer connection, in order)."""
    found, rows = {}, []
    for port, conn in sorted(conns.items()):
        data = conn.in_data
        for index, (_, e, key, version, corr, rs, re_) in enumerate(conn.exchanges):
            carried = []
            if key == kw.FETCH and rs is not None:
                for t, tid, p, _, _, span in (_read(counts, kw.fetch_response, data, rs, re_,
                                                    version) or []):
                    topic = _name(names, t, tid)
                    for b in _batches(counts, data, span):
                        for delta, at, end in b.records:
                            carried.append((topic, p, b.base_offset + delta))
                            _keep(found, carried[-1], (event_id(data, at, end),
                                                       conn.inb.readable(end - 1), port, index,
                                                       end - 1))
            rows.append(_exchange(conn, index, kw.api_name(key), version, corr, e, re_, carried,
                                  KAFKA_ID))
    return found, rows


# --- Redis ----------------------------------------------------------------------------------------

def _length(head, pos):
    try:
        return int(head)
    except ValueError:
        raise kw.WireError("no length at offset %d: %r" % (pos, head))


def resp_value(data, pos):
    """(kind, start, end, value) for the RESP2 or RESP3 value at `pos`, `kind` its first byte and
    `end` past its last; None where `data` holds only part of it. `value` is a string's or an
    error's bytes, a one-line value's line, None for a null, and a collection's list of values, a
    map's keys and values alternating. An attribute, RESP3's note on the value after it, is read
    past, and that value given as starting where the attribute did."""
    line = data.find(b"\r\n", pos)
    if line < 0:
        return None
    kind, head, after = data[pos], data[pos + 1:line], line + 2
    if kind in LINE_KINDS:
        return kind, pos, after, None if kind == NULL else head
    if kind not in BLOB_KINDS and kind not in COLLECTION_KINDS:
        raise kw.WireError("not a RESP value at offset %d: %r" % (pos, data[pos:pos + 16]))
    n = _length(head, pos)
    if n < 0:
        return kind, pos, after, None
    if kind in BLOB_KINDS:
        end = after + n + 2
        return None if end > len(data) else (kind, pos, end, data[after:after + n])
    items = []
    for _ in range(2 * n if kind in PAIRED_KINDS else n):
        got = resp_value(data, after)
        if got is None:
            return None
        items.append(got)
        after = got[2]
    if kind == ATTRIBUTE:
        got = resp_value(data, after)
        return None if got is None else (got[0], pos, got[2], got[3])
    return kind, pos, after, items


def resp_items(data):
    """([(kind, start, end, value)] for each whole RESP value in `data`, in order, and where the
    reading stopped: at the end, at a value cut short, or at bytes that are not RESP."""
    items, pos = [], 0
    while pos < len(data):
        try:
            got = resp_value(data, pos)
        except kw.WireError:
            break
        if got is None:
            break
        items.append(got)
        pos = got[2]
    return items, pos


def _text(raw):
    return raw.decode("utf-8", "replace")


def _words(node):
    """A client's command as its words: the bulk strings of the array it sends."""
    if node[0] != ARRAY or not node[3]:
        return []
    return [v[3] or b"" for v in node[3] if v[0] == BULK]


def entry_id(node):
    """(milliseconds, sequence) of the entry id a bulk string holds; None for any other value."""
    m = ENTRY_ID.fullmatch(node[3]) if node[0] == BULK and node[3] is not None else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def stream_entries(node):
    """[(stream, (milliseconds, sequence), entry)] for each entry an XREAD or XREADGROUP reply
    carries: in RESP2 an array of [stream, entries] pairs, in RESP3 a map from each stream to its
    entries; each entry an array of its id and its fields. A null reply, sent when the wait timed
    out, carries none, and so does an error."""
    kind, value = node[0], node[3]
    if kind == MAP and value:
        pairs = list(zip(value[0::2], value[1::2]))
    elif kind == ARRAY and value:
        pairs = [tuple(v[3]) for v in value if v[0] == ARRAY and v[3] and len(v[3]) == 2]
    else:
        return []
    found = []
    for name, entries in pairs:
        if name[0] != BULK or name[3] is None or entries[0] != ARRAY:
            continue
        for entry in entries[3] or []:
            got = entry_id(entry[3][0]) if entry[0] == ARRAY and entry[3] else None
            if got is not None:
                found.append((_text(name[3]), got, entry))
    return found


def _resp_streams(conn):
    """(the client's commands, the broker's replies) on one connection, push messages left out of
    the replies, since they answer no command. Sets how many bytes at the two streams' ends no
    whole value holds."""
    commands, stop = resp_items(conn.out_data)
    replies, stop_in = resp_items(conn.in_data)
    conn.unframed = len(conn.out_data) - stop + len(conn.in_data) - stop_in
    return commands, [r for r in replies if r[0] != PUSH]


def redis_produced(conns, counts):
    """{(stream, milliseconds, sequence): (event id, t_depart, t_ack, client port, command index,
    byte)} for every XADD the producer sent whose reply gave its entry an id, its first carrying
    kept."""
    found = {}
    for port, conn in sorted(conns.items()):
        commands, replies = _resp_streams(conn)
        for index, command in enumerate(commands):
            words = _words(command)
            if len(words) < 2 or words[0].upper() != b"XADD":
                continue
            counts["xadd"] += 1
            reply = replies[index] if index < len(replies) else None
            got = None if reply is None else entry_id(reply)
            if got is None:
                counts["xadd_unkeyed"] += 1
                continue
            end = command[2]
            _keep(found, (_text(words[1]),) + got,
                  (event_id(conn.out_data, command[1], end), conn.sent.at(end - 1),
                   conn.inb.readable(reply[2] - 1), port, index, end - 1))
    return found


def redis_consumed(conns, counts):
    """({(stream, milliseconds, sequence): (event id, t_arrive, client port, exchange, byte)} for
    every entry the consumer's XREADGROUP and XREAD replies carried, its first carrying kept, and
    [one row per exchange] for every command on every consumer connection, in order)."""
    found, rows = {}, []
    for port, conn in sorted(conns.items()):
        commands, replies = _resp_streams(conn)
        for index, command in enumerate(commands):
            words = _words(command)
            kind = _text(words[0]).upper() if words else ""
            reply = replies[index] if index < len(replies) else None
            carried = []
            if kind in ASKS and reply is not None:
                for stream, got, entry in stream_entries(reply):
                    carried.append((stream,) + got)
                    _keep(found, carried[-1], (event_id(conn.in_data, entry[1], entry[2]),
                                               conn.inb.readable(entry[2] - 1), port, index,
                                               entry[2] - 1))
            rows.append(_exchange(conn, index, kind, None, None, command[2],
                                  None if reply is None else reply[2], carried, REDIS_ID))
    return found, rows


# --- one run --------------------------------------------------------------------------------------

def _key_row(backend, key):
    if backend == "kafka":
        return {"topic": key[0], "partition": key[1], "offset": key[2]}
    return {"stream": key[0], "redis_id": "%d-%d" % (key[1], key[2])}


def message_rows(backend, produced, consumed):
    """One row per message either side carried, in the broker's order: its id, the event ids the
    two sides' payloads name, its three times, which request carried it each way, and where its
    last byte lies in each connection's stream."""
    rows = []
    for key in sorted(set(produced) | set(consumed)):
        sent, got = produced.get(key, (None,) * 6), consumed.get(key, (None,) * 5)
        row = _key_row(backend, key)
        row.update(zip(("eid_sent", "t_depart", "t_ack", "producer_port", "request",
                        "sent_byte"), sent))
        row.update(zip(("eid_got", "t_arrive", "consumer_port", "exchange", "got_byte"), got))
        rows.append(row)
    return rows


def summarize(backend, sending, getting, produced, consumed, exchanges, counts):
    """What the reading found and what it could not read, in counts."""
    every = list(sending.values()) + list(getting.values())
    both = set(produced) & set(consumed)
    named = [k for k in both if None not in (produced[k][0], consumed[k][0])]
    out = {"backend": backend, "producer_connections": len(sending),
           "consumer_connections": len(getting),
           "unopened": sum(1 for c in every if c.opened < 2),
           "holes": sum(bool(c.out.pending) + bool(c.inb.pending) for c in every),
           "unframed": sum(c.unframed for c in every),
           "produced": len(produced), "consumed": len(consumed), "matched": len(both),
           "sent_only": len(set(produced) - both), "got_only": len(set(consumed) - both),
           "ids_unread": len(both) - len(named),
           "ids_differ": sum(1 for k in named if produced[k][0] != consumed[k][0]),
           "exchanges": len(exchanges),
           "answered": sum(1 for r in exchanges if r["t_ans"] is not None),
           "carried": sum(r["carried"] for r in exchanges)}
    out.update(counts)
    return out


def match(backend, sending, getting):
    """(message rows, consumer exchange rows, summary) from the producer's connections (`sending`)
    and the consumer's (`getting`)."""
    counts = dict.fromkeys(COUNTS, 0)
    counts["first_unreadable"] = ""
    if backend == "kafka":
        every = list(sending.values()) + list(getting.values())
        for conn in every:
            conn.exchanges = kafka_exchanges(conn)
        names = kafka_topic_ids(every, counts)
        produced = kafka_produced(sending, names, counts)
        consumed, exchanges = kafka_consumed(getting, names, counts)
    else:
        produced = redis_produced(sending, counts)
        consumed, exchanges = redis_consumed(getting, counts)
    return (message_rows(backend, produced, consumed), exchanges,
            summarize(backend, sending, getting, produced, consumed, exchanges, counts))


def read_run(run_dir, driver, broker, receiver, port=None):
    """(message rows, consumer exchange rows, summary) for one run folder, from its two client
    captures: sender_full.pcap on the producer's host, where its connections come from `driver`,
    and receiver_full.pcap on the consumer's, where they come from `receiver`. The broker listens
    on `port`, by default its port in order_scope.PORTS."""
    backend = osc.setup_of(run_dir)[1].get("backend")
    if backend not in osc.PORTS:
        raise ValueError("%s names no broker read here: %r" % (run_dir, backend))
    port = port or osc.PORTS[backend]
    sending = connections(os.path.join(run_dir, "sender_full.pcap"), broker, port, driver)
    getting = connections(os.path.join(run_dir, "receiver_full.pcap"), broker, port, receiver)
    return match(backend, sending, getting)


# --- the command line -----------------------------------------------------------------------------

def write_csv(path, rows, fields):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", required=True)
    for name in ("--driver", "--broker", "--receiver", "--out-messages", "--out-exchanges"):
        ap.add_argument(name, required=True)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)
    messages, exchanges, summary = read_run(args.run, args.driver, args.broker, args.receiver,
                                            args.port)
    backend = summary["backend"]
    write_csv(args.out_messages, messages, KEY_FIELDS[backend] + MESSAGE_FIELDS)
    write_csv(args.out_exchanges, exchanges, EXCHANGE_FIELDS)
    print("%d messages by the broker's ids: %d both ways, %d only sent, %d only received; event "
          "ids differ for %d; %d of %d consumer requests answered; %d frames unreadable"
          % (len(messages), summary["matched"], summary["sent_only"], summary["got_only"],
             summary["ids_differ"], summary["answered"], summary["exchanges"],
             summary["unreadable"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
