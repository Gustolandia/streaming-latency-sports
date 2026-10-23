"""Tests for scripts/general_method.py, freeze 44's reader and judge (plan version 47), against runs
built by test_client_wire_brokers.World packet by packet in the shape the kit writes them, every
broker's frames as its server writes them, and against run rows built here for the judge.

The Redis world read in most of these tests, in microseconds on the client hosts' clock: six
messages, three sent in the load's on-block and three in its off-block, each a second clear of the
switch. Each crossing takes 100 us, so the broker's record says a message found none where its
request left more than 150 us after its acknowledgment came back (messages 1, 2 and 5), and that
it found one waiting where its request left before the message did (0, 3 and 4). The certain
reading sees only message 1, whose request left 300 us after the acknowledgment; the estimate,
with C_hat = 400 + 580 - 800 = 180 us, sees all three. In each state the top 1% of W is one
message: message 1 (W 1,500 us) when the load was on, message 5 (W 1,000 us) when it was off."""
import csv
import json
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import general_method as gm  # noqa: E402
import test_client_wire_brokers as tb  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

DRIVER, BROKER, RECEIVER = tb.DRIVER, tb.BROKER, tb.RECEIVER
US = 1000
ALLOWANCE = {"capture": {"redis": 10.0, "kafka": 10.0, "nats": 10.0, "rabbitmq": 10.0},
             "sockets": {"redis": 15.0}}

SWITCHES = [(-1000000, "on"), (2000000, "off")]
SENDS = [(100000, 100400), (200000, 200400), (300000, 300400), (3100000, 3100400),
         (3200000, 3200400), (3300000, 3300400)]
#: The first request is answered empty, so the first message's has a turnaround.
ASKS = [(50000, 98000, []), (99000, 101000, [0]), (200700, 201500, [1]), (300380, 301200, [2]),
        (3099000, 3100800, [3]), (3199500, 3200900, [4]), (3300420, 3301000, [5])]
LAGS = [100.0, 150.0, 200.0, 50.0, 60.0, 70.0]
W = [1000.0, 1500.0, 1200.0, 800.0, 900.0, 1000.0]


@pytest.fixture(autouse=True)
def a_small_world(monkeypatch):
    """The worlds carry a few messages, and each of the triangle's least values needs
    TRIANGLE_MIN values, so the tests ask for one."""
    monkeypatch.setattr(ph, "TRIANGLE_MIN", 1)


def redis_world(root, name="law_v1", **more):
    options = dict(setup="V2000-redis-d1", params={"consumer": "waiting", "depth": 1,
                                                   "one_reply_reads": True, "load_pct": 70},
                   config="ack_batch=200 depth=1 reads=one-reply", blocks=SWITCHES,
                   journals=True, card=True, counters=True)
    options.update(more)
    return tb.World("redis", SENDS, ASKS, LAGS, **options).write(root, name)


@pytest.fixture(scope="module")
def redis_row(tmp_path_factory):
    ph.TRIANGLE_MIN, saved = 1, ph.TRIANGLE_MIN
    try:
        run = redis_world(tmp_path_factory.mktemp("redis"))
        return gm.read_run(run, DRIVER, BROKER, RECEIVER, ALLOWANCE, warmup_s=0)
    finally:
        ph.TRIANGLE_MIN = saved


# --- the pieces ----------------------------------------------------------------------------------

class TestSmallPieces:
    def test_numbers_shares_ratios_and_flags(self):
        assert gm._p([], 50) is None and gm._p([1.0, 3.0], 50) == 2.0
        assert gm._mean([]) is None and gm._mean([1.0, 2.0]) == 1.5
        assert gm._median([None, 3.0, 1.0]) == 2.0 and gm._median([None]) is None
        assert gm._share(1, 0) is None and gm._share(1, 4) == 0.25
        assert gm._ratio(3.0, 2.0) == 1.5 and gm._ratio(None, 2.0) is None
        assert gm._ratio(1.0, 0.0) is None
        assert gm._int("7") == 7 and gm._int("7.0") == 7 and gm._int("") is None
        assert gm._int(None) is None
        assert [gm._flag(v) for v in (True, 0, "1", "True", "one-reply", "buffered", "0",
                                      None)] == [True, False, True, True, True, False, False,
                                                 False]

    def test_setup_ids(self, tmp_path):
        for setup, expected in (("V2000-redis-d256-lib", ("V", False, 2000)),
                                ("K2000-kafka-rdk-rt-pilot", ("K", True, 2000)),
                                ("A2000-kafka-rdk", ("A", False, 2000)),
                                ("U2000-kafka-l70", (None, False, None))):
            run = tb.new_run(tmp_path, "law_" + setup, "redis", setup)
            got = gm.setup_of(run)
            assert (got[0], got[1], got[2], got[3]) == (setup,) + expected
            assert got[4]["backend"] == "redis"

    def test_the_consumers_config_line(self, tmp_path):
        run = tb.new_run(tmp_path, "law_x", "nats")
        assert gm.client_config(run) == {}
        with open(os.path.join(run, "consumer.log"), "w", encoding="utf-8") as fh:
            fh.write("noise=1\nCONFIG effective depth=256 one_reply_reads=1 storage=memory\n"
                     "CONFIG effective client=python\n")
        assert gm.client_config(run) == {"depth": "256", "one_reply_reads": "1",
                                         "storage": "memory", "client": "python"}

    def test_settings_as_applied_or_as_asked(self, tmp_path):
        run = tb.new_run(tmp_path, "law_x", "nats")
        said = gm.run_settings(run, "nats", {"depth": 1, "consumer": "python"},
                               {"depth": "256", "one_reply_reads": "1", "storage": "memory"})
        assert (said["depth"], said["depth_asked"], said["one_reply"], said["storage"],
                said["consumer"], said["arch"], said["blocks"]) == (256, 1, True, "memory",
                                                                     "python", None, False)
        said = gm.run_settings(run, "redis", {"one_reply_reads": True}, {"reads": "buffered"})
        assert (said["depth"], said["one_reply"], said["consumer"]) == (1, False, "redis-py")
        said = gm.run_settings(run, "kafka", {"fetch_rt": True, "whole_core": True,
                                              "sibling_load": True, "irq_cpus": "core"}, {})
        assert (said["depth"], said["fetch_rt"], said["whole_core"], said["sibling_load"],
                said["irq_cpus"], said["one_reply"]) == (None, True, True, True, "core", False)
        said = gm.run_settings(run, "rabbitmq", {"prefetch": 1000}, {"prefetch": "1",
                                                                     "ack_batch": "1"})
        assert (said["prefetch"], said["ack_batch"], said["consumer"]) == (1, 1, "pika")

    def test_broker_ids_from_any_row(self):
        assert gm.key_of("kafka", {"topic": "t", "partition": "0", "offset": "7"}) == ("t", 0, 7)
        assert gm.key_of("redis", {"stream": "s", "redis_id": "17-3"}) == ("s", 17, 3)
        assert gm.key_of("nats", {"stream": "S", "stream_seq": 9}) == ("S", 9)
        assert gm.key_of("rabbitmq", {"queue": "q", "message_id": "m"}) == ("q", "m")
        assert gm.key_of("rabbitmq", {"stream": "q", "message_id": "m"}) == ("q", "m")
        for backend, row in (("kafka", {"topic": "t"}), ("redis", {"stream": "s",
                                                                   "redis_id": "x"}),
                             ("nats", {"stream": "S", "stream_seq": ""}),
                             ("rabbitmq", {"stream": "q", "message_id": ""})):
            assert gm.key_of(backend, row) is None

    def test_the_consumers_stamps_by_broker_id(self, tmp_path):
        run = tb.new_run(tmp_path, "law_x", "redis")
        with open(os.path.join(run, "consumer_events.csv"), "w", encoding="utf-8") as fh:
            fh.write("stream,redis_id,t_consume_ns\ns,1-1,30\ns,1-1,40\ns,,50\ns,1-2,\n")
        assert gm.consumer_stamps(run, "redis") == {("s", 1, 1): 30}, (
            "the first stamp kept; a row with no id, or no stamp, left out")

    def test_the_first_send(self, tmp_path):
        run = tb.new_run(tmp_path, "law_x", "redis")
        assert gm.first_send(run) is None
        with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
            fh.write("event_id,t_prod_send_ns\na,30\nb,\nc,20\n")
        assert gm.first_send(run) == 20

    def test_the_model(self):
        assert gm.kch_share(None, 5.0) is None and gm.kch_share(2000.0, None) is None
        x = 2000.0 * 250e-6
        assert gm.kch_share(2000.0, 250.0) == pytest.approx(x / (x + math.exp(-x)))
        assert gm.kch_share(2000.0, 0.0) == 0.0


