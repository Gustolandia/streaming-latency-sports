"""Tests for scripts/kafka_wire.py: Kafka's ids read from the wire.

Two kinds of frame. Frames copied byte for byte from a judged run's journals (block U, 2,000 a
second, Kafka idle; kafka-python 2.3.2 against a Kafka 4.1.1 broker): Produce v8, Fetch v10 and
Metadata v8, the versions the kit's clients send. And frames written here, at every version the
module reads, by an encoder driven by Apache Kafka's own message schemas: SCHEMAS below holds the
fields of ProduceRequest.json, ProduceResponse.json, FetchResponse.json and MetadataResponse.json
(clients/src/main/resources/common/message/ in apache/kafka at 4.1.1), each with the versions it
appears in, the versions it may be null in, and the versions it is a tagged field in, as the files
give them. The encoder applies the protocol's general rules to those fields and knows nothing of
the reader's code, so the flexible versions no client of the kit sends yet are held to the schemas,
not to the reader's own idea of them; and the encoder is itself held to the real frames, which it
must write again byte for byte.
"""
import base64
import os
import random
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import kafka_wire as kw  # noqa: E402

# --- the schemas ----------------------------------------------------------------------------------

#: Each message's valid versions, its flexible versions, and its fields: (name, type, versions,
#: nullable versions, tagged versions, tag, the fields of a structure it holds).
SCHEMAS = {
    'ProduceRequest': ('3-13', '9+', [
        ('TransactionalId', 'string', '3+', '3+', 'none', None, []),
        ('Acks', 'int16', '0+', 'none', 'none', None, []),
        ('TimeoutMs', 'int32', '0+', 'none', 'none', None, []),
        ('TopicData', '[]TopicProduceData', '0+', 'none', 'none', None, [
            ('Name', 'string', '0-12', 'none', 'none', None, []),
            ('TopicId', 'uuid', '13+', 'none', 'none', None, []),
            ('PartitionData', '[]PartitionProduceData', '0+', 'none', 'none', None, [
                ('Index', 'int32', '0+', 'none', 'none', None, []),
                ('Records', 'records', '0+', '0+', 'none', None, []),
            ]),
        ]),
    ]),
    'ProduceResponse': ('3-13', '9+', [
        ('Responses', '[]TopicProduceResponse', '0+', 'none', 'none', None, [
            ('Name', 'string', '0-12', 'none', 'none', None, []),
            ('TopicId', 'uuid', '13+', 'none', 'none', None, []),
            ('PartitionResponses', '[]PartitionProduceResponse', '0+', 'none', 'none', None, [
                ('Index', 'int32', '0+', 'none', 'none', None, []),
                ('ErrorCode', 'int16', '0+', 'none', 'none', None, []),
                ('BaseOffset', 'int64', '0+', 'none', 'none', None, []),
                ('LogAppendTimeMs', 'int64', '2+', 'none', 'none', None, []),
                ('LogStartOffset', 'int64', '5+', 'none', 'none', None, []),
                ('RecordErrors', '[]BatchIndexAndErrorMessage', '8+', 'none', 'none', None, [
                    ('BatchIndex', 'int32', '8+', 'none', 'none', None, []),
                    ('BatchIndexErrorMessage', 'string', '8+', '8+', 'none', None, []),
                ]),
                ('ErrorMessage', 'string', '8+', '8+', 'none', None, []),
                ('CurrentLeader', 'LeaderIdAndEpoch', '10+', 'none', '10+', 0, [
                    ('LeaderId', 'int32', '10+', 'none', 'none', None, []),
                    ('LeaderEpoch', 'int32', '10+', 'none', 'none', None, []),
                ]),
            ]),
        ]),
        ('ThrottleTimeMs', 'int32', '1+', 'none', 'none', None, []),
        ('NodeEndpoints', '[]NodeEndpoint', '10+', 'none', '10+', 0, [
            ('NodeId', 'int32', '10+', 'none', 'none', None, []),
            ('Host', 'string', '10+', 'none', 'none', None, []),
            ('Port', 'int32', '10+', 'none', 'none', None, []),
            ('Rack', 'string', '10+', '10+', 'none', None, []),
        ]),
    ]),
    'FetchResponse': ('4-18', '12+', [
        ('ThrottleTimeMs', 'int32', '1+', 'none', 'none', None, []),
        ('ErrorCode', 'int16', '7+', 'none', 'none', None, []),
        ('SessionId', 'int32', '7+', 'none', 'none', None, []),
        ('Responses', '[]FetchableTopicResponse', '0+', 'none', 'none', None, [
            ('Topic', 'string', '0-12', 'none', 'none', None, []),
            ('TopicId', 'uuid', '13+', 'none', 'none', None, []),
            ('Partitions', '[]PartitionData', '0+', 'none', 'none', None, [
                ('PartitionIndex', 'int32', '0+', 'none', 'none', None, []),
                ('ErrorCode', 'int16', '0+', 'none', 'none', None, []),
                ('HighWatermark', 'int64', '0+', 'none', 'none', None, []),
                ('LastStableOffset', 'int64', '4+', 'none', 'none', None, []),
                ('LogStartOffset', 'int64', '5+', 'none', 'none', None, []),
                ('DivergingEpoch', 'EpochEndOffset', '12+', 'none', '12+', 0, [
                    ('Epoch', 'int32', '12+', 'none', 'none', None, []),
                    ('EndOffset', 'int64', '12+', 'none', 'none', None, []),
                ]),
                ('CurrentLeader', 'LeaderIdAndEpoch', '12+', 'none', '12+', 1, [
                    ('LeaderId', 'int32', '12+', 'none', 'none', None, []),
                    ('LeaderEpoch', 'int32', '12+', 'none', 'none', None, []),
                ]),
                ('SnapshotId', 'SnapshotId', '12+', 'none', '12+', 2, [
                    ('EndOffset', 'int64', '0+', 'none', 'none', None, []),
                    ('Epoch', 'int32', '0+', 'none', 'none', None, []),
                ]),
                ('AbortedTransactions', '[]AbortedTransaction', '4+', '4+', 'none', None, [
                    ('ProducerId', 'int64', '4+', 'none', 'none', None, []),
                    ('FirstOffset', 'int64', '4+', 'none', 'none', None, []),
                ]),
                ('PreferredReadReplica', 'int32', '11+', 'none', 'none', None, []),
                ('Records', 'records', '0+', '0+', 'none', None, []),
            ]),
        ]),
        ('NodeEndpoints', '[]NodeEndpoint', '16+', 'none', '16+', 0, [
            ('NodeId', 'int32', '16+', 'none', 'none', None, []),
            ('Host', 'string', '16+', 'none', 'none', None, []),
            ('Port', 'int32', '16+', 'none', 'none', None, []),
            ('Rack', 'string', '16+', '16+', 'none', None, []),
        ]),
    ]),
    'MetadataResponse': ('0-13', '9+', [
        ('ThrottleTimeMs', 'int32', '3+', 'none', 'none', None, []),
        ('Brokers', '[]MetadataResponseBroker', '0+', 'none', 'none', None, [
            ('NodeId', 'int32', '0+', 'none', 'none', None, []),
            ('Host', 'string', '0+', 'none', 'none', None, []),
            ('Port', 'int32', '0+', 'none', 'none', None, []),
            ('Rack', 'string', '1+', '1+', 'none', None, []),
        ]),
        ('ClusterId', 'string', '2+', '2+', 'none', None, []),
        ('ControllerId', 'int32', '1+', 'none', 'none', None, []),
        ('Topics', '[]MetadataResponseTopic', '0+', 'none', 'none', None, [
            ('ErrorCode', 'int16', '0+', 'none', 'none', None, []),
            ('Name', 'string', '0+', '12+', 'none', None, []),
            ('TopicId', 'uuid', '10+', 'none', 'none', None, []),
            ('IsInternal', 'bool', '1+', 'none', 'none', None, []),
            ('Partitions', '[]MetadataResponsePartition', '0+', 'none', 'none', None, [
                ('ErrorCode', 'int16', '0+', 'none', 'none', None, []),
                ('PartitionIndex', 'int32', '0+', 'none', 'none', None, []),
                ('LeaderId', 'int32', '0+', 'none', 'none', None, []),
                ('LeaderEpoch', 'int32', '7+', 'none', 'none', None, []),
                ('ReplicaNodes', '[]int32', '0+', 'none', 'none', None, []),
                ('IsrNodes', '[]int32', '0+', 'none', 'none', None, []),
                ('OfflineReplicas', '[]int32', '5+', 'none', 'none', None, []),
            ]),
            ('TopicAuthorizedOperations', 'int32', '8+', 'none', 'none', None, []),
        ]),
        ('ClusterAuthorizedOperations', 'int32', '8-10', 'none', 'none', None, []),
        ('ErrorCode', 'int16', '13+', 'none', 'none', None, []),
    ]),
}
API_KEYS = {"ProduceRequest": 0}


