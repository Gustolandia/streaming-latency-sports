r"""Round 72's referee items, pinned so a later pass cannot quietly undo them.

Two required items, and the same sentence-level failure underneath both: a number that is
evidence for a claim it was not measured on.

R1. Section IV-D said "We replay 3,315 matches". Eleven replay plans exist. 3,315 is the size
of the corpus the workload *characterisation* covers, and commit `484b915` had already removed
that exact conflation from the abstract on 2026-07-26 -- installing a gate that reads the
abstract, because the abstract was where it had been seen. `13d1b40` wrote it into Section IV-D
six weeks later, one section below where anything was looking. Both numbers are emitted now and
the gate reads both documents (`test_paper_consistency.py`).

R2. Section V-E divided the scheduler's base slice by "a 0.1--0.5 ms delivery". That pair was
typed, and it is the range of the transport proxy: no condition in this corpus has a median
delivery below 700 us. The slice runs one to four times the delivery, not six to thirty, and
the corrected ratio is the better statement -- the scheduler's quantum lands on the scale of
the interval being measured, which is why 8.4% of events invert rather than 0.01% or 50%.

R3. Section V-B called `invCeiling` a ceiling the rate reaches while S9, repaired in round 70,
says "Neither number is a bound". Gated in `test_round70_findings.py`, beside the floor whose
repair this completes.

The round's own lesson is in `mutation_check.py`: nine of its ten anchors had gone stale, a
stale anchor printed SKIP and returned 0, and one of those nine was written against this very
defect. A skipped mutation is an unguarded claim.
"""
from pathlib import Path
import csv
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1TheCorpusAndTheCampaignAreDifferentNumbers:

    def test_both_are_emitted_from_their_own_artefact(self):
        import emit_paper_numbers as epn
        m = dict(epn.mechanism_macros())
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "football" / "feed" / "match_profiles.csv")
            .open(encoding="utf-8")))
        assert m["corpusMatches"].replace("{,}", "") == str(len(rows))
        plans = sorted((REPO / "data" / "processed" / "replay_plans").glob("*/match_*"))
        assert m["replayedMatchesWord"] == epn._spell(len(plans)) == "eleven"

    def test_the_sentence_names_each_number_with_its_own_verb(self, paper):
        """v5 (28 Sep): the setup became one paragraph (Section II-B) and the sentence is now
        "eleven of its 3,315 matches, replayed in order". The characterisation went to S20 with
        the rest of the workload's description; what stays pinned is that the replay verb
        governs the eleven and the corpus size is only the whole they were taken from."""
        i = paper.index("The workload is")
        passage = " ".join(paper[i:i + 460].split())
        assert ("StatsBomb's open football event data~" + chr(92) + "cite{statsbomb2023}: "
                + chr(92) + "replayedMatchesWord{} of its $" + chr(92)
                + "corpusMatches$ matches, replayed in order") in passage
        assert not re.search(r"replay\w*\s+(?:the\s+)?\$" + RE_BS + "corpusMatches", passage), (
            "the corpus size is the object of a replay verb again")

    def test_no_typed_corpus_size_survives_in_either_document(self, paper, supplement):
        """The characterisation number may be named; it may not be typed beside a replay."""
        for name, text in (("paper.tex", paper), ("postmortem.tex", supplement)):
            prose = re.sub(r"(?m)^%[^\n]*", "", text)
            for m in re.finditer(r"3\{,\}315", prose):
                window = " ".join(prose[max(0, m.start() - 90):m.start() + 90].split()).lower()
                assert "replay" not in window, "%s: %r" % (name, window)

    def test_the_rendered_page_says_characterize_and_eleven(self):
        """Spaces stripped: pypdf drops the space either side of a macro expansion, and a
        gate that fails on the extractor's habits stops being about the page.

        v5 (28 Sep): retargeted with the source pin above; the page reads "eleven of its
        3,315 matches, replayed in order", and the word "characterize" is S20's now."""
        tight = "".join(_rendered("paper").split())
        assert "elevenofits3,315matches,replayedinorder" in tight

    def test_the_gate_that_missed_it_now_reads_both_documents(self):
        """The fix is the gate, not the sentence. Mutation, not inspection."""
        src = (REPO / "tests" / "unit" / "test_paper_consistency.py").read_text(
            encoding="utf-8")
        i = src.index("def test_the_two_corpora_are_not_conflated")
        body = src[i:src.index("def test_both_corpus_counts_are_emitted", i)]
        assert "postmortem.tex" in body, "a gate on the abstract alone is how this got in"
        assert "REPLAY_VERBS" in body


