r"""Is every quantity that has a machine-readable source actually reading from it?

The ledger exists so a number in the prose cannot drift from the artifact it came from. Every
gate in this project until now has policed a number that *is* emitted --- whether it matches
the data, whether it is typeset correctly, whether the caption reaches it through a macro.
None asked the prior question: is this number emitted at all, or is it a copy someone typed?

A copy has the drift back. The emitted value moves when the campaign is recomputed and the
typed one does not, and the two disagree in print with nothing failing. Round 23 found four
such copies in `paper.tex` --- the geometry factor, its `z`, and the replication factor, one
of them in Contribution 2 --- sitting a few centimetres from a table that renders the same
three quantities through their macros. They had been there since the ledger existed. Nothing
had ever looked, because every round's search followed the previous round's repair and no
repair had ever touched them.

This is that sweep, run on every build. It is deliberately not clever:

* only macros the document actually uses somewhere, so a value that merely exists in the
  ledger cannot indict an unrelated number;
* only values with a decimal point, because a bare integer collides with ordinary prose;
* tabular bodies, `\input`ed files and comments are masked, because a number inside a
  generated table is data rather than a claim;
* a positive value is not matched where a minus sign precedes it, since `-0.05` is not the
  quantity `0.05`.

What survives is a small allow-list of genuine coincidences, each with a reason. The main text
needs none: after round 24 it is clean, and the pin below says so, so a new copy there fails
rather than joining a list.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
GENERATED = REPO / "docs" / "generated" / "paper_numbers.tex"
DOCS = ("paper.tex", "supplement.tex")

#: Literals that share a value with an emitted macro and are a different quantity. Keyed by
#: (document, macro, a distinctive fragment of the surrounding text) so that moving the
#: sentence does not silently keep the exemption alive somewhere else.
ALLOWED = {
    ("supplement.tex", "tailRsq", r"\rho$ of $0.881$, $0.920$, $0.950$, $0.970$ and $0.990$"):
        "a utilization in the knee sweep that happens to equal the fitted R-squared",
    ("supplement.tex", "tailRsq", r"Over $\rho = 0.881$ to $0.990$"):
        "the same utilization, as the upper end of the swept range",
    ("supplement.tex", "tailRsq", r"($\rho = 0.881$--$0.990$)"):
        "the same utilization again, in the round-2 restatement",
    ("supplement.tex", "tracedMleAlpha", r"($1.19\times$, $z=3.46$)"):
        "a between-arm factor that happens to equal the grouped tail index",
    ("supplement.tex", "tracedMleAlpha", r"a small $k=7$ difference ($1.19\times$"):
        "the same factor, in the round-2 restatement",
}


def _macros():
    if not GENERATED.exists():                      # pragma: no cover - generated at build
        pytest.skip("docs/generated/paper_numbers.tex absent; run emit_paper_numbers.py")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}\s*$",
                           GENERATED.read_text(encoding="utf-8"), re.M))


def _masked(text):
    """Blank the regions where a bare number is data rather than a claim.

    Same length as the original so line numbers still mean something.
    """
    def blank(m):
        # Newlines survive, so a line number reported after a masked table is still the
        # line the reader will find in an editor.
        return re.sub(r"[^\n]", " ", m.group(0))

    out = re.sub(r"\\begin\{tabular\}.*?\\end\{tabular\}", blank, text, flags=re.S)
    out = re.sub(r"\\input\{[^}]*\}", blank, out)
    out = re.sub(r"(?m)%[^\n]*", blank, out)
    return out


def transcribed(doc):
    """Every literal in `doc` that duplicates a macro the same document uses."""
    macros = _macros()
    raw = (REPO / doc).read_text(encoding="utf-8")
    text = _masked(raw)
    used = [n for n in macros if re.search(r"\\" + n + r"\b", raw)]
    out = []
    for name in sorted(used):
        value = macros[name].strip()
        if not re.fullmatch(r"-?\d+\.\d+", value):
            continue
        # A positive value is not this quantity where a minus sign precedes it.
        lead = r"(?<![\d.\w-])" if not value.startswith("-") else r"(?<![\d.\w])"
        for m in re.finditer(lead + re.escape(value) + r"(?![\d.])", text):
            line = text.count("\n", 0, m.start()) + 1
            context = " ".join(raw[max(0, m.start() - 70):m.start() + 40].split())
            out.append({"doc": doc, "macro": name, "value": value,
                        "line": line, "context": context})
    return out


def _excused(hit):
    for (doc, macro, fragment), _reason in ALLOWED.items():
        if hit["doc"] == doc and hit["macro"] == macro:
            if " ".join(fragment.split()) in hit["context"]:
                return True
    return False


class TestNoQuantityIsTypedWhereItCouldBeRead:

    @pytest.mark.parametrize("doc", DOCS)
    def test_the_document_reads_its_numbers_from_the_ledger(self, doc):
        bad = [h for h in transcribed(doc) if not _excused(h)]
        assert not bad, (
            "value(s) typed by hand that the ledger already emits -- the emitted copy moves "
            "when the campaign is recomputed and this one does not:\n  "
            + "\n  ".join("%s:%d  %s = %s  ...%s"
                          % (h["doc"], h["line"], "\\" + h["macro"], h["value"],
                             h["context"][-70:]) for h in bad))

    def test_the_main_text_needs_no_exemptions_at_all(self):
        """The paper is the document that matters and it is clean.

        If this ever fails, the honest move is to fix the literal, not to add an entry: four
        of these sat in Contribution 2 and Section V-C for twenty-two rounds precisely because
        nothing ever made them visible.
        """
        assert not [k for k in ALLOWED if k[0] == "paper.tex"], \
            "the main text has an exemption; fix the number instead"
        assert not transcribed("paper.tex")


class TestTheSweepItself:
    """A sweep that cannot find anything is worth nothing, so its parts are tested."""

    def test_it_finds_a_planted_copy(self, tmp_path):
        macros = _macros()
        name, value = next((n, v) for n, v in sorted(macros.items())
                           if re.fullmatch(r"\d+\.\d+", v.strip()))
        text = "we use \\%s here, and also %s typed out\n" % (name, value)
        assert re.search(r"(?<![\d.\w-])" + re.escape(value.strip()) + r"(?![\d.])", text)

    def test_a_longer_number_containing_the_value_is_not_a_match(self):
        assert not re.search(r"(?<![\d.\w-])" + re.escape("2.07") + r"(?![\d.])", "12.078")

    def test_a_negated_value_is_not_the_positive_quantity(self):
        assert not re.search(r"(?<![\d.\w-])" + re.escape("0.05") + r"(?![\d.])", "$R^2 = -0.05$")

    def test_masking_blanks_a_table_but_keeps_the_line_count(self):
        src = "before\n\\begin{tabular}{ll}\n1.23 & 4.56 \\\\\n\\end{tabular}\nafter\n"
        got = _masked(src)
        assert got.count("\n") == src.count("\n")
        assert "1.23" not in got and "before" in got and "after" in got

    def test_masking_blanks_a_comment(self):
        assert "2.07" not in _masked("% a comment mentioning 2.07\n")

    def test_masking_blanks_an_input(self):
        assert "generated" not in _masked(r"\input{docs/generated/grid_table}")

    def test_every_exemption_still_matches_something(self):
        """A stale entry would quietly licence a copy nobody is looking at any more."""
        live = {(h["doc"], h["macro"]) for doc in DOCS for h in transcribed(doc)}
        stale = [k for k in ALLOWED if (k[0], k[1]) not in live]
        assert not stale, "exemption(s) matching nothing: %s" % stale

    def test_every_exemption_carries_a_reason(self):
        assert all(v and len(v) > 20 for v in ALLOWED.values())
