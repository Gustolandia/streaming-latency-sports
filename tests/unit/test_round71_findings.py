r"""Round 71's referee items, pinned so a later pass cannot quietly undo them.

Both required items are the same failure at opposite ends of the paper: a sentence asserting
something the project measures, and then saying it in words the measurement contradicts.

R1 was one word. The Conclusion said two timestamps are written by threads that wait for a
core *"independently"*, while Section VII-C's reporting rule says in bold that two delays with
one cause are **not** independent, at a median correlation of 0.84 and a 12.4x mispricing.
The Introduction had the right phrase two hundred lines earlier -- "on its own account" -- and
it is the same length.

R2 was two macros. Section IV-D said the send schedule is measured rather than assumed and
then printed a typed range, 67--69 us, which excludes eleven of the twenty-four runs in the
column it claims to summarise. It is emitted now, at one decimal, from `jitter_p90_us`.

W1 put the word on the vocabulary review list, and W3 built the script that checks the audited
upstream lines are still there. W3 found two things on its first run that no test had: the
Pulsar evidence had moved to another file upstream, and one row of the registry had been
spilling its own note into phantom columns since it was written.
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


class TestR1TheConclusionAgreesWithTheReportingRule:

    def test_the_conclusion_does_not_call_the_two_waits_independent(self, paper):
        i = paper.index(RE_BS[:1] + "section{Conclusion}")
        conclusion = " ".join(paper[i:].split())
        assert "wait for a core independently" not in conclusion
        assert "each wait for a core on their own account" in conclusion

    def test_it_uses_the_introductions_own_phrase(self, paper):
        """Same words in both places, so a reader meets one idea and not two."""
        assert "waits for that core on its own account" in paper

    def test_the_rule_it_was_contradicting_is_still_there_and_still_measured(self, paper):
        i = paper.index("Two delays with one cause are not independent")
        rule = " ".join(paper[i:i + 420].split())
        assert RE_BS[:1] + "spanRhoMedian" in rule
        assert RE_BS[:1] + "indepOvershoot" in rule and RE_BS[:1] + "indepConditions" in rule

    def test_the_rendered_conclusion_carries_the_fix(self):
        flat = " ".join(_rendered("paper").split())
        assert "each wait for a core on their own account" in flat
        assert "independently invert" not in flat


class TestR2ThePacerJitterIsEmitted:

    def test_the_range_is_read_from_the_column_it_summarises(self):
        import stat_intervals
        lo, hi = stat_intervals.harness_pacer_jitter()
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "harness_results.csv")
            .open(encoding="utf-8")))
        vals = [float(r["jitter_p90_us"]) for r in rows]
        assert (lo, hi) == (min(vals), max(vals))
        assert len(vals) == 24, "every run, not the ones that fit the sentence"

    def test_the_printed_range_contains_every_measured_run(self):
        """The defect, stated as the property that failed: 67--69 excluded eleven of these."""
        import emit_paper_numbers as epn
        m = dict(epn.mechanism_macros())
        lo, hi = float(m["pacerJitterLo"]), float(m["pacerJitterHi"])
        rows = list(csv.DictReader(
            (REPO / "docs" / "results" / "external" / "harness_results.csv")
            .open(encoding="utf-8")))
        outside = [r["cell"] for r in rows if not lo <= float(r["jitter_p90_us"]) <= hi]
        assert not outside, "runs outside the printed range: %s" % outside

    def test_the_sentence_no_longer_types_its_number(self, paper):
        i = paper.index("Pacer jitter is")
        sentence = paper[i:i + 160]
        assert RE_BS[:1] + "pacerJitterLo" in sentence
        assert RE_BS[:1] + "pacerJitterHi" in sentence
        assert not re.search(r"\$6\d\$", sentence), "a typed endpoint is back"

    def test_the_macros_stay_decimal_so_the_ledger_sweep_sees_them(self):
        """Integers would print a bare 67 beside interHostOffsetUs, which is also 67 and is a
        different quantity; the decimal keeps them apart and keeps these two inside the
        sweep, which only checks decimal-valued macros."""
        import emit_paper_numbers as epn
        m = dict(epn.mechanism_macros())
        for k in ("pacerJitterLo", "pacerJitterHi"):
            assert "." in m[k], "%s lost its decimal" % k

    def test_a_column_that_is_not_there_is_nothing_rather_than_a_guess(self):
        """The other percentiles are reachable by name, so a name that is not a column has
        to come back empty rather than raise or invent."""
        import stat_intervals
        assert stat_intervals.harness_pacer_jitter(percentile="p95") is None
        assert stat_intervals.harness_pacer_jitter(percentile="p50") == (62.3, 66.7)
        assert stat_intervals.harness_pacer_jitter(percentile="p99") == (68.0, 72.4)

    def test_a_row_whose_cell_is_unreadable_is_skipped_and_the_rest_still_count(
            self, tmp_path, monkeypatch):
        import stat_intervals
        monkeypatch.setattr(stat_intervals, "_rows", lambda *a: [
            {"jitter_p90_us": "66.3"}, {"jitter_p90_us": ""},
            {"jitter_p90_us": None}, {"jitter_p90_us": "69.2"}])
        assert stat_intervals.harness_pacer_jitter() == (66.3, 69.2)

    def test_the_rendered_sentence_prints_the_measured_ends(self):
        flat = " ".join(_rendered("paper").split())
        i = flat.index("Pacer jitter is")
        assert "66.3" in flat[i:i + 90] and "69.2" in flat[i:i + 90]


class TestW1TheWordIsOnTheReviewList:

    def test_the_entry_exists_and_is_the_structural_sense(self):
        import apply_vocabulary as av
        keys = dict((k, rx) for k, rx, _ in av.REVIEW)
        assert "independence" in keys
        assert "wait" in keys["independence"], (
            "the entry is scoped to the nouns the measured claim is about; the bare word "
            "would file eleven judgments about prose that needs none")

    def test_it_catches_the_sentence_r1_fixed(self, paper):
        """Mutation, not inspection: put the defect back and the gate must fire on it."""
        import apply_vocabulary as av
        bad = paper.replace("threads that each wait for a core on their own\naccount invert",
                            "threads that wait for a core independently invert")
        assert bad != paper, "the Conclusion has been reworded; retarget this mutation"
        _, _, review = av.rewrite(bad, "paper.tex", True, av.load_adjudications(), set())
        assert any("independently" in r for r in review)

    def test_it_leaves_the_separate_route_sense_alone(self, paper, supplement):
        """"Arrived at independently" is a fact about provenance, not about correlation."""
        import apply_vocabulary as av
        for name, text in (("paper.tex", paper), ("supplement.tex", supplement)):
            _, _, review = av.rewrite(text, name, True, av.load_adjudications(), set())
            assert not review, "%s: %s" % (name, review)

    def test_every_flagged_sentence_carries_a_reason(self):
        import json
        raw = json.loads((REPO / "docs" / "vocabulary_adjudications.json")
                         .read_text(encoding="utf-8"))
        ours = [j for j in raw["judgments"] if j["key"] == "independence"]
        assert len(ours) == 4
        for j in ours:
            assert len(j["reason"].split()) >= 20, "a judgment is a sentence, not a tick"

    def test_the_check_still_passes_as_a_whole(self):
        import apply_vocabulary as av
        assert av.main(["--check", "paper.tex", "supplement.tex"]) == 0


class TestW3TheAuditedLinesAreChecked:

    def test_the_script_reads_both_ledgers(self):
        import check_upstream_lines as cul
        assert [name for name, _ in cul.LEDGERS] == ["harness_audit.csv",
                                                     "harness_registry.csv"]
        assert dict(cul.LEDGERS)["harness_audit.csv"] is True, (
            "Section VI-A prints these line numbers, so a drift in them is a paper defect")

    def test_it_finds_the_repository_for_a_ledger_that_carries_no_url(self):
        import check_upstream_lines as cul
        idx = cul.repo_index()
        for row in cul.rows("harness_audit.csv"):
            assert row["file"] in idx, "%s has no repository in the registry" % row["file"]

    def test_an_exact_line_is_ok_and_a_moved_one_is_moved(self):
        import check_upstream_lines as cul
        src = "alpha\n    if (x > 0) {\nbeta\n"
        row = {"file": "a/b.java", "source_url": "https://github.com/o/r",
               "line": "2", "evidence": "if (x > 0) {"}
        assert cul.check_row(row, True, lambda u: src)[0] == "OK"
        moved = dict(row, line="7")
        status, detail = cul.check_row(moved, True, lambda u: src)
        assert status == "MOVED" and "line 2" in detail

    def test_a_quotation_that_wraps_upstream_is_present_and_not_gone(self):
        """The first run called the OpenMessaging constructor GONE. It is two lines upstream
        and one string in the ledger, which is a wrapped quotation and not a missing one."""
        import check_upstream_lines as cul
        src = "x\n    Producer(A a, B b) {\n        this(System::nanoTime, a, b);\n    }\n"
        hits = cul.locate(src, "Producer(A a, B b) { this(System::nanoTime, a, b); }")
        assert hits == [(2, 4)]

    def test_a_changed_line_is_gone_and_not_quietly_ok(self):
        import check_upstream_lines as cul
        row = {"file": "a/b.java", "source_url": "https://github.com/o/r",
               "line": "2", "evidence": "if (x > 0) {"}
        assert cul.check_row(row, True, lambda u: "nothing like it\n")[0] == "GONE"

    def test_a_forge_it_cannot_read_is_reported_and_not_skipped(self):
        import check_upstream_lines as cul
        row = {"file": "a/b.c", "source_url": "https://gitlab.com/o/r", "evidence": "x"}
        assert cul.check_row(row, False, lambda u: "x\n")[0] == "UNSUPPORTED"
        assert cul.raw_url("https://github.com/openmessaging/benchmark.git", "/a/b.c") == (
            "https://raw.githubusercontent.com/openmessaging/benchmark/HEAD/a/b.c")

    def test_it_is_not_wired_into_the_suite(self):
        """It talks to ten strangers' servers. A red build here would mean somebody else
        pushed a commit, which is news about them and not about this repository.

        The gate is not "never call `main`" -- `main` is code and code gets covered. It is
        that no call in the suite may leave the fetcher to its default, because the default
        is the network.
        """
        src = (REPO / "scripts" / "check_upstream_lines.py").read_text(encoding="utf-8")
        assert "must not become part of it" in src
        calls = []
        for f in (REPO / "tests").rglob("*.py"):
            body = f.read_text(encoding="utf-8")
            pattern = r"(?:cul|check_upstream_lines)\.main\(([^)]*)\)"
            for m in re.finditer(pattern, body):
                calls.append((f.name, m.group(1)))
        assert calls, "main() is unreached, so nothing here is covering it"
        for name, argtext in calls:
            assert "fetcher=" in argtext, (
                "%s calls main() without an injected fetcher: %r" % (name, argtext))

    def test_it_needs_no_coverage_exclusion_of_its_own(self):
        """The opener is a parameter so that both of `fetch`'s outcomes run in the suite.
        A pragma here would have been the twenty-first in `scripts/`, one past the cap
        `test_coverage_exclusions.py` sets, and that cap is the whole reason the standard is
        worth stating."""
        src = (REPO / "scripts" / "check_upstream_lines.py").read_text(encoding="utf-8")
        hidden = [ln for ln in src.splitlines()
                  if "pragma: no cover" in ln and "__main__" not in ln]
        assert not hidden, hidden

    def test_fetch_returns_the_body_and_swallows_every_failure(self):
        import check_upstream_lines as cul

        class Fake:
            def __init__(self, payload):
                self.payload = payload
                self.closed = False

            def read(self):
                if isinstance(self.payload, Exception):
                    raise self.payload
                return self.payload

            def close(self):
                self.closed = True

        got = []

        def opener(url, timeout=None):
            got.append((url, timeout))
            return Fake(b"if (x > 0) {")

        assert cul.fetch("u", opener=opener) == "if (x > 0) {"
        assert got == [("u", 30)], "the timeout is not optional when a stranger is serving"

        def raises(url, timeout=None):
            raise OSError("no route")

        assert cul.fetch("u", opener=raises) is None
        assert cul.fetch("u", opener=lambda u, timeout=None: Fake(OSError("reset"))) is None
        # And the default opener, on a URL that fails before any socket is opened.
        assert cul.fetch("not-a-url") is None


class TestW3FoundTheRegistryWasSpillingARow:

    def test_the_note_that_was_truncated_is_whole(self):
        import harness_registry as hr
        rows = [r for r in hr.load() if r["evidence"] == "if (latencyMillis >= 0) {"]
        assert len(rows) == 1
        note = rows[0]["note"]
        assert "not > 0" in note, "the clause that was lost at the first comma"
        assert "so this tool drops its inversions" in note, "and the clause after it"

    def test_a_row_that_spills_stops_the_pipeline(self, tmp_path):
        """The failure was silent: DictReader files surplus values under `None`, which no
        check written over the column names can see."""
        import harness_registry as hr
        good = (REPO / "docs" / "results" / "external" / "harness_registry.csv") \
            .read_text(encoding="utf-8")
        bad = tmp_path / "r.csv"
        lines = good.splitlines()
        lines[1] = lines[1] + ",surplus"
        bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError) as e:
            hr.load(str(bad))
        assert "more than the header" in str(e.value)

    def test_a_row_that_stops_short_stops_the_pipeline_too(self, tmp_path):
        """The other half of the same blindness: a short row gives `None` for the fields it
        never reached, and `None` reads as a value until something asks."""
        import harness_registry as hr
        good = (REPO / "docs" / "results" / "external" / "harness_registry.csv")             .read_text(encoding="utf-8")
        lines = good.splitlines()
        lines[1] = ",".join(lines[1].split(",")[:-2])
        short = tmp_path / "r.csv"
        short.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError) as e:
            hr.load(str(short))
        assert "missing value(s)" in str(e.value)

    def test_the_committed_registry_is_the_shape_of_its_header(self):
        import harness_registry as hr
        rows = hr.load()
        assert len(rows) == 18
        assert all(set(r) == set(hr.FIELDS) for r in rows)

    def test_the_pulsar_evidence_points_at_the_file_that_holds_it(self):
        """Upstream moved the computation into the shared base class. The millisecond clock
        and the non-negativity guard are unchanged, so the finding stands and the pointer
        was what went stale -- which is the distinction the script draws."""
        import harness_registry as hr
        pulsar = [r for r in hr.load() if "Pulsar" in r["harness"]]
        assert len(pulsar) == 2
        for r in pulsar:
            assert r["file"].endswith("PerformanceConsumerBase.java")
            assert r["retrieved"] == "2026-09-12"
        assert {r["clock"] for r in pulsar} == {"millisecond"}

    def test_the_relocation_did_not_change_what_the_paper_counts(self):
        """The classes are derived from the evidence, so a re-read that changes the evidence
        could move a number. This one does not, and the assertion is the proof."""
        import harness_registry as hr
        s = hr.summary()
        assert s["nonnegative_filters"] == ["Apache Pulsar perf"]
        assert s["filters"] == ["OpenMessaging Benchmark"]
        assert s["evidence_lines"] == 18 and s["harnesses"] == 10
        assert s["n_silent"] == 5 and "Apache Pulsar perf" in s["silent"]


class TestW3TheScriptIsCoveredWithoutTouchingTheNetwork:
    """Every path through it, driven by two small ledgers and a dictionary for a forge."""

    LEDGERS = {
        "harness_audit.csv":
            "harness,kind,file,line,evidence\n"
            "Tool,filter,a/Hit.java,2,if (x > 0) {\n"
            "Tool,filter,a/Moved.java,9,if (y > 0) {\n",
        "harness_registry.csv":
            "harness,vendor,language,path,clock,file,symbol,evidence,source_url,"
            "retrieved,note\n"
            "Tool,V,Java,e2e,ms,a/Hit.java,f,if (x > 0) {,https://github.com/o/r,"
            "2026-01-01,n\n"
            "Tool,V,Java,e2e,ms,a/Gone.java,f,if (z > 0) {,https://github.com/o/r,"
            "2026-01-01,n\n"
            "Tool,V,Java,e2e,ms,a/Moved.java,f,if (y > 0) {,https://github.com/o/r,"
            "2026-01-01,n\n"
            "Tool,V,Java,e2e,ms,a/Unread.java,f,q,https://github.com/o/r,"
            "2026-01-01,n\n"
            "Tool,V,Java,e2e,ms,a/Away.java,f,x,https://example.invalid/o/r,"
            "2026-01-01,n\n",
    }
    FILES = {
        "https://raw.githubusercontent.com/o/r/a/Hit.java": "pad\nif (x > 0) {\n",
        "https://raw.githubusercontent.com/o/r/a/Gone.java": "nothing like it\n",
        "https://raw.githubusercontent.com/o/r/a/Moved.java": "if (y > 0) {\npad\n",
    }

    @pytest.fixture
    def bench(self, tmp_path, monkeypatch):
        import check_upstream_lines as cul
        for name, body in self.LEDGERS.items():
            (tmp_path / name).write_text(body, encoding="utf-8")
        monkeypatch.setattr(cul, "EXTERNAL", str(tmp_path))
        seen = []

        def fetcher(url):
            seen.append(url)
            return self.FILES.get(url.replace("/HEAD/", "/"))

        return cul, fetcher, seen

    def test_it_reports_every_outcome_and_exits_nonzero(self, bench, capsys):
        cul, fetcher, _ = bench
        assert cul.main([], fetcher=fetcher) == 1
        out = capsys.readouterr().out
        for status in ("OK", "GONE", "MOVED", "UNREAD", "UNSUPPORTED"):
            assert status in out, "%s never printed" % status
        assert "no longer match upstream" in out

    def test_quiet_prints_only_what_is_wrong(self, bench, capsys):
        cul, fetcher, _ = bench
        assert cul.main(["--quiet"], fetcher=fetcher) == 1
        lines = [ln for ln in capsys.readouterr().out.splitlines()
                 if ln.startswith("   ")]
        assert lines and not any(ln.strip().startswith("OK") for ln in lines)

    def test_a_clean_run_is_silent_and_exits_zero(self, bench, capsys):
        """The only shape in which this script says nothing at all."""
        cul, _, _ = bench
        root = Path(cul.EXTERNAL)
        keep = [ln for ln in self.LEDGERS["harness_registry.csv"].splitlines()
                if "Away.java" not in ln and "Unread.java" not in ln]
        root.joinpath("harness_registry.csv").write_text(
            "\n".join(keep) + "\n", encoding="utf-8")
        keep = [ln for ln in self.LEDGERS["harness_audit.csv"].splitlines()
                if "Moved.java" not in ln]
        root.joinpath("harness_audit.csv").write_text(
            "\n".join(keep) + "\n", encoding="utf-8")
        good = dict(self.FILES)
        good["https://raw.githubusercontent.com/o/r/a/Gone.java"] = "if (z > 0) {\n"
        assert cul.main(["--quiet"],
                        fetcher=lambda u: good.get(u.replace("/HEAD/", "/"))) == 0
        assert "no longer match" not in capsys.readouterr().out

    def test_each_url_is_read_once_however_many_rows_name_it(self, bench):
        """Twenty rows over ten repositories is twenty requests unless something caches."""
        cul, fetcher, seen = bench
        cul.main([], fetcher=fetcher)
        assert len(seen) == len(set(seen))

    def test_a_ledger_that_is_not_there_is_no_rows_and_no_crash(self, bench):
        cul, _, _ = bench
        assert cul.rows("not_a_ledger.csv") == []

    def test_an_empty_quotation_matches_nothing(self):
        import check_upstream_lines as cul
        assert cul.locate("if (x > 0) {\n", "   ") == []

    def test_a_url_that_is_not_one_repository_is_rejected(self):
        import check_upstream_lines as cul
        for bad in ("https://github.com/lonely", "https://github.com/a/b/c",
                    "https://github.com//b"):
            assert cul.raw_url(bad, "a/b.c") is None, bad

    def test_a_row_whose_line_number_is_not_a_number_is_moved_not_ok(self):
        import check_upstream_lines as cul
        row = {"file": "a/b.java", "source_url": "https://github.com/o/r",
               "line": "", "evidence": "if (x > 0) {"}
        status, detail = cul.check_row(row, True, lambda u: "if (x > 0) {\n")
        assert status == "MOVED" and "no usable line number" in detail
