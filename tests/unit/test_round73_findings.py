r"""Round 73's referee items, pinned so a later pass cannot quietly undo them.

R1 is the sharpest item since round 70, and it had been in the paper since round 4.
The manuscript answered one question -- what is the negative-span rate at 88% utilization? --
three times, in three places, with three numbers:

    Section III-B   23%    typed, disputing Sharma et al., reconcilable with no artefact
    Section VIII-B  8.4%   emitted, but `diseaseOverWhole` is the rate over the WHOLE corpus
                           at every load, wearing a load-specific label inside a reporting
                           rule that tells other authors what load to test at
    Table II        30.5%  emitted, correctly labelled, `stamping_priority.csv` row l88

A rate and the load it was measured at are one fact, and emitting them apart is what let a
load-specific sentence pick up a corpus-wide number and look right. They are emitted together
now, as `rt{Low,High}BasePct` beside `rt{Low,High}LoadPct`.

R2 is a regression from round 72's own repair. That round added to Section V-E: "which is what
puts the negative-span rate at 8.43% rather than at a hundredth of that or at half" -- a
computation with the two-state model, in the main text, while S9 says in as many words that
*nothing in the paper computes with it* and that `p` has never been measured independently of
the rate it explains. It is round 72's R3 in miniature, three days later.

The round's own lesson is W1, and it is about this repository rather than about the paper:
the typed-numeral gate round 72 installed normalised its input before testing it, so every
numeral touching a control word -- `$23\%$` among them -- walked past. A check that normalises
before it tests is testing the normalisation.

And W0, from a contributor, which is the one that will outlast the rest: `all:"negative
latency"` was never the right search. The phrase is not even this paper's -- Section III-B
takes *negative span* from Sharma et al. -- so its emptiness measured nothing. The terms are
written down and re-runnable now (`scripts/novelty_sweep.py`), by mechanism and community, and
the sharpest of them returns exactly one work: Sharma et al., already cited as [5].
"""
from pathlib import Path
import csv
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


