"""Tests for scripts/general_method49.py, freeze 46's judge (plan version 49): the remedy by
protocol, judged by what it changes, against run rows built here and against a run built packet by
packet by test_client_wire_brokers.World and read by general_method's read_run."""
import csv
import json
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import general_method as gm  # noqa: E402
import general_method49 as g49  # noqa: E402
import general_method_power as gp  # noqa: E402
import test_general_method as tgm  # noqa: E402
import under_load_posthoc as ph  # noqa: E402

X86, ARM = "x86_64", gm.ARM
#: A run whose instrument checks out: M1-b's matching and M2-a's certain reading.
SOUND = dict(m1b_missed=0, m1b_differ=0, cap_certain_false_none=0)


@pytest.fixture(autouse=True)
def a_small_world(monkeypatch):
    """The worlds carry a few messages, and each of the triangle's least values needs
    TRIANGLE_MIN values, so the tests ask for one."""
    monkeypatch.setattr(ph, "TRIANGLE_MIN", 1)


def runs(setup, values, **fields):
    """One row per run of a setup, its block its id's first letter, each run's fields from
    `values`, beside the shared ones, its instrument checking out unless a field says not."""
    backend = setup.split("-")[1]
    out = []
    for i, v in enumerate(values):
        row = dict(SOUND, run="%s_r%d" % (setup, i), setup=setup, block=setup[0],
                   backend=backend, rate=2000, pilot=False,
                   arch=ARM if setup[0] == "Z" else X86)
        row.update(fields)
        row.update(v)
        out.append(row)
    return out


#: A run in which a request waited for every message, certified at 10 ms; at 50 ms too.
WAITING = dict(broker_waiting_share=1.0, certified_share=1.0, b_checks="True",
               certified_share_50ms=1.0, b_checks_50ms="True", certified_share_2ms=0.9,
               b_checks_2ms="False", probe_kind="a probe", silence_max_us=6000.0,
               cap_calibrated_none_share=None, Q_own_ratio=1.05, Res_own_ratio=0.9,
               rq_share_on=0.3, rq_share_off=0.01)
STILL = (1.01, 0.99, 1.02, 1.00)


def redis(gap_ratio=2.0, gap_rise=1800.0, rises=(10.0, -20.0, 15.0, 5.0), still=STILL,
          d_own=4.0, **waiting):
    return (runs("R2000-redis-d1", [dict(W_ratio=gap_ratio, W_rise=gap_rise,
                                         D_own_ratio=2.0)] * 4, depth=1, consumer="waiting")
            + runs("R2000-redis-d256", [dict(WAITING, W_ratio=w, W_rise=r, D_own_ratio=d_own,
                                             waiting_W_ratio=w, D_ratio=1.3, **waiting)
                                        for w, r in zip(still, rises)], depth=256,
                   consumer="waiting"))


def kafka(block, normal_ratio=40.0, normal_rise=3000.0, rt_rise=20.0, unwaited=(0.6, 0.8)):
    return (runs(block + "2000-kafka-rdk", [dict(WF_own_ratio=normal_ratio,
                                                 WF_own_rise=normal_rise,
                                                 WF_own_tail_on=3100.0,
                                                 WF_own_tail_off=100.0)] * 4,
                 consumer="confluent")
            + runs(block + "2000-kafka-rdk-rt",
                   [dict(WF_own_rise=rt_rise, broker_unwaited_share_on=unwaited[0],
                         broker_unwaited_share_off=unwaited[1], g_us=600.0)] * 4,
                   consumer="confluent", fetch_rt=True))


