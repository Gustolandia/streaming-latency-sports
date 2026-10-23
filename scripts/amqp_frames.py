#!/usr/bin/env python3
"""
amqp_frames.py -- AMQP 0-9-1 read from the bytes one direction of a connection carried: a client's
socket journal (scripts/so_timestamps.py --so-journal keeps each connection's bytes, each way) or a
TCP stream reassembled from a capture (scripts/recv_wait.py, Stream). Pure Python, with nothing
beyond the standard library.

The wire format, as the AMQP 0-9-1 specification gives it:

  the client's first eight bytes   "AMQP" 0 0 9 1, the protocol header, which the broker does not
                                   send back;
  every frame                      type (1 octet), channel (2), payload size (4), the payload, and
                                   the frame-end octet 0xCE;
  a method frame (type 1)          class id (2), method id (2) and the method's arguments, the bit
                                   arguments packed into octets from the lowest bit up;
  a content header (type 2)        class id (2), weight (2), body size (8), property flags (2, and
                                   two more while the lowest bit is set), then the properties they
                                   flag, in the class's order;
  a content body (type 3)          the next piece of the body;
  a heartbeat (type 8)             nothing.

A message is a content-bearing method -- basic.publish from a client, basic.deliver to one -- with
the content header and bodies that follow it on its channel. It is known by AMQP's own fields and
never by its payload: the message-id property, which scripts/rabbitmq_producer.py sets to the event
id; the delivery tag, which numbers a channel's deliveries from 1; and, once a channel has asked for
publisher confirms, the number of each publish, which the broker's basic.ack repeats as its delivery
tag. Every item carries the stream offsets of its first byte and of the byte after its frame-end,
so that a reader can time it by the read, or the packet, that carried a given byte of it.

Two pairings are made from those fields: each delivery or publish with the first acknowledgement
that covered it (acknowledged), and each delivery with the acknowledgement that let the broker send
it (released). RabbitMQ sends a consumer no more unacknowledged deliveries than the prefetch count
of its basic.qos allows, 0 allowing any number; so a consumer's k-th delivery could leave the broker
only once k - N of its deliveries had been acknowledged, N being that count.

A third pairing is the consumer's probe (scripts/rabbitmq_consumer.py, --probe-ms): each passive
queue.declare it sends on a channel it consumes nothing on, with the queue.declare-ok that answered
it (probes), so that a reader can time its connection's round trip from the request's last byte out
to the reply's first or last byte in. A probe carries no content, so no delivery is ever made of its
reply, and it neither acknowledges nor holds anything, so no credit is ever counted from it.
"""
import collections
import struct

PROTOCOL_HEADER = b"AMQP\x00\x00\x09\x01"
FRAME_END = 0xCE
METHOD, HEADER, BODY, HEARTBEAT = 1, 2, 3, 8
KINDS = (METHOD, HEADER, BODY, HEARTBEAT)
FRAME = struct.Struct(">BHI")
CONTENT = struct.Struct(">HHQ")
BASIC = 60

NAMES = {
    (10, 10): "connection.start", (10, 11): "connection.start-ok",
    (10, 20): "connection.secure", (10, 21): "connection.secure-ok",
    (10, 30): "connection.tune", (10, 31): "connection.tune-ok",
    (10, 40): "connection.open", (10, 41): "connection.open-ok",
    (10, 50): "connection.close", (10, 51): "connection.close-ok",
    (10, 60): "connection.blocked", (10, 61): "connection.unblocked",
    (20, 10): "channel.open", (20, 11): "channel.open-ok",
    (20, 20): "channel.flow", (20, 21): "channel.flow-ok",
    (20, 40): "channel.close", (20, 41): "channel.close-ok",
    (50, 10): "queue.declare", (50, 11): "queue.declare-ok",
    (50, 20): "queue.bind", (50, 21): "queue.bind-ok",
    (50, 30): "queue.purge", (50, 31): "queue.purge-ok",
    (50, 40): "queue.delete", (50, 41): "queue.delete-ok",
    (60, 10): "basic.qos", (60, 11): "basic.qos-ok",
    (60, 20): "basic.consume", (60, 21): "basic.consume-ok",
    (60, 30): "basic.cancel", (60, 31): "basic.cancel-ok",
    (60, 40): "basic.publish", (60, 50): "basic.return", (60, 60): "basic.deliver",
    (60, 70): "basic.get", (60, 71): "basic.get-ok", (60, 72): "basic.get-empty",
    (60, 80): "basic.ack", (60, 90): "basic.reject",
    (60, 100): "basic.recover-async", (60, 110): "basic.recover", (60, 111): "basic.recover-ok",
    (60, 120): "basic.nack",
    (85, 10): "confirm.select", (85, 11): "confirm.select-ok",
}