# --- an encoder that follows the schemas ----------------------------------------------------------

def in_versions(spec, version):
    """Whether `version` lies in a schema's range: "none", "N+", "N" or "N-M"."""
    if spec == "none":
        return False
    if spec.endswith("+"):
        return version >= int(spec[:-1])
    low, _, high = spec.partition("-")
    return int(low) <= version <= int(high or low)


def uvarint(n):
    out = b""
    while n > 0x7F:
        out += bytes([(n & 0x7F) | 0x80])
        n >>= 7
    return out + bytes([n])


def varint(n):
    """A signed varint, zigzag-encoded, for a 64-bit value."""
    return uvarint((n << 1) ^ (n >> 63))


PRIMITIVE = {"int8": ">b", "bool": ">b", "int16": ">h", "int32": ">i", "int64": ">q"}
DEFAULT = {"int8": 0, "bool": 0, "int16": 0, "int32": 0, "int64": 0, "uuid": bytes(16),
           "string": "", "records": None}


def encode_value(kind, value, fields, version, flexible):
    if kind.startswith("[]"):
        if value is None:
            return uvarint(0) if flexible else struct.pack(">i", -1)
        head = uvarint(len(value) + 1) if flexible else struct.pack(">i", len(value))
        inner = kind[2:]
        if inner in PRIMITIVE:
            return head + b"".join(struct.pack(PRIMITIVE[inner], x) for x in value)
        return head + b"".join(encode_struct(fields, x, version, flexible) for x in value)
    if kind in PRIMITIVE:
        return struct.pack(PRIMITIVE[kind], value)
    if kind == "uuid":
        return value
    if kind in ("string", "records"):
        if value is None:
            return uvarint(0) if flexible else struct.pack(">h" if kind == "string" else ">i", -1)
        raw = value.encode() if kind == "string" else value
        if flexible:
            return uvarint(len(raw) + 1) + raw
        return struct.pack(">h" if kind == "string" else ">i", len(raw)) + raw
    return encode_struct(fields, value, version, flexible)


