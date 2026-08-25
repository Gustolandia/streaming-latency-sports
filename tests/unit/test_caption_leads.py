r"""Every exhibit opens on a claim, in bold, the way every section opens on a claim.

The Feynman rule is enforced on sections by `test_section_openings`: a section may not open on
a cross-reference, it must say something. The same convention runs through the exhibits and
was never checked, so it held in eight of ten and quietly lapsed in two.

Figure 5's caption led with a real claim --- "The campaign's confirmed prediction." --- and
simply was not bold. **Figure 1 had no claim at all**: its caption opened directly on the panel
label, "(a)~How a positive latency is measured as negative...". That is the paper's first
figure, the anchor for both failure modes, the exhibit a reader meets before any result, and
it was the only one of the ten that did not tell them what it was for.

Round 37 found this by putting all ten captions side by side, which nobody had done in
thirty-six rounds of review. This rule does it on every build.

The check is deliberately shallow: it asks that the caption *start* with `\textbf{...}` and
that the bolded lead read as a sentence rather than as a label. It does not judge whether the
claim is a good one --- no test can --- but a caption that opens on "(a)" is not making one.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex")

#: The main text's exhibits carry the convention. The supplement is a reference document with
#: forty-odd floats and a different job, so it is surveyed but not required to comply.
REQUIRED = ("paper.tex",)


def captions(text):
    """[(env, label, caption)] for every captioned float."""
    out = []
    for env in ("figure", "table"):
        for m in re.finditer(r"\\begin\{%s\*?\}(.*?)\\end\{%s\*?\}" % (env, env), text, re.S):
            block = m.group(1)
            cap = re.search(r"\\caption\{", block)
            if not cap:
                continue
            depth, i = 1, cap.end()
            while i < len(block) and depth:
                depth += {"{": 1, "}": -1}.get(block[i], 0)
                i += 1
            lab = re.search(r"\\label\{([^}]*)\}", block)
            out.append((env, lab.group(1) if lab else "?",
                        " ".join(block[cap.end():i - 1].split())))
    return out


def lead(caption):
    r"""The bolded opening of a caption, or None if it does not start with one."""
    m = re.match(r"\\textbf\{", caption)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(caption) and depth:
        depth += {"{": 1, "}": -1}.get(caption[i], 0)
        i += 1
    return caption[m.end():i - 1].strip()


class TestEveryExhibitOpensOnAClaim:

    @pytest.mark.parametrize("doc", REQUIRED)
    def test_every_caption_starts_with_a_bold_lead(self, doc):
        bad = [(env, lab, cap[:70]) for env, lab, cap in
               captions((REPO / doc).read_text(encoding="utf-8")) if lead(cap) is None]
        assert not bad, (
            "exhibit(s) whose caption does not open on a bolded claim, where the other "
            "exhibits do:\n  "
            + "\n  ".join("%s %-16s %s" % (e, l, c) for e, l, c in bad))

    @pytest.mark.parametrize("doc", REQUIRED)
    def test_the_lead_is_a_sentence_not_a_label(self, doc):
        """"(a)" in bold would satisfy the rule above and satisfy nothing a reader wants."""
        bad = []
        for env, lab, cap in captions((REPO / doc).read_text(encoding="utf-8")):
            text = lead(cap)
            if text is None:
                continue                                # the rule above owns this case
            words = [w for w in re.sub(r"[^A-Za-z ]", " ", text).split() if len(w) > 1]
            if len(words) < 3 or re.match(r"^\(?[a-z]\)", text):
                bad.append("%s %s: %r" % (env, lab, text))
        assert not bad, "caption lead(s) that are labels rather than claims:\n  " + \
            "\n  ".join(bad)

    def test_there_are_exhibits_to_police(self):
        found = captions((REPO / "paper.tex").read_text(encoding="utf-8"))
        assert len(found) >= 8, "expected the paper's figures and tables; found %d" % len(found)


class TestTheCheckCanFail:
    """The two round-37 defects, reconstructed, and the shapes that must not fire."""

    NO_CLAIM = (r"\begin{figure*}[t]\includegraphics{x.pdf}"
                r"\caption{(a)~How a positive latency is measured as negative, on one clock.}"
                r"\label{fig:model}\end{figure*}")
    NO_BOLD = (r"\begin{figure}[tb]\includegraphics{x.pdf}"
               r"\caption{The campaign's confirmed prediction. (a)~Retention replicates.}"
               r"\label{fig:payloadflip}\end{figure}")
    GOOD = (r"\begin{figure}[tb]\includegraphics{x.pdf}"
            r"\caption{\textbf{A late stamp, not an early record.} (a)~How it happens.}"
            r"\label{fig:model}\end{figure}")

    def test_a_caption_opening_on_a_panel_label_is_caught(self):
        assert lead(captions(self.NO_CLAIM)[0][2]) is None

    def test_a_claim_that_is_merely_unbolded_is_caught(self):
        assert lead(captions(self.NO_BOLD)[0][2]) is None

    def test_a_bolded_claim_passes(self):
        assert lead(captions(self.GOOD)[0][2]) == "A late stamp, not an early record."

    def test_a_bolded_panel_label_is_not_a_claim(self):
        cap = captions(self.GOOD.replace("A late stamp, not an early record.", "(a)"))[0][2]
        text = lead(cap)
        assert text == "(a)" and re.match(r"^\(?[a-z]\)", text)

    def test_brace_matching_survives_nesting_in_the_lead(self):
        cap = (r"\caption{\textbf{The \emph{traced} run-queue stall distribution is trimodal.} "
               r"$551{,}956$ wakeups.}")
        block = r"\begin{figure}" + cap + r"\label{f}\end{figure}"
        assert lead(captions(block)[0][2]).endswith("is trimodal.")
