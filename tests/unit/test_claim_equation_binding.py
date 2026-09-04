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
happened is that Equation 3 was *replaced in its own slot*: at commit 4c22c33 it read

    Pr[inversion] = F_Delta(-T_true)

which is exactly the law the sentence claims, and the rename that turned "inversion" into
"negative span" (5cc1600) put the identity there instead. Every `\\ref` followed the label,
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
DOCS = ("paper.tex", "supplement.tex")


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
    (r"a law relating the negative-span rate to the\s+flight measured",
     (r"T_\{\\mathrm\{true\}\}",),
     "a law relating a rate to the flight must contain the flight"),
    (r"stall distribution\s+overlaps a short flight",
     (r"T_\{\\mathrm\{true\}\}",),
     "an equation about how a distribution overlaps the flight must contain the flight"),
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
        """
        assert re.search(r"a law relating the negative-span rate to the\s+flight measured",
                         paper), (
            "Section II no longer claims the rate-to-flight law; if that is deliberate, "
            "retire the CLAIMS entry that guards it, and check the abstract still matches")

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
        """If Section V-C ever stops making it, this guard should be retired knowingly."""
        assert re.search(r"refutes every account in which the\s+negative-span rate is a "
                         r"function of utilization", paper), (
            "Section V-C no longer refutes utilization-only accounts; re-examine whether "
            "Equation 6 may carry p(rho) again")

    def test_the_main_text_says_why_p_is_not_a_function_of_rho(self, paper):
        """The clause that keeps a reader from thinking the paper contradicts itself."""
        assert re.search(r"\$p\$ and not \$p\(\\rho\)\$|not \$p\(\\rho\)\$", paper), (
            "Section V-B must say why p is written bare, or a reader who takes Equation 6 "
            "literally reads Table II as refuting it")
