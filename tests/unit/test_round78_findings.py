r"""Round 78's referee items, pinned so a later pass cannot quietly undo them.

The recommendation was accept, with one change asked for before proof.

R1. The manuscript said in four places that the two recovery populations are the same: "the
populations do not [differ]", "no shift remains", "They do not.", and Fig. S11's title. What
the data show is that the two cannot be told apart at these sample sizes. The 90% bootstrap
intervals on the two Hodges--Lehmann shifts would support equivalence only against margins of
8.3 and 7.1 points, about half the non-zero median errors, and Section VIII-A calls two brokers
equivalent only after a TOST against a stated margin. The pipeline now emits those margins
(`recoveryEquivMargin`, `recoveryNonzeroEquivMargin`), S16.9 states them and claims no
equivalence, and every sameness phrase became a statement about what was detected.

Recommended items, all taken. W1 labels the second bracket in Section V-D. W2 derives the band
edge from the accepted population's upper quartile, which it already equaled
(`stat_intervals.recovery_band_edge`), and states the range of edges over which the thirds
hold. W3 draws the rejected conditions in grey rather than in the red Figure 4 uses for
deleted. W4 keeps Fig. S11 below the heading of its section. W5 names cloud variability as an
internal-validity threat in S19, citing Henning et al. W6 sets the Go and Rust HdrHistogram
documentation beside the Java documentation in S24.

One correction to the referee, found by checking its advice against the source. W6 said the
Rust port "states that HDR bucketing is for non-negative magnitudes". That phrase is not in the
crate documentation. What the documentation does say -- that `record` "will error if the
value is too small or large" -- is quoted instead, and it makes the same point.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent


def _bibliographies():
    """Both reference files, joined: the one the paper and the supplement cite, and the
    postmortem's own, which moved to a file of its own on 7 Oct 2026. An entry is checked
    wherever it lives."""
    return "\n".join((REPO / name).read_text(encoding="utf-8")
                     for name in ("manuscript_references.bib", "postmortem_references.bib"))
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bib():
    return _bibliographies()


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


#: What Section III-D may say about the two recovery populations: what the data cannot do, in
#: B18's wording ("cannot be told apart", round 78's) or its active form ("the data cannot tell
#: apart", v5's).
NOT_TOLD_APART = r"cannot\s+(?:be\s+told|tell)\s+apart"

#: 5 Oct 2026: the rebuilt paper's recovery paragraph (Section VI-B) cut that sentence. It
#: prints both populations' medians over their counts and both upper quartiles and says
#: nothing about them, sameness included; its last number is where a claim would be added.
#: 15 Oct 2026: the paragraph quotes the recovery by broker, and its last number is Redis's
#: upper quartile, taken with or without the per cent sign and the closing dollar.
RECOVERY_END = (re.escape(BS) + r"recoveryErrRedisHi(?![A-Za-z])(?:" + re.escape(BS)
                + r"%)?\$?")


def _s169(supplement):
    i = supplement.index("S16.9.")
    return " ".join(supplement[i:supplement.index("S17. The 1970 counter note")].split())


def _rendered_pages(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return [" ".join((p.extract_text() or "").split()) for p in pypdf.PdfReader(str(pdf)).pages]


def _entry(bib, key):
    i = bib.index("{" + key + ",")
    return " ".join(bib[i:bib.index("\n}", i)].split())


class TestR1TheWordsSayWhatTheIntervalsSay:

    def test_the_margins_are_emitted_from_the_90_percent_intervals(self, ledger):
        """15 Oct 2026: the margins of the two shifts S16.9 states as undetectable, each
        broker's, at the digits its interval is printed to. The pooled and non-zero margins
        went with the pooled claim, whose interval now excludes zero."""
        import stat_intervals as si
        cells = si.recovery_populations(split="both")
        for broker in ("Kafka", "Redis"):
            a, b = cells[broker + "Pass"], cells[broker + "Fail"]
            lo, hi = si.hl_bootstrap_ci(a, b, conf=0.90)
            digits = len(ledger["recovery%sShift" % broker].split(".")[1])
            assert ledger["recovery%sEquivMargin" % broker] == "%.*f" % (
                digits, round(max(abs(lo), abs(hi)), digits) + 0.0), broker
        assert "recoveryEquivMargin" not in ledger and "recoveryNonzeroEquivMargin" not in ledger

    def test_they_are_the_values_the_referee_computed(self, ledger):
        """8.3 and 7.1 as the referee computed them; 7.1 and 7.5 since the late messages
        were left out of the groups (7 Oct 2026); 10.4 and 10.4 at native resolution, where
        the non-zero populations are the whole ones. 15 Oct 2026: the margins S16.9 quotes
        are each broker's, 0.39 points on Kafka and 5.9 on Redis."""
        assert (ledger["recoveryKafkaEquivMargin"], ledger["recoveryRedisEquivMargin"]) == \
            ("0.39", "5.9")

    def test_about_half_the_non_zero_median_errors(self, ledger):
        """S16.9 says so in words. Were the margins to shrink to a small fraction of the errors,
        an equivalence claim might become defensible and the sentence would need re-arguing.

        15 Oct 2026: the words are "about the whole of Kafka's median error, and two-fifths of
        Redis's", so each broker's margin is held to its own broker's median error."""
        kafka = float(ledger["recoveryKafkaEquivMargin"]) / float(ledger["recoveryErrKafka"])
        redis = float(ledger["recoveryRedisEquivMargin"]) / float(ledger["recoveryErrRedis"])
        assert 0.8 <= kafka <= 1.25, ("about the whole of Kafka's median error", kafka)
        assert 0.35 <= redis <= 0.45, ("two-fifths of Redis's", redis)
        s = _s169((REPO / "postmortem.tex").read_text(encoding="utf-8"))
        assert ("about the whole of " + BS + "kafka{}'s median error, and two-fifths of "
                + BS + "redis{}'s") in s

    def test_the_main_text_asserts_no_sameness(self, paper, supplement):
        """v5 (28 Sep): Section III-D kept one sentence of result, "two populations the data
        cannot tell apart", and the shift clause went to S16.9 with V-D's other statistics
        (editorial review, Section 5), where it reads "no shift can be detected". The refused
        phrases gain "indistinguishable": the editor's suggested wording for this sentence, and
        the word B18 names as where the drift to sameness began.

        5 Oct 2026: the rebuilt paper cut the kept sentence and prints the two populations'
        medians and upper quartiles with no word about them, so "cannot tell apart" is no
        longer required there; every sameness phrase stays refused, and should the paper
        describe the two populations again it must say what the data cannot do."""
        vd = _vd(paper)
        for gone in ("the populations do not.", "no shift remains", "indistinguishable",
                     "the same population", "do not differ"):
            assert gone not in vd, gone
        if re.search(r"\bpopulations?\b", vd):
            assert re.search(NOT_TOLD_APART, vd), \
                "the paper describes the two populations without saying what the data cannot do"
        assert "no shift can be detected" in _s169(supplement)

    def test_the_supplement_asserts_no_sameness(self, supplement):
        """15 Oct 2026: what the data cannot do is now said of each broker ("within either
        broker, no shift can be detected"), where until then "Nothing in these data separates
        them." was said of the pooled verdicts, whose shift now excludes zero. The margins
        stated are each broker's, and the refusals stand."""
        s = _s169(supplement)
        for gone in ("They do not.", "no shift is left to explain",
                     "nothing to choose between the populations", "no shift between them",
                     "Nothing in these data separates them."):
            assert gone not in s, gone
        assert "within either broker, no shift can be detected" in s
        assert "claims no equivalence" in s
        assert BS + "recoveryKafkaEquivMargin" in s and BS + "recoveryRedisEquivMargin" in s
        assert BS + "mainBrokers" in s and "TOST" in s

    def test_the_figure_title_and_its_list_entry_change_together(self, supplement):
        """15 Oct 2026: the lead is the figure's new claim (see round 77's caption pin)."""
        at = supplement.index("recovery_populations.pdf")
        m = re.search(re.escape(BS) + r"caption\[([^\]]*)\]\{" + re.escape(BS)
                      + r"textbf\{([^}]*)\}", supplement[at:])
        short, lead = m.group(1), " ".join(m.group(2).split())
        assert lead == "Within each broker, no shift between the verdicts can be detected."
        assert short == lead[:-1]

    def test_the_defect_that_prompted_this_is_caught(self, paper, supplement):
        """v5 (28 Sep): the anchor is Section III-D's "cannot tell apart", replaced by the
        sameness claim round 78 removed.

        5 Oct 2026: the sentence was cut, so the sameness claim round 78 removed is added
        after the rebuilt recovery paragraph's last number instead (see `RECOVERY_END`)."""
        bad, n = re.subn(RECOVERY_END, lambda m: m.group(0) + "; the populations do not.",
                         paper)
        assert n == 1, "Section VI-B has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_asserts_no_sameness(bad, supplement)

    def test_the_supplement_defect_is_caught_too(self, supplement):
        """15 Oct 2026: the sentence the sameness claim replaces is S16.9's statement inside
        the brokers, where "Nothing in these data separates them." stood until then."""
        bad, n = re.subn(r"within either broker, no shift can be detected between the groups\s+"
                         r"the check accepts and those it rejects\.", "They do not.", supplement)
        assert n == 1, "S16.9 has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_supplement_asserts_no_sameness(bad)


