"""The writing standards of docs/writing_standards.md, held by tests.

Adopted 2026-09-08 from the second author's sequential pass, which declined to back a journal
submission of v3.0.0 on presentation alone: paper-specific vocabulary before definition, the
order the work happened in rather than the order a reader needs, and a main text that leans on
its supplement. Each rule marked GATED there gets a test here. Every test was demonstrated
failing on the sentence that motivated it before that sentence was repaired; the docstrings
say which.

The vocabulary rules are not taste. They are held against the field: the corpus table in
docs/generated/corpus_vocabulary.json is built from the Transactions on Computers papers and
their neighbours in docs/reference_tc and docs/reference_corpus, and the test that guards a
word reads the field's count of that word before it objects to ours.
"""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
PAPER = REPO / "paper.tex"
TABLE = REPO / "docs" / "generated" / "corpus_vocabulary.json"


def _prose(tex):
    """The manuscript as a reader meets it: comments, math and macro names stripped, but the
    text of captions kept, because a caption is prose."""
    t = re.sub(r"(?m)^%.*$", "", tex)
    t = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", " [eq] ", t, flags=re.S)
    t = re.sub(r"\$[^$]*\$", " [m] ", t)
    t = re.sub(r"\\(?:cite|ref|label|eqref|href|url|includegraphics|input|bibliography"
               r"|bibliographystyle|brk|texttt|textsc)\{[^}]*\}", " ", t)
    return t


def _body(tex):
    return tex.split(r"\begin{document}", 1)[-1].split(r"\begin{IEEEbiographynophoto}", 1)[0]


def _lines_with(pattern, text, flags=0):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if re.search(pattern, line, flags):
            out.append("%d: %s" % (i, line.strip()[:110]))
    return out


@pytest.fixture(scope="module")
def paper():
    return PAPER.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def prose(paper):
    return _prose(_body(paper))


