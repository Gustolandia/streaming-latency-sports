"""Tests for scripts/general_method_power.py, the rounds rule for freeze 44's blocks: made-up runs
drawn about a pilot's, judged by the registered judge, and the rule's rounds."""
import csv
import json
import os
import random
import statistics
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "scripts"))

import general_method as gm  # noqa: E402
import general_method_power as gp  # noqa: E402


def pilot(setup, block, backend, **fields):
    row = {"run": setup + "_r1", "setup": setup, "block": block, "backend": backend,
           "rate": 2000, "pilot": True, "arch": "x86_64"}
    row.update(fields)
    return row


def kafka_python(on, off, **more):
    """A pilot run of an in-poll client at normal priority, whose turnaround's tail rose from
    `off` to `on`: KC-a's one cell."""
    return pilot("K2000-kafka-python-pilot", "K", "kafka", consumer="kafka-python",
                 Tc_tail_on=on, Tc_tail_off=off, Tc_ratio=on / off, Tc_rise=on - off,
                 m1b_missed=0, m1b_differ=0, **more)


class TestThePilotsValues:
    def test_only_the_pilots_runs_by_the_judged_name(self):
        rows = [kafka_python(3000.0, 1000.0),
                dict(kafka_python(3000.0, 1000.0), run="x", pilot=False),
                dict(kafka_python(2000.0, 1000.0), run="K2000-kafka-python-pilot_r2",
                     pilot="True")]
        found = gp.pilot_setups(rows)
        assert list(found) == ["K2000-kafka-python"] and len(found["K2000-kafka-python"]) == 2
        assert gp.setup_name("V2000-redis-d1") == "V2000-redis-d1"

    def test_means_spreads_and_the_settings_kept(self):
        runs = [kafka_python(3000.0, 1000.0, depth="256", fetch_rt=False, b_checks="True"),
                kafka_python(1000.0, 1000.0, depth="256", fetch_rt=False, b_checks="True",
                             q_p99="")]
        base, cv = gp.profile(runs)
        assert base["Tc_tail_on"] == 2000.0 and cv["Tc_tail_on"] == pytest.approx(0.5)
        assert cv["Tc_tail_off"] == 0.0
        assert base["depth"] == "256" and base["fetch_rt"] is False and "fetch_rt" not in cv
        assert base["b_checks"] == "True" and "b_checks" not in cv
        assert base["setup"] == "K2000-kafka-python-pilot"
        assert gp.spread([1.0]) is None and gp.spread([1.0, None]) is None
        assert gp.spread([-1.0, 1.0]) is None
        assert gp._number("x") is None and gp._number("None") is None
        assert gp._number(object()) is None and gp._number("2.5") == 2.5

    def test_which_readings_are_shares(self):
        assert gp.is_share("broker_waiting_share") and gp.is_share("broker_none_share_on")
        assert gp.is_share("certified_share_2ms") and not gp.is_share("W_tail_on")

    def test_the_ratios_spread_where_a_setup_ran_more_than_once(self):
        profiles = {"a": ({}, {"W_ratio": 0.1, "Tc_ratio": None}), "b": ({}, {"W_ratio": 0.3}),
                    "c": ({}, {})}
        assert gp.ratio_spreads(profiles) == {"W": pytest.approx(0.2)}


