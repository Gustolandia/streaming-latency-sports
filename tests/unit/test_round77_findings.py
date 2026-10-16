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


#: 15 Oct 2026: the shifts S16.9 now states as undetectable, each with its labeled bracket.
#: At native resolution the non-zero populations are the whole populations, so the non-zero
#: shift was the pooled shift under a second name, and its interval excludes zero; what cannot
#: be detected is a shift inside either broker.
BROKER_SHIFTS = tuple(
    BS + "recovery" + b + "Shift$ points on " + BS + b.lower() + "{} ($95" + BS
    + "%$ percentile bootstrap: $" + BS + "recovery" + b + "ShiftCI$)" for b in ("Kafka", "Redis"))


class TestR1NoShiftRemains:

    def test_the_shift_on_the_nonzero_populations_is_emitted(self, ledger):
        """15 Oct 2026: the shifts that carry 'no shift can be detected' are each broker's.
        The non-zero shift is no longer emitted: with no exact recoveries it was the pooled
        shift, whose interval excludes zero, and S16.9 reads that one as the brokers' mix."""
        assert "recoveryNonzeroShift" not in ledger and "recoveryNonzeroShiftCI" not in ledger
        for broker in ("Kafka", "Redis"):
            lo, hi = _bracket(ledger["recovery%sShiftCI" % broker])
            assert lo < float(ledger["recovery%sShift" % broker]) < hi, broker
            assert lo < 0.0 < hi, (
                "%s's interval no longer contains zero: 'no shift can be detected' is now "
                "false and S16.9 must be re-argued, not re-emitted" % broker)

    def test_it_is_the_statistic_the_referee_ran(self, pops):
        """The statistic S16.9 states, recomputed from the populations it is stated over.

        Until 15 Oct 2026 this was the shift between the two non-zero populations of the
        50 us grid: 0.0, with (-8.57, 6.07) once the late messages were left out (7 Oct
        2026) and (-8.0, 7.14) as the referee first ran it. At native resolution there are no
        zero groups, so the statistic is the shift inside each broker, with the bootstrap's own
        resamples and seed; the pooled one beside them excludes zero."""
        import stat_intervals as si
        assert all(v > 0 for p in pops.values() for v in p), "no group recovers exactly"
        cells = si.recovery_populations(split="both")
        for broker, shift, interval in (("Kafka", 0.157, (-0.173, 0.437)),
                                        ("Redis", 1.431, (-6.484, 6.542))):
            a, b = cells[broker + "Pass"], cells[broker + "Fail"]
            assert si.hodges_lehmann(a, b) == pytest.approx(shift, abs=0.001), broker
            assert si.hl_bootstrap_ci(a, b) == pytest.approx(interval, abs=0.001), broker
        assert si.hodges_lehmann(pops["Pass"], pops["Fail"]) == pytest.approx(3.689, abs=0.001)
        assert si.hl_bootstrap_ci(pops["Pass"], pops["Fail"])[0] > 0.0

    def test_the_main_text_states_the_shift_not_a_crossing(self, paper, supplement):
        """v5 (28 Sep): the shift and its labeled bracket moved from Section V-D to S16.9 with
        V-D's other statistics (editorial review, Section 5) and are pinned there, worded "no
        shift can be detected"; Section III-D, which kept one sentence of result, is still held
        to no crossing and no non-zero medians.

        15 Oct 2026: the undetectable shifts are the two brokers', each with its bracket, in
        place of the non-zero shift's (see `BROKER_SHIFTS`)."""
        s = _s169(supplement)
        # Round 78 (R1, W1): undetectable rather than absent, and the second bracket labeled.
        assert "no shift can be detected" in s
        for shift in BROKER_SHIFTS:
            assert shift in s, shift
        vd = _vd(paper)
        assert "crosses it" not in vd
        assert BS + "recoveryErrPassNonzero" not in vd, (
            "the medians belong in S16.9 as description; in the main text they read as a finding")

    def test_the_supplement_says_the_crossing_is_the_same_artifact(self, supplement):
        """15 Oct 2026: the crossing of the two non-zero medians, and the sentence that called it
        the same artifact as the gap, went with the grid's exact recoveries. What S16.9 says in
        their place is what the pooled shift is, the brokers' mix, and that is what is held."""
        s = _s169(supplement)
        assert "happen to cross" not in s
        assert "The shift is the brokers' mix, not the check's." in s
        assert "the pooled shift measures which broker a group came from" in s
        assert "if anything the worse of the two" not in s

    def test_the_defect_that_prompted_this_is_caught(self, paper, supplement):
        """v5 (28 Sep): the statement of the shift is in S16.9, so the crossing is put in its
        place there; a crossing added to the sentence Section III-D kept is caught as well.

        15 Oct 2026: the statement S16.9 makes is the one inside each broker, and the crossing
        is put in its place; in the paper it is added after the per-broker sentence's last
        number, Redis's upper quartile."""
        bad, n = re.subn(r"no\s+shift\s+can\s+be\s+detected\s+between\s+the\s+groups",
                         "setting the exact recoveries aside crosses it", supplement)
        assert n == 1, "S16.9 has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_states_the_shift_not_a_crossing(paper, bad)
        # 5 Oct 2026: Section III-D's kept sentence was cut; the crossing is added after the
        # last number of the rebuilt recovery paragraph (Section VI-B) instead.
        bad, n = re.subn(re.escape(BS) + r"recoveryErrRedisHi(?![A-Za-z])(?:" + re.escape(BS)
                         + r"%)?\$?",
                         lambda m: m.group(0) + ", and setting the exact recoveries aside "
                         "crosses it", paper)
        assert n == 1, "Section VI-B has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_states_the_shift_not_a_crossing(bad, supplement)


