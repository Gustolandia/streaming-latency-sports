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


class TestRatioCi:
    """Katz's log interval for a ratio of proportions.

    The audit found four ratios quoted in the manuscript with no interval on the ratio
    itself, only on the two arms it came from. Two disjoint arm intervals say the arms
    differ; they do not say by how much, which is what the sentence claims.
    """

    def test_identical_cells_bracket_one(self):
        lo, hi = si.ratio_ci(100, 1000, 100, 1000)
        assert lo < 1.0 < hi

    def test_the_interval_contains_the_point_estimate(self):
        lo, hi = si.ratio_ci(394, 2985, 10, 2985)
        assert lo < 39.4 < hi

    def test_the_papers_l75_factor_is_wide_because_the_collapsed_arm_is_sparse(self):
        """Ten events in the manipulated arm. The published 39x is really 21-74x, and the
        point of adding this interval was that the bare factor read stronger than the data."""
        lo, hi = si.ratio_ci(394, 2985, 10, 2985)
        assert lo == pytest.approx(21, abs=1)
        assert hi == pytest.approx(74, abs=1)

    def test_it_is_symmetric_in_the_log_not_in_the_ratio(self):
        lo, hi = si.ratio_ci(394, 2985, 10, 2985)
        point = (394 / 2985) / (10 / 2985)
        assert math.log(point) - math.log(lo) == pytest.approx(math.log(hi) - math.log(point))
        assert hi - point > point - lo          # asymmetric on the ratio scale

    def test_more_events_narrow_it(self):
        narrow = si.ratio_ci(3940, 29850, 100, 29850)
        wide = si.ratio_ci(394, 2985, 10, 2985)
        assert (narrow[1] / narrow[0]) < (wide[1] / wide[0])

    def test_an_empty_arm_is_refused_rather_than_bounded_on_one_side(self):
        with pytest.raises(ValueError):
            si.ratio_ci(100, 1000, 0, 1000)
        with pytest.raises(ValueError):
            si.ratio_ci(0, 1000, 100, 1000)

    def test_a_non_positive_denominator_is_refused(self):
        with pytest.raises(ValueError):
            si.ratio_ci(10, 0, 10, 100)
        with pytest.raises(ValueError):
            si.ratio_ci(10, 100, 10, 0)


class TestPayloadRateFallInterval:
    def test_an_endpoint_whose_rate_rounds_to_no_events_yields_no_interval(self, monkeypatch):
        """A rate can be non-zero and still imply fewer than half an event.

        Here the sparse arm is 0.0001 over 1000 trials, which rounds to zero events: the
        rate is a real number but Katz's method has no count to stand on. `payload_span`
        withholds the interval rather than reporting one the data cannot support, and the
        other three numbers are unaffected -- a missing interval must not take the estimate
        down with it. (A rate of exactly zero never reaches this branch: `rate_fall` divides
        by it first, which is pre-existing behaviour and not what this guard is for.)
        """
        monkeypatch.setattr(si, "_rows", lambda *parts: [
            {"transport_ms": "1.0", "inversion": "0.20", "rho": "0.80", "n_events": "1000"},
            {"transport_ms": "77.0", "inversion": "0.0001", "rho": "0.81", "n_events": "1000"},
        ])
        out = si.payload_span()
        assert "rate_fall_ci" not in out
        assert out["transport_factor"] == pytest.approx(77.0)
        assert out["levels"] == 2

    def test_a_normal_sweep_carries_the_interval_around_its_estimate(self, monkeypatch):
        monkeypatch.setattr(si, "_rows", lambda *parts: [
            {"transport_ms": "1.0", "inversion": "0.20", "rho": "0.80", "n_events": "1000"},
            {"transport_ms": "77.0", "inversion": "0.05", "rho": "0.81", "n_events": "1000"},
        ])
        out = si.payload_span()
        lo, hi = out["rate_fall_ci"]
        assert lo < out["rate_fall"] < hi


