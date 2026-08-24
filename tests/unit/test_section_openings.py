r"""Every section opens with something a reader could disagree with.

The rule the manuscript is written to: a section's first sentence states the section's claim,
not what the section is about and not where to find things. A round-23 review found the one
place it had lapsed --- Section III-C opened with "Figure 1(a) names the four stamps;
Supplement S45 maps them onto the span each metric covers", pure navigation, while the
section's own claim sat four sentences down under a sentence saying it was the most useful
thing in the paper.

A claim cannot be recognised by machine. Navigation can. This checks the negative: a section
may not *open* on a cross-reference, because a cross-reference is never a claim. That catches
the lapse that happened and stays quiet on everything else, which is the most a mechanical
check should promise here. The positive half of the rule stays a human job, and the release
checklist says so.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"

#: Openings that are navigation rather than assertion. A first sentence beginning with any of
#: these tells the reader where to look before telling them what is true.
NAVIGATIONAL = (
    r"Figure~\ref", r"Fig.~\ref", r"Table~\ref", r"Section~\ref", r"Equation~\ref",
    r"Supplement~S", r"Supplements~S", r"The figure", r"The table", r"This section",
    r"In this section", r"Here we", r"We now", r"This subsection",
)


def _body():
    text = PAPER.read_text(encoding="utf-8")
    text = re.sub(r"\\begin\{(figure\*?|table\*?)\}.*?\\end\{\1\}", " ", text, flags=re.S)
    text = re.sub(r"(?m)%[^\n]*", " ", text)
    return text


def openings():
    """(heading, first sentence) for every section and subsection of the main text."""
    text = _body()
    heads = list(re.finditer(r"\\(sub)?section\{([^}]*)\}", text))
    out = []
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(text)
        body = text[m.end():end]
        body = re.sub(r"\\label\{[^}]*\}", " ", body)
        body = re.sub(r"\\begin\{enumerate\}|\\end\{enumerate\}|\\item", " ", body)
        body = re.sub(r"\\IEEEPARstart\{(.)\}\{([^}]*)\}", r"\1\2", body)
        body = " ".join(body.split())
        first = re.match(r"(.{0,400}?[.:])(?:\s|$)", body)
        out.append((m.group(2), first.group(1) if first else body[:200]))
    return out


class TestNoSectionOpensOnNavigation:

    def test_there_are_sections_to_check(self):
        """A parser that silently finds nothing would make the rule below vacuous."""
        got = openings()
        assert len(got) > 20, "expected the paper's full sectional structure, got %d" % len(got)
        assert all(first for _, first in got), "a section opened with nothing"

    @pytest.mark.parametrize("heading,first", openings(),
                             ids=[h[:38] for h, _ in openings()])
    def test_the_first_sentence_is_not_a_signpost(self, heading, first):
        bad = [p for p in NAVIGATIONAL if first.startswith(p)]
        assert not bad, (
            "%r opens on %s, which points rather than claims: %r -- the section's claim "
            "should lead and the pointer can follow it"
            % (heading, bad[0], first[:110]))


class TestTheRuleItself:

    def test_a_signpost_opening_is_recognised(self):
        assert any(r"Figure~\ref".startswith(p) or p == r"Figure~\ref"
                   for p in NAVIGATIONAL)
        first = r"Figure~\ref{fig:model}(a) names the four stamps."
        assert [p for p in NAVIGATIONAL if first.startswith(p)]

    def test_a_claim_opening_is_not(self):
        first = ("A negative span is not a clock failure but an ordering failure between two "
                 "stamping delays.")
        assert not [p for p in NAVIGATIONAL if first.startswith(p)]

    def test_the_parser_strips_the_drop_cap(self):
        """The introduction opens inside \\IEEEPARstart and must not read as markup."""
        got = dict(openings())
        assert got["Introduction"].startswith("Stated plainly")

    def test_a_pointer_later_in_the_sentence_is_allowed(self):
        """Only the opening is policed; a claim that cites a figure is still a claim."""
        first = r"No pair of arms in Fig.~\ref{fig:mechanism} overlaps."
        assert not [p for p in NAVIGATIONAL if first.startswith(p)]