def exchange(port, index, kind, t_req, t_ans):
    return {"consumer_port": port, "exchange": index, "kind": kind, "t_req": t_req,
            "t_ans": t_ans}


class TestTheTurnaround:
    def test_from_the_previous_answer_less_the_other_requests(self):
        rows = [exchange(1, 0, "XREADGROUP", 0, 100), exchange(1, 1, "XACK", 150, 170),
                exchange(1, 2, "XREADGROUP", 300, 400), exchange(1, 3, "XREADGROUP", 350, 500),
                exchange(1, 4, "XREADGROUP", None, 600), exchange(1, 5, "XREADGROUP", 700, None),
                exchange(1, 6, "XREADGROUP", 800, 900), exchange(2, 0, "Fetch", 5, 6)]
        gaps, overlapped = gm.turnarounds(rows)
        assert gaps == {(1, 0): None, (1, 2): (300 - 100 - 20) / 1e3, (1, 3): 0.0,
                        (1, 4): None, (1, 5): 0.1, (1, 6): None, (2, 0): None}
        assert overlapped == 1, "request 3 left before request 2's answer came in"

    def test_the_gap_at_the_broker_and_the_time_no_request_waited(self):
        rows = [exchange(1, 0, "Fetch", 0, 100), exchange(1, 1, "Metadata", 110, 120),
                exchange(1, 2, "Fetch", 300, 400), exchange(1, 3, "Fetch", 380, 450),
                exchange(1, 4, "Fetch", None, 700), exchange(1, 5, "Fetch", 900, 1000),
                exchange(1, 6, "Fetch", 5000, 5100)]
        gaps, share = gm.broker_gaps(rows, 200, 1000)
        assert gaps == {(1, 2): 0.2, (1, 3): 0.0, (1, 5): 0.2}
        assert share == pytest.approx(1.0 - (150 + 100) / 800.0), (
            "fetches held [300, 450] and [900, 1000] of [200, 1000]")
        assert gm.broker_gaps(rows, None, 1000) == ({}, None)
        assert gm.broker_gaps(rows, 500, 500)[1] is None


class TestTheReceivePath:
    def test_the_counters_moved(self, tmp_path):
        run = tb.World("redis", SENDS[:1], ASKS[1:2], counters=True).write(tmp_path)
        assert gm.receive_path(run) == {"softnet_processed": 120, "softnet_dropped": 1,
                                        "softnet_squeezed": 2, "softirq_s": 0.3}

    def test_without_snapshots(self, tmp_path):
        run = tb.new_run(tmp_path, "law_x", "redis")
        assert gm.receive_path(run) == dict.fromkeys(("softnet_processed", "softnet_dropped",
                                                      "softnet_squeezed", "softirq_s"))
        with open(os.path.join(run, "stat_before.txt"), "w", encoding="utf-8") as fh:
            fh.write("intr 5\n")
        with open(os.path.join(run, "stat_after.txt"), "w", encoding="utf-8") as fh:
            fh.write("cpu  1 2 3 4 5 6 7\n")
        assert gm.receive_path(run)["softirq_s"] is None


class TestTheCard:
    def test_q_per_packet_against_the_cards_clock(self, tmp_path):
        run = redis_world(tmp_path)
        lags, window = gm.card_lags(run, BROKER, RECEIVER, 6379)
        assert lags == {40002: [float(tb.World.CARD_LAG)] * len(ASKS)}, "by the receiver's port"
        assert window == tb.World.WINDOW_NS
        assert gm.card_lags(run, BROKER, RECEIVER, 9999) == ({}, window), "another port"

    def test_a_packet_the_card_missed_has_no_q(self, tmp_path):
        world = tb.World("redis", SENDS, ASKS, card=True)
        run = world.write(tmp_path)
        ahead = (tb.World.CARD_AHEAD - tb.World.CARD_LAG) * US
        seen = [(ns + ahead, ip) for ns, ip in world.consumer.client.packets][:-1]
        with open(os.path.join(run, "receiver_hw.pcap"), "wb") as fh:
            fh.write(tb.tcw.pcap_bytes(seen, tb.tcw.ether, 1))
        lags, _ = gm.card_lags(run, BROKER, RECEIVER, 6379)
        assert len(lags[40002]) == len(ASKS) - 1

    def test_no_card_no_q(self, tmp_path):
        run = redis_world(tmp_path, card=False)
        assert gm.card_lags(run, BROKER, RECEIVER, 6379) == (None, None)
        assert gm._packets(os.path.join(run, "none.pcap"), BROKER, RECEIVER, 6379) == {}


def credit(port, t_req, grant, uses=()):
    return {"consumer_port": port, "t_req": t_req, "grant": grant, "uses": list(uses),
            "kind": "XREADGROUP", "t_ans": None}


def part(port, t_depart, t_ack_first):
    return {"message": {"consumer_port": port, "t_depart": t_depart, "t_ack_first": t_ack_first}}