class TestTheDraws:
    def test_the_lognormal_keeps_its_mean_its_sign_and_a_zero(self):
        rng = random.Random(1)
        values = [gp.draw(rng, 100.0, 0.25) for _ in range(20000)]
        assert statistics.fmean(values) == pytest.approx(100.0, rel=0.01)
        assert statistics.pstdev(values) / 100.0 == pytest.approx(0.25, rel=0.05)
        assert gp.draw(rng, 0.0, 0.25) == 0.0 and gp.draw(rng, -5.0, 0.25) < 0

    def test_a_made_up_runs_tails_ratios_and_rises_agree(self):
        base, cv = gp.profile([kafka_python(3000.0, 1000.0, W_tail_on=900.0, W_tail_off=1000.0,
                                            E2_tail_on=800.0, E2_tail_off=700.0,
                                            e2_share=0.5)])
        run = gp.made_up_run(random.Random(2), base, cv, 3)
        assert run["pilot"] is False and run["setup"] == "K2000-kafka-python"
        assert run["run"] == "K2000-kafka-python_m3"
        assert run["Tc_ratio"] == pytest.approx(run["Tc_tail_on"] / run["Tc_tail_off"])
        assert run["Tc_rise"] == pytest.approx(run["Tc_tail_on"] - run["Tc_tail_off"])
        assert run["Tc_tail_on"] != 3000.0 and run["m1b_missed"] == 0
        assert "waiting_W_ratio" not in run, "a tail the pilot lacks stays missing"
        # E2's share follows the drawn tails, and has none where W's tail did not rise.
        if run["W_tail_on"] > run["W_tail_off"]:
            assert run["e2_share"] == pytest.approx(1.0 - (run["E2_tail_on"] - run["E2_tail_off"])
                                                    / (run["W_tail_on"] - run["W_tail_off"]))
        flat = dict(base, W_tail_on=100.0, W_tail_off=1000.0)
        assert gp.made_up_run(random.Random(2), flat, {}, 0)["e2_share"] is None

    def test_each_state_at_version_45s_least_spread(self):
        base, cv = gp.profile([kafka_python(3000.0, 1000.0)])
        rng = random.Random(9)
        runs = [gp.made_up_run(rng, base, cv, i) for i in range(4000)]
        for state, least in (("on", gp.LOAD_CV), ("off", gp.IDLE_CV)):
            values = [r["Tc_tail_" + state] for r in runs]
            assert statistics.pstdev(values) / statistics.fmean(values) == pytest.approx(
                least, rel=0.08)
        wide, wcv = gp.profile([kafka_python(3000.0, 1000.0), kafka_python(6000.0, 1000.0)])
        values = [gp.made_up_run(rng, wide, wcv, i)["Tc_tail_on"] for i in range(4000)]
        assert statistics.pstdev(values) / statistics.fmean(values) == pytest.approx(
            wcv["Tc_tail_on"], rel=0.08), "a pilot's own wider spread is kept"

    def test_shares_stay_shares_and_signed_readings_keep_their_sign(self):
        base = pilot("V2000-redis-d256-pilot", "V", "redis", broker_waiting_share=0.9995,
                     broker_none_share=0.2, cap_calibrated_none_share="", q_p99=40.0,
                     m1_tail_diff=-3.0, b_checks="True", one_reply=True, W_p99=900.0)
        rng = random.Random(3)
        for i in range(500):
            run = gp.made_up_run(rng, base, {}, i)
            assert 0.0 <= run["broker_waiting_share"] <= 1.0
            assert 0.0 <= run["broker_none_share"] <= 1.0
            assert run["m1_tail_diff"] < 0 and run["q_p99"] > 0
            assert run["W_p99"] == 900.0 and run["cap_calibrated_none_share"] == ""
            assert run["one_reply"] is True and run["b_checks"] == "True"
        near = [gp.made_up_run(rng, base, {}, i)["broker_waiting_share"] for i in range(2000)]
        assert statistics.fmean(1.0 - s for s in near) == pytest.approx(0.0005, rel=0.05)

    def test_a_smaller_effect_moves_the_on_block_toward_the_off_block(self):
        base, cv = gp.profile([kafka_python(3000.0, 1000.0)])
        rng = random.Random(4)
        halved = [gp.made_up_run(rng, base, cv, i, scale=0.5)["Tc_tail_on"] for i in range(4000)]
        assert statistics.fmean(halved) == pytest.approx(2000.0, rel=0.02)

    def test_the_pilots_own_spread_holds_a_ratio_within_a_run(self):
        base, cv = gp.profile([kafka_python(3000.0, 1000.0), kafka_python(3300.0, 1100.0)])
        assert cv["Tc_ratio"] == pytest.approx(0.0, abs=1e-12)
        rng = random.Random(5)
        runs = [gp.made_up_run(rng, base, cv, i, mode="pilot") for i in range(2000)]
        ratios = [r["Tc_ratio"] for r in runs]
        assert statistics.pstdev(ratios) / statistics.fmean(ratios) == pytest.approx(
            gp.PILOT_CV_FLOOR, rel=0.1)
        offs = [r["Tc_tail_off"] for r in runs]
        assert statistics.pstdev(offs) / statistics.fmean(offs) == pytest.approx(gp.IDLE_CV,
                                                                                 rel=0.1)
        # A setup that ran once takes the median spread of those that ran more than once.
        once, cv1 = gp.profile([kafka_python(3000.0, 1000.0)])
        ratios = [gp.made_up_run(rng, once, cv1, i, mode="pilot", ratio_cv={"Tc": 0.2})
                  ["Tc_ratio"] for i in range(4000)]
        assert statistics.pstdev(ratios) / statistics.fmean(ratios) == pytest.approx(0.2,
                                                                                    rel=0.1)
        alone = [gp.made_up_run(rng, once, cv1, i, mode="pilot")["Tc_ratio"] for i in range(10)]
        assert all(r == pytest.approx(3.0, rel=0.2) for r in alone)
        zero = dict(once, Tc_tail_off=0.0)
        assert gp.made_up_run(rng, zero, cv1, 0, mode="pilot")["Tc_tail_on"] == 3000.0

    def test_only_the_tails_asked_for_are_drawn(self):
        base, cv = gp.profile([kafka_python(3000.0, 1000.0, W_tail_on=2.0, W_tail_off=1.0,
                                            W_ratio=2.0)])
        run = gp.made_up_run(random.Random(1), base, cv, 0, tails=("W",))
        assert run["Tc_tail_on"] == 3000.0 and run["Tc_ratio"] == 3.0, "not drawn"
        assert run["W_tail_on"] != 2.0 and run["W_ratio"] == pytest.approx(
            run["W_tail_on"] / run["W_tail_off"])
        twice = dict(kafka_python(3000.0, 1000.0), W_ratio=2.0)
        spreads = gp.ratio_spreads({"a": gp.profile([twice, dict(twice, W_ratio=4.0)])},
                                   tails=("W",))
        assert spreads == {"W": pytest.approx(1.0 / 3.0)}

    def test_a_block_has_its_rounds_of_every_setup(self):
        profiles = {"K2000-kafka-python": gp.profile([kafka_python(3000.0, 1000.0)]),
                    "V2000-redis-d1": gp.profile([pilot("V2000-redis-d1-pilot", "V", "redis")])}
        rows = gp.made_up_block(random.Random(6), profiles, 3)
        assert sorted(r["run"] for r in rows) == sorted(
            ["K2000-kafka-python_m%d" % i for i in range(3)]
            + ["V2000-redis-d1_m%d" % i for i in range(3)])
        assert len(gp.made_up_block(random.Random(6), profiles, 2, mode="pilot")) == 4


