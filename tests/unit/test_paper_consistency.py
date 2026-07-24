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

    def test_h3_is_reported_as_untested_not_refuted(self, tex):
        section = tex[tex.index(r"\label{sec:rules}"):tex.index(r"\label{sec:network}")]
        low = section.lower()
        assert "untested" in low
        assert "refuted" in low, "the untested/refuted distinction must be drawn explicitly"
