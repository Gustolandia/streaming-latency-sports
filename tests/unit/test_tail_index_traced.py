"""Tests for scripts/tail_index_traced.py.

The module exists because a referee objected, correctly, that the manuscript's traced
"windowed log-log index" was a slope through four nested survival points with no interval
attached, offered as an independent confirmation of a separately fitted exponent. The
replacement estimators must therefore be checked against cases whose answer is known in
advance, not against whatever the committed histogram happens to yield -- otherwise the
replacement inherits exactly the weakness it was written to remove.

Two kinds of test here:

  synthetic   bucket counts generated from a Pareto tail with a known alpha, so the
              estimator can be checked for recovering it, and exceedance counts built by
              hand so the two-point estimator can be checked against arithmetic.

  artefact    the committed histograms, checked for the properties the manuscript now
              asserts -- notably that the two estimators disagree, which is the finding.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import tail_index_traced as tit  # noqa: E402


def pareto_buckets(alpha, lo, hi, n=1_000_000):
    """Exact expected log2-bucket counts for a Pareto tail truncated to [lo, hi)."""
    edges, e = [], lo
    while e < hi:
        edges.append(e)
        e *= 2
    edges.append(hi)
    norm = lo ** -alpha - hi ** -alpha
    out = []
    for a, b in zip(edges, edges[1:]):
        mass = (a ** -alpha - b ** -alpha) / norm
        out.append((a, b, int(round(n * mass))))
    return out


SAMPLE = """Attaching 3 probes...

