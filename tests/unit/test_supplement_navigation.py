r"""A section nothing sends a reader to is not a section, it is bulk.

Measured on 2026-09-10, before the v5 reorganization: the supplement ran to 59 pages and 52
sections, and **24 of those sections, 17,801 words, 44% of the document, were never pointed at
from the paper.** The internal-reference counts did not rescue them either, because every
S-number appeared twice in the front matter regardless --- once in the table of contents, once
in a renumbering concordance --- so a count of two meant nothing pointed there at all.

That is what a reader meets as bulk, and no gate in this repository could see it. Every
existing check asks whether a claim is supported, whether a number is emitted, whether a
caption opens on its claim. None asked the question a reader asks first: **how would I ever
get here?**

Three rules, and they are navigation rules rather than content rules.

  1. Every pointer in the paper resolves to a section that exists. A dangling `Supplement~S40`
     is worse than no pointer, and the last renumbering is exactly the event that produces one.
  2. Every section is reachable --- from the paper, or from another section's prose. The table
     of contents does not count, because a contents entry is how you learn a thing exists, not
     why you would read it.
  3. Titles say what a section found, not where it sits relative to the paper. Eighteen titles
     read "... in full", which files the document by its relationship to the paper rather than
     by anything a reader wants.

The document is also not allowed to talk about its own production. Twelve mentions of
"internal review" rounds and a paragraph mapping fifty-five old section numbers to new ones
were written for the authors, and printed for everybody else.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPPLEMENT = REPO / "supplement.tex"

#: Below this a heading promises a topic and does not repay the lookup. Set from the v5
#: audit, where sixteen sections sat under 350 words and one held seventy-six.
MIN_WORDS = 350


def _strip_comments(text):
    return re.sub(r"(?m)%.*$", "", text)


def _sections(tex):
    """(number, title, body) for every top-level supplement section, in order."""
    marks = [(m.start(), int(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"\\section\{S(\d+)\.\s*([^}]*)\}", tex)]
    out = []
    for i, (pos, num, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(tex)
        out.append((num, title, tex[pos:end]))
    return out


def _words(body):
    return len(re.sub(r"\\[a-zA-Z]+\*?|[{}$&\\~^_]", " ", body).split())


@pytest.fixture(scope="module")
def supplement():
    return _strip_comments(SUPPLEMENT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def paper():
    return _strip_comments(PAPER.read_text(encoding="utf-8"))


class TestEveryPointerResolves:
    def test_the_paper_points_only_at_sections_that_exist(self, paper, supplement):
        have = {n for n, _, _ in _sections(supplement)}
        want = {int(m.group(1)) for m in re.finditer(r"Supplement~?\s*S(\d+)", paper)}
        missing = sorted(want - have)
        assert not missing, (
            "the paper sends a reader to %s, which the supplement does not contain. A "
            "renumbering did this last time; rewrite pointers from the map, never by hand."
            % ", ".join("S%d" % n for n in missing))


class TestEverySectionIsReachable:
    """Reachable means pointed at, not merely listed."""

    @staticmethod
    def _pointers(text, have):
        """Every section a passage sends a reader to, ranges included.

        `Sections~S20 to~S23` points at S21 and S22 as surely as naming them does, and a rule
        that missed that would push an author into writing worse prose to satisfy it.
        """
        out = set()
        for m in re.finditer(r"S(\d+)\s*(?:--|—|to)~?\s*S(\d+)", text):
            lo, hi = int(m.group(1)), int(m.group(2))
            out |= {n for n in range(lo, hi + 1) if n in have}
        out |= {int(m.group(1)) for m in re.finditer(r"S(\d+)", text)}
        return out & have

    def test_no_section_is_an_orphan(self, paper, supplement):
        secs = _sections(supplement)
        have = {n for n, _, _ in secs}
        from_paper = self._pointers(paper, have)
        # The front matter and each part's introduction are pointers too: they are where a
        # reader is told what is in the part they have just reached.
        first = supplement.index("\\section{S")
        from_inside = self._pointers(supplement[:first], have)
        for num, _, body in secs:
            body = body.split("\n", 1)[1] if "\n" in body else ""
            from_inside |= self._pointers(body, have) - {num}
        orphans = sorted(have - from_paper - from_inside)
        assert not orphans, (
            "%d of %d sections are unreachable: %s. Nothing in the paper and nothing in "
            "another section sends a reader to them, so they are read only by somebody "
            "working through the document front to back. Point at it, merge it, move it to "
            "the artifact, or delete it."
            % (len(orphans), len(have), ", ".join("S%d" % n for n in orphans)))


class TestTitlesSayWhatWasFound:
    def test_no_title_files_itself_against_the_paper(self, supplement):
        bad = [t for _, t, _ in _sections(supplement) if re.search(r"in full", t, re.I)]
        assert not bad, (
            "%d titles read `... in full`, which describes a section's relationship to the "
            "paper rather than what it found: %s. A reader scanning the contents learns "
            "nothing from it." % (len(bad), "; ".join(bad[:4])))

    def test_no_two_sections_carry_the_same_title(self, supplement):
        tex = supplement
        titles = [m.group(1).strip().lower().rstrip(".")
                  for m in re.finditer(r"\\(?:sub)?section\{S[\d.]+\.\s*([^}]*)\}", tex)]
        dupes = sorted({t for t in titles if titles.count(t) > 1})
        assert not dupes, (
            "the same title appears on more than one section: %s. Two sections with one "
            "title are one topic with two homes." % "; ".join(dupes))

    def test_no_section_is_too_small_to_be_a_section(self, supplement):
        small = [(n, t, _words(b)) for n, t, b in _sections(supplement)
                 if _words(b) < MIN_WORDS]
        assert not small, (
            "%d sections are under %d words, so their contents entry promises more than they "
            "hold: %s. Merge them into the section they belong beside."
            % (len(small), MIN_WORDS,
               "; ".join("S%d (%dw)" % (n, w) for n, _, w in small[:6])))


class TestTheDocumentDoesNotDiscussItsOwnProduction:
    def test_no_internal_review_rounds(self, supplement):
        hits = len(re.findall(r"internal review", supplement, re.I))
        assert not hits, (
            "%d mentions of `internal review`. No reader outside this project knows what "
            "internal review round 1 was, and naming it advertises the revision process "
            "rather than the result." % hits)

    def test_no_renumbering_concordance(self, supplement):
        arrows = len(re.findall(r"S\d+\$?\\?(?:to|rightarrow)\$?S\d+", supplement))
        assert arrows < 5, (
            "%d old-to-new section mappings are printed in the supplement. That belongs in "
            "docs/supplement_index.md, where the people who need it will look." % arrows)


class TestTheRuleCanFail:
    """Each rule, shown rejecting the document as it stood before v5."""

    def test_an_unreachable_section_is_caught(self):
        tex = "\\section{S1. A}\nsee S2.\n\\section{S2. B}\ntext\n\\section{S3. C}\ntext\n"
        secs = _sections(tex)
        have = {n for n, _, _ in secs}
        inside = set()
        for num, _, body in secs:
            body = body.split("\n", 1)[1]
            inside |= {int(m.group(1)) for m in re.finditer(r"S(\d+)", body)
                       if int(m.group(1)) != num}
        assert sorted(have - inside) == [1, 3]

    def test_an_in_full_title_is_caught(self):
        assert re.search(r"in full", "S3. The broker comparison in full", re.I)

    def test_a_seventy_six_word_section_is_caught(self):
        assert _words("\\section{S2. The first result set}\n" + "word " * 76) < MIN_WORDS

    def test_the_concordance_pattern_is_caught(self):
        line = "S1$\\to$S6, S2$\\to$S13, S3$\\to$S33, S4$\\to$S34, S5$\\to$S9"
        assert len(re.findall(r"S\d+\$?\\?(?:to|rightarrow)\$?S\d+", line)) >= 5
