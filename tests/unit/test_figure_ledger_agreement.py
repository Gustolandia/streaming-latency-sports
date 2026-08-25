r"""Does a number a figure draws agree with the macro the prose reads?

Figure 7 annotates "over a 77x span in transport". Four sentences in the manuscript and
eleven in the supplement said the same thing, some as `77` and one as `76.9`. Seventeen
copies of one quantity, in three different places -- a figure that recomputed
`round(xs[-1] / xs[0])`, a manuscript that typed it, and a CSV that neither read through the
ledger.

Every copy was correct. That is why it lasted thirty-three rounds: nothing was wrong, so
nothing failed, and the ledger sweep could not help because `77` is an integer and the sweep
skips integers by design.

The interesting part is that the *other* number in that same annotation had already been
fixed. `\tailSlope` was emitted in an earlier round with a comment saying the ledger emits it
"so they cannot drift apart again". Its neighbour on the same line was left recomputing. A
repair reaches the number you were looking at.

This file checks the general property behind that: **a quantity a figure prints and a macro
the prose reads must come out the same.** It is a small set --- figures mostly draw data, not
summary statistics, and only a handful annotate a number the text also quotes --- so the list
below is explicit rather than discovered. An explicit list that is short and correct beats a
scan that guesses which annotations are claims.
"""
import os
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
sys.path.insert(0, str(REPO / "scripts"))


def _macros():
    if not GENERATED.exists():                          # pragma: no cover - built by CI
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$",
                           GENERATED.read_text(encoding="utf-8"), re.M))


@pytest.fixture(scope="module")
def span():
    os.chdir(REPO)
    import stat_intervals
    return stat_intervals.payload_span()


class TestTheFigureAndTheLedgerAgree:
    """Figure 7's annotation against the macros Sections I, V-C, V-D and VI-D read."""

    def test_the_transport_span_matches(self, span):
        m = _macros()
        assert "%.0f" % round(span["transport_factor"]) == m["payloadTransportFactorRound"], \
            "Figure 7 draws a different span from the one the prose quotes"
        assert "%.1f" % span["transport_factor"] == m["payloadTransportFactor"]

    def test_the_rounded_macro_is_the_rounding_of_the_precise_one(self):
        """Two macros for one quantity is a decision; they must still be one quantity."""
        m = _macros()
        assert (round(float(m["payloadTransportFactor"]))
                == float(m["payloadTransportFactorRound"])), \
            "the rounded transport factor is not the rounding of the precise one"

    def test_the_rate_fall_and_spread_match(self, span):
        m = _macros()
        assert "%.1f" % span["rate_fall"] == m["payloadRateFall"]
        assert "%.3f" % span["rho_spread"] == m["payloadRhoSpread"]

    def test_the_slope_still_comes_from_the_fit(self):
        """The neighbour that was fixed first. If it regresses, this catches it too."""
        os.chdir(REPO)
        import stat_intervals
        slope = stat_intervals.payload_fit()[0]
        assert "%.2f" % slope == _macros()["tailSlope"]


class TestNoDocumentTypesTheseByHand:
    r"""The seventeen copies, and the rule that stops the eighteenth.

    `test_ledger_coverage` cannot do this one: it matches a macro's *value* against literals
    and skips bare integers, so `$77\times$` was invisible to it while `$76.9\times$` was not
    even emitted to be compared against.
    """

    #: value as it was typed -> the macro that now carries it. The last three are S25's
    #: two-campaign comparison caption, which had the primary run's numbers replaced and the
    #: replication's left typed until the half-and-half sentence made the omission obvious.
    RETIRED = {r"76.9": "payloadTransportFactor", r"77": "payloadTransportFactorRound",
               r"4.1": "payloadRateFall", r"76.8": "payloadReplTransportFactor",
               r"4.09": "payloadRateFallExact", r"4.26": "payloadReplRateFall"}

    @pytest.mark.parametrize("doc", ("paper.tex", "supplement.tex"))
    def test_the_payload_span_is_never_typed(self, doc):
        text = (REPO / doc).read_text(encoding="utf-8")
        bad = []
        for value, macro in self.RETIRED.items():
            for m in re.finditer(r"\$" + re.escape(value) + r"\\times\$", text):
                line = text.count("\n", 0, m.start()) + 1
                bad.append("%s:%d  $%s\\times$ should be $\\%s\\times$"
                           % (doc, line, value, macro))
        assert not bad, (
            "payload-sweep quantities typed by hand again -- there were seventeen of these "
            "and every one was correct, which is why nothing ever failed:\n  "
            + "\n  ".join(bad))

    def test_the_macros_are_actually_used(self):
        """A macro nobody reads is not a fix, it is a second place for the number to live."""
        both = "".join((REPO / d).read_text(encoding="utf-8")
                       for d in ("paper.tex", "supplement.tex"))
        for macro in set(self.RETIRED.values()) | {"payloadRhoSpread"}:
            assert re.search(r"\\" + macro + r"\b", both), "%s is emitted but unused" % macro

    def test_the_replication_agrees_with_its_own_campaign(self):
        """S25's caption claims two campaigns agree; both sides must come from their own."""
        os.chdir(REPO)
        import stat_intervals
        repl = stat_intervals.payload_span("ea10b")
        m = _macros()
        assert "%.1f" % repl["transport_factor"] == m["payloadReplTransportFactor"]
        assert "%.2f" % repl["rate_fall"] == m["payloadReplRateFall"]
        assert m["payloadReplTransportFactor"] != m["payloadTransportFactor"], \
            "the two campaigns are distinct runs; identical macros would mean one was reused"


class TestTheCheckCanFail:

    def test_a_typed_copy_is_caught(self):
        text = r"transport spans $76.9\times$ and the rate falls"
        assert re.search(r"\$76\.9\\times\$", text)

    def test_the_macro_form_is_not_caught(self):
        text = r"transport spans $\payloadTransportFactor\times$ and the rate falls"
        assert not re.search(r"\$76\.9\\times\$", text)

    def test_a_mismatched_rounding_would_fail(self):
        """If the two precisions ever stop being one quantity, the pin above fires."""
        assert round(76.9) == 77
        assert round(76.4) != 77
