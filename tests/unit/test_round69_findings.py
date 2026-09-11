r"""Round 69's referee items, pinned so a later pass cannot quietly undo them.

Both required items were the paper claiming a little more than its own supplement concedes.
R1: §VIII-B said "what we add is why" about the dither rule while §III-C conceded that the
1970 counter note carries "the symptom and the cure" and S17 said "we arrived at it
independently" -- the paper gave the point up twice and took it back once. R2: the audit
called Apache Pulsar's `if (latencyMillis >= 0)` a positivity guard and "the same design" as
the OpenMessaging Benchmark's `> 0`, when `>= 0` admits zero and zero is the entire
population Mode B is about.

Neither changed a number. `harnessAudited` is still ten, `harnessSilent` still five, and
`harnessDisposalClasses` still three -- the last because a threshold is not a new response,
which is modelled in `DISPOSAL_RESPONSES` rather than asserted here.
"""
from pathlib import Path
import re
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
RE_BS = chr(92) + chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "supplement.tex").read_text(encoding="utf-8")


def _rendered(name):
    pdf = REPO / ("%s.pdf" % name)
    if not pdf.is_file():
        pytest.skip("%s not built" % pdf.name)
    import pypdf
    return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(pdf)).pages)


class TestR1TheDitherRuleDoesNotClaimTheWhy:

    def test_the_rule_no_longer_claims_the_why(self, paper):
        assert "what we add is why" not in paper, (
            "III-C concedes that [1] carries 'the symptom and the cure', and S17 says the cure "
            "is phase jitter 'so the samples stop landing on the same points of the clock's "
            "cycle' -- which is the why. The rule may not claim it back.")

    def test_the_rule_says_what_the_paper_actually_adds(self, paper):
        i = paper.index("Dither the send instant")
        rule = " ".join(paper[i:i + 900].split())
        assert "already names the coherence it breaks" in rule
        assert "deleted rather than averaged" in rule, (
            "the contribution is the consequence under deletion, which is III-C's own wording")

    def test_the_concession_it_defers_to_is_still_there(self, paper):
        """If III-C ever stops conceding, this rule's new wording would be the overclaim."""
        assert "the symptom and the cure" in paper
        assert "we derived it, then found it in a counter manual" in paper

    def test_the_supplement_carries_the_patent_beside_the_note(self, supplement):
        i = supplement.index("S17. The 1970 counter note")
        j = supplement.index(chr(92) + "section{S18", i)
        section = supplement[i:j]
        assert "hp1976dither" in section, "the patent belongs where AN 162-1 is read line by line"
        assert "3,938,042" in section
        assert "coherence between the clock" in section, "quote the mechanism, do not paraphrase it"

    def test_the_patent_is_a_supplement_citation_only(self, paper):
        """The article is at 45/45 and a patent corroborating a concession does not displace
        anything in it."""
        assert "hp1976dither" not in paper

    def test_the_bibliography_entry_uses_the_styles_own_patent_fields(self):
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        entry = bib[bib.index("@patent{hp1976dither"):]
        entry = entry[:entry.index("\n}")]
        for field in ("nationality", "number", "yearfiled", "monthfiled"):
            assert field in entry, "IEEEtran's patent type wants %s" % field
        assert "assignee" not in entry, "not an IEEEtran field; the note carries it"

    def test_no_comment_in_the_bibliography_starts_a_bogus_entry(self):
        """BibTeX scans for an at-sign outside entries too. A comment naming an entry type
        with one swallows the entry below it -- which is what the first draft of round 69's
        comment did, and bibtex reported it as one error line in a log nobody reads."""
        bib = (REPO / "manuscript_references.bib").read_text(encoding="utf-8")
        for n, line in enumerate(bib.splitlines(), start=1):
            if line.lstrip().startswith("%"):
                assert "@" not in line, "bibliography comment at line %d carries an at-sign" % n