def encode_struct(fields, values, version, flexible):
    """A structure's fields at `version`, in order; in a flexible version its tagged fields last,
    each written only where `values` gives it one, in the order of their tags."""
    out, tagged = b"", []
    for name, kind, versions, _nullable, tagged_versions, tag, inner in fields:
        if not in_versions(versions, version):
            continue
        if in_versions(tagged_versions, version):
            if name in values:
                tagged.append((tag, encode_value(kind, values[name], inner, version, flexible)))
            continue
        value = values.get(name, [] if kind.startswith("[]") else DEFAULT.get(kind))
        out += encode_value(kind, value, inner, version, flexible)
    if flexible:
        out += uvarint(len(tagged)) + b"".join(uvarint(t) + uvarint(len(b)) + b
                                               for t, b in sorted(tagged))
    return out


#: A flexible header's tagged fields, one of each made up: the request header's version 3 adds a
#: client instance id as tag 0, and a response header may carry tags this reader does not know.
REQUEST_TAGS = uvarint(1) + uvarint(0) + uvarint(16) + bytes(range(16))
RESPONSE_TAGS = uvarint(1) + uvarint(5) + uvarint(2) + b"hi"


def encode(message, version, values, corr=7, client=b"client"):
    """A whole frame: its size, its header (a request's names its API, version, correlation id
    and client), and its body as the schema lays it out at `version`."""
    _, flexible_versions, fields = SCHEMAS[message]
    flexible = in_versions(flexible_versions, version)
    body = encode_struct(fields, values, version, flexible)
    if message in API_KEYS:
        head = struct.pack(">hhih", API_KEYS[message], version, corr, len(client)) + client
        head += REQUEST_TAGS if flexible else b""
    else:
        head = struct.pack(">i", corr) + (RESPONSE_TAGS if flexible else b"")
    return struct.pack(">i", len(head + body)) + head + body


# --- record batches, written here -----------------------------------------------------------------