class TestTheRunsJudged:
    def test_each_block_from_its_own_pair_and_its_instrument_sound(self):
        rows = (runs("R2000-redis-d1", [{}]) + runs("Z2000-kafka-rdk", [{}])
                + runs("Q2000-kafka-rdk", [{}], arch=ARM) + runs("Z2000-kafka-rdk-rt", [{}],
                                                                 arch=X86)
                + runs("R2000-redis-d256", [{}], pilot=True) + runs("V2000-redis-d1", [{}])
                + runs("J2000-nats-go", [dict(m1b_differ=2)])
                + runs("G2000-rabbitmq-p1000", [dict(order_differ=1)])
                + runs("Q2000-kafka-rdk-rt", [dict(cap_certain_false_none=None)]))
        kept, left = g49.runs_judged(rows)
        assert [r["setup"] for r in kept] == ["R2000-redis-d1", "Z2000-kafka-rdk"]
        assert [(x["setup"], x["why"].split(" (")[0]) for x in left] == [
            ("Q2000-kafka-rdk", "run on the other pair"),
            ("Z2000-kafka-rdk-rt", "run on the other pair"),
            ("R2000-redis-d256", "a pilot's run"),
            ("J2000-nats-go", "its instrument does not check out"),
            ("G2000-rabbitmq-p1000", "its instrument does not check out"),
            ("Q2000-kafka-rdk-rt", "its instrument does not check out")]
        assert left[-1]["why"].endswith("(M1-b or M2-a: None)"), "a check that cannot be read"

    def test_the_instruments_own_checks(self):
        row = dict(SOUND)
        assert g49.instrument_holds(row) is True
        assert g49.instrument_holds(dict(row, order_differ="0")) is True
        assert g49.instrument_holds(dict(row, order_differ="")) is True
        assert g49.instrument_holds(dict(row, m1b_missed="3")) is False
        assert g49.instrument_holds(dict(row, cap_certain_false_none=1)) is False
        assert g49.instrument_holds(dict(row, m1b_missed=None)) is None


class TestTheSetupsRoles:
    def test_the_gap_the_waiting_and_kafkas_two(self):
        role = lambda setup, **f: runs(setup, [{}], **f)[0]  # noqa: E731
        assert g49._gapped(role("R2000-redis-d1", depth=1))
        assert not g49._gapped(role("R2000-redis-d256", depth="256"))
        assert [g49._waiting(r) for r in (role("R2000-redis-d256", depth="256"),
                                          role("J2000-nats-d256", depth=256),
                                          role("J2000-nats-go", consumer="nats-go", depth=1),
                                          role("G2000-rabbitmq-p1000", prefetch=1000),
                                          role("G2000-rabbitmq-p1", prefetch=1),
                                          role("R2000-redis-d1", depth=1),
                                          role("Q2000-kafka-rdk", depth=256))] == [
            True, True, True, True, False, False, False]
        normal = role("Q2000-kafka-rdk", consumer="confluent")
        rt = role("Z2000-kafka-rdk-rt", consumer="confluent", fetch_rt=True)
        assert (g49._normal(normal), g49._fetch_rt(normal)) == (True, False)
        assert (g49._normal(rt), g49._fetch_rt(rt)) == (False, True)
        assert not g49._normal(role("Q2000-kafka-rdk", consumer="confluent", priority=True))
        assert not g49._normal(role("Q2000-kafka-python", consumer="kafka-python"))
        assert not g49._fetch_rt(role("R2000-redis-d1", consumer="confluent", fetch_rt=True))

    def test_every_setup_the_design_runs_is_reached(self):
        reached = set(s for setups in g49.REACHES.values() for s in setups)
        assert reached | set(g49.AGAINST.values()) == set(g49.FROM47.values())
        assert sorted(g49.REACHES) == sorted(g49.PREDICTIONS)


