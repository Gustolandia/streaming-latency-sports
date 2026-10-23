#!/usr/bin/env python3
"""
client_wire.py -- every message's kernel timestamps on the client machine, read from the client
host's own packet captures with no change to the client, each message named by the broker's own
id: Kafka's topic, partition and offset, Redis's stream and entry id, NATS JetStream's stream and
stream sequence, and, for an AMQP classic queue, which has no id of the broker's that both ends
see, the queue and the message-id property the producer sets.

Per message, on the client host's clock:

  t_depart  the capture time of the packet that carried the last byte of its record in the produce
            request (Kafka), of its XADD command (Redis), of its PUB frame (NATS) or of its
            publish's last frame (AMQP): the moment the message left the producer's host, whatever
            became of the packets before it;
  t_ack     when the last byte of the produce response, the XADD reply, the publish
            acknowledgment (NATS) or the publisher confirm, multiple ones included (AMQP), that
            acknowledged it could first be read: once that byte and every byte before it had
            arrived;
  t_arrive  when the last byte of its record in the fetch response, of its entry in the
            XREADGROUP or XREAD reply, of its delivered MSG frame (NATS) or of its delivery's last
            frame (AMQP) could first be read on the consumer's host;

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

NATS (scripts/nats_wire.py). Each publish names a reply subject of its own, and JetStream answers
there with the stream and the stream sequence it stored the message at, in whatever order; so a
publish is matched to its acknowledgment by that subject. A pull request too names a reply subject
of its own, and a status that ends it (408 when it expired) comes back to that subject. A delivered
message names its stream sequence in its own reply subject, $JS.ACK...., and the request it answered
by its subject where the server writes the request's reply subject there; where it writes the
stream's subject instead, the message went to the oldest request still waiting, which is the
server's own order for requests of one message each. A client's PING is answered by the next PONG,
and any other JetStream request by the message that comes back to its reply subject.

AMQP 0-9-1 (scripts/amqp_frames.py). A channel in confirm mode numbers its publishes from 1, and
the broker's basic.ack repeats a publish's number, or with multiple set covers every number up to
it, so each publish's confirm is the first that covers its number. RabbitMQ pushes a consumer no
more unacknowledged deliveries than its prefetch count, so the consumer's request for a message is
the acknowledgment that freed the credit it went out on, amqp_frames.released(); a delivery sent
on the consumer's first credit went out on its basic.consume. A synchronous method is answered by
the next "-ok" of its name on its channel.

The same walks read two other records of the same bytes. On the broker's own capture
(broker_times), a byte a client sent is timed by when the broker could first read it, and a byte
the broker sent by when it and every byte before it had been captured, as scripts/under_load.py
times them; there each message's P_in, A_out, F_in and R_out are given by its broker id. And on
the clients' own journals (socket_run; scripts/so_timestamps.py --so-journal), a byte is timed by
the client's own sockets: the transmit timestamp of the send call that carried it, the receive
timestamp of the read that delivered it.

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
import collections
import csv
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import amqp_frames as af  # noqa: E402
import kafka_wire as kw  # noqa: E402
import nats_wire as nw  # noqa: E402
import order_scope as osc  # noqa: E402
import recv_wait as rw  # noqa: E402
import so_journal as sj  # noqa: E402

#: TCP's SYN and RST flags, in the flags byte thirteen bytes into the TCP header, and where its
#: advertised window lies.
SYN, RST = 0x02, 0x04
WINDOW_AT = 14

#: The credit a basic.consume grants where its channel's prefetch count is 0, which RabbitMQ takes
#: as no limit: more than any run delivers.
UNLIMITED = 10 ** 12

#: Where each broker listens: Kafka's and Redis's ports as order_scope names them, and NATS's and
#: AMQP's own.
PORTS = dict(osc.PORTS, nats=nw.PORT, rabbitmq=5672)

#: The Redis commands that ask for messages. The consumer's connection also carries others, its
#: acknowledgments (XACK) among them, which carry none.
ASKS = ("XREAD", "XREADGROUP")

#: The name of a JetStream pull request among a connection's exchanges; the acknowledgments that
#: free an AMQP consumer's credit, each named by its method. With ASKS and Kafka's fetch, these are
#: the requests that can wait at the broker for a message. Every other exchange asks for none.
PULL = "CONSUMER.MSG.NEXT"
CREDITS = tuple(sorted(af.ACKNOWLEDGEMENTS))
WAITING_KINDS = frozenset(ASKS + (kw.api_name(kw.FETCH), PULL) + CREDITS)

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

#: The subjects JetStream's requests go to, and the prefix of a delivered message's reply subject.
JS_API = "$JS.API."
NEXT = JS_API + PULL + "."
JS_ACK = "$JS.ACK."
#: The NATS frames that publish, and those that deliver.
PUBLISHES = ("PUB", "HPUB")
DELIVERIES = ("MSG", "HMSG")

#: The AMQP methods a client sends that the broker answers with "<name>-ok" on the same channel.
SYNCHRONOUS = frozenset(name[:-3] for name in af.NAMES.values() if name.endswith("-ok"))

#: How each kind of broker id is written in an exchange's list of the ids its answer carried.
KAFKA_ID, REDIS_ID, NATS_ID, AMQP_ID = "%s:%d:%d", "%s:%d-%d", "%s:%d", "%s:%s"

#: The columns of the two tables the command line writes. A message's row: its broker id; the
#: event ids its produce request (eid_sent) and the answer that delivered it (eid_got) carry; its
#: three times, in ns; the producer's connection (its client port) and its request there, a
#: produce request's correlation id, the XADD's index among the connection's commands, the
#: publish's own number (NATS) or its confirm number (AMQP); the consumer's connection and the
#: index of the delivering request among its exchanges; and where its last byte lies in each
#: connection's stream. An exchange's row: the consumer connection, the request's index, its kind,
#: its version and correlation id (Kafka only), its departure, its answer's arrival (empty where
#: none was captured), and the broker ids the answer carried. In memory an exchange's row also
#: holds the credit its request granted the broker as it left (`grant`: one request for messages,
#: a pull request's batch, the deliveries an AMQP acknowledgment covers, a basic.consume's prefetch
#: count) and each answering frame's first byte's arrival with the credit it used (`uses`); and,
#: read with read_detail, a message's row holds when its acknowledgment's first byte arrived
#: (t_ack_first).
KEY_FIELDS = {"kafka": ("topic", "partition", "offset"), "redis": ("stream", "redis_id"),
              "nats": ("stream", "stream_seq"), "rabbitmq": ("queue", "message_id")}
MESSAGE_FIELDS = ("eid_sent", "eid_got", "t_depart", "t_ack", "t_arrive", "producer_port",
                  "request", "consumer_port", "exchange", "sent_byte", "got_byte")
EXCHANGE_FIELDS = ("consumer_port", "exchange", "kind", "version", "corr", "t_req", "t_ans",
                   "carried", "ids")

#: What the reader counts as it goes, beside the messages: frames that did not read, record
#: batches, those a CRC failed or a fetch cut short, compressed ones, transaction markers, and the
#: produce requests and XADD commands that gave no message an id. NATS and AMQP add their own:
#: publishes, those no acknowledgment answered and those refused; for NATS the pull requests a
#: status ended and the deliveries no request was outstanding for; for AMQP the publishes and
#: deliveries without a message-id, and the deliveries whose freeing acknowledgment the stream
#: does not hold.
COUNTS = ("unreadable", "batches", "crc_failed", "cut", "compressed", "control",
          "produce_requests", "produce_unanswered", "produce_unkeyed", "xadd", "xadd_unkeyed")
EXTRA_COUNTS = {"nats": ("publishes", "publishes_unanswered", "publishes_refused", "statuses",
                         "unrequested"),
                "rabbitmq": ("publishes", "publishes_unanswered", "publishes_refused",
                             "unkeyed", "unreleased")}


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

    def covers(self, start, end):
        """Whether a packet the capture holds carried any of the bytes [start, end) already."""
        i = bisect.bisect_right(self.starts, start) - 1
        if i >= 0 and self.ends[i] > start:
            return True
        return i + 1 < len(self.starts) and self.starts[i + 1] < end


class Conn(object):
    """One TCP connection between a client and the broker's port, as one capture saw it: what the
    client sent (`out`, with `sent`, when each of its bytes first left) and what the broker sent
    back (`inb`, with `got`, when each of its bytes was first captured), each reassembled in order
    by recv_wait.Stream; how many of its two directions the capture saw open; each direction's bytes
    once the capture is read (`out_data`, `in_data`), and how many bytes at their ends no whole
    frame holds (`unframed`). Beside them, what says whether the network carried it cleanly, each
    as capture times: of every packet either way (`packets`), of each packet that carried bytes the
    capture had already seen go that way (`resent`, tail-loss probes among them), and of each that
    advertised a zero window (`zero_windows`). `at_broker` says the capture is the broker's own."""

    def __init__(self, port, at_broker=False):
        self.port = port
        self.at_broker = at_broker
        self.out, self.inb, self.sent, self.got = rw.Stream(), rw.Stream(), Sent(), Sent()
        self.opened = 0
        self.out_data = self.in_data = b""
        self.exchanges, self.unframed = [], 0
        self.packets, self.resent, self.zero_windows = [], [], []

    def left(self, offset):
        """The time of the byte the client sent at `offset`: on the client's host, when it first
        left; on the broker's, when the broker could first read it, it and every byte before it
        having arrived. None where the capture holds no such time."""
        return self.out.readable(offset) if self.at_broker else self.sent.at(offset)

    def came(self, offset):
        """The time of the byte the broker sent at `offset`: when it and every byte before it had
        been captured, on the client's host the moment it could first be read, and on the broker's
        its departure as scripts/under_load.py times it."""
        return self.inb.readable(offset)


