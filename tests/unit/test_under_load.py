"""Tests for scripts/under_load.py, freeze 42's reader and judge, against runs built here file by
file in the shape the kit writes them: the clients' own files, their socket files and journals, both
client captures, the broker's own capture on the broker's clock, and the card's capture with its
clock samples."""
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
             trailing=False, card_misses=()):
    run = os.path.join(folder, name)
    os.makedirs(run)
    backend = params["backend"]
    port = PORT[backend]
    with open(os.path.join(run, "queue_row.json"), "w", encoding="utf-8") as fh:
        json.dump({"setup": setup, "params": params}, fh)
    with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "checks": {"load": {"value": 79.5}}}, fh)
    msgs = list(MESSAGES) + ([dict(MESSAGES[-1], pub=3500)] if unjournaled else [])
    with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,t_prod_send_ns,t_broker_ack_ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,%d,%d\n" % (eid(i), T0 + m["pub"] * US, T0 + m["ack"] * US))
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
    return run


def params(backend="kafka", load=0, rt=False):
    p = {"backend": backend, "load_pct": load, "slice_ns": 3000000, "delay_ms": 0}
    if rt:
        p["priority"] = True
    return p


class TestSetupIds:
    def test_judged_pilot_and_other_ids(self):
        assert ul.setup_parts("U2000-kafka-l80-rt") == (2000, "kafka", 80, True)
        assert ul.setup_parts("U50-redis-l0") == (50, "redis", 0, False)
        assert ul.setup_parts("UP500-redis-l80") == (500, "redis", 80, False)
        assert ul.setup_parts("L2000-kafka-l0") is None


class TestTheConsumersJournal:
    def test_a_redis_command_is_named_by_its_first_word(self):
        data = resp(b"xack", b"sb") + b"*1\r\n"
        assert ul.command_name(data, 0) == b"XACK"
        assert ul.command_name(data, len(data) - 4) == b""

    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_the_turnaround_starts_at_whatever_was_answered_last(self, tmp_path, backend):
        import so_journal as sj
        run = make_run(str(tmp_path), "law_x", "U2000-%s-l0" % backend, params(backend),
                       other=True)
        per_request, by_id = ul.turnarounds(sj.load(os.path.join(run, "consumer_journal")),
                                            backend)
        before = [None if b is None else (b - T0) // US for _, _, b in per_request]
        assert before == [None, 200, 1500, 2990], "fetch 3 waits from the other command's answer"
        assert by_id[eid(3)] == (T0 + 3000 * US, T0 + 2990 * US)
        assert by_id[eid(1)] == by_id[eid(2)] == (T0 + 2000 * US, T0 + 1500 * US)


class TestOneMessage:
    def message(self, **change):
        m = {"Wso": 1200.0, "tx_so": 1700 * US, "rx_so": 2900 * US, "rx_ack": 2300 * US,
             "D": 1400.0}
        m.update(change)
        return m

    def test_the_bounds_and_the_split_add_up(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US),
                             [1800 * US, 2200 * US, 2100 * US, 2800 * US], 2880 * US)
        assert p["Tc"] == 500 and p["s_min"] == 0 and p["s_max"] == 300
        assert p["F"] == 1200 and p["F_lo"] == 900 and p["flagged"] and not p["exact"]
        assert p["R"] == 1000 and p["Q"] == 20 and p["b_min"] == 0 and p["b_max"] == 300
        assert p["net"] + p["brk"] + p["q_term"] == p["F"]

    def test_an_acknowledgment_before_the_previous_answer_makes_it_exact(self):
        p = ul.message_parts(self.message(rx_ack=1400 * US, tx_so=1000 * US, Wso=1900.0),
                             (2000 * US, 1500 * US), None, None)
        assert p["s_min"] == p["s_max"] == 500 and p["exact"]
        assert p["R"] is None and p["Q"] is None and p["net"] is None

    def test_a_request_that_overlapped_the_answer_adds_nothing(self):
        p = ul.message_parts(self.message(), (1400 * US, 1500 * US), None, None)
        assert p["Tc"] == 0 and p["s_min"] == p["s_max"] == 0

    def test_a_broker_reading_without_its_acknowledgment_has_no_range(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US),
                             [1800 * US, None, 2100 * US, 2800 * US], None)
        assert p["R"] == 1000 and p["b_min"] is None and p["net"] is None

    def test_a_run_without_the_card_folds_q_into_the_first_term(self):
        p = ul.message_parts(self.message(), (2000 * US, 1500 * US),
                             [1800 * US, 2200 * US, 2100 * US, 2800 * US], None, card_ran=False)
        assert p["Q"] is None and p["q_term"] == 0 and p["net"] == 200
        assert p["net"] + p["brk"] + p["q_term"] == p["F"]

    @pytest.mark.parametrize("missing", ["Wso", "tx_so", "rx_so", "rx_ack"])
    def test_a_client_time_missing_times_nothing(self, missing):
        assert ul.message_parts(self.message(**{missing: None}), (2000 * US, 1500 * US),
                                None, None) is None

    def test_the_first_request_on_a_connection_times_nothing(self):
        assert ul.message_parts(self.message(), (2000 * US, None), None, None) is None


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


