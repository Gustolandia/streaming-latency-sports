"""A sentence that says what an equation does, against the equation.

Round 48 found this in the one sentence of the manuscript a referee reads first for
originality. Section II positions the paper against Villain et al. and says:

    We add its consequence for a two-process measurement, *a law relating the negative-span
    rate to the flight measured* (Equation~\\ref{eq:negspan}) ...

Equation 3 is `Pr[S < 0] = Pr[A > D]`. It is an identity between two measured quantities and
the flight does not appear in it. There is no `T_true`, no distribution function, nothing that
could relate a rate to a duration. The paper was claiming a contribution and pointing at an
equation that does not contain it.

**No existing gate could see this, and `\\ref` could not have prevented it.** The pointer
resolved. It resolved to a real, numbered, labelled equation in the same document. What had
happened is that Equation 3 was *replaced in its own slot*: at commit 9a59ba7 it read

    Pr[inversion] = F_Delta(-T_true)

which is exactly the law the sentence claims, and the rename that turned "inversion" into
"negative span" (4d2962d) put the identity there instead. Every `\\ref` followed the label,
because that is what labels do. The prose describing what the label pointed at did not,
because prose has no labels. Nothing in the build failed, because nothing was broken --
only untrue.

The claim is sound: Equation 6, `Pr[span<0 | T_true] = p(rho) G(T_true)`, is the law the
sentence promises. The citation was one equation short of the paper's own result.

So this file does the only thing that catches the class: it reads the sentence, finds the
equation it cites, and checks that the equation contains the symbols the sentence says it
relates. A description is bound to content rather than to a number, which means an equation
can be renamed, renumbered, or moved freely -- and cannot be quietly swapped for a different
one underneath a sentence that still describes the old one.
"""
from pathlib import Path
import re

import pytest

REPO = Path(__file__).parent.parent.parent
DOCS = ("paper.tex", "supplement.tex", "postmortem.tex")


