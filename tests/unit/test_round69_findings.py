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


def _bibliographies():
    """Both reference files, joined: the one the paper and the supplement cite, and the
    postmortem's own, which moved to a file of its own on 7 Oct 2026. An entry is checked
    wherever it lives."""
    return "\n".join((REPO / name).read_text(encoding="utf-8")
                     for name in ("manuscript_references.bib", "postmortem_references.bib"))
RE_BS = chr(92) + chr(92)
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def paper():
    return (REPO / "paper.tex").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def supplement():
    return (REPO / "postmortem.tex").read_text(encoding="utf-8")


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
        """v5 (28 Sep): the bold rule is a row of Table IV now, and its prose split: Section VI
        concedes the dither as standing advice under the IPPM citations and claims only the
        conjunction, and Section IV-C states what the paper adds to the 1970 note, the sign of
        the operation. The two v4 phrases give way to those, one pin for each.

        5 Oct 2026: the check is the table's "Randomize the publish instants (Poisson
        sampling)", the field's name for the cure. Related Work concedes the arithmetic and
        its cure, phase jitter, to the 1970 note and the randomization to the IPPM framework,
        and claims "these checks" beside them; Section V-C claims the deletion, which the
        counter does not perform. One pin for each, as before."""
        flat = " ".join(paper.split())
        i = flat.index(chr(92) + "label{tab:checks}")
        table = flat[i:flat.index(chr(92) + "end{table}", i)]
        assert "Randomize the publish instants (Poisson sampling)" in table, \
            "the randomization check has left the table of checks"
        paras = [" ".join(p.split()) for p in re.split(r"\n[ \t]*\n", paper)
                 if "IP measurement advises randomizing probe" in " ".join(p.split())]
        assert len(paras) == 1, "the randomization's precedents have moved; retarget this pin"
        passage = paras[0]
        assert "rfc2330" in passage and "rfc3432" in passage, \
            "the randomization's precedents are no longer cited where it is conceded"
        assert "its cure, phase jitter, are in a 1970 counter note" in passage, \
            "the cure is no longer conceded to the 1970 note"
        assert "What we add is these checks" in passage, (
            "Related Work claims something other than the checks beside the cure's "
            "precedents; the why is Hewlett-Packard's")
        j = flat.index("The arithmetic is in Hewlett-Packard's 1970 counter note")
        assert "but the deletion is not" in flat[j:j + 250], (
            "the contribution is the consequence under deletion, which is V-C's own wording")

    def test_the_concession_it_defers_to_is_still_there(self, paper):
        """If III-C ever stops conceding, this rule's new wording would be the overclaim.

        v5 (28 Sep): the concession is in Section IV-C and opens "The arithmetic is not
        ours", which concedes at least as much as v4's "we derived it, then found it in a
        counter manual"; the order of discovery is kept in S17 ("We arrived at it
        independently").

        5 Oct 2026: Section V-C opens it "The arithmetic is in Hewlett-Packard's 1970 counter
        note", and Related Work gives the note the cure too; both concede what v5 did."""
        flat = " ".join(paper.split())
        assert "The arithmetic is in Hewlett-Packard's 1970 counter note" in flat
        assert "The retention arithmetic and its cure, phase jitter, are in a 1970 counter note" \
            in flat

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
        bib = _bibliographies()
        entry = bib[bib.index("@patent{hp1976dither"):]
        entry = entry[:entry.index("\n}")]
        for field in ("nationality", "number", "yearfiled", "monthfiled"):
            assert field in entry, "IEEEtran's patent type wants %s" % field
        assert "assignee" not in entry, "not an IEEEtran field; the note carries it"

    def test_no_comment_in_the_bibliography_starts_a_bogus_entry(self):
        """BibTeX scans for an at-sign outside entries too. A comment naming an entry type
        with one swallows the entry below it -- which is what the first draft of round 69's
        comment did, and bibtex reported it as one error line in a log nobody reads."""
        bib = _bibliographies()
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
        """The referee said none would; this is where that is checked rather than trusted.

        2 Oct 2026: one did, for a reason that has nothing to do with the thresholds. RabbitMQ
        PerfTest's getDifference returns the absolute value of the difference, so PerfTest
        substitutes a value and joins the silent tools; so does the NATS CLI, whose percentile
        table is recorded into a library that refuses a negative, with the error ignored. Seven,
        not five. The other three counts hold, and test_harness_registry records why the two
        were missed."""
        import harness_registry
        s = harness_registry.summary()
        assert (s["harnesses"], s["n_silent"], s["vendors"], s["languages"]) == (10, 7, 9, 5)

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
        """v5 (28 Sep): Section V says "We read" where v4 said "We audited", and "one of them
        reaches that class at the other threshold" became the editor's plainer statement
        (section 7, example 14): Pulsar admits zero, drops negatives and keeps the samples the
        benchmark deletes. The pins follow those words and Table III, which prints both
        comparisons in one class."""
        assert "reaching the same design" not in paper
        i = paper.index(chr(92) + "label{sec:tools}")
        passage = " ".join(paper[i:paper.index(chr(92) + "subsection{", i)].split())
        # 4 Oct 2026: the table the audit fills moved to the supplement's tool registry, when
        # the paper's system and remedies figures needed its room; the passage points to it.
        assert "the supplement's tool registry" in passage, \
            "the class is shown in the table the audit fills"
        # 5 Oct 2026: the rebuilt Section V-A names the classes by what each does to the
        # value, a filter drops it, the library refuses it, another value replaces it, and
        # leaves Pulsar's threshold to the supplement's S5, which states what each threshold
        # does (see the next test). Should the paper name Pulsar again, it must say so too.
        assert "a filter drops it" in passage, "the class is no longer said by what it does"
        if "Pulsar" in passage:
            assert "admits zero" in passage or "keeps those" in passage, \
                "say what the threshold does"

    def test_pulsar_is_used_as_the_contrast_the_sign_channel_predicts(self, paper):
        """v5 (28 Sep): "quantum" is "timestamp resolution" throughout v5 (editor, section 7),
        and the pile-up is now "visibly at zero".

        5 Oct 2026: the contrast is the journal supplement's S5, which says what each
        threshold does, and that the zeros the benchmark deletes pile up visibly at zero
        under Pulsar's; it is held there."""
        journal = (REPO / "supplement.tex").read_text(encoding="utf-8")
        i = journal.index("Apache Pulsar's performance client")
        passage = " ".join(journal[max(0, i - 400):i + 300].split())
        assert "pile up visibly at zero" in passage, (
            "a visible pile-up is what IV-D predicts when only the inversions are dropped")
        assert "deletes every sample that computes to exactly zero" in passage
        assert "keeps those and drops only values below zero" in passage, \
            "say that the other threshold keeps what the benchmark deletes"

    def test_the_rendered_section_reads_the_same(self):
        """v5 (28 Sep): the pile-up phrase follows the source, as above. 5 Oct 2026: on the
        journal supplement's pages, where the contrast now is."""
        flat = " ".join(_rendered("paper").split())
        assert "reaching the same design" not in flat
        journal = " ".join(_rendered("supplement").split())
        assert "pile up visibly at zero" in journal
        assert "keeps those and drops only values below zero" in journal


