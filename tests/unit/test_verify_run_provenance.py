"""Tests for scripts/verify_run_provenance.py - target >=95% branch coverage.

This check exists because the paper quoted a number from a run that never happened. The tests
therefore centre on the case that matters: a file that looks like a result, carries a plausible
value, and has nothing in it to say whether any data was collected. That must come back
UNVERIFIABLE, and no amount of well-formedness may rescue it.

The check is also run against the repository's own artefacts, so a future result committed
without a sample size fails here rather than in review.
"""
import csv
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).parent.parent.parent
SCRIPTS_DIR = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from verify_run_provenance import (  # noqa: E402
    evidence_for,
    scan,
    cited_artefacts,
    main,
)


def _csv(tmp, name, rows, fields=None):
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or (list(rows[0].keys()) if rows else ["x"])
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return p


class TestEvidenceFor:
    def test_a_result_with_no_sample_size_is_unverifiable(self, temp_dir):
        """The shape the OMB zero had: a real-looking number, nothing behind it."""
        p = _csv(temp_dir, "a.csv", [{"harness": "OMB", "discarded_nonpositive": "0"}])
        verdict, detail = evidence_for(p)
        assert verdict == "UNVERIFIABLE" and "no sample-size" in detail

    def test_an_event_count_verifies(self, temp_dir):
        p = _csv(temp_dir, "b.csv", [{"rho": "0.88", "n_events": "2985"}])
        assert evidence_for(p)[0] == "VERIFIED"

    def test_a_zero_event_count_does_not_verify(self, temp_dir):
        """A count column present but zero everywhere is no evidence of a run."""
        p = _csv(temp_dir, "c.csv", [{"rho": "0.88", "n_events": "0"}])
        assert evidence_for(p)[0] == "UNVERIFIABLE"

    def test_suffixed_count_columns_are_recognised(self, temp_dir):
        """Comparisons name their counts n_runs_kafka, n_events_redis. An exact-match list
        missed all of them and called a well-provenanced artefact unverifiable."""
        p = _csv(temp_dir, "d.csv", [{"stamp": "inline", "n_runs_kafka": "10",
                                      "n_runs_redis": "10"}])
        assert evidence_for(p)[0] == "VERIFIED"

    def test_an_explicit_validity_gate_verifies(self, temp_dir):
        p = _csv(temp_dir, "e.csv", [{"valid": "1", "discarded_nonpositive": "6000"}])
        assert evidence_for(p)[0] == "VERIFIED"

    def test_a_failed_validity_gate_is_invalid(self, temp_dir):
        """valid=0 is the producing script saying the run did not happen. Never quote it."""
        p = _csv(temp_dir, "f.csv", [{"valid": "0", "reason": "no latency output"}])
        verdict, detail = evidence_for(p)
        assert verdict == "INVALID" and "valid!=1" in detail

    def test_an_empty_file_is_empty_not_verified(self, temp_dir):
        p = _csv(temp_dir, "g.csv", [], fields=["n_events"])
        assert evidence_for(p)[0] == "EMPTY"

    def test_an_unreadable_file_is_reported(self, temp_dir):
        assert evidence_for(temp_dir / "nope.csv")[0] == "UNREADABLE"

    def test_non_numeric_counts_are_ignored(self, temp_dir):
        p = _csv(temp_dir, "h.csv", [{"n_events": "many"}])
        assert evidence_for(p)[0] == "UNVERIFIABLE"