class TestR2TheTwoThresholdsAreDifferentThings:

    def test_the_classifier_tells_the_operators_apart(self):
        from audit_external_harness import classify
        assert classify("if (endToEndLatencyMicros > 0) {") == ["positive_only_filter"]
        assert classify("if (latencyMillis >= 0) {") == ["nonnegative_filter"]

    def test_a_counter_consequent_still_withdraws_either_guard(self):
        """Round 6's acquittal of emqtt-bench has to survive the split."""
        from audit_external_harness import classify
        assert classify("E2ELatency > 0 andalso inc_counter(P, publish_latency, E2ELatency),") == []
        assert classify("if (latency >= 0) { incCounter(x); }") == []

    def test_pulsar_is_in_the_weaker_class_and_still_silent(self):
        import harness_registry
        s = harness_registry.summary()
        assert s["filters"] == ["OpenMessaging Benchmark"]
        assert s["nonnegative_filters"] == ["Apache Pulsar perf"]
        assert "Apache Pulsar perf" in s["silent"], "a weaker guard is still an uncounted one"

    def test_no_headline_count_moved(self):
        """The referee said none would; this is where that is checked rather than trusted."""
        import harness_registry
        s = harness_registry.summary()
        assert (s["harnesses"], s["n_silent"], s["vendors"], s["languages"]) == (10, 5, 9, 5)

    def test_a_threshold_is_not_a_new_response(self):
        from audit_external_harness import DISPOSAL_KINDS, DISPOSAL_RESPONSES
        assert set(DISPOSAL_RESPONSES) == set(DISPOSAL_KINDS), "every kind maps to a response"
        assert len(set(DISPOSAL_RESPONSES.values())) == 3, (
            "Section VII enumerates three: drop it, replace it, let the library refuse it")
        assert DISPOSAL_RESPONSES["positive_only_filter"] == \
            DISPOSAL_RESPONSES["nonnegative_filter"]

    def test_the_table_prints_the_comparison_it_classified_by(self):
        table = (REPO / "docs" / "generated" / "registry_table.tex").read_text(encoding="utf-8")
        assert ">0" in table and "geq 0" in table, "both thresholds visible in the cells"

    def test_the_caption_defines_filter_by_what_it_drops(self, supplement):
        i = supplement.index("Audited harnesses, one row per span rather than per tool]{")
        caption = " ".join(supplement[i:i + 900].split())
        assert "admits only" not in caption, (
            "the old definition was true of `> 0` and false of `>= 0`")
        assert "deletes every sample that computes to exactly zero" in caption

    def test_the_registry_note_names_the_operator_it_found(self):
        csv_text = (REPO / "docs" / "results" / "external"
                    / "harness_registry.csv").read_text(encoding="utf-8")
        assert "NON-NEGATIVITY guard" in csv_text
        assert "a second vendor's millisecond cross-host span behind a positivity guard" \
            not in csv_text

    def test_the_main_text_claims_the_class_and_not_the_design(self, paper):
        assert "reaching the same design" not in paper
        i = paper.index("We audited")
        passage = " ".join(paper[i:i + 1100].split())
        assert "the other" in passage and "threshold" in passage
        assert "admits zero" in passage, "say what the threshold does"

    def test_pulsar_is_used_as_the_contrast_the_sign_channel_predicts(self, paper):
        i = paper.index("We audited")
        passage = " ".join(paper[i:i + 1100].split())
        assert "pile up on the quantum" in passage, (
            "a visible pile-up is what VI-C predicts when only the inversions are dropped")

    def test_the_rendered_section_reads_the_same(self):
        flat = " ".join(_rendered("paper").split())
        assert "reaching the same design" not in flat
        assert "admits zero" in flat and "pile up on the quantum" in flat


class TestW2TheAuditSaysWhatGrainItIsExactTo:

    def test_threats_names_the_threshold_grain(self, paper):
        i = paper.index("are readings of source rather than measured deployments")
        assert "exact to the threshold" in paper[i:i + 260]


class TestW1TheGeometryFigureStaysInTheSupplement:
    """Recorded rather than acted on, which is what the referee asked for.

    `quantum_geometry` is the clearest exhibit in the submission and it is in S17. Rounds 51,
    57, 59, 60 and 68 each declined to promote a figure into a main text whose budget is full
    at twelve pages, and round 69 declined to override them. What round 69 added is the
    arithmetic: the figure costs about 12-15 lines at column width against roughly 4 lines of
    prose it would replace, so the net is about a third of a column, and a thirteenth page
    costs $220 in overlength charges against two pages of headroom before TC's 14-page wall.

    The standing instruction on this manuscript is to move anything not necessary OUT of the
    main text, so a figure whose claim the prose already carries stays where it is. This test
    exists so that round 70 finds the decision and its price instead of re-deriving them.
    """

    def test_the_figure_is_in_the_supplement_and_the_main_text_points_at_it(
            self, paper, supplement):
        assert "quantum_geometry" in supplement
        assert "quantum_geometry" not in paper
        assert "S17" in paper, "the main text reaches it by pointer"

    def test_the_main_text_still_carries_the_claim_the_figure_draws(self, paper):
        i = paper.index("What moves retention is where the producer")
        passage = " ".join(paper[i:i + 420].split())
        assert "crosses a grid instant" in passage
        assert "T_{" in passage or "tau" in passage

    def test_the_paper_is_still_inside_the_free_page_budget(self):
        log = REPO / "paper.log"
        if not log.is_file():
            pytest.skip("paper.log absent")
        m = re.search(r"Output written on [^\n]*?\((\d+) pages",
                      log.read_text(encoding="utf-8", errors="replace").replace("\n", " "))
        assert m and int(m.group(1)) <= 12, (
            "past twelve pages TC charges $220 each; that is a decision, not a build outcome")


