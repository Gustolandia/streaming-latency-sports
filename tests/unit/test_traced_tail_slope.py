"""Tests for scripts/traced_tail_slope.py - target 100% branch coverage.

This script measures how the run-queue delay distribution steepens between the decade next to
the core and the far tail. The manuscript states that it steepens; this script is what makes
that statement falsifiable, and it exits non-zero when the data say otherwise. Until now it
had no test module of its own -- the one script in the project whose whole job is to be able
to contradict the paper, and nothing checked that it still could.

Two properties are pinned hardest: that the parser reads the histogram and not the surrounding
bpftrace chatter, and that the steepening check actually fails when the far tail is shallower.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import traced_tail_slope as tts  # noqa: E402


def _dump(pairs, preamble=("Attaching 4 probes...", "")):
    """A bpftrace capture whose @usecs histogram holds the given (bound, count) pairs."""
    lines = list(preamble) + ["@usecs:"]
    for bound, count in pairs:
        lines.append("[%s]  %d |@@@@|" % (bound, count))
    return lines


def _power_law(alpha, lo_exp=8, hi_exp=16, scale=1_000_000):
    """Counts whose survival falls as t^-alpha across log2 buckets from 2^lo_exp."""
    bounds = [2 ** e for e in range(lo_exp, hi_exp + 1)]
    surv = [scale * (b / bounds[0]) ** -alpha for b in bounds]
    pairs = []
    for i, b in enumerate(bounds[:-1]):
        pairs.append((str(b), int(round(surv[i] - surv[i + 1]))))
    pairs.append((str(bounds[-1]), int(round(surv[-1]))))
    return pairs


def _from_survival(survivals, lo_exp=8):
    """Bucket counts whose survival curve is exactly the one given, boundary by boundary."""
    bounds = [2 ** (lo_exp + i) for i in range(len(survivals))]
    pairs = []
    for i, b in enumerate(bounds[:-1]):
        pairs.append((str(b), int(round(survivals[i] - survivals[i + 1]))))
    pairs.append((str(bounds[-1]), int(round(survivals[-1]))))
    return pairs


def _two_slope(first, second, n=4, scale=1_000_000.0):
    """A survival curve with index `first` over the first n doublings and `second` after."""
    s = [scale]
    for i in range(1, 2 * n):
        alpha = first if i < n else second
        s.append(s[-1] * 2.0 ** -alpha)
    return s


class TestBoundUs:

    def test_a_plain_number_is_microseconds(self):
        assert tts._bound_us("512") == 512

    @pytest.mark.parametrize("token,expected", [("1K", 1024), ("32K", 32768),
                                                ("2M", 2 * 1024 ** 2), ("1G", 1024 ** 3)])
    def test_binary_suffixes_are_powers_of_two_not_of_ten(self, token, expected):
        """bpftrace prints 1K for 1024. Reading it as 1000 shifts the whole tail."""
        assert tts._bound_us(token) == expected


class TestParseHistogram:

    def test_it_reads_the_usecs_histogram(self):
        assert tts.parse_histogram(_dump([("256", 10), ("512", 4)])) == [(256, 10), (512, 4)]

    def test_chatter_before_the_histogram_is_stepped_over(self):
        """bpftrace prints its own preamble, and the map may be preceded by other maps."""
        lines = ["Attaching 4 probes...", "", "@count: 99", "", "@usecs:",
                 "[256]  10 |@|", "[512]  4 |@|"]
        assert tts.parse_histogram(lines) == [(256, 10), (512, 4)]

    def test_a_blank_line_inside_the_header_does_not_end_it(self, ):
        """The branch that had never been taken: a non-bucket line seen *before* any bucket
        must be skipped, not treated as the end of the histogram."""
        lines = ["@usecs:", "", "   ", "[256]  10 |@|", "[512]  4 |@|"]
        assert tts.parse_histogram(lines) == [(256, 10), (512, 4)]

    def test_the_first_non_bucket_line_after_the_histogram_ends_it(self):
        """Counters follow the histogram and are not buckets."""
        lines = ["@usecs:", "[256]  10 |@|", "", "@count: 2200", "[999]  7 |@|"]
        assert tts.parse_histogram(lines) == [(256, 10)]

    def test_no_histogram_at_all_is_no_buckets(self):
        assert tts.parse_histogram(["Attaching 4 probes...", "@count: 3"]) == []


class TestSurvival:

    def test_the_first_boundary_carries_everything(self):
        surv = tts.survival([(256, 6), (512, 3), (1024, 1)])
        assert surv[0] == (256, 1.0, 10)

    def test_each_boundary_carries_what_lies_at_or_above_it(self):
        surv = tts.survival([(256, 6), (512, 3), (1024, 1)])
        assert [n for _, _, n in surv] == [10, 4, 1]
        assert surv[-1][1] == pytest.approx(0.1)


class TestLocalSlopes:

    def test_a_power_law_gives_its_own_exponent_at_every_boundary(self):
        surv = tts.survival([(int(b), c) for b, c in _power_law(2.0)])
        slopes = [s for _, _, _, s in tts.local_slopes(surv) if s is not None]
        assert slopes, "a clean power law must produce slopes"
        assert all(abs(s - 2.0) < 0.15 for s in slopes[:-1])

    def test_the_last_boundary_has_no_slope_to_report(self):
        """A slope needs two points; the final boundary has nothing above it."""
        surv = tts.survival([(256, 6), (512, 3), (1024, 1)])
        assert tts.local_slopes(surv)[-1][3] is None

    def test_a_boundary_where_survival_reaches_zero_reports_no_slope(self):
        """log(0) is not a slope, and a fabricated one would land in the CSV as a number."""
        surv = tts.survival([(256, 10), (512, 0)])
        assert all(s is None for _, _, _, s in tts.local_slopes(surv))


class TestWindowSlope:

    def test_it_recovers_the_exponent_of_a_power_law(self):
        surv = tts.survival([(int(b), c) for b, c in _power_law(1.5)])
        assert tts.window_slope(surv, 256, 4096) == pytest.approx(1.5, abs=0.1)

    def test_fewer_than_three_points_is_not_a_fit(self):
        """Two points always lie on a line; calling that an index would be a claim."""
        surv = tts.survival([(256, 6), (512, 3), (1024, 1)])
        assert tts.window_slope(surv, 256, 512) is None

    def test_a_window_containing_nothing_is_not_a_fit(self):
        surv = tts.survival([(256, 6), (512, 3), (1024, 1)])
        assert tts.window_slope(surv, 10 ** 6, 10 ** 7) is None


class TestMain:

    def _capture(self, tmp_path, pairs, name="runqlat.txt"):
        p = tmp_path / name
        p.write_text("\n".join(_dump(pairs)) + "\n", encoding="utf-8")
        return p

    def test_a_steepening_tail_is_reported_and_written(self, tmp_path, capsys):
        """Shallow next to the core, steeper far out: what the manuscript states."""
        pairs = _from_survival(_two_slope(1.2, 3.0))
        out = tmp_path / "slope.csv"
        assert tts.main(["--runqlat", str(self._capture(tmp_path, pairs)),
                         "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "windowed index" in printed
        assert "length bias" in printed, "the residual caveat must travel with the number"
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert {r["kind"] for r in rows} == {"boundary", "window"}
        assert sum(1 for r in rows if r["kind"] == "window") == len(tts.WINDOWS_US)

    def test_a_flattening_tail_fails_loudly(self, tmp_path, capsys):
        """This is the whole point of the script: it must be able to contradict the paper.

        Steep next to the core and shallow far out is the opposite of what the manuscript
        states, and the run must exit non-zero rather than write the table and say nothing.
        """
        pairs = _from_survival(_two_slope(3.0, 1.1))
        assert tts.main(["--runqlat", str(self._capture(tmp_path, pairs)),
                         "--out", str(tmp_path / "s.csv")]) == 1
        assert "would be false" in capsys.readouterr().out

    def test_a_capture_with_no_histogram_is_fatal(self, tmp_path, capsys):
        p = tmp_path / "empty.txt"
        p.write_text("Attaching 4 probes...\n@count: 0\n", encoding="utf-8")
        assert tts.main(["--runqlat", str(p), "--out", str(tmp_path / "s.csv")]) == 2
        assert "no usable @usecs histogram" in capsys.readouterr().out

    def test_a_capture_too_short_to_fit_is_fatal(self, tmp_path, capsys):
        """Three boundaries cannot support a windowed index, so the run is refused up front."""
        assert tts.main(["--runqlat",
                         str(self._capture(tmp_path, [("256", 3), ("512", 2), ("1K", 1)])),
                         "--out", str(tmp_path / "s.csv")]) == 2

    def test_a_capture_that_cannot_be_windowed_still_writes_its_boundaries(self, tmp_path,
                                                                          capsys):
        """With no window fitted the survival table is still the measurement; only the
        steepening claim goes unjudged, and it must not be judged on nothing."""
        pairs = [("1M", 100), ("2M", 50), ("4M", 25), ("8M", 12), ("16M", 6)]
        out = tmp_path / "s.csv"
        assert tts.main(["--runqlat", str(self._capture(tmp_path, pairs)),
                         "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "windowed index 0.25-2 ms: None" in printed
        assert "would be false" not in printed
        assert list(csv.DictReader(open(out, encoding="utf-8")))

    def test_the_output_directory_is_created(self, tmp_path):
        pairs = _from_survival(_two_slope(1.2, 3.0))
        out = tmp_path / "deep" / "down" / "s.csv"
        tts.main(["--runqlat", str(self._capture(tmp_path, pairs)), "--out", str(out)])
        assert out.exists()

    def test_survival_at_512_us_is_reported_when_the_boundary_exists(self, tmp_path, capsys):
        pairs = _from_survival(_two_slope(1.2, 3.0))
        tts.main(["--runqlat", str(self._capture(tmp_path, pairs)),
                  "--out", str(tmp_path / "s.csv")])
        assert "survival at 512 us:" in capsys.readouterr().out

    def test_a_capture_without_that_boundary_says_nothing_about_it(self, tmp_path, capsys):
        pairs = [("1M", 100), ("2M", 50), ("4M", 25), ("8M", 12), ("16M", 6)]
        tts.main(["--runqlat", str(self._capture(tmp_path, pairs)),
                  "--out", str(tmp_path / "s.csv")])
        assert "survival at 512 us:" not in capsys.readouterr().out