def connections_of(pcap, broker, port, clients, at_broker=False):
    """{client host: {client port: Conn}} for every connection between each of the `clients` hosts
    and the broker's `port` that one capture holds, read in one pass; each host's {} where there is
    no capture or it holds none. A direction whose SYN the capture holds counts its bytes from the
    one after it, so that a first data packet captured out of order is not taken for the start;
    the others count from their first data packet, as recv_wait.Stream does."""
    found = dict((client, {}) for client in clients)
    if not os.path.exists(pcap):
        return found
    for ns, linktype, frame in rw.read_pcap(pcap):
        ip = rw.ip_payload(linktype, frame)
        seg = None if ip is None else rw.tcp_segment(ip)
        if seg is None:
            continue
        src, dst, sport, dport, seq, payload = seg
        if dst == broker and dport == port and src in found:
            conns, local, outgoing = found[src], sport, True
        elif src == broker and sport == port and dst in found:
            conns, local, outgoing = found[dst], dport, False
        else:
            continue
        conn = conns.get(local)
        if conn is None:
            conn = conns[local] = Conn(local, at_broker)
        stream = conn.out if outgoing else conn.inb
        head = (ip[0] & 0x0F) * 4
        flags = ip[head + 13]
        if flags & SYN and stream.base is None:
            stream.base = (seq + 1) & 0xFFFFFFFF
            conn.opened += 1
        conn.packets.append(ns)
        if not flags & (SYN | RST) and not struct.unpack_from(">H", ip, head + WINDOW_AT)[0]:
            conn.zero_windows.append(ns)
        if payload:
            stream.add(ns, seq, payload)
            start = stream.offset(seq)
            seen = conn.sent if outgoing else conn.got
            if seen.covers(start, start + len(payload)):
                conn.resent.append(ns)
            seen.add(ns, start, start + len(payload))
    for conns in found.values():
        for conn in conns.values():
            conn.out_data, conn.in_data = bytes(conn.out.data), bytes(conn.inb.data)
    return found


