"""Every float carries a label, and nothing points at a float by where it sits on the page.

Round 45 found prose pointers to *sections* that no longer resolved and gated them. Round 48
found the same defect one level down, at float level, and it had already broken in the built
PDF.

Four tables in S23 -- the send-interval ladder, the payload sweep, the load sweep behind the
withdrawn queueing form, and the selection bound -- carried no `\\label`. They were the only
four unlabelled floats in either document. Because they could not be referenced, the prose
introducing them pointed by position:

    The table below it keeps the individual replicate retentions for three arms.

That sentence rendered on page 23. The table it names rendered on page 24. It was true in the
source and false in the artifact, and no gate could have said so, because "below" is not a
property of the source at all -- LaTeX decides it, at build time, from the float queue.

A positional pointer cannot be checked. It can only be forbidden, which is what this file
does. Labels are the alternative: `\\ref` is correct wherever the float lands.

The label rule is the enabling half. Three of those four tables had no prose pointer of any
kind, so labelling them is what let the reachability rule below apply to them at all -- a
float nobody can name is also a float nobody has to introduce.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex")

FLOAT = re.compile(r"\\begin\{(figure|table)(\*?)\}(.*?)\\end\{\1\2\}", re.S)


def _source(name):
    path = REPO / name
    if not path.exists():
        pytest.skip("%s not present" % name)
    return re.sub(r"(?<!\\)%.*", "", path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", params=DOCS)
def doc(request):
    return request.param, _source(request.param)


class TestEveryFloatCanBeNamed:

    def test_every_float_carries_a_label(self, doc):
        name, text = doc
        bad = []
        for m in FLOAT.finditer(text):
            if re.search(r"\\label\{", m.group(3)):
                continue
            line = text.count("\n", 0, m.start()) + 1
            cap = re.search(r"\\caption\{(.{0,80})", m.group(3), re.S)
            bad.append("%s:%d  %s -- %s" % (
                name, line, m.group(1),
                re.sub(r"\s+", " ", cap.group(1)) if cap else "(no caption either)"))
        assert not bad, (
            "float(s) with no \\label, so no sentence can point at one except by position:\n  "
            + "\n  ".join(bad))

    def test_every_label_is_unique(self, doc):
        name, text = doc
        labels = [l for m in FLOAT.finditer(text)
                  for l in re.findall(r"\\label\{([^}]*)\}", m.group(3))]
        dupes = sorted({l for l in labels if labels.count(l) > 1})
        assert not dupes, "%s: duplicate float labels %s -- \\ref would pick one" % (
            name, dupes)

    def test_every_float_is_referenced(self, doc):
        """A float nothing points at is a float the reader arrives at without a reason."""
        name, text = doc
        refs = set(re.findall(r"\\(?:eq)?ref\{([^}]*)\}", text))
        if name == "supplement.tex":
            refs |= set(re.findall(r"\\(?:eq)?ref\{([^}]*)\}",
                                   _source("paper.tex")))
        orphans = []
        for m in FLOAT.finditer(text):
            for label in re.findall(r"\\label\{([^}]*)\}", m.group(3)):
                if label not in refs:
                    line = text.count("\n", 0, m.start()) + 1
                    orphans.append("%s:%d  %s" % (name, line, label))
        assert not orphans, "float(s) never referenced:\n  " + "\n  ".join(orphans)


class TestNothingPointsAtAFloatByPosition:
    """"The table below it" is decided by LaTeX at build time, not by the author."""

    POSITIONAL = re.compile(
        r"\b(?:the\s+)?(?:table|figure|plot|chart)\s+"
        r"(?:just\s+)?(?:below|above|beneath|overleaf|opposite|that\s+follows|"
        r"on\s+the\s+(?:left|right))\b",
        re.I)

    def test_no_positional_float_pointer(self, doc):
        name, text = doc
        bad = []
        for m in self.POSITIONAL.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 70):m.end() + 50])
            bad.append("%s:%d  %r\n        ...%s..." % (name, line, m.group(0), ctx.strip()))
        assert not bad, (
            "float pointed at by position; LaTeX chooses where floats land, so this is a "
            "claim about the page that the source cannot keep:\n  " + "\n  ".join(bad))

    def test_the_rule_can_fail(self):
        """The sentence that broke, and one that must stay legal."""
        assert self.POSITIONAL.search(
            "by the test suite rather than proofread. The table below it keeps the")
        assert self.POSITIONAL.search("see the figure above for the shape")
        # "below" about a *value* is ordinary prose and must not trip the rule.
        assert not self.POSITIONAL.search("every rate below saturation retains everything")
        assert not self.POSITIONAL.search("the rows below the rule are observed, not manipulated")
