"""Tests for scripts/recv_wait.py: R1's three measurements of the receiving thread's own wait, on
runs made up in the shape real runs have on disk, and the plan's predictions read off them.

A made-up run follows the path a real message takes. It is sent, reaches the receiver's kernel
half a millisecond later (the packet's capture time), wakes the consumer's stamping thread 20 us
after that, which waits for a CPU (2 ms for every fourth message, 30 us otherwise), runs, and
stamps the receipt 100 us later. So method 2 must find the wait itself, and method 3 the wait
plus 120 us. The files carry what the real ones carry: the clients' CSV columns, the queue row,
the integrity record, the consumer's thread record with both clocks, bpftrace's lines, and a
classic pcap file with the kernel's nanosecond stamps behind a Linux "any" header.
"""
import csv
import io
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import recv_wait as rw  # noqa: E402

US = 1000
MS = 1000000
S = 1000000000
T0 = 1790418467 * S
#: CLOCK_REALTIME's lead over the tracer's CLOCK_MONOTONIC in a made-up run.
LEAD = 1790368222 * S
BROKER, RECEIVER = "10.1.1.21", "10.1.1.11"
PRODUCER_COLUMNS = ("run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                    "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns")
CONSUMER_COLUMNS = ("run_id", "backend", "topic", "partition", "offset", "t_consume_ns",
                    "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                    "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction")


# --- the bytes on the wire ------------------------------------------------------------------------

def ip_tcp(src, dst, sport, dport, seq, payload, version=4, proto=6, total=None):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    length = 20 + len(tcp) if total is None else total
    return struct.pack(">BBHHHBBH4s4s", (version << 4) | 5, 0, length, 0, 0, 64, proto, 0,
                       socket.inet_aton(src), socket.inet_aton(dst)) + tcp


def sll2(ip, proto=0x0800):
    return struct.pack(">HHIHBB8s", proto, 0, 2, 1, 0, 6, b"\0" * 8) + ip


def sll(ip, proto=0x0800):
    return struct.pack(">HHH8sH", 0, 1, 6, b"\0" * 8, proto) + ip


def ether(ip, proto=0x0800):
    return b"\0" * 12 + struct.pack(">H", proto) + ip


def pcap_bytes(packets, linktype=276, nano=True, endian="<", cut=0):
    magic = 0xa1b23c4d if nano else 0xa1b2c3d4
    out = struct.pack(endian + "IHHiIII", magic, 2, 4, 0, 0, 262144, linktype)
    for ns, frame in packets:
        sec, frac = divmod(ns, S)
        out += struct.pack(endian + "IIII", sec, frac if nano else frac // US, len(frame),
                           len(frame)) + frame
    return out[:len(out) - cut] if cut else out


def record(eid, pad=0):
    """A message as Kafka carries it: the id as the record's key, then inside the value."""
    return (b"\x00" * pad + b"key:" + eid.encode() + b'|{"event_id":"' + eid.encode()
            + b'","type":"pass"}')


# --- a made-up R1 run -----------------------------------------------------------------------------

def r1_run(root, key, backend="kafka", load=75, priority=False, traced=True, capture=True,
           verdict="count", count=12, period_ms=1000.0, slow_every=4, slow_ms=2.0,
           quick_ms=0.03, lost=False, unidentified=False, err=None):
    """One R1 run's folder, and the per-message waits it was built with, in ns."""
    run = root / ("law_r1_%s" % key)
    run.mkdir(parents=True)
    setup = "R1-%s-l%d-%s" % (backend, load, "rtc" if priority else "ord")
    params = {"backend": backend, "load_pct": load, "slice_ns": 3000000, "delay_ms": 0,
              "trace_half": True, "trace_events": True, "recv_capture": True}
    if priority:
        params["consumer_priority"] = True
    (run / "queue_row.json").write_text(json.dumps(
        {"key": key, "round": "1", "setup": setup, "attempt": "1", "params": params}),
        encoding="utf-8")
    if verdict is not None:
        (run / "integrity.json").write_text(json.dumps(
            {"verdict": verdict, "reasons": [], "checks": {}, "recorded": {}}), encoding="utf-8")
    produced, consumed, packets, waits, events = [], [], [], {}, ["Attaching 3 probes..."]
    tid, seq = 201, 7000
    events.append("S %d %d" % (tid, T0 - LEAD - 5 * MS))
    for i in range(count):
        eid = "constant-%06d" % i
        send = T0 + int(i * period_ms * MS)
        kernel = send + 500 * US
        wake = kernel + 20 * US
        wait = int((slow_ms if i % slow_every == 0 else quick_ms) * MS)
        runs = wake + wait
        stamp = runs + 100 * US
        waits[eid] = wait
        produced.append({"run_id": key, "backend": backend, "topic": "t", "event_id": eid,
                         "match_id": "900000", "t_sim_seconds": "0", "t_emit_offset_s": "0",
                         "t_prod_sched_ns": str(send - 50 * US), "t_prod_send_ns": str(send),
                         "t_broker_ack_ns": str(send + 800 * US)})
        consumed.append({"run_id": key, "backend": backend, "topic": "t", "partition": "0",
                         "offset": str(i), "t_consume_ns": str(stamp), "event_id": eid,
                         "match_id": "900000", "t_sim_seconds": "0", "t_emit_offset_s": "0",
                         "t_emit_planned_ns": str(send), "s3_uid": "u", "s3_rev": "1",
                         "s3_is_correction": "False"})
        payload = record(eid)
        packets.append((kernel, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, seq, payload))))
        seq += len(payload)
        if not unidentified or i == 0:
            events += ["W %d %d" % (tid, wake - LEAD), "R %d %d" % (tid, runs - LEAD),
                       "S %d %d" % (tid, stamp + 20 * US - LEAD)]
    with open(run / "producer.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PRODUCER_COLUMNS)
        w.writeheader()
        w.writerows(produced)
    with open(run / "consumer_events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CONSUMER_COLUMNS)
        w.writeheader()
        w.writerows(consumed)
    if traced:
        if lost:
            events.append("Lost 12 events")
        (run / "waits.txt").write_text("\n".join(events) + "\n", encoding="utf-8")
        if err is not None:
            (run / "waits.err").write_text(err, encoding="utf-8")
        clocks = [{"monotonic_ns": T0 - LEAD - S, "realtime_ns": T0 - S},
                  {"monotonic_ns": T0 - LEAD + 60 * S, "realtime_ns": T0 + 60 * S}]
        (run / "consumer_threads.json").write_text(json.dumps(
            {"clocks": clocks, "pid": tid, "roles": {"stamps_receive": [tid]}}),
            encoding="utf-8")
    if capture:
        # the consumer's own request, the other way, and a frame that is not TCP, both ignored
        packets.insert(1, (T0 + 1 * MS, sll2(ip_tcp(RECEIVER, BROKER, 41000, 9092, 1, b"fetch"))))
        packets.insert(2, (T0 + 2 * MS, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1, b"",
                                                     proto=17))))
        (run / "receiver_full.pcap").write_bytes(pcap_bytes(packets))
    return run, waits