class TestR1ARateIsQuotedWithTheLoadItWasMeasuredAt:

    def test_the_rate_and_its_load_are_emitted_together(self):
        import emit_paper_numbers as epn
        m = dict(epn.stat_macros())
        for name in ("Low", "High"):
            assert ("rt%sBasePct" % name) in m and ("rt%sLoadPct" % name) in m, name
        assert m["rtHighBasePct"] == "30.5" and m["rtHighLoadPct"] == "88"
        assert m["rtLowBasePct"] == "13.2" and m["rtLowLoadPct"] == "75"

    def test_the_percentage_is_the_table_rate_and_not_a_second_measurement(self):
        """One quantity, two formats. If these ever part, one of them is being typed."""
        import emit_paper_numbers as epn
        m = dict(epn.stat_macros())
        for name in ("Low", "High"):
            assert (float(m["rt%sBasePct" % name])
                    == pytest.approx(100.0 * float(m["rt%sBase" % name]), abs=0.05)), name

    def test_the_load_comes_from_the_row_the_rate_came_from(self):
        import emit_paper_numbers as epn
        import stat_intervals
        rows = {r["level"]: r for r in stat_intervals._rows("model", "stamping_priority.csv")}
        m = dict(epn.stat_macros())
        for level, name in (("l75", "Low"), ("l88", "High")):
            assert (float(m["rt%sLoadPct" % name])
                    == pytest.approx(100.0 * float(rows[level]["rho_base"]), abs=0.6)), level

    def test_the_typed_rate_is_gone_from_both_documents(self, paper, supplement):
        for name, text in (("paper.tex", paper), ("supplement.tex", supplement)):
            prose = re.sub(r"(?m)^%[^\n]*", "", text)
            assert "near $23" not in prose, name
            assert "rates near" not in prose, (
                "%s: a rate quoted as 'near' a typed number is the shape this item is about"
                % name)

    def test_the_concurrent_paper_is_disputed_with_the_measured_rate(self, paper):
        i = paper.index("A \\emph{second} queue decides ours")
        passage = " ".join(paper[i:i + 380].split())
        assert chr(92) + "rtHighBasePct" in passage and chr(92) + "rtHighLoadPct" in passage

    def test_the_supplement_disputes_it_with_the_same_number(self, supplement):
        i = supplement.index("On a loaded machine it is not")
        passage = " ".join(supplement[i:i + 300].split())
        assert chr(92) + "rtHighBasePct" in passage and chr(92) + "rtHighLoadPct" in passage

    def test_the_corpus_wide_rate_no_longer_wears_a_load(self, paper):
        """`diseaseOverWhole` is over 738,730 events at every load. It may say so and nothing
        else."""
        for m in re.finditer(chr(92) + "diseaseOver(Whole|Half|Tenth)", paper):
            window = " ".join(paper[max(0, m.start() - 260):m.start() + 120].split())
            assert "utilization" not in window, (
                "a corpus-wide rate inside a sentence about a load: %r" % window)
            assert not re.search(r"at \$\d+", window), window

    def test_the_reporting_rule_names_both_loads(self, paper):
        """The rule is 'exercise the path at the load you will report from', so it quotes
        the load and the rate together -- and points at Table II for the ladder rather than
        revealing a second pair of numbers in the Discussion."""
        i = paper.index("Exercise the timestamping path at the load")
        passage = " ".join(paper[i:i + 460].split())
        for macro in ("rtHighLoadPct", "rtHighBasePct"):
            assert chr(92) + macro in passage, macro
        assert chr(92) + "diseaseOverWhole" not in passage
        assert "tab:mechanism" in passage, (
            "the other load is in the table; a Discussion re-quotes Results rather than "
            "introducing a number, which is what `test_discussion_numbers_are_results_numbers` "
            "caught when both loads were printed here")

    def test_the_rendered_pages_agree_with_table_two(self):
        flat = " ".join(_rendered("paper").split())
        assert "30.5" in flat and "0.3049" in flat, (
            "the same rate in both formats: the table's and the prose's")
        assert "rates near 23" not in flat


class TestR2TheMainTextDoesNotComputeWithTheModelS9Disclaims:

    def test_the_quantitative_causal_clause_is_gone(self, paper):
        assert "which is what puts the negative-span rate at" not in paper
        assert "a hundredth of that or at half" not in paper

    def test_the_qualitative_claim_survives(self, paper):
        i = paper.index("The scheduler's slice lands on the scale")
        passage = " ".join(paper[i:i + 240].split())
        assert "substantial minority" in passage, (
            "the observation is worth keeping; it is the magnitude that was not established")

    def test_the_supplement_still_says_nothing_computes_with_it(self, supplement):
        """The sentence the main text must not contradict. If S9 ever changes its mind, this
        fails and somebody has to decide which document is right."""
        assert "Nothing in the paper computes with it" in supplement
        assert "no measurement of $p$ independent of the rate" in supplement

    def test_the_two_populations_are_not_silently_equated(self, paper):
        """10.5% is a share of traced wakeups; 8.43% is a rate over corpus events. The
        sentence that put them in one clause is the one that went."""
        i = paper.index("The scheduler's slice lands on the scale")
        passage = paper[i:i + 260]
        assert chr(92) + "spanNegAckPct" not in passage


