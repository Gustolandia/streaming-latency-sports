"""Round 61's findings, each with the gate that would have caught it.

The interesting one is W1. Round 60 promoted a paragraph to fix a real defect, and the
paragraph it promoted had been written to sit second -- so the section came to open on a
connective about the *previous* section. Nothing looked, because the Feynman rule ("a section
opens on its claim") had been a writing standard and never a test. It is one now.
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


class TestASectionOpensOnItsOwnClaim:
    r"""The Feynman rule, tested rather than merely written down.

    A section's first sentence may not be *about the previous section*. That is the shape
    round 61 found in Section VII --- "Deletion is not the only way coarse resolution wins",
    which says what Section VI was --- and it is a shape a regular expression can recognise
    even though "opens on its claim" in general is not.

    Section II is exempt and the exemption is deliberate: it opens on a description because
    it holds the definitions, which a co-author required, and a definitions section that
    opened on a claim would be worse. That is a decision, so it is named here rather than
    silently accommodated by a looser rule.
    """

    #: Openers that describe what came before instead of what follows.
    BACKWARD = re.compile(
        r"^\s*(?:"
        r"(?:Deletion|That|This|These|Those|It|They)\s+is\s+not\s+the\s+only|"
        r"(?:But|However|Nevertheless|Nonetheless|Conversely)\b|"
        r"(?:The\s+)?(?:above|foregoing|preceding|previous)\b|"
        r"So\s+far\b|"
        r"Having\b"
        r")", re.I)

    EXEMPT = {"System and Measurement Model"}

    def _sections(self, paper):
        out = []
        for m in re.finditer(r"\\section\{([^}]*)\}", paper):
            start = m.end()
            nxt = paper.find(r"\section{", start)
            body = paper[start:nxt if nxt > 0 else len(paper)]
            body = re.sub(r"\\label\{[^}]*\}", " ", body)
            body = re.sub(r"\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}", " ", body)
            body = re.sub(r"\\IEEEPARstart\{(.)\}\{([^}]*)\}", r"\1\2", body)
            out.append((m.group(1), " ".join(body.split())))
        return out

    def test_the_extractor_finds_the_sections(self, paper):
        names = [n for n, _ in self._sections(paper)]
        assert len(names) >= 8, "only %d sections found: %s" % (len(names), names)

    def test_no_section_opens_on_the_previous_one(self, paper):
        bad = []
        for name, body in self._sections(paper):
            if name in self.EXEMPT:
                continue
            first = body.split(". ", 1)[0][:160]
            if self.BACKWARD.match(first):
                bad.append((name, first))
        assert not bad, (
            "section(s) opening on a sentence about what came before, where this paper's "
            "convention puts the section's own claim: %s" % bad)

    def test_the_rule_can_fail(self):
        """Round 61's actual defect, pinned, so the pattern cannot be loosened blind."""
        assert self.BACKWARD.match("Deletion is not the only way coarse resolution wins.")
        assert self.BACKWARD.match("However, the tools differ.")
        assert not self.BACKWARD.match(
            "The disposal is a pattern across the tooling rather than one project's oversight.")
        assert not self.BACKWARD.match(
            "The negatives in our own corpus are produced by scheduling.")

    def test_the_tools_section_still_makes_the_hinge_do_its_work(self, paper):
        """The hinge was not deleted, it was moved back against the case it introduces."""
        i = paper.find("Deletion is not the only way")
        assert i > 0, "the hinge sentence has gone; it introduces the integer-division case"
        assert "integer division" in paper[i:i + 400], (
            "'Deletion is not the only way coarse resolution wins' has drifted away from the "
            "case it introduces, which is the tool that keeps every sample and divides")


class TestAMedianTravelsWithItsSpread:
    """W2: the spread belongs to the quantity, not to the sample it was taken over."""

    def test_the_interquartile_range_is_not_a_property_of_the_conditions(self, paper):
        i = paper.find(r"\spanRatioConditions")
        assert i > 0, "the denominator has gone"
        window = paper[i:i + 320]
        assert "conditions whose interquartile" not in window, (
            "the interquartile range is hung off 'conditions' again; the range belongs to "
            "the understatement, and the worst case belongs to a condition")
        assert "the worst condition reaches" in window, \
            "the worst case no longer says which thing reaches it"