class TestRedis:
    def test_the_gap_present_the_requests_waiting_and_w_held_still(self):
        out = g49.judge(redis(), draws=100)
        gap = out["R-a"]["checks"][0]
        assert (out["R-a"]["verdict"], gap["W_ratio"], gap["W_rise"]) == ("confirmed", 2.0,
                                                                         1800.0)
        waiting = out["R-b"]["checks"][0]
        assert (out["R-b"]["verdict"], waiting["b_ms"], waiting["certified"]) == (
            "confirmed", gm.CERTIFY_B_MS, 1.0)
        assert (waiting["certified_2ms"], waiting["certified_50ms"], waiting["probes"]) == (
            None, 1.0, ["a probe"]), "described beside it"
        still = out["R-c"]["checks"][0]
        assert (out["R-c"]["verdict"], still["W_held_still"], still["D_own_ratio"],
                still["D_ratio"]) == ("confirmed", True, 4.0, 1.3)
        assert still["tost_p"] < gm.ALPHA
        assert still["parts"] == {"Q_own_ratio": 1.05, "Res_own_ratio": 0.9,
                                  "parts_still": True, "rq_share_on": 0.3,
                                  "rq_share_off": 0.01}, "described beside a held-still W"
        left = out["R-d"]["checks"][0]
        assert (left["setup"], left["against"], left["rise"], left["rise_against"]) == (
            "R2000-redis-d256", "R2000-redis-d1", 7.5, 1800.0)
        assert left["left"] == pytest.approx(7.5 / 1800.0) and left["holds"] is True
        assert left["low"] <= left["left"] <= left["high"] and left["undefined_draws"] == 0
        assert left["most_us"] is None, "W's rise has no bound in microseconds"

    def test_a_part_of_w_that_moved_is_said_beside_a_held_still_w(self):
        out = g49.judge(redis(Res_own_ratio=0.7), draws=0)
        assert out["R-c"]["verdict"] == "confirmed"
        assert out["R-c"]["checks"][0]["parts"]["parts_still"] is False
        out = g49.judge(redis(Q_own_ratio=None), draws=0)
        assert out["R-c"]["checks"][0]["parts"]["parts_still"] is None

    def test_no_gap_leaves_the_remedys_size_unjudged(self):
        out = g49.judge(redis(gap_ratio=1.2), draws=10)
        assert out["R-a"]["verdict"] == "not confirmed"
        assert out["R-d"]["verdict"] == "not judged"
        assert out["R-c"]["verdict"] == "confirmed", "W held still rests on the waiting alone"

    def test_more_than_a_tenth_left_and_d_that_did_not_grow(self):
        out = g49.judge(redis(rises=(300.0, 250.0, 200.0, 210.0), d_own=1.4), draws=0)
        assert out["R-d"]["verdict"] == "not confirmed"
        assert out["R-d"]["checks"][0]["low"] is None, "no interval drawn"
        assert out["R-c"]["verdict"] == "not confirmed"
        assert (out["R-c"]["checks"][0]["W_held_still"],
                out["R-c"]["checks"][0]["D_grew"]) == (True, False)

    def test_a_fall_counts_as_a_rise(self):
        out = g49.judge(redis(rises=(-300.0, -250.0, -200.0, -210.0)), draws=0)
        assert out["R-d"]["checks"][0]["left"] == pytest.approx(-230.0 / 1800.0)
        assert out["R-d"]["verdict"] == "not confirmed"

    def test_requests_not_waiting_leave_both_remedy_predictions_unjudged(self):
        out = g49.judge(redis(broker_waiting_share=0.99), draws=10)
        assert out["R-b"]["verdict"] == "not confirmed"
        assert (out["R-c"]["verdict"], out["R-d"]["verdict"]) == ("not judged", "not judged")
        assert out["R-c"]["checks"][0]["tost_p"] is None

    def test_w_moving_with_the_load_fails_the_equivalence(self):
        out = g49.judge(redis(still=(1.0, 1.4, 0.8, 1.3)), draws=0)
        assert out["R-c"]["verdict"] == "not confirmed"

    def test_a_setup_with_no_run_is_out_of_reach(self):
        out = g49.judge([r for r in redis() if r["setup"] == "R2000-redis-d256"], draws=0)
        assert out["R-a"]["out_of_reach"] == ["R2000-redis-d1"]
        assert out["R-a"]["verdict"] == "out of reach"
        assert out["R-d"]["out_of_reach"] == ["R2000-redis-d256"], "its gap setup has no run"
        assert out["R-d"]["checks"][0]["why"] == "no passing run"
        assert out["R-c"]["verdict"] == "confirmed" and out["R-c"]["out_of_reach"] == []


class TestTheShareLeft:
    def test_against_a_gap_that_did_not_rise(self):
        gap = runs("R2000-redis-d1", [dict(W_rise=0.0)])
        remedy = runs("R2000-redis-d256", [dict(W_rise=5.0)])
        assert g49.left_share(remedy, gap, "W_rise") is None
        assert g49.left_share(remedy, runs("R2000-redis-d1", [{}]), "W_rise") is None
        assert g49.left_interval(remedy, gap, "W_rise", 5) == (None, None, 5)

    def test_its_interval_resamples_each_setups_runs(self):
        gap = runs("R2000-redis-d1", [dict(W_rise=r) for r in (1000.0, 2000.0)])
        remedy = runs("R2000-redis-d256", [dict(W_rise=r) for r in (10.0, 30.0)])
        low, high, undefined = g49.left_interval(remedy, gap, "W_rise", 400)
        assert (low, high, undefined) == (pytest.approx(10.0 / 2000.0), pytest.approx(
            30.0 / 1000.0), 0), ("the extremes come up one draw in sixteen each: both of the "
                                 "remedy's runs its least and both of the gap's its largest, "
                                 "and the other way")
        assert g49.left_share(remedy, gap, "W_rise") == pytest.approx(20.0 / 1500.0)


