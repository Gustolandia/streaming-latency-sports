r"""Round 70's referee items, pinned so a later pass cannot quietly undo them.

R1 is the sharpest item in seven rounds: the paper asserted $A = t_ack - t_send$ non-negative
in Section II, built the whole of Section V-D on it -- median, tenth percentile, ninetieth --
and never counted its sign, while Table I existed to show that causal chains do not invert and
counted three *other* chains. The paper's own rule is that a chain you believe in must still be
counted: "we caught our own instance only on counting the send-referenced span separately".

It is counted now, and it is clean: zero negatives over 738,730 events, with the smallest run
minimum 112 us clear of zero. The premise is a measurement rather than an assumption, and the
biconditional it was attached to never needed it -- S = D - A is an identity, so S < 0 iff
A > D whatever the signs are.

R2 was S9 calling a measured maximum a bound and a scale a floor, where the main text's own
macros show the manipulated configurations running on both sides of it.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1TheAcknowledgmentLagIsCounted:

    def test_the_span_is_in_the_recounter(self):
        import recount_spans
        spans = dict((n, (a, b)) for n, a, b in recount_spans.SPANS)
        assert spans["acklag"] == ("t_broker_ack_ns", "t_prod_send_ns"), (
            "A is the acknowledgment lag: the producer's send call to the producer learning "
            "the broker accepted it, both stamps on one clock")

    def test_the_ledger_carries_the_count_and_its_margin(self):
        import recount_spans
        rows = recount_spans.read_csv(str(REPO / "docs" / "results" / "span_recount.csv"))
        agg = recount_spans.totals(rows)
        assert agg["neg_acklag"] == 0, (
            "if this ever moves off zero it is a finding, not a failure -- but the sentence "
            "in Section II and the row in Table I both have to move with it")
        assert agg["events"] == 738730, "counted over the whole corpus, not a subset"
        assert agg["shallowest_acklag_us"] > 0, (
            "the margin is what turns 'never inverted' from a fact about a threshold into a "
            "fact about distance from one")

    def test_every_chain_is_counted_per_broker_too(self):
        import recount_spans
        rows = recount_spans.read_csv(str(REPO / "docs" / "results" / "span_recount.csv"))
        split = recount_spans.by_backend(rows)
        assert set(split) == {"kafka", "redis"}
        for name, agg in split.items():
            assert agg["neg_acklag"] == 0, name

    def test_the_macros_are_emitted(self):
        import emit_paper_numbers as epn
        m = dict(epn.span_macros())
        assert m["spanNegAckLag"] == "0"
        assert m["spanKafkaNegAckLag"] == "0" and m["spanRedisNegAckLag"] == "0"
        assert int(m["spanAckLagFloorUs"]) > 0

    def test_table_one_carries_the_fourth_chain(self, paper):
        i = paper.index("label{tab:spans}")
        table = paper[i:paper.index("end{table}", i)]
        assert "spanNegAckLag" in table, "the row exists"
        assert table.count("publish (chain)") == 3, (
            "three spans now take the publish timestamp as their origin, and all three are rows")
        assert "---" not in table, "round 68's measured zeros stay measured zeros"

    def test_the_caption_gives_the_margin_rather_than_only_the_zero(self, paper):
        i = paper.index("Negatives by span and broker")
        caption = " ".join(paper[i:paper.index("label{tab:spans}", i)].split())
        assert "spanAckLagFloorUs" in caption

    def test_the_biconditional_no_longer_rests_on_a_premise_it_never_used(self, paper):
        """v5 (28 Sep): Section II-A says "Since Equation 1 holds per event, whatever the
        signs"; v4 said "is an identity holding per event, and whatever the signs". The anchor
        follows the wording, flattened because the source wraps it."""
        assert "with $D$ and $A$ both non-negative" not in paper, (
            "S = D - A is an identity, so S < 0 iff A > D holds whatever the signs are")
        flat = " ".join(paper.split())
        i = flat.index("holds per event")
        assert "whatever the signs" in flat[i:i + 120]

    def test_the_reading_names_where_its_premise_is_measured(self, paper):
        """Non-negativity licenses the reading, not the algebra -- and it is measured.

        v5 (28 Sep): Section II-A keeps the identity in two lines (editor, section 5), and v4's
        "Reading it as a lag outrunning a delivery does need both to be non-negative, and both
        are measured rather than assumed" went with the rest, so the premise is now stated only
        where it is measured: the Section III-A paragraph that introduces Table I. The pin
        moved there, and Section II may not call a span non-negative again without saying there
        that it is measured rather than assumed.
        """
        prose = " ".join(re.sub(r"(?m)(?<!\\)%.*$", " ", paper).split())
        model = prose[prose.index(r"\label{sec:sysmodel}"):prose.index(r"\label{sec:mechanism}")]
        if "non-negative" in model:
            assert "measured rather than assumed" in model, (
                "Section II calls a span non-negative again; if that is the reading's premise, "
                "say it is measured rather than assumed, and where")
        flat = " ".join(paper.split())
        i = flat.index(r"Table~\ref{tab:spans} separates the spans")
        passage = flat[i:i + 700]
        assert "The publish-referenced span, the publish latency $A$" in passage
        assert "negative on no event at all" in passage, \
            "the premise is no longer stated as a measurement beside the table that measures it"

    def test_the_prose_enumerates_every_chain(self, paper):
        """Flattened: the clause wraps in the source, and a line break is not a defect.

        v5 (28 Sep): the sentence no longer follows "Of the runs," and lost its "--- every
        causal chain the corpus contains ---" in the cut of em-dash parentheticals (editor,
        section 7.6). It still names A, and the completeness claim is pinned in Table I's
        caption, which says only the acknowledgment-origin span inverts.
        """
        flat = " ".join(paper.split())
        i = flat.index("The publish-referenced span, the publish latency $A$")
        passage = flat[i:i + 320]
        assert "publish latency $A$" in passage
        assert "negative on no event at all" in passage
        j = paper.index("Negatives by span and broker")
        caption = " ".join(paper[j:paper.index("label{tab:spans}", j)].split())
        assert "Only the transport proxy $S$ inverts" in caption, \
            "the chain inventory no longer says it is complete"
        assert "the causal chains are clean" in caption

    def test_the_rendered_table_shows_four_clean_chains(self):
        flat = " ".join(_rendered("paper").split())
        assert flat.count("publish (chain)0 0 0") == 3
        assert "event time0 0 0" in flat


class TestR2TheFloorIsAScaleNotALimit:

    def test_the_supplement_stops_calling_a_maximum_a_bound(self, supplement):
        assert "bounded above by" not in supplement
        assert "reaches but" not in supplement, (
            "the main text says the manipulated configurations run on both sides of the floor")

    def test_the_sentence_prints_the_spread_that_qualifies_the_floor(self, supplement):
        i = supplement.index("The negative-span rate has no such exit")
        passage = " ".join(supplement[i:i + 620].split())
        for macro in ("invCeiling", "invFloor", "rtResidualMin", "rtResidualMax", "rtPairs"):
            assert chr(92) + macro in passage, "%s missing" % macro
        assert "not a limit" in passage

    def test_the_main_text_and_the_supplement_now_agree(self, paper, supplement):
        """Both say the floor is where the rate settles, not a bound it respects."""
        # 1 Oct 2026: "so C_0 is where the rate settles and not a bound it respects" became
        # "they run from ... to ..., on both sides of C_0", the same claim without the
        # antithesis (editor 7.1).
        assert "on both sides of $C_0$" in paper
        assert "is a scale and" in supplement

    def test_the_ceiling_gets_the_same_treatment_as_the_floor(self, paper, supplement):
        """The other half of this item, which round 70 won and round 72 had to finish.

        `invCeiling` is max(vals) over the conditions at rho >= 0.95 -- the highest rate
        measured near saturation, with a consistency check across phases. S9 was repaired to
        say so, and says "Neither number is a bound, and neither needs to be". Section V-B
        kept "The rate has a ceiling below one: fully saturated it reaches 0.37", which is
        the same maximum-as-bound the item was about, in the other document, unguarded.

        A pair of symmetric claims wants a pair of symmetric gates, or the unguarded half is
        where the wording comes back.

        v5 (28 Sep): the ceiling left the paper with v4's Section V-B and returns to Section
        III-B as "a maximum over those conditions and not a bound"; that phrase is accepted
        beside "highest we measure" as saying the same thing, and "not a bound" is still
        required.
        """
        i = paper.index(chr(92) + "invCeiling")
        clause = " ".join(paper[max(0, i - 320):i + 200].split())
        assert "ceiling below one" not in clause, (
            "a measured maximum near saturation is not a ceiling the rate reaches")
        assert ("highest we measure" in clause or "a maximum over those conditions" in clause
                or "the largest observed" in clause), \
            "the clause no longer says the number is a measured maximum"
        assert "not a bound" in clause or "rather than a bound" in clause
        assert "Neither number is a bound" in supplement, (
            "S9's repair from round 70 is what the main text now agrees with")

    def test_the_ledger_shows_why_it_is_not_a_bound(self):
        import emit_paper_numbers as epn
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        vals = dict(re.findall(RE_BS + r"newcommand\{" + RE_BS + r"(\w+)\}\{([^}]*)\}", gen))
        lo, hi, floor = (float(vals["rtResidualMin"]), float(vals["rtResidualMax"]),
                         float(vals["invFloor"]))
        assert lo < floor < hi, (
            "the manipulated configurations straddle the floor, which is the whole reason "
            "'reaches but does not cross' was wrong")


class TestRecommendedItems:

    def test_w1_the_abstract_carries_the_bodys_denominator(self, paper):
        """v6 (2 Oct 2026): the abstract quotes no population at all now, so the hedge travels
        with the first sentence that does, in the introduction."""
        i = paper.index("label{sec:intro}")
        intro = " ".join(paper[i:paper.index("section{How a Benchmark", i)].split())
        assert "whose summary we captured" in intro, (
            "the body and Fig. 4's caption both hedge this population; the introduction must "
            "too")

    def test_w1_it_did_not_cost_the_word_budget(self):
        """Two words were bought back so the hedge does not seat the abstract on the cap."""
        import shutil
        import subprocess
        import tempfile
        pdf = REPO / "paper.pdf"
        if not pdf.is_file() or not shutil.which("pdftotext"):
            pytest.skip("paper.pdf or pdftotext absent")
        out = Path(tempfile.mkstemp(suffix=".txt")[1])
        subprocess.run(["pdftotext", "-q", "-nopgbrk", "-enc", "UTF-8", "-f", "1", "-l", "1",
                        str(pdf), str(out)], check=True)
        page = out.read_text(encoding="utf-8", errors="replace")
        i, j = page.find("Abstract"), page.find("Index Terms")
        body = re.sub(r"^Abstract\s*[-–—]*", "", page[i:j]).strip()
        n = len([w for w in body.split() if re.search(r"[A-Za-z0-9]", w)])
        assert n <= 198, (
            "%d words: the hedge is worth having and sitting on the 200-word cap is not, so "
            "two words were cut to pay for it" % n)

    def test_w2_the_figure_named_the_operator_before_the_table_did(self):
        """Recorded, not changed. Fig. S-deletion panel (b) has labelled the guard `> 0`
        since long before round 69 propagated that convention to Table S14, so the two agree
        and the figure is the precedent rather than an inconsistency with it."""
        src = (REPO / "scripts" / "make_result_figures.py").read_text(encoding="utf-8")
        assert "> 0" in src, "the deletion figure names the guard's comparison"

    def test_w3_the_span_inventory_says_it_is_complete(self, paper):
        """W3 asked for Section VIII-D's grain sentence to shrink now that the inventory is
        whole. It is answered in Section V-A instead, where the claim belongs: the sentence
        that enumerates the chains now says it enumerates all of them. Section VIII-D's
        sentence is about the ten-tool source audit, which round 70 did not touch.

        v5 (28 Sep): both halves moved in the line edit (editor, sections 7.1 and 7.6). The
        inventory's completeness is Table I's caption, "Only the acknowledgment-origin span
        inverts", since the prose lost its "every causal chain the corpus contains"; and round
        69's grain is Table III's caption, beside Section VIII's "were read at source, not
        deployed" (see round 69's W2 test)."""
        flat = " ".join(paper.split())
        j = paper.index("Negatives by span and broker")
        caption = " ".join(paper[j:paper.index("label{tab:spans}", j)].split())
        assert "Only the transport proxy $S$ inverts" in caption, \
            "the span inventory no longer says it is complete"
        assert "at source and did not run them" in flat, "the source-reading concession has gone"
        k = paper.index("label{tab:tools}")
        tools = " ".join(paper[paper.rindex("caption{", 0, k):k].split())
        assert "what happens to a value at or below zero" in tools, \
            "round 69's grain has gone from Table III's caption"
