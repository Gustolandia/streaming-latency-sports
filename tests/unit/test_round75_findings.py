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
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


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


def _section_iii_d(paper):
    """Section III-D, "What it costs, and the repair": v4's Section V-D, as source."""
    i = paper.index(BS + "label{sec:cost}")
    return paper[i:paper.index(BS + "section{", i)]


def _recovery(paper):
    """The recovery paragraph of Section III-D, flattened.

    v5 (28 Sep): v4's "The displacement can be recovered rather than discarded" paragraph is
    the last of Section III-D. Its opening sentence did not survive the rewrite, so it is found
    by what it prints, both populations' median errors, rather than by how it begins."""
    paras = [p for p in re.split(r"\n\s*\n", _section_iii_d(paper))
             if BS + "recoveryErrPass" in p and BS + "recoveryErrFail" in p]
    assert len(paras) == 1, "Section III-D's recovery paragraph has moved; retarget this pin"
    return " ".join(paras[0].split())


def _s169(supplement):
    i = supplement.index("S16.9.")
    return " ".join(supplement[i:supplement.index("S17. The 1970 counter note")].split())


def _checks_row(paper, words):
    """The row of Table IV (the checks that cost nothing) whose text contains `words`."""
    i = paper.index(BS + "label{tab:checks}")
    table = paper[i:paper.index(BS + "end{tabular}", i)]
    rows = [" ".join(r.split()) for r in table.split(BS + BS) if words in " ".join(r.split())]
    assert len(rows) == 1, "Table IV has been reworded; retarget this pin"
    return rows[0]


class TestR1TheIndexTermsNameTheirOwnSubject:
    r"""The retrieval surface, read rather than sorted."""

    #: Words the paper is about, each drawn from the title or from a section heading, with
    #: where it comes from. A term list that contains none of these describes another paper.
    #: Matched as a prefix so *benchmark* covers *benchmarking* and *clock* covers
    #: *clock synchronization*.
    #:
    #: 5 Oct 2026: re-derived for the rebuilt paper, whose title is "Super-Precise Latency:
    #: How CPU Threading Affects High-Precision Latency, and an Industry-Wide Audit".
    #: "measurement" was the old title's noun and left with it and with the term "measurement
    #: errors"; "clock" was the old Section IV-C's and left with the term "clock
    #: synchronization", both dropped from the index terms in the rebuild. "thread" and
    #: "audit" are the new title's nouns.
    SUBJECT_WORDS = {
        "latency": "the title's own noun",
        "thread": "the title's own noun, CPU threading, which the mechanism is about",
        "audit": "the title's own noun, the industry-wide audit of Section V",
        "benchmark": "the population Section V audits, and the abstract's latency benchmarks",
        "timestamp": "Section II, how a message is timed, and Section V-C's millisecond clock: "
                     "what a timestamp marks is the paper's subject",
        "scheduling": "Section IV's mechanism, a thread's wait for a core, and its slice",
        # "stream" until 1 Oct 2026: the v5 title says "message-broker", and an outside editor
        # noted that "streaming" points this journal's readers at stream-processing engines.
        "broker": "the abstract's own noun, and the whole population under audit",
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
                 # 4 Oct 2026: "silent" and "choose", the v7 title's adjective and verb.
                 # 5 Oct 2026: the rebuilt title's adjectives and verb, "super-precise" and
                 # "affects", and the first halves of its compound adjectives,
                 # "high-precision" and "industry-wide"; its nouns are latency, threading and
                 # audit.
                 if w not in ("faster", "light", "artifacts", "silent", "choose",
                              "super", "precise", "affects", "precision", "industry")]
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


