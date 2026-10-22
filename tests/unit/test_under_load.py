"""Tests for scripts/under_load.py, freeze 42's reader and judge as plan version 46 amends it, against
runs built here file by file in the shape the kit writes them: the clients' own files, their socket
files and journals, both client captures, the broker's own capture on the broker's clock, the
card's capture with its clock samples, and version 46's extra files (the consumer's samples of its
own thread, the clients' collector logs, the load's blocks and its frozen duty)."""
import csv
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import under_load as ul  # noqa: E402

T0 = 1791900000 * 10**9
DRIVER, BROKER, RECEIVER, OTHER = "10.2.1.10", "10.2.1.21", "10.2.1.11", "10.2.1.99"
US = 1000
#: The broker's clock runs 7 ms ahead of the driver's and the card's 3 ms ahead of the system's,
#: so a reading that mixed two clocks would be off by milliseconds.
BROKER_AHEAD = 7000 * US
CARD_AHEAD = 3000 * US
PORT = {"kafka": 19092, "redis": 6379}


def eid(i):
    return "constant-%06d" % i


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


def ip_packet(src, dst, sport, dport, seq, payload, proto=6):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0)
    return struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(payload), 0, 0, 64, proto,
                       0, socket.inet_aton(src), socket.inet_aton(dst)) + tcp + payload


def write_pcap(path, packets):
    """Nanosecond pcap of raw IPv4 packets: (ns, frame)."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, 65535, 101))
        for ns, frame in sorted(packets, key=lambda p: p[0]):
            fh.write(struct.pack("<IIII", ns // 10**9, ns % 10**9, len(frame), len(frame)))
            fh.write(frame)


def write_journal(stem, local, port, out, inb, reads, keys):
    with open(stem + "_streams.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,local_port,peer_host,peer_port\n0,%d,%s,%d\n" % (local, BROKER, port))
    with open(stem + "_reads.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,end,bytes,ns\n")
        before = 0
        for end, ns in reads:
            fh.write("0,%d,%d,%s\n" % (end, end - before, "" if ns is None else ns))
            before = end
    with open(stem + "_txkeys.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,key,ns\n")
        for key, ns in keys:
            fh.write("0,%d,%d\n" % (key, ns))
    with open(stem + "_conn0_out.bin", "wb") as fh:
        fh.write(out)
    with open(stem + "_conn0_in.bin", "wb") as fh:
        fh.write(inb)


#: The world every run is built from, in microseconds on the driver's clock. Four messages, each in
#: its own produce request; four fetches, the first answered empty before the measured window
#: opens with message 0's publish. Message 1's acknowledgment came in before the answer to fetch 1,
#: so the turnaround before fetch 2 surely held it (exact).
MESSAGES = [  # pub, tx, rx_ack, ack, recv; P_in, A_out on the broker
    dict(pub=250, tx=500, rx_ack=1000, ack=1050, recv=1600, p_in=600, a_out=900),
    dict(pub=900, tx=1000, rx_ack=1400, ack=1450, recv=3000, p_in=1100, a_out=1300),
    dict(pub=1600, tx=1700, rx_ack=2300, ack=2350, recv=3000, p_in=1800, a_out=2200),
    dict(pub=3100, tx=3200, rx_ack=3700, ack=3750, recv=4100, p_in=3300, a_out=3600),
]
FETCHES = [  # req, ans on the driver; f_in, r_out on the broker; the card's arrival; ids
    dict(req=0, ans=200, f_in=100, r_out=150, card=180, ids=[]),
    dict(req=300, ans=1500, f_in=400, r_out=1400, card=1480, ids=[0]),
    dict(req=2000, ans=2900, f_in=2100, r_out=2800, card=2880, ids=[1, 2]),
    dict(req=3000, ans=4000, f_in=3100, r_out=3900, card=3980, ids=[3]),
]
#: A command that asks for no messages, sent between fetch 2's answer and fetch 3: Redis's
#: acknowledgment batch, a Kafka offset commit. And a fetch after the window closes.
OTHER_COMMAND = dict(req=2950, ans=2990)
TRAILING = dict(req=5000, ans=5100, f_in=5100, r_out=5150, card=5180, ids=[])
#: The consumer's samples of its own thread, just before each fetch: (us, on-CPU us, waited us).
SAMPLES = [(-10, 0, 0), (290, 60, 20), (1990, 300, 150), (2990, 360, 170)]


def fetch_bytes(backend, k, f):
    body = b"".join(eid(i).encode() for i in f["ids"])
    if backend == "kafka":
        return kafka_request(1, 1000 + k), kafka_response(1000 + k, body)
    answer = (b"*%d\r\n" % len(f["ids"]) + b"".join(b"$15\r\n" + eid(i).encode() + b"\r\n"
                                                     for i in f["ids"])) if f["ids"] else b"*-1\r\n"
    return resp(b"XREADGROUP", b"GROUP", b"g", b"c", b"BLOCK", b"1000"), answer


def other_bytes(backend):
    if backend == "kafka":
        return kafka_request(8, 3000), kafka_response(3000, b"ok")
    return resp(b"XACK", b"sb", b"g", b"1-0"), b":1\r\n"


def wire(backend, other=False, trailing=False):
    """The bytes and times of each produce request and acknowledgment, and of each consumer
    command and its answer, with the consumer's commands as (request, answer, item) in order."""
    produce, acks = [], []
    for i in range(len(MESSAGES)):
        if backend == "kafka":
            produce.append(kafka_request(0, i + 1, eid(i).encode()))
            acks.append(kafka_response(i + 1, b"ok"))
        else:
            produce.append(resp(b"XADD", b"sb", b"*", b"payload", eid(i).encode()))
            acks.append(b"$15\r\n%015d\r\n" % i)
    commands = [fetch_bytes(backend, k, f) + (f,) for k, f in enumerate(FETCHES)]
    if other:
        commands.insert(3, other_bytes(backend) + (OTHER_COMMAND,))
    if trailing:
        commands.append(fetch_bytes(backend, len(FETCHES), TRAILING) + (TRAILING,))
    return produce, acks, commands


def chunks_at(chunks, times):
    """[(end offset, ns)] for consecutive chunks of one stream."""
    out, at = [], 0
    for chunk, ns in zip(chunks, times):
        at += len(chunk)
        out.append((at, ns))
    return out


def stream_packets(chunks, times, src, dst, sport, dport):
    packets, seq = [], 1000
    for chunk, ns in zip(chunks, times):
        packets.append((ns, ip_packet(src, dst, sport, dport, seq, chunk)))
        seq += len(chunk)
    return packets


