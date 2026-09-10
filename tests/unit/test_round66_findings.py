r"""Round 66. Four defects, each of a kind no existing gate could see.

**R1 was the serious one and it was invisible to every check here.** The supplement's
orientation paragraph --- the first prose a reader meets, sitting directly above the table of
contents --- still described the parts as they had been arranged before v5. Three of its four
descriptions were wrong, and it reintroduced the "in full" framing the rest of the document
had just abandoned. The v5 gates checked section titles, section sizes, reachability and
numbering, all of which were correct; nothing checked that the document's own summary of
itself matched the document. **A file can be internally consistent everywhere except in the
sentence that tells you what it is.**

The other three are smaller and share a shape: a place where the manuscript talks about its
own history to an outside reader. A List-of-Figures entry reading only "Withdrawn"; a
bibliography entry annotating its own revision; and, in the other direction, a caption naming
three modes and giving the mass of one.

Round 65's lesson was that a citation is transcribed from the work's own title page. Both
grey-literature items added here were read from the issue trackers rather than from the
referee's summary of them, which is why the dates and authors below are specific.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPPLEMENT = REPO / "supplement.tex"
BIB = REPO / "manuscript_references.bib"


def _strip(text):
    return re.sub(r"(?m)%.*$", "", text)


@pytest.fixture(scope="module")
def supp():
    return _strip(SUPPLEMENT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def paper():
    return _strip(PAPER.read_text(encoding="utf-8"))


class TestTheDocumentDescribesItself:
    """R1. The orientation paragraph and the contents page must agree."""

    @staticmethod
    def _parts(tex):
        return [m.group(1).strip()
                for m in re.finditer(r"\\section\*\{(Part [IVX]+\.[^}]*)\}", tex)]

    @staticmethod
    def _orientation(tex):
        i = tex.index("This document is the supplementary material")
        return " ".join(tex[i:tex.index("\\tableofcontents", i)].split())

    def test_the_opening_paragraph_names_every_part_by_its_real_title(self, supp):
        note = self._orientation(supp)
        for part in self._parts(supp):
            label, title = part.split(".", 1)
            key = " ".join(title.split())[:34]
            assert key.lower() in note.lower(), (
                "the orientation paragraph does not describe %s as %r. It sits directly "
                "above the table of contents, so a reader meets both at once and finds them "
                "disagreeing. This is what round 66 found: three of four descriptions were "
                "left over from the arrangement before v5." % (label, key))

    def test_the_opening_paragraph_has_dropped_the_in_full_framing(self, supp):
        note = self._orientation(supp)
        assert "in full" not in note.lower(), (
            "the orientation paragraph still files the parts against the paper rather than "
            "by what they answer. Eighteen section titles were retitled for exactly this "
            "reason; the paragraph introducing them may not undo it.")

    def test_the_rule_can_fail(self, supp):
        stale = ("Part I retells how the results were reached; Part II holds the experiments "
                 "in full; Part III the audits and derivations.")
        assert "in full" in stale
        assert "the mechanism, and the law it produces" not in stale.lower()


class TestEveryShortCaptionNamesItsSubject:
    """R3. A List-of-Figures line has to say what the figure is."""

    #: A short caption is what the reader sees in the List of Figures, with no picture beside
    #: it and no full caption underneath. Two words is the floor at which one can name a
    #: subject at all; "Withdrawn" named only a status.
    MIN_WORDS = 2

    def test_no_short_caption_is_a_bare_status_word(self, supp):
        bad = []
        for m in re.finditer(r"\\caption\[([^\]]*)\]", supp):
            words = m.group(1).split()
            if len(words) < self.MIN_WORDS:
                bad.append(m.group(1))
        assert not bad, (
            "these short captions carry fewer than %d words, so the List of Figures shows a "
            "line that names no subject: %s. The full caption explains itself; the entry a "
            "reader scans does not." % (self.MIN_WORDS, "; ".join(repr(b) for b in bad)))

    def test_the_withdrawn_figure_says_what_was_withdrawn(self, supp):
        i = supp.index("e1_end_to_end_lag.pdf")
        short = re.search(r"\\caption\[([^\]]*)\]", supp[i:i + 400])
        assert short, "the withdrawn figure lost its short caption"
        assert short.group(1).strip().lower() != "withdrawn", \
            "the List of Figures reads `Withdrawn` and names nothing"

    def test_the_rule_can_fail(self):
        assert len("Withdrawn".split()) < self.MIN_WORDS
        assert len("Withdrawn: the end-to-end gap as first decomposed".split()) >= self.MIN_WORDS


class TestTheBibliographyDoesNotAnnotateItsOwnRevisions:
    """R5. A reference entry attributes a source; it is not a changelog."""

    def test_no_note_points_at_the_supplement(self):
        text = BIB.read_text(encoding="utf-8")
        bad = []
        for m in re.finditer(r"@\w+\{([^,]+),(.*?)(?=\n@|\Z)", text, re.S):
            note = " ".join(m.group(2).split())
            if re.search(r"supplement's S\d|recorded in the supplement", note, re.I):
                bad.append(m.group(1).strip())
        assert not bad, (
            "%s annotate their own reading history and point the reader into the supplement "
            "for it. A bibliography entry says what a source is and when it was read; where "
            "an earlier misreading was corrected is the supplement's business, and it is "
            "already recorded there." % ", ".join(bad))

    def test_the_rule_can_fail(self):
        bad = "Read 2026-09-03. (The correction to an earlier reading of this page is " \
              "recorded in the supplement's S1.)"
        assert re.search(r"supplement's S\d|recorded in the supplement", bad, re.I)


class TestTheGreyLiteratureIsReadFromItsSource:
    """R2. Both OpenMessaging issues, pinned by what their trackers actually say."""

    def test_both_issues_are_in_the_bibliography(self):
        text = BIB.read_text(encoding="utf-8")
        for key, url in (("omb2022coordinated", "issues/247"),
                         ("omb2026histogram", "issues/452")):
            assert key in text, "%s is missing from the bibliography" % key
            assert url in text, "%s does not carry its issue URL" % url

    def test_the_entries_name_who_opened_them_and_when(self):
        text = BIB.read_text(encoding="utf-8")
        for key, who, year in (("omb2022coordinated", "franz1981", "2022"),
                               ("omb2026histogram", "SamBarker", "2026")):
            i = text.index("{%s," % key)
            entry = text[i:text.index("\n}", i)]
            assert who in entry, "%s does not name who opened it" % key
            assert year in entry, "%s does not carry its year" % key

    def test_the_supplement_carries_both_as_evidence(self, supp):
        for key in ("omb2022coordinated", "omb2026histogram"):
            assert key in supp, "%s is cited nowhere in the supplement" % key

    def test_the_main_text_makes_the_point_without_spending_a_reference(self, paper):
        """The article sits at the 45-reference cap, so the clause points at the supplement.

        The supplement's bibliography is uncapped (standard A1f), which is what makes this
        addition free. A main-text `\\cite` of either issue would cost a reference the paper
        does not have, and would have to displace one.
        """
        for key in ("omb2022coordinated", "omb2026histogram"):
            assert key not in paper, (
                "%s is cited in the article, which is at the reference cap. Point at the "
                "supplement section that holds the evidence instead." % key)
        assert "maintainers" in paper or "accepted" in paper, \
            "the remedy argument does not use the evidence the supplement now holds"


class TestTheCaptionGivesTheMassOfEveryModeItNames:
    """The figure's argument rests on where a mode sits; its size decides whether that matters."""

    def test_all_three_shares_are_emitted_rather_than_typed(self, paper):
        i = paper.index("stall_spectrum.pdf")
        caption = paper[i:paper.index("\\end{figure}", i)]
        for macro in ("\\tracedModeShareA", "\\tracedModeShareB", "\\tracedModeShare"):
            assert macro in caption, (
                "%s is not in Figure 3's caption. The caption names three modes; a reader "
                "weighing the argument needs the mass of each, and all three were computed "
                "in the emitter before this round without two of them being emitted." % macro)

    def test_no_share_is_typed_as_a_literal(self, paper):
        i = paper.index("stall_spectrum.pdf")
        caption = paper[i:paper.index("\\end{figure}", i)]
        for literal in ("20.0", "13.5", "10.5"):
            assert literal not in caption, \
                "%s is typed into the caption; every number is emitted" % literal

    def test_the_generated_macros_exist(self):
        """A and B, plus the third mode's share under the name it already had.

        Round 66 emitted A, B and C over the three modes in bucket order, which put a fourth
        name on a number `tracedModeShare` was already carrying. Round 68's full run caught it
        as an unread macro --- nothing quoted C, because the caption and the body both use
        `tracedModeShare` for that mode. An unread macro is a number nobody checked, so C was
        retired rather than the prose padded to consume it.
        """
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        for macro in ("tracedModeShareA", "tracedModeShareB", "tracedModeShare"):
            assert "\\newcommand{\\%s}" % macro in gen, "%s is not emitted" % macro
        assert "\\newcommand{\\tracedModeShareC}" not in gen, (
            "tracedModeShareC is back. It duplicates tracedModeShare, which is what made it "
            "unread; if the third mode ever needs its own name, retire the other one.")


