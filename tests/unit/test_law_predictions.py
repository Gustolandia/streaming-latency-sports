"""Tests for scripts/law_predictions.py, in a world where the law holds and worlds where it fails.

Every prediction is asked twice: once of runs made up under the law, where the answer must be
yes, and once of runs made up in the world its own falsifier names, where the answer must be no.
That is the same pair of worlds the rounds rule counts in, so a rule that could not tell them
apart here would be caught before any machine ran.

The made-up runs are small and the resamplings few: these tests ask whether each rule reads its
numbers and applies its sentence, not how much power a campaign has.
"""
import io
import json
import math
import statistics as st
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_predictions as lp  # noqa: E402
import law_world as lw  # noqa: E402
import law_design as ld  # noqa: E402
import rounds_rule as rr  # noqa: E402

#: Few draws and a coarse grid: these tests read rules, not power.
QUICK = {"draws": 80, "seed": 1, "grid": 24}
SIX = (1.5, 3.0, 4.5, 6.0, 7.5, 9.0)


class TestTheSmallPrints:

    @pytest.mark.parametrize("value,answer", [(0.9, True), (0.8, True), (1.2, True),
                                              (1.21, False), (None, False)])
    def test_inside_a_band_includes_its_edges(self, value, answer):
        assert lp.inside(value, 0.8, 1.2) is answer

    @pytest.mark.parametrize("span,answer", [((3.0, 4.0), True), ((1.0, 2.5), True),
                                             ((1.0, 2.4), False), ((None, None), False)])
    def test_an_interval_overlaps_a_band_when_they_share_ground(self, span, answer):
        assert lp.overlaps(span, 2.5, 5.5) is answer

    def test_an_interval_excludes_what_it_does_not_reach(self):
        assert lp.excludes((2.0, 3.0), 1.0) is True
        assert lp.excludes((2.0, 3.0), 2.5) is False
        assert lp.excludes((None, None), 1.0) is False

    def test_above_is_the_whole_interval_above(self):
        assert lp.above((2.1, 3.0), 2.0) is True
        assert lp.above((1.9, 3.0), 2.0) is False
        assert lp.above((None, None), 2.0) is False

    def test_a_straight_line_needs_two_different_places(self):
        assert lp.straight_line([1.0, 2.0], [2.0, 4.0]) == (pytest.approx(2.0), pytest.approx(0.0))
        assert lp.straight_line([1.0], [2.0]) is None
        assert lp.straight_line([1.0, 1.0], [2.0, 3.0]) is None
        assert lp.straight_line([1.0, 2.0, 3.0], [2.0, None, 6.0])[0] == pytest.approx(2.0)


class TestThePValueAndHolm:

    def test_a_resampling_far_from_the_null_gives_the_smallest_it_can(self):
        assert lp.p_value([2.0] * 100, 1.0) == pytest.approx(0.01), "one draw's worth, not zero"

    def test_a_resampling_astride_the_null_gives_a_large_one(self):
        assert lp.p_value([0.5, 1.5, 0.5, 1.5], 1.0) == pytest.approx(1.0)

    def test_nothing_drawn_is_no_p_value(self):
        assert lp.p_value([None, None], 1.0) is None

    def test_holm_corrects_a_family_in_order(self):
        found = lp.holm({"P2": 0.001, "P2b": 0.02, "P2c": 0.04})
        assert found["P2"][0] == pytest.approx(0.003) and found["P2"][1] is True
        assert found["P2b"][0] == pytest.approx(0.04) and found["P2b"][1] is True
        assert found["P2c"][0] == pytest.approx(0.04) and found["P2c"][1] is True

    def test_holm_never_lets_a_later_one_look_better_than_an_earlier(self):
        found = lp.holm({"a": 0.03, "b": 0.031})
        assert found["a"][0] == pytest.approx(0.06) and found["a"][1] is False
        assert found["b"][0] == pytest.approx(0.06)

    def test_a_member_without_a_p_value_rejects_nothing(self):
        assert lp.holm({"a": None, "b": 0.001})["a"] == (None, False)