def make_run(folder, name, setup, params, verdict="count", broker=True, card=True,
             clients=True, extra_packets=(), unjournaled=False, ack_missing=False, other=False,
             trailing=False, card_misses=(), planned=False, extras=None):
    run = os.path.join(folder, name)
    os.makedirs(run)
    backend = params["backend"]
    port = PORT[backend]
    with open(os.path.join(run, "queue_row.json"), "w", encoding="utf-8") as fh:
        json.dump({"setup": setup, "params": params}, fh)
    with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "checks": {"load": {"value": 79.5}},
                   "reasons": [] if verdict == "count" else ["the measured load was 63.3%"]}, fh)
    msgs = list(MESSAGES) + ([dict(MESSAGES[-1], pub=3500)] if unjournaled else [])
    with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
        # Planned, each message was sent 10 us after its plan, and message 3 2,010 us after it.
        fh.write("event_id,t_prod_send_ns,t_broker_ack_ns%s\n" % (",t_prod_sched_ns" * planned))
        for i, m in enumerate(msgs):
            late = 2010 if i == 3 else 10
            fh.write("%s,%d,%d%s\n" % (eid(i), T0 + m["pub"] * US, T0 + m["ack"] * US,
                                       (",%d" % (T0 + (m["pub"] - late) * US)) * planned))
    with open(os.path.join(run, "consumer_events.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,t_consume_ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,%d\n" % (eid(i), T0 + m["recv"] * US))
    delivered = {i: f for f in FETCHES for i in f["ids"]}
    with open(os.path.join(run, "producer_so.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,direction,ns\n")
        for i, m in enumerate(MESSAGES):
            fh.write("%s,tx,%d\n" % (eid(i), T0 + m["tx"] * US))
    with open(os.path.join(run, "consumer_so.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,direction,ns\n")
        for i in range(len(MESSAGES)):
            fh.write("%s,rx,%d\n" % (eid(i), T0 + delivered[i]["ans"] * US))
    produce, acks, commands = wire(backend, other, trailing)
    requests = [c[0] for c in commands]
    answers = [c[1] for c in commands]
    ack_times = [None if ack_missing and i == 0 else T0 + m["rx_ack"] * US
                 for i, m in enumerate(MESSAGES)]
    write_journal(os.path.join(run, "producer_journal"), 40001, port, b"".join(produce),
                  b"".join(acks), chunks_at(acks, ack_times),
                  [(end - 1, ns) for end, ns in chunks_at(
                      produce, [T0 + m["tx"] * US for m in MESSAGES])])
    write_journal(os.path.join(run, "consumer_journal"), 40002, port, b"".join(requests),
                  b"".join(answers), chunks_at(answers, [T0 + c[2]["ans"] * US for c in commands]),
                  [(end - 1, ns) for end, ns in chunks_at(
                      requests, [T0 + c[2]["req"] * US for c in commands])])
    for log in ("sender_full.err", "receiver_full.err"):
        with open(os.path.join(run, log), "w", encoding="utf-8") as fh:
            fh.write("12 packets captured\n0 packets dropped by kernel\n")
    if clients:
        # The sender's capture sees each produce request leave 3 us after its socket timestamp;
        # the receiver's, each answer come in 2 us before the read that took it, fetch 2's in two
        # packets that one read drained.
        write_pcap(os.path.join(run, "sender_full.pcap"), stream_packets(
            produce, [T0 + m["tx"] * US + 3 * US for m in MESSAGES], DRIVER, BROKER, 40001, port))
        pieces, times = [], []
        for c in commands:
            ns = T0 + c[2]["ans"] * US - 2 * US
            if c[2] is FETCHES[2]:
                pieces += [c[1][:9], c[1][9:]]
                times += [ns - 5 * US, ns]
            else:
                pieces.append(c[1])
                times.append(ns)
        write_pcap(os.path.join(run, "receiver_full.pcap"),
                   stream_packets(pieces, times, BROKER, RECEIVER, port, 40002))
    if broker:
        on_broker = lambda us: T0 + us * US + BROKER_AHEAD  # noqa: E731
        packets = (stream_packets(produce, [on_broker(m["p_in"]) for m in MESSAGES], DRIVER,
                                  BROKER, 40001, port)
                   + stream_packets(acks, [on_broker(m["a_out"]) for m in MESSAGES], BROKER,
                                    DRIVER, port, 40001)
                   + stream_packets(requests, [on_broker(c[2].get("f_in", c[2]["req"] + 50))
                                               for c in commands], RECEIVER, BROKER, 40002, port)
                   + stream_packets(answers, [on_broker(c[2].get("r_out", c[2]["ans"] - 50))
                                              for c in commands], BROKER, RECEIVER, port, 40002)
                   + list(extra_packets))
        write_pcap(os.path.join(run, "broker_full.pcap"), packets)
        with open(os.path.join(run, "broker_full.err"), "w", encoding="utf-8") as fh:
            fh.write("40 packets captured\n2 packets dropped by kernel\n")
    if card:
        seen = [(c[1], T0 + c[2].get("card", c[2]["ans"] - 20) * US + CARD_AHEAD)
                for c in commands]
        # A packet the card's capture missed leaves the rest of its stream unread.
        kept = [s for k, s in enumerate(seen) if k not in card_misses]
        packets, seq = [], 1000
        for k, (chunk, ns) in enumerate(seen):
            if k not in card_misses:
                packets.append((ns, ip_packet(BROKER, RECEIVER, port, 40002, seq, chunk)))
            seq += len(chunk)
        assert len(packets) == len(kept)
        write_pcap(os.path.join(run, "receiver_hw.pcap"), packets)
        with open(os.path.join(run, "receiver_hw.err"), "w", encoding="utf-8") as fh:
            fh.write("4 packets captured\n0 packets dropped by kernel\n")
        with open(os.path.join(run, "phc_offset.csv"), "w", encoding="utf-8") as fh:
            fh.write("system_ns,card_minus_system_ns,window_ns\n")
            for at in (0, 5000):
                fh.write("%d,%d,800\n" % (T0 + at * US, CARD_AHEAD))
    for file_name, text in (extras or {}).items():
        with open(os.path.join(run, file_name), "w", encoding="utf-8") as fh:
            fh.write(text)
    return run


def params(backend="kafka", load=0, rt=False):
    p = {"backend": backend, "load_pct": load, "slice_ns": 3000000, "delay_ms": 0}
    if rt:
        p["priority"] = True
    return p


def samples_csv(samples=SAMPLES):
    return "t_ns,exec_ns,delay_ns,slices\n" + "".join(
        "%d,%d,%d,%d\n" % (T0 + t * US, cpu * US, wait * US, k)
        for k, (t, cpu, wait) in enumerate(samples))


def blocks_csv(switches):
    return "t_ns,state\n" + "".join("%d,%s\n" % (T0 + t * US, s) for t, s in switches)


class TestSetupIds:
    def test_judged_pilot_blocks_and_other_ids(self):
        assert ul.setup_parts("U2000-kafka-l80-rt") == (2000, "kafka", 80, True)
        assert ul.setup_parts("U50-redis-l0") == (50, "redis", 0, False)
        assert ul.setup_parts("UP500-redis-l80") == (500, "redis", 80, False)
        assert ul.setup_parts("U50-kafka-l88-blocks") == (50, "kafka", 88, False)
        assert ul.setup_parts("L2000-kafka-l0") is None
        assert ul.in_blocks("U50-kafka-l88-blocks") and ul.in_blocks("UP50-redis-l88-blocks")
        assert not ul.in_blocks("U50-kafka-l88") and not ul.in_blocks("L50-kafka-l88-blocks")


class TestTheConsumersJournal:
    def test_a_redis_command_is_named_by_its_first_word(self):
        data = resp(b"xack", b"sb") + b"*1\r\n"
        assert ul.command_name(data, 0) == b"XACK"
        assert ul.command_name(data, len(data) - 4) == b""

    def test_what_other_requests_cover_of_a_gap(self):
        assert ul.covered([], 0, 100) == 0
        assert ul.covered([(10, 20), (15, 30), (40, 50)], 0, 100) == 30, "overlaps count once"
        assert ul.covered([(-10, 5), (90, 120)], 0, 100) == 15, "clipped to the gap"
        assert ul.covered([(10, 60), (20, 30)], 0, 100) == 50, "one inside another adds nothing"
        assert ul.covered([(10, 20)], 50, 40) == 0, "a gap that closed before it opened"

    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_the_turnaround_starts_at_the_last_answer_with_messages(self, tmp_path, backend):
        import so_journal as sj
        run = make_run(str(tmp_path), "law_x", "U2000-%s-l0" % backend, params(backend),
                       other=True)
        per_request, by_id = ul.turnarounds(sj.load(os.path.join(run, "consumer_journal")),
                                            backend)
        us = lambda t: None if t is None else (t - T0) // US  # noqa: E731
        assert [(us(a), None if o is None else o // US, us(b)) for _, _, a, o, b in per_request] == [
            (None, None, None), (200, 0, 200), (1500, 0, 1500), (2900, 40, 2990)], (
            "fetch 3 waits from fetch 2's answer, less the other command's round trip; version "
            "45 waited from the other command's answer")
        assert by_id[eid(3)] == (T0 + 3000 * US, T0 + 2900 * US, 40 * US, T0 + 2990 * US, "40002")
        assert by_id[eid(1)] == by_id[eid(2)] == (T0 + 2000 * US, T0 + 1500 * US, 0,
                                                  T0 + 1500 * US, "40002")

    def test_the_producers_connection_of_each_message(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params())
        ports = ul.producer_ports(os.path.join(run, "producer_journal"))
        assert ports == {eid(i): "40001" for i in range(4)}
        assert ul.producer_ports(os.path.join(run, "nobody_journal")) == {}


class TestOneMessage:
    def message(self, **change):
        m = {"Wso": 1200.0, "tx_so": 1700 * US, "rx_so": 2900 * US, "rx_ack": 2300 * US,
             "D": 1400.0}
        m.update(change)
        return m

    def test_the_bounds_and_both_splits_add_up(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US, 0, 1500 * US, "1"),
                             [1800 * US, 2200 * US, 2100 * US, 2800 * US], 2880 * US)
        assert p["Tc"] == 500 and p["s_min"] == 0 and p["s_max"] == 300
        assert p["F"] == 1200 and p["F_lo"] == 900 and p["flagged"] and not p["exact"]
        assert p["R"] == 1000 and p["Q"] == 20 and p["b_min"] == 0 and p["b_max"] == 300
        assert p["stored"] == 0 and p["stall"] == 400 and p["Fb"] == 1200
        assert p["net"] + p["brk"] + p["q_term"] == p["F45"] == p["F"]
        assert (p["hand"], p["ack"], p["wait"]) == (1000, 0, 0)
        assert p["net"] + p["hand"] + p["b_min"] + p["ack"] + p["wait"] + p["q_term"] == p["W"]

    def test_a_message_stored_through_an_acknowledgment_batch(self):
        """Fetch k left 60 us of the thread's own time after the previous answer, 40 us of which
        an acknowledgment batch spent on the broker; the message lay stored 230 us."""
        p = ul.message_parts(self.message(Wso=1150.0, tx_so=2850 * US, rx_so=4000 * US,
                                          rx_ack=2880 * US),
                             (3000 * US, 2900 * US, 40 * US, 2990 * US, "1"),
                             [2860 * US, 2870 * US, 3100 * US, 3900 * US], 3980 * US)
        assert p["Tc"] == 60 and p["Tc45"] == 10 and p["other"] == 40
        assert p["s_min"] == 60 and p["F"] == 1090 and p["s_min45"] == 10 and p["F45"] == 1140
        assert p["exact"] and p["stored"] == 230 and p["b_min"] == 60
        assert (p["hand"], p["ack"], p["wait"]) == (810, 40, 130)
        assert p["net"] + p["hand"] + p["b_min"] + p["ack"] + p["wait"] + p["q_term"] == p["W"]

    def test_an_acknowledgment_before_the_previous_answer_makes_it_exact(self):
        p = ul.message_parts(self.message(rx_ack=1400 * US, tx_so=1000 * US, Wso=1900.0),
                             (2000 * US, 1500 * US, 0, 1500 * US, "1"), None, None)
        assert p["s_min"] == p["s_max"] == 500 and p["exact"]
        assert p["R"] is None and p["Q"] is None and p["net"] is None and p["hand"] is None

    def test_a_request_that_overlapped_the_answer_adds_nothing(self):
        p = ul.message_parts(self.message(), (1400 * US, 1500 * US, 0, 1500 * US, "1"), None,
                             None)
        assert p["Tc"] == 0 and p["s_min"] == p["s_max"] == 0 and p["Tc45"] == 0

    def test_a_broker_reading_without_its_acknowledgment_has_no_range(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US, 0, 1500 * US, "1"),
                             [1800 * US, None, 2100 * US, 2800 * US], 2880 * US)
        assert p["R"] == 1000 and p["b_min"] is None and p["stored"] is None
        assert p["net"] == 180 and p["brk"] == 1000 and p["hand"] is None

    def test_version_45s_turnaround_needs_the_last_answer(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US, 0, None, "1"),
                             [1800 * US, 2200 * US, 2100 * US, 2800 * US], 2880 * US)
        assert p["Tc45"] is None and p["F45"] is None and p["brk"] is None
        assert p["hand"] == 1000 and p["F"] == 1200

    def test_a_run_without_the_card_folds_q_into_the_paths_terms(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US, 0, 1500 * US, "1"),
                             [1800 * US, 2200 * US, 2100 * US, 2800 * US], None, card_ran=False)
        assert p["Q"] is None and p["q_term"] == 0 and p["net"] == 200
        assert p["net"] + p["brk"] + p["q_term"] == p["F"]

    @pytest.mark.parametrize("missing", ["Wso", "tx_so", "rx_so", "rx_ack"])
    def test_a_client_time_missing_times_nothing(self, missing):
        assert ul.message_parts(self.message(**{missing: None}),
                                (2000 * US, 1500 * US, 0, 1500 * US, "1"), None, None) is None

    @pytest.mark.parametrize("timing", [(2000 * US, None, None, None, "1"),
                                        (None, 1500 * US, None, 1500 * US, "1"),
                                        (2000 * US, 1500 * US, None, 1500 * US, "1")])
    def test_the_first_request_on_a_connection_times_nothing(self, timing):
        assert ul.message_parts(self.message(), timing, None, None) is None


