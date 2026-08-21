"""Tests for scripts/audit_external_harness.py - target >=95% branch coverage.

This tool produces the paper's answer to its most serious referee objection, so every verdict
it can reach is pinned against a synthetic harness whose properties are known by construction.
The real OpenMessaging finding is checked separately, against the committed artefact.
"""
import csv
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_external_harness import (  # noqa: E402
    DISCARD_COUNTER,
    classify,
    scan,
    has_discard_counter,
    verdict,
    source_files,
    main,
)


def has_discard_counter_line(line):
    """Whether a single line is evidence that discards are counted."""
    return bool(DISCARD_COUNTER.search(line))

# Cross-process subtraction, positive-only filter, no counter: the OMB shape.
EXPOSED_SILENT = """
public class Worker {
    public void onMessage(int size, long publishTimestamp) {
        long now = System.currentTimeMillis();
        long latencyMicros = TimeUnit.MILLISECONDS.toMicros(now - publishTimestamp);
        stats.record(size, latencyMicros);
    }
}
"""
FILTER_ONLY = """
public class Stats {
    public void record(long size, long endToEndLatencyMicros) {
        received.increment();
        if (endToEndLatencyMicros > 0) {
            histogram.recordValue(endToEndLatencyMicros);
        }
    }
}
"""
FILTER_WITH_COUNTER = """
public class Stats {
    public void record(long size, long endToEndLatencyMicros) {
        if (endToEndLatencyMicros > 0) {
            histogram.recordValue(endToEndLatencyMicros);
        } else {
            negativeLatencyCounter.inc();
        }
    }
}
"""
SAME_PROCESS = """
public class RoundTrip {
    public void measure() {
        long begin = System.nanoTime();
        produceAndConsume();
        long elapsed = System.nanoTime() - begin;
    }
}
"""


def _harness(tmp, **files):
    d = tmp / "harness"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    return d


