"""T1 and T2 run against made-up tools, to find out what they could answer before they are run.

These tests hold the two things that make a made-up tool behave like a real one -- how coarsely
its clock reads, and whether it reads that clock once or twice -- and then the two findings that
came out of running the block against them:

  the plan's smaller offset makes no negative at all on the trips these campaigns run, and
  a tool reading whole milliseconds needs the offset to clear its own step before a negative
  survives its subtraction to be handled at all.

Both were found here rather than on a machine, which is the whole purpose of the script.
"""
import io
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import tool_synthetic as ts  # noqa: E402


def rng():
    return random.Random(20260920)


class TestHowAToolsOwnClockChangesWhatItSees:

    def test_reading_once_rounds_the_answer_and_nothing_else(self):
        """It measures the difference in fine units, then rounds: at most one step of error, and
        it never depends on when the message was sent."""
        for paced in (True, False):
            assert ts.seen(rng(), 3.4, 1.0, "once", paced) == pytest.approx(3.0)

    def test_reading_twice_depends_on_where_in_the_tick_the_sending_fell(self):
        """Two rounded numbers subtracted. Sent on the tick, a 3.4 ms trip reads 3; sent 0.7 ms
        into it, the same trip reads 4. That is the error the plan predicts for this class."""
        assert ts.seen(rng(), 3.4, 1.0, "twice", True) == pytest.approx(3.0)
        sent_late = (int((0.7 + 3.4) / 1.0) - int(0.7 / 1.0)) * 1.0
        assert sent_late == pytest.approx(4.0)

    def test_rounding_is_toward_zero_as_integer_division_does_it(self):
        """A trip of 1.9 ms under a 2 ms offset is minus a tenth. Java and C give zero for that,
        not minus one, and the difference is the whole of what T2 measures."""
        assert ts.seen(rng(), 1.9, 1.0, "once", True, offset_ms=2.0) == 0.0

    def test_a_fine_clock_keeps_what_a_coarse_one_loses(self):
        assert ts.seen(rng(), 1.9, 1e-6, "once", True, offset_ms=2.0) == pytest.approx(-0.1)

    def test_trips_are_spread_about_their_median(self):
        drawn = ts.trips(rng(), 2000, 3.0, 0.25)
        assert len(drawn) == 2000
        assert sorted(drawn)[1000] == pytest.approx(3.0, abs=0.2)


class TestWhatSuchAToolWouldPrint:

    def test_it_prints_no_more_digits_than_it_has(self):
        assert ts.printed(3.41592, 2) == pytest.approx(3.42)
        assert ts.printed(None, 2) is None

    def test_a_reading_carries_a_step_for_every_figure(self):
        said = ts.reading([1.0, 2.0, 3.0], 2)
        assert said["step_ms"] == pytest.approx(0.01)
        assert set(said["steps_ms"]) == {"avg", "min", "p50", "p99"}
        assert said["kept"] == 3

    def test_a_tool_left_with_nothing_prints_nothing(self):
        said = ts.reading([], 2)
        assert said["reported_ms"] == {} and said["step_ms"] is None and said["kept"] == 0

    def test_what_it_does_with_the_odd_values_decides_what_reaches_its_average(self):
        assert ts.surviving([-1.0, 0.0, 1.0], "keeps every value") == [-1.0, 0.0, 1.0]
        assert ts.surviving([-1.0, 0.0, 1.0], "drops the negatives") == [0.0, 1.0]
        assert ts.surviving([-1.0, 0.0, 1.0], "drops zero and below") == [1.0]
        assert ts.surviving([-1.0, 0.0, 1.0], "replaces the negatives with zero") == \
            [0.0, 0.0, 1.0]


class TestT1TheStaircase:

    def test_a_whole_millisecond_tool_cannot_report_a_tenth_of_one(self):
        """The audit's prediction for Kafka's EndToEndLatency, recovered from its own arithmetic
        rather than asserted."""
        steps = ts.t1(rng(), "millisecond", "once", "keeps every value", 0, messages=400)
        seen_at = [s["added_ms"] for s in steps if s["seen"]]
        assert 0.1 not in seen_at and max(seen_at) == 2.0

    def test_a_nanosecond_tool_reports_every_step_the_plan_adds(self):
        steps = ts.t1(rng(), "nanosecond", "once", "keeps every value", 3, messages=400)
        assert [s["added_ms"] for s in steps if s["seen"]] == list(ts.STAIRCASE[1:])

    def test_a_tool_that_reports_nothing_at_all_records_that_rather_than_a_zero(self):
        """Everything it measures rounds to zero and it drops zeros, so it prints nothing at any
        step. That is a reading of nothing, not a step of nothing."""
        steps = ts.t1(rng(), "millisecond", "once", "drops zero and below", 1,
                      messages=50, median_ms=0.3)
        assert steps[0]["reported_avg_ms"] is None and steps[0]["moved_ms"] is None
        assert not steps[0]["seen"] and steps[0]["off_by_ms"] is None


