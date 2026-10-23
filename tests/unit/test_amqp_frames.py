"""Tests for scripts/amqp_frames.py: AMQP 0-9-1 read from the bytes one direction of a connection
carried, each delivery paired with the acknowledgement that covered it and with the one that let
the broker send it, and each of the consumer's probes with the reply that answered it.

The frames are built here as pika 1.3.2's spec.py encodes them (the property flags from bit 15
down, the bits of a method packed from the lowest bit), and four are written out byte by byte from
the specification, so that an encoder and a decoder wrong in the same way cannot pass together."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import amqp_frames as af  # noqa: E402


# --- AMQP 0-9-1, written as a client and a broker write it ---------------------------------------

def frame(kind, channel, payload):
    return struct.pack(">BHI", kind, channel, len(payload)) + payload + b"\xce"


def shortstr(text):
    raw = text.encode("utf-8")
    return struct.pack(">B", len(raw)) + raw


def table(raw=b""):
    return struct.pack(">I", len(raw)) + raw


def bits(*flags):
    return struct.pack(">B", sum(1 << i for i, flag in enumerate(flags) if flag))


def method(channel, class_id, method_id, arguments=b""):
    return frame(af.METHOD, channel, struct.pack(">HH", class_id, method_id) + arguments)


def publish(channel, routing_key, exchange="", mandatory=False, immediate=False):
    return method(channel, 60, 40, struct.pack(">H", 0) + shortstr(exchange)
                  + shortstr(routing_key) + bits(mandatory, immediate))


def deliver(channel, tag, consumer="ctag1.a", redelivered=False, exchange="", routing_key="q"):
    return method(channel, 60, 60, shortstr(consumer) + struct.pack(">Q", tag)
                  + bits(redelivered) + shortstr(exchange) + shortstr(routing_key))


def ack(channel, tag, multiple=False):
    return method(channel, 60, 80, struct.pack(">Q", tag) + bits(multiple))


def nack(channel, tag, multiple=False, requeue=True):
    return method(channel, 60, 120, struct.pack(">Q", tag) + bits(multiple, requeue))


def reject(channel, tag, requeue=False):
    return method(channel, 60, 90, struct.pack(">Q", tag) + bits(requeue))


def qos(channel, count, size=0, apply_globally=False):
    return method(channel, 60, 10, struct.pack(">IH", size, count) + bits(apply_globally))


def consume(channel, queue, consumer="ctag1.a", no_ack=False, arguments=b""):
    return method(channel, 60, 20, struct.pack(">H", 0) + shortstr(queue) + shortstr(consumer)
                  + bits(False, no_ack, False, False) + table(arguments))


def select(channel, nowait=False):
    return method(channel, 85, 10, bits(nowait))


def declare(channel, queue, passive=True, durable=False, exclusive=False, auto_delete=False,
            no_wait=False, arguments=b""):
    return method(channel, 50, 10, struct.pack(">H", 0) + shortstr(queue)
                  + bits(passive, durable, exclusive, auto_delete, no_wait) + table(arguments))


def declare_ok(channel, queue, messages=0, consumers=1):
    return method(channel, 50, 11, shortstr(queue) + struct.pack(">II", messages, consumers))


ENCODE = {"shortstr": shortstr, "table": table, "octet": lambda v: struct.pack(">B", v),
          "longlong": lambda v: struct.pack(">Q", v)}


def header(channel, body_size, class_id=60, flag_words=(), **properties):
    flags, values = 0, b""
    for i, (name, kind) in enumerate(af.PROPERTIES):
        if name in properties:
            flags |= 1 << (15 - i)
            values += ENCODE[kind](properties[name])
    words = struct.pack(">H", flags | (1 if flag_words else 0))
    words += b"".join(struct.pack(">H", w) for w in flag_words)
    return frame(af.HEADER, channel, struct.pack(">HHQ", class_id, 0, body_size) + words + values)


def body(channel, data):
    return frame(af.BODY, channel, data)


HEARTBEAT = frame(af.HEARTBEAT, 0, b"")


def content(channel, opening, payload, message_id, pieces=1):
    """A content-bearing method with its header (message-id and transient delivery mode) and the
    payload in `pieces` bodies."""
    step = -(-len(payload) // pieces)
    return (opening + header(channel, len(payload), message_id=message_id, delivery_mode=1)
            + b"".join(body(channel, payload[i:i + step]) for i in range(0, len(payload), step)))


def payload(eid, run="r1"):
    return b'{"run_id":"%s","event_id":"%s"}' % (run.encode(), eid.encode())


# --- frames --------------------------------------------------------------------------------------

class TestTheFrames:

    def test_a_clients_stream_starts_past_its_protocol_header(self):
        data = af.PROTOCOL_HEADER + ack(1, 5) + HEARTBEAT
        found = list(af.frames(data))
        assert found == [(af.METHOD, 1, 8, 8 + len(ack(1, 5))),
                         (af.HEARTBEAT, 0, 8 + len(ack(1, 5)), len(data))]

    def test_a_brokers_stream_has_none(self):
        data = ack(1, 5)
        assert list(af.frames(data)) == [(af.METHOD, 1, 0, len(data))]

    def test_it_can_start_part_way(self):
        data = b"xxx" + af.PROTOCOL_HEADER + ack(1, 5)
        assert list(af.frames(data, 3)) == [(af.METHOD, 1, 11, len(data))]
        assert list(af.frames(data, 11)) == [(af.METHOD, 1, 11, len(data))]

    def test_a_stream_cut_off_ends_at_its_last_whole_frame(self):
        data = ack(1, 5) + ack(1, 6)
        assert [f[2] for f in af.frames(data[:-3])] == [0]
        assert [f[2] for f in af.frames(data[:len(ack(1, 5)) + 4])] == [0], "a frame head cut short"

    def test_bytes_that_are_no_frame_stop_it(self):
        with pytest.raises(ValueError, match="no AMQP frame at offset 0"):
            list(af.frames(b"\x07\x00\x01\x00\x00\x00\x00\xce"))
        bad = bytearray(ack(1, 5))
        bad[-1] = 0
        with pytest.raises(ValueError, match="no frame-end"):
            list(af.frames(bytes(bad)))

    def test_it_reads_a_memoryview_as_well(self):
        data = memoryview(af.PROTOCOL_HEADER + ack(1, 5))
        assert [m.fields for m in af.read(data)] == [{"delivery_tag": 5, "multiple": False}]


# --- methods -------------------------------------------------------------------------------------

def one(data):
    items = list(af.read(data))
    assert len(items) == 1
    return items[0]


class TestTheMethods:

    def test_an_ack_written_out_from_the_specification(self):
        """Channel 1, basic (60) ack (80), delivery tag 5, multiple: thirteen bytes of payload."""
        data = bytes.fromhex("01" "0001" "0000000d" "003c" "0050" "0000000000000005" "01" "ce")
        assert one(data) == af.Method(1, "basic.ack", 0, 21, {"delivery_tag": 5,
                                                              "multiple": True})

    def test_a_passive_declare_and_its_reply_written_out_from_the_specification(self):
        """Channel 2, queue (50) declare (10): reserved 0, the queue "q1", passive alone of its five
        bits and no arguments, fourteen bytes of payload; declare-ok (11): the queue, 7 messages
        ready and 1 consumer, fifteen."""
        request = bytes.fromhex("01" "0002" "0000000e" "0032" "000a" "0000" "02" "7131" "01"
                                "00000000" "ce")
        assert one(request) == af.Method(2, "queue.declare", 0, 22, {
            "reserved_1": 0, "queue": "q1", "passive": True, "durable": False,
            "exclusive": False, "auto_delete": False, "no_wait": False, "arguments": b""})
        reply = bytes.fromhex("01" "0002" "0000000f" "0032" "000b" "02" "7131" "00000007"
                              "00000001" "ce")
        assert one(reply) == af.Method(2, "queue.declare-ok", 0, 23, {
            "queue": "q1", "message_count": 7, "consumer_count": 1})
        assert (declare(2, "q1"), declare_ok(2, "q1", 7, 1)) == (request, reply)

    def test_a_declaration_with_each_of_its_bits_in_its_place(self):
        found = one(declare(1, "sb-events-r1", passive=False, durable=True, auto_delete=True,
                            arguments=b"\x00\x01")).fields
        assert found == {"reserved_1": 0, "queue": "sb-events-r1", "passive": False,
                         "durable": True, "exclusive": False, "auto_delete": True,
                         "no_wait": False, "arguments": b"\x00\x01"}
        found = one(declare(1, "q", exclusive=True, no_wait=True)).fields
        assert (found["passive"], found["durable"], found["exclusive"], found["no_wait"]) == (
            True, False, True, True)

    def test_publish_deliver_and_the_three_acknowledgements(self):
        assert one(publish(1, "sb-events-r1", mandatory=True)).fields == {
            "reserved_1": 0, "exchange": "", "routing_key": "sb-events-r1", "mandatory": True,
            "immediate": False}
        assert one(deliver(2, 7, redelivered=True, routing_key="sb-events-r1")).fields == {
            "consumer_tag": "ctag1.a", "delivery_tag": 7, "redelivered": True, "exchange": "",
            "routing_key": "sb-events-r1"}
        assert one(nack(1, 9, multiple=True)).fields == {"delivery_tag": 9, "multiple": True,
                                                         "requeue": True}
        assert one(reject(1, 9)).fields == {"delivery_tag": 9, "requeue": False}
        assert one(ack(3, 2**40)).channel == 3 and one(ack(3, 2**40)).fields["delivery_tag"] == 2**40

    def test_qos_consume_and_confirm_select(self):
        assert one(qos(1, 1000)).fields == {"prefetch_size": 0, "prefetch_count": 1000,
                                            "global": False}
        assert one(qos(1, 1, apply_globally=True)).fields["global"] is True
        found = one(consume(1, "q", no_ack=True, arguments=b"\x01\x02")).fields
        assert found == {"reserved_1": 0, "queue": "q", "consumer_tag": "ctag1.a",
                         "no_local": False, "no_ack": True, "exclusive": False, "no_wait": False,
                         "arguments": b"\x01\x02"}
        assert one(method(1, 60, 21, shortstr("ctag1.a"))).fields == {"consumer_tag": "ctag1.a"}
        assert one(select(1, nowait=True)) == af.Method(1, "confirm.select", 0,
                                                        len(select(1)), {"nowait": True})

    def test_a_return_and_a_get_ok(self):
        returned = method(1, 60, 50, struct.pack(">H", 312) + shortstr("NO_ROUTE")
                          + shortstr("") + shortstr("q"))
        assert one(returned).fields == {"reply_code": 312, "reply_text": "NO_ROUTE",
                                        "exchange": "", "routing_key": "q"}
        got = method(1, 60, 71, struct.pack(">Q", 4) + bits(False) + shortstr("") + shortstr("q")
                     + struct.pack(">I", 12))
        assert one(got).fields == {"delivery_tag": 4, "redelivered": False, "exchange": "",
                                   "routing_key": "q", "message_count": 12}

    def test_other_methods_are_named_and_left_undecoded(self):
        assert one(method(0, 10, 10, b"\x00\x09anything")) == af.Method(
            0, "connection.start", 0, 22, {})
        assert one(method(0, 70, 10)).name == "70.10"

    def test_a_field_past_its_frame_is_no_amqp(self):
        with pytest.raises(ValueError, match="number at offset 7"):
            list(af.read(frame(af.METHOD, 1, b"\x00")))
        with pytest.raises(ValueError, match="number at offset 11 runs past"):
            list(af.read(method(1, 60, 80, b"\x00\x00")))
        with pytest.raises(ValueError, match="short string"):
            list(af.read(method(1, 60, 21, b"\x09ctag")))
        with pytest.raises(ValueError, match="long string or table"):
            list(af.read(method(1, 60, 20, struct.pack(">H", 0) + shortstr("q") + shortstr("c")
                                + bits() + struct.pack(">I", 9) + b"ab")))


# --- content headers and bodies ------------------------------------------------------------------

class TestTheContent:

    def test_a_header_written_out_from_the_specification(self):
        """Delivery mode (flag bit 12) and message-id (bit 7): 0x1080, the octet before the
        string because delivery mode comes first in the class's order."""
        data = bytes.fromhex("02" "0001" "0000001f" "003c" "0000" "00000000000000c8" "1080" "01"
                             "0f") + b"constant-000001" + b"\xce"
        assert one(data) == af.Header(1, 0, 39, 60, 200, {"delivery_mode": 1,
                                                          "message_id": "constant-000001"})

    def test_every_property_of_the_basic_class(self):
        given = {"content_type": "application/json", "content_encoding": "utf-8",
                 "headers": b"\x03key", "delivery_mode": 2, "priority": 9,
                 "correlation_id": "c", "reply_to": "r", "expiration": "60000",
                 "message_id": "constant-000002", "timestamp": 1791900000, "type": "t",
                 "user_id": "guest", "app_id": "sbl", "cluster_id": "k"}
        assert one(header(1, 0, **given)).properties == given

    def test_more_flag_words_are_read_past(self):
        found = one(header(1, 10, flag_words=(0x0001, 0x0000), message_id="constant-000003"))
        assert found.properties == {"message_id": "constant-000003"}

    def test_another_class_is_left_undecoded(self):
        found = one(header(1, 10, class_id=70, message_id="constant-000004"))
        assert (found.class_id, found.body_size, found.properties) == (70, 10, {})

    def test_a_header_cut_short_is_no_amqp(self):
        with pytest.raises(ValueError, match="content header"):
            list(af.read(frame(af.HEADER, 1, struct.pack(">HH", 60, 0))))

    def test_a_body_and_a_heartbeat(self):
        data = body(1, b"hello") + HEARTBEAT
        found = list(af.read(data))
        assert found == [af.Body(1, 0, 13), af.Heartbeat(0, 13, 21)]
        assert found[0].size == 5 and found[0].payload(data) == b"hello"


