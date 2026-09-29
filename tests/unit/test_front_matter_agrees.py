r"""The documents' title pages, which no gate had ever read.

Round 52 found the supplement's first page stale since round 4. It carried

    Supplementary Material: When the Interval Is Smaller Than the Instrument
    Gustavo Pedro Ricou

against a paper bylined to four authors, under a title the paper does not have, with the
string "Faster-than-Light" occurring nowhere in `supplement.tex` and no `\markboth` to put
anything in the running head either. The author block was written in commit `836b0a9` and had
not been touched since; the paper went to four authors in `f57095e`. The front matter of one
document moved and the front matter of the other did not.

It survived forty-eight rounds of review because every gate in this repository reads content.
There are checks on numbers, cross-document pointers, float labels, figure reading rules,
claim-to-equation agreement, cross-sentence dependency and per-corpus denominators, and not
one of them looks at a title block.

TC requires supplementary material to be submitted as a separate file. That is precisely the
circumstance in which a document has to be able to say what it belongs to.

v4 (2026-09-08) changed what "agree" means. The second author asked for the supplement to be
a single-author document, coherent on its own -- a postmortem of how the results were
obtained -- rather than an appendix under the paper's byline.

v5 (2026-09-29) splits the two roles. An outside editor read a 75-page single-author
supplement as an undecided paper, so the supplementary material TC receives is now
`supplement.tex`, under the paper's byline and organized by its sections, and the postmortem
is `postmortem.tex`, bylined to the first author alone as the second author asked, archived
with the data and not submitted. Both must say which paper they belong to; each must say which
of the two it is, on the title page and on every page.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
COMPANIONS = ("supplement.tex", "postmortem.tex")


def _source(name):
    path = REPO / name
    if not path.exists():                       # pragma: no cover - all three ship in the repo
        pytest.fail("%s not present" % name)
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


def _byline(name):
    return [" ".join(n.split()) for n in _names(_field(name, "author"))]


def _markboth(name):
    r"""Both groups of `\markboth{left}{right}`; the recto head is the second."""
    text = _source(name)
    m = re.search(r"\\markboth\s*\{", text)
    assert m, "%s has no \\markboth" % name
    left = _braced(text, m.end() - 1)
    after = text.index("{", m.end() - 1 + len(left) + 2)
    return left, _braced(text, after)


def _short_title():
    # Read from the paper rather than typed here: the pin said "Faster-than-Light" until v5
    # (28 Sep) changed the title, and a typed title is the stale-copy failure this file exists
    # to catch.
    return _field("paper.tex", "title").split(":")[0].strip()


class TestTheDocumentsAgreeOnWhoWroteThem:

    def test_the_supplement_carries_the_papers_byline(self):
        """The supplementary material is the paper's, submitted with it."""
        assert _byline("supplement.tex") == _byline("paper.tex"), (
            "the supplement is bylined %s and the paper %s"
            % (_byline("supplement.tex"), _byline("paper.tex")))

    def test_the_postmortem_is_bylined_to_the_papers_first_author(self):
        paper = _byline("paper.tex")
        assert _byline("postmortem.tex") == paper[:1], (
            "the postmortem is bylined %s; as the single-author record the second author asked "
            "for on 8 Sep it carries the paper's first author, %s, alone"
            % (_byline("postmortem.tex"), paper[:1]))

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_each_companion_names_every_author_of_the_paper(self, name):
        """A loose page must still say whose paper it accompanies."""
        block = _field(name, "author")
        for author in _byline("paper.tex"):
            surname = author.split()[-1]
            assert surname in block, (
                "%s's author block does not name %s, an author of the paper" % (name, surname))

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_each_companion_names_every_affiliation_the_paper_does(self, name):
        paper = _field("paper.tex", "author")
        block = _field(name, "author")
        for inst in ("Trinity College Dublin", "Chalmers", "W\\\"urzburg"):
            if re.search(inst, paper):
                assert re.search(inst, block), (
                    "the paper gives an affiliation at %s and %s does not"
                    % (inst.replace("\\\\", ""), name))

    def test_the_paper_still_has_two_authors(self):
        """If the author list ever changes, this file should be read, not silently passed.

        It worked. The list stood at four from `f57095e` until 2026-09-10, when two authors
        withdrew and this assertion failed rather than the byline changing under a green
        suite. The count is the whole point of the check, so it moves to two and keeps doing
        the same job; `test_author_withdrawals.py` pins the rest of the front matter to match.
        """
        assert len(_byline("paper.tex")) == 2


