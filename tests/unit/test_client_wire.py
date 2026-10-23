"""Tests for scripts/client_wire.py: each message's kernel timestamps from the client host's own
captures, matched by the broker's ids, against runs built here packet by packet in the shape the kit
writes them: sender_full.pcap on the driver's Ethernet link, receiver_full.pcap in the receiver's
namespace (Linux cooked v2), each connection opened by its SYN, and the frames the clients and the
broker exchange, the kit's own copied byte for byte from a judged run's journals (block U, 2,000 a
second; kafka-python 2.3.2 against Kafka 4.1.1, redis-py 7.4.1 against Redis 7).

The made-up captures do what real ones can: a request split over two packets and sent again later,
an answer whose packets were captured out of order, a connection whose opening the capture missed
and one of whose packets it lost, traffic of other hosts and ports, and a request still in flight
when the capture stopped. Kafka's conversation holds frames of the versions the kit's clients send
(Produce v8, Fetch v10) and of flexible versions that name topics by id (Metadata v12, Produce v13,
Fetch v16); Redis's holds RESP2 and RESP3 replies, a push message and an attribute among them."""
import csv
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import client_wire as cw  # noqa: E402
import kafka_wire as kw  # noqa: E402

US = 1000
T0 = 1792694830 * 10**9
DRIVER, BROKER, RECEIVER, OTHER = "10.2.1.10", "10.2.1.21", "10.2.1.11", "10.2.1.99"
KAFKA_PORT, REDIS_PORT = 19092, 6379


def at(us):
    return T0 + us * US


# --- packets and captures -------------------------------------------------------------------------

def ip_tcp(src, dst, sport, dport, seq, payload=b"", flags=0x18, proto=6):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, flags, 65535, 0, 0) + payload
    return struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, proto, 0,
                       socket.inet_aton(src), socket.inet_aton(dst)) + tcp


def ether(ip, proto=0x0800):
    return b"\0" * 12 + struct.pack(">H", proto) + ip


def sll2(ip):
    return struct.pack(">HHIHBB8s", 0x0800, 0, 2, 1, 0, 6, b"\0" * 8) + ip