ARGUMENTS = {
    "queue.declare": (("reserved_1", "short"), ("queue", "shortstr"), ("passive", "bit"),
                      ("durable", "bit"), ("exclusive", "bit"), ("auto_delete", "bit"),
                      ("no_wait", "bit"), ("arguments", "table")),
    "queue.declare-ok": (("queue", "shortstr"), ("message_count", "long"),
                         ("consumer_count", "long")),
    "basic.qos": (("prefetch_size", "long"), ("prefetch_count", "short"), ("global", "bit")),
    "basic.consume": (("reserved_1", "short"), ("queue", "shortstr"),
                      ("consumer_tag", "shortstr"), ("no_local", "bit"), ("no_ack", "bit"),
                      ("exclusive", "bit"), ("no_wait", "bit"), ("arguments", "table")),
    "basic.consume-ok": (("consumer_tag", "shortstr"),),
    "basic.publish": (("reserved_1", "short"), ("exchange", "shortstr"),
                      ("routing_key", "shortstr"), ("mandatory", "bit"), ("immediate", "bit")),
    "basic.return": (("reply_code", "short"), ("reply_text", "shortstr"),
                     ("exchange", "shortstr"), ("routing_key", "shortstr")),
    "basic.deliver": (("consumer_tag", "shortstr"), ("delivery_tag", "longlong"),
                      ("redelivered", "bit"), ("exchange", "shortstr"),
                      ("routing_key", "shortstr")),
    "basic.get-ok": (("delivery_tag", "longlong"), ("redelivered", "bit"),
                     ("exchange", "shortstr"), ("routing_key", "shortstr"),
                     ("message_count", "long")),
    "basic.ack": (("delivery_tag", "longlong"), ("multiple", "bit")),
    "basic.reject": (("delivery_tag", "longlong"), ("requeue", "bit")),
    "basic.nack": (("delivery_tag", "longlong"), ("multiple", "bit"), ("requeue", "bit")),
    "confirm.select": (("nowait", "bit"),),
}

PROPERTIES = (("content_type", "shortstr"), ("content_encoding", "shortstr"),
              ("headers", "table"), ("delivery_mode", "octet"), ("priority", "octet"),
              ("correlation_id", "shortstr"), ("reply_to", "shortstr"),
              ("expiration", "shortstr"), ("message_id", "shortstr"),
              ("timestamp", "longlong"), ("type", "shortstr"), ("user_id", "shortstr"),
              ("app_id", "shortstr"), ("cluster_id", "shortstr"))

CARRIES_CONTENT = frozenset(("basic.publish", "basic.return", "basic.deliver", "basic.get-ok"))
ACKNOWLEDGEMENTS = frozenset(("basic.ack", "basic.nack", "basic.reject"))
#: The consumer's probe and the broker's reply to it (scripts/rabbitmq_consumer.py, --probe-ms).
PROBE, PROBE_REPLY = "queue.declare", "queue.declare-ok"

Method = collections.namedtuple("Method", "channel name start end fields")
Header = collections.namedtuple("Header", "channel start end class_id body_size properties")
Heartbeat = collections.namedtuple("Heartbeat", "channel start end")


class Body(collections.namedtuple("Body", "channel start end")):
    """A content body frame; its piece of the body lies between its frame header and frame-end."""
    __slots__ = ()

    @property
    def size(self):
        return self.end - self.start - FRAME.size - 1

    def payload(self, data):
        return bytes(data[self.start + FRAME.size:self.end - 1])


