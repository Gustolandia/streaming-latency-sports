r"""A claim attributed to an outside document must name the document.

Round 54 found three sentences in the main text that describe a specific external artifact
and cite nothing:

    "...a 2026 comparison that calls two of three brokers sub-millisecond without naming a
     percentile cannot be placed against that resolution at all."
    "...skew adjusters that rewrite a span's timestamps are called harmful and default to
     off..."
    "None of this is hypothetical: a 2026 framework for the same comparisons already
     timestamps in nanoseconds and subtracts a span that cannot invert..."

Each is checkable, each is load-bearing -- the first two sit in Related Work, which the second
author required to be readable without the supplement -- and a reader who wanted to check any
of them had nowhere to go. The evidence existed in all three cases: the supplement had already
identified the objects and cited them. What failed was the transfer into a section whose
reference budget is capped, where the cheapest way to keep a sentence is to drop its citation.

That is the defect this file gates, and it is worth gating rather than fixing once because
the pressure that produced it is permanent: the paper is at the journal's 45-reference cap,
and the temptation at the cap is to allude rather than cite.

**Two shapes, both narrow on purpose.**

*Dated document.* Prose that dates an external document and gives its genre -- "a 2026
comparison", "a 2025 preprint", "a 1970 application note" -- is alluding to one specific
artifact. Naming the year is the tell: a reader who is told the year expects to be told which
one. This shape generalises, which is why it is here rather than as a pin on two sentences.

*Reported default.* Prose that reports what another project decided or ships as its default
-- "called harmful", "defaults to off" -- is quoting a decision made elsewhere. First person
is excluded: "we recommend" is this paper's own position, not a report of somebody else's.

The rule is scoped to `paper.tex`. The supplement's bibliography is uncapped, and it already
cites all three objects; it is the main text where the cap bites.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
PAPER = REPO / "paper.tex"

#: An allusion to a dated external document. The genre words are the ones a systems paper
#: actually uses for other people's work; the year is what makes it a specific artifact.
DATED = re.compile(
    r"\b(?:a|an|another|the)\s+(?:19|20)\d\d\s+"
    r"(?:comparison|framework|preprint|tutorial|guide|methodology|study|survey|report|"
    r"benchmark|paper|note|standard|specification|manual|harness|tool)\b", re.I)

#: A decision or default reported from another project. `(?<!we )` keeps the paper's own
#: recommendations out: those are claims it makes, not claims it is passing on.
REPORTED = re.compile(
    r"(?<!we )\b(?:called harmful|considered harmful|defaults? to off|"
    r"defaulted (?:it )?off)\b", re.I)

RULES = (("dated document", DATED), ("reported default", REPORTED))

#: What else counts as telling the reader which document is meant. The requirement is that
#: the artifact be *identifiable*, and a reference is not the only way to identify one: a
#: document with a unique public name -- RFC 1242, IEEE 1588, SPECjbb2015, OWAMP -- is
#: located by that name, and so is a tool the paper typesets as code. This is why dropping
#: `rfc1242` from the reference list in round 54 cost the reader nothing: the sentence still
#: says RFC 1242, which is the locator. An allusion by year and genre alone -- "a 2026
#: comparison" -- names nothing, and that is the case the rules above exist for.
NAMED_ARTIFACT = re.compile(
    r"\\texttt\{|\\brk\{|\bRFC~?\d+|\bIEEE~?\s?\d+|\bSPECjbb\w*|\bOWAMP\b|\bTPC-\w+")

#: A pointer into the submission's own supplement, where the bibliography is uncapped.
SUPPLEMENT_POINTER = re.compile(r"Supplements?~S\d+")


def _prose():
    """The main text's running prose: no comments, no floats, no bibliography."""
    text = PAPER.read_text(encoding="utf-8")
    body = text[text.index(r"\section{Introduction}"):text.index(r"\section*{Acknowledgment}")]
    body = re.sub(r"(?m)^%.*$", "", body)
    body = re.sub(r"\\begin\{(figure|table)\*?\}.*?\\end\{\1\*?\}", " ", body, flags=re.S)
    return body


def _sentences(body):
    return re.split(r"(?<=[.!?])\s+(?=[A-Z(\\])", body)


def _cited(sentence):
    """Strict: a reference in this very sentence. What Related Work is held to."""
    return bool(re.search(r"\\cite\{", sentence))


def _sourced(sentence):
    """Loose: the reader can identify the document -- by reference, public name, or pointer.

    Outside Related Work the paper may send a reader to its own supplement, which carries an
    uncapped bibliography; that is the idiom the Discussion uses throughout.
    """
    return (_cited(sentence)
            or bool(NAMED_ARTIFACT.search(sentence))
            or bool(SUPPLEMENT_POINTER.search(sentence)))


def attributions():
    """(rule name, sentence) for every sentence carrying one of the shapes above."""
    out = []
    for sentence in _sentences(_prose()):
        for name, rx in RULES:
            if rx.search(sentence):
                out.append((name, " ".join(sentence.split())))
    return out


class TestEveryAttributedClaimNamesItsSource:

    def test_there_are_attributions_to_check(self):
        """A parser that silently matched nothing would make the rule below vacuous."""
        got = attributions()
        assert got, "no attributed claims found; the extractor or the prose changed shape"

    @pytest.mark.parametrize("rule,sentence", attributions(),
                             ids=[s[:44] for _r, s in attributions()])
    def test_the_sentence_identifies_the_document(self, rule, sentence):
        assert _sourced(sentence), (
            "this sentence makes a %s claim about an outside artifact and neither cites it, "
            "names it, nor points at the supplement, so a reader cannot tell which document "
            "is meant: %r" % (rule, sentence[:200]))


