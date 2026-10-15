"""Tests for scripts/so_journal.py: the clients' journals read through the brokers' own wire
formats, against journals and captures built here byte by byte."""
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import so_journal as sj  # noqa: E402

T0 = 1791900000 * 10**9


def kafka_request(api, corr, body=b""):
    payload = struct.pack(">hhi", api, 9, corr) + b"\x00\x06client" + body
    return struct.pack(">i", len(payload)) + payload


def kafka_response(corr, body=b""):
    payload = struct.pack(">i", corr) + body
    return struct.pack(">i", len(payload)) + payload


def resp(*args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        out += b"$%d\r\n%s\r\n" % (len(a), a)
    return out


def write_journal(stem, conns):
    """conns: [(local port, peer port, out bytes, in bytes, [(end, ns)], [(key, ns)])]."""
    with open(stem + "_streams.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,local_port,peer_host,peer_port\n")
        for i, (local, peer, _, _, _, _) in enumerate(conns):
            fh.write("%d,%d,10.1.1.21,%d\n" % (i, local, peer))
    with open(stem + "_reads.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,end,bytes,ns\n")
        for i, conn in enumerate(conns):
            before = 0
            for end, ns in conn[4]:
                fh.write("%d,%d,%d,%s\n" % (i, end, end - before, "" if ns is None else ns))
                before = end
    with open(stem + "_txkeys.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,key,ns\n")
        for i, conn in enumerate(conns):
            for key, ns in conn[5]:
                fh.write("%d,%d,%d\n" % (i, key, ns))
    for i, conn in enumerate(conns):
        with open("%s_conn%d_out.bin" % (stem, i), "wb") as fh:
            fh.write(conn[2])
        with open("%s_conn%d_in.bin" % (stem, i), "wb") as fh:
            fh.write(conn[3])


class TestWireFormats:
    def test_kafka_frames_stop_at_a_cut_or_a_bad_size(self):
        one, two = kafka_request(3, 1), kafka_request(0, 2, b"constant-000001")
        assert sj.kafka_frames(one + two) == [(0, len(one)), (len(one), len(one + two))]
        assert sj.kafka_frames(one + two[:-1]) == [(0, len(one))], "a cut frame is left out"
        assert sj.kafka_frames(struct.pack(">i", -1) + one) == []
        assert sj.kafka_requests(one + two) == [(0, len(one), 3, 1),
                                                (len(one), len(one + two), 0, 2)]
        assert sj.kafka_requests(struct.pack(">i", 2) + b"ab") == [], "too short for a header"

    def test_kafka_responses_keep_the_first_of_a_repeated_id(self):
        a, b = kafka_response(5, b"x"), kafka_response(5, b"y")
        assert sj.kafka_responses(a + b) == {5: (0, len(a))}
        assert sj.kafka_responses(struct.pack(">i", 2) + b"ab") == {}

    def test_resp_values_of_every_kind(self):
        items = [b"+OK\r\n", b"-ERR no\r\n", b":12\r\n", b"$-1\r\n", b"$3\r\nabc\r\n",
                 b"*-1\r\n", resp(b"XADD", b"s"), b"*2\r\n*1\r\n:1\r\n$0\r\n\r\n"]
        data = b"".join(items)
        found = sj.resp_items(data)
        assert [data[s:e] for s, e in found] == items
        assert sj.resp_items(b"$5\r\nab") == [], "a bulk string cut short"
        assert sj.resp_items(b"*2\r\n:1\r\n") == [], "an array cut short"
        assert sj.resp_items(b"+OK") == [], "a line with no end"
        assert sj._resp_end(b"", 0) is None
        with pytest.raises(ValueError, match="not a RESP value"):
            sj.resp_items(b"?what\r\n")

    def test_ids_are_found_once_each_inside_the_range(self):
        data = b"..constant-000001..constant-000001..constant-000002.."
        assert sj.ids_in(data, 0, len(data)) == ["constant-000001", "constant-000002"]
        assert sj.ids_in(data, 0, 20) == ["constant-000001"]
        assert sj.ids_in(data, 0, 10) == [], "an id cut by the range is not in it"


class TestThePerMessageTimes:
    def kafka(self, tmp_path):
        meta, produce = kafka_request(3, 1), kafka_request(0, 7, b"constant-000001constant-000002")
        meta_r, produce_r = kafka_response(1, b"m"), kafka_response(7, b"ok")
        out = meta + produce
        inb = meta_r + produce_r
        producer = (40001, 9092, out, inb, [(len(meta_r), T0 + 10), (len(inb), T0 + 99)],
                    [(len(meta) - 1, T0 + 1), (len(out) - 1, T0 + 50)])
        fetch, other = kafka_request(1, 11), kafka_request(3, 12)
        fetch_r = kafka_response(11, b"constant-000001constant-000002")
        consumer = (40002, 9092, fetch + other, fetch_r,
                    [(len(fetch_r), T0 + 120)], [(len(fetch) - 1, T0 + 60)])
        stem_p, stem_c = str(tmp_path / "p"), str(tmp_path / "c")
        write_journal(stem_p, [producer])
        write_journal(stem_c, [consumer])
        return sj.load(stem_p), sj.load(stem_c)

    def test_kafka_acknowledgment_and_request_by_correlation_id(self, tmp_path):
        prod, cons = self.kafka(tmp_path)
        assert sj.acknowledgments(prod, "kafka") == {"constant-000001": T0 + 99,
                                                     "constant-000002": T0 + 99}
        assert sj.requests(cons, "kafka") == {"constant-000001": T0 + 60,
                                              "constant-000002": T0 + 60}

    def test_redis_replies_answer_commands_in_order(self, tmp_path):
        ping, xadd = resp(b"PING"), resp(b"XADD", b"sb", b"*", b"payload", b"constant-000003")
        pong, entry = b"+PONG\r\n", b"$15\r\n1791937134158-0\r\n"
        producer = (40003, 6379, ping + xadd, pong + entry,
                    [(len(pong), T0 + 5), (len(pong + entry), T0 + 77)],
                    [(len(ping + xadd) - 1, T0 + 40)])
        xread = resp(b"XREADGROUP", b"GROUP", b"g", b"c", b"BLOCK", b"1000")
        reply = b"*1\r\n*2\r\n$2\r\nsb\r\n*1\r\n$15\r\nconstant-000003\r\n"
        consumer = (40004, 6379, xread + xread, reply + b"*-1\r\n",
                    [(len(reply), T0 + 90), (len(reply) + 5, None)],
                    [(len(xread) - 1, T0 + 30), (2 * len(xread) - 1, T0 + 95)])
        stem_p, stem_c = str(tmp_path / "rp"), str(tmp_path / "rc")
        write_journal(stem_p, [producer])
        write_journal(stem_c, [consumer])
        assert sj.acknowledgments(sj.load(stem_p), "redis") == {"constant-000003": T0 + 77}
        assert sj.requests(sj.load(stem_c), "redis") == {"constant-000003": T0 + 30}

    def test_an_acknowledgment_split_across_reads_is_timed_by_its_last_byte(self, tmp_path):
        produce, ack = kafka_request(0, 7, b"constant-000004"), kafka_response(7, b"okay")
        write_journal(str(tmp_path / "s"), [(40005, 9092, produce, ack,
                                            [(len(ack) - 1, T0 + 10), (len(ack), T0 + 20)], [])])
        assert sj.acknowledgments(sj.load(str(tmp_path / "s")), "kafka") == {
            "constant-000004": T0 + 20}, "the read that brought its last byte, not the one before"

    def test_only_a_produce_request_acknowledges_and_only_a_fetch_delivers(self, tmp_path):
        # An id inside another API's request or response is not a message's acknowledgment or
        # delivery: here a metadata request names one, and its answer comes first.
        meta, meta_r = kafka_request(3, 2, b"constant-000006"), kafka_response(2, b"x")
        write_journal(str(tmp_path / "m"), [(40006, 9092, meta, meta_r, [(len(meta_r), T0 + 5)],
                                            [(len(meta) - 1, T0 + 1)])])
        conns = sj.load(str(tmp_path / "m"))
        assert sj.acknowledgments(conns, "kafka") == {}
        offset, offset_r = kafka_request(2, 3), kafka_response(3, b"constant-000006")
        write_journal(str(tmp_path / "o"), [(40007, 9092, offset, offset_r,
                                            [(len(offset_r), T0 + 5)],
                                            [(len(offset) - 1, T0 + 1)])])
        assert sj.requests(sj.load(str(tmp_path / "o")), "kafka") == {}

    def test_a_missing_read_or_key_gives_no_time(self, tmp_path):
        prod, _ = self.kafka(tmp_path)
        conn = prod[0]
        assert sj.rx_at(conn, 10 ** 6) is None and sj.tx_at(conn, 10 ** 6) is None
        assert sj.load(str(tmp_path / "absent")) == {}


def pcap(path, packets, linktype=101):
    """A classic nanosecond pcap of raw IPv4 TCP packets, as the runs' tcpdump writes with
    --time-stamp-precision=nano: (ns, src, dst, sport, dport, seq, payload)."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, 65535, linktype))
        for ns, src, dst, sport, dport, seq, payload in packets:
            tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0)
            ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(payload), 0, 0, 64, 6,
                             0, socket.inet_aton(src), socket.inet_aton(dst))
            frame = ip + tcp + payload
            fh.write(struct.pack("<IIII", ns // 10**9, ns % 10**9, len(frame), len(frame)))
            fh.write(frame)


class TestTheCaptures:
    def test_segments_reads_packets_and_the_journal_against_the_capture(self, tmp_path):
        produce = kafka_request(0, 7, b"constant-000009")
        ack = kafka_response(7, b"ok")
        stem = str(tmp_path / "p")
        write_journal(stem, [(40010, 9092, produce, ack, [(len(ack), T0 + 2000)],
                              [(len(produce) - 1, T0 + 10)])])
        conns = sj.load(stem)
        path = str(tmp_path / "s.pcap")
        base = 1000
        pcap(path, [
            (T0 + 1000, "10.1.1.10", "10.1.1.21", 40010, 9092, 5000, produce),
            (T0 + 1500, "10.1.1.21", "10.1.1.10", 9092, 40010, base, ack[:6]),
            (T0 + 1990, "10.1.1.21", "10.1.1.10", 9092, 40010, base + 6, ack[6:]),
            (T0 + 2500, "10.1.1.21", "10.1.1.10", 9092, 40010, base + 6, ack[6:]),
            (T0 + 2600, "10.1.1.21", "10.1.1.10", 9092, 40099, 7, b""),
            (T0 + 2700, "10.1.1.21", "10.1.1.99", 9092, 40010, 7, b"elsewhere"),
        ])
        segs = sj.incoming_segments(path, "10.1.1.21", 9092, "10.1.1.10")
        assert segs == {"40010": [(0, 6, T0 + 1500), (6, len(ack), T0 + 1990)]}, (
            "a range seen twice keeps its first time; empty and other packets are left out")
        assert sj.seen_at(segs["40010"], len(ack) - 1) == T0 + 1990
        assert sj.seen_at(segs["40010"], 10 ** 6) is None and sj.seen_at([], 0) is None
        assert sj.packets_per_read(conns[0], segs["40010"]) == [2]
        assert sj.acknowledgment_checks(conns, "kafka", segs) == [(T0 + 2000, T0 + 1990)]
        assert sj.acknowledgment_checks(conns, "kafka", {}) == [], "a connection not captured"

    def test_reads_count_only_the_segments_they_drained(self, tmp_path):
        stem = str(tmp_path / "c")
        write_journal(stem, [(1, 9092, b"", b"x" * 30, [(10, T0), (25, T0 + 1), (30, None)], [])])
        conn = sj.load(stem)[0]
        segs = [(0, 10, T0), (10, 20, T0), (20, 30, T0)]
        assert sj.packets_per_read(conn, segs) == [1, 2, 1]
        assert sj.packets_per_read(conn, []) == [0, 0, 0]

    def test_an_acknowledgment_the_capture_or_the_journal_cannot_time_is_left_out(self, tmp_path):
        produce = kafka_request(0, 7, b"constant-000009")
        ack = kafka_response(7, b"ok")
        stem = str(tmp_path / "q")
        empty, empty_ack = kafka_request(0, 9, b"no ids here"), kafka_response(9, b"ok")
        write_journal(stem, [(40011, 9092, produce + kafka_request(3, 8) + empty, ack +
                              kafka_response(8, b"m") + empty_ack, [(len(ack), None)], [])])
        conns = sj.load(stem)
        segs = {"40011": [(0, len(ack), T0)]}
        assert sj.acknowledgment_checks(conns, "kafka", segs) == [], (
            "the read had no timestamp, and a produce request carrying no id is not a message's")
        segs = {"40011": [(100, 200, T0)]}
        write_journal(stem, [(40011, 9092, produce, ack, [(len(ack), T0 + 5)], [])])
        assert sj.acknowledgment_checks(sj.load(stem), "kafka", segs) == [], (
            "the capture holds no segment for its last byte")
