r"""Defects that exist only after the artists are placed, or only after LaTeX numbers a label.

Three classes, all found in round 44 by reading the built PDF rather than the source, and all
invisible to every gate that reads `.tex`.

**A cross-reference to a `\paragraph`.** IEEEtran numbers a paragraph inside a subsection as
"0a", so `\ref{sec:metrics}` renders as "Section III-A0a". There is no Section III-A0a. Two
were in the build: one pre-existing, one introduced by the round-43 edit that named `t_out`,
which is to say the round that fixed a dangling pointer created one.

**A sentence opening on a lowercase word.** A macro expanding to "five" lands at the head of a
sentence and the source still looks right. The project already generates a capitalised twin
for every such macro -- `\harnessSilentWordCap` is "Five" -- and the one place that needed it
was not using it.

**A generated macro no document reads.** Round 29's reason for generating them at all: "A
generated file carrying macros nobody reads is a place for a stale number to survive a
revision." Sixty-six of two hundred and seventy-five were unread when this was written. Most
are deliberate -- the `Word`/`WordCap` pairs exist so a number can open a sentence, and
keeping both halves is right even when one is idle. So this is an inventory with a ceiling
rather than a prohibition: the count may not grow without someone looking.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PDFS = ("paper.pdf", "supplement.pdf")

#: Lowercase words that may legitimately open a fragment after a full stop.
CONTINUATIONS = ("e.g", "i.e", "vs", "cf", "pp", "vol")

#: Tokens whose trailing full stop is an abbreviation rather than a sentence end.
ABBREVIATIONS = frozenset((
    "al", "eg", "ie", "cf", "vs", "fig", "figs", "sec", "eq", "eqs", "no", "vol",
    "pp", "ref", "refs", "approx", "resp", "cs", "st", "ca", "dr", "prof", "inc",
))

#: What the unused-macro inventory stands at. A ceiling, not a target: it may fall freely and
#: may not rise without the reason being written down. It was 66 when round 44 first counted
#: it, and 64 after that round quoted the exposure lag and its percentiles; the four macros
#: round 44 added are all read.
UNUSED_MACRO_CEILING = 64


def rendered(name):
    path = REPO / name
    if not path.is_file():
        pytest.skip("%s not built" % name)
    out = subprocess.run(["pdftotext", "-q", "-nopgbrk", str(path), "-"],
                         capture_output=True, text=True, errors="replace")
    if out.returncode != 0:
        pytest.skip("pdftotext unavailable")
    return re.sub(r"\s+", " ", out.stdout)


class TestNoPointerLandsOnAParagraph:
    r"""`\ref` to a `\paragraph` renders as a section number that does not exist."""

    @pytest.mark.parametrize("name", PDFS)
    def test_no_section_pointer_carries_a_paragraph_suffix(self, name):
        bad = sorted(set(re.findall(r"Section[s]?~?\s+([IVX]+-[A-Z]\d[a-z])", rendered(name))))
        assert not bad, (
            "%s points at %s, which IEEEtran prints for a label sitting on a \\paragraph. "
            "A reader has no such section to find; point at the enclosing subsection."
            % (name, ", ".join(bad)))

    def test_the_check_would_fire_on_the_defect_it_was_written_for(self):
        """Round 44's two, reconstructed, so the rule is known to have teeth."""
        pat = re.compile(r"Section[s]?~?\s+([IVX]+-[A-Z]\d[a-z])")
        assert pat.findall("A fifth is consumer-internal (Section III-A0a).") == ["III-A0a"]
        assert pat.findall("Over the campaign of Section IV-B0a that silence") == ["IV-B0a"]
        assert not pat.findall("the audit of Section IV-D reads ten tools at source")


class TestNoSentenceOpensOnALowercaseWord:
    """A macro at the head of a sentence, in the one place the source cannot show it."""

    @staticmethod
    def offenders(text):
        out = []
        for m in re.finditer(r"(\w+)\.\s+([a-z]{2,})\s+(\w+\s+\w+\s+\w+)", text):
            before, word = m.group(1).lower(), m.group(2)
            # A stop that is not a sentence end: "et al.", "e.g.", "Fig. 3", "No. 4".
            if before in ABBREVIATIONS or word.lower().startswith(CONTINUATIONS):
                continue
            out.append("%s %s" % (word, m.group(3)))
        return out

    @pytest.mark.parametrize("name,expected", [("paper.pdf", 0), ("supplement.pdf", 0)])
    def test_the_known_offenders_are_gone(self, name, expected):
        """Not a general grammar check: a two-column reflow puts a continued sentence at the
        head of a line and this sweep cannot tell that from a real one. So it pins the three
        found in round 44 by their own text, and leaves the sweep to `test_the_sweep_still_sees`.
        """
        text = rendered(name)
        known = ("benchmark. five of the ten",
                 "not documented. the main text recovers",
                 "load model. the main text shows")
        found = [k for k in known if k in text]
        assert not found, "round 44's sentence-case defects are back: %s" % found

    def test_the_sweep_still_sees_the_shape(self):
        assert self.offenders("classified the benchmark. five of the ten dispose of it")
        assert not self.offenders("the rate fell 4.1x. The direction Equation 3 predicts here")
        assert not self.offenders("cited by Villain et al. and by Paxson in the same year")


class TestTheGeneratedLedgerIsRead:
    """Macros emitted and quoted nowhere."""

    @staticmethod
    def unused():
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex")
        if not gen.exists():                            # pragma: no cover - built by CI
            pytest.skip("paper_numbers.tex absent; run emit_paper_numbers.py")
        names = re.findall(r"\\newcommand\{\\(\w+)\}", gen.read_text(encoding="utf-8"))
        docs = ((REPO / "paper.tex").read_text(encoding="utf-8")
                + (REPO / "supplement.tex").read_text(encoding="utf-8"))
        return sorted(n for n in names
                      if not re.search(re.escape("\\" + n) + r"(?![A-Za-z])", docs))

    def test_the_unread_inventory_does_not_grow(self):
        unused = self.unused()
        assert len(unused) <= UNUSED_MACRO_CEILING, (
            "%d generated macros are read by neither document, up from %d. Either quote the "
            "new ones or stop emitting them: %s"
            % (len(unused), UNUSED_MACRO_CEILING, ", ".join(unused[:8])))

    def test_the_lag_the_exposure_curve_rests_on_is_printed(self):
        """M1's smallest symptom. The curve in Section VI-B is one number wearing nine rows,
        and that number was emitted and shown to nobody."""
        assert r"\ackLagMedianUs" not in self.unused(), \
            "the median acknowledgment lag must appear where the exposure curve is introduced"
