"""The paper's headline numbers must match the committed result artefacts.

This exists because of a real failure. An earlier revision withdrew an entire measurement arm
as physically invalid, yet kept quoting a transport figure (1.35 ms) from one of the withdrawn
tables in its abstract, while its conclusion quoted a different value for the same quantity.
Source-level proofreading missed it three times. Every number asserted here is recomputed from
the CSV that produced it, so a re-run that changes the data fails the test rather than silently
desynchronising the paper.

Targets paper.tex (ACM, systems venue). The superseded SAGE manuscript is gone; its framing was
retired when the broker comparison turned out to be the least interesting result in the study.
"""
import csv
import re
import statistics as st
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
RESULTS = REPO / "docs" / "results"


@pytest.fixture(scope="module")
def tex():
    return PAPER.read_text(encoding="utf-8")


def _rows(*parts):
    with open(RESULTS.joinpath(*parts), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _replayed_plan_t_sim():
    """Event times of the plan the single-feed campaigns actually replayed.

    run_concurrency_test.resolve_plans sorts the plans directory and plan_for_feed hands feed i
    plans[(i-1) % len(plans)], so feed 1 always gets the first plan in sort order. Reading any
    other plan would silently compare the paper against a match that was never replayed.
    """
    import glob
    plans = sorted(glob.glob(str(REPO / "data" / "processed" / "replay_plans" /
                                 "*" / "match_*" / "replay_plan.csv")))
    assert plans, "no replay plan committed to check against"
    with open(plans[0], encoding="utf-8", errors="replace") as fh:
        return [float(r["t_sim_seconds"]) for r in csv.DictReader(fh)]


def _contains_number(tex, value, decimals):
    """True if `value` appears in the paper at the given precision.

    LaTeX writes thousands separators as `{,}`, so 4138.0 may appear as `4{,}138`.
    """
    plain = f"{value:.{decimals}f}"
    if decimals == 0:
        n = int(round(value))
        grouped = f"{n:,}".replace(",", "{,}")
        return plain in tex or grouped in tex
    return plain in tex


class TestSetting:
    """Section 3 must match the workload characterisation output."""

    def test_arrival_rate_and_burstiness(self, tex):
        s = _rows("football", "feed", "feed_summary.csv")[0]
        assert _contains_number(tex, float(s["mean_rate_evs"]), 3)
        assert _contains_number(tex, float(s["peak_rate_evs"]), 2)
        assert _contains_number(tex, float(s["burstiness"]), 2)
        assert _contains_number(tex, float(s["n_matches"]), 0)

    def test_concurrency_is_derived_not_chosen(self, tex):
        s = _rows("football", "concurrency", "concurrency_summary.csv")[0]
        assert _contains_number(tex, float(s["max_simultaneous_kickoffs"]), 0)
        assert _contains_number(tex, float(s["peak_matches_in_play"]), 0)
        assert _contains_number(tex, float(s["n_slots"]), 0)
        assert s["recommended_levels"].split(";") == ["1", "9", "10", "12"]
        assert r"N \in \{1,9,10,12\}" in tex


class TestAudit:
    """Section 6's audit table must match the two integrity CSVs."""

    @staticmethod
    def _totals(path):
        rows = _rows(*path)
        runs = sum(int(r["n_runs"]) for r in rows)
        kept = sum(int(r["n_trustworthy"]) for r in rows)
        return runs, runs - kept, len(rows), sum(r["usable"] == "True" for r in rows)

    def test_single_machine_corpus(self, tex):
        totals = self._totals(("integrity_windows", "clock_integrity_by_condition.csv"))
        assert totals == (1382, 862, 76, 8)
        for v in totals[:2]:
            assert _contains_number(tex, v, 0)

    def test_multi_machine_corpus(self, tex):
        totals = self._totals(("integrity_by_condition.csv",))
        assert totals == (884, 459, 40, 13)
        for v in totals[:2]:
            assert _contains_number(tex, v, 0)

    def test_totals_are_the_sum_of_the_parts(self, tex):
        a = self._totals(("integrity_windows", "clock_integrity_by_condition.csv"))
        b = self._totals(("integrity_by_condition.csv",))
        assert _contains_number(tex, a[0] + b[0], 0), "total runs audited"
        assert _contains_number(tex, a[1] + b[1], 0), "total runs rejected"

    def test_the_audit_is_the_headline_in_both_abstract_and_conclusion(self, tex):
        """The paper's claim is the audit, so both ends must carry its numbers."""
        abstract = tex[tex.index(r"\begin{abstract}"):tex.index(r"\end{abstract}")]
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        for section, name in ((abstract, "abstract"), (conclusion, "conclusion")):
            assert "1{,}321" in section, f"rejected count missing from {name}"
            assert "2{,}266" in section, f"total count missing from {name}"


class TestThresholdSensitivity:
    """Section 6.3 must match the rule the check actually applies.

    Added after the figure disproved an earlier claim: we had asserted the inversion-rate
    distribution was bimodal, so the 1% threshold did not matter. It is not bimodal and the
    threshold does matter for the run count, so the paper reports the sensitivity instead.
    """

    THRESHOLDS = [(0.0, 1278), (0.001, 1086), (0.002, 1037), (0.005, 937),
                  (0.01, 862), (0.02, 763), (0.05, 594), (0.10, 445), (0.20, 265)]

    @pytest.fixture(scope="class")
    def by_run(self):
        import pandas as pd
        return pd.read_csv(RESULTS / "integrity_windows" / "clock_integrity_by_run.csv")

    def test_curve_matches_the_check_rule(self, by_run):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from make_paper_figures import condemned_at
        for threshold, expected in self.THRESHOLDS:
            assert condemned_at(by_run, threshold) == expected, threshold

    def test_the_quoted_endpoints_are_correct(self, by_run, tex):
        """The paper quotes the extremes of the curve rather than the whole table."""
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from make_paper_figures import condemned_at
        n = len(by_run)
        for threshold in (0.0, 0.20):
            pct = 100 * condemned_at(by_run, threshold) / n
            assert _contains_number(tex, pct, 1), f"{threshold:.0%} endpoint"

    def test_the_chosen_threshold_matches_the_audit_table(self, by_run):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from make_paper_figures import condemned_at
        audit = _rows("integrity_windows", "clock_integrity_by_condition.csv")
        assert condemned_at(by_run, 0.01) == sum(
            int(r["n_runs"]) - int(r["n_trustworthy"]) for r in audit)

    def test_bimodality_is_never_asserted(self, tex):
        """The word may appear only where the paper says the distribution is *not* bimodal."""
        low = tex.lower()
        for m in re.finditer("bimodal", low):
            window = low[max(0, m.start() - 300):m.start() + 300]
            assert "it is not" in window or "not (" in window, (
                f"bimodality asserted without negation at offset {m.start()}")


class TestSurvivingBenchmark:
    """Section 7.1's comparison must match the gated per-run CSV."""

    @staticmethod
    def _gated():
        return _rows("e1", "e1_by_run_gated.csv")

    def test_retention_is_stated_with_both_counts(self, tex):
        ci = _rows("e1", "e1_clock_integrity.csv")
        measured = sum(int(r["n_runs"]) for r in ci)
        retained = sum(int(r["n_trustworthy"]) for r in ci)
        assert retained == len(self._gated())
        near = [m.start() for m in re.finditer(str(retained), tex)
                if str(measured) in tex[m.start():m.start() + 120]]
        assert near, f"{retained} of {measured} not stated together"

    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_pooled_scheduling_lag(self, tex, backend):
        """The attribution claim rests on this number, so pin it."""
        vals = [float(r["schedlag_p50"]) for r in self._gated() if r["backend"] == backend]
        assert _contains_number(tex, st.median(vals), 1)

    def test_per_n_table(self, tex):
        for r in _rows("e1", "e1_transport_kafka_vs_redis_by_n.csv"):
            assert _contains_number(tex, float(r["kafka_median"]), 3)
            assert _contains_number(tex, float(r["redis_median"]), 3)

    def test_no_concurrency_effect_for_either_backend(self, tex):
        for r in _rows("e1", "e1_transport_kruskal_across_n.csv"):
            assert r["significant"] == "False"
            assert _contains_number(tex, float(r["p"]), 3)

    def test_the_gap_is_scheduling_lag_not_transport(self, tex):
        gated = self._gated()
        med = {b: {k: st.median(float(r[k]) for r in gated if r["backend"] == b)
                   for k in ("tti_p50", "schedlag_p50", "transport_p50")}
               for b in ("kafka", "redis")}
        tti_gap = med["kafka"]["tti_p50"] - med["redis"]["tti_p50"]
        lag_gap = med["kafka"]["schedlag_p50"] - med["redis"]["schedlag_p50"]
        assert lag_gap / tti_gap > 0.98, "scheduling lag must account for the whole gap"
        assert abs(med["kafka"]["transport_p50"] - med["redis"]["transport_p50"]) < 1.0


class TestRetentionBound:
    """Section 6.4 must match scripts/retention_bias.py."""

    def test_bound_holds_and_is_reported(self, tex):
        rows = _rows("e1", "e1_retention_bias.csv")
        assert rows, "run scripts/retention_bias.py"
        for r in rows:
            assert r["equivalent_worst_case"] == "True", r["n"]
            assert _contains_number(tex, float(r["hl_shift_ms"]), 3)
            assert _contains_number(tex, float(r["hl_shift_worst_case_ms"]), 3)

    def test_the_breakdown_limit_is_stated(self, tex):
        """The bound holds only above 1/2 retention, and the paper must say so."""
        rows = _rows("e1", "e1_retention_bias.csv")
        tightest = min(float(r["redis_retention"]) for r in rows)
        assert _contains_number(tex, 100 * tightest, 1), "tightest retention not quoted"
        assert "breakdown point" in tex


class TestAckBatching:
    """Section 7.3's intervention must match the read-loop CSV."""

    def test_improvement_factor_and_read_loop(self, tex):
        rows = _rows("e5", "e5_ack_batching.csv")
        arms = {a: [float(r["tti_median_ms"]) for r in rows if r["arm"] == a]
                for a in ("unbatched", "batched")}
        factor = st.median(arms["unbatched"]) / st.median(arms["batched"])
        assert _contains_number(tex, factor, 1)
        for arm in ("unbatched", "batched"):
            assert _contains_number(tex, st.median(arms[arm]), 0)
        sub = [r for r in rows if r["arm"] == "unbatched"]
        assert _contains_number(tex, st.median(float(r["msgs_per_read_median"]) for r in sub), 0)


class TestNoRejectedFigureIsQuotedAsLive:
    """The specific defect that motivated this file."""

    REJECTED_TRANSPORT = "1.346"   # Redis N=10 from the rejected accelerated corpus
    CONDEMNATION = ("reject", "artefact", "withdraw", "invalid", "impossible", "fails the")

    def test_it_is_always_marked_as_rejected(self, tex):
        """It may be quoted -- the argument requires it -- but never neutrally."""
        hits = [m.start() for m in re.finditer(re.escape(self.REJECTED_TRANSPORT), tex)]
        assert hits, "the rejected figure should still be reported, as evidence"
        for pos in hits:
            window = tex[max(0, pos - 1200):pos + 1200].lower()
            assert any(w in window for w in self.CONDEMNATION), (
                f"rejected figure at offset {pos} quoted without being marked invalid")

    def test_the_rejected_table_caption_says_so(self, tex):
        label = tex.index(r"\label{tab:first}")
        caption = tex[tex.rindex(r"\caption{", 0, label):label]
        assert any(w in caption.lower() for w in self.CONDEMNATION), caption[:120]


class TestSecondWithdrawalIsStated:
    """The 103 ms offset is withdrawn: it was a per-run start-up cost, not a per-event constant.

    The runs behind it matched a median of seven events each, so the start-up cost WAS the
    median. This is the paper's second withdrawal and the one its own integrity check does not
    catch, so the text must state it plainly rather than hedge it.
    """

    def test_the_withdrawal_is_explicit(self, tex):
        section = tex[tex.index(r"\label{sec:attribution}"):tex.index(r"\label{sec:rules}")]
        low = section.lower()
        assert "withdraw" in low, "the end-to-end gap must be explicitly withdrawn"
        assert "start-up" in low or "startup" in low, "the real mechanism must be named"
        assert "seven events" in low, "the events-per-run cause must be stated"

    def test_the_events_per_run_figure_matches_the_data(self, tex):
        """The median events-per-run behind E1 is what makes the withdrawal argument."""
        import statistics as stat
        gated = _rows("e1", "e1_by_run_gated.csv")
        med = stat.median(int(r["n_matched"]) for r in gated if r["backend"] == "kafka")
        assert med == 7, f"expected a median of 7 events per run, got {med}"
        assert "seven events" in tex.lower()

    def test_the_507_emitted_events_match_the_replay_plan(self, tex):
        """The window was not the cause: the plan holds 507 events in the span E1 replayed.

        E1 ran --max-t-sim 600 against a 120x-compressed plan. If that span really did contain
        only seven events the withdrawal argument would be about window choice; it contains 507,
        so the seven are a join failure, and the paper must state a number that can be checked.
        """
        t_sim = _replayed_plan_t_sim()
        assert sum(1 for t in t_sim if t <= 600) == 507
        assert "507" in tex

    def test_the_windows_in_the_sweep_table_match_the_plan(self, tex):
        """57 and 148 events per run are properties of the plan, not of the harness.

        This is the check that the right plan is being read at all: the sweep passed both a
        positional plan (match_3895074) and --plans-dir, and --plans-dir wins, so feed 1 replayed
        plans[0] = match_3895052. Those two matches hold different numbers of events (46/112
        against 57/148), so agreeing with the measured events-per-run confirms the selection.
        """
        t_sim = _replayed_plan_t_sim()
        for window, expected in ((60, 57), (180, 148)):
            got = sum(1 for t in t_sim if t <= window)
            assert got == expected, f"{window}s window: plan holds {got}, paper says {expected}"

    def test_five_events_share_the_kickoff_timestamp(self, tex):
        """Why exactly four events queue behind the blocking send: the kickoff burst is five."""
        assert sum(1 for t in _replayed_plan_t_sim() if t == 0.0) == 5
        assert "first five events" in tex

    def test_the_kickoff_burst_is_general_not_one_match(self, tex):
        """The paper generalises from this plan, so the generalisation must hold on all of them."""
        import glob
        counts = []
        for p in sorted(glob.glob(str(REPO / "data" / "processed" / "replay_plans" /
                                      "*" / "match_*" / "replay_plan.csv"))):
            with open(p, encoding="utf-8", errors="replace") as fh:
                counts.append(sum(1 for r in csv.DictReader(fh)
                                  if float(r["t_sim_seconds"]) == 0.0))
        assert len(counts) >= 10, "too few plans to support a claim about matches in general"
        assert min(counts) >= 5, f"a match opened with fewer than five events at t=0: {counts}"

    def test_the_median_arithmetic_is_stated_and_holds(self, tex):
        """A median of seven values at 102.93 ms needs at least four of them that high.

        This is what makes the selection claim arithmetic rather than a guess, so both the
        premise and the count must survive a change to the data.
        """
        import statistics as stat
        gated = [r for r in _rows("e1", "e1_by_run_gated.csv") if r["backend"] == "kafka"]
        med_lag = stat.median(float(r["schedlag_p50"]) for r in gated)
        med_n = stat.median(int(r["n_matched"]) for r in gated)
        assert med_lag == pytest.approx(102.93, abs=0.005)
        # For an odd count n, the median is the (n+1)/2-th value, so that many are >= it.
        assert (med_n + 1) / 2 == 4
        assert "at least four" in tex.lower()

    def test_the_window_table_matches_the_sweep_csv(self, tex):
        """Every Kafka row in Table 5 is recomputed from the committed sweep output."""
        rows = {int(float(r["window_s"])): r for r in _rows("window", "window_sweep.csv")}
        assert set(rows) == {60, 180, 600}
        for w, r in rows.items():
            assert _contains_number(tex, float(r["schedlag_p50"]), 2)
            assert _contains_number(tex, float(r["schedlag_max"]), 1)
            assert str(r["events_per_run"]) in tex
            assert str(r["trace_events"]) in tex
        # The finding itself: the count is fixed while the run grows.
        assert {int(r["slow_wake"]) for r in rows.values()} == {4}
        assert {int(r["slow_produce"]) for r in rows.values()} == {1}
        grew = rows[600]["trace_events"] and (int(rows[600]["trace_events"]) /
                                              int(rows[60]["trace_events"]))
        assert f"{grew:.1f}" in tex, f"the growth factor {grew:.1f}x must be stated"

    def test_redis_counts_are_measured_zeros_not_dashes(self, tex):
        """Both arms are now loop-traced, so Redis's zeros are a measurement, not an absence.

        The em-dash placeholder belonged to the earlier one-armed campaign. Its return would
        mean the untraced data had crept back in.
        """
        # The caption precedes the label, so slice the whole table environment around it.
        lbl = tex.index(r"\label{tab:window}")
        table = tex[tex.rindex(r"\begin{table}", 0, lbl):tex.index(r"\end{table}", lbl)]
        assert "---" not in table, "no unmeasured-count placeholder may remain in the table"
        # Three Redis rows, each ending in the measured "0 & 0" counts.
        assert table.count("& 0 & 0") >= 3, "each Redis window row must show measured 0 late, 0 blocking"
        assert "both arms" in table.lower() or "same instrument" in table.lower()

    def test_the_one_armed_instrumentation_is_recorded_as_fixed(self, tex):
        """The failure is worth keeping in the text, but as something we corrected."""
        section = tex[tex.index(r"\label{sec:attribution}"):tex.index(r"\label{sec:rules}")]
        low = section.lower()
        assert "no trace" in low or "carried no trace" in low
        assert "re-ran both arms" in low or "re-ran both" in low

    def test_limitations_do_not_still_call_the_offset_unattributed(self, tex):
        """The pre-withdrawal text said the offset was 'attributed, not proven' and that a
        client comparison was 'underway'. Both were overtaken by the loop trace and by M1."""
        limits = tex[tex.index(r"\label{sec:limitations}"):]
        limits = limits[:limits.index(r"\section{Conclusion}")]
        low = limits.lower()
        assert "attributed, not proven" not in low
        assert "underway" not in low, "no limitation may point at work that has since finished"


class TestH3IsMeasuredAndSupported:
    """H3 was untested for two campaigns; E-C3 finally created the symmetric condition."""

    def test_the_h3_table_matches_the_committed_csv(self, tex):
        rows = {r["stamp"]: r for r in _rows("model", "ec3_stamping.csv")}
        assert set(rows) == {"callback", "inline"}
        for r in rows.values():
            assert _contains_number(tex, float(r["kafka_ms"]), 3)
            assert _contains_number(tex, abs(float(r["difference_ms"])), 3)

    def test_the_gap_shrinks_and_only_on_kafkas_side(self, tex):
        """The prediction is specific: symmetric stamping shrinks the gap from Kafka's side."""
        rows = {r["stamp"]: r for r in _rows("model", "ec3_stamping.csv")}
        cb, inl = rows["callback"], rows["inline"]
        assert abs(float(inl["difference_ms"])) < abs(float(cb["difference_ms"]))
        # Kafka moves; Redis does not.
        assert float(cb["kafka_ms"]) - float(inl["kafka_ms"]) > 0.03
        assert abs(float(cb["redis_ms"]) - float(inl["redis_ms"])) < 0.01

    def test_the_paper_reports_h3_supported_not_untested(self, tex):
        rules = tex[tex.index(r"\label{sec:rules}"):tex.index(r"\label{sec:network}")]
        h3 = rules[rules.index("H3, the asymmetry rule"):]
        h3 = h3[:h3.index(r"\paragraph") if r"\paragraph" in h3[20:] else len(h3)]
        assert r"\textbf{Supported.}" in h3, "H3 must now be reported as supported"
        assert "untested" not in h3.split("Two earlier attempts")[0].lower()

    def test_the_25_percent_reduction_is_stated(self, tex):
        rows = {r["stamp"]: r for r in _rows("model", "ec3_stamping.csv")}
        reduction = 1 - abs(float(rows["inline"]["difference_ms"])) / abs(
            float(rows["callback"]["difference_ms"]))
        assert 0.20 < reduction < 0.30, f"reduction is {reduction:.0%}, paper says ~25%"
        assert "25" in tex

    def test_the_scorecard_says_all_four_hold(self, tex):
        # The contribution item, not the abstract's first mention of the rules.
        item = tex[tex.index(r"\textbf{Four falsifiable rules, derived and measured}"):]
        item = item[:item.index(r"\item")]
        assert "All four hold" in item
        assert "All three hold" not in tex

    def test_the_argument_holds_at_every_candidate_replay_rate(self, tex):
        """The withdrawal must not depend on the rate the artefacts cannot supply.

        The blocking send lasts 102.6 ms of wall time, so at R times real time it spans 0.103R
        seconds of match time. At each of 1x, 120x and 1200x that span must already contain at
        least as many events as E1 matched (5-11), or the whole matched sample would not sit
        inside the prologue and the argument would need the rate after all.
        """
        t_sim = sorted(_replayed_plan_t_sim())
        median_matched = 7   # the cell that carries the reported 103 ms
        expected = {1: 5, 120: 16, 1200: 112}
        for rate, want in expected.items():
            inside = sum(1 for t in t_sim if t <= 0.1026 * rate)
            assert inside == want, f"{rate}x: plan gives {inside} events, paper says {want}"
            # The first event pays the block in produce_ms rather than inheriting it, so the
            # number of LATE events is one fewer than the prologue holds. The median of the
            # matched sample is late whenever that count reaches ceil(n/2).
            late = inside - 1
            assert late >= -(-median_matched // 2), (
                f"at {rate}x only {late} events run late, too few to carry the median of "
                f"{median_matched}: the argument no longer covers this rate")
        for rate in expected:
            assert str(rate) in tex

    def test_the_check_is_not_claimed_to_catch_it(self, tex):
        """Honesty about the limit of our own instrument is the point of this section."""
        section = tex[tex.index(r"\label{sec:attribution}"):tex.index(r"\label{sec:rules}")]
        assert "does not catch" in section.lower()

    def test_no_product_recommendation_rests_on_it(self, tex):
        """We must not tell practitioners to choose a product on a withdrawn measurement."""
        discussion = tex[tex.index(r"\subsection{For practitioners}"):]
        head = discussion[:discussion.index(r"\subsection{Threats to validity}")]
        assert "equivalent within a millisecond" in head
        assert "twentyfold" not in head.lower(), "withdrawn claim must not drive guidance"


class TestMeasuredRules:
    """Section 7.3 must report the model's rules with the values actually measured."""

    def test_h1_h2_h4_values_appear(self, tex):
        section = tex[tex.index(r"\label{sec:rules}"):tex.index(r"\label{sec:network}")]
        for token in ("-0.80", "0.98", "+0.80"):        # H1, H2, H4 rank correlations
            assert token in section, f"missing rank correlation {token}"
        for token in ("0.945", "0.640"):                # H2 model-vs-linear fit
            assert token in section, f"missing R^2 {token}"

    def test_all_four_rules_are_reported_supported(self, tex):
        section = tex[tex.index(r"\label{sec:rules}"):tex.index(r"\label{sec:network}")]
        # One \textbf{Supported.} per rule, H1 through H4.
        assert section.count(r"\textbf{Supported.}") == 4
        assert "NOT SUPPORTED" not in section.upper().replace("NOT SUPPORTED IF", "")


class TestPoweredTransportReplication:
    """Claim 1 is refined by a powered replication over ~127 events/run, not E1's seven.

    The finding is a both-and: TOST-equivalent within 1 ms at every N, yet a tight reproducible
    ~0.41 ms Hodges-Lehmann shift (Kafka slower). Both halves must survive a data change.
    """

    def test_the_transport_table_matches_the_committed_summary(self, tex):
        rows = {r["n"]: r for r in _rows("transport_rt", "transport_realtime_summary.csv")}
        assert set(rows) == {"1", "9", "12"}
        for r in rows.values():
            assert _contains_number(tex, float(r["kafka_transport_p50"]), 3)
            assert _contains_number(tex, float(r["redis_transport_p50"]), 3)

    def test_the_hl_shifts_match_the_tost_output(self, tex):
        tost = {int(r["n"]): r for r in _rows("transport_rt", "transport_realtime_tost.csv")}
        assert set(tost) == {1, 9, 12}
        for n, r in tost.items():
            # Equivalent within 1 ms by every estimator...
            assert r["equivalent"] == "True"
            assert r["boot_equivalent"] == "True"
            assert r["hl_equivalent"] == "True"
            # ...yet the shift is a real ~0.41 ms, tightly bounded, Kafka slower.
            shift = float(r["hl_shift"])
            assert 0.40 < shift < 0.43, f"N={n} HL shift {shift} outside the reported range"
            assert _contains_number(tex, round(shift, 3), 3)

    def test_redis_is_faster_and_the_effect_is_flat(self, tex):
        tost = {int(r["n"]): float(r["hl_shift"]) for r in
                _rows("transport_rt", "transport_realtime_tost.csv")}
        assert all(s > 0 for s in tost.values()), "Kafka must be the slower system at every N"
        assert max(tost.values()) - min(tost.values()) < 0.05, "the shift must be flat in N"

    def test_the_paper_states_both_halves(self, tex):
        e1 = tex[tex.index(r"\label{sec:e1}"):tex.index(r"\label{sec:attribution}")]
        low = e1.lower()
        assert "not" in low and "indistinguishable" in low, "the 'not a tie' half must be stated"
        assert "equivalent within" in low, "the within-margin half must be stated"
        assert "127 events" in e1 or "127$ events" in e1, "the powered sample size must be given"
        assert "seven events" in low, "the contrast with E1's seven events must be drawn"

    def test_the_measurement_supersedes_not_contradicts_e1(self, tex):
        e1 = tex[tex.index(r"\label{sec:e1}"):tex.index(r"\label{sec:attribution}")]
        assert "refines" in e1.lower(), "the powered run refines rather than contradicts E1"


class TestClusteringConstructCheck:
    """Inversions cluster in time (runs test z << 0): scheduling, not quantisation."""

    def test_the_clustering_z_values_match_the_csv(self, tex):
        rows = {r["condition"]: float(r["median_z"]) for r in
                _rows("model", "inversion_clustering.csv")}
        assert rows, "the clustering CSV must exist"
        for z in rows.values():
            assert z < -2, "every reported condition must be clustered"
            assert _contains_number(tex, round(z, 1), 1)

    def test_the_paper_uses_it_against_the_quantisation_rival(self, tex):
        threats = tex[tex.index(r"Construct validity: the check may not measure"):]
        para = threats[:threats.index(r"\paragraph")]
        low = para.lower()
        assert "quantis" in low, "the quantisation rival must be named"
        assert "runs test" in low or "wald" in low, "the test must be named"
        assert "cluster" in low, "the clustering finding must be stated"
        assert "no background load" in low or "idle" in low, \
            "must note clustering holds without background load"


class TestNetemConfoundIsDisclosed:
    """The injected-delay sweep confounds T_true with backlog, so H1's slope is not leaned on."""

    def test_the_variance_inflation_is_stated(self, tex):
        threats = tex[tex.index("injected-delay sweep is not a clean"):]
        para = threats[:threats.index(r"\paragraph")]
        assert "9{,}200" in para or "9200" in para, "the variance blow-up must be quantified"
        assert "confound" in para.lower()

    def test_h1_does_not_lean_on_the_confounded_slope(self, tex):
        rules = tex[tex.index("H1, the effect-size rule"):]
        h1 = rules[:rules.index(r"\paragraph{H2")]
        low = h1.lower()
        assert "do not lean on its slope" in low or "not lean on" in low
        assert "co-located" in low and "network arm" in low, \
            "H1 must lead with the clean contrast"


class TestRateProvenanceIsDisclosed:
    """The replay rate of the earliest corpus is not recoverable, and the paper must say so.

    Plans carry a baked-in 120x compression, so --speedup 1 means 120x, not real time. No
    committed artefact records the rate of any run. For E1 the surviving evidence conflicts:
    the commit says true real time, the reconstructed script says --speedup 10. A paper that
    audits its own data for physical impossibility cannot quietly assert a rate it cannot show.
    """

    def test_the_section_exists_and_states_the_compression(self, tex):
        assert r"\label{sec:rateprovenance}" in tex
        section = tex[tex.index(r"\label{sec:rateprovenance}"):]
        section = section[:section.index(r"\subsection{The property")]
        assert "120" in section, "the baked-in compression factor must be given"
        assert "1200" in section, "all three candidate rates must be named"

    def test_no_surviving_artefact_records_an_achieved_replay_rate(self):
        """The claim in that section, checked against the repo rather than asserted.

        A file recording the nominal --speedup flag does not record a rate: converting one to
        the other needs the plan's baked-in compression. So a header carrying `speedup` is only
        a counterexample if the plan it names still exists. One does carry it -- a superseded
        Testbed A scenario -- and its plan is gone, which is why the paper says "achieved".
        """
        import glob
        for path in glob.glob(str(RESULTS / "**" / "*.csv"), recursive=True):
            with open(path, encoding="utf-8", errors="replace") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames or "speedup" not in [
                        f.lower() for f in reader.fieldnames]:
                    continue
                for row in reader:
                    plan = row.get("plan_csv") or row.get("plan") or ""
                    # Recoverable only if the file names a plan AND that plan still exists,
                    # since the compression lives in the plan.
                    assert not (plan and (REPO / plan).exists()), (
                        f"{path} names a surviving plan ({plan}), so its achieved rate IS "
                        f"recoverable -- the paper's claim needs narrowing")

    def test_the_reported_cloud_corpora_record_no_rate_at_all(self):
        """E1 and the integrity audit are what the paper's results rest on."""
        import glob
        reported = glob.glob(str(RESULTS / "e1" / "*.csv")) + [
            str(RESULTS / "integrity_by_condition.csv")]
        for path in reported:
            with open(path, encoding="utf-8", errors="replace") as fh:
                header = fh.readline().lower()
            assert "speedup" not in header, f"{path} records a rate; narrow the paper's claim"

    def test_what_the_gap_does_not_touch_is_stated(self, tex):
        """A disclosure that does not bound its own scope is not useful to a reader."""
        section = tex[tex.index(r"\label{sec:rateprovenance}"):]
        section = section[:section.index(r"\subsection{The property")]
        low = section.lower()
        assert "audit is unaffected" in low
        assert "external validity" in low

    def test_the_rate_is_recovered_from_the_diagnostic_cell(self, tex):
        """The 52.34 ms cell is what identifies the rate, so it must survive a data change.

        A median of eight values is the mean of the fourth and fifth. Landing midway between
        1.6 ms and 103.5 ms requires exactly four of the eight to be late -- which is the count
        the loop trace gives at a verified real-time rate. Under 120x or 1200x the prologue
        would swallow all eight and the cell would read ~103 ms.
        """
        import statistics as stat
        cell = [float(r["schedlag_p50"]) for r in _rows("e1", "e1_by_run_gated.csv")
                if r["backend"] == "kafka" and int(r["n_matched"]) == 8]
        assert len(cell) == 15, f"the diagnostic cell has {len(cell)} runs, paper says 15"
        med = stat.median(cell)
        assert med == pytest.approx(52.34, abs=0.005)
        assert min(cell) == pytest.approx(51.60, abs=0.005)
        assert max(cell) == pytest.approx(53.01, abs=0.005)
        # Midway between the two modes, and far from either.
        assert 40 < med < 65, "the cell must sit between the modes for the argument to work"
        for token in ("52.34", "51.60", "53.01"):
            assert token in tex, f"{token} must appear in the paper"

    def test_e1_states_the_rate_as_an_inference(self, tex):
        """Recovered, not documented -- and the paper must not blur the two."""
        e1 = tex[tex.index(r"\label{sec:e1}"):tex.index(r"\label{sec:attribution}")]
        assert "true real time" in e1.lower()
        assert "inference" in e1.lower(), "the rate must be flagged as inferred"
        assert "rateprovenance" in e1, "E1 must point at the recovery argument"

    def test_the_protocol_gained_the_rule_that_would_have_prevented_it(self, tex):
        protocol = tex[tex.index(r"\label{sec:protocol}"):]
        protocol = protocol[:protocol.index(r"\subsection{For practitioners}")]
        low = protocol.lower()
        assert "achieved rate" in low
        assert "elapsed wall time" in low


class TestNoMangledMacros:
    r"""Source-level LaTeX that silently renders as literal text.

    A backslash lost in a heredoc turns \textbf{X} into a tab plus extbf{X}. LaTeX compiles it
    without error or warning -- the tab is whitespace and extbf{X} is ordinary text -- so the
    build is clean, the reference check passes, and the rendered page reads "extbfInversion
    probability is a property...". That shipped, and was found by reading the PDF.

    Note what the residue actually looks like: the backslash is not merely dropped, it is
    consumed together with the letter after it. \textbf becomes TAB + extbf, not textbf. So
    scanning for macro names missing a backslash finds nothing at all. What every instance of
    this bug does leave behind is a control character, because the escapes a shell or a Python
    string interprets -- \t \b \f \v \a \r -- each produce one. A LaTeX source has no
    legitimate use for any of them, which makes their absence a complete check rather than a
    list of the cases someone happened to think of.
    """

    # The characters those escapes produce, with the macros each one eats the front of.
    RESIDUES = {
        "\t": "\\t: textbf, texttt, tti, toprule, tabular",
        "\x08": "\\b: begin, bottomrule, bibliography",
        "\x0c": "\\f: frac, footnote, figure",
        "\x0b": "\\v: vspace, vfill",
        "\x07": "\\a: acmJournal, alpha",
        "\r": "\\r: ref, right, rho, rule",
        "\x00": "\\0: null",
    }

    def test_the_source_contains_no_control_characters(self, tex):
        """Line endings excluded: splitlines drops them, so only in-line residue registers."""
        offenders = []
        for lineno, line in enumerate(tex.splitlines(), start=1):
            for ch, which in self.RESIDUES.items():
                if ch in line:
                    offenders.append(f"line {lineno}: {which}")
        assert offenders == [], f"mangled macro left a control character: {offenders}"

    def test_the_guard_catches_the_bug_it_was_written_for(self, tmp_path):
        """The text that actually shipped, so the check cannot rot into a no-op."""
        broken = "thing in this paper. " + chr(9) + "extbf{Inversion probability is a property"
        assert any(ch in broken for ch in self.RESIDUES)

    def test_the_guard_accepts_correct_markup(self):
        good = "thing in this paper. " + chr(92) + "textbf{Inversion probability is a property}"
        assert not any(ch in good for ch in self.RESIDUES)

    def test_every_residue_is_recognised(self):
        """Each escape a heredoc or a Python string would interpret is covered."""
        for esc in ("\t", "\b", "\f", "\v", "\a", "\r", "\0"):
            assert esc in self.RESIDUES, f"unhandled escape residue {esc!r}"