class TestR2TheSliceIsMeasuredAgainstTheDelivery:

    def test_the_three_spans_are_emitted_from_the_ledger(self):
        import stat_intervals
        med = stat_intervals.span_medians()
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "span_symmetry.csv").open(encoding="utf-8")))
        for key, col in (("D", "median_D_us"), ("A", "median_A_us"), ("S", "median_S_us")):
            vals = sorted(float(r[col]) for r in rows)
            assert med[key][0] == vals[0] and med[key][2] == vals[-1]

    def test_the_delivery_and_the_proxy_are_not_the_same_range(self):
        """The defect in one assertion: these were printed as one pair of numbers."""
        import stat_intervals
        med = stat_intervals.span_medians()
        assert med["D"][0] > med["S"][1], (
            "the slowest condition's delivery still exceeds the typical proxy; a sentence "
            "that prints one where it means the other is out by more than the quantity "
            "itself")
        assert 500.0 < med["D"][0], (
            "the retired literal's upper end, 0.5 ms, sits below every condition's median "
            "delivery -- which is how a proxy range came to be labelled a delivery one")

    def test_the_printed_ratio_is_the_slice_over_the_delivery(self):
        import emit_paper_numbers as epn
        import kernel_constants
        import stat_intervals
        m = dict(epn.mechanism_macros())
        slice_us = 1000.0 * float(kernel_constants.constants()["base_slice_ms"])
        lo, _, hi = stat_intervals.span_medians()["D"]
        assert float(m["sliceOverDeliveryLo"]) == pytest.approx(slice_us / hi, abs=0.05)
        assert float(m["sliceOverDeliveryHi"]) == pytest.approx(slice_us / lo, abs=0.05)
        assert float(m["sliceOverDeliveryHi"]) < 6.0, (
            "'six to thirty times' was the slice over the proxy; against the delivery it is "
            "one to four, and that is the number the mechanism turns on")

    def test_the_sentence_carries_the_macros_and_no_typed_pair(self, paper):
        """v5 (28 Sep): the same sentence, now in Section III-C, wraps after "task's", so the
        anchor matches across the line break."""
        # Anchored on the sentence as rewritten on 28 September 2026, when the law campaign timed
        # the wait (Supplement S16.10): "descheduled at the wrong instant ... about a slice late"
        # became "woken while another task holds the CPU ... what is left of that task's slice".
        # What this pins is unchanged: the slice against the delivery, read from the ledger.
        # 4 Oct 2026: "thread" for "task", the paper's one name for what the scheduler runs, so
        # the slice is "the running thread's".
        i = re.search(r"waits out what is left of the\s+running\s+thread's\s+slice",
                      paper).start()
        passage = " ".join(paper[i:i + 420].split())
        for macro in ("sliceOverDeliveryLo", "sliceOverDeliveryHi",
                      "condDeliveryLoMs", "condDeliveryHiMs"):
            assert chr(92) + macro in passage, macro
        assert "0.1$--$0.5" not in passage and "six to\nthirty" not in paper

    def test_the_deletion_claim_rests_on_the_benchmarks_own_delivery(self, paper):
        """Section VI-A used our harness's proxy as evidence about the benchmark's path.

        It has the benchmark's own answer one subsection later: retention inverts Equation 4,
        so the incommensurate rates' median retention names T_true directly.

        v5 (28 Sep): Section IV-A now says only that every delivery shorter than a millisecond
        computes to zero, and the size is Section IV-C's (the incommensurate settings sit near
        50%, which gives T_true), so the pin moves there; IV-A may still size the deletion only
        beside the benchmark's own delivery.
        """
        flat = " ".join(paper.split())
        law = flat[flat.index("label{sec:extcomp}"):flat.index("label{sec:generality}")]
        i = law.index("sit near $50" + chr(92) + "%$")
        assert chr(92) + "spreadIncommensurateTrueMs" in law[i:i + 260], (
            "the claim is quantitative now: retention names the fraction, where the old "
            "wording left 'most of them' resting on a range that was the wrong span")
        assert "our own transport measures" not in paper
        filt = flat[flat.index("label{sec:extmethod}"):flat.index("label{sec:extphase}")]
        if re.search(r"\b(?:half|most|nearly all)\b", filt):
            assert chr(92) + "spreadIncommensurateTrueMs" in filt, (
                "Section IV-A sizes the deletion without the benchmark's own delivery")

    def test_the_derived_true_delivery_is_emitted_not_typed(self, paper):
        import emit_paper_numbers as epn
        m = dict(epn.spread_macros())
        assert "spreadIncommensurateTrueMs" in m
        assert abs(float(m["spreadIncommensurateTrueMs"]) - 0.49) < 0.02
        assert "T_{\\mathrm{true}} \\approx 0.5" not in paper

    def test_the_typed_pair_is_gone_from_the_whole_document(self, paper):
        assert "$0.1$--$0.5$" not in paper, (
            "the only measured property of this corpus that was typed into the main text")


