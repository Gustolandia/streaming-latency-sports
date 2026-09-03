r"""Cross-references that LaTeX cannot check, because they are written as prose.

Both documents point at supplement sections by number in running text --- "Supplement~S23",
"supplementary material S27" --- rather than with `\ref`. There are more than sixty of them,
and until round 45 nothing verified a single one. LaTeX has nothing to warn about: to the
compiler they are words.

What round 45 found at the end of one of those chains. Supplement S31 makes the strongest
claim in Section V --- nine arms, classified in advance by their phase denominator, seven
predicted full and two predicted flat, and every one of them behaving as predicted --- and
said the table backing it was in S27. S27 said the table had gone back to the main text. The
main text had two tables and neither was it. The table was real, correct and gated the whole
time; it was in S23. It had been in the main text for one revision at a reviewer's request,
left again when the page budget tightened, and the move updated neither signpost. So a
nine-fold confirmed prediction reached the reader as a sentence with a pointer to nowhere,
in a paper whose thesis is that a reader should not have to take a number on trust.

Three rules here, in increasing strictness:

  * every pointed-at section exists;
  * a pointer that promises an exhibit --- "the table in S27 states", "S31 draws" --- lands
    on a section that has a float;
  * no section whose own body says its content moved elsewhere is the target of a pointer,
    which is the specific shape of the S31 -> S27 chain.

The third is the one that would have caught it, and it is the one worth keeping: a forwarding
address is not a destination, and a document that leaves them behind will grow more.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: Verbs that promise the reader will find an exhibit, not just discussion, at the far end.
EXHIBIT_VERBS = (
    "states", "gives", "draws", "lists", "tabulates", "plots", "shows", "reproduces",
    "tabulate", "table",
)

#: Phrases by which a section admits its content is somewhere else. A pointer that lands on
#: one of these has not reached the evidence; it has reached a forwarding address.
FORWARDING = (
    "is back in the main text",
    "is not duplicated here",
    "returned to the main text",
    "moved to s",
)


def _read(name):
    r"""The document with its LaTeX comments removed.

    Comments must go before anything reads context around a pointer. A `%` line after
    "(Supplement~S2)" explaining why a figure moved put the word "table" inside the sweep's
    context window and produced a finding about a sentence no reader will ever see. An
    escaped \% is not a comment.
    """
    tex = (REPO / name).read_text(encoding="utf-8")
    return re.sub(r"(?<!\\)%.*", "", tex)


def _sections():
    r"""{number: body} for every `\section{S<n>. ...}` in the supplement."""
    tex = _read("supplement.tex")
    marks = [(int(m.group(1)), m.start()) for m in
             re.finditer(r"\\section\{S(\d+)\.", tex)]
    out = {}
    for i, (num, at) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(tex)
        out[num] = tex[at:end]
    return out


def _pointers():
    """Every prose pointer in either document, as (source file, section number, context)."""
    pat = re.compile(
        r"(?:Supplements?~?\s*|supplementary material~?\s*)S(\d+)(?:\.\d+)?", re.I)
    found = []
    for name in ("paper.tex", "supplement.tex"):
        tex = _read(name)
        for m in pat.finditer(tex):
            context = re.sub(r"\s+", " ", tex[m.start(): m.start() + 160])
            found.append((name, int(m.group(1)), context))
    return found


@pytest.fixture(scope="module")
def sections():
    return _sections()


@pytest.fixture(scope="module")
def pointers():
    return _pointers()


class TestEveryProsePointerHasADestination:

    def test_the_documents_still_point_at_supplement_sections_in_prose(self, pointers):
        """If this drops to zero the rest of the file is vacuous and should be deleted."""
        assert len(pointers) >= 40, (
            "only %d prose pointers found; the regex has stopped matching the house form"
            % len(pointers))

    def test_every_pointed_at_section_exists(self, sections, pointers):
        missing = sorted({(src, num) for src, num, _ in pointers if num not in sections})
        assert not missing, (
            "these point at supplement sections that do not exist: %s"
            % ", ".join("%s -> S%d" % (s, n) for s, n in missing))

    def test_a_pointer_promising_an_exhibit_lands_on_one(self, sections, pointers):
        """"The table in S27 states each rate's cell width" must find a float in S27."""
        bad = []
        for src, num, context in pointers:
            low = context.lower()
            if not any(v in low for v in EXHIBIT_VERBS):
                continue
            body = sections.get(num, "")
            if r"\begin{table}" in body or r"\begin{figure}" in body:
                continue
            bad.append("%s -> S%d (%s...)" % (src, num, context[:70].strip()))
        assert not bad, (
            "these promise the reader an exhibit and land on a section with no table or "
            "figure: %s" % "; ".join(bad))

    def test_no_pointer_lands_on_a_forwarding_address(self, sections, pointers):
        """The S31 -> S27 defect, stated as a rule.

        A section that says its content is elsewhere is not a destination. Either the pointer
        should name the real location or the section should hold the thing again.
        """
        bad = []
        for src, num, context in pointers:
            body = sections.get(num, "").lower()
            hit = next((f for f in FORWARDING if f in body), None)
            if hit is None:
                continue
            # Naming the real destination in the same breath is a redirection a reader can
            # follow, not a dead end: "S27 (moved to S23)" is fine.
            if re.search(r"moved to s\d+|is table~", body[:600]):
                continue
            bad.append("%s -> S%d, whose body says %r" % (src, num, hit))
        assert not bad, (
            "these point at a section that says its content is somewhere else: %s"
            % "; ".join(bad))


class TestTheRuleWouldHaveCaughtTheDefect:
    """Round 45's chain, reconstructed, so the sweep is known to have teeth."""

    def test_a_forwarding_stub_is_detected(self):
        body = ("the table of replicate spread, which this section previously held, is back "
                "in the main text: the reviewer of v2.5 was right. it is not duplicated here.")
        assert any(f in body for f in FORWARDING)

    def test_a_real_section_is_not(self):
        body = ("every commensurate arm shows the spread its position predicts, and this is "
                "the table that lets a reader check it one rate at a time.")
        assert not any(f in body for f in FORWARDING)

    def test_an_exhibit_verb_is_recognised(self):
        context = "the grid table in supplementary material S27 states each rate's cell width"
        assert any(v in context.lower() for v in EXHIBIT_VERBS)