def crc32c_bitwise(data):
    """CRC-32C one bit at a time, with no table: the reader's tables are checked against it."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def record(delta, key, value, headers=(), ts_delta=0):
    body = b"\x00" + varint(ts_delta) + varint(delta)
    for part in (key, value):
        body += varint(-1) if part is None else varint(len(part)) + part
    body += varint(len(headers))
    for name, part in headers:
        body += varint(len(name)) + name + (varint(-1) if part is None else
                                            varint(len(part)) + part)
    return varint(len(body)) + body


def batch(base, records, last_delta=None, attributes=0, count=None, crc=None, magic=2,
          first_ts=0x1A164F05155, epoch=0):
    """A message format v2 batch, its CRC-32C computed bit by bit unless given."""
    count = len(records) if count is None else count
    last_delta = count - 1 if last_delta is None else last_delta
    after = struct.pack(">hiqqqhii", attributes, last_delta, first_ts, first_ts, -1, -1, -1,
                        count) + b"".join(records)
    crc = crc32c_bitwise(after) if crc is None else crc
    tail = struct.pack(">ibI", epoch, magic, crc) + after
    return struct.pack(">qi", base, len(tail)) + tail


def topic_text(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


ID_A, ID_B = bytes(range(1, 17)), bytes(range(101, 117))
BATCH_A = batch(0, [record(0, b"constant-000001", b'{"event_id":"constant-000001"}'),
                    record(1, None, b"x", headers=[(b"h", None), (b"g", b"v")])])
BATCH_B = batch(0, [record(0, b"k", None)])


# --- frames copied from the judged run's journals -------------------------------------------------

#: law_u2000_r001-U2000-kafka-l0-a1: the producer's smallest produce request, correlation id 116,
#: one record (constant-000400), and the broker's answer: base offset 400.
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
#: The consumer's fetch response, correlation id 69, that delivered offsets 400 and 401, each in
#: its own batch as the producer wrote it; and an answer to a fetch with nothing new, which a
#: fetch session's answer leaves with no topic at all.
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
FETCH_V10_EMPTY = bytes.fromhex("00000012000000060000000000001106b3f100000000")
#: The producer's first answer, a metadata response, version 8: one broker, one topic.
METADATA_V8_RESPONSE = bytes.fromhex(
    "0000009e00000001000000000000000100000001000931302e322e312e323100004a94ffff00164d6b55334f4556"
    "424e5463774e544a454e444d32516b00000001000000010000002a73622d6576656e74732d6c61775f7532303030"
    "5f723030312d55323030302d6b61666b612d6c302d61310000000001000000000000000000010000000000000001"
    "000000010000000100000001000000008000000080000000"
)
TOPIC = "sb-events-law_u2000_r001-U2000-kafka-l0-a1"
#: The produce request's one batch, as the producer wrote it: offsets from 0, and its CRC.
REAL_BATCH = PRODUCE_V8_REQUEST[105:]
REAL_RECORD_KEY = b"constant-000400"


def real_value():
    """The real record's value: the event's JSON, as the producer's journal holds it."""
    start = REAL_BATCH.index(b"{")
    return REAL_BATCH[start:-1]


# --- CRC-32C --------------------------------------------------------------------------------------

class TestCrc32c:
    def test_the_published_check_values(self):
        assert kw.crc32c(b"123456789") == 0xE3069283
        assert kw.crc32c(bytes(32)) == 0x8A9136AA
        assert kw.crc32c(b"\xff" * 32) == 0x62A8AB43
        assert kw.crc32c(bytes(range(32))) == 0x46DD794E
        assert kw.crc32c(b"") == 0

    def test_the_tables_are_castagnoli_s(self):
        assert kw.TABLES[0][1] == 0xF26B8303
        assert kw.TABLES[0][128] == kw.CASTAGNOLI
        assert len(kw.TABLES) == 8 and all(len(t) == 256 for t in kw.TABLES)

    def test_eight_at_a_time_agrees_with_one_bit_at_a_time(self):
        rng = random.Random(20261023)
        data = bytes(rng.getrandbits(8) for _ in range(3000))
        for start, end in [(0, n) for n in range(0, 41)] + [(3, 3), (5, 7), (1, 2999), (7, 3000)]:
            assert kw.crc32c(data, start, end) == crc32c_bitwise(data[start:end]), (start, end)
        assert kw.crc32c(bytearray(data)) == crc32c_bitwise(data)

    def test_the_real_batch_carries_the_crc_this_computes(self):
        assert struct.unpack(">I", REAL_BATCH[17:21])[0] == kw.crc32c(REAL_BATCH, 21) == 0x7036BC50


# --- Kafka's primitive types ----------------------------------------------------------------------