class TestW3RecordedNotRequested:
    """The fork sentence's closing clause reads from the wrong end -- "bounds how few have
    diverged" is a bound on divergence stated as a bound on fewness. Every rewrite tried was
    longer, and the clause is doing real work: it separates inheritance from endorsement.
    Kept, and pinned here so a copy editor's query has an answer and round 70 does not
    rediscover it as a defect."""

    def test_the_fork_clause_is_deliberate(self, paper):
        i = paper.index("public forks we could read")
        clause = " ".join(paper[i:i + 220].split())
        assert "rather than how many chose it" in clause, (
            "the contrast is the point: the survey measures inheritance, not adoption")


class TestTheBibliographyLogIsRead:
    """Every other build artefact here is checked; bibtex's was not.

    Round 69 put a comment naming an entry type into `manuscript_references.bib`, BibTeX
    found the at-sign, parsed prose as an entry and skipped the real one below it. The LaTeX
    build reported zero undefined citations, because a `.bbl` from an earlier run was still
    on disk, so the only evidence anywhere was one line in `supplement.blg`.
    """

    @pytest.mark.parametrize("stem", ["paper", "supplement"])
    def test_no_bibtex_error_or_skipped_entry(self, stem):
        log = REPO / ("%s.blg" % stem)
        if not log.is_file():
            pytest.skip("%s.blg absent; run bibtex" % stem)
        text = log.read_text(encoding="utf-8", errors="replace")
        for phrase in ("I was expecting", "I'm skipping whatever remains",
                       "error message", "I didn't find a database entry"):
            assert phrase not in text, (
                "%s.blg reports %r; a skipped entry can still resolve against a stale .bbl, "
                "so this log is the only place it shows" % (stem, phrase))

    @pytest.mark.parametrize("stem", ["paper", "supplement"])
    def test_every_cited_key_reached_the_printed_list(self, stem):
        """The failure mode the log line above produces, checked from the other side."""
        aux = REPO / ("%s.aux" % stem)
        bbl = REPO / ("%s.bbl" % stem)
        if not (aux.is_file() and bbl.is_file()):
            pytest.skip("%s not built" % stem)
        cited = set()
        for m in re.finditer(RE_BS + r"citation\{([^}]*)\}",
                             aux.read_text(encoding="utf-8", errors="replace")):
            cited.update(k.strip() for k in m.group(1).split(",") if k.strip() != "*")
        printed = set(re.findall(RE_BS + r"bibitem\{([^}]*)\}",
                                 bbl.read_text(encoding="utf-8", errors="replace")))
        assert not (cited - printed), \
            "%s cites keys the printed list does not carry: %s" % (stem, sorted(cited - printed))


class TestNoWordIsDoubled:
    r"""A splice can leave one word at the end of a line and the same word at the start of
    the next, and nothing in this project could see it.

    Round 69's own edit to Section VII did exactly that: the replaced clause ended with
    "and" and the replacement began with it, the two landed on consecutive lines, and the
    build was clean, the vocabulary check clean, every content pin green. It was found by
    reading the rendered page -- which is the right way to find it and a poor way to be sure
    of finding it, since the same reading had already passed over the line twice.

    Checked on the SOURCE with its whitespace flattened, which is where the defect is: a
    line break is the only thing hiding the pair. The rendered text was tried first and is
    the wrong surface -- it flattens a table's columns into one line, so `send (chain)`
    beside a `send` origin column, and a `utilization` header beside a `utilization` cell,
    both read as doubled words. Table rows are excluded here for the same reason, by the
    ampersand that makes them rows.
    """

    #: Words that legitimately double in English or in this manuscript's subject matter.
    ALLOWED = {"had had", "that that", "is is"}

    #: A word, whitespace, then the same word again. Written as a plain raw string and not
    #: built from RE_BS: that constant is a LITERAL backslash, which is what the rest of this
    #: file wants when it searches LaTeX source, and exactly wrong for a regex escape. The
    #: first draft used it here and the pattern silently matched nothing.
    DOUBLED = re.compile(r"\b([A-Za-z]{2,})\s+\1\b")

    @staticmethod
    def _prose(name):
        text = (REPO / ("%s.tex" % name)).read_text(encoding="utf-8")
        keep = [l for l in text.splitlines()
                if not l.lstrip().startswith("%") and "&" not in l]
        return " ".join(" ".join(keep).split())

    @pytest.mark.parametrize("name", ["paper", "supplement"])
    def test_no_word_is_immediately_repeated(self, name):
        flat = self._prose(name)
        doubled = []
        for m in self.DOUBLED.finditer(flat):
            if m.group(0).lower() not in self.ALLOWED:
                doubled.append(" ".join(flat[max(0, m.start() - 60):m.end() + 40].split()))
        assert not doubled, "%s repeats a word: %s" % (name, doubled[:3])

    def test_the_rule_catches_the_pair_that_prompted_it(self):
        source = "in three classes, and" + chr(10) + "and one of them reaches that class"
        m = self.DOUBLED.search(" ".join(source.split()))
        assert m and m.group(1) == "and"

    def test_the_rule_does_not_fire_on_a_word_inside_another(self):
        """Word boundaries on both ends, so "an android" is not a pair."""
        assert not self.DOUBLED.search("an android and androids")
