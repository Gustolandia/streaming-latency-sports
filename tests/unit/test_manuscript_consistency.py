"""The manuscript's headline numbers must match the committed result artefacts.

This exists because of a real failure: an earlier revision withdrew an entire measurement
arm as physically invalid, yet the abstract kept quoting a transport figure (1.35 ms) taken
from one of the withdrawn tables, and the conclusion quoted a different figure for the same
quantity. Source-level proofreading missed it three times. Every number asserted here is
recomputed from the CSV that produced it, so a re-run that changes the data fails the test
rather than silently desynchronising the paper.
"""
import csv
import re
import statistics as st
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
MANUSCRIPT = REPO / "manuscript.tex"
RESULTS = REPO / "docs" / "results"


@pytest.fixture(scope="module")
def tex():
    return MANUSCRIPT.read_text(encoding="utf-8")


def _rows(*parts):
    with open(RESULTS.joinpath(*parts), encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _contains_number(tex, value, decimals):
    """True if `value` appears in the manuscript at the given precision.

    LaTeX writes thousands separators as `{,}`, so 4138.0 may appear as `4{,}138`.
    """
    plain = f"{value:.{decimals}f}"
    if decimals == 0:
        n = int(round(value))
        grouped = f"{n:,}".replace(",", "{,}")
        return plain in tex or grouped in tex
    return plain in tex


class TestWorkloadCharacterisation:
    """Section 3 must match scripts/characterize_feed.py and kickoff_concurrency.py output."""

    def test_arrival_rate_and_burstiness(self, tex):
        s = _rows("football", "feed", "feed_summary.csv")[0]
        assert _contains_number(tex, float(s["mean_rate_evs"]), 3), "mean arrival rate"
        assert _contains_number(tex, float(s["peak_rate_evs"]), 2), "peak arrival rate"
        assert _contains_number(tex, float(s["burstiness"]), 2), "peak-to-mean ratio"
        assert _contains_number(tex, float(s["n_matches"]), 0), "corpus size"

    def test_concurrency_levels_are_derived_not_chosen(self, tex):
        s = _rows("football", "concurrency", "concurrency_summary.csv")[0]
        assert _contains_number(tex, float(s["max_simultaneous_kickoffs"]), 0)
        assert _contains_number(tex, float(s["peak_matches_in_play"]), 0)
        assert _contains_number(tex, float(s["n_slots"]), 0)
        levels = s["recommended_levels"].split(";")
        # The benchmark must sweep exactly the levels the corpus recommends.
        assert r"N \in \{1, 9, 10, 12\}" in tex
        assert levels == ["1", "9", "10", "12"]


class TestClockIntegrityAudit:
    """Section 6's audit table must match the two integrity CSVs."""

    @staticmethod
    def _totals(path):
        rows = _rows(*path)
        runs = sum(int(r["n_runs"]) for r in rows)
        kept = sum(int(r["n_trustworthy"]) for r in rows)
        usable = sum(r["usable"] == "True" for r in rows)
        return runs, runs - kept, len(rows), usable

    def test_single_host_corpus(self, tex):
        runs, condemned, conds, usable = self._totals(
            ("integrity_windows", "clock_integrity_by_condition.csv"))
        assert (runs, condemned, conds, usable) == (1382, 862, 76, 8)
        for v in (runs, condemned):
            assert _contains_number(tex, v, 0)

    def test_multi_host_corpus(self, tex):
        runs, condemned, conds, usable = self._totals(
            ("integrity_by_condition.csv",))
        assert (runs, condemned, conds, usable) == (884, 459, 40, 13)
        for v in (runs, condemned):
            assert _contains_number(tex, v, 0)

    def test_totals_are_the_sum_of_the_parts(self, tex):
        a = self._totals(("integrity_windows", "clock_integrity_by_condition.csv"))
        b = self._totals(("integrity_by_condition.csv",))
        assert _contains_number(tex, a[0] + b[0], 0), "total runs audited"
        assert _contains_number(tex, a[1] + b[1], 0), "total runs condemned"


class TestE1Benchmark:
    """Section 7.1's headline comparison must match the gated per-run CSV."""

    @staticmethod
    def _gated():
        return _rows("e1", "e1_by_run_gated.csv")

    def test_retention_matches_the_integrity_record(self, tex):
        ci = _rows("e1", "e1_clock_integrity.csv")
        measured = sum(int(r["n_runs"]) for r in ci)
        retained = sum(int(r["n_trustworthy"]) for r in ci)
        assert retained == len(self._gated())
        assert f"Of {measured}" in tex and f"{retained} survive gating" in tex

    @pytest.mark.parametrize("backend,decimals", [("kafka", 1), ("redis", 1)])
    def test_pooled_end_to_end_lag(self, tex, backend, decimals):
        vals = [float(r["tti_p50"]) for r in self._gated() if r["backend"] == backend]
        assert _contains_number(tex, st.median(vals), decimals)

    @pytest.mark.parametrize("backend", ["kafka", "redis"])
    def test_pooled_transport(self, tex, backend):
        vals = [float(r["transport_p50"]) for r in self._gated() if r["backend"] == backend]
        assert _contains_number(tex, st.median(vals), 2)

    def test_per_n_transport_table(self, tex):
        rows = _rows("e1", "e1_transport_kafka_vs_redis_by_n.csv")
        assert len(rows) == 4
        for r in rows:
            assert _contains_number(tex, float(r["kafka_median"]), 3)
            assert _contains_number(tex, float(r["redis_median"]), 3)

    def test_no_concurrency_effect_for_either_backend(self, tex):
        for r in _rows("e1", "e1_transport_kruskal_across_n.csv"):
            assert r["significant"] == "False", "the paper claims neither backend degrades"
            assert _contains_number(tex, float(r["p"]), 3)

    def test_the_gap_is_scheduling_lag_not_transport(self, tex):
        """The paper's attribution claim: the 20x gap is upstream of both brokers."""
        gated = self._gated()
        med = {b: {k: st.median(float(r[k]) for r in gated if r["backend"] == b)
                   for k in ("tti_p50", "schedlag_p50", "transport_p50")}
               for b in ("kafka", "redis")}
        tti_gap = med["kafka"]["tti_p50"] - med["redis"]["tti_p50"]
        lag_gap = med["kafka"]["schedlag_p50"] - med["redis"]["schedlag_p50"]
        transport_gap = abs(med["kafka"]["transport_p50"] - med["redis"]["transport_p50"])
        assert lag_gap / tti_gap > 0.98, "scheduling lag must account for the whole gap"
        assert transport_gap < 1.0, "brokers must be within the 1 ms equivalence margin"
        assert _contains_number(tex, med["kafka"]["schedlag_p50"], 1)


class TestAckBatchingIntervention:
    """Section 7.3's intervention must match the E5 read-loop CSV."""

    def test_improvement_factor(self, tex):
        rows = _rows("e5", "e5_ack_batching.csv")
        arms = {a: [float(r["tti_median_ms"]) for r in rows if r["arm"] == a]
                for a in ("unbatched", "batched")}
        factor = st.median(arms["unbatched"]) / st.median(arms["batched"])
        assert _contains_number(tex, factor, 1), "improvement factor"
        assert _contains_number(tex, st.median(arms["unbatched"]), 0)
        assert _contains_number(tex, st.median(arms["batched"]), 0)

    def test_read_loop_evidence(self, tex):
        rows = _rows("e5", "e5_ack_batching.csv")
        for arm in ("unbatched", "batched"):
            sub = [r for r in rows if r["arm"] == arm]
            for col in ("reads", "nonempty_reads", "msgs_per_read_median"):
                assert _contains_number(tex, st.median(float(r[col]) for r in sub), 0)


class TestStalenessBudget:
    """Section 7.6 must be computed from the surviving delivery measurement."""

    def test_budget_uses_the_gated_tti_not_a_withdrawn_figure(self):
        gated = _rows("e1", "e1_by_run_gated.csv")
        kafka = st.median(float(r["tti_p50"]) for r in gated if r["backend"] == "kafka")
        redis = st.median(float(r["tti_p50"]) for r in gated if r["backend"] == "redis")
        budget = _rows("football", "budget", "backend_comparison.csv")
        transport = {float(r["transport_ms"]) for r in budget}
        assert transport == {round(kafka, 3), round(redis, 3)}, (
            "the budget must be recomputed from gated data whenever E1 changes")

    def test_shares_appear_in_the_manuscript(self, tex):
        row = _rows("football", "budget", "backend_comparison.csv")[0]
        assert _contains_number(tex, float(row["transport_share_pct"]), 2)
        assert _contains_number(tex, float(row["diff_share_pct"]), 2)


class TestNoWithdrawnFigureIsQuotedAsLive:
    """The specific defect that motivated this file."""

    WITHDRAWN_TRANSPORT = "1.346"   # Redis N=10 from the condemned accelerated corpus
    CONDEMNATION = ("condemned", "withdraw", "artefact", "invalid", "it was wrong",
                    "subsequently condemned", "fails the clock-integrity gate")

    def test_withdrawn_transport_is_always_marked_as_condemned(self, tex):
        """The figure may be quoted -- the paper's argument requires it -- but never neutrally.

        Every occurrence must sit inside a passage that says it is invalid. This is the
        check that the earlier revision failed: the abstract quoted a withdrawn transport
        figure as the paper's headline measurement.
        """
        occurrences = [m.start() for m in re.finditer(re.escape(self.WITHDRAWN_TRANSPORT), tex)]
        assert occurrences, "the condemned figure should still be reported, as evidence"
        for pos in occurrences:
            window = tex[max(0, pos - 1200):pos + 1200].lower()
            assert any(w in window for w in self.CONDEMNATION), (
                f"the condemned figure at offset {pos} is quoted without being marked invalid")

    def test_it_never_appears_in_the_abstract_or_conclusion(self, tex):
        abstract = tex[tex.index(r"\begin{abstract}"):tex.index(r"\end{abstract}")]
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        for section, name in ((abstract, "abstract"), (conclusion, "conclusion")):
            assert self.WITHDRAWN_TRANSPORT not in section, (
                f"a condemned measurement is quoted in the {name}")

    def test_every_condemned_table_says_so(self, tex):
        """Tables built on condemned data must carry the word in their caption."""
        start = tex.index(r"\caption{\textbf{The first result set, subsequently condemned.}")
        assert "condemned" in tex[start:tex.index(r"\label{tab:withdrawn}")]

    def test_abstract_and_conclusion_agree_on_the_headline(self, tex):
        abstract = tex[tex.index(r"\begin{abstract}"):tex.index(r"\end{abstract}")]
        conclusion = tex[tex.index(r"\section{Conclusion}"):]
        for figure in ("105.5", "5.2"):
            assert figure in abstract, f"{figure} missing from abstract"
            assert figure in conclusion, f"{figure} missing from conclusion"