class TestReader:
    def test_varints_unsigned_and_zigzag(self):
        for n in (0, 1, 127, 128, 300, 16383, 16384, 2 ** 31 - 1, 2 ** 63 - 1, 2 ** 64 - 1):
            raw = uvarint(n)
            r = kw.Reader(raw, 0, len(raw))
            assert r.uvarint() == n and r.pos == len(raw)
        for n in (0, -1, 1, -2, 2, 63, -64, 2 ** 31 - 1, -2 ** 31, -2 ** 63, 2 ** 63 - 1):
            raw = varint(n)
            assert kw.Reader(raw, 0, len(raw)).varint() == n
        assert varint(-1) == b"\x01" and varint(1) == b"\x02" and uvarint(300) == b"\xac\x02"

    def test_a_varint_longer_than_ten_bytes_is_refused(self):
        raw = b"\x80" * 10 + b"\x01"
        with pytest.raises(kw.WireError, match="longer than ten bytes"):
            kw.Reader(raw, 0, len(raw)).uvarint()

    def test_nothing_is_read_past_the_frame(self):
        r = kw.Reader(b"\x00\x01\x02\x03", 0, 2)
        with pytest.raises(kw.WireError, match="run past"):
            r.int32()
        with pytest.raises(kw.WireError, match="run past"):
            r.skip(-1)
        with pytest.raises(kw.WireError, match="run past"):
            kw.Reader(b"\x80", 0, 1).uvarint()

    def test_strings_bytes_and_arrays_old_and_flexible(self):
        old = (struct.pack(">h", 3) + b"abc" + struct.pack(">h", -1) + struct.pack(">i", 2)
               + b"xy" + struct.pack(">i", -1) + struct.pack(">i", 4))
        r = kw.Reader(old, 0, len(old))
        assert (r.string(), r.string(), r.blob(), r.blob(), r.size()) == ("abc", None, (11, 13),
                                                                            None, 4)
        r.tags()
        r.done()
        new = (uvarint(4) + b"abc" + uvarint(0) + uvarint(3) + b"xy" + uvarint(0) + uvarint(5)
               + uvarint(2) + uvarint(1) + uvarint(1) + b"z" + uvarint(9) + uvarint(0) + ID_A)
        r = kw.Reader(new, 0, len(new), compact=True)
        assert (r.string(), r.string(), r.blob(), r.blob(), r.size()) == ("abc", None, (6, 8),
                                                                            None, 4)
        r.tags()
        assert r.uuid() == topic_text(ID_A)
        r.done()
        r = kw.Reader(new, 0, len(new) + 1)
        with pytest.raises(kw.WireError, match="left unread"):
            r.done()

    def test_topic_ids_read_as_kafka_writes_them(self):
        assert kw.topic_id_text(bytes(16)) == kw.NO_TOPIC_ID == "AAAAAAAAAAAAAAAAAAAAAA"
        assert kw.topic_id_text(ID_A) == topic_text(ID_A) == "AQIDBAUGBwgJCgsMDQ4PEA"

    def test_api_names(self):
        assert kw.api_name(1) == "Fetch" and kw.api_name(18) == "ApiVersions"
        assert kw.api_name(999) == "api 999"


# --- the encoder against the real frames ----------------------------------------------------------

class TestTheEncoderWritesTheRealFramesAgain:
    """The schema-driven encoder writes the kit's real frames byte for byte, so it is the schemas,
    and not a guess, that the flexible versions are held to below."""

    def test_produce_v8_request(self):
        values = {"TransactionalId": None, "Acks": -1, "TimeoutMs": 30000, "TopicData": [
            {"Name": TOPIC, "PartitionData": [{"Index": 0, "Records": REAL_BATCH}]}]}
        assert encode("ProduceRequest", 8, values, corr=116,
                      client=b"kafka-python-producer-1") == PRODUCE_V8_REQUEST

    def test_produce_v8_response(self):
        values = {"Responses": [{"Name": TOPIC, "PartitionResponses": [
            {"Index": 0, "ErrorCode": 0, "BaseOffset": 400, "LogAppendTimeMs": -1,
             "LogStartOffset": 0, "RecordErrors": [], "ErrorMessage": None}]}],
            "ThrottleTimeMs": 0}
        assert encode("ProduceResponse", 8, values, corr=116) == PRODUCE_V8_RESPONSE

    def test_fetch_v10_response(self):
        records = FETCH_V10_RESPONSE[108:]
        values = {"ThrottleTimeMs": 0, "ErrorCode": 0, "SessionId": 0x1106B3F1, "Responses": [
            {"Topic": TOPIC, "Partitions": [
                {"PartitionIndex": 0, "ErrorCode": 0, "HighWatermark": 402,
                 "LastStableOffset": 402, "LogStartOffset": 0, "AbortedTransactions": None,
                 "Records": records}]}]}
        assert encode("FetchResponse", 10, values, corr=69) == FETCH_V10_RESPONSE
        assert encode("FetchResponse", 10, {"SessionId": 0x1106B3F1}, corr=6) == FETCH_V10_EMPTY

    def test_metadata_v8_response(self):
        values = {"ThrottleTimeMs": 0, "Brokers": [
            {"NodeId": 1, "Host": "10.2.1.21", "Port": 19092, "Rack": None}],
            "ClusterId": "MkU3OEVBNTcwNTJENDM2Qk", "ControllerId": 1, "Topics": [
            {"ErrorCode": 0, "Name": TOPIC, "IsInternal": 0, "Partitions": [
                {"ErrorCode": 0, "PartitionIndex": 0, "LeaderId": 1, "LeaderEpoch": 0,
                 "ReplicaNodes": [1], "IsrNodes": [1], "OfflineReplicas": []}],
             "TopicAuthorizedOperations": -2 ** 31}], "ClusterAuthorizedOperations": -2 ** 31}
        assert encode("MetadataResponse", 8, values, corr=1) == METADATA_V8_RESPONSE

    def test_the_batch_writer_writes_the_real_batch_again(self):
        again = batch(0, [record(0, REAL_RECORD_KEY, real_value())])
        assert again == REAL_BATCH


