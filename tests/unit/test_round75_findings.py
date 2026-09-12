r"""Round 75's referee items, pinned so a later pass cannot quietly undo them.

Two required items. They are different failures and they have the same shape: a check that
looked at a property of a line instead of at what the line said.

R1. The Index Terms. Three rounds recorded "six, alphabetical" and all three were right --
`test_index_terms_are_alphabetical` has verified the ordering since round 33. Nobody read the
terms. A paper titled *Latency Measurement Artifacts in Streaming Benchmarks* carried index
terms containing none of *latency*, *benchmark*, *streaming*, *timestamp*, *clock*,
*resolution* or *quantization*, so the readers who would search for it could not find it by
them. One term was an eight-word IEEE subject-category heading with three commas inside a
semicolon-separated list, which a parser reads as four items. The gate below reads the terms.

R2. Section V-D asserted that the recovery's two populations "separate at the median, not in
the upper tail". The four numbers under that clause are emitted and exact; the inference on
top of them was tested by nothing and is false. The maxima are identical, the upper quartiles
are a point and a quarter apart, and the Hodges--Lehmann shift is about a point. The
eight-point median gap is a concentration at exactly zero in the accepted population. Section
VIII-B's fourth rule already drew the opposite inference from the same data and was right, so
the manuscript was contradicting itself across four pages with no gate able to see it.

Two corrections to the referee, both in the direction of the manuscript's own evidence.

First, its R2 states the recovery is "never exact on the rejected ones". It is exact on
`recoveryFailExact` percent of them -- six of twenty-eight. The correction strengthens the
referee's own conclusion rather than weakening it: exactness is not a property the check
selects for, which is a cleaner statement than a population boundary. Its suggested wording
also says "same upper quartile", and the two round to different whole percentages, so the
sentence written instead claims the maximum and the shift, both of which are true as printed.

Second, its W1 asked for a clause and the paragraph written is longer, because naming a
remedy without saying what it costs is how the remedy gets prescribed again. A monotonic
clock has a per-boot origin and the end-to-end span crosses two hosts.

W3 asked for no change at all: Section VII spells the disposal-class count twice, six lines
apart, and both come from one macro. Recorded here so a later round does not read the
repetition as an oversight and delete one of them.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ledger():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(BS * 2 + r"newcommand\{" + BS * 2 + r"(\w+)\}\{([^}]*)\}",
                           gen.read_text(encoding="utf-8")))


def _index_terms(tex):
    m = re.search(r"\\begin\{IEEEkeywords\}(.*?)\\end\{IEEEkeywords\}", tex, re.S)
    assert m, "no IEEEkeywords block"
    body = re.sub(r"(?m)%[^\n]*", "", m.group(1))
    return [t.strip().rstrip(".") for t in body.split(";") if t.strip()]


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1TheIndexTermsNameTheirOwnSubject:
    r"""The retrieval surface, read rather than sorted."""

    #: Words the paper is about, each drawn from the title or from a section heading, with
    #: where it comes from. A term list that contains none of these describes another paper.
    #: Matched as a prefix so *benchmark* covers *benchmarking* and *clock* covers
    #: *clock synchronization*.
    SUBJECT_WORDS = {
        "latency": "the title's own noun",
        "benchmark": "the title's own noun, and the population Section VII audits",
        "measurement": "the title's own noun",
        "clock": "Section IV-C, and the failure the paper says is NOT the cause",
        "timestamp": "Sections III and IV-C: what a timestamp marks is the paper's subject",
        "scheduling": "Section III's mechanism, and Section V-E's slice",
        "stream": "the title's own adjective, and the whole population under audit",
    }

    def test_the_terms_carry_the_paper_s_own_subject_words(self, paper):
        terms = " ".join(_index_terms(paper)).lower()
        missing = sorted(w for w in self.SUBJECT_WORDS if w not in terms)
        assert not missing, (
            "the index terms name none of %s. A reader searching IEEE Xplore for what this "
            "paper is about will not surface it; each of these is in the title or a section "
            "heading. Reasons: %s"
            % (missing, {w: self.SUBJECT_WORDS[w] for w in missing}))

    def test_the_title_s_nouns_are_all_there(self, paper):
        """Narrower and harder to argue with: the words on the front page.

        Matched on a six-character stem, because an index term is a noun phrase and a title
        is prose: *streaming benchmarks* and *stream processing; benchmarking* are the same
        two subjects under different inflections, and a gate that could not see that would
        force the title's grammar onto the keyword line.
        """
        title = re.search(r"\\title\{(.*?)\}", paper, re.S)
        assert title, "no title"
        nouns = [w for w in re.findall(r"[A-Za-z]{5,}", title.group(1).lower())
                 if w not in ("faster", "light", "artifacts")]
        assert len(nouns) >= 4, "the title has changed shape; re-derive this list"
        terms = " ".join(_index_terms(paper)).lower()
        missing = [n for n in nouns if n[:6] not in terms]
        assert not missing, "title nouns absent from the index terms: %s" % missing

    def test_no_term_is_a_subject_category_heading(self, paper):
        """House style, measured over the reference corpus: median two words per term, median
        longest term three. An eight-word category heading is not a keyword."""
        long = [t for t in _index_terms(paper) if len(t.split()) > 4]
        assert not long, (
            "index terms of more than four words are subject-category headings, not "
            "keywords: %s" % long)

    def test_no_term_contains_the_separator_of_another_list(self, paper):
        """A comma inside a semicolon-separated list is read as four items where one was
        meant -- by a parser, and by a reader skimming the line."""
        commas = [t for t in _index_terms(paper) if "," in t]
        assert not commas, "commas inside semicolon-separated index terms: %s" % commas

    def test_the_count_is_within_the_corpus_s_own_range(self, paper):
        terms = _index_terms(paper)
        assert 4 <= len(terms) <= 8, (
            "%d index terms; the reference corpus's median is five and IEEE recommends a "
            "minimum of three" % len(terms))

    def test_the_ordering_the_earlier_rounds_checked_still_holds(self, paper):
        """Not a contradiction of rounds 33 to 74: the list was alphabetical and still is.
        The property was true and insufficient, which is the finding."""
        lowered = [t.lower() for t in _index_terms(paper)]
        assert lowered == sorted(lowered)

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        """Mutation: put round 74's list back and the subject-word gate must fire."""
        old = ("distributed systems;\nmeasurement techniques;\n"
               "measurement, evaluation, modeling, simulation of multiple-processor "
               "systems;\nmessage passing;\nperformance attributes;\n"
               "scheduling and task partitioning.")
        block = re.search(r"(\\begin\{IEEEkeywords\}\n)(.*?)(\n\\end\{IEEEkeywords\})",
                          paper, re.S)
        assert block, "the keywords block has moved; retarget this mutation"
        bad = paper[:block.start(2)] + old + paper[block.end(2):]
        with pytest.raises(AssertionError):
            self.test_the_terms_carry_the_paper_s_own_subject_words(bad)
        with pytest.raises(AssertionError):
            self.test_no_term_contains_the_separator_of_another_list(bad)