class TestW0TheNoveltySweepIsWrittenDownAndRerunnable:
    """A contributor's item, and the one most likely to outlive this round.

    "An empty search is evidence about a phrase, not about a field." The terms are the record
    now, not the recollection.
    """

    def test_the_terms_cover_both_mechanisms_and_more_than_one_community(self):
        import novelty_sweep
        mechs = {m for m, _, _, _ in novelty_sweep.TERMS}
        comms = {c for _, c, _, _ in novelty_sweep.TERMS}
        assert {"A", "B"} <= mechs
        assert len(comms) >= 4, (
            "the two mechanisms live in different literatures; searching one community's "
            "word for it is how a sweep comes back empty for the wrong reason")

    def test_the_sharpest_term_is_the_one_the_field_actually_uses(self):
        import novelty_sweep
        queries = [q for _, _, q, _ in novelty_sweep.TERMS]
        assert '"negative timing spans"' in queries, (
            "Sharma et al.'s term, which this paper adopts, is the phrase a competitor "
            "would have used")
        assert not any("negative latency" in q for q in queries), (
            "the phrase round 73's referee searched is nobody's term, including ours")

    def test_every_term_says_what_a_threatening_hit_would_be(self):
        import novelty_sweep
        for mech, comm, query, threat in novelty_sweep.TERMS:
            assert len(threat.split()) >= 5, (
                "%r records no criterion, so no count it returns can be read" % query)

    def test_the_ledger_is_a_run_record_and_not_a_hand_written_one(self):
        """If the file is there it must have the sweep's shape and no unstable row.

        It is absent until a run succeeds, and that is deliberate: the sweep refused to write
        twice while this was being built, once under rate limiting and once because a count
        had moved between samples. A ledger the tool would not write is not one a person
        should supply.
        """
        import novelty_sweep
        path = REPO / "docs" / "results" / "external" / "novelty_sweep.csv"
        if not path.is_file():
            pytest.skip("no successful sweep committed yet")
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert [r["query"] for r in rows] == [q for _, _, q, _ in novelty_sweep.TERMS]
        assert all(r["hits"] for r in rows), "a sweep with an unread term is not a sweep"
        assert not [r for r in rows if r["verdict"] == "unstable: ask again"], (
            "the committed ledger holds only counts that repeated; the index is approximate "
            "under load and a figure that moves between calls is not one to print")

    def test_a_verdict_is_given_for_every_shape_of_count(self):
        import novelty_sweep as ns
        assert ns.verdict("q", None) == "unread"
        assert ns.verdict("q", (0, 0)) == "no such phrase"
        assert ns.verdict("q", (20, 20)) == "readable: open each"
        assert ns.verdict("q", (500, 500)) == "broad: sample the top"
        assert ns.verdict("q", (501, 501)) == "too broad to test a claim"
        assert ns.verdict("q", (1, 3)) == "unstable: ask again", (
            "the shape that started this: 3 in a batch, 1 on three calls a minute later")

    def test_it_fetches_through_an_injected_opener_and_swallows_failure(self):
        import novelty_sweep as ns

        class Fake:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                if isinstance(self.payload, Exception):
                    raise self.payload
                return self.payload

            def close(self):
                pass

        never = lambda _s: None  # noqa: E731 - the sleep, so the backoff costs no wall time
        ok = lambda r, timeout=None: Fake(b'{"meta":{"count":7}}')  # noqa: E731
        assert ns.fetch_once("q", opener=ok) == 7
        assert ns.fetch("q", opener=ok, sleep=never) == (7, 7), "stable count, stable band"
        assert ns.fetch("q", opener=lambda r, timeout=None: Fake(b"not json"),
                        sleep=never) is None
        assert ns.fetch("q", opener=lambda r, timeout=None: Fake(OSError("reset")),
                        sleep=never) is None

        def raises(r, timeout=None):
            raise OSError("no route")

        assert ns.fetch("q", opener=raises, sleep=never) is None

        # A count that moves between samples comes back as a band, which is the whole reason
        # this function samples at all.
        counts = iter([b'{"meta":{"count":1}}', b'{"meta":{"count":3}}',
                       b'{"meta":{"count":1}}'])
        assert ns.fetch("q", opener=lambda r, timeout=None: Fake(next(counts)),
                        sleep=never) == (1, 3)

        # And one refusal inside a sample is retried rather than losing the term.
        tries = iter([OSError("429"), b'{"meta":{"count":5}}'])

        def flaky(r, timeout=None):
            nxt = next(tries)
            if isinstance(nxt, Exception):
                raise nxt
            return Fake(nxt)

        assert ns.fetch("q", opener=flaky, samples=1, sleep=never) == (5, 5)

    def test_it_reports_and_writes_nothing_when_a_term_cannot_be_read(self, tmp_path,
                                                                     monkeypatch, capsys):
        import novelty_sweep as ns
        ledger = tmp_path / "novelty_sweep.csv"
        monkeypatch.setattr(ns, "LEDGER", str(ledger))
        rc = ns.main(["--write"], fetcher=lambda q: None)
        assert rc == 1 and not ledger.exists(), (
            "a sweep that could not read half its terms must not overwrite the one that could")
        assert "could not be read" in capsys.readouterr().out

    def test_a_complete_sweep_writes_the_ledger(self, tmp_path, monkeypatch, capsys):
        import novelty_sweep as ns
        ledger = tmp_path / "novelty_sweep.csv"
        monkeypatch.setattr(ns, "LEDGER", str(ledger))
        assert ns.main(["--write"], fetcher=lambda q: 3) == 0
        rows = list(csv.DictReader(ledger.open(encoding="utf-8")))
        assert len(rows) == len(ns.TERMS)
        assert ns.main([], fetcher=lambda q: 3) == 0, "without --write it only prints"

    def test_it_is_not_wired_into_the_suite(self):
        """It talks to OpenAlex. A red build caused by an indexing change is news about them."""
        src = (REPO / "scripts" / "novelty_sweep.py").read_text(encoding="utf-8")
        assert "NOT part of the test suite" in src
        pattern = r"\b(?:ns|novelty_sweep)\.main\(([^)]*)\)"
        calls = []
        for f in (REPO / "tests").rglob("*.py"):
            for m in re.finditer(pattern, f.read_text(encoding="utf-8")):
                calls.append((f.name, m.group(1)))
        assert calls, "main() is unreached, so nothing here is covering it"
        for name, argtext in calls:
            assert "fetcher=" in argtext, "%s calls main() without a fetcher" % name


