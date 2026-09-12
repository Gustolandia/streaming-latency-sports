r"""Round 68's referee items, pinned in the documents so a later pass cannot undo them.

The three required items were one defect wearing three faces: a number whose stated basis
was not the basis it was computed from. R1 printed a median as the floor of a percentile
band; R2 asserted a frequency over a literature with no denominator, against a record that
runs the other way; R3 anchored four ratios on the fit window while the sentence anchored
them on the mode.

The standing rule behind R1 lives in `test_printed_ranges.py`, because it applies to every
range the documents will ever print. What is here is what is specific to these sentences.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rendered_paper():
    return _text(REPO / "paper.pdf")


@pytest.fixture(scope="module")
def rendered_supplement():
    return _text(REPO / "supplement.pdf")


def _text(pdf):
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1TheExposureBand:

    def test_the_band_is_introduced_as_percentiles_not_as_a_span(self, paper):
        """"Spans" was the second half of the defect: 500-1900 us is the middle eighty per
        cent of the acknowledgment lag, not its range."""
        i = paper.index("not a constant")
        clause = paper[i:i + 320]
        assert "tenth and ninetieth percentiles" in clause
        assert "spans" not in clause, "a p10-p90 interval is not a span"

    def test_both_derived_bands_take_their_floor_from_the_tenth_percentile(self, paper):
        i = paper.index("not a constant")
        clause = paper[i:paper.index("Two consequences follow", i)]
        assert chr(92) + "exposureErrTenLo" in clause
        assert chr(92) + "exposureCrossoverLo" in clause

    def test_the_median_is_still_named_as_the_median(self, paper):
        """The clause before the band gives the median and must keep saying so."""
        i = paper.index("At our\nmedian acknowledgment lag") if "At our\nmedian" in paper \
            else paper.index("median acknowledgment lag")
        assert chr(92) + "exposureCrossover$" in paper[i:i + 480]

    def test_the_supplements_labelling_is_unchanged(self, supplement):
        """S12 was right all along, and is the wording the main text was reconciled to."""
        assert "the same error at the tenth and ninetieth percentiles of that lag" in supplement
        assert "the median lag and $" + chr(92) + "exposureCrossoverHi$~ms at the " \
               "ninetieth percentile" in supplement

    def test_the_rendered_numbers_are_the_percentile_ones(self, rendered_paper):
        """On the page, not in the source: the ledger can be right and the sentence wrong.

        The median's own numbers, 7% and 0.72 ms, sit in the clause *before* this one and
        must not reappear inside the band -- that reappearance was the defect.
        """
        flat = " ".join(rendered_paper.split())
        i = flat.index("not a constant")
        band = flat[i:flat.index("Two consequences follow", i)]
        assert "500" in band and "1900" in band, "the band names the two percentiles"
        assert "19%" in band and "1.90" in band, "and keeps its ninetieth-percentile ends"
        assert "0.50" in band, "the crossover floor is the tenth percentile, 0.50 ms"
        assert "0.72" not in band, \
            "the median crossover is back inside the band; that is round 68's defect"


class TestR2TheConcession:

    def test_the_concession_is_a_condition_and_not_a_frequency(self, paper):
        assert "Where a comparison reports a median above the" in paper
        assert "Most published comparisons" not in paper, \
            "a quantitative claim about a literature needs a denominator; this one had none"

    def test_the_exception_keeps_its_exhibit(self, paper):
        i = paper.index("Where a comparison reports a median above the")
        passage = paper[i:i + 700]
        assert "Not every comparison does" in passage
        assert "indexdev2026brokers" in passage

    def test_related_work_still_does_not_point_at_the_supplement(self, paper):
        """The referee's suggested wording ended "(Supplement S33.4 gives the record we
        assembled)" and it was applied before the suite named what it broke.

        R. Duvignau's annotation #12 -- related work is self-contained -- is gated in
        `test_writing_standards.py` and `test_attributed_claims.py`, and a third gate caught
        the same edit from another side: the pointer promised a record, and S33.4 carries no
        exhibit. A human referee's condition outranks a simulated one's suggested phrasing,
        and the substance of R2 never depended on the pointer.
        """
        i = paper.index(chr(92) + "section{Background and Related Work}")
        j = paper.index(chr(92) + "section{", i + 10)
        assert "Supplement" not in re.sub(r"(?m)^%[^\n]*", "", paper[i:j])

    def test_the_supplement_no_longer_quotes_a_sentence_the_paper_dropped(self, supplement):
        assert "The main text concedes that most published comparisons" not in supplement
        assert "The main text states the condition under which the deletion law does not bind" \
            in supplement

    def test_the_record_still_runs_two_of_three_the_other_way(self):
        """The count the concession is measured against, read from the artefact."""
        import csv
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "literature_regime.csv")
            .open(encoding="utf-8")))
        comparisons = [r for r in rows if r["kind"] == "broker_comparison"]
        inside = [r for r in comparisons if r["figures_inside_regime"] == "yes"]
        # Three of four, since round 72 added a March 2026 comparison that puts the whole
        # body of the distribution below the tick and redraws a 2024 benchmark to do it.
        # The concession the count qualifies is unchanged; the denominator grew and the
        # majority went with it, which is the direction round 68 predicted it would.
        assert (len(comparisons), len(inside)) == (4, 3)


class TestR3TheCollapseAboveTheMode:

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
    def test_the_sentence_prints_the_three_falls_above_the_mode(self, doc):
        text = (REPO / doc).read_text(encoding="utf-8")
        i = text.index("counts collapse")
        passage = text[i:i + 400]
        for macro in ("tracedModeFallA", "tracedModeFallB", "tracedModeFallC",
                      "tracedModeFallOctaves", "tracedLastBucketFall"):
            assert chr(92) + macro in passage, "%s is missing from %s" % (macro, doc)

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex"])
    def test_the_retired_fit_anchored_names_are_gone(self, doc):
        text = (REPO / doc).read_text(encoding="utf-8")
        for macro in ("tracedTailFallA", "tracedTailFallB", "tracedTailFallLast",
                      "tracedTailOctaves"):
            assert chr(92) + macro not in text

    def test_the_ledger_agrees_with_the_drawn_histogram(self):
        """The ratio a reader gets by dividing the two bars either side of the mode."""
        import sys
        sys.path.insert(0, str(REPO / "scripts"))
        import tail_index_traced as tit
        est = tit.estimate(dict(tit.traced_histograms())["ea9/l88_base"])
        mode = max(m[0] for m in est["modes"])
        bins = dict((b[0], b[2]) for b in tit.parse_runqlat(
            (REPO / est["path"]).read_text(encoding="utf-8"))[0])
        assert est["mode_falls"][0][1] == pytest.approx(
            bins[mode] / float(bins[mode * 2]), rel=1e-9)

    def test_the_rendered_sentence_carries_four_ratios(self, rendered_paper):
        flat = " ".join(rendered_paper.split())
        i = flat.index("collapse rather")
        passage = flat[i:i + 220]
        for n in ("5.0", "3.4", "4.7", "357"):
            assert n in passage, "%s missing from the collapse sentence" % n
        assert "three octaves" in passage


class TestRecommendedItems:

    def test_w1_the_retired_word_arm_is_in_neither_document(self, paper, supplement):
        """The co-author asked for it by name and neither document defines it."""
        for doc, text in (("paper", paper), ("supplement", supplement)):
            prose = re.sub(r"(?m)^%[^\n]*", "", text)
            assert not re.search(r"\barms?\b", prose), "%s still uses 'arm'" % doc

    def test_w1_the_vocabulary_check_is_clean_and_gates(self):
        import apply_vocabulary as av
        assert av.main(["--check", "paper.tex", "supplement.tex"]) == 0

    def test_w3_table_one_prints_its_measured_zeros(self, paper, rendered_paper):
        i = paper.index("label{tab:spans}")
        table = paper[i:paper.index("end{table}", i)]
        assert "---" not in table, "an em-dash in an IEEE table reads 'not measured'"
        assert "dashed" not in paper[:i][-900:], \
            "the caption stopped needing to explain the glyph"
        flat = " ".join(rendered_paper.split())
        assert flat.count("send (chain)0 0 0") == 3, \
            "all three send-referenced chain rows print three measured zeros -- the "\
            "acknowledgment lag joined them in round 70"
        assert "emission0 0 0" in flat, "and so does TTI"

    def test_w4_the_supplement_imports_the_papers_labels_under_a_prefix(self, supplement):
        assert chr(92) + "externaldocument[P-]{paper}" in supplement
        assert chr(92) + "externaldocument{paper}" not in supplement
        # The supplement refers to its own floats as well, and those must NOT be prefixed.
        # What must be is every label that actually lives in the paper, so the check runs
        # against the paper's own label set rather than against a naming pattern -- a
        # pattern would either miss `eq:` or condemn the supplement's own tables.
        aux = REPO / "paper.aux"
        if not aux.is_file():
            pytest.skip("paper.aux not built")
        theirs = set(re.findall(RE_BS + r"newlabel\{([^}]*)\}",
                                aux.read_text(encoding="utf-8", errors="replace")))
        referenced = set(re.findall(RE_BS + r"ref\{([^}]*)\}", supplement))
        leaked = sorted(theirs & referenced)
        assert not leaked, \
            "these point into the paper without the prefix and resolve to nothing: %s" % leaked
        assert theirs & {r[2:] for r in referenced if r.startswith("P-")}, \
            "no prefixed pointer resolves into the paper at all"

    def test_w4_the_build_is_free_of_multiply_defined_labels(self):
        log = REPO / "supplement.log"
        if not log.is_file():
            pytest.skip("supplement.log not present")
        assert "multiply defined" not in log.read_text(encoding="utf-8", errors="replace")

    def test_w5_the_supplement_does_not_date_itself_by_this_projects_rounds(
            self, rendered_supplement):
        """Its first page says nothing in it was asked for by a referee; a reader who has
        just been told that cannot resolve "round 59"."""
        assert not re.search(r"\b[Rr]ound \d+", rendered_supplement)

    def test_w6_the_colocation_rule_has_an_instance_that_is_not_our_own_audit(self, paper):
        i = paper.index("Do not assume co-location makes the measurement safer")
        rule = paper[i:i + 620]
        assert "mq-bench" in rule and "S33.3" in rule

    def test_w6_did_not_cost_the_busy_poll_sentence_a_correspondent_asked_for(self, paper):
        """The other half of W6 was applied and backed out, and this is why.

        The referee proposed trading this sentence away as the one speculation in a rule
        list whose authority is that everything in it was measured. The reasoning is sound
        and the conclusion was wrong: the sentence is J. Kunkel's, asked for in
        correspondence, and `TestTheReportingRulesAreInternallyConsistent` gates it because
        a requirement from correspondence carries referee weight in this project. It had
        already gone missing once in a page cut, which is why that gate exists. The
        co-location clause W6 wanted is kept; the trade is not made, and the page still
        holds at twelve.
        """
        assert "Busy-polling a dedicated core should buy the same" in paper
        i = paper.index("Do not assume co-location makes the measurement safer")
        assert "mq-bench" in paper[i:i + 620], "and the clause it was offered for stays too"
