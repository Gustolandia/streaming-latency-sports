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
BS = chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bib():
    return (REPO / "manuscript_references.bib").read_text(encoding="utf-8")


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
    i = paper.index("The displacement can be recovered rather than discarded")
    return " ".join(paper[i:i + 1600].split())


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

    def test_the_margins_are_emitted_from_the_90_percent_intervals(self, ledger, pops):
        import stat_intervals as si
        a, b = pops["Pass"], pops["Fail"]
        na, nb = [v for v in a if v > 0], [v for v in b if v > 0]
        for macro, (x, y) in (("recoveryEquivMargin", (a, b)),
                              ("recoveryNonzeroEquivMargin", (na, nb))):
            lo, hi = si.hl_bootstrap_ci(x, y, conf=0.90)
            assert ledger[macro] == "%.1f" % (round(max(abs(lo), abs(hi)), 1) + 0.0), macro

    def test_they_are_the_values_the_referee_computed(self, ledger):
        assert (ledger["recoveryEquivMargin"], ledger["recoveryNonzeroEquivMargin"]) == \
            ("8.3", "7.1")

    def test_about_half_the_non_zero_median_errors(self, ledger):
        """S16.9 says so in words. Were the margins to shrink to a small fraction of the errors,
        an equivalence claim might become defensible and the sentence would need re-arguing."""
        medians = (float(ledger["recoveryErrPassNonzero"]),
                   float(ledger["recoveryErrFailNonzero"]))
        for macro in ("recoveryEquivMargin", "recoveryNonzeroEquivMargin"):
            for med in medians:
                assert 0.33 <= float(ledger[macro]) / med <= 0.67, (macro, med)

    def test_the_main_text_asserts_no_sameness(self, paper):
        vd = _vd(paper)
        for gone in ("the populations do not.", "no shift remains"):
            assert gone not in vd, gone
        assert "the populations cannot be told apart" in vd
        assert "no shift is detectable" in vd

    def test_the_supplement_asserts_no_sameness(self, supplement):
        s = _s169(supplement)
        for gone in ("They do not.", "no shift is left to explain",
                     "nothing to choose between the populations", "no shift between them"):
            assert gone not in s, gone
        assert "Nothing in these data separates them." in s
        assert "claims no equivalence" in s
        assert BS + "recoveryEquivMargin" in s and BS + "recoveryNonzeroEquivMargin" in s
        assert BS + "mainBrokers" in s and "TOST" in s

    def test_the_figure_title_and_its_list_entry_change_together(self, supplement):
        at = supplement.index("recovery_populations.pdf")
        m = re.search(re.escape(BS) + r"caption\[([^\]]*)\]\{" + re.escape(BS)
                      + r"textbf\{([^}]*)\}", supplement[at:])
        short, lead = m.group(1), " ".join(m.group(2).split())
        assert lead == "Two populations with no detectable shift between them."
        assert short == lead[:-1]

    def test_the_defect_that_prompted_this_is_caught(self, paper):
        bad, n = re.subn(r"the populations cannot\s+be told apart\.",
                         "the populations do not.", paper)
        assert n == 1, "Section V-D has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_main_text_asserts_no_sameness(bad)

    def test_the_supplement_defect_is_caught_too(self, supplement):
        bad, n = re.subn(r"Nothing in these data separates them\.", "They do not.", supplement)
        assert n == 1, "S16.9 has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_the_supplement_asserts_no_sameness(bad)


class TestW1EveryBracketInSectionVDSaysWhatItIs:

    def test_both_brackets_are_labeled(self, paper):
        vd = _vd(paper)
        for macro in ("recoveryShiftCI", "recoveryNonzeroShiftCI"):
            j = vd.index("$" + BS + macro + "$]")
            k = vd.rindex("[", 0, j)
            assert vd[k:j] == "[95" + BS + "% bootstrap: ", (macro, vd[k:j])

    def test_a_bare_bracket_is_caught(self, paper):
        bad, n = re.subn(r"\[95" + re.escape(BS) + r"%\s+bootstrap:\s+(\$" + re.escape(BS)
                         + r"recoveryNonzeroShiftCI\$\])", r"[\1", paper)
        assert n == 1, "Section V-D has been reworded; retarget this mutation"
        with pytest.raises(AssertionError):
            self.test_both_brackets_are_labeled(bad)