class TestRecommendedItems:

    def test_w1_the_equivalence_is_stated_on_the_chain_too(self, paper):
        """v5 (28 Sep): the heading went and the paragraph (label sec:brokers) now leads with
        the causal chain (editor 6.6), so the window is the paragraph, not the text after
        "TOST".

        Left failing on purpose: v5 moved the proxy's test onto the chain ("On the end-to-end
        latency ... the two brokers sit within a millisecond (TOST against a 1 ms margin,
        p < 0.001 ...)"), but that TOST is the transport proxy's (S13.1), and the chain is
        equivalent only "against a wider margin", as v4 and S13.1 say.
        """
        i = paper.index("label{sec:brokers}")
        passage = " ".join(paper[i:paper.index(chr(92) + "section{", i)].split())
        assert "TOST" in passage
        # 1 Oct 2026: "against a wider margin" names its margin, \ttiTostMargin ms.
        assert "causal chain" in passage and (chr(92) + "ttiTostMargin") in passage

    def test_w2_the_omission_clause_excludes_the_table_that_shows_them(self, paper):
        """v5 (28 Sep): the clause ("Wilson intervals are under 0.1 points on corpus-wide
        rates and are omitted where they are that narrow, not in Table II") went with the
        pre-emptive defences (editor 6.11), so the check is now two-sided: a clause, if present,
        must exclude the table that shows the intervals, and without one the paper may not say
        that every proportion carries an interval.

        Left failing on purpose: Section II-D says "Every proportion below carries a Wilson
        score 95% interval", and Section III-A prints its corpus-wide rates (spanNegAckPct,
        the diseaseOver trio, the two rejection rates) with none.
        """
        flat = " ".join(re.sub(r"(?m)^%[^\n]*", "", paper).split())
        assert "omitted hereafter" not in flat
        i = flat.find("Wilson intervals are under")
        if i >= 0:
            assert "tab:mechanism" in flat[i:i + 200]
        universal = re.search(r"Every proportion below (?:carries|is a count over a stated "
                              r"denominator with) a Wilson", flat)
        assert i >= 0 or not universal, (
            "Section II-D says every proportion below carries a Wilson interval, the clause "
            "saying where they are omitted is gone, and Section III-A prints corpus-wide rates "
            "without one")

    def test_w3_every_factor_in_table_two_carries_its_interval(self, paper, supplement):
        """v5 (28 Sep): the Katz brackets and the z column left Table II (editor section 9)
        for S12's paragraph "The mechanism table's factors, with their intervals", so they are
        pinned there, and Table II is pinned to print each factor once with no bracket, which
        keeps the intervals in one place."""
        i = paper.index("label{tab:mechanism}")
        table = paper[i:paper.index("end{table}", i)]
        for stem in ("rtLow", "rtHigh", "GeomOrig", "GeomRepl"):
            assert chr(92) + stem + "Factor" + chr(92) + "times" in table, stem
            assert chr(92) + stem + "FactorCI" not in paper, stem
        # The interval sat on the pair's second row rather than beside the factor: the
        # multirow cell already spanned both, so it cost no column width. Widening the cell
        # instead overfull-ed the table by 47pt, which is how that arrangement was found.
        s = supplement.index("The mechanism table's factors, with their intervals")
        para = " ".join(supplement[s:supplement.index("\n\n", s)].split())
        assert "Katz $95" in para, "the paragraph names what the bracket is"
        assert "P-tab:mechanism" in para, "and which table's factors it is bracketing"
        for stem in ("rtLow", "rtHigh", "GeomOrig", "GeomRepl"):
            assert chr(92) + stem + "FactorCI" in para, stem
            assert chr(92) + stem + "Z$" in para, "%s: the z left the header with the bracket" % stem

    def test_w3_did_not_leave_the_intervals_in_two_places(self, paper):
        """The prose kept them only to have said them; the table is where they belong."""
        i = paper.index("the rate falls by factors of")
        assert chr(92) + "rtLowFactorCI" not in paper[i:i + 320]
        j = paper.index("negative-span rates differ by")
        assert chr(92) + "GeomOrigFactorCI" not in paper[j:j + 260]

    def test_w4_the_two_worst_clock_bounds_are_printed_not_only_summed(self, paper, supplement):
        """v5 (28 Sep): Section VIII keeps the per-host bound and "so we claim no cross-host
        bound in general", and the sum with its two addends is S19's alone, so it is pinned
        there and the paper is pinned to print no sum without them."""
        import emit_paper_numbers as epn
        m = dict(epn.clock_macros()) if hasattr(epn, "clock_macros") else {}
        i = paper.index("bounds its own error at")
        here = " ".join(paper[i:i + 260].split())
        assert chr(92) + "chronyHostBoundLo" in here and chr(92) + "chronyHostBoundHi" in here
        assert "we claim no cross-host bound in general" in here
        if chr(92) + "chronyPairBound" in paper:
            for macro in ("chronyWorstBound", "chronySecondWorstBound", "chronyPairBound"):
                assert chr(92) + macro in here, macro
        s = supplement.index("section{S19.")
        s19 = supplement[s:supplement.index("section{S20.", s)]
        j = s19.index("the bound it places on its own error")
        passage = " ".join(s19[j:j + 360].split())
        for macro in ("chronyWorstBound", "chronySecondWorstBound", "chronyPairBound"):
            assert chr(92) + macro in passage, macro
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert (int(vals["chronyWorstBound"]) + int(vals["chronySecondWorstBound"])
                == int(vals["chronyPairBound"])), "a sum a reader can now do"
        assert m is not None

    def test_w5_the_repeated_sample_count_says_it_is_deliberate(self, paper):
        """v5 (28 Sep): the remark went with the pre-emptive defences (editor 6.11) and with
        the alternatives list that printed the two-clock count, so the main text prints the
        count once, in Section IV-D; the two-clock count may come back only with the remark."""
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert vals["harnessOneClockSamples"] == vals["harnessCrossHostSamples"], (
            "if these ever part, the sentence below has to go")
        assert chr(92) + "harnessOneClockSamples" in paper
        i = paper.find(chr(92) + "harnessCrossHostSamples")
        if i >= 0:
            assert "matched run for run" in paper[i:i + 260], (
                "the two-clock count is back in the main text without the remark that says "
                "why it equals the one-clock count")

    def test_w6_the_better_clock_section_opens_on_its_claim(self, paper):
        """v5 (28 Sep): the subsection became the paragraph labelled sec:betterclock, whose
        claim now names the clock it means (editor 6.6), "A better-synchronized clock fixes
        neither failure"; the rule is unchanged, the claim first and the PTP arithmetic after."""
        # 4 Oct 2026: the protocol is named in full where the paper uses it, its one use.
        paras = [p for p in re.split(r"\n[ \t]*\n", paper) if "Precision Time Protocol~" in p]
        assert len(paras) == 1, "one paragraph carries the PTP arithmetic"
        opening = " ".join(re.sub(r"(?m)^\s*" + RE_BS + r"label\{[^}]*\}\s*$", "",
                                  paras[0]).split())
        assert opening.startswith("A better-synchronized clock fixes neither failure."), (
            opening[:120])
        assert (opening.index("fixes neither failure")
                < opening.index("Precision Time Protocol")), (
            "the Feynman rule: the claim first, the arithmetic that supports it after")

    def test_w7_the_grey_literature_ledger_gained_its_fourth_row(self):
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "literature_regime.csv")
            .open(encoding="utf-8")))
        comparisons = [r for r in rows if r["kind"] == "broker_comparison"]
        inside = [r for r in comparisons if r["figures_inside_regime"] == "yes"]
        assert (len(comparisons), len(inside)) == (4, 3)
        assert any(r["citation_key"] == "javacodegeeks2026brokers" for r in comparisons)

    def test_w7_the_supplement_says_what_the_new_row_adds(self, supplement):
        assert "javacodegeeks2026brokers" in supplement
        i = supplement.index("javacodegeeks2026brokers")
        passage = " ".join(supplement[max(0, i - 700):i + 900].split())
        assert "99.7th percentile" in passage
        assert "redrawing" in passage, "the row's own claim is about how figures travel"

    def test_the_bibliography_nits_are_closed(self):
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        assert "arXiv:2605.24217v2" not in bib, "no other entry carries a version suffix"
        i = bib.index("@misc{indexdev2026brokers")
        entry = bib[i:bib.index("}\n\n", i)]
        # Round 62 requires the S1 pointer; round 72 wanted the note shorter. Both are
        # satisfiable, so neither had to be overridden: the pointer stays and the sentence
        # that restated Section III-A goes. A requirement from an earlier report outranks a
        # later report's style preference (standard A1w), and here it did not have to.
        # Since 28 Sep the pointer lives in the entry's unprinted `annote`: an outside
        # editor's reading ruled that a printed reference carries a citation, not the
        # bibliography's own history (test_reference_notes.py).
        assert "S1.9 records" in entry
        assert "Section~III-A" not in entry, (
            "the note restated the body; Section III-A already says which broker gets the "
            "percentile and what it is")


