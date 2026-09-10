"""A count macro can be correct and still be the wrong one for its sentence.

Round 62 found Section VIII-D conceding that "the five tools of Section VII are readings of
source rather than measured deployments". Ten tools were read at source; five of them dispose
silently. `\\harnessSilentWord` was standing where `\\harnessAuditedWord` belonged.

**Every gate in this project was structurally blind to it.** `test_ledger_coverage` catches a
typed literal that duplicates a macro -- nothing was typed. `test_emit_paper_numbers` checks
each macro carries the number it names -- both did. `test_rendered_prose` checks every emitted
macro is read somewhere -- both were. Nothing was stale, nothing disagreed, and the sentence
was still false. What was wrong was the *pairing* of a macro with the population its sentence
describes, and no gate had ever looked at that.

This is that gate, in the only form that can work: an inventory, maintained by hand, of what
each count macro counts and the words a sentence must carry to be allowed to use it. Same
shape as `ATTRIBUTED` in `test_pointer_sense.py`, and for the same reason -- judging whether a
number fits a sentence is not something a regular expression does on its own.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent


def _flat(name):
    text = (REPO / name).read_text(encoding="utf-8")
    text = re.sub(r"(?m)(?<!\\)%.*$", " ", text)
    return " ".join(text.split())


@pytest.fixture(scope="module")
def paper():
    return _flat("paper.tex")


@pytest.fixture(scope="module")
def supplement():
    return _flat("supplement.tex")


#: macro -> what it counts, and the words that must follow it inside its own sentence.
#:
#: The test is on what comes *after* the macro, not on the whole sentence. One sentence
#: legitimately uses both harness counts --- "reads ten tools at source and finds five
#: disposing" --- so a whole-sentence rule cannot separate them, and the first draft of this
#: gate failed on exactly that. What a count quantifies is named immediately to its right.
COUNTS = {
    "harnessAuditedWord": {
        "counts": "every tool the audit read at source",
        "require": ("tool", "dispose"),
    },
    "harnessSilentWord": {
        "counts": "the tools that dispose of a sample without counting it",
        "require": ("dispos", "counting", "silent"),
    },
    "harnessSilentIndependentWord": {
        "counts": "the silent tools other than the audited subject itself",
        "require": ("independent",),
    },
    "harnessCountingWord": {
        "counts": "the tool that exposes its discards",
        "require": ("counts", "discard"),
    },
}


def _uses(text, macro):
    """The remainder of the sentence after each use of `macro`.

    A count names its population to its right: "ten tools", "five disposing". What stands to
    its left is the sentence's subject, which is why the whole sentence cannot decide this.
    """
    out = []
    for m in re.finditer(r"\\" + macro + r"\{\}", text):
        end = text.find(". ", m.end())
        out.append(text[m.end():end if end > 0 else len(text)])
    return out


class TestACountMacroMatchesTheSentenceItStandsIn:
    """The inventory above, checked on every build."""

    @pytest.mark.parametrize("macro", sorted(COUNTS))
    def test_every_use_names_the_population_it_counts(self, macro, paper):
        rule = COUNTS[macro]
        bad = [tail[:130] for tail in _uses(paper, macro)
               if not any(w in tail.lower() for w in rule["require"])]
        assert not bad, (
            "\\%s counts %s, and stands before text naming something else. Expected one of "
            "%s to its right: %s" % (macro, rule["counts"], rule["require"], bad))

    @pytest.mark.parametrize("macro", sorted(COUNTS))
    def test_the_macro_is_actually_used(self, macro, paper):
        """An inventory row for a macro nobody uses is a row that tests nothing."""
        assert _uses(paper, macro), \
            "\\%s is inventoried but the article does not use it" % macro

    def test_round_62s_own_defect_is_pinned(self, paper):
        """The Threats concession covers every tool that was read, not the subset."""
        i = paper.find("are readings of source rather than measured deployments")
        assert i > 0, "the source-reading concession has gone from Threats"
        window = paper[max(0, i - 200):i]
        assert r"\harnessAuditedWord" in window, (
            "Threats concedes over the wrong population again. All ten tools are source "
            "readings; five is the subset that disposes silently, and conceding over five "
            "claims more than the audit supports.")
        assert r"\harnessSilentWord" not in window


class TestEveryResultSectionBelongsToAContribution:
    """Section VII was a full section of the paper that no contribution claimed.

    The abstract names three instruments -- an identity, a manipulation and an audit of ten
    tools -- and the third mapped to nothing. Structural sections do not need a contribution;
    sections that carry results do, or the contribution list is not a list of the paper.
    """

    #: Sections whose job is to set up rather than to establish.
    STRUCTURAL = {"sec:intro", "sec:sysmodel", "sec:related", "sec:method",
                  "sec:discussion", "sec:conclusion"}

    def test_each_result_section_is_named_by_a_contribution(self, paper):
        block = paper[paper.index("Contributions"):]
        block = block[:block.index(r"\section{")]
        claimed = set(re.findall(r"\\ref\{(sec:[a-zA-Z_]+)\}", block))
        labels = set(re.findall(r"\\label\{(sec:[a-zA-Z_]+)\}", paper))
        results = labels - self.STRUCTURAL
        # Subsections carry their own labels; only the ones a \section owns are in scope.
        owned = set()
        for m in re.finditer(r"\\section\{[^}]*\}\s*(\\label\{(sec:[a-zA-Z_]+)\})", paper):
            owned.add(m.group(2))
        unclaimed = sorted((results & owned) - claimed)
        assert not unclaimed, (
            "result section(s) that no contribution claims: %s. The contribution list is the "
            "paper's own account of what it establishes; a results section outside it is "
            "either unclaimed work or a section that should not be a section." % unclaimed)

    def test_the_tools_section_is_claimed(self, paper):
        """Pinned by name, because it is the one round 62 found unclaimed."""
        block = paper[paper.index("Contributions"):]
        block = block[:block.index(r"\section{")]
        assert "sec:tools" in block, \
            "Section VII is unclaimed again; Contribution 2 is where its generality belongs"


class TestAReferenceNoteSaysWhatOnlyItCanSay:
    """[11]'s note restated the sentence that cites it before adding its own disclosure."""

    def test_the_practitioner_note_does_not_restate_the_body(self):
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        entry = bib[bib.index("@misc{indexdev2026brokers"):]
        entry = entry[:entry.index("\n}")]
        assert "sub-10ms latency at p99" not in entry, (
            "[11]'s note quotes the percentile again. Section III-A already says a 2026 "
            "comparison names a percentile for one broker and gives the others only "
            "'sub-millisecond'; the note's job is what the body cannot fit.")
        for kept in ("retained fraction", "timestamp resolution", "S1"):
            assert kept in entry, (
                "[11]'s note lost %r, which is what only the note can say" % kept)



