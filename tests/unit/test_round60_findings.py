"""Round 60's five findings, each with the gate that would have caught it.

The referee's own summary of R2 is the shape of every item here: *"the fix is ten lines in the
emitter"*. Four of the five were repairable in the pipeline and are; the fifth, R1, is an
ordering of two paragraphs and is pinned as prose.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent


def _flat(name):
    text = (REPO / name).read_text(encoding="utf-8")
    text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    return " ".join(text.split())


@pytest.fixture(scope="module")
def paper():
    return _flat("paper.tex")


@pytest.fixture(scope="module")
def supplement():
    return _flat("postmortem.tex")


class TestR1TheSectionOpensOnItsEvidence:
    """A fork is a copy, so the count bounds divergence rather than adoption."""

    def test_the_tools_section_opens_on_the_audit(self, paper):
        """v5 (28 Sep): the section is Section V, "How Widespread", and its second sentence says
        "We read ten tools at source" where v4 said "We audited", so the pin is on that clause
        (macro and all) rather than on the verb.

        v6 (2 Oct): the section became Section V-E, "Ten tools, read at source", inside the
        industry's section; its opening is unchanged and so is the pin.

        5 Oct 2026: the rebuilt paper's Section V, "An Industry-Wide Audit", opens on the four
        studies, the tools read at source first, and its subsection V-A, "Tools read at
        source", opens "We read ten measurement tools at source". Both openings are held: no
        fork count, and the tool audit stated with its macro."""
        section = paper.split(r"\section{An Industry-Wide Audit}", 1)[1]
        section = section.split(r"\section{", 1)[0]
        body = section.split(r"\subsection{Tools read at source}", 1)[1]
        for name, opening in (("Section V", section[:400]), ("Section V-A", body[:400])):
            assert "forks" not in opening, (
                "%s opens on the fork count again. A fork is a copy: the number bounds how few "
                "have diverged, not how many adopted, and it is the weakest evidence in the "
                "section. The ten-tool audit is the claim." % name)
            assert re.search(r"\\harnessAuditedWord\{\} (?:measurement )?tools at source",
                             opening), \
                "%s no longer opens on the tool audit; say what replaced it" % name

    def test_the_fork_count_says_what_it_bounds(self, paper, supplement):
        """Kept, but not allowed back without its qualification.

        v5 (28 Sep): the fork count left the paper with the editor's cuts (section 5, "the fork
        count") and now opens Supplement S25's paragraph on forks, qualification included. It
        is pinned there, and it may not come back to the paper without the clause either.
        """
        i = supplement.find(r"\forkUnchanged")
        assert i > 0, "the fork count has gone entirely; it is evidence, just not the opening"
        window = supplement[i:i + 420]
        assert "diverged" in window, (
            "the fork count no longer says that it bounds divergence rather than adoption; "
            "without that clause it reads as a survey of independent uptake")
        j = paper.find(r"\forkUnchanged")
        if j >= 0:
            assert "diverged" in paper[j:j + 420], (
                "the fork count is back in the paper without the clause saying it bounds "
                "divergence rather than adoption")


class TestR2AMedianTravelsWithItsSpread:
    """Commit ff36e86: a remedy quoted by its median is a bound. So is a distortion."""

    def test_the_understatement_carries_denominator_and_interquartile_range(self, paper):
        """5 Oct 2026: the rebuilt paper quotes the factor twice, in a cell of the table of
        checks, which points at the figure, and in Section VI-B's sentence, which now names
        its denominator before the factor ("Over our N conditions, S understates ...") and its
        interquartile range after it. So the window is the sentence, on both sides of the
        factor, and every quote in running text is held to it. The table's cell, a summary
        that sends the reader to the figure and sits a column from this sentence, is not."""
        prose = re.sub(r"\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}", " ", paper)
        hits = [m.start() for m in re.finditer(r"\\understateFactor(?![A-Za-z])", prose)]
        assert hits, "the understatement factor has gone from the running text"
        for i in hits:
            start = prose.rfind(". ", 0, i) + 2
            end = prose.find(". ", i)
            sentence = prose[start:end if end > 0 else len(prose)]
            for macro, why in ((r"\spanRatioConditions", "the denominator"),
                               (r"\understateIQRLo", "the lower interquartile bound"),
                               (r"\understateIQRHi", "the upper interquartile bound")):
                assert macro in sentence, (
                    "the understatement is quoted without %s. The second author's annotation "
                    "#42 requires experiment, denominator and uncertainty, and the median sits "
                    "at the bottom of its own interquartile range: %r" % (why, sentence[:200]))

    def test_the_median_really_does_sit_low_in_its_range(self):
        """The reason the sentence needs the spread, checked against the ledger.

        If a recomputation ever moves the median into the middle of its range this test
        fails, and the sentence should be rewritten rather than the test deleted: the claim
        "half of them are worse than the headline" would have stopped being interesting.
        """
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")

        def val(name):
            m = re.search(r"\\newcommand\{\\%s\}\{([0-9.]+)\}" % name, gen)
            assert m, "%s is not emitted" % name
            return float(m.group(1))

        med, lo, hi = val("understateFactor"), val("understateIQRLo"), val("understateIQRHi")
        assert lo <= med <= hi, "the median is outside its own interquartile range"
        assert med - lo < hi - med, (
            "the median no longer sits in the lower half of the interquartile range, so "
            "'half of them are worse than the headline' has lost its force")


class TestW1ASectionTitleIsTheOnlyIndexTheSupplementHas:
    """Three of the most-cited sections were titled for one of the things they hold."""

    #: figure stem -> a word its section's title must carry, because the main text sends a
    #: reader to that section by name for that figure's subject.
    TITLED = {
        "exposure_curve": "exposure",
        "deletion_histogram": "deletes",
        "quantum_geometry": "geometry",
    }

    @pytest.mark.parametrize("stem", sorted(TITLED))
    def test_the_section_holding_it_says_so_in_its_title(self, stem, supplement):
        i = supplement.find(stem)
        assert i > 0, "%s is no longer included" % stem
        titles = re.findall(r"\\section\{(S\d+[^}]*)\}", supplement[:i])
        assert titles, "%s sits before the first section" % stem
        assert self.TITLED[stem] in titles[-1].lower(), (
            "%s sits in %r, whose title does not mention it. The supplement has no list of "
            "figures, so the title is the reader's only index, and the main text sends a "
            "reader here by section number." % (stem, titles[-1]))


class TestW2NumbersComeFromTheLedgerAndCarryTheirUnits:
    """Four typed literals in two documents, in two units, invisible to the ledger gate."""

    QUARTET = ("13.6", "26.7", "69.2", "66.67")

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex", "postmortem.tex"])
    @pytest.mark.parametrize("literal", QUARTET)
    def test_the_flip_quartet_is_not_typed(self, doc, literal):
        text = _flat(doc)
        # The generated table files are \input, so a value inside one is data, not a claim.
        assert ("$%s$" % literal) not in text, (
            "%s types %s again. It is emitted as a flip macro; a typed copy has the drift "
            "back, and `test_ledger_coverage` cannot see it because it only catches a "
            "literal that collides with a macro it already knows." % (doc, literal))

    def test_the_spread_says_points_and_the_pin_says_percent(self, paper):
        """5 Oct 2026: the payload flip's spread is the journal supplement's now (S4.3), and
        the paper keeps only the failed detail, the 32 KB pin, in Section VIII. The spread is
        held where it is printed, and the pin in both documents."""
        journal = _flat("supplement.tex")
        i = journal.find(r"\flipSpreadThirtyTwo")
        assert i > 0, "the payload flip no longer quotes its spread"
        window = journal[i:i + 420]
        assert "points" in window, \
            "the replicate spread is a range in percentage points and no longer says so"
        assert re.search(r"\\flipPinThirtyTwo\\%", window), \
            "the pin is a retention level in percent and no longer says so"
        pins = [m.end() for m in re.finditer(r"\\flipPinThirtyTwo(?![A-Za-z])", paper)]
        assert pins, "the paper no longer states the failed detail of the flip"
        for j in pins:
            assert paper[j:j + 2] == "\\%", \
                "the paper prints the pin without saying it is a retention level in percent"

    def test_the_figure_and_the_prose_read_one_function(self):
        src = (REPO / "scripts" / "make_result_figures.py").read_text(encoding="utf-8")
        body = src[src.index("def payload_arms"):]
        body = body[:body.index("\ndef ", 1)]
        assert "stat_intervals.payload_flip_replicates" in body, (
            "the payload figure derives its own replicates again; it and the two documents "
            "quoting them must read one function")


class TestNoSourceCarriesAControlCharacter:
    r"""The recurring shell bug, finally gated.

    A shell heredoc interprets backslash escapes in the string it is passed, so a patch
    carrying `\flipVertexTwoThirds` arrives as a formfeed followed by `lipVertexTwoThirds`.
    Round 60 shipped exactly that into `postmortem.tex`, and what caught it was
    `test_no_line_is_stretched_to_the_limit` -- a *typesetting* gate noticing that the
    paragraph would not set, several steps downstream of the cause. `docs/infrastructure.md`
    has recorded this failure mode since round 40 as item 1aa, "a backslash the shell ate
    compiles cleanly and prints a word", and it kept happening because nothing looked.

    Tab and newline are the only control characters a LaTeX source has any use for.
    """

    ALLOWED = {"\t", "\n", "\r"}

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex", "postmortem.tex"])
    def test_the_document_holds_no_control_characters(self, doc):
        text = (REPO / doc).read_text(encoding="utf-8")
        bad = []
        for i, ch in enumerate(text):
            if ch < " " and ch not in self.ALLOWED:
                line = text.count("\n", 0, i) + 1
                bad.append((line, hex(ord(ch)), repr(text[max(0, i - 30):i + 30])))
        assert not bad, (
            "%s carries control character(s) no LaTeX source needs -- almost always a "
            "backslash a shell heredoc ate, which compiles and prints the rest of the "
            "macro name as a word: %s" % (doc, bad[:3]))

    def test_the_rule_can_fail(self):
        """The round-60 corruption itself, so the check cannot be loosened blind."""
        corrupted = "shows.\n$\x0clipVertexTwoThirds\\%$ is $2/3$"
        assert any(ch < " " and ch not in self.ALLOWED for ch in corrupted)
        assert not any(ch < " " and ch not in self.ALLOWED
                       for ch in corrupted.replace("\x0c", "\\f"))


class TestW3APercentageStatesWhatItIsOver:
    """Section IV-F promises 'a count over a stated denominator'. Table I did not state it."""

    def test_the_per_broker_percentages_carry_their_denominators(self, paper):
        i = paper.find(r"\spanKafkaNegAckPct")
        assert i > 0, "Table I no longer quotes the per-broker rate"
        window = paper[i:i + 300]
        for macro in (r"\spanKafkaEvents", r"\spanRedisEvents"):
            assert macro in window, (
                "Table I's caption quotes a percentage whose denominator is not stated, "
                "against Section IV-F's own rule. %s already exists." % macro)
