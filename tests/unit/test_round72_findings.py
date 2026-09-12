r"""Round 72's referee items, pinned so a later pass cannot quietly undo them.

Two required items, and the same sentence-level failure underneath both: a number that is
evidence for a claim it was not measured on.

R1. Section IV-D said "We replay 3,315 matches". Eleven replay plans exist. 3,315 is the size
of the corpus the workload *characterisation* covers, and commit `6717ce3` had already removed
that exact conflation from the abstract on 2026-07-26 -- installing a gate that reads the
abstract, because the abstract was where it had been seen. `2e15b93` wrote it into Section IV-D
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
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


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
        i = paper.index("The workload is StatsBomb")
        passage = " ".join(paper[i:i + 460].split())
        assert "characterize the full $" + chr(92) + "corpusMatches$-match corpus" in passage
        assert "replay " + chr(92) + "replayedMatchesWord{} of its matches" in passage

    def test_no_typed_corpus_size_survives_in_either_document(self, paper, supplement):
        """The characterisation number may be named; it may not be typed beside a replay."""
        for name, text in (("paper.tex", paper), ("supplement.tex", supplement)):
            prose = re.sub(r"(?m)^%[^\n]*", "", text)
            for m in re.finditer(r"3\{,\}315", prose):
                window = " ".join(prose[max(0, m.start() - 90):m.start() + 90].split()).lower()
                assert "replay" not in window, "%s: %r" % (name, window)

    def test_the_rendered_page_says_characterize_and_eleven(self):
        """Spaces stripped: pypdf drops the space either side of a macro expansion, and a
        gate that fails on the extractor's habits stops being about the page."""
        tight = "".join(_rendered("paper").split())
        assert "characterizethefull3,315-matchcorpusandreplayelevenofitsmatches" in tight

    def test_the_gate_that_missed_it_now_reads_both_documents(self):
        """The fix is the gate, not the sentence. Mutation, not inspection."""
        src = (REPO / "tests" / "unit" / "test_paper_consistency.py").read_text(
            encoding="utf-8")
        i = src.index("def test_the_two_corpora_are_not_conflated")
        body = src[i:src.index("def test_both_corpus_counts_are_emitted", i)]
        assert "supplement.tex" in body, "a gate on the abstract alone is how this got in"
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
        i = paper.index("descheduled at the wrong instant")
        passage = " ".join(paper[i:i + 420].split())
        for macro in ("sliceOverDeliveryLo", "sliceOverDeliveryHi",
                      "condDeliveryLoMs", "condDeliveryHiMs"):
            assert chr(92) + macro in passage, macro
        assert "0.1$--$0.5" not in passage and "six to\nthirty" not in paper

    def test_the_deletion_claim_rests_on_the_benchmarks_own_delivery(self, paper):
        """Section VI-A used our harness's proxy as evidence about the benchmark's path.

        It has the benchmark's own answer one subsection later: retention inverts Equation 4,
        so the incommensurate rates' median retention names T_true directly.
        """
        i = paper.index("has millisecond resolution")
        passage = " ".join(paper[i:i + 380].split())
        assert chr(92) + "spreadIncommensurateTrueMs" in passage
        assert "our own transport measures" not in paper
        assert "about half of what a co-located run takes" in passage, (
            "the claim is quantitative now: retention names the fraction, where the old "
            "wording left 'most of them' resting on a range that was the wrong span")

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
        i = paper.index("TOST against a")
        passage = " ".join(paper[i:i + 300].split())
        assert "causal chain" in passage and "wider margin" in passage

    def test_w2_the_omission_clause_excludes_the_table_that_shows_them(self, paper):
        i = paper.index("Wilson intervals are under")
        passage = " ".join(paper[i:i + 200].split())
        assert "omitted hereafter" not in passage
        assert "tab:mechanism" in passage

    def test_w3_every_factor_in_table_two_carries_its_interval(self, paper):
        i = paper.index("label{tab:mechanism}")
        table = paper[i:paper.index("end{table}", i)]
        for stem in ("rtLow", "rtHigh", "GeomOrig", "GeomRepl"):
            assert chr(92) + stem + "FactorCI" in table, stem
        # The interval sits on the pair's second row rather than beside the factor: the
        # multirow cell already spans both, so it costs no column width. Widening the cell
        # instead overfull-ed the table by 47pt, which is how this arrangement was found.
        i = paper.index("label{tab:mechanism}")
        caption = " ".join(paper[max(0, i - 900):i].split())
        assert "Katz $95" in caption, "the caption names what the bracket is"
        assert "Factor ($z$)" in table, "the header stays at its original width"

    def test_w3_did_not_leave_the_intervals_in_two_places(self, paper):
        """The prose kept them only to have said them; the table is where they belong."""
        i = paper.index("The rate falls by factors of")
        assert chr(92) + "rtLowFactorCI" not in paper[i:i + 320]
        j = paper.index("negative-span rates differ by")
        assert chr(92) + "GeomOrigFactorCI" not in paper[j:j + 260]

    def test_w4_the_two_worst_clock_bounds_are_printed_not_only_summed(self, paper):
        import emit_paper_numbers as epn
        m = dict(epn.clock_macros()) if hasattr(epn, "clock_macros") else {}
        i = paper.index("bounds its own error at")
        passage = " ".join(paper[i:i + 260].split())
        for macro in ("chronyWorstBound", "chronySecondWorstBound", "chronyPairBound"):
            assert chr(92) + macro in passage, macro
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert (int(vals["chronyWorstBound"]) + int(vals["chronySecondWorstBound"])
                == int(vals["chronyPairBound"])), "a sum a reader can now do"
        assert m is not None

    def test_w5_the_repeated_sample_count_says_it_is_deliberate(self, paper):
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        assert vals["harnessOneClockSamples"] == vals["harnessCrossHostSamples"], (
            "if these ever part, the sentence below has to go")
        i = paper.index(chr(92) + "harnessCrossHostSamples$ two-clock samples")
        assert "matched run for run" in paper[i:i + 260]

    def test_w6_the_better_clock_section_opens_on_its_claim(self, paper):
        i = paper.index("subsection{The limits of a better clock}")
        opening = " ".join(paper[i:i + 420].split())
        assert opening.index("converts an uncounted") < opening.index("PTP"), (
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
        assert "S1.9 records" in entry
        assert "Section~III-A" not in entry, (
            "the note restated the body; Section III-A already says which broker gets the "
            "percentile and what it is")


class TestTheMutationCheckGuardsWhatItSaysItGuards:
    """The round's own lesson, and the one with the widest blast radius."""

    def test_every_anchor_is_present_in_the_manuscript(self):
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
    """

    #: The span of math, and the numerals inside it that a person wrote. `(?<![A-Za-z0-9.,{}\\])`
    #: keeps `2` in `log$_2$` (a person wrote it) while dropping the `2` of `\baseSliceMs`-style
    #: names (nobody did).
    MATH = re.compile(r"(?<!\\)\$([^$]*)\$")
    NUMERAL = re.compile(r"(?<![A-Za-z0-9.,{}\\])(\d[\d,.{}]*)")

    #: value -> why it is a literal rather than a macro.
    ALLOWED = {
        # quoted from somebody else's paper or standard
        "3": "Sharma et al.'s injected-skew threshold, quoted from their paper",
        "5": "Sharma et al.'s upper skew figure, quoted from their paper",
        "70": "PTP's specified accuracy, quoted from the standard",
        "0.75": "the kernel's published per-core slice constant, quoted from the commit that "
                "set it; the product beside it is emitted",
        # settings this campaign chose
        "0": "the bottom of the audit-threshold sweep",
        "20": "the top of the audit-threshold sweep",
        "6": "the loaded-core count k of the geometry manipulation",
        "200": "the payload of the named cell",
        "500": "the send rate of the named cell",
        "32": "a payload size the sweep set",
        "64": "a payload size the sweep set",
        # statistical conventions, not measurements
        "95": "the confidence level, which is a convention and not a result",
        "0.1": "the precision at which the corpus-wide Wilson intervals are described",
        "0.001": "the p-value ceiling the TOST clears, reported as an inequality",
        "6.9": "a z-statistic quoted to one decimal beside the effect it belongs to",
        # configuration constants and values that are multiples of the resolution
        "1": "an evaluation point on the exposure curve, and the millisecond tick and "
             "timestamp resolution, both configuration constants",
        "10": "an evaluation point on the exposure curve",
        "100": "an evaluation point on the exposure curve",
        "1.0": "a grid value: an exact multiple of the timestamp resolution, which is what "
               "the sentence is about",
        "2.0": "a grid value, as above",
        "1000": "the timestamp resolution in microseconds, negated: the only negative value a "
                "millisecond-floored difference can take, which is the sentence's whole point",
        "2": "the log base of the histogram's buckets",
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