class TestR2TheRecoveryPopulationsDoNotSeparate:

    def test_the_separation_claim_is_gone(self, paper):
        assert "they separate\nat the median" not in paper
        assert "separate at the median" not in " ".join(paper.split()), (
            "Section V-D's four numbers support no such claim; the shift is about a point")

    def test_the_shift_is_emitted_from_the_same_function_as_the_four_numbers(self):
        import emit_paper_numbers as epn
        got = dict(epn._recovery_macros())
        for name in ("recoveryErrPass", "recoveryErrFail", "recoveryShift",
                     "recoveryShiftPairs", "recoveryPassExact", "recoveryFailExact",
                     "recoveryPassMax", "recoveryFailMax"):
            assert name in got, "%s is not emitted beside the numbers it qualifies" % name

    def test_the_shift_is_small_and_the_maxima_agree(self, ledger):
        """The two facts Section V-D now asserts, checked against the ledger rather than
        against the sentence."""
        assert abs(float(ledger["recoveryShift"])) < 3.0, (
            "the Hodges-Lehmann shift has moved; Section V-D's 'the populations behind them "
            "do not differ' must be re-argued, not merely re-emitted")
        assert ledger["recoveryPassMax"] == ledger["recoveryFailMax"], (
            "Section V-D says the worst condition is the same on either side and prints one "
            "of the two macros; if they diverge the sentence is false")

    def test_the_concentration_at_zero_is_what_moves_the_median(self, ledger):
        """The structure the corrected sentence attributes the median gap to."""
        exact = float(ledger["recoveryPassExact"])
        gap = float(ledger["recoveryErrFail"]) - float(ledger["recoveryErrPass"])
        assert exact >= 25.0, (
            "fewer than a quarter of accepted conditions recover exactly, so the "
            "concentration at zero no longer explains the %.1f-point median gap" % gap)
        assert gap > 0

    def test_the_referee_s_never_exact_is_not_repeated(self, ledger, paper, supplement):
        """The referee's R2 said the recovery is 'never exact on the rejected ones'. It is
        exact on `recoveryFailExact` percent of them. Neither document may say otherwise."""
        assert float(ledger["recoveryFailExact"]) > 0.0
        for doc in (paper, supplement):
            flat = " ".join(doc.split())
            assert "never exact" not in flat

    def test_section_v_d_and_section_viii_b_now_agree(self, paper):
        """The reason this mattered beyond one clause: the Discussion's fourth rule cited a
        Results subsection that contradicted it."""
        i = paper.index("The displacement can be recovered rather than discarded")
        vd = " ".join(paper[i:i + 1400].split())
        assert BS + "recoveryShift" in vd and BS + "recoveryPassExact" in vd
        assert "holds where the check rejects as well as where it passes" in vd
        j = paper.index("Where the span cannot be re-timestamped")
        viiib = " ".join(paper[j:j + 500].split())
        assert "on the runs the check rejects as well as on those it passes" in viiib
        assert (BS + "ref{sec:cost}") in viiib, "the rule still cites Section V-D"
        assert (BS + "ref{sec:authors}") in vd, "and Section V-D now points back"

    def test_no_p_value_was_reached_for(self, paper, supplement):
        """Explicitly asked for. The manuscript's register is intervals and shifts, and a
        rank test between distributions that cross would have said nothing either way."""
        i = paper.index("The displacement can be recovered rather than discarded")
        vd = " ".join(paper[i:i + 1400].split())
        assert "Mann" not in vd and "$p$" not in vd and "p =" not in vd
        k = supplement.index("S16.9.")
        s169 = " ".join(supplement[k:k + 3600].split())
        assert "Mann" not in s169
        assert "rank test" in s169, "the supplement says why, rather than leaving a gap"

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        """Mutation, not inspection. Anchored on the claim across its line break, because
        round 75's own rewording moved the wrap and a literal anchor went stale the same
        afternoon it was written -- which is how nine of ten mutation anchors died in round
        72."""
        bad, n = re.subn(r"Those\s+medians\s+differ;\s+the\s+populations\s+do\s*\n?\s*not\.",
                         "they separate\nat the median, not in the upper tail.", paper)
        assert n == 1, "Section V-D has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_separation_claim_is_gone(bad)


