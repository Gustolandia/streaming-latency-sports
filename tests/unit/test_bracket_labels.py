r"""Every interval printed in the article's prose says what it is, where it is printed.

Round 77 set the rule for Section V-D's bracket; round 78 restated it for the second bracket in
the same paragraph; round 79 found two more that nobody had listed. Section V-C printed
"fell 4.1x [3.5-4.8]", a Katz 95% interval sitting in prose outside Table II, whose caption
labels only the table's own brackets. Section VI-B printed "(+0.31, Fisher +0.08-+0.51, over 71
cells)": the method was named, the level was not, the statistic (Spearman's) was not, and a
dash between two signed numbers did not read as a range.

A rule applied bracket by bracket, when a referee points at one, leaves the next one standing.
This gate reads every `$\...CI$` macro in the article's prose (tables excluded: their captions
carry the label) and requires the bracket or parenthesis around it to name a method and a level.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
BS = chr(92)

METHOD = re.compile(r"bootstrap|Katz|Wilson|Fisher|Newcombe|Clopper", re.I)
LEVEL = re.compile(r"(?:90|95|99)" + re.escape(BS) + r"%")
CI = re.compile(r"\$" + re.escape(BS) + r"(\w+CI)\$")


def prose(tex):
    """The document body without comments and without table floats."""
    body = tex[tex.index(BS + "begin{document}"):]
    body = re.sub(r"(?m)(?<!\\)%.*$", "", body)
    body = re.sub(re.escape(BS) + r"begin\{table\*?\}.*?" + re.escape(BS) + r"end\{table\*?\}",
                  " ", body, flags=re.S)
    return " ".join(body.split())


def unlabeled(tex):
    """(macro, context) for every prose interval whose bracket names no method or no level."""
    text = prose(tex)
    out = []
    for m in CI.finditer(text):
        start = max(text.rfind("[", 0, m.start()), text.rfind("(", 0, m.start()))
        window = text[start:m.start()] if start >= 0 and m.start() - start <= 80 else ""
        if not (METHOD.search(window) and LEVEL.search(window)):
            out.append((m.group(1), text[max(0, m.start() - 70):m.end()]))
    return out


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


def test_every_prose_interval_names_its_method_and_level(paper):
    bad = unlabeled(paper)
    assert not bad, "bracket(s) that do not say what they are: %s" % "; ".join(
        "%s in ...%s" % (name, ctx) for name, ctx in bad)


def test_the_article_has_prose_intervals_to_check(paper):
    """A gate over an empty set passes for the wrong reason."""
    assert len(CI.findall(prose(paper))) >= 4


def test_a_bare_bracket_is_caught(paper):
    bad = paper.replace("[Katz 95" + BS + "%: $" + BS + "payloadRateFallCI$]",
                        "[$" + BS + "payloadRateFallCI$]")
    assert bad != paper, "Section V-C has been reworded; retarget this mutation"
    assert [n for n, _ in unlabeled(bad)] == ["payloadRateFallCI"]


def test_a_method_without_a_level_is_caught(paper):
    bad = paper.replace("Fisher 95" + BS + "%: $", "Fisher $")
    assert bad != paper, "Section VI-B has been reworded; retarget this mutation"
    assert [n for n, _ in unlabeled(bad)] == ["ombRetentionRhoCI"]


def test_tables_are_left_to_their_captions():
    tex = (BS + "begin{document}" + BS + "begin{table}[$" + BS + "rtLowFactorCI$]"
           + BS + "end{table} text")
    assert unlabeled(tex) == []
