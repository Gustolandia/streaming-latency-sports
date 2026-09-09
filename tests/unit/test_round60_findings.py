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
    return _flat("supplement.tex")


class TestR1TheSectionOpensOnItsEvidence:
    """A fork is a copy, so the count bounds divergence rather than adoption."""

    def test_the_tools_section_opens_on_the_audit(self, paper):
        body = paper.split(r"\section{Evidence Across Tools}", 1)[1]
        body = body.split(r"\section{", 1)[0]
        opening = body[:400]
        assert "forks" not in opening, (
            "Section VII opens on the fork count again. A fork is a copy: the number bounds "
            "how few have diverged, not how many adopted, and it is the weakest evidence in "
            "the section. The ten-tool audit is the claim.")
        assert "audited" in opening, \
            "Section VII no longer opens on the tool audit; say what replaced it"

    def test_the_fork_count_says_what_it_bounds(self, paper):
        """Kept, but not allowed back without its qualification."""
        i = paper.find(r"\forkUnchanged")
        assert i > 0, "the fork count has gone entirely; it is evidence, just not the opening"
        window = paper[i:i + 420]
        assert "diverged" in window, (
            "the fork count no longer says that it bounds divergence rather than adoption; "
            "without that clause it reads as a survey of independent uptake")


class TestR2AMedianTravelsWithItsSpread:
    """Commit 987e525: a remedy quoted by its median is a bound. So is a distortion."""

    def test_the_understatement_carries_denominator_and_interquartile_range(self, paper):
        i = paper.find(r"\understateFactor")
        assert i > 0, "the understatement factor has gone"
        window = paper[i:i + 460]
        for macro, why in ((r"\spanRatioConditions", "the denominator"),
                           (r"\understateIQRLo", "the lower interquartile bound"),
                           (r"\understateIQRHi", "the upper interquartile bound")):
            assert macro in window, (
                "the understatement is quoted without %s. The second author's annotation #42 "
                "requires experiment, denominator and uncertainty, and the median sits at the "
                "bottom of its own interquartile range." % why)

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

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
    @pytest.mark.parametrize("literal", QUARTET)
    def test_the_flip_quartet_is_not_typed(self, doc, literal):
        text = _flat(doc)
        # The generated table files are \input, so a value inside one is data, not a claim.
        assert ("$%s$" % literal) not in text, (
            "%s types %s again. It is emitted as a flip macro; a typed copy has the drift "
            "back, and `test_ledger_coverage` cannot see it because it only catches a "
            "literal that collides with a macro it already knows." % (doc, literal))

    def test_the_spread_says_points_and_the_pin_says_percent(self, paper):
        i = paper.find(r"\flipSpreadThirtyTwo")
        assert i > 0, "the payload flip no longer quotes its spread"
        window = paper[i:i + 420]
        assert "points" in window, \
            "the replicate spread is a range in percentage points and no longer says so"
        assert re.search(r"\\flipPinThirtyTwo\\%", window), \
            "the pin is a retention level in percent and no longer says so"

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
    Round 60 shipped exactly that into `supplement.tex`, and what caught it was
    `test_no_line_is_stretched_to_the_limit` -- a *typesetting* gate noticing that the
    paragraph would not set, several steps downstream of the cause. `docs/infrastructure.md`
    has recorded this failure mode since round 40 as item 1aa, "a backslash the shell ate
    compiles cleanly and prints a word", and it kept happening because nothing looked.

    Tab and newline are the only control characters a LaTeX source has any use for.
    """

    ALLOWED = {"\t", "\n", "\r"}

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
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
