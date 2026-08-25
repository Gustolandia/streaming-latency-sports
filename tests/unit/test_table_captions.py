r"""Does a table caption describe the table it captions?

Table II's caption promised, for thirty-one rounds:

    The mechanism, by manipulation (2,985 matched events per cell; Wilson 95% intervals in
    brackets).

The Wilson intervals are not in brackets. They sit in their own column, headed `95% CI`,
printed as `0.1203--0.1446`. The only bracketed quantity anywhere in the table is the *z* value
inside the Factor column, `39x (19.8)` --- so a reader who follows the caption's own
instruction and looks at the brackets finds the wrong statistic.

Small, and worth a gate anyway, because of where the blind spot is. Three checks read every
figure before it is written: `figure_collisions` measures what is drawn through what,
`figure_legibility` measures type size, `figure_vocabulary` reads the words. **None of them
reads a table.** Both tables in the manuscript are hand-authored LaTeX rather than generated,
so they are the one class of exhibit in this project that nothing was ever asked to check, and
the first careful look found this.

The rule is narrow on purpose. A caption that promises a *typographic* convention --- brackets,
parentheses, italics, bold --- is making a claim about marks the checker can see in the source,
so that claim is checkable. Everything else a caption says is prose about the data, and a gate
that tried to police it would be guessing.

Tables only. A figure caption saying "intervals in brackets" is describing pixels this checker
cannot read, and a rule that pretended otherwise would either pass vacuously or fire on
correct captions. `figure_collisions` and its siblings own the figures; this owns the tables.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex")

#: promise in a caption -> a pattern that must appear in the table body if the promise holds.
#: The body patterns are deliberately loose: the question is whether the mark is used at all,
#: not whether every value carries it.
CONVENTIONS = (
    (r"\b(?:in|shown in) brackets\b|\bbracketed\b", r"\[[^\]]+\]", "square brackets"),
    (r"\b(?:in|shown in) (?:parentheses|parens)\b", r"\([^)]+\)", "parentheses"),
    (r"\b(?:in|shown in) italics\b|\bitalicised\b|\bitalicized\b",
     r"\\(?:emph|textit)\{", "italics"),
    (r"\b(?:in|shown in) bold\b|\bboldface\b|\bbolded\b", r"\\textbf\{", "bold"),
)


def tables(text):
    r"""[(line, caption, body)] for every table float that carries a caption.

    The body is the `tabular` content and nothing else. A first version took the whole float
    minus the caption, and every table passed the bracket rule for free: `\begin{table}[tb]`
    is square brackets, and so is a `\begin{tabular}[t]` placement. The gate reported the
    manuscript clean while Table II's caption was wrong, which is the failure this file exists
    to prevent one level up. The self-test below is what caught it.
    """
    out = []
    for m in re.finditer(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", text, re.S):
        block = m.group(1)
        cap = re.search(r"\\caption\{", block)
        if not cap:
            continue
        # Brace-match the caption so a nested \textbf{...} does not truncate it.
        depth, i = 1, cap.end()
        while i < len(block) and depth:
            depth += {"{": 1, "}": -1}.get(block[i], 0)
            i += 1
        caption = block[cap.end():i - 1]
        body = "".join(
            # An optional argument is markup, not data: `\begin{tabular}[t]`, `\addlinespace
            # [2pt]`, `\cmidrule[0.5pt]`. Each one is a pair of square brackets that would
            # satisfy the bracket rule for free, which is how the first two versions of this
            # gate reported Table II clean.
            re.sub(r"\\[a-zA-Z]+\s*\[[^\]]*\]", "", re.sub(r"^\[[^\]]*\]", "", t.group(1)))
            for t in re.finditer(r"\\begin\{tabular\}(.*?)\\end\{tabular\}", block, re.S))
        out.append((text.count("\n", 0, m.start()) + 1, caption, body))
    return out


def broken_promises(text):
    """[(line, what was promised, the caption)] for captions the table does not keep."""
    bad = []
    for line, caption, body in tables(text):
        flat = " ".join(caption.split())
        for promise, mark, name in CONVENTIONS:
            if re.search(promise, flat, re.I) and not re.search(mark, body):
                bad.append((line, name, flat))
    return bad


@pytest.fixture(scope="module", params=DOCS)
def doc(request):
    return request.param, (REPO / request.param).read_text(encoding="utf-8")


class TestACaptionDescribesItsOwnTable:

    def test_every_typographic_promise_is_kept(self, doc):
        name, text = doc
        bad = broken_promises(text)
        assert not bad, (
            "table caption(s) promising a convention the table does not use -- a reader who "
            "follows the caption looks at the wrong thing:\n  "
            + "\n  ".join("%s:%d  promises %s\n      %s" % (name, line, what, cap[:170])
                          for line, what, cap in bad))

    def test_there_are_tables_to_police(self):
        """If the float pattern ever stops matching, this rule goes quiet; say so loudly."""
        found = sum(len(tables((REPO / d).read_text(encoding="utf-8"))) for d in DOCS)
        assert found >= 2, "no captioned tables found at all -- has the markup changed?"


class TestTheCheckCanFail:
    """The round-31 defect, reconstructed, and the shapes that must not fire."""

    DEFECT = "\n".join([
        r"\begin{table}[tb]",
        r"\caption{\textbf{The mechanism} (Wilson $95\%$ intervals in brackets).}",
        r"\begin{tabular}{@{}llr@{}}",
        r"Arm & Rate & 95\% CI \\",
        r"real-time & $0.0034$ & $0.0018$--$0.0062$ \\",
        r"\end{tabular}", r"\end{table}"])

    KEPT = DEFECT.replace(r"$0.0018$--$0.0062$", r"[$0.0018$--$0.0062$]")

    def test_it_finds_the_defect_it_was_written_for(self):
        bad = broken_promises(self.DEFECT)
        assert len(bad) == 1 and bad[0][1] == "square brackets"

    def test_a_table_that_keeps_its_promise_passes(self):
        assert not broken_promises(self.KEPT)

    def test_a_caption_promising_nothing_is_not_policed(self):
        text = self.DEFECT.replace(" in brackets", "")
        assert not broken_promises(text)

    def test_the_caption_is_brace_matched_not_truncated(self):
        r"""`\textbf{...}` inside a caption must not end it early, or the promise is missed."""
        line, caption, body = tables(self.DEFECT)[0]
        assert "in brackets" in caption, "the caption was cut at the first closing brace"
        assert "0.0018" in body and "Wilson" not in body

    def test_the_caption_is_not_counted_as_the_body(self):
        """A promise satisfied only by marks inside the caption itself is not satisfied."""
        text = "\n".join([
            r"\begin{table}", r"\caption{Rates [see text] with intervals in brackets.}",
            r"\begin{tabular}{@{}l@{}} $0.1$ \\ \end{tabular}", r"\end{table}"])
        assert broken_promises(text), "the caption's own brackets must not count"

    def test_parentheses_italics_and_bold_are_each_recognised(self):
        for promise, mark in (("in parentheses", "($0.1$)"),
                              ("in italics", r"\emph{x}"),
                              ("in bold", r"\textbf{x}")):
            miss = "\n".join([r"\begin{table}", r"\caption{Values %s.}" % promise,
                              r"\begin{tabular}{@{}l@{}} $0.1$ \\ \end{tabular}",
                              r"\end{table}"])
            assert broken_promises(miss), "%s must be policed" % promise
            assert not broken_promises(miss.replace("$0.1$ \\\\", mark + " \\\\"))

    def test_a_float_without_a_caption_is_skipped(self):
        assert not tables(r"\begin{table}\begin{tabular}{l}x\end{tabular}\end{table}")