class TestRelatedWorkCitesRatherThanPoints:
    """Related work must be self-contained: a source, not a forwarding address.

    The second author's annotation 12 removed the supplement pointers from this section. The
    risk that creates is the one above -- a claim with nowhere to go -- so the two rules are
    kept together: no pointers, and therefore every attributed claim carries a reference.
    """

    def _related_work(self):
        body = _prose()
        start = body.index(r"\section{Background and Related Work}")
        end = body.index(r"\section{Experimental Setup}")
        return body[start:end]

    def test_related_work_has_no_supplement_pointers(self):
        pointers = re.findall(r"Supplements?~S\d+", self._related_work())
        assert not pointers, (
            "Related Work points at the supplement (%s); it must be readable on its own, so "
            "the source belongs in the reference list" % ", ".join(sorted(set(pointers))))

    def test_related_work_attributions_are_cited(self):
        section = self._related_work()
        bad = []
        for sentence in _sentences(section):
            for name, rx in RULES:
                if rx.search(sentence) and not _cited(sentence):
                    bad.append("%s: %s" % (name, " ".join(sentence.split())[:120]))
        assert not bad, "uncited attributed claims in Related Work:\n  " + "\n  ".join(bad)


class TestTheLiteratureRegistryAndTheProseAgree:
    """The count in Section III-A is emitted from a registry; the registry must be real.

    `docs/results/external/literature_regime.csv` is the list of published comparisons the
    paper placed against the timestamp resolution, and `literature_macros()` counts it. The
    risk of counting a list nobody checks is that the list drifts from the submission: a row
    for a document neither document cites would inflate the denominator silently.
    """

    REGISTRY = REPO / "docs" / "results" / "external" / "literature_regime.csv"

    def _rows(self):
        import csv
        if not self.REGISTRY.is_file():
            pytest.skip("literature registry not present")
        with self.REGISTRY.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def _surface(self):
        return "\n".join((REPO / n).read_text(encoding="utf-8")
                         for n in ("paper.tex", "supplement.tex"))

    def test_every_row_is_a_document_the_submission_cites(self):
        surface = self._surface()
        missing = [r["citation_key"] for r in self._rows()
                   if ("\\cite{%s}" % r["citation_key"]) not in surface
                   and r["citation_key"] not in surface]
        assert not missing, (
            "the registry counts documents the submission never cites: %s" % missing)

    def test_the_counted_rows_are_broker_comparisons(self):
        """A methodology examined for another reason must not swell the denominator."""
        kinds = {r["kind"] for r in self._rows()}
        assert "broker_comparison" in kinds, "nothing left to count"
        counted = [r for r in self._rows() if r["kind"] == "broker_comparison"]
        for r in counted:
            assert r["figures_inside_regime"] in ("yes", "no"), (
                "a counted comparison must be placed against the resolution, and %r is %r"
                % (r["citation_key"], r["figures_inside_regime"]))

    def test_the_paper_uses_the_emitted_count_rather_than_a_typed_one(self):
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        assert r"\litComparisonsWord" in paper and r"\litInsideRegimeWord" in paper, (
            "Section III-A should read its count from the registry; a typed number drifts "
            "from the list it summarises")


class TestTheRuleWouldHaveCaughtTheDefect:
    """Each shape is asserted to fire on the round-54 sentence it was written for."""

    def test_a_dated_comparison_without_a_source_is_caught(self):
        s = ("Not all do, and a 2026 comparison that calls two of three brokers "
             "sub-millisecond without naming a percentile cannot be placed against that "
             "resolution at all.")
        assert DATED.search(s) and not _sourced(s)

    def test_a_dated_framework_without_a_source_is_caught(self):
        s = ("None of this is hypothetical: a 2026 framework for the same comparisons "
             "already timestamps in nanoseconds.")
        assert DATED.search(s) and not _sourced(s)

    def test_a_reported_default_without_a_source_is_caught(self):
        s = ("skew adjusters that rewrite a span's timestamps are called harmful and "
             "default to off.")
        assert REPORTED.search(s) and not _sourced(s)

    def test_the_same_sentences_pass_once_cited(self):
        s = (r"a 2026 comparison that calls two of three brokers sub-millisecond"
             r"~\cite{indexdev2026brokers} cannot be placed against that resolution.")
        assert DATED.search(s) and _cited(s)

    def test_naming_the_artifact_is_enough_outside_related_work(self):
        r"""The Discussion may name a tool and send the reader to the supplement for it."""
        s = (r"None of this is hypothetical: \brk{mq-bench}, a 2026 framework for the same "
             r"comparisons, already timestamps in nanoseconds (Supplement~S52.2).")
        assert DATED.search(s) and _sourced(s) and not _cited(s)

    def test_a_numbered_standard_locates_itself(self):
        """Why round 54 could drop `rfc1242` from the list without stranding the sentence."""
        s = "It is not RFC~1242's negative latency, a cut-through forwarding artifact."
        assert _sourced(s) and not _cited(s)

    def test_the_papers_own_recommendation_is_not_a_reported_default(self):
        """First person is the paper speaking, and it needs no source for its own advice."""
        s = ("That is why we recommend publishing a retention rate rather than calling any "
             "published number wrong.")
        assert not REPORTED.search(s)

    def test_an_ordinary_sentence_is_untouched(self):
        s = "The acknowledgment lag exceeds half the delivery time on most events."
        assert not DATED.search(s) and not REPORTED.search(s)