class TestTheJudgeOnMadeUpBlocks:
    def profiles(self, on):
        return {"K2000-kafka-python": gp.profile([kafka_python(on, 1000.0)])}

    def test_the_pilots_own_values_clear_a_margin_or_do_not(self):
        assert gp.clears(self.profiles(3000.0))["KC-a"] is True
        assert gp.clears(self.profiles(1200.0))["KC-a"] is False
        assert gp.clears(self.profiles(3000.0))["M1-b"] is True
        assert gp.clears(self.profiles(3000.0))["C-a"] is False, "no block C: out of reach"

    def test_a_large_effect_is_confirmed_in_every_block_and_none_in_none(self):
        strong = gp.power(self.profiles(6000.0), 4, 60, 7)
        assert strong["KC-a"] == 1.0 and strong["M1-b"] == 1.0
        assert strong["M3-a"] == 0.0, "no setup it reaches"
        assert gp.power(self.profiles(1000.0), 4, 60, 7)["KC-a"] < 0.2
        assert gp.power(self.profiles(6000.0), 4, 60, 7) == strong, "the seed fixes the blocks"

    def test_a_smaller_effect_lowers_the_power(self):
        full = gp.power(self.profiles(1800.0), 4, 200, 8)["KC-a"]
        half = gp.power(self.profiles(1800.0), 4, 200, 8, scale=0.5)["KC-a"]
        assert 0.3 < full < 1.0 and half < full

    def test_the_verdicts_are_the_judges(self):
        rows = [dict(kafka_python(3000.0, 1000.0), pilot=False, setup="K2000-kafka-python")]
        assert gp.verdicts(rows)["KC-a"] == gm.judge(rows, draws=0)["KC-a"]["verdict"]
        assert set(gp.verdicts(rows)) == set(gp.PREDICTIONS)


