"""Complete tests for compare_plans.py - Target: 95%+ branch coverage."""
import pytest
import pandas as pd
import numpy as np
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from compare_plans import (
    infer_col,
    infer_match_col,
    infer_time_col,
    colsig,
    summarize_plan,
    gap_quantiles,
    by_match,
    main,
)


class TestInferCol:
    """Tests for infer_col function."""

    def test_known_column(self):
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        result = infer_col(df, ["id", "name"])
        assert result == "id"

    def test_unknown_column(self):
        df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        result = infer_col(df, ["unknown", "also_unknown"])
        assert result is None

    def test_empty_candidates(self):
        df = pd.DataFrame({"id": [1, 2]})
        result = infer_col(df, [])
        assert result is None


class TestInferMatchCol:
    """Tests for infer_match_col function."""

    def test_known_match_column(self):
        df = pd.DataFrame({"match_id": [1, 2, 3], "name": ["a", "b", "c"]})
        result = infer_match_col(df)
        assert result == "match_id"

    def test_known_game_column(self):
        df = pd.DataFrame({"game_id": [1, 2, 3], "name": ["a", "b", "c"]})
        result = infer_match_col(df)
        assert result == "game_id"

    def test_inferred_match_column(self):
        # Column contains "match" but not exact match
        df = pd.DataFrame({"matching_events": [1, 2, 3], "name": ["a", "b", "c"]})
        result = infer_match_col(df)
        assert result == "matching_events"

    def test_no_match_column(self):
        df = pd.DataFrame({"id": [1, 2, 3], "value": [10, 20, 30]})
        result = infer_match_col(df)
        assert result is None

    def test_column_with_too_many_unique(self):
        # Column has too many unique values
        df = pd.DataFrame({"id": range(10000), "value": range(10000)})
        result = infer_match_col(df)
        assert result is None


class TestInferTimeCol:
    """Tests for infer_time_col function."""

    def test_known_emit_column(self):
        df = pd.DataFrame({"emit_ts_ms": [1000, 2000, 3000], "value": [1, 2, 3]})
        result = infer_time_col(df)
        assert result == "emit_ts_ms"

    def test_known_scheduled_column(self):
        df = pd.DataFrame({"scheduled_time_ms": [1000, 2000, 3000], "value": [1, 2, 3]})
        result = infer_time_col(df)
        assert result == "scheduled_time_ms"

    def test_inferred_time_column(self):
        # Column contains "time" and is numeric
        df = pd.DataFrame({"event_time_ms": [1000, 2000, 3000], "value": [1, 2, 3]})
        result = infer_time_col(df)
        assert result == "event_time_ms"

    def test_no_time_column(self):
        df = pd.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
        result = infer_time_col(df)
        assert result is None


class TestColsig:
    """Tests for colsig function."""

    def test_basic_columns(self):
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["a", "b", "c"],
            "value": [10.0, 20.0, 30.0]
        })
        result = colsig(df)
        # "object" is the pinned spelling, not the one this pandas reports: pandas 3.0 calls
        # a text column "str". colsig normalises, so a signature recorded before the upgrade
        # still compares equal to one recorded after it.
        assert result == {"id": "int64", "name": "object", "value": "float64"}

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = colsig(df)
        assert result == {}


