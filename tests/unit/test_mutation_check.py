"""Tests for mutation_check.

The script edits paper.tex in place, so the property that matters most is that it always puts it
back. The tests exercise the restore path through a failing subprocess, a passing one, and an
exception, because a harness that leaves a mutated manuscript behind is worse than no harness.

3 Nov 2026: a claim whose sentence moved to the supplement took its anchor there, so an entry may
name the document it edits beside the paper. The fixture writes each document with its anchors,
and the restore tests check every document.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mutation_check import MUTATIONS, _target, main, run  # noqa: E402

#: The documents beside the paper that some entry edits.
COMPANIONS = sorted({m[3] for m in MUTATIONS if len(m) > 3})


@pytest.fixture
def paper(tmp_path):
    p = tmp_path / "paper.tex"
    p.write_text("\n".join(m[1] for m in MUTATIONS if len(m) == 3), encoding="utf-8")
    for doc in COMPANIONS:
        (tmp_path / doc).write_text("\n".join(m[1] for m in MUTATIONS if m[3:] == (doc,)),
                                    encoding="utf-8")
    return p


def _documents(paper):
    return {f.name: f.read_text(encoding="utf-8") for f in sorted(paper.parent.glob("*.tex"))}


class TestRestore:
    def test_the_manuscript_is_restored_when_every_mutation_is_caught(self, paper, monkeypatch):
        before = _documents(paper)
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        undetected, _ = run(str(paper), "tests")
        assert undetected == []
        assert _documents(paper) == before

    def test_the_manuscript_is_restored_when_mutations_are_missed(self, paper, monkeypatch):
        before = _documents(paper)
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        undetected, _ = run(str(paper), "tests")
        assert len(undetected) == len(MUTATIONS)
        assert _documents(paper) == before

    def test_the_manuscript_is_restored_when_the_run_raises(self, paper, monkeypatch):
        """An interrupted run must not leave a mutated paper.tex on disk."""
        before = _documents(paper)

        def boom(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr("subprocess.run", boom)
        with pytest.raises(KeyboardInterrupt):
            run(str(paper), "tests")
        assert _documents(paper) == before

    def test_no_backup_file_is_left_behind(self, paper, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        run(str(paper), "tests")
        assert not list(paper.parent.glob("*.mutbak"))

    def test_each_mutation_meets_every_other_document_as_it_was(self, paper, monkeypatch):
        """A mutation of the supplement must be undone before the next one edits the paper."""
        before = _documents(paper)
        changed = []

        def record(*a, **k):
            now = _documents(paper)
            changed.append(sorted(name for name in now if now[name] != before[name]))
            return subprocess.CompletedProcess(a, 1, "", "")

        monkeypatch.setattr("subprocess.run", record)
        run(str(paper), "tests")
        assert len(changed) == len(MUTATIONS)
        assert all(len(c) == 1 for c in changed), changed


class TestAnchors:
    def test_absent_anchors_are_skipped_not_counted_as_caught(self, tmp_path, monkeypatch):
        """A reworded claim must report as skipped. Counting it as caught would be a false pass."""
        p = tmp_path / "paper.tex"
        p.write_text("nothing here matches any anchor", encoding="utf-8")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        undetected, skipped = run(str(p), "tests")
        assert undetected == []
        assert len(skipped) == len(MUTATIONS)

    def test_a_missing_companion_document_skips_its_mutations(self, paper, monkeypatch):
        """No supplement beside the paper: its mutations are skipped, which fails the run."""
        for doc in COMPANIONS:
            (paper.parent / doc).unlink()
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        undetected, skipped = run(str(paper), "tests")
        assert undetected == []
        assert skipped == [m[0] for m in MUTATIONS if len(m) > 3]

    def test_an_entry_names_the_document_beside_the_paper(self):
        assert _target(os.path.join("d", "paper.tex"), ("n", "o", "m")) == os.path.join(
            "d", "paper.tex")
        assert _target(os.path.join("d", "paper.tex"), ("n", "o", "m", "supplement.tex")) == \
            os.path.join("d", "supplement.tex")

    def test_every_mutation_actually_changes_the_text(self):
        for mutation in MUTATIONS:
            name, old, new = mutation[:3]
            assert old != new, f"{name}: mutation is a no-op"
            assert old and new, f"{name}: empty fragment"


class TestCLI:
    def test_missing_paper_is_an_error(self, tmp_path):
        assert main(["--paper", str(tmp_path / "absent.tex")]) == 1

    def test_undetected_mutation_fails_the_run(self, paper, monkeypatch, capsys):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        assert main(["--paper", str(paper), "--tests", "t"]) == 1
        assert "not guarding that claim" in capsys.readouterr().out

    def test_all_caught_passes(self, paper, monkeypatch, capsys):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        assert main(["--paper", str(paper), "--tests", "t"]) == 0
        assert "every mutation was caught" in capsys.readouterr().out

    def test_a_vanished_anchor_fails_rather_than_being_reported(
            self, tmp_path, monkeypatch, capsys):
        """It used to print SKIP and return 0, and that is how nine claims went unguarded.

        Round 72 found nine of ten anchors stale. The check had been saying so in its own
        output for some rounds -- "OK every mutation was caught (9 skipped: anchors absent)"
        -- and returning success, so nothing downstream and nobody upstream noticed. A
        mutation whose anchor is gone is an unguarded claim, and an unguarded claim is the
        thing this file exists to prevent.
        """
        p = tmp_path / "paper.tex"
        p.write_text("no anchors", encoding="utf-8")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        assert main(["--paper", str(p), "--tests", "t"]) == 1
        out = capsys.readouterr().out
        assert "anchors are gone" in out and "unguarded claim" in out
