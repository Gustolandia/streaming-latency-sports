"""T2: naming what a tool did with a latency the subtraction pushed below zero.

The temptation in a script like this is to always produce an answer. Four behaviours predict four
averages, the tool reported one number, and something is always nearest. But a tool whose printing
cannot separate two of those averages has not told us which it did, and an offset that made no
negatives has not asked the question at all. So most of what is tested here is the script
declining to answer -- and declining for a stated reason.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import tool_negatives as tn  # noqa: E402

#: Ten trips at 3 ms and ten at 0.5 ms. At an offset of 2 ms the short ones go negative.
TRIPS = [3.0] * 10 + [0.5] * 10


def reading(avg=None, kept=None, step=0.001, **rest):
    """A reading in the shape tool_readings produces, with only what this script reads."""
    got = {} if avg is None else {"avg": avg}
    out = {"tool": "made up", "reported_ms": got, "steps_ms": {"avg": step},
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
        said = tn.predictions(TRIPS, 2.0)
        assert said["keeps every value"]["avg_ms"] == pytest.approx(-0.25)
        assert said["drops the negatives"]["avg_ms"] == pytest.approx(1.0)
        assert said["drops zero and below"]["avg_ms"] == pytest.approx(1.0)
        assert said["replaces the negatives with zero"]["avg_ms"] == pytest.approx(0.5)

    def test_each_behaviour_also_predicts_a_count(self):
        said = tn.predictions(TRIPS, 2.0)
        assert said["keeps every value"]["count"] == 20
        assert said["drops the negatives"]["count"] == 10
        assert said["replaces the negatives with zero"]["count"] == 20

    def test_zeros_are_what_separates_dropping_the_negatives_from_dropping_them_too(self):
        """A trip of exactly the offset lands on zero. One behaviour keeps it and one does not,
        and that is the only thing that tells those two apart."""
        said = tn.predictions([3.0, 2.0], 2.0)
        assert said["drops the negatives"]["count"] == 2
        assert said["drops zero and below"]["count"] == 1

    def test_a_behaviour_that_leaves_nothing_has_no_average_rather_than_a_zero(self):
        said = tn.predictions([0.5, 0.5], 2.0)
        assert said["drops the negatives"]["avg_ms"] is None
        assert said["keeps every value"]["avg_ms"] == pytest.approx(-1.5)


class TestNamingWhatTheToolDid:

    def test_a_tool_that_kept_them_all_is_named(self):
        got = tn.what_it_did(reading(avg=-0.25), TRIPS, 2.0)
        assert got["decided"] and got["behaviour"] == "keeps every value"

    def test_a_tool_that_replaced_them_with_zero_is_named(self):
        got = tn.what_it_did(reading(avg=0.5), TRIPS, 2.0)
        assert got["decided"] and got["behaviour"] == "replaces the negatives with zero"

    def test_a_tool_that_dropped_them_is_named(self):
        got = tn.what_it_did(reading(avg=1.0, kept=10), TRIPS, 2.0)
        assert got["decided"] and got["behaviour"] == "drops the negatives"

    def test_its_count_is_checked_against_what_was_sent(self):
        got = tn.what_it_did(reading(avg=1.0, kept=10), TRIPS, 2.0)
        assert got["count_matches_sent"] is False
        assert "drops the negatives" in got["count_agrees_with"]

    def test_a_count_that_matches_is_reported_as_matching(self):
        got = tn.what_it_did(reading(avg=-0.25, kept=20), TRIPS, 2.0)
        assert got["count_matches_sent"] is True

    def test_a_tool_that_reports_no_count_is_not_held_to_one(self):
        got = tn.what_it_did(reading(avg=-0.25), TRIPS, 2.0)
        assert got["count_matches_sent"] is None and got["count_agrees_with"] == []

    def test_how_many_were_sent_can_be_told_rather_than_counted(self):
        """The tool's own run may be longer than the reference sample we hold."""
        got = tn.what_it_did(reading(avg=-0.25, kept=20), TRIPS, 2.0, sent=5000)
        assert got["sent"] == 5000 and got["count_matches_sent"] is False