# --- messages ------------------------------------------------------------------------------------

OPENING = deliver(1, 1)
HEAD = header(1, 3, message_id="a")

class TestTheMessages:

    def test_a_delivery_is_its_method_header_and_bodies(self):
        data = content(1, deliver(1, 1), payload("constant-000001"), "constant-000001", pieces=3)
        found = af.messages(af.read(data))
        assert len(found) == 1
        m = found[0]
        assert (m.channel, m.name, m.delivery_tag, m.message_id) == (
            1, "basic.deliver", 1, "constant-000001")
        assert (m.start, m.end, len(m.bodies)) == (0, len(data), 3)
        assert m.body(data) == payload("constant-000001")

    def test_it_is_known_by_its_message_id_never_by_its_payload(self):
        data = content(1, deliver(1, 1), payload("constant-000009"), "constant-000001")
        assert [m.message_id for m in af.messages(af.read(data))] == ["constant-000001"]

    def test_an_empty_body_ends_at_its_header(self):
        data = deliver(1, 1) + header(1, 0, message_id="constant-000001")
        found = af.messages(af.read(data))
        assert found[0].bodies == () and found[0].end == len(data)

    def test_channels_may_interleave_and_heartbeats_and_other_methods_pass(self):
        one_ = deliver(1, 1)
        two = deliver(2, 1)
        data = (one_ + two + HEARTBEAT + header(2, 3, message_id="b") + ack(3, 1)
                + header(1, 3, message_id="a") + body(1, b"aaa") + body(2, b"bbb"))
        found = af.messages(af.read(data))
        assert [(m.channel, m.message_id) for m in found] == [(1, "a"), (2, "b")]

    def test_one_the_stream_cut_off_is_left_out(self):
        data = content(1, deliver(1, 1), payload("constant-000001"), "constant-000001")
        data += deliver(1, 2) + header(1, 40, message_id="constant-000002") + body(1, b"x" * 10)
        assert [m.delivery_tag for m in af.messages(af.read(data))] == [1]

    @pytest.mark.parametrize("data,said", [
        (HEAD, "header at offset 0 on channel 1 follows no content-bearing method"),
        (body(1, b"aaa"), "body at offset 0 on channel 1 follows no content header"),
        (OPENING + body(1, b"aaa"),
         "body at offset %d on channel 1 follows no content header" % len(OPENING)),
        (OPENING + HEAD + HEAD, "header at offset %d on channel 1 follows no content-bearing "
                                "method" % (len(OPENING) + len(HEAD))),
        (OPENING + ack(1, 1), "basic.ack at offset %d interrupts the content of the basic.deliver "
                              "at offset 0" % len(OPENING)),
    ])
    def test_content_out_of_place_is_no_amqp(self, data, said):
        with pytest.raises(ValueError, match=said):
            af.messages(af.read(data))