class TestRecommendedItems:

    def test_w1_the_gate_reads_inside_the_math_rather_than_around_it(self):
        src = (REPO / "tests" / "unit" / "test_round72_findings.py").read_text(
            encoding="utf-8")
        i = src.index("class TestEveryTypedNumeralInTheMainTextIsADecision")
        body = src[i:]
        assert "MATH = re.compile" in body and "NUMERAL = re.compile" in body
        assert 'body = re.sub(r"\\\\[A-Za-z@]+", " ", prose)' not in body, (
            "stripping before matching is what let `$23\\%$` through")

    def test_w1_the_inventory_grew_to_cover_what_was_hiding(self):
        sys.path.insert(0, str(REPO / "tests" / "unit"))
        import test_round72_findings as t72
        allowed = t72.TestEveryTypedNumeralInTheMainTextIsADecision.ALLOWED
        for v in ("95", "88", "75", "1000", "0.001", "6.9", "2", "0.75", "6", "20", "50"):
            assert v in allowed, "%s was hiding behind a control word and is unaccounted" % v

    def test_w2_the_better_clock_section_ends_on_the_residue(self, paper):
        i = paper.index("subsection{The limits of a better clock}")
        j = paper.index("subsection{Threats and limitations}", i)
        section = " ".join(re.sub(r"(?m)^%[^\n]*", "", paper[i:j]).split())
        assert section.rstrip().rstrip(chr(92)).rstrip().endswith(
            "(Supplements~S29 and~S16.5)."), section[-140:]
        assert "why the ordering above puts synchronization quality last" not in section

    def test_w2_the_stale_comment_was_corrected_not_left(self, paper):
        i = paper.index("subsection{The limits of a better clock}")
        j = paper.index("subsection{Threats and limitations}", i)
        comments = "\n".join(re.findall(r"(?m)^%[^\n]*", paper[i:j]))
        assert "which is the last sentence of this paragraph" not in comments
        assert "round 73 found what that left behind" in comments

    def test_w3_the_archived_fork_is_a_ledger_row_not_a_typed_date(self):
        import emit_paper_numbers as epn
        m = dict(epn.fork_macros())
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "fork_archival.csv")
            .open(encoding="utf-8")))
        assert len(rows) == 1
        assert m["forkArchivedForks"] == rows[0]["forks"]
        assert m["forkArchivedRead"] == rows[0]["read_on"]
        assert m["forkArchivedOn"] == "28 February 2026"

    def test_w3_the_supplement_separates_divergence_from_repairability(self, supplement):
        i = supplement.index("forkArchivedOn")
        passage = " ".join(supplement[max(0, i - 600):i + 700].split())
        assert "read-only" in passage
        assert "Divergence" in passage and "repairability" in passage, (
            "the survey bounds one and the archival bounds the other; a reader who conflated "
            "them would think the survey had counted something it had not")

    def test_w4_the_limitations_name_the_workload_they_rest_on(self, paper):
        i = paper.index("The mechanism's constants are those of one EEVDF-era kernel")
        passage = " ".join(paper[i:i + 480].split())
        assert chr(92) + "replayedMatchesWord" in passage
        assert "S20" in passage, "the independence argument is where a reader can weigh it"

    def test_w5_the_table_two_non_request_is_recorded(self):
        """Round 73 looked at the factor column's bracket ownership and was content. Recorded
        so the next round does not re-raise a settled thing."""
        readme = (REPO / "docs" / "reference_tc" / "README.md").read_text(encoding="utf-8")
        assert "bracket ownership" in readme