# --- the capture ------------------------------------------------------------------------------

class TestReadingTheCapture:

    def test_a_nanosecond_capture_keeps_the_kernels_stamps_to_the_nanosecond(self, tmp_path):
        frame = sll2(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x"))
        path = tmp_path / "a.pcap"
        path.write_bytes(pcap_bytes([(T0 + 123456789, frame)]))
        assert rw.read_pcap(str(path)) == [(T0 + 123456789, 276, frame)]

    def test_a_microsecond_big_endian_capture_is_read_too(self, tmp_path):
        frame = ether(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x"))
        path = tmp_path / "b.pcap"
        path.write_bytes(pcap_bytes([(T0 + 123456000, frame)], linktype=1, nano=False,
                                    endian=">"))
        assert rw.read_pcap(str(path)) == [(T0 + 123456000, 1, frame)]

    def test_a_record_the_end_of_the_file_cuts_short_is_left_out(self, tmp_path):
        frame = sll2(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"xyz"))
        path = tmp_path / "c.pcap"
        path.write_bytes(pcap_bytes([(T0, frame), (T0 + 1, frame)], cut=5))
        assert [ns for ns, _, _ in rw.read_pcap(str(path))] == [T0]

    def test_an_empty_file_has_no_frames_and_a_stranger_is_refused(self, tmp_path):
        empty, other = tmp_path / "e.pcap", tmp_path / "o.pcap"
        empty.write_bytes(b"")
        other.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\0" * 40)      # a pcapng section header
        assert rw.read_pcap(str(empty)) == []
        with pytest.raises(ValueError, match="not a classic pcap"):
            rw.read_pcap(str(other))

    @pytest.mark.parametrize("linktype,wrap", [(276, sll2), (113, sll), (1, ether)])
    def test_every_link_layer_tcpdump_writes_yields_the_ip_packet(self, linktype, wrap):
        ip = ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x")
        assert rw.ip_payload(linktype, wrap(ip)) == ip
        assert rw.ip_payload(linktype, wrap(ip, proto=0x86DD)) is None
        assert rw.ip_payload(linktype, wrap(ip)[:10]) is None

    def test_a_raw_layer_is_the_packet_and_an_unknown_one_is_nothing(self):
        ip = ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x")
        assert rw.ip_payload(101, ip) == ip
        assert rw.ip_payload(999, ip) is None

    def test_a_tcp_segment_is_read_and_anything_else_is_not(self):
        ip = ip_tcp(BROKER, RECEIVER, 9092, 41000, 77, b"payload")
        assert rw.tcp_segment(ip) == (BROKER, RECEIVER, 9092, 41000, 77, b"payload")
        assert rw.tcp_segment(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x", total=0))[5] == b"x"
        assert rw.tcp_segment(ip[:19]) is None
        assert rw.tcp_segment(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x", version=6)) is None
        assert rw.tcp_segment(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x", proto=17)) is None
        assert rw.tcp_segment(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x", total=30)) is None


class TestReassembly:

    def test_bytes_in_order_are_readable_when_they_arrive(self):
        s = rw.Stream()
        s.add(10, 100, b"abc")
        s.add(20, 103, b"def")
        s.add(30, 106, b"")
        assert bytes(s.data) == b"abcdef"
        assert (s.readable(0), s.readable(2), s.readable(3), s.readable(5)) == (10, 10, 20, 20)
        assert s.readable(6) is None

    def test_a_segment_ahead_of_a_gap_is_readable_only_once_the_gap_fills(self):
        s = rw.Stream()
        s.add(10, 100, b"abc")
        s.add(20, 106, b"ghi")               # held: bytes 3-5 have not arrived
        s.add(25, 106, b"GHI")               # its retransmission is not a second copy
        s.add(30, 103, b"def")
        assert bytes(s.data) == b"abcdefghi"
        assert (s.readable(4), s.readable(7)) == (30, 30)

    def test_a_retransmission_and_an_overlap_add_only_what_is_new(self):
        s = rw.Stream()
        s.add(10, 100, b"abcdef")
        s.add(20, 100, b"abc")               # already held
        s.add(30, 103, b"defgh")             # overlaps three held bytes
        s.add(40, 95, b"vwxyzabcdefghij")    # starts before the stream's first byte
        assert bytes(s.data) == b"abcdefghij"
        assert (s.readable(6), s.readable(8), s.readable(9)) == (30, 40, 40)

    def test_held_segments_that_the_fill_covers_or_leaves_behind(self):
        s = rw.Stream()
        s.add(10, 100, b"ab")
        s.add(11, 104, b"ef")                # inside what the next fill brings
        s.add(12, 120, b"zz")                # still beyond it afterwards
        s.add(13, 102, b"cdefgh")
        assert bytes(s.data) == b"abcdefgh"
        assert list(s.pending) == [20]

    def test_the_sequence_number_wraps_around(self):
        s = rw.Stream()
        s.add(10, 0xFFFFFFFE, b"ab")
        s.add(20, 0, b"cd")
        assert bytes(s.data) == b"abcd" and s.readable(3) == 20


class TestKernelTimes:

    def test_each_message_is_timed_from_the_packet_that_carries_its_id(self, tmp_path):
        frames = [
            (T0 + 1000, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1, record("constant-000001")))),
            (T0 + 2000, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1 + 40,
                                    record("constant-000002")[:10]))),
            (T0 + 3000, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1 + 50,
                                    record("constant-000002")[10:]))),
            (T0 + 4000, sll2(ip_tcp(BROKER, RECEIVER, 6379, 42000, 9, record("constant-000003")))),
            (T0 + 5000, sll2(ip_tcp(RECEIVER, BROKER, 41000, 9092, 1, b"constant-000009"))),
            (T0 + 6000, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1, b"x", version=6))),
            (T0 + 7000, sll2(ip_tcp(BROKER, RECEIVER, 1, 2, 3, b"x"), proto=0x86DD)),
        ]
        path = tmp_path / "k.pcap"
        path.write_bytes(pcap_bytes(frames))
        found = rw.kernel_times(str(path), BROKER, RECEIVER)
        assert found == {"constant-000001": T0 + 1000, "constant-000002": T0 + 3000,
                         "constant-000003": T0 + 4000}

    def test_an_id_seen_again_far_downstream_is_a_later_record_and_not_this_one(self, tmp_path):
        first = record("constant-000001")
        later = record("constant-000001", pad=rw.SAME_RECORD + 10)
        path = tmp_path / "far.pcap"
        path.write_bytes(pcap_bytes([
            (T0 + 1, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1, first))),
            (T0 + 9, sll2(ip_tcp(BROKER, RECEIVER, 9092, 41000, 1 + len(first), later)))]))
        assert rw.kernel_times(str(path), BROKER, RECEIVER) == {"constant-000001": T0 + 1}