# --- what a reader pairs -------------------------------------------------------------------------

def client_stream(*frames_):
    return af.PROTOCOL_HEADER + b"".join(frames_)


class TestThePublishesAndTheirNumbers:

    def test_they_are_numbered_from_1_once_the_channel_asks_for_confirms(self):
        data = client_stream(
            content(1, publish(1, "q"), b"before", "constant-000000"),
            select(1),
            content(1, publish(1, "q"), b"first", "constant-000001"),
            content(2, publish(2, "q"), b"unasked", "constant-000099"),
            select(1),
            content(1, publish(1, "q"), b"second", "constant-000002"),
            publish(1, "q") + header(1, 9, message_id="constant-000003"))
        found = af.publishes(af.read(data))
        assert sorted(found) == [(1, 1), (1, 2)], "a second select restarts nothing"
        assert [found[k].message_id for k in sorted(found)] == ["constant-000001",
                                                                "constant-000002"]

    def test_the_broker_side_deliveries_acks_and_prefetch(self):
        data = (qos(1, 5) + qos(1, 1) + qos(2, 0)
                + content(1, deliver(1, 1), b"x", "a") + ack(1, 1) + nack(1, 2) + reject(1, 3)
                + content(1, publish(1, "q"), b"y", "b"))
        items = list(af.read(data))
        assert sorted(af.deliveries(items)) == [(1, 1)]
        assert [a.name for a in af.acks(items)] == ["basic.ack", "basic.nack", "basic.reject"]
        assert af.prefetch_counts(items) == {1: 1, 2: 0}


