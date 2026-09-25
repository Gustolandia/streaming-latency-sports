"""Tests for scripts/pcap_read.py, on capture files built byte by byte the way tcpdump writes them."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import pcap_read as pr  # noqa: E402

RECEIVER, BROKER = "10.1.1.11", "10.1.1.21"


def packet(payload=b"", src=RECEIVER, dst=BROKER, sport=40000, dport=6379, seq=1000, ack=2000,
           flags=pr.PSH | pr.ACK, window=502, protocol=6, carried=None):
    """An IPv4 packet; `carried` is what the IP header says the segment held, if not the payload."""
    tcp = struct.pack("!HHIIHH", sport, dport, seq, ack, (5 << 12) | flags, window) \
        + b"\x00\x00\x00\x00" + payload
    total = 40 + (len(payload) if carried is None else carried)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total, 1, 0, 64, protocol, 0,
                     bytes(int(x) for x in src.split(".")), bytes(int(x) for x in dst.split(".")))
    return ip + tcp


def frame(linktype, body, ethertype=pr.IPV4):
    if linktype == 1:
        return b"\x02" * 12 + struct.pack("!H", ethertype) + body
    if linktype == 113:
        return b"\x00" * 14 + struct.pack("!H", ethertype) + body
    return struct.pack("!H", ethertype) + b"\x00" * 18 + body


def capture(path, linktype, frames, nano=False, big=False, snap=200, cut=0):
    """A classic pcap file: its header, then each (ns, frame) kept to `snap` bytes."""
    order = ">" if big else "<"
    out = struct.pack(order + "IHHiIII", 0xa1b23c4d if nano else 0xa1b2c3d4, 2, 4, 0, 0, snap,
                      linktype)
    for ns, whole in frames:
        kept = whole[:snap]
        seconds, rest = divmod(ns, 1000000000)
        out += struct.pack(order + "IIII", seconds, rest if nano else rest // 1000, len(kept),
                           len(whole)) + kept
    path.write_bytes(out[:len(out) - cut])
    return str(path)


@pytest.mark.parametrize("linktype", [1, 113, 276])
def test_each_link_type_tcpdump_writes_gives_the_segment(tmp_path, linktype):
    path = capture(tmp_path / "c.pcap", linktype,
                   [(1789762672558177000, frame(linktype, packet(b"*3\r\n$10\r\nXREADGROUP")))])
    [seg] = pr.segments(path)
    assert seg == {"src": RECEIVER, "sport": 40000, "dst": BROKER, "dport": 6379, "seq": 1000,
                   "ack": 2000, "flags": pr.PSH | pr.ACK, "window": 502, "length": 19,
                   "payload": b"*3\r\n$10\r\nXREADGROUP", "ns": 1789762672558177000}


def test_what_the_snap_length_cut_is_counted_from_the_ip_header(tmp_path):
    """Two hundred bytes kept of a 1,448-byte segment: it carried 1,448, and 160 are here."""
    body = packet(b"x" * 1448, src=BROKER, dst=RECEIVER, sport=6379, dport=40000)
    [seg] = pr.segments(capture(tmp_path / "c.pcap", 276, [(10 ** 18, frame(276, body))]))
    assert seg["length"] == 1448 and seg["payload"] == b"x" * (200 - 20 - 40)


def test_a_vlan_tag_is_stepped_over(tmp_path):
    tagged = b"\x02" * 12 + struct.pack("!HHH", pr.VLAN, 7, pr.IPV4) + packet(b"hi")
    [seg] = pr.segments(capture(tmp_path / "c.pcap", 1, [(10 ** 18, tagged)]))
    assert seg["payload"] == b"hi"


def test_nanosecond_and_big_endian_files_keep_their_stamps(tmp_path):
    stamp = 1789762672558177123
    nano = capture(tmp_path / "n.pcap", 1, [(stamp, frame(1, packet()))], nano=True)
    big = capture(tmp_path / "b.pcap", 1, [(stamp, frame(1, packet()))], big=True)
    assert pr.segments(nano)[0]["ns"] == stamp
    assert pr.segments(big)[0]["ns"] == stamp - 123, "microseconds, as tcpdump writes by default"


def test_what_is_not_an_ipv4_tcp_segment_is_passed_over(tmp_path):
    frames = [(10 ** 18, frame(1, packet(protocol=17))),
              (10 ** 18, frame(1, b"\x00" * 28, ethertype=0x0806)),
              (10 ** 18, frame(1, b"\x60" + b"\x00" * 39, ethertype=0x86DD)),
              (10 ** 18, frame(1, b"\x45" + b"\x00" * 10)),
              (10 ** 18, frame(1, packet()[:30])),
              (10 ** 18, b"\x02" * 8),
              (10 ** 18, frame(1, packet(b"kept")))]
    assert [seg["payload"] for seg in pr.segments(capture(tmp_path / "c.pcap", 1, frames))] == \
        [b"kept"]


def test_a_capture_cut_off_mid_packet_ends_at_the_last_whole_one(tmp_path):
    frames = [(10 ** 18, frame(1, packet(b"one"))), (10 ** 18 + 1000, frame(1, packet(b"two")))]
    assert [s["payload"] for s in pr.segments(capture(tmp_path / "c.pcap", 1, frames,
                                                      cut=5))] == [b"one"]
    assert len(pr.segments(capture(tmp_path / "d.pcap", 1, frames, cut=len(frame(1, packet(
        b"two"))) + 8))) == 1, "a record header cut short ends it too"


def test_files_this_does_not_read_say_why(tmp_path):
    short = tmp_path / "short.pcap"
    short.write_bytes(b"\xd4\xc3\xb2\xa1")
    with pytest.raises(ValueError, match="shorter than a pcap file header"):
        pr.segments(str(short))
    ng = tmp_path / "ng.pcap"
    ng.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 20)
    with pytest.raises(ValueError, match="not a classic pcap file"):
        pr.segments(str(ng))
    with pytest.raises(ValueError, match="link type 101"):
        pr.segments(capture(tmp_path / "raw.pcap", 101, []))