# --- the real frames, read ------------------------------------------------------------------------

class TestRealFrames:
    def test_the_produce_request(self):
        frame = PRODUCE_V8_REQUEST
        assert kw.request_header(frame, 0, len(frame)) == (0, 8, 116, "kafka-python-producer-1",
                                                           37)
        [(topic, tid, partition, span)] = kw.produce_request(frame, 0, len(frame), 8)
        assert (topic, tid, partition, span) == (TOPIC, None, 0, (105, len(frame)))
        batches, cut = kw.record_batches(frame, *span)
        assert cut == 0 and len(batches) == 1
        b = batches[0]
        assert (b.start, b.end, b.base_offset, b.last_delta, b.codec, b.control, b.crc_ok) == (
            105, len(frame), 0, 0, 0, False, True)
        [(delta, start, end)] = b.records
        assert (delta, start, end) == (0, 166, len(frame))
        assert frame[start:end].count(REAL_RECORD_KEY) == 3, "its key, its event id and its uid"

    def test_the_produce_response_gives_the_base_offset(self):
        frame = PRODUCE_V8_RESPONSE
        assert kw.produce_response(frame, 0, len(frame), 8) == [(TOPIC, None, 0, 0, 400)]

    def test_the_fetch_response_carries_the_stored_batches(self):
        frame = FETCH_V10_RESPONSE
        [(topic, tid, partition, error, high, span)] = kw.fetch_response(frame, 0, len(frame), 10)
        assert (topic, tid, partition, error, high, span) == (TOPIC, None, 0, 0, 402,
                                                              (108, len(frame)))
        batches, cut = kw.record_batches(frame, *span)
        assert cut == 0 and [(b.base_offset, b.crc_ok) for b in batches] == [(400, True),
                                                                             (401, True)]
        ids = [frame[s:e][frame[s:e].index(b"constant-"):][:15] for b in batches
               for _, s, e in b.records]
        assert ids == [b"constant-000400", b"constant-000401"]
        # The broker stores the batch as the producer wrote it, from its leader epoch on: only
        # the base offset differs, which the CRC does not cover.
        assert frame[span[0] + 8:batches[0].end] == REAL_BATCH[8:]
        assert kw.fetch_response(FETCH_V10_EMPTY, 0, len(FETCH_V10_EMPTY), 10) == []

    def test_the_metadata_response_carries_no_ids_at_version_8(self):
        frame = METADATA_V8_RESPONSE
        assert kw.metadata_topics(frame, 0, len(frame), 8) == {}

    def test_a_frame_read_with_the_wrong_version_fails_loudly(self):
        with pytest.raises(kw.WireError):
            kw.produce_response(PRODUCE_V8_RESPONSE, 0, len(PRODUCE_V8_RESPONSE), 9)
        with pytest.raises(kw.WireError):
            kw.fetch_response(FETCH_V10_RESPONSE, 0, len(FETCH_V10_RESPONSE), 11)
        with pytest.raises(kw.WireError, match="left unread"):
            kw.produce_response(PRODUCE_V8_RESPONSE + b"\x00", 0,
                                len(PRODUCE_V8_RESPONSE) + 1, 8)


# --- every version, written from the schemas ------------------------------------------------------

def _named(version, name, tid):
    """What the reader gives for a topic entry at `version`: the name, or the id from 13 on."""
    return (None, topic_text(tid)) if version >= 13 else (name, None)


@pytest.mark.parametrize("version", list(kw.PRODUCE_VERSIONS))
def test_every_produce_request_version(version):
    values = {"TransactionalId": "tx" if version % 2 else None, "Acks": -1, "TimeoutMs": 30000,
              "TopicData": [
                  {"Name": "alpha", "TopicId": ID_A, "PartitionData": [
                      {"Index": 0, "Records": BATCH_A}, {"Index": 3, "Records": None}]},
                  {"Name": "beta", "TopicId": ID_B, "PartitionData": [
                      {"Index": 1, "Records": BATCH_B}]}]}
    frame = encode("ProduceRequest", version, values, corr=40 + version)
    assert kw.request_header(frame, 0, len(frame))[:4] == (0, version, 40 + version, "client")
    found = kw.produce_request(frame, 0, len(frame), version)
    assert [f[:3] for f in found] == [_named(version, "alpha", ID_A) + (0,),
                                      _named(version, "alpha", ID_A) + (3,),
                                      _named(version, "beta", ID_B) + (1,)]
    spans = [f[3] for f in found]
    assert frame[slice(*spans[0])] == BATCH_A and spans[1] is None
    assert frame[slice(*spans[2])] == BATCH_B
    empty = encode("ProduceRequest", version, {"TopicData": []})
    assert kw.produce_request(empty, 0, len(empty), version) == []