class TestCertainByCounting:
    def test_the_credit_granted_before_less_the_credit_used_after(self):
        """B = 1 us. Message a left at 6,000 ns and its acknowledgment's first byte came at 6,500:
        by 5,000 the requests had granted 3, and by 7,500 their answers had used 1. Message b's
        acknowledgment came at 9,000, by when 2 were used of the 2 granted by 3,000."""
        exchanges = [credit(1, 0, 2, [(3000, 1), (None, 1), (9500, 0)]), credit(1, 5000, 1),
                     credit(1, None, 5), credit(1, 7000, 0, [(8000, 1)])]
        parts = [part(1, 6000, 6500), part(1, 4000, 9000), part(1, 6000, None),
                 part(2, 6000, 6500)]
        assert gm.certified(parts, exchanges, 0.001) == (1, 2), (
            "a message whose acknowledgment's first byte is unknown, or whose connection granted "
            "nothing, is not counted")
        assert gm.certified([], exchanges, 10.0) == (0, 0)

    def test_the_probes_each_broker_has(self):
        rows = [dict(exchange(1, 0, "PING", 100, 310), grant=0),
                dict(exchange(1, 1, gm.cw.PULL, 150, 900), grant=1),
                dict(exchange(1, 2, "basic.consume", 160, 200), grant=1000),
                dict(exchange(1, 3, "PING", 5000, 5100), grant=0),
                dict(exchange(2, 0, "PING", 200, 260), grant=0),
                dict(exchange(1, 4, "PING", 400, None), grant=0),
                dict(exchange(3, 0, "XACK", 300, 340), grant=0)]
        assert gm.probes("nats", rows, {1}, 0, 1000) == [0.21], (
            "a PING on the delivering connection within the window, answered")
        assert gm.probes("redis", rows, {1}, 0, 1000) == [0.04], "XACK, on any connection"
        assert gm.probes("nats", rows, {1}, None, 1000) == []

    def test_what_falls_within_the_measured_window(self):
        assert gm._within([1, 5, 9], 2, 8) == 1

    def test_the_longest_silence(self):
        assert gm.silence([10, 30, 100], 0, 50) == 0.02, "from the window's start to 10 ns ..."
        assert gm.silence([], 0, 4000) == 4.0
        assert gm.silence([5], None, 10) is None and gm.silence([5], 10, 10) is None

    def test_the_checks_of_b(self):
        clean = {"retransmitted": 0, "zero_windows": 0, "probe_max_us": 300.0, "q_max_us": 90.0,
                 "silence_max_us": 4000.0}
        assert gm.b_checks(clean, 10.0) is True and gm.b_checks(clean, 2.0) is False
        assert gm.b_checks(dict(clean, retransmitted=1), 10.0) is False
        assert gm.b_checks(dict(clean, zero_windows=2), 10.0) is False
        assert gm.b_checks(dict(clean, q_max_us=4999.0), 10.0) is True
        assert gm.b_checks(dict(clean, q_max_us=5000.0), 10.0) is False
        assert gm.b_checks(dict(clean, q_max_us=999.0, silence_max_us=1000.0,
                                probe_max_us=1000.0), 2.0) is True
        assert gm.b_checks(dict(clean, q_max_us=1000.0, silence_max_us=1000.0,
                                probe_max_us=1000.0), 2.0) is False
        assert gm.b_checks(dict(clean, probe_max_us=None), 10.0) is None
        assert gm.b_checks(dict(clean, probe_max_us=None, q_max_us=5000.0), 10.0) is False


#: A dense NATS run with its requests kept waiting: twenty messages 5 ms apart, twenty-five pull
#: requests sent before the first, and a PING probe between each two messages.
DENSE_SENDS = [(20000 + 5000 * i, 20400 + 5000 * i) for i in range(20)]
DENSE_ASKS = ([(-60 + k, 20900 + 5000 * k, [k]) for k in range(20)]
              + [(-40 + k, 200000 + k, []) for k in range(5)])
DENSE_PROBES = [22000 + 5000 * i for i in range(20)]


class TestTheRemedysOwnCheck:
    def test_requests_kept_waiting_are_certified_and_the_checks_hold(self, tmp_path):
        run = tb.World("nats", DENSE_SENDS, DENSE_ASKS, setup="N2000-nats-d256",
                       params={"consumer": "python", "depth": 256}, card=True,
                       probes=DENSE_PROBES).write(tmp_path)
        row = gm.read_run(run, DRIVER, BROKER, RECEIVER, ALLOWANCE, warmup_s=0)
        assert (row["certified_share"], row["certified_n"], row["certified_share_2ms"]) == (
            1.0, 20, 1.0)
        assert (row["delivering"], row["retransmitted"], row["zero_windows"],
                row["retransmitted_run"], row["zero_windows_run"],
                row["retransmitted_producer"]) == ("40002", 0, 0, 0, 0, 0)
        assert (row["probe_kind"], row["probe_n"], row["probe_max_us"], row["q_max_us"]) == (
            gm.PROBES["nats"], 19, float(tb.World.PROBE_TRIP), float(tb.World.CARD_LAG)), (
            "the last probe left after the last message arrived")
        assert row["silence_max_us"] == pytest.approx(4600.0), (
            "between an acknowledgment and the next message's departure, on the driver")
        assert (row["b_checks"], row["b_checks_2ms"]) == (True, False)
        assert row["broker_waiting_share"] == 1.0
        assert row["cap_pairs"] == 1 and row["cap_calibrated_n"] == 20, (
            "the PINGs could not have waited, so the estimate has its floor")

    def test_one_request_at_a_time_is_never_certified(self, redis_row):
        row = redis_row
        assert (row["certified_share"], row["certified_share_2ms"]) == (0.0, 0.0)
        assert (row["retransmitted"], row["zero_windows"], row["q_max_us"]) == (0, 0, 20.0)
        assert (row["probe_n"], row["probe_max_us"]) == (0, None), "no XACK, so no proxy"
        assert row["silence_max_us"] == pytest.approx(2799600.0)
        assert row["b_checks"] is False, "the run is silent for 2.8 s between its blocks"

    def test_the_checks_read_only_the_measured_window(self, tmp_path):
        """A 2-s warm-up: the window opens at 2,099,990 us, the first send plus 2 s, so the run's
        silence between its blocks counts from there, to message 3's departure at 3,100,000."""
        run = redis_world(tmp_path)
        row = gm.read_run(run, DRIVER, BROKER, RECEIVER, ALLOWANCE, warmup_s=2)
        assert row["timed"] == 3 and row["silence_max_us"] == pytest.approx(1000010.0)

    def test_a_run_without_its_captures_cannot_be_checked(self, tmp_path):
        run = tb.World("redis", SENDS, ASKS, setup="V2000-redis-d256").write(tmp_path)
        os.remove(os.path.join(run, "sender_full.pcap"))
        row = gm.read_run(run, DRIVER, BROKER, RECEIVER, ALLOWANCE, warmup_s=0)
        assert (row["silence_max_us"], row["retransmitted_producer"], row["q_max_us"],
                row["retransmitted"], row["certified_share"]) == (None, 0, None, None, None)
        assert row["b_checks"] is None, "no message is timed, so nothing can be checked"


