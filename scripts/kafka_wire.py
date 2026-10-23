#!/usr/bin/env python3
"""
kafka_wire.py -- Kafka's own ids for its messages, read from the bytes a client and the broker
exchange: which topic, partition and offset each record is, and where in its connection's byte
stream the record lies, so that the packet carrying its last byte can be found.

The offsets are the broker's. A produce request carries each record with its offset counted from
the start of its batch (the record's offset delta), and the broker gives the batch its first offset
when it writes it and says which in the produce response, so a produced record is that base offset
plus its delta. A fetch response carries batches as the broker stored them, with their real first
offsets. Up to Produce version 12 and Fetch version 12 a topic is named by its name; from version
13 by a 16-byte topic id alone, which a metadata response from version 10 on gives beside the name.

Each frame is read by its API version, field by field, as Apache Kafka's message schemas lay it out
(clients/src/main/resources/common/message/ in apache/kafka, at the broker's release, 4.1.1):
ProduceRequest and ProduceResponse versions 3 to 13, FetchResponse versions 4 to 18 and
MetadataResponse versions 0 to 13. A flexible version (Produce 9 on, Fetch 12 on, Metadata 9 on)
writes arrays, strings and bytes with an unsigned varint length plus one, so that zero means null,
and ends every structure, its header's too, with tagged fields, which are skipped here by their
sizes. Every frame must be read to its last byte, so a layout read wrongly fails loudly.

Record batches are message format v2 ("magic" 2). Each batch's CRC-32C is checked over its bytes
from the attributes to its end, as the broker checks it, and each record's varint fields are read
to find its offset delta and where it ends. A compressed batch's records cannot be read without
decompressing it, and none of them can be read before the whole batch has arrived, so each of its
offsets is given the batch's own bytes.

Every function here reads bytes and returns values; scripts/client_wire.py finds the bytes in the
captures and times them.
"""
import base64
import struct

#: Kafka's API keys for the frames read here.
PRODUCE, FETCH, METADATA = 0, 1, 3

#: Names for the requests a client sends, for each exchange's kind; any other key is named by its
#: number.
API_NAMES = {0: "Produce", 1: "Fetch", 2: "ListOffsets", 3: "Metadata", 8: "OffsetCommit",
             9: "OffsetFetch", 10: "FindCoordinator", 11: "JoinGroup", 12: "Heartbeat",
             13: "LeaveGroup", 14: "SyncGroup", 15: "DescribeGroups", 16: "ListGroups",
             17: "SaslHandshake", 18: "ApiVersions", 19: "CreateTopics", 22: "InitProducerId",
             23: "OffsetForLeaderEpoch", 24: "AddPartitionsToTxn", 25: "AddOffsetsToTxn",
             26: "EndTxn", 28: "TxnOffsetCommit", 32: "DescribeConfigs", 36: "SaslAuthenticate",
             60: "DescribeCluster", 68: "ConsumerGroupHeartbeat", 71: "GetTelemetrySubscriptions",
             72: "PushTelemetry"}

#: The versions read here: every one the broker's release (4.1.1) accepts.
PRODUCE_VERSIONS = range(3, 14)
FETCH_VERSIONS = range(4, 19)
METADATA_VERSIONS = range(0, 14)

#: The first flexible version of each API read here.
FLEXIBLE_FROM = {PRODUCE: 9, FETCH: 12, METADATA: 9}

#: The first version that names a produce request's, a produce response's or a fetch response's
#: topics by id alone.
TOPIC_ID_FROM = 13

#: The topic id a metadata response gives a topic that has none: sixteen zero bytes, as text.
NO_TOPIC_ID = "A" * 22

#: A record batch's header, message format v2: base offset, length (of what follows it), the
#: partition leader's epoch, magic, CRC-32C, attributes, last offset delta, first and largest
#: timestamps, producer id, producer epoch, base sequence and record count. The CRC covers the
#: batch from its attributes, CRC_FROM bytes in, to its end.
BATCH = struct.Struct(">qiibIhiqqqhii")
LOG_OVERHEAD = 12
CRC_FROM = 21
#: The attributes' bits for the compression codec (0 for none) and for a control batch, which
#: carries a transaction's marker, not messages.
CODEC_BITS, CONTROL_BIT = 0x07, 0x20

#: CRC-32C's polynomial (Castagnoli), bit-reversed, as Kafka's batches use it.
CASTAGNOLI = 0x82F63B78


class WireError(ValueError):
    """Bytes that do not read as the broker's wire format says they must."""