class TestTheLiteratureCensusIsDerivedNotRemembered:
    """W1's evidence, and an older claim of the same shape that nothing had checked."""

    #: (macro, the supplement sentence it must appear in)
    QUOTED = (
        (r"\surveyLatencyMentions", "survey"),
        # Not `surveyTimestampMentions`: the sentence says the three absent words "occur
        # never" rather than "occur 0 times", so what it quotes is `surveyAbsentTimes`, the
        # prose form of their combined count. The raw per-term counts stay in the census.
        (r"\surveyAbsentTimes", "survey"),
        (r"\surveyBenchmarkMentions", "survey"),
        (r"\surveyPages", "survey"),
        (r"\playbookPages", "playbook"),
        (r"\playbookClockTimes", "playbook"),
    )

    @pytest.mark.parametrize("macro,_which", QUOTED)
    def test_the_supplement_reads_the_census(self, macro, _which, supplement):
        assert macro in supplement, (
            "%s is emitted but the supplement does not quote it; a census nobody reads is a "
            "census that stops being checked" % macro)

    def test_no_absence_claim_types_its_own_page_count(self, supplement):
        """The shape of the defect: a claim about a corpus with the number written by hand."""
        assert "Over thirty-one pages" not in supplement, (
            "S52.4 types its page count again. It is emitted, and `_spell`'s own rule is that "
            "above twelve IEEE style takes the digits back.")

    def test_the_census_record_is_committed(self):
        rec = REPO / "docs" / "results" / "external" / "literature_census.csv"
        assert rec.exists(), (
            "the census record is missing; docs/reference_tc is gitignored, so the committed "
            "CSV is the only thing that lets a build off this machine emit these numbers")
        body = rec.read_text(encoding="utf-8")
        assert "yue2024streamsurvey" in body and "krishnamachari2026playbook" in body


class TestTheSupplementIndexesItsExhibits:
    """W3: forty exhibits over fifty-six pages, and a contents list that named none of them."""

    def test_it_lists_its_figures_and_tables(self, supplement):
        for macro in (r"\listoffigures", r"\listoftables"):
            assert macro in supplement, (
                "the supplement dropped %s. It carries 13 figures and 27 tables over 56 pages "
                "with no page limit, and a reader who remembers an exhibit but not its "
                "section has only the section titles to go on." % macro)


class TestThePromiseNamesWhoKeepsIt:
    """W3b: Section IV-F promised a corrected value that its own two tables do not display."""

    def test_the_holm_promise_says_which_tables(self, paper):
        i = paper.find("Holm correction is applied")
        assert i > 0, "the Holm sentence has gone"
        window = paper[i:i + 220]
        assert "supplement's tables" in window, (
            "Section IV-F promises that 'the tables' display the corrected value, in a "
            "document whose own two tables display counts, rates and z. The p_Holm column "
            "is in the supplement.")


class TestEveryCaptionParserReadsBothForms:
    r"""`\caption[short]{long}` is standard LaTeX, and nine parsers here could not read it.

    The supplement's list of forty exhibits is an index only if its entries are the exhibits'
    claims rather than their whole captions, so each caption gained the short form its own
    opening sentence provides. Every parser in the project looked for the literal `\caption{`,
    which `\caption[...]{...}` does not contain, and seven gates failed or errored at once --
    loudly, because each asserts on caption *content*, so a parser that walks past a caption
    finds either nothing or text that does not match.

    This is the gate that stops the tenth parser being written the same way.
    """

    #: A parser may not look for the plain form without also allowing the optional argument.
    #: Both spellings the sources use: `r"\caption{"` inside a raw string, and `"\\caption{"`
    #: or `r"\\caption\{"` inside a regex, where the brace may itself be escaped.
    BLIND = re.compile(r"""r?["']\\{1,2}caption\\?\{""")

    def _sources(self):
        for d in ("tests/unit", "scripts"):
            for path in sorted((REPO / d).glob("*.py")):
                if path.name == "test_round61_findings.py":
                    continue
                yield path

    #: What makes a line a *lookup* rather than a fixture. A caption literal that is only
    #: test data --- a sample caption a rule is exercised against --- is not a parser and
    #: must not be flagged; a caption literal handed to a search is.
    LOOKUP = ("re.search", "re.finditer", "re.match", "re.split",
              ".index(", ".rindex(", ".find(")

    def test_no_parser_matches_only_the_plain_form(self):
        bad = []
        for path in self._sources():
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if not (self.BLIND.search(line) and any(k in line for k in self.LOOKUP)):
                    continue
                # The short form may be handled on a neighboring line of the same statement,
                # which is how the two `rindex` sites take the later of the two positions.
                near = " ".join(lines[max(0, i - 3):i + 2])
                if "caption[" in near or "caption(?:" in near:
                    continue
                bad.append("%s:%d  %s" % (path.name, i, line.strip()[:90]))
        assert not bad, (
            r"parser(s) looking for the literal `\caption{`, which does not appear in "
            r"`\caption[short]{long}`. The supplement uses the short form on 35 of its 40 "
            "captions, so such a parser reads a neighboring caption or none:\n  "
            + "\n  ".join(bad))

    def test_the_rule_can_fail(self):
        assert self.BLIND.search(r'cap = re.search(r"\caption\{", block)')
        assert not self.BLIND.search(r'cap = re.search(r"\caption(?:\[[^\]]*\])?\{", block)')

    def test_the_supplement_really_does_use_the_short_form(self, supplement):
        """If the short captions are ever backed out, this gate stops being load-bearing."""
        assert supplement.count(r"\caption[") >= 30, (
            "the supplement no longer uses short captions; if that was deliberate, retire "
            "this class rather than leaving it passing vacuously")