def acks_of(*frames_):
    return af.acks(af.read(b"".join(frames_)))


class TestTheAcknowledgementThatCoveredEach:

    def test_alone_and_with_multiple(self):
        found = acks_of(ack(1, 2), ack(1, 1), ack(1, 5, multiple=True), ack(1, 7))
        keys = [(1, n) for n in range(1, 8)]
        covered = af.acknowledged(keys, found)
        assert [covered[(1, n)].fields["delivery_tag"] for n in (1, 2, 3, 4, 5, 7)] == \
            [1, 2, 5, 5, 5, 7]
        assert (1, 6) not in covered, "nothing covered it"

    def test_the_first_covering_one_is_kept(self):
        found = acks_of(ack(1, 1), ack(1, 1), ack(1, 2, multiple=True))
        covered = af.acknowledged([(1, 1), (1, 2)], found)
        assert covered[(1, 1)] is found[0] and covered[(1, 2)] is found[2]

    def test_tag_0_with_multiple_covers_all_not_yet_covered(self):
        found = acks_of(ack(1, 2), ack(1, 0, multiple=True))
        covered = af.acknowledged([(1, 1), (1, 2), (1, 3)], found)
        assert [covered[(1, n)] for n in (1, 2, 3)] == [found[1], found[0], found[1]]

    def test_other_channels_and_unknown_tags_cover_nothing(self):
        found = acks_of(ack(2, 1), ack(2, 9, multiple=True), ack(1, 9), reject(1, 1))
        covered = af.acknowledged([(1, 1)], found)
        assert covered == {(1, 1): found[3]}, "a reject, alone, covers its own"

    def test_confirms_cover_publishes_as_acks_cover_deliveries(self):
        sent = client_stream(select(1), *[content(1, publish(1, "q"), b"m", "constant-00000%d" % i)
                                          for i in range(1, 5)])
        confirms = acks_of(ack(1, 3, multiple=True), nack(1, 4))
        covered = af.acknowledged(af.publishes(af.read(sent)), confirms)
        assert [covered[(1, n)].name for n in (1, 2, 3, 4)] == ["basic.ack"] * 3 + ["basic.nack"]