# --- CRC-32C --------------------------------------------------------------------------------------

def crc_tables():
    """Eight lookup tables for CRC-32C, eight bytes at a time ("slicing by 8"): the first is the
    usual table, each entry the CRC of one byte; table k gives a byte's CRC followed by k zero
    bytes, so that eight bytes' effects can be looked up at once and combined."""
    first = []
    for n in range(256):
        crc = n
        for _ in range(8):
            crc = (crc >> 1) ^ (CASTAGNOLI if crc & 1 else 0)
        first.append(crc)
    tables = [first]
    for _ in range(7):
        tables.append([(c >> 8) ^ first[c & 0xFF] for c in tables[-1]])
    return tables


TABLES = crc_tables()


def crc32c(data, start=0, end=None):
    """CRC-32C of data[start:end]: eight bytes at a time through TABLES, then byte by byte."""
    end = len(data) if end is None else end
    t0, t1, t2, t3, t4, t5, t6, t7 = TABLES
    crc = 0xFFFFFFFF
    whole = start + (end - start) // 8 * 8
    for low, high in struct.iter_unpack("<II", memoryview(data)[start:whole]):
        crc ^= low
        crc = (t7[crc & 0xFF] ^ t6[(crc >> 8) & 0xFF] ^ t5[(crc >> 16) & 0xFF] ^ t4[crc >> 24]
               ^ t3[high & 0xFF] ^ t2[(high >> 8) & 0xFF] ^ t1[(high >> 16) & 0xFF]
               ^ t0[high >> 24])
    for byte in bytes(data[whole:end]):
        crc = t0[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc ^ 0xFFFFFFFF


# --- Kafka's primitive types ----------------------------------------------------------------------

def topic_id_text(raw):
    """A topic id's 16 bytes as Kafka writes them in its logs: URL-safe base64, unpadded."""
    return base64.urlsafe_b64encode(bytes(raw)).decode("ascii").rstrip("=")


class Reader(object):
    """A cursor over one frame, reading Kafka's types in order and never past `end`; `compact`
    reads a flexible version's forms."""

    def __init__(self, data, pos, end, compact=False):
        self.data, self.pos, self.end, self.compact = data, pos, end, compact

    def skip(self, n):
        """Move past n bytes, returning where they start."""
        if n < 0 or self.pos + n > self.end:
            raise WireError("%d bytes at offset %d run past the end of their frame at %d"
                            % (n, self.pos, self.end))
        start = self.pos
        self.pos += n
        return start

    def _unpack(self, fmt, size):
        return struct.unpack_from(fmt, self.data, self.skip(size))[0]

    def int8(self):
        return self._unpack(">b", 1)

    def int16(self):
        return self._unpack(">h", 2)

    def int32(self):
        return self._unpack(">i", 4)

    def int64(self):
        return self._unpack(">q", 8)

    def uvarint(self):
        """An unsigned varint: seven bits a byte, the lowest first, the top bit set on every byte
        but the last."""
        value = shift = 0
        while True:
            byte = self.data[self.skip(1)]
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift > 63:
                raise WireError("a varint longer than ten bytes ends at offset %d" % self.pos)

    def varint(self):
        """A signed varint, zigzag-encoded so that small negatives stay short, as a record's fields
        are written."""
        raw = self.uvarint()
        return (raw >> 1) ^ -(raw & 1)

    def size(self):
        """An array's count or a bytes field's length, -1 for null: an int32, or in a flexible
        version an unsigned varint holding it plus one."""
        return self.uvarint() - 1 if self.compact else self.int32()

    def string(self):
        """A string, None for null: an int16 length, or in a flexible version an unsigned varint
        holding the length plus one."""
        n = self.uvarint() - 1 if self.compact else self.int16()
        if n < 0:
            return None
        start = self.skip(n)
        return bytes(self.data[start:self.pos]).decode("utf-8", "replace")

    def blob(self):
        """(start, end) of a bytes or records field, None for null."""
        n = self.size()
        if n < 0:
            return None
        return self.skip(n), self.pos

    def uuid(self):
        """A topic id, as text."""
        start = self.skip(16)
        return topic_id_text(self.data[start:self.pos])

    def tags(self):
        """Skip a flexible structure's tagged fields: their count, then each one's tag, size and
        bytes. A structure that is not flexible has none."""
        if self.compact:
            for _ in range(self.uvarint()):
                self.uvarint()
                self.skip(self.uvarint())

    def done(self):
        """Fail unless the frame has been read to its last byte."""
        if self.pos != self.end:
            raise WireError("%d bytes are left unread at the end of the frame ending at %d"
                            % (self.end - self.pos, self.end))


def _topic(r, version):
    """(name, topic id) of a produce or fetch frame's topic entry: the name before
    TOPIC_ID_FROM, the id from it on."""
    if version >= TOPIC_ID_FROM:
        return None, r.uuid()
    return r.string(), None


def _check(api, version, versions):
    if version not in versions:
        raise WireError("%s version %d is not read here" % (API_NAMES[api], version))


def api_name(key):
    """The name of the API a request's key names."""
    return API_NAMES.get(key, "api %d" % key)


# --- the frames -----------------------------------------------------------------------------------

def request_header(data, start, end):
    """(API key, version, correlation id, client id, where the client id ends) of the request frame
    data[start:end], its size prefix included. The client id keeps its two-byte length even in a
    flexible header, so that any broker can read who is asking."""
    r = Reader(data, start + 4, end)
    api, version, corr = r.int16(), r.int16(), r.int32()
    client = r.string()
    return api, version, corr, client, r.pos


def produce_request(data, start, end, version):
    """[(topic, topic id, partition, (start, end) of its records or None)] for each partition the
    produce request frame data[start:end] writes to, in order: the name and no id before version
    13, the id and no name from it on."""
    _check(PRODUCE, version, PRODUCE_VERSIONS)
    _, _, _, _, pos = request_header(data, start, end)
    r = Reader(data, pos, end, version >= FLEXIBLE_FROM[PRODUCE])
    r.tags()
    r.string()  # the transactional id
    r.int16()  # acks
    r.int32()  # the timeout
    found = []
    for _ in range(max(r.size(), 0)):
        topic, tid = _topic(r, version)
        for _ in range(max(r.size(), 0)):
            partition = r.int32()
            found.append((topic, tid, partition, r.blob()))
            r.tags()
        r.tags()
    r.tags()
    r.done()
    return found


def produce_response(data, start, end, version):
    """[(topic, topic id, partition, error code, base offset)] for each partition the produce
    response frame data[start:end] answers for: the offset the broker gave the first record of the
    batch it wrote there, where the error code is 0."""
    _check(PRODUCE, version, PRODUCE_VERSIONS)
    r = Reader(data, start + 8, end, version >= FLEXIBLE_FROM[PRODUCE])
    r.tags()
    found = []
    for _ in range(max(r.size(), 0)):
        topic, tid = _topic(r, version)
        for _ in range(max(r.size(), 0)):
            partition, error, base = r.int32(), r.int16(), r.int64()
            r.int64()  # the log append time
            if version >= 5:
                r.int64()  # the log start offset
            if version >= 8:
                for _ in range(max(r.size(), 0)):  # the records that failed the batch
                    r.int32()
                    r.string()
                    r.tags()
                r.string()  # the error message
            r.tags()
            found.append((topic, tid, partition, error, base))
        r.tags()
    r.int32()  # the throttle time
    r.tags()
    r.done()
    return found


def fetch_response(data, start, end, version):
    """[(topic, topic id, partition, error code, high watermark, (start, end) of its records or
    None)] for each partition the fetch response frame data[start:end] answers for, in order."""
    _check(FETCH, version, FETCH_VERSIONS)
    r = Reader(data, start + 8, end, version >= FLEXIBLE_FROM[FETCH])
    r.tags()
    r.int32()  # the throttle time
    if version >= 7:
        r.int16()  # the error code
        r.int32()  # the fetch session's id
    found = []
    for _ in range(max(r.size(), 0)):
        topic, tid = _topic(r, version)
        for _ in range(max(r.size(), 0)):
            partition, error, high = r.int32(), r.int16(), r.int64()
            r.int64()  # the last stable offset
            if version >= 5:
                r.int64()  # the log start offset
            for _ in range(max(r.size(), 0)):  # the aborted transactions
                r.int64()
                r.int64()
                r.tags()
            if version >= 11:
                r.int32()  # the preferred read replica
            records = r.blob()
            r.tags()
            found.append((topic, tid, partition, error, high, records))
        r.tags()
    r.tags()
    r.done()
    return found


def metadata_topics(data, start, end, version):
    """{topic id: name} for the topics the metadata response frame data[start:end] names with both;
    {} before version 10, which carries no ids."""
    _check(METADATA, version, METADATA_VERSIONS)
    r = Reader(data, start + 8, end, version >= FLEXIBLE_FROM[METADATA])
    r.tags()
    if version >= 3:
        r.int32()  # the throttle time
    for _ in range(max(r.size(), 0)):  # the brokers
        r.int32()
        r.string()
        r.int32()
        if version >= 1:
            r.string()  # the rack
        r.tags()
    if version >= 2:
        r.string()  # the cluster id
    if version >= 1:
        r.int32()  # the controller's id
    found = {}
    for _ in range(max(r.size(), 0)):
        r.int16()  # the topic's error code
        name = r.string()
        tid = r.uuid() if version >= 10 else None
        if version >= 1:
            r.int8()  # whether the topic is internal
        for _ in range(max(r.size(), 0)):  # the partitions
            r.int16()
            r.int32()
            r.int32()
            if version >= 7:
                r.int32()  # the leader's epoch
            for _ in range(3 if version >= 5 else 2):  # replicas, in-sync ones, offline ones
                r.skip(4 * max(r.size(), 0))
            r.tags()
        if version >= 8:
            r.int32()  # the operations the client may perform on the topic
        r.tags()
        if name is not None and tid not in (None, NO_TOPIC_ID):
            found[tid] = name
    if 8 <= version <= 10:
        r.int32()  # the operations the client may perform on the cluster
    if version >= 13:
        r.int16()  # the error code
    r.tags()
    r.done()
    return found


# --- record batches -------------------------------------------------------------------------------

class Batch(object):
    """One record batch: where it lies, its first offset and its last offset delta, its codec,
    whether it is a control batch, whether its CRC-32C held, and its records, [(offset delta,
    start, end)], each from its length prefix to its last byte. A batch whose CRC failed has none;
    a compressed batch's records each span the whole batch."""

    def __init__(self, start, end, base_offset, last_delta, attributes, crc_ok, records):
        self.start, self.end = start, end
        self.base_offset, self.last_delta = base_offset, last_delta
        self.codec = attributes & CODEC_BITS
        self.control = bool(attributes & CONTROL_BIT)
        self.crc_ok = crc_ok
        self.records = records


def record_batches(data, start, end):
    """([Batch], cut) for the records field data[start:end]: its batches in order, and how many
    bytes at its end a batch cut short holds. A fetch response may end its records in the middle of
    a batch, which the client then fetches again whole; those bytes are not a batch yet, and are
    left out, as the client leaves them."""
    batches, pos = [], start
    while end - pos >= BATCH.size:
        _, size, _, magic = struct.unpack_from(">qiib", data, pos)
        if magic != 2:
            raise WireError("message format v%d at offset %d is not read here" % (magic, pos))
        if LOG_OVERHEAD + size < BATCH.size:
            raise WireError("a %d-byte record batch at offset %d is shorter than its header"
                            % (LOG_OVERHEAD + size, pos))
        stop = pos + LOG_OVERHEAD + size
        if stop > end:
            break
        batches.append(read_batch(data, pos, stop))
        pos = stop
    return batches, end - pos


def read_batch(data, start, stop):
    """The Batch in data[start:stop]."""
    head = BATCH.unpack_from(data, start)
    base, crc, attributes, last_delta, count = head[0], head[4], head[5], head[6], head[12]
    crc_ok = crc32c(data, start + CRC_FROM, stop) == crc
    if not crc_ok:
        records = []
    elif attributes & CODEC_BITS:
        # Offsets a producer writes in one batch run on without a gap; a batch the broker has
        # compacted may have lost some, and which cannot be told without decompressing it.
        whole = count == last_delta + 1
        records = [(delta, start, stop) for delta in range(count)] if whole else []
    else:
        records = _records(data, start + BATCH.size, stop, count)
    return Batch(start, stop, base, last_delta, attributes, crc_ok, records)


def _records(data, pos, stop, count):
    """[(offset delta, start, end)] for the `count` records of an uncompressed batch, which must
    fill it to its end."""
    r = Reader(data, pos, stop)
    found = []
    for _ in range(count):
        at = r.pos
        length = r.varint()
        body = r.pos
        r.int8()  # the record's attributes
        r.varint()  # its timestamp delta
        delta = r.varint()
        r.skip(max(r.varint(), 0))  # the key, -1 for null
        r.skip(max(r.varint(), 0))  # the value
        for _ in range(max(r.varint(), 0)):  # the headers: each a key and a value
            r.skip(max(r.varint(), 0))
            r.skip(max(r.varint(), 0))
        if r.pos != body + length:
            raise WireError("the record at offset %d says %d bytes and holds %d"
                            % (at, length, r.pos - body))
        found.append((delta, at, r.pos))
    r.done()
    return found