class TestW1EveryBracketInSectionVDSaysWhatItIs:

    #: Each bracket's label as S16.9 prints it: the method and the level, inside the bracket.
    #: 15 Oct 2026: the pooled shift's and each broker's; the non-zero shift's bracket went with
    #: the non-zero populations, which at native resolution are the whole ones.
    LABELS = {"recoveryShiftCI": "($95" + BS + "%$ percentile bootstrap: ",
              "recoveryKafkaShiftCI": "($95" + BS + "%$ percentile bootstrap: ",
              "recoveryRedisShiftCI": "($95" + BS + "%$ percentile bootstrap: "}

    def test_both_brackets_are_labeled(self, paper, supplement):
        """v5 (28 Sep): both brackets left Section V-D for S16.9 with the shifts they qualify
        (editorial review, Section 5), and S16.9 prints them in parentheses. Each is held to its
        label there, and neither may return to the article without one."""
        s = _s169(supplement)
        for macro, label in self.LABELS.items():
            j = s.index("$" + BS + macro + "$)")
            k = s.rindex("(", 0, j)
            assert s[k:j] == label, (macro, s[k:j])
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_bracket_labels as tbl
        bare = [n for n, _ in tbl.unlabeled(paper) if n in self.LABELS]
        assert not bare, bare

    def test_a_bare_bracket_is_caught(self, paper, supplement):
        """v5 (28 Sep): the label is stripped from S16.9's second bracket, where it now is.
        15 Oct 2026: the last bracket is Redis's shift's."""
        bad, n = re.subn(r"\(\$95" + re.escape(BS) + r"%\$\s+percentile\s+bootstrap:\s+(\$"
                         + re.escape(BS) + r"recoveryRedisShiftCI\$\))", r"(\1", supplement)
        assert n == 1, "S16.9 has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_both_brackets_are_labeled(paper, bad)