# --- one run ----------------------------------------------------------------------------------

class TestOneRun:

    def test_the_three_measurements_find_what_the_run_was_built_with(self, tmp_path):
        run, waits = r1_run(tmp_path, "r001-a")
        row = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=0)
        expected = sorted(w / 1e3 for w in waits.values())
        assert row["messages"] == 12 and row["traced"] and not row["consumer_priority"]
        assert row["wait_n"] == 12 and row["wait_note"] == ""
        assert row["wait_median"] == pytest.approx((expected[5] + expected[6]) / 2)
        assert row["wait_mean"] == pytest.approx(sum(expected) / 12)
        assert row["kernel_n"] == 12 and row["kernel_unmatched"] == 0
        assert row["kernel_mean"] == pytest.approx(sum(expected) / 12 + 120)
        assert row["kernel_ge_wait_share"] == 1.0
        assert row["kernel_minus_wait_median"] == pytest.approx(120)
        assert row["kernel_negative"] == 0
        assert row["D_mean"] == pytest.approx(500 + 20 + sum(expected) / 12 + 100)
        assert row["D_max"] == pytest.approx(500 + 20 + 2000 + 100) and row["D_held"] == 0
        assert row["iowait_s"] is None, "no reading of /proc/stat around the run"

    def test_a_run_that_holds_messages_past_the_pause_limit_says_how_many_and_how_long(
            self, tmp_path):
        run, _ = r1_run(tmp_path, "r001-p", slow_ms=400.0)
        (run / "stat_before.txt").write_text("cpu 10 0 5 1000 200 0 0 0\n", encoding="utf-8")
        (run / "stat_after.txt").write_text("cpu 20 0 9 2000 1134 0 0 0\n", encoding="utf-8")
        row = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=0)
        assert row["D_held"] == 3, "messages 0, 4 and 8"
        assert row["D_max"] == pytest.approx(500 + 20 + 400000 + 100)
        assert row["iowait_s"] == pytest.approx(9.34), "the disk wait the census reads"
        nothing = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=60)
        assert nothing["messages"] == 0 and nothing["D_max"] is None and nothing["D_held"] == 0

    def test_an_untraced_run_without_a_capture_keeps_only_d(self, tmp_path):
        run, _ = r1_run(tmp_path, "r002-a", traced=False, capture=False, priority=True)
        row = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=0)
        assert row["consumer_priority"] and not row["traced"]
        assert row["wait_note"] == rw.hw.NOT_RECORDED and row["wait_n"] == 0
        assert row["kernel_unmatched"] is None and row["kernel_ge_wait_share"] is None
        assert row["D_n"] == 12

    def test_a_message_missing_from_the_capture_is_counted_and_left_out(self, tmp_path):
        run, _ = r1_run(tmp_path, "r003-a", traced=False)
        frames = rw.read_pcap(str(run / "receiver_full.pcap"))[:-1]
        (run / "receiver_full.pcap").write_bytes(pcap_bytes([(ns, f) for ns, f, in
                                                             [(n, fr) for n, _, fr in frames]]))
        row = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=0)
        assert row["kernel_unmatched"] == 1 and row["kernel_n"] == 11

    def test_the_warm_up_and_messages_never_sent_or_never_stamped_are_left_out(self, tmp_path):
        run, _ = r1_run(tmp_path, "r004-a", count=40)
        rows = list(csv.DictReader(open(run / "consumer_events.csv", encoding="utf-8")))
        rows[35]["t_consume_ns"] = ""
        rows.append(dict(rows[36], event_id="constant-999999"))
        with open(run / "consumer_events.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CONSUMER_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        found = rw.messages(str(run))
        assert [eid for eid, _, _ in found] == ["constant-%06d" % i for i in range(30, 40)
                                                if i != 35]

    def test_a_producer_that_logged_no_send_gives_no_messages(self, tmp_path):
        run, _ = r1_run(tmp_path, "r005-a", count=3)
        rows = list(csv.DictReader(open(run / "producer.csv", encoding="utf-8")))
        for r in rows:
            r["t_prod_send_ns"] = ""
        with open(run / "producer.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=PRODUCER_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        row = rw.read_run(str(run), BROKER, RECEIVER, warmup_s=0)
        assert row["messages"] == 0 and row["wait_note"] == "no message measured"
        assert row["D_median"] is None and row["kernel_n"] == 0

    @pytest.mark.parametrize("kind,why", [
        ("lost", "the recording lost events"),
        ("err", "the recording lost events"),
        ("unidentified", "identified for 1 of 12"),
        ("record", "no thread record from the consumer")])
    def test_a_recording_that_cannot_be_laid_on_the_clients_clock_is_not_read(self, tmp_path,
                                                                             kind, why):
        run, _ = r1_run(tmp_path, "r006-a", lost=kind == "lost",
                        err="Lost 3 events\n" if kind == "err" else "",
                        unidentified=kind == "unidentified")
        if kind == "record":
            os.remove(run / "consumer_threads.json")
        waits, reason = rw.receive_waits(str(run), rw.messages(str(run), warmup_s=0))
        assert waits is None and why in reason

    def test_a_clean_error_file_does_not_condemn_the_recording(self, tmp_path):
        run, _ = r1_run(tmp_path, "r007-a", err="Attached\n")
        waits, reason = rw.receive_waits(str(run), rw.messages(str(run), warmup_s=0))
        assert reason is None and len(waits) == 12


class TestTheCampaign:

    def test_only_r1_runs_the_integrity_rule_passed_are_read(self, tmp_path):
        """By the setup a run's queue row names, not by its folder: campaign.sh names folders
        after their queue, and amendment R1-1's runs came from a second one, r1_more. Reading by
        folder left them out on the first try."""
        r1_run(tmp_path, "r001-R1-kafka-l75-ord-a1")
        r1_run(tmp_path, "r001-R1-kafka-l75-ord-a2", verdict="repeat")
        r1_run(tmp_path, "r002-R1-kafka-l75-ord-a1", verdict=None)
        r1_run(tmp_path, "more_r007-R1-kafka-l75-ord-a1")
        other, _ = r1_run(tmp_path, "a9_r001-A9-kafka-l75-s3000-c02h-a1")
        row = json.loads((other / "queue_row.json").read_text(encoding="utf-8"))
        (other / "queue_row.json").write_text(json.dumps(dict(row, setup="A9-kafka")),
                                              encoding="utf-8")
        bare, _ = r1_run(tmp_path, "r003-R1-kafka-l75-ord-a1")
        os.remove(bare / "queue_row.json")
        rows, skipped = rw.read_campaign([str(tmp_path)], BROKER, RECEIVER, warmup_s=0)
        assert [r["run"] for r in rows] == ["law_r1_more_r007-R1-kafka-l75-ord-a1",
                                            "law_r1_r001-R1-kafka-l75-ord-a1"]
        assert skipped == [("law_r1_r001-R1-kafka-l75-ord-a2", "repeat"),
                           ("law_r1_r002-R1-kafka-l75-ord-a1", "not judged")]


# --- the comparison ------------------------------------------------------------------------------

def table_row(priority, traced, d, wait, kernel, share=1.0, diff=120.0, backend="kafka",
              load=75, unmatched=0, run="law_r1_r001", held=0, longest=None):
    """A row as r1_runs.csv holds it: every value a string, as csv.DictReader returns it."""
    row = {"run": run, "backend": backend, "load_pct": str(load),
           "consumer_priority": str(priority), "traced": str(traced),
           "kernel_unmatched": str(unmatched), "D_held": str(held),
           "D_max": "" if longest is None else str(longest),
           "kernel_ge_wait_share": str(share) if traced else "",
           "kernel_minus_wait_median": str(diff) if traced else ""}
    for prefix, stats in (("D", d), ("wait", wait if traced else None), ("kernel", kernel)):
        for name, value in zip(("median", "mean", "p90", "p99"), stats or (None,) * 4):
            row["%s_%s" % (prefix, name)] = "" if value is None else str(value)
    return row


ORDINARY = dict(d=(900, 1600, 3200, 4500), wait=(20, 700, 2600, 4000),
                kernel=(150, 820, 2700, 4100))
GO_FIRST = dict(d=(850, 900, 1000, 1100), wait=(10, 12, 15, 20), kernel=(130, 140, 180, 240))


class TestTheComparison:

    def test_a_campaign_shaped_like_the_plans_expectation_meets_every_prediction(self):
        rows = [table_row(False, True, **ORDINARY), table_row(False, False, **ORDINARY),
                table_row(True, True, **GO_FIRST), table_row(True, False, **GO_FIRST)]
        found = rw.compare(rows)[("kafka", "75")]
        assert found["runs"] == (2, 2) and found["traced"] == (1, 1)
        assert found["estimates"] == (700.0, 688.0, 680.0)
        assert all(found[p] for p in ("R1-a", "R1-b", "R1-c", "R1-d"))
        text = rw.lines({("kafka", "75"): found})
        assert ("method 1 0.70 ms, method 2 0.69 ms, method 3 0.68 ms; largest over smallest "
                "1.03") in text[8]
        assert "for 100.0% of messages (median over traced runs; lowest run 100.0%)" in text[9]
        assert text[10].endswith("pause limit: none") and "R1-d holds" in text[11]
        assert text[-1] == "R1-d holds in 1 of 1 broker-and-load parts"

    def test_the_runs_a_pause_carries_are_named(self):
        """A pause releases every message it held at once and can carry a run's mean, and a cell
        of two runs has no median to hide it in. So the runs that hold one are named."""
        rows = [table_row(False, False, **ORDINARY),
                table_row(True, False, run="law_r1_r006", held=297, longest=6036716.5,
                          **GO_FIRST),
                table_row(True, True, run="law_r1_r003", held=80, longest=1731000.0,
                          **GO_FIRST)]
        found = rw.compare(rows)[("kafka", "75")]
        assert found["held"] == [("law_r1_r003", 80, 1731000.0), ("law_r1_r006", 297, 6036716.5)]
        text = rw.lines({("kafka", "75"): found})
        assert text[10] == ("  runs holding a message over the quality report's 150 ms pause "
                            "limit: law_r1_r003, 80 messages, longest 1731.00 ms; law_r1_r006, "
                            "297 messages, longest 6036.72 ms")

    def test_traced_and_untraced_runs_are_also_shown_apart(self):
        """The plan reports them apart wherever D is compared, since the tracer is not a free
        observer. The plan's own reading, a setup's median over all its runs, is unchanged."""
        heavier = dict(ORDINARY, d=(1000, 1900, 3600, 5000), kernel=(160, 900, 2800, 4200))
        rows = [table_row(False, True, share=0.98, **heavier),
                table_row(False, False, **ORDINARY), table_row(False, False, **ORDINARY),
                table_row(True, True, **GO_FIRST), table_row(True, False, **GO_FIRST)]
        found = rw.compare(rows)[("kafka", "75")]
        apart = found["apart"]
        assert apart["untraced"]["runs"] == (2, 1) and apart["traced"]["runs"] == (1, 1)
        assert apart["untraced"]["D"]["mean"] == (1600.0, 900.0)
        assert apart["traced"]["D"]["mean"] == (1900.0, 900.0)
        assert apart["traced"]["kernel"]["median"] == (160.0, 130.0)
        assert found["D"]["mean"] == (1600.0, 900.0), "every run, as the plan reads a setup"
        assert found["share"] == 0.99 and found["lowest_share"] == 0.98
        text = rw.lines({("kafka", "75"): found})
        assert text[1].startswith("  method 1, D: median 0.90 ms -> 0.85 ms; mean 1.60 ms")
        assert text[2] == ("    untraced runs only, 2 -> 1: median 0.90 ms -> 0.85 ms; mean 1.60 ms"
                           " -> 0.90 ms; p90 3.20 ms -> 1.00 ms; p99 4.50 ms -> 1.10 ms")
        assert text[3].startswith("    traced runs only, 1 -> 1: median 1.00 ms -> 0.85 ms; "
                                  "mean 1.90 ms -> 0.90 ms")
        assert text[4].startswith("  method 2, traced own wait: "), "the tracer's own, never apart"
        assert text[5].startswith("  method 3, kernel receipt to stamp: ")
        assert text[6].startswith("    untraced runs only, 2 -> 1: median 0.15 ms -> 0.13 ms")
        assert text[7].startswith("    traced runs only, 1 -> 1: median 0.16 ms -> 0.13 ms")
        assert "for 99.0% of messages (median over traced runs; lowest run 98.0%)" in text[9]

    def test_each_prediction_can_fail(self):
        small = dict(d=(900, 950, 1500, 2000), wait=(20, 100, 900, 1500),
                     kernel=(150, 400, 1000, 1600))
        rows = [table_row(False, True, share=0.5, diff=500.0, **small),
                table_row(True, True, **GO_FIRST)]
        found = rw.compare(rows)[("kafka", "75")]
        assert not any(found[p] for p in ("R1-a", "R1-b", "R1-c", "R1-d"))

    def test_a_part_with_one_arm_or_no_traced_run_says_nothing_it_cannot(self):
        rows = [table_row(False, False, backend="redis", load=88, **ORDINARY)]
        found = rw.compare(rows)[("redis", "88")]
        assert found["estimates"] == (None, None, None) and found["share"] is None
        assert found["ratio"] is None and found["lowest_share"] is None
        assert not any(found[p] for p in ("R1-a", "R1-b", "R1-c", "R1-d"))
        text = rw.lines({("redis", "88"): found})
        assert text[3] == "    traced runs only, 0 -> 0: " + "; ".join(
            "%s - -> -" % stat for stat in ("median", "mean", "p90", "p99"))
        assert "method 1 -, method 2 -, method 3 -; largest over smallest -" in text[8]
        assert "for - of messages (median over traced runs; lowest run -)" in text[9]

    def test_two_estimates_that_agree_are_not_three(self):
        """R1-d asks the three estimates to agree. Two that agree, with the traced one missing,
        or with priority lengthening the wait instead, are not that, and give no ratio."""
        untraced = [table_row(False, False, **ORDINARY), table_row(True, False, **GO_FIRST)]
        found = rw.compare(untraced)[("kafka", "75")]
        assert found["estimates"] == (700.0, None, 680.0)
        assert found["ratio"] is None and not found["R1-d"]
        worse = dict(GO_FIRST, wait=(10, 900, 15, 20))
        found = rw.compare([table_row(False, True, **ORDINARY),
                            table_row(True, True, **worse)])[("kafka", "75")]
        assert found["estimates"] == (700.0, -200.0, 680.0)
        assert found["ratio"] is None and not found["R1-d"]


# --- the pauses -----------------------------------------------------------------------------------

class TestThePauses:

    def test_each_pause_in_a_counted_run_is_read_with_the_census_functions(self, tmp_path):
        """Messages 32 and 36 wait 400 ms for their thread: two pauses past the warm-up, each of
        one message, whose confirmations came back as usual. The driver's sampler skipped two
        seconds across the first; the run's processors waited 9.34 s on the disk."""
        runs = tmp_path / "runs"
        run, _ = r1_run(runs, "r001-R1-redis-l75-rtc-a1", backend="redis", priority=True,
                        count=40, slow_ms=400.0)
        start = T0 / 1e9
        (run / "utilisation.csv").write_text("t_wall,cpu_pct\n" + "".join(
            "%.3f,50\n" % (start + k * 0.5) for k in range(90) if not 63 <= k <= 66),
            encoding="utf-8")
        (run / "stat_before.txt").write_text("cpu 10 0 5 1000 200 0 0 0\n", encoding="utf-8")
        (run / "stat_after.txt").write_text("cpu 20 0 9 2000 1134 0 0 0\n", encoding="utf-8")
        r1_run(runs, "r002-R1-redis-l75-rtc-a1", backend="redis", priority=True, count=40,
               slow_ms=400.0, verdict="repeat")
        r1_run(runs, "r001-R1-redis-l75-ord-a1", backend="redis", count=40)
        rows = rw.pause_rows([str(runs)])
        assert [r["run"] for r in rows] == ["law_r1_r001-R1-redis-l75-rtc-a1"] * 2, \
            "nothing from the run sent back, nor from the run that never paused"
        first, second = rows
        assert first["setup"] == "R1-redis-l75-rtc" and first["late"] == 1
        assert first["worst_ms"] == pytest.approx(400.62) and first["kind"] == "receiver"
        assert first["max_gotit_ms"] == pytest.approx(0.8)
        assert first["sampler_gap_s"] == pytest.approx(2.5)
        assert second["sampler_gap_s"] == pytest.approx(0.5), "the sampler kept going"
        assert first["inside_reads"] is None and first["iowait_s"] == pytest.approx(9.34)
        table, out = tmp_path / "pauses.csv", io.StringIO()
        assert rw.main(["pauses", "--runs", str(runs), "--out", str(table)], out=out) == 0
        assert out.getvalue() == "2 pauses in 1 runs\n"
        with open(table, newline="", encoding="utf-8") as fh:
            assert [r["kind"] for r in csv.DictReader(fh)] == ["receiver", "receiver"]


# --- the earlier campaigns ------------------------------------------------------------------------

class TestTheEarlierCampaigns:

    def test_method_two_on_the_law_campaigns_traced_runs(self, tmp_path, monkeypatch):
        folder = tmp_path / "final_campaigns" / "matched" / "a9_x"
        traced, waits = r1_run(folder, "r001-A9", count=40)
        plain, _ = r1_run(folder, "r002-A9", count=40, traced=False)
        runs = [{"run_dir": str(traced), "backend": "kafka", "load_pct": 75, "setup": "A9-k",
                 "run": traced.name}, {"run_dir": str(plain), "backend": "kafka",
                                       "load_pct": 75, "setup": "A9-k", "run": plain.name}]
        monkeypatch.setattr(rw.hw, "counted_runs", lambda folders, blocks: runs)
        rows, skipped = rw.traced_runs([str(folder)])
        assert [r["pair"] for r in rows] == ["matched"] and skipped == {rw.hw.NOT_RECORDED: 1}
        kept = [w / 1e3 for e, w in waits.items() if int(e[-6:]) >= 30]
        assert rows[0]["wait_mean"] == pytest.approx(sum(kept) / len(kept))

    def test_d_with_and_without_go_first_pooled_by_setup(self, tmp_path, monkeypatch):
        folder = tmp_path / "final_campaigns" / "matched" / "a7_x"
        one, _ = r1_run(folder, "r001-A7", count=40)
        two, _ = r1_run(folder, "r002-A7", count=40, slow_ms=0.03)
        runs = [{"run_dir": str(one), "backend": "kafka", "point": "c05h", "priority": False},
                {"run_dir": str(two), "backend": "kafka", "point": "c05h", "priority": True}]
        monkeypatch.setattr(rw.hw, "counted_runs", lambda folders, blocks: runs)
        rows = rw.priority_runs([str(folder)])
        assert [(r["priority"], r["D_n"]) for r in rows] == [("go-first", 10), ("ordinary", 10)]
        assert rows[0]["D_mean"] < rows[1]["D_mean"]


# --- the command line -----------------------------------------------------------------------------

class TestTheCommandLine:

    def test_read_then_compare(self, tmp_path):
        runs = tmp_path / "runs"
        r1_run(runs, "r001-R1-kafka-l75-ord-a1", count=40)
        r1_run(runs, "r001-R1-kafka-l75-rtc-a1", count=40, priority=True, slow_ms=0.03)
        r1_run(runs, "r002-R1-kafka-l75-ord-a1", count=40, verdict="repeat")
        table, answer = tmp_path / "r1.csv", tmp_path / "r1.txt"
        out = io.StringIO()
        assert rw.main(["read", "--runs", str(runs), "--broker", BROKER, "--receiver", RECEIVER,
                        "--out", str(table)], out=out) == 0
        assert "2 runs read, 1 not read" in out.getvalue() and "repeat" in out.getvalue()
        out = io.StringIO()
        assert rw.main(["compare", "--table", str(table), "--out", str(answer)], out=out) == 0
        assert out.getvalue() == answer.read_text(encoding="utf-8")
        assert "kafka at 75% load: 1 ordinary runs (1 traced)" in out.getvalue()
        out = io.StringIO()
        assert rw.main(["compare", "--table", str(table)], out=out) == 0

    def test_a_folder_with_no_run_writes_an_empty_table(self, tmp_path):
        table = tmp_path / "none.csv"
        assert rw.main(["read", "--runs", str(tmp_path), "--broker", BROKER, "--receiver",
                        RECEIVER, "--out", str(table)], out=io.StringIO()) == 0
        assert table.read_text(encoding="utf-8").strip() == "empty"

    def test_traced_and_priority(self, tmp_path, monkeypatch):
        folder = tmp_path / "final_campaigns" / "arm" / "a9_x"
        run, _ = r1_run(folder, "r001-A9", count=40)
        monkeypatch.setattr(rw.hw, "counted_runs", lambda folders, blocks: [
            {"run_dir": str(run), "backend": "redis", "load_pct": 88, "setup": "A9-r",
             "run": run.name, "point": "p09s", "priority": False}])
        out = io.StringIO()
        assert rw.main(["traced", "--runs", str(folder), "--out", str(tmp_path / "t.csv")],
                       out=out) == 0
        assert "1 traced runs read; not read: none" in out.getvalue()
        out = io.StringIO()
        assert rw.main(["priority", "--runs", str(folder), "--out", str(tmp_path / "p.csv")],
                       out=out) == 0
        assert "1 pooled rows" in out.getvalue()