def connections(pcap, broker, port, client):
    """{client port: Conn} for every connection between the `client` host and the broker's `port`
    that one capture holds; {} where there is no capture."""
    return connections_of(pcap, broker, port, (client,))[client]


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


def _unread(counts, exc):
    """Count a frame that does not read as its wire format says, the first one's reason kept."""
    counts["unreadable"] += 1
    counts["first_unreadable"] = counts["first_unreadable"] or str(exc)


def _read(counts, parse, *args):
    """parse(*args), or None, counted, where the frame does not read as its wire format says."""
    try:
        return parse(*args)
    except kw.WireError as exc:
        _unread(counts, exc)
        return None


def _exchange(conn, index, kind, version, corr, request_end, answer_end, carried, written,
              grant=0, uses=()):
    """One consumer exchange's row: the request's departure, the packet carrying its last byte;
    its answer's arrival, when the answer's last byte could first be read (None where the capture
    holds no answer); the broker's ids the answer carried; the credit the request granted; and,
    for each frame that answered it, given as (its first byte's offset, the credit it used), when
    that first byte arrived."""
    return {"consumer_port": conn.port, "exchange": index, "kind": kind, "version": version,
            "corr": corr, "t_req": conn.left(request_end - 1),
            "t_ans": None if answer_end is None else conn.came(answer_end - 1),
            "carried": len(carried), "ids": ";".join(written % key for key in carried),
            "grant": grant, "uses": [(conn.came(at), used) for at, used in uses]}


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
    byte, whole, t_ack_first)} for every record the producer's produce requests carried and the
    broker acknowledged with an offset, its first carrying kept; `byte` is where the record's last
    byte lies in its connection's stream, `whole` where the produce request carrying it ends, and
    t_ack_first when the produce response's first byte arrived."""
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
            t_ack, t_first = conn.came(re_ - 1), conn.came(rs)
            for t, tid, p, span in parts:
                topic = _name(names, t, tid)
                base = bases.get((topic, p))
                for b in _batches(counts, conn.out_data, span):
                    if base is None:
                        counts["produce_unkeyed"] += len(b.records)
                        continue
                    for delta, at, end in b.records:
                        _keep(found, (topic, p, base + delta),
                              (event_id(conn.out_data, at, end), conn.left(end - 1), t_ack,
                               port, corr, end - 1, e, t_first))
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
                                                       conn.came(end - 1), port, index,
                                                       end - 1))
            fetch = key == kw.FETCH
            rows.append(_exchange(conn, index, kw.api_name(key), version, corr, e, re_, carried,
                                  KAFKA_ID, int(fetch), [(rs, 1)] if fetch and rs is not None
                                  else []))
    return found, rows


