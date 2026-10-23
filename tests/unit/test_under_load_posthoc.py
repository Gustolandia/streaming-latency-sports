"""Tests for scripts/under_load_posthoc.py, block U read again after its verdicts as the general
method reads any run: the check against the broker's own record, the three latencies, the floors
and the rise, every verdict with a run left out, and the census of stalls. The runs are built by
test_under_load's own builder, file by file in the shape the kit writes them, so that this reader
and block U's are read over the same world.

That world, in microseconds on the driver's clock: four messages and four fetches. Message 1's
delivering request left 600 us after the producer had its acknowledgment, so it surely found no
request waiting, and the broker agrees (F_in 800 us after A_out). Messages 0 and 3 found one
waiting, and message 2's request came in while the broker held it. Every pair of crossings is
200 us. The least acknowledgment round trip is 400 us and the least W_so 800 us; the only request
that cannot have waited is fetch 2, whose answer carried message 1, a round trip of 900 us. So
C_hat before any allowance is 500 us, 300 us over the true 200."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import so_journal as sj  # noqa: E402
import test_under_load as tul  # noqa: E402
import under_load as ul  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

DRIVER, BROKER, RECEIVER = tul.DRIVER, tul.BROKER, tul.RECEIVER
US = 1000


@pytest.fixture(autouse=True)
def a_small_world(monkeypatch):
    """The world here carries four messages, and the triangle's least values each need
    TRIANGLE_MIN values, so the tests ask for one; TestTheLeastCount puts the rule back."""
    monkeypatch.setattr(ph, "TRIANGLE_MIN", 1)


def sockets(**allowance):
    return {"sockets": allowance}


def part(pair=(1, 2), W=1000.0, slack=-100.0, ack_rtt=400.0, C=200.0, Tc=300.0, Fb=900.0,
         stored=0.0, **more):
    out = {"pair": pair, "W": W, "slack": slack, "ack_rtt": ack_rtt, "C": C, "Tc": Tc, "Fb": Fb,
           "stored": stored}
    out.update(more)
    return out


class TestSmallPieces:
    def test_percentiles_shares_and_least_values(self):
        assert ph._p([], 50) is None and ph._p([1.0, 3.0], 50) == 2.0
        assert ph._share(1, 0) is None and ph._share(1, 4) == 0.25
        assert ph._min_by([(None, 1.0), ("a", None), ("a", 5.0), ("a", 3.0), ("b", 9.0)]) == {
            "a": 3.0, "b": 9.0}
        assert ph._min_by([("a", 5.0), ("a", 3.0), ("b", 9.0)], 2) == {"a": 3.0}

    def test_what_the_broker_says_each_message_found(self):
        us = 1000
        assert ph.found(None) is None and ph.found([1, None, 3, 4]) is None
        assert ph.found([100 * us, 200 * us, 260 * us, 0]) == "none"
        assert ph.found([100 * us, 200 * us, 250 * us, 0]) == "close", "within the resolution"
        assert ph.found([100 * us, 200 * us, 100 * us, 0]) == "waiting"
        assert ph.found([100 * us, 200 * us, 150 * us, 0]) == "close"

    def test_the_three_readings(self):
        p = part(slack=-100.0)
        assert ph.readings(p, None, None) == {"certain": False, "raw": None, "calibrated": None}
        assert ph.readings(p, 200.0, None) == {"certain": False, "raw": True, "calibrated": None}
        assert ph.readings(p, 200.0, 60.0) == {"certain": False, "raw": True,
                                               "calibrated": False}
        assert ph.readings(p, 150.0, None)["raw"] is False, "50 us is within the resolution"
        assert ph.readings(part(slack=60.0), 0.0, 0.0)["certain"] is True
        assert ph.readings(part(slack=50.0), None, None)["certain"] is False, (
            "a request sent 50 us after the acknowledgment arrived is within the resolution")

    def test_a_ready_receivers_latencies(self):
        p = part(W=1000.0, slack=-100.0, Tc=300.0, Fb=900.0, stored=None)
        ph.ready_latencies(p, 250.0)
        assert p["s_tri"] == 150.0 and p["E2c"] == 850.0 and p["E3c"] == 850.0
        assert p["E2b"] == 900.0 and p["E3b"] is None
        p = part(W=1000.0, slack=500.0, Tc=300.0, stored=600.0)
        ph.ready_latencies(p, -400.0)
        assert p["s_tri"] == 300.0 and p["E2c"] == 700.0 and p["E3c"] == 500.0
        assert p["E3b"] == 400.0, "a negative estimate lifts nothing"

    def test_the_census(self):
        quick = [{"W": 900.0, "pub": 5}]
        assert ph.census(quick, 0) == {"stall_n": 0, "stall_from_s": None, "stall_to_s": None,
                                       "stall_max_ms": None}
        slow = [{"W": 60000.0, "pub": 3 * 10**9}, {"W": 150000.0, "pub": 2 * 10**9},
                {"W": 10.0, "pub": 10**9}]
        assert ph.census(slow, None)["stall_n"] == 2
        assert ph.census(slow, 0) == {"stall_n": 2, "stall_from_s": 2.0, "stall_to_s": 3.0,
                                      "stall_max_ms": 150.0}


class TestTheCrossings:
    def test_c_hat_per_pair_and_the_least_c(self):
        parts = [part(pair=(1, 2), W=900.0, ack_rtt=450.0, C=260.0),
                 part(pair=(1, 2), W=800.0, ack_rtt=500.0, C=240.0),
                 part(pair=(1, 3), W=700.0, ack_rtt=480.0, C=None),
                 part(pair=(None, 2), W=100.0, ack_rtt=10.0, C=5.0)]
        raw, true = ph.crossing_floors(parts, {2: 300.0})
        assert raw == {(1, 2): 450.0 + 300.0 - 800.0}, "pair (1, 3) has no fetch round trip"
        assert true == {(1, 2): 240.0, (None, 2): 5.0}

    def test_the_floor_takes_only_requests_that_cannot_have_waited(self):
        # Fetch 7's answer carried a message stored before it left, and request 8 asks for no
        # messages: both count. Fetch 9 was quicker, but nothing shows it did not wait, and
        # fetch 10's send carried no transmit timestamp.
        requests = [tul.kafka_request(1, 7), tul.kafka_request(8, 8), tul.kafka_request(1, 9),
                    tul.kafka_request(1, 10)]
        answers = [tul.kafka_response(7, tul.eid(1).encode()), tul.kafka_response(8, b"ok"),
                   tul.kafka_response(9, tul.eid(2).encode()),
                   tul.kafka_response(10, tul.eid(3).encode())]
        sent = [(end - 1, ns) for (end, ns) in tul.chunks_at(requests[:3], [1000, 1500, 3000])]
        reads = [(end, len(a), ns) for (end, ns), a in
                 zip(tul.chunks_at(answers, [2000, 2600, 3100, 9000]), answers)]
        conn = sj.Conn(0, 40002, BROKER, 9092, b"".join(requests), b"".join(answers), reads,
                       sent)
        stored_first = {tul.eid(1), tul.eid(3)}
        assert ph.request_floors({"0": conn}, "kafka", stored_first) == {40002: 1.0}
        assert ph.request_floors({"0": conn}, "kafka", set()) == {40002: 1.1}


class TestOneRun:
    @pytest.mark.parametrize("backend, ready, wf_p99", [("kafka", "E2", 485.0),
                                                        ("redis", "E3", 776.0)])
    def test_the_check_and_the_three_latencies(self, tmp_path, backend, ready, wf_p99):
        run = tul.make_run(str(tmp_path), "law_x", "U2000-%s-l80" % backend,
                           tul.params(backend, 80))
        row, split = ph.read_run(run, DRIVER, BROKER, RECEIVER, sockets(**{backend: 0.0}),
                                 warmup_s=0)
        assert (row["rate"], row["backend"], row["load_pct"], row["priority"]) == (
            2000, backend, 80, False)
        assert row["timed"] == 4 and row["pairs"] == 1 and row["allowance_us"] == 0.0
        assert row["overshoot_max_us"] == pytest.approx(300.0), "C_hat 500 against C 200"
        assert row["broker_found"] == 4 and row["broker_none_share"] == 0.25
        assert row["broker_waiting_share"] == 0.5 and row["broker_close_share"] == 0.25
        assert row["broker_none0_share"] == 0.25
        assert row["certain_n"] == 4 and row["certain_none_share"] == 0.25
        assert row["certain_agree"] == 1.0 and row["certain_false_none"] == 0
        # C_hat 300 us too high calls message 2, which came 100 us before its acknowledgment
        # left the broker, unwaited.
        for reading in ("raw", "calibrated"):
            assert row[reading + "_none_share"] == 0.5 and row[reading + "_agree"] == 0.75
            assert row[reading + "_false_none"] == 1 and row[reading + "_missed_none"] == 0
        assert row["wait_err_raw_p50"] == pytest.approx(100.0)
        assert row["wait_err_raw_p99"] == pytest.approx(200.0 + 0.97 * 100.0)
        assert row["W_p50"] == pytest.approx(1100.0) and row["D_p50"] == pytest.approx(1375.0)
        assert row["E2b_p50"] == pytest.approx(1100.0) and row["E3b_p50"] == pytest.approx(1050.0)
        assert row["E2c_p50"] == pytest.approx(1000.0) and row["E3c_p50"] == pytest.approx(900.0)
        assert row["Fb_p50"] == row[ready + "b_p50"] and row["Fc_p99"] == row[ready + "c_p99"]
        assert row["WF_p50"] == 0 and row["WF_p99"] == pytest.approx(wf_p99)
        assert row["DW_p50"] == pytest.approx(200.0)
        assert row["Wfloor_p99"] == pytest.approx(1020.0 + 0.97 * 700.0), "floor 180"
        assert row["tri_over_share"] == 0.25 and row["tri_over_max_us"] == pytest.approx(200.0)
        assert row["gap_smin_p50"] == 0 and row["gap_tri_p50"] == 0
        assert row["stall_n"] == 0 and row["stall_max_ms"] is None and row["pooled"]
        assert len(split) == 4 and all(len(s) == len(ul.SPLIT_FIELDS) + 1 for s in split)

    def test_against_block_us_own_reading_of_the_same_run(self, tmp_path):
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l80", tul.params("kafka", 80))
        mine, my_split = ph.read_run(run, DRIVER, BROKER, RECEIVER, None, warmup_s=0)
        theirs, their_split = ul.read_run(run, DRIVER, BROKER, RECEIVER, warmup_s=0)
        for field in ("W_p50", "W_p99", "D_p50", "D_p99", "Fb_p50", "Fb_p99"):
            assert mine[field] == pytest.approx(theirs[field]), field
        assert sorted(my_split, key=str) == sorted(their_split, key=str)
        assert mine["allowance_us"] is None and mine["calibrated_n"] == 0
        assert mine["calibrated_none_share"] is None and mine["calibrated_agree"] is None
        # The world's captures carry no frames a broker writes, so the captures' check finds
        # nothing to time; it is read below from client_wire's own rows.
        assert mine["cap_timed"] == 0 and mine["cap_pairs"] == 0
        assert mine["cap_allowance_us"] is None

    def test_without_the_brokers_capture_nothing_is_checked(self, tmp_path):
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params(),
                           broker=False, clients=False)
        row, split = ph.read_run(run, DRIVER, BROKER, RECEIVER, sockets(kafka=0.0), warmup_s=0)
        assert "cap_timed" not in row, "without the client captures there is nothing to read"
        assert row["broker_found"] == 0 and row["broker_none_share"] is None
        assert row["certain_none_share"] == 0.25 and row["certain_agree"] is None
        assert row["overshoot_max_us"] is None and row["pairs"] == 1
        assert row["tri_over_share"] is None and row["tri_over_max_us"] is None
        assert row["E3b_p50"] is None and row["WF_p50"] is None and row["Wfloor_p99"] is None
        assert split == [] and not row["pooled"]

    def test_messages_the_journal_cannot_time_are_left_out(self, tmp_path):
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params(),
                           unjournaled=True, ack_missing=True)
        row, _ = ph.read_run(run, DRIVER, BROKER, RECEIVER, None, warmup_s=0)
        assert row["timed"] == 3

    def test_an_estimate_too_generous_is_caught_by_the_broker(self, tmp_path):
        # An allowance of 100 us leaves C_hat at 400 us, twice the true 200. Message 2's request
        # left 300 us before its acknowledgment arrived, so the estimate calls it unwaited, which
        # the broker does not, and puts 100 us of the thread's time on it, which the broker's own
        # bound (0) does not allow. Message 1's bound stays at its whole turnaround, 500 us.
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params())
        row, _ = ph.read_run(run, DRIVER, BROKER, RECEIVER, sockets(kafka=100.0), warmup_s=0)
        assert row["calibrated_none_share"] == 0.5 and row["calibrated_false_none"] == 1
        assert row["calibrated_missed_none"] == 0 and row["calibrated_agree"] == 0.75
        assert row["certain_false_none"] == 0 and row["raw_false_none"] == 1
        assert row["tri_over_share"] == 0.25 and row["tri_over_max_us"] == pytest.approx(100.0)
        assert row["gap_tri_p50"] == 0 and row["E3c_p50"] == pytest.approx(950.0)

    def test_a_run_with_no_message_that_arrived(self, tmp_path):
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params())
        with open(os.path.join(run, "consumer_events.csv"), "w", encoding="utf-8") as fh:
            fh.write("event_id,t_consume_ns\n")
        row, split = ph.read_run(run, DRIVER, BROKER, RECEIVER, None, warmup_s=0)
        assert row["timed"] == 0 and split == [] and "cap_timed" not in row
        assert row["stall_n"] == 0 and row["certain_none_share"] is None

    def test_a_stall_and_a_broker_without_a_ready_receiver(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ph, "STALL_US", 1500.0)
        monkeypatch.setattr(ph, "READY", {})
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params())
        row, _ = ph.read_run(run, DRIVER, BROKER, RECEIVER, None, warmup_s=0)
        assert row["stall_n"] == 1 and row["stall_max_ms"] == pytest.approx(1.9)
        assert row["stall_from_s"] == row["stall_to_s"] == pytest.approx(650e-6)
        assert row["Fb_p50"] is None and row["Fc_p99"] is None and row["WF_p50"] is None


class TestDecisionsWithARunLeftOut:
    def test_a_naming_that_rests_on_one_run(self):
        def split(base, wait):
            # G is the handling (base + i) and the wait; the excess, the ack and Q are zero.
            return [(base + i + wait, 0.0, base + i, 0.0, wait, 0.0, 180.0,
                     base + i + wait + 180.0, None) for i in range(3)]
        splits = {("U2000-kafka-l0", "a"): split(100.0, 0.0),
                  ("U2000-kafka-l0", "b"): split(103.0, 0.0),
                  ("U2000-kafka-l70", "c"): split(100.0, 0.0),
                  ("U2000-kafka-l70", "d"): split(100.0, 4900.0),
                  ("U2000-kafka-l70-rt", "e"): split(1.0, 0.0)}
        full, without = ph.decisions_without(splits, "U2000-kafka-l0", "U2000-kafka-l70", "tail")
        # Idle, the top 1% is G = 105; loaded, G = 5,002 of which 4,900 is the wait.
        assert full == ("wait", 4897.0)
        assert dict(without) == {"a": ("wait", 4897.0), "b": ("wait", 4900.0),
                                 "c": ("wait", 4897.0), "d": (None, -3.0)}
        assert [run for run, _ in without] == ["a", "b", "c", "d"], "run e is another setup's"


class TestTheBlock:
    def test_cells_read_and_decided(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ul, "BLOCK_GUARD_S", 1e-4)
        folder = str(tmp_path)
        tul.make_run(folder, "law_a", "U2000-kafka-l0", tul.params())
        tul.make_run(folder, "law_b", "U2000-kafka-l70", tul.params(load=70))
        tul.make_run(folder, "law_c", "U2000-kafka-l70", tul.params(load=70), card_misses=(2,))
        tul.make_run(folder, "law_d", "U2000-kafka-l70-rt", tul.params(load=70, rt=True))
        tul.make_run(folder, "law_e", "U2000-redis-l70", tul.params("redis", 70))
        tul.make_run(folder, "law_f", "U50-kafka-l88-blocks", tul.params(load=88), extras={
            "load_blocks.csv": tul.blocks_csv([(0, "on"), (1500, "off"), (3000, "on")])})
        tul.make_run(folder, "law_g", "U50-redis-l0", tul.params("redis"))
        tul.make_run(folder, "law_h", "UP2000-kafka-l0", tul.params())
        rows, decided = ph.read_block([folder], DRIVER, BROKER, RECEIVER, sockets(kafka=0.0),
                                      warmup_s=0)
        assert sorted(r["run"] for r in rows) == ["law_%s" % c for c in "abcdefg"]
        assert sorted(decided) == [(50, "kafka"), (2000, "kafka")], (
            "Redis at 2,000 has no idle setup, and at 50 no blocks")
        full, without = decided[(2000, "kafka")]
        assert [run for run, _ in without] == ["law_a", "law_b"], "law_c is not pooled"
        assert [run for run, _ in decided[(50, "kafka")][1]] == ["law_f"]
        rows, _ = ph.read_block([folder], DRIVER, BROKER, RECEIVER, None, warmup_s=0,
                                pilot=True)
        assert [r["run"] for r in rows] == ["law_h"]

    def test_the_allowance_from_a_pilot(self):
        rows = [{"backend": "kafka", "overshoot_max_us": 31.2, "cap_overshoot_max_us": 40.1},
                {"backend": "kafka", "overshoot_max_us": 12.0},
                {"backend": "kafka", "overshoot_max_us": None, "cap_overshoot_max_us": None},
                {"backend": "redis", "overshoot_max_us": -40.0},
                {"backend": "redis", "overshoot_max_us": -60.0}]
        assert ph.calibrate(rows) == {"sockets": {"kafka": 35.0, "redis": 0.0},
                                      "capture": {"kafka": 45.0}}
        assert ph.calibrate([]) == {"sockets": {}, "capture": {}}


def judged(w_rt=(2000.0, 2000.0), **kw):
    rows = tul.block(**kw)
    for r in rows:
        r["run"] = "%s-%s" % (r["setup"], id(r))
    rt = [r for r in rows if r["rate"] == 500 and r["backend"] == "kafka" and r["priority"]]
    for r, w in zip(rt, w_rt):
        r["W_p99"] = str(w)
    return rows


class TestTheVerdictsAgain:
    def test_floored_and_on_the_rise(self):
        rows = []
        for (load, rt), (w, wf) in (((0, False), (1700.0, 1000.0)),
                                    ((80, False), (6000.0, 5000.0)),
                                    ((80, True), (2000.0, 1100.0))):
            rows.append({"rate": 500, "backend": "kafka", "load_pct": load, "priority": rt,
                         "W_p99": w, "Wfloor_p99": wf})
        rows.append({"rate": 2000, "backend": "redis", "load_pct": 0, "priority": False,
                     "W_p99": 5000.0, "Wfloor_p99": 5000.0})
        rows.append({"rate": 2000, "backend": "redis", "load_pct": 80, "priority": False,
                     "W_p99": 4000.0, "Wfloor_p99": 4000.0})
        rows.append({"rate": 2000, "backend": "redis", "load_pct": 80, "priority": True,
                     "W_p99": 3000.0, "Wfloor_p99": None})
        out = {(e["rate"], e["backend"]): e for e in ph.floored(rows)}
        k = out[(500, "kafka")]
        assert k["raw_growth"] == pytest.approx(6000 / 1700.0)
        assert k["raw_rise_taken"] == pytest.approx(4000 / 4300.0)
        assert k["floored_rt_ratio"] == pytest.approx(0.22)
        assert k["floored_rise_taken"] == pytest.approx(3900 / 4000.0)
        r = out[(2000, "redis")]
        assert r["raw_rise_taken"] is None, "nothing rose"
        assert r["raw_rt_ratio"] == 0.75 and r["raw_growth"] == 0.8
        assert r["floored_growth"] is None and out[(500, "redis")]["raw_growth"] is None

    def test_a_verdict_that_rests_on_one_run(self):
        steady = judged()
        flips, changed = ph.leave_one_out(steady, draws=20)
        assert [f for f in flips if f[0] == "U-d"] == [] and changed == []
        # Kafka at 500 holds U-d at a ratio of exactly one half, by the median of two runs; left
        # without its lower run, it fails.
        edge = judged(w_rt=(2000.0, 4000.0), w=(1700.0, 6000.0, 3000.0))
        flips, changed = ph.leave_one_out(edge, draws=20)
        lower = [r["run"] for r in edge if r["W_p99"] == "2000.0"][0]
        assert ("U-d", 500, "kafka", lower, True, False) in flips
        assert (lower, "U-d", "confirmed", "not confirmed") in changed

    def test_each_setups_medians(self):
        rows = [{"setup": "U2000-kafka-l0", "W_p99": 1.0, "broker_none_share": 0.2},
                {"setup": "U2000-kafka-l0", "W_p99": 3.0, "broker_none_share": None},
                {"setup": "U2000-redis-l0", "W_p99": 5.0}]
        out = ph.by_setup(rows)
        assert out[0]["runs"] == 2 and out[0]["W_p99"] == 2.0
        assert out[0]["broker_none_share"] == 0.2 and out[1]["D_p50"] is None


class TestTheCommandLine:
    def test_calibrate_then_read(self, tmp_path, capsys):
        pilot = str(tmp_path / "pilot")
        os.makedirs(pilot)
        tul.make_run(pilot, "law_p", "UP2000-kafka-l0", tul.params())
        allowance = str(tmp_path / "allowance.json")
        assert ph.main(["calibrate", "--runs", pilot, "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--warmup", "0", "--out", allowance]) == 0
        with open(allowance, encoding="utf-8") as fh:
            assert json.load(fh) == {"sockets": {"kafka": 300.0}, "capture": {}}
        assert "from 1 pilot runs" in capsys.readouterr().out
        runs = str(tmp_path / "runs")
        os.makedirs(runs)
        tul.make_run(runs, "law_a", "U2000-kafka-l0", tul.params())
        tul.make_run(runs, "law_b", "U2000-kafka-l70", tul.params(load=70))
        table = str(tmp_path / "u_runs.csv")
        rows, tails, _, _ = ul.read_block([runs], DRIVER, BROKER, RECEIVER, warmup_s=0)
        ul.osc.write_csv(table, rows)
        out_runs, out = str(tmp_path / "posthoc_runs.csv"), str(tmp_path / "posthoc.json")
        assert ph.main(["read", "--runs", runs, "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--warmup", "0", "--allowance", allowance,
                        "--judged-runs", table, "--out-runs", out_runs, "--out", out,
                        "--draws", "10"]) == 0
        assert "OK 2 runs read again, post hoc" in capsys.readouterr().out
        with open(out, encoding="utf-8") as fh:
            found = json.load(fh)
        assert found["post_hoc"] is True and len(found["setups"]) == 2
        assert found["check_totals"]["certain"] == {"n": 8, "false_none": 0, "missed_none": 0}
        assert found["check_totals"]["calibrated"] == {"n": 8, "false_none": 0, "missed_none": 0}
        assert found["tri_valid"] == {"runs": 2, "over_b_min_share_max": 0.0,
                                      "over_b_min_max_us": 0.0}
        assert found["stalls"] == [] and "2000 kafka" in found["decisions_without_a_run"]
        # Two runs, one idle and one loaded, both the same world: U-a and U-b fail their cell,
        # and with either run left out the cell is out of reach.
        cells = found["leave_one_out"]["cells"]
        assert cells == [["U-a", 2000, "kafka", "law_a", False, None],
                         ["U-b", 2000, "kafka", "law_a", False, None],
                         ["U-a", 2000, "kafka", "law_b", False, None],
                         ["U-b", 2000, "kafka", "law_b", False, None]]
        assert ["law_a", "U-a", "not confirmed", "out of reach"] in found["leave_one_out"][
            "verdicts"]


def wire_rows():
    """client_wire's rows for one pair, in microseconds: message e0's request was waiting, e1's
    left 600 us after its acknowledgment came in, and e2 the broker's capture missed. Four more
    are left out: e3 has no acknowledgment, e4 was sent in the warm-up, e5's request the capture
    did not time, and e6 came in answer to a request the rows do not hold. Of the requests, only
    fetch 2 (it carried e1) and the commit cannot have waited: fetch 1, quicker, might have."""
    def msg(eid, depart, ack, arrive, exchange):
        return {"eid_got": eid, "t_depart": depart * US,
                "t_ack": None if ack is None else ack * US, "t_arrive": arrive * US,
                "producer_port": 1, "consumer_port": 2, "exchange": exchange}

    def ex(index, kind, req, ans):
        return {"consumer_port": 2, "exchange": index, "kind": kind,
                "t_req": None if req is None else req * US, "t_ans": ans * US}
    messages = [msg("e0", 1000, 1500, 1700, 1), msg("e1", 3000, 3400, 5000, 2),
                msg("e2", 4500, 4900, 5000, 2), msg("e3", 6000, None, 7000, 3),
                msg("e4", 10, 20, 30, 1), msg("e5", 8000, 8400, 9000, 4),
                msg("e6", 8000, 8400, 9000, 9)]
    exchanges = [ex(0, "Fetch", 100, 300), ex(1, "Fetch", 900, 1700), ex(2, "Fetch", 4000, 5000),
                 ex(3, "Fetch", 6500, 7000), ex(4, "Fetch", None, 9000),
                 ex(5, "OffsetCommit", 9500, 10700)]
    at_broker = {"e0": [1100 * US, 1400 * US, 1000 * US, 1900 * US],
                 "e1": [3100 * US, 3300 * US, 4100 * US, 4900 * US]}
    return messages, exchanges, at_broker


class TestTheCapturesCheck:
    def test_the_check_from_the_captures_alone(self):
        # C_hat = 400 (e1's and e2's acknowledgment) + 1,000 (fetch 2) - 500 (e2's W) = 900 us,
        # 700 us over the true 200.
        messages, exchanges, at_broker = wire_rows()
        row = ph.capture_check(messages, exchanges, at_broker, 500 * US, 650.0)
        assert row["cap_timed"] == 3 and row["cap_pairs"] == 1
        assert row["cap_overshoot_max_us"] == pytest.approx(700.0)
        assert row["cap_certain_n"] == 3
        assert row["cap_certain_none_share"] == pytest.approx(1 / 3.0)
        assert row["cap_certain_agree"] == 1.0 and row["cap_certain_false_none"] == 0
        assert row["cap_raw_none_share"] == pytest.approx(2 / 3.0) and row["cap_raw_agree"] == 0.5
        assert row["cap_raw_false_none"] == 1 and row["cap_raw_missed_none"] == 0
        assert row["cap_calibrated_none_share"] == pytest.approx(1 / 3.0)
        assert row["cap_calibrated_agree"] == 1.0 and row["cap_calibrated_false_none"] == 0
        assert row["cap_wait_err_raw_p50"] == pytest.approx(500.0)
        assert row["cap_wait_err_raw_p99"] == pytest.approx(300.0 + 0.99 * 400.0)
        assert ph.capture_check(messages, exchanges, at_broker, 500 * US)[
            "cap_calibrated_n"] == 0, "no allowance, no calibrated reading"

    def test_each_least_value_needs_its_count(self, monkeypatch):
        messages, exchanges, at_broker = wire_rows()
        monkeypatch.setattr(ph, "TRIANGLE_MIN", 2)
        assert ph.capture_check(messages, exchanges, at_broker, 500 * US)["cap_pairs"] == 1
        monkeypatch.setattr(ph, "TRIANGLE_MIN", 4)
        row = ph.capture_check(messages, exchanges, at_broker, 500 * US)
        assert row["cap_pairs"] == 0 and row["cap_raw_n"] == 0 and row["cap_certain_n"] == 3


class TestTheLeastCount:
    def test_the_rule_is_the_path_floors_own(self, tmp_path, monkeypatch):
        monkeypatch.undo()
        assert ph.TRIANGLE_MIN == ul.FLOOR_MIN == 100
        run = tul.make_run(str(tmp_path), "law_x", "U2000-kafka-l0", tul.params())
        row, _ = ph.read_run(run, DRIVER, BROKER, RECEIVER, sockets(kafka=0.0), warmup_s=0)
        assert row["pairs"] == 0 and row["raw_n"] == 0 and row["calibrated_n"] == 0
        assert row["certain_n"] == 4, (
            "four messages give no least value; the certain reading stands")