@pytest.mark.parametrize("version", list(kw.PRODUCE_VERSIONS))
def test_every_produce_response_version(version):
    values = {"Responses": [{"Name": "alpha", "TopicId": ID_A, "PartitionResponses": [
        {"Index": 0, "ErrorCode": 0, "BaseOffset": 400, "LogAppendTimeMs": -1,
         "LogStartOffset": 7, "RecordErrors": [{"BatchIndex": 2, "BatchIndexErrorMessage": "no"},
                                               {"BatchIndex": 3,
                                                "BatchIndexErrorMessage": None}],
         "ErrorMessage": "some failed", "CurrentLeader": {"LeaderId": 1, "LeaderEpoch": 4}},
        {"Index": 3, "ErrorCode": 6, "BaseOffset": -1}]}],
        "ThrottleTimeMs": 5, "NodeEndpoints": [{"NodeId": 1, "Host": "h", "Port": 9092,
                                                "Rack": None}]}
    frame = encode("ProduceResponse", version, values)
    assert kw.produce_response(frame, 0, len(frame), version) == [
        _named(version, "alpha", ID_A) + (0, 0, 400), _named(version, "alpha", ID_A) + (3, 6, -1)]


@pytest.mark.parametrize("version", list(kw.FETCH_VERSIONS))
def test_every_fetch_response_version(version):
    values = {"ThrottleTimeMs": 1, "ErrorCode": 0, "SessionId": 99, "Responses": [
        {"Topic": "alpha", "TopicId": ID_A, "Partitions": [
            {"PartitionIndex": 0, "ErrorCode": 0, "HighWatermark": 402, "LastStableOffset": 402,
             "LogStartOffset": 0, "DivergingEpoch": {"Epoch": 1, "EndOffset": 5},
             "CurrentLeader": {"LeaderId": 1, "LeaderEpoch": 3},
             "SnapshotId": {"EndOffset": 9, "Epoch": 2},
             "AbortedTransactions": [{"ProducerId": 7, "FirstOffset": 3},
                                     {"ProducerId": 8, "FirstOffset": 4}],
             "PreferredReadReplica": -1, "Records": BATCH_A},
            {"PartitionIndex": 1, "ErrorCode": 1, "HighWatermark": -1,
             "AbortedTransactions": None, "Records": None}]},
        {"Topic": "beta", "TopicId": ID_B, "Partitions": [
            {"PartitionIndex": 2, "HighWatermark": 10, "AbortedTransactions": [],
             "Records": BATCH_B}]}],
        "NodeEndpoints": [{"NodeId": 2, "Host": "b", "Port": 1, "Rack": "r"}]}
    frame = encode("FetchResponse", version, values, corr=69)
    found = kw.fetch_response(frame, 0, len(frame), version)
    assert [f[:5] for f in found] == [_named(version, "alpha", ID_A) + (0, 0, 402),
                                      _named(version, "alpha", ID_A) + (1, 1, -1),
                                      _named(version, "beta", ID_B) + (2, 0, 10)]
    assert [None if f[5] is None else frame[slice(*f[5])] for f in found] == [BATCH_A, None,
                                                                              BATCH_B]


@pytest.mark.parametrize("version", list(kw.METADATA_VERSIONS))
def test_every_metadata_response_version(version):
    third = None if version >= 12 else "gamma"
    values = {"ThrottleTimeMs": 0, "Brokers": [
        {"NodeId": 1, "Host": "10.2.1.21", "Port": 19092, "Rack": None},
        {"NodeId": 2, "Host": "b", "Port": 1, "Rack": "r"}],
        "ClusterId": "cluster", "ControllerId": 1, "Topics": [
        {"ErrorCode": 0, "Name": "alpha", "TopicId": ID_A, "IsInternal": 0, "Partitions": [
            {"PartitionIndex": 0, "LeaderId": 1, "LeaderEpoch": 3, "ReplicaNodes": [1, 2],
             "IsrNodes": [1], "OfflineReplicas": [2]},
            {"PartitionIndex": 1, "LeaderId": 2, "ReplicaNodes": [2], "IsrNodes": []}],
         "TopicAuthorizedOperations": -2 ** 31},
        {"ErrorCode": 3, "Name": "missing", "TopicId": bytes(16), "Partitions": []},
        {"ErrorCode": 0, "Name": third, "TopicId": ID_B, "IsInternal": 1, "Partitions": []}],
        "ClusterAuthorizedOperations": 0, "ErrorCode": 0}
    frame = encode("MetadataResponse", version, values, corr=2)
    expected = {}
    if version >= 10:
        expected[topic_text(ID_A)] = "alpha"
        if third is not None:
            expected[topic_text(ID_B)] = third
    assert kw.metadata_topics(frame, 0, len(frame), version) == expected