class TestTheMatching:
    def message(self, eid_sent, eid_got, port=1, request=1, byte=1, t=1):
        return {"t_depart": t, "t_arrive": t, "eid_sent": eid_sent, "eid_got": eid_got,
                "producer_port": port, "consumer_port": port, "request": request,
                "got_byte": byte}

    def test_against_the_payloads_pairing(self):
        messages = [self.message("a", "a"), self.message("b", "c"), self.message(None, None),
                    self.message("d", "d"), self.message("d", "d"),
                    dict(self.message("e", "e"), t_arrive=None)]
        assert gm.matching_check("redis", messages, {"a", "d", "f"}) == {
            "broker_pairs": 5, "payload_pairs": 3, "m1b_missed": 1, "m1b_differ": 3,
            "order_differ": None}
        assert gm.matching_check("redis", messages, None)["m1b_missed"] is None

    def test_rabbitmqs_two_orders(self):
        messages = [self.message("a", "a", request=1, byte=10),
                    self.message("b", "b", request=2, byte=30),
                    self.message("c", "c", request=3, byte=20)]
        assert gm.matching_check("rabbitmq", messages, set())["order_differ"] == 2
        messages.append(self.message("d", "d", port=2, request=4, byte=40))
        assert gm.matching_check("rabbitmq", messages, set())["order_differ"] is None
        assert gm.matching_check("rabbitmq", [], set())["order_differ"] is None

    def test_no_captures_no_payload_pairs(self, tmp_path):
        assert gm.payload_pairs(tb.new_run(tmp_path, "law_x", "redis"), DRIVER, BROKER,
                                RECEIVER) is None


# --- one run -------------------------------------------------------------------------------------

class TestOneRedisRun:
    def test_its_settings_and_the_wire(self, redis_row):
        row = redis_row
        assert (row["setup"], row["block"], row["pilot"], row["rate"], row["backend"],
                row["consumer"], row["depth"], row["one_reply"], row["blocks"], row["arch"],
                row["verdict"]) == ("V2000-redis-d1", "V", False, 2000, "redis", "waiting", 1,
                                    True, True, "x86_64", "count")
        assert (row["wire_matched"], row["wire_unreadable"], row["broker_matched"],
                row["timed"], row["d_joined"], row["untimed_gap"]) == (6, 0, 6, 6, 6, 0)
        assert row["producer_join"] == "broker id"

    def test_the_card_and_the_sockets(self, redis_row):
        row = redis_row
        assert (row["q_n"], row["q_p99"], row["q_min"], row["card_window_ns"]) == (
            len(ASKS), 20.0, 20.0, 1500)
        assert row["m1_matched"] == 6 and row["m1_dif_p50"] == pytest.approx(5.0)
        assert row["m1_tail_diff"] == pytest.approx(5.0) and row["m1_tail_diff_on"] == (
            pytest.approx(5.0))
        assert row["W_so_p50"] == pytest.approx(1005.0)
        assert (row["payload_pairs"], row["broker_pairs"], row["m1b_missed"],
                row["m1b_differ"]) == (6, 6, 0, 0)

    def test_the_check_from_the_capture(self, redis_row):
        row = redis_row
        assert (row["cap_timed"], row["cap_pairs"], row["cap_allowance_us"]) == (6, 1, 10.0)
        assert row["cap_overshoot_max_us"] == pytest.approx(-20.0), "C_hat 180 against C 200"
        assert (row["broker_none_share"], row["broker_waiting_share"],
                row["broker_close_share"], row["broker_unwaited_share"]) == (0.5, 0.5, 0.0, 0.5)
        assert row["broker_none0_share"] == 0.5
        assert (row["cap_certain_none_share"], row["cap_certain_agree"],
                row["cap_certain_false_none"], row["cap_certain_missed_none"]) == (
            pytest.approx(1 / 6.0), pytest.approx(4 / 6.0), 0, 2)
        for reading in ("raw", "calibrated"):
            assert (row["cap_%s_none_share" % reading], row["cap_%s_agree" % reading]) == (
                0.5, 1.0)
        assert row["cap_wait_err_raw_p50"] == pytest.approx(10.0)
        assert row["so_timed"] == 6 and row["so_allowance_us"] == 15.0
        assert row["so_certain_false_none"] == 0

    def test_the_three_latencies(self, redis_row):
        row = redis_row
        assert row["W_p50"] == pytest.approx(1000.0) and row["F_p50"] == pytest.approx(950.0)
        assert row["D_p50"] == pytest.approx(1080.0 + (1110.0 - 1080.0) / 2)
        assert row["Tc_p50"] == pytest.approx(99520.0), "over the requests within the window"
        assert row["requests"] == 5 and row["overlapped"] == 0

    def test_each_states_tail(self, redis_row):
        row = redis_row
        assert (row["n_on"], row["n_off"]) == (3, 3)
        on = dict((q, row[q + "_tail_on"]) for q in gm.TAILED)
        off = dict((q, row[q + "_tail_off"]) for q in gm.TAILED)
        assert on == pytest.approx({"W": 1500.0, "D": 1660.0, "F": 1000.0, "Fc": 1030.0,
                                    "E2": 1000.0, "Fs": 1200.0, "Tc": 99700.0})
        assert off == pytest.approx({"W": 1000.0, "D": 1080.0, "F": 780.0, "Fc": 810.0,
                                     "E2": 780.0, "Fs": 980.0, "Tc": 99520.0})
        assert row["W_ratio"] == pytest.approx(1.5) and row["W_rise"] == pytest.approx(500.0)
        assert row["e2_share"] == pytest.approx(1 - 220.0 / 500.0)
        assert row["D_own_ratio"] == pytest.approx(1660.0 / 1080.0)
        assert row["Tc_req_ratio"] == pytest.approx(99700.0 / 2797800.0)
        assert row["waiting_n_on"] == 1 and row["waiting_W_tail_on"] is None, (
            "one message: none lies above its own 99th percentile")
        assert row["waiting_W_tail_off"] == pytest.approx(900.0)
        assert (row["broker_none_share_on"], row["broker_unwaited_share_on"],
                row["broker_none_share_off"]) == (pytest.approx(2 / 3.0), pytest.approx(2 / 3.0),
                                                  pytest.approx(1 / 3.0))

    def test_the_gap_at_the_broker(self, redis_row):
        row = redis_row
        assert row["g_n"] == 5 and row["g_us"] == pytest.approx(99720.0)
        assert row["g_turnaround_us"] == pytest.approx(99520.0)
        assert row["g_rest_us"] == pytest.approx(200.0), "two crossings of 100 us"
        assert row["lam_per_s"] == pytest.approx(5 / 3.2)
        assert row["nofetch_time_share"] == pytest.approx(1 - 5200.0 / 3200800.0)
        assert row["kch_predicted"] == pytest.approx(gm.kch_share(5 / 3.2, 99720.0))
        assert row["softnet_squeezed"] == 2 and row["softirq_s"] == 0.3


