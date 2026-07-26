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


def _two_prop_z(row_a, row_b):
    """Two-proportion z between two cells that each record inversions and events."""
    import math
    ka, na = int(row_a["n_inversions"]), int(row_a["n_events"])
    kb, nb = int(row_b["n_inversions"]), int(row_b["n_events"])
    pp = (ka + kb) / (na + nb)
    return (kb / nb - ka / na) / math.sqrt(pp * (1 - pp) * (1 / na + 1 / nb))


def _rows(*parts):
    with open(RESULTS.joinpath(*parts), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _section(tex, label):
    """The text of one \\subsection, found by its label and read to the next heading.

    Slicing between two labels assumes they appear in a fixed order, which broke every time the
    paper was reordered. This finds the section itself, so a test says what it means -- "in the
    section about X" -- and survives the sections being rearranged.
    """
    start = tex.index("\\label{" + label + "}")
    nxt = [i for i in (tex.find("\n\\subsection", start), tex.find("\n\\section", start))
           if i != -1]
    return tex[start:min(nxt)] if nxt else tex[start:]


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
        section = _section(tex, "sec:attribution")
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
        section = _section(tex, "sec:attribution")
        low = section.lower()
        assert "no trace" in low or "carried no trace" in low
        assert "re-ran both arms" in low or "re-ran both" in low

    def test_limitations_do_not_still_call_the_offset_unattributed(self, tex):
        """The pre-withdrawal text said the offset was 'attributed, not proven' and that a
        client comparison was 'underway'. Both were overtaken by the loop trace and by M1."""
        limits = _section(tex, "sec:limitations")
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
        rules = _section(tex, "sec:rules")
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

    def test_the_scorecard_does_not_still_claim_the_withdrawn_form(self, tex):
        """This test used to assert "All four hold", and by doing so enforced a refuted claim.

        One of the four was that inversion probability follows M/G/1 waiting time in utilisation.
        The paper refutes it: extended to the utilisation range where the candidate forms
        diverge, M/G/1 fits worse than the mean. The contribution item said all four held, and
        this test kept it that way -- a test pinned to prose rather than to a result will defend
        the prose after the result has moved.
        """
        item = tex[tex.index(r"\textbf{Falsifiable rules, derived and measured}"):]
        item = item[:item.index(r"\item")]
        assert "All four hold" not in item, "the contributions list still claims all four rules"
        assert "M/G/1" in item and "withdraw" in item, \
            "the contributions list must state the M/G/1 withdrawal where it made the claim"
        # And the refutation must be the one the artefact supports, not merely a hedge.
        assert "worse than the mean" in item

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
        section = _section(tex, "sec:attribution")
        assert "does not catch" in section.lower()

    def test_no_product_recommendation_rests_on_it(self, tex):
        """We must not tell practitioners to choose a product on a withdrawn measurement."""
        discussion = tex[tex.index(r"\subsection{For practitioners}"):]
        head = discussion[:discussion.index(r"\subsection{Threats to validity}")]
        assert "equivalent within a millisecond" in head
        assert "twentyfold" not in head.lower(), "withdrawn claim must not drive guidance"


class TestMeasuredRules:
    """Section 7.3 must report the model's rules with the values actually measured."""

    def test_h2_h4_values_appear(self, tex):
        """H1 no longer quotes a rank correlation: its sweep was withdrawn, not merely doubted."""
        section = _section(tex, "sec:rules")
        for token in ("0.98", "+0.80"):                 # H2, H4 rank correlations
            assert token in section, f"missing rank correlation {token}"
        for token in ("0.945", "0.640"):                # H2 model-vs-linear fit
            assert token in section, f"missing R^2 {token}"
        assert "-0.80" not in section, \
            "the withdrawn netem rank correlation must not reappear"

    def test_all_four_rules_are_reported_supported(self, tex):
        section = _section(tex, "sec:rules")
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
        e1 = _section(tex, "sec:e1")
        low = e1.lower()
        assert "not" in low and "indistinguishable" in low, "the 'not a tie' half must be stated"
        assert "equivalent within" in low, "the within-margin half must be stated"
        assert "127 events" in e1 or "127$ events" in e1, "the powered sample size must be given"
        assert "seven events" in low, "the contrast with E1's seven events must be drawn"

    def test_the_measurement_supersedes_not_contradicts_e1(self, tex):
        e1 = _section(tex, "sec:e1")
        assert "refines" in e1.lower(), "the powered run refines rather than contradicts E1"


class TestExternalHarnessEvidence:
    """The paper's answer to its decisive referee objection must match its artefact.

    The claim is specific -- named commit, named files, named lines -- precisely so a reader can
    check it. If the paper and the audit CSV ever drift apart, the claim becomes unverifiable,
    which is worse than not making it.
    """

    @staticmethod
    def _rows():
        return _rows("external", "harness_audit.csv")

    def test_the_cited_files_and_lines_match_the_audit(self, tex):
        section = _section(tex, "sec:external")
        for r in self._rows():
            fname = r["file"].split("/")[-1]
            assert fname in section, f"{fname} is in the audit but not cited in the paper"
            assert r["line"] in section, f"line {r['line']} ({fname}) not cited"

    def test_both_properties_are_stated(self, tex):
        section = _section(tex, "sec:external").lower()
        assert "publishtimestamp" in section, "the cross-process subtraction must be quoted"
        assert "endtoendlatencymicros > 0" in section, "the positive-only filter must be quoted"
        assert "no counter" in section or "not merely unpublished" in section

    def test_the_claim_is_scoped_to_what_the_run_shows(self, tex):
        """The result is now positive, so the scoping requirement moves rather than lapses.

        This assertion has changed twice. It began as "we have not run it", became "a null must
        not be read as support", and is now "a positive result must not be read as more than it
        is". The constant is that the section states exactly what was established and stops:
        the discard happens, it is large, it is unreported -- and whether any PUBLISHED result
        is affected remains unclaimed, because we audited no deployment but our own.
        """
        section = " ".join(_section(tex, "sec:external").lower().split())
        assert "6{,}000" in section or "6,000" in section, "the count must be stated"
        assert "6.7" in section, "the share of the run must be stated"
        assert "do not claim" in section, "the unaudited scope must stay unclaimed"
        assert "88" in section, "the load must be stated; an idle run would not have found it"

    def test_the_vacuous_zero_is_disclosed(self, tex):
        """The first attempt reported zero because the benchmark never ran, and that number
        reached a draft. A paper about instruments that fail silently cannot quietly drop its
        own instance of exactly that; the section must own it."""
        section = " ".join(_section(tex, "sec:external").lower().split())
        assert "never runs discards nothing" in section or "never ran" in section
        assert "artefact of the instrument" in section

    def test_the_result_matches_its_artefact(self, tex):
        """Guards the count AND the evidence that the run happened.

        The earlier version of this test asserted the count was ZERO, which was true of a run
        that never executed. Asserting a number is not enough when the number can be produced
        by the instrument failing, so valid and pub_lines are checked too: a benchmark that
        emitted no latency output must never have its count quoted.
        """
        rows = _rows("external", "omb_loaded_result.csv")
        assert rows, "the OMB run artefact must exist"
        r = rows[0]
        assert r["valid"] == "1", "a run that produced no output must not be quoted"
        assert int(r["pub_lines"]) > 0, "the benchmark must have produced latency output"
        assert int(r["discarded_nonpositive"]) == 6000
        assert r["load_pct"] == "88", "an idle run would not have found this"

    def test_the_commit_is_named(self, tex):
        section = _section(tex, "sec:external")
        assert "5b1fa70" in section, "the audited commit must be named for checkability"

    def test_the_criticism_is_fair_to_the_software(self, tex):
        """We criticise a widely used project by name, so the charitable reading must be given.

        The filter guards an HdrHistogram Recorder, which rejects negatives -- almost certainly
        defensive rather than evasive. Saying so is both fairer and a stronger point: the failure
        is a reasonable local fix with a non-local consequence.
        """
        # LaTeX hard-wraps prose, so collapse whitespace before matching phrases.
        section = " ".join(_section(tex, "sec:external").lower().split())
        assert "defensive rather than evasive" in section
        assert "hdrhistogram" in section, "the reason for the guard must be given"
        assert "not describing carelessness" in section

    def test_the_conclusion_carries_the_external_evidence(self, tex):
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        low = conclusion.lower()
        assert "openmessaging" in low, "the decisive evidence must reach the conclusion"
        assert "did not run" in low or "not addressed to ourselves" in low


class TestH2FormIsWithdrawn:
    """H2's functional form is withdrawn: the data cannot separate M/G/1 from an exponential.

    The pre-registered criterion (beat a straight line) still passes and is still reported as
    such. What is withdrawn is the stronger claim we had made from it. A referee raised this and
    the refit confirmed it, so the paper must not drift back to asserting the M/G/1 form.
    """

    @staticmethod
    def _table():
        """Table 7's (rho, inversion rate) rows, as the paper prints them."""
        return ([0.003, 0.253, 0.504, 0.628, 0.753, 0.878, 1.000, 1.000, 1.000],
                [0.007, 0.009, 0.022, 0.047, 0.132, 0.207, 0.208, 0.221, 0.264])

    def test_an_exponential_fits_the_published_table_at_least_as_well(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        from measurement_model import fit_mg1
        rho, inv = self._table()
        fit = fit_mg1(rho, inv)
        # Pre-registered test still passes...
        assert fit["r2_mg1"] > fit["r2_linear"]
        # ...but the form is not discriminated against a fair alternative.
        assert not fit["mg1_better"], "if this passes, the withdrawal must be revisited"
        assert fit["best_alternative"] == "exponential"

    def test_the_paper_withdraws_the_form_and_keeps_the_shape(self, tex):
        rules = _section(tex, "sec:rules")
        low = rules.lower()
        assert "withdraw" in low, "the functional-form claim must be withdrawn in the text"
        assert "superlinear" in low, "the surviving claim is the shape"
        assert "0.961" in rules, "the exponential's fit must be reported"

    def test_abstract_and_conclusion_do_not_assert_the_mg1_form(self, tex):
        for name, part in (("abstract", tex[tex.index(r"\begin{abstract}"):
                                            tex.index(r"\end{abstract}")]),
                           ("conclusion", tex[tex.index(r"\section{Conclusion}"):])):
            low = part.lower()
            if "m/g/1" in low:
                assert "withdraw" in low or "cannot" in low, \
                    f"{name} names M/G/1 without withdrawing the form claim"


class TestTwoStateModel:
    """The replacement model must match its artefact and stay honest about its status."""

    def test_the_separability_numbers_match_the_csv(self, tex):
        rows = _rows("model", "separability.csv")
        assert rows, "the separability artefact must exist"
        spreads = sorted(float(r["spread"]) for r in rows)
        median = spreads[len(spreads) // 2]
        worst = max(spreads)
        section = _section(tex, "sec:twostate")
        assert _contains_number(section, median, 2), f"median spread {median} not in the paper"
        assert _contains_number(section, worst, 2), f"worst spread {worst} not in the paper"
        # The claim is only meaningful against the scale family's failure.
        assert "23" in section, "the scale-family comparison must be stated"

    def test_the_mechanism_and_its_prediction_are_stated(self, tex):
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "preempted" in section and "running" in section
        assert "rare state" in section, "the central claim must be stated plainly"
        assert "vertically" in section and "horizontal" in section, \
            "the discriminating geometric prediction must be given"

    def test_the_exploratory_status_is_admitted(self, tex):
        """We found this by looking at the data; the paper must not present it as confirmed."""
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "exploratory" in section
        assert "found this by looking at the data" in section
        # The decisive test was un-run when this section was written and has since been run;
        # the section must name it and point forward rather than leave it pending.
        assert "real-time priority" in section, "the decisive test must be named"
        assert "ran it" in section or "reported immediately below" in section,             "the confirmatory test is no longer pending and the text must not say it is"
        assert "pre-registered in the artefact" not in section,             "the confirmatory version was run; it is not still sitting in the artefact"

    def test_the_load_axis_is_not_claimed(self, tex):
        """The bare form is a tautology in rho, and the section must say so before using it.

        With p unconstrained, any monotone rate curve is p(rho)*S under p = rate/S. The paper
        already withdrew the M/G/1 form for being unfalsifiable, so adopting a replacement that
        cannot fail would be the worse error. The fitted variant beats its comparators only by
        reading sigma and mu, and freezing sigma IMPROVES the fit -- so the section must report
        the load axis as untested rather than supported.
        """
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "tautology" in section, "the empty form must be named as empty"
        assert "no content" in section
        assert "0.9982" in section, "the ablation that undercuts the fit must be reported"

    def test_our_own_failed_prediction_is_reported_as_a_failure(self, tex):
        """E-A5 vindicated the mechanism; the load-axis prediction still missed, and the
        section must not let the first quietly cover the second.

        Registered before the sweep: 2.45-3.07 over rho 0.88 -> 0.99. Observed: 1.44. That is
        outside the band, so it failed -- being nearer than M/G/1's 13.8 does not make it a hit.
        """
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "1.44" in section, "the observed growth must be stated"
        assert "2.45" in section, "the prediction it missed must be stated beside it"
        assert "failed" in section

    def test_the_occupancy_result_matches_its_artefact(self, tex):
        rows = _rows("model", "stamping_priority.csv")
        assert rows, "the E-A5 artefact must exist"
        section = _section(tex, "sec:twostate")
        for r in rows:
            assert r["confounded"] == "False", "a confounded cell must not be reported"
            # Utilisation equality is the premise of the whole comparison.
            assert abs(float(r["rho_base"]) - float(r["rho_rt"])) <= 0.05
            assert _contains_number(section, float(r["inv_base"]), 4), \
                f"{r['level']} baseline rate missing from the paper"
            assert _contains_number(section, float(r["inv_rt"]), 4), \
                f"{r['level']} real-time rate missing from the paper"

    def test_the_fit_numbers_match_the_artefact(self, tex):
        rows = {r["model"]: float(r["r2_log"]) for r in _rows("model", "two_state_fit.csv")}
        assert rows, "the fit artefact must exist"
        section = _section(tex, "sec:twostate")
        for model in ("two_state_corrected", "exp(k rho)", "(rho/(1-rho))^k"):
            assert model in rows, f"{model} must be fitted"
            assert _contains_number(section, rows[model], 4), \
                f"{model} R2 {rows[model]} is not quoted in the paper"

    def test_the_corrected_form_does_not_win_in_the_artefact(self):
        """A guard on the conclusion, not the prose: if a rerun ever makes sigma carry the fit,
        the paper's 'untested' wording becomes wrong and must be revisited deliberately."""
        rows = {r["model"]: float(r["r2_log"]) for r in _rows("model", "two_state_fit.csv")}
        assert rows["two_state_simple"] < rows["two_state_corrected"], \
            "the simple parametric form should still fit worse"

    def test_clustering_is_offered_as_the_motivating_fact(self, tex):
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "cluster" in section
        rows = _rows("model", "inversion_clustering.csv")
        for r in rows:
            assert float(r["median_z"]) < -2
        # The paper quotes the range, which must bracket the measured values.
        assert "-4.3" in section and "-6.9" in section


class TestNarrativeArc:
    """The paper must read as one story: broker question -> impossible answer -> what survives.

    Each rewrite risks leaving a section orphaned from that arc, so the joints are pinned here
    rather than left to proofreading, which has already missed this class of drift three times.
    """

    def test_the_abstract_follows_the_stated_shape(self, tex):
        abstract = tex[tex.index(r"\begin{abstract}"):tex.index(r"\end{abstract}")]
        for beat in ("What we set out to do", "What we found instead",
                     "What we think is happening", "What the measurements say"):
            assert beat in abstract, f"abstract is missing the '{beat}' beat"
        # Humble about the original question rather than selling it.
        assert "modest" in abstract.lower()

    def test_results_are_ordered_by_consequence_not_chronology(self, tex):
        """The transferable science leads; the two-broker answer follows."""
        order = [tex.index("\\label{" + lbl + "}")
                 for lbl in ("sec:rules", "sec:mixture", "sec:e1", "sec:attribution")]
        assert order == sorted(order), \
            "Section 7 must run rules -> mixture -> brokers -> withdrawal"
        intro = _section(tex, "sec:results")
        assert "consequence rather than by chronology" in intro, \
            "the ordering must be declared, not left implicit"

    def test_the_conclusion_carries_every_headline(self, tex):
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        low = conclusion.lower()
        for claim, token in (("the audit", "1{,}321"), ("the second withdrawal", "withdraw"),
                             ("the mixture correction", "mixture"),
                             ("the broker answer", "0.41")):
            assert token.lower() in low, f"conclusion omits {claim}"

    def test_the_story_returns_to_the_original_question(self, tex):
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        low = conclusion.lower()
        assert "began by asking" in low or "we set out" in low
        assert "barely matters" in low or "least interesting" in low, \
            "the ending must be honest about what the original question was worth"

    def test_method_gives_the_reader_the_map_and_the_settings(self, tex):
        """Two things a referee needs to check the work rather than trust it."""
        assert r"\label{fig:expmap}" in tex, "the experiment map must exist"
        assert r"\label{tab:config}" in tex, "the configuration table must exist"
        config = _section(tex, "sec:config_table")
        assert "learned" in config.lower(), \
            "settings discovered through a defect must be marked as such"


class TestIndependentReplications:
    """Each headline result has a second, independent campaign confirming it."""

    def test_transport_shift_reproduces_within_the_first_campaigns_ci(self, tex):
        orig = {int(r["n"]): r for r in _rows("transport_rt", "transport_realtime_tost.csv")}
        rep = {int(r["n"]): r for r in _rows("transport_rt2", "transport_realtime_tost.csv")}
        assert set(rep) == {1, 9, 12}
        for n in (1, 9, 12):
            o_lo, o_hi = float(orig[n]["hl_ci90_lo"]), float(orig[n]["hl_ci90_hi"])
            r_lo, r_hi = float(rep[n]["hl_ci90_lo"]), float(rep[n]["hl_ci90_hi"])
            assert max(o_lo, r_lo) <= min(o_hi, r_hi), f"N={n} campaign CIs must overlap"
            assert rep[n]["hl_equivalent"] == "True"
        for token in ("0.397", "0.412", "0.413"):   # the replication shifts, as printed
            assert token in tex

    def test_h3_reproduces_in_an_independent_campaign(self, tex):
        rows = {r["stamp"]: r for r in _rows("depth_rep2/model", "ec3_stamping.csv")}
        assert set(rows) == {"callback", "inline"}
        cb, inl = abs(float(rows["callback"]["difference_ms"])), abs(float(rows["inline"]["difference_ms"]))
        assert inl < cb, "the symmetric stamp must again shrink the gap"
        # Kafka moves, Redis does not, as in the first campaign.
        assert float(rows["callback"]["kafka_ms"]) - float(rows["inline"]["kafka_ms"]) > 0.02
        assert abs(float(rows["callback"]["redis_ms"]) - float(rows["inline"]["redis_ms"])) < 0.01
        for token in ("0.276", "0.237"):
            assert token in tex


class TestMixtureStructure:
    """H9 falsified, H10 (mixture) supported, from the pre-registered E-A3 campaign."""

    def test_the_mixture_table_matches_the_conditions_csv(self, tex):
        rows = _rows("model", "collapse_conditions.csv")
        assert len(rows) == 9, "the campaign has nine load levels"
        section = tex[tex.index(r"\label{tab:mixture}"):]
        for r in rows:
            assert _contains_number(section, float(r["inversion"]), 3), \
                f"inversion {r['inversion']} at rho={r['rho']} missing from the table"
        # clustering holds at every load, and the table rounds it to one decimal
        assert all(float(r["runs_z_median"]) < -2 for r in rows)

    def test_the_core_and_tail_growth_ratio_is_stated(self, tex):
        rows = sorted(_rows("model", "collapse_conditions.csv"), key=lambda r: float(r["rho"]))
        idle, knee = rows[0], next(r for r in rows if 0.85 < float(r["rho"]) < 0.9)
        core_growth = float(knee["sigma_core"]) / float(idle["sigma_core"])
        tail_growth = float(knee["inversion"]) / float(idle["inversion"])
        assert 4 < core_growth < 6, f"core grows {core_growth:.1f}x, paper says ~5"
        assert 50 < tail_growth < 70, f"tail grows {tail_growth:.1f}x, paper says ~60"
        section = _section(tex, "sec:mixture")
        assert "60" in section and "12" in section, "the tail:core ratio must be stated"

    def test_the_collapse_is_reported_falsified(self, tex):
        section = _section(tex, "sec:mixture")
        low = section.lower()
        assert "falsified" in low, "the scale-family collapse must be reported falsified"
        assert "pre-register" in low, "and pre-registered as expected"
        assert "mixture" in low

    def test_the_fdelta_reproduction_boundary_is_honest(self, tex):
        section = _section(tex, "sec:mixture")
        rows = _rows("model", "fdelta_reproduction.csv")
        below = [r for r in rows if float(r["rho_new"]) < 0.96]
        overlap = sum(1 for r in below if r["ci_overlap"] == "True")
        assert overlap == 12 and len(below) == 17, "below-saturation reproduction is 12/17"
        assert "12" in section and "17" in section
        assert "degenerate" in section.lower(), "the rho=1 degeneracy must be named"


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

    def test_h1_rests_only_on_the_contrast_the_manipulation_cannot_spoil(self, tex):
        """The netem sweep is withdrawn outright: it does not act on T_true at all.

        Delay injected at the broker reaches the acknowledgement and the record equally, so it
        cancels in their difference. A test that merely checked for hedging would let the old
        correlation creep back; this one requires the withdrawal and its reason.
        """
        rules = tex[tex.index("H1, the effect-size rule"):]
        h1 = " ".join(rules[:rules.index(r"\paragraph{H2")].lower().split())
        assert "withdraw the intermediate points" in h1
        assert "common-mode" in h1, "the reason the manipulation fails must be named"
        assert "co-located" in h1 and "network arm" in h1, \
            "H1 must rest on the clean five-order-of-magnitude contrast"

    def test_the_common_mode_evidence_matches_the_measurement(self, tex):
        """TTI tracks the injected delay; transport does not. Both halves must be shown."""
        table = tex[tex.index(r"\label{tab:eb2}"):]
        table = table[:table.index(r"\end{table}")]
        for token in ("3.72", "23.61", "0.535", "0.480"):
            assert token in table, f"{token} missing from the common-mode table"


class TestRateProvenanceIsDisclosed:
    """The replay rate of the earliest corpus is not recoverable, and the paper must say so.

    Plans carry a baked-in 120x compression, so --speedup 1 means 120x, not real time. No
    committed artefact records the rate of any run. For E1 the surviving evidence conflicts:
    the commit says true real time, the reconstructed script says --speedup 10. A paper that
    audits its own data for physical impossibility cannot quietly assert a rate it cannot show.
    """

    def test_the_section_exists_and_states_the_compression(self, tex):
        assert r"\label{sec:rateprovenance}" in tex
        section = _section(tex, "sec:rateprovenance")
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
        section = _section(tex, "sec:rateprovenance")
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
        e1 = _section(tex, "sec:e1")
        assert "true real time" in e1.lower()
        assert "inference" in e1.lower(), "the rate must be flagged as inferred"
        assert "rateprovenance" in e1, "E1 must point at the recovery argument"

    def test_the_protocol_gained_the_rule_that_would_have_prevented_it(self, tex):
        protocol = _section(tex, "sec:protocol")
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


class TestCrossReferencesResolve:
    r"""Every \ref must point at a \label that exists.

    Written after three references were added naming sections that had never existed
    (sec:knee, sec:cleanslope, tab:claims). LaTeX renders those as bold "??" rather than
    failing, so a source-level check is what catches them. The rendered-PDF sweep this
    repository already runs found the earlier macro-mangling bugs but would report these
    only as two question marks among thirty pages.
    """

    REF = re.compile(r"\\(?:ref|autoref|eqref)\{([^}]+)\}")
    LABEL = re.compile(r"\\label\{([^}]+)\}")

    def test_no_reference_is_dangling(self, tex):
        labels = set(self.LABEL.findall(tex))
        dangling = sorted({r for r in self.REF.findall(tex) if r not in labels})
        assert dangling == [], f"\ref to labels that do not exist: {dangling}"

    def test_no_label_is_defined_twice(self, tex):
        """Duplicates make \ref resolve to whichever came last, silently."""
        found = self.LABEL.findall(tex)
        dupes = sorted({lab for lab in found if found.count(lab) > 1})
        assert dupes == [], f"labels defined more than once: {dupes}"

    def test_the_guard_catches_an_invented_label(self):
        """The exact failure that prompted this test, so it cannot rot into a no-op."""
        broken = r"see Section~\ref{sec:knee}. \label{sec:rules} text"
        labels = set(self.LABEL.findall(broken))
        assert [r for r in self.REF.findall(broken) if r not in labels] == ["sec:knee"]


class TestLoadGeometryAndTtrue:
    """The two results the audit found missing from the manuscript entirely.

    Both were collected, analysed and committed, and neither appeared in the paper. A number
    that exists only in a CSV is not a finding, and the gap was invisible to every check we had
    -- the consistency tests verify that what the paper says matches the data, and say nothing
    about data the paper never mentions.
    """

    def test_the_geometry_result_is_in_the_paper(self, tex):
        section = _section(tex, "sec:twostate")
        rows = _rows("model", "ea6", "knee_resolution.csv")
        assert rows, "the E-A6 artefact must exist"
        by = {r["condition"]: float(r["inversion_rate"]) for r in rows}
        for cond in ("k6_conc", "k6_spread"):
            assert _contains_number(section, by[cond], 4), f"{cond} rate missing from the paper"

    def test_the_identical_utilisation_is_stated(self, tex):
        """The whole force of the result is that rho is the SAME in both arms at k=6."""
        rows = _rows("model", "ea6", "knee_resolution.csv")
        rho = {r["condition"]: float(r["rho"]) for r in rows}
        assert rho["k6_conc"] == rho["k6_spread"], "the artefact must show identical rho"
        section = " ".join(_section(tex, "sec:twostate").split())
        assert "0.7531" in section and "identical to four decimals" in section

    def test_the_two_corpora_are_not_conflated(self, tex):
        """3,315 matches are characterised; eleven are replayed. The abstract merged them.

        It said the benchmark was driven with 3,315 real matches. The plan corpus holds eleven.
        The larger number is the workload characterisation and belongs only to that claim.
        """
        abstract = " ".join(re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
                                      tex, re.S).group(1).split())
        assert "characterise" in abstract, "the abstract must say 3,315 is a characterisation"
        assert "eleven" in abstract, "the abstract must say how many matches drive the benchmark"
        plans = sorted((REPO / "data" / "processed" / "replay_plans").glob("*/match_*"))
        if plans:
            assert len(plans) == 11, f"the corpus holds {len(plans)} plans; the paper says eleven"

    def test_the_traced_agreement_percentage_is_recomputed(self, tex):
        """The paper quotes an agreement figure in three places. It must be the computed one.

        docs/laws.md said 30% where the artefacts give 21.9%; a looser bound is still true but
        two documents quoting different numbers for one comparison is how a wrong one survives.
        """
        rows = {r["arm"]: r for r in _rows("model", "runq_tail.csv")}
        base = rows["base"]
        traced, observed = float(base["p_tail"]), float(base["inversion"])
        gap = abs(observed - traced) / observed
        assert 0.215 < gap < 0.225, f"agreement recomputes to {gap:.1%}"
        assert f"{round(gap * 100)}" in " ".join(tex.split()), \
            f"the paper must quote {round(gap * 100)}% for the traced/observed agreement"

    def test_the_discussion_recommends_the_mitigation_the_data_support(self, tex):
        """The paper measures a mitigation with a 7-80x effect and did not recommend it.

        Section 8.1 told benchmark authors to audit, to count events, and to use a realistic
        RTT -- all sound, none of them the thing our own manipulation shows works. The
        recommendation must also carry its two limits, or it overstates what the floor allows.
        """
        section = " ".join(_section(tex, "sec:authors").split())
        assert "unpreemptable" in section or "real-time priority" in section, \
            "the measured mitigation must be recommended"
        ratios = []
        for name in ("stamping_priority", "stamping_priority_ea5b", "stamping_priority_ea7"):
            for r in _rows("model", f"{name}.csv"):
                if float(r["inv_rt"]) > 0:
                    ratios.append(float(r["inv_base"]) / float(r["inv_rt"]))
        assert f"${round(min(ratios))}$" in section and f"${round(max(ratios))}" in section, \
            "the recommendation must quote the effect its artefacts show"
        # It reduces exposure; it does not remove it, and it perturbs what it measures.
        assert "not zero" in section, "the floor must be stated as non-zero"
        assert "changes the system it measures" in section, \
            "the perturbation caveat must accompany the recommendation"

    def test_the_measured_floor_and_ceiling_are_reported(self, tex):
        """L1 and L2 are verified in occupancy_law.csv and were reported nowhere in the paper.

        Both are load-bearing for interpretation rather than magnitude: the floor says a
        real-time thread under load measures like an idle machine, and the ceiling estimates the
        share of events exposed to a stall, which is what makes P = p*S a measurement rather
        than a fitted asymptote.
        """
        section = " ".join(_section(tex, "sec:twostate").split())
        detail = {r["law"]: r["detail"] for r in _rows("model", "occupancy_law.csv")}
        parts = dict(kv.split("=") for kv in detail["L1_floor_is_idle"].split(";"))
        assert _contains_number(section, float(parts["idle"]), 4), "the idle rate is missing"
        assert _contains_number(section, float(parts["floor"]), 4), "the real-time floor is missing"
        assert _contains_number(section, float(parts["ratio"]), 2), "the L1 ratio is missing"
        c = dict(kv.split("=") for kv in detail["L2_ceiling_below_one"].split(";"))
        assert _contains_number(section, float(c["ceiling"]), 3), "the ceiling is missing"
        assert _contains_number(section, float(c["consistency"]), 2), \
            "the across-campaign agreement on the ceiling is missing"

    def test_the_colocation_null_is_reported_as_a_failed_manipulation(self, tex):
        """E-A8 appeared in the experiment map and nowhere in the text.

        It matters that it is described as a manipulation that did not manipulate. Reporting its
        overlapping inversion rates as a null would claim a test we did not perform.
        """
        tex_flat = " ".join(tex.split())
        row = [r for r in _rows("model", "colocation.csv") if r["load"] == "0"][0]
        for field in ("t_remote_ms", "t_colocated_ms"):
            assert _contains_number(tex_flat, float(row[field]), 3), \
                f"co-location {field} missing from the paper"
        assert "E-A8" in tex_flat, "the withheld campaign must be named"
        assert row["disjoint"] == "False", "artefact must show the rates did not separate"

    def test_the_traced_tail_result_is_actually_in_the_body(self, tex):
        """The abstract's fourth headline claim had no section behind it.

        E-A9 was quoted in the abstract, listed in the power table, and forward-referenced from
        related work -- and Section 7.3 never reported it. An abstract may summarise the body;
        it may not be the only place a result appears.
        """
        section = " ".join(_section(tex, "sec:twostate").split())
        rows = {r["arm"]: r for r in _rows("model", "runq_tail.csv")}
        base = rows["base"]
        assert _contains_number(section, float(base["p_tail"]), 3), \
            "the traced stall probability is missing from the body"
        assert _contains_number(section, float(base["inversion"]), 3), \
            "the observed rate it is compared against is missing from the body"
        assert "551" in section and "570" in section, "the traced event counts are missing"
        # The zero arm must be reported, and reported as not load-bearing.
        assert "zero" in section.lower(), "the real-time arm's zero must be disclosed"

    def test_the_tail_index_rule_is_in_the_body_with_its_limits(self, tex):
        """alpha < 1 is the paper's explanation for why mean-based counters fail. It must appear
        where the mechanism is argued, not only in the abstract, and it must carry its caveats."""
        section = " ".join(_section(tex, "sec:twostate").split())
        vals = {r["quantity"]: r["value"] for r in _rows("model", "tail_index.csv")}
        assert f"{float(vals['C']):.3f}" in section, "the fitted prefactor is missing"
        assert f"{abs(float(vals['alpha'])):.3f}" in section, "the fitted exponent is missing"
        assert "finite mean" in section, "the alpha < 1 consequence must be stated"
        # The cross-check against the independent trace, and the honest gap.
        assert f"{float(vals['predicted_p_tail']):.3f}" in section, "the predicted value is missing"
        assert f"{float(vals['cross_check_ratio']):.2f}" in section, "the cross-check ratio is missing"
        assert "fitted" in section and "not derived" in section, \
            "the fit's limits must be stated where the rule is claimed"

    def test_the_priority_collapse_range_is_recomputed_from_every_pair(self, tex):
        """The abstract quotes a range. It must be the range the artefacts actually contain.

        It was not: the upper bound read 76x where the 95%-load pair gives 79.7x, an arithmetic
        slip in docs/laws.md that propagated into the abstract and the README. It understated
        our own effect, which is the direction least likely to be questioned and therefore the
        one worth pinning to a computation.
        """
        ratios = []
        for name in ("stamping_priority", "stamping_priority_ea5b", "stamping_priority_ea7"):
            for r in _rows("model", f"{name}.csv"):
                base, rt = float(r["inv_base"]), float(r["inv_rt"])
                if rt > 0:
                    ratios.append(base / rt)
        assert len(ratios) == 8, f"expected 8 matched pairs, found {len(ratios)}"
        abstract = " ".join(re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}",
                                      tex, re.S).group(1).split())
        lo, hi = min(ratios), max(ratios)
        assert f"${round(lo)}$ to ${round(hi)}" in abstract, (
            f"artefacts give {lo:.1f}x-{hi:.1f}x; abstract does not state that range")

    def test_every_float_is_referenced_from_the_text(self, tex):
        """A figure, table or equation no sentence points to is a float the reader never meets.

        LaTeX does not warn about this: an unreferenced label is perfectly legal, and the float
        still typesets. fig:window -- the whole picture of the window sweep, the evidence for a
        withdrawal -- sat unreferenced for exactly that reason. Section labels are exempt: those
        are routinely defined for navigation without being cited.
        """
        labels = set(re.findall(r"\\label\{((?:fig|tab|eq):[^}]*)\}", tex))
        referenced = set(re.findall(r"\\ref\{([^}]*)\}", tex))
        orphans = sorted(labels - referenced)
        assert not orphans, f"floats defined but never referenced: {orphans}"

    def test_no_reference_lost_its_backslash(self, tex):
        """`\\ref` mangled to `ef` renders as garbage and raises no LaTeX error.

        Five of these shipped in the built PDF as "efsec:gate" and similar. The cause is a
        heredoc reading the \\r of \\ref as a carriage return, so the residue characteristically
        begins a line.
        """
        residue = re.findall(r"(?m)^(?:ef|exttt|extbf|mph|ite|abel)\{[^}]*\}", tex)
        assert not residue, f"macros whose backslash was eaten: {residue[:5]}"

    def test_the_uniform_denominator_claim_holds_across_every_campaign(self, tex):
        """Section 6 states every inversion rate is over 2,985 events. Check it against the files.

        The claim earns something specific -- that every rate comparison is at equal n, so a
        ratio between cells cannot come from one resting on more data. That is only worth stating
        if it is true everywhere, so this test reads every rate artefact rather than a sample. A
        campaign added later with a different run count must either match or move the sentence.
        """
        import csv as _csv
        import glob as _glob
        offenders = []
        for path in sorted(_glob.glob(str(RESULTS / "model" / "**" / "*.csv"), recursive=True)):
            with open(path, newline="", encoding="utf-8") as fh:
                rows = list(_csv.DictReader(fh))
            if not rows:
                continue
            cols = [c for c in rows[0] if c in ("n_events", "n_base", "n_rt")]
            for r in rows:
                for c in cols:
                    v = (r.get(c) or "").strip()
                    if v and v != "2985":
                        offenders.append(f"{Path(path).name}:{c}={v}")
        # variance_law is the one artefact on a different footing: it is not an inversion rate,
        # so the sentence does not cover it and it must not be silently folded in.
        offenders = [o for o in offenders if not o.startswith("variance_law")]
        assert not offenders, f"the uniform-n sentence is false for: {offenders}"

    def test_the_mechanism_campaigns_appear_in_the_power_table(self, tex):
        """tab:power says what each claim rests on, and had stopped before the mechanism.

        The four campaigns that decided the mechanism were carrying results in the text with no
        row here, which is the same gap an earlier audit found in the experiment map.
        """
        section = " ".join(_section(tex, "sec:stats").split())
        for campaign in ("E-A5", "E-A6", "E-A9", "E-A10"):
            assert campaign in section, f"{campaign} missing from the power table"

    def test_the_geometry_z_scores_are_recomputed_from_the_counts(self, tex):
        """The z values in tab:ea6 must follow from the recorded counts, not from memory.

        The artefact carried a rate and no denominator until an audit caught it. A ratio of two
        proportions with no n behind it cannot be checked by anyone, including us -- so the
        counts are now recorded, and this test recomputes every z the paper prints.
        """
        section = " ".join(_section(tex, "sec:twostate").split())
        campaigns = {
            ("ea6",): (("k5", 4.09), ("k6", 10.27), ("k7", 1.22)),
            ("ea6b",): (("k5", 8.89), ("k6", 8.44), ("k7", 3.46)),
        }
        for (phase,), expectations in campaigns.items():
            rows = {r["condition"]: r for r in _rows("model", phase, "knee_resolution.csv")}
            for k, expected in expectations:
                a, b = rows[f"{k}_conc"], rows[f"{k}_spread"]
                assert int(a["n_events"]) > 0, f"{phase}/{k}: no denominator recorded"
                z = _two_prop_z(a, b)
                assert abs(z - expected) < 0.01, \
                    f"{phase}/{k}: z recomputes to {z:.2f}, paper prints {expected}"
                assert f"{expected}" in section, \
                    f"{phase}/{k}: z={expected} missing from the paper"

    def test_the_k7_null_is_withdrawn_because_the_replication_refutes_it(self, tex):
        """An earlier draft read k=7 as convergence to a null. E-A6b does not support that.

        The original campaign could not separate the geometries at k=7 (z=1.22). The replication
        separates them (z=3.46, intervals disjoint). One campaign finding no difference and
        another finding one is not a null; it is an unsettled cell, and the paper must say so
        rather than quote the campaign that agreed with us.
        """
        section = " ".join(_section(tex, "sec:twostate").split())
        orig = {r["condition"]: r for r in _rows("model", "ea6", "knee_resolution.csv")}
        rep = {r["condition"]: r for r in _rows("model", "ea6b", "knee_resolution.csv")}
        z_orig = _two_prop_z(orig["k7_conc"], orig["k7_spread"])
        z_rep = _two_prop_z(rep["k7_conc"], rep["k7_spread"])
        # The premise of the withdrawal: the two campaigns really do disagree at k=7.
        assert abs(z_orig) < 1.96 <= abs(z_rep), (
            f"k7 z: original {z_orig:.2f}, replication {z_rep:.2f} -- if these now agree, the "
            "withdrawal text needs revisiting")
        assert "withdraw" in section, "the stronger k=7 reading must be withdrawn in the text"
        assert "2\\,985" in section or "2985" in section, "the sample size must be stated"

    def test_the_geometry_replication_reproduces_the_load_bearing_cell(self, tex):
        """k=6 carries the claim: identical rho, twofold difference. It must replicate."""
        orig = {r["condition"]: r for r in _rows("model", "ea6", "knee_resolution.csv")}
        rep = {r["condition"]: r for r in _rows("model", "ea6b", "knee_resolution.csv")}
        # Identical utilisation in all four arms is what makes the cell decisive.
        rhos = {orig["k6_conc"]["rho"], orig["k6_spread"]["rho"],
                rep["k6_conc"]["rho"], rep["k6_spread"]["rho"]}
        assert len(rhos) == 1, f"k6 rho must match across all four arms, got {rhos}"
        r_o = float(orig["k6_spread"]["inversion_rate"]) / float(orig["k6_conc"]["inversion_rate"])
        r_r = float(rep["k6_spread"]["inversion_rate"]) / float(rep["k6_conc"]["inversion_rate"])
        assert abs(r_o - r_r) < 0.15, f"k6 ratio {r_o:.2f} vs {r_r:.2f} -- no longer a replication"
        section = " ".join(_section(tex, "sec:twostate").split())
        for v in (f"{r_o:.2f}", f"{r_r:.2f}"):
            assert v in section, f"ratio {v} missing from the paper"

    def test_the_ttrue_sweep_is_in_the_paper(self, tex):
        section = _section(tex, "sec:twostate")
        rows = _rows("model", "ttrue_sweep.csv")
        assert rows, "the E-A10 artefact must exist"
        for r in rows:
            assert _contains_number(section, float(r["transport_ms"]), 3), \
                f"pad {r['pad_bytes']} transport missing"
            assert _contains_number(section, float(r["inversion"]), 4), \
                f"pad {r['pad_bytes']} inversion missing"

    def test_the_ttrue_direction_is_stated_as_counterintuitive(self, tex):
        """A slower path being a MORE reliable measurement is the discriminating claim; if the
        paper states it as ordinary, the reader misses why it is evidence."""
        section = " ".join(_section(tex, "sec:twostate").lower().split())
        assert "slower" in section and "more reliable" in section
        assert "against the observed fall" in section or "against its own confound" in section

    def test_the_ttrue_sweep_manipulation_actually_worked(self):
        """Guards the precondition, not the prose: if a re-run failed to move transport, the
        inversion rates in the paper would mean nothing."""
        rows = _rows("model", "ttrue_sweep.csv")
        t = [float(r["transport_ms"]) for r in rows]
        inv = [float(r["inversion"]) for r in rows]
        assert t[-1] / t[0] > 10, "padding must have lengthened transport substantially"
        assert inv[-1] < inv[0], "the inversion rate must have fallen"