@count: 1000
@over_500us: 300
@over_1000us: 200
@over_2000us: 100
@qt[379732]: 348469780736693
@usecs:
[1]                   10 |@@@@                |
[2, 4)                20 |@@@@@@@@            |
[256, 512)           100 |@@@@@@@@@@@@@@@@@@@@|
[512, 1K)             50 |@@@@@@@@@@          |
[1K, 2K)              25 |@@@@@               |
[2K, 4K)              12 |@@                  |
"""


class TestParsing:
    def test_it_reads_bucket_edges_and_counts(self):
        bins, _ = tit.parse_runqlat(SAMPLE)
        assert (256, 512, 100) in bins
        assert (512, 1024, 50) in bins

    def test_a_single_value_bucket_becomes_a_half_open_pair(self):
        """bpftrace prints the first log2 bucket as "[1]"; it means [1, 2)."""
        bins, _ = tit.parse_runqlat(SAMPLE)
        assert (1, 2, 10) in bins

    def test_the_k_suffix_is_binary_not_decimal(self):
        """1K in a log2 histogram is 1024. Reading it as 1000 would bias every index."""
        bins, _ = tit.parse_runqlat(SAMPLE)
        assert (1024, 2048, 25) in bins

    def test_it_reads_the_exact_counters(self):
        _, counters = tit.parse_runqlat(SAMPLE)
        assert counters["count"] == 1000
        assert counters["over_500us"] == 300
        assert counters["over_2000us"] == 100

    def test_noise_lines_are_ignored(self):
        bins, counters = tit.parse_runqlat(SAMPLE)
        assert all(isinstance(b[2], int) for b in bins)
        assert "qt[379732]" not in counters

    def test_an_empty_dump_yields_nothing_rather_than_raising(self):
        assert tit.parse_runqlat("") == ([], {})


class TestWindow:
    def test_it_keeps_only_buckets_wholly_inside(self):
        bins, _ = tit.parse_runqlat(SAMPLE)
        win = tit.window(bins, 256, 2048)
        assert [b[0] for b in win] == [256, 512, 1024]

    def test_partial_buckets_are_dropped_not_split(self):
        """Splitting would need a within-bucket density, which is the thing being
        estimated."""
        bins, _ = tit.parse_runqlat(SAMPLE)
        assert (2048, 4096, 12) not in tit.window(bins, 256, 2048)

    def test_an_empty_window_is_empty(self):
        bins, _ = tit.parse_runqlat(SAMPLE)
        assert tit.window(bins, 10 ** 7, 10 ** 8) == []


class TestBinnedParetoMLE:
    @pytest.mark.parametrize("alpha", [0.3, 0.75, 1.0, 2.0])
    def test_it_recovers_a_known_exponent(self, alpha):
        """The estimator's one job. Generated from the exact bucket masses, so the only
        error is numerical."""
        est, lo, hi, n = tit.binned_pareto_mle(pareto_buckets(alpha, 256, 4096))
        assert est == pytest.approx(alpha, abs=0.01)
        assert lo < alpha < hi

    def test_the_interval_narrows_as_the_sample_grows(self):
        wide = tit.binned_pareto_mle(pareto_buckets(0.5, 256, 4096, n=1_000))
        tight = tit.binned_pareto_mle(pareto_buckets(0.5, 256, 4096, n=1_000_000))
        assert (tight[2] - tight[1]) < (wide[2] - wide[1])

    def test_the_interval_brackets_the_estimate(self):
        est, lo, hi, _ = tit.binned_pareto_mle(pareto_buckets(0.9, 256, 4096))
        assert lo < est < hi

    def test_empty_buckets_are_skipped_not_counted(self):
        bins = pareto_buckets(0.6, 256, 4096)
        padded = bins + [(4096, 8192, 0)]
        assert tit.binned_pareto_mle(padded)[0] == pytest.approx(
            tit.binned_pareto_mle(bins)[0], abs=1e-6)

    def test_it_refuses_to_estimate_from_one_bucket(self):
        """An index from a single bucket is not an estimate; the project's whole argument
        is against numbers that look like measurements and are not."""
        with pytest.raises(ValueError):
            tit.binned_pareto_mle([(256, 512, 100)])

    def test_it_refuses_to_estimate_from_nothing(self):
        with pytest.raises(ValueError):
            tit.binned_pareto_mle([(256, 512, 0), (512, 1024, 0)])

    def test_the_reported_n_is_the_windowed_count(self):
        bins = pareto_buckets(0.5, 256, 4096)
        assert tit.binned_pareto_mle(bins)[3] == sum(b[2] for b in bins)


class TestExceedanceIndex:
    def test_it_matches_the_closed_form(self):
        """Halving the survival across a doubling of x is exactly alpha = 1."""
        alpha, _, _ = tit.exceedance_index(1000, 500, 500.0, 1000.0)
        assert alpha == pytest.approx(1.0)

    def test_a_quartering_over_a_doubling_is_two(self):
        alpha, _, _ = tit.exceedance_index(1000, 250, 500.0, 1000.0)
        assert alpha == pytest.approx(2.0)

    def test_an_unchanged_survival_is_a_zero_index(self):
        alpha, _, _ = tit.exceedance_index(1000, 1000, 500.0, 2000.0)
        assert alpha == pytest.approx(0.0)

    def test_the_interval_brackets_the_estimate(self):
        alpha, lo, hi = tit.exceedance_index(10_000, 5_000, 500.0, 1000.0)
        assert lo < alpha < hi

    def test_more_data_narrows_the_interval(self):
        _, lo_s, hi_s = tit.exceedance_index(100, 50, 500.0, 1000.0)
        _, lo_l, hi_l = tit.exceedance_index(100_000, 50_000, 500.0, 1000.0)
        assert (hi_l - lo_l) < (hi_s - lo_s)

    def test_counts_must_be_nested(self):
        """n_hi counts a subset of n_lo. Passing them the other way round would silently
        return a negative index."""
        with pytest.raises(ValueError):
            tit.exceedance_index(100, 200, 500.0, 1000.0)

    def test_a_zero_exceedance_count_is_refused(self):
        with pytest.raises(ValueError):
            tit.exceedance_index(100, 0, 500.0, 1000.0)

    def test_the_thresholds_must_be_ordered(self):
        with pytest.raises(ValueError):
            tit.exceedance_index(100, 50, 1000.0, 500.0)


class TestOctaveIndices:
    def test_a_true_power_law_gives_the_same_index_in_every_octave(self):
        """The check the manuscript's earlier slope skipped."""
        got = tit.octave_indices(pareto_buckets(0.8, 256, 8192))
        assert len(got) >= 2
        assert all(a == pytest.approx(0.8, abs=0.02) for _, a in got)

    def test_an_empty_bucket_widens_the_span_rather_than_deleting_two_estimates(self):
        """With the middle bucket empty the surviving pair spans 256 to 1024, a factor of
        four, and the mass ratio is 10/5 = 2, so alpha = log 2 / log 4 = 0.5. Skipping the
        empty bucket in place would instead have discarded both estimates."""
        got = tit.octave_indices([(256, 512, 10), (512, 1024, 0), (1024, 2048, 5)])
        assert got == [(256, pytest.approx(math.log(2) / math.log(4)))]

    def test_a_single_bucket_yields_no_octave(self):
        assert tit.octave_indices([(256, 512, 10)]) == []