class TestEachDocumentSaysWhatItIs:
    r"""Separated from the paper, a file has to identify itself, and say which of the two it is."""

    def _paper_title_words(self):
        title = _field("paper.tex", "title")
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", title)
        return [w for w in plain.split() if len(w) > 3]

    @pytest.mark.parametrize("name", COMPANIONS)
    def test_each_title_carries_the_paper_title(self, name):
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", _field(name, "title"))
        missing = [w for w in self._paper_title_words() if w not in plain]
        assert not missing, (
            "%s's title does not contain the paper's; missing %s. A reader holding the "
            "separate file cannot tell what it belongs to" % (name, missing[:6]))

    def test_the_supplement_declares_itself_supplementary(self):
        assert "Supplementary Material for" in _field("supplement.tex", "title")

    def test_the_postmortem_declares_itself_the_record_and_not_the_supplement(self):
        title = " ".join(_field("postmortem.tex", "title").split())
        assert "Complete Record" in title and "Supplementary" not in title
        prose = " ".join(_source("postmortem.tex").split())
        assert "not part of the submission" in prose

    @pytest.mark.parametrize("name", ("paper.tex",) + COMPANIONS)
    def test_both_running_heads_are_set(self, name):
        r"""IEEEtran's one-column mode prints only the verso head, so the recto group is
        belt-and-braces rather than something a reader sees. It is still asserted, because a
        `\markboth` with an empty second group is a half-written command and the next person
        to change the class would inherit a blank recto."""
        left, recto = _markboth(name)
        assert left.strip() and recto.strip(), "%s has an empty running head" % name

    def test_the_supplements_recto_head_names_the_paper(self):
        assert _short_title() in _markboth("supplement.tex")[1], \
            "the supplement's recto head should name the paper"

    def test_the_supplement_head_says_it_is_supplementary(self):
        """This is the one that prints. A stray page must not read as the paper itself."""
        left, _recto = _markboth("supplement.tex")
        assert re.search(r"supplement", left, re.I), (
            "the supplement's verso head should mark it as supplementary material; it "
            "reads %r" % left)

    def test_the_postmortem_head_says_it_is_the_record(self):
        left, _recto = _markboth("postmortem.tex")
        assert re.search(r"complete record", left, re.I) and not re.search(
            r"supplement", left, re.I), (
            "the postmortem's verso head should mark it as the record, not as the supplement; "
            "it reads %r" % left)


class TestTheBuiltDocumentsIdentifyThemselves:
    """The source is not the artifact. Round 48 through 52 kept finding that the rendered
    page and the source disagreed about something, so this reads the PDFs."""

    @staticmethod
    def _page(name, n):
        import shutil
        import subprocess
        pdf = REPO / name
        assert pdf.exists(), "%s is missing" % name
        assert shutil.which("pdftotext"), "pdftotext is not on PATH"
        out = subprocess.run(["pdftotext", "-enc", "UTF-8", "-f", str(n), "-l", str(n),
                              str(pdf), "-"], capture_output=True).stdout
        return re.sub(r"\s+", " ", out.decode("utf-8", "replace"))

    def test_the_supplements_page_one_names_the_paper_and_every_author(self):
        first = self._page("supplement.pdf", 1)
        assert _short_title() in first, "the built supplement's first page does not name the paper"
        for surname in ("Ricou", "Duvignau"):
            assert surname in first, "the built supplement's byline omits %s" % surname

    def test_the_postmortems_page_one_names_the_paper_and_what_it_is(self):
        first = self._page("postmortem.pdf", 1)
        assert _short_title() in first
        assert "Complete Record" in first
        assert "Ricou" in first

    @pytest.mark.parametrize("page_no", [2, 3, 20])
    def test_every_supplement_page_carries_the_running_head(self, page_no):
        assert re.search(r"supplementary material", self._page("supplement.pdf", page_no),
                         re.I), (
            "page %d of the built supplement carries nothing marking it as supplementary; a "
            "loose page reads as the paper" % page_no)

    @pytest.mark.parametrize("page_no", [2, 3, 20])
    def test_every_postmortem_page_carries_its_running_head(self, page_no):
        assert re.search(r"complete record", self._page("postmortem.pdf", page_no), re.I), (
            "page %d of the built postmortem carries nothing marking it as the record; a loose "
            "page reads as the supplementary material" % page_no)

    def test_the_rule_can_fail(self):
        """The exact front matter round 52 found."""
        stale = r"\title{Supplementary Material:\\When the Interval Is Smaller Than the Instrument}"
        plain = re.sub(r"\\[a-zA-Z]+|[{}~%]", " ", stale)
        assert "Faster" not in plain
        assert _names("Gustavo~Pedro~Ricou") != _names(
            "Gustavo~Pedro~Ricou~and~Romaric~Duvignau")