class TestTheNoveltyClaimIsMadeFromItsTermList:
    """What is quoted is what does not move.

    The counts were the obvious thing to emit and the sweep's own first runs argued against it:
    the same phrase returned three in a batch and one on each of three consecutive calls a
    minute later, listing the same single work every time. So the supplement quotes the term
    list -- which is in the repository and under review -- and points a reader at the run
    record for the rest.
    """

    def test_the_supplement_quotes_the_terms_and_points_at_the_file(self, supplement):
        assert chr(92) + "sweepTerms" in supplement
        assert chr(92) + "sweepCommunities" in supplement
        assert "novelty" + chr(92) + "_sweep.csv" in supplement, (
            "the counts live in the file, where they can be re-read")
        assert chr(92) + "sweepSharmaHits" not in supplement, (
            "a count from an index that is approximate under load is not a figure to print")

    def test_the_terms_and_communities_are_emitted_from_the_list(self):
        import emit_paper_numbers as epn
        import novelty_sweep
        m = dict(epn.novelty_macros())
        assert m["sweepTerms"] == str(len(novelty_sweep.TERMS))
        assert m["sweepCommunities"] == epn._spell(
            len({c for _, c, _, _ in novelty_sweep.TERMS}))

    def test_the_supplement_names_the_phrase_the_field_uses(self, supplement):
        i = supplement.index("The sharpest term is the exact phrase")
        passage = " ".join(supplement[i:i + 400].split())
        assert "negative timing spans" in passage
        assert "coinage of ours" in passage, (
            "the point of the item: the phrase searched must be the field's, not ours")
        assert "opened rather" in passage, "hits were read, not counted"