class TestTheAcknowledgementThatReleasedEach:
    """RabbitMQ holds back a consumer's deliveries beyond its prefetch count unacknowledged."""

    @staticmethod
    def delivered(tags, consumer="ctag1.a", channel=1):
        data = b"".join(content(channel, deliver(channel, t, consumer=consumer), b"m", "id%d" % t)
                        for t in tags)
        return af.deliveries(af.read(data))

    def test_at_prefetch_1_each_waits_for_the_ack_of_the_one_before(self):
        found = acks_of(ack(1, 1), ack(1, 2), ack(1, 3))
        released = af.released(self.delivered([1, 2, 3]), found, 1)
        assert released == {(1, 1): None, (1, 2): found[0], (1, 3): found[1]}

    def test_at_prefetch_1000_a_credit_is_always_waiting(self):
        found = acks_of(ack(1, 1), ack(1, 2))
        assert set(af.released(self.delivered([1, 2, 3]), found, 1000).values()) == {None}
        assert set(af.released(self.delivered([1, 2, 3]), found, 0).values()) == {None}

    def test_one_multiple_ack_can_release_several(self):
        found = acks_of(ack(1, 2, multiple=True), ack(1, 4, multiple=True))
        released = af.released(self.delivered([1, 2, 3, 4, 5, 6]), found, 2)
        assert [released[(1, t)] for t in range(1, 7)] == [None, None, found[0], found[0],
                                                           found[1], found[1]]

    def test_out_of_order_acks_are_counted_as_they_were_sent(self):
        found = acks_of(ack(1, 2), ack(1, 1))
        released = af.released(self.delivered([1, 2, 3, 4]), found, 2)
        assert released == {(1, 1): None, (1, 2): None, (1, 3): found[0], (1, 4): found[1]}

    def test_one_whose_ack_the_stream_does_not_hold_is_left_out(self):
        found = acks_of(ack(1, 1))
        assert af.released(self.delivered([1, 2, 3]), found, 1) == {(1, 1): None,
                                                                    (1, 2): found[0]}

    def test_each_consumer_has_its_own_count_and_each_channel_its_own_prefetch(self):
        mixed = b"".join(content(1, deliver(1, t, consumer=c), b"m", "id%d" % t)
                         for t, c in ((1, "a"), (2, "b"), (3, "a"), (4, "b")))
        delivered = af.deliveries(af.read(mixed))
        delivered.update(self.delivered([1, 2], channel=2))
        found = acks_of(ack(1, 2), ack(1, 1), ack(2, 1))
        released = af.released(delivered, found, {1: 1})
        assert released == {(1, 1): None, (1, 2): None, (1, 3): found[1], (1, 4): found[0],
                            (2, 1): None, (2, 2): None}

    def test_a_consumer_at_prefetch_1_from_both_of_its_streams(self):
        """The bytes a consumer writes and reads, paired as a reader of its journal pairs them."""
        out = client_stream(qos(1, 1), consume(1, "sb-events-r1"), ack(1, 1), ack(1, 2), ack(1, 3))
        inb = b"".join(content(1, deliver(1, t, routing_key="sb-events-r1"),
                               payload("constant-00000%d" % t), "constant-00000%d" % t)
                       for t in (1, 2, 3))
        sent, read_ = list(af.read(out)), list(af.read(inb))
        delivered = af.deliveries(read_)
        released = af.released(delivered, af.acks(sent), af.prefetch_counts(sent))
        acked = af.acknowledged(delivered, af.acks(sent))
        by_id = dict((m.message_id, key) for key, m in delivered.items())
        assert [released[by_id["constant-00000%d" % t]] and
                released[by_id["constant-00000%d" % t]].fields["delivery_tag"]
                for t in (1, 2, 3)] == [None, 1, 2]
        assert [acked[by_id["constant-00000%d" % t]].start for t in (1, 2, 3)] == [
            a.start for a in af.acks(sent)]