def test_versions_outside_what_is_read_are_refused():
    for parse, version in ((kw.produce_request, 2), (kw.produce_request, 14),
                           (kw.produce_response, 2), (kw.fetch_response, 3),
                           (kw.fetch_response, 19), (kw.metadata_topics, 14)):
        with pytest.raises(kw.WireError, match="is not read here"):
            parse(PRODUCE_V8_REQUEST, 0, len(PRODUCE_V8_REQUEST), version)


# --- record batches -------------------------------------------------------------------------------

class TestRecordBatches:
    def test_records_with_keys_values_and_headers(self):
        data = b"\xee" * 5 + BATCH_A + BATCH_B
        batches, cut = kw.record_batches(data, 5, len(data))
        assert cut == 0 and [len(b.records) for b in batches] == [2, 1]
        first, second = batches[0].records
        assert first[0] == 0 and second[0] == 1
        assert first[1] == 5 + 61 and second[2] == 5 + len(BATCH_A)
        assert data[first[1]:first[2]].endswith(b'"constant-000001"}\x00')
        assert data[second[1]:second[2]].endswith(b"\x02g\x02v")

    def test_a_batch_cut_short_is_left_out_and_its_bytes_counted(self):
        data = BATCH_A + BATCH_B[:-1]
        batches, cut = kw.record_batches(data, 0, len(data))
        assert len(batches) == 1 and cut == len(BATCH_B) - 1
        batches, cut = kw.record_batches(BATCH_A[:30], 0, 30)
        assert batches == [] and cut == 30, "not even a whole header"

    def test_a_failed_crc_leaves_the_batch_without_records(self):
        bad = bytearray(BATCH_A)
        bad[-3] ^= 0x01
        [b] = kw.record_batches(bytes(bad), 0, len(bad))[0]
        assert b.crc_ok is False and b.records == []
        wrong = batch(5, [record(0, b"k", b"v")], crc=1)
        [b] = kw.record_batches(wrong, 0, len(wrong))[0]
        assert b.crc_ok is False

    def test_a_compressed_batch_gives_each_offset_the_whole_batch(self):
        packed = batch(40, [b"\x1f\x8b not decompressed here"], attributes=1, count=3)
        [b] = kw.record_batches(packed, 0, len(packed))[0]
        assert (b.codec, b.crc_ok, b.base_offset) == (1, True, 40)
        assert b.records == [(0, 0, len(packed)), (1, 0, len(packed)), (2, 0, len(packed))]
        compacted = batch(40, [b"zstd bytes"], attributes=4, count=2, last_delta=5)
        [b] = kw.record_batches(compacted, 0, len(compacted))[0]
        assert b.codec == 4 and b.records == [], "offsets lost to compaction cannot be told"

    def test_a_control_batch_is_marked(self):
        marker = batch(9, [record(0, b"\x00\x00\x00\x00", b"\x00\x00\x00\x00\x00\x00")],
                       attributes=0x30)
        [b] = kw.record_batches(marker, 0, len(marker))[0]
        assert b.control is True and b.codec == 0 and len(b.records) == 1

    def test_what_is_not_a_v2_batch_is_refused(self):
        old = batch(0, [record(0, b"k", b"v")], magic=1)
        with pytest.raises(kw.WireError, match="message format v1"):
            kw.record_batches(old, 0, len(old))
        short = struct.pack(">qiib", 0, 20, 0, 2) + bytes(60)
        with pytest.raises(kw.WireError, match="shorter than its header"):
            kw.record_batches(short, 0, len(short))

    def test_records_that_do_not_fill_their_batch_are_refused(self):
        body = b"\x00" + varint(0) + varint(0) + varint(1) + b"k" + varint(1) + b"v" + varint(0)
        long_record = batch(0, [varint(len(body) + 1) + body + b"\x00"])
        with pytest.raises(kw.WireError, match="says"):
            kw.record_batches(long_record, 0, len(long_record))
        extra = batch(0, [record(0, b"k", b"v"), b"\x00"], count=1)
        with pytest.raises(kw.WireError, match="left unread"):
            kw.record_batches(extra, 0, len(extra))
