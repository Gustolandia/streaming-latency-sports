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


@pytest.fixture(scope="module")
def journal():
    """The journal supplement, which holds Table I and the stall spectrum since 5 Oct 2026."""
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rendered_journal():
    return _text(REPO / "supplement.pdf")


@pytest.fixture(scope="module")
def ledger():
    gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
    return dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))


def _text(pdf):
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


def _band_clause(paper):
    """The sentence that introduces the band of publish latencies, flattened.

    v5 (28 Sep): the clause no longer opens "$A$ is not a constant"; it reads "Across
    conditions $A$ runs ... between its tenth and ninetieth percentiles", and the source wraps
    inside both phrases, so they are matched whitespace-tolerantly.

    5 Oct 2026: the rebuilt paper introduces the band once, in Fig. 3's caption: "The curve
    is A/D at the median publish latency, and its band spans the tenth to ninetieth
    percentiles of A across conditions, 500--1900 us." The sentence that prints the band's
    two ends is that clause.
    """
    i = paper.index(chr(92) + "label{fig:exposure}")
    caption = " ".join(paper[paper.rindex(chr(92) + "caption{", 0, i):i].split())
    sentences = [s for s in re.split(r"(?<=\.) ", caption)
                 if chr(92) + "exposureLagLo" in s]
    assert len(sentences) == 1, "the exposure band's clause has moved; retarget this pin"
    return sentences[0]


class TestR1TheExposureBand:

    def test_the_band_is_introduced_as_percentiles_not_as_a_span(self, paper):
        """"Spans" was the second half of the defect: 500-1900 us is the middle eighty per
        cent of the acknowledgment lag, not its range.

        v5 (28 Sep): anchored on the v5 clause; the checks are unchanged.

        5 Oct 2026: the clause is Fig. 3's caption (see `_band_clause`). It names the two
        percentiles, and the verb "spans" now has the drawn band as its subject, which does
        run from the tenth percentile to the ninetieth; what stays refused is the defect
        itself, the publish latency A said to span or range over the pair, and the median's
        own numbers inside the band."""
        clause = _band_clause(paper)
        assert re.search(r"tenth\s+(?:and|to)\s+ninetieth\s+percentiles", clause)
        assert chr(92) + "exposureLagLo" in clause and chr(92) + "exposureLagHi" in clause
        assert not re.search(r"(?:\$A\$|lag|latency|latencies)\s+(?:spans?|ranges?|runs)\b",
                             clause), "a p10-p90 interval is not a span of the publish latency"
        for median in ("ackLagMedianUs", "exposureCrossover$", "exposureErrTen$"):
            assert chr(92) + median not in clause, (
                "the median's own number sits inside the band again; that is round 68's defect")

    def test_the_median_is_still_named_as_the_median(self, paper):
        """The clause before the band gives the median and must keep saying so.

        5 Oct 2026: it is Section VI-B's sentence "At our median publish latency, A = 725 us,
        the error is ... and below 0.72 ms the median publish latency exceeds the end-to-end
        latency itself", matched across its line breaks."""
        m = re.search(r"At\s+our\s+median\s+publish\s+latency", paper)
        assert m, "the sentence that names the median has gone"
        assert chr(92) + "exposureCrossover$" in paper[m.start():m.start() + 480]

    def test_the_supplements_labelling_is_unchanged(self, supplement):
        """S12 was right all along, and is the wording the main text was reconciled to."""
        assert ("the same error at the tenth and ninetieth percentiles of that publish "
                "latency") in supplement
        assert "the median publish latency and $" + chr(92) + "exposureCrossoverHi$~ms at the " \
               "ninetieth percentile" in supplement

    def test_the_rendered_numbers_are_the_percentile_ones(self, rendered_paper, ledger):
        """On the page, not in the source: the ledger can be right and the sentence wrong.

        The median's own numbers, 7% and 0.72 ms, sit in the clause *before* this one and
        must not reappear inside the band -- that reappearance was the defect.

        v5 (28 Sep): the band opens "Across conditions" and ends at its pointer to Fig. 4,
        whose caption quotes the median crossover; bounding the band by its own "(Fig." keeps
        a float that lands mid-paragraph from putting 0.72 inside it.

        5 Oct 2026: the rebuilt paper prints the band of publish latencies alone, in Fig. 3's
        caption, from "tenth to ninetieth percentiles" to its microseconds; the error and
        crossover bands derived from it went with the old Section III-D. The numbers are read
        from the ledger rather than typed, and the median's are refused inside the band.
        """
        flat = " ".join(rendered_paper.split())
        i = flat.index("tenth to ninetieth percentiles")
        band = flat[i:flat.index("s.", i) + 2]
        assert len(band) < 160, "the band clause no longer ends nearby: %r" % band[:200]
        assert ledger["exposureLagLo"] in band and ledger["exposureLagHi"] in band, \
            "the band names the two percentiles"
        assert ledger["ackLagMedianUs"] not in band, \
            "the median publish latency is inside the band; that is round 68's defect"
        assert ledger["exposureCrossover"] not in band, \
            "the median crossover is back inside the band; that is round 68's defect"


