r"""Every supplement pointer to the main text names what it points at.

Round 79 (R1). S19's "Threats to validity (full)" still described an earlier paper. It pointed
"(the main text)" at an H1 slope, a netem sweep, a 15/15 count and "timer granularity on both
platforms", and the main text contains none of them. The ledger gate catches a typed number;
nothing caught a typed pointer, and the source carried 25 bare "(the main text)" parentheses
and more than a hundred other mentions without a label. When the supplement was split from the
article, a whole class of `\ref{sec:...}` had become the words "the main text", which resolve
to nothing and so can never break.

The supplement already defines a `\main...` macro for each main-text section it cites. A pointer
that uses one resolves through xr to a label, and a label that disappears breaks the build. So:
every sentence that mentions the main text carries a `\main...` macro or a `\ref{P-...}`, unless
it is one of a short, capped list of phrasings that point at nothing (where an exhibit came
from; statements about the document as a whole).
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)

#: Mentions of the main text that are not pointers. Capped: a list that grows to admit whatever
#: fails is the gate turned off one entry at a time.
NOT_POINTERS = (
    r"(?:moved|demoted)(?: \w+)?(?: here)? (?:from|out of) the main text",
    r"rather than in the main text",
    r"made in the main text",
    r"skip to the main text",
    r"discover it in the main text",
    r"checkable sentence of the main text",
    r"every number in the main text",
    r"the main text is organized",
)
ALLOW_CAP = 10

MACRO = re.compile(re.escape(BS) + r"main[A-Z]\w*|" + re.escape(BS) + r"ref\{P-")


def body(tex):
    """The source with LaTeX comments removed and whitespace collapsed."""
    kept = []
    for line in tex.split("\n"):
        if line.lstrip().startswith("%"):
            continue
        kept.append(re.split(r"(?<!" + re.escape(BS) + r")%", line)[0])
    return " ".join(" ".join(kept).split())


def sentences(tex):
    return re.split(r"(?<=[.!?])\s+(?=[A-Z" + re.escape(BS) + r"(])", body(tex))


def bare_pointers(tex):
    """Sentences that mention the main text with nothing a reader or a build could resolve."""
    out = []
    for s in sentences(tex):
        low = s.lower()
        if "the main text" not in low or MACRO.search(s):
            continue
        if any(re.search(p, low) for p in NOT_POINTERS):
            continue
        out.append(s)
    return out


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


def test_no_supplement_pointer_to_the_main_text_is_bare(supplement):
    bad = bare_pointers(supplement)
    assert not bad, "%d bare pointer(s) to the main text; name the section:\n  %s" % (
        len(bad), "\n  ".join(s[:160] for s in bad[:8]))


def test_the_exemptions_stay_few():
    assert len(NOT_POINTERS) <= ALLOW_CAP


def test_every_pointer_macro_resolves_to_a_label_in_the_paper(supplement, paper):
    defs = re.findall(re.escape(BS) + r"newcommand\{" + re.escape(BS)
                      + r"(main[A-Z]\w*)\}\{" + re.escape(BS) + r"ref\{P-([^}]+)\}\}", supplement)
    assert len(defs) >= 20
    for name, label in defs:
        assert BS + "label{" + label + "}" in paper, "%s points at a label the paper lacks" % name


def test_the_defect_that_prompted_this_is_caught():
    """Mutation: the four stale pointers the referee found, each as it was written."""
    for stale in ("H1's quantitative slope (the main text) is estimated from a delay sweep.",
                  "The network configuration passes 15/15 on the same hardware (the main text).",
                  "This is a scheduling delay, and the main text additionally reports the timer "
                  "granularity on both platforms.",
                  "The threshold was fixed late; the sensitivity analysis of the main text exists "
                  "partly to compensate."):
        assert bare_pointers(stale), stale


def test_a_labelled_pointer_and_a_provenance_note_pass():
    assert not bare_pointers("Section~" + BS + "mainGate{} of the main text rejects them.")
    assert not bare_pointers("Two exhibits moved here from the main text.")
    assert not bare_pointers("% the main text says so, in a comment\nNothing here.")