class TestW1TheMonotonicClockIsNamedWhereItBelongs:

    def test_the_supplement_names_the_remedy(self, supplement):
        i = supplement.index("S16.6. The redesign that does not help")
        section = supplement[i:supplement.index("S16.7.")]
        flat = " ".join(section.split())
        assert "CLOCK" + BS + "_MONOTONIC" in flat, (
            "the remedy a systems reader reaches for first is still unnamed")
        assert "per-boot origin" in flat, "naming it without its cost invites it back"
        assert "scheduled first" in flat, (
            "the argument that defeats it is the one this section already makes")

    def test_the_main_text_did_not_pay_for_it(self, paper):
        """Eight rounds of declining to spend main-text space on the redesign question, and
        the referee asked for the supplement specifically: Section VIII-C is about BETTER
        clocks -- synchronization and resolution -- and a monotonic clock is neither."""
        i = paper.index("The limits of a better clock")
        section = paper[i:paper.index("Threats and limitations")]
        assert "MONOTONIC" not in section

    def test_the_exhibit_it_points_at_exists(self, supplement):
        assert "S25. The evidence behind the count of tools that dispose silently" \
            in supplement
        i = supplement.index("EndToEndLatency")
        assert "monotonic clock" in " ".join(supplement[i - 400:i + 400].split())