class TestR2TheConcession:

    def test_the_concession_is_a_condition_and_not_a_frequency(self, paper):
        """5 Oct 2026: the rebuilt paper drops the concession and its exception (the deletion
        is claimed for the audited reports and our own runs only, Section VIII); what stays
        refused is the frequency claim over a literature with no denominator, in the paper
        and in the journal supplement."""
        journal = (REPO / "supplement.tex").read_text(encoding="utf-8")
        for name, text in (("paper.tex", paper), ("supplement.tex", journal)):
            flat = " ".join(text.split())
            assert "Most published comparisons" not in flat, (
                "%s: a quantitative claim about a literature needs a denominator; this one had "
                "none" % name)

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

    FALLS = ("tracedModeFallA", "tracedModeFallB", "tracedModeFallC",
             "tracedModeFallOctaves", "tracedLastBucketFall")

    @pytest.mark.parametrize("doc", ["supplement.tex", "postmortem.tex"])
    def test_the_sentence_prints_the_three_falls_above_the_mode(self, doc):
        """v5 (28 Sep): Section III-C was cut to a few sentences and, in the paper, the falls
        went with it; they are restored there as "they fall ... over the next three octaves
        and then ...". The check is unchanged; only the anchor now tolerates a line break
        between its two words, since that sentence is being rewrapped.

        5 Oct 2026: the rebuilt paper says only that "above it the counts collapse" and points
        to S3.7, which prints the falls; the paper is held to that pointer below."""
        text = (REPO / doc).read_text(encoding="utf-8")
        m = re.search(r"counts\s+collapse", text)
        assert m, "the collapse sentence has gone from %s" % doc
        i = m.start()
        passage = text[i:i + 400]
        for macro in self.FALLS:
            assert chr(92) + macro in passage, "%s is missing from %s" % (macro, doc)

    def test_the_paper_sends_its_collapse_to_the_section_that_prints_the_falls(self, paper,
                                                                               journal):
        """5 Oct 2026: the paper's sentence is anchored on the mode ("The last sits in the
        bucket that contains the slice ... and above it the counts collapse"), and whatever it
        does not print itself it must send the reader to: its pointer resolves to the
        supplement section whose own collapse sentence prints all four falls."""
        flat = " ".join(paper.split())
        m = re.search(r"above it the counts collapse \(Supplement~(S\d+\.\d+)\)", flat)
        assert m, "the paper's collapse sentence lost its pointer to the falls"
        printed = [macro for macro in self.FALLS if chr(92) + macro in flat]
        if len(printed) < len(self.FALLS):
            head = re.search(r"subsection\{%s\. " % re.escape(m.group(1)), journal)
            assert head, "Supplement %s does not exist" % m.group(1)
            section = journal[head.start():journal.index(chr(92) + "subsection{", head.end())]
            c = re.search(r"counts\s+collapse", section)
            assert c, "Supplement %s does not carry the collapse" % m.group(1)
            for macro in self.FALLS:
                assert chr(92) + macro in section[c.start():c.start() + 400], (
                    "%s is missing where the paper points, Supplement %s" % (macro, m.group(1)))

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

    def test_the_rendered_sentence_carries_four_ratios(self, rendered_journal, ledger):
        """v5 (28 Sep): the restored sentence need not say "rather than trail" or "falls by
        one factor", so it is bounded by what the restored clause does carry: from "counts
        collapse" to "octaves and then", plus the last factor that follows. Same sentence,
        same four ratios, same octave count.

        5 Oct 2026: the four ratios print in the journal supplement's S3.7, where the paper
        points, so its pages are read; the ratios come from the ledger rather than being
        typed here."""
        flat = " ".join(rendered_journal.split())
        i = flat.index("counts collapse")
        # Bounded by the sentence, not by a character count: round 80 moved a column break
        # into it, and the extractor reads Figure 3 -- tick labels and a caption that says
        # "power law" too -- between its two halves.
        j = flat.index("octaves and then", i)
        assert j - i < 900, "the collapse sentence no longer reaches its own end nearby"
        passage = flat[i:j + len("octaves and then") + 12]
        for macro in ("tracedModeFallA", "tracedModeFallB", "tracedModeFallC",
                      "tracedLastBucketFall"):
            assert ledger[macro] in passage, "%s missing from the collapse sentence" % macro
        assert ledger["tracedModeFallOctaves"] + " octaves" in passage


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
        """5 Oct 2026: Table I, the values below zero by span, went to the journal supplement.
        6 Oct 2026: it is the paper's Table I again (tab:spans), and is read there."""
        i = paper.index("label{tab:spans}")
        table = paper[i:paper.index("end{table}", i)]
        assert "---" not in table, "an em-dash in an IEEE table reads 'not measured'"
        assert "dashed" not in paper[:i][-900:], \
            "the caption stopped needing to explain the glyph"
        flat = " ".join(rendered_paper.split())
        assert flat.count("publish (chain)0 0 0") == 3, \
            "all three publish-referenced chain rows print three measured zeros -- the "\
            "publish latency joined them in round 70"
        assert "event time0 0 0" in flat, "and so does E"

    def test_w4_the_supplement_imports_the_papers_labels_under_a_prefix(self, supplement):
        """v5 (28 Sep): the paper's new exposure figure took `fig:exposure`, the label the
        supplement's own exposure curve has always carried, and under the P- prefix the two
        cannot collide. A label the supplement defines itself therefore resolves to its own
        float and is not a leak; every other unprefixed reference to a paper label still fails.

        5 Oct 2026: the postmortem was written against the paper as it stood before the
        rebuild, and its pointers read that version's labels, kept with it in
        docs/archive/2026-10-05-before-cleanup/. The prefix rule is unchanged, and the archived
        label map is committed, so its absence fails instead of skipping."""
        archived = "docs/archive/2026-10-05-before-cleanup/paper"
        assert chr(92) + "externaldocument[P-]{%s}" % archived in supplement
        assert chr(92) + "externaldocument{" not in supplement
        # The supplement refers to its own floats as well, and those must NOT be prefixed.
        # What must be is every label that actually lives in the paper, so the check runs
        # against the paper's own label set rather than against a naming pattern -- a
        # pattern would either miss `eq:` or condemn the supplement's own tables.
        aux = REPO / (archived + ".aux")
        assert aux.is_file(), "the archived paper's label map is committed beside it"
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