class TestNatsAndRabbitmq:
    def rows(self, **rabbit):
        return (runs("J2000-nats-d256", [dict(WAITING, W_ratio=w, D_own_ratio=5.0)
                                         for w in STILL], depth=256, consumer="python")
                + runs("J2000-nats-go", [dict(WAITING, W_ratio=w, D_own_ratio=1.2)
                                         for w in STILL], consumer="nats-go", depth=1)
                + runs("G2000-rabbitmq-p1000",
                       [dict(WAITING, b_checks="False", certified_share=1.0, W_ratio=w,
                             D_own_ratio=20.0, **rabbit) for w in STILL], prefetch=1000))

    def test_nats_held_still_but_one_setups_d_did_not_grow(self):
        out = g49.judge(self.rows(), draws=0)
        assert out["J-a"]["verdict"] == "confirmed"
        assert sorted(c["setup"] for c in out["J-a"]["checks"]) == ["J2000-nats-d256",
                                                                    "J2000-nats-go"]
        held = dict((c["setup"], c["holds"]) for c in out["J-b"]["checks"])
        assert held == {"J2000-nats-d256": True, "J2000-nats-go": False}
        assert out["J-b"]["verdict"] == "not confirmed"

    def test_a_nats_setup_with_no_run_is_said_out_of_reach(self):
        rows = [r for r in self.rows() if r["setup"] != "J2000-nats-go"]
        out = g49.judge(rows, draws=0)
        assert (out["J-a"]["verdict"], out["J-a"]["out_of_reach"]) == ("confirmed",
                                                                       ["J2000-nats-go"])

    def test_rabbitmq_certified_at_the_wide_bound(self):
        out = g49.judge(self.rows(), draws=0)
        cell = out["G-a"]["checks"][0]
        assert (cell["b_ms"], cell["runs_checked"], cell["certified"], cell["holds"]) == (
            gm.CERTIFY_B_WIDE_MS, [True] * 4, 1.0, True)
        assert cell["certified_10ms"] is None, "its checks fail at 10 ms"
        assert cell["silence_max_us"] == [6000.0] * 4
        assert out["G-b"]["verdict"] == "confirmed"

    def test_rabbitmq_whose_checks_fail_even_at_the_wide_bound(self):
        out = g49.judge(self.rows(b_checks_50ms="False"), draws=0)
        assert (out["G-a"]["verdict"], out["G-a"]["checks"][0]["client_held"]) == (
            "out of reach", None)
        assert out["G-b"]["verdict"] == "not judged"


class TestKafka:
    def test_the_clients_part_grows_and_the_broker_thread_takes_it_out(self):
        out = g49.judge(kafka("Q") + kafka("Z", unwaited=(0.01, 0.005)), draws=50)
        for b in ("Q", "Z"):
            problem = out[b + "-a"]["checks"][0]
            assert (out[b + "-a"]["verdict"], problem["WF_own_ratio"],
                    problem["WF_own_tail_on"]) == ("confirmed", 40.0, 3100.0)
            left = out[b + "-b"]["checks"][0]
            assert (out[b + "-b"]["verdict"], left["left"], left["against"],
                    left["most_us"]) == ("confirmed", pytest.approx(20.0 / 3000.0),
                                         b + "2000-kafka-rdk", ph.RESOLUTION_US)
        trip = out["Q-c"]["checks"][0]
        assert (out["Q-c"]["verdict"], trip["unwaited_on"], trip["unwaited_off"]) == (
            "confirmed", 0.6, 0.8)
        assert trip["described"]["g_us"] == 600.0
        arm = out["described"]["round_trip_arm"]
        assert [(c["setup"], c["holds"]) for c in arm] == [("Z2000-kafka-rdk-rt", False)], (
            "on the Arm pair the round trip is described only")

    def test_no_growth_at_normal_priority_and_too_much_left(self):
        out = g49.judge(kafka("Q", normal_ratio=1.3) + kafka("Z", rt_rise=600.0), draws=0)
        assert (out["Q-a"]["verdict"], out["Q-b"]["verdict"]) == ("not confirmed",
                                                                  "not judged")
        assert (out["Z-a"]["verdict"], out["Z-b"]["verdict"]) == ("confirmed",
                                                                  "not confirmed")

    def test_within_a_tenth_but_above_the_checks_resolution(self):
        out = g49.judge(kafka("Q", normal_rise=30000.0, rt_rise=-60.0), draws=0)
        cell = out["Q-b"]["checks"][0]
        assert (cell["left"], cell["holds"]) == (pytest.approx(-0.002), False), (
            "a fall of 60 us is more than the 50 us the check reads to")

    def test_fetches_waiting_in_one_state(self):
        out = g49.judge(kafka("Q", unwaited=(0.45, 0.8)), draws=0)
        assert out["Q-c"]["verdict"] == "not confirmed"
        assert out["Z-a"]["verdict"] == "out of reach", "no run of the Arm pair"
        assert out["Z-a"]["out_of_reach"] == ["Z2000-kafka-rdk"]


