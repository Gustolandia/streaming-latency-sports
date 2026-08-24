"""Tests for trace_table_numbers.

The script's whole value is that it is scoped. Its first version searched every committed CSV,
reported all 237 manuscript cells traced, and did not notice a wrong rho planted into tab:ea6 --
the corpus holds thousands of per-run utilisation figures, so any plausible four-decimal value
matches something. The tests that matter here are the ones that would have caught that: a value
present in a *different* artefact must not count as traced.
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from trace_table_numbers import (  # noqa: E402
    SOURCES, corpus_for, main, numbers_in, table_blocks, trace,
)

TABLE = r"""
\begin{table}[t]
\caption{A caption with 0.9999 in it, which is prose, not a cell.}
\label{tab:demo}
\begin{tabular}{rr}
\toprule
$k/C$ & rate \\
\midrule
5 & 0.0201 \\
6 & 0.0824 \\
\bottomrule
\end{tabular}
\end{table}
"""


class TestExtraction:
    def test_finds_labelled_tables(self):
        blocks = table_blocks(TABLE)
        assert [lab for lab, _ in blocks] == ["tab:demo"]

    def test_an_unlabelled_table_is_skipped(self):
        assert table_blocks(TABLE.replace(r"\label{tab:demo}", "")) == []

    def test_only_the_tabular_body_is_read(self):
        """The caption is prose. Its numbers are checked elsewhere and must not be traced here."""
        _lab, body = table_blocks(TABLE)[0]
        assert "0.0201" in body
        assert "0.9999" not in body, "the caption leaked into the cells"

    def test_structural_and_declared_values_are_not_measurements(self):
        nums = numbers_in(r"5 & 0.0201 & 40 & 0.05 \\")
        assert "0.0201" in nums
        assert "5" not in nums and "40" not in nums and "0.05" not in nums

    def test_thousands_separators_and_math_markup_are_stripped(self):
        assert "551956" in numbers_in(r"$551{,}956$ & 2\,985 \\")


class TestScoping:
    """The defect the first version had: a value found in some other artefact counted."""

    def _artefacts(self, tmp_path, right="0.0201", wrong="0.0824"):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        (tmp_path / "a" / "mine.csv").write_text(f"x\n{right}\n", encoding="utf-8")
        (tmp_path / "b" / "other.csv").write_text(f"x\n{wrong}\n", encoding="utf-8")
        return tmp_path

    def test_a_value_in_another_artefact_does_not_count(self, tmp_path):
        results = self._artefacts(tmp_path)
        report = trace(TABLE, str(results), sources={"tab:demo": ["a/mine.csv"]})
        untraced = report[0]["untraced"]
        assert "0.0201" not in untraced, "its own artefact should trace it"
        assert "0.0824" in untraced, "a value living only in another artefact must not trace"

    def test_roundings_of_the_stored_value_trace(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "mine.csv").write_text("x\n0.02010000001\n0.08240\n", encoding="utf-8")
        report = trace(TABLE, str(tmp_path), sources={"tab:demo": ["a/mine.csv"]})
        assert report[0]["untraced"] == []

    def test_a_missing_source_file_traces_nothing(self, tmp_path):
        report = trace(TABLE, str(tmp_path), sources={"tab:demo": ["absent.csv"]})
        assert set(report[0]["untraced"]) == {"0.0201", "0.0824"}

    def test_corpus_harvests_numbers_from_packed_cells(self, tmp_path):
        (tmp_path / "c.csv").write_text("law,detail\nL1,idle=0.00352;floor=0.004858\n",
                                        encoding="utf-8")
        corpus = corpus_for(str(tmp_path), ["c.csv"])
        assert "0.00352" in corpus and "0.004858" in corpus


class TestUnmapped:
    def test_an_unmapped_table_is_not_reported_as_passing(self, tmp_path):
        """"We did not look" and "we looked and it was fine" must not print the same way."""
        report = trace(TABLE, str(tmp_path), sources={})
        assert report[0]["mapped"] is False
        assert report[0]["untraced"] == []

    def test_every_declared_source_names_a_table_label(self):
        for label, paths in SOURCES.items():
            assert label.startswith("tab:"), f"{label} is not a table label"
            assert paths and all(p.endswith(".csv") for p in paths), f"{label}: bad sources"


class TestCLI:
    def test_it_never_gates_the_build(self, tmp_path, capsys):
        """Derived cells cannot be string-matched, so this is a worklist and always exits 0."""
        paper = tmp_path / "p.tex"
        paper.write_text(TABLE, encoding="utf-8")
        rc = main(["--paper", str(paper), "--results", str(tmp_path)])
        assert rc == 0
        assert "UNMAPPED" in capsys.readouterr().out

    def test_untraced_cells_carry_the_caveat(self, tmp_path, capsys):
        paper = tmp_path / "p.tex"
        paper.write_text(TABLE.replace("tab:demo", "tab:ea6"), encoding="utf-8")
        (tmp_path / "model" / "ea6").mkdir(parents=True)
        (tmp_path / "model" / "ea6" / "knee_resolution.csv").write_text("x\n0.0201\n",
                                                                       encoding="utf-8")
        main(["--paper", str(paper), "--results", str(tmp_path)])
        out = capsys.readouterr().out
        assert "FAIL tab:ea6" in out
        assert "derived quantities" in out, "an untraced cell must not read as wrong"


class TestZeroHasNoReciprocal:

    def test_the_reciprocal_roundings_are_skipped_rather_than_dividing_by_zero(self):
        """Every table number is searched for at several roundings, and ratios are often
        stored as the reciprocal of a fraction. Zero has no reciprocal, and the guard is what
        keeps a legitimate 0 in a table from crashing the trace."""
        import trace_table_numbers as ttn
        got = ttn._roundings(0.0)
        assert "0.00" in got
        assert not any(v.startswith("inf") for v in got)

    def test_a_non_zero_value_does_carry_its_reciprocal(self):
        import trace_table_numbers as ttn
        assert "4.00" in ttn._roundings(0.25)
