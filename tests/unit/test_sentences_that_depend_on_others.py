r"""Sentences whose truth lives in a different sentence, and sometimes a different document.

Rounds 48, 49 and 50 each found a defect of one shape: an edit in one place quietly falsified
a sentence somewhere else that depended on it. The gates this project already has are very
good at numbers and at pointers, and blind to this, because nothing about either sentence is
individually wrong.

**The conjunction that lost its antecedent.** Section II-A read

    Nor is the survey one-sided: Supplement S36 gives every row ...
    Nor is the architecture that produces those spans a blunder to be designed away ...

a matched pair. Round 49 cut the first for the page budget, and the second was left following
an affirmative sentence, where "Nor is X" has nothing to negate. Both halves were fine; the
join was not.

**The claim about the other document's silence.** Round 48 added a sentence to S23 saying the
main text "spends a line on each" of three tables, which was false for one. Round 49 fixed it
twice, in the supplement and in the main text, and the two fixes then disagreed: the
supplement said the selection bound "answers a question the main text does not raise" while
Section VI-A, edited in the same round, had begun to raise exactly that question.

A claim about what another document *does not* say is the worst kind here, because it is
falsified by an edit somewhere the author is not looking, and it reads as true right up until
someone checks. So the rule is not to assert the other document's silence: say what this
document holds, and point.

Neither rule is clever. Both are the kind that only pay when a document is edited in two
places under a page budget, which is exactly what the last three rounds were.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex")

#: Words that make a preceding clause negative enough for "Nor"/"Neither" to attach to.
#: "rather than Y" is included because it negates Y as plainly as "not Y" does: the Threats
#: paragraph's "readings of source rather than measured deployments" is what the "Nor is the
#: guard confined ..." after it attaches to, and that join is correct.
NEGATIVES = re.compile(
    r"\brather\s+than\b|"
    r"\b(?:not|no|none|never|neither|nor|nothing|nobody|cannot|can't|without|"
    r"un\w+|\w+n't|fails?|failed|declines?|declined|refuses?|lacks?)\b", re.I)


def _prose(name):
    path = REPO / name
    if not path.exists():                       # pragma: no cover - both ship in the repo
        pytest.skip("%s not present" % name)
    text = re.sub(r"(?m)^%.*$", "", path.read_text(encoding="utf-8"))
    # Floats carry their own register and their own gates; displayed maths is not prose.
    text = re.sub(r"\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}", " ", text, flags=re.S)
    text = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", " . ", text, flags=re.S)
    return text


@pytest.fixture(scope="module", params=DOCS)
def doc(request):
    return request.param, _prose(request.param)


class TestNoConjunctionLostItsAntecedent:
    """"Nor is X" needs something negative in front of it."""

    #: Sentence-initial "Nor" only. "Neither" is excluded on purpose: it carries its own
    #: negation and needs nothing in front of it -- "Neither failure appears in the output",
    #: "Neither asks what a millisecond stamp does" are determiner and pronoun uses, and both
    #: documents are full of correct ones. It is "Nor", the coordinating conjunction, that
    #: has to attach to a negative clause, and it was a "Nor" that round 49 stranded.
    OPENER = re.compile(r"(?<=[.!?])\s+(Nor)\b")

    def test_every_negative_conjunction_has_something_to_negate(self, doc):
        name, text = doc
        bad = []
        for m in self.OPENER.finditer(text):
            before = text[max(0, m.start() - 400):m.start()]
            # The clause it attaches to is the sentence immediately before.
            prev = re.split(r"(?<=[.!?])\s+", before.strip())[-1] if before.strip() else ""
            if NEGATIVES.search(prev):
                continue
            line = text.count("\n", 0, m.start()) + 1
            bad.append("%s:%d  %r follows %r"
                       % (name, line, m.group(1),
                          re.sub(r"\s+", " ", prev)[-90:].strip()))
        assert not bad, (
            "a negative conjunction with nothing to negate; the sentence it paired with was "
            "probably cut:\n  " + "\n  ".join(bad))

    def test_the_rule_can_fail(self):
        """The exact join round 49 broke, and the one it used to have."""
        broken = ("The tool computes its percentiles by integer division. "
                  "Nor is the architecture a blunder.")
        intact = ("The survey is not one-sided. "
                  "Nor is the architecture a blunder.")
        for text, expect_bad in ((broken, True), (intact, False)):
            m = self.OPENER.search(text)
            assert m, "the opener pattern stopped matching"
            prev = re.split(r"(?<=[.!?])\s+", text[:m.start()].strip())[-1]
            assert bool(NEGATIVES.search(prev)) is not expect_bad


class TestNoDocumentAssertsTheOtherOnesSilence:
    r"""Do not claim the other document does not say something.

    Such a claim is falsified by an edit in a file the author is not reading, and it reads as
    true until someone checks. Round 49 introduced one and round 50 found it, one round later,
    already false.

    Claims about what the main text *does* -- "Section VI-A raises", "the main text keeps the
    inference" -- are fine and common here: they are checkable by a reader in one hop, and
    when they rot they rot loudly. It is the negative that hides.
    """

    SILENCE = re.compile(
        r"(?:the\s+)?main\s+text\s+(?:does\s+not|doesn't|never)\s+"
        r"(raises?|mentions?|says?|discusses|discuss|treats?|names?|reports?|makes?)\b", re.I)

    def test_the_supplement_does_not_assert_the_main_text_is_silent(self):
        text = _prose("supplement.tex")
        bad = []
        for m in self.SILENCE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 80):m.start() + 90])
            bad.append("supplement.tex:%d  %r\n        ...%s..."
                       % (line, m.group(0), ctx.strip()))
        assert not bad, (
            "the supplement asserts the main text is silent about something; an edit to the "
            "main text falsifies this without touching the supplement. State what this "
            "document holds and point instead:\n  " + "\n  ".join(bad))

    def test_the_rule_leaves_capability_claims_alone(self):
        """Two legitimate neighbours must keep passing: they describe what a *check* or a
        *section* does, not what the main text failed to mention."""
        for legal in ("The integrity check of the main text does not catch",
                      "Section~\\mainModeB{} of the main text does not do"):
            assert not self.SILENCE.search(legal), (
                "the rule caught a capability claim: %r" % legal)

    def test_the_rule_can_fail(self):
        assert self.SILENCE.search("A third answers a question the main text does not raise:")
        assert self.SILENCE.search("the main text never mentions the selection bound")