class TestTheMutationCheckGuardsWhatItSaysItGuards:
    """The round's own lesson, and the one with the widest blast radius."""

    def test_every_anchor_is_present_in_the_manuscript(self):
        """v5 (28 Sep): left failing on purpose. Seven of the ten anchors in
        `scripts/mutation_check.py` went stale with the rewrite, and the anchors live in that
        script rather than here; a stale anchor guards nothing, so this fails until each is
        re-anchored to the sentence that carries its claim now, or retired with a reason."""
        import mutation_check
        src = (REPO / "paper.tex").read_text(encoding="utf-8")
        stale = [name for name, old, _ in mutation_check.MUTATIONS if old not in src]
        assert not stale, (
            "these mutations guard nothing: %s. Nine of ten were in this state when round 72 "
            "looked, and one of the nine was written against the exact defect that round's "
            "referee found." % stale)

    def test_a_vanished_anchor_fails_rather_than_skips(self, tmp_path, capsys):
        import mutation_check
        paper = tmp_path / "p.tex"
        paper.write_text("nothing any anchor matches\n", encoding="utf-8")
        rc = mutation_check.main(["--paper", str(paper),
                                  "--tests", "tests/unit/test_printed_ranges.py"])
        out = capsys.readouterr().out
        assert rc == 1, "a skip used to print and pass"
        assert "anchors are gone" in out

    def test_no_anchor_is_a_rendered_number(self):
        """Anchoring on a digit in a manuscript that emits every digit is a dead anchor."""
        import mutation_check
        for name, old, _ in mutation_check.MUTATIONS:
            digits = re.findall(r"\$-?\d[\d,.{}]*\$", old)
            assert not digits, (
                "%s anchors on %s, which the ledger can move without anyone editing the "
                "sentence" % (name, digits))


