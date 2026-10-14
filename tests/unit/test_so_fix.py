"""Tests for scripts/so_fix.py: freeze 40's test of the full fix as a benchmark tool reads it, on
runs made up in the shape real runs have on disk, and G-a to G-e read off tables made to hold or to
fail.

A made-up message is published, leaves the driver's kernel 300 us later (the sender capture's
timestamp), reaches the receiver's kernel 500 us after that, and is stamped by the consumer 120 us
later. The producer's socket reports its transmit timestamp 3 us before the capture's, as the
device queue precedes the capture's tap, and the consumer's socket the receive timestamp the
capture saw. So W is 500 us, W_so 503 us, and they differ by 3 us for every message.
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

import so_fix as sf  # noqa: E402
import full_fix as ff  # noqa: E402

US = 1000
S = 1000000000
T0 = 1791900000 * S
DRIVER, BROKER, RECEIVER = "10.1.1.10", "10.1.1.21", "10.1.1.11"
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
    return b"key:" + eid.encode() + b'|{"event_id":"' + eid.encode() + b'","type":"pass"}'


def made_up_run(root, key, setup="F2-kafka-l88-ord", backend="kafka", load=88, priority=False,
                verdict="count", n=40, missing_so_tx=(), missing_so_rx=(), reversed_so=(),
                slow=None, so_files=True):
    """One run of the block on disk: n messages after the warm-up, each published every 20 ms.
    `slow` holds a message 200 ms in the broker: {index: True}."""
    run = root / ("law_f2_" + key)
    run.mkdir(parents=True)
    with open(run / "queue_row.json", "w", encoding="utf-8") as fh:
        json.dump({"setup": setup, "params": {"backend": backend, "load_pct": load,
                                              "priority": priority}}, fh)
    with open(run / "integrity.json", "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "checks": {"load": {"value": load + 0.2}}}, fh)
    prod, cons, sent, got, so_rows = [], [], [], [], []
    seq_tx = seq_rx = 1000
    for i in range(n + 5):
        eid = "constant-%06d" % i
        t_pub = T0 + (0 if i < 5 else 31 * S) + i * 20 * 1000 * US
        t_tx = t_pub + 300 * US
        t_rx = t_tx + 500 * US + (200000 * US if (slow or {}).get(i) else 0)
        t_recv = t_rx + 120 * US
        prod.append({"event_id": eid, "t_prod_send_ns": t_pub})
        cons.append({"event_id": eid, "t_consume_ns": t_recv})
        payload = record(eid)
        sent.append((t_tx, ether(ip_tcp(DRIVER, BROKER, 40000, 9092, seq_tx, payload))))
        got.append((t_rx, sll2(ip_tcp(BROKER, RECEIVER, 9092, 40001, seq_rx, payload))))
        seq_tx += len(payload)
        seq_rx += len(payload)
        tx_so = t_tx - 3 * US
        rx_so = (tx_so - 1 * US) if i in reversed_so else t_rx
        so_rows.append((eid, "tx", "" if i in missing_so_tx else tx_so))
        so_rows.append((eid, "rx", "" if i in missing_so_rx else rx_so))
    for name, columns, rows in (("producer.csv", PRODUCER_COLUMNS, prod),
                                ("consumer_events.csv", CONSUMER_COLUMNS, cons)):
        with open(run / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=columns)
            w.writeheader()
            w.writerows(rows)
    (run / "sender_full.pcap").write_bytes(pcap_bytes(sent, 1))
    (run / "receiver_full.pcap").write_bytes(pcap_bytes(got, 276))
    if so_files:
        for name, way in (("producer_so.csv", "tx"), ("consumer_so.csv", "rx")):
            with open(run / name, "w", encoding="utf-8", newline="") as fh:
                fh.write("event_id,direction,ns\n")
                for eid, d, ns in so_rows:
                    if d == way:
                        fh.write("%s,%s,%s\n" % (eid, d, ns))
    return run


class TestOneRun:
    def test_the_two_instruments_agree_to_the_queues_lead(self, tmp_path):
        row = sf.read_run(str(made_up_run(tmp_path, "r001")), DRIVER, BROKER, RECEIVER)
        assert (row["stamped"], row["messages"], row["so_messages"], row["agreed"]) == (
            40, 40, 40, 40)
        assert row["W_median"] == pytest.approx(500.0) and row["Wso_median"] == pytest.approx(503.0)
        assert row["Dif_median"] == pytest.approx(3.0) and row["Dif_p99"] == pytest.approx(3.0)
        assert row["tx_diff_median"] == pytest.approx(-3.0) and row["rx_diff_median"] == 0
        assert row["rx_same_share"] == 1.0 and row["so_nonpositive"] == 0
        assert (row["so_missing_tx"], row["so_missing_rx"]) == (0, 0)
        assert row["load_measured"] == pytest.approx(88.2) and row["D_held"] == 0

    def test_a_message_either_socket_missed_is_counted(self, tmp_path):
        run = made_up_run(tmp_path, "r002", missing_so_tx=(10,), missing_so_rx=(11, 12))
        row = sf.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert (row["so_missing_tx"], row["so_missing_rx"], row["so_messages"]) == (1, 2, 37)

    def test_a_run_without_socket_files_misses_every_message(self, tmp_path):
        run = made_up_run(tmp_path, "r003", so_files=False)
        assert sf.socket_times(str(run)) == ({}, {})
        row = sf.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert (row["so_missing_tx"], row["so_missing_rx"]) == (40, 40)
        assert row["Wso_median"] is None and row["tx_diff_median"] is None
        assert row["rx_same_share"] is None

    def test_a_socket_latency_at_or_below_zero_is_counted(self, tmp_path):
        run = made_up_run(tmp_path, "r004", reversed_so=(5, 6))
        assert sf.read_run(str(run), DRIVER, BROKER, RECEIVER)["so_nonpositive"] == 2

    def test_a_pause_is_marked_in_D_and_in_W_so(self, tmp_path):
        run = made_up_run(tmp_path, "r005", slow={20: True})
        row = sf.read_run(str(run), DRIVER, BROKER, RECEIVER)
        assert (row["D_held"], row["Wso_held"]) == (1, 1) and row["D_max"] > 150000

    def test_a_run_with_no_message_has_no_spans(self, tmp_path):
        row = sf.read_run(str(made_up_run(tmp_path, "r006", n=0)), DRIVER, BROKER, RECEIVER)
        assert row["D_max"] is None and row["Dif_median"] is None


def table_row(backend, load, priority, **fields):
    row = {"run": "r", "setup": "F2-x", "backend": backend, "load_pct": str(load),
           "priority": str(priority), "stamped": "5000", "so_missing_tx": "0",
           "so_missing_rx": "0", "so_nonpositive": "0", "Dif_median": "4", "Dif_p99": "30",
           "Wso_median": "700", "Wso_p99": "850", "Wso_mean": "710", "D_p99": "1000",
           "D_mean": "1000", "D_held": "0", "Wso_held": "0", "D_max": "2000"}
    row.update({k: str(v) for k, v in fields.items()})
    return row


def held_block(changes=None):
    """Every setup, one run each, as the fix predicts: W_so close to W and the same everywhere,
    D's tail and mean up under the load at normal priority."""
    rows = []
    for b in ff.BACKENDS:
        for load in (ff.IDLE, ff.BUSY):
            for p in (False, True):
                busy_normal = load == ff.BUSY and not p
                fields = {"D_p99": 4000 if busy_normal else 1000,
                          "D_mean": 1600 if busy_normal else 1000}
                fields.update((changes or {}).get((b, load, p), {}))
                rows.append(table_row(b, load, p, **fields))
    return rows