class TestTheFramingClaimArguesFromLimitsAndNotFromSlopes:
    r"""A gate that tests vocabulary cannot test reasoning, and round 63 proved it.

    Section I claims the two failure modes "act differently", which is what stops a reader
    rebuilding the shared-number framing a co-author removed. S16 proves it. Round 62 wrote
    two proofs and a gate asserting that neither used the payload sweep's log--log slope,
    which S15 withdraws --- and the gate looked for the strings `tailExponent`, `tailSlope`
    and `0.339`. It passed. The first proof was that slope:

        log(4.089) / log(76.885) = 0.3243     against the withdrawn OLS fit of 0.3387

    **Comparing one response factor against another over a shared range is an exponent
    estimate.** That is what the ratio of their logs means, and no rewording changes it. The
    string check could not see it because the argument never spelled the word.

    So this gate tests the shape of the argument instead. The transport rise and the rate
    fall may not appear together in the demonstration, because their co-appearance *is* the
    fit; and the demonstration must argue from what the two failures cannot do --- one has an
    exit, the other has a floor --- which involves no rate of change at all.
    """

    #: Quoting both of these over the payload sweep is an exponent estimate, whatever the
    #: surrounding prose calls it. Round 63's defect in one line.
    RATE_PAIR = (r"\payloadTransportFactor", r"\payloadRateFall")

    #: What the surviving argument rests on: a ceiling that is reached and a floor that is not.
    LIMITS = (r"\ombEscapeCellsWord", r"\invFloor", r"\invCeiling")

    def _demonstration(self, supplement):
        i = supplement.find("not one failure seen twice")
        assert i > 0, "S16 no longer demonstrates that the two failures differ"
        return supplement[i:i + 2200]

    def test_it_does_not_pair_a_rise_factor_with_a_fall_factor(self, supplement):
        body = self._demonstration(supplement)
        present = [m for m in self.RATE_PAIR if m in body]
        assert len(present) < 2, (
            "the demonstration quotes both %s over the payload sweep. The ratio of their "
            "logs is an exponent -- 0.324 against the 0.339 that S15 withdraws -- so this is "
            "the withdrawn fit however the sentence describes itself." % (present,))

    def test_it_argues_from_limits(self, supplement):
        body = self._demonstration(supplement)
        missing = [m for m in self.LIMITS if m not in body]
        assert not missing, (
            "the limits argument has lost %s. It is the demonstration that survives: one "
            "failure saturates and switches off, the other has a floor it never crosses, and "
            "neither fact is a rate of change." % missing)

    def test_the_claim_points_at_its_proof(self, paper):
        i = paper.find("act differently")
        assert i > 0, "Section I no longer says the two failures act differently"
        window = paper[i:i + 260]
        assert "S16" in window, (
            "the framing claim has lost its pointer. It denies a framing a co-author removed, "
            "so it may not stand on assertion.")

    def test_the_claim_does_not_quote_a_ratio(self, paper):
        """Section I carried the 19x with the paragraph, and goes with it."""
        i = paper.find("act differently")
        window = paper[i:i + 260]
        assert r"\payloadAsymmetry" not in window, \
            "Section I quotes the asymmetry ratio again; it is the withdrawn fit"

    def test_the_ratio_is_not_emitted_at_all(self):
        """Not merely unread: removed, so it cannot be quoted by a later edit."""
        gen = (REPO / "docs" / "generated" / "paper_numbers.tex").read_text(encoding="utf-8")
        assert "payloadAsymmetry" not in gen, (
            "the asymmetry ratio is emitted again. It is the transport rise over the rate "
            "fall, which is the exponent S15 withdrew; leaving it in the ledger invites the "
            "argument back.")

    def test_the_reason_is_recorded_where_it_would_be_rewritten(self):
        """The emitter says why the macro is absent, so the next edit does not restore it."""
        src = (REPO / "scripts" / "emit_paper_numbers.py").read_text(encoding="utf-8")
        i = src.find("No `payloadAsymmetry` here")
        assert i > 0, "the emitter no longer records why the ratio is not emitted"
        assert "0.3243" in src[i:i + 700] and "0.3387" in src[i:i + 700],             "the record no longer shows the two numbers that make it the same quantity"