class TestW2TheBandEdgeIsTheQuartile:

    def test_the_constant_is_gone(self):
        import stat_intervals as si
        assert not hasattr(si, "RECOVERY_BAND_PCT"), (
            "a constant that equals a quartile is free to part from it")

    def test_the_edge_is_the_upper_quartile_the_table_prints(self, ledger, pops):
        import stat_intervals as si
        edge = si.recovery_band_edge(pops)
        assert edge == si.nearest_rank(pops["Pass"], 0.75)
        assert ledger["recoveryBandPct"] == ledger["recoveryErrPassHi"] == "%.0f" % edge

    def test_the_figure_and_the_ledger_call_the_same_function(self):
        import inspect
        import emit_paper_numbers as epn
        import make_result_figures as mrf
        assert "recovery_band_edge(" in inspect.getsource(mrf.build_recovery)
        assert "recovery_band_edge(" in inspect.getsource(epn._recovery_macros)

    def test_the_thirds_hold_over_the_stated_range_and_nowhere_else(self, ledger, pops):
        import stat_intervals as si
        a = pops["Pass"]
        lo, hi = si.equal_split_edges(a)
        assert ledger["recoveryThirdsEdgeLo"] == "%.1f" % lo
        assert hi == si.recovery_band_edge(pops)

        def tally(e):
            return (sum(v == 0.0 for v in a), sum(0.0 < v < e for v in a),
                    sum(v >= e for v in a))
        thirds = (len(a) // 3,) * 3
        for e in (lo + 1e-6, (lo + hi) / 2.0, hi):
            assert tally(e) == thirds, e
        for e in (lo, lo - 1.0, hi + 1e-6, hi + 5.0):
            assert tally(e) != thirds, e

    def test_the_supplement_says_what_the_edge_is(self, supplement):
        s = _s169(supplement)
        assert "The edge is not a free choice" in s and "upper quartile" in s
        assert BS + "recoveryThirdsEdgeLo" in s and "for no other" in s
        cap = supplement[supplement.index("recovery_populations.pdf"):
                         supplement.index(BS + "label{fig:recovery}")]
        assert "upper quartile" in " ".join(cap.split())

    def test_equal_split_edges_refuses_what_cannot_split(self):
        import stat_intervals as si
        assert si.equal_split_edges([]) is None
        assert si.equal_split_edges([0.0, 1.0, 2.0, 3.0]) is None      # three non-zero
        assert si.equal_split_edges([1.0, 2.0, 2.0, 3.0]) is None      # a tie at the split
        assert si.equal_split_edges([0.0, 1.0, 2.0, 3.0, 4.0]) == (2.0, 3.0)

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

    def test_where_the_thirds_hold_the_range_is_emitted(self, tmp_path):
        got = self._macros(tmp_path, (0, 0, 50, 100, 150, 200))
        assert got["recoveryBandPct"] == "15" and got["recoveryThirdsEdgeLo"] == "10.0"

    def test_too_few_exact_recoveries_emit_nothing(self, tmp_path):
        got = self._macros(tmp_path, (0, 50, 100, 150, 200))
        assert "recoveryBandPct" in got and "recoveryThirdsEdgeLo" not in got

    def test_a_quartile_away_from_the_split_emits_nothing(self, tmp_path):
        # Six exact and twelve non-zero at 1%..12%: the halves split between 6% and 7%, and the
        # nearest-rank upper quartile of eighteen values is the fourteenth, 8%. In the real data
        # the two coincide only because several conditions tie at the quartile.
        got = self._macros(tmp_path, (0,) * 6 + tuple(10 * i for i in range(1, 13)))
        assert got["recoveryBandPct"] == "8" and "recoveryThirdsEdgeLo" not in got


class TestW3RedMeansDeletedAndNothingElse:

    def test_the_rejected_population_is_not_drawn_in_deleted_red(self, pops):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import to_hex
        import make_result_figures as mrf
        import stat_intervals as si
        fig, (ax_cdf, ax_strip) = plt.subplots(1, 2)
        try:
            mrf.plot_recovery(ax_cdf, ax_strip, pops, si.recovery_band_edge(pops))
            colours = {to_hex(line.get_color()) for line in ax_cdf.lines}
            for coll in ax_strip.collections:
                colours |= {to_hex(fc) for fc in coll.get_facecolors()}
        finally:
            plt.close(fig)
        assert to_hex(mrf.DELETED) not in colours
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
        pages = _rendered_pages("supplement")
        heading = "S16.9. The displacement recovery, distribution by distribution"
        caption = "Two populations with no detectable shift between them."
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
        flat = " ".join(_rendered_pages("paper"))
        assert "cannot be told apart" in flat and "no shift is detectable" in flat
        assert flat.count("95% bootstrap") >= 2

    def test_the_supplement(self):
        flat = " ".join(_rendered_pages("supplement"))
        assert "Nothing in these data separates them." in flat
        assert "no detectable shift between them" in flat
        assert "claims no equivalence" in flat
