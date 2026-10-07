r"""Round 77's referee items, pinned so a later pass cannot quietly undo them.

Two required items, both in S16.9, and the first corrects the round-76 referee's own advice.

R1. Round 76 recommended saying that once the exact recoveries are removed the two medians
"cross". They do, as medians. But S16.9's thesis is that a quantile can move while a
population does not, and applied to the crossing it says what it said about the gap: the
Hodges--Lehmann shift between the two non-zero populations is 0.0 points, with a bootstrap
interval containing zero. Section V-D now states the shift. S16.9 keeps the medians as
description and says that the crossing is the same artifact as the gap.

R2. Three sentences in S16.9 did not match the data they described. The two Wilson intervals
"overlap across almost their whole length" (about two-thirds; and overlap is not a test -- the
interval on the difference is). The rejected population is "nearly flat" (it has its own pile
of exact recoveries). The accepted one is "a spike at zero with a second cluster" (that omits
half its non-zero conditions).

Two corrections to the referee, both found by implementing its advice from the data.

The referee's replacement grouping -- 14 exact, 14 between 1.9% and 14.3%, 12 between 20% and
33% -- was itself drawn by eye: splitting the accepted population at its largest gap puts the
break between 22% and 29%. So neither the old clusters nor the new ones are used. Both
populations are counted in bands from one stated edge, then `stat_intervals.RECOVERY_BAND_PCT`
and since round 78 `stat_intervals.recovery_band_edge`, the accepted upper quartile it equaled.

The referee's sketch read the two distribution functions as crossing "near 15% and 29%". They
change order at 18.2% and 34.8%, and the figure's caption now reads those values from the
pipeline.

Recommended items, all taken: W1 draws both populations; W2 names the bracket's method and
level and corrects "used the same way"; W3 labels Figure 4's grid values in one notation; W4
records, as a dated ledger row, that one tracker item upstream in eight years has named the
filtered variable; W5 prepares, and does not make, the swap of reference [9] for Chen et al.
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
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ledger():
    gen = REPO / "docs" / "generated" / "paper_numbers.tex"
    if not gen.exists():                                # pragma: no cover - built by CI
        pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(BS * 2 + r"newcommand\{" + BS * 2 + r"(\w+)\}\{(.*)\}\s*$",
                           gen.read_text(encoding="utf-8"), re.M))


@pytest.fixture(scope="module")
def pops():
    import stat_intervals
    return stat_intervals.recovery_populations()


def _vd(paper):
    """Section III-D, v4's Section V-D, flattened.

    v5 (28 Sep): the paragraph this read from ("The displacement can be recovered rather than
    discarded") is III-D's last, reworded, so the whole subsection is read."""
    i = paper.index(BS + "label{sec:cost}")
    return " ".join(paper[i:paper.index(BS + "section{", i)].split())


def _rendered_s169(supplement_text):
    """S16.9's pages of the rendered supplement: from its heading to S16.10's, the last
    occurrence of each so the table of contents is skipped."""
    return supplement_text[supplement_text.rindex("S16.9. The displacement recovery"):
                           supplement_text.rindex("S16.10. How late")]


def _s169(supplement):
    i = supplement.index("S16.9.")
    return " ".join(supplement[i:supplement.index("S17. The 1970 counter note")].split())


def _bracket(value):
    return tuple(float(v) for v in value.replace("$ to $", " ").split())


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1NoShiftRemains:

    def test_the_shift_on_the_nonzero_populations_is_emitted(self, ledger):
        assert "recoveryNonzeroShift" in ledger and "recoveryNonzeroShiftCI" in ledger
        lo, hi = _bracket(ledger["recoveryNonzeroShiftCI"])
        assert lo < float(ledger["recoveryNonzeroShift"]) < hi or \
            float(ledger["recoveryNonzeroShift"]) == 0.0
        assert lo < 0.0 < hi, (
            "the interval no longer contains zero: 'no shift is detectable' is now false and the "
            "clause in Section V-D must be re-argued, not re-emitted")

    def test_it_is_the_statistic_the_referee_ran(self, pops):
        import stat_intervals as si
        a = [v for v in pops["Pass"] if v > 0]
        b = [v for v in pops["Fail"] if v > 0]
        assert si.hodges_lehmann(a, b) == pytest.approx(0.0, abs=0.05)
        # 7 Oct 2026: (-8.0, 7.14) as the referee ran it; (-8.57, 6.07) once the late
        # messages were left out of the groups. Still no shift, still zero inside.
        assert si.hl_bootstrap_ci(a, b) == pytest.approx((-8.57, 6.07), abs=0.05)

    def test_the_main_text_states_the_shift_not_a_crossing(self, paper, supplement):
        """v5 (28 Sep): the shift and its labeled bracket moved from Section V-D to S16.9 with
        V-D's other statistics (editorial review, Section 5) and are pinned there, worded "no
        shift can be detected"; Section III-D, which kept one sentence of result, is still held
        to no crossing and no non-zero medians."""
        s = _s169(supplement)
        # Round 78 (R1, W1): undetectable rather than absent, and the second bracket labeled.
        assert "no shift can be detected" in s
        assert (BS + "recoveryNonzeroShift$ points ($95" + BS + "%$ bootstrap: $" + BS
                + "recoveryNonzeroShiftCI$)") in s
        vd = _vd(paper)
        assert "crosses it" not in vd
        assert BS + "recoveryErrPassNonzero" not in vd, (
            "the medians belong in S16.9 as description; in the main text they read as a finding")

    def test_the_supplement_says_the_crossing_is_the_same_artifact(self, supplement):
        s = _s169(supplement)
        assert "happen to cross" in s
        assert "the same artifact as a gap between them" in s
        assert BS + "recoveryNonzeroShift" in s and BS + "recoveryNonzeroShiftCI" in s
        assert "if anything the worse of the two" not in s

    def test_the_defect_that_prompted_this_is_caught(self, paper, supplement):
        """v5 (28 Sep): the statement of the shift is in S16.9, so the crossing is put in its
        place there; a crossing added to the sentence Section III-D kept is caught as well."""
        bad, n = re.subn(r"no\s+shift\s+can\s+be\s+detected\s+in\s+what\s+is\s+left",
                         "setting the exact recoveries aside crosses it", supplement)
        assert n == 1, "S16.9 has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_states_the_shift_not_a_crossing(paper, bad)
        # 5 Oct 2026: Section III-D's kept sentence was cut; the crossing is added after the
        # last number of the rebuilt recovery paragraph (Section VI-B) instead.
        bad, n = re.subn(r"\$" + re.escape(BS) + r"recoveryErrFailHi" + re.escape(BS) + r"%\$",
                         lambda m: m.group(0) + ", and setting the exact recoveries aside "
                         "crosses it", paper)
        assert n == 1, "Section VI-B has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_states_the_shift_not_a_crossing(bad, supplement)


class TestR2TheDescriptionsMatchTheData:

    def test_the_difference_interval_is_emitted_and_contains_zero(self, ledger):
        import stat_intervals as si
        lo, hi = _bracket(ledger["recoveryExactDiffCI"])
        assert lo < 0.0 < hi
        k_a, n_a = int(ledger["recoveryPassExactN"]), int(ledger["recoveryPassN"])
        k_b, n_b = int(ledger["recoveryFailExactN"]), int(ledger["recoveryFailN"])
        exp = si.newcombe_diff_ci(k_a, n_a, k_b, n_b)
        assert (lo, hi) == pytest.approx((100 * exp[0], 100 * exp[1]), abs=0.06)

    def test_overlap_is_no_longer_the_argument(self, supplement):
        s = _s169(supplement)
        assert "overlap across almost their whole length" not in s
        assert "overlap is not the test" in s
        assert BS + "recoveryExactDiffCI" in s

    def test_the_shapes_are_counted_not_described(self, supplement):
        s = _s169(supplement)
        for gone in ("nearly flat", "second cluster", "spike at zero with a"):
            assert gone not in s, gone
        for side in ("Pass", "Fail"):
            for band in ("ExactN", "BelowBandN", "FromBandN"):
                assert BS + "recovery" + side + band in s, side + band
        assert BS + "recoveryBandPct" in s

    def test_the_counts_are_the_data(self, ledger, pops):
        import stat_intervals as si
        band = si.recovery_band_edge(pops)
        assert ledger["recoveryBandPct"] == "%.0f" % band
        for side in ("Pass", "Fail"):
            v = pops[side]
            assert int(ledger["recovery%sExactN" % side]) == sum(1 for x in v if x == 0.0)
            assert int(ledger["recovery%sBelowBandN" % side]) == sum(1 for x in v if 0 < x < band)
            assert int(ledger["recovery%sFromBandN" % side]) == sum(1 for x in v if x >= band)

    def test_a_cluster_would_have_been_wherever_the_eye_put_it(self, pops):
        """Why bands and not clusters. The referee grouped the accepted population with a break
        between 14.3% and 20%; its largest gap is elsewhere. Neither is a property of the data
        a reader can check; a stated edge is."""
        nz = sorted(v for v in pops["Pass"] if v > 0)
        gaps = [(nz[i + 1] - nz[i], nz[i], nz[i + 1]) for i in range(len(nz) - 1)]
        size, below, above = max(gaps)
        assert (round(below, 1), round(above, 1)) != (14.3, 20.0)
        # 7 Oct 2026: 22 to 29 as first computed; 20 to 29 without the late messages.
        assert round(below) == 20 and round(above) == 29


class TestW1TheTwoPopulationsAreDrawn:

    def test_the_figure_is_built_by_the_pipeline_and_included(self, supplement):
        import make_result_figures as mrf
        assert "recovery" in mrf.main.__code__.co_consts or hasattr(mrf, "build_recovery")
        assert hasattr(mrf, "plot_recovery")
        assert "docs/results/figures/recovery_populations.pdf" in supplement
        assert (REPO / "docs" / "results" / "figures" / "recovery_populations.pdf").is_file()

    def test_the_caption_opens_on_a_claim_without_an_article(self, supplement):
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_caption_leads as tcl
        leads = {lab: tcl.lead(cap) for env, lab, cap in tcl.captions(supplement)}
        lead = leads.get("fig:recovery")
        assert lead == "Two populations with no detectable shift between them."
        assert not re.match(r"^(A|An|The)\b", lead)

    def test_the_caption_reads_its_crossing_from_the_curves(self, supplement, ledger, pops):
        """7 Oct 2026: the curves crossed twice, at 18.2% and 34.8%, as first computed;
        without the late messages they cross once, and the caption says once."""
        import stat_intervals as si
        cap = supplement[supplement.index("recovery_populations.pdf"):
                         supplement.index(BS + "label{fig:recovery}")]
        assert BS + "recoveryEcdfCross" + BS + "%" in cap
        assert "change order once" in " ".join(cap.split())
        got = si.ecdf_crossings(pops["Pass"], pops["Fail"])
        assert len(got) == 1 and ledger["recoveryEcdfCross"] == "%.1f" % got[0]
        assert float(ledger["recoveryEcdfCross"]) != 15.0, \
            "the referee's reading off the sketch, which the curves do not bear out"

    def test_one_crossing_leaves_no_change_back_to_describe(self, ledger):
        assert "recoveryEcdfCrossLo" not in ledger and "recoveryEcdfCrossHi" not in ledger

    def test_the_text_points_at_the_figure(self, supplement):
        assert BS + "ref{fig:recovery}" in _s169(supplement)


class TestW2TheBracketSaysWhatItIs:

    def test_the_main_text_names_method_and_level(self, paper, supplement):
        """v5 (28 Sep): both shift brackets are printed in S16.9 now, not in Section V-D
        (editorial review, Section 5). Each still names its method and level where it is
        printed, and neither may come back to the article without its label."""
        s = _s169(supplement)
        for macro in ("recoveryShiftCI", "recoveryNonzeroShiftCI"):
            j = s.index("$" + BS + macro + "$)")
            label = s[s.rindex("(", 0, j):j]
            assert re.fullmatch(r"\(\$95" + re.escape(BS) + r"%\$ (?:percentile )?bootstrap: ",
                                label), (macro, label)
        text = " ".join(paper.split())
        label = re.compile(r"95" + re.escape(BS) + r"%\$? (?:percentile )?bootstrap: $")
        for macro in ("recoveryShiftCI", "recoveryNonzeroShiftCI"):
            for m in re.finditer(re.escape("$" + BS + macro + "$"), text):
                assert label.search(text[max(0, m.start() - 40):m.start()]), macro

    def test_same_way_is_corrected_with_both_levels(self, supplement):
        s = _s169(supplement)
        assert "used the same way in both places" not in s
        assert "on the same footing in both places" in s
        assert "$90" + BS + "%$ interval" in s and "$95" + BS + "%$ interval" in s


class TestW3OneNotationForTheGridTicks:

    def test_a_decade_that_is_a_grid_value_prints_plainly(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import make_result_figures as mrf
        fig, ax = plt.subplots()
        mrf.plot_deletion(ax, mrf.retention_points())
        fmt = ax.xaxis.get_major_formatter()
        assert fmt(1.0, 0) == "1", "the grid value 1 must read as the caption names it"
        assert fmt(10.0, 1) != "10", "other decades keep their own labels"
        plt.close(fig)


class TestW4TheTrackerIsALedgerRow:

    def test_the_sentence_reads_the_row(self, supplement, ledger):
        import check_omb_tracker as cot
        row = cot.read_ledger(REPO / cot.LEDGER)
        assert ledger["ombTrackerItems"] == row["total_items"]
        assert ledger["ombTrackerFirstItem"] == row["first_item"]
        assert ledger["ombTrackerChecked"] == row["checked"]
        import emit_paper_numbers as epn
        years = int(row["checked"][:4]) - int(row["first_item_created"][:4])
        assert ledger["ombTrackerYearsWord"] == epn._spell(years)
        for name in ("ombTrackerItems", "ombTrackerFirstItem", "ombTrackerChecked",
                     "ombTrackerYearsWord"):
            assert BS + name in supplement, name

    def test_a_missing_or_malformed_row_emits_nothing(self, tmp_path):
        import emit_paper_numbers as epn
        assert epn._tracker_macros(str(tmp_path / "absent.csv")) == []
        bad = tmp_path / "two.csv"
        bad.write_text("repository,query,checked,total_items,first_item,first_item_created,"
                       "first_item_title\n", encoding="utf-8")
        assert epn._tracker_macros(str(bad)) == []


class TestW5ThePreparedSwap:

    def test_the_entry_is_prepared_and_not_cited(self, paper):
        """5 Oct 2026: the rebuilt Related Work cites Georges et al. inside a group,
        "\\cite{mytkowicz2009wrong,georges2007rigorous,hoefler2015benchmarking}", so the pin
        reads every citation's keys rather than the opening of one.

        7 Oct 2026: the prepared entry left the bibliography with every entry nothing cited,
        on the author's instruction that it hold only what the documents use. The swap stays
        unmade and Georges et al. stays cited; the entry, should it be wanted, is in the
        history."""
        bib = "\n".join((REPO / name).read_text(encoding="utf-8")
                        for name in ("manuscript_references.bib", "postmortem_references.bib"))
        assert "@article{chen2015statcomparisons," not in bib
        prose = re.sub(r"(?m)(?<!\\)%.*$", "", paper)
        cited = {k.strip() for group in re.findall(re.escape(BS) + r"cite\{([^}]*)\}", prose)
                 for k in group.split(",")}
        assert "chen2015statcomparisons" not in cited
        assert "georges2007rigorous" in cited, "the reference stays, as advised"

    def test_the_decision_is_recorded_beside_the_citation(self, paper):
        """5 Oct 2026: the comment that recorded the decision beside the citation went with
        the rebuilt paper's comments, and the record is the prepared entry's own note, which
        names the work it would replace and says it was not made unprompted. A comment beside
        the citation, should one come back, must name the entry.

        7 Oct 2026: the note left with the entry, which nothing cited. What stays checkable is
        that the paper does not name an entry the bibliography no longer holds, in a comment
        or anywhere else."""
        assert "chen2015statcomparisons" not in paper


class TestTheRenderedPagesCarryIt:

    def test_the_main_text(self):
        """v5 (28 Sep): the undetectable shift and its bracket print on S16.9's pages now
        (editorial review, Section 5). The extractor drops the spaces around inline math, so
        they are matched with all spaces removed; the article still prints no crossing.
        29 Sep: S16.9 is the postmortem's, so its pages are read from postmortem.pdf."""
        tight = "".join(_rendered_s169(_rendered("postmortem")).split())
        assert "noshiftcanbedetected" in tight
        assert "(95%bootstrap:" in tight
        assert "crosses it" not in " ".join(_rendered("paper").split())

    def test_the_supplement(self):
        """29 Sep: these are S16.9's words, which the postmortem keeps; postmortem.pdf."""
        flat = " ".join(_rendered("postmortem").split())
        assert "Two populations with no detectable shift between them" in flat
        assert "happen to cross" in flat