class TestAgainstTheCommittedHistograms:
    def test_the_committed_dumps_are_discovered(self):
        tags = [t for t, _ in tit.traced_histograms()]
        assert "ea9/l88_base" in tags

    def test_the_histogram_sums_to_its_own_counter(self):
        """A parse that dropped a bucket would still produce a plausible index."""
        path = dict((t, p) for t, p in tit.traced_histograms())["ea9/l88_base"]
        with open(path, encoding="utf-8") as fh:
            bins, counters = tit.parse_runqlat(fh.read())
        assert sum(b[2] for b in bins) == counters["count"]

    def test_the_two_estimators_disagree_which_is_the_finding(self):
        """The manuscript now reports this disagreement rather than a single index. If a
        future re-run made them agree, the text would be wrong and this test should fail."""
        est = tit.estimate(dict(tit.traced_histograms())["ea9/l88_base"])
        assert est["mle_alpha"] > 3 * est["exc_alpha"]

    def test_the_window_is_not_a_power_law(self):
        """The reason the estimators disagree, stated as a property of the data."""
        est = tit.estimate(dict(tit.traced_histograms())["ea9/l88_base"])
        indices = [a for _, a in est["octaves"]]
        assert max(indices) > 10 * max(min(indices), 1e-3)

    def test_the_estimate_carries_its_denominator(self):
        est = tit.estimate(dict(tit.traced_histograms())["ea9/l88_base"])
        assert est["traced_events"] > est["mle_n"] > 0


class TestCLI:
    def test_it_reports_every_histogram(self, capsys):
        assert tit.main([]) == 0
        out = capsys.readouterr().out
        assert "grouped Pareto MLE" in out and "exceedance" in out
        assert "per-octave" in out

    def test_json_mode_is_machine_readable(self, capsys):
        import json
        assert tit.main(["--json"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert any(r["tag"] == "ea9/l88_base" for r in rows)

    def test_an_empty_tree_is_an_error_not_a_silent_pass(self, tmp_path, capsys):
        assert tit.main(["--root", str(tmp_path)]) == 1
        assert "no traced histograms" in capsys.readouterr().out

    def test_unreadable_dumps_are_skipped_rather_than_fatal(self, tmp_path):
        d = tmp_path / "depth" / "x" / "y"
        d.mkdir(parents=True)
        (d / "runqlat.txt").write_text("nothing parseable here", encoding="utf-8")
        assert tit.report(str(tmp_path)) == []


class TestDegenerateInputs:
    """Branches that only fire on inputs the committed artefacts do not contain.

    They exist because the estimator will outlive this campaign, and a likelihood that
    returns a plausible number on impossible input is exactly the failure the manuscript
    is about.
    """

    def test_a_degenerate_window_has_no_likelihood(self):
        """lo == hi leaves no probability mass to normalise by."""
        assert tit._loglik(0.5, [(512, 512, 10)]) == -math.inf

    def test_a_zero_width_bucket_has_no_likelihood(self):
        assert tit._loglik(0.5, [(256, 256, 10), (256, 1024, 5)]) == -math.inf

    def test_empty_buckets_contribute_nothing_to_the_likelihood(self):
        """An unobserved bucket carries no information, so dropping it must leave the
        likelihood untouched -- the normalising window is set by the outer edges, which
        the empty bucket does not move."""
        with_zero = tit._loglik(0.7, [(256, 512, 10), (512, 1024, 0), (1024, 2048, 5)])
        without = tit._loglik(0.7, [(256, 512, 10), (1024, 2048, 5)])
        assert math.isfinite(with_zero)
        assert with_zero == pytest.approx(without)

    def test_a_root_outside_the_bracket_returns_none(self):
        """_root reports "no crossing here" rather than inventing an endpoint."""
        bins = pareto_buckets(0.5, 256, 4096)
        target = tit._loglik(0.5, bins) + 1000.0  # unreachably high
        assert tit._root(bins, target, 0.1, 2.0) is None

    def test_non_octave_buckets_with_no_span_are_skipped(self):
        assert tit.octave_indices([(256, 512, 10), (256, 1024, 5)]) == []

    def test_a_dump_without_exact_counters_still_yields_the_likelihood_estimate(self, tmp_path):
        """bpftrace can be run without the @over_Nus counters; the exceedance estimator
        then has no input, and the report must degrade rather than fail."""
        d = tmp_path / "depth" / "x" / "y"
        d.mkdir(parents=True)
        (d / "runqlat.txt").write_text(
            "@usecs:\n[256, 512)   100 |x|\n[512, 1K)   50 |x|\n[1K, 2K)   25 |x|\n",
            encoding="utf-8")
        rows = tit.report(str(tmp_path))
        assert len(rows) == 1
        assert "mle_alpha" in rows[0] and "exc_alpha" not in rows[0]

    def test_the_cli_prints_a_dump_that_has_no_exceedance_counters(self, tmp_path, capsys):
        d = tmp_path / "depth" / "x" / "y"
        d.mkdir(parents=True)
        (d / "runqlat.txt").write_text(
            "@usecs:\n[256, 512)   100 |x|\n[512, 1K)   50 |x|\n[1K, 2K)   25 |x|\n",
            encoding="utf-8")
        assert tit.main(["--root", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "grouped Pareto MLE" in out
        assert "exceedance" not in out