class TestFisherCi:
    def test_zero_correlation_gives_a_symmetric_interval_about_zero(self):
        lo, hi = si.fisher_ci(0.0, 100)
        assert lo == pytest.approx(-hi)

    def test_the_papers_retention_correlation_excludes_zero(self):
        lo, hi = si.fisher_ci(0.31, 71)
        assert 0.0 < lo < 0.31 < hi < 1.0

    def test_it_stays_inside_the_unit_interval_at_a_strong_correlation(self):
        lo, hi = si.fisher_ci(0.98, 10)
        assert -1.0 < lo and hi < 1.0

    def test_it_narrows_as_n_grows(self):
        small = si.fisher_ci(0.5, 10)
        large = si.fisher_ci(0.5, 1000)
        assert (large[1] - large[0]) < (small[1] - small[0])

    def test_a_degenerate_correlation_is_refused(self):
        for bad in (1.0, -1.0, 1.5):
            with pytest.raises(ValueError):
                si.fisher_ci(bad, 100)

    def test_too_few_points_are_refused(self):
        with pytest.raises(ValueError):
            si.fisher_ci(0.5, 3)


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


class TestRoundTwoReaders:
    """Readers added because the manuscript stated four things the artefacts contradict.

    Each test names the wrong claim it replaces, so a later edit that reintroduces the
    claim fails here rather than in review.
    """

    def test_the_harness_totals_are_not_one_and_a_half_million(self):
        """The manuscript said "1.5 million samples" for the one-clock harness and again
        for the cross-host one. Neither topology has that count."""
        h = si.harness_cells()
        assert set(h) == {"one_clock", "cross_host"}
        assert h["one_clock"]["sent"] == 905_040
        assert h["cross_host"]["sent"] == 905_040
        assert h["one_clock"]["sent"] != 1_500_000

    def test_neither_topology_recorded_a_negative(self):
        h = si.harness_cells()
        assert h["one_clock"]["negatives"] == 0
        assert h["cross_host"]["negatives"] == 0

    def test_the_inversion_rate_has_a_ceiling_below_one_half(self):
        """"Fully saturated, two events in three are still stamped unpreempted" confused a
        rate ceiling with an occupancy. The ceiling is what the artefact holds."""
        b = si.occupancy_bounds()
        assert 0.3 < b["ceiling"] < 0.4
        assert b["floor"] < b["ceiling"]

    def test_idle_to_knee_growth_is_the_inversion_rate_not_a_tail_mass(self):
        g = si.load_growth()
        assert g["core_growth"] == pytest.approx(5.0, abs=0.1)
        assert g["inv_growth"] == pytest.approx(61, abs=1)
        assert g["rho_knee"] == pytest.approx(0.877, abs=0.001)

    def test_the_tracer_perturbs_the_rate_it_is_used_to_predict(self):
        """The campaign measured this and the manuscript never reported it."""
        o = si.observer_effect()
        assert o["untraced"] > o["traced"], "tracing suppresses the rate here"
        assert o["z"] > 2, "the perturbation is larger than sampling noise"
        assert 1.0 < o["ratio"] < 1.5

    def test_a_missing_condition_returns_nothing_rather_than_half_a_result(self):
        assert si.observer_effect(condition="does_not_exist") == {}
        assert si.load_growth(idle="nope", knee="also_nope") == {}


class TestTheRowsAndFragmentsThatCarryNothing:

    def test_a_side_of_the_split_with_no_cells_is_absent_rather_than_empty(self, monkeypatch):
        """The harness table is split by whether the clocks are on one host. A side with no
        runs has no interval, and an entry of zeros would read as a measurement of zero."""
        monkeypatch.setattr(si, "_rows", lambda *parts: [
            {"cross_host": "false", "sent": "100", "kept": "90",
             "discarded_negative": "0"},
            {"cross_host": "false", "sent": "200", "kept": "180",
             "discarded_negative": "0"},
        ])
        got = si.harness_cells()
        assert "one_clock" in got
        assert "cross_host" not in got, "no cross-host runs is not a cross-host result"

    def test_a_detail_fragment_with_no_equals_sign_is_skipped(self, monkeypatch):
        """The detail column is semicolon-separated `k=v`, and carries free text between the
        pairs. Splitting a fragment without `=` would raise mid-parse."""
        monkeypatch.setattr(si, "_rows", lambda *parts: [
            {"law": "L2", "detail": "ceiling=0.42; measured on E-A4; median=0.31"},
        ])
        got = si.occupancy_bounds()
        assert got["ceiling"] == 0.42
        assert got["median"] == 0.31


