r"""Does a superlative in the prose agree with the ranking the data actually has?

Section I said, for twenty-nine rounds:

    the run-queue stall distribution's largest mode sits at \baseSliceMs~ms

Figure 8 prints the three modes at 20.0%, 13.5% and 10.5%, and the one at the base slice is
the one holding 10.5%. It is the *smallest* of the three. Section V-D had it right and used a
different word --- "the last" --- so the two halves of the paper disagreed about a ranking the
paper itself publishes, in its most-read paragraph, and nothing saw it.

Nothing could see it. Every gate here polices a *value*: whether it is emitted, whether the
prose reads it from its macro, whether the caption reaches it. "Largest" is not a value, it is
a claim about the order of several values, and the ledger had never been asked to compute the
order. `test_ledger_coverage` could not have helped either way --- it skips bare integers by
design, and a rank is exactly that.

So the emitter now computes the rank. `\tracedModeRank` is where the argued-about mode sits
among all the modes by share, and `\tracedModeTopShare` is the share of the biggest one. The
rule below reads the rank rather than hard-coding the answer: if a recomputation ever makes
this mode the largest, the rule relaxes by itself instead of having to be remembered.

The check is deliberately narrow. It polices superlatives *about the traced stall mode*, which
is the one ranking claim either document makes about an emitted quantity. A general "check
every adjective" rule would be unmaintainable and would cry wolf; this one has a denominator.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
DOCS = ("paper.tex", "supplement.tex")

#: Words that assert a quantity is first in some order.
SUPERLATIVES = ("largest", "biggest", "greatest", "dominant", "most common", "principal",
                "predominant", "chief")

#: Macros that name the traced stall mode. A superlative in the same sentence as one of these
#: is a claim that the mode ranks first among the modes.
MODE_ANCHORS = (r"\baseSliceMs", r"\tracedModeShare", r"\tracedModeLo")


def _macros():
    if not GENERATED.exists():                          # pragma: no cover - generated at build
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$",
                           GENERATED.read_text(encoding="utf-8"), re.M))


def sentences_with(text, anchors):
    """Every sentence containing one of `anchors`, whitespace-normalized."""
    out = []
    for m in re.finditer("|".join(re.escape(a) for a in anchors), text):
        start = max(text.rfind(". ", 0, m.start()), text.rfind("\n\n", 0, m.start()), 0)
        end = text.find(". ", m.end())
        end = len(text) if end == -1 else end + 1
        out.append((text.count("\n", 0, m.start()) + 1,
                    " ".join(text[start:end].split())))
    return out


def superlatives_in(sentence):
    low = sentence.lower()
    return [w for w in SUPERLATIVES if re.search(r"\b" + re.escape(w) + r"\b", low)]


class TestTheModeIsNotCalledSomethingItIsNot:

    def test_the_rank_is_emitted(self):
        """Without the rank there is nothing to check the adjective against."""
        m = _macros()
        assert "tracedModeRank" in m, "emit_paper_numbers must publish the mode's rank"
        assert "tracedModes" in m and "tracedModeTopShare" in m
        assert 1 <= int(m["tracedModeRank"]) <= int(m["tracedModes"])

    @pytest.mark.parametrize("doc", DOCS)
    def test_no_superlative_unless_the_mode_ranks_first(self, doc):
        m = _macros()
        rank = int(m["tracedModeRank"])
        text = (REPO / doc).read_text(encoding="utf-8")
        bad = []
        for line, sentence in sentences_with(text, MODE_ANCHORS):
            found = superlatives_in(sentence)
            if found and rank != 1:
                bad.append("%s:%d  %s -- the mode ranks %s of %s by share (the biggest holds "
                           "%s%%, this one %s%%)\n      %s"
                           % (doc, line, found, m["tracedModeRank"], m["tracedModes"],
                              m["tracedModeTopShare"], m["tracedModeShare"], sentence[:150]))
        assert not bad, (
            "superlative(s) applied to a mode that is not first in the order the data gives:\n  "
            + "\n  ".join(bad))

    def test_the_body_and_the_introduction_use_the_same_word(self):
        """Section V-D says "the last". Whatever Section I says, it must not say otherwise."""
        text = (REPO / "paper.tex").read_text(encoding="utf-8")
        rank, total = (int(_macros()[k]) for k in ("tracedModeRank", "tracedModes"))
        if rank != total:                               # pragma: no cover - it is 3 of 3 today
            return
        for line, sentence in sentences_with(text, MODE_ANCHORS):
            assert not superlatives_in(sentence), (
                "the mode is last of %d by share, so it is also the smallest; "
                "paper.tex:%d calls it otherwise" % (total, line))


class TestTheCheckCanFail:
    """The round-29 defect, reconstructed, and the shapes that must not fire."""

    DEFECT = (r"A practitioner is wrong by a factor. The run-queue stall distribution's "
              r"largest mode sits at $\baseSliceMs$~ms (Section V-D), three times the quantum.")
    FIXED = (r"A practitioner is wrong by a factor. The run-queue stall distribution's "
             r"last mode sits at $\baseSliceMs$~ms (Section V-D), three times the quantum.")

    def test_it_finds_the_defect_it_was_written_for(self):
        found = sentences_with(self.DEFECT, MODE_ANCHORS)
        assert found, "the anchor must be recognised"
        assert superlatives_in(found[0][1]) == ["largest"]

    def test_the_repair_passes(self):
        found = sentences_with(self.FIXED, MODE_ANCHORS)
        assert found and not superlatives_in(found[0][1])

    def test_a_superlative_about_something_else_is_not_indicted(self):
        """"the largest payload" is a different claim and has no business failing here."""
        text = r"The largest payload is 256 KB. The mode sits at $\baseSliceMs$~ms."
        found = sentences_with(text, MODE_ANCHORS)
        assert found and not superlatives_in(found[0][1])

    def test_a_sentence_without_the_anchor_is_not_read(self):
        assert not sentences_with("The largest mode is elsewhere.", MODE_ANCHORS)

    def test_word_boundaries_hold(self):
        assert not superlatives_in("the enlargement of the window")
