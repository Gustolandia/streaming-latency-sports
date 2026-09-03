r"""Statements both documents make, which must not drift apart.

The project generates every *number* it prints twice, so a value cannot disagree with itself
across the two files. It had no such discipline for a *statement*, and round 45 found the
consequence: the spread law, which is the paper's central quantitative claim, appeared in the
main text as

    spread  =  { 100/q  mid-cell ;  > 0  on a grid point }

and in the supplement, six pages later, as

    spread  ->  { 100/q  mid-cell ;  0    on a grid point }

Both branches differed, in opposite directions, and the main text had the worse of each. The
equality is falsified by the authors' own ledger --- the 250 msg/s arm has cell width 100 and
a measured spread of 58.6 --- while `> 0` is not a prediction at all, since no floating-point
range is ever exactly zero. The supplement, `analyze_phase_quantisation.py` and that module's
test all said "upper bound, not a point prediction". Only the main text still carried the
superseded form, and nothing compared them because nothing ever had.

So: the shared statements are enumerated, normalised, and required to be character-identical.
The list is deliberately short. Every entry costs something to keep in step, and the argument
for an entry is that the two copies have already drifted or that a reader would be misled if
they did.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

#: Where each document states the spread law.
#: Labels, not prose. The first anchor tried here was the sentence introducing the
#: supplement's copy, and it broke the moment the paragraph reflowed across a line.
MAIN_ANCHOR = r"\label{eq:quant}"
SUPP_ANCHOR = r"\label{eq:quantsupp}"


def _tex(name):
    return (REPO / name).read_text(encoding="utf-8")


def _cases_body(tex, after):
    r"""The body of the first `\begin{cases}` block appearing after `after`."""
    at = tex.index(after)
    start = tex.index(r"\begin{cases}", at)
    end = tex.index(r"\end{cases}", start)
    return tex[start + len(r"\begin{cases}"):end]


def _normalise(fragment):
    """Whitespace and LaTeX spacing commands carry no meaning here; the operators do."""
    out = re.sub(r"\\\\\[[^\]]*\]", r"\\\\", fragment)      # \\[2pt] -> \\
    out = re.sub(r"\\[,;:!]|\\quad|\\qquad", " ", out)
    return re.sub(r"\s+", " ", out).strip()


@pytest.fixture(scope="module")
def branches():
    return (_normalise(_cases_body(_tex("paper.tex"), MAIN_ANCHOR)),
            _normalise(_cases_body(_tex("supplement.tex"), SUPP_ANCHOR)))


@pytest.fixture(scope="module")
def emitted():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                    # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return re.findall(r"\\newcommand\{\\(\w+)\}", gen.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def documents():
    """Both documents with line wrapping normalised away.

    A phrase search must not depend on where LaTeX's source happened to break the line:
    "contain\\n\\textbf{not one negative}" is the same sentence as "contain \\textbf{not one
    negative}", and a test that can tell them apart fails on a reflow rather than on a defect.
    """
    return re.sub(r"\s+", " ", _tex("paper.tex") + "\n" + _tex("supplement.tex"))


class TestTheSpreadLawIsStatedOnce:
    """Equation 5 of the main text and its twin in supplementary material S31."""

    def test_both_documents_state_the_same_two_branches(self, branches):
        main, supp = branches
        assert main == supp, (
            "the spread law differs between the documents.\n  main text: %s\n  supplement: %s\n"
            "One of them is telling a reader something the other denies." % (main, supp))

    def test_the_lower_branch_is_zero_and_not_an_inequality(self, branches):
        """`> 0` excludes only exact equality with zero, which no measured range achieves.

        A branch that cannot fail is not half of a law. The limit is zero; the reason a real
        arm sits above it belongs in the prose beside the equation, where it now is.
        """
        for text in branches:
            assert ">" not in text, (
                "a branch of the spread law reads as an inequality (%s). The collapse branch "
                "is a limit of 0; the noise floor that keeps a real arm off it is prose." % text)

    @pytest.mark.parametrize("name,anchor", [("paper.tex", MAIN_ANCHOR),
                                             ("supplement.tex", SUPP_ANCHOR)])
    def test_the_relation_is_a_limit(self, name, anchor):
        r"""`\longrightarrow`, not `=`.

        As an equality the upper branch is falsified by the ledger it is drawn from: replicates
        that never realize both bracketing vertices fall short of the cell width, and three of
        them did at 250 msg/s. As a limit it is exactly right, and the supplement's own prose
        has called it "an upper bound" since round 29.
        """
        tex = _tex(name)
        at = tex.index(anchor)
        head = tex[max(0, at - 400): tex.index(r"\begin{cases}", at)]
        assert r"\longrightarrow" in head, (
            "%s states the spread law with something other than a limit arrow; as an "
            "equality its upper branch is falsified by the 250 msg/s arm" % name)
        assert r"\text{spread} \;=\;" not in head, \
            "%s still states the spread law as an equality" % name

    def test_the_check_would_have_caught_round_45s_defect(self):
        """The two forms as they actually stood, so the comparison is known to have teeth."""
        was_main = _normalise(
            r"100/q & \text{when } T \text{ sits mid-cell,}\\[2pt]"
            r"> 0 & \text{when } T \text{ sits on a grid point.}")
        was_supp = _normalise(
            r"100/q & \text{when } T \text{ sits mid-cell,}\\[2pt]"
            r"0 & \text{when } T \text{ sits on a grid point.}")
        assert was_main != was_supp
        assert ">" in was_main and ">" not in was_supp


#: Claims written as English words whose whole content is that a count is zero, and the
#: emitted macro each one is really asserting. A sentence saying "not one negative" is a
#: statement about `ombKafkaNegatives`, whether or not it prints it.
ZERO_CLAIMS = [
    (r"contain \textbf{not one negative}", "ombKafkaNegatives"),
    (r"\textbf{zero} negative differences", "harnessOneClockNegatives"),
]


class TestEveryCountOfNegativesIsChecked:
    r"""The number a sentence exists to deliver may not reach the page unchecked.

    Two sentences carry the paper's most emphatic claims --- "\textbf{zero} negative
    differences across \harnessOneClockSamples samples" and "\ombKafkaDiscarded discarded
    samples contain \textbf{not one negative}" --- with the denominator generated and the
    count in words beside it. Both counts exist as macros, and both macros were read by
    neither document. Round 29's stated reason for generating macros at all is that an
    unread one is where a stale number survives a revision, and these were the two sentences
    where that would have cost most: a corpus that produced a single negative would have
    changed the ledger, passed every gate, and left both sentences still reading zero.

    Round 45 first fixed this by substituting the macros into the prose, and that was the
    wrong fix. "The discarded samples contain 0 negatives" is a weaker sentence than "contain
    not one negative", and it buys no safety a value check does not: what makes the claim
    true is that the ledger's count is zero, not that the digit is printed. So the words stay
    and the *claim behind them* is what is gated. If the corpus ever produces a negative
    these fail, and the sentence has to be rewritten by someone who has seen the number.
    """

    def test_the_negative_counts_are_emitted_at_all(self, emitted):
        for name in ("harnessOneClockNegatives", "harnessCrossHostNegatives",
                     "ombKafkaNegatives"):
            assert name in emitted, "%s is no longer emitted" % name

    @pytest.mark.parametrize("phrase,macro", ZERO_CLAIMS)
    def test_a_claim_of_no_negatives_is_a_claim_the_ledger_backs(self, documents, phrase,
                                                                 macro):
        assert phrase in documents, (
            "%r is gone; if the sentence was reworded, update ZERO_CLAIMS so the claim it "
            "now makes is the one being checked" % phrase)
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        m = re.search(r"\\newcommand\{\\%s\}\{([^}]*)\}" % macro, gen)
        assert m, "%s is not emitted, so %r rests on nothing" % (macro, phrase)
        assert m.group(1).strip() == "0", (
            "the text says %r but the ledger puts %s at %s. The sentence is now false and "
            "has to be rewritten, not re-rendered." % (phrase, macro, m.group(1)))

    def test_every_emitted_count_of_negatives_is_quoted_or_claimed(self, emitted, documents):
        """A count of negatives may not be emitted and then ignored by both documents.

        Quoting the macro satisfies this; so does making a claim about it in ZERO_CLAIMS,
        which the test above then holds to the ledger.
        """
        claimed = {macro for _, macro in ZERO_CLAIMS}
        loose = [n for n in emitted
                 if n.endswith("Negatives") and n not in claimed
                 and not re.search(re.escape("\\" + n) + r"(?![A-Za-z])", documents)]
        assert not loose, (
            "these counts of negatives are emitted, quoted nowhere and claimed nowhere: %s. "
            "A count of negatives is the load-bearing number in whatever sentence reports "
            "it; quote it, claim it, or stop emitting it." % ", ".join(loose))

    def test_the_supplement_no_longer_types_its_own_zero(self, documents):
        """S10 reported the cross-host result in words beside no number at all."""
        assert "measures zero negatives" not in documents, (
            "supplementary material S10 is typing a count the ledger emits")


class TestTheCrossHostArmIsDescribedCorrectly:
    """The arm Section V-D reports, and the one word that says why it is the right arm.

    The harness has three rates and only one of them can show a clock effect: at the two
    commensurate rates the grid's own two-point support spreads retention across 33 and 100
    points, which buries a few points of clock drift, while the incommensurate arm's one-clock
    spread sits on the noise floor at 0.98. Reporting the incommensurate arm is therefore a
    designed contrast; reporting it without saying so reads as the best of three.

    The macro that says which it is was emitted against an unfiltered membership set, so it
    came out "commensurate" for every arm, and the built PDF called 457 msg/s "the
    commensurate arm" -- inverting the one word the sentence turns on. Caught by rendering the
    page, which is the only place it was visible.
    """

    def test_the_named_arm_is_the_incommensurate_one(self):
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        import stat_intervals

        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        rate = int(re.search(r"\\newcommand\{\\harnessXHostRate\}\{(\d+)\}", gen).group(1))
        klass = re.search(r"\\newcommand\{\\harnessXHostArmClass\}\{(\w+)\}", gen).group(1)

        commensurate = {c["rate_hz"] for c in stat_intervals.spread_cells()
                        if c["commensurate"]}
        expected = "commensurate" if rate in commensurate else "incommensurate"
        assert klass == expected, (
            "the ledger puts %d msg/s in the %s class and the macro says %s"
            % (rate, expected, klass))

    def test_the_named_arm_is_the_one_the_numbers_came_from(self):
        """The three quoted values must be that arm's, not another's."""
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        import stat_intervals

        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")

        def macro(name):
            return re.search(r"\\newcommand\{\\%s\}\{([^}]*)\}" % name, gen).group(1)

        rate = int(macro("harnessXHostRate"))
        spreads = stat_intervals.harness_arm_spreads()
        assert rate in spreads, "%d msg/s is not in the harness ledger" % rate
        (xlo, xhi) = spreads[rate]["cross_host"]
        (olo, ohi) = spreads[rate]["one_clock"]
        assert macro("harnessXHostRetLo") == "%.1f" % xlo
        assert macro("harnessXHostRetHi") == "%.1f" % xhi
        assert macro("harnessOneClockSpread") == "%.2f" % (ohi - olo)
