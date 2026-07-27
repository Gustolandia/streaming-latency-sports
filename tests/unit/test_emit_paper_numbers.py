"""Tests for emit_paper_numbers.

The manuscript's campaign counts were hand-typed in eleven places and went stale in all eleven
together: the paper said 80 runs and 420,000 discarded samples when the ledger held 108 and
4,377,904. This script exists so that number lives in exactly one place.

The tests that matter here are not the formatting ones. They are: that `--check` actually fails on
a stale file (a check that cannot fail is worse than no check), and that the script refuses to emit
numbers from an empty ledger rather than confidently writing zeroes into a manuscript.
"""
import csv
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from emit_paper_numbers import (  # noqa: E402
    HEADER, latex_thousands, macros, main, render,
)
from check_paper_omb_numbers import load_cells, measured  # noqa: E402

LEDGER_FIELDS = ("campaign", "cell", "valid", "count_source",
                 "kept", "discarded_zero", "discarded_negative")


def write_ledger(path, rows):
    """rows: (campaign, kept, discarded_zero, discarded_negative)"""
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LEDGER_FIELDS)
        for i, (camp, kept, zero, neg) in enumerate(rows):
            w.writerow([camp, "c%d" % i, "1", "shutdown_hook", kept, zero, neg])


def measured_from(path):
    return measured(load_cells(str(path)))


class TestThousandsSeparator:
    def test_short_numbers_are_untouched(self):
        assert latex_thousands(0) == "0"
        assert latex_thousands(999) == "999"

    def test_groups_are_counted_from_the_right(self):
        assert latex_thousands(1000) == "1{,}000"
        assert latex_thousands(12345) == "12{,}345"
        assert latex_thousands(123456) == "123{,}456"

    def test_millions_get_every_separator(self):
        assert latex_thousands(4377904) == "4{,}377{,}904"
        assert latex_thousands(1000000) == "1{,}000{,}000"

    def test_the_separator_is_the_brace_form_math_mode_needs(self):
        """A bare comma in math mode renders with the wrong spacing."""
        assert "," not in latex_thousands(4377904).replace("{,}", "")
        assert "{,}" in latex_thousands(4377904)


class TestMacros:
    def test_the_quantities_the_manuscript_quotes_are_all_present(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0), ("load_sweep", 30, 70, 0)])
        names = {n for n, _ in macros(measured_from(p))}
        assert {"ombRuns", "ombDiscarded", "ombKept", "ombNegatives"} <= names

    def test_values_come_from_the_ledger(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 1000, 2000, 0), ("load_sweep", 500, 1500, 0)])
        got = dict(macros(measured_from(p)))
        assert got["ombRuns"] == "2"
        assert got["ombDiscarded"] == "3{,}500"
        assert got["ombKept"] == "1{,}500"

    def test_retention_bounds_are_emitted_when_measurable(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 25, 75, 0), ("load_sweep", 90, 10, 0)])
        got = dict(macros(measured_from(p)))
        assert got["ombRetentionMin"] == "25.00"
        assert got["ombRetentionMax"] == "90.00"

    def test_retention_bounds_are_omitted_when_no_cell_saw_a_sample(self, tmp_path):
        """Emitting a bound from nothing would put a fabricated number in the manuscript."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 0, 0, 0)])
        names = {n for n, _ in macros(measured_from(p))}
        assert "ombRetentionMin" not in names
        assert "ombRetentionMax" not in names

    def test_a_negative_count_is_emitted_verbatim(self, tmp_path):
        """The section's withdrawal rests on this being zero; it must never be massaged."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 80, 7)])
        assert dict(macros(measured_from(p)))["ombNegatives"] == "7"


class TestRender:
    def test_output_is_valid_newcommands(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0)])
        text = render(measured_from(p))
        assert "\\newcommand{\\ombRuns}{1}" in text
        for line in text.splitlines():
            assert line.startswith("%") or line.startswith("\\newcommand{\\")

    def test_the_file_says_not_to_edit_it(self, tmp_path):
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0)])
        assert HEADER in render(measured_from(p))
        assert "Do not edit by hand" in render(measured_from(p))

    def test_rendering_is_deterministic(self, tmp_path):
        """--check compares text, so any instability would make it fail at random."""
        p = tmp_path / "l.csv"
        write_ledger(p, [("load_sweep", 10, 90, 0), ("resolution", 5, 5, 0)])
        assert render(measured_from(p)) == render(measured_from(p))


