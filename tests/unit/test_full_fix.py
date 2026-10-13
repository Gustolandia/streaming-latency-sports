"""Tests for scripts/full_fix.py: freeze 39's test of a full fix, on runs made up in the shape real
runs have on disk, and its predictions F-a to F-e read off tables made to hold or to fail.

A made-up message is published, leaves the driver's kernel 300 us later (the sender capture's
stamp), reaches the receiver's kernel 500 us after that (the receiver capture's stamp), and is
stamped by the consumer 120 us later. So W must come out at 500 us, H_send at 300, H_recv at 120,
and D at their sum, for every message.
"""
import csv
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import full_fix as ff  # noqa: E402

US = 1000
S = 1000000000
T0 = 1790418467 * S
DRIVER, BROKER, RECEIVER = "10.1.1.4", "10.1.1.21", "10.1.1.11"
PRODUCER_COLUMNS = ("run_id", "backend", "topic", "event_id", "match_id", "t_sim_seconds",
                    "t_emit_offset_s", "t_prod_sched_ns", "t_prod_send_ns", "t_broker_ack_ns")
CONSUMER_COLUMNS = ("run_id", "backend", "topic", "partition", "offset", "t_consume_ns",
                    "event_id", "match_id", "t_sim_seconds", "t_emit_offset_s",
                    "t_emit_planned_ns", "s3_uid", "s3_rev", "s3_is_correction")


def ip_tcp(src, dst, sport, dport, seq, payload):
    tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0) + payload
    return struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp), 0, 0, 64, 6, 0,
                       socket.inet_aton(src), socket.inet_aton(dst)) + tcp


def ether(ip):
    return b"\0" * 12 + struct.pack(">H", 0x0800) + ip


def sll2(ip):
    return struct.pack(">HHIHBB8s", 0x0800, 0, 2, 1, 0, 6, b"\0" * 8) + ip


def pcap_bytes(packets, linktype):
    out = struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, 262144, linktype)
    for ns, frame in packets:
        sec, frac = divmod(ns, S)
        out += struct.pack("<IIII", sec, frac, len(frame), len(frame)) + frame
    return out


def record(eid):
    """A message as the clients carry it: the id as its key, then inside its value."""
    return b"key:" + eid.encode() + b'|{"event_id":"' + eid.encode() + b'","type":"pass"}'


#: What tcpdump writes to its log as it stops, with the packets the kernel dropped.
REPORT = ("tcpdump: listening on eth0, link-type EN10MB (Ethernet), snapshot length 262144 bytes\n"
          "6507 packets captured\n6510 packets received by filter\n%d packets dropped by kernel\n")