class TestOtherBrokersRuns:
    def read(self, root, backend, **more):
        sends, asks = tb.schedule(backend)
        run = tb.World(backend, sends, asks, **more).write(root)
        return gm.read_run(run, DRIVER, BROKER, RECEIVER, ALLOWANCE, warmup_s=0)

    def test_kafka_joins_its_producer_through_the_wire_until_producer_csv_names_offsets(
            self, tmp_path):
        row = self.read(tmp_path / "a", "kafka", setup="K2000-kafka-python",
                        params={"consumer": "kafka-python"})
        assert (row["producer_join"], row["d_joined"], row["consumer"]) == (
            "the wire's record", 4, "kafka-python")
        assert row["F_p50"] == row["E2b_p50"], "Kafka's ready receiver asks again at once"
        row = self.read(tmp_path / "b", "kafka", offsets=True)
        assert (row["producer_join"], row["d_joined"]) == ("broker id", 4)

    def test_nats_by_its_stream_sequence(self, tmp_path):
        row = self.read(tmp_path, "nats", setup="N2000-nats-d1",
                        params={"consumer": "python", "depth": 1})
        assert (row["producer_join"], row["d_joined"], row["timed"]) == ("broker id", 4, 4)
        assert row["F_p50"] == row["E3b_p50"]

    def test_rabbitmq_by_its_confirm_numbers_and_its_two_orders(self, tmp_path):
        row = self.read(tmp_path, "rabbitmq", setup="P2000-rabbitmq-p1", params={"prefetch": 1},
                        config="prefetch=1 ack_batch=1")
        assert (row["producer_join"], row["d_joined"], row["prefetch"], row["order_differ"]) == (
            "confirm number", 4, 1, 0)
        assert row["m1b_missed"] == 0 and row["untimed_gap"] == 2, (
            "the first delivery went out on the consume's credit and the second on the first "
            "acknowledgment's, which has no answer before it to time a turnaround from")

    def test_a_run_without_its_producers_file(self, tmp_path):
        sends, asks = tb.schedule("redis")
        run = tb.World("redis", sends, asks).write(tmp_path)
        os.remove(os.path.join(run, "producer.csv"))
        row = gm.read_run(run, DRIVER, BROKER, RECEIVER, None)
        assert row["timed"] == 4 and row["d_joined"] == 0 and row["cap_calibrated_n"] == 0
        assert row["q_n"] is None and row["m1_matched"] == 0 and row["W_so_p50"] is None


# --- the block -----------------------------------------------------------------------------------

class TestTheBlock:
    def test_passing_runs_by_setup_and_the_pilot_apart(self, tmp_path):
        sends, asks = tb.schedule("redis")
        folder = tmp_path / "runs"
        folder.mkdir()
        tb.World("redis", sends, asks, setup="V2000-redis-d1").write(folder, "law_a")
        tb.World("redis", sends, asks, setup="V2000-redis-d1", verdict="fail").write(folder,
                                                                                     "law_b")
        tb.World("redis", sends, asks, setup="V2000-redis-d1-pilot").write(folder, "law_c")
        tb.World("redis", sends, asks, setup="U2000-redis-l0").write(folder, "law_d")
        tb.World("redis", sends, asks, setup="V2000-redis-d256",
                 verdict=None).write(folder, "law_e")
        (folder / "notes.txt").write_text("not a run", encoding="utf-8")
        (folder / "other").mkdir()
        found, skipped = gm.block_runs([str(folder)])
        assert sorted(found) == ["V2000-redis-d1"] and len(found["V2000-redis-d1"]) == 1
        assert skipped == [("law_b", "fail"), ("law_e", "not judged")]
        found, _ = gm.block_runs([str(folder)], pilot=True)
        assert sorted(found) == ["V2000-redis-d1-pilot"]
        rows, _ = gm.read_block([str(folder)], DRIVER, BROKER, RECEIVER, ALLOWANCE, 0)
        assert [r["run"] for r in rows] == ["law_a"]

    def test_the_allowance_from_a_pilots_rows(self):
        rows = [{"backend": "redis", "cap_overshoot_max_us": 12.1, "so_overshoot_max_us": -3.0},
                {"backend": "redis", "cap_overshoot_max_us": 31.0},
                {"backend": "nats", "cap_overshoot_max_us": None}]
        assert gm.calibrate(rows) == {"capture": {"redis": 35.0}, "sockets": {"redis": 0.0}}


# --- the judgments -------------------------------------------------------------------------------

def run_row(setup, block, backend, **fields):
    row = {"setup": setup, "block": block, "backend": backend, "rate": 2000, "pilot": False,
           "arch": "x86_64"}
    row.update(fields)
    return row


def runs(setup, block, backend, values, **fields):
    """One row per run, each run's fields from `values`, a list of dicts, beside the shared ones."""
    return [run_row(setup, block, backend, run="%s_r%d" % (setup, i), **dict(fields, **v))
            for i, v in enumerate(values)]


