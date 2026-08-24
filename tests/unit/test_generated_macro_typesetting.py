r"""Where a generated macro may be set, and where it may not.

Round 18's referee found this on the printed page:

    ...40 carry the expression unchanged, surveyed2026-08-24and recorded with the artifact.

`\forkCheckedOn` holds the date `2026-08-24` and was wrapped in `$...$`. In math mode LaTeX
reads the hyphens as minus signs and sets them with the spacing of a subtraction, and it
discards the word spaces on either side of the group. A date printed as an arithmetic
expression, in a paper whose subject is numbers that do not mean what they appear to mean.

The emitter cannot prevent this, because a macro does not know where it will be used. The
manuscript cannot be trusted to remember, because it was not remembered. So the rule is
checked. What math mode deforms is a letter, which comes out italic and wrongly spaced,
and a hyphen between two digits, which comes out as a minus; a macro whose value carries
either must be set in text mode, and every other value is free to be set either way.

The confidence-interval macros are the reason this is not simply "no hyphens in math mode".
They hold values like `0.234$--$0.443`, closing and reopening math around an en-dash on
purpose, and they are correct precisely because they are used inside `$...$`.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
SOURCES = ("paper.tex", "supplement.tex")

#: What math mode does to a value that is not a number. A letter is set italic with
#: inter-symbol spacing; a hyphen between two digits is set as a minus. Those are the two
#: things that go wrong, so those are the two things the rule names.
HAS_LETTER = re.compile(r"[A-Za-z]")
DIGIT_HYPHEN_DIGIT = re.compile(r"\d-\d")

#: A value that opens and closes math itself is built for math mode and is exempt.
SELF_MATHED = re.compile(r"\$")


def _macro_values(text):
    """{name: value} for every \\newcommand, counting braces so `1{,}321` survives intact."""
    out = {}
    for m in re.finditer(r"\\newcommand\{\\(\w+)\}\{", text):
        i = m.end()
        depth, start = 1, i
        while i < len(text) and depth:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        out[m.group(1)] = text[start:i - 1]
    return out


def _macros():
    if not GENERATED.exists():
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return _macro_values(GENERATED.read_text(encoding="utf-8"))


def _math_spans(text):
    """Every inline `$...$` group, so a macro use can be located inside or outside one."""
    return [m.span() for m in re.finditer(r"(?<!\\)\$(?:[^$\\]|\\.)*(?<!\\)\$", text, re.S)]


def _uses_in_math(name, text):
    """Every `$...$` group in which this macro is used."""
    spans = _math_spans(text)
    out = []
    for m in re.finditer(r"\\" + re.escape(name) + r"\b", text):
        for a, b in spans:
            if a <= m.start() < b:
                out.append(" ".join(text[a:b].split()))
                break
    return out


def _text_valued():
    """Macros whose value math mode would deform, and which do not carry their own math."""
    return {k: v for k, v in _macros().items()
            if v and not SELF_MATHED.search(v)
            and (HAS_LETTER.search(v) or DIGIT_HYPHEN_DIGIT.search(v))}


class TestTheEmittedValuesAreWhatWeThink:

    def test_there_are_text_valued_macros_to_police(self):
        """If this ever empties, the rule below is vacuously true and worth nothing."""
        assert _text_valued(), "no text-valued macros found; the check would be inert"

    def test_the_survey_date_is_one_of_them(self):
        """The macro that caused the defect, named, so a rename cannot silently drop it."""
        assert "forkCheckedOn" in _text_valued()

    def test_a_confidence_interval_carries_its_own_math_and_is_exempt(self):
        """These are correct in math mode, which is why the rule is about values not hyphens."""
        macros = _macros()
        ci = [k for k in macros if k.endswith("CI")]
        assert ci, "expected the emitted confidence intervals"
        for k in ci:
            assert SELF_MATHED.search(macros[k]), k
            assert k not in _text_valued()


class TestNoTextValuedMacroIsSetInMathMode:

    @pytest.mark.parametrize("source", SOURCES)
    def test_the_manuscript_sets_them_in_text_mode(self, source):
        path = REPO / source
        if not path.exists():
            pytest.skip("%s absent" % source)
        text = path.read_text(encoding="utf-8")
        bad = []
        for name, value in sorted(_text_valued().items()):
            for group in _uses_in_math(name, text):
                bad.append("%s: \\%s holds %r and is set inside %s"
                           % (source, name, value, group[:60]))
        assert not bad, (
            "a date or a word typeset as arithmetic prints with minus signs and loses its "
            "surrounding spaces:\n  " + "\n  ".join(bad))


class TestTheRuleItself:
    """The parser has to be right or the rule above is decoration."""

    def test_a_macro_inside_math_is_found(self):
        assert _uses_in_math("forkCheckedOn", r"surveyed $\forkCheckedOn$ and") == [
            r"$\forkCheckedOn$"]

    def test_a_macro_outside_math_is_not(self):
        assert _uses_in_math("forkCheckedOn", r"surveyed \forkCheckedOn{} and") == []

    def test_a_macro_beside_a_math_group_is_not_caught_by_it(self):
        """The span search must locate the use, not merely notice that math exists."""
        assert _uses_in_math("forkCheckedOn", r"$x$ then \forkCheckedOn{} then $y$") == []

    def test_an_escaped_dollar_does_not_open_math(self):
        """A literal `\\$` is a currency sign; treating it as math would mislocate every
        following group and turn the rule into noise."""
        assert _uses_in_math("forkCheckedOn", r"costs \$5 and \forkCheckedOn{} follows") == []

    def test_a_prefix_of_a_longer_macro_is_not_a_use(self):
        assert _uses_in_math("fork", r"$\forkCheckedOn$") == []

    @pytest.mark.parametrize("value,safe", [
        ("1234", True), ("1{,}321", True), ("0.36", True), ("-99.8", True),
        ("62.4\\%", True), ("<0.0004", True), ("0.78, 1.06, 1.32", True),
        ("2026-08-24", False), ("millisecond", False), ("end-to-end", False),
        ("\\texttt{kvm-clock}", False),
    ])
    def test_what_math_mode_would_deform(self, value, safe):
        deformed = bool(HAS_LETTER.search(value) or DIGIT_HYPHEN_DIGIT.search(value))
        assert deformed is not safe

    def test_the_value_parser_counts_braces(self):
        got = _macro_values(r"\newcommand{\spanEvents}{738{,}730}" "\n"
                            r"\newcommand{\forkCheckedOn}{2026-08-24}")
        assert got == {"spanEvents": "738{,}730", "forkCheckedOn": "2026-08-24"}

    def test_the_value_parser_survives_an_escaped_brace(self):
        got = _macro_values(r"\newcommand{\x}{a\}b}")
        assert got == {"x": r"a\}b"}
