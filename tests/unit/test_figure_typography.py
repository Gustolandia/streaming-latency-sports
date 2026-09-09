"""One submission printed the multiplication sign three ways and the microsecond two.

Round 59's triple image review read the seventeen included figures *against each other*, which
is the reading that finds this class: the E-A5 collapse factor is the same number in Fig. S7
and Fig. S8, and it was set as "39 x" in one and "39x" in the other. Across the seventeen the
sign appeared as a literal U+00D7, as mathtext `$\\times$` --- which matplotlib sets as a
binary operator and pads on both sides --- and as the ASCII letter x, three times in Fig. S10's
map. The microsecond was `µs` on Fig. 3's axis and `us` on Fig. S12's.

The gate reads the **built figure PDFs** rather than the scripts, for the reason
`docs/writing_standards.md` A1b gives about its own subject: that is the only formulation a
sixth figure script cannot escape. What it can check from a text layer is what survives one:
the letter x is a character and extracts as one, and so does the micro sign. Mathtext's
padding is glyph positioning rather than a space, so it does not survive extraction --- that
half is held at the source, where the two forms are distinguishable.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
FIGURES = REPO / "docs" / "results" / "figures"

#: Every figure either document includes, read off the sources rather than listed by hand.
INCLUDED = sorted({
    m for tex in ("paper.tex", "supplement.tex")
    for m in re.findall(r"figures/([A-Za-z0-9_]+)\.pdf",
                        (REPO / tex).read_text(encoding="utf-8"))
})

#: The scripts that draw them.
DRAWERS = sorted(p.name for p in (REPO / "scripts").glob("make_*.py"))


def _text(stem):
    pdf = FIGURES / (stem + ".pdf")
    if not pdf.exists():
        pytest.skip("%s is not built" % stem)
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pymupdf is a hard dependency of the figure gates
        pytest.skip("pymupdf unavailable")
    with pymupdf.open(pdf) as doc:
        return " ".join(" ".join(page.get_text() for page in doc).split())


def test_the_review_has_something_to_read():
    """A source list that silently empties turns every check below into a pass."""
    assert len(INCLUDED) >= 15, \
        "only %d figures included; the extractor is broken" % len(INCLUDED)


class TestTheMultiplicationSignIsTheMultiplicationSign:
    """U+00D7, in every figure, in both halves of the pipeline."""

    @pytest.mark.parametrize("stem", INCLUDED)
    def test_no_figure_uses_the_letter_x_as_a_multiplier(self, stem):
        bad = re.findall(r"[0-9]\s?x\b", _text(stem))
        assert not bad, (
            "%s prints %s; the multiplication sign is ×, which is what the other "
            "figures print. A letter x beside a number reads as a variable." % (stem, bad))

    @pytest.mark.parametrize("script", DRAWERS)
    def test_no_script_sets_the_sign_in_math_mode(self, script):
        r"""`$\times$` is a binary operator, and matplotlib pads binary operators.

        With nothing on its right the padding still lands, so `$39\times$` prints "39 x"
        against a literal's "39x". The space is glyph positioning rather than a space
        character, so it does not survive text extraction --- this half has to be held here.
        """
        src = (REPO / "scripts" / script).read_text(encoding="utf-8")
        src = re.sub(r"(?m)^\s*#.*$", "", src)
        bad = re.findall(r"[^\s$]{0,6}\$?\\\\?times", src)
        assert not bad, (
            r"%s sets the multiplication sign in math mode (%s). Mathtext pads \times as a "
            "binary operator, so it prints wider than the literal × the other figures "
            "use. Use the character." % (script, bad[:4]))


class TestTheMicrosecondIsSpelledOneWay:
    """`µs`, as Fig. 3's axis has it."""

    @pytest.mark.parametrize("stem", INCLUDED)
    def test_no_figure_writes_the_microsecond_as_us(self, stem):
        bad = re.findall(r"\(\s*us\s*[,)]|\bus\b(?=\s*[,)])", _text(stem))
        assert not bad, (
            "%s writes the microsecond as 'us'; Fig. 3's axis writes 'µs'" % stem)