class TestTheRunsThatCannotAnswer:

    def test_a_tool_that_printed_nothing_and_died_is_reported_as_that(self):
        got = tn.what_it_did(reading(), TRIPS, 2.0, exit_code=134)
        assert not got["decided"] and got["behaviour"] is None
        assert "crashed" in got["why"]

    def test_a_tool_that_finished_and_printed_no_average_is_a_different_thing(self):
        got = tn.what_it_did(reading(), TRIPS, 2.0, exit_code=0)
        assert not got["decided"] and "ran to the end" in got["why"]

    def test_without_reference_trips_there_is_nothing_to_compare(self):
        got = tn.what_it_did(reading(avg=1.0), [], 2.0)
        assert not got["decided"] and "nothing to compare" in got["why"]

    def test_an_offset_too_small_to_make_a_negative_asks_no_question(self):
        got = tn.what_it_did(reading(avg=0.25), TRIPS, 0.25)
        assert not got["decided"]
        assert "made no negative value" in got["why"]

    def test_a_tool_too_coarse_to_separate_two_behaviours_does_not_decide(self):
        """Dropping the negatives and dropping zero with them differ by 0.05 ms here. A tool
        printing whole milliseconds reported the same number either way, and saying which it did
        would be reading a difference out of a figure that cannot carry one."""
        trips = [3.0] * 10 + [2.0] + [0.5] * 9
        got = tn.what_it_did(reading(avg=1.0, step=1.0), trips, 2.0)
        assert not got["decided"] and "cannot separate them" in got["why"]

    def test_two_behaviours_that_coincide_are_stepped_over_rather_than_compared(self):
        """Dropping the negatives and dropping zero with them agree exactly whenever no trip
        lands on the offset. Comparing the nearest against its own twin would call every such run
        undecided; the comparison has to be against a behaviour predicting a different number."""
        got = tn.what_it_did(reading(avg=1.0), TRIPS, 2.0)
        said = tn.predictions(TRIPS, 2.0)
        assert said["drops the negatives"]["avg_ms"] == said["drops zero and below"]["avg_ms"]
        assert got["decided"] and got["behaviour"] == "drops the negatives"

    def test_a_tool_whose_clock_never_moved_is_not_asked_about_negatives(self):
        """libfaketime moves a whole process. A tool that writes both timestamps itself has both
        moved together and subtracts the same difference as before, so its average sits where it
        always did. That says T2 does not reach it, not that it keeps negatives."""
        got = tn.what_it_did(reading(avg=1.75), TRIPS, 2.0)
        assert not got["decided"] and got["behaviour"] is None
        assert "never reached its subtraction" in got["why"]


class TestSayingItInWords:

    def test_a_decided_run_reads_as_a_verdict(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=0.5, kept=20), TRIPS, 2.0)))
        assert "VERDICT" in said and "replaces the negatives with zero" in said
        assert "10 of 20 trips go below zero" in said
        assert "it counted 20 of 20 sent" in said

    def test_an_undecided_run_says_undecided_and_why(self):
        said = "\n".join(tn.lines(tn.what_it_did(reading(avg=0.25), TRIPS, 0.25)))
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

    def write(self, tmp_path, avg, trips, kept=None):
        r = tmp_path / "reading.json"
        r.write_text(json.dumps(reading(avg=avg, kept=kept)), encoding="utf-8")
        t = tmp_path / "trips.json"
        t.write_text(json.dumps(trips), encoding="utf-8")
        return str(r), str(t)

    def run(self, argv):
        out = io.StringIO()
        return tn.main(argv, out), out.getvalue()

    def test_a_decided_run_leaves_with_zero(self, tmp_path):
        r, t = self.write(tmp_path, 0.5, TRIPS, kept=20)
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0"])
        assert code == 0 and "VERDICT" in said

    def test_an_undecided_run_leaves_with_one_so_a_campaign_notices(self, tmp_path):
        r, t = self.write(tmp_path, 0.25, TRIPS)
        code, said = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "0.25"])
        assert code == 1 and "UNDECIDED" in said

    def test_it_can_write_the_verdict_beside_the_run(self, tmp_path):
        r, t = self.write(tmp_path, 0.5, TRIPS, kept=20)
        where = tmp_path / "verdict.json"
        code, _ = self.run(["judge", "--reading", r, "--reference", t, "--offset-ms", "2.0",
                            "--sent", "20", "--exit-code", "0", "--out", str(where)])
        assert code == 0
        assert json.loads(where.read_text(encoding="utf-8"))["behaviour"] == \
            "replaces the negatives with zero"