class TestTheRule:
    def rule(self, monkeypatch, clear, table):
        monkeypatch.setattr(gp, "clears", lambda profiles: {
            **dict.fromkeys(gp.PREDICTIONS, False), **clear})
        asked = []

        def power(profiles, rounds, blocks, seed, mode="rule", scale=1.0):
            asked.append(rounds)
            out = dict.fromkeys(gp.PREDICTIONS, 0.0)
            out.update(table(rounds))
            return out
        monkeypatch.setattr(gp, "power", power)
        return asked

    def test_four_where_every_clearing_prediction_reaches_the_bar(self, monkeypatch):
        asked = self.rule(monkeypatch, {"KC-a": True}, lambda r: {"KC-a": 0.9})
        assert gp.rounds_needed({}, 10, 1) == (4, {**dict.fromkeys(gp.PREDICTIONS, 0.0),
                                                   "KC-a": 0.9}, ["KC-a"], [])
        assert asked == [4]

    def test_more_rounds_where_one_needs_them(self, monkeypatch):
        asked = self.rule(monkeypatch, {"KC-a": True, "M1-b": True},
                          lambda r: {"KC-a": 0.5 + 0.05 * r, "M1-b": 1.0})
        rounds, at, wanted, unreachable = gp.rounds_needed({}, 10, 1)
        assert (rounds, wanted, unreachable) == (6, ["M1-b", "KC-a"], [])
        assert at["KC-a"] == pytest.approx(0.8)
        assert asked == [4, 12, 5, 6]

    def test_up_to_the_most_where_only_the_most_brings_one_to_the_bar(self, monkeypatch):
        asked = self.rule(monkeypatch, {"KC-a": True},
                          lambda r: {"KC-a": 0.8 if r >= 12 else 0.5})
        assert gp.rounds_needed({}, 10, 1)[0] == 12
        assert asked == [4, 12] + list(range(5, 12))

    def test_another_plans_judge_and_predictions(self, monkeypatch):
        monkeypatch.setattr(gp, "power", lambda *a: pytest.fail("version 47's power"))
        monkeypatch.setattr(gp, "clears", lambda *a: pytest.fail("version 47's clears"))
        asked = []

        def power_of(profiles, rounds, blocks, seed, mode="rule"):
            asked.append((rounds, mode))
            return {"X-a": 0.5 + 0.1 * rounds, "X-b": 0.1}
        assert gp.rounds_needed({}, 10, 1, mode="pilot", power_of=power_of,
                                clear={"X-a": True, "X-b": False},
                                predictions=("X-a", "X-b")) == (
            4, {"X-a": pytest.approx(0.9), "X-b": 0.1}, ["X-a"], [])
        assert asked == [(4, "pilot")]

    def test_one_no_rounds_bring_to_the_bar_is_reported_at_the_others_rounds(self,
                                                                               monkeypatch):
        self.rule(monkeypatch, {"KC-a": True, "M3-a": True},
                  lambda r: {"KC-a": 0.85, "M3-a": 0.05 * r})
        rounds, at, wanted, unreachable = gp.rounds_needed({}, 10, 1)
        assert (rounds, unreachable) == (4, ["M3-a"]) and at["M3-a"] == 0.2


class TestTheCommandLine:
    def write(self, path, rows):
        fields = sorted(set(k for r in rows for k in r))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    def test_the_rule_from_a_pilots_table(self, tmp_path, capsys):
        table = tmp_path / "pilot.csv"
        self.write(str(table), [kafka_python(6000.0, 1000.0)])
        out = tmp_path / "power.json"
        assert gp.main(["--pilot-table", str(table), "--blocks", "20", "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "setups: 1, from 1 pilot runs" in said and "the rule asks 4 rounds" in said
        assert "KC-a yes" in said and "with the load's excess halved" in said
        found = json.loads(out.read_text(encoding="utf-8"))
        assert found["rounds"] == 4 and found["power"]["KC-a"] == 1.0
        assert found["bar"] == gp.POWER and found["unreachable"] == []
        assert (found["idle_cv"], found["load_cv"]) == (gp.IDLE_CV, gp.LOAD_CV)

    def test_one_no_rounds_bring_to_the_bar_is_named(self, tmp_path, capsys, monkeypatch):
        table = tmp_path / "pilot.csv"
        self.write(str(table), [kafka_python(6000.0, 1000.0)])
        monkeypatch.setattr(gp, "rounds_needed", lambda *a: (4, dict.fromkeys(gp.PREDICTIONS,
                                                                              0.1), ["M3-a"],
                                                             ["M3-a"]))
        assert gp.main(["--pilot-table", str(table), "--blocks", "5", "--spread", "pilot"]) == 0
        assert "no number of rounds up to 12 brings M3-a to 0.80" in capsys.readouterr().out

    def test_a_table_without_a_pilot_run(self, tmp_path, capsys):
        table = tmp_path / "judged.csv"
        self.write(str(table), [dict(kafka_python(6000.0, 1000.0), pilot=False)])
        assert gp.main(["--pilot-table", str(table)]) == 1
        assert "no pilot run" in capsys.readouterr().err