class TestCLI:
    def test_it_writes_the_file_and_lists_what_it_wrote(self, tmp_path, capsys):
        led, out = tmp_path / "l.csv", tmp_path / "gen" / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(out)]) == 0
        assert "\\newcommand{\\ombRuns}{1}" in out.read_text(encoding="utf-8")
        assert "ombRuns" in capsys.readouterr().out

    def test_it_creates_the_parent_directory(self, tmp_path):
        led, out = tmp_path / "l.csv", tmp_path / "a" / "b" / "c" / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(out)]) == 0
        assert out.exists()

    def test_check_passes_on_a_current_file(self, tmp_path, capsys):
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out)])
        assert main(["--ledger", str(led), "--out", str(out), "--check"]) == 0
        assert "matches the ledger" in capsys.readouterr().out

    def test_check_fails_once_the_ledger_moves(self, tmp_path, capsys):
        """The whole point: this is what catches a campaign landing after the last build."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out)])
        write_ledger(led, [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        assert main(["--ledger", str(led), "--out", str(out), "--check"]) == 1
        out_txt = capsys.readouterr().out
        assert "STALE" in out_txt and "regenerate with" in out_txt

    def test_check_writes_nothing(self, tmp_path):
        """A check that repaired the file would always pass and never report anything."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out)])
        before = out.read_text(encoding="utf-8")
        write_ledger(led, [("load_sweep", 10, 90, 0), ("load_sweep", 20, 80, 0)])
        main(["--ledger", str(led), "--out", str(out), "--check"])
        assert out.read_text(encoding="utf-8") == before

    def test_check_on_a_file_that_does_not_exist_says_how_to_make_it(self, tmp_path, capsys):
        led = tmp_path / "l.csv"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", str(led), "--out", str(tmp_path / "no.tex"), "--check"]) == 1
        assert "run without --check" in capsys.readouterr().out

    def test_crlf_in_the_committed_file_is_not_a_difference(self, tmp_path):
        """The working tree is CRLF on Windows; that must not read as a stale file."""
        led, out = tmp_path / "l.csv", tmp_path / "n.tex"
        write_ledger(led, [("load_sweep", 10, 90, 0)])
        main(["--ledger", str(led), "--out", str(out)])
        body = out.read_text(encoding="utf-8")
        with out.open("w", encoding="utf-8", newline="") as fh:
            fh.write(body.replace("\n", "\r\n"))
        assert main(["--ledger", str(led), "--out", str(out), "--check"]) == 0

    def test_a_bare_filename_needs_no_parent_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        write_ledger(tmp_path / "l.csv", [("load_sweep", 10, 90, 0)])
        assert main(["--ledger", "l.csv", "--out", "n.tex"]) == 0
        assert (tmp_path / "n.tex").exists()

    def test_a_missing_ledger_is_an_error(self, tmp_path, capsys):
        assert main(["--ledger", str(tmp_path / "no.csv"), "--out", str(tmp_path / "n.tex")]) == 1
        assert "missing" in capsys.readouterr().out

    def test_it_refuses_to_emit_from_an_empty_ledger(self, tmp_path, capsys):
        """Writing zeroes into the manuscript would be worse than failing."""
        led = tmp_path / "l.csv"
        write_ledger(led, [("smoke", 1, 1, 0)])          # not a paper campaign
        assert main(["--ledger", str(led), "--out", str(tmp_path / "n.tex")]) == 1
        assert "refusing to emit numbers from nothing" in capsys.readouterr().out
        assert not (tmp_path / "n.tex").exists()


class TestAgainstTheRealLedger:
    """The committed artefacts, checked as a pair."""

    ROOT = Path(__file__).resolve().parents[2]

    def test_the_committed_macro_file_matches_the_committed_ledger(self):
        led = self.ROOT / "docs" / "results" / "external_campaigns_index.csv"
        gen = self.ROOT / "docs" / "generated" / "paper_numbers.tex"
        if not led.exists() or not gen.exists():
            pytest.skip("ledger or generated file not present")
        want = render(measured(load_cells(str(led))))
        have = gen.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert have == want, "run python scripts/emit_paper_numbers.py and commit the result"

    def test_the_manuscript_uses_the_macros_it_is_given(self):
        paper = self.ROOT / "paper.tex"
        gen = self.ROOT / "docs" / "generated" / "paper_numbers.tex"
        if not paper.exists() or not gen.exists():
            pytest.skip("paper or generated file not present")
        src = paper.read_text(encoding="utf-8", errors="replace")
        assert "\\input{docs/generated/paper_numbers}" in src
        for name in ("ombRuns", "ombDiscarded"):
            assert ("\\" + name) in src, "%s is emitted but the manuscript ignores it" % name