#: 5 Oct 2026: the rebuilt paper's recovery paragraph (Section VI-B, label sec:cost) prints
#: both populations' median errors over their counts and both upper quartiles, and claims
#: neither a separation nor a sameness; the mutations below put each claim back after the
#: last of its numbers.
RECOVERY_END = r"\$" + re.escape(BS) + r"recoveryErrFailHi" + re.escape(BS) + r"%\$"


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
        # 7 Oct 2026: leaving out the late messages parted the two maxima by two points, 38
        # and 36, and S16.9 now says the worst conditions lie within two points of each other.
        assert abs(float(ledger["recoveryPassMax"]) - float(ledger["recoveryFailMax"])) <= 2, (
            "S16.9 says the worst conditions lie within two points of each other; if they "
            "part further the sentence is false")

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

    def test_section_v_d_and_section_viii_b_now_agree(self, paper, supplement):
        """The reason this mattered beyond one clause: the Discussion's fourth rule cited a
        Results subsection that contradicted it.

        v5 (28 Sep): V-D is Section III-D and the Discussion's rules are Table IV. An outside
        editor asked for V-D's Hodges--Lehmann and bootstrap sentences to go to the supplement,
        one sentence of result kept (editorial review, Section 5 and Section 7, row 12), so the
        shift, the non-zero shift and the statement that no shift is detectable are pinned in
        S16.9, where they now are, and III-D is held to the sentence it kept: both populations'
        errors, a statement of what the data cannot separate, and the pointer to S16.9. The
        rule is Table IV's add-back row, which cites III-D and restates nothing III-D could
        contradict. III-D's own pointer forward to the rule went with the list of rules and is
        not asked for.

        29 Sep: the pointer lands on the journal supplement's S3.8, which states the shift and
        its non-zero form too; it is found there by the shift. S16.9 is the postmortem's.

        5 Oct 2026: the rebuilt paper keeps the recovery as Section VI-B's paragraph, which
        prints both median errors over their counts and both upper quartiles, 20% and 19%,
        the numbers that show the tails agree, and draws no inference over them. The kept
        sentence "the data cannot tell apart" and its pointer to the shift were cut, and the
        journal supplement no longer carries the shift; S16.9 of the postmortem does. Held:
        both populations described alike, no separation or sameness claimed, S16.9 as before,
        and the table of checks quoting only numbers the paragraph prints, so the two cannot
        disagree."""
        vd = _recovery(paper)
        for macro in ("recoveryErrPass", "recoveryErrFail", "recoveryPassN", "recoveryFailN",
                      "recoveryErrPassHi", "recoveryErrFailHi"):
            assert re.search(re.escape(BS + macro) + r"(?![A-Za-z])", vd), macro
        for claim in ("separate", "do not differ", "indistinguishable", "no shift remains",
                      "the populations do not"):
            assert claim not in vd, claim
        s169 = _s169(supplement)
        assert BS + "recoveryShift$" in s169
        # Round 76 replaced the one-sided quote of `recoveryPassExact` here. It read "33% of
        # the passing conditions recover the delivery exactly", which invites the inference
        # that the rejected ones never do -- the error round 75's own report made in prose.
        # What stands in its place is the crossing of the two medians with the exact
        # recoveries removed, which is both two-sided and a stronger statement.
        # Round 77 (R1) then replaced that crossing with the shift on the non-zero populations,
        # which is 0.0: the medians still cross, but a crossing of medians is the same artifact
        # as the gap round 75 corrected, so the main text states the shift and S16.9 keeps the
        # medians as description. Round 78 (R1) reworded "no shift remains", a claim of
        # equivalence, to "no shift is detectable", which is what the interval supports; S16.9
        # words it "no shift can be detected".
        assert BS + "recoveryNonzeroShift$" in s169 and "no shift can be detected" in s169
        assert "the recovery holds where the check rejects as well as where it passes" in s169
        row = _checks_row(paper, "add it back")
        quoted = set(re.findall(re.escape(BS) + r"(recovery\w+)", row))
        assert quoted, "the add-back row no longer says what the recovery buys"
        assert quoted <= set(re.findall(re.escape(BS) + r"(recovery\w+)", vd)), (
            "the add-back row quotes a recovery number the paragraph does not print: %s"
            % sorted(quoted - set(re.findall(re.escape(BS) + r"(recovery\w+)", vd))))
        for claim in ("separate", "do not differ", "indistinguishable"):
            assert claim not in row, claim

    def test_no_p_value_was_reached_for(self, paper, supplement):
        """Explicitly asked for. The manuscript's register is intervals and shifts, and a
        rank test between distributions that cross would have said nothing either way.

        v5 (28 Sep): V-D is Section III-D, and the whole subsection is read, which covers the
        recovery paragraph wherever its sentences now begin."""
        vd = " ".join(_section_iii_d(paper).split())
        assert "Mann" not in vd and "$p$" not in vd and "p =" not in vd
        k = supplement.index("S16.9.")
        s169 = " ".join(supplement[k:supplement.index("S17. The 1970 counter note")].split())
        # What round 75 ruled out was a RANK test standing in for the shift: Mann-Whitney
        # tests dominance between distributions that cross, so a large p would have carried
        # no information about whether the populations agree. That still holds and is still
        # gated. Round 76's Kolmogorov-Smirnov p is not the same object and was asked for by
        # the referee in the same breath as the intervals: it answers a question the shift
        # cannot -- whether the two distributions differ in SHAPE -- and it is an addition to
        # the shift rather than a substitute for it. Both are pinned here so a later round
        # can see which was excluded and why.
        assert "Mann" not in s169 and "Wilcoxon" not in s169
        assert "rank test" in s169, "the supplement says why, rather than leaving a gap"
        assert "Kolmogorov" in s169 and BS + "recoveryKsD" in supplement

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        """Mutation, not inspection. Anchored on the claim across its line break, because
        round 75's own rewording moved the wrap and a literal anchor went stale the same
        afternoon it was written -- which is how nine of ten mutation anchors died in round
        72."""
        # Round 78 (R1) changed "the populations do not" to "cannot be told apart"; the
        # anchor followed it, and still spans the line break by construction.
        # v5 (28 Sep): Section III-D's kept sentence says "two populations the data cannot tell
        # apart"; the anchor is that clause, in either of the two wordings round 78 allows, and
        # the separation claim is put in its place.
        # 5 Oct 2026: that sentence was cut; the claim is put back after the last of the
        # rebuilt paragraph's numbers (`RECOVERY_END`), and both gates must fire on it.
        bad, n = re.subn(RECOVERY_END,
                         lambda m: m.group(0) + ", so they separate\nat the median, not in the "
                         "upper tail", paper)
        assert n == 1, "Section VI-B has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_separation_claim_is_gone(bad)
        with pytest.raises(AssertionError):
            self.test_section_v_d_and_section_viii_b_now_agree(bad, (REPO / "postmortem.tex")
                                                              .read_text(encoding="utf-8"))


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
        clocks -- synchronization and resolution -- and a monotonic clock is neither.

        v5 (28 Sep): Section VIII-C is now the paragraph of Section VI labeled `sec:betterclock`,
        which runs to the broker paragraph labeled `sec:brokers`.

        5 Oct 2026: the rebuilt paper has neither label; the paragraph is Section VI's last,
        "A better-synchronized clock repairs neither ...", and runs to Related Work. The whole
        paper is held too, since it names no clock source at all."""
        i = paper.index(BS + "label{sec:practice}")
        j = paper.index("A better-synchronized clock repairs neither", i)
        section = paper[j:paper.index(BS + "section{", j)]
        assert "better-synchronized clock" in section, "the paragraph has moved; retarget this pin"
        assert "MONOTONIC" not in section
        assert "MONOTONIC" not in re.sub(r"(?m)^%[^\n]*", "", paper)

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
        # Bounded by the next section rather than by a character count: round 76 grew S16.9
        # past the 3,600-character window this used, and a window that silently stops short
        # of the sentence it is checking reports success for the wrong reason.
        section = " ".join(supplement[i:supplement.index("S17. The 1970 counter note")].split())
        assert "the recovery holds where the check rejects" in section


class TestW3TheRepeatedCountIsDeliberate:
    """No change asked for. Recorded so a later round does not delete one of the two.

    v5 (28 Sep): the rewrite said it once. Section VII is Section V, rebuilt around Table III
    at an outside editor's request (editorial review, Sections 5 and 9), and its paragraph now
    lists the classes by name in the sentence that counts them, with "Substitution is the
    worst" directly after, so the superlative no longer needs a count of its own. What the two
    tests below pin is that single use: from the macro, with no typed "three" in the place of
    the second, and in view of the sentence that ranks the classes."""

    def test_both_threes_come_from_one_macro(self, paper):
        """v5 (28 Sep): one use, not two; the count dropped because the second use was
        rewritten out with the superlative's clause, not because a typed word replaced it.

        5 Oct 2026: the rebuilt sentence counts "ways" where v5 counted "classes", and the
        typed count is refused under either noun."""
        assert paper.count(BS + "harnessDisposalClassesWord") == 1
        i = paper.index(BS + "label{sec:tools}")
        section = paper[i:paper.index(BS + "section{", i)]
        assert BS + "harnessDisposalClassesWord" in section
        assert "of the three classes" not in section and "of the three ways" not in section
        rest = section.replace(BS + "harnessDisposalClassesWord{} classes", "").replace(
            BS + "harnessDisposalClassesWord{} ways", "")
        assert "three classes" not in rest and "three ways" not in rest

    def test_they_are_close_enough_that_the_repetition_is_visible(self, paper):
        """v5 (28 Sep): with the count said once, what must stay in view of it is the sentence
        that ranks within it, so the distance is now from the count to the superlative.

        5 Oct 2026: the superlative reads "Replacement hides best" in the rebuilt Section V-A."""
        a = paper.index(BS + "harnessDisposalClassesWord")
        b = paper.index("Replacement hides best", a)
        assert b - a < 1200, (
            "the count and the superlative that ranks within it have drifted out of one "
            "passage; 'hides best' reads against the count only while both are in view")


class TestTheRenderedPageCarriesIt:

    def test_the_index_terms_print_the_subject_words(self, paper):
        """5 Oct 2026: read on the Index Terms line itself, de-hyphenated, rather than anywhere
        on the pages, where the references alone printed "clock synchronization" once the
        index terms no longer did; every term the source lists prints there."""
        flat = " ".join(_rendered("paper").split())
        i = flat.index("Index Terms")
        line = re.sub(r"(\w)- (\w)", r"\1\2", flat[i:flat.index("INTRODUCTION", i)]).lower()
        for term in _index_terms(paper):
            assert term.lower() in line, term

    def test_the_shift_prints_in_section_v_d(self):
        """v5 (28 Sep): the shift went to S16.9 with the rest of V-D's statistics (editorial
        review, Section 5), so it is looked for on S16.9's pages; the separation claim is
        refused in both documents.

        29 Sep: S16.9's pages are the postmortem's, and the paper points at the journal
        supplement's S3.8, so the shift is looked for on both; the claim is refused in all three.

        5 Oct 2026: the journal supplement no longer carries the recovery (its S3.8 is the
        receiving thread's wait), so the shift is looked for on S16.9's pages alone; the claim
        is still refused in all three documents."""
        flat = " ".join(_rendered("paper").split())
        post = _rendered("postmortem")
        s169 = " ".join(post[post.rindex("S16.9. The displacement recovery"):
                             post.rindex("S16.10. How late")].split())
        assert "Hodges" in s169
        journal = _rendered("supplement")
        assert "separate at the median" not in flat
        for supp in (post, journal):
            assert "separate at the median" not in " ".join(supp.split())

    def test_the_supplement_table_prints(self):
        """5 Oct 2026: the recovery table and the monotonic-clock remedy are the postmortem's
        (S16.9 and S16.6), so their pages are read from postmortem.pdf."""
        flat = " ".join(_rendered("postmortem").split())
        assert "Check accepts" in flat and "Check rejects" in flat
        assert "CLOCK_MONOTONIC" in flat.replace(" ", "")