class TestTheBrokersCapture:
    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_four_times_per_message_on_the_brokers_clock(self, tmp_path, backend):
        run = make_run(str(tmp_path), "law_x", "U2000-%s-l0" % backend, params(backend),
                       other=True)
        found = ul.broker_times(os.path.join(run, "broker_full.pcap"), PORT[backend], DRIVER,
                                RECEIVER, backend)
        assert sorted(found) == [eid(i) for i in range(4)]
        on_broker = lambda us: T0 + us * US + BROKER_AHEAD  # noqa: E731
        assert found[eid(1)] == [on_broker(1100), on_broker(1300), on_broker(2100),
                                 on_broker(2800)]

    def test_an_id_carried_twice_in_one_record_ends_at_its_later_carrying(self):
        record = b"xx" + eid(1).encode() + b"--" + eid(1).encode() + eid(2).encode()
        far = record + b"." * 3000 + eid(1).encode()
        assert ul.ids_ending(record, 0, len(record)) == [(eid(1), 33), (eid(2), 48)]
        assert ul.ids_ending(far, 0, len(far)) == [(eid(1), 33), (eid(2), 48)]

    def test_retries_other_hosts_and_stray_packets_are_left_out(self, tmp_path):
        retry = kafka_request(1, 9999)
        redelivered = kafka_response(9999, eid(1).encode())
        at = lambda us: T0 + us * US + BROKER_AHEAD  # noqa: E731
        extra = [
            # a second consumer connection that fetched message 1 again, later, and a third
            # whose first packet is captured before the first connection's but whose request
            # for message 1 arrives later still
            (at(5000), ip_packet(RECEIVER, BROKER, 40003, 19092, 1, retry)),
            (at(5100), ip_packet(BROKER, RECEIVER, 19092, 40003, 1, redelivered)),
            (at(-50), ip_packet(RECEIVER, BROKER, 40008, 19092, 1, kafka_request(3, 1))),
            (at(6000), ip_packet(RECEIVER, BROKER, 40008, 19092, 1 + len(kafka_request(3, 1)),
                                 retry)),
            (at(6100), ip_packet(BROKER, RECEIVER, 19092, 40008, 1, kafka_response(1))),
            (at(6200), ip_packet(BROKER, RECEIVER, 19092, 40008, 1 + len(kafka_response(1)),
                                 redelivered)),
            # another host, a connection with only one direction, a bare acknowledgment, a
            # packet on another port and one that is not TCP
            (at(5200), ip_packet(OTHER, BROKER, 40004, 19092, 1, retry)),
            (at(5300), ip_packet(BROKER, OTHER, 19092, 40004, 1, redelivered)),
            (at(5400), ip_packet(RECEIVER, BROKER, 40005, 19092, 1, retry)),
            (at(5500), ip_packet(BROKER, RECEIVER, 19092, 40002, 1, b"")),
            (at(5600), ip_packet(RECEIVER, BROKER, 40006, 22, 1, b"ssh")),
            (at(5700), ip_packet(RECEIVER, BROKER, 40007, 19092, 1, b"x", proto=17)),
        ]
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), extra_packets=extra)
        found = ul.broker_times(os.path.join(run, "broker_full.pcap"), 19092, DRIVER, RECEIVER,
                                "kafka")
        assert found[eid(1)][2:] == [at(2100), at(2800)]

    def test_no_capture_finds_nothing(self, tmp_path):
        assert ul.broker_times(str(tmp_path / "none.pcap"), 19092, DRIVER, RECEIVER,
                               "kafka") == {}

    def test_the_brokers_drops(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params())
        assert ul.broker_drops(run) == 2
        with open(os.path.join(run, ul.BROKER_LOG), "w", encoding="utf-8") as fh:
            fh.write("tcpdump: listening on eth0\n")
        assert ul.broker_drops(run) is None
        os.remove(os.path.join(run, ul.BROKER_LOG))
        assert ul.broker_drops(run) is None