class TestTheJudge:
    def test_every_prediction_holds_on_a_block_that_behaves_as_predicted(self):
        found = sf.judge(held_block())
        assert {k: v["verdict"] for k, v in found.items()} == dict.fromkeys(
            ("G-a", "G-b", "G-c", "G-d", "G-e"), "holds")

    @pytest.mark.parametrize("change, name", [
        ({("kafka", 88, False): {"Dif_median": 25}}, "G-a"),
        ({("redis", 0, True): {"Dif_p99": 140}}, "G-a"),
        ({("redis", 88, False): {"Wso_median": 800}}, "G-b"),
        ({("kafka", 88, True): {"Wso_p99": 1100}}, "G-c"),
        ({("redis", 0, False): {"so_nonpositive": 1}}, "G-d"),
        ({("kafka", 88, True): {"so_missing_rx": 26}}, "G-d"),
        ({("kafka", 0, False): {"stamped": 0}}, "G-d"),
        ({("redis", 88, False): {"D_p99": 1400}}, "G-e"),
        ({("kafka", 88, False): {"Wso_mean": 850}}, "G-e"),
    ], ids=["the medians disagree", "the tails disagree", "W_so's median moved", "W_so's tail moved",
            "a socket latency below zero", "too many missing", "nothing stamped",
            "no tail effect", "W_so carrying the rise"])
    def test_a_block_that_does_otherwise_fails_that_prediction(self, change, name):
        assert sf.judge(held_block(change))[name]["verdict"] == "fails"

    def test_a_block_missing_a_setup_is_undecided(self):
        rows = [r for r in held_block() if not (r["backend"] == "redis" and r["load_pct"] == "0")]
        found = sf.judge(rows)
        assert {k: v["verdict"] for k, v in found.items() if k != "G-d"} == dict.fromkeys(
            ("G-a", "G-b", "G-c", "G-e"), "undecided")
        assert sf.judge([])["G-d"]["verdict"] == "undecided"

    def test_the_runs_a_pause_held_are_listed(self):
        rows = [table_row("kafka", 0, False), table_row("kafka", 0, False, run="p", D_held=2,
                                                        Wso_held=1, D_max=300000)]
        assert sf.pauses(rows) == [["p", "F2-x", 2, 1, 300000.0]]


class TestTheBlock:
    def test_only_the_blocks_passing_runs_are_read_and_judged(self, tmp_path, capsys):
        made_up_run(tmp_path / "runs", "r001")
        made_up_run(tmp_path / "runs", "r002", verdict="repeat")
        made_up_run(tmp_path / "runs", "r003", setup="F1-kafka-l88-ord")
        table, judged = tmp_path / "out" / "f2.csv", tmp_path / "out" / "f2_verdicts.json"
        assert sf.main(["read", "--runs", str(tmp_path / "runs"), "--driver", DRIVER, "--broker",
                        BROKER, "--receiver", RECEIVER, "--out", str(table)]) == 0
        assert "left out: [('law_f2_r002', 'repeat')]" in capsys.readouterr().out
        with table.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1 and tuple(rows[0]) == sf.FIELDS
        assert sf.main(["judge", "--table", str(table), "--out", str(judged)]) == 0
        found = json.loads(judged.read_text(encoding="utf-8"))
        assert found["G-d"]["verdict"] == "holds" and found["G-a"]["verdict"] == "undecided"
        assert found["pauses"] == [] and "G-a  undecided" in capsys.readouterr().out

    def test_a_folder_with_no_passing_run_writes_nothing(self, tmp_path, capsys):
        out = tmp_path / "f2.csv"
        assert sf.main(["read", "--runs", str(tmp_path), "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--out", str(out)]) == 1
        assert not out.exists() and "no passing run" in capsys.readouterr().out