class TestOneRun:
    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_the_runs_row_and_its_split(self, tmp_path, backend):
        run = make_run(str(tmp_path), "law_x", "U2000-%s-l80" % backend, params(backend, 80))
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert (row["rate"], row["backend"], row["load_pct"], row["priority"]) == (
            2000, backend, 80, False)
        assert row["messages"] == row["timed"] == row["split"] == 4
        assert row["requests"] == 3 and row["overlapped"] == 0, "fetch 0 is before the window"
        assert row["flagged"] == 2 and row["exact"] == 1
        assert row["broker_matched"] == row["card_matched"] == 4 and not row["card_folded"]
        assert row["Tc_p50"] == 100 and row["dropped"] == 0 and row["broker_dropped"] == 2
        assert row["load_measured"] == 79.5 and row["W_mean"] == pytest.approx(1225.0)
        assert row["Q_p50"] == pytest.approx(20.0) and row["R_p50"] == pytest.approx(900.0)
        assert row["card_window_ns"] == 800 and row["s_max_p50"] == pytest.approx(150.0)
        assert row["Dif_p50"] == pytest.approx(5.0)
        assert (row["reads"], row["reads_multi"]) == (4, 1)
        assert sorted(split) == sorted([(1000.0, 180.0, 800.0, 20.0, 1000.0),
                                        (1400.0, 180.0, 1200.0, 20.0, 1900.0),
                                        (1200.0, 180.0, 1000.0, 20.0, 1200.0),
                                        (800.0, 180.0, 600.0, 20.0, 800.0)])

    def test_requests_outside_the_window_and_other_commands_are_not_turnarounds(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-redis-l0", params("redis"), other=True,
                       trailing=True)
        row, _ = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["requests"] == 3 and row["Tc_p50"] == 100 and row["timed"] == 4

    def test_without_the_broker_the_card_or_the_client_captures(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), broker=False,
                       card=False, clients=False)
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert row["timed"] == 4 and row["split"] == 0 and split == []
        assert row["card_folded"] is False and row["card_window_ns"] is None
        assert row["R_p50"] is None and row["brange_p50"] is None and row["broker_dropped"] is None
        assert row["Dif_p50"] is None and (row["reads"], row["reads_multi"]) == (0, 0)

    def test_a_run_without_the_card_has_no_split_unless_the_block_folds_q(self, tmp_path):
        run = make_run(str(tmp_path), "law_x", "U2000-kafka-l0", params(), card=False)
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert not row["card_folded"] and row["split"] == 0 and split == []
        row, split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0, fold=True)
        assert row["card_folded"] and row["split"] == 4 and all(s[3] == 0 for s in split)
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


