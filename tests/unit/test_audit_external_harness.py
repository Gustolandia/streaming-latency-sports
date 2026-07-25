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
    scan,
    has_discard_counter,
    verdict,
    source_files,
    main,
)

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
