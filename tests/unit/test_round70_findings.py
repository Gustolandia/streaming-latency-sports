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
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


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
        assert table.count("send (chain)") == 3, (
            "three spans now take the send timestamp as their origin, and all three are rows")
        assert "---" not in table, "round 68's measured zeros stay measured zeros"

    def test_the_caption_gives_the_margin_rather_than_only_the_zero(self, paper):
        i = paper.index("Negatives by span and broker")
        caption = " ".join(paper[i:paper.index("label{tab:spans}", i)].split())
        assert "spanAckLagFloorUs" in caption

    def test_the_biconditional_no_longer_rests_on_a_premise_it_never_used(self, paper):
        assert "with $D$ and $A$ both non-negative" not in paper, (
            "S = D - A is an identity, so S < 0 iff A > D holds whatever the signs are")
        i = paper.index("is an identity holding per event")
        assert "whatever the signs" in paper[i:i + 120]

    def test_the_reading_names_where_its_premise_is_measured(self, paper):
        """Non-negativity licenses the reading, not the algebra -- and it is measured."""
        i = paper.index("Reading it as a")
        passage = " ".join(paper[i:i + 400].split())
        assert "measured rather" in passage and "assumed" in passage
        assert "tab:spans" in passage, "and it points at the table that measures it"

    def test_the_prose_enumerates_every_chain(self, paper):
        """Flattened: the clause wraps in the source, and a line break is not a defect."""
        flat = " ".join(paper.split())
        i = flat.index("Of the runs,")
        passage = flat[i:i + 320]
        assert "acknowledgment lag $A$" in passage
        assert "every causal chain the corpus contains" in passage

    def test_the_rendered_table_shows_four_clean_chains(self):
        flat = " ".join(_rendered("paper").split())
        assert flat.count("send (chain)0 0 0") == 3
        assert "emission0 0 0" in flat


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
        assert "not a bound it respects" in paper
        assert "is a scale and" in supplement

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
        i = paper.index("begin{abstract}")
        abstract = " ".join(paper[i:paper.index("end{abstract}")].split())
        assert "whose summary we captured" in abstract, (
            "the body and Fig. 4's caption both hedge this population; the abstract was the "
            "last surface that did not")

    def test_w1_it_did_not_cost_the_word_budget(self):
        """Two words were bought back so the hedge does not seat the abstract on the cap."""
        import shutil
        import subprocess
        import tempfile
        pdf = REPO / "paper.pdf"
        if not pdf.is_file() or not shutil.which("pdftotext"):
            pytest.skip("paper.pdf or pdftotext absent")
        out = Path(tempfile.mkstemp(suffix=".txt")[1])
        subprocess.run(["pdftotext", "-q", "-nopgbrk", "-f", "1", "-l", "1",
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
        sentence is about the ten-tool source audit, which round 70 did not touch."""
        flat = " ".join(paper.split())
        assert "every causal chain the corpus contains" in flat
        i = flat.index("are readings of source rather than measured deployments")
        assert "exact to the threshold" in flat[i:i + 260], "round 69's clause is untouched"