class TestScan:
    def test_finds_the_cross_process_subtraction(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        hits = [f for f in scan(str(d)) if f["kind"] == "cross_process_latency"]
        assert len(hits) == 1
        assert hits[0]["file"] == "Worker.java"
        assert "publishTimestamp" in hits[0]["evidence"]

    def test_finds_the_positive_only_filter(self, temp_dir):
        d = _harness(temp_dir, **{"Stats.java": FILTER_ONLY})
        hits = [f for f in scan(str(d)) if f["kind"] == "positive_only_filter"]
        assert len(hits) == 1 and hits[0]["line"] > 0

    def test_same_process_timing_is_not_flagged(self, temp_dir):
        """A span measured inside one process cannot invert and must not be reported."""
        d = _harness(temp_dir, **{"RoundTrip.java": SAME_PROCESS})
        assert [f for f in scan(str(d)) if f["kind"] == "cross_process_latency"] == []

    def test_python_spelling_is_recognised(self, temp_dir):
        d = _harness(temp_dir, **{"w.py": "lat = time.time() - publish_timestamp\n"
                                          "if latency > 0:\n    h.record(lat)\n"})
        kinds = {f["kind"] for f in scan(str(d))}
        assert kinds == {"cross_process_latency", "positive_only_filter"}

    def test_build_directories_are_skipped(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        buried = d / "target" / "generated"
        buried.mkdir(parents=True)
        (buried / "Copy.java").write_text(EXPOSED_SILENT, encoding="utf-8")
        assert len([f for f in scan(str(d)) if f["kind"] == "cross_process_latency"]) == 1

    def test_unreadable_file_does_not_abort_the_scan(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        (d / "Broken.java").mkdir()          # a directory where a .java file is expected
        assert len(scan(str(d))) >= 1


class TestDiscardCounter:
    def test_detects_a_counter(self, temp_dir):
        d = _harness(temp_dir, **{"Stats.java": FILTER_WITH_COUNTER})
        assert has_discard_counter(str(d))

    def test_absent_when_nothing_counts_discards(self, temp_dir):
        d = _harness(temp_dir, **{"Stats.java": FILTER_ONLY})
        assert not has_discard_counter(str(d))


class TestVerdict:
    def test_exposed_and_silent(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT, "Stats.java": FILTER_ONLY})
        tag, why = verdict(scan(str(d)), has_discard_counter(str(d)))
        assert tag == "EXPOSED, AND SILENT"
        assert "conditioned on being positive" in why

    def test_exposed_but_counted(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT,
                                  "Stats.java": FILTER_WITH_COUNTER})
        tag, _ = verdict(scan(str(d)), has_discard_counter(str(d)))
        assert tag == "EXPOSED, BUT COUNTED"

    def test_exposed_not_filtered(self, temp_dir):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        tag, why = verdict(scan(str(d)), False)
        assert tag == "EXPOSED, NOT FILTERED"
        assert "at least visible" in why

    def test_not_exposed(self, temp_dir):
        d = _harness(temp_dir, **{"RoundTrip.java": SAME_PROCESS})
        tag, why = verdict(scan(str(d)), False)
        assert tag == "NOT EXPOSED"
        assert "same-process" in why


class TestSourceFiles:
    def test_only_source_extensions(self, temp_dir):
        d = _harness(temp_dir, **{"a.java": "x", "b.txt": "x", "c.py": "x"})
        names = {Path(p).name for p in source_files(str(d))}
        assert names == {"a.java", "c.py"}


class TestProvenance:
    def test_reports_nothing_outside_a_git_checkout(self, temp_dir):
        """A plain directory has no commit; the audit must degrade, not crash."""
        from audit_external_harness import provenance
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        p = provenance(str(d))
        assert set(p) == {"commit", "date", "upstream"}

    def test_survives_git_being_unavailable(self, temp_dir, monkeypatch):
        """Auditing a source tree that was never a git checkout must still produce a report."""
        import audit_external_harness as mod
        monkeypatch.setattr(mod.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
        p = mod.provenance(str(temp_dir))
        assert p == {"commit": "", "date": "", "upstream": ""}

    def test_main_omits_provenance_when_there_is_none(self, temp_dir, capsys):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        main(["--repo", str(d), "--out", str(temp_dir / "o")])
        assert "commit" not in capsys.readouterr().out


class TestUnreadableSources:
    """A harness we did not write may contain files we cannot read; the audit must not abort."""

    def test_scan_skips_unreadable_files(self, temp_dir, monkeypatch):
        import audit_external_harness as mod
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT})
        monkeypatch.setattr("builtins.open",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
        assert scan(str(d)) == []

    def test_counter_scan_skips_unreadable_files(self, temp_dir, monkeypatch):
        d = _harness(temp_dir, **{"Stats.java": FILTER_WITH_COUNTER})
        monkeypatch.setattr("builtins.open",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
        assert not has_discard_counter(str(d))


class TestMain:
    def test_end_to_end_writes_evidence(self, temp_dir, capsys):
        d = _harness(temp_dir, **{"Worker.java": EXPOSED_SILENT, "Stats.java": FILTER_ONLY})
        rc = main(["--repo", str(d), "--name", "Synthetic", "--out", str(temp_dir / "out")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "EXPOSED, AND SILENT" in out
        rows = list(csv.DictReader(open(temp_dir / "out" / "harness_audit.csv")))
        assert {r["kind"] for r in rows} == {"cross_process_latency", "positive_only_filter"}
        assert all(r["harness"] == "Synthetic" for r in rows)

    def test_missing_repository(self, temp_dir, capsys):
        assert main(["--repo", str(temp_dir / "nope")]) == 1
        assert "missing repository" in capsys.readouterr().out


class TestTheCommittedOpenMessagingFinding:
    """The real finding, pinned against the committed artefact.

    If OpenMessaging changes upstream this test still describes what we audited, because the
    paper cites a specific commit. It exists so the claim cannot drift from its evidence.
    """

    @staticmethod
    def _rows():
        p = (Path(__file__).parent.parent.parent / "docs" / "results" / "external"
             / "harness_audit.csv")
        with open(p, encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_the_cross_process_subtraction_is_recorded(self):
        cross = [r for r in self._rows() if r["kind"] == "cross_process_latency"]
        assert len(cross) == 1
        assert "LocalWorker.java" in cross[0]["file"]
        assert "now - publishTimestamp" in cross[0]["evidence"]

    def test_the_silent_filter_is_recorded(self):
        filt = [r for r in self._rows() if r["kind"] == "positive_only_filter"]
        assert len(filt) == 1
        assert "WorkerStats.java" in filt[0]["file"]
        assert "> 0" in filt[0]["evidence"]

    def test_the_evidence_is_attributable(self):
        assert all(r["harness"] == "OpenMessaging Benchmark" and int(r["line"]) > 0
                   for r in self._rows())


class TestSuppressionClass:
    """The third disposal: substitute a value and leave the sample count untouched.

    This class was added after auditing beyond the JVM. It matters more than the filter,
    because a filter at least leaves a hole in the counts; a substitution leaves an output
    that looks complete and is wrong.
    """

    def test_a_ternary_substitution_is_suppression(self):
        # blktrace btt: every inverted stage interval becomes one nanosecond.
        assert classify("return (from < to) ? (to - from) : 1;") == ["silent_suppression"]

    def test_a_sign_guard_on_a_time_variable_is_suppression(self):
        # fio: a negative interval returns zero, under a question-marked guess at the cause.
        assert classify("if (sec < 0 || (sec == 0 && nsec < 0))") == ["silent_suppression"]

    def test_a_floor_clamp_is_suppression(self):
        # Both classes, correctly: it is a cross-process subtraction *and* a clamp on the result.
        assert set(classify("v = Math.max(0, now - publishTimestamp);")) == {
            "cross_process_latency", "silent_suppression"}

    def test_a_nan_substitution_is_suppression(self):
        assert classify("latencyMs = Double.NaN;") == ["silent_suppression"]

    def test_an_ordinary_subtraction_is_not_suppression(self):
        assert "silent_suppression" not in classify("total = end - start;")

    def test_an_ordinary_ternary_is_not_suppression(self):
        assert "silent_suppression" not in classify("x = flag ? a : b;")

    def test_suppression_without_a_counter_gets_its_own_verdict(self):
        findings = [{"kind": "cross_process_latency", "file": "g.c", "line": 1, "evidence": ""},
                    {"kind": "silent_suppression", "file": "g.c", "line": 2, "evidence": ""}]
        tag, why = verdict(findings, counted=False)
        assert tag == "EXPOSED, AND REPAIRED"
        assert "nothing is missing from the output" in why

    def test_suppression_that_is_counted_falls_through_to_the_milder_verdict(self):
        findings = [{"kind": "cross_process_latency", "file": "g.c", "line": 1, "evidence": ""},
                    {"kind": "silent_suppression", "file": "g.c", "line": 2, "evidence": ""}]
        tag, _ = verdict(findings, counted=True)
        assert tag != "EXPOSED, AND REPAIRED"


class TestPatternsAddedForNonJvmSources:
    """Each of these was added because a real harness used a spelling the tool could not see."""

    def test_erlang_counter_guard_is_not_a_filter(self):
        """Round 6 caught us reporting emqtt-bench as deleting samples. Its guard gates a
        Prometheus counter, and the next source line observes the histogram unconditionally,
        so nothing is deleted. The classifier now withdraws the filter label when the guarded
        action is a counter increment -- a guard is only a deletion if what it guards is the
        sample -- and this test is the error, pinned so it cannot come back."""
        line = "E2ELatency > 0 andalso inc_counter(Prometheus, publish_latency, E2ELatency),"
        assert "positive_only_filter" not in classify(line)

    def test_erlang_short_circuit_guarding_a_record_is_still_a_filter(self):
        """The withdrawal is about the consequent, not the syntax: the same short-circuit
        guarding an observation would still delete, and must still classify."""
        line = "E2ELatency > 0 andalso histogram_observe(Prometheus, e2e_latency, E2ELatency),"
        assert "positive_only_filter" in classify(line)

    def test_erlang_system_time_subtraction_is_cross_process(self):
        assert "cross_process_latency" in classify("E2ELatency = os:system_time(millisecond) - TS,")

    def test_a_discard_metric_named_for_samples_counts_as_a_counter(self):
        # Rezolus names the noun it counts "samples", not "count".
        assert has_discard_counter_line('name = "scheduler_discarded_samples",')

    def test_an_unrelated_sample_name_is_not_a_counter(self):
        assert not has_discard_counter_line('name = "scheduler_runqueue_latency",')

    def test_c_and_erlang_sources_are_now_walked(self, tmp_path):
        (tmp_path / "a.c").write_text("return (from < to) ? (to - from) : 1;\n", encoding="utf-8")
        (tmp_path / "b.erl").write_text("X > 0 andalso ok,\n", encoding="utf-8")
        (tmp_path / "c.txt").write_text("ignored\n", encoding="utf-8")
        names = {Path(p).name for p in source_files(str(tmp_path))}
        assert names == {"a.c", "b.erl"}