def _kafka(sending, getting, counts):
    every = list(sending.values()) + list(getting.values())
    for conn in every:
        conn.exchanges = kafka_exchanges(conn)
    names = kafka_topic_ids(every, counts)
    return (kafka_produced(sending, names, counts),) + kafka_consumed(getting, names, counts)


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
    byte, whole, t_ack_first)} for every XADD the producer sent whose reply gave its entry an id,
    its first carrying kept; an XADD's command ends where its entry does."""
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
                  (event_id(conn.out_data, command[1], end), conn.left(end - 1),
                   conn.came(reply[2] - 1), port, index, end - 1, end, conn.came(reply[1])))
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
                                               conn.came(entry[2] - 1), port, index,
                                               entry[2] - 1))
            asks = kind in ASKS
            rows.append(_exchange(conn, index, kind, None, None, command[2],
                                  None if reply is None else reply[2], carried, REDIS_ID,
                                  int(asks), [(reply[1], 1)] if asks and reply is not None
                                  else []))
    return found, rows


def _redis(sending, getting, counts):
    return (redis_produced(sending, counts),) + redis_consumed(getting, counts)


# --- NATS -----------------------------------------------------------------------------------------

def nats_frames(data, counts):
    """([(start, end, Frame)] for each whole frame of one direction of a NATS connection, in
    order, by scripts/nats_wire.py's own splitter and reader, and where the walk stopped: at the
    end, at a frame cut short, or at bytes that are not the protocol, which are counted. A walk
    that has lost its place cannot be trusted to find where the next frame begins, so it stops."""
    frames, pos = [], 0
    while pos < len(data):
        try:
            size = nw.frame_length(data, pos)
            if size is None:
                break
            frame = nw.parse_frame(data[pos:pos + size])
        except nw.ProtocolError as exc:
            _unread(counts, exc)
            break
        frames.append((pos, pos + size, frame))
        pos += size
    return frames, pos


def _nats_streams(conn, counts):
    """(the client's frames, the broker's frames) on one connection; sets how many bytes at the
    two streams' ends no whole frame holds."""
    out, stop = nats_frames(conn.out_data, counts)
    inb, stop_in = nats_frames(conn.in_data, counts)
    conn.unframed = len(conn.out_data) - stop + len(conn.in_data) - stop_in
    return out, inb


def _number(subject):
    """A reply subject's last token as a number, the client's own count of its requests; None
    where it is not one."""
    token = subject.rsplit(".", 1)[-1]
    return int(token) if token.isdigit() else None


def _status(frame):
    """A NATS frame's status, (code, description); None for a message, and for a header block
    that does not read, which no status can be."""
    try:
        return nw.status(frame)
    except nw.ProtocolError:
        return None


def nats_produced(conns, counts):
    """{(stream, stream sequence): (event id, t_depart, t_ack, client port, the publish's number,
    byte, whole, t_ack_first)} for every publish JetStream acknowledged with a stream sequence: a
    PUB or HPUB
    with a reply subject of its own to any subject outside JetStream's API, matched to the
    acknowledgment that came back to that reply subject, whatever the order the answers came in;
    its first carrying kept. A status in the acknowledgment's place (503: no stream took the
    subject) or an error refuses the publish."""
    found = {}
    for port, conn in sorted(conns.items()):
        out, inb = _nats_streams(conn, counts)
        waiting = {}
        for s, e, f in out:
            if f.op in PUBLISHES and f.reply and not f.subject.startswith(JS_API):
                counts["publishes"] += 1
                waiting.setdefault(f.reply, (s, e))
        for s, e, f in inb:
            sent = waiting.pop(f.subject, None) if f.op in DELIVERIES else None
            if sent is None:
                continue
            got = None
            if _status(f) is None:
                try:
                    got = nw.pub_ack(f.payload)
                except (nw.JetStreamError, nw.ProtocolError):
                    pass
            if got is None:
                counts["publishes_refused"] += 1
                continue
            _keep(found, got[:2], (event_id(conn.out_data, sent[0], sent[1]),
                                   conn.left(sent[1] - 1), conn.came(e - 1), port,
                                   _number(f.subject), sent[1] - 1, sent[1], conn.came(s)))
        counts["publishes_unanswered"] += len(waiting)
    return found


def _api_kind(subject):
    """The kind of a JetStream request, by its subject: a pull request, or the two words after
    $JS.API that name any other, STREAM.CREATE or CONSUMER.CREATE among them."""
    if subject.startswith(NEXT):
        return PULL
    return ".".join(subject[len(JS_API):].split(".")[:2])


def _batch(payload):
    """How many messages a pull request asks for: its JSON's batch, one where it names none."""
    try:
        asked = json.loads(payload).get("batch", 1)
        return asked if isinstance(asked, int) and asked > 0 else 1
    except (AttributeError, ValueError):
        return 1


