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

    5 Oct 2026: the rebuilt paper has no Terms subsection, and the supplement's glossary
    defines its words for the supplement alone. The paper still says *condition*, *run* and
    *replicate*, so the paragraph is still owed; it must define the words the paper uses, and
    *cell* and *arm* are no longer among them.
    """

    #: "run" is defined in the same paragraph but not held to the before-use rule: it is
    #: the field's universal word (84% of corpus papers) and an ordinary English verb --
    #: processes run on a host, a callback runs -- so a gate on it would fire on grammar.
    TERMS = ("replicate", "cell", "arm", "condition")
    DEFINED = TERMS + ("run",)

    @staticmethod
    def _used(paper, term):
        """Whether the body, from the introduction on, uses the word at all."""
        reader = _prose(_body(paper)).split(r"\section{Introduction}", 1)[-1]
        return bool(re.search(r"\b%ss?\b" % term, reader, re.I))

    @staticmethod
    def _paragraph_at(body, at):
        """The paragraph, blank line to blank line, that holds offset `at`."""
        start = body.rfind("\n\n", 0, at)
        end = body.find("\n\n", at)
        return body[start + 2 if start != -1 else 0:end if end != -1 else len(body)]

    def test_the_definition_paragraph_exists(self, paper):
        assert r"\label{def:vocabulary}" in paper, "no paragraph defines the experimental vocabulary"
        body = _body(paper)
        paragraph = self._paragraph_at(body, body.index(r"\label{def:vocabulary}"))
        missing = [t for t in self.DEFINED if t != "arm" and self._used(paper, t)
                   and not re.search(r"\\emph\{%ss?\}" % t, paragraph)]
        assert not missing, "the terms paragraph does not define: %s" % missing

    def test_no_term_precedes_its_definition(self, paper):
        body = _body(paper)
        assert r"\label{def:vocabulary}" in body, (
            "no paragraph defines the experimental vocabulary, so every use of %s is a use "
            "before definition" % (self.TERMS,))
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


class TestTheBibliographyObeysTheVocabularyToo:
    r"""The notes print, so they are prose the reader sees.

    Round 55 found `mqbench2026` carrying "nanosecond send stamps" in its note field. A
    `note` is typeset into the reference list, so the retired word was printing in the
    supplement's bibliography while every rule that could have caught it looked at `.tex`
    sources and at figures. The `.bib` is the third surface, and the only one left.

    Titles are exempt: a reference reproduces the title its author gave it, and correcting
    someone else's title would be a misquotation. The rule is on the fields this project
    writes -- `note` and `howpublished`.
    """

    OURS = re.compile(r"^\s*(?:note|howpublished)\s*=\s*", re.I)
    BARE_STAMP = re.compile(
        r"(?<!Time )(?<![A-Za-z\-])[Ss]tamp(?:s|ed|ing)?\b(?![-_])(?! Counter)")

    def _our_fields(self):
        """(line number, text) for every note/howpublished value, brace-continuations joined."""
        text = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        out, lines = [], text.splitlines()
        for i, line in enumerate(lines, 1):
            if not self.OURS.match(line):
                continue
            chunk, depth, k = line, line.count("{") - line.count("}"), i
            while depth > 0 and k < len(lines):
                chunk += " " + lines[k]
                depth += lines[k].count("{") - lines[k].count("}")
                k += 1
            out.append((i, chunk))
        return out

    def test_there_are_fields_to_check(self):
        assert len(self._our_fields()) > 40, "the bibliography's own notes should be many"

    def test_no_note_says_stamp_where_the_documents_say_timestamp(self):
        bad = ["line %d: %r" % (n, self.BARE_STAMP.search(t).group(0))
               for n, t in self._our_fields() if self.BARE_STAMP.search(t)]
        assert not bad, (
            "the reference list prints these notes, so the retired word reaches the reader "
            "through them: %s" % bad)

    def test_the_rule_would_catch_the_defect_it_was_written_for(self):
        assert self.BARE_STAMP.search("Introduces mq-bench: nanosecond send stamps, one host")
        assert not self.BARE_STAMP.search("nanosecond send timestamps, one host")


class TestOneNameForTheSendLag:
    r"""The first term of the TTI decomposition has one name across the submission.

    v4.1 renamed $t_{\mathrm{send}} - t_{\mathrm{sched}}$ from *scheduling lag* to *send
    lag*, because the paper had just defined *scheduling delay* for something else -- the
    wait a timestamping thread serves before a core runs it -- and two quantities a page
    apart were sharing a word. The rename reached the paper and its figures. It did not
    reach the supplement, which went on calling the same term *scheduling lag* in nine
    places, nor the E1 figure, whose bars were labelled *sched. lag*.

    So the collision the rename removed from one document survived in the other, which is
    worse than not renaming at all: a reader who moves between them meets *scheduling delay*
    and *scheduling lag* naming different things.
    """

    def test_neither_document_calls_the_send_lag_a_scheduling_lag(self):
        bad = []
        for name in ("paper.tex", "supplement.tex", "postmortem.tex"):
            text = (REPO / name).read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("%"):
                    continue          # the revision record may name what it retired
                if "scheduling lag" in line:
                    bad.append("%s:%d" % (name, line_no))
        assert not bad, (
            "'scheduling lag' survives at %s; the term is the publish delay, and 'scheduling "
            "delay' is the thread's wait for a core" % ", ".join(bad))

    def test_the_send_lag_is_what_the_documents_do_say(self):
        """The rename has to have landed, not merely have been deleted.

        Since the 5 Oct 2026 rebuild the paper no longer names the publish delay at all: its
        model is t_pub, t_ack and t_recv, and the sign check's three spans, the publish delay
        among them, are listed in Supplement S2. So the rename is held in the two documents
        that still name the quantity, and the paper keeps the other term defined.
        """
        paper = (REPO / "paper.tex").read_text(encoding="utf-8")
        for name in ("supplement.tex", "postmortem.tex"):
            text = (REPO / name).read_text(encoding="utf-8")
            assert "publish delay" in text, "%s no longer names the publish delay" % name
        assert r"\label{def:scheddelay}" in paper, "and the other term stays defined"


class TestTheFiguresObeyTheVocabularyToo:
    r"""A figure is prose a reader meets first, and the vocabulary rules never reached it.

    Round 54's image review found the supplement's deletion histogram titled "as measured,
    one clock, nanosecond stamps", with a legend reading "nanosecond stamps" against
    "millisecond stamps" -- the exact word the A-vocabulary rule retired, printed four times
    in the one exhibit a reader is most likely to look at before reading anything.

    It survived because the rule was enforced on `.tex` sources and on the figures built by
    two of the seven figure-building scripts. `scripts/figure_vocabulary.py` runs inside
    `make_paper_figures` and `make_result_figures`; `make_deletion_histogram`,
    `make_e1_figure`, `make_method_figure`, `make_thread_figure` and `make_window_figure`
    never call it, so their labels were checked by nobody.

    This gate reads the built PDFs instead of the scripts, which is the only formulation that
    cannot be escaped by adding a script: whatever draws a figure, if the figure ships in
    either document its text is held to the manuscript's vocabulary.
    """

    #: The same rule the prose is held to, applied to the text layer of a figure.
    BARE_STAMP = re.compile(
        r"(?<!Time )(?<![A-Za-z\-])[Ss]tamp(?:s|ed|ing)?\b(?![-_])(?! Counter)")

    def _included(self):
        """Every figure either document includes, as a path."""
        tex = "\n".join((REPO / n).read_text(encoding="utf-8")
                        for n in ("paper.tex", "supplement.tex", "postmortem.tex"))
        stems = re.findall(r"\\includegraphics\[[^\]]*\]\{([^}]*)\}", tex)
        return sorted({REPO / s for s in stems if s.endswith(".pdf")})

    def _text(self, path):
        import shutil
        import subprocess
        if not shutil.which("pdftotext"):            # pragma: no cover - tool absent
            pytest.skip("pdftotext not available")
        out = subprocess.run(["pdftotext", "-q", "-enc", "UTF-8", str(path), "-"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace")
        return out.stdout

    def test_there_are_figures_to_check(self):
        got = self._included()
        assert len(got) >= 10, "expected the submission's figures, found %d" % len(got)
        assert all(p.is_file() for p in got), (
            "included but not built: %s" % [p.name for p in got if not p.is_file()])

    def test_no_figure_says_stamp_where_the_prose_says_timestamp(self):
        bad = []
        for path in self._included():
            if not path.is_file():
                continue
            for hit in set(self.BARE_STAMP.findall(self._text(path))):
                bad.append("%s: %r" % (path.name, hit))
        assert not bad, (
            "figures using the retired word: %s -- the A-vocabulary rule applies to the "
            "text a reader sees, and a figure is the first prose they meet" % sorted(bad))

    #: The same shape the prose rule uses (A3): "instrument" standing in for the quantity
    #: being named. The image review found "as a millisecond instrument holds it" as a panel
    #: title, which is the abstract's retired phrasing surviving in a picture.
    #: A determiner, up to two modifiers, then the noun -- "a millisecond instrument" is the
    #: form the review actually found, and the prose rule's adjacent-word pattern missed it.
    INSTRUMENT_NOUN = re.compile(
        r"\b(?:a|an|the|our|its|this|that|whatever)(?:\s+\w+){0,2}\s+instrument\b"
        r"|\binstrument'?s\b")

    #: "arm" for an experimental setting, retired for "configuration" (annotation 36). The
    #: prose gate cannot ban the bare word -- the ledger emits macros named `\armSixHundred`
    #: and the revision history discusses the retirement -- but a figure has neither, so the
    #: word can be banned outright in the one place it is only ever the retired sense.
    ARM = re.compile(r"\barms?\b", re.I)

    def test_no_figure_calls_a_configuration_an_arm(self):
        bad = []
        for path in self._included():
            if not path.is_file():
                continue
            if self.ARM.search(self._text(path)):
                bad.append(path.name)
        assert not bad, (
            "figures still calling a configuration an arm: %s -- the manuscript says "
            "configuration" % sorted(bad))

    def test_no_figure_uses_instrument_as_the_apparatus(self):
        bad = []
        for path in self._included():
            if not path.is_file():
                continue
            for hit in set(self.INSTRUMENT_NOUN.findall(self._text(path))):
                bad.append("%s: %r" % (path.name, hit))
        assert not bad, (
            "figures naming the apparatus 'instrument' rather than the quantity: %s"
            % sorted(bad))

    def test_the_rule_would_catch_the_defect_it_was_written_for(self):
        assert self.BARE_STAMP.search("(a) as measured, one clock, nanosecond stamps")
        assert self.BARE_STAMP.search("millisecond stamps")
        assert not self.BARE_STAMP.search("nanosecond timestamps")
        assert not self.BARE_STAMP.search("Time Stamp Counter")
        assert self.INSTRUMENT_NOUN.search("(b) as a millisecond instrument holds it")
        assert not self.INSTRUMENT_NOUN.search("(b) as a millisecond timestamp holds it")
        assert not self.INSTRUMENT_NOUN.search("instrumented runs")


class TestSymbolsAreDefinedBeforeUse:
    """A7. Every symbol has a \\label{def:<name>} on its defining sentence, earlier than its
    first use. First failure: T_true in the introduction, defined nowhere; C_0 at "C_0 ~
    \\invFloor" with no definition; k=6 in a table caption before any text says what k is."""

    #: 5 Oct 2026: C_0, the core count k and the load geometry left the paper with the
    #: rebuild (the supplement's glossary defines k and the load geometry for its own tables),
    #: so their entries went too; a symbol that is no longer used fails below rather than
    #: being skipped, so the list cannot rot silently.
    SYMBOLS = {
        "ttrue": r"T_\{?\\mathrm\{true\}|T_\{true\}",
        "rho": r"\\rho\b",
        # v4.1 (2026-09-08): the co-author's confusion point -- "scheduling delay" (the
        # timestamping thread's wait for a core) beside the TTI term once called "scheduling
        # lag" (the send call's lateness). The term is defined where it first appears and
        # the TTI term is now the "send lag". The source may break the line inside the term.
        "scheddelay": r"[Ss]cheduling\s+delay",
        # Round 54 (M3): Table II's caption says "so occupancy alone moved" and Section VI-C
        # says the manipulation "moves occupancy while utilization stays fixed", but the
        # quantity was introduced only as "the probability of the second state". A reader
        # met the word twice before anything told them it was p. On 5 Oct 2026 the word
        # became the field's, "waiting probability"; the label kept its name, and the pattern
        # follows the word (the old one had come to match only the label itself).
        "occupancy": r"\b[Ww]aiting probabilit(?:y|ies)\b",
    }

    @pytest.mark.parametrize("name", sorted(SYMBOLS))
    def test_defined_before_first_use(self, paper, name):
        body = _body(paper)
        anchor = body.find(r"\label{def:%s}" % name)
        first = re.search(self.SYMBOLS[name], body)
        assert first is not None, "%s is no longer used; take it off the list" % name
        assert anchor != -1, "no \\label{def:%s} marks where %s is defined" % (name, name)
        assert anchor <= first.start() + 400, (
            "%s is used at offset %d before its definition at %d" % (name, first.start(), anchor))