class TestScan:
    def test_missing_artefacts_are_reported(self, temp_dir):
        rows = scan(temp_dir, {"nowhere/absent.csv"})
        assert rows[0]["verdict"] == "MISSING"

    def test_a_source_audit_is_its_own_category(self, temp_dir):
        """A code audit's provenance is file+line at a commit, not a sample size. Demanding a
        run count of it is a category error."""
        _csv(temp_dir, "external/harness_audit.csv",
             [{"harness": "OMB", "file": "WorkerStats.java", "line": "95"}])
        rows = scan(temp_dir, {"external/harness_audit.csv"})
        assert rows[0]["verdict"] == "AUDIT"

    def test_a_derived_artefact_inherits_from_a_verified_source(self, temp_dir):
        _csv(temp_dir, "model/collapse_conditions.csv", [{"rho": "0.9", "n_events": "2985"}])
        _csv(temp_dir, "model/two_state_fit.csv", [{"model": "x", "r2_log": "0.99"}])
        rows = {r["artefact"]: r for r in scan(
            temp_dir, {"model/two_state_fit.csv", "model/collapse_conditions.csv"})}
        assert rows["model/two_state_fit.csv"]["verdict"] == "DERIVED"
        assert "collapse_conditions" in rows["model/two_state_fit.csv"]["detail"]

    def test_a_derived_artefact_with_an_unverified_source_stays_unverifiable(self, temp_dir):
        """Inheritance must not launder a source that itself has no provenance."""
        _csv(temp_dir, "model/collapse_conditions.csv", [{"rho": "0.9"}])
        _csv(temp_dir, "model/two_state_fit.csv", [{"model": "x", "r2_log": "0.99"}])
        rows = {r["artefact"]: r for r in scan(
            temp_dir, {"model/two_state_fit.csv", "model/collapse_conditions.csv"})}
        assert rows["model/two_state_fit.csv"]["verdict"] == "UNVERIFIABLE"

    def test_a_derived_artefact_with_a_missing_source_stays_unverifiable(self, temp_dir):
        _csv(temp_dir, "model/two_state_fit.csv", [{"model": "x", "r2_log": "0.99"}])
        rows = scan(temp_dir, {"model/two_state_fit.csv"})
        assert rows[0]["verdict"] == "UNVERIFIABLE" and "MISSING" in rows[0]["detail"]


class TestCitedArtefacts:
    def test_reads_multi_part_paths_from_the_consistency_tests(self, temp_dir):
        t = temp_dir / "t.py"
        t.write_text('_rows("football", "feed", "feed_summary.csv")\n'
                     '_rows("model", "separability.csv")\n', encoding="utf-8")
        assert cited_artefacts(t) == {"football/feed/feed_summary.csv",
                                      "model/separability.csv"}


class TestMain:
    def test_fails_on_an_artefact_that_cannot_be_trusted(self, temp_dir, capsys):
        t = temp_dir / "t.py"
        t.write_text('_rows("external", "bad.csv")\n', encoding="utf-8")
        _csv(temp_dir / "res", "external/bad.csv", [{"valid": "0", "reason": "never ran"}])
        rc = main(["--results", str(temp_dir / "res"), "--tests", str(t),
                   "--out", str(temp_dir / "prov.csv")])
        assert rc == 1 and "cannot be trusted" in capsys.readouterr().out

    def test_passes_when_everything_carries_evidence(self, temp_dir, capsys):
        t = temp_dir / "t.py"
        t.write_text('_rows("model", "good.csv")\n', encoding="utf-8")
        _csv(temp_dir / "res", "model/good.csv", [{"rho": "0.9", "n_events": "2985"}])
        rc = main(["--results", str(temp_dir / "res"), "--tests", str(t),
                   "--out", str(temp_dir / "prov.csv")])
        out = capsys.readouterr().out
        assert rc == 0 and "carries evidence" in out
        assert list(csv.DictReader(open(temp_dir / "prov.csv")))[0]["verdict"] == "VERIFIED"

    def test_reports_unverifiable_without_failing_the_run(self, temp_dir, capsys):
        """An artefact we cannot vouch for is a warning, not a broken build: the check must
        surface it while still letting the rest of the report be read."""
        t = temp_dir / "t.py"
        t.write_text('_rows("model", "thin.csv")\n', encoding="utf-8")
        _csv(temp_dir / "res", "model/thin.csv", [{"estimate": "0.41"}])
        rc = main(["--results", str(temp_dir / "res"), "--tests", str(t),
                   "--out", str(temp_dir / "prov.csv")])
        assert rc == 0 and "cannot tell" in capsys.readouterr().out

    def test_no_cited_artefacts_is_an_error(self, temp_dir, capsys):
        t = temp_dir / "t.py"
        t.write_text("nothing here\n", encoding="utf-8")
        assert main(["--results", str(temp_dir), "--tests", str(t)]) == 1
        assert "no cited artefacts" in capsys.readouterr().out


class TestTheRepositoryItself:
    def test_every_quoted_artefact_has_provenance(self, capsys):
        """The check applied to this repository. A result committed without a sample size, or a
        run that did not happen, fails here rather than in review."""
        rc = main(["--results", str(REPO / "docs" / "results"),
                   "--tests", str(REPO / "tests" / "unit" / "test_paper_consistency.py"),
                   "--out", str(REPO / "docs" / "results" / "provenance.csv")])
        out = capsys.readouterr().out
        assert rc == 0, "an artefact the paper quotes cannot be trusted as a measurement"
        assert "UNVERIFIABLE" not in out.split("== summary ==")[1]