class Waiting(object):
    """A connection's pull requests as nats-server keeps them waiting (server/consumer.go's
    waitQueue): each joins at the back once it has reached the server, here once its time is no
    later than the delivery's, in the order it was sent; each delivery goes to the request at the
    front, which leaves once it has had the messages its batch asked for, and otherwise, with
    others waiting, goes to the back. So requests of one message each are served oldest first,
    and nats.go's requests of many are served in turn. A request whose time the capture lacks is
    taken to have arrived, and where none has, the next one sent is taken to have."""

    def __init__(self, pulls, times, batches):
        self.pulls, self.times = list(pulls), times
        self.left = dict((i, batches[i]) for i in self.pulls)
        self.queue, self.at = collections.deque(), 0

    def _admit(self):
        i = self.pulls[self.at]
        self.at += 1
        if self.left[i] > 0:
            self.queue.append(i)

    def take(self, t, named=None):
        """The request a delivery at `t` went to: `named` where it names one still owed a message,
        else the one at the front; None where no request is outstanding."""
        if named is not None and self.left.get(named, 0) > 0:
            i = named
        else:
            while self.at < len(self.pulls) and (
                    None in (t, self.times[self.pulls[self.at]])
                    or self.times[self.pulls[self.at]] <= t):
                self._admit()
            while not self.queue and self.at < len(self.pulls):
                self._admit()
            if not self.queue:
                return None
            i = self.queue[0]
        self.left[i] -= 1
        if i in self.queue and (not self.left[i] or (self.queue[0] == i and len(self.queue) > 1)):
            self.queue.remove(i)
            if self.left[i]:
                self.queue.append(i)
        return i

    def end(self, i):
        """A status ended request i, whatever it was still owed."""
        self.left[i] = 0
        if i in self.queue:
            self.queue.remove(i)


def nats_consumed(conns, counts):
    """({(stream, stream sequence): (event id, t_arrive, client port, exchange, byte)} for every
    message delivered on the consumer's connections, its first carrying kept, and [one row per
    exchange] for every request on each of them, in order: its pull requests, its other JetStream
    requests and its PINGs. An exchange's answer is the first frame that answered it.

    A delivered message is a MSG or HMSG with a $JS.ACK reply subject and no status. It answered
    the pull request whose reply subject is its subject, where that is one still owed a message;
    otherwise the one nats-server's waiting queue had at its front (Waiting). A status ends the
    first request still owed a message among those whose reply subject it names, all but an idle
    heartbeat (100), which ends nothing. A pull request grants the broker its batch; each delivery
    uses one of it, and a status that ends it the rest."""
    found, rows = {}, []
    for port, conn in sorted(conns.items()):
        out, inb = _nats_streams(conn, counts)
        requests, batches = [], {}
        for _, e, f in out:
            if f.op in PUBLISHES and f.reply and f.subject.startswith(JS_API):
                if f.subject.startswith(NEXT):
                    batches[len(requests)] = _batch(f.payload)
                requests.append((e, _api_kind(f.subject), f.reply))
            elif f.op == "PING":
                requests.append((e, "PING", None))
        named = {}
        for i, (_, kind, reply) in enumerate(requests):
            named.setdefault(reply, []).append(i)
        waiting = Waiting(sorted(batches), dict((i, conn.left(requests[i][0] - 1))
                                                 for i in batches), batches)
        pings = collections.deque(named.get(None, []))
        answered, carried, uses = {}, {}, {}
        for s, e, f in inb:
            if f.op == "PONG" and pings:
                answered[pings.popleft()] = e
            if f.op not in DELIVERIES:
                continue
            code = _status(f)
            mine = named.get(f.subject, [])
            if (f.reply or "").startswith(JS_ACK) and code is None:
                i = waiting.take(conn.came(e - 1),
                                 mine[0] if len(mine) == 1 and mine[0] in batches else None)
                if i is None:
                    counts["unrequested"] += 1
                    continue
                answered.setdefault(i, e)
                uses.setdefault(i, []).append((s, 1))
                try:
                    meta = nw.ack_metadata(f.reply)
                except nw.ProtocolError as exc:
                    _unread(counts, exc)
                    continue
                key = (meta.stream, meta.stream_seq)
                carried.setdefault(i, []).append(key)
                _keep(found, key, (event_id(conn.in_data, s, e), conn.came(e - 1), port, i,
                                   e - 1))
                continue
            owed = [i for i in mine if i not in batches or waiting.left[i] > 0]
            if not owed:
                continue
            i = owed[0]
            if i in batches:
                if code is None or code[0] == nw.HEARTBEAT:
                    continue
                counts["statuses"] += 1
                uses.setdefault(i, []).append((s, waiting.left[i]))
                waiting.end(i)
            answered.setdefault(i, e)
        for i, (end, kind, _) in enumerate(requests):
            rows.append(_exchange(conn, i, kind, None, None, end, answered.get(i),
                                  carried.get(i, []), NATS_ID, batches.get(i, 0),
                                  uses.get(i, [])))
    return found, rows