class TestAcronymsAreExpandedOnFirstUse:
    """A9. First failure: TSC, never expanded."""

    KNOWN = {"IEEE", "ACM", "SPEC", "TPC", "TCP", "UDP", "NIC", "CPU", "JVM", "PTP", "LAN",
             "DAG", "NIST", "RFC", "TTI", "TOST", "CI", "IQR", "IPPM", "OWAMP", "YCSB", "HP",
             "CFS", "EEVDF", "KVM", "VM", "API", "OS", "IO", "GNU", "MIT", "DOI", "URL",
             "PDF", "CSV", "JSON", "SHA", "GB", "MB", "KB", "MSC", "CC", "BY", "NC", "SA",
             "E-A", "E-B", "E-C", "FIFO", "USA",
             # 2 Oct 2026: the NATS messaging system's name, used as a name. Its project gives
             # no expansion, so there is none to write on first use.
             "NATS"}

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


class TestTheIndustrysNames:
    """A10 (3 Oct 2026). The measured quantities carry the industry's names: the OpenMessaging
    Benchmark's publish latency, publish delay and end-to-end latency, Karimov et al.'s
    event-time and processing-time latency, and Linux's real-time and normal priority. First
    failure: Section VI-B said "timing from the send", and the author asked what a send was."""

    RETIRED = ("acknowledgment lag", "send lag", "send call", "send rate", "send-referenced",
               "send instant", "send schedule", "handling span", "go-first", "lag brake",
               "got-it brake", "timed from the send", "timing from the send",
               "one-way delivery", "delivery factor", "stolen time", "stolen processor time",
               "stolen virtual-cpu time", "stolen vcpu time")
    DOCS = ("paper.tex", "supplement.tex", "postmortem.tex")

    @pytest.mark.parametrize("doc", DOCS)
    def test_no_document_uses_a_retired_name(self, doc):
        flat = " ".join(_prose((REPO / doc).read_text(encoding="utf-8")).split()).lower()
        hits = [t for t in self.RETIRED if re.search(r"(?<![\w-])%s\b" % re.escape(t), flat)]
        assert not hits, "%s still says %s" % (doc, hits)

    @pytest.mark.parametrize("doc", DOCS)
    def test_delivery_time_survives_only_as_specjms_own_metric(self, doc):
        """SPECjms2007 calls its metric Delivery Time, a proper name the documents quote; the
        quantity the paper measures is the end-to-end latency."""
        flat = " ".join(_prose((REPO / doc).read_text(encoding="utf-8")).split())
        hits = [m.start() for m in re.finditer(r"(?i)\bdelivery\s+times?\b", flat)
                if not flat[max(0, m.start() - 8):m.start()].endswith("defines ")]
        assert not hits, "%s: 'delivery time' at %s" % (doc, hits)

    @pytest.mark.parametrize("doc", DOCS)
    def test_the_symbols_follow_the_words(self, doc):
        body = "\n".join(line for line in (REPO / doc).read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("%"))
        assert "mathrm{send}" not in body and r"\rm send" not in body

    #: The industry's names for the quantities of the paper's model. The 5 Oct 2026 rebuild kept
    #: D, A and E in the paper and left the publish delay and the processing-time latency to the
    #: supplement, so a name is held to its definition wherever the paper uses it, and the two
    #: names the model cannot lose are held unconditionally.
    INDUSTRY = ("end-to-end latency", "publish latency", "publish delay",
                "processing-time latency", "event-time latency")
    CORE = ("end-to-end latency", "publish latency")

    def test_the_paper_defines_each_name_where_its_model_begins(self, paper):
        flat = " ".join(paper.split())
        reader = TestEachNameIsBuiltWhereAReaderFirstMeetsIt._reader_text(paper)
        used = [t for t in self.INDUSTRY
                if TestEachNameIsBuiltWhereAReaderFirstMeetsIt._first(t, reader)]
        assert set(self.CORE) <= set(used), "the model no longer names D and A: %s" % used
        for term in used:
            assert "\\emph{%s}" % term in flat, term
        # Where the model says each span starts: t_pub at the publish call, and E at the
        # moment the message fell due.
        assert "$t_{\\mathrm{pub}}$, read immediately before the publish call" in flat
        assert "mark when the message was due" in flat