class TestWhatElseTheRunWrote:
    def test_the_producers_lateness(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), planned=True)
        late = ul.lateness(run, warmup_s=0)
        assert late["late_p1_ms"] == pytest.approx(0.01) and late["late_p50_ms"] == pytest.approx(
            0.01)
        assert late["late_p99_ms"] == pytest.approx(0.01 + 2.0 * 0.97)
        assert late["late_spread_ms"] == pytest.approx(2.0 * 0.97) and late["late_share"] == 0.25

    def test_no_plan_or_nothing_after_the_warm_up_gives_no_lateness(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params())
        assert set(ul.lateness(run).values()) == {None}
        planned = make_run(str(tmp_path), "law_y", "U2000-kafka-l0", params(), planned=True)
        assert set(ul.lateness(planned, warmup_s=1000).values()) == {None}

    def test_the_loads_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ul, "BLOCK_GUARD_S", 1e-4)
        run = make_run(str(tmp_path), "law_x", "U50-kafka-l88-blocks", params(load=88),
                       extras={"load_blocks.csv": blocks_csv([(1500, "off"), (0, "on")])})
        switches = ul.load_switches(run)
        assert switches == ([T0, T0 + 1500 * US], ["on", "off"])
        state = lambda us: ul.block_state(switches, T0 + us * US)  # noqa: E731
        assert (state(500), state(1700), state(1550), state(-5)) == ("on", "off", None, None)
        assert ul.block_state(switches, None) is None
        assert ul.load_switches(str(tmp_path / "none")) == ([], [])
        assert ul.block_state(([], []), T0) is None

    def test_the_consumers_samples_of_its_own_thread(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(),
                       extras={"consumer_schedstat.csv": samples_csv()})
        times, execs, delays = ul.schedstat(run)
        assert times[0] == T0 - 10 * US and execs[-1] == 360 * US and delays[2] == 150 * US
        assert ul.schedstat(str(tmp_path / "none")) is None
        at = lambda us: T0 + us * US  # noqa: E731
        requests = [(at(300), at(1500), at(200), 0, at(200)),
                    (at(2000), at(2900), at(1500), 0, at(1500)),
                    (at(3000), at(4000), at(2900), 40 * US, at(2990)),
                    (at(50), None, at(-20), 0, None),     # before the first sample
                    (at(1000), None, at(1995), 0, None),  # sent before the answer came in
                    (None, None, at(200), 0, None), (at(300), None, None, None, None)]
        parts = ul.turnaround_parts(ul.schedstat(run), requests)
        assert parts == [(100.0, 20.0, 60.0), (500.0, 130.0, 240.0), (60.0, 20.0, 60.0),
                         (0.0, 0.0, 0.0)]

    def test_the_clients_collectors_and_the_duty(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l70", params(load=70), extras={
            "consumer_gc.json": json.dumps({"collections": [{"generation": 2}] * 3}),
            "producer_gc.json": json.dumps({"gc_off": True, "collections": []}),
            "load_correction.json": json.dumps({"designed_pct": 70, "duty_frozen_pct": 77})})
        assert ul.gc_collections(os.path.join(run, "consumer_gc.json")) == 3
        assert ul.gc_collections(os.path.join(run, "producer_gc.json")) == 0
        assert ul.gc_collections(os.path.join(run, "none.json")) is None
        assert ul.duty_in_effect(run) == 77
        with open(os.path.join(run, "load_recorrection.json"), "w", encoding="utf-8") as fh:
            json.dump({"duty_used_pct": 76}, fh)
        assert ul.duty_in_effect(run) == 76
        with open(os.path.join(run, "load_recorrection.json"), "w", encoding="utf-8") as fh:
            json.dump({"duty_used_pct": None}, fh)
        with open(os.path.join(run, "load_correction.json"), "w", encoding="utf-8") as fh:
            json.dump({"designed_pct": 70, "duty_used_pct": 72}, fh)
        assert ul.duty_in_effect(run) == 72
        assert ul.duty_in_effect(str(tmp_path / "none")) is None

    def test_the_runs_facts_in_a_few_words(self, tmp_path):
        host = {"stress_ng_version": "stress-ng, version 0.13.12", "irqbalance": "active",
                "network_irqs": [{"effective_affinity_list": "3"},
                                 {"effective_affinity_list": "0"},
                                 {"effective_affinity_list": "3"},
                                 {"effective_affinity_list": None}],
                "kernel_config": ["CONFIG_PREEMPT_VOLUNTARY=y", "# CONFIG_PREEMPT is not set",
                                  "CONFIG_PREEMPT_DYNAMIC=y", "CONFIG_HZ_1000=y"],
                "sched": {"sched_rt_runtime_us": "950000"},
                "client_libraries": "python 3.10.12 kafka-python 2.3.2 redis-py 5.0.1"}
        clients = {"processes": [
            {"names": "kafka_producer.py", "threads": [{"policy_name": "SCHED_FIFO"}] * 3},
            {"names": "kafka_consumer.py", "threads": [{"policy_name": "SCHED_OTHER"},
                                                       {"policy_name": None}]},
            {"names": "stress-ng", "threads": None}]}
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), extras={
            "run_facts.json": json.dumps(host), "run_facts_clients.json": json.dumps(clients)})
        facts = ul.run_facts_summary(run)
        assert facts == {"stress_ng_version": "stress-ng, version 0.13.12",
                         "irqbalance": "active", "net_irq_cpus": "0;3;None",
                         "preempt": "CONFIG_PREEMPT_VOLUNTARY=y;CONFIG_PREEMPT_DYNAMIC=y",
                         "rt_runtime_us": "950000",
                         "client_libraries": "python 3.10.12 kafka-python 2.3.2 redis-py 5.0.1",
                         "client_policies": "kafka_consumer.py=None/SCHED_OTHER;"
                                            "kafka_producer.py=SCHED_FIFO"}
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["client_policies"] == facts["client_policies"]
        assert set(ul.run_facts_summary(str(tmp_path / "none")).values()) == {None}

    def test_each_connection_pairs_floor(self):
        many = [{"net": 300.0 + i, "pair": ("a", "c")} for i in range(150)]
        few = [{"net": v, "pair": ("b", "c")} for v in (520.0, 500.0, 510.0)]
        floors = ul.path_floors(many + few + [{"net": None, "pair": ("z", "c")}])
        assert floors == {("a", "c"): pytest.approx(301.49), ("b", "c"): 500.0}