class Message(collections.namedtuple("Message", "method header bodies")):
    """A content-bearing method with the content header and the bodies that followed it."""
    __slots__ = ()

    @property
    def channel(self):
        return self.method.channel

    @property
    def name(self):
        return self.method.name

    @property
    def message_id(self):
        return self.header.properties.get("message_id")

    @property
    def delivery_tag(self):
        return self.method.fields.get("delivery_tag")

    @property
    def start(self):
        return self.method.start

    @property
    def end(self):
        """The offset after the message's last byte on the wire."""
        return self.bodies[-1].end if self.bodies else self.header.end

    def body(self, data):
        return b"".join(piece.payload(data) for piece in self.bodies)


class Probe(collections.namedtuple("Probe", "channel number request reply")):
    """A probe the client sent, the number-th on its channel, and the reply that answered it, or
    None where the stream holds none. Three of their bytes time it: the request's last, out, by the
    first transmit timestamp at or past its offset; the reply's first or last, in, by the read or
    the packet that carried it."""
    __slots__ = ()

    @property
    def last_out(self):
        """The offset of the request's last byte, its frame-end, in the client's stream."""
        return self.request.end - 1

    @property
    def first_in(self):
        """The offset of the reply's first byte in the broker's stream; None without a reply."""
        return None if self.reply is None else self.reply.start

    @property
    def last_in(self):
        """The offset of the reply's last byte, its frame-end; None without a reply."""
        return None if self.reply is None else self.reply.end - 1


# --- one field at a time ------------------------------------------------------------------------

def _after(at, size, end, what):
    """The offset after a field of `size` bytes at `at`; a ValueError where it would run past the
    end of its frame, as it does when the bytes are not the AMQP they were taken for."""
    if at + size > end:
        raise ValueError("the AMQP %s at offset %d runs past its frame's end at %d" % (what, at, end))
    return at + size


def _number(fmt):
    shape = struct.Struct(fmt)

    def read_number(data, at, end):
        stop = _after(at, shape.size, end, "number")
        return shape.unpack_from(data, at)[0], stop
    return read_number


def _shortstr(data, at, end):
    size, at = READ["octet"](data, at, end)
    stop = _after(at, size, end, "short string")
    return bytes(data[at:stop]).decode("utf-8", "replace"), stop


def _longbytes(data, at, end):
    """A long string or a field table, kept as its bytes."""
    size, at = READ["long"](data, at, end)
    stop = _after(at, size, end, "long string or table")
    return bytes(data[at:stop]), stop


READ = {"octet": _number(">B"), "short": _number(">H"), "long": _number(">I"),
        "longlong": _number(">Q"), "shortstr": _shortstr, "longstr": _longbytes,
        "table": _longbytes}


def _arguments(data, at, end, spec):
    """A method's arguments by name; consecutive bits share an octet, the first in its lowest
    bit."""
    fields, bit, octet = {}, 8, 0
    for name, kind in spec:
        if kind == "bit":
            if bit == 8:
                octet, at = READ["octet"](data, at, end)
                bit = 0
            fields[name] = bool(octet >> bit & 1)
            bit += 1
        else:
            bit = 8
            fields[name], at = READ[kind](data, at, end)
    return fields


def _properties(data, at, end, class_id):
    """The properties a content header's flags name, by name; those of a class other than basic
    are left undecoded."""
    words = []
    while not words or words[-1] & 1:
        word, at = READ["short"](data, at, end)
        words.append(word)
    found = {}
    if class_id != BASIC:
        return found
    for i, (name, kind) in enumerate(PROPERTIES):
        if words[0] >> (15 - i) & 1:
            found[name], at = READ[kind](data, at, end)
    return found


# --- frames -------------------------------------------------------------------------------------

def frames(data, start=0):
    """(type, channel, start, end) for each whole frame in `data` from `start`, in order, past the
    protocol header where the bytes begin with it. A stream cut off inside a frame ends at the last
    whole one; bytes that are not a frame where one should begin stop it with a ValueError."""
    pos = start + len(PROTOCOL_HEADER) \
        if bytes(data[start:start + len(PROTOCOL_HEADER)]) == PROTOCOL_HEADER else start
    while pos + FRAME.size <= len(data):
        kind, channel, size = FRAME.unpack_from(data, pos)
        if kind not in KINDS:
            raise ValueError("no AMQP frame at offset %d: %r" % (pos, bytes(data[pos:pos + 16])))
        end = pos + FRAME.size + size + 1
        if end > len(data):
            return
        if data[end - 1] != FRAME_END:
            raise ValueError("the AMQP frame at offset %d has no frame-end at %d" % (pos, end - 1))
        yield kind, channel, pos, end
        pos = end