class TestACapitalisedMacroOpensASentence:
    r"""Lesson 12 in reverse, and round 61 produced the reverse itself.

    The `Word`/`WordCap` pairs exist so a generated number can open a sentence:
    `\harnessSilentWord` is "five" and `\harnessSilentWordCap` is "Five". Round 43 found the
    lower-case twin at the head of a sentence, and the project has watched that direction ever
    since.

    Nothing watched the other one. Round 61's reordering of Section VII joined two clauses with
    a semicolon and left `\harnessSilentWordCap{}` sitting after it, so the built page read
    "...classified the benchmark; Five of the ten dispose...". Visible only in the render, and
    only to someone looking at the page rather than at the source --- which is lesson 11's
    class, found again from the other end.
    """

    #: What may stand immediately before a capitalised word macro: a sentence end, a colon,
    #: an em dash, a list item, or the opening brace of a caption or cell.
    #: No empty string here. It was in the first draft, to stand for "start of text", and it
    #: made `endswith` true for every input --- a rule that could not fail, which its own
    #: negative example caught immediately. Start of text is handled as start of text.
    OPENER = (".", "!", "?", ":", "---", "{", "}", r"\item", r"\par")

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
    def test_no_capitalised_macro_sits_mid_sentence(self, doc):
        text = re.sub(r"(?m)(?<!\\)%.*$", " ", (REPO / doc).read_text(encoding="utf-8"))
        bad = []
        for m in re.finditer(r"\\[a-zA-Z]+WordCap\{\}", text):
            before = " ".join(text[max(0, m.start() - 120):m.start()].split())
            if before and not before.endswith(self.OPENER):
                bad.append((m.group(0), before[-70:]))
        assert not bad, (
            "capitalised word macro(s) standing mid-sentence, where the lower-case twin "
            "belongs: %s" % bad)

    def test_the_rule_can_fail(self):
        """Round 61's own defect, and the sentence-opening use that must stay legal."""
        assert not "the benchmark;".endswith(self.OPENER)
        assert "and nothing more.".endswith(self.OPENER)
        assert "the criterion:".endswith(self.OPENER)


class TestTheCensusEmitterDeclinesRatherThanInvents:
    """Off the author's machine there is no corpus, so the emitter must return nothing.

    `docs/reference_tc` is gitignored: a build on any other machine reads the committed CSV,
    and a build with neither corpus nor CSV must emit no census macros at all rather than
    emit some of them. A supplement sentence quoting half a census would be worse than one
    quoting none, because LaTeX would render the missing half as an undefined control
    sequence and the build would say so --- but only for the macros that happen to be used.
    """

    def _emitter(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        import emit_paper_numbers
        return emit_paper_numbers

    def test_an_unreadable_census_emits_nothing(self, monkeypatch):
        epn = self._emitter()
        import literature_census

        def boom(*_a, **_kw):
            raise OSError("no record")

        monkeypatch.setattr(literature_census, "counts_for", boom)
        assert epn.literature_census_macros() == []

    def test_an_empty_census_emits_nothing(self, monkeypatch):
        epn = self._emitter()
        import literature_census
        monkeypatch.setattr(literature_census, "counts_for", lambda _k: {})
        assert epn.literature_census_macros() == []

    def test_a_census_without_the_playbook_still_emits_the_survey(self, monkeypatch):
        """The two sources are independent: losing one may not silence the other."""
        epn = self._emitter()
        import literature_census
        monkeypatch.setattr(literature_census, "counts_for",
                            lambda key: {"latency": 33, "benchmark": 169, "timestamp": 0,
                                         "clock": 0, "resolution": 0}
                            if key == "yue2024streamsurvey" else {})
        monkeypatch.setattr(literature_census, "read_record",
                            lambda path=None: [{"key": "yue2024streamsurvey", "pages": "21"}])
        got = dict(epn.literature_census_macros())
        assert got["surveyLatencyMentions"] == "33"
        assert got["surveyAbsentTimes"] == "never"
        assert "playbookPages" not in got
