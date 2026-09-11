"""A pointer that resolves is not a pointer that is right.

Round 59 read the supplement's pointers *into* the article, which nothing had ever done, and
found four sentences sending a reader to Section V-A for material round 60 had taken out of
it: a start-up cost, an opening burst, topic auto-creation and connection setup, and a failure
of window selection. The article contains none of those words. Every one resolved through
`xr`, produced a real section number, and left the build clean. That is lesson 1ad ---
*"a pointer that stays valid while changing meaning is invisible to every gate"* --- arriving
from the one direction nobody had instrumented.

**The referee's proposed rule was attempted, measured, and could not be built.** It was: a
sentence naming a main-text section must share distinctive vocabulary with the section it
names. Measured over the 67 pointer sentences in this supplement, legitimate ones miss as many
as **10 of 24** content words against the *whole* article, because a supplement's job is to
say more than the article does. Round 59's four defects missed **2 to 4 of 4 to 8**. The fifth
pointer, the one round 59 checked and found correct, missed **1 of 6** --- and the word it
missed was "withdrawal", which round 60 had removed from the article at the same time. No
threshold separates those populations, and a rule tuned until the corpus passes is a rule that
has stopped testing anything.

**What is buildable is the half that does separate them.** Each of the four leaned on a phrase
the article does not contain *anywhere*: not in Section V-A, not in Section IV, nowhere. So the
inventory below names the phrases the supplement attributes to the article, and requires the
article to still contain them. It is short and it is maintained by hand, like the allow-list in
`test_ledger_coverage`, and for the same reason: the judgement of what a sentence leans on is
not one a regular expression makes well. When material leaves the article, this fires.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: Phrases the supplement attributes to the main text, and must therefore find there.
#:
#: A row earns its place by being *load-bearing*: the supplement's sentence is false if the
#: article does not carry it. Round 59's four defects are the worked examples --- each named
#: a phrase the article had stopped containing, and each is repaired to point at the
#: supplement section that carries it now, so none of them appears here as an article claim.
ATTRIBUTED = {
    "transport proxy":
        "the supplement calls S the transport proxy throughout, on the article's authority",
    "acknowledgment lag":
        "S40 and S24 both reason about A by the article's name for it",
    "negative-span rate":
        "the quantity most of the supplement's tables are of; the article defines it",
    "retention":
        "S22, S42 and S46 all turn on the article's definition of the retained fraction",
    "send lag":
        "renamed from 'scheduling lag' in v4.1; the supplement follows the article's word",
    "one-per-cent":
        "the audit threshold S27 sweeps; the article is where it is fixed",
}


def _macro_targets():
    """`mainX` -> the label it resolves to, with the xr prefix removed.

    Round 68, W4: the supplement imports the paper's labels under `P-`, so that the 26
    citation keys the two documents share stop being reported as multiply defined on every
    build. `\\ref{P-sec:audit}` is satisfied by the paper's `\\label{sec:audit}`, so the
    prefix is transport and the label is what this file is about.
    """
    supp = (REPO / "supplement.tex").read_text(encoding="utf-8")
    pairs = re.findall(r"\\newcommand\{\\(main[A-Za-z]+)\}\{\\ref\{([^}]+)\}\}", supp)
    return {name: re.sub(r"^P-", "", label) for name, label in pairs}


def _flat(path):
    text = (REPO / path).read_text(encoding="utf-8")
    text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    return " ".join(text.split())


def _sentences_with_pointers(text):
    """(macro, sentence) for every `Section~\\mainX{}` in the supplement."""
    out = []
    for m in re.finditer(r"Section~\\(main[A-Za-z]+)\{\}", text):
        start = max(text.rfind(". ", 0, m.start()) + 2, 0)
        end = text.find(". ", m.end())
        out.append((m.group(1), text[start:end if end > 0 else len(text)]))
    return out


class TestWhatTheSupplementAttributesToTheArticleIsInTheArticle:
    """The inventory above, checked against the article on every build."""

    @pytest.mark.parametrize("phrase", sorted(ATTRIBUTED))
    def test_the_article_still_carries_it(self, phrase):
        assert phrase in _flat("paper.tex").lower(), (
            "the supplement attributes %r to the article and the article no longer contains "
            "it (%s). Either restore it or repoint the supplement at whatever carries it now."
            % (phrase, ATTRIBUTED[phrase]))

    @pytest.mark.parametrize("phrase", sorted(ATTRIBUTED))
    def test_the_supplement_actually_uses_it(self, phrase):
        """A row for a phrase nobody attributes is a row that tests nothing."""
        assert phrase in _flat("supplement.tex").lower(), \
            "%r is inventoried but the supplement does not use it" % phrase

    def test_round_59s_four_phrases_are_no_longer_attributed_to_the_article(self):
        """The repair, pinned: each phrase now points at the supplement section that has it.

        "start-up cost" and "window selection" belong to S4, "opening burst" to S3, and the
        auto-creation reason is S9's own. None of them may go back to naming a main-text
        section, because the article has not carried them since round 60.
        """
        supp = _flat("supplement.tex")
        for macro, sentence in _sentences_with_pointers(supp):
            low = sentence.lower()
            for phrase in ("start-up cost", "opening burst", "auto-creation",
                           "window selection"):
                assert phrase not in low, (
                    "%r is attributed to the main text again, in a sentence naming %s; the "
                    "article has not carried it since round 60" % (phrase, macro))


class TestThePointersStillResolve:
    """Sense is the new half; resolution is the half that already worked, kept beside it."""

    def test_every_macro_names_a_label_the_article_defines(self):
        labels = set(re.findall(r"\\label\{([^}]+)\}", _flat("paper.tex")))
        missing = [(m, l) for m, l in _macro_targets().items() if l not in labels]
        assert not missing, "macros naming labels the article lacks: %s" % missing

    def test_the_supplement_points_at_the_article_somewhere(self):
        found = _sentences_with_pointers(_flat("supplement.tex"))
        assert len(found) > 40, \
            "only %d pointers found; the extractor is broken rather than the document clean" \
            % len(found)