def read(data, start=0):
    """Each whole frame from `start`, decoded, in order: a Method with its arguments by name, a
    Header with its body size and properties, a Body, or a Heartbeat."""
    for kind, channel, first, end in frames(data, start):
        at, stop = first + FRAME.size, end - 1
        if kind == METHOD:
            class_id, at = READ["short"](data, at, stop)
            method_id, at = READ["short"](data, at, stop)
            name = NAMES.get((class_id, method_id), "%d.%d" % (class_id, method_id))
            yield Method(channel, name, first, end,
                         _arguments(data, at, stop, ARGUMENTS.get(name, ())))
        elif kind == HEADER:
            _after(at, CONTENT.size, stop, "content header")
            class_id, _weight, body_size = CONTENT.unpack_from(data, at)
            yield Header(channel, first, end, class_id, body_size,
                         _properties(data, at + CONTENT.size, stop, class_id))
        elif kind == BODY:
            yield Body(channel, first, end)
        else:
            yield Heartbeat(channel, first, end)


def messages(items):
    """[Message] for each content-bearing method whose content header and bodies all followed it,
    in the order of their methods. One the stream cut off is left out; a header or body that no
    content-bearing method opened, or a method that interrupts a content on its own channel, is a
    ValueError."""
    held, done = {}, []
    for item in items:
        if isinstance(item, Method):
            if item.channel in held:
                raise ValueError("the %s at offset %d interrupts the content of the %s at offset %d"
                                 % (item.name, item.start, held[item.channel][0].name,
                                    held[item.channel][0].start))
            if item.name in CARRIES_CONTENT:
                held[item.channel] = [item, None, [], 0]
            continue
        if isinstance(item, Heartbeat):
            continue
        header = isinstance(item, Header)
        open_ = held.get(item.channel)
        if open_ is None or (open_[1] is None) != header:
            raise ValueError("the content %s at offset %d on channel %d follows no %s"
                             % ("header" if header else "body", item.start, item.channel,
                                "content-bearing method" if header else "content header"))
        if header:
            open_[1] = item
        else:
            open_[2].append(item)
            open_[3] += item.size
        if open_[3] >= open_[1].body_size:
            done.append(Message(open_[0], open_[1], tuple(open_[2])))
            del held[item.channel]
    return sorted(done, key=lambda message: message.start)


# --- what a reader pairs ------------------------------------------------------------------------

def deliveries(items):
    """{(channel, delivery tag): Message} for each basic.deliver."""
    return dict(((m.channel, m.delivery_tag), m) for m in messages(items)
                if m.name == "basic.deliver")


def publishes(items):
    """{(channel, number): Message} for each basic.publish on a channel that asked for publisher
    confirms, numbered as the broker numbers it: from 1, in the order of the publishes, from the
    channel's confirm.select on. A publish on a channel that never asked has no number and is left
    out."""
    items = list(items)
    counted, numbers = {}, {}
    for item in items:
        if isinstance(item, Method) and item.name == "confirm.select":
            counted.setdefault(item.channel, 0)
        elif isinstance(item, Method) and item.name == "basic.publish" \
                and item.channel in counted:
            counted[item.channel] += 1
            numbers[item.start] = counted[item.channel]
    return dict(((m.channel, numbers[m.start]), m) for m in messages(items)
                if m.name == "basic.publish" and m.start in numbers)


def acks(items):
    """[Method] for each basic.ack, basic.nack and basic.reject, in the order they came."""
    return [item for item in items if isinstance(item, Method) and item.name in ACKNOWLEDGEMENTS]


def prefetch_counts(items):
    """{channel: the prefetch count of the last basic.qos on it}."""
    return dict((item.channel, item.fields["prefetch_count"]) for item in items
                if isinstance(item, Method) and item.name == "basic.qos")