class TestEachNameIsBuiltWhereAReaderFirstMeetsIt:
    """A10, 4 Oct 2026: the author asked that the industry's names be "clear in a way tipler and
    mosca would build them", and that everything in the paper be explained. A name is defined,
    in plain words and in italics, where a reader first meets it in the body; the abstract is a
    summary and may use it first. First failure: "one-way latency" was used in the introduction
    and in the contributions and glossed only in Section V, and "real-time priority" and
    "normal priority", the paper's main manipulation, were defined nowhere."""

    #: 5 Oct 2026: origin, transport proxy, publish delay, processing-time latency, consumer
    #: pattern and tick left the paper with the passages that used them, and so left this list.
    DEFINED = ("scheduling delay", "end-to-end latency", "publish latency", "real-time priority",
               "normal priority", "one-way latency", "positivity filter", "manipulation",
               "retention", "event-time latency", "background load", "negative-span rate",
               # 4 Oct 2026, the author: "yes gloss those four too, cut elsewhere to fit." The
               # knee, used once, is said in plain words instead; stolen time is Linux's steal time.
               "busy-polling", "steal time",
               # 4 Oct 2026: the introduction opens on the stakes, and its first paragraph
               # defines the two programs a broker joins.
               "producer", "consumer")

    @staticmethod
    def _reader_text(paper):
        body = paper.split(r"\section{Introduction}", 1)[1]
        body = body.split(r"\section*{Acknowledgment}", 1)[0]
        body = re.sub(r"(?m)(?<!\\)%.*$", " ", body)
        body = re.sub(r"\\begin\{equation\*?\}.*?\\end\{equation\*?\}", " ", body, flags=re.S)
        body = re.sub(r"\$[^$]*\$", " ", body)
        return " ".join(body.split())

    @staticmethod
    def _first(term, text):
        words = r"\s+".join(re.escape(w) for w in term.split())
        return re.search(r"(?i)(?<![\w-])%s(?![\w-])" % words, text)

    def _assert_defined_first(self, term, text):
        first = self._first(term, text)
        assert first, "%r is no longer used; take it off the list" % term
        assert text[max(0, first.start() - 6):first.start()] == "\\emph{", (
            "%r is first used before its definition: ...%s..."
            % (term, text[max(0, first.start() - 90):first.end() + 30]))

    @pytest.mark.parametrize("term", DEFINED)
    def test_the_first_use_is_the_definition(self, paper, term):
        self._assert_defined_first(term, self._reader_text(paper))

    def test_the_publish_call_is_said_where_it_first_appears(self, paper):
        """Since 5 Oct 2026 the gloss is also in italics, so a closing brace may come first."""
        text = self._reader_text(paper)
        first = self._first("publish call", text)
        assert first, "the paper no longer says 'publish call'"
        after = text[first.end():first.end() + 60]
        assert re.match(r"\}?, the moment the producer hands the message over", after), after

    def test_published_means_the_producers_act_only(self, paper):
        """A10 freed "publish" for the producer's act; until 4 Oct the paper still said
        "published reports", "published practice" and "the kernel's published rule"."""
        text = " ".join(_prose(_body(paper)).split())
        uses = [text[max(0, m.start() - 50):m.end() + 10]
                for m in re.finditer(r"(?i)\bpublished\b", text)]
        made_public = [u for u in uses if not re.search(r"before (?:they were|being) published"
                                                        r"|due to be published", u)]
        assert not made_public, made_public