class TestThePanelTitlesAgreeOnACapital:
    """Eighteen titles, ten capitalised and eight not, and nothing had decided which."""

    #: A title may open on a count --- a digit, or the `{...}` of an f-string that will hold
    #: one --- or on an ellipsis, which is how panel (b) continues the sentence panel (a)
    #: starts. Everything else opens on a capital.
    OPENER = re.compile(r"^\(([a-z])\)\s*(\.\.\.|…|[0-9{]|[A-Z$])")

    @pytest.mark.parametrize("script", DRAWERS)
    def test_every_panel_title_opens_on_a_capital(self, script):
        src = (REPO / "scripts" / script).read_text(encoding="utf-8")
        titles = re.findall(r"set_title\(\s*[fr]?\"(\([a-z]\)[^\"]*)\"", src)
        bad = [t for t in titles if not self.OPENER.match(t)]
        assert not bad, (
            "%s has panel titles opening lower-case: %s. Ten of the submission's eighteen "
            "opened on a capital and nothing had decided the rest; the majority is the rule."
            % (script, bad))

    def test_the_rule_can_fail(self):
        """Pin the shape the round-59 review found, so the regex cannot be loosened blind."""
        assert not self.OPENER.match("(a) as measured, one clock, nanosecond timestamps")
        assert self.OPENER.match("(a) As measured, one clock, nanosecond timestamps")
        assert self.OPENER.match("(a) 104 of 1,382 runs with no negative span")
        assert self.OPENER.match("(a) {clean:,} of {len(by_run):,} runs with no negative span")
        assert self.OPENER.match("(b) ...and burstier than their mean suggests")


class TestTheArmsKeepOneColourAcrossFigures:
    """Blue was the real-time arm in Fig. S7 and the ordinary arm in Fig. S8."""

    def test_the_ladder_and_the_forest_agree(self):
        src = (REPO / "scripts" / "make_result_figures.py").read_text(encoding="utf-8")
        forest = re.search(
            r"colour = (\w+) if arm in \(\"real-time\", \"concentrated\"\) else (\w+)", src)
        assert forest, "the forest's colour rule has moved; re-derive this check from it"
        accent, kept = forest.groups()
        ladder = re.search(r"\"o\", color=(\w+), mec=\"none\", ms=4\.0, ls=\"none\", "
                           r"label=\"ordinary\"", src)
        assert ladder, "the ladder's legend has moved"
        assert ladder.group(1) == kept, (
            "the ladder paints `ordinary` %s while the forest paints it %s; a reader carrying "
            "one key to the other figure reads every arm backwards"
            % (ladder.group(1), kept))
        rt = re.search(r"\"s\", color=(\w+), mec=\"none\", ms=4\.0, ls=\"none\", "
                       r"label=\"real-time\"", src)
        assert rt and rt.group(1) == accent, (
            "the ladder paints `real-time` %s while the forest paints it %s"
            % (rt and rt.group(1), accent))


class TestBarsDoNotStandOnALogAxis:
    """A bar states its value as a length from zero, and a log axis has no zero."""

    def test_the_e1_decomposition_is_not_bars(self):
        src = (REPO / "scripts" / "make_e1_figure.py").read_text(encoding="utf-8")
        body = src[src.index("def plot_decomposition"):]
        body = body[:body.index("\ndef ", 1)]
        assert "set_yscale(\"log\")" in body, \
            "the panel is no longer log-scaled; this check needs rewriting rather than deleting"
        assert "ax.bar(" not in body, (
            "Fig. S2(b) draws bars on a log axis again. Their lengths would be "
            "log(v) - log(floor), so moving the y-limit would change every bar while changing "
            "no number. The panel claims a ratio; a log axis measures ratios as distances.")


def test_pymupdf_is_available():
    """The PDF half of this gate is the half a new script cannot escape; skipping it is a hole."""
    pytest.importorskip("pymupdf")