class TestTails:
    def test_the_pooled_means_and_the_tail_above_the_99th_percentile(self):
        split = [(float(f), 1.0, f - 2.0, 1.0, float(f)) for f in range(1, 201)]
        t = ul.tail_summary("U2000-redis-l80", split, 3)
        assert (t["rate"], t["backend"], t["load_pct"], t["priority"]) == (2000, "redis", 80,
                                                                            False)
        assert t["split"] == 200 and t["tail_n"] == 2 and t["all_F"] == pytest.approx(100.5)
        assert t["tail_F"] == pytest.approx(199.5) and t["tail_brk"] == pytest.approx(197.5)
        assert t["runs_pooled"] == 3

    def test_an_empty_setup_has_no_tail(self):
        t = ul.tail_summary("U50-kafka-l88", [])
        assert t["tail_cut"] is None and t["tail_n"] == 0 and t["all_F"] is None


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
        found, skipped = ul.block_runs([folder])
        assert {s: len(v) for s, v in found.items()} == {"U2000-kafka-l0": 2}
        assert skipped == [("law_d", "repeat"), ("law_f", "not judged")]
        found, _ = ul.block_runs([folder], pilot=True)
        assert list(found) == ["UP2000-kafka-l0"]

    def test_a_setups_runs_are_pooled_where_their_split_reaches_far_enough(self, tmp_path):
        folder = str(tmp_path)
        make_run(folder, "law_a", "U2000-kafka-l0", params())
        make_run(folder, "law_b", "U2000-kafka-l0", params())
        make_run(folder, "law_c", "U2000-kafka-l0", params(), card_misses=(2,))
        rows, tails, skipped = ul.read_block([folder], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert len(rows) == 3 and skipped == [] and [r["pooled"] for r in rows] == [
            True, True, False]
        assert tails[0]["split"] == 8 and tails[0]["runs_pooled"] == 2

    def test_a_block_without_the_card_folds_q_and_one_with_it_leaves_out_a_run_without(
            self, tmp_path):
        bare = str(tmp_path / "bare")
        make_run(bare, "law_a", "U2000-kafka-l0", params(), card=False)
        make_run(bare, "law_b", "U2000-kafka-l80", params(load=80), card=False)
        rows, tails, _ = ul.read_block([bare], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert all(r["card_folded"] and r["pooled"] for r in rows)
        assert [t["split"] for t in tails] == [4, 4] and tails[0]["all_Q"] == 0
        mixed = str(tmp_path / "mixed")
        make_run(mixed, "law_a", "U2000-kafka-l0", params())
        make_run(mixed, "law_b", "U2000-kafka-l0", params(), card=False)
        rows, tails, _ = ul.read_block([mixed], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert [(r["card_folded"], r["pooled"]) for r in rows] == [(False, True), (False, False)]
        assert tails[0]["runs_pooled"] == 1 and tails[0]["split"] == 4

    def test_a_run_with_nothing_timed_is_not_pooled(self, tmp_path):
        folder = str(tmp_path)
        run = make_run(folder, "law_a", "U2000-kafka-l0", params())
        os.remove(os.path.join(run, "consumer_so.csv"))
        rows, tails, _ = ul.read_block([folder], DRIVER, BROKER, RECEIVER, warmup_s=0)
        assert rows[0]["pooled"] is False and tails[0]["runs_pooled"] == 0


def row(rate, backend, load, rt=False, **fields):
    setup = "U%d-%s-l%d%s" % (rate, backend, load, "-rt" if rt else "")
    out = {"setup": setup, "rate": rate, "backend": backend, "load_pct": load, "priority": rt,
           "timed": "10", "flagged": "5", "exact": "1", "broker_matched": "10",
           "card_matched": "0", "split": "10", "reads": "4", "reads_multi": "1"}
    out.update(fields)
    return out


def block(tc=(500.0, 4000.0, 600.0), w=(1700.0, 6000.0, 2000.0), f=(1300.0, 1400.0, 1350.0),
          rates=(500, 2000)):
    """Run rows for the upper rates, two runs per setup, values (idle, load, real-time)."""
    rows = []
    for rate in rates:
        for backend in ("kafka", "redis"):
            for (load, rt), i in (((0, False), 0), ((80, False), 1), ((80, True), 2)):
                for _ in range(2):
                    rows.append(row(rate, backend, load, rt, Tc_p99=str(tc[i]), W_p99=str(w[i]),
                                    F_p99=str(f[i]), W_p50="900", D_p50="1100"))
    return rows


class TestJudgingThePredictions:
    def test_all_four_confirmed(self):
        v = ul.judge(block(), [])
        for name in ("U-a", "U-b", "U-c", "U-d"):
            assert v[name]["verdict"] == "confirmed" and not v[name]["out_of_reach"], name
        c = v["U-c"]["checks"][0]
        assert c["share"] == pytest.approx(1 - 100.0 / 4300.0) and c["only_path"]
        assert c["after_U_b"] and v["U-b"]["gives_way_at"][0] == (500, "kafka")

    def test_each_fails_on_its_own_margin(self):
        assert ul.judge_turnaround(block(tc=(500.0, 700.0, 100.0)))["verdict"] == "not confirmed"
        assert ul.judge_turnaround(block(tc=(500.0, 4000.0, 2500.0)))["verdict"] == (
            "not confirmed")
        assert ul.judge_fix_alone(block(w=(1700.0, 2000.0, 900.0)))["verdict"] == "not confirmed"
        assert ul.judge_priority(block(w=(1700.0, 6000.0, 3500.0)))["verdict"] == "not confirmed"
        everywhere = {(r, b) for r in (500, 2000) for b in ("kafka", "redis")}
        checks = ul.judge_removal(block(f=(1300.0, 3800.0, 1300.0)), everywhere)
        assert checks["verdict"] == "not confirmed" and not checks["checks"][0]["only_path"]
        partial = ul.judge_removal(block(f=(1300.0, 2300.0, 1300.0)), everywhere)["checks"][0]
        assert partial["holds"] and not partial["only_path"]

    def test_u_c_is_judged_only_where_u_b_holds(self):
        v = ul.judge(block(w=(1700.0, 2000.0, 900.0)), [])
        assert v["U-b"]["verdict"] == "not confirmed" and v["U-b"]["gives_way_at"] == []
        assert v["U-c"]["verdict"] == "out of reach" and v["U-c"]["out_of_reach"] == []
        assert v["U-c"]["not_judged"] == [(500, "kafka"), (500, "redis"), (2000, "kafka"),
                                          (2000, "redis")]
        assert all(c["share"] is None and not c["after_U_b"] for c in v["U-c"]["checks"])

    def test_a_failed_growth_clause_fails_its_cell_without_its_real_time_setup(self):
        rows = [r for r in block(tc=(500.0, 600.0, 100.0)) if not r["priority"]]
        v = ul.judge_turnaround(rows)
        assert v["verdict"] == "not confirmed" and v["out_of_reach"] == []
        assert all(c["grew"] is False and c["held"] is None and c["holds"] is False
                   for c in v["checks"])

    def test_a_setup_with_no_passing_run_puts_its_cells_out_of_reach(self):
        rows = [r for r in block() if not (r["rate"] == 500 and r["backend"] == "redis"
                                           and r["priority"])]
        v = ul.judge(rows, [])
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


def tail(rate, backend, load, prefix, f, net, brk, q):
    return {"setup": "U%d-%s-l%d" % (rate, backend, load), "rate": rate, "backend": backend,
            "load_pct": load, "priority": False, "%s_F" % prefix: f, "%s_net" % prefix: net,
            "%s_brk" % prefix: brk, "%s_Q" % prefix: q}


class TestNamingTheTerm:
    def test_the_term_that_holds_half(self):
        d = ul.name_the_term(tail(2000, "redis", 0, "tail", 1500, 200, 1200, 100),
                             tail(2000, "redis", 80, "tail", 2500, 300, 1300, 900), "tail")
        assert d["rise"] == 1000 and d["terms"] == {"net": 100, "brk": 100, "Q": 800}
        assert d["named"] == "Q"

    def test_the_largest_when_two_do(self):
        d = ul.name_the_term(tail(2000, "redis", 0, "tail", 1000, 0, 1000, 0),
                             tail(2000, "redis", 80, "tail", 2000, 700, 1600, -300), "tail")
        assert d["named"] == "net"

    def test_none_when_no_term_holds_half_or_nothing_rose(self):
        d = ul.name_the_term(tail(500, "kafka", 0, "tail", 1000, 0, 1000, 0),
                             tail(500, "kafka", 80, "tail", 1900, 300, 1300, 300), "tail")
        assert d["named"] is None
        d = ul.name_the_term(tail(500, "kafka", 0, "tail", 1000, 0, 1000, 0),
                             tail(500, "kafka", 80, "tail", 900, 0, 900, 0), "tail")
        assert d["named"] is None and d["rise"] == -100

    def test_a_missing_tail_decides_nothing(self):
        assert ul.name_the_term(None, None, "tail")["rise"] is None
        partial = tail(500, "kafka", 0, "tail", 1000, None, 1000, 0)
        assert ul.name_the_term(partial, partial, "tail")["named"] is None

    def test_both_decisions_from_the_tables(self):
        rows = block() + [row(50, b, load, Tc_p99="1") for b in ("kafka", "redis")
                          for load in (0, 88)]
        tails = [tail(r, b, load, "tail", 1000 + load * 10, 0, 1000 + load * 10, 0)
                 for r in (500, 2000) for b in ("kafka", "redis") for load in (0, 80)]
        tails += [tail(50, b, load, "all", 500 + load, 0, 500, load)
                  for b in ("kafka", "redis") for load in (0, 88)]
        out = ul.judge_split(rows, tails)
        assert [d["named"] for d in out["U-e"]["decisions"]] == ["brk"] * 4
        assert [d["named"] for d in out["U-f"]["decisions"]] == ["Q", "Q"]
        assert out["U-f"]["decisions"][0]["load"] == 88


class TestDescribed:
    def test_medians_and_shares_setup_by_setup(self):
        rows = [row(2000, "kafka", 0, W_p50="900", timed="10", flagged="5"),
                row(2000, "kafka", 0, W_p50="1100", timed="0", flagged="0", reads="0")]
        d = ul.described(rows)
        assert d[0]["W_p50"] == 1000 and d[0]["flagged_share"] == 0.5
        assert d[0]["card_matched_share"] == 0.0 and d[0]["R_p50"] is None
        assert d[0]["reads_multi_share"] == 0.25

    def test_what_the_extra_instruments_cost_against_block_l(self):
        ladder = [{"rate": r, "backend": b, "load_pct": 0, "Wso_median": "850",
                   "D_median": "1000"} for r in (500, 2000) for b in ("kafka", "redis")]
        cost = ul.judge(block(), [], ladder)["described"]["capture_cost"]
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
        assert ul.main(["read", "--runs", folder, "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--out-runs", runs, "--out-tails", tails,
                        "--warmup", "0"]) == 0
        out = capsys.readouterr().out
        assert "left out law_b: repeat" in out and "OK 1 runs of block U ->" in out
        ladder = str(tmp_path / "l_runs.csv")
        with open(ladder, "w", encoding="utf-8", newline="") as fh:
            fh.write("rate,backend,load_pct,Wso_median,D_median\n2000,kafka,0,800,1000\n")
        verdicts = str(tmp_path / "u_verdicts.json")
        assert ul.main(["judge", "--runs-table", runs, "--tails-table", tails, "--ladder-table",
                        ladder, "--out", verdicts]) == 0
        with open(verdicts, encoding="utf-8") as fh:
            judged = json.load(fh)
        assert judged["U-a"]["verdict"] == "out of reach" and judged["described"]["setups"]
        assert judged["described"]["capture_cost"][2]["W_L"] == 800.0
        assert "U-e: decision recorded" in capsys.readouterr().out

    def test_the_pilot_is_read_by_name(self, tmp_path, capsys):
        folder = str(tmp_path / "runs")
        os.makedirs(folder)
        make_run(folder, "law_a", "UP2000-kafka-l0", params())
        assert ul.main(["read", "--pilot", "--runs", folder, "--driver", DRIVER, "--broker",
                        BROKER, "--receiver", RECEIVER, "--out-runs", str(tmp_path / "r.csv"),
                        "--out-tails", str(tmp_path / "t.csv"), "--warmup", "0"]) == 0
        assert "OK 1 runs of block U's pilot" in capsys.readouterr().out

    def test_tables_come_back_typed(self, tmp_path):
        path = str(tmp_path / "t.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["rate", "load_pct", "priority", "all_F", "tail_F", "note"])
            w.writerow(["2000", "80.0", "True", "1.5", "", "x"])
            w.writerow(["", "", "maybe", "", "2", ""])
        a, b = ul.read_table(path)
        assert (a["rate"], a["load_pct"], a["priority"], a["all_F"], a["tail_F"]) == (
            2000, 80, True, 1.5, None)
        assert b["rate"] == "" and b["priority"] == "maybe" and b["tail_F"] == 2.0
        assert ul.read_table(str(tmp_path / "none.csv")) == [] and ul.read_table(None) == []
        bare = str(tmp_path / "bare.csv")
        with open(bare, "w", encoding="utf-8", newline="") as fh:
            fh.write("rate,setup\n50,U50-kafka-l0\n")
        assert ul.read_table(bare) == [{"rate": 50, "setup": "U50-kafka-l0"}]