class TestTheWholeJudgment:
    def test_every_prediction_the_described_setups_and_the_runs_left_out(self):
        rows = (redis() + TestNatsAndRabbitmq().rows() + kafka("Q") + kafka("Z")
                + runs("Q2000-kafka-rdk", [dict(m1b_missed=1)], consumer="confluent"))
        out = g49.judge(rows, draws=20)
        assert sorted(out) == sorted(g49.PREDICTIONS + ("described",))
        assert [s["setup"] for s in out["described"]["setups"]] == [
            "G2000-rabbitmq-p1000", "J2000-nats-d256", "J2000-nats-go", "Q2000-kafka-rdk",
            "Q2000-kafka-rdk-rt", "R2000-redis-d1", "R2000-redis-d256", "Z2000-kafka-rdk",
            "Z2000-kafka-rdk-rt"]
        assert out["described"]["setups"][6]["W_rise"] == 7.5
        assert set(g49.DESCRIBED) <= set(out["described"]["setups"][0])
        assert [x["run"] for x in out["described"]["left_out"]] == ["Q2000-kafka-rdk_r0"]
        assert all(out[p]["verdict"] == "confirmed" for p in g49.PREDICTIONS
                   if p != "J-b"), "nats.go's D did not grow in these rows"

    def test_a_cell_in_another_block_is_left_out(self):
        verdict = {"checks": [{"setup": "a", "block": "R", "holds": True},
                              {"setup": "b", "block": "J", "holds": False}]}
        assert g49._in_block(verdict, "R")["verdict"] == "confirmed"


def v47(setup, values, **fields):
    """Version 47's rows of a setup, as its table holds them."""
    block = setup[0]
    return [dict(r, block=block, arch=ARM if block == "A" else X86) for r in runs(
        setup, values, **fields)]


def table47():
    still = [dict(WAITING, W_tail_on=1000.0 * w, W_tail_off=1000.0, W_ratio=w,
                  W_rise=1000.0 * (w - 1.0), D_own_tail_on=4000.0, D_own_tail_off=1000.0,
                  D_own_ratio=4.0) for w in STILL]
    gap = dict(W_tail_on=3000.0, W_tail_off=1500.0, W_ratio=2.0, W_rise=1500.0)
    normal = dict(WF_own_tail_on=3000.0, WF_own_tail_off=60.0, WF_own_ratio=50.0,
                  WF_own_rise=2940.0)
    rt = dict(WF_own_tail_on=70.0, WF_own_tail_off=55.0, WF_own_ratio=70.0 / 55.0,
              WF_own_rise=15.0, broker_unwaited_share_on=0.6, broker_unwaited_share_off=0.8)
    return (v47("V2000-redis-d1", [gap] * 4, depth=1)
            + v47("V2000-redis-d256", still, depth=256)
            + v47("V2000-redis-d256-lib", still, depth=256)
            + v47("N2000-nats-d256", still, depth=256, consumer="python")
            + v47("N2000-nats-go", still, consumer="nats-go")
            + v47("P2000-rabbitmq-p1000", [dict(s, b_checks="False") for s in still],
                  prefetch=1000)
            + v47("K2000-kafka-rdk", [normal] * 4, consumer="confluent")
            + v47("K2000-kafka-rdk-rt", [rt] * 4, consumer="confluent", fetch_rt=True)
            + v47("A2000-kafka-rdk", [normal] * 4, consumer="confluent")
            + v47("A2000-kafka-rdk-rt", [rt] * 4, consumer="confluent", fetch_rt=True)
            + v47("V2000-redis-d1-pilot", [gap], pilot=True, depth=1))