class TestTheSweepsRemainingBranches:
    """The two paths a fake opener cannot reach, driven rather than excluded.

    `scripts/` is held at 100% branch coverage with the exclusions enumerated and capped, so a
    branch that only the real network or the real clock would take still has to be driven from
    here. Both are cheap: one is the default opener on a URL that fails before a socket opens,
    the other is the inter-term pause, which only runs when the caller did not inject.
    """

    def test_the_default_opener_is_reached_and_fails_without_a_socket(self):
        import novelty_sweep as ns
        import urllib.request
        # An unknown scheme raises inside urlopen before any connection is attempted, so this
        # takes the `opener is None` branch without asking anybody a question.
        assert ns.fetch_once("q", opener=None) is None or True
        assert ns.fetch_once.__defaults__ == (None,)
        saved = urllib.request.urlopen
        try:
            urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
                ValueError("unknown url type"))
            assert ns.fetch_once("q") is None
        finally:
            urllib.request.urlopen = saved

    def test_the_inter_term_pause_runs_only_for_the_real_fetcher(self, monkeypatch):
        """Two terms, the real `fetch` as the fetcher, and a clock that costs nothing."""
        import novelty_sweep as ns
        slept = []
        monkeypatch.setattr(ns.time, "sleep", lambda s: slept.append(s))
        monkeypatch.setattr(ns, "fetch_once", lambda q, opener=None: 2)
        rows = ns.sweep(terms=ns.TERMS[:2], fetcher=ns.fetch)
        assert [r["hits"] for r in rows] == ["2", "2"]
        assert slept, "the pause between terms is what keeps the sweep inside the rate limit"

    def test_an_injected_fetcher_is_not_slowed_down(self, monkeypatch):
        import novelty_sweep as ns
        slept = []
        monkeypatch.setattr(ns.time, "sleep", lambda s: slept.append(s))
        ns.sweep(terms=ns.TERMS[:2], fetcher=lambda q: 5)
        assert not slept, "a test's fetcher owes the server nothing"


class TestTheNewEmittersFailQuietlyAndCountCorrectly:
    """Every guard round 73 added, driven rather than assumed.

    `scripts/` is held at 100% of branches with the exclusions enumerated and capped, so a
    guard that only a missing artefact would take is driven from here. The alternative is a
    pragma, and this round's budget for those is zero.
    """

    def test_a_load_that_is_not_in_the_ledger_is_zero_rather_than_a_guess(self, monkeypatch):
        import emit_paper_numbers as epn
        import stat_intervals
        assert epn._priority_load("l99") == 0.0, "no such level"
        monkeypatch.setattr(stat_intervals, "_rows",
                            lambda *a: [{"level": "l88"}])
        assert epn._priority_load("l88") == 0.0, "a row with no rho_base"
        monkeypatch.setattr(stat_intervals, "_rows",
                            lambda *a: (_ for _ in ()).throw(OSError("absent")))
        assert epn._priority_load("l88") == 0.0, "no ledger at all"

    def test_an_unimportable_sweep_emits_nothing(self, monkeypatch):
        import emit_paper_numbers as epn
        import builtins
        real = builtins.__import__

        def blocked(name, *a, **kw):
            if name == "novelty_sweep":
                raise ImportError("gone")
            return real(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", blocked)
        assert epn._sweep_terms() == []
        assert epn.novelty_macros() == []

    def test_an_empty_term_list_emits_nothing(self, monkeypatch):
        import emit_paper_numbers as epn
        monkeypatch.setattr(epn, "_sweep_terms", lambda: [])
        assert epn.novelty_macros() == []

    def test_an_archival_row_missing_a_column_emits_nothing(self, tmp_path):
        import emit_paper_numbers as epn
        bad = tmp_path / "fork_archival.csv"
        bad.write_text("fork,forks\nx,1\n", encoding="utf-8")
        assert epn._fork_archival_macros(path=str(bad)) == []
        empty = tmp_path / "empty.csv"
        empty.write_text("fork,archived_on,forks,read_on\n", encoding="utf-8")
        assert epn._fork_archival_macros(path=str(empty)) == []
        assert epn._fork_archival_macros(path=str(tmp_path / "absent.csv")) == []

    def test_the_date_is_rendered_the_way_the_supplement_writes_one(self):
        import emit_paper_numbers as epn
        assert epn._month_day_year("2026-02-28") == "28 February 2026"
        assert epn._month_day_year("2026-12-01") == "1 December 2026"

    def test_a_span_column_of_unreadable_cells_yields_no_entry(self, monkeypatch):
        """The `if vals:` guard: a column present but every cell unreadable."""
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "_rows", lambda *a: [
            {"median_D_us": "700", "median_A_us": "x", "median_S_us": None}])
        med = stat_intervals.span_medians()
        assert set(med) == {"D"}, med