class TestSummarizePlan:
    """Tests for summarize_plan function."""

    def test_basic_summary(self, temp_dir):
        df = pd.DataFrame({
            "match_id": [1, 1, 2, 2],
            "emit_ts_ms": [1000, 2000, 3000, 4000]
        })
        
        path = temp_dir / "test.csv"
        df.to_csv(path, index=False)
        
        overview, match_col, time_col = summarize_plan("test", path, df)
        
        assert match_col == "match_id"
        assert time_col == "emit_ts_ms"
        assert overview["n_rows"] == 4
        assert overview["n_cols"] == 2
        assert overview["n_matches"] == 2
        assert overview["time_min"] == 1000.0
        assert overview["time_max"] == 4000.0
        assert overview["time_span"] == 3000.0

    def test_no_match_column(self, temp_dir):
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "emit_ts_ms": [1000, 2000, 3000]
        })
        
        path = temp_dir / "test.csv"
        df.to_csv(path, index=False)
        
        overview, match_col, time_col = summarize_plan("test", path, df)
        
        assert match_col is None
        assert time_col == "emit_ts_ms"
        assert overview["n_matches"] is None or pd.isna(overview["n_matches"])

    def test_no_time_column(self, temp_dir):
        df = pd.DataFrame({
            "match_id": [1, 1, 2, 2],
            "value": [10, 20, 30, 40]
        })
        
        path = temp_dir / "test.csv"
        df.to_csv(path, index=False)
        
        overview, match_col, time_col = summarize_plan("test", path, df)
        
        assert match_col == "match_id"
        assert time_col is None
        assert pd.isna(overview["time_min"])
        assert pd.isna(overview["time_max"])
        assert pd.isna(overview["time_span"])


class TestGapQuantiles:
    """Tests for gap_quantiles function."""

    def test_basic_gaps(self):
        df = pd.DataFrame({"time": [1000, 2000, 3000, 4000, 5000]})
        result = gap_quantiles(df, "test", "time")
        
        assert result is not None
        assert result["plan"] == "test"
        assert result["time_col"] == "time"
        assert result["n_gaps"] == 4
        assert result["gap_mean"] == 1000.0
        assert result["gap_q00"] == 1000.0
        assert result["gap_q100"] == 1000.0

    def test_non_numeric_column(self):
        df = pd.DataFrame({"time": ["a", "b", "c"]})
        result = gap_quantiles(df, "test", "time")
        assert result is None

    def test_empty_dataframe(self):
        df = pd.DataFrame({"time": []})
        result = gap_quantiles(df, "test", "time")
        assert result is None

    def test_single_row(self):
        df = pd.DataFrame({"time": [1000]})
        result = gap_quantiles(df, "test", "time")
        assert result is None  # No gaps with single row


class TestByMatch:
    """Tests for by_match function."""

    def test_basic_grouping(self):
        df = pd.DataFrame({
            "match_id": [1, 1, 2, 2, 2],
            "time": [1000, 2000, 3000, 4000, 5000]
        })
        result = by_match(df, "test", "match_id", "time")
        
        assert result is not None
        assert len(result) == 2  # Two unique match_ids
        assert "plan" in result.columns
        assert "match_id" in result.columns
        assert "n_rows" in result.columns
        assert "span" in result.columns

    def test_no_match_column(self):
        df = pd.DataFrame({"time": [1000, 2000, 3000]})
        result = by_match(df, "test", None, "time")
        # When match_col is None, it returns None
        assert result is None

    def test_no_time_column(self):
        df = pd.DataFrame({"match_id": [1, 1, 2]})
        result = by_match(df, "test", "match_id", None)
        assert result is not None
        assert "span" not in result.columns

    def test_empty_dataframe(self):
        df = pd.DataFrame({"match_id": [], "time": []})
        result = by_match(df, "test", "match_id", "time")
        assert result is not None
        assert len(result) == 0