@pytest.fixture(scope="module")
def table():
    if not TABLE.exists():
        pytest.skip("corpus table not built; run scripts/build_vocabulary_table.py")
    return json.loads(TABLE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- A. vocabulary


class TestTheFieldsWordForATimestamp:
    """A1. Bare `stamp` occurs in none of the corpus papers; `timestamp` is the word.

    First failure: 65 bare uses in the paper, from "both stamps are written by threads" in
    the abstract onward.
    """

    #: "Time Stamp Counter" is the register's proper name and the expansion rule A9 asks
    #: for; it is the one place the bare word is right.
    BARE = r"(?<!Time )(?<![A-Za-z\\-])[Ss]tamp(?:s|ed|ing)?\b(?![-_])(?! Counter)"

    def test_the_corpus_backs_the_rule(self, table):
        p = table["phrases"]
        assert p["timestamp"]["papers"] >= 2 * max(1, p["stamp (bare)"]["papers"]), (
            "the field's usage no longer supports this rule; re-examine before enforcing")

    def test_no_bare_stamp_in_prose(self, prose):
        hits = _lines_with(self.BARE, prose)
        assert not hits, "bare 'stamp' (use timestamp / timestamping):\n  " + "\n  ".join(hits)


class TestNoCoinedNounForTheInterval:
    """A2. `flight` appears in the corpus only inside `in-flight`. First failure: the
    definition sentence itself, "A flight, here and throughout, is that one span"."""

    def test_the_corpus_backs_the_rule(self, table):
        # On 45 papers the count was exactly zero; on four hundred it is a few per cent,
        # from time-of-flight sensing and aviation workloads, never as a name for a measured
        # interval. The rule is that the field does not use the word the way we did.
        p = table["phrases"]["flight (bare)"]
        assert p["share"] < 0.10, "bare 'flight' is in %d%% of corpus papers" % (100 * p["share"])

    def test_no_flight(self, prose):
        hits = _lines_with(r"(?<!in-)(?<!in )\b[Ff]lights?\b", prose)
        assert not hits, "'flight' is ours alone:\n  " + "\n  ".join(hits)


class TestTheInstrumentIsNamed:
    """A3. `the instrument` as a noun for the measuring apparatus: 1 corpus paper. Name the
    quantity -- timestamp resolution, timestamping delay, the benchmark tool. First failure:
    "instrument timescale" in the abstract's first sentence."""

    NOUN = r"\b(?:the|an|our|its|this|that|whatever) instrument\b|\binstrument timescale\b|\binstrument'?s\b"

    def test_no_instrument_noun(self, prose):
        hits = _lines_with(self.NOUN, prose)
        assert not hits, "'instrument' as the apparatus; name the quantity:\n  " + "\n  ".join(hits)


class TestExperimentalVocabularyIsDefinedBeforeUse:
    """A5. run, replicate, cell, arm, condition: one paragraph defines them, marked
    \\label{def:vocabulary}, and none of the five appears in the body before it.

    First failure: "cell" at "75 instrumented cells" in Section IV, with no definition
    anywhere; "arm" in the Contributions; "condition" in the consistency check.
    """

    #: "run" is defined in the same paragraph but not held to the before-use rule: it is
    #: the field's universal word (84% of corpus papers) and an ordinary English verb --
    #: processes run on a host, a callback runs -- so a gate on it would fire on grammar.
    TERMS = ("replicate", "cell", "arm", "condition")
    DEFINED = TERMS + ("run",)

    def test_the_definition_paragraph_exists(self, paper):
        assert r"\label{def:vocabulary}" in paper, "no paragraph defines the experimental vocabulary"
        body = _body(paper)
        start = body.index(r"\label{def:vocabulary}")
        paragraph = body[start:start + 1500]
        missing = [t for t in self.DEFINED if not re.search(r"\\emph\{%ss?\}" % t, paragraph)
                   and t != "arm"]
        assert not missing, "the terms paragraph does not define: %s" % missing

    def test_no_term_precedes_its_definition(self, paper):
        body = _body(paper)
        anchor = body.index(r"\label{def:vocabulary}")
        before = _prose(body[:anchor])
        # The abstract is allowed to use the words a reader can parse unaided; the rule
        # bites from the introduction on.
        before = before.split(r"\section{Introduction}", 1)[-1]
        bad = []
        for term in self.TERMS:
            for hit in _lines_with(r"\b%ss?\b" % term, before, re.I):
                bad.append("%s -> %s" % (term, hit))
        assert not bad, "used before \\label{def:vocabulary}:\n  " + "\n  ".join(bad)


class TestSymbolsAreDefinedBeforeUse:
    """A7. Every symbol has a \\label{def:<name>} on its defining sentence, earlier than its
    first use. First failure: T_true in the introduction, defined nowhere; C_0 at "C_0 ~
    \\invFloor" with no definition; k=6 in a table caption before any text says what k is."""

    SYMBOLS = {
        "ttrue": r"T_\{?\\mathrm\{true\}|T_\{true\}",
        "czero": r"C_0\b",
        "rho": r"\\rho\b",
        "kcores": r"\bk\s*\{?=\}?\s*6\b|\$k\$",
        # v4.1 (2026-09-08): the co-author's confusion point -- "scheduling delay" (the
        # timestamping thread's wait for a core) beside the TTI term once called "scheduling
        # lag" (the send call's lateness). The term is defined where it first appears and
        # the TTI term is now the "send lag".
        "scheddelay": r"[Ss]cheduling delay",
    }

    @pytest.mark.parametrize("name", sorted(SYMBOLS))
    def test_defined_before_first_use(self, paper, name):
        body = _body(paper)
        anchor = body.find(r"\label{def:%s}" % name)
        first = re.search(self.SYMBOLS[name], body)
        if first is None:
            pytest.skip("%s no longer used" % name)
        assert anchor != -1, "no \\label{def:%s} marks where %s is defined" % (name, name)
        assert anchor <= first.start() + 400, (
            "%s is used at offset %d before its definition at %d" % (name, first.start(), anchor))


class TestAcronymsAreExpandedOnFirstUse:
    """A9. First failure: TSC, never expanded."""

    KNOWN = {"IEEE", "ACM", "SPEC", "TPC", "TCP", "UDP", "NIC", "CPU", "JVM", "PTP", "LAN",
             "DAG", "NIST", "RFC", "TTI", "TOST", "CI", "IQR", "IPPM", "OWAMP", "YCSB", "HP",
             "CFS", "EEVDF", "KVM", "VM", "API", "OS", "IO", "GNU", "MIT", "DOI", "URL",
             "PDF", "CSV", "JSON", "SHA", "GB", "MB", "KB", "MSC", "CC", "BY", "NC", "SA",
             "E-A", "E-B", "E-C", "FIFO", "USA"}

    def test_every_acronym_is_expanded_once(self, prose):
        seen = {}
        for m in re.finditer(r"\b([A-Z]{3,})\b", prose):
            seen.setdefault(m.group(1), m.start())
        bad = []
        for acro, pos in seen.items():
            if acro in self.KNOWN or acro.isdigit():
                continue
            window = prose[max(0, pos - 120): pos + 120]
            if not re.search(r"\(%s\)" % acro, window):
                bad.append(acro)
        assert not bad, "acronyms never expanded: %s" % sorted(bad)


# ---------------------------------------------------------------- B. structure


class TestNoForwardPointerStandsInForADefinition:
    """B7. A sentence whose content is only a pointer to a later section or the supplement.
    First failure: "Section VI-B is the rule list the two failures produce."."""

    POINTER_ONLY = re.compile(
        r"(?:^|[.!?]\s+)(?:Section|Supplement)~?\\?[A-Za-z{}:_]*\s+(?:is|has|gives|holds|contains)"
        r" [^.]{0,60}\.", re.M)

    def test_no_pointer_only_sentences(self, paper):
        body = _body(paper)
        body = re.sub(r"(?m)^%.*$", "", body)
        hits = [m.group(0).strip()[:100] for m in self.POINTER_ONLY.finditer(body)]
        assert not hits, "sentences that only point:\n  " + "\n  ".join(hits)


class TestRelatedWorkIsSelfContained:
    """B4. No supplement pointer inside Background and Related Work. First failure:
    "Supplement~S52.3 sizes that literature"."""

    def test_no_supplement_pointer_in_related_work(self, paper):
        body = _body(paper)
        start = body.index(r"\section{Background and Related Work}")
        end = body.index(r"\section{", start + 10)
        section = re.sub(r"(?m)^%.*$", "", body[start:end])
        hits = _lines_with(r"Supplement~?S\d", section)
        assert not hits, "related work leans on the supplement:\n  " + "\n  ".join(hits)


class TestHeadlineNumbersAppearInResultsFirst:
    """B8. Every emitted number the Discussion quotes must already appear in a Results
    section. First failure: \\reportedFraction, \\understateFactor and
    \\gapDistortionPaired -- the 24% / 4.2x / 1.7x distortion -- first seen in Discussion."""

    #: The rules for benchmark authors are where a result was being revealed for the first
    #: time; that subsection is the one held. "What the brokers actually do" reports a
    #: measurement in its own right, and Threats quantifies threats -- neither is a rule
    #: smuggling a result, and both keep their numbers.
    def test_discussion_numbers_are_results_numbers(self, paper):
        body = re.sub(r"(?m)^%.*$", "", _body(paper))
        disc = body.index(r"\section{Discussion}")
        rules = body.index(r"\subsection{For benchmark authors}")
        after = body.index(r"\subsection{", rules + 10)
        results = body[:disc]
        discussion = body[rules:after]
        macros = set(re.findall(r"\\([a-zA-Z]+(?:Lo|Hi|Pct|Factor|Fraction|Paired|Median|Err\w*|Crossover\w*|Gap\w*))\b",
                                discussion))
        missing = sorted(m for m in macros if ("\\" + m) not in results)
        assert not missing, "first revealed in Discussion: %s" % missing


# ---------------------------------------------------------------- C. register


class TestNoJokesInAJournalPaper:
    """C1. First failures: "Houdini at least took a bow" and "That is either a Nobel Prize
    or a scheduling artifact"."""

    BANNED = ("Houdini", "Nobel Prize", "we regret to report", "took a bow",
              "invented a time zone")

    def test_banned_phrases_absent(self, prose):
        hits = [p for p in self.BANNED if p in prose]
        assert not hits, "remove: %s" % hits


class TestNoMetaCommentary:
    """C2. First failures: "the model that says so is two equations long"; "one number that
    governs both"; "The claim that measurement can dominate"."""

    BANNED = (r"two equations long", r"one number that governs", r"\bThe claim that\b",
              r"That is the scope of our claim", r"in a 2026 preprint", r"In a 2026 preprint")

    def test_meta_phrases_absent(self, prose):
        hits = [p for p in self.BANNED if re.search(p, prose)]
        assert not hits, "meta-commentary: %s" % hits


class TestTheFailureIsDescribedPrecisely:
    """C5. A timestamp is not "untrustworthy"; negativity is not a "physical-impossibility
    criterion" and does not "prove something is wrong". First failures: all three phrases."""

    BANNED = (r"untrustworth", r"physical.impossibility", r"proves something is wrong",
              r"impossible physics")

    def test_dramatic_phrases_absent(self, prose):
        hits = [p for p in self.BANNED if re.search(p, prose)]
        assert not hits, "imprecise description of negativity: %s" % hits


class TestAnIdentityIsNotDressedAsAModel:
    """C6. S = D - A is exact, so S<0 iff A>D is an equivalence, not a probability statement.
    First failure: Equation 3, Pr[S<0] = Pr[A>D]."""

    def test_no_probability_notation_on_the_identity(self, paper):
        assert not re.search(r"\\Pr\[S\s*<\s*0\]\s*(?:\\;)?=\s*(?:\\;)?\\Pr\[A\s*>\s*D\]", paper)


# ---------------------------------------------------------------- the table itself


class TestTheCorpusIsLargeEnoughToArgueFrom:
    """A vocabulary rule read off ten papers is an anecdote. The user's instruction was to
    get a lot of papers from the journal and its neighbours before correcting anything."""

    def test_corpus_size(self, table):
        assert table["corpus_papers"] >= 150, (
            "corpus has %d papers; fetch more before treating its counts as the field"
            % table["corpus_papers"])