class TestW2TheAuditSaysWhatGrainItIsExactTo:

    def test_threats_names_the_threshold_grain(self, paper, supplement):
        """v5 (28 Sep): Section VIII says the tools "were read at source, not deployed", and
        "exact to the threshold rather than to the behavior a deployment would show" went in
        the cut of antitheses (editor, section 7.1). Both halves are pinned where they now are:
        the concession in Section VIII, and the grain in Table III, whose caption records what
        each tool does to a value at or below zero and whose cells print the comparison."""
        flat = " ".join(paper.split())
        # 5 Oct 2026: the rebuilt Limitations concede it as "We classified the ten tools by
        # reading them", beside the eleven the registered campaign ran on one pair of machines.
        assert re.search(r"classified the " + re.escape(chr(92)) + r"harnessAuditedWord\{\} "
                         r"tools by reading them", flat), \
            "Threats no longer concedes that the audit read source and deployed nothing"
        # 4 Oct 2026: Table III is the supplement's now (stab:tools), caption and cells unchanged.
        journal = (REPO / "supplement.tex").read_text(encoding="utf-8")
        j = journal.index("label{stab:tools}")
        caption = " ".join(journal[journal.rindex("caption{", 0, j):j].split())
        assert "what happens to a value at or below zero" in caption, (
            "Table III's caption no longer says the audit is exact to what a tool does at the "
            "threshold")
        table = journal[j:journal.index("end{table", j)]
        assert "docs/generated/registry_table" in table, \
            "Table III no longer prints the generated registry, with its comparisons"


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
        """29 Sep: the journal supplement draws it in S4.2 and the postmortem keeps it in S17.
        The pointer to S17 went under the editor's budget of fifteen (the HP citation carries
        its sentence), so the main text reaches the figure through the section holding it.

        5 Oct 2026: the rebuilt paper carries neither geometry figure. The journal supplement
        draws the four phases of one millisecond as panel (a) of the deletion figure
        (`deletion_phases`, S4.1), from the plotting function `quantum_geometry`'s panel (a)
        came from, and the postmortem keeps the two-panel figure in S17. The main text still
        reaches the journal supplement's figure through the section holding it.

        6 Oct 2026: the deletion figure is the main text's again, Section V-C's, on the
        review's ruling that the paper use its room for the figures that carry its argument,
        and it left the journal supplement, whose S4.1 and S4.2 now point at it. The two-panel
        geometry figure stays in the postmortem's S17."""
        journal = (REPO / "supplement.tex").read_text(encoding="utf-8")
        assert "quantum_geometry" in supplement
        assert "quantum_geometry" not in paper, "quantum_geometry is back in the main text"
        assert "deletion_phases" not in journal, "the deletion figure is printed twice"
        at = paper.index("deletion_phases")
        caption = " ".join(paper[at:paper.index(chr(92) + "end{figure", at)].split())
        assert "four phases within one millisecond" in caption, \
            "the paper's figure no longer draws the phases of one millisecond"
        for panel in ("a", "b"):
            assert ("Fig.~" + chr(92) + "ref{P-fig:deletion}" + panel) in journal, \
                "the supplement reaches panel (%s) by pointer" % panel

    def test_the_main_text_still_carries_the_claim_the_figure_draws(self, paper):
        """v5 (28 Sep): the sentence reads "What moves retention is not the path but where the
        producer's send instants fall against the grid"; the anchor follows it and the checks
        are unchanged. v5 also took the editor's advice (section 9) on half of this class's
        decision: panel (a), the four phases of one tick, is redrawn as Fig. 5(a) from the same
        plotting function, while the two-panel `quantum_geometry` figure stays in S17.

        5 Oct 2026: Section V-C says it as "A sample survives only if a millisecond boundary
        falls between its two timestamps", and gives the probability, T_true over tau; the
        anchor follows it and the checks are the same."""
        flat = " ".join(paper.split())
        i = flat.index("A sample survives only if a millisecond boundary falls between its two")
        passage = flat[i:i + 420]
        assert ("with probability $T_{" + chr(92) + "mathrm{true}}/" + chr(92) + "tau$"
                in passage), "the claim no longer says what the geometry gives"
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

    def test_the_fork_clause_is_deliberate(self, supplement):
        """v5 (28 Sep): the fork sentence left the paper with the fork count (editor, section
        5) and opens Supplement S25's paragraph on forks, clause intact; it is pinned there."""
        # Round 80 bought a line back as "readable public forks"; the clause itself is untouched.
        flat = " ".join(supplement.split())
        i = flat.index("readable public forks")
        clause = flat[i:i + 220]
        assert "rather than how many chose it" in clause, (
            "the contrast is the point: the survey measures inheritance, not adoption")


class TestTheBibliographyLogIsRead:
    """Every other build artefact here is checked; bibtex's was not.

    Round 69 put a comment naming an entry type into `manuscript_references.bib`, BibTeX
    found the at-sign, parsed prose as an entry and skipped the real one below it. The LaTeX
    build reported zero undefined citations, because a `.bbl` from an earlier run was still
    on disk, so the only evidence anywhere was one line in `postmortem.blg`.
    """

    @pytest.mark.parametrize("stem", ["paper", "supplement", "postmortem"])
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

    @pytest.mark.parametrize("stem", ["paper", "supplement", "postmortem"])
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

    @pytest.mark.parametrize("name", ["paper", "supplement", "postmortem"])
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
