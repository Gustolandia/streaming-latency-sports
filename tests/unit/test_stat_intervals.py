"""Tests for scripts/stat_intervals.py.

The module exists so that every proportion the paper quotes carries an interval computed
from its own denominator. The tests therefore check the estimators against values that can
be verified independently (textbook worked examples and analytic limits), not against
whatever the code happens to produce.
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "scripts"))

import stat_intervals as si  # noqa: E402


class TestWilson:
    def test_matches_a_published_worked_example(self):
        """Wilson 95% for ic=8 successes in 10 trials is about [0.49, 0.94]; the value is
        quoted in the interval-estimation literature and is what a reader can check."""
        lo, hi = si.wilson(8, 10)
        assert lo == pytest.approx(0.4901, abs=5e-4)
        assert hi == pytest.approx(0.9433, abs=5e-4)

    def test_it_never_leaves_the_unit_interval_at_a_tiny_rate(self):
        """The reason the module does not use Wald: at the real-time arm's rate the normal
        approximation puts the lower bound below zero, which is not a possible rate."""
        lo, hi = si.wilson(10, 2985)
        assert lo > 0.0 and hi < 1.0
        wald_lo = 10 / 2985 - 1.96 * math.sqrt((10 / 2985) * (1 - 10 / 2985) / 2985)
        assert wald_lo < lo, "Wilson must be the more conservative lower bound here"

    def test_zero_successes_gives_a_lower_bound_of_zero_and_a_positive_upper_bound(self):
        lo, hi = si.wilson(0, 100)
        assert lo == 0.0 and 0.0 < hi < 0.05

    def test_all_successes_gives_an_upper_bound_of_one(self):
        lo, hi = si.wilson(100, 100)
        assert hi == 1.0 and 0.95 < lo < 1.0

    def test_the_interval_narrows_as_n_grows(self):
        wide = si.wilson(50, 100)
        narrow = si.wilson(5000, 10000)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_a_non_positive_denominator_is_refused(self):
        with pytest.raises(ValueError):
            si.wilson(0, 0)


class TestRatioZ:
    def test_identical_cells_give_zero_z_and_unit_ratio(self):
        z, ratio = si.ratio_z(100, 1000, 100, 1000)
        assert z == pytest.approx(0.0)
        assert ratio == pytest.approx(1.0)

    def test_the_papers_l75_cell_reproduces_its_quoted_factor(self):
        z, ratio = si.ratio_z(394, 2985, 10, 2985)
        assert ratio == pytest.approx(39.4, rel=0.02)
        assert z > 15

    def test_a_zero_denominator_rate_gives_an_infinite_ratio_not_a_crash(self):
        z, ratio = si.ratio_z(100, 1000, 0, 1000)
        assert math.isinf(ratio) and z > 0

    def test_two_empty_cells_are_refused_rather_than_dividing_by_zero(self):
        with pytest.raises(ValueError):
            si.ratio_z(0, 1000, 0, 1000)


class TestOlsSlope:
    def test_a_perfect_line_is_recovered_exactly(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0 + 2.0 * x for x in xs]
        slope, intercept, r2, lo, hi = si.ols_slope(xs, ys)
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)
        assert lo == pytest.approx(2.0) and hi == pytest.approx(2.0)

    def test_noise_widens_the_interval_and_lowers_r2(self):
        xs = [0.0, 1.0, 2.0, 3.0]
        clean = si.ols_slope(xs, [2.0 * x for x in xs])
        noisy = si.ols_slope(xs, [0.0, 2.4, 3.6, 6.4])
        assert noisy[2] < clean[2]
        assert (noisy[4] - noisy[3]) > (clean[4] - clean[3])

    def test_the_interval_brackets_the_slope(self):
        slope, _, _, lo, hi = si.ols_slope([0.0, 1.0, 2.0, 3.0], [0.1, 2.2, 3.7, 6.1])
        assert lo < slope < hi

    def test_two_points_are_refused_because_the_interval_would_be_undefined(self):
        with pytest.raises(ValueError):
            si.ols_slope([0.0, 1.0], [0.0, 1.0])

    def test_it_uses_the_t_quantile_at_n_minus_two_degrees_of_freedom(self):
        """Four points means two degrees of freedom, so the multiplier is 4.30, not 1.96.
        Using the normal quantile here would understate the interval by more than half."""
        assert si.T_975[2] == pytest.approx(4.302653, abs=1e-5)
        assert si.T_975[2] > 2 * si.Z_975


class TestArtefactReaders:
    """These read the committed campaign artefacts, so they double as a check that the
    files the paper cites still hold the shape the paper assumes."""

    def test_priority_cells_are_matched_pairs_of_equal_size(self):
        cells = si.priority_cells()
        assert cells, "the real-time priority artefact must not be empty"
        for level, kb, nb, kr, nr in cells:
            assert nb == nr == 2985, f"{level}: cells must be matched at 2,985 events"
            assert 0 <= kr < kb <= nb, f"{level}: real-time must invert less than ordinary"

    def test_the_geometry_pair_sits_at_one_utilisation(self):
        cells = si.geometry_cells("ea6")
        assert len(cells) == 2
        assert all(n == 2985 for _, _, n in cells)
        (_, kc, _), (_, ks, _) = cells
        assert ks > kc, "the spread geometry must invert more than the concentrated one"

    def test_the_payload_fit_reproduces_the_papers_exponent(self):
        slope, _, r2, lo, hi = si.payload_fit()
        assert -slope == pytest.approx(0.339, abs=0.002)
        assert r2 == pytest.approx(0.990, abs=0.002)
        assert lo < slope < hi
        assert (hi - lo) > 0.15, "four points give a wide interval; the paper must say so"

    def test_the_replication_agrees_with_the_original_within_its_interval(self):
        original = si.payload_fit()
        replication = si.payload_fit("ea10b")
        assert original[3] < replication[0] < original[4]


class TestReportAndCLI:
    def test_the_report_names_every_quantity_the_paper_quotes(self, capsys):
        assert si.main([]) == 0
        out = capsys.readouterr().out
        for token in ("Real-time priority", "Geometry k=6", "Payload sweep",
                      "disjoint=True", "Wilson"):
            assert token in out

    def test_the_report_shows_the_two_priority_arms_as_disjoint(self):
        text = si.report()
        assert text.count("disjoint=True") == 2, \
            "both quoted real-time arms must have intervals disjoint from their controls"


class TestHolm:
    """The correction the grid table's caption claimed and its body did not apply.

    Holm is checked against hand-computable cases rather than against the artefact, so a
    change in the artefact cannot silently redefine what "corrected" means.
    """

    def test_the_smallest_p_is_multiplied_by_the_family_size(self):
        adjusted = si.holm([0.01, 0.5, 0.5, 0.5])
        assert adjusted[0] == pytest.approx(0.04)

    def test_the_largest_p_is_not_multiplied_at_all(self):
        adjusted = si.holm([0.001, 0.002, 0.003, 0.6])
        assert adjusted[3] == pytest.approx(0.6)

    def test_adjusted_values_never_decrease_along_the_sorted_order(self):
        """Without the monotone step a larger raw p can adjust below a stricter neighbour,
        which would make the set incoherent."""
        raw = [0.001, 0.049, 0.05, 0.06, 0.9]
        adjusted = si.holm(raw)
        pairs = sorted(zip(raw, adjusted))
        assert all(a[1] <= b[1] + 1e-12 for a, b in zip(pairs, pairs[1:]))

    def test_it_caps_at_one(self):
        assert si.holm([0.9, 0.95]) == [pytest.approx(1.0), pytest.approx(1.0)]

    def test_order_is_preserved(self):
        """Returned in input order, not sorted order: the caller zips it against rows."""
        assert si.holm([0.5, 0.01])[1] == pytest.approx(0.02)

    def test_an_empty_family_is_not_an_error(self):
        assert si.holm([]) == []

    def test_the_arm_the_paper_misreported_does_not_survive_correction(self):
        """The specific regression. 900 msg/s carried a raw p of 0.044 and was printed as a
        rejection under a caption claiming Holm correction. Corrected within the family of
        twelve it is 0.13, and the table now says so."""
        cells = si.grid_cells()
        arm = next(c for c in cells if c["rate_hz"] == 900)
        assert arm["p_raw"] < 0.05, "the raw value is what made this look like a rejection"
        assert arm["p_holm"] > 0.05, "corrected, it is not a rejection"
        assert arm["verdict"] == "not resolved"


class TestGridCells:
    def test_every_arm_gets_one_of_three_verdicts(self):
        allowed = {"grid", "not resolved", "flat (coincident)"}
        assert {c["verdict"] for c in si.grid_cells()} <= allowed

    def test_unpowered_arms_are_never_counted_as_evidence(self):
        """An arm where the grid and the continuum predict the same thing cannot support
        either. The paper previously described these two as the ones that "do not reject",
        which read as a failure of the model rather than an absence of power."""
        for c in si.grid_cells():
            if not c["powered"]:
                assert c["verdict"] == "flat (coincident)"

    def test_the_paper_s_headline_count_is_what_the_artefact_supports(self):
        cells = si.grid_cells()
        powered = [c for c in cells if c["powered"]]
        assert len(powered) == 10
        assert sum(1 for c in powered if c["verdict"] == "grid") == 9

    def test_the_verdict_is_derived_from_the_corrected_value_not_the_raw_one(self):
        for c in si.grid_cells():
            if c["powered"]:
                assert (c["verdict"] == "grid") == (c["p_holm"] < 0.05)


class TestSpearman:
    def test_perfect_monotone_agreement_is_one(self):
        assert si.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)

    def test_perfect_reversal_is_minus_one(self):
        assert si.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)

    def test_it_is_rank_based_not_value_based(self):
        """A monotone but wildly nonlinear map leaves the rank correlation at one."""
        assert si.spearman([1, 2, 3, 4], [1, 4, 900, 1e6]) == pytest.approx(1.0)

    def test_ties_are_averaged(self):
        """x ranks to (1.5, 1.5, 3.5, 3.5) against y's (1, 2, 3, 4), giving
        S_xy/sqrt(S_xx S_yy) = 4/sqrt(20) = 2/sqrt(5). Averaging the tied ranks is what
        keeps the tied pair from inventing an order it does not have."""
        assert si.spearman([1, 1, 2, 2], [1, 2, 3, 4]) == pytest.approx(2 / math.sqrt(5))

    def test_a_constant_column_has_no_correlation(self):
        assert math.isnan(si.spearman([1, 1, 1], [1, 2, 3]))

    def test_too_few_points_is_nan_rather_than_an_exception(self):
        assert math.isnan(si.spearman([1], [2]))


class TestRetentionCells:
    def test_the_denominator_the_paper_quotes_exists_in_the_artefact(self):
        """The regression: the paper said "the 49 runs on an unsaturated path", and no
        partition of this artefact yields 49. These are the numbers that do."""
        cells = si.retention_cells()
        grid = [c for c in cells if c["p50_ms"] in (1.0, 2.0)]
        assert len(cells) == 75
        assert len(grid) == 71

    def test_the_retention_range_spans_the_claim(self):
        grid = [c for c in si.retention_cells() if c["p50_ms"] in (1.0, 2.0)]
        assert min(c["retention_pct"] for c in grid) < 0.4
        assert max(c["retention_pct"] for c in grid) == pytest.approx(100.0)

    def test_the_extremes_share_a_reported_median(self):
        """The point of the sentence: the two cells furthest apart in retention are
        typographically identical in the benchmark's own output."""
        grid = [c for c in si.retention_cells() if c["p50_ms"] in (1.0, 2.0)]
        lo = min(grid, key=lambda c: c["retention_pct"])
        hi = max(grid, key=lambda c: c["retention_pct"])
        assert lo["p50_ms"] == hi["p50_ms"]


class TestReaderRobustness:
    """Branches that fire when an artefact is partial. A reader that quietly returns half a
    result is worse than one that returns nothing, because the emitter would put the half
    into the paper."""

    def test_a_geometry_phase_with_one_arm_is_skipped_not_half_reported(self, monkeypatch):
        monkeypatch.setattr(si, "geometry_cells", lambda phase="ea6": [("k6_conc", 1, 10)])
        assert "Geometry" not in si.report()