def _source(name):
    path = REPO / name
    if not path.exists():
        pytest.skip("%s not present" % name)
    return re.sub(r"(?<!\\)%.*", "", path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def paper():
    return _source("paper.tex")


@pytest.fixture(scope="module", params=DOCS)
def doc(request):
    return request.param, _source(request.param)


@pytest.fixture(scope="module")
def equations():
    """label -> the equation's body, across both documents.

    The supplement loads `xr`, so a `\\ref{eq:twostate}` there resolves against the paper's
    equation. The seventh instance of this defect was exactly that: a supplement figure
    caption citing a main-text equation that could not support the caption's own sentence.
    A table built from one document would not have seen it.
    """
    out = {}
    for name in DOCS:
        for m in re.finditer(r"\\begin\{(equation|align)\}(.*?)\\end\{\1\}",
                             _source(name), re.S):
            for label in re.findall(r"\\label\{([^}]*)\}", m.group(2)):
                out[label] = m.group(2)
    return out


#: (what the prose claims, symbols the cited equation must contain, why).
#:
#: Each entry names a sentence that makes a claim *about an equation* rather than merely
#: citing one, and the symbol that claim requires. The test is deliberately about content:
#: it never checks which label is cited, only that whatever is cited can support the
#: sentence. That is what keeps it alive across renames.
CLAIMS = (
    # v4 (2026-09-08): "flight" retired for the field's word; the claim and the symbol it
    # requires are unchanged.
    #
    # Retired in round 60, deliberately, which is what the guard on this list asks for. The
    # sentence it watched -- Section III-B's "a law relating the negative-span rate to the
    # delivery being measured (Equation 6)" -- no longer exists. Equation 6 went to
    # Supplement S16 because nothing in the paper computed with it, and the claim against
    # Villain et al. now rests on the manipulations: "the negative-span rate falls as the
    # delivery being measured grows, and the manipulations that establish it separate
    # scheduling from its rival explanations". That sentence points at a section rather than
    # an equation, so there is no equation for it to disagree with, which is the only thing
    # this file checks. The lesson round 48 took from it is in `docs/infrastructure.md`.
    #
    # (r"a law relating the negative-span rate to the delivery being\s+measured",
    #  (r"T_\{\\mathrm\{true\}\}",),
    #  "a law relating a rate to the delivery must contain the true delivery"),
    # v4.1 (2026-09-08): "flight" retired in the supplement too; the claim is the same.
    (r"stall distribution\s+overlaps a short end-to-end\s+latency",
     (r"T_\{\\mathrm\{true\}\}",),
     "an equation about how a distribution overlaps the delivery must contain the delivery"),
    (r"lengthening what is being\s+measured lowers the rate",
     (r"T_\{\\mathrm\{true\}\}|D \\equiv|\\Pr\[A > D\]",),
     "the flight must appear, or the delivery it is compared against"),
    (r"predicts how the rate scales with",
     (r"T_\{\\mathrm\{true\}\}",),
     "a scaling law in the flight must contain the flight"),
)


class TestEveryClaimAboutAnEquationMatchesTheEquation:

    def _cited(self, text, match):
        """The equation labels cited in the sentence the match sits in."""
        start = text.rfind(".", 0, match.start()) + 1
        end = text.find(".", match.end())
        sentence = text[start:end if end != -1 else len(text)]
        return sentence, re.findall(r"\\(?:eq)?ref\{(eq:[^}]*)\}", sentence)

    @pytest.mark.parametrize("pattern,required,why", CLAIMS)
    def test_the_cited_equation_supports_the_claim(self, doc, equations, pattern,
                                                   required, why):
        name, text = doc
        problems = []
        for m in re.finditer(pattern, text):
            sentence, labels = self._cited(text, m)
            if not labels:
                continue
            for label in labels:
                body = equations.get(label)
                if body is None:
                    problems.append("%s cites \\ref{%s}, which labels no equation"
                                    % (name, label))
                    continue
                for symbol in required:
                    if not re.search(symbol, body):
                        problems.append(
                            "%s cites \\ref{%s}, whose body is %r -- %s"
                            % (name, label, re.sub(r"\s+", " ", body).strip()[:90], why))
        assert not problems, (
            "a sentence describes an equation that cannot support the description:\n  "
            + "\n  ".join(problems))

    def test_every_claim_pattern_still_matches_something(self, equations):
        """A pattern that matches nothing is a retired guard pretending to be a live one."""
        joined = "\n".join(_source(n) for n in DOCS)
        dead = [why for pattern, _req, why in CLAIMS if not re.search(pattern, joined)]
        assert not dead, (
            "these guards no longer match any sentence; the prose was reworded and the guard "
            "should be retired or updated deliberately: %s" % dead)

    def test_the_contribution_claim_is_still_made(self, paper):
        """If this sentence is ever reworded away, the check above silently skips.

        The claim is the paper's delta over Villain et al. Losing it without noticing would
        be worse than mis-citing it.

        Round 60 reworded it and the guard follows the claim rather than the wording. It read
        "a law relating the negative-span rate to the delivery being measured (Equation 6)";
        Equation 6 went to Supplement S16 because nothing in the paper computed with it, and
        the delta is now stated as the measured dependence plus the manipulations that
        establish it. Two things must survive, and they are what this asserts: the rate's
        dependence on the delivery, and the manipulations. A claim that keeps only the first
        is a claim Villain et al. could have made.
        """
        flat = " ".join(paper.split())
        # The 5 Oct 2026 rebuild restated the delta as the laws: Related Work says what Villain
        # et al. do not give, "the consequence for a difference read by two processes: that it
        # falls below zero at a rate set by the waiting probability and the path's length, on
        # the timescale of the slice", and Section IV opens on the manipulations that establish
        # it. Both halves are still required, each where the paper now makes it.
        related = flat[flat.index(r"\section{Related Work}"):]
        related = related[:related.index(r"\section{", 10)]
        assert re.search(r"consequence for a difference read by two processes", related) and \
            re.search(r"at a rate set by the waiting probability and the path's length",
                      related), (
            "Related Work no longer claims the rate's dependence on the delivery; if that is "
            "deliberate, say what replaced the delta over Villain et al.")
        mechanism = flat[flat.index(r"\label{sec:mechanism}"):flat.index(r"\label{sec:external}")]
        assert re.search(r"We show by \\emph\{manipulation\}", mechanism), (
            "the delta over Villain et al. is the dependence *and* the manipulations; the "
            "dependence alone is what they already had")

    def test_the_binding_can_fail(self, equations):
        """Prove the rule bites: Equation 3 must NOT satisfy the rate-to-flight claim."""
        identity = equations.get("eq:negspan")
        assert identity is not None, "eq:negspan should still exist"
        assert not re.search(r"T_\{\\mathrm\{true\}\}", identity), (
            "eq:negspan now contains the flight; if the identity was replaced by a law, "
            "this guard needs rewriting rather than deleting")

    def test_the_equation_that_carries_the_law_still_does(self, equations):
        """The positive half: Equation 6 must keep the flight term Section II cites it for."""
        two_state = equations.get("eq:twostate")
        assert two_state is not None, "eq:twostate should still exist"
        assert re.search(r"T_\{\\mathrm\{true\}\}", two_state), (
            "eq:twostate lost the flight term; Section II cites it for a law relating the "
            "rate to the flight measured")


class TestTheModelDoesNotAssertWhatTheTableRefutes:
    r"""Equation 6 must not write the preemption probability as a function of $\rho$ alone.

    Round 49: the equation read $p(\rho)\,G(T_{\mathrm{true}})$, which at fixed flight makes
    the rate a function of utilization. Table II's lower panel is a manipulation showing it
    is not --- two core geometries at $\rho = 0.7531$, rates 0.0824 against 0.1709 --- and
    the table's own caption draws the inference in as many words: "a function of $\rho$
    returns one value for one input". Section V-C then generalises it to "refutes *every*
    account in which the negative-span rate is a function of utilization".

    So the main text asserted a form, and refuted it on the facing page, and said nothing
    about the collision. The supplement had it right all along --- "read as a function of
    $\rho$ alone the model has no content" --- which makes this a propagation failure rather
    than a misunderstanding, and exactly the kind a gate can hold.

    The rule is deliberately narrow: it does not police notation in general, only that this
    one equation does not re-acquire the dependence this paper's own experiment removes.
    """

    def test_the_two_state_model_does_not_parameterise_p_by_rho(self, equations):
        body = equations.get("eq:twostate")
        assert body is not None, "eq:twostate should still exist"
        assert not re.search(r"p\s*\(\s*\\rho\s*\)", body), (
            "Equation 6 writes p as a function of rho, which Table II's lower panel refutes "
            "at a single rho; write p and name what moves it")

    def test_the_refutation_claim_is_still_made(self, paper):
        """If Section V-C ever stops making it, this guard should be retired knowingly.

        v5 (28 Sep) narrowed "every account in which the negative-span rate is a function of
        utilization" to "any account in which utilization alone sets the rate": an outside
        editor read "every account" as a dare, and the narrower form is the one the geometry
        rows prove. The refutation is the same one; so is the guard's reason to exist."""
        assert re.search(r"refutes any account in which utilization alone\s+sets the rate",
                         paper), (
            "Section V-C no longer refutes utilization-only accounts; re-examine whether "
            "Equation 6 may carry p(rho) again")

    def test_the_main_text_says_why_p_is_not_a_function_of_rho(self, paper):
        """The clause that keeps a reader from thinking the paper contradicts itself.

        Until 5 Oct 2026 it read "we write $p$, not $p(\\rho)$". The rebuilt Section IV-B says
        instead what moves $p$ -- "Load, its placement and priority move $p$" -- which names
        the placement that moves it at a fixed utilization; either form keeps a reader of
        Equation 3 from reading the placement contrast as refuting it.
        """
        flat = " ".join(paper.split())
        assert re.search(r"\$p\$ and not\s+\$p\(\\rho\)\$|not\s+\$p\(\\rho\)\$", flat) or \
            re.search(r"placement[^.]*\bmove \$p\$", flat), (
                "Section IV-B must say why p is written bare, or a reader who takes Equation 3 "
                "literally reads the placement contrast as refuting it")
