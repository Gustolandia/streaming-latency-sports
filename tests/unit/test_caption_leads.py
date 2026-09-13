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
            cap = re.search(r"\\caption(?:\[[^\]]*\])?\{", block)
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

    def test_every_supplement_figure_opens_on_a_bolded_claim_too(self):
        """Round 76 narrowed the supplement's exemption to its tables.

        The exemption above was recorded for "forty-odd floats and a different job", and for
        the supplement's twenty-seven tables it still holds: most open on a claim sentence, a
        few on a description, and bolding them is a style cascade nobody has asked for. The
        FIGURES were different. Nine of thirteen carried a bolded claim. Three opened on
        labels -- "Window sweep, as a picture.", "Experiment map.", "Audit on Testbed A." --
        and the round-76 image review found them by setting all seventeen captions side by
        side, which is how round 37 found the paper's. The fourth was found by this test on
        its first run, and not by the eye: `fig:e1` was bold, but its entire lead was
        "Withdrawn." -- one word, a status rather than a claim, which the sentence rule below
        rejects and a glance at a list of bold leads does not.

        All thirteen comply now, so requiring it costs nothing today and stops the three
        from coming back. Tables stay surveyed, not required, and this docstring is where to
        change that if a later round decides otherwise.
        """
        figures = [(lab, cap) for env, lab, cap in
                   captions((REPO / "supplement.tex").read_text(encoding="utf-8"))
                   if env == "figure"]
        assert len(figures) >= 13, "the supplement's figures stopped parsing"
        bad = []
        for lab, cap in figures:
            text = lead(cap)
            words = ([w for w in re.sub(r"[^A-Za-z ]", " ", text).split() if len(w) > 1]
                     if text else [])
            if text is None or len(words) < 3 or re.match(r"^\(?[a-z]\)", text):
                bad.append("%s: %r" % (lab, (text if text is not None else cap)[:60]))
        assert not bad, ("supplement figure(s) not opening on a bolded claim:\n  "
                         + "\n  ".join(bad))

    def test_a_supplement_figure_is_listed_by_the_claim_it_opens_on(self):
        """The List of Figures shows the short caption, and round 76 fixed only the long one.

        Round 76 rewrote four supplement figure captions to open on a claim, and left their
        `\\caption[short]` arguments alone, so the supplement's List of Figures kept listing
        three of them by the labels the repair had removed -- "Window sweep, as a picture",
        "Experiment map", "Audit on Testbed A" -- and a fourth by a claim its caption no longer
        makes. Round 77's image review found them in the rendered list, beside the new
        recovery figure, whose short title had drifted from its own lead the day it was written.

        A reader scanning the list for an exhibit should meet the same sentence the exhibit
        opens with. Figures only, for the reason the supplement's tables are surveyed rather
        than required above.
        """
        text = (REPO / "supplement.tex").read_text(encoding="utf-8")
        bad = []
        for block in re.findall(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", text, re.S):
            short = re.search(r"\\caption\[([^\]]*)\]\{", block)
            if not short:
                continue
            cap = captions(r"\begin{figure}" + block + r"\end{figure}")
            if not cap:
                continue
            env, lab, body = cap[0]
            claim = lead(body)
            if claim is None:
                continue                                # the lead rules above own this case
            want = " ".join(claim.rstrip(".").split())
            got = " ".join(short.group(1).split())
            if got != want:
                bad.append("%s: listed as %r, opens on %r" % (lab, got, want))
        assert not bad, ("supplement figure(s) listed by a title that is not their claim:\n  "
                         + "\n  ".join(bad))

    def test_there_are_exhibits_to_police(self):
        """A floor, not a target.

        It guards against the rule quietly policing nothing, which is what happens if the
        caption regex stops matching. The number tracks the paper: seven exhibits after
        round 43 moved the payload-flip figure to the supplement to fit four biographies
        inside twelve pages. Lower it when a float genuinely leaves; do not lower it to make
        a broken extractor pass.

        Six since round 59, and the float genuinely left. The second author's note asked for
        the grid refinement to become the explanation of the deletion rather than a
        contribution in its own right, so the grid-membership figure went to Supplement S23,
        beside the per-configuration table it summarises. Four figures and two tables remain.
        """
        found = captions((REPO / "paper.tex").read_text(encoding="utf-8"))
        assert len(found) >= 6, "expected the paper's figures and tables; found %d" % len(found)


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
