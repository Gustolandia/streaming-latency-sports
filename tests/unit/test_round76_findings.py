r"""Round 76's referee items, pinned so a later pass cannot quietly undo them.

One required item, and it is the round-75 repair audited one level up.

R1. Round 75 replaced a false separation claim with a Hodges--Lehmann shift. The shift was
correct and it was emitted bare. Section VIII-A quotes the *other* Hodges--Lehmann shift in
this manuscript -- the broker equivalence -- with a 90% bootstrap interval beside it, and
S16.9's own justification for choosing the statistic ends "one statistic, used the same way
in both places it is needed." It was not being used the same way. The same round introduced
two exact-recovery proportions over stated denominators and printed those bare too, against
Section IV-F's promise of a Wilson interval on every proportion; Table I's exemption is for
intervals "under 0.1 points" and these are twenty-seven and twenty-nine points wide.

Every interval, once computed, supports the corrected reading rather than weakening it. That
is the argument for emitting them. A paper that reports an interval only where the interval
is comfortable is doing the thing this paper is about.

The recommended items, all taken:

W1. The sharper form of the finding. Remove the exact recoveries from both populations and
the medians do not converge, they CROSS -- 17.1% accepted against 14.3% rejected. The gap is
the spike entire.

W2. The main text quoted the accepted population's exact-recovery share alone, which invites
the reading that the rejected conditions never recover exactly. They do, a fifth of the time.
W1's replacement clause removes the invitation.

W3. A 2026 same-node instance for S33.2, carried with the caveat that its magnitudes are far
beyond a run-queue stall, so it evidences the missing hypothesis and not our mechanism.

W4. The cross-domain corroboration, in S33.4 and nowhere near the main text: the references
are at the cap and a preprint that rounds rather than deletes is not worth displacing one.

W5. Figure 4's at-grid cells sit at 1.0 and 2.0 ms -- three tenths of a decade on an axis
spanning five -- so the caption asserted two columns the eye read as one. They have ticks now.

And the referee's own suggested check, which was not on either list: a shift cannot carry
"the populations do not differ", because two distributions can sit at zero offset and differ
in shape. Tested with a statistic about distributions instead.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ledger():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(BS * 2 + r"newcommand\{" + BS * 2 + r"(\w+)\}\{(.*)\}\s*$",
                           gen.read_text(encoding="utf-8"), re.M))


def _s169(supplement):
    i = supplement.index("S16.9.")
    return " ".join(supplement[i:supplement.index("S17. The 1970 counter note")].split())


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1EveryStatedQuantityCarriesItsUncertainty:

    def test_the_shift_is_emitted_with_an_interval(self, ledger):
        assert "recoveryShiftCI" in ledger, (
            "the shift is quoted bare; Section VIII-A's shift is not")
        lo, hi = (float(v) for v in
                  ledger["recoveryShiftCI"].replace("$ to $", " ").split())
        assert lo < 0.0 < hi, (
            "the interval no longer contains zero, so 'the populations do not [differ]' "
            "has to be re-argued rather than re-emitted")
        assert lo < float(ledger["recoveryShift"]) < hi

    def test_both_exact_shares_are_emitted_with_wilson_intervals(self, ledger):
        for side in ("Pass", "Fail"):
            name = "recovery%sExactCI" % side
            assert name in ledger, "%s is a proportion over a stated denominator" % side
            lo, hi = (float(v) for v in ledger[name].split("$--$"))
            point = float(ledger["recovery%sExact" % side])
            assert lo <= point <= hi

    def test_the_two_exact_shares_overlap(self, ledger):
        """The careful statement the intervals buy: the concentration at zero is not itself
        established as a population difference either."""
        plo, phi = (float(v) for v in ledger["recoveryPassExactCI"].split("$--$"))
        flo, fhi = (float(v) for v in ledger["recoveryFailExactCI"].split("$--$"))
        assert max(plo, flo) < min(phi, fhi), "the intervals no longer overlap"

    def test_the_main_text_prints_the_bracket(self, paper):
        i = paper.index("The displacement can be recovered rather than discarded")
        vd = " ".join(paper[i:i + 1400].split())
        # Round 77 (W2) added the method and level inside the bracket, because every other
        # bracket in the main text is a Wilson or a Katz interval and a reader would assume one.
        assert (BS + "recoveryShift$ points [95" + BS + "% bootstrap: $" + BS
                + "recoveryShiftCI$]") in vd, (
            "the shift's interval must sit beside the shift, as Section VIII-A's does, and say "
            "what kind of interval it is")

    def test_the_supplement_table_carries_the_intervals(self, supplement):
        section = _s169(supplement)
        for name in ("recoveryPassExactCI", "recoveryFailExactCI", "recoveryShiftCI"):
            assert BS + name in section, name

    def test_the_claim_s16_9_makes_about_its_own_statistic_is_now_true(self, supplement):
        """The sentence that made this a required item: it asserted the two shifts were used
        the same way while one of them had no interval."""
        section = _s169(supplement)
        # Round 77 (W2) corrected the sentence itself: the two brackets are at different
        # levels, 90% for the TOST and 95% for the two-sided estimate, so "the same way"
        # became "on the same footing ... each at the level its question calls for".
        assert "one statistic, on the same footing in both places" in section
        i = supplement.index(BS + "tostHLCI")
        assert BS + "tostHL" in supplement[max(0, i - 400):i], "the other shift and its CI"
        assert BS + "recoveryShiftCI" in section, "and now this one"

    def test_the_estimators_live_where_section_iv_f_says_they_do(self):
        """Section IV-F names `scripts/stat_intervals.py` as where interval arithmetic is
        recomputed at build time. A shift's bracket computed anywhere else would make that
        sentence false."""
        import stat_intervals
        for name in ("hodges_lehmann", "hl_bootstrap_ci", "ks_two_sample",
                     "ks_permutation_p", "wilson"):
            assert hasattr(stat_intervals, name), name
        src = (REPO / "scripts" / "stat_intervals.py").read_text(encoding="utf-8")
        assert "hl_bootstrap_ci()" in src, "the module docstring lists its estimators"


class TestW1TheMediansCross:

    def test_the_crossing_is_emitted(self, ledger):
        a = float(ledger["recoveryErrPassNonzero"])
        b = float(ledger["recoveryErrFailNonzero"])
        assert a > b, (
            "with the exact recoveries removed the accepted conditions were the worse of "
            "the two; if that has reversed, Section V-D's clause must change with it")
        assert float(ledger["recoveryErrFail"]) > float(ledger["recoveryErrPass"]), (
            "and the ordering with them included is the opposite one, which is the point")

    def test_the_denominators_are_emitted_beside_the_medians(self, ledger):
        for side in ("Pass", "Fail"):
            n = int(ledger["recovery%sNonzeroN" % side])
            total = int(ledger["recovery%sN" % side])
            exact = round(float(ledger["recovery%sExact" % side]) / 100.0 * total)
            assert n == total - exact, "%s: %d != %d - %d" % (side, n, total, exact)

    def test_the_main_text_states_it(self, paper):
        i = paper.index("The displacement can be recovered rather than discarded")
        vd = " ".join(paper[i:i + 1400].split())
        # Round 77 (R1) withdrew the crossing this test pinned: the shift between the two
        # non-zero populations is 0.0, so "crosses it" read a reversal into no shift at
        # all. The main text now states the shift; the medians stay in S16.9 as description.
        # Round 78 (R1): and states it as undetectable, not as absent.
        assert "no shift is detectable" in vd and "crosses it" not in vd
        assert BS + "recoveryNonzeroShift" in vd

    def test_the_supplement_states_it_with_both_denominators(self, supplement):
        section = _s169(supplement)
        assert "they happen" in section and "to cross" in section, (
            "the medians are still reported as crossing, as description only (round 77)")
        for name in ("recoveryPassNonzeroN", "recoveryFailNonzeroN"):
            assert BS + name in section, name


class TestW2NeitherDocumentImpliesTheRejectedNeverRecoverExactly:

    def test_the_main_text_no_longer_quotes_one_side_alone(self, paper):
        i = paper.index("The displacement can be recovered rather than discarded")
        vd = " ".join(paper[i:i + 1400].split())
        assert (BS + "recoveryPassExact\\%$ of the passing conditions") not in vd
        assert "recover the delivery exactly" not in vd, (
            "the one-sided clause is what invited the wrong reading")

    def test_the_supplement_says_both_shares_out_loud(self, supplement):
        section = _s169(supplement)
        assert BS + "recoveryPassExact" in section and BS + "recoveryFailExact" in section
        assert "The rejected conditions recover exactly as well" in section

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        """Mutation: put the one-sided clause back and the gate must fire."""
        bad, n = re.subn(
            r"and without it\s+no shift is\s+detectable,[^(]*",
            "where " + BS + "recoveryPassExact" + r"\\% of the passing conditions "
            "recover the delivery exactly", paper)
        assert n == 1, "Section V-D has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_no_longer_quotes_one_side_alone(bad)


class TestTheShapeTestTheRefereeAskedFor:
    """Not on either list; offered in Part 6 as "the number a statistician will ask for"."""

    def test_the_ks_statistic_and_its_permutation_p_are_emitted(self, ledger):
        d = float(ledger["recoveryKsD"])
        p = float(ledger["recoveryKsP"])
        assert 0.0 < d < 1.0
        assert p > 0.05, (
            "the distributional claim no longer survives; 'the populations do not [differ]' "
            "is a claim about distributions and this is the statistic that tests it")
        assert ledger["recoveryKsPerms"] == "20{,}000"

    def test_it_is_tie_correct(self):
        """The samples are mostly ties. An ECDF that steps once per observation reads a gap
        inside a tie, and reports a D no pair of distributions has."""
        import stat_intervals as si
        a = [0.0, 0.0, 1.0]
        b = [0.0, 0.0, 1.0]
        assert si.ks_two_sample(a, b) == 0.0, (
            "two identical samples must have D = 0 however many ties they carry")

    def test_the_supplement_says_why_a_shift_alone_would_not_carry_the_claim(self, supplement):
        section = _s169(supplement)
        assert "differ in shape" in section
        assert "tie-corrected" in section
        assert BS + "recoveryKsD" in section and BS + "recoveryKsP" in section


class TestW3AndW4TheTwoLiteratureItems:

    def test_the_same_node_instance_is_recorded_with_its_caveat(self, supplement):
        i = supplement.index("otel_obi_2568")
        passage = " ".join(supplement[max(0, i - 1200):i + 900].split())
        assert "same-node" in passage
        assert "seconds to minutes" in passage, (
            "the magnitude caveat is the condition the referee attached to this exhibit")
        assert "absence of a second hypothesis" in passage
        assert "otel_obi_2568" not in (REPO / "paper.tex").read_text(encoding="utf-8")

    def test_the_cross_domain_hit_is_in_the_supplement_only(self, supplement, paper):
        assert "li2026rounding" in supplement
        assert "li2026rounding" not in paper, (
            "the main text is at the reference cap and this displaces nothing")
        i = supplement.index("li2026rounding")
        passage = " ".join(supplement[max(0, i - 900):i + 900].split())
        assert "corroboration and not as a precedent" in passage
        assert "arithmetic without the sign" in passage

    def test_both_entries_exist_in_the_bibliography(self):
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        for key in ("otel_obi_2568", "li2026rounding"):
            assert ("@misc{%s," % key) in bib, key

    def test_the_main_text_reference_count_did_not_move(self):
        bbl = REPO / "paper.bbl"
        if not bbl.is_file():                           # pragma: no cover - built by CI
            pytest.skip("paper.bbl absent")
        n = bbl.read_text(encoding="utf-8", errors="replace").count("\\bibitem")
        assert n == 45, "TC caps the article at 45 references; this is %d" % n


class TestW5TheFigureLetsTheReaderCheckItsCaption:

    def test_the_generator_labels_the_grid_vertices(self):
        src = (REPO / "scripts" / "make_result_figures.py").read_text(encoding="utf-8")
        assert "grid_values" in src and "minor=True" in src
        assert "sorted(set(med[at_grid]" in src, (
            "the ticks must come from the data, so a third grid value grows a third tick "
            "rather than leaving the figure asserting there were two")

    def test_the_tick_type_clears_the_journal_floor(self):
        """`figure_legibility` caught the first attempt at 7 pt. The comment recording that
        is what stops the next person reaching for a smaller size."""
        src = (REPO / "scripts" / "make_result_figures.py").read_text(encoding="utf-8")
        i = src.index("which=\"minor\"")
        assert "labelsize=8" in src[i:i + 120]

    def test_the_caption_reads_the_grid_values_the_axis_draws(self, paper):
        """The caption used to type $1.0$ or $2.0$ while the axis showed neither. Both now
        come from the same rows of the same file."""
        i = paper.index("What the benchmark prints against what it kept")
        caption = " ".join(paper[i:i + 700].split())
        assert BS + "ombGridMedianCells" in caption
        assert BS + "ombGridPrintedLo" in caption and BS + "ombGridPrintedHi" in caption
        assert "$1.0$ or $2.0$" not in caption
        # "labeled", American: the first draft wrote the British form and `test_american_spelling`
        # caught it on the full run.
        assert "the two labeled ticks" in caption

    def test_the_emitter_and_the_figure_share_one_definition_of_at_grid(self):
        """They did not. The emitter tested membership of the literal pair (1.0, 2.0) and the
        figure tested `<= 2.0`, so a cell printing 1.5 ms would have been drawn at the grid
        and counted away from it, and the caption's count would have parted from the
        picture's with nothing to notice."""
        import emit_paper_numbers as epn
        import make_result_figures as mrf
        assert epn.AT_GRID_MAX_MS == mrf.AT_GRID_MAX_MS
        src = (REPO / "scripts" / "emit_paper_numbers.py").read_text(encoding="utf-8")
        assert 'c["p50_ms"] in (1.0, 2.0)' not in src


