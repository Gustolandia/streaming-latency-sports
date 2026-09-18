"""Tests for scripts/rounds_rule.py.

The rule is what matters here, not the numbers a real campaign will get: that the count climbs
from the floor, stops at the first number with the power the plan asks for, reports a campaign
that cannot reach it as underpowered rather than pretending, and refuses a prediction whose
falsifier the plan never named. The simulations are tiny on purpose -- a handful of made-up
campaigns each -- because a thousand of them take half an hour and say nothing more about the rule.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import rounds_rule as rr  # noqa: E402

#: Few campaigns, few resamplings, a coarse grid: enough to exercise the rule, quick enough to run.
TINY = {"trials": 2, "draws": 20, "grid": 24}
SIX = (1.5, 3.0, 4.5, 6.0, 7.5, 9.0)
DESIGN = {"slices": SIX, "spread": 0.05, "plateau": 0.30, "floor": 0.01}


class TestCountingConfirmations:

    def test_the_law_is_confirmed_and_the_world_where_it_is_false_is_not(self):
        power = rr.confirms("P1", DESIGN, 4, "law", **TINY)
        wrongly = rr.confirms("P1", DESIGN, 4, "cliff_fixed", seed=rr.SEED + 7, **TINY)
        assert power == 1.0 and wrongly == 0.0

    def test_the_same_seed_counts_the_same(self):
        assert rr.confirms("P1", DESIGN, 4, "law", **TINY) == \
            rr.confirms("P1", DESIGN, 4, "law", **TINY)


class TestTheRuleItself:

    def test_it_stops_at_the_first_number_with_enough_power(self):
        found = rr.rounds_for("P1", DESIGN, **TINY)
        assert found["rounds"] == 4 and found["underpowered"] is False
        assert len(found["tried"]) == 1, "a campaign with power at the floor asks no more"
        assert found["tried"][0]["power"] >= rr.POWER

    def test_it_never_goes_below_the_floor(self):
        found = rr.rounds_for("P1", DESIGN, steps=(1, 2, 4), **TINY)
        assert found["tried"][0]["rounds"] == rr.FLOOR

    def test_a_campaign_that_cannot_reach_the_power_runs_at_the_ceiling(self):
        """A plateau this low leaves no cliff to find, so no number of rounds confirms it."""
        flat = dict(DESIGN, plateau=0.011, spread=0.6)
        found = rr.rounds_for("P1", flat, steps=(4, 6), **TINY)
        assert found["rounds"] == rr.CEILING and found["underpowered"] is True
        assert [step["rounds"] for step in found["tried"]] == [4, 6]

    def test_it_records_what_it_was_run_with(self):
        found = rr.rounds_for("P1", DESIGN, **TINY)
        assert found["settings"] == {"trials": 2, "draws": 20, "grid": 24, "seed": rr.SEED}
        assert found["asked_of_it"] == {"power": 0.8, "false_confirm": 0.05}

    def test_a_prediction_with_no_falsifier_named_is_refused(self):
        with pytest.raises(ValueError, match="no falsifier named for P6"):
            rr.rounds_for("P6", DESIGN, **TINY)

    @pytest.mark.parametrize("prediction,world", sorted(rr.FALSIFIERS.items()))
    def test_every_falsifier_names_a_world_that_exists(self, prediction, world):
        assert world in __import__("law_world").WORLDS


class TestWhereTheNumberIsFixedInstead:

    @pytest.mark.parametrize("campaign,rounds", [("C0", 2), ("S0-1", 4), ("B0", 3), ("P0", 5),
                                                 ("M0", 10), ("tools", 4)])
    def test_the_plan_fixes_it_and_nothing_is_simulated(self, campaign, rounds):
        found = rr.fixed_rounds(campaign)
        assert found["rounds"] == rounds and found["underpowered"] is False
        assert "no prediction is tested" in found["why"]

    def test_a_campaign_that_does_test_a_prediction_is_not_in_the_list(self):
        with pytest.raises(ValueError, match="not a campaign with a fixed number"):
            rr.fixed_rounds("A1")


class TestHowItReads:

    def test_the_answer_reads_as_it_is_written_into_a_log(self):
        said = "\n".join(rr.lines(rr.rounds_for("P1", DESIGN, **TINY)))
        assert said.startswith("P1: 4 rounds")
        assert "4 rounds: confirmed in 100% under the law, in 0% where it is false" in said
        assert "at least 80% power, at most 5% false" in said and "seed" in said

    def test_an_underpowered_answer_says_so(self):
        flat = dict(DESIGN, plateau=0.011, spread=0.6)
        said = "\n".join(rr.lines(rr.rounds_for("P1", flat, steps=(4,), **TINY)))
        assert "reported as underpowered" in said

    def test_a_fixed_number_reads_in_one_line(self):
        assert rr.lines(rr.fixed_rounds("B0")) == [
            "B0 runs 3 rounds: no prediction is tested, so the plan fixes the number"]


class TestTheCommand:

    def run(self, argv):
        out = io.StringIO()
        return rr.main(argv, out=out), out.getvalue()

    def test_it_simulates_a_campaign_and_can_write_the_answer(self, tmp_path):
        where = str(tmp_path / "rounds.json")
        code, said = self.run(["for", "--prediction", "P1", "--slices", "1.5,3.0,4.5,6.0,7.5,9.0",
                               "--spread", "0.05", "--trials", "2", "--draws", "20",
                               "--grid", "24", "--out", where])
        assert code == 0 and said.startswith("P1: 4 rounds")
        with open(where, encoding="utf-8") as fh:
            assert json.load(fh)["rounds"] == 4

    def test_the_steps_it_tries_can_be_named(self):
        code, said = self.run(["for", "--prediction", "P1", "--slices", "1.5,3.0,4.5",
                               "--spread", "0.6", "--plateau", "0.011", "--trials", "2",
                               "--draws", "20", "--grid", "24", "--steps", "4,8"])
        assert code == 0 and "40 rounds" in said and "8 rounds: confirmed" in said

    def test_a_campaign_with_loads_cores_priorities_and_languages(self):
        code, said = self.run(["for", "--prediction", "P4", "--priorities", "--loads", "50,88",
                               "--cores", "2,4", "--languages", "--fixed-at", "2.5",
                               "--session-shift", "--spread", "0.05", "--trials", "1",
                               "--draws", "10", "--grid", "24", "--steps", "4"])
        assert code == 0 and said.startswith("P4:")

    def test_the_fixed_numbers_need_no_simulation(self):
        code, said = self.run(["fixed", "--campaign", "P0"])
        assert code == 0 and said.strip() == ("P0 runs 5 rounds: no prediction is tested, so the "
                                              "plan fixes the number")

    def test_a_prediction_it_has_no_falsifier_for_is_an_error_line(self):
        code, said = self.run(["for", "--prediction", "P6", "--trials", "1", "--draws", "10"])
        assert code == 2 and said.startswith("ERROR: no falsifier named for P6")
