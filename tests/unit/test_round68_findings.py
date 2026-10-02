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
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rendered_paper():
    return _text(REPO / "paper.pdf")


@pytest.fixture(scope="module")
def rendered_supplement():
    return _text(REPO / "postmortem.pdf")


def _text(pdf):
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


def _band_start(paper):
    """Where Section III-D introduces the band of acknowledgment lags.

    v5 (28 Sep): the clause no longer opens "$A$ is not a constant"; it reads "Across
    conditions $A$ runs ... between its tenth and ninetieth percentiles", and the source wraps
    inside both phrases, so they are matched whitespace-tolerantly.
    """
    m = re.search(r"Across\s+conditions\s+\$A\$\s+runs", paper)
    assert m, "the exposure band's clause has gone from Section III-D"
    return m.start()


class TestR1TheExposureBand:

    def test_the_band_is_introduced_as_percentiles_not_as_a_span(self, paper):
        """"Spans" was the second half of the defect: 500-1900 us is the middle eighty per
        cent of the acknowledgment lag, not its range.

        v5 (28 Sep): anchored on the v5 clause (see `_band_start`); the checks are unchanged.
        """
        i = _band_start(paper)
        clause = paper[i:i + 320]
        assert re.search(r"tenth\s+and\s+ninetieth\s+percentiles", clause)
        assert "spans" not in clause, "a p10-p90 interval is not a span"

    def test_both_derived_bands_take_their_floor_from_the_tenth_percentile(self, paper):
        """v5 (28 Sep): the band's paragraph is now followed by Fig. 4 rather than by the
        paragraph that opened "Two consequences follow", so the clause runs to the end of its
        own paragraph."""
        i = _band_start(paper)
        clause = paper[i:paper.index("\n\n", i)]
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

        v5 (28 Sep): the band opens "Across conditions" and ends at its pointer to Fig. 4,
        whose caption quotes the median crossover; bounding the band by its own "(Fig." keeps
        a float that lands mid-paragraph from putting 0.72 inside it.
        """
        flat = " ".join(rendered_paper.split())
        i = flat.index("Across conditions")
        # 1 Oct 2026: the band moved into Fig. 4's caption, so it ends at its own sentence.
        j = flat.index("crossover at", i)
        band = flat[i:flat.index("ms", j) + 2]
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
        assert "Some give no number to place" in passage
        assert "indexdev2026brokers" in passage

    def test_related_work_still_does_not_point_at_the_supplement(self, paper):
        """The referee's suggested wording ended "(Supplement S33.4 gives the record we
        assembled)" and it was applied before the suite named what it broke.

        R. Duvignau's annotation #12 -- related work is self-contained -- is gated in
        `test_writing_standards.py` and `test_attributed_claims.py`, and a third gate caught
        the same edit from another side: the pointer promised a record, and S33.4 carries no
        exhibit. A condition set in correspondence outranks a review round's suggested phrasing,
        and the substance of R2 never depended on the pointer.

        v5 (28 Sep): the section is Section VII, "Related Work", after the results.
        """
        i = paper.index(chr(92) + "section{Related Work}")
        j = paper.index(chr(92) + "section{", i + 10)
        assert "Supplement" not in re.sub(r"(?m)^%[^\n]*", "", paper[i:j])

    def test_the_supplement_no_longer_quotes_a_sentence_the_paper_dropped(self, supplement):
        assert "The main text concedes that most published comparisons" not in supplement
        # Round 79 (R1): the pointer now names its section, Section~\mainRelatedBench{}.
        assert "states the condition under which the deletion law does not bind" in supplement

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

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex", "postmortem.tex"])
    def test_the_sentence_prints_the_three_falls_above_the_mode(self, doc):
        """v5 (28 Sep): Section III-C was cut to a few sentences and, in the paper, the falls
        went with it; they are restored there as "they fall ... over the next three octaves
        and then ...". The check is unchanged; only the anchor now tolerates a line break
        between its two words, since that sentence is being rewrapped."""
        text = (REPO / doc).read_text(encoding="utf-8")
        m = re.search(r"counts\s+collapse", text)
        assert m, "the collapse sentence has gone from %s" % doc
        i = m.start()
        passage = text[i:i + 400]
        for macro in ("tracedModeFallA", "tracedModeFallB", "tracedModeFallC",
                      "tracedModeFallOctaves", "tracedLastBucketFall"):
            assert chr(92) + macro in passage, "%s is missing from %s" % (macro, doc)

    @pytest.mark.parametrize("doc", ["paper.tex", "supplement.tex", "postmortem.tex"])
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
        """v5 (28 Sep): the restored sentence need not say "rather than trail" or "falls by
        one factor", so it is bounded by what the restored clause does carry: from "counts
        collapse" to "octaves and then", plus the last factor that follows. Same sentence,
        same four ratios, same octave count."""
        flat = " ".join(rendered_paper.split())
        i = flat.index("counts collapse")
        # Bounded by the sentence, not by a character count: round 80 moved a column break
        # into it, and the extractor reads Figure 3 -- tick labels and a caption that says
        # "power law" too -- between its two halves.
        j = flat.index("octaves and then", i)
        assert j - i < 900, "the collapse sentence no longer reaches its own end nearby"
        passage = flat[i:j + len("octaves and then") + 12]
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
        assert av.main(["--check", "paper.tex", "supplement.tex", "postmortem.tex"]) == 0

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
        """v5 (28 Sep): the paper's new exposure figure took `fig:exposure`, the label the
        supplement's own exposure curve has always carried, and under the P- prefix the two
        cannot collide. A label the supplement defines itself therefore resolves to its own
        float and is not a leak; every other unprefixed reference to a paper label still fails."""
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
        own = set(re.findall(RE_BS + r"label\{([^}]*)\}",
                             re.sub(r"(?m)(?<!\\)%.*$", "", supplement)))
        leaked = sorted((theirs & referenced) - own)
        assert not leaked, \
            "these point into the paper without the prefix and resolve to nothing: %s" % leaked
        assert theirs & {r[2:] for r in referenced if r.startswith("P-")}, \
            "no prefixed pointer resolves into the paper at all"

    def test_w4_the_build_is_free_of_multiply_defined_labels(self):
        log = REPO / "postmortem.log"
        if not log.is_file():
            pytest.skip("postmortem.log not present")
        assert "multiply defined" not in log.read_text(encoding="utf-8", errors="replace")

    def test_w5_the_supplement_does_not_date_itself_by_this_projects_rounds(
            self, rendered_supplement):
        """Its first page says nothing in it was asked for by a referee; a reader who has
        just been told that cannot resolve "round 59"."""
        assert not re.search(r"\b[Rr]ound \d+", rendered_supplement)

    def test_w6_the_colocation_rule_has_an_instance_that_is_not_our_own_audit(
            self, paper, supplement):
        """v5 (28 Sep): the twelve bold rules became Table IV's six checks (editor, sections 9
        and 11), the co-location rule is not one of them, and the mq-bench paragraph went to
        the supplement (section 5). The instance is pinned where it now lives, S33.3, which
        reads mq-bench's reason for co-locating, and the rule may not return without it."""
        i = paper.find("Do not assume co-location makes the measurement safer")
        if i >= 0:
            rule = paper[i:i + 620]
            assert "mq-bench" in rule and "S33.3" in rule
        j = supplement.index(chr(92) + "subsection{S33.3.")
        section = " ".join(supplement[j:supplement.index(chr(92) + "subsection{", j + 10)].split())
        assert "mq-bench" in section
        assert "co-located" in section and "clock synchronization" in section, (
            "S33.3 no longer reads mq-bench's stated reason for co-location, which is the "
            "instance the co-location rule had")

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

        v5 (28 Sep): the sentence did not survive the move from bold rules to Table IV, and
        nothing in the editor's review asked for it to go; it returns in the paragraph after
        the table, so the pin stands and is only made indifferent to case and line breaks.
        The co-location clause is a different matter: that rule is not among Table IV's
        checks, and its instance is pinned in S33.3 by the test above, so the second half now
        applies only if the rule comes back.
        """
        flat = " ".join(paper.split())
        assert re.search("busy-polling a dedicated core should buy the same", flat, re.I), (
            "J. Kunkel's busy-poll sentence has gone from the paper again; it was asked for in "
            "correspondence, beside the real-time-priority mitigation")
        i = paper.find("Do not assume co-location makes the measurement safer")
        if i >= 0:
            assert "mq-bench" in paper[i:i + 620], "and the clause it was offered for stays too"
