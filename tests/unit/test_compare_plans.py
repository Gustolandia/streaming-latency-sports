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
