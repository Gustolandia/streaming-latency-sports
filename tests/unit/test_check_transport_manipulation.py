"""Tests for scripts/check_transport_manipulation.py - target 100% branch coverage.

This is a manipulation check, which makes it the load-bearing part of two experiments: if
co-location did not shorten T_true, and if padding did not lengthen it, then the arms differ in
name only and every comparison downstream is between two copies of the same condition.

The direction of the verdict is pinned hardest. The tool was written for co-location, where the
second arm should be faster, and printed "shorter" unconditionally; used later on the padding
sweep, where the second arm should be slower, that word inverted the meaning of a correct
number. A label that can invert on a correct number is the failure mode this file exists to
prevent recurring.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_transport_manipulation as ctm  # noqa: E402


@pytest.fixture
def runs(tmp_path):
    """Write tti_summary.json files under a runs-shaped tree; returns the root."""
    root = tmp_path / "runs"

    def write(timestamp, backend, summaries):
        for i, summary in enumerate(summaries):
            d = root / ("concurrency_%s_%s_n%d" % (timestamp, backend, i))
            d.mkdir(parents=True, exist_ok=True)
            (d / "tti_summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return str(root)
    return write


def _summary(p50, p99=None):
    return {"transport_ms": {"p50": p50, **({"p99": p99} if p99 is not None else {})}}


class TestParseArms:

    def test_pairs_are_read_in_the_order_given(self):
        """The first arm is the reference; reordering them inverts every ratio."""
        arms = ctm.parse_arms(["base=111", "padded=222"])
        assert list(arms) == ["base", "padded"]
        assert arms == {"base": "111", "padded": "222"}

    def test_a_pair_with_no_timestamp_is_refused(self):
        with pytest.raises(ValueError, match="name=timestamp"):
            ctm.parse_arms(["base"])

    def test_an_empty_timestamp_is_refused(self):
        with pytest.raises(ValueError):
            ctm.parse_arms(["base="])

    def test_no_pairs_is_no_arms(self):
        assert ctm.parse_arms([]) == {}

    def test_a_timestamp_containing_an_equals_sign_keeps_it(self):
        assert ctm.parse_arms(["a=b=c"]) == {"a": "b=c"}


class TestTransportPercentiles:

    def test_every_run_of_one_arm_is_collected(self, runs):
        root = runs("111", "kafka", [_summary(1.0, 4.0), _summary(2.0, 5.0)])
        p50, p99 = ctm.transport_percentiles("111", "kafka", root)
        assert sorted(p50) == [1.0, 2.0]
        assert sorted(p99) == [4.0, 5.0]

    def test_another_arm_is_not_swept_in(self, runs):
        root = runs("111", "kafka", [_summary(1.0)])
        runs("222", "kafka", [_summary(9.0)])
        assert ctm.transport_percentiles("111", "kafka", root)[0] == [1.0]

    def test_another_backend_is_not_swept_in(self, runs):
        root = runs("111", "kafka", [_summary(1.0)])
        runs("111", "redis", [_summary(9.0)])
        assert ctm.transport_percentiles("111", "kafka", root)[0] == [1.0]

    def test_an_unreadable_summary_is_skipped_not_fatal(self, runs):
        """Interrupted runs leave partial writes; one must not hide the whole arm."""
        root = runs("111", "kafka", [_summary(1.0)])
        bad = Path(root) / "concurrency_111_kafka_broken"
        bad.mkdir(parents=True)
        (bad / "tti_summary.json").write_text("{not json", encoding="utf-8")
        assert ctm.transport_percentiles("111", "kafka", root)[0] == [1.0]

    def test_a_summary_with_no_transport_block_contributes_nothing(self, runs):
        root = runs("111", "kafka", [{"other": 1}])
        assert ctm.transport_percentiles("111", "kafka", root) == ([], [])

    def test_a_null_transport_block_contributes_nothing(self, runs):
        root = runs("111", "kafka", [{"transport_ms": None}])
        assert ctm.transport_percentiles("111", "kafka", root) == ([], [])

    def test_p50_and_p99_are_collected_independently(self, runs):
        root = runs("111", "kafka", [_summary(1.0), {"transport_ms": {"p99": 7.0}}])
        p50, p99 = ctm.transport_percentiles("111", "kafka", root)
        assert p50 == [1.0] and p99 == [7.0]

    def test_a_missing_root_yields_nothing(self, tmp_path):
        assert ctm.transport_percentiles("111", "kafka", str(tmp_path / "gone")) == ([], [])


class TestMedians:

    def test_an_arm_with_no_data_is_absent_rather_than_zero(self, runs):
        root = runs("111", "kafka", [_summary(1.0)])
        found = ctm.medians({"base": "111"}, root)
        assert ("base", "kafka") in found
        assert ("base", "redis") not in found, "no runs is not a median of zero"

    def test_the_median_is_over_runs(self, runs):
        root = runs("111", "kafka", [_summary(1.0), _summary(2.0), _summary(9.0)])
        assert ctm.medians({"base": "111"}, root)[("base", "kafka")][:2] == (3, 2.0)

    def test_p99_is_none_when_no_run_reported_one(self, runs):
        root = runs("111", "kafka", [_summary(1.0)])
        assert ctm.medians({"base": "111"}, root)[("base", "kafka")][2] is None


class TestDescribe:
    """The defect this tool once had, pinned from both sides."""

    def test_a_slower_second_arm_is_called_longer(self):
        line = ctm.describe("kafka", 1.0, 3.0, "padded")
        assert "LONGER in padded" in line
        assert "3.00x" in line

    def test_a_faster_second_arm_is_called_shorter(self):
        line = ctm.describe("kafka", 4.0, 1.0, "colocated")
        assert "shorter in colocated" in line
        assert "4.00x" in line

    def test_the_ratio_is_always_at_least_one_whichever_way_it_went(self):
        """A ratio below 1 printed next to the word 'shorter' reads as a typo, not a result."""
        for line in (ctm.describe("k", 1.0, 3.0, "b"), ctm.describe("k", 3.0, 1.0, "b")):
            factor = float(line.split("(")[1].split("x")[0])
            assert factor >= 1.0

    def test_equal_arms_read_as_no_change_not_as_longer(self):
        """A manipulation that did nothing must not be reported as having done something."""
        line = ctm.describe("kafka", 2.0, 2.0, "other")
        assert "shorter" in line and "1.00x" in line


class TestMain:

    def test_a_lengthened_transport_is_reported_as_such(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0, 2.0)])
        runs("222", "kafka", [_summary(3.0, 6.0)])
        assert ctm.main(["base=111", "padded=222", "--root", root]) == 0
        assert "LONGER in padded" in capsys.readouterr().out

    def test_a_shortened_transport_is_reported_as_such(self, runs, capsys):
        root = runs("111", "kafka", [_summary(4.0, 8.0)])
        runs("222", "kafka", [_summary(1.0, 2.0)])
        assert ctm.main(["base=111", "colocated=222", "--root", root]) == 0
        assert "shorter in colocated" in capsys.readouterr().out

    def test_both_backends_are_compared_when_both_have_data(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0, 2.0)])
        runs("111", "redis", [_summary(1.0, 2.0)])
        runs("222", "kafka", [_summary(2.0, 4.0)])
        runs("222", "redis", [_summary(2.0, 4.0)])
        ctm.main(["a=111", "b=222", "--root", root])
        out = capsys.readouterr().out
        assert "kafka: T_true" in out and "redis: T_true" in out

    def test_a_backend_present_in_only_one_arm_is_not_compared(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0, 2.0)])
        runs("111", "redis", [_summary(1.0, 2.0)])
        runs("222", "kafka", [_summary(2.0, 4.0)])
        ctm.main(["a=111", "b=222", "--root", root])
        out = capsys.readouterr().out
        assert "kafka: T_true" in out
        assert "redis: T_true" not in out, "an arm with no counterpart cannot be compared"

    def test_one_arm_cannot_be_a_comparison(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0)])
        assert ctm.main(["base=111", "--root", root]) == 1
        assert "at least two arms" in capsys.readouterr().out

    def test_no_arms_at_all_fails(self, capsys):
        assert ctm.main([]) == 1
        assert "at least two arms" in capsys.readouterr().out

    def test_two_arms_with_no_shared_data_fails_rather_than_printing_nothing(self, runs,
                                                                            capsys):
        """Silence would read as 'no change'. It is 'no measurement'."""
        root = runs("111", "kafka", [_summary(1.0)])
        runs("222", "redis", [_summary(1.0)])
        assert ctm.main(["a=111", "b=222", "--root", root]) == 1
        assert "no backend produced data in both arms" in capsys.readouterr().out

    def test_the_table_reports_the_run_count_behind_each_median(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0, 2.0), _summary(3.0, 4.0)])
        runs("222", "kafka", [_summary(1.0, 2.0)])
        ctm.main(["a=111", "b=222", "--root", root])
        assert "     2 " in capsys.readouterr().out

    def test_a_missing_p99_prints_a_dash_rather_than_crashing(self, runs, capsys):
        root = runs("111", "kafka", [_summary(1.0)])
        runs("222", "kafka", [_summary(2.0)])
        assert ctm.main(["a=111", "b=222", "--root", root]) == 0
        assert "-" in capsys.readouterr().out

    def test_a_malformed_pair_is_reported_as_a_value_error(self, runs):
        with pytest.raises(ValueError):
            ctm.main(["nonsense"])