class TestW2TheBandEdgeIsTheQuartile:
    """15 Oct 2026: the bands, their edge and the thirds went with the pile of exact recoveries
    they counted, which was the 50 us grid's; `stat_intervals.recovery_band_edge` and
    `equal_split_edges` were deleted with them. What round 78 asked of the edge -- that it be
    the upper quartile the table prints, by one rule, and that figure and ledger take it from
    one place -- is asked now of the table's upper-quartile column and of the one loader both
    read. Each test says what it held until that day."""

    def test_the_constant_is_gone(self):
        import stat_intervals as si
        assert not hasattr(si, "RECOVERY_BAND_PCT"), (
            "a constant that equals a quartile is free to part from it")

    def test_the_edge_is_the_upper_quartile_the_table_prints(self, ledger, pops):
        """Was: the band edge equals the accepted upper quartile and `recoveryErrPassHi`. Now:
        every upper quartile the table prints is the nearest-rank one of its population."""
        import stat_intervals as si
        for side in ("Pass", "Fail"):
            assert ledger["recoveryErr%sHi" % side] == "%.0f" % si.nearest_rank(pops[side], 0.75)
        import emit_paper_numbers as epn
        for name, v in si.recovery_populations(split="both").items():
            assert ledger["recoveryErr%sHi" % name] == epn._exposure_pct(
                si.nearest_rank(v, 0.75)), name

    def test_the_figure_and_the_ledger_call_the_same_function(self):
        """Was: both call `recovery_band_edge`. Now: both read each broker's two verdicts
        through `recovery_populations(split="both")`, so the table and the panels cannot
        part."""
        import inspect
        import emit_paper_numbers as epn
        import make_result_figures as mrf
        for source in (inspect.getsource(mrf.build_recovery),
                       inspect.getsource(epn._recovery_macros)):
            assert 'recovery_populations(' in source and 'split="both"' in source

    def test_the_thirds_hold_over_the_stated_range_and_nowhere_else(self, ledger):
        """Was: the accepted groups split into thirds for edges in the stated range alone.
        At native resolution no group recovers exactly, so no edge gives thirds and the range
        was read from the grid's columns only to keep the old sentence building. The sentence
        and that bridge are gone, and neither the macros nor the functions may come back."""
        import stat_intervals as si
        for name in ("recovery_band_edge", "equal_split_edges", "RECOVERY_BAND_QUANTILE"):
            assert not hasattr(si, name), name
        assert not [n for n in ledger
                    if n.startswith("recovery") and ("Thirds" in n or "Band" in n)]

    def test_the_supplement_says_what_the_edge_is(self, supplement):
        """Was: S16.9 says the edge is the accepted upper quartile and the range of thirds.
        Now: it says what its Q3 column is, and no band edge is left in the text or the
        caption."""
        s = _s169(supplement)
        assert ("\\emph{Median}, \\emph{Q3} and \\emph{Worst} are the median, the upper quartile "
                "and the largest of the groups' errors") in s
        for gone in ("band edge", "The edge is not a free choice", "for no other"):
            assert gone not in s, gone
        cap = supplement[supplement.index("recovery_populations.pdf"):
                         supplement.index(BS + "label{fig:recovery}")]
        assert "band" not in " ".join(cap.split())

    def test_nearest_rank_returns_a_value_the_data_contain(self):
        import stat_intervals as si
        assert si.nearest_rank([3.0, 1.0, 2.0], 0.75) == 3.0
        assert si.nearest_rank([1.0, 2.0, 3.0, 4.0, 5.0], 0.75) == 4.0
        with pytest.raises(ValueError):
            si.nearest_rank([], 0.5)

    @staticmethod
    def _macros(tmp_path, passing):
        import emit_paper_numbers as epn
        rows = ["condition,recovery_err_us,median_D_us,rho_DA,median_A_us,median_S_us"]
        rows += ["p%d#pass,%d,1000,0.5,10,900" % (i, e) for i, e in enumerate(passing)]
        rows += ["f%d#fail,%d,1000,0.5,10,900" % (i, e) for i, e in enumerate((0, 60, 120, 180))]
        path = tmp_path / "span_symmetry.csv"
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return dict(epn._recovery_macros(str(path)))

    @pytest.mark.parametrize("passing", [
        # The four shapes round 78 and 7 Oct 2026 held the thirds to: thirds that reach the
        # quartile, too few exact recoveries, thirds just short of the quartile (the committed
        # shape from 7 to 15 Oct 2026), and a quartile away from the split.
        (0, 0, 50, 100, 150, 200),
        (0, 50, 100, 150, 200),
        (0,) * 6 + tuple(10 * i for i in range(1, 13)),
        (0,) * 10 + tuple(10 * i for i in range(1, 21)),
    ])
    def test_no_shape_brings_a_band_or_a_third_back(self, tmp_path, passing):
        """Was four tests, one per shape, of when the thirds were emitted. Now no shape emits
        them, while exact recoveries a file does hold are still counted, with their interval."""
        got = self._macros(tmp_path, passing)
        assert not [n for n in got if "Band" in n or "Thirds" in n]
        exact = sum(1 for e in passing if e == 0)
        assert got["recoveryPassExact"] == "%.0f" % (100.0 * exact / len(passing))
        assert "recoveryPassExactCI" in got