# --- the consumer's probes ----------------------------------------------------------------------

class TestTheProbesAndTheirReplies:
    """The consumer's probe: a passive queue.declare on a channel it consumes nothing on, and the
    queue.declare-ok that answered it."""

    def test_each_pairs_in_order_with_the_reply_on_its_own_channel(self):
        out = client_stream(qos(1, 1000), consume(1, "q"), declare(2, "q"), declare(3, "q"),
                            ack(1, 1), declare(2, "q"))
        inb = (declare_ok(3, "q", messages=9) + declare_ok(2, "q", messages=1)
               + content(1, deliver(1, 1), b"m", "id1") + declare_ok(2, "q", messages=2))
        found = af.probes(af.read(out), af.read(inb))
        assert [(p.channel, p.number, p.reply.fields["message_count"]) for p in found] == [
            (2, 1, 1), (3, 1, 9), (2, 2, 2)], "in the order sent, each with its channel's reply"

    def test_the_three_bytes_that_time_it(self):
        out = client_stream(qos(1, 1), consume(1, "q"), declare(2, "q"))
        delivered = content(1, deliver(1, 1), b"m", "id1")
        inb = delivered + declare_ok(2, "q")
        probe, = af.probes(af.read(out), af.read(inb))
        assert probe.last_out == len(out) - 1 and out[probe.last_out] == af.FRAME_END
        assert (probe.first_in, probe.last_in) == (len(delivered), len(inb) - 1)
        assert inb[probe.first_in:probe.last_in + 1] == declare_ok(2, "q")

    def test_one_the_stream_holds_no_reply_to_has_none(self):
        out = client_stream(declare(2, "q"), declare(2, "q"))
        found = af.probes(af.read(out), af.read(declare_ok(2, "q")))
        assert [p.reply is None for p in found] == [False, True]
        assert (found[1].last_out, found[1].first_in, found[1].last_in) == (
            len(out) - 1, None, None)

    def test_none_is_taken_from_a_channel_that_consumes_nor_from_a_producer(self):
        consumer = client_stream(declare(1, "q", passive=False, durable=True), qos(1, 1),
                                 consume(1, "q"), declare(1, "q"))
        assert af.probes(af.read(consumer), af.read(declare_ok(1, "q") * 2)) == [], \
            "a reply there would wait behind the channel's deliveries"
        producer = client_stream(declare(1, "q", passive=False, durable=True), select(1),
                                 content(1, publish(1, "q"), b"m", "id1"))
        assert af.probes(af.read(producer), af.read(declare_ok(1, "q"))) == []

    def test_a_declaration_that_is_no_probe_keeps_its_place_in_the_order(self):
        """One not passive is answered in its turn, and one that asks for no answer gets none."""
        out = client_stream(declare(2, "", passive=False), declare(2, "q", no_wait=True),
                            declare(2, "q"))
        inb = declare_ok(2, "amq.gen-JzTY20BRgKO-HjmUJj0wLg") + declare_ok(2, "q", messages=5)
        found = af.probes(af.read(out), af.read(inb))
        assert [(p.number, p.reply.fields["message_count"]) for p in found] == [(1, 5)]

    def test_a_reply_that_names_another_queue_answers_nothing(self):
        with pytest.raises(ValueError, match="the queue.declare-ok at offset 0 names queue "
                                             "'other', so it does not answer the queue.declare "
                                             "of 'q' at offset 8"):
            af.probes(af.read(client_stream(declare(2, "q"))), af.read(declare_ok(2, "other")))

    def test_a_probe_is_never_a_delivery_an_acknowledgement_or_a_credit(self):
        """A consumer at prefetch 1 with its probes between its deliveries, a reply even between a
        delivery's method and its content: what is paired without the probes is paired the same
        with them."""
        def streams(probing):
            p = (lambda frame: frame) if probing else (lambda frame: b"")
            out = client_stream(qos(1, 1), consume(1, "q"), p(declare(2, "q")), ack(1, 1),
                                p(declare(2, "q")), ack(1, 2), p(declare(2, "q")), ack(1, 3))
            inb = (content(1, deliver(1, 1), b"a", "id1") + p(declare_ok(2, "q"))
                   + deliver(1, 2) + p(declare_ok(2, "q")) + header(1, 1, message_id="id2")
                   + body(1, b"b") + content(1, deliver(1, 3), b"c", "id3")
                   + p(declare_ok(2, "q")))
            return list(af.read(out)), list(af.read(inb))

        def paired(sent, received):
            delivered = af.deliveries(received)
            released = af.released(delivered, af.acks(sent), af.prefetch_counts(sent))
            return ([(key, m.name, m.message_id) for key, m in sorted(delivered.items())],
                    [a.fields["delivery_tag"] for a in af.acks(sent)],
                    dict((key, a and a.fields["delivery_tag"]) for key, a in released.items()),
                    af.prefetch_counts(sent))

        probed = streams(True)
        assert paired(*probed) == paired(*streams(False)) == (
            [((1, 1), "basic.deliver", "id1"), ((1, 2), "basic.deliver", "id2"),
             ((1, 3), "basic.deliver", "id3")], [1, 2, 3],
            {(1, 1): None, (1, 2): 1, (1, 3): 2}, {1: 1})
        assert [(p.channel, p.number) for p in af.probes(*probed)] == [(2, 1), (2, 2), (2, 3)]