class TestOneRun:
    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_the_runs_row_and_its_split(self, tmp_path, backend):
        run = make_run(str(tmp_path), "law_x", "U2000-%s-l80" % backend, params(backend, 80))
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert (row["rate"], row["backend"], row["load_pct"], row["priority"]) == (
            2000, backend, 80, False)
        assert row["messages"] == row["timed"] == row["split"] == 4 and not row["blocks"]
        assert row["requests"] == 3 and row["overlapped"] == 0, "fetch 0 is before the window"
        assert row["flagged"] == 2 and row["exact"] == 1
        assert row["broker_matched"] == row["card_matched"] == 4 and not row["card_folded"]
        assert row["Tc_p50"] == 100 and row["dropped"] == 0 and row["broker_dropped"] == 2
        assert row["Tc45_p50"] == 100 and row["duty_pct"] is None
        assert row["load_measured"] == 79.5 and row["W_mean"] == pytest.approx(1225.0)
        assert row["Q_p50"] == pytest.approx(20.0) and row["R_p50"] == pytest.approx(900.0)
        assert row["card_window_ns"] == 800 and row["s_max_p50"] == pytest.approx(150.0)
        assert row["Dif_p50"] == pytest.approx(5.0)
        assert (row["reads"], row["reads_multi"]) == (4, 1)
        assert row["floor_pairs"] == 1 and row["floor_lo"] == row["floor_hi"] == 180
        assert row["stall_share"] == 0 and row["gc_producer"] is None and row["late_share"] is None
        assert row["Tc_wait_share"] is None and row["on_n"] == row["off_n"] == 0
        assert row["W_tail"] == 1900 and row["F_tail"] == 1400 and row["F45_tail"] == 1400
        assert row["Fb_tail"] == 1400 and row["tail_n"] == 1
        assert sorted(split) == sorted([(820.0, 0.0, 800.0, 0.0, 0.0, 20.0, 180.0, 1000.0, None),
                                        (1220.0, 0.0, 900.0, 0.0, 300.0, 20.0, 180.0, 1900.0,
                                         None),
                                        (1020.0, 0.0, 1000.0, 0.0, 0.0, 20.0, 180.0, 1200.0, None),
                                        (620.0, 0.0, 600.0, 0.0, 0.0, 20.0, 180.0, 800.0, None)])
        for s in split:
            assert s[0] == pytest.approx(sum(s[1:6])), "G splits exactly into its five terms"

    def test_version_46s_files_in_a_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ul, "BLOCK_GUARD_S", 1e-4)
        run = make_run(str(tmp_path), "law_x", "U50-kafka-l88-blocks", params(load=88),
                       planned=True, extras={
                           "consumer_schedstat.csv": samples_csv(),
                           "load_blocks.csv": blocks_csv([(0, "on"), (1500, "off"), (3000, "on")]),
                           "consumer_gc.json": json.dumps({"collections": []}),
                           "load_correction.json": json.dumps({"duty_frozen_pct": 88})})
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["blocks"] and row["on_n"] == 3 and row["off_n"] == 1
        assert [s[-1] for s in sorted(split, key=lambda s: s[7])] == ["on", "on", "off", "on"]
        assert row["Tc_wait_share"] == pytest.approx(170 / 700.0)
        assert row["Tc_cpu_share"] == pytest.approx(360 / 700.0)
        assert (row["Tc_tail_mean"], row["Tc_tail_wait"], row["Tc_tail_cpu"]) == (500, 130, 240)
        assert row["gc_consumer"] == 0 and row["duty_pct"] == 88 and row["late_share"] == 0.25

    def test_samples_that_time_no_turnaround(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(),
                       extras={"consumer_schedstat.csv": samples_csv([(5000, 0, 0)])})
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["Tc_wait_share"] is None and row["Tc_tail_mean"] is None

    def test_requests_outside_the_window_and_other_commands_are_not_turnarounds(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-redis-l0", params("redis"), other=True,
                       trailing=True)
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["requests"] == 3 and row["Tc_p50"] == 100 and row["timed"] == 4
        assert row["Tc45_p99"] == pytest.approx(100 + 400 * 0.98), "10, 100 and 500 us"

    def test_without_the_broker_the_card_or_the_client_captures(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), broker=False,
                       card=False, clients=False)
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["timed"] == 4 and row["split"] == 0 and split == []
        assert row["card_folded"] is False and row["card_window_ns"] is None
        assert row["R_p50"] is None and row["brange_p50"] is None and row["broker_dropped"] is None
        assert row["Dif_p50"] is None and (row["reads"], row["reads_multi"]) == (0, 0)
        assert row["floor_pairs"] == 0 and row["floor_lo"] is None and row["stall_share"] is None
        assert row["Fb_tail"] is None and row["W_tail"] == 1900

    def test_a_run_without_the_card_has_no_split_unless_the_block_folds_q(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), card=False)
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert not row["card_folded"] and row["split"] == 0 and split == []
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0, fold=True)
        assert row["card_folded"] and row["split"] == 4 and all(s[5] == 0 for s in split)
        assert row["net_p50"] == pytest.approx(200.0) and row["brk_p50"] == pytest.approx(900.0)

    def test_a_packet_the_card_missed_leaves_the_rest_of_its_stream_out(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), card_misses=(2,))
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["card_matched"] == row["split"] == 1 and not row["card_folded"]

    def test_a_receiver_capture_without_the_consumers_packets_counts_no_reads(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params())
        write_pcap(os.path.join(run, "receiver_full.pcap"), [])
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert (row["reads"], row["reads_multi"]) == (0, 0) and row["Dif_p50"] is None

    def test_messages_the_journal_cannot_time_are_left_out(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), unjournaled=True,
                       ack_missing=True)
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["messages"] == 5 and row["timed"] == 3

    def test_a_run_whose_messages_never_arrived_has_no_window(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params())
        os.remove(os.path.join(run, "consumer_so.csv"))
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["requests"] == 0 and row["Tc_p50"] is None and row["timed"] == 0
        assert row["W_tail"] is None and row["tail_n"] == 0