class TestW3RedMeansDeletedAndNothingElse:

    def test_the_rejected_population_is_not_drawn_in_deleted_red(self, pops):
        """15 Oct 2026: three panels of curves with a mark per group, where there were a
        panel of curves and a strip; the rule holds on every line and mark of all three, and
        Redis's red from the paper's other figures is refused too, since here red would read as
        deleted or as Redis and is meant as neither."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import to_hex
        import make_result_figures as mrf
        import stat_intervals as si
        fig, axes = plt.subplots(1, 3)
        try:
            mrf.plot_recovery(axes, pops, si.recovery_populations(split="both"))
            colours = {to_hex(line.get_color()) for ax in axes for line in ax.lines}
        finally:
            plt.close(fig)
        assert to_hex(mrf.DELETED) not in colours
        assert to_hex(dict((k, c) for k, _n, c in mrf.BROKER_COLOURS)["redis"]) not in colours
        assert to_hex(mrf.KEPT) in colours and to_hex(mrf.GREY) in colours

    def test_the_defect_that_prompted_this_is_caught(self, pops, monkeypatch):
        import make_result_figures as mrf
        monkeypatch.setattr(mrf, "GREY", mrf.DELETED)
        with pytest.raises(AssertionError):
            self.test_the_rejected_population_is_not_drawn_in_deleted_red(pops)


class TestW4TheFigureFollowsItsHeading:

    def test_the_float_is_defined_after_the_heading_and_not_sent_to_the_top(self, supplement):
        at = supplement.index("recovery_populations.pdf")
        assert supplement.index("S16.9.") < at
        env = supplement.rindex(BS + "begin{figure}", 0, at)
        opt = re.match(re.escape(BS) + r"begin\{figure\}\[(\w*)\]", supplement[env:]).group(1)
        assert "t" not in opt, "a top float lands above the heading of the page it shares"

    def test_on_the_rendered_page_the_heading_comes_first(self):
        """29 Sep: S16.9 and Fig. S11 are the postmortem's; its pages are postmortem.pdf.
        15 Oct 2026: the caption's new lead."""
        pages = _rendered_pages("postmortem")
        heading = "S16.9. The displacement recovery, distribution by distribution"
        caption = "Within each broker, no shift between the verdicts can be detected."
        h = max(i for i, t in enumerate(pages) if heading in t)
        f = max(i for i, t in enumerate(pages) if caption in t)
        assert f >= h
        if f == h:
            assert pages[h].index(heading) < pages[h].rindex(caption)