class TestEveryTypedNumeralInTheMainTextIsADecision:
    r"""Every numeral a human typed into `paper.tex`, with the reason it is not a measurement.

    Round 72 installed this after its referee swept the main text by hand and found two typed
    literals -- `0.1`--`0.5` ms, printed once for the transport proxy and once for the delivery
    -- that were the only measured property of this corpus among twenty-eight numerals.

    **Round 73 found the gate had a blind spot, and R1 was sitting in it.** The first version
    stripped every `\macro` from the source and then matched `$digits$`, admitting no
    whitespace between the delimiters. Stripping leaves a space where the control word was, so
    `$23\%$` became `$23 $` and walked straight past. Seventeen numerals hid there --
    every `$N\%$`, every `$N\,\mu$s`, `$k=6$`, `$z = -6.9$`, `$p < 0.001$`, `log$_2$` -- and
    one of them was `$23\%$`, a rate typed in round 4, quoted in the paragraph that disputes a
    concurrent paper, and reconcilable with no artefact this project holds.

    So the sweep no longer strips and then matches. It finds each math span and reads the
    numerals *inside* it, skipping those that are part of a macro name. That is the same
    question asked where the answer lives, and it is the general lesson: **a check that
    normalises its input before testing it is testing the normalisation.**

    A new literal fails this test until somebody adds it below with a reason. That is the
    point of the file -- typing a number into this manuscript is a decision that gets written
    down rather than a habit that accumulates.

    v5 (28 Sep): 3, 5, 70, 0.1 and 6.9 left with their sentences (Sharma et al.'s skew
    figures and the clustering z to the supplement, editor sections 5 and 6.11; PTP's 70 ns with
    the old better-clock arithmetic; the Wilson precision with the omission clause, 6.11), and
    0.35, 1.5 and 80 came in with new sentences, each with its reason below.
    """

    #: The span of math, and the numerals inside it that a person wrote. `(?<![A-Za-z0-9.,{}\\])`
    #: keeps `2` in `log$_2$` (a person wrote it) while dropping the `2` of `\baseSliceMs`-style
    #: names (nobody did).
    MATH = re.compile(r"(?<!\\)\$([^$]*)\$")
    NUMERAL = re.compile(r"(?<![A-Za-z0-9.,{}\\])(\d[\d,.{}]*)")

    #: value -> why it is a literal rather than a macro.
    ALLOWED = {
        # quoted from somebody else's paper or standard
        "0.75": "the kernel's published per-core slice constant, quoted from the commit that "
                "set it; the product beside it is emitted",
        "1.5": "the law campaign's registered bound on Python's plateau over Java's "
               "(prediction P8), a threshold fixed in the plan before its runs and quoted "
               "from it; what the runs measured, 3.25 and 4.25, is Part V's",
        # settings this campaign chose
        "0": "the bottom of the audit-threshold sweep",
        "20": "the top of the audit-threshold sweep",
        "6": "the loaded-core count k of the geometry manipulation",
        "200": "the payload of the named cell",
        "500": "the send rate of the named cell",
        "32": "a payload size the sweep set",
        "64": "a payload size the sweep set",
        # illustrations and presentation choices, not measurements
        "0.35": "the delivery Figure 5(a) draws at four phases of one tick, set by "
                "make_paper_figures.T_TRUE_MS to fall between grid values and to equal no "
                "quantity the ledger emits",
        # statistical conventions, not measurements
        "95": "the confidence level, which is a convention and not a result",
        "0.001": "the p-value ceiling the TOST clears, reported as an inequality",
        # configuration constants and values that are multiples of the resolution
        "1": "an evaluation point on the exposure curve, and the millisecond tick and "
             "timestamp resolution, both configuration constants",
        "10": "an evaluation point on the exposure curve",
        "100": "an evaluation point on the exposure curve",
        # "1.0" and "2.0" left this inventory in round 76: the grid values are now emitted
        # (`ombGridPrintedLo`, `ombGridPrintedHi`) from the same rows Figure 4's ticks are drawn
        # from, so neither is typed anywhere in the main text any longer.
        "1000": "the timestamp resolution in microseconds, negated: the only negative value a "
                "millisecond-floored difference can take, which is the sentence's whole point",
        "50": "the retention a half-millisecond delivery implies at a millisecond grid, the "
              "prediction the measured medians are compared against",
        # loads, which are named beside the rates measured at them
        "75": "a load level of the priority manipulation, named in Table II's stub",
        "88": "the other load level, named in Table II's stub",
    }

    def _typed(self, paper):
        """value -> one context, for every numeral a person typed inside math."""
        prose = re.sub(r"(?m)^%[^\n]*", "", paper)
        found = {}
        for m in self.MATH.finditer(prose):
            for d in self.NUMERAL.finditer(m.group(1)):
                v = d.group(1).rstrip(".,")
                found.setdefault(
                    v, " ".join(prose[max(0, m.start() - 80):m.start() + 90].split()))
        return found

    def test_no_typed_numeral_is_unaccounted_for(self, paper):
        found = self._typed(paper)
        unknown = sorted(set(found) - set(self.ALLOWED))
        assert not unknown, (
            "typed into the main text with no reason recorded: %s. Either emit it from the "
            "ledger, or add it to ALLOWED with the reason it is not a measurement. Context: "
            "%s" % (unknown, [found[u] for u in unknown]))

    def test_the_inventory_has_not_gone_stale(self, paper):
        """An entry that matches nothing is a claim about a sentence that is no longer there.

        Reported as loudly as an unaccounted literal, for the reason round 69 gave about
        vocabulary adjudications and round 72 re-learned from nine dead mutation anchors.
        """
        stale = sorted(set(self.ALLOWED) - set(self._typed(paper)))
        assert not stale, "these literals are no longer in the paper: %s" % stale

    def test_the_sweep_sees_a_numeral_a_control_word_is_touching(self):
        r"""Mutation, not inspection: the blind spot, put back, must be found.

        `$23\%$` is the shape that escaped. If this passes, the gate is measuring the
        manuscript; if it fails, the gate is measuring its own normalisation.
        """
        seen = self._typed(r"a rate of $23\%$ at $88\%$ and $-1000\,\mu$s besides")
        assert set(seen) >= {"23", "88", "1000"}, seen

    def test_the_retired_pair_cannot_come_back_under_either_name(self, paper):
        for literal in ("$0.1$--$0.5$", "$0.5$--$0.1$"):
            assert literal not in paper
        assert "3{,}315" not in paper, "the corpus size is emitted, not typed"


