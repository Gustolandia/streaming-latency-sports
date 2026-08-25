r"""When one document says where content lives, is it telling the truth about the other?

Supplement S36 carried this sentence for two rounds:

    We record it here rather than in the main text because its mechanism is genuine
    wall-clock non-monotonicity, and placing it beside Mode A would invite exactly the
    clock-versus-stall conflation the paper separates.

The main text carried the whole case anyway --- five lines of it, with the same citation. The
two documents disagreed about where the case lived, and both were confident. Nothing could
see it: the citation resolved in both files, the reference count was right, every cross-
document pointer landed. What was wrong was a claim *about the documents*, and no gate read
those.

A placement claim is cheap to check when it carries a citation. If a sentence says the
material is here **rather than** in the main text, and the sentence cites a source, then the
main text citing that same source is a contradiction --- either the sentence is stale or the
relocation never happened. Both were true at different points in this file's history.

The rule is deliberately narrow. It fires only on the "rather than / not in the main text"
family, only when the sentence carries a citation, and it says nothing about placement claims
made without one, which are prose a reader must still check by hand. A narrow rule that
cannot be argued with is worth more here than a broad one that cries wolf: this suite has
already lost one gate to over-reach and had to rewrite it.

`ALLOWED` is for the case where both documents genuinely cite a source and the supplement's
sentence is about the *detail* rather than the mention. Each entry has to say why.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"

#: Sentence patterns that assert the material is *not* in the other document.
EXCLUSIVE = (
    r"rather than in the (?:main text|paper)",
    r"not in the (?:main text|paper)",
    r"only in the supplement",
    r"kept out of the (?:main text|paper)",
    r"absent from the (?:main text|paper)",
)

#: (citation key, why the paper may cite it anyway). Keyed by key so a sentence that moves
#: keeps its reason with the source rather than with a fragment of wording.
ALLOWED = {}


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    if not SUPP.exists():                               # pragma: no cover - always present
        pytest.skip("supplement not present")
    return SUPP.read_text(encoding="utf-8")


def _paragraph_at(text, pos):
    """The paragraph containing `pos`, bounded by blank lines.

    The paragraph and not the sentence, and the first version of this file got it wrong. In
    the defect that prompted the rule the citation sits in the sentence *before* the placement
    claim --- "the merged fix clamps the negative to zero ... ~\\cite{kafka19888}. We record it
    here rather than in the main text because ..." --- so a sentence-scoped reader finds no
    citation and reports the document clean. The self-test below is what caught that.
    """
    start = text.rfind("\n\n", 0, pos)
    start = 0 if start == -1 else start + 2
    end = text.find("\n\n", pos)
    end = len(text) if end == -1 else end
    return " ".join(text[start:end].split())


def exclusive_claims(text):
    """[(line, paragraph, [cited keys])] for every claim content is *not* in the paper."""
    out = []
    for pat in EXCLUSIVE:
        for m in re.finditer(pat, text, re.I):
            para = _paragraph_at(text, m.start())
            keys = [k.strip() for group in re.findall(r"\\cite\{([^}]*)\}", para)
                    for k in group.split(",")]
            out.append((text.count("\n", 0, m.start()) + 1, para, keys))
    return out


def cited_by(text):
    return {k.strip() for group in re.findall(r"\\cite\{([^}]*)\}", text)
            for k in group.split(",")}


class TestTheSupplementIsRightAboutWhatThePaperContains:

    def test_no_exclusive_claim_names_a_source_the_paper_cites(self, paper, supp):
        in_paper = cited_by(paper)
        bad = []
        for line, sentence, keys in exclusive_claims(supp):
            for key in keys:
                if key in in_paper and key not in ALLOWED:
                    bad.append("supplement.tex:%d  cites %s, which the main text also cites\n"
                               "      %s" % (line, key, sentence[:180]))
        assert not bad, (
            "the supplement says material is here rather than in the main text, and the main "
            "text cites the same source -- one of the two documents is out of date:\n  "
            + "\n  ".join(bad))

    def test_every_exemption_carries_a_reason(self):
        assert all(v and len(v) > 20 for v in ALLOWED.values())

    def test_no_exemption_is_stale(self, supp):
        """An entry for a source no exclusive claim mentions any more licences nothing."""
        named = {k for _, _, keys in exclusive_claims(supp) for k in keys}
        assert not [k for k in ALLOWED if k not in named], \
            "exemption(s) for a source no placement claim names: %s" % sorted(
                k for k in ALLOWED if k not in named)


class TestTheCheckCanFail:
    """The round-26 defect, reconstructed, plus the shapes that must not fire."""

    #: The shape the real one had: the citation one sentence above the claim, same paragraph.
    DEFECT = ("The fix clamps the negative to zero with no counter~\\cite{kafka19888} --- "
              "silent substitution. We record it here rather than in the main text because "
              "its mechanism is genuine wall-clock non-monotonicity.")

    def test_it_finds_the_defect_it_was_written_for(self):
        claims = exclusive_claims(self.DEFECT)
        assert claims, "the phrase must be recognised"
        assert "kafka19888" in claims[0][2], \
            "the citation is a sentence above the claim and must still be seen"
        assert "kafka19888" in cited_by(r"the broker adopted it~\cite{kafka19888}")

    def test_a_claim_with_no_citation_is_not_indicted(self):
        claims = exclusive_claims("Two items belong here rather than in the main text, which "
                                  "sits at the journal's twelve-page target.")
        assert claims and claims[0][2] == []

    def test_a_citation_in_another_paragraph_is_not_pulled_in(self):
        text = ("A cited claim~\\cite{elsewhere} stands alone.\n\nWe keep the rest here rather "
                "than in the main text for space.")
        assert exclusive_claims(text)[0][2] == []

    def test_here_rather_than_dropped_is_not_a_placement_claim(self):
        """S19 says a withdrawn phase is recorded "here rather than dropped". Different claim."""
        assert not exclusive_claims("It is recorded here rather than dropped because a phase "
                                    "removed without saying so is a hole in the record.")

    def test_the_live_documents_have_at_least_one_claim_to_police(self, supp):
        """If the phrasing ever changes wholesale this rule goes quiet; say so loudly."""
        assert exclusive_claims(supp), \
            "no placement claims found at all -- has the wording changed?"