class TestW5CloudNoiseIsANamedThreat:

    def test_s19_names_it_and_cites_the_study(self, supplement):
        i = supplement.index("S19. Threats to the scheduling attribution")
        s = " ".join(supplement[i:supplement.index("External validity: one workload", i)].split())
        assert "Internal validity: the cloud's own noise" in s
        assert BS + "cite{henning2025variability}" in s
        assert BS + "GeomReplFactor" in s and BS + "rtFactorHigh" in s
        assert "context rather than a test" in s, "their metric is not ours, and the text says so"

    def test_the_effects_named_are_the_smallest_and_the_largest(self, ledger):
        # Every manipulation factor on the negative-span rate: Table III's four pairs and the
        # priority range across the load sweep. The payload factor is on transport, not on
        # the rate, and is not a manipulation effect of the kind the sentence names.
        names = ("rtLowFactor", "rtHighFactor", "GeomOrigFactor", "GeomReplFactor",
                 "rtFactorLow", "rtFactorHigh")
        factors = [float(ledger[n]) for n in names]
        assert float(ledger["GeomReplFactor"]) == min(factors)
        assert float(ledger["rtFactorHigh"]) == max(factors)
        assert 1.5 < float(ledger["GeomReplFactor"]) < 2.5, "'about a hundred percent'"

    def test_the_article_cites_none_of_the_three(self, paper):
        """At 45 of 45 references each would displace something (the referee's own advice)."""
        for key in ("henning2025variability", "hdrhistogram_go", "hdrhistogram_rust"):
            assert key not in paper, key

    def test_the_entry_matches_the_abstract(self, bib):
        e = _entry(bib, "henning2025variability")
        assert "2504.11826" in e and "FSE" in e
        assert "Henning, S" in e and "Rabiser, Rick" in e
        assert "below 3.7" in e and "2366 benchmarks" in e


