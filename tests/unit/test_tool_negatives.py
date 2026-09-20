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
        assert got["still_standing"] == [] and "never reached its subtraction" in got["why"]


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