class TestTheInstrumentsPredictions:
    def test_m1a_the_card(self):
        rows = (runs("V-a", "V", "redis", [dict(q_n=10, q_p99=100.0, q_min=-1.0,
                                                card_window_ns=1500),
                                           dict(q_n=0, q_p99=None)])
                + runs("V-b", "V", "redis", [dict(q_n=10, q_p99=151.0, q_min=1.0,
                                                  card_window_ns=1500)])
                + runs("V-c", "V", "redis", [dict(q_n=10, q_p99=10.0, q_min=-2.0,
                                                  card_window_ns=1500)])
                + runs("V-d", "V", "redis", [dict(q_n=None)])
                + runs("V-e", "V", "redis", [dict(q_n=10, q_p99=10.0, q_min=1.0,
                                                  card_window_ns=None)]))
        verdict = gm.judge_card(rows)
        held = dict((c["setup"], c["holds"]) for c in verdict["checks"])
        assert held == {"V-a": True, "V-b": False, "V-c": False, "V-d": None, "V-e": None}
        assert verdict["verdict"] == "not confirmed" and verdict["out_of_reach"] == ["V-d", "V-e"]

    def test_m1b_the_matching(self):
        rows = (runs("V-a", "V", "redis", [dict(m1b_missed=0, m1b_differ=0)])
                + runs("P-a", "P", "rabbitmq", [dict(m1b_missed=0, m1b_differ=0,
                                                     order_differ=1)])
                + runs("V-b", "V", "redis", [dict(m1b_missed=None, m1b_differ=0)]))
        held = dict((c["setup"], c["holds"]) for c in gm.judge_matching(rows)["checks"])
        assert held == {"V-a": True, "P-a": False, "V-b": None}

    def test_m1c_one_reply_and_the_librarys_reads(self):
        rows = (runs("V-one", "V", "redis", [dict(m1_matched=5, depth=256, one_reply=True,
                                                  m1_tail_diff=d) for d in (-9.0, 3.0, 50.0)])
                + runs("V-lib", "V", "redis", [dict(m1_matched=5, depth=256, one_reply=False,
                                                    m1_tail_diff_on=99.0)])
                + runs("N-one", "N", "nats", [dict(m1_matched=5, depth=256, one_reply=True,
                                                   m1_tail_diff=None)])
                + runs("V-d1", "V", "redis", [dict(m1_matched=5, depth=1, one_reply=True)])
                + runs("N-go", "N", "nats", [dict(m1_matched=0, depth=256)]))
        verdict = gm.judge_reads(rows)
        assert [(c["setup"], c["tail_diff"], c["holds"]) for c in verdict["checks"]] == [
            ("N-one", None, None), ("V-lib", 99.0, False), ("V-one", 3.0, True)]

    def test_m2a_and_m2b(self):
        rows = (runs("V-a", "V", "redis", [dict(cap_certain_false_none=0,
                                                cap_calibrated_none_share=0.50,
                                                broker_none_share=0.55),
                                           dict(cap_certain_false_none=0,
                                                cap_calibrated_none_share=None,
                                                broker_none_share=0.9)])
                + runs("V-b", "V", "redis", [dict(cap_certain_false_none=1,
                                                  cap_calibrated_none_share=0.40,
                                                  broker_none_share=0.47)])
                + runs("V-c", "V", "redis", [dict(cap_certain_false_none=0)]))
        held = dict((c["setup"], c["holds"]) for c in gm.judge_causality(rows)["checks"])
        assert held == {"V-a": True, "V-b": False, "V-c": True}
        verdict = gm.judge_calibrated(rows)
        held = dict((c["setup"], c["holds"]) for c in verdict["checks"])
        assert held == {"V-a": True, "V-b": False, "V-c": None}, (
            "5 points, within 6; 7, not; and a setup whose estimate never had a value")
        assert verdict["checks"][0]["points"][1] is None


WAITING = dict(broker_waiting_share=0.9995, certified_share=0.9995, b_checks=True,
               certified_share_2ms=0.99, b_checks_2ms="False", cap_calibrated_none_share=0.004,
               cap_certain_none_share=0.0, probe_kind=gm.PROBES["redis"])


class TestTheChecksManipulation:
    def rows(self):
        return (runs("V2000-redis-d256", "V", "redis",
                     [WAITING, dict(WAITING, b_checks="False", certified_share=0.2)], depth=256)
                + runs("N2000-nats-go", "N", "nats", [dict(WAITING, broker_waiting_share=0.99)],
                       consumer="nats-go", depth=1)
                + runs("P2000-rabbitmq-p1000", "P", "rabbitmq",
                       [dict(WAITING, b_checks="", cap_calibrated_none_share=None)],
                       prefetch=1000)
                + runs("N2000-nats-d256", "N", "nats", [dict(WAITING, certified_share=0.99)],
                       consumer="python", depth=256)
                + runs("V2000-redis-d1", "V", "redis", [WAITING], depth=1))

    def test_m2c_the_brokers_record_and_the_certified_share(self):
        cells = dict((c["setup"], c) for c in gm.judge_manipulation(self.rows())["checks"])
        assert sorted(cells) == ["N2000-nats-d256", "N2000-nats-go", "P2000-rabbitmq-p1000",
                                 "V2000-redis-d256"]
        redis = cells["V2000-redis-d256"]
        assert (redis["certified"], redis["runs_checked"], redis["runs_certified"],
                redis["holds"]) == (0.9995, [True, False], [0.9995, 0.2], True), (
            "the run whose checks of B failed is left out of the certified share")
        assert (redis["estimate_none"], redis["probes"], redis["certified_2ms"]) == (
            0.004, [gm.PROBES["redis"]], None), "beside: the estimate, the proxy, and B = 2 ms"
        assert (cells["N2000-nats-go"]["broker_held"], cells["N2000-nats-go"]["holds"]) == (
            False, False)
        rabbit = cells["P2000-rabbitmq-p1000"]
        assert (rabbit["client_held"], rabbit["holds"], rabbit["estimate_none"]) == (
            None, None, None), "no run whose checks could be read"
        assert cells["N2000-nats-d256"]["holds"] is False, "certified for 99% of messages"

    def test_a_tables_three_valued_checks(self):
        assert [gm._three(v) for v in (True, "True", False, "False", "", None)] == [
            True, True, False, False, None, None]


def tailed(w_on, w_off, d_on, d_off, **more):
    return dict({"W_ratio": w_on / w_off, "D_ratio": d_on / d_off, "W_tail_on": w_on,
                 "W_tail_off": w_off}, **more)