class TestMain:
    """The driver: four artefacts, and the inference results carried into all of them.

    `main` was the largest untested block in the project -- seventy statements that wrote four
    files nobody had ever watched it write. Nothing here mocks the writing: the files are read
    back, because the failure this guards against is a comparison that runs cleanly and puts
    the wrong thing on disk.
    """

    @staticmethod
    def _plan(path, rows):
        pd.DataFrame(rows).to_csv(path, index=False)
        return str(path)

    @staticmethod
    def _rows(match_ids=(1, 1, 2), times=(0.0, 10.0, 20.0)):
        return {"match_id": list(match_ids), "emit_ts_ms": list(times)}

    def test_it_writes_all_four_artefacts(self, tmp_path, capsys):
        a = self._plan(tmp_path / "a.csv", self._rows())
        b = self._plan(tmp_path / "b.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out)])
        for name in ("plan_compare_overview.csv", "plan_compare_columns.txt",
                     "plan_compare_gap_quantiles.csv", "plan_compare_by_match.csv"):
            assert (out / name).exists(), name
        assert "Wrote:" in capsys.readouterr().out

    def test_the_output_directory_is_created(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        main(["--a", a, "--b", a, "--outdir", str(tmp_path / "deep" / "down")])
        assert (tmp_path / "deep" / "down").is_dir()

    def test_a_missing_plan_a_stops_the_run(self, tmp_path):
        b = self._plan(tmp_path / "b.csv", self._rows())
        with pytest.raises(SystemExit, match="Missing plan A"):
            main(["--a", str(tmp_path / "gone.csv"), "--b", b,
                  "--outdir", str(tmp_path / "out")])

    def test_a_missing_plan_b_stops_the_run(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        with pytest.raises(SystemExit, match="Missing plan B"):
            main(["--a", a, "--b", str(tmp_path / "gone.csv"),
                  "--outdir", str(tmp_path / "out")])

    def test_the_overview_carries_one_row_per_plan_under_the_names_given(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        b = self._plan(tmp_path / "b.csv", self._rows(match_ids=(3, 4, 5)))
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out),
              "--name-a", "baseline", "--name-b", "padded"])
        overview = pd.read_csv(out / "plan_compare_overview.csv")
        assert list(overview["plan"]) == ["baseline", "padded"]
        assert list(overview["n_matches"]) == [2, 3]

    def test_the_column_report_names_what_differs_between_the_plans(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", {"match_id": [1], "emit_ts_ms": [0.0],
                                            "only_in_a": [1]})
        b = self._plan(tmp_path / "b.csv", {"match_id": [1], "emit_ts_ms": [0.0],
                                            "only_in_b": [1]})
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out)])
        report = (out / "plan_compare_columns.txt").read_text()
        assert "Columns only in A (1): ['only_in_a']" in report
        assert "Columns only in B (1): ['only_in_b']" in report
        assert "Inferred A match_col=match_id, time_col=emit_ts_ms" in report

    def test_a_shared_column_with_a_different_dtype_is_reported(self, tmp_path):
        """Same name, different type is the difference most likely to be missed by eye."""
        a = self._plan(tmp_path / "a.csv", {"match_id": [1], "emit_ts_ms": [0.0]})
        b = self._plan(tmp_path / "b.csv", {"match_id": [1], "emit_ts_ms": ["x"]})
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out)])
        report = (out / "plan_compare_columns.txt").read_text()
        assert "dtype differences (1)" in report
        assert "emit_ts_ms" in report.split("dtype differences")[1]

    def test_gap_quantiles_are_written_for_both_plans(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        b = self._plan(tmp_path / "b.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out)])
        gaps = pd.read_csv(out / "plan_compare_gap_quantiles.csv")
        assert len(gaps) == 2
        assert set(gaps.columns) >= {"gap_mean", "gap_q50", "gap_q99", "n_gaps"}

    def test_a_plan_with_no_time_column_contributes_no_gaps(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        b = self._plan(tmp_path / "b.csv", {"match_id": [1, 2]})
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out)])
        assert len(pd.read_csv(out / "plan_compare_gap_quantiles.csv")) == 1

    def test_a_single_row_plan_yields_no_gap_row(self, tmp_path):
        """One timestamp has no interval; a gap table row for it would be fabricated."""
        a = self._plan(tmp_path / "a.csv", {"match_id": [1], "emit_ts_ms": [0.0]})
        out = tmp_path / "out"
        main(["--a", a, "--b", a, "--outdir", str(out)])
        gaps = pd.read_csv(out / "plan_compare_gap_quantiles.csv")
        assert gaps.empty

    def test_the_by_match_table_concatenates_both_plans(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        b = self._plan(tmp_path / "b.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out),
              "--name-a", "one", "--name-b", "two"])
        by = pd.read_csv(out / "plan_compare_by_match.csv")
        assert set(by["plan"]) == {"one", "two"}

    def test_only_plan_b_having_matches_still_produces_a_table(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", {"value": [1.0, 2.0]})
        b = self._plan(tmp_path / "b.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", b, "--outdir", str(out), "--name-b", "two"])
        by = pd.read_csv(out / "plan_compare_by_match.csv")
        assert set(by["plan"]) == {"two"}

    def test_neither_plan_having_matches_writes_an_empty_table_not_nothing(self, tmp_path):
        """A missing file and an empty result are different findings; the caller reads a file."""
        a = self._plan(tmp_path / "a.csv", {"value": [1.0, 2.0]})
        out = tmp_path / "out"
        main(["--a", a, "--b", a, "--outdir", str(out)])
        by = pd.read_csv(out / "plan_compare_by_match.csv")
        assert by.empty
        assert list(by.columns) == ["plan", "match_id", "n_rows"]

    def test_the_default_names_are_used_when_none_are_given(self, tmp_path):
        a = self._plan(tmp_path / "a.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", a, "--outdir", str(out)])
        overview = pd.read_csv(out / "plan_compare_overview.csv")
        assert list(overview["plan"]) == ["plan_a", "plan_b"]

    def test_it_prints_the_path_of_every_file_it_wrote(self, tmp_path, capsys):
        a = self._plan(tmp_path / "a.csv", self._rows())
        out = tmp_path / "out"
        main(["--a", a, "--b", a, "--outdir", str(out)])
        printed = capsys.readouterr().out
        for name in ("plan_compare_overview.csv", "plan_compare_columns.txt",
                     "plan_compare_gap_quantiles.csv", "plan_compare_by_match.csv"):
            assert name in printed


