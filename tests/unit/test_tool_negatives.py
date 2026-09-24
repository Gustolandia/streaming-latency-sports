"""T2: naming what a tool did with a latency the subtraction pushed below zero.

The temptation in a script like this is to always produce an answer. Four behaviours predict four
sets of figures, the tool printed one set, and something is always nearest. Naming the nearest is
what the first version did, and synthetic runs showed it unsound: on a tool whose clock is coarser
than the gap between two behaviours, the nearest is decided by the rounding rather than by the
tool, and it named one that had done nothing of the sort.

So the verdict is what survives. Each behaviour is ruled out by a figure it cannot account for,
and a run that leaves two standing has not answered. Most of what is tested here is this script
declining to answer, and declining for a stated reason.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import tool_negatives as tn  # noqa: E402

#: Ten trips at 3 ms and ten at 0.5 ms. At an offset of 2 ms the short ones go below zero, and
#: none lands exactly on it -- so dropping the negatives and dropping zero with them agree.
TRIPS = [3.0] * 10 + [0.5] * 10

#: The same, with one trip exactly on the offset. That single value is the only thing that tells
#: "drops the negatives" from "drops zero and below" apart.
TRIPS_ON_ZERO = [3.0] * 10 + [2.0] + [0.5] * 9


def reading(avg=None, low=None, kept=None, step=0.001, **rest):
    """A reading in the shape tool_readings produces, with only what this script reads."""
    got, steps = {}, {}
    for key, value in (("avg", avg), ("min", low)):
        if value is not None:
            got[key], steps[key] = value, step
    out = {"tool": "made up", "reported_ms": got, "steps_ms": steps,
           "step_ms": step, "kept": kept, "unit": None}
    out.update(rest)
    return out


class TestWhatEachBehaviourWouldHaveGiven:

    def test_the_offset_moves_every_trip_down_by_itself(self):
        assert tn.measured([3.0, 0.5], 2.0) == pytest.approx([1.0, -1.5])

    def test_how_many_go_below_zero(self):
        assert tn.negatives_made(TRIPS, 2.0) == 10
        assert tn.negatives_made(TRIPS, 0.25) == 0

    def test_the_four_behaviours_give_four_different_answers(self):
        said = tn.predictions(TRIPS_ON_ZERO, 2.0)
        assert said["keeps every value"]["avg_ms"] == pytest.approx(-0.175)
        assert said["drops the negatives"]["avg_ms"] == pytest.approx(10.0 / 11.0)
        assert said["drops zero and below"]["avg_ms"] == pytest.approx(1.0)
        assert said["replaces the negatives with zero"]["avg_ms"] == pytest.approx(0.5)

    def test_each_also_predicts_a_count_and_a_smallest_value(self):
        said = tn.predictions(TRIPS, 2.0)
        assert said["keeps every value"]["count"] == 20
        assert said["keeps every value"]["min_ms"] == pytest.approx(-1.5)
        assert said["drops the negatives"]["count"] == 10
        assert said["replaces the negatives with zero"]["min_ms"] == 0.0

    def test_a_behaviour_that_leaves_nothing_has_no_figures_rather_than_zeros(self):
        said = tn.predictions([0.5, 0.5], 2.0)
        assert said["drops the negatives"]["avg_ms"] is None
        assert said["drops the negatives"]["min_ms"] is None
        assert said["keeps every value"]["avg_ms"] == pytest.approx(-1.5)


class TestThroughTheToolsOwnStep:
    """A tool's rule for odd values runs on what its own clock handed it, not on the truth. A
    whole millisecond truncated toward zero puts everything between minus one and plus one at
    zero, so a tool reading that clock never meets a negative and never drops one -- and a
    prediction made from the true trips has it dropping values it never saw."""

    def test_a_coarse_clock_never_shows_a_negative_at_a_small_offset(self):
        """A trip of 1.9 ms under a 2 ms offset is minus a tenth, which truncates to zero."""
        assert tn.measured([1.9], 2.0, step_ms=1.0) == [0.0]
        assert tn.negatives_made([1.9], 2.0, step_ms=1.0) == 0
        assert tn.negatives_made([1.9], 2.0) == 1, "and one, before its clock is allowed for"

    def test_the_offset_has_to_clear_the_step_before_a_negative_survives(self):
        assert tn.negatives_made([3.0], 4.0, step_ms=1.0) == 1, "minus one is a negative to it"
        assert tn.negatives_made([3.0], 3.5, step_ms=1.0) == 0, "minus a half is not"

    def test_a_fine_clock_is_left_as_it_is(self):
        assert tn.measured([1.9], 2.0, step_ms=1e-6)[0] == pytest.approx(-0.1, abs=1e-6)

    def test_the_predictions_follow_the_step_they_are_given(self):
        """At a 6 ms offset a millisecond tool sees every 3 ms trip as minus three, so dropping
        the negatives leaves it nothing at all -- which is a reading, and a striking one."""
        said = tn.predictions([3.0] * 5, 6.0, step_ms=1.0)
        assert said["keeps every value"]["avg_ms"] == pytest.approx(-3.0)
        assert said["drops the negatives"]["count"] == 0


class TestNamingWhatTheToolDid:

    def test_a_tool_that_kept_them_all_is_named(self):
        got = tn.what_it_did(reading(avg=-0.25, low=-1.5), TRIPS, 2.0)
        assert got["decided"] and got["behaviour"] == "keeps every value"

    def test_a_tool_that_replaced_them_with_zero_is_named(self):
        got = tn.what_it_did(reading(avg=0.5, low=0.0), TRIPS, 2.0)
        assert got["decided"] and got["behaviour"] == "replaces the negatives with zero"

    def test_the_others_are_ruled_out_with_a_reason_each(self):
        got = tn.what_it_did(reading(avg=-0.25, low=-1.5), TRIPS, 2.0)
        assert set(got["ruled_out"]) == {"drops the negatives", "drops zero and below",
                                         "replaces the negatives with zero"}
        assert all("more than" in why for why in got["ruled_out"].values())

    def test_a_count_short_of_what_was_sent_rules_out_what_could_not_have_given_it(self):
        """Printing whole milliseconds, its average cannot separate dropping the negatives from
        dropping the zeros with them. Its count can, and only because it is short of what was
        sent: it says outright that the tool left values out."""
        got = tn.what_it_did(reading(avg=10.0 / 11.0, kept=11, step=1.0), TRIPS_ON_ZERO, 2.0)
        assert got["decided"] and got["behaviour"] == "drops the negatives"
        assert "it counted 11" in got["ruled_out"]["drops zero and below"]

    def test_dropping_the_zeros_too_is_a_different_answer(self):
        got = tn.what_it_did(reading(avg=1.0, low=1.0, kept=10), TRIPS_ON_ZERO, 2.0)
        assert got["decided"] and got["behaviour"] == "drops zero and below"

    def test_a_count_that_matches_what_was_sent_rules_nothing_out(self):
        """It may be reporting what it sent rather than what it kept, and a tool that drops a
        value from its average without saying so is exactly what this block is looking for."""
        got = tn.what_it_did(reading(avg=-0.25, low=-1.5, kept=20), TRIPS, 2.0)
        assert got["decided"] and got["count_matches_sent"] is True

    def test_its_count_is_reported_against_what_was_sent_either_way(self):
        got = tn.what_it_did(reading(avg=1.0, kept=10), TRIPS, 2.0)
        assert got["count_matches_sent"] is False
        assert "drops the negatives" in got["count_agrees_with"]

    def test_a_tool_that_reports_no_count_is_not_held_to_one(self):
        got = tn.what_it_did(reading(avg=-0.25), TRIPS, 2.0)
        assert got["count_matches_sent"] is None and got["count_agrees_with"] == []

    def test_how_many_were_sent_can_be_told_rather_than_counted(self):
        got = tn.what_it_did(reading(avg=-0.25, kept=20), TRIPS, 2.0, sent=5000)
        assert got["sent"] == 5000 and got["count_matches_sent"] is False


class TestComparingHowFarItMoved:
    """A tool reading a coarse clock carries a bias of its own into every figure. Held against
    the truth it looks like a tool mishandling negatives; held against itself with nothing moved,
    the bias cancels and what is left is what the offset did."""

    def test_a_tool_half_a_millisecond_low_throughout_is_not_blamed_for_it(self):
        plain = reading(avg=1.75 - 0.5, step=0.1)
        offset = reading(avg=-0.25 - 0.5, step=0.1)
        got = tn.what_it_did(offset, TRIPS, 2.0, plain=plain)
        assert got["decided"] and got["behaviour"] == "keeps every value"

    def test_without_the_plain_reading_that_same_tool_is_ruled_out_of_everything(self):
        got = tn.what_it_did(reading(avg=-0.25 - 0.5, step=0.1), TRIPS, 2.0)
        assert not got["decided"] and got["still_standing"] == []

    def test_a_shift_that_no_behaviour_accounts_for_still_rules_them_all_out(self):
        plain = reading(avg=1.75, step=0.001)
        got = tn.what_it_did(reading(avg=1.74, step=0.001), TRIPS, 2.0, plain=plain)
        assert got["still_standing"] == [] and not got["decided"]
        assert "none of the four describes" in got["why"]


class TestWhetherItsSubtractionSpansTwoClocks:
    """D23-1. T2's question has an answer only where the subtraction spans two clocks.

    Ten of the eleven tools write both timestamps in one process, so the moved clock moves both
    and the difference is untouched. Until the control run that came out as "no behaviour
    accounts for what it printed", which is the same sentence a tool doing something unforeseen
    produces. The two are told apart by whether the tool's own figures moved.
    """

    def test_a_clock_that_moved_under_figures_that_did_not_is_one_clock(self):
        control = reading(avg=1.75, step=0.01)
        got = tn.what_it_did(reading(avg=1.752, step=0.01), TRIPS, 2.0,
                             step_ms=0.01, control=control, shift_ms=1.806)
        assert got["decided"] and got["behaviour"] == tn.ONE_CLOCK
        assert "1.806" in got["why"] and "one clock" in got["why"]

    def test_figures_that_moved_past_the_step_are_judged_as_before(self):
        control = reading(avg=1.75, step=0.01)
        got = tn.what_it_did(reading(avg=-0.25, step=0.01), TRIPS, 2.0,
                             step_ms=0.01, control=control, shift_ms=1.806)
        assert got["behaviour"] != tn.ONE_CLOCK, "a tool whose figures moved is not one-clock"

    def test_a_shift_nobody_measured_decides_nothing(self):
        """The verdict is that the clock moved and the figures did not; half of that is not it."""
        control = reading(avg=1.75, step=0.01)
        got = tn.what_it_did(reading(avg=1.752, step=0.01), TRIPS, 2.0,
                             step_ms=0.01, control=control, shift_ms=None)
        assert got["behaviour"] != tn.ONE_CLOCK

    def test_with_no_control_there_is_nothing_to_have_moved_from(self):
        got = tn.what_it_did(reading(avg=1.752, step=0.01), TRIPS, 2.0,
                             step_ms=0.01, control=None, shift_ms=1.806)
        assert got["behaviour"] != tn.ONE_CLOCK
        assert got["moved_from_control_ms"] == {}

    def test_the_undecided_run_prints_both_numbers_a_reader_needs(self):
        control = reading(avg=1.75, step=0.001)
        got = tn.what_it_did(reading(avg=1.74, step=0.001), TRIPS, 2.0,
                             plain=reading(avg=1.75, step=0.001),
                             step_ms=0.001, control=control, shift_ms=1.806)
        assert not got["decided"]
        assert "1.806" in got["why"], "the shift that was confirmed"
        assert "0.010" in got["why"], "and how far the figures actually moved"

    def test_a_figure_that_will_not_subtract_is_skipped_rather_than_crashing(self):
        control = reading(avg=1.75, step=0.01)
        control["reported_ms"]["max"] = "n/a"
        offset = reading(avg=1.752, step=0.01)
        offset["reported_ms"]["max"] = 9.0
        moved_by, moved = tn.figures_moved(offset, control, 0.01)
        assert "max" not in moved_by and moved is False

    def test_both_numbers_reach_the_page_a_person_reads(self):
        control = reading(avg=1.75, step=0.01)
        got = tn.what_it_did(reading(avg=1.752, step=0.01), TRIPS, 2.0,
                             step_ms=0.01, control=control, shift_ms=1.806)
        page = "\n".join(tn.lines(got))
        assert "move 1.806 ms" in page and "its figures moved" in page


class TestTheJudgementOfFreeze21:
    """D25-1 and D25-2. The judge held every hypothesis to a tool's printing step and compared
    against T1's zero step. Two runs of one tool minutes apart differ by far more than a printing
    step, so a tool whose figures did not move was ruled out of "did not move" by its own scatter.
    """

    #: The four behaviours at a 2 ms shift over TRIPS predict, on the average: keeps -2.0,
    #: replaces with zero -1.25, the two drops -0.75. One clock predicts no change at all.
    CONTROL = reading(avg=1.75, low=0.5, step=0.001)

    def test_a_tool_whose_figures_stayed_within_their_noise_times_against_one_clock(self):
        """valkey-benchmark on 24 September: average up 0.075 ms under a clock moved back 1.78."""
        got = tn.what_it_did(reading(avg=1.825, low=0.58, step=0.001), TRIPS, 1.812,
                             control=self.CONTROL, shift_ms=2.0, noise={"avg": 0.05, "min": 0.05})
        assert got["decided"] and got["behaviour"] == tn.ONE_CLOCK
        assert "moved 2.000 ms" in got["why"]

    def test_the_same_run_held_to_the_printing_step_could_not_say_so(self):
        """What D23-1 as implemented made of it: one step of 0.001 ms, against 0.075 of noise."""
        got = tn.what_it_did(reading(avg=1.825, low=0.58, step=0.001), TRIPS, 1.812,
                             control=self.CONTROL, shift_ms=2.0)
        assert not got["decided"]

    def test_a_tool_whose_figures_moved_with_the_clock_is_told_apart_by_the_behaviours(self):
        got = tn.what_it_did(reading(avg=-0.25, low=-1.5, step=0.001), TRIPS, 1.9,
                             control=self.CONTROL, shift_ms=2.0, noise={"avg": 0.05, "min": 0.05})
        assert got["decided"] and got["behaviour"] == "keeps every value"
        assert tn.ONE_CLOCK in got["ruled_out"], "one clock predicts no change and it moved 2 ms"

    def test_it_predicts_at_the_offset_measured_at_the_clock(self):
        got = tn.what_it_did(reading(avg=-0.25, low=-1.5), TRIPS, 1.9, control=self.CONTROL,
                             shift_ms=2.0, noise={"avg": 0.05})
        assert got["asked_ms"] == 1.9 and got["offset_ms"] == 2.0

    def test_the_allowance_is_three_noises_of_a_difference_and_never_under_two_steps(self):
        got = tn.what_it_did(reading(avg=1.75, low=0.5, step=0.01), TRIPS, 2.0,
                             control=self.CONTROL, shift_ms=2.0, noise={"avg": 0.1, "min": 0.0})
        assert got["allowed_ms"]["avg"] == pytest.approx(3.0 * 0.1 * 2.0 ** 0.5)
        assert got["allowed_ms"]["min"] == pytest.approx(0.02), "two steps of 0.01, not zero"

    def test_a_figure_with_no_noise_is_not_judged(self):
        got = tn.what_it_did(reading(avg=1.75, low=0.5), TRIPS, 2.0, control=self.CONTROL,
                             shift_ms=2.0, noise={"avg": 0.05})
        assert list(got["changes_ms"]) == ["avg"]

    def test_with_no_figure_to_judge_it_says_so(self):
        got = tn.what_it_did(reading(avg=1.75), TRIPS, 2.0, control=self.CONTROL, shift_ms=2.0,
                             noise={})
        assert not got["decided"] and "no figure could be judged" in got["why"]

    def test_a_tool_no_hypothesis_accounts_for_is_undecided_with_every_prediction(self):
        got = tn.what_it_did(reading(avg=9.0, low=9.0), TRIPS, 2.0, control=self.CONTROL,
                             shift_ms=2.0, noise={"avg": 0.01, "min": 0.01})
        assert not got["decided"] and "none of the five" in got["why"]
        assert set(got["predicted_changes_ms"]) == set(got["expected"]) | {tn.ONE_CLOCK}

    def test_a_tool_too_noisy_for_its_offset_is_undecided_between_what_survives(self):
        """rdkafka_performance: about 1.1 ms of noise against a 3.4 ms offset."""
        got = tn.what_it_did(reading(avg=0.75, low=0.0), TRIPS, 2.0, control=self.CONTROL,
                             shift_ms=2.0, noise={"avg": 1.1, "min": 1.1})
        assert not got["decided"] and tn.ONE_CLOCK in got["still_standing"]
        assert "within its own noise" in got["why"]

    def test_two_clocks_with_no_negative_made_is_said_to_be_two_clocks(self):
        """Every trip clears the offset, so the four give the same figures -- but they moved."""
        trips = [3.0] * 20
        got = tn.what_it_did(reading(avg=2.0, low=2.0), trips, 1.0,
                             control=reading(avg=3.0, low=3.0), shift_ms=1.0,
                             noise={"avg": 0.01, "min": 0.01})
        assert tn.ONE_CLOCK in got["ruled_out"] and len(got["still_standing"]) == 4
        assert "spans two clocks" in got["why"]

    def test_a_count_short_of_what_was_sent_still_rules_behaviours_out(self):
        got = tn.what_it_did(reading(avg=1.0, low=1.0, kept=10), TRIPS_ON_ZERO, 2.0,
                             control=reading(avg=1.725, low=0.5), shift_ms=2.0,
                             noise={"avg": 0.5, "min": 0.5})
        assert "it counted 10" in got["ruled_out"]["drops the negatives"]
        assert tn.ONE_CLOCK not in got["ruled_out"] or "counted" not in \
            got["ruled_out"][tn.ONE_CLOCK], "the count is a question for the four, as before"

    def test_a_behaviour_that_would_leave_nothing_is_ruled_out_by_a_printed_figure(self):
        got = tn.what_it_did(reading(avg=-2.5, low=-2.5), [0.5] * 20, 3.0,
                             control=reading(avg=0.5, low=0.5), shift_ms=3.0,
                             noise={"avg": 0.05, "min": 0.05})
        assert "nothing to print" in got["ruled_out"]["drops the negatives"]
        assert got["predicted_changes_ms"]["drops the negatives"] is None

    def test_the_page_shows_every_number_it_was_decided_on(self):
        got = tn.what_it_did(reading(avg=-2.5, low=-2.5), [0.5] * 20, 3.0,
                             control=reading(avg=0.5, low=0.5), shift_ms=3.0,
                             noise={"avg": 0.05, "min": 0.05})
        page = "\n".join(tn.lines(got))
        assert "judged under freeze 21" in page and "its own noise is 0.0500" in page
        assert "predicts nothing to print" in page and "one clock" in page


class TestTheNoiseComesFromTheStaircase:

    def test_it_is_what_is_left_about_the_line_of_the_figure_against_the_delay(self):
        points = [(d, reading(avg=1.0 + d + e, low=0.5 + d))
                  for d, e in ((0.0, 0.1), (0.5, -0.1), (1.0, 0.1), (1.5, -0.1))]
        found = tn.noise_from_staircase(points)
        said = "the fitted slope of 0.92 leaves residuals of 0.04 and 0.12, not the raw 0.1"
        assert found["avg"] == pytest.approx(0.1265, abs=1e-4), said
        assert found["min"] == pytest.approx(0.0, abs=1e-12), "a perfect line leaves nothing"

    def test_a_figure_at_fewer_than_three_steps_has_no_noise(self):
        points = [(0.0, reading(avg=1.0)), (1.0, reading(avg=2.0, low=1.0)),
                  (2.0, reading(avg=3.1, low=2.0))]
        found = tn.noise_from_staircase(points)
        assert "avg" in found and "min" not in found

    def test_steps_all_at_one_delay_are_held_to_their_mean(self):
        found = tn.noise_from_staircase([(1.0, reading(avg=v)) for v in (1.0, 1.2, 1.4)])
        assert found["avg"] == pytest.approx(((0.04 + 0.0 + 0.04) / 1) ** 0.5)

    def test_it_is_read_from_the_folders_t1_writes(self, tmp_path):
        for name, value in (("t1-vx-0ms", 1.0), ("t1-vx-0_5ms", 1.5), ("t1-vx-1_1ms", 2.1)):
            (tmp_path / name).mkdir()
            (tmp_path / name / "reading.json").write_text(
                json.dumps(reading(avg=value)), encoding="utf-8")
        (tmp_path / "t1-vx-2_0ms").mkdir()                                  # no reading at all
        (tmp_path / "t1-vx-1_5ms").mkdir()
        (tmp_path / "t1-vx-1_5ms" / "reading.json").write_text(
            json.dumps(reading()), encoding="utf-8")                        # reported nothing
        (tmp_path / "t1-vx-step.json").write_text("{}", encoding="utf-8")   # not a step
        found = tn.staircase(str(tmp_path), "vx")
        assert sorted(d for d, _ in found) == [0.0, 0.5, 1.1]


class TestTheRunsThatCannotAnswer:

    def test_a_tool_that_printed_nothing_and_died_is_reported_as_that(self):
        got = tn.what_it_did(reading(), TRIPS, 2.0, exit_code=134)
        assert not got["decided"] and got["behaviour"] is None
        assert "crashed" in got["why"]

    def test_a_tool_that_finished_and_printed_nothing_is_a_different_thing(self):
        got = tn.what_it_did(reading(), TRIPS, 2.0, exit_code=0)
        assert not got["decided"] and "ran to the end" in got["why"]

    def test_without_reference_trips_there_is_nothing_to_compare(self):
        got = tn.what_it_did(reading(avg=1.0), [], 2.0)
        assert not got["decided"] and "nothing to compare" in got["why"]

    def test_an_offset_too_small_to_make_a_negative_asks_no_question(self):
        got = tn.what_it_did(reading(avg=1.5), TRIPS, 0.25)
        assert not got["decided"] and "made no negative value" in got["why"]

    def test_two_behaviours_that_agree_leave_the_run_without_an_answer(self):
        """With no trip landing on the offset, dropping the negatives and dropping zero with
        them are the same thing. Naming either would be reading a decision out of a coin."""
        got = tn.what_it_did(reading(avg=1.0, low=1.0, kept=10), TRIPS, 2.0)
        assert not got["decided"]
        assert got["still_standing"] == ["drops the negatives", "drops zero and below"]
        assert "does not say which" in got["why"]

    def test_a_tool_too_coarse_to_separate_two_behaviours_does_not_decide(self):
        """Printing whole milliseconds, it reported the same number whichever it did."""
        got = tn.what_it_did(reading(avg=0.0, step=1.0), TRIPS, 2.0)
        assert not got["decided"] and len(got["still_standing"]) > 1

    def test_a_behaviour_that_would_have_left_nothing_is_ruled_out_by_the_tool_printing(self):
        """Both dropping rules leave this run empty, so no figure of theirs can be compared with
        anything. The tool having printed an average at all is what rules them out."""
        got = tn.what_it_did(reading(avg=-1.5, low=-1.5), [0.5, 0.5], 2.0)
        assert got["decided"] and got["behaviour"] == "keeps every value"
        assert "left it nothing to print" in got["ruled_out"]["drops the negatives"]


class TestSayingItInWords:

    def test_a_decided_run_reads_as_a_verdict(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=0.5, low=0.0, kept=20), TRIPS, 2.0)))
        assert "VERDICT" in said and "replaces the negatives with zero" in said
        assert "10 of 20 trips go below zero" in said
        assert "it counted 20 of 20 sent" in said
        assert "ruled out" in said, "and why each of the others cannot be what it did"

    def test_an_undecided_run_says_undecided_and_why(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=1.5), TRIPS, 0.25)))
        assert "UNDECIDED" in said and "made no negative value" in said

    def test_a_count_that_does_not_match_is_pointed_at(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=1.0, kept=10), TRIPS, 2.0)))
        assert "they do not match" in said

    def test_no_count_and_no_average_are_both_said_plainly(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(), TRIPS, 2.0)))
        assert "reported no average" in said and "reports no count" in said

    def test_a_behaviour_that_left_nothing_says_so_instead_of_printing_a_number(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=-1.5), [0.5, 0.5], 2.0)))
        assert "nothing survives" in said

    def test_a_behaviour_ruled_out_before_the_figures_were_compared_says_so(self):
        """Nothing was compared at all when the tool printed nothing, so no behaviour carries a
        reason; the line must still be readable rather than raising."""
        verdict = tn.what_it_did(reading(), TRIPS, 2.0)
        verdict["still_standing"] = []
        assert "not compared" in "\n".join(tn.lines(verdict))


class TestReadingTheReference:

    def test_a_json_list_of_trips(self, tmp_path):
        path = tmp_path / "trips.json"
        path.write_text(json.dumps([1.0, 2.0]), encoding="utf-8")
        assert tn.reference_trips(str(path)) == [1.0, 2.0]

    def test_a_json_object_the_harness_writes(self, tmp_path):
        path = tmp_path / "trips.json"
        path.write_text(json.dumps({"trips_ms": [1.0, 2.0]}), encoding="utf-8")
        assert tn.reference_trips(str(path)) == [1.0, 2.0]

    def test_one_number_per_line(self, tmp_path):
        path = tmp_path / "trips.txt"
        path.write_text("1.0\n2.0\n", encoding="utf-8")
        assert tn.reference_trips(str(path)) == [1.0, 2.0]


class TestTheCommand:

    def write(self, tmp_path, trips, **figures):
        r = tmp_path / "reading.json"
        r.write_text(json.dumps(reading(**figures)), encoding="utf-8")
        t = tmp_path / "trips.json"
        t.write_text(json.dumps(trips), encoding="utf-8")
        return str(r), str(t)

    def run(self, argv):
        out = io.StringIO()
        return tn.main(argv, out), out.getvalue()

    def test_a_decided_run_leaves_with_zero(self, tmp_path):
        r, t = self.write(tmp_path, TRIPS, avg=0.5, low=0.0, kept=20)
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0"])
        assert code == 0 and "VERDICT" in said

    def test_an_undecided_run_leaves_with_one_so_a_campaign_notices(self, tmp_path):
        r, t = self.write(tmp_path, TRIPS, avg=1.5)
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "0.25"])
        assert code == 1 and "UNDECIDED" in said

    def test_it_can_be_given_the_same_tools_reading_with_nothing_moved(self, tmp_path):
        r, t = self.write(tmp_path, TRIPS, avg=-0.75, step=0.1)
        plain = tmp_path / "plain.json"
        plain.write_text(json.dumps(reading(avg=1.25, step=0.1)), encoding="utf-8")
        code, _ = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0",
                            "--plain", str(plain)])
        assert code == 0, "its own bias cancels, so the run decides"

    def test_it_can_be_given_the_control_run_and_the_shift_that_was_measured(self, tmp_path):
        """D23-1 through the command, which is how the campaign reaches it."""
        r, t = self.write(tmp_path, TRIPS, avg=1.752, step=0.01)
        control = tmp_path / "control.json"
        control.write_text(json.dumps(reading(avg=1.75, step=0.01)), encoding="utf-8")
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0",
                               "--step-ms", "0.01", "--control", str(control),
                               "--shift-ms", "1.806"])
        assert code == 0, "the clock moved and the figures did not, which is a verdict"
        assert tn.ONE_CLOCK in said, "the page names the verdict it reached"
        assert "move 1.806 ms" in said, "and the shift it was decided on"

    def test_given_the_staircase_it_judges_as_freeze_21_says(self, tmp_path):
        """How tools.sh calls it from D25-2 on: the T1 runs beside the T2 ones."""
        for name, value in (("t1-vx-0ms", 1.70), ("t1-vx-0_5ms", 2.30), ("t1-vx-1_0ms", 2.72),
                            ("t1-vx-1_5ms", 3.28)):
            (tmp_path / name).mkdir()
            (tmp_path / name / "reading.json").write_text(
                json.dumps(reading(avg=value, low=value - 1.25)), encoding="utf-8")
        r, t = self.write(tmp_path, TRIPS, avg=1.80, low=0.55, step=0.001)
        control = tmp_path / "control.json"
        control.write_text(json.dumps(reading(avg=1.75, low=0.5, step=0.001)), encoding="utf-8")
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "1.9",
                               "--shift-ms", "2.0", "--control", str(control),
                               "--staircase", str(tmp_path), "--tool", "vx"])
        assert code == 0 and tn.ONE_CLOCK in said and "judged under freeze 21" in said

    def test_a_staircase_without_its_tool_is_refused(self, tmp_path):
        r, t = self.write(tmp_path, TRIPS, avg=1.8)
        with pytest.raises(SystemExit):
            self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0",
                      "--staircase", str(tmp_path)])

    def test_it_can_be_told_the_step_the_tool_reads_in(self, tmp_path):
        r, t = self.write(tmp_path, [3.0] * 20, avg=-3.0, low=-3.0, kept=20, step=1.0)
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "6.0",
                               "--step-ms", "1.0"])
        assert code == 0 and "keeps every value" in said

    def test_it_can_write_the_verdict_beside_the_run(self, tmp_path):
        r, t = self.write(tmp_path, TRIPS, avg=0.5, low=0.0, kept=20)
        where = tmp_path / "verdict.json"
        code, _ = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0",
                            "--sent", "20", "--exit-code", "0", "--out", str(where)])
        assert code == 0
        assert json.loads(where.read_text(encoding="utf-8"))["behaviour"] == \
            "replaces the negatives with zero"