class TestTheLatencies:
    def test_held_still_by_two_one_sided_tests(self):
        still, p = gm.holds_still([1.01, 0.99, 1.02, 1.00])
        assert still and p < 1e-3
        still, p = gm.holds_still([1.0, 1.4, 0.8, 1.3])
        assert not still and p > gm.ALPHA
        assert gm.holds_still([1.1, 1.1]) == (True, 0.0)
        assert gm.holds_still([1.3, 1.3]) == (False, 1.0)
        assert gm.holds_still([1.0]) == (None, None)
        assert gm.holds_still([1.0, None]) == (None, None) == gm.holds_still([1.0, 0.0])
        from scipy import stats
        logs = [math.log(r) for r in (1.05, 1.15, 1.10)]
        mean, sd = sum(logs) / 3, __import__("statistics").stdev(logs)
        se = sd / math.sqrt(3)
        expected = max(1 - stats.t.cdf((mean + math.log(1.2)) / se, 2),
                       stats.t.cdf((mean - math.log(1.2)) / se, 2))
        assert gm.holds_still([1.05, 1.15, 1.10])[1] == pytest.approx(expected)

    def test_m3a_over_the_messages_that_found_one_waiting(self):
        good = dict(WAITING, waiting_W_ratio=1.0, waiting_D_ratio=2.0, W_ratio=1.6, D_ratio=1.9)
        rows = (runs("V2000-redis-d256", "V", "redis",
                     [dict(good, waiting_W_ratio=r) for r in (1.01, 0.99, 1.0, 1.02)], depth=256)
                + runs("N2000-nats-go", "N", "nats", [dict(good, broker_waiting_share=0.5)] * 4,
                       consumer="nats-go"))
        manipulation = gm.judge_manipulation(rows)
        verdict = gm.judge_ready(rows, manipulation)
        redis, nats = verdict["checks"][1], verdict["checks"][0]
        assert (redis["judged"], redis["W_held_still"], redis["D_grew"], redis["holds"]) == (
            True, True, True, True)
        assert redis["all_messages"]["W_ratio"] == pytest.approx(1.6), "described beside"
        assert (nats["judged"], nats["holds"], nats["tost_p"]) == (False, None, None)
        assert verdict["verdict"] == "confirmed" and verdict["not_judged"] == ["N2000-nats-go"]
        assert gm._by_broker(verdict, "nats")["verdict"] == "not judged"
        assert gm._by_broker(verdict, "rabbitmq")["verdict"] == "out of reach"

    def test_m3b_the_rise_and_the_share_removing_the_turnaround_takes_out(self):
        rose = [tailed(1500.0, 1000.0, 3.0, 1.0, E2_tail_on=1100.0, E2_tail_off=900.0,
                       Fs_tail_on=1200.0, Fs_tail_off=950.0),
                tailed(1700.0, 1000.0, 3.0, 1.0, E2_tail_on=1150.0, E2_tail_off=950.0,
                       Fs_tail_on=1300.0, Fs_tail_off=990.0)]
        rows = (runs("V2000-redis-d1", "V", "redis", rose, depth=1)
                + runs("N2000-nats-d1", "N", "nats", [tailed(1100.0, 1000.0, 2.0, 1.0)],
                       depth=1, consumer="python")
                + runs("P2000-rabbitmq-p1", "P", "rabbitmq", [dict(W_ratio=None)], prefetch=1)
                + runs("K2000-kafka-java", "K", "kafka",
                       [tailed(1600.0, 1000.0, 2.0, 1.0, E2_tail_on=1500.0,
                               E2_tail_off=1000.0)], consumer="java")
                + runs("K2000-kafka-rdk", "K", "kafka", [tailed(1600.0, 1000.0, 2.0, 1.0)],
                       consumer="confluent")
                + runs("N2000-nats-go", "N", "nats", [tailed(1.0, 1.0, 1.0, 1.0)],
                       consumer="nats-go", depth=1))
        verdict = gm.judge_gap(rows, draws=200)
        cells = dict((c["setup"], c) for c in verdict["checks"])
        assert sorted(cells) == ["K2000-kafka-java", "N2000-nats-d1", "P2000-rabbitmq-p1",
                                 "V2000-redis-d1"]
        redis = cells["V2000-redis-d1"]
        assert redis["share"] == pytest.approx(1 - (1125.0 - 925.0) / (1600.0 - 1000.0))
        assert redis["low"] <= redis["share"] <= redis["high"] and redis["holds"] is True
        assert redis["share_certain"] == pytest.approx(1 - (1250.0 - 970.0) / 600.0)
        assert (cells["N2000-nats-d1"]["holds"], cells["N2000-nats-d1"]["share"]) == (False, None)
        assert cells["P2000-rabbitmq-p1"]["holds"] is None
        assert cells["K2000-kafka-java"]["holds"] is False, "the turnaround took out 1/6"

    def test_the_share_and_its_interval_where_none_can_be_had(self):
        flat = [tailed(1000.0, 1000.0, 1.0, 1.0, E2_tail_on=1.0, E2_tail_off=1.0)]
        assert gm.onoff_share(flat) is None
        assert gm.share_interval(flat, draws=5) == (None, None, 5)


def kafka(setup, consumer, values, **fields):
    return runs(setup, "K", "kafka", values, consumer=consumer, **fields)


class TestKafkasPredictions:
    def rows(self):
        return (kafka("K2000-kafka-python", "kafka-python",
                      [tailed(2000.0, 1000.0, 3.0, 1.0, Tc_ratio=4.0, Tc_rise=900.0,
                              E2_tail_on=1100.0, E2_tail_off=1000.0)] * 2)
                + kafka("K2000-kafka-java", "java", [tailed(1300.0, 1000.0, 3.0, 1.0,
                                                            Tc_ratio=1.2, Tc_rise=300.0)])
                + kafka("K2000-kafka-franz", "franz", [tailed(1600.0, 1000.0, 3.0, 1.0,
                                                              Tc_ratio=2.0, Tc_rise=100.0)])
                + kafka("K2000-kafka-rdk", "confluent", [tailed(1700.0, 1000.0, 3.0, 1.0,
                                                                Tc_ratio=1.1, Tc_rise=60.0,
                                                                E2_tail_on=1600.0,
                                                                E2_tail_off=1000.0)])
                + kafka("K2000-kafka-rdk-rt", "confluent",
                        [dict(W_ratio=r, D_ratio=1.8, Tc_ratio=1.1,
                              broker_unwaited_share_on=0.6, broker_unwaited_share_off=0.55,
                              broker_none_share_on=0.5, broker_none_share_off=0.4,
                              nofetch_time_share=0.6, kch_predicted=0.5, g_us=600.0)
                         for r in (1.0, 1.01, 0.99, 1.02)], fetch_rt=True))

    def test_kc_a_the_turnaround_of_each_in_poll_client(self):
        verdict = gm.judge_turnaround(self.rows())
        assert [(c["setup"], c["holds"]) for c in verdict["checks"]] == [
            ("K2000-kafka-franz", True), ("K2000-kafka-java", False),
            ("K2000-kafka-python", True)]

    def test_kc_b_only_where_w_rose(self):
        verdict = gm.judge_fetch_share(self.rows(), draws=200)
        cells = dict((c["setup"], c) for c in verdict["checks"])
        assert cells["K2000-kafka-java"]["judged"] is False, "W rose 1.3 times"
        assert cells["K2000-kafka-python"]["share"] == pytest.approx(0.9)
        assert cells["K2000-kafka-python"]["holds"] is True
        assert cells["K2000-kafka-rdk"]["holds"] is False
        assert cells["K2000-kafka-franz"]["holds"] is None, "no tail means of E2"
        assert verdict["not_judged"] == ["K2000-kafka-java"]

    def test_kc_c_librdkafkas_rise_against_each(self):
        verdict = gm.judge_librdkafka(self.rows())
        assert [(c["consumer"], c["holds"]) for c in verdict["checks"]] == [
            ("kafka-python", True), ("java", True), ("franz", False)]
        assert gm.judge_librdkafka(self.rows()[:2])["verdict"] == "out of reach"

    def test_kc_d_and_kc_h_with_the_broker_thread_at_real_time_priority(self):
        verdict = gm.judge_fetch_thread(self.rows())
        assert [(c["setup"], c["W_held_still"], c["D_grew"], c["holds"])
                for c in verdict["checks"]] == [("K2000-kafka-rdk-rt", True, True, True)]
        verdict = gm.judge_round_trip(self.rows())
        cell = verdict["checks"][0]
        assert (cell["turnaround_held"], cell["left_waiting"], cell["holds"]) == (True, True,
                                                                                  True)
        assert cell["described"]["nofetch_time_share"] == 0.6
        rows = [dict(r, broker_unwaited_share_off=0.4) for r in self.rows()]
        assert gm.judge_round_trip(rows)["checks"][0]["holds"] is False


