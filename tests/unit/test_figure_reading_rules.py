r"""A figure caption that supplies a reading rule must not break it on its own exhibit.

Round 45 found Figure 4's caption stating its reading rule without a direction. That was
fixed: the rule now says which side means what. Round 49 then found the *next* layer down —
the caption applied its own repaired rule to the one marginal marker and got the side wrong.

    "a marker below its bar is an arm that rejects and a marker above one is not"
    ...
    "the open circle is the one powered arm that does not, and it sits at the edge of its
     bar rather than below it."

The ledger puts that arm at 0.2647 against a null band opening at 0.2680. It is below. By
the caption's own rule it therefore rejects, while the legend labels it unresolved. The gap
is 0.0033 — under a point at print size, smaller than the marker's own stroke — so no eye
was ever going to settle it, and none did across four rounds.

The cause is not a typo. The bars draw the **uncorrected** null; the verdicts come from a
Holm correction across the family, which is not a geometric property and cannot appear in the
picture at all. For nine arms the two agree and the discrepancy is invisible. At the one
margin it is the whole story, and the margin is where a careful reader looks hardest.

So this file pins the two things that can drift apart:

* the side-word the caption prints is emitted from the ledger, not typed, and must match
  where the committed null actually puts that marker;
* the caption must not claim the picture settles a verdict that only the correction settles.

The general rule the class suggests — a caption that supplies a decision rule must be
checkable against the data it decides on — is not something a test can enforce in general.
What it can do is hold the one exhibit where the paper makes that claim explicitly.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"


@pytest.fixture(scope="module")
def paper():
    return re.sub(r"(?<!\\)%.*", "", (REPO / "paper.tex").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def macros():
    if not GENERATED.exists():                      # pragma: no cover - generated at build
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{(.*)\}",
                           GENERATED.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def caption(paper):
    m = re.search(r"\\caption\{(\\textbf\{Grid membership.*?)\}\s*\n\\label\{fig:grid\}",
                  paper, re.S)
    assert m, "could not find Figure 4's caption; the anchor changed"
    return m.group(1)


@pytest.fixture(scope="module")
def unresolved():
    import stat_intervals
    cells = [c for c in stat_intervals.grid_cells()
             if c["powered"] and c["verdict"] == "not resolved"]
    if not cells:
        pytest.skip("no unresolved powered arm in this corpus")
    return cells[0]


class TestTheSideWordMatchesTheLedger:

    def test_the_macro_says_where_the_marker_actually_is(self, macros, unresolved):
        obs, lo, hi = (unresolved["d_observed"], unresolved["d_null_lo"],
                       unresolved["d_null_hi"])
        expected = "below" if obs < lo else "above" if obs > hi else "inside"
        assert macros.get("gridUnresolvedSide") == expected, (
            "the caption prints %r for an arm at %.4f against [%.4f, %.4f]"
            % (macros.get("gridUnresolvedSide"), obs, lo, hi))

    def test_the_caption_reads_the_side_from_the_ledger(self, caption):
        assert r"\gridUnresolvedSide" in caption, (
            "the caption states which side of its bar the unresolved marker sits on; that is "
            "a fact about the committed null and must come from it, not from the eye")

    def test_the_caption_does_not_type_the_side(self, caption):
        """The exact sentence that was wrong, and its near neighbours."""
        for banned in (r"at the edge of its bar",
                       r"rather than below it",
                       r"clear of its bar"):
            assert banned not in caption, (
                "%r describes the marker's position by hand; round 45 and round 49 both "
                "found that sentence wrong" % banned)

    def test_the_numbers_beside_the_side_word_are_emitted_too(self, caption):
        for macro in (r"\gridUnresolvedObs", r"\gridUnresolvedNullLo",
                      r"\gridUnresolvedRaw", r"\gridUnresolvedHolm"):
            assert macro in caption, "%s should back the positional claim" % macro


class TestTheCaptionDoesNotOverclaimWhatThePictureShows:
    """The bars are the uncorrected null; the verdicts are corrected. Say so."""

    def test_the_caption_names_the_bars_uncorrected(self, caption):
        assert re.search(r"\\emph\{uncorrected\}|uncorrected", caption), (
            "the bars draw the uncorrected null while every verdict in the legend is "
            "Holm-corrected; a reader who is not told cannot reconcile the open circle")

    def test_the_caption_admits_what_it_cannot_draw(self, caption):
        assert re.search(r"cannot draw|not (?:something|a thing) the picture", caption), (
            "Holm correction is not a geometric property; the caption claims the picture "
            "carries the test, so it must say where that stops")

    def test_every_filled_circle_really_does_survive_correction(self):
        """The caption's 'filled circles reject and also survive Holm correction'."""
        import stat_intervals
        bad = [c for c in stat_intervals.grid_cells()
               if c["powered"] and c["verdict"] == "grid" and c["p_holm"] > 0.05]
        assert not bad, "arm(s) drawn as rejecting whose corrected p exceeds 0.05: %s" % (
            [(c["rate_hz"], c["p_holm"]) for c in bad],)

    def test_the_unresolved_arm_really_does_reject_uncorrected(self, unresolved):
        """If it ever stops rejecting raw, the caption's whole explanation changes."""
        assert unresolved["p_raw"] <= 0.05 < unresolved["p_holm"], (
            "the caption explains this arm as raw-rejecting and correction-failing; it is "
            "now raw %.3f, corrected %.3f" % (unresolved["p_raw"], unresolved["p_holm"]))