def made_up_run(root, key, setup="F1-kafka-l88-ord", backend="kafka", load=88, priority=False,
                verdict="count", n=40, send=300 * US, wire=500 * US, recv=120 * US,
                missing_tx=(), reversed_wire=(), card=None, slow=None, logs=None):
    """One run of the block on disk: n messages after the warm-up, each sent every 20 ms. `slow`
    holds a message back: {index: (ns more before its bytes leave, ns more on the wire)}. The
    integrity rule measured the load 0.2 points above its design, and each capture's log reports
    no packet dropped unless `logs` says otherwise."""
    run = root / ("law_f1_" + key)
    run.mkdir(parents=True)
    with open(run / "queue_row.json", "w", encoding="utf-8") as fh:
        json.dump({"setup": setup, "params": {"backend": backend, "load_pct": load,
                                              "priority": priority}}, fh)
    with open(run / "integrity.json", "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "checks": {"load": {"value": load + 0.2}}}, fh)
    for name, text in (logs if logs is not None else {
            "sender_full.err": REPORT % 0, "receiver_full.err": REPORT % 0}).items():
        (run / name).write_text(text, encoding="utf-8")
    prod, cons, sent, got = [], [], [], []
    seq_tx = seq_rx = 1000
    for i in range(n + 5):
        eid = "constant-%06d" % i
        t_pub = T0 + (0 if i < 5 else 31 * S) + i * 20 * 1000 * US
        more_send, more_wire = (slow or {}).get(i, (0, 0))
        t_tx = t_pub + send + more_send
        t_rx = t_tx + wire + more_wire
        if i in reversed_wire:
            t_rx = t_tx - 10 * US
        t_recv = t_rx + recv
        prod.append({"event_id": eid, "t_prod_send_ns": t_pub})
        cons.append({"event_id": eid, "t_consume_ns": t_recv})
        payload = record(eid)
        if i not in missing_tx:
            sent.append((t_tx, ether(ip_tcp(DRIVER, BROKER, 40000, 9092, seq_tx, payload))))
        seq_tx += len(payload)
        got.append((t_rx, sll2(ip_tcp(BROKER, RECEIVER, 9092, 40001, seq_rx, payload))))
        seq_rx += len(payload)
    for name, columns, rows in (("producer.csv", PRODUCER_COLUMNS, prod),
                                ("consumer_events.csv", CONSUMER_COLUMNS, cons)):
        with open(run / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
    (run / "sender_full.pcap").write_bytes(pcap_bytes(sent, 1))
    (run / "receiver_full.pcap").write_bytes(pcap_bytes(got, 276))
    if card is not None:
        # The card stamps each packet `ahead` before the kernel does, on a clock `offset` from
        # the system's; the sampler records that offset every half second through the run.
        offset, ahead = card
        (run / "receiver_hw.pcap").write_bytes(pcap_bytes(
            [(ns - ahead + offset, ether(frame[20:])) for ns, frame in got], 1))
        (run / "receiver_hw.err").write_text(REPORT % 0, encoding="utf-8")
        with open(run / "phc_offset.csv", "w", encoding="utf-8", newline="") as fh:
            fh.write("system_ns,card_minus_system_ns,window_ns\n")
            for k in range(260):
                fh.write("%d,%d,1450\n" % (T0 + k * S // 2, offset))
    return run


class TestOneRun:
    def test_each_span_is_what_the_made_up_message_took(self, tmp_path):
        row = ff.read_run(str(made_up_run(tmp_path, "r001")), DRIVER, BROKER, RECEIVER)
        assert (row["stamped"], row["messages"], row["unmatched_tx"], row["unmatched_rx"]) == (
            40, 40, 0, 0)
        assert row["W_median"] == pytest.approx(500.0) and row["W_p99"] == pytest.approx(500.0)
        assert row["Hsend_mean"] == pytest.approx(300.0)
        assert row["Hrecv_median"] == pytest.approx(120.0)
        assert row["D_mean"] == pytest.approx(920.0)
        assert row["wire_nonpositive"] == 0 and row["priority"] is False
        assert row["W_min"] == pytest.approx(500.0) and row["Hsend_min"] == pytest.approx(300.0)
        assert row["load_measured"] == pytest.approx(88.2) and row["dropped"] == 0

    def test_the_captures_drops_are_summed_and_a_capture_that_never_reported_leaves_none(
            self, tmp_path):
        run = made_up_run(tmp_path, "r008", logs={"sender_full.err": REPORT % 2,
                                                  "receiver_full.err": REPORT % 3})
        assert ff.read_run(str(run), DRIVER, BROKER, RECEIVER)["dropped"] == 5
        (run / "receiver_hw.err").write_text("tcpdump: listening on enP58460s1\n",
                                             encoding="utf-8")
        assert ff.capture_drops(str(run)) is None, "a capture that ran and was never heard from"
        assert ff.capture_drops(str(tmp_path / "nowhere")) is None, "no capture ran"

    def test_a_message_the_sender_capture_missed_is_counted_and_left_out(self, tmp_path):
        run = made_up_run(tmp_path, "r002", missing_tx=(10,))
        row = ff.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert (row["stamped"], row["messages"], row["unmatched_tx"]) == (40, 39, 1)

    def test_a_wire_time_at_or_below_zero_is_counted(self, tmp_path):
        run = made_up_run(tmp_path, "r003", reversed_wire=(12, 13))
        assert ff.read_run(str(run), DRIVER, BROKER, RECEIVER)["wire_nonpositive"] == 2

    def test_the_cards_arrival_gives_the_kernels_own_delay(self, tmp_path):
        """Described, not judged: the card saw each packet 30 us before the kernel stamped it, on a
        clock 4.8 ms behind the system's, so W to the card is 470 us and the kernel's delay 30."""
        run = made_up_run(tmp_path, "r005", card=(-4800 * US, 30 * US))
        row = ff.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert row["card_matched"] == 40 and row["card_window_ns"] == 1450
        assert row["Kdelay_median"] == pytest.approx(30.0, abs=0.01)
        assert row["Kdelay_min"] == pytest.approx(30.0, abs=0.01)
        assert row["Wcard_p99"] == pytest.approx(470.0, abs=0.01)
        assert row["dropped"] == 0, "the card's capture reported too"

    def test_a_run_without_a_card_capture_has_no_card_spans(self, tmp_path):
        row = ff.read_run(str(made_up_run(tmp_path, "r006")), DRIVER, BROKER, RECEIVER)
        assert row["card_matched"] == 0 and row["Kdelay_median"] is None
        assert row["card_window_ns"] is None and row["Kdelay_min"] is None

    def test_a_run_with_no_message_has_no_spans(self, tmp_path):
        run = made_up_run(tmp_path, "r004", n=0)
        row = ff.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert row["messages"] == 0 and row["W_median"] is None and row["D_p99"] is None
        assert row["D_max"] is None and row["D_held"] == row["W_held"] == 0

    def test_a_pause_is_marked_in_D_and_in_W_where_the_broker_held_it(self, tmp_path):
        """Two messages held 200 ms in the broker and one held 200 ms in the host before its bytes
        left: all three pass the quality report's 150 ms limit in D, and the broker's two in W."""
        run = made_up_run(tmp_path, "r007", slow={20: (0, 200000 * US), 21: (0, 200000 * US),
                                                  30: (200000 * US, 0)})
        row = ff.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert (row["D_held"], row["W_held"]) == (3, 2)
        assert row["D_max"] == pytest.approx(200920.0)


class TestDepartures:
    """departure_times: each id timed by the packet that carried the end of it out."""

    def _capture(self, tmp_path, segments, name="s.pcap"):
        path = tmp_path / name
        path.write_bytes(pcap_bytes(
            [(ns, ether(ip_tcp(src, BROKER, 40000, 9092, seq, data)))
             for ns, seq, data, src in segments], 1))
        return str(path)

    def test_an_id_split_across_two_packets_is_timed_by_the_second(self, tmp_path):
        data = record("constant-000001")
        cut = 10
        path = self._capture(tmp_path, [(T0, 5000, data[:cut], DRIVER),
                                        (T0 + 7 * US, 5000 + cut, data[cut:], DRIVER)])
        assert ff.departure_times(path, DRIVER, BROKER) == {"constant-000001": T0 + 7 * US}

    def test_a_packet_the_capture_lost_costs_only_its_own_ids(self, tmp_path):
        one, two, three = (record("constant-%06d" % i) for i in (1, 2, 3))
        path = self._capture(tmp_path, [
            (T0, 1, one, DRIVER),
            (T0 + 40 * US, 1 + len(one) + len(two), three, DRIVER)])
        assert ff.departure_times(path, DRIVER, BROKER) == {
            "constant-000001": T0, "constant-000003": T0 + 40 * US}

    def test_a_segment_sent_twice_keeps_the_time_it_was_first_sent(self, tmp_path):
        data = record("constant-000004")
        again = record("constant-000005")
        path = self._capture(tmp_path, [
            (T0, 1, data, DRIVER), (T0 + 200 * US, 1, data, DRIVER),
            (T0 + 300 * US, 1 + len(data), again, DRIVER),
            (T0 + 900 * US, 1 + len(data) - 4, data[-4:] + again, DRIVER)])
        assert ff.departure_times(path, DRIVER, BROKER) == {
            "constant-000004": T0, "constant-000005": T0 + 300 * US}

    def test_an_id_carried_twice_in_one_record_is_timed_by_the_later_carrying(self, tmp_path):
        data = record("constant-000006")
        cut = data.index(b"|") + 1
        path = self._capture(tmp_path, [(T0, 1, data[:cut], DRIVER),
                                        (T0 + 9 * US, 1 + cut, data[cut:], DRIVER)])
        assert ff.departure_times(path, DRIVER, BROKER) == {"constant-000006": T0 + 9 * US}

    def test_the_same_id_far_further_on_is_another_messages_and_is_ignored(self, tmp_path):
        data = record("constant-000007")
        filler = b"x" * 3000
        path = self._capture(tmp_path, [
            (T0, 1, data, DRIVER), (T0 + US, 1 + len(data), filler, DRIVER),
            (T0 + 5 * US, 1 + len(data) + len(filler), data, DRIVER)])
        assert ff.departure_times(path, DRIVER, BROKER) == {"constant-000007": T0}

    def test_other_traffic_and_empty_segments_are_left_out(self, tmp_path):
        data = record("constant-000008")
        path = self._capture(tmp_path, [(T0, 1, data, "10.1.1.99"), (T0, 1, b"", DRIVER),
                                        (T0 + 3 * US, 1, data, DRIVER)])
        raw = tmp_path / "raw.pcap"
        frames = pcap_bytes([(T0, b"\0" * 14 + struct.pack(">H", 0x86DD) + b"\0" * 40)], 1)
        raw.write_bytes(frames)
        assert ff.departure_times(path, DRIVER, BROKER) == {"constant-000008": T0 + 3 * US}
        assert ff.departure_times(str(raw), DRIVER, BROKER) == {}

    def test_offsets_wrap_round_at_two_to_the_thirty_two(self):
        assert ff._offset(5, 0xFFFFFFF0) == 21 and ff._offset(0xFFFFFFF0, 5) == -21


class TestTheCardsClock:
    def test_an_offset_between_samples_is_interpolated_and_held_beyond_them(self):
        """A card 100 ns behind, drifting 10 parts in a million: the system time the card read
        1,600,000 stands for is 1,600,106, as solving t + offset(t) = 1,600,000 gives."""
        offsets = [(1000000, -100), (2000000, -110)]
        assert ff.to_system(1600000, offsets) == 1600106
        assert ff.to_system(100, offsets) == 200
        assert ff.to_system(9000000, offsets) == 9000110

    def test_no_samples_or_no_capture_give_no_card_times(self, tmp_path):
        assert ff.card_offsets(str(tmp_path / "none.csv")) == []
        run = made_up_run(tmp_path, "r001", card=(0, 0))
        (run / "phc_offset.csv").write_text("system_ns,card_minus_system_ns,window_ns\n",
                                            encoding="utf-8")
        assert ff.card_window(str(run / "phc_offset.csv")) is None, "a sampler that took none"
        (run / "phc_offset.csv").unlink()
        assert ff.card_times(str(run), BROKER, RECEIVER) == {}


class TestTheBlock:
    def test_only_the_blocks_passing_runs_are_read(self, tmp_path):
        made_up_run(tmp_path, "r001")
        made_up_run(tmp_path, "r002", verdict="repeat")
        made_up_run(tmp_path, "r003", verdict=None)
        made_up_run(tmp_path, "r004", setup="R1-kafka-l75-ord")
        rows, skipped = ff.read_block([str(tmp_path)], DRIVER, BROKER, RECEIVER)
        assert [r["run"] for r in rows] == ["law_f1_r001"]
        assert skipped == [("law_f1_r002", "repeat"), ("law_f1_r003", "not judged")]


def table_row(backend, load, priority, **fields):
    row = {"run": "r", "backend": backend, "load_pct": str(load), "priority": str(priority),
           "stamped": "5000", "messages": "5000", "unmatched_tx": "0", "unmatched_rx": "0",
           "wire_nonpositive": "0", "W_median": "700", "W_p99": "850", "W_mean": "710",
           "D_median": "900", "D_mean": "1000", "D_p99": "1000", "Hsend_mean": "40",
           "Hrecv_mean": "250"}
    row.update({k: str(v) for k, v in fields.items()})
    return row


def held_block(changes=None):
    """Every setup of the block, one run each, as the fix predicts: W the same everywhere, D's
    tail and mean up under the load at normal priority, carried by the host, Kafka's H_send up."""
    rows = []
    for b in ff.BACKENDS:
        for load in (ff.IDLE, ff.BUSY):
            for p in (False, True):
                busy_normal = load == ff.BUSY and not p
                fields = {"D_p99": 4000 if busy_normal else 1000,
                          "D_mean": 1600 if busy_normal else 1000}
                if b == "kafka" and busy_normal:
                    fields["Hsend_mean"] = 400
                fields.update((changes or {}).get((b, load, p), {}))
                rows.append(table_row(b, load, p, **fields))
    return rows


class TestTheJudge:
    def test_every_prediction_holds_on_a_block_that_behaves_as_the_fix_predicts(self):
        found = ff.judge(held_block())
        assert {k: v["verdict"] for k, v in found.items()} == {
            "F-a": "holds", "F-b": "holds", "F-c": "holds", "F-d": "holds", "F-e": "holds"}

    @pytest.mark.parametrize("change, name", [
        ({("redis", 88, False): {"W_median": 800}}, "F-a"),
        ({("kafka", 0, True): {"W_median": 600}}, "F-a"),
        ({("kafka", 88, True): {"W_p99": 1100}}, "F-b"),
        ({("redis", 0, False): {"wire_nonpositive": 1}}, "F-c"),
        ({("kafka", 88, True): {"unmatched_rx": 26}}, "F-c"),
        ({("kafka", 0, False): {"stamped": 0}}, "F-c"),
        ({("redis", 88, False): {"D_p99": 1400}}, "F-d"),
        ({("redis", 88, False): {"D_mean": 1000}}, "F-d"),
        ({("kafka", 88, False): {"W_mean": 850}}, "F-d"),
        ({("kafka", 88, False): {"Hsend_mean": 100}}, "F-e"),
        ({("redis", 88, False): {"Hsend_mean": 200}}, "F-e"),
    ], ids=["W's median moved with the load", "W's median moved with the priority",
            "W's tail moved", "a wire time below zero", "too many unmatched", "nothing stamped",
            "no tail effect to remove", "no rise in D's mean", "W carrying the rise",
            "no send-side wait on Kafka", "a send-side wait on Redis"])
    def test_a_block_that_does_otherwise_fails_that_prediction(self, change, name):
        assert ff.judge(held_block(change))[name]["verdict"] == "fails"

    def test_a_block_missing_a_setup_is_undecided(self):
        rows = [r for r in held_block() if not (r["backend"] == "redis" and r["load_pct"] == "0")]
        found = ff.judge(rows)
        assert {k: v["verdict"] for k, v in found.items() if k != "F-c"} == {
            "F-a": "undecided", "F-b": "undecided", "F-d": "undecided", "F-e": "undecided"}
        assert ff.judge([])["F-c"]["verdict"] == "undecided"

    def test_a_setup_value_is_the_median_over_its_runs_and_skips_empty_cells(self):
        rows = [table_row("kafka", 0, False, W_median=v) for v in (600, 700, 900)]
        rows.append(table_row("kafka", 0, False, W_median=""))
        assert ff.setup_value(rows, "kafka", 0, False, "W_median") == 700


class TestMain:
    def test_read_then_judge(self, tmp_path, capsys):
        made_up_run(tmp_path / "runs", "r001")
        table, judged = tmp_path / "out" / "f1.csv", tmp_path / "out" / "f1_verdicts.json"
        assert ff.main(["read", "--runs", str(tmp_path / "runs"), "--driver", DRIVER, "--broker",
                        BROKER, "--receiver", RECEIVER, "--out", str(table)]) == 0
        with table.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1 and tuple(rows[0]) == ff.FIELDS
        assert ff.main(["judge", "--table", str(table), "--out", str(judged)]) == 0
        found = json.loads(judged.read_text(encoding="utf-8"))
        assert found["F-c"]["verdict"] == "holds" and found["F-a"]["verdict"] == "undecided"
        assert found["pauses"] == []
        assert "F-a  undecided" in capsys.readouterr().out

    def test_the_runs_a_pause_held_are_listed_beside_the_verdicts(self, tmp_path, capsys):
        made_up_run(tmp_path / "runs", "r001")
        made_up_run(tmp_path / "runs", "r002", slow={20: (0, 200000 * US)})
        table, judged = tmp_path / "f1.csv", tmp_path / "f1_verdicts.json"
        ff.main(["read", "--runs", str(tmp_path / "runs"), "--driver", DRIVER, "--broker", BROKER,
                 "--receiver", RECEIVER, "--out", str(table)])
        assert ff.main(["judge", "--table", str(table), "--out", str(judged)]) == 0
        found = json.loads(judged.read_text(encoding="utf-8"))
        assert found["pauses"] == [["law_f1_r002", "F1-kafka-l88-ord", 1, 1,
                                    pytest.approx(200920.0)]]
        assert "runs a pause held messages in: 1" in capsys.readouterr().out

    def test_a_folder_with_no_passing_run_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "f1.csv"
        assert ff.main(["read", "--runs", str(tmp_path), "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--out", str(out)]) == 1
        assert not out.exists() and "no passing run" in capsys.readouterr().out