class TestAFigureSetsASymbolTheWayTheTextDoes:
    r"""The image review found Figure 2 setting the paper's own symbols differently.

    The body defines $t_{\mathrm{sched}}$, $t_{\mathrm{send}}$, $t_{\mathrm{ack}}$ and
    $t_{\mathrm{recv}}$ with roman subscripts, twenty-eight times. Figure 2 --- the drawing a
    reader consults *while* reading Equation 1 --- set the same four symbols with italic
    subscripts, so the two most closely coupled objects in the paper disagreed about how the
    quantity they share is spelled. Twenty instances across three figure scripts, none of them
    visible to a gate that reads LaTeX, because they live in matplotlib mathtext.

    Standard A5b says a defined symbol means one thing. It has to look like one thing too.
    """

    SUBSCRIPTS = ("sched", "send", "ack", "recv", "out", "true")
    SCRIPTS = ("make_paper_figures.py", "make_thread_figure.py", "make_result_figures.py")

    @pytest.mark.parametrize("name", SCRIPTS)
    def test_no_figure_script_sets_a_defined_subscript_in_italic(self, name):
        src = (REPO / "scripts" / name).read_text(encoding="utf-8")
        bad = re.findall(r"[a-zA-Z]_\{(?:%s)\}" % "|".join(self.SUBSCRIPTS), src)
        assert not bad, (
            "%s sets %s with an italic subscript. The paper sets the same symbols roman, and "
            "a reader meets the figure and the equation together." % (name, sorted(set(bad))))

    def test_the_paper_still_uses_the_convention_the_figures_now_match(self, paper):
        assert paper.count("\\mathrm{recv}") >= 5, \
            "the paper's own subscript convention changed; the figures follow it, not the reverse"

    def test_the_rule_can_fail(self):
        pat = r"[a-zA-Z]_\{(?:%s)\}" % "|".join(self.SUBSCRIPTS)
        assert re.findall(pat, r'ax.text(3.1, 5.34, r"$t_{send}$")')
        assert not re.findall(pat, r'ax.text(3.1, 5.34, r"$t_{\mathrm{send}}$")')
