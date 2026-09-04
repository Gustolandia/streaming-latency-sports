r"""The two documents' title pages, which no gate had ever read.

Round 52 found the supplement's first page stale since round 4. It carried

    Supplementary Material: When the Interval Is Smaller Than the Instrument
    Gustavo Pedro Ricou

against a paper bylined to four authors, under a title the paper does not have, with the
string "Faster Than Light" occurring nowhere in `supplement.tex` and no `\markboth` to put
anything in the running head either. The author block was written in commit `01dc662` and had
not been touched since; the paper went to four authors in `07c57bc`. The front matter of one
document moved and the front matter of the other did not.

It survived forty-eight rounds of review because every gate in this repository reads content.
There are checks on numbers, cross-document pointers, float labels, figure reading rules,
claim-to-equation agreement, cross-sentence dependency and per-corpus denominators, and not
one of them looks at a title block.

TC requires supplementary material to be submitted as a separate file. That is precisely the
circumstance in which a document has to be able to say what it belongs to, and a fifty-four
page document of working behind a four-author paper, credited to one of them, is not a
formatting nit.

So: the two bylines must be identical, the supplement must name the paper, and it must carry
a running head. Three assertions, and the class they close is the last unautomated seam in the
project.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent


def _source(name):
    path = REPO / name
    if not path.exists():                       # pragma: no cover - both ship in the repo
        pytest.skip("%s not present" % name)
    return re.sub(r"(?m)^%.*$", "", path.read_text(encoding="utf-8"))


def _braced(text, start):
    """The balanced {...} group beginning at `start`, which \\author's thanks blocks need."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    raise AssertionError("unbalanced group")


def _field(name, macro):
    text = _source(name)
    m = re.search(r"\\%s\s*\{" % macro, text)
    assert m, "%s has no \\%s" % (name, macro)
    return _braced(text, m.end() - 1)


def _names(author_block):
    """The byline with affiliation footnotes and markup stripped."""
    body = re.sub(r"\\thanks\s*\{", "\x00{", author_block)
    out, depth = [], 0
    for ch in body:
        if ch == "\x00":
            depth = 1
            continue
        if depth:
            depth += {"{": 1, "}": -1}.get(ch, 0)
            continue
        out.append(ch)
    plain = re.sub(r"\\[a-zA-Z]+|[{}%]", " ", "".join(out))
    plain = plain.replace("~", " ")
    return [n for n in re.split(r",|\band\b", plain) if n.strip()]


class TestTheTwoDocumentsAgreeOnWhoWroteThem:

    def test_the_bylines_name_the_same_people_in_the_same_order(self):
        paper = [" ".join(n.split()) for n in _names(_field("paper.tex", "author"))]
        supp = [" ".join(n.split()) for n in _names(_field("supplement.tex", "author"))]
        assert supp == paper, (
            "the supplement is bylined %s and the paper %s; supplementary material carries "
            "the paper's authorship" % (supp, paper))

    def test_the_supplement_names_every_affiliation_the_paper_does(self):
        paper = _field("paper.tex", "author")
        supp = _field("supplement.tex", "author")
        for inst in ("Trinity College Dublin", "Chalmers", "W\\\"urzburg"):
            if re.search(inst, paper):
                assert re.search(inst, supp), (
                    "the paper gives an affiliation at %s and the supplement does not"
                    % inst.replace("\\\\", ""))

    def test_the_paper_still_has_four_authors(self):
        """If the author list ever changes, this file should be read, not silently passed."""
        assert len(_names(_field("paper.tex", "author"))) == 4


class TestTheSupplementSaysWhichPaperItBelongsTo:
    r"""Separated from the paper, the file has to identify itself."""

    def _paper_title_words(self):
        title = _field("paper.tex", "title")
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", title)
        return [w for w in plain.split() if len(w) > 3]

    def test_the_supplement_title_carries_the_paper_title(self):
        supp = _field("supplement.tex", "title")
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", supp)
        missing = [w for w in self._paper_title_words() if w not in plain]
        assert not missing, (
            "the supplement's title does not contain the paper's; missing %s. A reader "
            "holding the separate file cannot tell what it supplements" % missing[:6])

    def test_the_supplement_declares_itself_supplementary(self):
        supp = _source("supplement.tex")
        assert re.search(r"[Ss]upplementary [Mm]aterial", supp), \
            "the supplement should say that it is one"

    def test_the_supplement_carries_a_running_head(self):
        supp = _source("supplement.tex")
        assert re.search(r"\\markboth\s*\{", supp), (
            "no \\markboth, so the supplement's pages carry nothing tying them to the paper")

    def _markboth(self, name):
        r"""Both groups of `\markboth{left}{right}`; the recto head is the second."""
        text = _source(name)
        m = re.search(r"\\markboth\s*\{", text)
        assert m, "%s has no \\markboth" % name
        left = _braced(text, m.end() - 1)
        after = text.index("{", m.end() - 1 + len(left) + 2)
        return left, _braced(text, after)

    def test_both_running_heads_are_set(self):
        r"""IEEEtran's one-column mode prints only the verso head, so the recto group is
        belt-and-braces rather than something a reader sees. It is still asserted, because a
        `\markboth` with an empty second group is a half-written command and the next person
        to change the class would inherit a blank recto."""
        for name in ("paper.tex", "supplement.tex"):
            left, recto = self._markboth(name)
            assert left.strip() and recto.strip(), "%s has an empty running head" % name
        assert "Faster Than Light" in self._markboth("supplement.tex")[1], \
            "the supplement's recto head should name the paper"

    def test_the_supplement_head_says_it_is_supplementary(self):
        """This is the one that prints. A stray page must not read as the paper itself."""
        left, _recto = self._markboth("supplement.tex")
        assert re.search(r"supplement", left, re.I), (
            "the supplement's verso head should mark it as supplementary material; it "
            "reads %r" % left)


class TestTheBuiltSupplementIdentifiesItself:
    """The source is not the artifact. Round 48 through 52 kept finding that the rendered
    page and the source disagreed about something, so this reads the PDF."""

    @pytest.fixture(scope="class")
    def pages(self):
        import shutil
        import subprocess
        pdf = REPO / "supplement.pdf"
        if not pdf.exists() or not shutil.which("pdftotext"):
            pytest.skip("built supplement or pdftotext unavailable")

        def page(n):
            out = subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), str(pdf), "-"],
                                 capture_output=True).stdout
            return re.sub(r"\s+", " ", out.decode("utf-8", "replace"))
        return page

    def test_page_one_names_the_paper_and_every_author(self, pages):
        first = pages(1)
        assert "Faster Than Light" in first, \
            "the built supplement's first page does not name the paper"
        for surname in ("Ricou", "Duvignau", "Herbst", "Gregg"):
            assert surname in first, \
                "the built supplement's byline omits %s" % surname

    @pytest.mark.parametrize("page_no", [2, 3, 20])
    def test_every_page_carries_the_running_head(self, pages, page_no):
        assert re.search(r"supplementary material", pages(page_no), re.I), (
            "page %d of the built supplement carries nothing marking it as supplementary; a "
            "loose page reads as the paper" % page_no)

    def test_the_rule_can_fail(self):
        """The exact front matter round 52 found."""
        stale = r"\title{Supplementary Material:\\When the Interval Is Smaller Than the Instrument}"
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", stale)
        assert "Faster" not in plain
        assert _names("Gustavo~Pedro~Ricou") != _names(
            "Gustavo~Pedro~Ricou,~Romaric~Duvignau,~Nikolas~Herbst,~and~David~Gregg")
