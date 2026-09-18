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
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_predictions as lp  # noqa: E402
import law_world as lw  # noqa: E402

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
        assert "at least 5 of 6 slices" in found["rule"]

    def test_with_fewer_slices_every_one_must_be_inside(self):
        runs = lw.campaign(slices=(1.5, 3.0, 4.5), rounds=4, seed=1)
        found = lp.cliff_follows_slice(runs, 1.0, need_interval=False, **QUICK)
        assert "at least 3 of 3 slices" in found["rule"] and found["confirmed"] is True
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


class TestP3LoadRaisesThePlateau:

    def test_the_plateau_rises_and_the_cliff_stays(self):
        runs = lw.campaign(slices=(3.0,), rounds=6, loads=(50, 75, 88), seed=5, spread=0.05)
        found = lp.load_raises_the_plateau(runs, **QUICK)
        assert found["confirmed"] is True
        assert found["by_summary"]["free"]["halfway_move_ms"] < 0.25

    def test_a_cliff_that_moves_with_load_is_caught(self):
        runs = lw.campaign(slices=(3.0,), rounds=6, loads=(50, 75, 88), seed=5, spread=0.05,
                           world="cliff_moves_with_load")
        found = lp.load_raises_the_plateau(runs, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["halfway_move_ms"] >= 0.25

    def test_one_load_alone_says_nothing(self):
        runs = lw.campaign(slices=(3.0,), rounds=4, loads=(75,), seed=5)
        found = lp.load_raises_the_plateau(runs, **QUICK)
        assert found["confirmed"] is False
        assert found["by_summary"]["free"]["halfway_move_ms"] is None


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

    def test_a_slice_the_machine_does_not_report_is_caught(self):
        found = lp.default_slices(self.campaign(), {2: 1.4, 4: 2.1}, 1.0, **QUICK)
        assert found["confirmed"] is False and found["read_back"]["8"] is False

    def test_a_cliff_that_stays_put_as_cpus_go_is_caught(self):
        found = lp.default_slices(self.campaign(world="cliff_fixed_by_cores"), self.READ_BACK,
                                  1.0, **QUICK)
        assert found["confirmed"] is False and found["band"]["confirmed"] is False


class TestP8Language:

    def campaign(self, world="law", share=1.0):
        return lw.campaign(slices=(3.0,), rounds=4, languages=("python", "java"), seed=8,
                           spread=0.05, world=world, python_share=share)

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

    @pytest.mark.parametrize("prediction", ["P2", "P3"])
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
