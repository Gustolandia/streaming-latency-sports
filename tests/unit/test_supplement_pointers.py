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


# ---------------------------------------------------------------- round 81 (R1)
#
# The gate above proves a pointer names a section that exists. It cannot prove the number printed
# beside the pointer is one that section prints. Round 81 found S12 calling "12.4x against 21.3x,
# pooled and with no floor" the overshoot "of Section VIII-B" a round after VIII-B had moved to
# 7.4 within runs above a 0.1% floor, and the first run of this check found two more: a factor
# credited to V-B that V-C prints, and a payload-parse cost credited to VIII-B that VIII-A prints.
# The pointer was right each time, and the number had moved.

#: Sentences that name a main-text section beside a ledger number that section does not print,
#: because the section is named for something else: the rule that produced the number, the
#: quantity it is contrasted with, the harness that ran it. Each carries its reason. Capped: the
#: defect this gate was written for read exactly like these until someone opened the section.
NUMBER_POINTER_EXEMPT = {
    "The sign check of Section~" + BS + "mainGate{} rejected":
        "names the rule that did the rejecting; the workstation's counts are S1's",
    "a different quantity from the inter-host clock offset of Section~" + BS + "mainTestbeds{}":
        "names the offset the H3 shrinkage is contrasted with, not the shrinkage",
    "the harness of Section~" + BS + "mainGenerality{} runs":
        "names the harness; the cross-host counts it ran are the supplement's",
}
NUMBER_POINTER_CAP = 5

LEVEL = {"section": 1, "subsection": 2, "subsubsection": 3}


def ledger_macros():
    ledger = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
    return set(re.findall(re.escape(BS) + r"newcommand\{" + re.escape(BS) + r"([A-Za-z]+)\}",
                          ledger))


def pointer_labels(tex):
    return dict(re.findall(re.escape(BS) + r"newcommand\{" + re.escape(BS)
                           + r"(main[A-Z]\w*)\}\{" + re.escape(BS) + r"ref\{P-([^}]+)\}\}", tex))


def section_source(paper, label):
    """The paper's source from the heading carrying `label` to the next heading of its level or
    above; '' when the label is absent."""
    at = paper.find(BS + "label{" + label + "}")
    heads = [(m.start(), LEVEL[m.group(1)]) for m in
             re.finditer(re.escape(BS) + r"(section|subsection|subsubsection)\*?\{", paper)]
    before = [h for h in heads if h[0] <= at]
    if at < 0 or not before:
        return ""
    start, level = before[-1]
    after = [h[0] for h in heads if h[0] > start and h[1] <= level]
    return paper[start:after[0] if after else len(paper)]


def numbers_beside_pointers(supp, paper, macros):
    """(sentence, missing macros) for each supplement sentence that names a main-text section
    beside a ledger macro that none of the named sections prints."""
    labels = pointer_labels(supp)
    out = []
    for s in sentences(supp):
        named = re.findall(re.escape(BS) + r"(main[A-Z]\w*)", s)
        used = {m for m in re.findall(re.escape(BS) + r"([A-Za-z]+)", s) if m in macros}
        if not named or not used:
            continue
        text = "".join(section_source(paper, labels.get(p, "")) for p in named)
        missing = sorted(m for m in used
                         if not re.search(re.escape(BS + m) + r"(?![A-Za-z])", text))
        if missing:
            out.append((s, missing))
    return out


@pytest.fixture(scope="module")
def macros():
    return ledger_macros()


def test_a_number_beside_a_main_text_pointer_is_one_that_section_prints(supplement, paper, macros):
    flagged = [(s, miss) for s, miss in numbers_beside_pointers(supplement, paper, macros)
               if not any(frag in s for frag in NUMBER_POINTER_EXEMPT)]
    assert not flagged, "the named section does not print these numbers:\n  %s" % (
        "\n  ".join("%s | %s" % (miss, s[:160]) for s, miss in flagged[:6]))


def test_the_number_pointer_exemptions_stay_few_and_each_still_applies(supplement, paper, macros):
    assert len(NUMBER_POINTER_EXEMPT) <= NUMBER_POINTER_CAP
    flagged = [s for s, _ in numbers_beside_pointers(supplement, paper, macros)]
    for frag in NUMBER_POINTER_EXEMPT:
        assert any(frag in s for s in flagged), "stale exemption, remove it: %s" % frag


def test_the_rule_catches_the_sentence_that_prompted_it():
    defs = BS + "newcommand{" + BS + "mainAuthors}{" + BS + "ref{P-sec:authors}}\n"
    stale = defs + ("This project has been caught once before, on the independence overshoot of "
                    "Section~" + BS + "mainAuthors{}, where the two estimators differ by $"
                    + BS + "indepOvershoot" + BS + "times$.")
    paper_now = (BS + "section{Discussion}\n" + BS + "subsection{For benchmark authors}\n"
                 + BS + "label{sec:authors}\nby a median factor of $" + BS
                 + "indepWithinFloored$.\n" + BS + "subsection{Limits}\n$" + BS
                 + "indepOvershoot$ lives elsewhere.\n")
    known = {"indepOvershoot", "indepWithinFloored"}
    assert numbers_beside_pointers(stale, paper_now, known)
    fixed = stale.replace(BS + "indepOvershoot", BS + "indepWithinFloored")
    assert not numbers_beside_pointers(fixed, paper_now, known)


def test_a_longer_macro_does_not_count_as_printing_its_prefix():
    defs = BS + "newcommand{" + BS + "mainX}{" + BS + "ref{P-sec:x}}\n"
    s = defs + "Section~" + BS + "mainX{} gives $" + BS + "hThreeShrinkage$."
    paper_x = BS + "section{X}\n" + BS + "label{sec:x}\n$" + BS + "hThreeShrinkageCI$\n"
    assert numbers_beside_pointers(s, paper_x, {"hThreeShrinkage", "hThreeShrinkageCI"})


def test_an_absent_label_names_no_text():
    assert section_source(BS + "section{A}\n" + BS + "label{sec:a}\n", "sec:missing") == ""
    assert section_source("no headings " + BS + "label{sec:a}", "sec:a") == ""