class TestTheWholeCore:
    def arms(self, idle_rise):
        return (runs("C2000-kafka-base", "C", "kafka", [dict(W_rise=600.0)] * 2,
                     consumer="kafka-python", priority=True)
                + runs("C2000-kafka-core", "C", "kafka", [dict(W_rise=idle_rise)],
                       consumer="kafka-python", priority=True, whole_core=True)
                + runs("C2000-kafka-core-sib", "C", "kafka", [dict(W_rise=400.0)],
                       consumer="kafka-python", priority=True, whole_core=True,
                       sibling_load=True))

    def test_c_a_against_its_own_baseline(self):
        cell = gm.judge_whole_core(self.arms(150.0))["checks"][0]
        assert (cell["setup"], cell["against"], cell["residual"], cell["residual_baseline"],
                cell["holds"]) == ("C2000-kafka-core", "C2000-kafka-base", 150.0, 600.0, True)
        assert cell["described"] == {"sibling_loaded": "C2000-kafka-core-sib", "residual": 400.0}
        assert gm.judge_whole_core(self.arms(201.0))["verdict"] == "not confirmed"
        assert gm.judge_whole_core([])["verdict"] == "out of reach"


class TestTheWholeJudgment:
    def rows(self):
        waiting = dict(WAITING, waiting_W_ratio=1.0, waiting_D_ratio=2.0)
        return (runs("V2000-redis-d256", "V", "redis", [waiting] * 2, depth=256, q_n=0,
                     m1b_missed=0, m1b_differ=0, cap_certain_false_none=0)
                + runs("A2000-redis-d256", "A", "redis", [waiting] * 2, depth=256,
                       arch=gm.ARM, m1b_missed=0, m1b_differ=0, cap_certain_false_none=0)
                + runs("A2000-kafka-rdk-rt", "A", "kafka",
                       [dict(W_ratio=1.0, D_ratio=2.0)] * 2, consumer="confluent",
                       fetch_rt=True, arch=gm.ARM)
                + runs("S2000-redis-udp", "S", "redis", [dict(waiting, softnet_squeezed=4)],
                       depth=256, load_kind="udp")
                + runs("V2000-redis-d1-pilot", "V", "redis", [dict(W_ratio=9.0)], pilot=True,
                       depth=1))

    def test_every_prediction_and_the_arm_pair(self):
        out = gm.judge(self.rows(), draws=50)
        assert sorted(out) == sorted(["M1-a", "M1-b", "M1-c", "M2-a", "M2-b", "M2-c", "M3-a",
                                      "M3-b", "V-a", "N-a", "P-a", "KC-a", "KC-b", "KC-c",
                                      "KC-d", "KC-h", "C-a", "A", "S", "described"])
        assert out["M2-c"]["verdict"] == "confirmed" and out["V-a"]["verdict"] == "confirmed"
        assert [c["setup"] for c in out["M1-b"]["checks"]] == ["A2000-kafka-rdk-rt",
                                                              "A2000-redis-d256",
                                                              "V2000-redis-d256"]
        assert out["M3-b"]["verdict"] == "out of reach", "the pilot's rows are never judged"
        assert out["A"]["verdict"] == "confirmed"
        assert sorted(out["A"]["parts"]) == ["KC-d", "M2-c", "V-a"]
        scope = out["S"]["described"]
        assert [s["setup"] for s in scope] == ["S2000-redis-udp"] and scope[0]["squeezed"] == [4.0]
        assert [s["setup"] for s in out["described"]["setups"]][-1] == "V2000-redis-d256"

    def test_one_verdict_over_several(self):
        assert gm._all([{"verdict": "confirmed"}, {"verdict": "not confirmed"}]) == (
            "not confirmed")
        assert gm._all([{"verdict": "confirmed"}, {"verdict": "out of reach"}]) == (
            "out of reach")
        assert gm._all([]) == "out of reach"


# --- files and the command line ------------------------------------------------------------------

class TestTheCommandLine:
    def test_read_then_judge(self, tmp_path, capsys):
        folder = tmp_path / "runs"
        folder.mkdir()
        redis_world(folder, "law_v1")
        redis_world(folder, "law_v2")
        allowance = tmp_path / "allowance.json"
        allowance.write_text(json.dumps(ALLOWANCE), encoding="utf-8")
        table = str(tmp_path / "t" / "runs.csv")
        os.makedirs(os.path.dirname(table))
        assert gm.main(["read", "--runs", str(folder), "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--allowance", str(allowance), "--out-runs",
                        table, "--warmup", "0"]) == 0
        assert "OK 2 runs of plan version 47 ->" in capsys.readouterr().out
        rows = gm.read_table(table)
        assert [r["run"] for r in rows] == ["law_v1", "law_v2"]
        assert (rows[0]["depth"], rows[0]["one_reply"], rows[0]["pilot"]) == (1, True, False)
        out = str(tmp_path / "verdicts.json")
        assert gm.main(["judge", "--runs-table", table, "--out", out, "--draws", "20"]) == 0
        with open(out, encoding="utf-8") as fh:
            verdicts = json.load(fh)
        cell = verdicts["M3-b"]["checks"][0]
        assert (cell["setup"], cell["W_ratio"], cell["rose"]) == ("V2000-redis-d1", 1.5, True)
        assert "M1-a: confirmed" in capsys.readouterr().out
        assert gm.read_table(str(tmp_path / "nowhere.csv")) == [] == gm.read_table(None)
        bare = tmp_path / "bare.csv"
        bare.write_text("run,setup\nr1,V2000-redis-d1\n", encoding="utf-8")
        assert gm.read_table(str(bare)) == [{"run": "r1", "setup": "V2000-redis-d1"}]

    def test_a_pilots_runs_and_their_allowance(self, tmp_path, capsys):
        folder = tmp_path / "runs"
        folder.mkdir()
        redis_world(folder, "law_p1", setup="V2000-redis-d1-pilot")
        out = str(tmp_path / "allowance.json")
        assert gm.main(["calibrate", "--runs", str(folder), "--driver", DRIVER, "--broker",
                        BROKER, "--receiver", RECEIVER, "--out", out, "--warmup", "0"]) == 0
        with open(out, encoding="utf-8") as fh:
            assert json.load(fh)["capture"] == {"redis": 0.0}
        assert "from 1 pilot runs" in capsys.readouterr().out
        table = str(tmp_path / "pilot.csv")
        assert gm.main(["read", "--runs", str(folder), "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--allowance", out, "--out-runs", table,
                        "--pilot"]) == 0
        assert "OK 1 runs of plan version 47's pilot" in capsys.readouterr().out
        redis_world(folder, "law_f1", verdict="fail")
        assert gm.main(["read", "--runs", str(folder), "--driver", DRIVER, "--broker", BROKER,
                        "--receiver", RECEIVER, "--allowance", out, "--out-runs", table]) == 0
        assert "left out law_f1: fail" in capsys.readouterr().out
        with open(table, encoding="utf-8", newline="") as fh:
            assert list(csv.DictReader(fh)) == []
