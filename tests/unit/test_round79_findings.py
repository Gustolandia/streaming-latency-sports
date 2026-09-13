r"""Round 79's referee items, pinned so a later pass cannot quietly undo them.

Accept, with two things before proof.

R1. S19's "Threats to validity (full)" and "Limitations (full)" still described an earlier
paper. They called the cloud attribution "probable rather than established"; put producer and
consumer on "different hosts"; pointed "(the main text)" at an H1 slope, a netem sweep, a 15/15
count and a timer granularity the main text does not contain; said the audit removed "all of
Testbed A" (8 of its 76 conditions survive); and used "Testbed A/B", defined nowhere. The two
subsections now say what the main text says, the letters are gone, and a gate
(`test_supplement_pointers.py`) requires every supplement pointer to the main text to name its
target. 114 pointers were repointed or rewritten to pass it.

R2. Section V-A said D and A are "correlated within a run" of a correlation pooled over each
condition's runs. `span_by_condition.py` now also accumulates run-centred co-moments. The
within-run median is 0.80 against the pooled 0.84, so the unit stands and the article prints
the number that matches it; S24.2 reports both.

W1 the Katz and Fisher brackets name method and level, and a gate fails on a bare one.
W2 the recovery shift says which way it points. W3 Figure 4 prints each grid column's count and
draws overlap as depth. W4 the acknowledgment says Herbst pointed to the timer study. W5 S25
records that Kafka Streams keeps the negative Kafka's coordinator clamps. W6 one access-date
form, IEEE's, written by a script the suite checks.

One item was deleted rather than repaired, as the referee allowed: S19's "the surviving
comparison is small" named no corpus, and its counts (8 to 35 samples, an N=1 cell, 19 or more
runs) match no table in either document. S2 already says the broker claim does not rest on E1.
"""
from pathlib import Path
import re
import statistics
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "unit"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bib():
    return (REPO / "manuscript_references.bib").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ledger():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(BS * 2 + r"newcommand\{" + BS * 2 + r"(\w+)\}\{(.*)\}\s*$",
                           gen.read_text(encoding="utf-8"), re.M))


@pytest.fixture(scope="module")
def pops():
    import stat_intervals
    return stat_intervals.recovery_populations()


def flat(text):
    return " ".join(text.split())


