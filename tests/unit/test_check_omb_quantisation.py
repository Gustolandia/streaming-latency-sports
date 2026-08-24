"""Tests for scripts/check_omb_quantisation.py - target 100% branch coverage.

This script produced a number the response to the referee leans on: 36 of 40 reported latency
values were exactly whole milliseconds. That is the corroboration for the claim that OMB's
end-to-end latency carries no sub-millisecond structure, and until now it was computed by a
file that nothing could import and no one but the author could run -- the same defect the paper
documents in others.

What the tests pin is the arithmetic behind that number: which values are counted, what "whole"
means, and that an absent value is not silently treated as a round one.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_omb_quantisation as coq  # noqa: E402


def _report(p50=1.0, p95=1.0, p99=1.0, mx=2.0, avg=1.0):
    return {"endToEndLatency50pct": p50, "endToEndLatency95pct": p95,
            "endToEndLatency99pct": p99, "endToEndLatencyMax": mx,
            "endToEndLatencyAvg": avg}


@pytest.fixture
def omb(tmp_path):
    """Write OMB-shaped result files; returns the directory."""
    def write(reports):
        for i, report in enumerate(reports):
            path = tmp_path / ("omb_workload-Kafka-2026-08-24-%02d.json" % i)
            path.write_text(json.dumps(report), encoding="utf-8")
        return str(tmp_path)
    return write


class TestRunFiles:

    def test_only_kafka_workload_reports_are_picked_up(self, tmp_path):
        (tmp_path / "omb_workload-Kafka-a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "omb_workload-Redis-a.json").write_text("{}", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        found = coq.run_files(str(tmp_path))
        assert [Path(f).name for f in found] == ["omb_workload-Kafka-a.json"]

    def test_it_keeps_the_most_recent_runs_not_the_first(self, omb):
        directory = omb([_report() for _ in range(12)])
        found = coq.run_files(directory, last=8)
        assert len(found) == 8
        assert Path(found[-1]).name.endswith("11.json")

    def test_last_zero_means_every_run(self, omb):
        directory = omb([_report() for _ in range(12)])
        assert len(coq.run_files(directory, last=0)) == 12

    def test_an_empty_directory_yields_nothing(self, tmp_path):
        assert coq.run_files(str(tmp_path)) == []


class TestLastValue:
    """OMB writes a scalar in some versions and a per-interval list in others."""

    def test_a_scalar_is_returned_as_is(self):
        assert coq.last_value({"k": 1.5}, "k") == 1.5

    def test_a_list_yields_its_final_interval(self):
        """The run's value is the last interval, not the first and not the mean."""
        assert coq.last_value({"k": [9.0, 3.0, 1.0]}, "k") == 1.0

    def test_an_empty_list_is_not_a_value(self):
        assert coq.last_value({"k": []}, "k") == []

    def test_an_absent_key_is_none(self):
        assert coq.last_value({}, "k") is None


class TestPercentiles:

    def test_all_five_come_back_in_a_fixed_order(self):
        assert coq.percentiles(_report(1, 2, 3, 4, 5)) == [1, 2, 3, 4, 5]

    def test_a_missing_percentile_is_none_and_holds_its_place(self):
        report = _report()
        del report["endToEndLatency99pct"]
        assert coq.percentiles(report)[2] is None


class TestIsWhole:

    def test_an_integer_millisecond_is_whole(self):
        assert coq.is_whole(1.0)

    def test_a_sub_millisecond_value_is_not(self):
        assert not coq.is_whole(1.4)

    def test_floating_point_noise_does_not_break_it(self):
        """A Java-printed 1 ms can arrive as 0.9999999999; that is quantised, not structure."""
        assert coq.is_whole(1.0 - 1e-12)

    def test_the_tolerance_is_tight_enough_to_see_real_structure(self):
        """A microsecond of real sub-millisecond detail must not be rounded away."""
        assert not coq.is_whole(1.000001)


class TestWholeFraction:

    def test_it_counts_only_the_whole_ones(self):
        assert coq.whole_fraction([1.0, 2.0, 1.4, 3.0]) == (3, 4, 0.75)

    def test_missing_values_are_excluded_from_both_sides(self):
        """An absent percentile is not evidence of quantisation and not evidence against it."""
        assert coq.whole_fraction([1.0, None, None]) == (1, 1, 1.0)

    def test_nothing_numeric_has_no_fraction_rather_than_a_fraction_of_zero(self):
        """0/0 printed as 0% would read as 'no quantisation found', which is a lie."""
        assert coq.whole_fraction([None, None]) == (0, 0, None)
        assert coq.whole_fraction([]) == (0, 0, None)

    def test_booleans_are_not_numbers_here(self):
        """True is an int in Python and would count as a whole millisecond."""
        assert coq.whole_fraction([True, False]) == (0, 0, None)

    def test_integers_count(self):
        assert coq.whole_fraction([1, 2]) == (2, 2, 1.0)


class TestMain:

    def test_a_fully_quantised_set_reports_one_hundred_percent(self, omb, capsys):
        directory = omb([_report(1.0, 1.0, 1.0, 2.0, 1.0)])
        assert coq.main(["--dir", directory]) == 0
        out = capsys.readouterr().out
        assert "percentile values inspected: 5" in out
        assert "exactly whole milliseconds : 5  (100%)" in out

    def test_sub_millisecond_structure_shows_up_as_a_lower_fraction(self, omb, capsys):
        directory = omb([_report(0.4, 0.7, 1.0, 2.0, 0.6)])
        coq.main(["--dir", directory])
        assert "exactly whole milliseconds : 2  (40%)" in capsys.readouterr().out

    def test_an_absent_value_prints_a_dash_rather_than_a_number(self, omb, capsys):
        report = _report()
        del report["endToEndLatencyMax"]
        coq.main(["--dir", omb([report])])
        assert "        -" in capsys.readouterr().out

    def test_a_run_with_no_usable_values_reports_n_a(self, omb, capsys):
        directory = omb([{"endToEndLatency50pct": None}])
        assert coq.main(["--dir", directory]) == 0
        assert "(n/a)" in capsys.readouterr().out

    def test_per_interval_lists_are_reduced_to_the_final_interval(self, omb, capsys):
        directory = omb([_report(p50=[5.0, 1.0])])
        coq.main(["--dir", directory])
        assert "1.0" in capsys.readouterr().out

    def test_an_empty_directory_says_so_and_fails(self, tmp_path, capsys):
        assert coq.main(["--dir", str(tmp_path)]) == 1
        assert "no OMB result files" in capsys.readouterr().out

    def test_the_last_flag_limits_what_is_read(self, omb, capsys):
        directory = omb([_report() for _ in range(6)])
        coq.main(["--dir", directory, "--last", "2"])
        assert "percentile values inspected: 10" in capsys.readouterr().out

    def test_it_says_what_the_quantisation_implies(self, omb, capsys):
        """The conclusion is the point; a table of round numbers on its own proves nothing."""
        coq.main(["--dir", omb([_report()])])
        out = capsys.readouterr().out
        assert "no sub-millisecond resolution" in out
        assert "discarded by the > 0 guard" in out