def acknowledged(keys, acknowledgements):
    """{(channel, number): the first of the acknowledgements that covered it}, for `keys` the
    (channel, delivery tag) of deliveries or the (channel, number) of publishes. One without
    multiple covers its own number; one with multiple covers every number on its channel up to and
    including its own, and with delivery tag 0 every number not covered before it, of those the
    keys hold -- a reading of "all outstanding" that holds only where every one of them had arrived
    before it was sent, which only the times can say."""
    wanted = set(keys)
    ordered = {}
    for channel, number in sorted(wanted):
        ordered.setdefault(channel, []).append(number)
    reached = dict.fromkeys(ordered, 0)
    found = {}
    for ack in acknowledgements:
        numbers = ordered.get(ack.channel, ())
        tag = ack.fields["delivery_tag"]
        if not ack.fields.get("multiple"):
            if (ack.channel, tag) in wanted:
                found.setdefault((ack.channel, tag), ack)
            continue
        i = reached.get(ack.channel, 0)
        while i < len(numbers) and (tag == 0 or numbers[i] <= tag):
            found.setdefault((ack.channel, numbers[i]), ack)
            i += 1
        reached[ack.channel] = i
    return found


def released(delivered, acknowledgements, prefetch):
    """{(channel, delivery tag): the acknowledgement after which the broker could send that
    delivery, or None where the consumer's own credit could}, for `delivered` as deliveries()
    gives it. Counted for each consumer, as RabbitMQ applies a prefetch count to each consumer on
    the channel: its k-th delivery is free while k is at most the prefetch count N, or N is 0, and
    otherwise waits for the acknowledgement after which k - N of its deliveries had been
    acknowledged, in the order the acknowledgements were sent. `prefetch` is a count, or
    {channel: count} as prefetch_counts() gives it. A delivery whose acknowledgement the stream does
    not hold is left out."""
    acknowledgements = list(acknowledgements)
    position = dict((id(ack), i) for i, ack in enumerate(acknowledgements))
    covering = acknowledged(delivered, acknowledgements)
    consumers = {}
    for key in sorted(delivered):
        consumers.setdefault((key[0], delivered[key].method.fields.get("consumer_tag")),
                             []).append(key)
    found = {}
    for (channel, _consumer), keys in consumers.items():
        limit = prefetch.get(channel, 0) if isinstance(prefetch, dict) else prefetch
        steps = sorted(position[id(covering[key])] for key in keys if key in covering)
        for k, key in enumerate(keys, 1):
            if not limit or k <= limit:
                found[key] = None
            elif k - limit <= len(steps):
                found[key] = acknowledgements[steps[k - limit - 1]]
    return found


def probes(sent, received):
    """[Probe] for each passive queue.declare in `sent`, the client's stream, on a channel the
    client consumes nothing on, in the order the client sent them, each with the queue.declare-ok in
    `received`, the broker's stream, that answered it, or None where that stream holds none.

    A channel answers its synchronous methods one at a time and in the order they came, and pika
    sends a channel's next only once the last is answered; so the k-th queue.declare-ok on a channel
    answers the k-th queue.declare on it that asked for an answer, a probe or not, and one that
    names another queue than that declaration is a ValueError. None is taken from a channel that
    consumes, where a reply would wait behind the channel's own deliveries."""
    sent, received = list(sent), list(received)
    consuming = set(item.channel for item in sent
                    if isinstance(item, Method) and item.name == "basic.consume")
    asked, answers = {}, {}
    for item in sent:
        if isinstance(item, Method) and item.name == PROBE and not item.fields["no_wait"] \
                and item.channel not in consuming:
            asked.setdefault(item.channel, []).append(item)
    for item in received:
        if isinstance(item, Method) and item.name == PROBE_REPLY:
            answers.setdefault(item.channel, []).append(item)
    found = []
    for channel, requests in asked.items():
        replies = answers.get(channel, [])
        number = 0
        for k, request in enumerate(requests):
            reply = replies[k] if k < len(replies) else None
            if reply is not None and request.fields["queue"] \
                    and reply.fields["queue"] != request.fields["queue"]:
                raise ValueError("the queue.declare-ok at offset %d names queue %r, so it does not "
                                 "answer the queue.declare of %r at offset %d"
                                 % (reply.start, reply.fields["queue"], request.fields["queue"],
                                    request.start))
            if request.fields["passive"]:
                number += 1
                found.append(Probe(channel, number, request, reply))
    return sorted(found, key=lambda probe: probe.request.start)