class TestR2TheDescriptionsMatchTheData:
    """15 Oct 2026: three of the descriptions this class held were of the 50 us grid's pile of
    exact recoveries: Newcombe's interval on the two exact shares, the bands counted from the
    accepted upper quartile, and the largest gap in the accepted population that showed why
    bands and not clusters. At native resolution no group recovers exactly, the section
    describes no pile, and the macros went with it. Each test below says what it held and what
    it holds now."""

    def test_the_difference_interval_is_emitted_and_contains_zero(self, ledger):
        """Was Newcombe's interval on the difference of the two exact shares. Both shares are
        zero now, a difference with nothing in it to test, and it is no longer emitted; the
        two shares keep their Wilson intervals, which overlap (round 76)."""
        assert "recoveryExactDiff" not in ledger and "recoveryExactDiffCI" not in ledger
        assert ledger["recoveryPassExact"] == ledger["recoveryFailExact"] == "0"
        plo, phi = (float(v) for v in ledger["recoveryPassExactCI"].split("$--$"))
        flo, fhi = (float(v) for v in ledger["recoveryFailExactCI"].split("$--$"))
        assert plo == flo == 0.0 and phi > 0.0 and fhi > 0.0

    def test_overlap_is_no_longer_the_argument(self, supplement):
        """15 Oct 2026: S16.9 no longer compares the two exact shares at all, so neither the
        overlap argument nor its correction ("overlap is not the test") has a sentence left to
        stand in; the old wording stays refused."""
        s = _s169(supplement)
        assert "overlap across almost their whole length" not in s
        assert "overlap" not in s

    def test_the_shapes_are_counted_not_described(self, supplement):
        """15 Oct 2026: the shapes are tested, broker by broker, and their tails are printed:
        the Kolmogorov-Smirnov statistic for each broker, and each broker's upper quartile and
        worst error for each verdict in the table. The bands that counted the pile at zero
        went with it."""
        s = _s169(supplement)
        for gone in ("nearly flat", "second cluster", "spike at zero with a", "band edge"):
            assert gone not in s, gone
        for broker in ("Kafka", "Redis"):
            assert BS + "recovery%sKsD" % broker in s, broker
            for side in ("Pass", "Fail"):
                for tail in ("recoveryErr%s%sHi", "recovery%s%sMax"):
                    assert BS + tail % (broker, side) in s, tail % (broker, side)

    def test_the_counts_are_the_data(self, ledger):
        """15 Oct 2026: the table's cells are the four populations' own medians, upper
        quartiles, worst errors and counts, by the rules the ledger prints them with. Until
        then this held the band counts to the pooled populations."""
        import statistics
        import emit_paper_numbers as epn
        import stat_intervals as si
        cells = si.recovery_populations(split="both")
        for name, v in cells.items():
            assert ledger["recoveryErr" + name] == "%.1f" % statistics.median(v), name
            assert ledger["recoveryErr" + name + "Hi"] == epn._exposure_pct(
                si.nearest_rank(v, 0.75)), name
            assert ledger["recovery" + name + "Max"] == epn._exposure_pct(max(v)), name
            assert ledger["recovery" + name + "N"] == str(len(v)), name

    def test_a_cluster_would_have_been_wherever_the_eye_put_it(self, ledger, supplement):
        """Why bands and not clusters, until 15 Oct 2026: the referee grouped the accepted
        population with a break between 14.3% and 20%, and its largest gap was elsewhere, 20%
        to 29%. Neither was a property of the data a reader could check; a stated edge was.
        The bands then counted a pile at zero that was the grid's, and they went with it.
        What is held now is that neither a band nor a cluster came back in their place: no
        band or thirds macro is emitted, and S16.9 draws no boundary by eye."""
        assert not [n for n in ledger
                    if n.startswith("recovery") and ("Band" in n or "Thirds" in n)]
        s = _s169(supplement)
        for gone in ("largest gap", "a third in each", "cluster"):
            assert gone not in s, gone