def _nats(sending, getting, counts):
    return (nats_produced(sending, counts),) + nats_consumed(getting, counts)


# --- AMQP -----------------------------------------------------------------------------------------

def amqp_items(data, counts):
    """(each whole frame of one direction of an AMQP connection, decoded, in order, and where the
    reading stopped): at the end, at a frame cut short, or at bytes that are not AMQP, which are
    counted."""
    items = []
    try:
        for item in af.read(data):
            items.append(item)
    except ValueError as exc:
        _unread(counts, exc)
    start = len(af.PROTOCOL_HEADER) if data.startswith(af.PROTOCOL_HEADER) else 0
    return items, items[-1].end if items else start


def _amqp_streams(conn, counts):
    """(the client's frames, the broker's frames) on one connection; sets how many bytes at the
    two streams' ends no whole frame holds."""
    out, stop = amqp_items(conn.out_data, counts)
    inb, stop_in = amqp_items(conn.in_data, counts)
    conn.unframed = len(conn.out_data) - stop + len(conn.in_data) - stop_in
    return out, inb


def _contents(counts, pick, items):
    """pick(items), amqp_frames.publishes or deliveries; {} where a content's frames do not
    follow one another as the protocol says, counted."""
    try:
        return pick(items)
    except ValueError as exc:
        _unread(counts, exc)
        return {}


def _amqp_key(message):
    """A message's id: the queue its routing key names, through the default exchange, and its
    message-id property; None without one."""
    if message.message_id is None:
        return None
    return message.method.fields.get("routing_key"), message.message_id


def amqp_produced(conns, counts):
    """{(queue, message id): (event id, t_depart, t_ack, client port, confirm number, byte,
    whole, t_ack_first)} for every message published on a channel in confirm mode that carries a
    message-id, its first carrying kept; t_ack the arrival of the first basic.ack that covered its
    number, None where a basic.nack refused it or no confirm came. A message ends with its last
    frame."""
    found = {}
    for port, conn in sorted(conns.items()):
        out, inb = _amqp_streams(conn, counts)
        published = _contents(counts, af.publishes, out)
        covering = af.acknowledged(published, af.acks(inb))
        for (channel, number), m in sorted(published.items()):
            counts["publishes"] += 1
            key = _amqp_key(m)
            if key is None:
                counts["unkeyed"] += 1
                continue
            confirm = covering.get((channel, number))
            if confirm is None:
                counts["publishes_unanswered"] += 1
            elif confirm.name != "basic.ack":
                counts["publishes_refused"] += 1
            confirmed = confirm is not None and confirm.name == "basic.ack"
            _keep(found, key, (event_id(conn.out_data, m.start, m.end), conn.left(m.end - 1),
                               conn.came(confirm.end - 1) if confirmed else None, port, number,
                               m.end - 1, m.end, conn.came(confirm.start) if confirmed else None))
    return found