class TestW6ThePortsThatDocumentIt:

    def test_s24_sets_both_ports_beside_the_java_documentation(self, supplement):
        i = supplement.index("The library's own documentation does not describe")
        s = " ".join(supplement[i:i + 2200].split())
        for key in ("hdrhistogram_javadoc", "hdrhistogram_go", "hdrhistogram_rust"):
            assert BS + "cite{" + key + "}" in s, key
        assert "an error if the value is out of range" in s
        assert "will error if the value is too small or large" in s

    def test_each_quote_is_the_one_recorded_in_the_bibliography(self, bib):
        for key, quote in (("hdrhistogram_go", "an error if the value is out of range"),
                           ("hdrhistogram_rust", "will error if the value is too small or large")):
            assert quote in _entry(bib, key), key

    def test_the_phrase_the_crate_docs_do_not_contain_is_not_quoted(self, supplement):
        assert "non-negative magnitudes" not in supplement


class TestTheRenderedPagesCarryIt:

    def test_the_main_text(self):
        """v5 (28 Sep): the article prints Section III-D's "cannot tell apart"; the undetectable
        shift and both labeled brackets print on S16.9's pages (editorial review, Section 5),
        matched with spaces removed because the extractor drops them around inline math.
        29 Sep: S16.9 is the postmortem's, so its pages are read from postmortem.pdf.
        5 Oct 2026: the rebuilt article prints no such sentence (see the source pin above)
        and no sameness claim; it is held to the second on its pages."""
        flat = " ".join(_rendered_pages("paper"))
        for gone in ("The populations do not.", "no shift remains", "indistinguishable"):
            assert gone not in flat, gone
        supp = " ".join(_rendered_pages("postmortem"))
        tight = "".join(supp[supp.rindex("S16.9. The displacement recovery"):
                             supp.rindex("S16.10. How late")].split())
        assert "noshiftcanbedetected" in tight
        assert tight.count("(95%percentilebootstrap:") + tight.count("(95%bootstrap:") >= 2

    def test_the_supplement(self):
        """29 Sep: these are S16.9's words, which the postmortem keeps; postmortem.pdf.
        15 Oct 2026: S16.9 says of each broker what it said of the pooled verdicts, and the
        figure's lead says the same."""
        flat = " ".join(_rendered_pages("postmortem"))
        assert "within either broker, no shift can be detected" in flat
        assert "no shift between the verdicts can be detected" in flat
        assert "claims no equivalence" in flat
        assert "Nothing in these data separates them." not in flat