class TestTheRounds:
    def test_version_47s_runs_by_this_versions_names(self):
        found = g49.from47(table47())
        assert sorted(found) == sorted(g49.FROM47.values())
        assert all(len(r) == 4 for r in found.values()), "the pilot's run and V-lib left out"
        first = found["Z2000-kafka-rdk-rt"][0]
        assert (first["setup"], first["block"], first["arch"]) == ("Z2000-kafka-rdk-rt", "Z",
                                                                  ARM)

    def test_made_up_runs_draw_the_tails_judged_and_each_runs_checks(self):
        found = g49.profiles(g49.from47(table47()))
        base, cv, runs47 = found["G2000-rabbitmq-p1000"]
        assert base["W_tail_on"] == pytest.approx(1005.0) and len(runs47) == 4
        rows = g49.made_up_block(random.Random(3), found, 2)
        assert len(rows) == 2 * len(found)
        rabbit = [r for r in rows if r["setup"] == "G2000-rabbitmq-p1000"]
        assert all(r["b_checks"] == "False" and r["b_checks_50ms"] == "True" for r in rabbit)
        assert rabbit[0]["W_tail_on"] != base["W_tail_on"]
        assert rabbit[0]["W_ratio"] == pytest.approx(rabbit[0]["W_tail_on"]
                                                     / rabbit[0]["W_tail_off"])
        assert rabbit[0]["D_own_rise"] == pytest.approx(rabbit[0]["D_own_tail_on"]
                                                        - rabbit[0]["D_own_tail_off"])
        assert g49.instrument_holds(rabbit[0]) is True, "the instrument's checks as run"
        pilot = g49.made_up_block(random.Random(3), found, 1, mode="pilot")
        assert len(pilot) == len(found)

    def test_the_checks_drawn_from_the_setups_own_runs(self):
        runs47 = g49.from47(v47("P2000-rabbitmq-p1000", [dict(WAITING, b_checks_50ms=v)
                                                         for v in ("True", "False")],
                                prefetch=1000))
        found = g49.profiles(runs47)
        drawn = [r["b_checks_50ms"] for r in g49.made_up_block(random.Random(5), found, 60)]
        assert set(drawn) == {"True", "False"}

    def test_what_version_47s_own_runs_confirm(self):
        clear = g49.clears(g49.from47(table47()))
        assert set(clear) == set(g49.PREDICTIONS)
        assert clear["R-a"] and clear["Q-b"] and clear["Z-b"] and clear["Q-c"]
        assert clear["G-a"], "RabbitMQ's checks fail at 10 ms in this table, and hold at 50 ms"

    def test_power_and_the_rule(self):
        runs47 = g49.from47(table47())
        found = g49.profiles(runs47)
        at = g49.power(found, 4, 20, 1)
        assert set(at) == set(g49.PREDICTIONS) and at["R-a"] == 1.0 and at["Q-b"] == 1.0
        rounds, at, wanted, unreachable = g49.rounds_needed(runs47, 10, 1, most=5)
        assert 4 <= rounds <= 5 and "R-a" in wanted and set(at) == set(g49.PREDICTIONS)
        assert set(unreachable) <= set(wanted)

    def test_the_verdicts_are_the_judges(self):
        rows = redis()
        assert g49.verdicts(rows)["R-a"] == g49.judge(rows, draws=0)["R-a"]["verdict"]