class TestW2TheRecoveryNumbersHaveASupplementHome:

    def test_the_section_exists(self, supplement):
        assert "S16.9. The displacement recovery, distribution by distribution" in supplement

    def test_every_recovery_macro_is_read_in_it(self, supplement, ledger):
        i = supplement.index("S16.9.")
        section = supplement[i:supplement.index("S17. The 1970 counter note")]
        missing = sorted(n for n in ledger
                         if n.startswith("recovery")
                         and not re.search(re.escape(BS + n) + r"(?![A-Za-z])", section))
        assert not missing, (
            "emitted, quoted in the main text, and with nowhere for a reader to check it: "
            "%s" % missing)

    def test_it_names_the_file_the_numbers_come_from(self, supplement):
        i = supplement.index("S16.9.")
        section = " ".join(supplement[i:i + 3600].split())
        assert "span" + BS + "_symmetry.csv" in section
        assert (REPO / "docs" / "results" / "span_symmetry.csv").is_file()

    def test_the_main_text_claim_and_the_supplement_agree_on_direction(self, supplement):
        i = supplement.index("S16.9.")
        section = " ".join(supplement[i:i + 3600].split())
        assert "the recovery holds\nwhere the check rejects".replace("\n", " ") in section


class TestW3TheRepeatedCountIsDeliberate:
    """No change asked for. Recorded so a later round does not delete one of the two."""

    def test_both_threes_come_from_one_macro(self, paper):
        assert paper.count(BS + "harnessDisposalClassesWord") == 2
        i = paper.index("Evidence Across Tools")
        section = paper[i:paper.index("Discussion")]
        assert "of the three classes" not in section
        assert "three classes" not in section.replace(
            BS + "harnessDisposalClassesWord{} classes", "")

    def test_they_are_close_enough_that_the_repetition_is_visible(self, paper):
        a = paper.index(BS + "harnessDisposalClassesWord")
        b = paper.index(BS + "harnessDisposalClassesWord", a + 1)
        assert b - a < 1200, (
            "the two uses have drifted out of one passage; the repetition was deliberate "
            "because they are the same quantity said twice from one source, and that reads "
            "as deliberate only while both are in view")


class TestTheRenderedPageCarriesIt:

    def test_the_index_terms_print_the_subject_words(self):
        flat = " ".join(_rendered("paper").split()).lower()
        for word in ("latency measurement", "timestamp resolution", "clock synchronization",
                     "benchmarking"):
            assert word in flat, word

    def test_the_shift_prints_in_section_v_d(self):
        flat = " ".join(_rendered("paper").split())
        assert "Hodges" in flat
        assert "separate at the median" not in flat

    def test_the_supplement_table_prints(self):
        flat = " ".join(_rendered("supplement").split())
        assert "Check accepts" in flat and "Check rejects" in flat
        assert "CLOCK_MONOTONIC" in flat.replace(" ", "") or "MONOTONIC" in flat