def pcap_bytes(packets, wrap, linktype):
    """A nanosecond pcap of the packets in the order they were captured, each wrapped in its link
    layer's header."""
    out = struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, 262144, linktype)
    for ns, ip in sorted(packets, key=lambda p: p[0]):
        frame = wrap(ip)
        out += struct.pack("<IIII", ns // 10**9, ns % 10**9, len(frame), len(frame)) + frame
    return out


class Wire(object):
    """One made-up connection between a client and the broker, as the client host's capture sees
    it: its packets with their capture times, and each direction's bytes in stream order."""

    def __init__(self, client, port, broker_port, opened=True):
        self.client, self.port, self.broker_port = client, port, broker_port
        self.isn = {True: 1000, False: 70000}
        self.data = {True: b"", False: b""}
        self.packets = []
        if opened:
            self.packets.append((at(0), self._packet(True, self.isn[True], b"", 0x02)))
            self.packets.append((at(1), self._packet(False, self.isn[False], b"", 0x12)))

    def _packet(self, outgoing, seq, payload, flags=0x18):
        if outgoing:
            return ip_tcp(self.client, BROKER, self.port, self.broker_port, seq, payload, flags)
        return ip_tcp(BROKER, self.client, self.broker_port, self.port, seq, payload, flags)

    def carry(self, outgoing, us, data):
        """`data` sent next one way, in one packet captured at `us`; where it starts."""
        start = len(self.data[outgoing])
        self.packets.append((at(us), self._packet(outgoing, self.isn[outgoing] + 1 + start, data)))
        self.data[outgoing] += data
        return start

    def again(self, outgoing, us, start, end):
        """The stream's bytes [start, end) carried again, in a packet captured at `us`."""
        self.packets.append((at(us), self._packet(outgoing, self.isn[outgoing] + 1 + start,
                                                  self.data[outgoing][start:end])))

    def lose(self, outgoing, data):
        """Bytes the connection sent that the capture missed."""
        self.data[outgoing] += data

    def control(self, outgoing, us, flags):
        """A packet with no data: an acknowledgment, or a SYN sent again."""
        seq = self.isn[outgoing] + (0 if flags & 0x02 else 1 + len(self.data[outgoing]))
        self.packets.append((at(us), self._packet(outgoing, seq, b"", flags)))


def write_run(root, name, backend, sending, getting, noise=()):
    """A run folder: its queue row, and its two client captures, from the producer's wires
    (`sending`) and the consumer's (`getting`), with any packets of other traffic (`noise`)."""
    run = root / name
    run.mkdir()
    (run / "queue_row.json").write_text(json.dumps(
        {"setup": "U2000-%s-l0" % backend, "params": {"backend": backend}}), encoding="utf-8")
    sent = [p for w in sending for p in w.packets] + list(noise)
    got = [p for w in getting for p in w.packets]
    (run / "sender_full.pcap").write_bytes(pcap_bytes(sent, ether, 1))
    (run / "receiver_full.pcap").write_bytes(pcap_bytes(got, sll2, 276))
    return str(run)


# --- Kafka's frames -------------------------------------------------------------------------------

def uvarint(n):
    out = b""
    while n > 0x7F:
        out += bytes([(n & 0x7F) | 0x80])
        n >>= 7
    return out + bytes([n])


def varint(n):
    return uvarint((n << 1) ^ (n >> 63))


def compact(raw):
    return uvarint(len(raw) + 1) + raw


def compact_array(items):
    return uvarint(len(items) + 1) + b"".join(items)


NO_TAGS = b"\x00"


def kafka_request(api, version, corr, body=b"", client=b"client"):
    payload = struct.pack(">hhih", api, version, corr, len(client)) + client + body
    return struct.pack(">i", len(payload)) + payload


def kafka_response(corr, body=b""):
    payload = struct.pack(">i", corr) + body
    return struct.pack(">i", len(payload)) + payload


def produce_v8(corr, topic, partition, records):
    body = (struct.pack(">hhii", -1, -1, 30000, 1) + struct.pack(">h", len(topic)) + topic
            + struct.pack(">iii", 1, partition, len(records)) + records)
    return kafka_request(0, 8, corr, body, b"kafka-python-producer-1")


def produce_v8_answer(corr, topic, partition, error, base):
    body = (struct.pack(">ih", 1, len(topic)) + topic
            + struct.pack(">iihqqqih", 1, partition, error, base, -1, 0, 0, -1)
            + struct.pack(">i", 0))
    return kafka_response(corr, body)


def produce_v13(corr, tid, partition, records):
    part = struct.pack(">i", partition) + compact(records) + NO_TAGS
    body = (uvarint(0) + struct.pack(">hi", -1, 30000)
            + compact_array([tid + compact_array([part]) + NO_TAGS]) + NO_TAGS)
    return kafka_request(0, 13, corr, NO_TAGS + body, b"producer-1")


def produce_v13_answer(corr, tid, partition, base):
    part = struct.pack(">ihqqq", partition, 0, base, -1, 0) + compact_array([]) + uvarint(0)
    body = (compact_array([tid + compact_array([part + NO_TAGS]) + NO_TAGS])
            + struct.pack(">i", 0) + NO_TAGS)
    return kafka_response(corr, NO_TAGS + body)


def metadata_v12_answer(corr, name, tid):
    broker = struct.pack(">i", 1) + compact(b"10.2.1.21") + struct.pack(">i", KAFKA_PORT)
    partition = (struct.pack(">hiii", 0, 0, 1, 0) + compact_array([struct.pack(">i", 1)])
                 + compact_array([struct.pack(">i", 1)]) + compact_array([]) + NO_TAGS)
    topic = (struct.pack(">h", 0) + compact(name) + tid + b"\x00" + compact_array([partition])
             + struct.pack(">i", -2 ** 31) + NO_TAGS)
    body = (struct.pack(">i", 0) + compact_array([broker + uvarint(0) + NO_TAGS])
            + compact(b"cluster") + struct.pack(">i", 1) + compact_array([topic]) + NO_TAGS)
    return kafka_response(corr, NO_TAGS + body)


def fetch_v16_answer(corr, parts):
    """parts: [(topic id, partition, high watermark, records)]."""
    topics = []
    for tid, partition, high, records in parts:
        part = (struct.pack(">ihqqq", partition, 0, high, high, 0) + uvarint(0)
                + struct.pack(">i", -1) + compact(records) + NO_TAGS)
        topics.append(tid + compact_array([part]) + NO_TAGS)
    body = struct.pack(">ihi", 0, 0, 7) + compact_array(topics) + NO_TAGS
    return kafka_response(corr, NO_TAGS + body)


def crc32c_bitwise(data):
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def record(delta, key, value):
    body = (b"\x00" + varint(0) + varint(delta) + varint(len(key)) + key + varint(len(value))
            + value + b"\x00")
    return varint(len(body)) + body


def batch(base, records, attributes=0, count=None, crc=None, magic=2):
    count = len(records) if count is None else count
    after = struct.pack(">hiqqqhii", attributes, count - 1, 0, 0, -1, -1, -1,
                        count) + b"".join(records)
    tail = struct.pack(">ibI", 0, magic, crc32c_bitwise(after) if crc is None else crc) + after
    return struct.pack(">qi", base, len(tail)) + tail


def value(eid):
    return b'{"event_id":"' + eid + b'","t_sim_seconds":0}'


#: Copied from law_u2000_r001-U2000-kafka-l0-a1's journals: the producer's produce request with
#: correlation id 116, one record (constant-000400), its answer (base offset 400), and the
#: consumer's fetch request 69 and its answer, offsets 400 and 401 in a batch each.
PRODUCE_V8_REQUEST = bytes.fromhex(
    "000001ac000000080000007400176b61666b612d707974686f6e2d70726f64756365722d31ffffffff0000753000"
    "000001002a73622d6576656e74732d6c61775f75323030305f723030312d55323030302d6b61666b612d6c302d61"
    "3100000001000000000000014700000000000000000000013b00000000027036bc50000000000000000001a164f0"
    "5155000001a164f05155ffffffffffffffffffffffffffff0000000190040000001e636f6e7374616e742d303030"
    "343030e4037b2272756e5f6964223a226c61775f75323030305f723030312d55323030302d6b61666b612d6c302d"
    "6131222c226d617463685f6964223a3930303030302c226576656e745f6964223a22636f6e7374616e742d303030"
    "343030222c22745f73696d5f7365636f6e6473223a302c22745f656d69745f6f66667365745f73223a302e322c22"
    "745f656d69745f706c616e6e65645f6e73223a313739323639343833333439333239373832322c2273335f756964"
    "223a223930303030303a636f6e7374616e742d303030343030222c2273335f726576223a312c2273335f69735f63"
    "6f7272656374696f6e223a66616c73657d00"
)
PRODUCE_V8_RESPONSE = bytes.fromhex(
    "000000600000007400000001002a73622d6576656e74732d6c61775f75323030305f723030312d55323030302d6b"
    "61666b612d6c302d6131000000010000000000000000000000000190ffffffffffffffff00000000000000000000"
    "0000ffff00000000"
)
FETCH_V10_REQUEST = bytes.fromhex(
    "000000890001000a0000004500126b61666b612d707974686f6e2d322e332e32ffffffff000001f4000000010320"
    "0000001106b3f10000004000000001002a73622d6576656e74732d6c61775f75323030305f723030312d55323030"
    "302d6b61666b612d6c302d61310000000100000000ffffffff0000000000000190ffffffffffffffff0010000000"
    "000000"
)
FETCH_V10_RESPONSE = bytes.fromhex(
    "000002f9000000450000000000001106b3f100000001002a73622d6576656e74732d6c61775f75323030305f7230"
    "30312d55323030302d6b61666b612d6c302d61310000000100000000000000000000000001920000000000000192"
    "0000000000000000ffffffff0000029100000000000001900000013b00000000027036bc50000000000000000001"
    "a164f05155000001a164f05155ffffffffffffffffffffffffffff0000000190040000001e636f6e7374616e742d"
    "303030343030e4037b2272756e5f6964223a226c61775f75323030305f723030312d55323030302d6b61666b612d"
    "6c302d6131222c226d617463685f6964223a3930303030302c226576656e745f6964223a22636f6e7374616e742d"
    "303030343030222c22745f73696d5f7365636f6e6473223a302c22745f656d69745f6f66667365745f73223a302e"
    "322c22745f656d69745f706c616e6e65645f6e73223a313739323639343833333439333239373832322c2273335f"
    "756964223a223930303030303a636f6e7374616e742d303030343030222c2273335f726576223a312c2273335f69"
    "735f636f7272656374696f6e223a66616c73657d0000000000000001910000013e00000000022c9d2fd900000000"
    "0000000001a164f05155000001a164f05155ffffffffffffffffffffffffffff0000000196040000001e636f6e73"
    "74616e742d303030343031ea037b2272756e5f6964223a226c61775f75323030305f723030312d55323030302d6b"
    "61666b612d6c302d6131222c226d617463685f6964223a3930303030302c226576656e745f6964223a22636f6e73"
    "74616e742d303030343031222c22745f73696d5f7365636f6e6473223a302c22745f656d69745f6f66667365745f"
    "73223a302e323030352c22745f656d69745f706c616e6e65645f6e73223a31373932363934383333343933373930"
    "3638322c2273335f756964223a223930303030303a636f6e7374616e742d303030343031222c2273335f72657622"
    "3a312c2273335f69735f636f7272656374696f6e223a66616c73657d00"
)
TOPIC = "sb-events-law_u2000_r001-U2000-kafka-l0-a1"
TID = bytes(range(1, 17))


def kafka_world(root):
    """A Kafka run and where each frame lies in its stream. Two producer connections: the kit's
    client, with the copied produce request split over two packets and sent again later, a request
    the broker refused, one of a version not read here and one still unanswered; and a client
    of flexible versions, whose metadata response names the topic's id and whose produce request
    names the topic by it. Two consumer connections: the kit's, with the copied fetch and its
    answer captured out of order, then a fetch by topic id; and one whose opening the capture
    missed and one of whose packets it lost."""
    kit = Wire(DRIVER, 40001, KAFKA_PORT)
    where = {"p116": kit.carry(True, 300, PRODUCE_V8_REQUEST[:200])}
    kit.carry(True, 310, PRODUCE_V8_REQUEST[200:])
    kit.control(False, 320, 0x10)
    kit.again(True, 2000, where["p116"] + 200, where["p116"] + len(PRODUCE_V8_REQUEST))
    kit.carry(False, 500, PRODUCE_V8_RESPONSE)
    kit.carry(True, 700, produce_v8(118, TOPIC.encode(), 0,
                                    batch(0, [record(0, b"constant-000700", b"v")])))
    kit.carry(False, 750, produce_v8_answer(118, TOPIC.encode(), 0, 6, -1))
    kit.carry(True, 800, kafka_request(0, 2, 119, b"\x00\x00"))
    kit.carry(False, 850, kafka_response(119, b"\x00"))
    kit.carry(True, 900, produce_v8(120, TOPIC.encode(), 0,
                                    batch(0, [record(0, b"constant-000800", b"v")])))
    kit.carry(True, 950, b"\x00\x00\x01\x00" + b"\x00" * 10)
    flexible = Wire(DRIVER, 40002, KAFKA_PORT)
    flexible.control(True, 2, 0x02)
    flexible.carry(True, 100, kafka_request(3, 12, 1, NO_TAGS + b"\x01" + NO_TAGS, b"producer-1"))
    flexible.carry(False, 200, metadata_v12_answer(1, TOPIC.encode(), TID))
    sent_500 = batch(0, [record(0, b"constant-000500", value(b"constant-000500")),
                         record(1, b"constant-000501", value(b"constant-000501"))])
    where["p2"] = flexible.carry(True, 600, produce_v13(2, TID, 0, sent_500))
    flexible.carry(False, 650, produce_v13_answer(2, TID, 0, 500))

    consumer = Wire(RECEIVER, 45770, KAFKA_PORT)
    consumer.carry(True, 50, kafka_request(18, 4, 1, NO_TAGS))
    consumer.carry(False, 60, kafka_response(1, b"\x00\x00"))
    consumer.carry(True, 1000, FETCH_V10_REQUEST)
    where["f69"] = consumer.carry(False, 1200, FETCH_V10_RESPONSE[:450])
    consumer.carry(False, 1220, FETCH_V10_RESPONSE[450:600])
    consumer.carry(False, 1210, FETCH_V10_RESPONSE[600:])
    consumer.carry(True, 1500, kafka_request(1, 16, 70, NO_TAGS + b"\x00"))
    got_500 = batch(500, [record(0, b"constant-000500", value(b"constant-000500")),
                          record(1, b"constant-000599", value(b"constant-000599"))])
    again_400 = batch(400, [record(0, b"constant-000400", value(b"constant-000400"))])
    broken = batch(450, [record(0, b"constant-000450", b"v")], crc=1)
    marker = batch(460, [record(0, b"\x00\x00\x00\x00", b"\x00\x00\x00\x00\x00\x00")],
                   attributes=0x30)
    packed = batch(600, [b"gzip bytes, not read"], attributes=1, count=2)
    cut = batch(700, [record(0, b"constant-000700", b"v")])[:-5]
    answer_70 = fetch_v16_answer(70, [(TID, 0, 602, got_500 + again_400 + broken + marker
                                       + packed + cut),
                                      (TID, 1, 0, batch(0, [record(0, b"k", b"v")], magic=1))])
    where["f70"] = consumer.carry(False, 1600, answer_70)
    where["packed_end"] = answer_70.index(packed) + len(packed)
    consumer.carry(True, 1700, kafka_request(1, 3, 71))
    consumer.carry(False, 1750, kafka_response(71, b"\x00" * 8))
    consumer.carry(True, 1800, kafka_request(1, 10, 72))
    late = Wire(RECEIVER, 45780, KAFKA_PORT, opened=False)
    late.carry(True, 1100, kafka_request(1, 10, 5))
    answer_5 = kafka_response(5, b"\x00" * 36)
    late.carry(False, 1150, answer_5[:10])
    late.lose(False, answer_5[10:20])
    late.carry(False, 1170, answer_5[20:])

    noise = [(at(5), ip_tcp(OTHER, BROKER, 40003, KAFKA_PORT, 1, b"constant-000001")),
             (at(6), ip_tcp(DRIVER, BROKER, 40001, 22, 1, b"ssh")),
             (at(7), ip_tcp(DRIVER, BROKER, 40001, KAFKA_PORT, 1, b"udp", proto=17))]
    run = write_run(root, "law_u2000_r001-U2000-kafka-l0-a1", "kafka", [kit, flexible],
                    [consumer, late], noise)
    with open(os.path.join(run, "sender_full.pcap"), "ab") as fh:
        frame = ether(b"\x60" + b"\0" * 39, proto=0x86DD)
        fh.write(struct.pack("<IIII", T0 // 10**9, 8000, len(frame), len(frame)) + frame)
    return run, where


# --- Redis's frames -------------------------------------------------------------------------------

def resp(*words):
    return b"*%d\r\n" % len(words) + b"".join(b"$%d\r\n%s\r\n" % (len(w), w) for w in words)


STREAM = b"sb:events:law_u2000_r001-U2000-redis-l0-a1"
VALUE_14 = (b'{"run_id":"law_u2000_r001-U2000-redis-l0-a1","match_id":900000,"event_id":"constant-'
            b'000014","t_sim_seconds":0,"t_emit_offset_s":0.007,"t_emit_planned_ns":1792694468125'
            b'142222,"s3_uid":"900000:constant-000014","s3_rev":1,"s3_is_correction":false}')
#: Copied from law_u2000_r001-U2000-redis-l0-a1's journals: the producer's library announcing
#: itself, its XADD of constant-000014 and the id the broker gave it; the consumer's XREADGROUP.
CLIENT_SETINFO = b"*4\r\n$6\r\nCLIENT\r\n$7\r\nSETINFO\r\n$8\r\nLIB-NAME\r\n$8\r\nredis-py\r\n"
XADD_14 = (b"*5\r\n$4\r\nXADD\r\n$42\r\n" + STREAM + b"\r\n$1\r\n*\r\n$5\r\nvalue\r\n$244\r\n"
           + VALUE_14 + b"\r\n")
XADD_14_REPLY = b"$15\r\n1792694468149-1\r\n"
XREADGROUP = (b"*11\r\n$10\r\nXREADGROUP\r\n$5\r\nGROUP\r\n$41\r\nsb-group:law_u2000_r001-U2000-red"
              b"is-l0-a1\r\n$34\r\nc-law_u2000_r001-U2000-redis-l0-a1\r\n$5\r\nCOUNT\r\n$3\r\n200\r"
              b"\n$5\r\nBLOCK\r\n$4\r\n1000\r\n$7\r\nSTREAMS\r\n$42\r\n" + STREAM
              + b"\r\n$1\r\n>\r\n")


def entry(entry_id, eid=None):
    """An entry as XREAD and XREADGROUP carry it: its id, then its fields."""
    fields = VALUE_14 if eid is None else value(eid)
    return (b"*2\r\n$%d\r\n%s\r\n*2\r\n$5\r\nvalue\r\n$%d\r\n%s\r\n"
            % (len(entry_id), entry_id, len(fields), fields))


def redis_world(root):
    """A Redis run and where its commands and entries lie. Two producer connections: the kit's
    client in RESP2, with the copied XADD split over two packets, an XADD the broker refused, a
    PING and an XADD still unanswered; and a RESP3 client, whose HELLO is answered with a map and
    whose XADD's reply follows a push message. One consumer connection: a read that timed out,
    the copied XREADGROUP answered in two packets, an acknowledgment, an XREAD of two streams, and
    an XREADGROUP answered in RESP3, an attribute before its map, carrying one entry again and one
    whose fields were deleted."""
    kit = Wire(DRIVER, 47560, REDIS_PORT)
    kit.carry(True, 100, CLIENT_SETINFO)
    kit.carry(False, 110, b"+OK\r\n")
    where = {"x14": kit.carry(True, 200, XADD_14[:100])}
    kit.carry(True, 205, XADD_14[100:])
    kit.carry(False, 230, XADD_14_REPLY)
    kit.carry(True, 300, resp(b"XADD", STREAM, b"*", b"value", value(b"constant-000015")))
    kit.carry(False, 320, b"-ERR no such stream\r\n")
    kit.carry(True, 400, resp(b"PING"))
    kit.carry(False, 410, b"+PONG\r\n")
    kit.carry(True, 500, resp(b"XADD", STREAM, b"*", b"value", value(b"constant-000016")))
    resp3 = Wire(DRIVER, 47562, REDIS_PORT)
    resp3.carry(True, 150, resp(b"HELLO", b"3"))
    resp3.carry(False, 160, b"%2\r\n$6\r\nserver\r\n$5\r\nredis\r\n$5\r\nproto\r\n:3\r\n")
    resp3.carry(False, 165, b">2\r\n$10\r\ninvalidate\r\n*1\r\n$1\r\nk\r\n")
    where["x17"] = resp3.carry(True, 600, resp(b"XADD", STREAM, b"*", b"value",
                                               value(b"constant-000017")))
    resp3.carry(False, 640, b"$15\r\n1792694468150-0\r\n")

    consumer = Wire(RECEIVER, 57560, REDIS_PORT)
    consumer.carry(True, 50, CLIENT_SETINFO)
    consumer.carry(False, 55, b"+OK\r\n")
    consumer.carry(True, 60, resp(b"XGROUP", b"CREATE", STREAM, b"g", b"0-0", b"MKSTREAM"))
    consumer.carry(False, 65, b"+OK\r\n")
    consumer.carry(True, 70, XREADGROUP)
    consumer.carry(False, 170, b"*-1\r\n")
    consumer.carry(True, 180, XREADGROUP)
    reply = (b"*1\r\n*2\r\n$42\r\n" + STREAM + b"\r\n*1\r\n" + entry(b"1792694468149-1"))
    where["r149"] = consumer.carry(False, 240, reply[:150])
    consumer.carry(False, 250, reply[150:])
    where["r149_end"] = len(reply)
    consumer.carry(True, 260, resp(b"XACK", STREAM, b"g", b"1792694468149-1"))
    consumer.carry(False, 270, b":1\r\n")
    consumer.carry(True, 700, resp(b"XREAD", b"COUNT", b"10", b"STREAMS", STREAM, b"other",
                                   b"0", b"0"))
    two = (b"*2\r\n*2\r\n$42\r\n" + STREAM + b"\r\n*1\r\n" + entry(b"1792694468150-0",
                                                                   b"constant-000017")
           + b"*2\r\n$5\r\nother\r\n*1\r\n*2\r\n$3\r\n5-1\r\n*2\r\n$1\r\nf\r\n$1\r\nv\r\n")
    where["r150"] = consumer.carry(False, 720, two)
    consumer.carry(True, 800, XREADGROUP)
    noted = (b"|1\r\n+key-popularity\r\n%1\r\n$1\r\na\r\n,0.19\r\n%1\r\n$42\r\n" + STREAM
             + b"\r\n*2\r\n" + entry(b"1792694468149-1") + b"*2\r\n$15\r\n1792694468151-0\r\n_\r\n")
    where["r151"] = consumer.carry(False, 820, noted)
    consumer.carry(True, 900, XREADGROUP)
    return write_run(root, "law_u2000_r001-U2000-redis-l0-a1", "redis", [kit, resp3],
                     [consumer]), where


# --- the pieces -----------------------------------------------------------------------------------

class TestSent:
    def test_each_byte_keeps_the_first_packet_that_carried_it(self):
        s = cw.Sent()
        s.add(10, 0, 100)
        s.add(20, 150, 200)
        assert s.at(120) is None, "a gap the capture missed"
        s.add(30, 100, 160)
        s.add(40, 0, 50)
        s.add(50, 180, 260)
        assert (s.starts, s.ends, s.times) == ([0, 100, 150, 200], [100, 150, 200, 260],
                                               [10, 30, 20, 50])
        assert [s.at(o) for o in (-1, 0, 99, 100, 149, 150, 259, 260)] == [
            None, 10, 10, 30, 30, 20, 50, None]


class TestResp:
    @pytest.mark.parametrize("raw,kind,value", [
        (b"+OK\r\n", "+", b"OK"), (b"-ERR no\r\n", "-", b"ERR no"), (b":12\r\n", ":", b"12"),
        (b"_\r\n", "_", None), (b"#t\r\n", "#", b"t"), (b",0.19\r\n", ",", b"0.19"),
        (b"(3492890328409238509324850943850943825024385\r\n", "(",
         b"3492890328409238509324850943850943825024385"),
        (b"$3\r\nabc\r\n", "$", b"abc"), (b"$-1\r\n", "$", None), (b"$0\r\n\r\n", "$", b""),
        (b"!3\r\nerr\r\n", "!", b"err"), (b"=7\r\ntxt:abc\r\n", "=", b"txt:abc"),
        (b"*-1\r\n", "*", None)])
    def test_single_values_of_every_kind(self, raw, kind, value):
        assert cw.resp_value(raw, 0) == (ord(kind), 0, len(raw), value)

    def test_collections(self):
        raw = b"*2\r\n:1\r\n*1\r\n$1\r\nx\r\n"
        assert cw.resp_value(raw, 0) == (ord("*"), 0, len(raw), [
            (ord(":"), 4, 8, b"1"), (ord("*"), 8, len(raw), [(ord("$"), 12, len(raw), b"x")])])
        for raw, n in ((b"~2\r\n+a\r\n+b\r\n", 2), (b"%1\r\n+k\r\n:5\r\n", 2),
                       (b">2\r\n+message\r\n+hi\r\n", 2)):
            got = cw.resp_value(raw, 0)
            assert got[2] == len(raw) and len(got[3]) == n

    def test_an_attribute_is_read_past_to_the_value_it_notes(self):
        raw = b"|1\r\n+ttl\r\n:3600\r\n:5\r\n"
        assert cw.resp_value(raw, 0) == (ord(":"), 0, len(raw), b"5")
        assert cw.resp_value(raw[:-4], 0) is None, "the noted value has not arrived"

    @pytest.mark.parametrize("raw", [b"", b"+OK", b"$3\r\nab", b"*2\r\n:1\r\n", b"|1\r\n+a\r\n"])
    def test_a_value_cut_short_is_none(self, raw):
        assert cw.resp_value(raw, 0) is None

    def test_what_is_not_resp_is_refused(self):
        with pytest.raises(kw.WireError, match="not a RESP value"):
            cw.resp_value(b"PING\r\n", 0)
        with pytest.raises(kw.WireError, match="no length"):
            cw.resp_value(b"$?\r\n;4\r\nHell\r\n", 0)

    def test_items_stop_where_the_stream_stops_reading(self):
        assert cw.resp_items(b"+OK\r\n:1\r\n") == ([(ord("+"), 0, 5, b"OK"),
                                                     (ord(":"), 5, 9, b"1")], 9)
        assert cw.resp_items(b"+OK\r\n$5\r\nab")[1] == 5
        assert cw.resp_items(b"+OK\r\nPING\r\n")[1] == 5

    def test_words_of_a_command(self):
        assert cw._words(cw.resp_value(resp(b"XACK", b"s", b"1-1"), 0)) == [b"XACK", b"s", b"1-1"]
        assert cw._words(cw.resp_value(b"*3\r\n$4\r\nPING\r\n:1\r\n$-1\r\n", 0)) == [b"PING", b""]
        assert cw._words(cw.resp_value(b"+OK\r\n", 0)) == []
        assert cw._words(cw.resp_value(b"*0\r\n", 0)) == []

    def test_entry_ids(self):
        assert cw.entry_id(cw.resp_value(b"$15\r\n1792694468149-1\r\n", 0)) == (1792694468149, 1)
        for raw in (b"$3\r\nabc\r\n", b"$-1\r\n", b"+1-1\r\n", b"$4\r\n1-1\n\r\n"):
            assert cw.entry_id(cw.resp_value(raw, 0)) is None

    def test_stream_entries_of_every_shape(self):
        two = (b"*2\r\n*2\r\n$1\r\na\r\n*2\r\n" + entry(b"1-1", b"constant-000001")
               + b"*2\r\n$3\r\n2-2\r\n_\r\n*2\r\n$1\r\nb\r\n*1\r\n" + entry(b"3-0"))
        found = cw.stream_entries(cw.resp_value(two, 0))
        assert [(s, i) for s, i, _ in found] == [("a", (1, 1)), ("a", (2, 2)), ("b", (3, 0))]
        assert cw.event_id(two, found[0][2][1], found[0][2][2]) == "constant-000001"
        mapped = b"%1\r\n$1\r\na\r\n*1\r\n" + entry(b"4-4")
        assert [(s, i) for s, i, _ in cw.stream_entries(cw.resp_value(mapped, 0))] == [
            ("a", (4, 4))]
        odd = (b"*6\r\n*1\r\n$1\r\na\r\n+x\r\n*2\r\n:1\r\n*0\r\n*2\r\n$1\r\nc\r\n+no\r\n"
               b"*2\r\n$-1\r\n*0\r\n*2\r\n$1\r\nd\r\n*3\r\n:1\r\n*0\r\n" + entry(b"5-5"))
        assert [(s, i) for s, i, _ in cw.stream_entries(cw.resp_value(odd, 0))] == [("d", (5, 5))]
        for raw in (b"*-1\r\n", b"_\r\n", b"*0\r\n", b"-NOGROUP\r\n", b"%0\r\n"):
            assert cw.stream_entries(cw.resp_value(raw, 0)) == []


class TestSmallPieces:
    def test_the_first_carrying_is_the_one_timed_first(self):
        found = {}
        cw._keep(found, "k", ("a", 30))
        cw._keep(found, "k", ("b", 40))
        cw._keep(found, "k", ("c", None))
        assert found["k"] == ("a", 30)
        cw._keep(found, "k", ("d", 20))
        assert found["k"] == ("d", 20)
        cw._keep(found, "u", ("e", None))
        cw._keep(found, "u", ("f", 50))
        assert found["u"] == ("f", 50)

    def test_event_ids_and_topic_names(self):
        assert cw.event_id(b"xx constant-000123 constant-000999", 0, 40) == "constant-000123"
        assert cw.event_id(b"xx constant-000123", 4, 18) is None
        assert cw._name({}, "alpha", None) == "alpha"
        assert cw._name({"AQID": "alpha"}, None, "AQID") == "alpha"
        assert cw._name({}, None, "AQID") == "AQID", "an id no metadata response named stays"

    def test_no_capture_no_connections(self, tmp_path):
        assert cw.connections(str(tmp_path / "none.pcap"), BROKER, KAFKA_PORT, DRIVER) == {}

    def test_a_run_of_a_broker_not_read_here_is_refused(self, tmp_path):
        run = tmp_path / "law_x"
        run.mkdir()
        (run / "queue_row.json").write_text(json.dumps({"params": {"backend": "pulsar"}}),
                                            encoding="utf-8")
        with pytest.raises(ValueError, match="names no broker read here"):
            cw.read_run(str(run), DRIVER, BROKER, RECEIVER)


# --- a Kafka run ----------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def kafka_read(tmp_path_factory):
    """(messages, exchanges, summary, where each frame lies) for the made-up Kafka run."""
    run, where = kafka_world(tmp_path_factory.mktemp("kafka"))
    return cw.read_run(run, DRIVER, BROKER, RECEIVER) + (where,)


@pytest.fixture(scope="module")
def redis_read(tmp_path_factory):
    """(messages, exchanges, summary, where each command and entry lies) for the Redis run."""
    run, where = redis_world(tmp_path_factory.mktemp("redis"))
    return cw.read_run(run, DRIVER, BROKER, RECEIVER) + (where,)


class TestKafkaRun:
    def test_the_connections_each_capture_holds(self, tmp_path):
        run, _ = kafka_world(tmp_path)
        sending = cw.connections(os.path.join(run, "sender_full.pcap"), BROKER, KAFKA_PORT, DRIVER)
        assert sorted(sending) == [40001, 40002], "other hosts, ports and protocols left out"
        assert [sending[p].opened for p in (40001, 40002)] == [2, 2]
        kit = sending[40001]
        assert kit.out_data.startswith(PRODUCE_V8_REQUEST)
        assert kit.in_data.startswith(PRODUCE_V8_RESPONSE)
        getting = cw.connections(os.path.join(run, "receiver_full.pcap"), BROKER, KAFKA_PORT,
                                 RECEIVER)
        assert sorted(getting) == [45770, 45780]
        assert getting[45780].opened == 0 and getting[45780].inb.pending

    def test_each_message_by_its_offset(self, kafka_read):
        messages, _, _, where = kafka_read
        key = [(m["topic"], m["partition"], m["offset"]) for m in messages]
        assert key == [(TOPIC, 0, o) for o in (400, 401, 500, 501, 600, 601)]
        m = dict((row["offset"], row) for row in messages)
        assert m[400] == {
            "topic": TOPIC, "partition": 0, "offset": 400, "eid_sent": "constant-000400",
            "t_depart": at(310), "t_ack": at(500), "producer_port": 40001, "request": 116,
            "sent_byte": where["p116"] + len(PRODUCE_V8_REQUEST) - 1,
            "eid_got": "constant-000400", "t_arrive": at(1200), "consumer_port": 45770,
            "exchange": 1, "got_byte": where["f69"] + 434}
        assert (m[401]["eid_sent"], m[401]["t_depart"], m[401]["eid_got"], m[401]["t_arrive"],
                m[401]["got_byte"]) == (None, None, "constant-000401", at(1220),
                                        where["f69"] + len(FETCH_V10_RESPONSE) - 1)
        assert (m[500]["eid_sent"], m[500]["t_depart"], m[500]["t_ack"], m[500]["producer_port"],
                m[500]["request"], m[500]["t_arrive"], m[500]["exchange"]) == (
            "constant-000500", at(600), at(650), 40002, 2, at(1600), 2)
        assert (m[501]["eid_sent"], m[501]["eid_got"]) == ("constant-000501", "constant-000599")
        for o in (600, 601):
            assert (m[o]["eid_got"], m[o]["t_arrive"], m[o]["got_byte"]) == (
                None, at(1600), where["f70"] + where["packed_end"] - 1)

    def test_every_consumer_exchange_in_order(self, kafka_read):
        _, exchanges, _, _ = kafka_read
        rows = [(r["consumer_port"], r["exchange"], r["kind"], r["version"], r["corr"], r["t_req"],
                 r["t_ans"], r["carried"]) for r in exchanges]
        assert rows == [(45770, 0, "ApiVersions", 4, 1, at(50), at(60), 0),
                        (45770, 1, "Fetch", 10, 69, at(1000), at(1220), 2),
                        (45770, 2, "Fetch", 16, 70, at(1500), at(1600), 5),
                        (45770, 3, "Fetch", 3, 71, at(1700), at(1750), 0),
                        (45770, 4, "Fetch", 10, 72, at(1800), None, 0),
                        (45780, 0, "Fetch", 10, 5, at(1100), None, 0)]
        assert exchanges[1]["ids"] == "%s:0:400;%s:0:401" % (TOPIC, TOPIC)
        assert exchanges[2]["ids"] == ";".join("%s:0:%d" % (TOPIC, o)
                                               for o in (500, 501, 400, 600, 601))
        assert exchanges[0]["ids"] == ""

    def test_what_it_counted_and_could_not_read(self, kafka_read):
        _, _, summary, _ = kafka_read
        assert summary == {
            "backend": "kafka", "producer_connections": 2, "consumer_connections": 2,
            "unopened": 1, "holes": 1, "unframed": 14 + 10,
            "produced": 3, "consumed": 6, "matched": 3, "sent_only": 0, "got_only": 3,
            "ids_unread": 0, "ids_differ": 1, "exchanges": 6, "answered": 4, "carried": 7,
            "unreadable": 4, "first_unreadable": "Produce version 2 is not read here",
            "batches": 10, "crc_failed": 1, "cut": 1, "compressed": 1, "control": 1,
            "produce_requests": 5, "produce_unanswered": 1, "produce_unkeyed": 1,
            "xadd": 0, "xadd_unkeyed": 0}

    def test_a_port_named_on_the_command_line_is_the_one_read(self, tmp_path):
        run, _ = kafka_world(tmp_path)
        messages, exchanges, summary = cw.read_run(run, DRIVER, BROKER, RECEIVER, port=9092)
        assert (messages, exchanges, summary["producer_connections"]) == ([], [], 0)

    def test_the_command_line_writes_both_tables(self, tmp_path, capsys):
        run, _ = kafka_world(tmp_path)
        out_m, out_x = str(tmp_path / "t" / "messages.csv"), str(tmp_path / "t" / "exchanges.csv")
        assert cw.main(["--run", run, "--driver", DRIVER, "--broker", BROKER, "--receiver",
                        RECEIVER, "--out-messages", out_m, "--out-exchanges", out_x]) == 0
        with open(out_m, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert list(rows[0]) == list(cw.KEY_FIELDS["kafka"] + cw.MESSAGE_FIELDS)
        assert [r["offset"] for r in rows] == ["400", "401", "500", "501", "600", "601"]
        assert rows[1]["t_depart"] == "" and rows[0]["t_depart"] == str(at(310))
        with open(out_x, encoding="utf-8", newline="") as fh:
            assert [r["kind"] for r in csv.DictReader(fh)] == ["ApiVersions"] + ["Fetch"] * 5
        said = capsys.readouterr().out
        assert "6 messages by the broker's ids: 3 both ways, 0 only sent, 3 only received" in said
        assert "event ids differ for 1; 4 of 6 consumer requests answered" in said


# --- a Redis run ----------------------------------------------------------------------------------

class TestRedisRun:
    def test_each_message_by_its_entry_id(self, redis_read):
        messages, _, _, where = redis_read
        assert [(m["stream"], m["redis_id"]) for m in messages] == [
            ("other", "5-1"), (STREAM.decode(), "1792694468149-1"),
            (STREAM.decode(), "1792694468150-0"), (STREAM.decode(), "1792694468151-0")]
        other, sent_14, sent_17, deleted = messages
        assert sent_14 == {
            "stream": STREAM.decode(), "redis_id": "1792694468149-1",
            "eid_sent": "constant-000014", "t_depart": at(205), "t_ack": at(230),
            "producer_port": 47560, "request": 1, "sent_byte": where["x14"] + len(XADD_14) - 1,
            "eid_got": "constant-000014", "t_arrive": at(250), "consumer_port": 57560,
            "exchange": 3, "got_byte": where["r149"] + where["r149_end"] - 1}
        assert (sent_17["eid_sent"], sent_17["t_depart"], sent_17["t_ack"],
                sent_17["producer_port"], sent_17["request"], sent_17["eid_got"],
                sent_17["t_arrive"], sent_17["exchange"]) == (
            "constant-000017", at(600), at(640), 47562, 1, "constant-000017", at(720), 5)
        assert (other["eid_got"], other["t_arrive"], other["eid_sent"]) == (None, at(720), None)
        assert (deleted["eid_got"], deleted["t_arrive"], deleted["exchange"]) == (None, at(820),
                                                                                  6)

    def test_every_consumer_exchange_in_order(self, redis_read):
        _, exchanges, _, _ = redis_read
        rows = [(r["exchange"], r["kind"], r["version"], r["corr"], r["t_req"], r["t_ans"],
                 r["carried"]) for r in exchanges]
        assert rows == [(0, "CLIENT", None, None, at(50), at(55), 0),
                        (1, "XGROUP", None, None, at(60), at(65), 0),
                        (2, "XREADGROUP", None, None, at(70), at(170), 0),
                        (3, "XREADGROUP", None, None, at(180), at(250), 1),
                        (4, "XACK", None, None, at(260), at(270), 0),
                        (5, "XREAD", None, None, at(700), at(720), 2),
                        (6, "XREADGROUP", None, None, at(800), at(820), 2),
                        (7, "XREADGROUP", None, None, at(900), None, 0)]
        stream = STREAM.decode()
        assert exchanges[5]["ids"] == "%s:1792694468150-0;other:5-1" % stream
        assert exchanges[6]["ids"] == "%s:1792694468149-1;%s:1792694468151-0" % (stream, stream)

    def test_what_it_counted(self, redis_read):
        _, _, summary, _ = redis_read
        assert {k: summary[k] for k in ("producer_connections", "consumer_connections",
                                        "unopened", "holes", "unframed", "produced", "consumed",
                                        "matched", "sent_only", "got_only", "ids_unread",
                                        "ids_differ", "exchanges", "answered", "carried",
                                        "unreadable", "batches", "xadd", "xadd_unkeyed")} == {
            "producer_connections": 2, "consumer_connections": 1, "unopened": 0, "holes": 0,
            "unframed": 0, "produced": 2, "consumed": 4, "matched": 2, "sent_only": 0,
            "got_only": 2, "ids_unread": 0, "ids_differ": 0, "exchanges": 8, "answered": 7,
            "carried": 5, "unreadable": 0, "batches": 0, "xadd": 4, "xadd_unkeyed": 2}

    def test_the_command_line_writes_redis_columns(self, tmp_path, capsys):
        run, _ = redis_world(tmp_path)
        out_m, out_x = str(tmp_path / "m.csv"), str(tmp_path / "x.csv")
        cw.main(["--run", run, "--driver", DRIVER, "--broker", BROKER, "--receiver", RECEIVER,
                 "--out-messages", out_m, "--out-exchanges", out_x, "--port", str(REDIS_PORT)])
        with open(out_m, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert list(rows[0]) == list(cw.KEY_FIELDS["redis"] + cw.MESSAGE_FIELDS)
        assert rows[1]["redis_id"] == "1792694468149-1" and rows[1]["producer_port"] == "47560"
        assert "4 messages by the broker's ids: 2 both ways" in capsys.readouterr().out