class TestTheFirstHalfStatesWhatHolds:
    """B26, 4 Oct 2026. The author: "everything must look perfect in the 1st half of the paper,
    any pull back to reality must happen only in the second half, this should not mean an
    exageration or omission", and "you cannot make a generalization that is not true". So the
    first half, Sections I to IV, states each result for exactly the cases it holds in, and each
    limit it used to carry is stated, whole, in Section VIII. First failure: Section IV-B said
    a registered prediction "failed" and that "the probe is not free" in the middle of the
    mechanism, and Section II-A that "one early stage ... is excluded" before any result.

    5 Oct 2026: the rebuilt paper's first half is still Sections I to IV, from the introduction
    to the mechanism, and Section VIII is now "Limitations"; the halves are found by their
    labels rather than their headings. Section VIII rewords the slice's limit ("derived, not
    read off them"), and the sign check's history went, with the rest of the sign check's
    detail, to Supplement S2, where it is held whole."""

    #: Each limit the first half used to carry, by a phrase only that limit uses.
    MOVED = ("tenfold failed", "is not free", "derived, not read off them")
    #: A limit the rebuild handed to the supplement, and the supplement section that states it.
    HANDED_ON = (("fixed the rule after earlier campaigns had run", "s:signcheck"),)

    @staticmethod
    def _flat(text):
        return " ".join(re.sub(r"(?m)(?<!\\)%.*$", " ", text).split())

    @staticmethod
    def _section_holding(body, label):
        """Where the \\section that carries `label` begins."""
        return body.rindex(r"\section{", 0, body.index(r"\label{%s}" % label))

    @classmethod
    def _halves(cls, paper):
        body = cls._flat(paper)
        first = body[body.index(r"\section{Introduction}"):
                     cls._section_holding(body, "sec:external")]
        threats = body[cls._section_holding(body, "sec:limitations"):
                       body.index(r"\section{Conclusion}")]
        return first, threats

    @pytest.mark.parametrize("phrase", MOVED + tuple(p for p, _ in HANDED_ON))
    def test_the_limit_is_not_in_the_first_half(self, paper, phrase):
        first, _ = self._halves(paper)
        assert phrase not in first, "%r is back in Sections I to IV" % phrase

    @pytest.mark.parametrize("phrase", MOVED)
    def test_the_limit_is_stated_whole_in_section_viii(self, paper, phrase):
        _, threats = self._halves(paper)
        assert phrase in threats, "%r has left the paper, not just the first half" % phrase

    @pytest.mark.parametrize("phrase,label", HANDED_ON)
    def test_a_limit_handed_to_the_supplement_is_stated_whole_there(self, phrase, label):
        supp = self._flat((REPO / "supplement.tex").read_text(encoding="utf-8"))
        at = supp.index(r"\label{%s}" % label)
        end = supp.find(r"\section{", at)
        assert phrase in supp[at:end if end != -1 else len(supp)], (
            "%r has left the submission, not just the paper" % phrase)


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
    """B4. No supplement pointer inside Related Work. First failure:
    "Supplement~S52.3 sizes that literature". The section was "Background and Related Work"
    until v5 (28 Sep), when it moved after the results under its plain name."""

    def test_no_supplement_pointer_in_related_work(self, paper):
        body = _body(paper)
        start = body.index(r"\section{Related Work}")
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
    #: v5 (28 Sep): the rules became Section VI, "What Benchmark Authors Should Do", with its
    #: checks in Table IV. The held span is that section up to the paragraph on a better
    #: clock, which is where the rules end and the measured asides begin, as before.
    #: v6 (2 Oct): the rules are Section VI-C, "Checks that cost nothing", inside Practical
    #: Implications. VI-B before it is a results subsection (the proxy's cost, measured, and
    #: its repair) and is held as results, as it was when it closed the scheduling section.
    #: 5 Oct 2026: Section VI, "What to Do", sets the rules out as Table I (tab:checks), each
    #: row with what it buys, and its paragraphs report those measurements in full, as VI-B
    #: did. The table is the span held; every number it prints must be reported in the paper's
    #: text before Related Work.
    CHECKS = re.compile(r"\\begin\{table\*?\}(?:(?!\\end\{table).)*?\\label\{tab:checks\}"
                        r".*?\\end\{table\*?\}", re.S)

    def test_discussion_numbers_are_results_numbers(self, paper):
        body = re.sub(r"(?m)^%.*$", "", _body(paper))
        table = self.CHECKS.search(body)
        assert table, "the table of checks (tab:checks) is gone; re-read B8 before moving this"
        discussion = table.group(0)
        results = body[:table.start()] + body[table.end():body.index(r"\section{Related Work}")]
        macros = set(re.findall(r"\\([a-zA-Z]+(?:Lo|Hi|Pct|Factor|Fraction|Paired|Median|Err\w*|Crossover\w*|Gap\w*))\b",
                                discussion))
        assert macros, "the table of checks quotes no measured number; the rule has gone vacuous"
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
