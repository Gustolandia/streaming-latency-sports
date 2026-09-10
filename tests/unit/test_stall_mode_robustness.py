r"""Tests for scripts/stall_mode_robustness.py --- target 100% branch coverage.

The script answers one question: is `trimodal` a property of the run-queue stalls, or of
`bpftrace`'s log2 bucket edges? The per-event durations were not retained, so rebinning raw
data is impossible; coarsening the retained histogram is what remains, and phasing the merge
two ways is what makes it a test rather than a restatement.

Two branches were nearly bought with coverage pragmas instead of earned. The project's own
gate refused them --- *100% is being bought, not earned* --- which was right, and both are
covered here on synthetic traces: a histogram with no buckets, and one whose modes are far
enough apart to survive a fourfold widening. The second matters beyond coverage. It shows the
measure is capable of returning the stronger answer, so the real trace's failure to survive
quadrupling is a finding rather than a limitation of the code.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import stall_mode_robustness as smr  # noqa: E402


def write_trace(tmp_path, rows):
    """A bpftrace-shaped log2 histogram: [(label, count)]."""
    lines = ["Attaching 3 probes...", "", "@usecs: "]
    for label, count in rows:
        lines.append("%-18s %8d |%s" % (label, count, "@" * 10))
    p = tmp_path / "runqlat.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


class TestReadingTheHistogram:
    def test_the_committed_trace_parses_to_sixteen_buckets(self):
        bins = smr.read_histogram()
        assert len(bins) == 16
        assert bins[0] == (1, 54682)
        assert sum(c for _, c in bins) == 551956

    def test_k_and_m_suffixes_become_microseconds(self):
        assert smr._us("512") == 512
        assert smr._us("1K") == 1024
        assert smr._us("2M") == 2 * 1024 * 1024

    def test_a_trace_with_no_buckets_fails_loudly(self, tmp_path):
        """The branch that was nearly excluded. A truncated trace must not read as zero modes."""
        p = tmp_path / "empty.txt"
        p.write_text("Attaching 3 probes...\n\n@count: 0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no log2 buckets"):
            smr.read_histogram(str(p))


class TestLocalMaxima:
    def test_a_peak_beats_both_neighbours(self):
        assert smr.local_maxima([1, 5, 1]) == [1]

    def test_the_edges_compare_against_one_side(self):
        assert smr.local_maxima([9, 1, 1]) == [0]
        assert smr.local_maxima([1, 1, 9]) == [2]

    def test_a_plateau_is_not_a_maximum(self):
        assert smr.local_maxima([1, 5, 5, 1]) == []

    def test_a_flat_histogram_has_none(self):
        assert smr.local_maxima([3, 3, 3]) == []


class TestCoarsening:
    def test_pairing_from_the_first_bucket(self):
        bins = [(1, 10), (2, 20), (4, 30), (8, 40)]
        assert smr.coarsen(bins, 2, 0) == [(1, 30), (4, 70)]

    def test_pairing_from_the_second_puts_the_edges_elsewhere(self):
        bins = [(1, 10), (2, 20), (4, 30), (8, 40)]
        assert smr.coarsen(bins, 2, 1) == [(1, 10), (2, 50), (8, 40)]

    def test_a_ragged_tail_is_kept_rather_than_dropped(self):
        bins = [(1, 1), (2, 2), (4, 4)]
        assert smr.coarsen(bins, 2, 0) == [(1, 3), (4, 4)]


class TestTheReportOnTheRealTrace:
    @pytest.fixture(scope="class")
    def got(self):
        return smr.report()

    def test_three_modes_on_the_tools_own_binning(self, got):
        assert got["base_modes"] == 3
        assert got["base_mode_lows_us"] == [2, 128, 2048]

    def test_they_survive_a_doubling_in_both_phases(self, got):
        assert got["survives_doubling"] is True
        assert got["doubling_phases"] == 2

    def test_they_do_not_survive_a_quadrupling(self, got):
        """The measured limit, and the reason the claim is stated to a factor of two."""
        assert got["survives_quadrupling"] is False
        assert got["resolved_to_octaves"] == 1

    def test_the_committed_record_matches(self, got):
        path = REPO / "docs" / "results" / "external" / "stall_mode_robustness.json"
        assert json.loads(path.read_text(encoding="utf-8")) == got


class TestAHistogramWhoseModesAreFurtherApart:
    """The other nearly-excluded branch, and the control the real result needs.

    If the measure could never return `survives_quadrupling`, the real trace failing it would
    say nothing. Here the modes are eight buckets apart and they survive.
    """

    @pytest.fixture
    def got(self, tmp_path):
        rows, labels = [], ["1", "2", "4", "8", "16", "32", "64", "128", "256",
                            "512", "1K", "2K", "4K", "8K", "16K", "32K"]
        for i, label in enumerate(labels):
            rows.append((("[%s]" % label) if i == 0 else "[%s, x)" % label,
                         100 if i % 8 == 1 else 1))
        return smr.report(write_trace(tmp_path, rows))

    def test_the_modes_survive_every_widening(self, got):
        assert got["survives_doubling"] is True
        assert got["survives_quadrupling"] is True

    def test_the_resolution_bound_records_the_stronger_answer(self, got):
        assert got["resolved_to_octaves"] == 2


class TestTheCommandLine:
    def test_check_passes_against_the_committed_record(self):
        assert smr.main(["--check"]) == 0

    def test_check_fails_when_the_record_disagrees(self, tmp_path, monkeypatch):
        stale = tmp_path / "stale.json"
        stale.write_text(json.dumps({"base_modes": 99}), encoding="utf-8")
        assert smr.main(["--check", "--out", str(stale)]) == 1

    def test_check_reports_a_missing_record(self, tmp_path):
        assert smr.main(["--check", "--out", str(tmp_path / "absent.json")]) == 1

    def test_writing_the_record_round_trips(self, tmp_path):
        out = tmp_path / "nested" / "record.json"
        assert smr.main(["--out", str(out)]) == 0
        assert json.loads(out.read_text(encoding="utf-8")) == smr.report()
        assert smr.main(["--check", "--out", str(out)]) == 0