class TestW1TheTwoPopulationsAreDrawn:

    def test_the_figure_is_built_by_the_pipeline_and_included(self, supplement):
        import make_result_figures as mrf
        assert "recovery" in mrf.main.__code__.co_consts or hasattr(mrf, "build_recovery")
        assert hasattr(mrf, "plot_recovery")
        assert "docs/results/figures/recovery_populations.pdf" in supplement
        assert (REPO / "docs" / "results" / "figures" / "recovery_populations.pdf").is_file()

    def test_the_caption_opens_on_a_claim_without_an_article(self, supplement):
        """15 Oct 2026: the figure draws the verdicts pooled and inside each broker, and its
        claim is the one S16.9 now makes. Until then the lead was "Two populations with no
        detectable shift between them.", which the pooled shift's interval no longer bears."""
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_caption_leads as tcl
        leads = {lab: tcl.lead(cap) for env, lab, cap in tcl.captions(supplement)}
        lead = leads.get("fig:recovery")
        assert lead == "Within each broker, no shift between the verdicts can be detected."
        assert not re.match(r"^(A|An|The)\b", lead)

    def test_the_caption_reads_its_crossing_from_the_curves(self, supplement, ledger, pops):
        """7 Oct 2026: the curves crossed twice, at 18.2% and 34.8%, as first computed;
        without the late messages they cross once, and the caption says once.

        15 Oct 2026: the caption names no crossing point. It says that inside each broker the
        two curves cross, and that pooled the rejected curve rises later; both are read from
        the curves here, and the counts it prints for each panel from the ledger's populations.
        The pooled crossing's macro went with the caption that quoted it."""
        import statistics
        import stat_intervals as si
        cap = " ".join(supplement[supplement.index("recovery_populations.pdf"):
                                  supplement.index(BS + "label{fig:recovery}")].split())
        assert "inside each broker the two curves cross" in cap
        assert "the rejected curve rises later" in cap
        assert not [n for n in ledger if n.startswith("recoveryEcdfCross")]
        cells = si.recovery_populations(split="both")
        for broker in ("Kafka", "Redis"):
            assert si.ecdf_crossings(cells[broker + "Pass"], cells[broker + "Fail"]), broker
            for side in ("Pass", "Fail"):
                assert BS + "recovery%s%sN" % (broker, side) in cap, broker + side
        assert min(pops["Fail"]) > min(pops["Pass"])
        assert statistics.median(pops["Fail"]) > statistics.median(pops["Pass"])

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
        # 15 Oct 2026: the shift's brackets are the pooled one and each broker's; the non-zero
        # shift's went with the non-zero populations, which at native resolution are the whole.
        brackets = ("recoveryShiftCI", "recoveryKafkaShiftCI", "recoveryRedisShiftCI")
        for macro in brackets:
            j = s.index("$" + BS + macro + "$)")
            label = s[s.rindex("(", 0, j):j]
            assert re.fullmatch(r"\(\$95" + re.escape(BS) + r"%\$ (?:percentile )?bootstrap: ",
                                label), (macro, label)
        text = " ".join(paper.split())
        label = re.compile(r"95" + re.escape(BS) + r"%\$? (?:percentile )?bootstrap: $")
        for macro in brackets:
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
        # 15 Oct 2026: every decade is written out, as the grid values are, since as 10^n its
        # exponent printed at 5.75 pt; one notation for the whole axis, not two.
        assert (fmt(10.0, 1), fmt(1e3, 3)) == ("10", "1k")
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
        # 15 Oct 2026: three labeled brackets, the pooled shift's and each broker's, where the
        # non-zero shift's "(95% bootstrap:" stood beside the pooled one.
        assert tight.count("(95%percentilebootstrap:") == 3
        assert "crosses it" not in " ".join(_rendered("paper").split())

    def test_the_supplement(self):
        """29 Sep: these are S16.9's words, which the postmortem keeps; postmortem.pdf.

        15 Oct 2026: the figure's new lead, and the sentence that says what the pooled shift
        is, in place of the old lead and the crossing of the non-zero medians."""
        flat = " ".join(_rendered("postmortem").split())
        assert "Within each broker, no shift between the verdicts can be detected" in flat
        assert "the pooled shift measures which broker a group came from" in flat
        assert "happen to cross" not in flat
