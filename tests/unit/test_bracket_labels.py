r"""Every interval printed in the manuscript's prose says what it is, where it is printed.

Round 77 set the rule for Section V-D's bracket; round 78 restated it for the second bracket in
the same paragraph; round 79 found two more that nobody had listed. Section V-C printed
"fell 4.1x [3.5-4.8]", a Katz 95% interval sitting in prose outside Table II, whose caption
labels only the table's own brackets. Section VI-B printed "(+0.31, Fisher +0.08-+0.51, over 71
cells)": the method was named, the level was not, the statistic (Spearman's) was not, and a
dash between two signed numbers did not read as a range.

A rule applied bracket by bracket, when a referee points at one, leaves the next one standing.
This gate reads every `$\...CI$` macro in the prose (tables excluded: their captions and column
heads carry the label) and requires the bracket or parenthesis around it to name a method and a
level.

v5 (28 Sep). An outside editor asked for the paper's prose to stop carrying intervals ("the
Katz brackets can go to the supplement"), and they went there. The article now prints none, so
a gate over the article alone would pass on an empty set; the rule follows the intervals into
the supplement, whose twelve unlabeled ones it found at once. Two extensions came with the
move, both narrower than they look. A supplement sentence may introduce its interval in words
rather than brackets ("Newcombe's 95% interval on that difference is ..."), so where no bracket
opens within reach the clause before the interval is read instead; it must still name both. And
a bare `tabular` outside a float is a table like any other: its column head labels its cells.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)
DOCS = ("paper.tex", "supplement.tex", "postmortem.tex")

METHOD = re.compile(r"bootstrap|Katz|Wilson|Fisher|Newcombe|Clopper|Student|profile likelihood",
                    re.I)
LEVEL = re.compile(r"(?:90|95|99)" + re.escape(BS) + r"%")
CI = re.compile(r"\$" + re.escape(BS) + r"(\w+CI)\$")


def prose(tex):
    """The document body without comments, table floats or bare tabulars."""
    body = tex[tex.index(BS + "begin{document}"):]
    body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
    for env in (r"table\*?", r"tabular\*?"):
        body = re.sub(re.escape(BS) + r"begin\{(" + env + r")\}.*?" + re.escape(BS)
                      + r"end\{\1\}", " ", body, flags=re.S)
    return " ".join(body.split())


def unlabeled(tex):
    """(macro, context) for every prose interval whose label names no method or no level.

    The label is the bracket or parenthesis the interval sits in, when one opens within 80
    characters before it; otherwise the words that introduce it, back to the start of the
    clause and no further than 120 characters."""
    text = prose(tex)
    out = []
    for m in CI.finditer(text):
        start = max(text.rfind("[", 0, m.start()), text.rfind("(", 0, m.start()))
        if start >= 0 and m.start() - start <= 80:
            window = text[start:m.start()]
        else:
            clause = max(text.rfind(". ", 0, m.start()), text.rfind("; ", 0, m.start()))
            window = text[max(clause, m.start() - 120, 0):m.start()]
        if not (METHOD.search(window) and LEVEL.search(window)):
            out.append((m.group(1), text[max(0, m.start() - 70):m.end()]))
    return out


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


@pytest.mark.parametrize("doc", DOCS)
def test_every_prose_interval_names_its_method_and_level(doc):
    bad = unlabeled((REPO / doc).read_text(encoding="utf-8"))
    assert not bad, "%s: bracket(s) that do not say what they are: %s" % (doc, "; ".join(
        "%s in ...%s" % (name, ctx) for name, ctx in bad))


def test_the_manuscript_has_prose_intervals_to_check(paper, supplement):
    """A gate over an empty set passes for the wrong reason."""
    assert len(CI.findall(prose(paper))) + len(CI.findall(prose(supplement))) >= 4


def test_a_bare_bracket_is_caught(supplement):
    bad = supplement.replace("[Katz $95" + BS + "%$: $" + BS + "payloadRateFallCI$]",
                             "[$" + BS + "payloadRateFallCI$]")
    assert bad != supplement, "S7's payload sentence has been reworded; retarget this mutation"
    assert [n for n, _ in unlabeled(bad)] == ["payloadRateFallCI"]


def test_a_method_without_a_level_is_caught(supplement):
    bad = supplement.replace("Fisher $95" + BS + "%$: $", "Fisher $")
    assert bad != supplement, "S10's correlation has been reworded; retarget this mutation"
    assert [n for n, _ in unlabeled(bad)] == ["ombRetentionRhoCI"]


def test_an_interval_introduced_in_words_must_name_both():
    doc = BS + "begin{document} "
    named = doc + "Newcombe's $95" + BS + "%$ interval on that difference is $" + BS + "xCI$."
    assert unlabeled(named) == []
    no_level = doc + "Newcombe's interval on that difference is $" + BS + "xCI$."
    assert [n for n, _ in unlabeled(no_level)] == ["xCI"]
    # The clause boundary stops the search: a label in the previous sentence is not this one's.
    earlier = doc + "A Wilson $95" + BS + "%$ interval. The next one is $" + BS + "xCI$."
    assert [n for n, _ in unlabeled(earlier)] == ["xCI"]


def test_tables_are_left_to_their_captions():
    tex = (BS + "begin{document}" + BS + "begin{table}[$" + BS + "rtLowFactorCI$]"
           + BS + "end{table} text")
    assert unlabeled(tex) == []


def test_a_bare_tabular_is_left_to_its_column_heads():
    tex = (BS + "begin{document}" + BS + "begin{tabular}{l} Exact (Wilson 95" + BS
           + "% CI) " + BS + BS + " [$" + BS + "recoveryPassExactCI$] " + BS + "end{tabular} text")
    assert unlabeled(tex) == []
