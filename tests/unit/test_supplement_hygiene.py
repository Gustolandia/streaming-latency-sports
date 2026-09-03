r"""Three checks the supplement had no equivalent of, all found in round 46.

The main text has been hardened round after round. The supplement has not, and round 46
measured the gap: of the non-structural numerals each document prints, 78% of the main text's
arrive through a generated macro and **15%** of the supplement's do. The supplement carries
roughly four fifths of the paper's evidence.

Three consequences, one per class:

**Numbers that describe an arm.** Round 45 rebuilt `phase_quantisation.csv`. The generated
tables followed; four narrative paragraphs in S13 and S23 did not, and went on describing a
nine-arm corpus with a 46.6% median where the rebuilt one has ten replicates and 51.04. None
was caught, because `test_ledger_coverage.py` only flags a typed value that equals an *emitted*
macro, and none of these was emitted. They are emitted now (`arm_macros`), and this file checks
that the documents read them rather than restating them.

**A citation with nothing to find it by.** A grey entry quoting two specific latency figures
carried no URL and no identifier, and the figures could not be found at either page matching its
title. Every other figure-quoting grey entry in the file is locatable and exact -- one of them
verbatim -- so this is a lapse rather than a habit, and a rule stops it recurring.

**A reference list in the middle of a document.** The supplement's bibliography sat 61% of the
way through the source, rendering on page 32 of 53, with 22 sections, 9 floats and 48 distinct
citation keys after it.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"


def _tex(name):
    """A document with its LaTeX comments stripped."""
    raw = (REPO / name).read_text(encoding="utf-8")
    return re.sub(r"(?<!\\)%.*", "", raw)


@pytest.fixture(scope="module")
def emitted():
    if not GENERATED.exists():                              # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}", GENERATED.read_text(
        encoding="utf-8")))


@pytest.fixture(scope="module")
def documents():
    return _tex("paper.tex") + "\n" + _tex("supplement.tex")


class TestArmNarrativesReadTheLedger:
    """A paragraph that narrates an arm's replicates must not type their values.

    The five defects round 46 found were a median, a miss against a registered prediction, a
    spread quoted as 58.6 that is 98.7, a spread quoted as 30.5 that is 31.2, and a replicate
    count. Every one is a function of `phase_quantisation.csv`.
    """

    #: Values the rebuilt ledger retired, with what they were. A document containing one of
    #: these is quoting the pre-rebuild corpus.
    RETIRED = {
        "46.6": "the 625 msg/s median at five replicates; it is 51.04 at ten",
        "58.6": "the 250 msg/s spread at three replicates; it is 98.73 at five",
        "30.5": "the 300 msg/s spread at five replicates; it is 31.24 at ten",
    }

    def test_no_retired_arm_value_survives_in_either_document(self, documents):
        found = ["%s (%s)" % (v, why) for v, why in self.RETIRED.items()
                 if re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d])", documents)]
        assert not found, (
            "these describe the corpus as it stood before the round-45 rebuild: %s"
            % "; ".join(found))

    @pytest.mark.parametrize("macro", [
        "armSixTwentyFiveMedian", "armSixTwentyFiveMedianOffBy", "armSixTwentyFiveNWord",
        "armTwoFiftySpread", "armTwoFiftyCell", "armThreeHundredSpread",
        "armFourHundredSpread", "armFourHundredHi", "armFourHundredWithoutHiSpan",
        "spreadIncommensurateWord", "spreadIncommensurateLo", "spreadIncommensurateHi",
    ])
    def test_the_narrated_quantities_are_emitted(self, emitted, macro):
        assert macro in emitted, "%s is no longer emitted; the prose has nothing to read" % macro

    @pytest.mark.parametrize("macro", [
        "armSixTwentyFiveMedian", "armSixTwentyFiveMedianOffBy",
        "armTwoFiftySpread", "armThreeHundredSpread", "spreadIncommensurateWord",
    ])
    def test_the_narrated_quantities_are_read(self, documents, macro):
        assert re.search(re.escape("\\" + macro) + r"(?![A-Za-z])", documents), (
            "%s is emitted and quoted by neither document; that is where a stale number "
            "survives a revision" % macro)

    def test_the_emitted_values_match_the_ledger(self, emitted):
        """Two routes: this reads the phase ledger directly, the emitter goes through
        `spread_cells`. Agreement is the check."""
        import csv
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        path = REPO / "docs" / "results" / "external" / "phase_quantisation.csv"
        rows = {int(r["rate_hz"]): r for r in csv.DictReader(path.open(encoding="utf-8"))}
        for rate, name in ((625, "armSixTwentyFive"), (250, "armTwoFifty"),
                           (300, "armThreeHundred"), (400, "armFourHundred")):
            values = sorted(float(v) for v in rows[rate]["retentions"].split())
            mid = len(values) // 2
            median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
            # Each arm emits only the fields its own paragraph quotes, so check what is there
            # rather than demanding a uniform set -- an unread macro is its own defect.
            expected = {
                "N": "%d" % len(values),
                "Spread": "%.2f" % (values[-1] - values[0]),
                "Median": "%.2f" % median,
                "Lo": "%.2f" % values[0],
                "Hi": "%.2f" % values[-1],
            }
            checked = 0
            for suffix, want in expected.items():
                if name + suffix in emitted:
                    assert emitted[name + suffix] == want, "%s%s" % (name, suffix)
                    checked += 1
            assert checked, "no comparable field emitted for %d msg/s" % rate


class TestEveryFigureQuotingCitationCanBeFound:
    r"""A grey citation that quotes a number must say where the number is.

    S52.3 called one such source "the clearest current instance" of a published ranking inside
    this paper's regime, and quoted two latency figures from it. The entry carried no URL and no
    identifier; neither page matching its title contains those figures. Every other
    figure-quoting grey entry in the file is locatable, and one is quoted verbatim and correct,
    so the rule costs the authors nothing they are not already doing.
    """

    BIB = REPO / "manuscript_references.bib"

    @staticmethod
    def entries():
        text = TestEveryFigureQuotingCitationCanBeFound.BIB.read_text(encoding="utf-8")
        return re.findall(r"@(\w+)\{([^,]+),(.*?)\n\}", text, re.S)

    @staticmethod
    def cited_keys():
        surface = _tex("paper.tex") + _tex("supplement.tex")
        for path in (REPO / "docs" / "generated").glob("*.tex"):
            surface += path.read_text(encoding="utf-8")
        keys = set()
        for group in re.findall(r"\\cite\w*\{([^}]*)\}", surface):
            keys.update(k.strip() for k in group.split(","))
        return keys

    #: A repository, a mailing-list commit or a numbered standard identifies itself. The rule
    #: is aimed at the tier that does not: a web page whose only handle is its title.
    SELF_IDENTIFYING = re.compile(
        r"\\url\{|\burl\s*=|arXiv:\s*\d|\bdoi\b|source repository|mailing list|"
        r"\bnumber\s*=|Std\s+\d|RFC\s*\d|User Guide", re.I)

    #: Clause, section and version references look like decimals and are not measurements.
    CLAUSE = re.compile(r"(?:\\S|\bSection|\bsection|§|\bv|\bp\.|\bpp\.)\s*~?\d[\d.]*", re.I)

    @staticmethod
    def locatable(body):
        return bool(TestEveryFigureQuotingCitationCanBeFound.SELF_IDENTIFYING.search(body))

    @staticmethod
    def _measurements_only(note):
        """The note with clause and version references removed.

        "\\S3.4.5" is a place in a document, not a quantity read off one. A rule that cannot
        tell them apart asks a standards body for a URL and teaches everyone to ignore it.
        """
        return TestEveryFigureQuotingCitationCanBeFound.CLAUSE.sub(" ", note)

    def test_a_cited_web_entry_quoting_a_measurement_carries_a_locator(self):
        """Restricted to the tier the finding was about.

        A standard is found by its designation and a kernel commit by its hash; requiring a
        URL of those would be noise. What has no handle at all is a practitioner or vendor
        page, and that is where the unverifiable figures were.
        """
        cited = self.cited_keys()
        bad = []
        for kind, key, body in self.entries():
            key = key.strip()
            if kind.lower() not in ("misc", "online", "techreport") or key not in cited:
                continue
            note = re.search(r"note\s*=\s*\{(.*)", body, re.S)
            note = self._measurements_only(note.group(1) if note else "")
            # A measurement, not a clause number: a decimal, or a digit with a unit.
            if not re.search(r"\d+\.\d|\d+\s*~?(ms|s|us|\\,?\\mu|%)", note):
                continue
            if not self.locatable(body):
                bad.append(key)
        assert not bad, (
            "these are cited, quote a measured figure in their note, and give nothing to "
            "check it against -- no URL, arXiv id, DOI or standard designation: %s"
            % ", ".join(sorted(bad)))

    def test_the_rule_would_have_caught_the_entry_it_was_written_for(self):
        """`indexdev2026brokers` as it stood: a note full of figures and nothing to find."""
        was = ('  author = {{Index.dev}},\n  howpublished = {Practitioner comparison},\n'
               '  note = {reports a p99 of $0.8$~ms against $12.5$~ms}\n')
        assert not self.locatable(was)

    def test_the_rule_leaves_a_numbered_standard_alone(self):
        """A standard is found by its designation; demanding a URL of it would be noise."""
        std = '  howpublished = {IEEE Std 1588-2019},\n  note = {Revision of IEEE Std 1588-2008}\n'
        assert self.locatable(std)


class TestTheReferenceListIsWhereAReaderExpectsIt:
    """The supplement's bibliography rendered on page 32 of 53, with 22 sections after it."""

    @pytest.mark.parametrize("name", ["paper.tex", "supplement.tex"])
    def test_nothing_of_substance_follows_the_bibliography(self, name):
        tex = _tex(name)
        at = tex.index("\\bibliography{")
        after = tex[at:]
        sections = re.findall(r"\\section\{", after)
        floats = re.findall(r"\\begin\{(?:table|figure)\}", after)
        assert not sections, (
            "%s has %d \\section after its reference list; a reader who reaches the "
            "references reasonably concludes the document has ended" % (name, len(sections)))
        assert not floats, (
            "%s has %d float(s) after its reference list" % (name, len(floats)))

    @pytest.mark.parametrize("name", ["paper.tex", "supplement.tex"])
    def test_the_bibliography_is_near_the_end_of_the_source(self, name):
        tex = _tex(name)
        at = tex.index("\\bibliography{")
        fraction = at / len(tex)
        assert fraction > 0.85, (
            "%s puts its reference list %.0f%% of the way through the source; it was 61%% in "
            "the supplement before round 47, which rendered on page 32 of 53"
            % (name, 100 * fraction))