class TestTheCommandLine:
    def write(self, path, rows):
        fields = sorted(set(k for r in rows for k in r))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    def test_read_then_judge(self, tmp_path, capsys):
        folder = tmp_path / "runs"
        folder.mkdir()
        tgm.redis_world(folder, "law_g49r_r1", setup="R2000-redis-d1")
        tgm.redis_world(folder, "law_v1")
        tgm.redis_world(folder, "law_g49r_f1", setup="R2000-redis-d1", verdict="fail")
        allowance = tmp_path / "allowance.json"
        allowance.write_text(json.dumps(tgm.ALLOWANCE), encoding="utf-8")
        table = str(tmp_path / "runs.csv")
        assert g49.main(["read", "--runs", str(folder), "--driver", tgm.DRIVER, "--broker",
                         tgm.BROKER, "--receiver", tgm.RECEIVER, "--allowance", str(allowance),
                         "--out-runs", table, "--warmup", "0"]) == 0
        said = capsys.readouterr().out
        assert "OK 1 runs of plan version 49 ->" in said and "left out law_g49r_f1: fail" in said
        rows = gm.read_table(table)
        assert [(r["run"], r["block"], r["depth"]) for r in rows] == [("law_g49r_r1", "R", 1)]
        assert rows[0]["WF_own_rise"] == "280.0"
        out = str(tmp_path / "verdicts.json")
        assert g49.main(["judge", "--runs-table", table, "--out", out, "--draws", "10"]) == 0
        assert "R-a: confirmed" in capsys.readouterr().out, "W's tail rose 1.5 times"
        with open(out, encoding="utf-8") as fh:
            assert json.load(fh)["R-a"]["checks"][0]["W_ratio"] == pytest.approx(1.5)
        self.write(table, [dict(r, m1b_missed=2) for r in rows])
        assert g49.main(["judge", "--runs-table", table, "--out", out, "--draws", "0"]) == 0
        assert "left out law_g49r_r1 (R2000-redis-d1): its instrument" in (
            capsys.readouterr().out)

    def test_reading_several_runs_at_a_time(self, tmp_path, monkeypatch):
        folder = tmp_path / "runs"
        folder.mkdir()
        tgm.redis_world(folder, "law_g49r_r1", setup="R2000-redis-d1")
        tgm.redis_world(folder, "law_g49r_r2", setup="R2000-redis-d256")

        class Pool:
            def __init__(self, max_workers):
                self.workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def map(self, job, jobs):
                return [job(j) for j in jobs]
        monkeypatch.setattr(g49, "ProcessPoolExecutor", Pool)
        rows, skipped = g49.read_block([str(folder)], tgm.DRIVER, tgm.BROKER, tgm.RECEIVER,
                                       tgm.ALLOWANCE, 0, workers=2)
        assert [r["setup"] for r in rows] == ["R2000-redis-d1", "R2000-redis-d256"]
        assert skipped == []

    def test_the_rounds_from_version_47s_table(self, tmp_path, capsys, monkeypatch):
        table = tmp_path / "v47.csv"
        self.write(str(table), table47())
        out = tmp_path / "power.json"
        assert g49.main(["power", "--runs-table", str(table), "--blocks", "10", "--most", "5",
                         "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "setups: 9, from 36 of version 47's runs" in said
        assert "R-a yes" in said and "with the load's excess halved" in said
        found = json.loads(out.read_text(encoding="utf-8"))
        assert 4 <= found["rounds"] <= 5 and found["bar"] == gp.POWER
        assert found["runs"]["R2000-redis-d1"] == ["V2000-redis-d1_r%d" % i for i in range(4)]
        monkeypatch.setattr(g49, "rounds_needed", lambda *a: (
            4, dict.fromkeys(g49.PREDICTIONS, 0.1), ["R-c"], ["R-c"]))
        assert g49.main(["power", "--runs-table", str(table), "--blocks", "2",
                         "--spread", "pilot"]) == 0
        assert "no number of rounds up to 12 brings R-c to 0.80" in capsys.readouterr().out
        monkeypatch.setattr(g49, "rounds_needed", lambda *a: (
            4, dict.fromkeys(g49.PREDICTIONS, 0.9), ["R-a"], []))
        assert g49.main(["power", "--runs-table", str(table), "--blocks", "2"]) == 0
        assert "no number of rounds" not in capsys.readouterr().out

    def test_a_table_without_version_47s_setups(self, tmp_path, capsys):
        table = tmp_path / "other.csv"
        self.write(str(table), runs("R2000-redis-d1", [{}]))
        assert g49.main(["power", "--runs-table", str(table)]) == 1
        assert "no run of version 47's setups" in capsys.readouterr().err