class TestConcurrentWork:
    """Sharma et al. (arXiv:2604.21361) report the same observable from a different cause.

    Their baseline is that with clocks aligned, NO negative spans occur -- which is what licenses
    reading their 3-5 ms onset as a safety threshold. We see ~23% with no skew available to
    blame. The paper must state both the convergence and the qualification, and must not
    overstate the disagreement: their measurements are not in doubt, only the generalisation a
    reader would draw from them.
    """

    def test_the_concurrent_work_is_cited(self, tex):
        assert "sharma2026causality" in tex, "concurrent work on the same failure must be cited"

    def test_their_threshold_is_stated_accurately(self, tex):
        section = " ".join(_section(tex, "sec:related_time").split())
        assert "$5$~ms" in section or "5~ms" in section, "their onset must be given"
        assert "$3$~ms" in section or "3~ms" in section

    def test_our_measured_offset_is_compared_to_their_skew(self, tex):
        """The qualification only lands if the numbers are put side by side."""
        section = " ".join(_section(tex, "sec:related_time").split())
        assert "0.067" in section, "our measured inter-host offset must be quoted"
        assert "load" in section.lower(), "the difference between the settings must be named"

    def test_the_disagreement_is_scoped_to_the_generalisation(self, tex):
        """We must not imply their measurements are wrong; only that the safe-threshold
        reading does not survive load."""
        section = " ".join(_section(tex, "sec:related_time").lower().split())
        assert "qualifies" in section or "would be wrong on a loaded machine" in section

    def test_the_scheduler_mechanism_is_cited(self, tex):
        """L3 presumes a runnable thread does not simply migrate to an idle core. That
        presumption needs a source, and it has one."""
        assert "lozi2016wastedcores" in tex
        section = " ".join(_section(tex, "sec:related_tail").split())
        assert "work conservation" in section or "cores stay idle" in section

    def test_the_tail_index_is_not_claimed_as_a_constant(self, tex):
        section = " ".join(_section(tex, "sec:related_tail").lower().split())
        assert "one fitted value from one campaign" in section
