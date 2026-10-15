"""Tests for scripts/order_scope.py, freeze 41's judge, against runs built here file by file in the
shape the kit writes them: the clients' own files, their socket files and journals, and both
captures."""
import csv
import json
import os
import socket
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import order_scope as osc  # noqa: E402

T0 = 1791900000 * 10**9
DRIVER, BROKER, RECEIVER = "10.1.1.10", "10.1.1.21", "10.1.1.11"
US = 1000


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


def eid(i):
    return "constant-%06d" % i


def write_pcap(path, packets):
    """Nanosecond pcap of raw IPv4 TCP packets: (ns, src, dst, sport, dport, seq, payload)."""
    with open(path, "wb") as fh:
        fh.write(struct.pack("<IHHiIII", 0xa1b23c4d, 2, 4, 0, 0, 65535, 101))
        for ns, src, dst, sport, dport, seq, payload in packets:
            tcp = struct.pack(">HHIIBBHHH", sport, dport, seq, 0, 5 << 4, 0x18, 65535, 0, 0)
            ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(tcp) + len(payload), 0, 0, 64, 6,
                             0, socket.inet_aton(src), socket.inet_aton(dst))
            frame = ip + tcp + payload
            fh.write(struct.pack("<IIII", ns // 10**9, ns % 10**9, len(frame), len(frame)))
            fh.write(frame)


def write_journal(stem, local, peer, out, inb, reads, keys):
    with open(stem + "_streams.csv", "w", encoding="utf-8") as fh:
        fh.write("conn,local_port,peer_host,peer_port\n0,%d,%s,%d\n" % (local, BROKER, peer))
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


def make_run(folder, name, setup, params, msgs, verdict="count", journals=True, captures=True):
    """A Kafka or Redis run. msgs: [dict(pub, tx, rx_ack, ack, req, rx, recv)] in ns from T0."""
    run = os.path.join(folder, name)
    os.makedirs(run)
    backend = params["backend"]
    with open(os.path.join(run, "queue_row.json"), "w", encoding="utf-8") as fh:
        json.dump({"setup": setup, "params": params}, fh)
    with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
        json.dump({"verdict": verdict, "checks": {"load": {"value": 0.7}}}, fh)
    with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,t_prod_send_ns,t_broker_ack_ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,%d,%s\n" % (eid(i), T0 + m["pub"],
                                     "" if m.get("ack") is None else T0 + m["ack"]))
    with open(os.path.join(run, "consumer_events.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,t_consume_ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,%d\n" % (eid(i), T0 + m["recv"]))
    with open(os.path.join(run, "producer_so.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,direction,ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,tx,%d\n" % (eid(i), T0 + m["tx"]))
    with open(os.path.join(run, "consumer_so.csv"), "w", encoding="utf-8") as fh:
        fh.write("event_id,direction,ns\n")
        for i, m in enumerate(msgs):
            fh.write("%s,rx,%d\n" % (eid(i), T0 + m["rx"]))
    port = osc.PORTS[backend]
    p_out = p_in = c_out = c_in = b""
    p_reads, p_keys, c_reads, c_keys = [], [], [], []
    for i, m in enumerate(msgs):
        body = eid(i).encode()
        if backend == "kafka":
            req, ack = kafka_request(0, i + 1, body), kafka_response(i + 1, b"ok")
            fetch, delivery = kafka_request(1, 1000 + i), kafka_response(1000 + i, body)
        else:
            req = resp(b"XADD", b"sb", b"*", b"payload", body)
            ack = b"$15\r\n%015d\r\n" % i
            fetch = resp(b"XREADGROUP", b"GROUP", b"g", b"c", b"BLOCK", b"1000")
            delivery = b"*1\r\n*1\r\n$15\r\n" + body + b"\r\n"
        p_out += req
        p_keys.append((len(p_out) - 1, T0 + m["tx"]))
        p_in += ack
        p_reads.append((len(p_in), None if m.get("rx_ack") is None else T0 + m["rx_ack"]))
        c_out += fetch
        c_keys.append((len(c_out) - 1, T0 + m["req"]))
        c_in += delivery
        c_reads.append((len(c_in), T0 + m["rx"]))
    if journals:
        write_journal(os.path.join(run, "producer_journal"), 40001, port, p_out, p_in, p_reads,
                      p_keys)
        write_journal(os.path.join(run, "consumer_journal"), 40002, port, c_out, c_in, c_reads,
                      c_keys)
    if captures:
        sender, receiver = [], []
        p_seq = c_seq = 0
        acks = [p_in[:p_reads[0][0]]] + [p_in[a:b] for (a, _), (b, _) in
                                          zip(p_reads, p_reads[1:])]
        acks = [p_in[s:e] for s, e in zip([0] + [r[0] for r in p_reads[:-1]],
                                           [r[0] for r in p_reads])]
        reqs = [p_out[s:e + 1] for s, e in zip([0] + [k[0] + 1 for k in p_keys[:-1]],
                                                [k[0] for k in p_keys])]
        deliveries = [c_in[s:e] for s, e in zip([0] + [r[0] for r in c_reads[:-1]],
                                                 [r[0] for r in c_reads])]
        out_seq = 0
        for i, m in enumerate(msgs):
            sender.append((T0 + m["tx"] + 3 * US, DRIVER, BROKER, 40001, port, out_seq, reqs[i]))
            out_seq += len(reqs[i])
            if m.get("rx_ack") is not None:
                sender.append((T0 + m["rx_ack"] - 2 * US, BROKER, DRIVER, port, 40001, p_seq,
                               acks[i]))
            p_seq += len(acks[i])
            receiver.append((T0 + m["rx"], BROKER, RECEIVER, port, 40002, c_seq, deliveries[i]))
            c_seq += len(deliveries[i])
        write_pcap(os.path.join(run, "sender_full.pcap"), sender)
        write_pcap(os.path.join(run, "receiver_full.pcap"), receiver)
    return run


def msg(pub=0, tx=100, rx_ack=600, ack=700, req=50, rx=900, recv=1000):
    """One message's times in microseconds from T0, as ns."""
    return dict(pub=pub * US, tx=tx * US, rx_ack=None if rx_ack is None else rx_ack * US,
                ack=None if ack is None else ack * US, req=req * US, rx=rx * US, recv=recv * US)


class TestEquationS3:
    def test_the_copy_agrees_with_the_emitters(self):
        import emit_paper_numbers as epn
        for x in (-1.0, 0.0, 0.5, 1.0, 2.0, 3.0, 3.5, 4.0, 5.0):
            assert osc.rest_of_slice_g(x, 3.0, 1.0) == epn.rest_of_slice_g(x, 3.0, 1.0)


class TestReadingRuns:
    def test_an_order_run_counts_each_cause(self, tmp_path):
        msgs = [msg(),                                                  # in order, S > 0
                msg(pub=10000, tx=10100, rx_ack=10600, ack=12500, req=10050, rx=10900,
                    recv=11000),                                        # read late: S < 0, S_k > 0
                msg(pub=20000, tx=20100, rx_ack=20950, ack=21010, req=20150, rx=20900,
                    recv=21000),                                        # delivered first
                msg(pub=30000, tx=30100, rx_ack=None, ack=None, req=30050, rx=30900,
                    recv=31000)]                                        # no acknowledgment
        run = make_run(str(tmp_path), "law_k_r001-K-kafka-l88-ord-a1", "K-kafka-l88-ord",
                       {"backend": "kafka", "load_pct": 88, "send_workers": 1,
                        "sched_features": "NO_RUN_TO_PARITY", "idle_poll": True}, msgs)
        row, full = osc.read_order_run(run, DRIVER, BROKER, RECEIVER, 0)
        assert (row["messages"], row["timed"], row["missing_ack"]) == (4, 3, 1)
        assert (row["S_neg"], row["S_neg_Sk_neg"], row["Sk_neg"]) == (2, 1, 1)
        assert row["workers"] == "1" and row["idle_poll"] is True
        assert row["sched_features"] == "NO_RUN_TO_PARITY"
        assert row["flagged"] == 1, "the third message's request left after the message did"
        assert row["dack_waited"] == 1, "only the late reading waited past 100 us"
        assert row["ack_checked"] == 3 and row["ack_diff_median"] == pytest.approx(2.0)
        assert len(full) == 3 and full[1]["dack"] == pytest.approx(1900.0)

    def test_a_redis_run_reads_through_resp_and_without_captures(self, tmp_path):
        run = make_run(str(tmp_path), "law_k_r001-K-redis-l0-ord-a1", "K-redis-l0-ord",
                       {"backend": "redis", "load_pct": 0}, [msg(), msg(pub=5000, tx=5100,
                       rx_ack=5600, ack=5700, req=5900, rx=5900, recv=6000)], captures=False)
        row, _ = osc.read_order_run(run, DRIVER, BROKER, RECEIVER, 0)
        assert row["timed"] == 2 and row["ack_checked"] == 0 and row["ack_diff_median"] is None
        assert row["flagged"] == 1, "its request left after the message did"
        assert row["idle_poll"] == "" and row["workers"] == ""

    def test_a_control_run_gives_each_median(self, tmp_path):
        run = make_run(str(tmp_path), "law_p_r001-P-kafka-d1-a1", "P-kafka-d1",
                       {"backend": "kafka", "load_pct": 0, "delay_ms": 1}, [msg(), msg(
                           pub=5000, tx=5100, rx_ack=5600, ack=5700, req=5050, rx=5900,
                           recv=6000)])
        row, msgs = osc.read_control_run(run, DRIVER, BROKER, RECEIVER, 0)
        assert msgs == [] and row["delay_ms"] == 1
        assert row["Wso_median"] == pytest.approx(800.0)
        assert row["W_median"] == pytest.approx(797.0)
        assert row["A_median"] == pytest.approx(700.0) and row["D_median"] == pytest.approx(1000.0)

    def test_a_ladder_run_reads_its_rung_flags_and_packets(self, tmp_path):
        run = make_run(str(tmp_path), "law_l500_r001-L500-redis-l0-a1", "L500-redis-l0",
                       {"backend": "redis", "load_pct": 0}, [msg(), msg(
                           pub=5000, tx=5100, rx_ack=5600, ack=5700, req=5200, rx=5900,
                           recv=6000)])
        row, _ = osc.read_ladder_run(run, DRIVER, BROKER, RECEIVER, 0)
        assert row["rate"] == 500 and row["messages"] == 2
        assert (row["flag_known"], row["flagged"]) == (2, 1)
        assert row["Wso_flagged_median"] == pytest.approx(800.0)
        assert row["Wso_unflagged_median"] == pytest.approx(800.0)
        assert row["Dif_median"] == pytest.approx(3.0)
        assert (row["reads"], row["reads_multi"]) == (2, 0)
        assert (row["S_count"], row["S_neg"]) == (2, 0)

    def test_a_setup_outside_the_ladder_has_no_rung_and_a_journal_off_the_capture_is_left(
            self, tmp_path):
        run = make_run(str(tmp_path), "law_x_r001-X-kafka-a1", "X-kafka",
                       {"backend": "kafka", "load_pct": 0}, [msg()])
        stem = os.path.join(run, "consumer_journal_streams.csv")
        with open(stem, "w", encoding="utf-8") as fh:
            fh.write("conn,local_port,peer_host,peer_port\n0,49999,%s,9092\n" % BROKER)
        row, _ = osc.read_ladder_run(run, DRIVER, BROKER, RECEIVER, 0)
        assert row["rate"] is None and row["reads"] == 0


class TestBins:
    def test_the_bins_hold_the_observed_rate_and_both_predictions(self):
        msgs = []
        for i in range(10):
            sk = 100.0 * i
            msgs.append({"Sk": sk, "S": -1.0 if i < 4 else 50.0, "dack": 300.0 + 10 * i,
                         "drecv": 20.0})
        msgs.append({"Sk": -5.0, "S": -5.0, "dack": 30.0, "drecv": 20.0})
        rows = osc.bins_by_margin("K-kafka-l88-ord", msgs)
        assert [r["messages"] for r in rows] == [2, 2, 2, 2, 2]
        assert [r["negatives"] for r in rows] == [2, 2, 0, 0, 0]
        assert rows[0]["observed"] == 1.0 and 0 <= rows[-1]["predicted"] < rows[0]["predicted"]
        assert rows[-1]["predicted"] == 0.0, "no delay outlasts the last bin's margin"
        assert rows[0]["pG"] > rows[-1]["pG"] >= 0

    def test_a_setup_with_too_few_messages_leaves_empty_bins_out(self):
        rows = osc.bins_by_margin("s", [{"Sk": 1.0, "S": 2.0, "dack": 5.0, "drecv": 1.0}])
        assert len(rows) == 1 and rows[0]["bin"] == 5


def order_rows():
    """Block K's run rows, with every prediction holding."""
    rows = []
    for backend in ("kafka", "redis"):
        for load, prio, workers, dack in ((0, False, "", 200.0), (88, False, "", 900.0),
                                           (88, True, "", 100.0), (0, True, "", 50.0),
                                           (88, True, "1", 90.0), (0, True, "1", 40.0)):
            if backend == "kafka" and workers:
                continue
            setup = "K-%s-l%d-%s%s" % (backend, load, "rt" if prio else "ord",
                                       "-w1" if workers else "")
            order = 30 if (backend == "redis" and prio) else 1
            neg = 40 if not (backend == "redis" and prio and workers == "1") else 10
            rows.append({"setup": setup, "backend": backend, "load_pct": load, "priority": prio,
                         "workers": workers, "ack_diff_median": "3.0", "S_neg": neg,
                         "S_neg_Sk_neg": order, "timed": 1000, "Sk_neg": order,
                         "dack_p99": dack})
    return rows


def k_bins(observed=(0.5, 0.3, 0.2, 0.1, 0.05), predicted=(0.5, 0.3, 0.2, 0.1, 0.05)):
    return [{"setup": "K-kafka-l88-ord", "bin": i + 1, "negatives": 50, "observed": o,
             "predicted": p} for i, (o, p) in enumerate(zip(observed, predicted))]


class TestJudgingK:
    def test_every_prediction_holds(self):
        out = osc.judge_order(order_rows(), k_bins())
        assert {k: out[k]["verdict"] for k in ("K-v", "K-a", "K-b", "K-c", "K-d")} == \
            dict.fromkeys(("K-v", "K-a", "K-b", "K-c", "K-d"), "confirmed")
        decision = out["K-e"]["decision"]
        assert [d["the_lock_sets_it"] for d in decision] == [True, True]

    def test_each_prediction_can_fail(self):
        rows = order_rows()
        for r in rows:
            if r["backend"] == "kafka":
                r["S_neg_Sk_neg"] = 20
            if r["backend"] == "redis" and r["priority"] and not r["workers"]:
                r["S_neg_Sk_neg"] = 2
            r["ack_diff_median"] = "25"
        rows[1]["dack_p99"] = 210.0
        out = osc.judge_order(rows, k_bins(observed=(0.5, 0.6, 0.2, 0.1, 0.05)))
        assert all(out[k]["verdict"] == "not confirmed"
                   for k in ("K-v", "K-a", "K-b", "K-c", "K-d"))
        out = osc.judge_order(rows, k_bins(predicted=(0.1, 0.3, 0.2, 0.1, 0.05)))
        assert out["K-d"]["checks"][0]["within"] is False
        out = osc.judge_order(rows, k_bins(predicted=(0.0, 0.3, 0.2, 0.1, 0.05)))
        assert out["K-d"]["checks"][0]["within"] is False

    def test_missing_setups_and_values_decide_nothing(self):
        out = osc.judge_order([{"setup": "K-kafka-l0-ord", "backend": "kafka", "load_pct": 0,
                                "priority": False, "workers": "", "ack_diff_median": "",
                                "S_neg": 3, "S_neg_Sk_neg": 0, "timed": 0, "Sk_neg": 0,
                                "dack_p99": ""}], [])
        assert out["K-v"]["verdict"] == "not confirmed" and out["K-a"]["checks"] == []
        assert out["K-a"]["verdict"] == "not confirmed", "a prediction with nothing to judge"
        assert out["K-e"]["decision"][0]["the_lock_sets_it"] is None


class TestJudgingTheOthers:
    def test_run_to_parity(self):
        rows = [{"backend": b, "sched_features": f, "S_neg": n, "timed": 1000, "dack_p99": p}
                for b in ("kafka", "redis") for f, n, p in (("", 90, 2000.0),
                                                          ("NO_RUN_TO_PARITY", 30, 600.0))]
        out = osc.judge_parity(rows, [])
        assert out["R-a"]["verdict"] == out["R-b"]["verdict"] == "confirmed"
        rows[1]["S_neg"], rows[1]["dack_p99"] = 80, 1900.0
        out = osc.judge_parity(rows, [])
        assert out["R-a"]["verdict"] == out["R-b"]["verdict"] == "not confirmed"
        assert osc.judge_parity([], [])["R-a"]["checks"][0]["holds"] is False

    def test_the_positive_control(self):
        rows = [{"backend": b, "delay_ms": d, "Wso_median": 800.0 + 1000.0 * d,
                 "D_median": 1500.0 + 1000.0 * d, "A_median": 700.0 + 10.0 * d}
                for b in ("kafka", "redis") for d in (0, 1, 2)]
        out = osc.judge_control(rows, [])
        assert {k: out[k]["verdict"] for k in ("P-a", "P-b", "P-c")} == \
            dict.fromkeys(("P-a", "P-b", "P-c"), "confirmed")
        for r in rows:
            r["Wso_median"] = 800.0 + 500.0 * r["delay_ms"]
            r["A_median"] = 700.0 + 200.0 * r["delay_ms"]
        out = osc.judge_control(rows, [])
        assert out["P-a"]["verdict"] == out["P-b"]["verdict"] == "not confirmed"
        assert osc._slope([(1.0, 2.0)]) is None
        out = osc.judge_control([{"backend": "kafka", "delay_ms": 0, "Wso_median": "",
                                  "D_median": "", "A_median": ""}], [])
        assert out["P-a"]["checks"][0]["holds"] is False
        assert out["P-b"]["checks"][0]["move"] is None

    def test_the_ladder(self):
        rows = []
        for rate in (50, 500):
            for b in ("kafka", "redis"):
                for load, w in ((0, 800.0), (88, 820.0)):
                    rows.append({"setup": "L%d-%s-l%d" % (rate, b, load), "rate": rate,
                                 "backend": b, "load_pct": load, "Dif_median": "3",
                                 "Wso_median": w, "flagged": 0, "flag_known": 100,
                                 "reads": 100, "reads_multi": 2, "S_neg": 1, "S_count": 100,
                                 "Wso_flagged_median": "", "Wso_unflagged_median": w})
        out = osc.judge_ladder(rows, [])
        assert {k: out[k]["verdict"] for k in ("L-a", "L-b", "L-c")} == \
            dict.fromkeys(("L-a", "L-b", "L-c"), "confirmed")
        assert out["L-b"]["holds_at_rates"] == [50, 500]
        rows[-1]["Wso_median"] = 1200.0
        rows[0]["flagged"], rows[0]["Dif_median"] = 50, "40"
        out = osc.judge_ladder(rows, [])
        assert out["L-b"]["holds_at_rates"] == [50]
        assert out["L-a"]["verdict"] == out["L-c"]["verdict"] == "not confirmed"

    def test_idle_processors(self):
        rows = [{"backend": b, "idle_poll": p, "bump": bump, "S_neg": 100, "dack_median": d,
                 "dack_waited": 5, "timed": 1000}
                for b in ("kafka", "redis") for p, bump, d in ((False, 40, 200.0),
                                                              (True, 10, 120.0))]
        out = osc.judge_idle(rows, [])
        assert out["I"]["decision"]["the_mode_is_idle_wake"] is True
        assert osc.judge_idle([], [])["I"]["decision"]["the_mode_is_idle_wake"] is None


class TestFilesAndTheCommandLine:
    def test_read_and_judge_a_block_from_the_command_line(self, tmp_path, capsys):
        folder = str(tmp_path / "runs")
        os.makedirs(folder)
        for i in range(2):
            make_run(folder, "law_k_r00%d-K-kafka-l88-ord-a1" % i, "K-kafka-l88-ord",
                     {"backend": "kafka", "load_pct": 88}, [msg(), msg(
                         pub=10000, tx=10100, rx_ack=10600, ack=12500, req=10050, rx=10900,
                         recv=11000)])
        make_run(folder, "law_k_r009-K-kafka-l0-ord-a1", "K-kafka-l0-ord",
                 {"backend": "kafka", "load_pct": 0}, [msg()], verdict="repeat")
        make_run(folder, "law_k_r010-P-kafka-d0-a1", "P-kafka-d0",
                 {"backend": "kafka", "load_pct": 0, "delay_ms": 0}, [msg()])
        os.makedirs(os.path.join(folder, "not_a_run"))
        with open(os.path.join(folder, "law_file.txt"), "w") as fh:
            fh.write("x")
        table, bins = str(tmp_path / "k.csv"), str(tmp_path / "k_bins.csv")
        assert osc.main(["read", "--block", "K", "--runs", folder, "--driver", DRIVER,
                         "--broker", BROKER, "--receiver", RECEIVER, "--out", table,
                         "--quintiles", bins, "--warmup", "0"]) == 0
        said = capsys.readouterr().out
        assert "left out law_k_r009-K-kafka-l0-ord-a1: repeat" in said
        assert "OK 2 runs of block K" in said
        rows = osc.read_table(table)
        assert len(rows) == 2 and rows[0]["load_pct"] == 88 and rows[0]["priority"] is False
        out = str(tmp_path / "k.json")
        assert osc.main(["judge", "--block", "K", "--table", table, "--quintiles", bins,
                         "--out", out]) == 0
        verdicts = json.load(open(out, encoding="utf-8"))
        assert "K-a" in verdicts and "decision" in verdicts["K-e"]
        assert "K-e: decision recorded" in capsys.readouterr().out
        assert osc.main(["read", "--block", "P", "--runs", folder, "--driver", DRIVER,
                         "--broker", BROKER, "--receiver", RECEIVER, "--out",
                         str(tmp_path / "p.csv")]) == 0
        assert osc.read_table(str(tmp_path / "absent.csv")) == []
        assert osc.read_table(None) == []

    def test_a_pilot_never_joins_a_judged_block_and_its_rung_is_read_from_its_id(self):
        """Block L's prefix is a single letter, so its rung after it is what separates its runs
        from its pilot's (LP50-...), which share a folder only by mistake."""
        assert osc.in_block("L500-kafka-l0", "L") and not osc.in_block("LP500-kafka-l0", "L")
        assert osc.in_block("K-redis-l0-rt", "K") and not osc.in_block("KP-redis-l0-rt", "K")
        assert not osc.in_block("RP-kafka-run_to_parity", "R")
        assert not osc.in_block("IP-redis-poll", "I") and osc.in_block("I-redis-poll", "I")
        assert not osc.in_block("L-kafka", "L") and not osc.in_block("", "L")
        assert osc.rate_of("L5000-redis-l88") == 5000 and osc.rate_of("LP50-kafka-l0") == 50
        assert osc.rate_of("K-kafka-l0-ord") is None and osc.rate_of("LP-kafka") is None

    def test_a_run_without_its_setup_reads_as_none(self, tmp_path):
        run = str(tmp_path / "law_x")
        os.makedirs(run)
        assert osc.setup_of(run) == ("", {})
