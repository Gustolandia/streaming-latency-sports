"""The clock check both clients hold, and the bar it enforces.

A8 compares our Python client with Kafka's official Java one. The Java client has refused to run
on a clock too coarse to see the effect since it was written; this is the same rule on the Python
side, and these hold the two to the same number.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_clock  # noqa: E402


def ticking(*steps):
    """A clock that returns each step in turn, then stays where it ended."""
    readings = [0]
    for step in steps:
        readings.append(readings[-1] + step)

    def clock():
        return readings.pop(0) if len(readings) > 1 else readings[0]
    return clock


class TestReadingTheClock:

    def test_it_reads_wall_time_and_not_a_process_relative_origin(self):
        import time
        assert abs(law_clock.now_ns() - time.time_ns()) < 1_000_000_000

    def test_the_finest_step_is_the_smallest_one_that_moved(self):
        assert law_clock.resolution_ns(3, clock=ticking(500, 100, 900)) == 100

    def test_a_clock_that_never_moves_cannot_be_characterised(self):
        """Zero, not "infinitely fine": the two must not be confused, and both are refused."""
        assert law_clock.resolution_ns(3, clock=ticking(0, 0, 0)) == 0

    def test_a_step_that_does_not_move_forward_is_not_a_resolution(self):
        assert law_clock.resolution_ns(3, clock=ticking(0, 400, 0)) == 400

    def test_a_later_coarser_step_does_not_replace_the_finest(self):
        assert law_clock.resolution_ns(3, clock=ticking(50, 800, 900)) == 50

    def test_it_reads_the_real_clock_when_none_is_given(self):
        assert law_clock.resolution_ns(500) >= 0


class TestTheBarAClockHasToClear:

    def test_a_fine_enough_clock_passes_and_reports_its_step(self):
        assert law_clock.demand_usable_resolution(
            "the producer", 3, clock=ticking(1000, 1000, 1000)) == 1000

    def test_the_bar_is_ten_parts_of_the_quarter_millisecond_p2d_and_p3a_are_judged_against(self):
        # Not ten parts of the 1 ms cliff, which would be 100 us and only 2.5 parts of 0.25 ms.
        assert law_clock.FINEST_USABLE_NS == 25_000

    def test_a_clock_at_the_bar_exactly_is_allowed(self):
        assert law_clock.demand_usable_resolution(
            "the producer", 2, clock=ticking(25_000, 25_000)) == 25_000

    def test_a_clock_one_step_coarser_than_the_bar_stops_the_run(self):
        with pytest.raises(SystemExit) as stopped:
            law_clock.demand_usable_resolution(
                "the producer", 2, clock=ticking(25_001, 25_001))
        assert "STOP_RULE" in str(stopped.value) and "25001 ns" in str(stopped.value)

    def test_the_windows_millisecond_clock_is_refused_by_name(self):
        with pytest.raises(SystemExit) as stopped:
            law_clock.demand_usable_resolution(
                "the consumer", 2, clock=ticking(998_600, 998_600))
        assert "the consumer will not run on this clock" in str(stopped.value)

    def test_a_clock_that_never_moved_stops_the_run_too(self):
        with pytest.raises(SystemExit) as stopped:
            law_clock.demand_usable_resolution("the producer", 2, clock=ticking(0, 0))
        assert "steps in 0 ns" in str(stopped.value)

    def test_the_linux_testbed_clocks_both_clear_it(self):
        """1000 ns from the JVM and 232 ns from Python, as measured on the Arm driver."""
        for step in (1000, 232):
            assert law_clock.demand_usable_resolution(
                "the producer", 2, clock=ticking(step, step)) == step