class TestTails:
    def test_the_pooled_means_the_tail_and_the_blocks(self):
        split = [(float(g), 1.0, g - 4.0, 1.0, 1.0, 1.0, 300.0, g + 400.0,
                  "on" if g % 2 else "off") for g in range(1, 201)]
        t = ul.tail_summary("U2000-redis-l80", split, 3)
        assert (t["rate"], t["backend"], t["load_pct"], t["priority"], t["blocks"]) == (
            2000, "redis", 80, False, False)
        assert t["split"] == t["all_n"] == 200 and t["tail_n"] == 2
        assert t["all_G"] == pytest.approx(100.5) and t["tail_G"] == pytest.approx(199.5)
        assert t["tail_hand"] == pytest.approx(195.5) and t["tail_floor"] == 300
        assert t["on_n"] == t["off_n"] == 100 and t["on_G"] == 100 and t["off_G"] == 101
        assert t["runs_pooled"] == 3 and t["tail_W"] == pytest.approx(599.5)

    def test_an_empty_setup_has_no_tail(self):
        t = ul.tail_summary("U50-kafka-l88-blocks", [])
        assert t["tail_cut"] is None and t["tail_n"] == 0 and t["all_G"] is None
        assert t["blocks"] and t["on_G"] is None


class TestTheBlock:
    def test_judged_pilot_failed_and_foreign_runs(self, tmp_path):
        folder = str(tmp_path)
        make_run(folder, "law_a", "U2000-kafka-l0", params())
        make_run(folder, "law_b", "U2000-kafka-l0", params())
        make_run(folder, "law_c", "UP2000-kafka-l0", params())
        make_run(folder, "law_d", "U2000-kafka-l80", params(load=80), verdict="repeat")
        make_run(folder, "law_e", "L2000-kafka-l0", params())
        make_run(folder, "law_f", "U2000-kafka-l80", params(load=80), verdict=None)
        os.makedirs(os.path.join(folder, "notes"))
        open(os.path.join(folder, "law_g.txt"), "w").close()
        found, skipped, failed = ul.block_runs([folder])
        assert {s: len(v) for s, v in found.items()} == {"U2000-kafka-l0": 2}
        assert skipped == [("law_d", "repeat"), ("law_f", "not judged")]
        assert [os.path.basename(p) for p in failed["U2000-kafka-l80"]] == ["law_d", "law_f"]
        found, _, _ = ul.block_runs([folder], pilot=True)
        assert list(found) == ["UP2000-kafka-l0"]

    def test_a_setups_runs_are_pooled_where_their_split_reaches_far_enough(self, tmp_path):
        folder = str(tmp_path)
        make_run(folder, "law_a", "U2000-kafka-l0", params())
        make_run(folder, "law_b", "U2000-kafka-l0", params())
        make_run(folder, "law_c", "U2000-kafka-l0", params(), card_misses=(2,))
        rows, tails, skipped, attempts = ul.read_block([folder], DRIVER, BROKER, RECEIVER,
                                                       warmup_s=0)
        assert len(rows) == 3 and skipped == [] and attempts == []
        assert [r["pooled"] for r in rows] == [True, True, False]
        assert tails[0]["split"] == 8 and tails[0]["runs_pooled"] == 2

    def test_a_block_without_the_card_folds_q_and_one_with_it_leaves_out_a_run_without(
            self, tmp_path):
        bare = str(tmp_path / "bare")
        make_run(bare, "law_a", "U2000-kafka-l0", params(), card=False)
        make_run(bare, "law_b", "U2000-kafka-l80", params(load=80), card=False)
        make_run(bare, "law_c", "U2000-kafka-l80", params(load=80), card=False, verdict="repeat")
        rows, tails, _, attempts = ul.read_block([bare], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert all(r["card_folded"] and r["pooled"] for r in rows)
        assert [t["split"] for t in tails] == [4, 4] and tails[0]["all_Q"] == 0
        assert attempts[0]["card_folded"] and attempts[0]["split"] == 4
        mixed = str(tmp_path / "mixed")
        make_run(mixed, "law_a", "U2000-kafka-l0", params())
        make_run(mixed, "law_b", "U2000-kafka-l0", params(), card=False)
        rows, tails, _, _ = ul.read_block([mixed], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert [(r["card_folded"], r["pooled"]) for r in rows] == [(False, True), (False, False)]
        assert tails[0]["runs_pooled"] == 1 and tails[0]["split"] == 4

    def test_a_run_with_nothing_timed_is_not_pooled(self, tmp_path):
        folder = str(tmp_path)
        run = make_run(folder, "law_a", "U2000-kafka-l0", params())
        os.remove(os.path.join(run, "consumer_so.csv"))
        rows, tails, _, _ = ul.read_block([folder], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert rows[0]["pooled"] is False and tails[0]["runs_pooled"] == 0

    def test_every_failed_attempt_is_read_where_its_files_allow(self, tmp_path):
        folder = str(tmp_path)
        make_run(folder, "law_a", "U2000-kafka-l70", params(load=70), verdict="repeat")
        broken = make_run(folder, "law_b", "U2000-kafka-l70", params(load=70), verdict="repeat")
        os.remove(os.path.join(broken, "producer.csv"))
        _, _, _, attempts = ul.read_block([folder], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert [a["run"] for a in attempts] == ["law_a", "law_b"]
        assert attempts[0]["verdict"] == "repeat" and attempts[0]["W_p99"] is not None
        assert attempts[0]["reasons"] == "the measured load was 63.3%"
        assert attempts[1]["unreadable"].startswith(("FileNotFoundError", "OSError", "ValueError"))


def row(rate, backend, load, rt=False, **fields):
    setup = "U%d-%s-l%d%s" % (rate, backend, load, "-rt" if rt else "")
    out = {"setup": setup, "rate": rate, "backend": backend, "load_pct": load, "priority": rt,
           "timed": "10", "flagged": "5", "exact": "1", "broker_matched": "10",
           "card_matched": "0", "split": "10", "reads": "4", "reads_multi": "1"}
    out.update(fields)
    return out


def block(tc=(500.0, 4000.0, 600.0), w=(1700.0, 6000.0, 2000.0),
          w_tail=((2000.0, 2100.0), (6000.0, 6400.0), (2500.0, 2600.0)),
          f_tail=((1500.0, 1550.0), (1700.0, 1720.0), (1600.0, 1650.0)), rates=(500, 2000)):
    """Run rows for the upper rates, two runs per setup, values (idle, load, real-time); U-c's
    tail means differ between a setup's two runs."""
    rows = []
    for rate in rates:
        for backend in ("kafka", "redis"):
            for (load, rt), i in (((0, False), 0), ((80, False), 1), ((80, True), 2)):
                for k in range(2):
                    rows.append(row(rate, backend, load, rt, Tc_p99=str(tc[i]),
                                    Tc_p50=str(tc[i] / 4), W_p99=str(w[i]),
                                    W_tail=str(w_tail[i][k]), F_tail=str(f_tail[i][k]),
                                    F45_tail=str(f_tail[i][k] + 100),
                                    Fb_tail=str(f_tail[i][k] - 100),
                                    W_p50="900", D_p50="1100"))
    return rows


class TestJudgingThePredictions:
    def test_all_four_confirmed(self):
        v = ul.judge(block(), [], draws=200)
        for name in ("U-a", "U-b", "U-c", "U-d"):
            assert v[name]["verdict"] == "confirmed" and not v[name]["out_of_reach"], name
        c = v["U-c"]["checks"][0]
        # idle W 2050, F 1525; load W 6200, F 1710: 1 - 185 / 4150
        assert c["share"] == pytest.approx(1 - 185.0 / 4150.0)
        assert c["low"] <= c["share"] <= c["high"] and c["low"] >= 0.9 and c["only_path"]
        assert c["share_45"] == pytest.approx(c["share"]) and c["undefined_draws"] == 0
        assert c["share_broker_bound"] == pytest.approx(c["share"])
        assert c["after_U_b"] and v["U-b"]["gives_way_at"][0] == (500, "kafka")

    def test_each_fails_on_its_own_margin(self):
        assert ul.judge_turnaround(block(tc=(500.0, 700.0, 100.0)))["verdict"] == "not confirmed"
        assert ul.judge_turnaround(block(tc=(500.0, 4000.0, 2500.0)))["verdict"] == (
            "not confirmed")
        assert ul.judge_fix_alone(block(w=(1700.0, 2000.0, 900.0)))["verdict"] == "not confirmed"
        assert ul.judge_priority(block(w=(1700.0, 6000.0, 3500.0)))["verdict"] == "not confirmed"
        everywhere = {(r, b) for r in (500, 2000) for b in ("kafka", "redis")}
        lost = ul.judge_removal(block(f_tail=((1500.0, 1500.0), (4500.0, 4500.0),
                                              (1600.0, 1600.0))), everywhere, draws=50)
        assert lost["verdict"] == "not confirmed" and not lost["checks"][0]["only_path"]
        partial = ul.judge_removal(block(f_tail=((1500.0, 1500.0), (2500.0, 2600.0),
                                                 (1600.0, 1600.0))), everywhere,
                                   draws=200)["checks"][0]
        assert partial["holds"] and not partial["only_path"] and partial["low"] < 0.9

    def test_u_c_is_not_judged_where_u_b_holds_nowhere(self):
        v = ul.judge(block(w=(1700.0, 2000.0, 900.0)), [], draws=10)
        assert v["U-b"]["verdict"] == "not confirmed" and v["U-b"]["gives_way_at"] == []
        assert v["U-c"]["verdict"] == "not judged" and v["U-c"]["out_of_reach"] == []
        assert v["U-c"]["not_judged"] == [(500, "kafka"), (500, "redis"), (2000, "kafka"),
                                          (2000, "redis")]
        assert all(c["share"] is None and not c["after_U_b"] and c["share_45"] is None
                   for c in v["U-c"]["checks"])

    def test_u_cs_share_needs_every_runs_tail_and_a_rise(self):
        idle = [row(500, "kafka", 0, W_tail="2000", F_tail="1500")]
        busy = [row(500, "kafka", 80, W_tail="6000", F_tail="1700")]
        assert ul.removal_share(idle, busy) == pytest.approx(1 - 200.0 / 4000.0)
        assert ul.removal_share(idle, [row(500, "kafka", 80, W_tail="6000", F_tail="")]) is None
        assert ul.removal_share(idle, []) is None
        assert ul.removal_share(busy, idle) is None, "W_so's tail did not rise"
        assert ul.removal_interval(busy, idle, draws=5) == (None, None, 5)

    def test_a_cell_u_b_reaches_without_its_runs_is_out_of_reach_for_u_c(self):
        rows = [r for r in block() if not (r["rate"] == 500 and r["backend"] == "kafka"
                                           and r["load_pct"] == 0)]
        v = ul.judge_removal(rows, {(500, "kafka")}, draws=10)
        assert v["verdict"] == "out of reach" and v["out_of_reach"] == [(500, "kafka")]

    def test_a_failed_growth_clause_fails_its_cell_without_its_real_time_setup(self):
        rows = [r for r in block(tc=(500.0, 600.0, 100.0)) if not r["priority"]]
        v = ul.judge_turnaround(rows)
        assert v["verdict"] == "not confirmed" and v["out_of_reach"] == []
        assert all(c["grew"] is False and c["held"] is None and c["holds"] is False
                   for c in v["checks"])

    def test_a_setup_with_no_passing_run_puts_its_cells_out_of_reach(self):
        rows = [r for r in block() if not (r["rate"] == 500 and r["backend"] == "redis"
                                           and r["priority"])]
        v = ul.judge(rows, [], draws=10)
        assert v["U-a"]["verdict"] == "confirmed" and v["U-a"]["out_of_reach"] == [
            (500, "redis")]
        assert v["U-d"]["out_of_reach"] == [(500, "redis")]
        assert v["U-b"]["verdict"] == "confirmed" and not v["U-b"]["out_of_reach"]
        assert ul.judge_turnaround([])["verdict"] == "out of reach"

    def test_two_loads_at_one_rate_are_refused(self):
        rows = block() + [row(500, "kafka", 70, Tc_p99="1")]
        with pytest.raises(ValueError, match="at loads \\[70, 80\\]"):
            ul.loaded_level(rows, 500, "kafka")
        assert ul.loaded_level([], 500, "kafka") is None


def tail(rate, backend, load, prefix, g, terms, floor=180.0, blocks=False, **more):
    """A tail row: G and its five terms under `prefix`, and the floor."""
    out = {"setup": "U%d-%s-l%d%s" % (rate, backend, load, "-blocks" if blocks else ""),
           "rate": rate, "backend": backend, "load_pct": load, "priority": False,
           "blocks": blocks, "%s_G" % prefix: g, "%s_floor" % prefix: floor}
    out.update(("%s_%s" % (prefix, n), v) for n, v in zip(ul.TERMS, terms))
    out.update(more)
    return out


class TestNamingTheTerm:
    def test_the_term_that_holds_half(self):
        d = ul.name_the_term(tail(2000, "redis", 0, "tail", 1500, (200, 1000, 0, 200, 100)),
                             tail(2000, "redis", 80, "tail", 2500, (300, 1000, 0, 300, 900),
                                  floor=430.0), "tail")
        assert d["rise"] == 1000 and d["terms"] == {"excess": 100, "hand": 0, "ack": 0,
                                                    "wait": 100, "Q": 800}
        assert d["named"] == "Q" and d["floor"] == 250

    def test_the_largest_when_two_do(self):
        d = ul.name_the_term(tail(2000, "redis", 0, "tail", 1000, (0, 1000, 0, 0, 0)),
                             tail(2000, "redis", 80, "tail", 2000, (700, 1000, 600, 0, -300)),
                             "tail")
        assert d["named"] == "excess" and d["terms"]["Q"] == -300

    def test_none_when_no_term_holds_half_or_nothing_rose(self):
        d = ul.name_the_term(tail(500, "kafka", 0, "tail", 1000, (0, 1000, 0, 0, 0)),
                             tail(500, "kafka", 80, "tail", 1900, (300, 1300, 0, 0, 300)), "tail")
        assert d["named"] is None
        d = ul.name_the_term(tail(500, "kafka", 0, "tail", 1000, (0, 1000, 0, 0, 0)),
                             tail(500, "kafka", 80, "tail", 900, (0, 900, 0, 0, 0)), "tail")
        assert d["named"] is None and d["rise"] == -100

    def test_a_missing_tail_decides_nothing(self):
        assert ul.name_the_term(None, None, "tail")["rise"] is None
        partial = tail(500, "kafka", 0, "tail", 1000, (None, 1000, 0, 0, 0))
        assert ul.name_the_term(partial, partial, "tail")["named"] is None
        unfloored = tail(500, "kafka", 0, "tail", 1000, (0, 1000, 0, 0, 0), floor=None)
        assert ul.name_the_term(unfloored, unfloored, "tail")["floor"] is None

    def test_both_decisions_from_the_tables(self):
        rows = block() + [row(50, b, load, Tc_p99="1") for b in ("kafka", "redis")
                          for load in (0, 88)]
        tails = [tail(r, b, load, "tail", 1000 + load * 10, (0, 1000, 0, load * 10, 0))
                 for r in (500, 2000) for b in ("kafka", "redis") for load in (0, 80)]
        for b in ("kafka", "redis"):
            tails.append(tail(50, b, 0, "all", 500, (0, 500, 0, 0, 0)))
            on = {"on_%s" % n: v for n, v in zip(("G",) + ul.TERMS, (560, 0, 500, 0, 0, 60))}
            on["on_floor"] = 180.0
            tails.append(tail(50, b, 88, "off", 500, (0, 500, 0, 0, 0), blocks=True, **on))
        out = ul.judge_split(rows, tails)
        assert [d["named"] for d in out["U-e"]["decisions"]] == ["wait"] * 4
        assert [d["named"] for d in out["U-f"]["decisions"]] == ["Q", "Q"]
        assert out["U-f"]["decisions"][0]["load"] == 88
        assert out["U-f"]["decisions"][0]["between_runs"]["rise"] == 60

    def test_u_f_without_blocks_decides_nothing(self):
        rows = [row(50, "kafka", 0, Tc_p99="1"), row(50, "kafka", 88, Tc_p99="1")]
        out = ul.judge_split(rows, [tail(50, "kafka", 0, "all", 500, (0, 500, 0, 0, 0))])
        assert out["U-f"]["decisions"][0]["rise"] is None


class TestDescribed:
    def test_medians_and_shares_setup_by_setup(self):
        rows = [row(2000, "kafka", 0, W_p50="900", timed="10", flagged="5", late_share="0.5"),
                row(2000, "kafka", 0, W_p50="1100", timed="0", flagged="0", reads="0",
                    late_share="")]
        d = ul.described(rows)
        assert d[0]["W_p50"] == 1000 and d[0]["flagged_share"] == 0.5
        assert d[0]["card_matched_share"] == 0.0 and d[0]["R_p50"] is None
        assert d[0]["reads_multi_share"] == 0.25 and d[0]["late_share"] == 0.5
        assert d[0]["irqbalance"] == [] and d[0]["preempt"] == []
        facts = [row(2000, "kafka", 0, irqbalance=state) for state in ("active", "", "active",
                                                                        "inactive")]
        assert ul.described(facts)[0]["irqbalance"] == ["active", "inactive"]

    def test_the_wait_for_a_core_and_what_it_leaves(self):
        out = ul.wait_and_interference(block())
        assert out[0] == {"rate": 500, "backend": "kafka", "wait_p50": 850.0,
                          "interference_p50": 25.0, "wait_p99": 3400.0, "interference_p99": 100.0}
        assert ul.wait_and_interference([])[0]["wait_p99"] is None

    def test_each_setup_with_its_failed_attempts(self):
        rows = [row(2000, "kafka", 70, W_p99="5000", Tc_p99="4000")]
        attempts = [row(2000, "kafka", 70, W_p99="7000", Tc_p99="6000", unreadable=""),
                    row(2000, "kafka", 70, unreadable="FileNotFoundError: producer.csv"),
                    row(2000, "redis", 70, unreadable="OSError: gone")]
        out = ul.with_failed(rows, attempts)
        assert out[0] == {"setup": "U2000-kafka-l70", "attempts": 3, "failed": 2,
                          "W_p99": 6000.0, "Tc_p99": 5000.0}
        assert out[1] == {"setup": "U2000-redis-l70", "attempts": 1, "failed": 1,
                          "W_p99": None, "Tc_p99": None}

    def test_what_the_extra_instruments_cost_against_block_l(self):
        ladder = [{"rate": r, "backend": b, "load_pct": 0, "Wso_median": "850",
                   "D_median": "1000"} for r in (500, 2000) for b in ("kafka", "redis")]
        cost = ul.judge(block(), [], ladder, draws=10)["described"]["capture_cost"]
        assert cost[0] == {"rate": 500, "backend": "kafka", "W_U": 900.0, "W_L": 850.0,
                           "W_moved": 50.0, "D_U": 1100.0, "D_L": 1000.0, "D_moved": 100.0}
        assert ul.capture_cost(block(), [])[0]["W_moved"] is None


class TestFilesAndTheCommandLine:
    def test_read_and_judge(self, tmp_path, capsys):
        folder = str(tmp_path / "runs")
        os.makedirs(folder)
        make_run(folder, "law_a", "U2000-kafka-l0", params())
        make_run(folder, "law_b", "U2000-kafka-l80", params(load=80), verdict="repeat")
        runs, tails = str(tmp_path / "u_runs.csv"), str(tmp_path / "u_tails.csv")
        attempts = str(tmp_path / "u_attempts.csv")
        assert ul.main(["read", "--runs", folder, "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--out-runs", runs, "--out-tails", tails,
                        "--out-attempts", attempts, "--warmup", "0"]) == 0
        out = capsys.readouterr().out
        assert "left out law_b: repeat" in out and "OK 1 runs of block U ->" in out
        ladder = str(tmp_path / "l_runs.csv")
        with open(ladder, "w", encoding="utf-8", newline="") as fh:
            fh.write("rate,backend,load_pct,Wso_median,D_median\n2000,kafka,0,800,1000\n")
        verdicts = str(tmp_path / "u_verdicts.json")
        assert ul.main(["judge", "--runs-table", runs, "--tails-table", tails, "--ladder-table",
                        ladder, "--attempts-table", attempts, "--out", verdicts]) == 0
        with open(verdicts, encoding="utf-8") as fh:
            judged = json.load(fh)
        assert judged["U-a"]["verdict"] == "out of reach" and judged["described"]["setups"]
        assert judged["described"]["capture_cost"][2]["W_L"] == 800.0
        assert [w["setup"] for w in judged["described"]["with_failed"]] == [
            "U2000-kafka-l0", "U2000-kafka-l80"]
        assert "U-e: decision recorded" in capsys.readouterr().out

    def test_the_pilot_is_read_by_name_and_attempts_are_optional(self, tmp_path, capsys):
        folder = str(tmp_path / "runs")
        os.makedirs(folder)
        make_run(folder, "law_a", "UP2000-kafka-l0", params())
        assert ul.main(["read", "--pilot", "--runs", folder, "--driver", DRIVER, "--broker",
                        BROKER, "--receiver", RECEIVER, "--out-runs", str(tmp_path / "r.csv"),
                        "--out-tails", str(tmp_path / "t.csv"), "--warmup", "0"]) == 0
        assert "OK 1 runs of block U's pilot" in capsys.readouterr().out
        assert not os.path.exists(str(tmp_path / "u_attempts.csv"))

    def test_tables_come_back_typed(self, tmp_path):
        path = str(tmp_path / "t.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["rate", "load_pct", "priority", "blocks", "all_G", "tail_G", "on_G",
                        "off_G", "note"])
            w.writerow(["2000", "80.0", "True", "False", "1.5", "", "2", "None", "x"])
            w.writerow(["", "", "maybe", "True", "", "2", "", "", ""])
        a, b = ul.read_table(path)
        assert (a["rate"], a["load_pct"], a["priority"], a["blocks"], a["all_G"], a["tail_G"],
                a["on_G"], a["off_G"]) == (2000, 80, True, False, 1.5, None, 2.0, None)
        assert b["rate"] == "" and b["priority"] == "maybe" and b["tail_G"] == 2.0 and b["blocks"]
        assert ul.read_table(str(tmp_path / "none.csv")) == [] and ul.read_table(None) == []
        bare = str(tmp_path / "bare.csv")
        with open(bare, "w", encoding="utf-8", newline="") as fh:
            fh.write("rate,setup\n50,U50-kafka-l0\n")
        assert ul.read_table(bare) == [{"rate": 50, "setup": "U50-kafka-l0"}]