class TestP1TheCliffFollowsTheSlice:

    def test_it_is_confirmed_where_the_law_holds(self):
        runs = lw.campaign(slices=SIX, rounds=4, seed=1)
        found = lp.cliff_follows_slice(runs, 1.0, **QUICK)
        assert found["confirmed"] is True
        for name in lp.SUMMARIES:
            said = found["by_summary"][name]
            assert sum(said["in_band"].values()) >= 5 and lp.inside(said["value"], 0.8, 1.2)

    def test_it_is_not_confirmed_where_the_cliff_stays_put(self):
        """The world its falsifier names: a cliff that does not move with the slice."""
        runs = lw.campaign(slices=SIX, rounds=4, seed=1, world="cliff_fixed", fixed_at=4.0)
        found = lp.cliff_follows_slice(runs, 1.0, **QUICK)
        assert found["confirmed"] is False
        assert all(sum(found["by_summary"][n]["in_band"].values()) < 5 for n in lp.SUMMARIES)

    def test_one_slice_of_six_may_miss_the_band(self):
        runs = lw.campaign(slices=SIX, rounds=4, seed=1)
        found = lp.cliff_follows_slice(runs, 1.0, **QUICK)
        assert "at least 5 of the 6 slices this pair can reach" in found["rule"]

    def test_with_fewer_slices_every_one_must_be_inside(self):
        runs = lw.campaign(slices=(1.5, 3.0, 4.5), rounds=4, seed=1)
        found = lp.cliff_follows_slice(runs, 1.0, need_interval=False, **QUICK)
        assert "at least 3 of the 3 slices this pair can reach" in found["rule"]
        assert found["confirmed"] is True
        assert found["by_summary"]["free"]["p_value"] is None, "P9 asks for no interval"

    def test_a_campaign_with_one_slice_has_no_slope_to_read(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, seed=1)
        found = lp.cliff_follows_slice(runs, 1.0, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["value"] is None


class TestP2TheWidthFollowsTheTick:

    def campaign(self, world="law", ticks=(1.0, 4.0), rounds=4):
        runs = []
        for tick in ticks:
            runs += lw.campaign(slices=(8.0,), rounds=rounds, tick_ms=tick, seed=2, world=world,
                                spread=0.05)
        return runs

    def test_a_longer_tick_gives_a_wider_cliff(self):
        found = lp.width_follows_tick(self.campaign(), 4.0, **QUICK)
        assert found["confirmed"] is True and found["hz"] == 250
        assert all(found["by_summary"][n]["value"] > 1.0 for n in lp.SUMMARIES)

    def test_it_is_not_confirmed_where_the_width_ignores_the_tick(self):
        found = lp.width_follows_tick(self.campaign(world="width_fixed"), 4.0, **QUICK)
        assert found["confirmed"] is False

    def test_the_slowest_kernel_has_a_band_of_its_own(self):
        runs = []
        for tick in (1.0, 10.0):
            runs += lw.campaign(slices=(20.0,), rounds=4, tick_ms=tick, seed=2, spread=0.05)
        found = lp.width_follows_tick(runs, 10.0, **QUICK)
        assert found["hz"] == 100 and "6.0-14.0" in found["rule"]

    def test_without_the_kernel_to_compare_against_there_is_no_ratio(self):
        found = lp.width_follows_tick(self.campaign(ticks=(4.0,)), 4.0, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["fitted"]["value"] is None


class TestP2cTheWidthIsProportionalToTheTick:
    """A slope of one needs widths read finely: the fit's width steps are what it can tell apart,
    and at the coarse grid these quick tests use elsewhere they are 25% apart."""

    FINER = dict(QUICK, grid=48)

    def campaign(self, world="law"):
        runs = []
        for tick in (1.0, 4.0, 10.0):
            runs += lw.campaign(slices=(20.0,), rounds=4, tick_ms=tick, seed=3, world=world,
                                spread=0.05)
        return runs

    def test_a_straight_line_through_zero_with_slope_one(self):
        found = lp.width_against_tick(self.campaign(), **self.FINER)
        assert found["confirmed"] is True and found["judged_on"] == ["fitted"]
        cut = found["by_summary"]["fitted"]["intercept"]
        assert cut[0] <= 0.0 <= cut[1]

    def test_it_is_not_confirmed_where_the_width_ignores_the_tick(self):
        found = lp.width_against_tick(self.campaign(world="width_fixed"), **self.FINER)
        assert found["confirmed"] is False

    def test_one_kernel_alone_has_no_line(self):
        runs = lw.campaign(slices=(20.0,), rounds=4, tick_ms=1.0, seed=3, spread=0.05)
        assert lp.width_against_tick(runs, **self.FINER)["confirmed"] is False


class TestP2dTheTickDoesNotMoveTheStart:

    def test_the_start_stays_at_the_slice_whatever_the_tick(self):
        runs = []
        for tick in (1.0, 4.0):
            runs += lw.campaign(slices=(8.0, 12.0), rounds=4, tick_ms=tick, seed=4, spread=0.02)
        found = lp.start_at_slice(runs, grid=96)
        assert found["confirmed"] is True
        assert all(found["by_summary"]["fitted"]["within"].values())

    def test_a_cliff_that_sits_elsewhere_is_caught(self):
        runs = lw.campaign(slices=(8.0, 12.0), rounds=4, seed=4, spread=0.02,
                           world="cliff_fixed", fixed_at=6.0)
        assert lp.start_at_slice(runs, grid=96)["confirmed"] is False

    def test_no_runs_at_all_confirm_nothing(self):
        assert lp.start_at_slice([])["confirmed"] is False


class TestP3aLoadLeavesTheCliffWhereItIs:
    """An absence is claimed by two one-sided tests: the whole interval of the movement inside
    the band, not the number in the middle of it. Reading the number alone lets a noisy estimate
    claim the cliff stayed put by luck, which is a claim the data has not earned."""

    def test_a_cliff_that_stays_put_is_confirmed(self):
        runs = lw.campaign(slices=(3.0,), rounds=16, loads=(50, 75, 88), seed=5, spread=0.05)
        assert lp.cliff_stays_under_load(runs, **QUICK)["confirmed"] is True

    def test_a_cliff_that_moves_with_load_is_caught(self):
        runs = lw.campaign(slices=(3.0,), rounds=6, loads=(50, 75, 88), seed=5, spread=0.05,
                           world="cliff_moves_with_load")
        assert lp.cliff_stays_under_load(runs, **QUICK)["confirmed"] is False

    def test_an_interval_that_reaches_past_the_band_is_not_a_claim(self):
        """Few rounds and a wide scatter: the cliff did stay put, and the campaign cannot say so."""
        runs = lw.campaign(slices=(3.0,), rounds=4, loads=(50, 75, 88), seed=5, spread=0.6)
        found = lp.cliff_stays_under_load(runs, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["interval"][1] >= lp.HALFWAY_MOVE_MS

    def test_one_load_alone_says_nothing(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, loads=(75,), seed=5)
        assert lp.cliff_stays_under_load(runs, **QUICK)["confirmed"] is False

    def test_the_rule_it_reports_names_the_band_and_both_sides(self):
        runs = lw.campaign(slices=(3.0,), rounds=6, loads=(50, 88), seed=5, spread=0.05)
        assert "either way" in lp.cliff_stays_under_load(runs, **QUICK)["rule"]


class TestP3bLoadRaisesThePlateau:
    """Judged on its own. Together with P3a it confirmed neither: an intersection of two claims
    is confirmed only where both are, so its power was the power of the weaker."""

    def test_a_plateau_that_rises_with_load_is_confirmed(self):
        runs = lw.campaign(slices=(3.0,), rounds=16, loads=(50, 75, 88), seed=5, spread=0.05)
        assert lp.load_raises_the_plateau(runs, **QUICK)["confirmed"] is True

    def test_a_plateau_that_does_not_move_with_load_is_caught(self):
        runs = lw.campaign(slices=(3.0,), rounds=16, loads=(50, 75, 88), seed=5, spread=0.05,
                           world="plateau_flat_with_load")
        assert lp.load_raises_the_plateau(runs, **QUICK)["confirmed"] is False

    def test_one_load_alone_says_nothing(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, loads=(75,), seed=5)
        assert lp.load_raises_the_plateau(runs, **QUICK)["confirmed"] is False

    def test_it_no_longer_asks_anything_about_the_cliff(self):
        """The clause that could not tell the law from its falsifier is gone from this one."""
        runs = lw.campaign(slices=(3.0,), rounds=6, loads=(50, 88), seed=5, spread=0.05)
        found = lp.load_raises_the_plateau(runs, **QUICK)
        assert "halfway" not in found["rule"]
        assert "halfway_move_ms" not in found["by_summary"]["free"]


class TestP4GoFirstRemovesThePlateau:

    def test_the_plateau_is_cut_many_times_over(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, priorities=(False, True), seed=6, spread=0.05)
        found = lp.priority_removes_the_plateau(runs, **QUICK)
        assert found["confirmed"] is True
        assert all(found["by_summary"][n]["value"] >= 5.0 for n in lp.SUMMARIES)

    def test_no_go_first_effect_is_caught(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, priorities=(False, True), seed=6,
                           spread=0.05, world="no_priority_effect")
        assert lp.priority_removes_the_plateau(runs, **QUICK)["confirmed"] is False

    def test_without_go_first_runs_there_is_nothing_to_compare(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, priorities=(False,), seed=6, spread=0.05)
        found = lp.priority_removes_the_plateau(runs, **QUICK)
        assert found["confirmed"] is False and found["by_summary"]["free"]["value"] is None

    def test_where_there_is_no_plateau_to_cut_there_is_nothing_to_say(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, priorities=(False, True), plateau=0.005,
                           seed=6, spread=0.02)
        found = lp.priority_removes_the_plateau(runs, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["value"] is None


class TestP7DefaultSlicesFollowTheCoreCount:

    def campaign(self, world="law"):
        runs = []
        for cores, slice_ms in ((2, 1.4), (4, 2.1), (8, 2.8)):
            runs += lw.campaign(slices=(slice_ms,), rounds=4, cores=(cores,), seed=7,
                                spread=0.05, world=world, fixed_at=2.1)
        return runs

    READ_BACK = {2: 1.4, 4: 2.1, 8: 2.8}

    def test_the_machine_reports_what_was_computed_and_the_cliff_follows(self):
        found = lp.default_slices(self.campaign(), self.READ_BACK, 1.0, **QUICK)
        assert found["confirmed"] is True and all(found["read_back"].values())
        assert found["band"]["confirmed"] is True

    def as_a5_really_runs(self, runs):
        """The shape a real A5 campaign has, which is not the shape the made-up world builds.

        A5 sets no slice. Its whole prediction is that the kernel picks one from the core count,
        so every run carries the slice the design *predicted* and none of its own. The made-up
        world sets a slice on every run, so this shape never reached the judge until a real
        campaign produced it -- and then the judge could not read it at all.
        """
        return [dict(run, slice_ms=None, predicted_slice_ms=run["slice_ms"]) for run in runs]

    def test_it_judges_the_campaign_a5_actually_produces(self):
        """On 21 September this raised "unsupported operand type(s) for -: 'float' and
        'NoneType'" on every run of A5's finished 8-CPU campaign: the judge compared the
        machine's reported slice against a designed one that, for the one block that needs it,
        is never set. P7 could not be judged at all, and the two remaining A5 sessions -- about
        eight hours of machine time -- would have been run before anyone found out."""
        found = lp.default_slices(self.as_a5_really_runs(self.campaign()), self.READ_BACK, 1.0,
                                  **QUICK)
        assert found["confirmed"] is True and all(found["read_back"].values())
        assert found["band"]["confirmed"] is True, "the band is read against the predicted slice"

    def test_a_campaign_with_neither_slice_reports_no_match_rather_than_falling_over(self):
        bare = [dict(run, slice_ms=None, predicted_slice_ms=None) for run in self.campaign()]
        found = lp.default_slices(bare, self.READ_BACK, 1.0, **QUICK)
        assert found["confirmed"] is False and not any(found["read_back"].values())

    def test_a_slice_the_machine_does_not_report_is_caught(self):
        found = lp.default_slices(self.campaign(), {2: 1.4, 4: 2.1}, 1.0, **QUICK)
        assert found["confirmed"] is False and found["read_back"]["8"] is False

    def test_a_cliff_that_stays_put_as_cpus_go_is_caught(self):
        found = lp.default_slices(self.campaign(world="cliff_fixed_by_cores"), self.READ_BACK,
                                  1.0, **QUICK)
        assert found["confirmed"] is False and found["band"]["confirmed"] is False


class TestP8Language:

    def campaign(self, world="law", share=1.0):
        #: Both ways round, as A8 runs them: P8's third clause is about go-first, and a campaign
        #: that never gives it cannot answer the whole prediction.
        return lw.campaign(slices=(3.0,), rounds=4, languages=("python", "java"), seed=8,
                           priorities=(False, True), spread=0.05, world=world,
                           python_share=share)

    def test_java_shows_the_cliff_and_python_is_not_far_above_it(self):
        found = lp.language(self.campaign(), **QUICK)
        assert found["confirmed"] is True
        assert found["by_summary"]["free"]["java_cliff"] == 1.0

    def test_python_at_twice_javas_rate_is_caught(self):
        found = lp.language(self.campaign(world="python_twice_java"), **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["value"] > 1.5

    def test_a_campaign_with_one_language_says_nothing(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, languages=("java",), seed=8, spread=0.05)
        assert lp.language(runs, **QUICK)["confirmed"] is False

    def test_without_javas_runs_there_is_no_cliff_to_read(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, languages=("python",), seed=8, spread=0.05)
        found = lp.language(runs, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["java_cliff"] is None

    def a8(self, world="law", points=("p09s", "c05h", "f15h")):
        return lw.campaign(slices=(3.0,), rounds=6, points=points, priorities=(False, True),
                           languages=("python", "java"), loads=(75,), backends=("kafka",),
                           spread=0.05, seed=3, world=world)

    def test_the_ratio_is_taken_only_where_both_clients_ran(self):
        """The plan takes it "at matched setups". Each client is calibrated on its own, so a trip
        can be out of reach for one and not the other, and a ratio between a trip one client took
        and a trip the other never did is not a comparison of clients."""
        wider = self.a8(points=("p05s", "p09s", "c05h", "f15h"))
        uneven = [r for r in wider
                  if not (r["language"] == "java" and r["point"] == "p05s")]
        found = lp.language(uneven, **QUICK)
        assert found["matched_on"] == ["p09s"], "p05s was Python's alone and cannot be compared"
        assert found["tested"] is True and found["confirmed"] is True

    def test_runs_one_client_alone_reached_are_still_kept(self):
        """They are a measurement of that client; they are only left out of the comparison."""
        wider = self.a8(points=("p05s", "p09s", "c05h", "f15h"))
        uneven = [r for r in wider
                  if not (r["language"] == "java" and r["point"] == "p05s")]
        assert any(r["point"] == "p05s" for r in uneven)
        assert lp.language(uneven, **QUICK)["confirmed"] is True

    def test_no_shared_plateau_trip_means_the_campaign_did_not_test_p8(self):
        """Not that P8 failed. The ratio is undefined, and an undefined ratio reported as a
        prediction that did not hold would be a broken test read as a result -- after the runs."""
        thinned = [r for r in self.a8()
                   if not (r["language"] == "java" and r["point"] == "p09s")]
        found = lp.language(thinned, **QUICK)
        assert found["tested"] is False and found["matched_on"] == []
        assert found["confirmed"] is False

    def test_a_whole_campaign_is_tested_and_says_where_it_was_compared(self):
        found = lp.language(self.a8(), **QUICK)
        assert found["tested"] is True and found["matched_on"] == ["p09s"]

    def test_how_far_go_first_cuts_javas_plateau(self):
        """The plan's third clause, which this judge did not test until 22 September."""
        runs = ([{"language": "java", "point": "p09s", "priority": False,
                  "negative_rate": 0.02}] * 3
                + [{"language": "java", "point": "p09s", "priority": True,
                    "negative_rate": 0.002}] * 3)
        assert lp.priority_cut(runs, ["p09s"]) == pytest.approx(10.0)

    def test_a_cut_to_nothing_is_reported_as_the_cut_it_is(self):
        """Both clients reached zero under go-first on the Arm pair, and a division that raised
        instead would read as a broken campaign rather than as a complete effect."""
        runs = [{"language": "java", "point": "p09s", "priority": False, "negative_rate": 0.02},
                {"language": "java", "point": "p09s", "priority": True, "negative_rate": 0.0}]
        assert lp.priority_cut(runs, ["p09s"]) == float("inf")

    def test_a_campaign_that_ran_only_one_way_cannot_say(self):
        runs = [{"language": "java", "point": "p09s", "priority": False, "negative_rate": 0.02}]
        assert lp.priority_cut(runs, ["p09s"]) is None
        assert lp.priority_cut([], ["p09s"]) is None

    def test_pythons_runs_do_not_enter_javas_cut(self):
        runs = [{"language": "java", "point": "p09s", "priority": False, "negative_rate": 0.02},
                {"language": "java", "point": "p09s", "priority": True, "negative_rate": 0.002},
                {"language": "python", "point": "p09s", "priority": True, "negative_rate": 0.9}]
        assert lp.priority_cut(runs, ["p09s"]) == pytest.approx(10.0)

    def test_go_first_has_to_work_in_java_too(self):
        """In a world where go-first changes nothing the other two clauses still hold, so this
        is the clause that decides. Before 22 September the judge confirmed P8 in that world."""
        flat = lp.language(self.a8(world="no_priority_effect"), **QUICK)
        assert flat["confirmed"] is False
        assert flat["by_summary"]["free"]["java_cliff"] == 1.0, "the cliff clause still holds"
        assert flat["by_summary"]["free"]["java_priority_cut"] < lp.PRIORITY_CUT
        worked = lp.language(self.a8(), **QUICK)
        assert worked["confirmed"] is True
        assert worked["by_summary"]["free"]["java_priority_cut"] >= lp.PRIORITY_CUT

    def test_the_rule_it_prints_names_all_three_clauses(self):
        found = lp.language(self.a8(), **QUICK)
        assert "lies between its plateau and its floor" in found["rule"]
        assert "go-first cuts Java's plateau at least 5.0 times" in found["rule"]
        assert "at most 1.5 times Java's" in found["rule"]


class TestTheSlicesAPairCanReach:
    """A message cannot arrive sooner than the client's own zero-delay trip, and the plateau lives
    at trips below the slice. On 18 September the first pair measured that floor at 1.964 ms for
    Kafka, which leaves the 0.75 and 1.5 ms slices with no plateau to stand on."""

    def campaign(self, slices=(0.75, 1.5, 2.25, 3.0, 4.5, 6.0), floor=2.0, spread=0.28):
        runs = []
        for slice_ms in slices:
            part = lw.campaign(slices=(slice_ms,), rounds=4, seed=int(slice_ms * 100),
                               spread=spread)
            runs += [run for run in part if run["trip_ms"] >= floor]
        return runs

    def test_a_slice_needs_its_plateau_its_floor_and_most_of_its_cliff(self):
        runs = lw.campaign(slices=(3.0,), rounds=2, seed=1, spread=0.05)
        assert lp.testable(runs) == {3.0: True}
        assert lp.testable([r for r in runs if r["point"] != "p09s"]) == {3.0: False}
        assert lp.testable([r for r in runs if r["point"] != "f2sh"]) == {3.0: False}
        assert lp.testable([r for r in runs if r["point"] != "c02h"]) == {3.0: True}, \
            "three of the four trips across the cliff are enough"
        assert lp.testable([r for r in runs if r["point"] not in ("c02h", "c04h")]) == {3.0: False}

    def test_the_prediction_is_judged_on_the_reachable_slices_and_says_which_they_were(self):
        found = lp.judge(self.campaign(), "P1", 1.0, draws=40, seed=1, grid=24)
        said = found["by_summary"]["free"]
        assert said["out_of_reach"] == [0.75, 1.5]
        assert sorted(said["in_band"]) == [2.25, 3.0, 4.5, 6.0]
        assert "at least 3 of the 4 slices this pair can reach" in found["rule"]
        assert "out of reach: [0.75, 1.5]" in "\n".join(lp.lines("P1", found))

    def test_too_few_reachable_slices_confirm_nothing(self):
        """Three slices are not a dose-response, however well they behave."""
        found = lp.judge(self.campaign(slices=(2.25, 3.0, 4.5), floor=5.0), "P1", 1.0,
                         draws=40, seed=1, grid=24)
        assert found["confirmed"] is False

    def test_the_arm_pair_needs_two_and_every_one_of_them(self):
        runs = self.campaign(slices=(1.5, 3.0, 4.5), floor=2.0)
        found = lp.judge(runs, "P9", 1.0, draws=40, seed=1, grid=24)
        said = found["by_summary"]["free"]
        assert said["out_of_reach"] == [1.5] and sorted(said["in_band"]) == [3.0, 4.5]
        assert "at least 2 of the 2 slices this pair can reach" in found["rule"]


class TestTheAnchorTheCampaignsShare:
    """A1 and A4 run as several campaigns on different days, and each has an offset of its own.
    The plan removes it through the slice they all share, before P1 or P9 is judged."""

    def campaigns(self, shifts=None, anchor=3.0, spread=0.05):
        runs = []
        for i, (slices, shift) in enumerate(shifts or [((3.0, 0.75, 1.5), 0.0),
                                                       ((3.0, 2.25, 4.5), 0.4),
                                                       ((3.0, 6.0), -0.3)]):
            part = lw.campaign(slices=slices, rounds=4, seed=10 + i, spread=spread)
            for run in part:
                run["campaign"] = "a1_%d" % i
                run["trip_ms"] += shift
            runs += part
        return runs

    def test_each_campaign_is_measured_against_the_mean_of_the_anchors(self):
        found = lp.anchor_offsets(self.campaigns(), 3.0, grid=24)
        assert sorted(found) == ["a1_0", "a1_1", "a1_2"]
        assert sum(found.values()) == pytest.approx(0.0, abs=1e-9), "the offsets sum to nothing"
        assert found["a1_1"] > found["a1_0"] > found["a1_2"]

    def test_a_campaign_that_never_ran_the_anchor_is_left_where_it_is(self):
        runs = self.campaigns()
        for run in runs:
            if run["campaign"] == "a1_2":
                run["campaign"] = "a1_x"
                run["slice_ms"] = 6.0 if run["slice_ms"] == 3.0 else run["slice_ms"]
        found = lp.anchor_offsets(runs, 3.0, grid=24)
        assert "a1_x" not in found and len(found) == 2

    def test_one_campaign_alone_has_nothing_to_be_measured_against(self):
        runs = lw.campaign(slices=(3.0, 1.5), rounds=4, seed=1, spread=0.05)
        for run in runs:
            run["campaign"] = "a1_only"
        assert lp.anchor_offsets(runs, 3.0, grid=24) == {}

    def test_the_anchor_itself_counts_once_however_many_campaigns_ran_it(self):
        found = lp.through_the_anchor(self.campaigns(), 3.0, grid=24)
        assert sorted(found) == [0.75, 1.5, 2.25, 3.0, 4.5, 6.0]
        assert found[3.0] == pytest.approx(3.5, abs=0.2)

    def test_a_slice_whose_curve_says_nothing_is_left_out(self):
        runs = self.campaigns()
        for run in runs:
            if run["slice_ms"] == 6.0:
                run["negative_rate"] = 0.01
        assert 6.0 not in lp.through_the_anchor(runs, 3.0, grid=24)

    def test_the_correction_recovers_the_slope_the_shifts_hid(self):
        runs = self.campaigns(shifts=[((3.0, 0.75, 1.5), 0.0), ((3.0, 2.25, 4.5), 0.9),
                                      ((3.0, 6.0), -0.8)])
        plain = lp.judge(runs, "P1", 1.0, draws=40, seed=1, grid=24)
        fixed = lp.judge(runs, "P1", 1.0, draws=40, seed=1, grid=24, anchor_ms=3.0)
        astray = plain["by_summary"]["free"]
        through = fixed["by_summary"]["free"]
        assert abs(through["value"] - 1.0) < abs(astray["value"] - 1.0)
        assert sum(through["in_band"].values()) >= sum(astray["in_band"].values())
        assert "through the 3 ms anchor" in fixed["rule"]
        assert "anchor ms: 3.0" in "\n".join(lp.lines("P1", fixed))

    def test_the_arm_pair_reads_its_three_slices_the_same_way(self):
        runs = self.campaigns(shifts=[((3.0, 1.5), 0.0), ((3.0, 4.5), 0.3)])
        found = lp.judge(runs, "P9", 1.0, draws=40, seed=1, grid=24, anchor_ms=3.0)
        assert found["confirmed"] is True and found["anchor_ms"] == 3.0


class TestJudgingFromTheOutside:

    def runs(self):
        return lw.campaign(slices=SIX, rounds=4, seed=1)

    @pytest.mark.parametrize("prediction", ["P1", "P9", "P2d"])
    def test_each_prediction_reaches_its_own_rule(self, prediction):
        found = lp.judge(self.runs(), prediction, 1.0, draws=40, seed=1, grid=24)
        assert "confirmed" in found and found["rule"]

    def test_nothing_is_pooled_across_backends_or_pairs(self):
        runs = lw.campaign(slices=SIX, rounds=4, seed=1, backends=("kafka", "redis"))
        for run in runs:
            run["pair"] = "matched" if run["backend"] == "kafka" else "arm"
        found = lp.judge(runs, "P1", 1.0, draws=40, seed=1, grid=24)
        assert found["split_by"] == ["pair", "backend"]
        assert sorted(found["by_part"]) == ["arm, redis", "matched, kafka"]
        assert found["confirmed"] is all(a["confirmed"] for a in found["by_part"].values())

    def test_a_part_that_does_not_confirm_sinks_the_whole(self):
        runs = lw.campaign(slices=SIX, rounds=4, seed=1)
        astray = lw.campaign(slices=SIX, rounds=4, seed=1, world="cliff_fixed", fixed_at=4.0)
        for run in astray:
            run["backend"] = "redis"
        found = lp.judge(runs + astray, "P1", 1.0, draws=40, seed=1, grid=24)
        assert found["confirmed"] is False
        assert found["by_part"]["kafka"]["confirmed"] is True
        assert found["by_part"]["redis"]["confirmed"] is False
        said = "\n".join(lp.lines("P1", found))
        assert "nothing pooled across: backend" in said and "  redis: not confirmed" in said

    def test_the_slowest_kernel_has_its_own_prediction(self):
        runs = []
        for tick in (1.0, 10.0):
            runs += lw.campaign(slices=(20.0,), rounds=4, tick_ms=tick, seed=2, spread=0.05)
        found = lp.judge(runs, "P2b", 10.0, draws=40, seed=1, grid=24)
        assert found["hz"] == 100 and "6.0-14.0" in found["rule"]

    def test_the_core_count_rule_is_reachable_by_name(self):
        runs = []
        for cores, slice_ms in ((2, 1.4), (4, 2.1)):
            runs += lw.campaign(slices=(slice_ms,), rounds=4, cores=(cores,), seed=7, spread=0.05)
        found = lp.judge(runs, "P7", 1.0, draws=40, seed=1, grid=24,
                         read_back={2: 1.4, 4: 2.1})
        assert found["confirmed"] is True
        assert lp.judge(runs, "P7", 1.0, draws=40, seed=1, grid=24)["confirmed"] is False

    def test_a_prediction_with_no_rule_here_says_which_it_has(self):
        with pytest.raises(ValueError, match="no rule for P42"):
            lp.judge(self.runs(), "P42")

    @pytest.mark.parametrize("prediction", ["P2", "P3a", "P3b"])
    def test_the_rules_that_take_the_campaign_as_it_is(self, prediction):
        runs = lw.campaign(slices=(3.0,), rounds=4, loads=(50, 88), seed=5, spread=0.05)
        assert "confirmed" in lp.judge(runs, prediction, 1.0, draws=40, seed=1, grid=24)

    def test_the_answer_reads_as_a_person_would_say_it(self):
        found = lp.cliff_follows_slice(self.runs(), 1.0, **QUICK)
        said = "\n".join(lp.lines("P1", found))
        assert said.startswith("P1: confirmed") and "rule: halfway inside" in said
        assert "95% interval" in said and "in band" in said
        assert "free shape: holds" in said and "fitted shape: holds" in said


class TestHowTheAnswersRead:

    def test_an_answer_with_no_interval_still_reads(self):
        runs = lw.campaign(slices=(8.0,), rounds=4, seed=4, spread=0.02)
        said = "\n".join(lp.lines("P2d", lp.start_at_slice(runs, grid=24)))
        assert "P2d: confirmed" in said and "fitted shape: holds" in said
        assert "resamplings" not in said, "P2d reads a fit, it does not resample"
        assert "within" in said

    def test_a_ratio_answer_names_the_kernel_it_compared(self):
        runs = []
        for tick in (1.0, 4.0):
            runs += lw.campaign(slices=(8.0,), rounds=4, tick_ms=tick, seed=2, spread=0.05)
        said = "\n".join(lp.lines("P2", lp.width_follows_tick(runs, 4.0, **QUICK)))
        assert "hz: 250" in said

    def test_the_core_count_answer_names_what_the_machine_reported(self):
        runs = []
        for cores, slice_ms in ((2, 1.4), (4, 2.1)):
            runs += lw.campaign(slices=(slice_ms,), rounds=4, cores=(cores,), seed=7, spread=0.05)
        found = lp.default_slices(runs, {2: 1.4, 4: 2.1}, 1.0, **QUICK)
        assert "read back:" in "\n".join(lp.lines("P7", found))


class TestTheCommand:

    def write(self, folder, runs):
        for i, run in enumerate(runs):
            where = folder / ("law_a1_r%s-%03d" % (run["round"], i))
            where.mkdir(parents=True, exist_ok=True)
            (where / "queue_row.json").write_text(json.dumps(
                {"key": where.name, "round": run["round"], "setup": "A1",
                 "params": {"backend": run["backend"], "point": run["point"],
                            "slice_ns": run["slice_ms"] * 1e6, "tick_ms": run["tick_ms"],
                            "load_pct": run["load_pct"], "priority": run["priority"],
                            "cpus": run["cpus"]}}), encoding="utf-8")
            (where / "integrity.json").write_text(json.dumps(
                {"verdict": "count", "recorded": {"trip_median_ms": run["trip_ms"],
                                                  "measured_negative_rate": run["negative_rate"]}}),
                encoding="utf-8")
        return str(folder)

    def test_it_judges_a_copied_campaign_and_can_write_the_answer(self, tmp_path):
        folder = self.write(tmp_path / "runs", lw.campaign(slices=SIX, rounds=4, seed=1))
        out, where = io.StringIO(), str(tmp_path / "p1.json")
        code = lp.main(["judge", "--runs", folder, "--prediction", "P1", "--tick-ms", "1.0",
                        "--draws", "40", "--seed", "1", "--out", where], out=out)
        assert code == 0 and "P1: confirmed" in out.getvalue()
        with open(where, encoding="utf-8") as fh:
            assert json.load(fh)["confirmed"] is True

    def test_a_prediction_that_did_not_come_true_leaves_with_one(self, tmp_path):
        folder = self.write(tmp_path / "runs", lw.campaign(slices=SIX, rounds=4, seed=1,
                                                           world="cliff_fixed", fixed_at=4.0))
        out = io.StringIO()
        code = lp.main(["judge", "--runs", folder, "--prediction", "P1", "--draws", "40"],
                       out=out)
        assert code == 1 and "P1: not confirmed" in out.getvalue()

    def test_the_core_count_answer_can_be_asked_for_from_the_command_line(self, tmp_path):
        runs = []
        for cores, slice_ms in ((2, 1.4), (4, 2.1)):
            runs += lw.campaign(slices=(slice_ms,), rounds=4, cores=(cores,), seed=7, spread=0.05)
        folder = self.write(tmp_path / "runs", runs)
        out = io.StringIO()
        code = lp.main(["judge", "--runs", folder, "--prediction", "P7", "--draws", "40",
                        "--read-back", "2=1.4,4=2.1"], out=out)
        assert code == 0 and "P7: confirmed" in out.getvalue()

    def test_a_folder_with_nothing_in_it_is_an_error_line(self, tmp_path):
        out = io.StringIO()
        assert lp.main(["judge", "--runs", str(tmp_path), "--prediction", "P1"], out=out) == 2
        assert out.getvalue().startswith("ERROR:")


class TestTheWorldsThemselves:

    def test_a_world_it_does_not_know_is_refused(self):
        with pytest.raises(ValueError, match="no such world"):
            lw.campaign(world="the one where it all works out")

    def test_a_run_carries_what_the_analysis_reads(self):
        run = lw.campaign(slices=(3.0,), rounds=1, seed=1)[0]
        assert set(run) >= {"round", "point", "backend", "slice_ms", "tick_ms", "load_pct",
                            "priority", "cpus", "language", "trip_ms", "negative_rate"}

    def test_shifts_between_sittings_move_the_trips_and_the_plateau(self):
        steady = lw.campaign(slices=(3.0,), rounds=6, seed=2, spread=0.0)
        shifted = lw.campaign(slices=(3.0,), rounds=6, seed=2, spread=0.0, session_shift=True)
        assert len(set(r["trip_ms"] for r in steady)) == len(lw.POINTS)
        assert len(set(r["trip_ms"] for r in shifted)) > len(lw.POINTS)

    def test_a_cliff_with_no_width_falls_all_at_once(self):
        assert lw.rate_of(2.9, 3.0, 0.0, 0.3, 0.01) == 0.3
        assert lw.rate_of(3.1, 3.0, 0.0, 0.3, 0.01) == 0.01

    def test_the_load_world_moves_the_cliff_by_half_a_millisecond(self):
        assert lw._cliff("cliff_moves_with_load", 3.0, 9.9, None, 88, (50, 88)) == 3.5
        assert lw._cliff("cliff_moves_with_load", 3.0, 9.9, None, 50, (50, 88)) == 3.0
        assert lw._cliff("cliff_moves_with_load", 3.0, 9.9, None, 50, (50, 50)) == 3.0
        assert lw._cliff("cliff_moves_with_load", 3.0, 9.9, None, 50, ()) == 3.0

    def test_the_core_world_only_moves_where_cores_were_switched(self):
        assert lw._cliff("cliff_fixed_by_cores", 3.0, 2.1, 4, 75, (75,)) == 2.1
        assert lw._cliff("cliff_fixed_by_cores", 3.0, 2.1, None, 75, (75,)) == 3.0

    def test_a_design_point_sits_where_the_slice_and_tick_put_it(self):
        assert lw.trip_of("p09s", 3.0, 1.0) == pytest.approx(2.7)
        assert lw.trip_of("f2sh", 3.0, 1.0) == pytest.approx(8.0)


#: The slice the kernel's rule gives at each core count, for the core-count campaign.
SLICE_BY_CORE = {2: 6.0, 4: 4.5, 8: 3.0}


def _campaign_for(prediction, world, points):
    """The campaign that tests one prediction, built on the points its own block runs."""
    if prediction in ("P2", "P2b", "P2c", "P2d"):
        slices = (20.0,) if prediction == "P2c" else (8.0,)
        ticks = (1.0, 4.0, 10.0) if prediction == "P2c" else (1.0, 4.0)
        runs = []
        for tick in ticks:
            runs += lw.campaign(slices=slices, rounds=4, tick_ms=tick, seed=3, world=world,
                                spread=0.05, points=points)
        return runs
    if prediction in ("P1", "P9"):
        return lw.campaign(slices=SIX, rounds=6, points=points, spread=0.05, seed=5, world=world)
    if prediction in ("P3a", "P3b"):
        return lw.campaign(slices=(3.0,), rounds=6, points=points, loads=(50, 75, 88),
                           spread=0.05, seed=5, world=world)
    if prediction == "P4":
        return lw.campaign(slices=(3.0,), rounds=6, points=points, priorities=(False, True),
                           backends=("kafka", "redis"), spread=0.05, seed=5, world=world)
    if prediction == "P7":
        return lw.campaign(slices=(3.0,), rounds=6, points=points, cores=(2, 4, 8),
                           slice_by_core=SLICE_BY_CORE, spread=0.05, seed=5, world=world)
    return lw.campaign(slices=(3.0,), rounds=6, points=points, priorities=(False, True),
                       languages=("python", "java"), spread=0.05, seed=5, world=world)


def _judge(prediction, runs):
    """The rule, called the way its campaign calls it."""
    if prediction in ("P1", "P9"):
        return lp.RULES[prediction](runs, 1.0, **QUICK)
    if prediction in ("P2", "P2b"):
        return lp.RULES[prediction](runs, 4.0, **QUICK)
    if prediction == "P2c":
        return lp.RULES[prediction](runs, **dict(QUICK, grid=48))
    if prediction == "P2d":
        return lp.RULES[prediction](runs, grid=96)
    if prediction == "P7":
        return lp.RULES[prediction](runs, SLICE_BY_CORE, 1.0, **QUICK)
    return lp.RULES[prediction](runs, **QUICK)


class TestEveryRuleIsJudgedOnTheDesignItsOwnBlockRuns:
    """Each rule must be satisfiable by the campaign that tests it, and refused by its falsifier.

    The block numbers and the prediction numbers do not line up -- A7 is the go-first block and is
    judged by P4, A5 is the core-count block and is judged by P7 -- so law_design.TESTED_BY says
    which block runs which prediction, and these build each campaign from that block's own points
    rather than from the eight-point ladder law_world offers by default.

    This is the check that was missing. P8 read the middle of the cliff from c04h, a point A8's
    three-trip design never runs. Against the default ladder the rule looked well; against A8's
    own design it could not confirm at any number of rounds, and the round simulation reported
    that as 40 rounds and underpowered -- 1,440 runs to learn nothing.
    """

    def test_every_prediction_names_the_block_that_tests_it(self):
        assert set(rr.FALSIFIERS) <= set(ld.TESTED_BY)
        assert all(block in ld.BLOCKS for block in ld.TESTED_BY.values())

    @pytest.mark.parametrize("prediction", sorted(rr.FALSIFIERS))
    def test_the_rule_confirms_under_the_law_on_its_own_points(self, prediction):
        points = ld.BLOCKS[ld.TESTED_BY[prediction]]["points"]
        found = _judge(prediction, _campaign_for(prediction, "law", points))
        assert found["confirmed"] is True, (
            "%s cannot be confirmed by %s, the block that tests it, on its points %s"
            % (prediction, ld.TESTED_BY[prediction], ", ".join(points)))

    @pytest.mark.parametrize("prediction", sorted(rr.FALSIFIERS))
    def test_the_rule_is_refused_where_it_is_false_on_its_own_points(self, prediction):
        points = ld.BLOCKS[ld.TESTED_BY[prediction]]["points"]
        found = _judge(prediction, _campaign_for(prediction, rr.FALSIFIERS[prediction], points))
        assert found["confirmed"] is False, (
            "%s is confirmed in the world where it is false (%s)"
            % (prediction, rr.FALSIFIERS[prediction]))


class TestARunCountsWhatItSees:
    """A run does not observe a rate; it counts negatives out of the messages it sent.

    That matters wherever the rate is low. A3's 50% load saw four to seven negatives in a run of
    about 5,000 messages, and its run-to-run scatter is within a fifth of what counting alone
    produces; at 75 and 88% the counts are in the hundreds and most of the scatter is the cliff's
    own position moving between runs, which the curve's slope turns into rate. A single spread
    multiplied onto the rate can represent neither, and cannot represent the messages a run sends
    at all -- so it cannot answer whether a longer run would buy what another round buys.
    """

    def rates(self, **kw):
        runs = lw.campaign(slices=(3.0,), rounds=200, points=("p09s",), seed=4, **kw)
        return [r["negative_rate"] for r in runs]

    def test_counting_gives_a_rate_that_is_a_whole_number_of_messages(self):
        for rate in self.rates(plateau=0.02, messages=1000, spread=0):
            assert abs(rate * 1000 - round(rate * 1000)) < 1e-9

    def test_more_messages_make_the_counting_quieter(self):
        few = st.pstdev([math.log(max(r, 1e-9)) for r in self.rates(plateau=0.02, messages=500)])
        many = st.pstdev([math.log(max(r, 1e-9)) for r in self.rates(plateau=0.02, messages=8000)])
        assert many < few / 2, "sixteen times the messages should halve the scatter twice over"

    def test_overdispersion_widens_it_and_one_leaves_it_poisson(self):
        plain = st.pstdev(self.rates(plateau=0.02, messages=2000, overdispersion=1.0))
        wide = st.pstdev(self.rates(plateau=0.02, messages=2000, overdispersion=4.0))
        assert wide > plain

    def test_the_large_count_path_is_taken_too(self):
        """Knuth's method below 30 expected, the normal shape above it: both must work."""
        big = self.rates(plateau=0.5, messages=2000, overdispersion=1.0)
        assert 0.4 < st.mean(big) < 0.6

    def test_a_rate_of_nothing_counts_nothing(self):
        assert set(self.rates(plateau=0.0, floor=0.0, messages=1000)) == {0.0}

    def test_the_messages_can_differ_by_load(self):
        """Only the load that needs them has to pay for them."""
        runs = lw.campaign(slices=(3.0,), rounds=40, points=("p09s",), loads=(50, 88), seed=4,
                           plateau=0.02, messages={50: 16000, 88: 1000})
        by = {}
        for r in runs:
            by.setdefault(r["load_pct"], []).append(r["negative_rate"])
        quiet = st.pstdev([math.log(max(v, 1e-9)) for v in by[50]])
        noisy = st.pstdev([math.log(max(v, 1e-9)) for v in by[88]])
        assert quiet < noisy


class TestTheCliffWobblesBetweenRuns:

    def test_jitter_moves_the_fall_and_the_slope_turns_it_into_rate(self):
        """On the steep part a quarter of a millisecond of wobble is most of the scatter; on the
        flat plateau it is almost none. That is the shape A3 measured."""
        def scatter(point):
            runs = lw.campaign(slices=(3.0,), rounds=200, points=(point,), seed=6, spread=0,
                               plateau=0.09, floor=0.03, trip_jitter_ms=0.25)
            return st.pstdev([r["negative_rate"] for r in runs])
        assert scatter("c06h") > 4 * scatter("p09s")

    def test_without_jitter_a_flat_world_does_not_move(self):
        runs = lw.campaign(slices=(3.0,), rounds=20, points=("p09s",), spread=0, seed=6)
        assert len(set(r["negative_rate"] for r in runs)) == 1


class TestTheLevelsCanBeGivenPerLoad:
    """A3 measured the plateau 59 times higher at 88% load than at 50%. The rule the world used
    puts it 17% higher, so a campaign simulated by that rule is not the campaign that runs."""

    LEVELS = {50: 0.0015, 75: 0.041, 88: 0.089}

    def plateaus(self, world="law"):
        runs = lw.campaign(slices=(3.0,), rounds=1, points=("p09s",), loads=(50, 75, 88),
                           spread=0, world=world, plateau_by_load=self.LEVELS,
                           floor_by_load={50: 0.0005, 75: 0.009, 88: 0.029})
        return dict((r["load_pct"], r["negative_rate"]) for r in runs)

    def test_each_load_gets_the_level_that_was_measured_there(self):
        assert self.plateaus() == pytest.approx(self.LEVELS)

    def test_where_the_plateau_does_not_rise_every_load_reads_the_lowest(self):
        found = self.plateaus(world="plateau_flat_with_load")
        assert sorted(found.values()) == pytest.approx([self.LEVELS[50]] * 3)

    def test_the_floor_is_taken_per_load_as_well(self):
        runs = lw.campaign(slices=(3.0,), rounds=1, points=("f15h",), loads=(50, 88), spread=0,
                           plateau_by_load=self.LEVELS, floor_by_load={50: 0.0005, 88: 0.029})
        found = dict((r["load_pct"], r["negative_rate"]) for r in runs)
        assert found[50] == pytest.approx(0.0005) and found[88] == pytest.approx(0.029)