def _between(text, start, end):
    i = text.index(start)
    return flat(text[i:text.index(end, i)])


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return flat("\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages))


STALE = ("probable rather than established", "may sit on different hosts",
         "H1's quantitative slope", "timer granularity on both platforms",
         "sensitivity analysis of the main text", "all of Testbed",
         "comparable to the distributed ones", "surviving comparison is small",
         "reported above: the queueing form")


class TestR1TheFullThreatsSayWhatTheMainTextSays:

    def test_the_stale_claims_are_gone(self, supplement):
        text = flat(supplement)
        for phrase in STALE:
            assert phrase not in text, phrase

    def test_no_testbed_is_named_by_a_letter(self, supplement):
        text = flat(supplement)
        for letter in ("Testbed~A", "Testbed~B", "Testbed A", "Testbed B"):
            assert letter not in text, letter

    def test_construct_validity_points_at_the_elimination_list(self, supplement):
        s = _between(supplement, "Threats to validity (full)", "Limitations (full)")
        assert BS + "mainThreats" in s
        assert "run on one clock by construction" in s
        assert "The workstation testbed enters only through the audit" in s

    def test_the_main_text_says_the_same_two_things(self, paper):
        text = flat(paper)
        assert "one clock by construction on the rejecting configurations" in text
        assert "enters only through the audit" in text

    def test_the_limitations_count_the_surviving_workstation_conditions(self, supplement):
        s = _between(supplement, "Limitations (full)", "E1's replay rate is inferred")
        assert BS + "auditUsableConditionsWorkstation" in s
        assert BS + "auditConditionsWorkstation" in s and "none carries a claim" in s

    def test_the_old_pointers_now_name_supplement_sections(self, supplement):
        s = _between(supplement, "Threats to validity (full)", "Limitations (full)")
        assert "S18.1 addresses it" in s and "threshold sweep of S18" in s
        assert "reported in S1.5" in s and "S3.1 withdraws that sweep" in s

    def test_the_pointer_gate_passes(self, supplement):
        import test_supplement_pointers as tsp
        assert tsp.bare_pointers(supplement) == []

    def test_the_defect_that_prompted_this_is_caught(self, supplement):
        bad = supplement.replace(
            "The workstation testbed enters only through the audit",
            "We regard the Testbed~B attribution as probable rather than established. The "
            "workstation testbed enters only through the audit")
        assert bad != supplement
        with pytest.raises(AssertionError):
            self.test_the_stale_claims_are_gone(bad)


class TestR2TheCorrelationIsComputedInTheUnitItIsQuotedIn:

    def test_both_correlations_are_emitted(self, ledger):
        pooled, within = float(ledger["spanRhoMedian"]), float(ledger["spanRhoWithinMedian"])
        assert within <= pooled, "centring on each run removes covariance, it cannot add it"
        assert 0.7 < within < 0.9, "near the pool, so 'within a run' stands"

    def test_the_article_quotes_the_within_run_median(self, paper):
        text = flat(paper)
        assert "correlated within a run (median $" + BS + "spanRhoWithinMedian$" in text
        assert "median correlation $" + BS + "spanRhoWithinMedian$" in text
        assert BS + "spanRhoMedian$" not in text

    def test_the_supplement_reports_both(self, supplement):
        s = _between(supplement, "S24.2. The statistical inventory", "S24.3. The metric map")
        assert BS + "spanRhoMedian" in s and BS + "spanRhoWithinMedian" in s

    def test_the_committed_csv_carries_the_within_run_column(self):
        import csv
        rows = list(csv.DictReader(open(REPO / "docs" / "results" / "span_symmetry.csv",
                                        encoding="utf-8")))
        vals = [float(r["rho_DA_within"]) for r in rows if r["rho_DA_within"] not in ("", "nan")]
        assert len(vals) == len(rows) == 70
        assert all(-1.0 <= v <= 1.0 for v in vals)

    @staticmethod
    def _macros(tmp_path, with_within):
        import emit_paper_numbers as epn
        cols = "condition,recovery_err_us,median_D_us,rho_DA,median_A_us,median_S_us"
        rows = [cols + (",rho_DA_within" if with_within else "")]
        for i, e in enumerate((0, 0, 50, 100, 150, 200)):
            rows.append("p%d#pass,%d,1000,0.8,10,900" % (i, e) + (",0.7" if with_within else ""))
        for i, e in enumerate((0, 60, 120, 180)):
            rows.append("f%d#fail,%d,1000,0.9,10,900" % (i, e) + (",0.6" if with_within else ""))
        path = tmp_path / "span_symmetry.csv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return dict(epn._recovery_macros(str(path)))

    def test_the_emitter_reads_the_column_when_it_is_there(self, tmp_path):
        got = self._macros(tmp_path, True)
        assert got["spanRhoWithinMedian"] == "0.70" and got["spanRhoMedian"] == "0.80"

    def test_an_older_csv_without_the_column_emits_nothing_for_it(self, tmp_path):
        got = self._macros(tmp_path, False)
        assert "spanRhoWithinMedian" not in got and "spanRhoMedian" in got


class TestW1EveryBracketNamesItsMethod:

    def test_katz_and_fisher_are_named_with_their_level(self, paper):
        text = flat(paper)
        assert "[Katz 95" + BS + "%: $" + BS + "payloadRateFallCI$]" in text
        assert ("(Spearman $" + BS + "ombRetentionRho$; Fisher 95" + BS + "%: $" + BS
                + "ombRetentionRhoCI$;") in text

    def test_the_signed_interval_reads_as_a_range(self, ledger):
        assert ledger["ombRetentionRhoCI"] == "+0.08$ to $+0.51"

    def test_the_gate_passes_and_would_have_failed(self, paper):
        import test_bracket_labels as tbl
        assert tbl.unlabeled(paper) == []
        old = paper.replace("[Katz 95" + BS + "%: $", "[$").replace(
            "(Spearman $" + BS + "ombRetentionRho$; Fisher 95" + BS + "%: $",
            "($" + BS + "ombRetentionRho$, Fisher $")
        assert sorted(n for n, _ in tbl.unlabeled(old)) == ["ombRetentionRhoCI",
                                                            "payloadRateFallCI"]


class TestW2TheShiftSaysWhichWayItPoints:

    def test_both_documents_name_the_direction(self, paper, supplement):
        i = paper.index("The displacement can be recovered rather than discarded")
        assert "rejected minus accepted" in flat(paper[i:i + 1700])
        j = supplement.index("S16.9.")
        assert "rejected minus accepted" in flat(supplement[j:j + 6000])

    def test_the_direction_is_the_one_the_pipeline_computes(self, ledger, pops):
        diffs = [y - x for x in pops["Pass"] for y in pops["Fail"]]
        assert "%.1f" % statistics.median(diffs) == ledger["recoveryShift"]
        assert float(ledger["recoveryShift"]) > 0, "positive: the rejected sit higher"

    def test_both_worst_conditions_really_are_equal(self, paper, ledger):
        assert "Both worst conditions are $" + BS + "recoveryPassMax" in flat(paper)
        assert ledger["recoveryPassMax"] == ledger["recoveryFailMax"]


class TestW3Figure4ShowsTheCountItsLegendPrints:

    def test_each_grid_column_prints_its_own_count(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import make_result_figures as mrf
        pts = mrf.retention_points()
        fig, ax = plt.subplots()
        try:
            mrf.plot_deletion(ax, pts)
            texts = [t.get_text() for t in ax.texts]
            at_grid = [p for p in pts if p[1] <= mrf.AT_GRID_MAX_MS]
            by_value = {}
            for p in at_grid:
                by_value[p[1]] = by_value.get(p[1], 0) + 1
            for value, count in by_value.items():
                assert str(count) in texts, (value, count, texts)
            assert sum(by_value.values()) == len(at_grid) == 71
            grid_markers = ax.collections[0]
            assert grid_markers.get_alpha() is not None and grid_markers.get_alpha() < 1.0
            legend = ax.get_legend()
            handles = getattr(legend, "legend_handles", None) or legend.legendHandles
            assert all(h.get_alpha() in (None, 1.0) for h in handles)
        finally:
            plt.close(fig)


class TestW4TheAcknowledgmentCreditsWhatWasDone:

    def test_the_wording_says_he_pointed_to_it(self, paper):
        i = paper.index(BS + "section*{Acknowledgment}")
        ack = flat(paper[i:i + 600])
        assert "for pointing us to the timer study cited in" in ack
        assert "timer-characterization work" not in ack


class TestW5KafkaDisposesOfTheSameNegativeBothWays:

    def test_s25_sets_the_streams_metric_beside_the_clamp(self, supplement, paper):
        i = supplement.index(BS + "cite{kafka19888}")
        near = flat(supplement[i:i + 1400])
        assert BS + "cite{kafka_streams_e2e}" in near
        assert "the disposal is a choice, not a necessity" in near
        assert "kafka_streams_e2e" not in paper, "supplement only"

    def test_the_entry_names_the_line_that_records_it(self, bib):
        i = bib.index("@misc{kafka_streams_e2e,")
        entry = flat(bib[i:bib.index("\n}", i)])
        assert "StreamTask.java" in entry and "maybeRecordE2ELatency" in entry
        assert "now - recordTimestamp" in entry and "Accessed: Sep. 13, 2026" in entry


class TestW6OneFormForAccessDates:

    def test_no_retired_form_remains(self, bib):
        import normalize_access_dates as nad
        assert nad.old_forms(bib) == []
        assert nad.normalize(bib)[1] == 0, "normalizing again changes nothing"

    def test_undated_references_are_dated_only_where_the_page_allows(self, bib):
        """The referee's condition: one form, as long as the reference column does not grow.
        Dating [34] cost nothing. Dating [24] and [32] each pushed its entry onto a new line and
        the article onto a thirteenth page, so, as the referee said, those two stay undated for
        the copy-editors rather than costing the page budget."""
        def entry(key):
            i = bib.index("{" + key + ",")
            return bib[i:bib.index("\n}", i)]
        assert "Accessed: Sep. 13, 2026" in entry("gregg2016runqlat")
        for key in ("omb_issue216", "statsbomb2023"):
            assert "Accessed" not in entry(key), key

    def test_each_retired_form_is_rewritten(self):
        import normalize_access_dates as nad
        text, n = nad.normalize("x. Read 2026-08-21}\ny; accessed 19 August 2026}\n"
                                "Accessed: June 15, 2026}")
        assert n == 3
        assert text == ("x. Accessed: Aug. 21, 2026}\ny. Accessed: Aug. 19, 2026}\n"
                        "Accessed: Jun. 15, 2026}")

    def test_the_cli_checks_and_rewrites(self, tmp_path, capsys):
        import normalize_access_dates as nad
        p = tmp_path / "refs.bib"
        p.write_text("@misc{a, note={Read 2026-09-01}}\n", encoding="utf-8")
        assert nad.main([str(p), "--check"]) == 1
        assert nad.main([str(p)]) == 0
        assert nad.main([str(p), "--check"]) == 0
        assert "Accessed: Sep. 1, 2026" in p.read_text(encoding="utf-8")
        assert "rewrote 1 date(s)" in capsys.readouterr().out


class TestTheRenderedPagesCarryIt:

    def test_the_article(self):
        text = _rendered("paper")
        for phrase in ("rejected minus accepted", "Katz 95%", "Fisher 95%",
                       "pointing us to the timer study"):
            assert phrase in text, phrase
        assert "Read 2026-" not in text

    def test_the_supplement(self):
        text = _rendered("supplement")
        assert "Testbed A" not in text and "probable rather than established" not in text
        # W6 is about the reference list. A dated observation in running prose ("Read
        # 2026-09-12.") is a sentence, not a bibliography entry, and keeps its own form.
        refs = text[text.rindex("REFERENCES"):]
        assert "Read 2026-" not in refs
