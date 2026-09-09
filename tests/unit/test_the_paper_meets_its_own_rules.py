"""Every rule the paper applies to other people's numbers, applied to the paper's own.

Round 56's referee found the manuscript quoting a fitted power-law index, with a 95% interval
and the words "a finite variance", for a fit that this repository's own bootstrap rejects --
six lines after using that same bootstrap to justify withdrawing a different index. The test
existed, in the same module, and had never been pointed at the number. Round 55 had found the
recovery remedy quoted by its median and called a bound, which is the criticism the paper
makes of the exposure curve two sections earlier. Round 54 found two claims about named
artefacts standing without the citation the paper demands of others.

Three rounds, one shape: the paper failing a rule the paper wrote. So the referee asked for
one gate worth more than any single fix -- *run every test the paper applies to others against
every number the paper publishes* -- and this file is that gate. Each class below is a rule
stated in the manuscript, checked against the manuscript.

It is deliberately not merged into `test_paper_consistency.py`. That file asks whether a
number matches its artefact; this one asks whether a number is allowed to be stated at all.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"
SUPP = REPO / "supplement.tex"
LEDGER = REPO / "docs" / "generated" / "paper_numbers.tex"


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supp():
    return SUPP.read_text(encoding="utf-8") if SUPP.exists() else ""


@pytest.fixture(scope="module")
def package(paper, supp):
    return paper + "\n" + supp


@pytest.fixture(scope="module")
def ledger():
    """name -> value, for every generated macro."""
    text = LEDGER.read_text(encoding="utf-8")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}", text))


def _sentences(text):
    """Body sentences, comments stripped, one per element.

    Quoted spans go too. A claim inside ``...'' is a report of somebody's claim -- a
    source's, a maintainer's, or one of our own that a postmortem is withdrawing -- and the
    rules below are about what the manuscript asserts in its own voice. Without this the
    supplement cannot describe the sentence round 56 withdrew without tripping the gate that
    withdrew it.
    """
    text = re.sub(r"(?m)^\s*%.*$", " ", text)
    text = re.sub(r"\\(section|subsection|paragraph)\*?\{", " . ", text)
    text = re.sub(r"``.*?''", " ", text, flags=re.S)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


# --- Rule: a moment claim is a claim about an interval, not about a point estimate ---------

MOMENT = re.compile(r"finite (mean|variance)", re.I)

#: The Pareto survival exponent a moment needs. `binned_pareto_mle` fits
#: P(X > x) proportional to x**-alpha, so E[X**k] is finite exactly when alpha > k. A claim
#: about the mean needs one, a claim about the variance needs two.
MOMENT_BOUNDARY = {"mean": 1.0, "variance": 2.0}


class TestAMomentClaimMustClearTheIntervalItDependsOn:
    """"A finite variance" needs alpha > 2, and the interval ran 2.00--2.07.

    The point estimate cleared the boundary by 0.036 and the interval's lower limit sat on it,
    so the data did not separate a finite variance from an infinite one. The manuscript said
    "a finite variance" as a fact for eight rounds. Nothing checked it, because every gate
    about numbers checked the value and none checked what the sentence around it was allowed
    to conclude.
    """

    def test_no_moment_claim_rests_on_an_interval_that_crosses_its_boundary(self, package,
                                                                           ledger):
        offenders = []
        for sentence in _sentences(package):
            hit = MOMENT.search(sentence)
            if not hit:
                continue
            need = MOMENT_BOUNDARY[hit.group(1).lower()]
            for name in re.findall(r"\\(\w*CI)\b", sentence):
                raw = ledger.get(name, "")
                bounds = re.findall(r"-?\d+\.?\d*", raw.replace("$--$", " "))
                if len(bounds) != 2:
                    continue
                lo = float(bounds[0])
                if lo <= need:
                    offenders.append("%s: %s has lower limit %s against a boundary of %s"
                                     % (hit.group(0), name, lo, need))
        assert not offenders, "; ".join(offenders)

    def test_the_boundary_table_matches_the_estimator_it_describes(self):
        """The parameterisation is the whole content of the rule above.

        Read as a density exponent the boundaries would be 2 and 3; read as a survival
        exponent they are 1 and 2. This asserts which one the repository fits, so that a
        change of estimator cannot silently move the rule.
        """
        source = (REPO / "scripts" / "tail_index_traced.py").read_text(encoding="utf-8")
        assert "(a^-alpha - b^-alpha)" in source, \
            "the estimator no longer fits a survival exponent; MOMENT_BOUNDARY must move"


# --- Rule: publish the check's verdict, not only the number it judged ----------------------

class TestAFittedIndexTravelsWithItsGoodnessOfFit:
    """The paper's own rule, from Section VII-B: report the audit, not just the result.

    Round 56: `estimate()` computed a bootstrap goodness of fit for the 256--2048 microsecond
    window and for no other, so the tail index above 4 ms was published for eight rounds
    without ever being judged. When the test was finally pointed at it, it rejected.
    """

    def test_every_published_tail_index_has_a_goodness_of_fit_macro(self, package, ledger):
        for name in sorted(n for n in ledger if n.endswith("TailAlpha")):
            if ("\\" + name) not in package:
                continue
            verdict = name.replace("TailAlpha", "TailGofP")
            assert verdict in ledger, \
                "%s is published with no %s beside it" % (name, verdict)
            assert ("\\" + verdict) in package, \
                ("%s is published but %s never appears in the submission: the fit is quoted "
                 "and its verdict is not" % (name, verdict))

    def test_the_estimator_judges_every_window_it_fits(self):
        """The defect was one missing call inside `estimate`, so `estimate` is what is pinned.

        Counting over the whole module would count the definitions and the estimator's own
        internal fit; the question is narrower and exact: every window `estimate` fits, it
        must also judge.
        """
        source = (REPO / "scripts" / "tail_index_traced.py").read_text(encoding="utf-8")
        body = source.split("def estimate(")[1].split("\ndef ")[0]
        fits = body.count("binned_pareto_mle(")
        judged = body.count("gof_pvalue(")
        assert fits >= 2, "estimate() no longer fits two windows; this pin needs rewriting"
        assert judged >= fits, \
            ("estimate() fits %d windows and judges %d: a published fit is not tested"
             % (fits, judged))

    def test_a_rejected_fit_is_not_offered_as_a_finding(self, paper, ledger):
        """A rejected fit may be reported as withdrawn; it may not be reported as a result.

        The main text is where a number reads as established, so the rule is placement-
        sensitive: the supplement may state the withdrawn index, with its rejection, because
        that is the postmortem the supplement exists for.
        """
        p = ledger.get("tracedTailGofP", "")
        rejected = p.startswith("<") or (p and float(p.lstrip("<")) < 0.05)
        if not rejected:
            pytest.skip("the tail fit is no longer rejected; the prohibition does not apply")
        assert "\\tracedTailAlpha" not in paper, \
            ("the tail index is rejected at p=%s and the main text still prints it" % p)


# --- Rule: a derived constant is not a measurement -----------------------------------------

class TestADerivedConstantIsNotReportedAsAMeasurement:
    """Section VI-E is careful: the slice is "derived rather than measured".

    The introduction was not. It said "the last mode of the run-queue stall distribution sits
    at 3 ms" using `\\baseSliceMs`, the derived scheduler constant, for the position of a
    measured mode that the trace resolves only to a log2 bucket of 2--4 ms. Two quantities,
    one number, and the reader cannot tell which was measured.
    """

    def test_the_slice_macro_never_gives_a_measured_modes_position(self, package):
        offenders = []
        for sentence in _sentences(package):
            if "\\baseSliceMs" not in sentence:
                continue
            if not re.search(r"\bmode\b", sentence):
                continue
            # Naming the derivation in the same sentence is what makes it honest.
            if re.search(r"derived|base slice", sentence):
                continue
            offenders.append(sentence[:150])
        assert not offenders, \
            "a measured mode is positioned by the derived slice: " + " | ".join(offenders)

    def test_the_measured_mode_keeps_its_own_macros(self, package):
        for name in ("tracedModeLo", "tracedModeHi"):
            assert ("\\" + name) in package, \
                "%s is unused, so nothing states the bucket the mode was measured in" % name


# --- Rule: one name for one thing, symbols included ----------------------------------------

class TestADefinedSymbolKeepsItsOneMeaning:
    """`docs/writing_standards.md` forbids one word for two things. Symbols are worse.

    Section IV-B defines rho as utilization and the paper holds to it through Section VI-B,
    Table II and Section VII-D. Section VII-B then wrote "(rho = 0.84)" for a correlation
    between D and A -- the emitter calls it `spanRhoMedian` and computes it from `rho_DA` --
    so a reader met rho meaning two things three sections apart.
    """

    def test_rho_is_utilization_everywhere_it_appears(self, package):
        offenders = []
        for sentence in _sentences(package):
            if "\\rho" not in sentence:
                continue
            if re.search(r"correlat|coefficient|Spearman|Pearson", sentence, re.I):
                offenders.append(sentence[:150])
        assert not offenders, \
            "rho is the utilization; it is used for a correlation in: " + " | ".join(offenders)

    def test_the_correlation_keeps_a_name_that_is_not_a_symbol(self, package):
        assert "median correlation $\\spanRhoMedian$" in package, \
            "the D-A correlation must be named rather than given a symbol already in use"


# --- Rule: count your events before you quote a percentile ---------------------------------

class TestThePapersOwnPercentilesCarryTheirDenominators:
    """Section VII-B: "A median over as few as seven events per run is not a property of the
    system." Every percentile the paper quotes of its own corpus therefore names what it is
    over, in its own sentence or the one beside it.
    """

    def test_the_recovery_quartiles_name_their_populations(self, paper):
        for name in ("recoveryPassN", "recoveryFailN"):
            assert ("\\" + name) in paper, \
                "%s is not printed, so a quartile is quoted with no denominator" % name

    def test_the_exposure_curve_is_quoted_with_its_spread(self, paper):
        """Section VII-B tells the reader to know "how wide it is"; round 51 found the paper
        quoting the curve by its middle, which it calls "this paper's own mistake one level
        up"."""
        assert "\\exposureErrTenHi" in paper, \
            "the exposure error is quoted without the upper quartile that gives its width"
        assert "\\exposureCrossoverHi" in paper or "\\exposureLagHi" in paper, \
            "the crossover is quoted without the spread that moves it"


# --- Rule: a printed number keeps the significant figure it has -----------------------------

class TestAPrintedPercentageKeepsItsSignificantFigure:
    """`exposureErrHundred` printed 0.725% as "1" -- 38% high, in a paper about rounded
    numbers standing for unrounded ones. Formatting by magnitude is the fix; this pins it.
    """

    def test_no_emitted_percentage_below_one_prints_as_an_integer(self, ledger):
        offenders = []
        for name, value in sorted(ledger.items()):
            if not re.match(r"^-?\d+$", value.strip()):
                continue
            if "Err" not in name and "Pct" not in name:
                continue
            if value.strip() != "1":
                continue
            offenders.append(name)
        # A genuine 1% is legal; what is not is a value under one rounded up to it. The
        # emitter now formats by magnitude, so this asserts the formatter rather than
        # guessing at intent.
        source = (REPO / "scripts" / "emit_paper_numbers.py").read_text(encoding="utf-8")
        assert '("%.1f" if pct < 1.0 else "%.0f") % pct' in source, \
            ("the exposure formatter no longer widens below one; %s may be a rounded-up "
             "fraction" % ", ".join(offenders) if offenders else
             "the exposure formatter no longer widens below one")