class TestHarnessArmSpreads:
    """Retention spread per rate arm, one clock against two.

    The manuscript said cross-host retention "wandered from 13.4 to 27.0%" over four
    replicates "where the same arm on one clock held to 0.8 points". Both numbers were
    typed, and both had drifted: the arm runs 13.4 to 26.9, and its one-clock twin holds to
    0.98 points, which is what three of its four replicates span. The claim was unchanged;
    only the digits were wrong, which is the usual shape of this defect.
    """

    @staticmethod
    def _rows(rows):
        return [{"rate_hz": str(rate), "cross_host": xh, "kept": str(kept),
                 "discarded_zero": str(1000 - kept), "discarded_negative": "0"}
                for rate, xh, kept in rows]

    def test_only_arms_measured_in_both_topologies_are_returned(self, monkeypatch):
        """A one-sided arm cannot support the comparison the sentence makes."""
        monkeypatch.setattr(si, "_rows", lambda *p: self._rows([
            (457, "True", 134), (457, "True", 269),
            (457, "False", 295), (457, "False", 305),
            (300, "True", 400),
        ]))
        got = si.harness_arm_spreads()
        assert set(got) == {457}, "300 has no one-clock twin and cannot be compared"

    def test_the_endpoints_are_the_arm_extremes(self, monkeypatch):
        monkeypatch.setattr(si, "_rows", lambda *p: self._rows([
            (457, "True", 134), (457, "True", 161), (457, "True", 269),
            (457, "False", 295), (457, "False", 305),
        ]))
        got = si.harness_arm_spreads()[457]
        assert got["cross_host"] == (13.4, 26.9)
        assert round(got["one_clock"][1] - got["one_clock"][0], 1) == 1.0

    def test_a_run_that_took_no_samples_is_skipped_not_divided_by(self, monkeypatch):
        monkeypatch.setattr(si, "_rows", lambda *p: [
            {"rate_hz": "457", "cross_host": "True", "kept": "0",
             "discarded_zero": "0", "discarded_negative": "0"},
            {"rate_hz": "457", "cross_host": "True", "kept": "134",
             "discarded_zero": "866", "discarded_negative": "0"},
            {"rate_hz": "457", "cross_host": "False", "kept": "295",
             "discarded_zero": "705", "discarded_negative": "0"},
        ])
        assert si.harness_arm_spreads()[457]["cross_host"] == (13.4, 13.4)

    def test_an_unreadable_row_is_skipped_rather_than_raising(self, monkeypatch):
        """One mangled row must not cost the arm its comparison; a shrinking denominator
        is how a split total starts disagreeing with the pooled one."""
        monkeypatch.setattr(si, "_rows", lambda *p: [
            {"rate_hz": "not-a-rate", "cross_host": "True", "kept": "1",
             "discarded_zero": "1", "discarded_negative": "0"},
            {"rate_hz": "457", "cross_host": "True", "kept": "134",
             "discarded_zero": "866", "discarded_negative": "0"},
            {"rate_hz": "457", "cross_host": "False", "kept": "295",
             "discarded_zero": "705", "discarded_negative": "0"},
        ])
        assert set(si.harness_arm_spreads()) == {457}

    def test_a_row_missing_a_column_entirely_is_skipped(self, monkeypatch):
        monkeypatch.setattr(si, "_rows", lambda *p: [
            {"rate_hz": "457", "cross_host": "True"},
            {"rate_hz": "457", "cross_host": "True", "kept": "134",
             "discarded_zero": "866", "discarded_negative": "0"},
            {"rate_hz": "457", "cross_host": "False", "kept": "295",
             "discarded_zero": "705", "discarded_negative": "0"},
        ])
        assert set(si.harness_arm_spreads()) == {457}

    def test_the_committed_ledger_gives_the_numbers_the_paper_prints(self):
        """End to end, on the artefact: this is the pair the macros resolve from."""
        got = si.harness_arm_spreads()
        assert 457 in got, "the r457 arm is the one the sentence is about"
        lo, hi = got[457]["cross_host"]
        olo, ohi = got[457]["one_clock"]
        assert (round(lo, 1), round(hi, 1)) == (13.4, 26.9)
        assert round(ohi - olo, 2) == 0.98
