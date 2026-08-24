"""Pointers between the two documents, which LaTeX cannot check and nobody re-reads.

The manuscript and the supplement are separate compilations, so `\\ref` cannot reach across
them. Every pointer in one document at the other is therefore a *hand-typed number*, outside
every mechanism this project uses to stop numbers drifting. There are more than thirty of
them.

Round 5 asked for twelve descriptive pointers ("the main text's attribution section") to be
replaced by numbers, and for five unresolvable `\\ref` calls to go. That fix ran a
substitution and left two sentences reading

    Equation~the main text tells a reader where to be careful

which compiled without a warning, rendered without an overfull box, and passed 2,473 tests.
It was found by eye, three rounds later. A third pointer still cited "the main text's
Section~6.2" -- arabic, where the paper numbers in Roman, and pointing at a section number
the paper has not used since the TC restructure.

These are all one defect class: a cross-document pointer that no longer denotes anything.
The checks below read `paper.aux`, which holds the real numbers LaTeX assigned, and hold
every pointer against it. A pointer that resolves to nothing now fails here rather than in
a referee's browser tab.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"
AUX = REPO / "paper.aux"


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    if not SUPP.exists():
        pytest.skip("supplement not present")
    return SUPP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def aux():
    """label -> printed number, as LaTeX actually assigned them.

    `\\newlabel{sec:gate}{{\\mbox {III-B}}{3}{...}}` -- the number is the first group, with
    the \\mbox wrapper IEEEtran adds to subsection numbers stripped off.
    """
    if not AUX.exists():
        pytest.skip("paper.aux not present; build the paper first")
    out = {}
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{(.*?)\}\{\d+\}", AUX.read_text(encoding="utf-8")):
        label, printed = m.group(1), m.group(2)
        printed = printed.replace(r"\mbox", "").strip().strip("{}").strip()
        if printed:
            out[label] = printed
    return out


class TestNoStrandedPointer:
    """A float word with no number after it. This is what the round-5 substitution left."""

    # "Equation~the", "Section~ ", "Table~and" -- a pointer word followed by anything that
    # cannot begin a number or a \ref.
    STRANDED = re.compile(
        r"(Equation|Section|Table|Figure|Fig\.|Supplement)~(?!\\ref|\\[a-zA-Z]|[0-9IVXS])")

    @pytest.mark.parametrize("name", ["paper", "supplement"])
    def test_no_pointer_word_lacks_its_number(self, name, paper, supp):
        text = paper if name == "paper" else supp
        hits = []
        for m in self.STRANDED.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append("%s:%d  %r" % (name, line, text[m.start():m.start() + 48]))
        assert not hits, "pointer word with nothing to point at:\n  " + "\n  ".join(hits)


class TestSupplementPointsAtRealSections:
    """Every "Section~X of the main text" must be a section the main text has."""

    POINTER = re.compile(
        r"(?:main text's Section~|Section~)([IVX]+(?:-[A-D])?|[0-9]+(?:\.[0-9]+)?)"
        r"(?=[^a-zA-Z]|$)")

    def test_every_pointer_resolves(self, supp, aux):
        real = set(aux.values())
        bad = []
        for m in self.POINTER.finditer(supp):
            num = m.group(1)
            if num not in real:
                line = supp.count("\n", 0, m.start()) + 1
                bad.append("supplement:%d  Section~%s (the paper has no such number)"
                           % (line, num))
        assert not bad, "\n  " + "\n  ".join(bad)

    def test_pointers_use_roman_numerals(self, supp):
        """The paper numbers sections in Roman. An arabic pointer is a stale one.

        "the main text's Section~6.2" survived the round-5 sweep because the sweep looked for
        descriptive names, and this one was already a number -- just a number from a
        structure two restructures old.
        """
        arabic = []
        for m in re.finditer(r"(?:main text's )?Section~([0-9]+(?:\.[0-9]+)?)", supp):
            line = supp.count("\n", 0, m.start()) + 1
            arabic.append("supplement:%d  Section~%s" % (line, m.group(1)))
        assert not arabic, "arabic section pointers:\n  " + "\n  ".join(arabic)


class TestPaperPointsAtRealSupplementSections:
    """Every "Supplement~SNN" must be a section the supplement has.

    The reverse direction of the same defect. Round 3 raised it for the main text and it was
    fixed by hand; nothing has held it since.
    """

    def _supplement_sections(self, supp):
        return {int(n) for n in re.findall(r"^\\section\{S(\d+)[.:]", supp, re.M)}

    def test_every_supplement_pointer_exists(self, paper, supp):
        have = self._supplement_sections(supp)
        assert have, "no S-numbered sections found; the heading pattern changed"
        missing = sorted({int(n) for n in re.findall(r"Supplement~S(\d+)", paper)} - have)
        assert not missing, "paper cites supplement sections that do not exist: %s" % (
            ["S%d" % n for n in missing],)


class TestSupplementNumbering:
    """The contents list is read as a list. Two defects in it are visible at a glance."""

    def _order(self, supp):
        return [int(n) for n in re.findall(r"^\\section\{S(\d+)[.:]", supp, re.M)]

    def test_sections_appear_in_increasing_order(self, supp):
        order = self._order(supp)
        swaps = [(a, b) for a, b in zip(order, order[1:]) if a > b]
        assert not swaps, "sections out of order in the contents list: %s" % (
            ["S%d before S%d" % (a, b) for a, b in swaps],)

    def test_any_gap_is_explained(self, supp):
        """Gaps are allowed -- S14 and S30 were withdrawn and their numbers are cited in
        correspondence -- but only where the document says so, so a reader is not left
        counting."""
        order = self._order(supp)
        gaps = sorted(set(range(min(order), max(order) + 1)) - set(order))
        if not gaps:
            return
        note = re.search(r"\\emph\{On the numbering\.\}(.*)", supp)
        assert note, "the contents list has gaps (%s) and no note explaining them" % (
            ["S%d" % g for g in gaps],)
        for g in gaps:
            assert "S%d" % g in note.group(1), \
                "S%d is missing from the contents list and unexplained in the note" % g

    def test_headings_punctuate_consistently(self, supp):
        """S1--S5 used a colon where S6--S42 used a period, in the one list a reader scans
        top to bottom."""
        marks = {m.group(1) for m in re.finditer(r"^\\section\{S\d+([.:])", supp, re.M)}
        assert len(marks) == 1, "S-headings mix separators: %s" % sorted(marks)


class TestSupplementPointsAtRealFloats:
    """Every "Figure~N" and "Table~N" in the supplement must be that float in the main text.

    These are hand-typed numbers crossing a document boundary, which is the same hazard the
    Section pointers carry and the same fix: resolve them against the paper's own .aux, so a
    renumbered float fails the build instead of quietly redirecting the reader.
    """

    POINTER = re.compile(r"\b(Figure|Table)~([0-9]+|[IVX]+)(?=[^a-zA-Z0-9]|$)")

    def test_every_float_pointer_resolves(self, supp, aux):
        printed = {
            "Figure": {v for k, v in aux.items() if k.startswith("fig:")},
            "Table": {v for k, v in aux.items() if k.startswith("tab:")},
        }
        if not printed["Figure"] or not printed["Table"]:
            pytest.skip("paper.aux carries no float labels; build the paper first")
        bad = []
        for m in self.POINTER.finditer(supp):
            kind, num = m.group(1), m.group(2)
            if num not in printed[kind]:
                line = supp.count("\n", 0, m.start()) + 1
                bad.append("supplement:%d  %s~%s (the paper has %s %s)"
                           % (line, kind, num, kind.lower(),
                              ", ".join(sorted(printed[kind]))))
        assert not bad, "\n  " + "\n  ".join(bad)

    def test_the_pointers_that_exist_are_the_ones_we_expect(self, supp, aux):
        """A cheap tripwire: if the supplement grows float pointers, they get read.

        Two exist today, and both were added in the last two rounds. Listing them keeps a
        third from arriving unexamined.
        """
        found = {"%s~%s" % (m.group(1), m.group(2))
                 for m in self.POINTER.finditer(supp)}
        expected = {"Table~II", "Figure~7", "Figure~1"}
        assert found <= expected, \
            "new cross-document float pointer(s) %s -- check each against the paper" % (
                sorted(found - expected))