def amqp_consumed(conns, counts):
    """({(queue, message id): (event id, t_arrive, client port, exchange, byte)} for every
    delivery on the consumer's connections that carries a message-id, its first carrying kept, and
    [one row per exchange] for every request on each of them, in order.

    The requests are each synchronous method the client sent, answered by the next "-ok" of its
    name on its channel, and each acknowledgment, which carries the deliveries whose credit it
    freed (amqp_frames.released) and is answered by the first of them to arrive. A delivery sent
    on the consumer's first credit is carried by the basic.consume of its channel and consumer
    tag, or, where the broker named the tag, the first on its channel. A delivery whose credit no
    request the stream holds can have freed is kept with no exchange, and counted.

    The credit: a basic.consume grants its channel's prefetch count (UNLIMITED where it is 0), an
    acknowledgment the deliveries it covers, a multiple one each delivery up to its tag that no
    acknowledgment covered before; and each delivery uses one, from the moment its first byte
    arrived, the use of a delivery no request can have freed held by its channel's first
    basic.consume, so that no delivery goes uncounted."""
    found, rows = {}, []
    for port, conn in sorted(conns.items()):
        out, inb = _amqp_streams(conn, counts)
        delivered = _contents(counts, af.deliveries, inb)
        acks, prefetch = af.acks(out), af.prefetch_counts(out)
        released = af.released(delivered, acks, prefetch)
        covered = collections.Counter(ack.start for ack in
                                      af.acknowledged(delivered, acks).values())
        requests, waiting, credits, consumes, unfreed = [], {}, {}, {}, {}
        for item in out:
            if not isinstance(item, af.Method):
                continue
            if item.name in af.ACKNOWLEDGEMENTS:
                credits[item.start] = len(requests)
            elif item.name in SYNCHRONOUS:
                waiting.setdefault((item.channel, item.name), collections.deque()).append(
                    len(requests))
                if item.name == "basic.consume":
                    consumes.setdefault(item.channel, []).append(len(requests))
            else:
                continue
            requests.append([item, None, []])
        for item in inb:
            if isinstance(item, af.Method) and item.name.endswith("-ok"):
                queue = waiting.get((item.channel, item.name[:-3]))
                if queue:
                    requests[queue.popleft()][1] = item.end
        for tag_key in sorted(delivered, key=lambda k: delivered[k].start):
            m = delivered[tag_key]
            index = None
            if tag_key in released and released[tag_key] is not None:
                index = credits[released[tag_key].start]
            elif tag_key in released:
                tag = m.method.fields.get("consumer_tag")
                mine = consumes.get(m.channel, [])
                index = next((i for i in mine if requests[i][0].fields.get("consumer_tag") == tag),
                             mine[0] if mine else None)
            key = _amqp_key(m)
            if index is None:
                counts["unreleased"] += 1
                held = consumes.get(m.channel)
                if held:
                    unfreed.setdefault(held[0], []).append(m.start)
            else:
                requests[index][2].append((m, key))
            if key is None:
                counts["unkeyed"] += 1
                continue
            _keep(found, key, (event_id(conn.in_data, m.start, m.end), conn.came(m.end - 1), port,
                               index, m.end - 1))
        for index, (item, answer_end, freed) in enumerate(requests):
            grant = covered.get(item.start, 0)
            if item.name in af.ACKNOWLEDGEMENTS and freed:
                answer_end = freed[0][0].end
            elif item.name == "basic.consume":
                grant = prefetch.get(item.channel, 0) or UNLIMITED
            uses = sorted([m.start for m, _ in freed] + unfreed.get(index, []))
            rows.append(_exchange(conn, index, item.name, None, None, item.end, answer_end,
                                  [key for _, key in freed if key is not None], AMQP_ID, grant,
                                  [(at, 1) for at in uses]))
    return found, rows


def _amqp(sending, getting, counts):
    return (amqp_produced(sending, counts),) + amqp_consumed(getting, counts)


# --- one run --------------------------------------------------------------------------------------

#: Each broker's reading: (what the producer's connections carried, what the consumer's did, the
#: consumer's exchanges).
WALKS = {"kafka": _kafka, "redis": _redis, "nats": _nats, "rabbitmq": _amqp}


def _key_row(backend, key):
    if backend == "kafka":
        return {"topic": key[0], "partition": key[1], "offset": key[2]}
    if backend == "nats":
        return {"stream": key[0], "stream_seq": key[1]}
    if backend == "rabbitmq":
        return {"queue": key[0], "message_id": key[1]}
    return {"stream": key[0], "redis_id": "%d-%d" % (key[1], key[2])}


def message_rows(backend, produced, consumed, detail=False):
    """One row per message either side carried, in the broker's order: its id, the event ids the
    two sides' payloads name, its three times, which request carried it each way, and where its
    last byte lies in each connection's stream; with `detail`, also when the first byte of its
    acknowledgment arrived (t_ack_first)."""
    rows = []
    for key in sorted(set(produced) | set(consumed)):
        sent, got = produced.get(key, (None,) * 8), consumed.get(key, (None,) * 5)
        row = _key_row(backend, key)
        row.update(zip(("eid_sent", "t_depart", "t_ack", "producer_port", "request",
                        "sent_byte"), sent))
        row.update(zip(("eid_got", "t_arrive", "consumer_port", "exchange", "got_byte"), got))
        if detail:
            row["t_ack_first"] = sent[7]
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


def walk(backend, sending, getting):
    """(what the producer's connections carried, by broker id; what the consumer's did; the
    consumer's exchanges; the counts), from the producer's connections (`sending`) and the
    consumer's (`getting`), each set read with the times its own record gives."""
    counts = dict.fromkeys(COUNTS + EXTRA_COUNTS.get(backend, ()), 0)
    counts["first_unreadable"] = ""
    return WALKS[backend](sending, getting, counts) + (counts,)


def match(backend, sending, getting, detail=False):
    """(message rows, consumer exchange rows, summary) from the producer's connections (`sending`)
    and the consumer's (`getting`); with `detail`, message rows as message_rows gives them so."""
    produced, consumed, exchanges, counts = walk(backend, sending, getting)
    return (message_rows(backend, produced, consumed, detail), exchanges,
            summarize(backend, sending, getting, produced, consumed, exchanges, counts))


def backend_of(run_dir):
    """The broker a run folder's queue row names; a ValueError for one not read here."""
    backend = osc.setup_of(run_dir)[1].get("backend")
    if backend not in PORTS:
        raise ValueError("%s names no broker read here: %r" % (run_dir, backend))
    return backend