class TestTheInferenceCornersThatDecideAWholeComparison:
    """Three paths that change which columns the comparison is about.

    Column inference is the part of this tool with no visible failure: it picks the wrong
    column, everything downstream runs, and the report describes a comparison nobody asked
    for. These are the branches where it chooses to keep looking.
    """

    def test_an_unusable_match_like_column_does_not_stop_the_search(self):
        """A constant 'game_phase' must not shadow a real identifier further along."""
        df = pd.DataFrame({"game_phase": ["first"] * 6,
                           "fixture_ref": [1, 1, 2, 2, 3, 3]})
        assert infer_match_col(df) == "fixture_ref"

    def test_every_match_like_column_being_unusable_yields_none(self):
        """Guessing here would be worse than declining to guess."""
        df = pd.DataFrame({"game_phase": ["a"] * 4, "match_note": ["x"] * 4})
        assert infer_match_col(df) is None

    def test_a_time_like_column_outside_the_known_names_is_found(self):
        """The candidate list cannot enumerate every harness; the fallback is what catches
        a plan written by a tool we have not seen."""
        df = pd.DataFrame({"match_id": [1, 2], "kickoff_scheduled_at": [1.0, 2.0]})
        assert infer_time_col(df) == "kickoff_scheduled_at"

    def test_a_time_like_column_that_is_not_numeric_is_not_a_time_column(self):
        df = pd.DataFrame({"emit_label": ["early", "late"]})
        assert infer_time_col(df) is None

    def test_a_time_column_with_no_values_reports_no_span_rather_than_zero(self, tmp_path):
        """A span of 0.0 would read as 'all events at once'. There were no events."""
        df = pd.DataFrame({"match_id": [1, 2], "emit_ts_ms": [np.nan, np.nan]})
        overview, _, time_col = summarize_plan("p", tmp_path / "p.csv", df)
        assert time_col == "emit_ts_ms"
        assert np.isnan(overview["time_min"])
        assert np.isnan(overview["time_max"])
        assert np.isnan(overview["time_span"])