class TestEveryWordSpelledQuantityIsADecisionToo:
    r"""The other representation. Round 74's required item.

    Round 73 closed the gap where a numeral touching a control word escaped the sweep. It did
    not close the gap where a number is not a numeral at all. This manuscript spells small
    numbers as words, and it does so deliberately: `emit_paper_numbers.py` carries a `_spell()`
    helper and emits eleven `...Word` twins -- `harnessAuditedWord` -> *ten*,
    `harnessSilentWord` -> *five*, `replayedMatchesWord` -> *eleven* -- so that a quantity can
    open a sentence. **A number spelled out is a number typed.**

    Section VI-A read "the only cells that escape are the **four** whose payload is large
    enough". `ombEscapeCellsWord` exists, emits *four* from `len(cells) - len(grid)`, and the
    supplement uses it in exactly that sentence's twin. The same quantity was emitted in one
    document and typed in the other, four pages from the code that computes it.

    So the rule here is narrower than the numeral one and has to be, because English is full
    of the word *one*. It is not "no word-numbers"; it is **"no word-number that names a
    quantity the ledger already emits"**. That is mechanical: for each `...Word` macro, take
    its value and look for the bare word in a context that is about the same thing.

    The residue -- word-numbers naming quantities with no macro -- is enumerated below with a
    reason, the same way the numerals are.
    """

    #: Spelled quantities that are typed on purpose, with the reason. Short by design.
    ALLOWED_WORDS = {
        "four": "'about four samples in ninety thousand' is a gloss on an emitted "
                "percentage, marked as approximate so it cannot be read as a second reading",
        "ninety": "the other half of that gloss, and an approximation of the same emitted "
                  "percentage rather than a reading of its own",
        "thirty": "'nearly thirty years' since Paxson 1998, an approximation flagged as one",
        "three": "the instance count of the testbed and the decimal places of a printed "
                 "figure, both design facts rather than measurements",
        "five": "SPEC and TPC's criteria count, quoted from their paper",
        "two": "the log base of the histogram's buckets, and ordinary English throughout",
        "hundred": "'more than one event in a hundred' is the audit threshold written as a "
                   "proportion in words; the threshold itself is a rule we chose, not a "
                   "measurement, and Section II-D gives it as a percentage a few lines above",
        "thousand": "the other half of the 'about four samples in ninety thousand' gloss",
    }

    def _word_macros(self):
        """value -> macro name, for every `...Word` macro the ledger emits."""
        import re as _re
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        out = {}
        for name, val in _re.findall(
                chr(92) * 2 + r"newcommand\{" + chr(92) * 2 + r"(\w*Word)\}\{([^}]*)\}", gen):
            if name.endswith("WordCap"):
                continue
            out.setdefault(val.lower(), []).append(name)
        return out

    def test_no_sentence_types_a_word_the_ledger_emits_for_that_quantity(self, paper):
        r"""The mechanical half: a bare word next to the noun its macro is about.

        Checked by proximity to the macro's own subject rather than by the word alone, because
        "one clock" and "two threads" are English and must stay English. The subjects come
        from the macro names themselves, so a new `...Word` macro is covered the day it is
        added.
        """
        import re as _re
        subjects = {
            "ombEscapeCellsWord": ("settings that print above the grid",),
            "harnessAuditedWord": ("tools at source", "tools of Section"),
            "harnessSilentWord": ("dispose of", "disposing of"),
            "harnessSilentIndependentWord": ("independent tools",),
            "harnessDisposalClassesWord": ("classes",),
            "replayedMatchesWord": ("of its matches", "matches of one sport"),
            "spreadIncommensurateWord": ("configurations whose send interval",),
            "litComparisonsWord": ("comparisons we placed",),
            "litInsideRegimeWord": ("report figures at or below",),
            "ombEscapeCellsWordCap": (),
        }
        emitted = self._word_macros()
        prose = _re.sub(r"(?m)^%[^\n]*", "", paper)
        bad = []
        for value, names in emitted.items():
            for name in names:
                for cue in subjects.get(name, ()):
                    i = prose.find(cue)
                    while i >= 0:
                        window = " ".join(prose[max(0, i - 160):i + 160].split())
                        if (_re.search(r"(?<![A-Za-z])" + value + r"(?![A-Za-z])", window)
                                and (chr(92) + name) not in window):
                            bad.append("%r near %r but %s emits it"
                                       % (value, cue, name))
                        i = prose.find(cue, i + 1)
        assert not bad, (
            "typed where the ledger already emits the same quantity: %s" % sorted(set(bad)))

    def test_every_other_spelled_quantity_is_accounted_for(self, paper):
        """The enumerated half, matching the numeral inventory's discipline."""
        import re as _re
        prose = _re.sub(r"(?m)^%[^\n]*", "", paper)
        # Only words that sit next to a unit, a noun of count, or a comparative -- the shapes
        # in which English writes a quantity rather than an article.
        pat = _re.compile(
            r"(?<![A-Za-z])(seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
            r"sixty|seventy|eighty|ninety|hundred|thousand)(?![A-Za-z])")
        found = {}
        for m in pat.finditer(prose):
            if (chr(92) + "ombEscapeCellsWord") in prose[max(0, m.start() - 40):m.start()]:
                continue
            found.setdefault(
                m.group(1),
                " ".join(prose[max(0, m.start() - 80):m.start() + 80].split()))
        unknown = sorted(set(found) - set(self.ALLOWED_WORDS))
        assert not unknown, (
            "spelled quantities with no reason recorded: %s. Emit them, or add them to "
            "ALLOWED_WORDS with why they are not measurements. Context: %s"
            % (unknown, [found[u] for u in unknown]))

    def test_the_word_inventory_has_not_gone_stale(self, paper):
        """v5 (28 Sep): "seven" left the inventory with the rule it sat in, "Count your events
        before you quote a percentile", which the outside editor found unearned in the main
        text (6.7); S3 still states the withdrawn corpus's seven events per run. The reason for
        "hundred" names the sign check's new place, Section II-D."""
        import re as _re
        prose = _re.sub(r"(?m)^%[^\n]*", "", paper)
        stale = sorted(w for w in self.ALLOWED_WORDS
                       if not _re.search(r"(?<![A-Za-z])" + w + r"(?![A-Za-z])", prose))
        assert not stale, "these words are no longer in the paper: %s" % stale

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        """Mutation, not inspection: put the typed word back and the gate must fire.

        v5 (28 Sep): the sentence is Section IV-B's now and wraps between "that" and
        "escape", so the mutation matches across the line break instead of at one wrap.
        1 Oct 2026: the sentence was corrected (the 64 KB settings delete most of their
        samples; only the 256 KB pair keeps everything), and its count now opens it.
        """
        import re as _re
        bad = _re.sub(r"(The\s+)" + RE_BS + r"ombEscapeCellsWord\{\}(\s+settings that print)",
                      r"\g<1>four\g<2>", paper)
        assert bad != paper, "Section IV-B has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_no_sentence_types_a_word_the_ledger_emits_for_that_quantity(bad)