def _client_connections(run_dir, driver, broker, receiver, port):
    """(the run's broker, the producer's connections, the consumer's) from its two client
    captures."""
    backend = backend_of(run_dir)
    port = port or PORTS[backend]
    return (backend,
            connections(os.path.join(run_dir, "sender_full.pcap"), broker, port, driver),
            connections(os.path.join(run_dir, "receiver_full.pcap"), broker, port, receiver))


def read_run(run_dir, driver, broker, receiver, port=None):
    """(message rows, consumer exchange rows, summary) for one run folder, from its two client
    captures: sender_full.pcap on the producer's host, where its connections come from `driver`,
    and receiver_full.pcap on the consumer's, where they come from `receiver`. The broker listens
    on `port`, by default its port in PORTS."""
    return match(*_client_connections(run_dir, driver, broker, receiver, port))


def read_detail(run_dir, driver, broker, receiver, port=None):
    """(message rows, consumer exchange rows, summary, {"sending": the producer's connections,
    "getting": the consumer's}) for one run folder, as read_run reads it, the message rows with
    t_ack_first, and the connections themselves for what they say of the network: their packets,
    retransmissions and zero windows."""
    backend, sending, getting = _client_connections(run_dir, driver, broker, receiver, port)
    return match(backend, sending, getting, True) + ({"sending": sending, "getting": getting},)


# --- the broker's own capture ---------------------------------------------------------------------

def broker_times(run_dir, driver, broker, receiver, port=None):
    """({broker id: [P_in, A_out, F_in, R_out]}, the consumer's exchanges, summary), on the
    broker's clock, from the broker's own capture (broker_full.pcap), the producer's connections
    coming from `driver` and the consumer's from `receiver`; a time None where it was not found.

    P_in is the arrival of the last byte of the request that carried the message (the produce
    request, the XADD, the PUB, the publish's last frame), when the broker could first act on it,
    and A_out the departure of the last byte of its acknowledgment. F_in is the arrival of the last
    byte of the request that delivered it: the fetch, the XREADGROUP, the pull request, or the
    acknowledgment that freed the credit it went out on (its basic.consume for a first credit).
    R_out is the departure of the message's own last byte in the answer that delivered it, the
    byte whose arrival t_arrive times on the consumer's host. Under scripts/under_load.py's
    broker_times, which matches by the payload's event id, R_out was the end of that id instead;
    the two differ only where a packet boundary falls between the id and the record's end. The
    exchanges' t_req are the requests' arrivals, and their t_ans their answers' departures."""
    backend = backend_of(run_dir)
    port = port or PORTS[backend]
    found = connections_of(os.path.join(run_dir, "broker_full.pcap"), broker, port,
                           (driver, receiver), at_broker=True)
    sending, getting = found[driver], found[receiver]
    produced, consumed, exchanges, counts = walk(backend, sending, getting)
    asked = dict(((r["consumer_port"], r["exchange"]), r["t_req"]) for r in exchanges)
    times = {}
    for key in set(produced) | set(consumed):
        sent, got = produced.get(key), consumed.get(key)
        times[key] = [None if sent is None else sending[sent[3]].left(sent[6] - 1),
                      None if sent is None else sent[2],
                      None if got is None else asked.get((got[2], got[3])),
                      None if got is None else got[1]]
    return times, exchanges, summarize(backend, sending, getting, produced, consumed, exchanges,
                                       counts)


# --- the clients' own journals --------------------------------------------------------------------

class Journaled(Conn):
    """One connection as its client's own journal holds it (scripts/so_timestamps.py --so-journal,
    read by scripts/so_journal.py): every byte each way, a byte the client sent timed by the
    transmit timestamp of the send call that carried it out, a byte it read by the receive
    timestamp of the read that delivered it, that read's last packet's."""

    def __init__(self, journal):
        Conn.__init__(self, int(journal.local_port))
        self.journal = journal
        self.out_data, self.in_data = journal.out, journal.inb
        self.opened = 2

    def left(self, offset):
        return sj.tx_at(self.journal, offset)

    def came(self, offset):
        return sj.rx_at(self.journal, offset)


def journaled(stem, port):
    """{local port: Journaled} for each connection to the broker's `port` a client's journal
    holds; {} where the run wrote none."""
    return dict((int(c.local_port), Journaled(c)) for c in sj.load(stem).values()
                if c.peer_port == port)


def socket_run(run_dir, port=None):
    """(message rows, consumer exchange rows, summary) for one run folder as read_run gives them,
    but each time the clients' own sockets', from their journals (producer_journal_* and
    consumer_journal_*); no rows where the run wrote none."""
    backend = backend_of(run_dir)
    port = port or PORTS[backend]
    return match(backend, journaled(os.path.join(run_dir, "producer_journal"), port),
                 journaled(os.path.join(run_dir, "consumer_journal"), port))


# --- the command line -----------------------------------------------------------------------------

def write_csv(path, rows, fields):
    """The rows' `fields`, those an exchange's row holds only in memory left out."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
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
