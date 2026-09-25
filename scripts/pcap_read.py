#!/usr/bin/env python3
"""
pcap_read.py -- the TCP segments of a packet capture, read without a library.

M0 captures the packets between the receiver and the broker at both ends (plan version 29,
D29-1): on the broker's card, where tcpdump writes Ethernet frames, and in the receiver's
namespace with `-i any`, where the pairs' tcpdump 4.99 writes Linux cooked frames
(LINKTYPE_LINUX_SLL2; the older LINUX_SLL is read too). Two hundred bytes of each packet are
kept, which holds every header M0 reads and the first bytes of each request and reply.

This reads the classic pcap format tcpdump writes with -w -- a 24-byte file header, then a 16-byte
header before each packet, in the byte order the magic number says, with microsecond or
nanosecond stamps -- and returns each IPv4 TCP segment: when it was seen, both ends, the sequence
and acknowledgement numbers, the flags and window, how many bytes it carried (from the IP header,
not from what was kept), and the bytes that were kept. Everything else in the file is passed
over, and a capture cut off in the middle of a packet ends at the last whole one.
"""
import struct

#: Link type: (name, bytes before the IP header, where the EtherType sits).
LINKTYPES = {1: ("ethernet", 14, 12), 113: ("linux_sll", 16, 14), 276: ("linux_sll2", 20, 0)}
#: Magic number: (byte order, nanoseconds per unit of the stamp's second field).
MAGIC = {0xa1b2c3d4: ("<", 1000), 0xd4c3b2a1: (">", 1000),
         0xa1b23c4d: ("<", 1), 0x4d3cb2a1: (">", 1)}
IPV4, VLAN, TCP = 0x0800, 0x8100, 6
#: TCP's flags, by the letters tcpdump prints.
FIN, SYN, RST, PSH, ACK = 0x01, 0x02, 0x04, 0x08, 0x10


def _address(raw):
    return ".".join(str(b) for b in raw)


def _segment(frame, before_ip, ethertype_at, ethernet):
    """One frame's TCP segment as a dict, or None if it carries none."""
    if len(frame) < ethertype_at + 2:
        return None
    ethertype = struct.unpack("!H", frame[ethertype_at:ethertype_at + 2])[0]
    if ethernet and ethertype == VLAN and len(frame) >= 18:
        ethertype, before_ip = struct.unpack("!H", frame[16:18])[0], 18
    if ethertype != IPV4:
        return None
    ip = frame[before_ip:]
    if len(ip) < 20 or ip[0] >> 4 != 4 or ip[9] != TCP:
        return None
    header = (ip[0] & 0x0F) * 4
    total = struct.unpack("!H", ip[2:4])[0]
    tcp = ip[header:]
    if len(tcp) < 20:
        return None
    sport, dport, seq, ack, offset_flags, window = struct.unpack("!HHIIHH", tcp[:16])
    tcp_header = (offset_flags >> 12) * 4
    length = max(0, total - header - tcp_header)
    return {"src": _address(ip[12:16]), "sport": sport, "dst": _address(ip[16:20]),
            "dport": dport, "seq": seq, "ack": ack, "flags": offset_flags & 0x3F,
            "window": window, "length": length, "payload": bytes(tcp[tcp_header:tcp_header
                                                                    + length])}


def segments(path):
    """Every IPv4 TCP segment in a classic pcap file, in the order it was written."""
    with open(path, "rb") as fh:
        head = fh.read(24)
        if len(head) < 24:
            raise ValueError("%s is shorter than a pcap file header" % path)
        magic = struct.unpack("<I", head[:4])[0]
        if magic not in MAGIC:
            raise ValueError("%s is not a classic pcap file (magic %08x); pcapng is not read here"
                             % (path, magic))
        order, scale = MAGIC[magic]
        linktype = struct.unpack(order + "I", head[20:24])[0] & 0x0FFFFFFF
        if linktype not in LINKTYPES:
            raise ValueError("%s holds link type %d, which is not read here" % (path, linktype))
        name, before_ip, ethertype_at = LINKTYPES[linktype]
        found = []
        while True:
            record = fh.read(16)
            if len(record) < 16:
                break
            seconds, fraction, kept, _ = struct.unpack(order + "IIII", record)
            frame = fh.read(kept)
            if len(frame) < kept:
                break
            segment = _segment(frame, before_ip, ethertype_at, name == "ethernet")
            if segment is not None:
                segment["ns"] = seconds * 1000000000 + fraction * scale
                found.append(segment)
    return found
