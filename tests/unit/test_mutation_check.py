"""Tests for mutation_check.

The script edits paper.tex in place, so the property that matters most is that it always puts it
back. The tests exercise the restore path through a failing subprocess, a passing one, and an
exception, because a harness that leaves a mutated manuscript behind is worse than no harness.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from mutation_check import MUTATIONS, main, run  # noqa: E402


@pytest.fixture
def paper(tmp_path):
    p = tmp_path / "paper.tex"
    body = "\n".join(old for _, old, _ in MUTATIONS)
    p.write_text(body, encoding="utf-8")
    return p


class TestRestore:
    def test_the_manuscript_is_restored_when_every_mutation_is_caught(self, paper, monkeypatch):
        before = paper.read_text(encoding="utf-8")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        undetected, _ = run(str(paper), "tests")
        assert undetected == []
        assert paper.read_text(encoding="utf-8") == before

    def test_the_manuscript_is_restored_when_mutations_are_missed(self, paper, monkeypatch):
        before = paper.read_text(encoding="utf-8")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        undetected, _ = run(str(paper), "tests")
        assert len(undetected) == len(MUTATIONS)
        assert paper.read_text(encoding="utf-8") == before

    def test_the_manuscript_is_restored_when_the_run_raises(self, paper, monkeypatch):
        """An interrupted run must not leave a mutated paper.tex on disk."""
        before = paper.read_text(encoding="utf-8")

        def boom(*a, **k):
            raise KeyboardInterrupt

        monkeypatch.setattr("subprocess.run", boom)
        with pytest.raises(KeyboardInterrupt):
            run(str(paper), "tests")
        assert paper.read_text(encoding="utf-8") == before

    def test_no_backup_file_is_left_behind(self, paper, monkeypatch):
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        run(str(paper), "tests")
        assert not Path(str(paper) + ".mutbak").exists()


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

    def test_every_mutation_actually_changes_the_text(self):
        for name, old, new in MUTATIONS:
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

    def test_skips_are_reported_in_the_summary(self, tmp_path, monkeypatch, capsys):
        p = tmp_path / "paper.tex"
        p.write_text("no anchors", encoding="utf-8")
        monkeypatch.setattr("subprocess.run",
                            lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        assert main(["--paper", str(p), "--tests", "t"]) == 0
        assert "skipped" in capsys.readouterr().out