class TestT2ForcedNegatives:

    def a_class(self, name, offsets, messages=400, median_ms=3.0):
        clock, reads, odd, digits = ts.CLASSES[name]
        return ts.t2(rng(), clock, reads, odd, digits, messages=messages, median_ms=median_ms,
                     offsets=offsets)

    def test_the_plans_smaller_offset_makes_no_negative_on_these_trips(self):
        """0.5 ms against a 3 ms trip leaves every value comfortably positive. The experiment
        runs, costs what it costs, and asks nothing."""
        said = self.a_class("high, keeps all", (0.5,))[0]
        assert said["negatives_made"] == 0 and not said["decided"]

    def test_a_fine_clock_answers_at_the_plans_larger_offset(self):
        assert self.a_class("high, keeps all", (2.0,))[0]["right"]

    def test_a_whole_millisecond_clock_does_not(self):
        """Truncation toward zero puts everything between minus one and plus one at zero, so at
        a 2 ms offset against 3 ms trips this tool never meets a negative."""
        said = self.a_class("low, drops the negatives", (2.0,))[0]
        assert said["negatives_made"] == 0 and not said["decided"]

    def test_an_offset_that_clears_its_step_does(self):
        assert self.a_class("low, drops the negatives", (6.0,))[0]["right"]

    @pytest.mark.parametrize("name", sorted(ts.CLASSES))
    def test_every_class_is_named_once_the_offset_clears_its_step(self, name):
        """The finding this script exists for: at the trip plus three milliseconds, each of the
        six is named from its own figures, and none is named wrongly."""
        said = self.a_class(name, (6.0,), messages=2000)[0]
        assert said["right"], "%s: %s" % (name, said["why"])

    def test_offsets_are_taken_from_the_trip_they_act_on(self):
        assert ts.reachable_offsets(3.0) == (4.0, 6.0)
        assert ts.reachable_offsets(1.5) == (2.5, 4.5)


class TestTheWholeReport:

    def test_it_covers_every_class_under_both_ways_of_sending(self):
        found = ts.report(messages=100)
        assert set(found) == set(ts.CLASSES)
        assert set(found["medium"]) == {"spread evenly", "paced with the tick"}
        assert len(found["medium"]["spread evenly"]["t1"]) == len(ts.STAIRCASE)

    def test_the_offsets_can_be_asked_for(self):
        found = ts.report(messages=100, offsets=(6.0,))
        assert [s["offset_ms"] for s in found["medium"]["spread evenly"]["t2"]] == [6.0]

    def test_it_reads_as_a_table_of_what_each_class_could_answer(self):
        said = "\n".join(ts.lines(ts.report(messages=100, offsets=(6.0,))))
        assert "smallest step it reports" in said and "T2 at 6.0 ms" in said

    def test_a_class_that_reports_no_step_at_all_says_so(self):
        found = {"made up": {"spread evenly": {
            "t1": [{"added_ms": 0.1, "seen": False, "off_by_ms": None}],
            "t2": [{"offset_ms": 2.0, "right": False, "decided": False, "named": None,
                    "why": "nothing to go on"}]}}}
        said = "\n".join(ts.lines(found))
        assert "none of them" in said and "unknown" in said and "undecided" in said

    def test_a_class_named_wrongly_is_pointed_at_rather_than_passed_over(self):
        found = {"made up": {"spread evenly": {
            "t1": [{"added_ms": 0.1, "seen": True, "off_by_ms": 0.02}],
            "t2": [{"offset_ms": 2.0, "right": False, "decided": True,
                    "named": "drops the negatives", "why": ""}]}}}
        said = "\n".join(ts.lines(found))
        assert "names the wrong one (drops the negatives)" in said


class TestTheCommand:

    def run(self, argv):
        out = io.StringIO()
        return ts.main(argv, out), out.getvalue()

    def test_the_plans_own_offsets_leave_classes_unanswered_so_it_leaves_with_one(self):
        code, said = self.run(["report", "--messages", "200"])
        assert code == 1 and "made no negative value" in said

    def test_offsets_that_clear_every_step_leave_with_zero(self):
        code, _ = self.run(["report", "--messages", "800", "--offsets", "6.0"])
        assert code == 0, "every class named, which is what makes the block worth running"

    def test_it_can_write_what_it_found_beside_the_run(self, tmp_path):
        where = tmp_path / "synthetic.json"
        code, _ = self.run(["report", "--messages", "100", "--offsets", "6.0",
                            "--seed", "7", "--median-ms", "3.0", "--spread", "0.25",
                            "--out", str(where)])
        found = json.loads(where.read_text(encoding="utf-8"))
        assert set(found) == set(ts.CLASSES) and code in (0, 1)