class TestTheImageReviewFindings:
    """Found by the round-76 triple image review rather than by the referee.

    Pass 3 set all seventeen captions side by side and found three supplement figures opening
    on a label where the others open on a bolded claim. Extending the caption gate to the
    supplement's figures then found a FOURTH the eye had passed: `fig:e1` was bold, but its
    whole lead was the one word "Withdrawn." -- a status, not a claim. Its new lead restates
    only what its own caption already said. The caption gate had required the convention of
    the paper only, by a recorded decision about the supplement's many floats; that decision
    still holds for its tables and no longer for its figures.
    """

    FIXED = {
        # Opened on "A" in the first repair; `TestACaptionDoesNotOpenOnAnArticle` enforces the
        # IEEE style manual's "do not use A, An, or The at the beginning of a caption", and
        # the full suite caught it. The claim survives the cut unchanged.
        "fig:window": "Once-per-run cost, diluted by the window.",
        "fig:expmap": "One variable per campaign, one claim per row.",
        "fig:audit": "No natural threshold, and the choice moves no conclusion.",
        "fig:e1": "Withdrawn: a per-run start-up cost, read as a per-event gap.",
    }

    def test_the_four_now_open_on_their_claim(self, supplement):
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_caption_leads as tcl
        leads = {lab: tcl.lead(cap) for env, lab, cap in tcl.captions(supplement)}
        for lab, claim in self.FIXED.items():
            assert leads.get(lab) == claim, "%s leads with %r" % (lab, leads.get(lab))

    def test_the_labels_they_used_to_open_on_are_gone(self, supplement):
        for label in ("{Window sweep, as a picture.", "{Experiment map.",
                      "{Audit on Testbed~A. (a)", "\\textbf{Withdrawn.}"):
            assert label not in supplement, label

    def test_the_e1_lead_says_only_what_its_caption_already_did(self, supplement):
        """A new lead must not smuggle in a new claim. This one's substance is the caption's
        own sentence: 'the apparent per-event offset is a per-run start-up cost'."""
        i = supplement.index("\\label{fig:e1}")
        block = " ".join(supplement[max(0, i - 900):i].split())
        assert "the apparent per-event offset is a per-run start-up cost" in block

    def test_the_gate_now_covers_supplement_figures(self):
        src = (REPO / "tests" / "unit" / "test_caption_leads.py").read_text(encoding="utf-8")
        assert "def test_every_supplement_figure_opens_on_a_bolded_claim_too" in src


class TestTheRenderedPageCarriesIt:

    def test_the_bracket_prints_in_section_v_d(self):
        flat = " ".join(_rendered("paper").split())
        assert "1.2 points [-1.8 to 8.3]" in flat or "points [" in flat
        assert "no shift is detectable" in flat and "crosses it" not in flat

    def test_the_supplement_table_prints_its_intervals(self):
        flat = " ".join(_rendered("supplement").split())
        assert "Exact (95% CI)" in flat
        assert "Kolmogorov" in flat
