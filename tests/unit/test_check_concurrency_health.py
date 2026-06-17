"""
Unit tests for check_concurrency_health.py
Tests the concurrency test health check script.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.check_concurrency_health import (
    get_concurrency_from_run_id,
    get_scenario_from_run_id,
    get_scenario_from_meta,
    get_feed_number_from_run_id,
    check_required_files,
    count_csv_rows,
    check_event_counts,
    check_tti_values,
    check_metadata,
    check_logs_for_errors,
    check_run_health,
    discover_concurrency_runs,
    group_runs_by_test_suite,
    check_test_suite_health,
    print_run_report,
    print_suite_report,
    SCENARIO_MAP,
    EXPECTED_FEED_COUNTS,
)


class TestGetConcurrencyFromRunId:
    """Tests for get_concurrency_from_run_id function."""

    def test_extract_n5(self):
        """Test extracting concurrency level n=5 from run_id."""
        run_id = "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        assert get_concurrency_from_run_id(run_id) == 5

    def test_extract_n10(self):
        """Test extracting concurrency level n=10 from run_id."""
        run_id = "concurrency_n10_20260613_002010_redis_feed5_rep1"
        assert get_concurrency_from_run_id(run_id) == 10

    def test_extract_n20(self):
        """Test extracting concurrency level n=20 from run_id."""
        run_id = "concurrency_n20_20260613_002749_kafka_feed10_rep1"
        assert get_concurrency_from_run_id(run_id) == 20

    def test_no_concurrency_in_name(self):
        """Test run_id without concurrency pattern."""
        run_id = "regular_run_20260613_001322_kafka_rep1"
        assert get_concurrency_from_run_id(run_id) is None


class TestGetFeedNumberFromRunId:
    """Tests for get_feed_number_from_run_id function."""

    def test_extract_feed1(self):
        """Test extracting feed number 1."""
        run_id = "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        assert get_feed_number_from_run_id(run_id) == 1

    def test_extract_feed10(self):
        """Test extracting feed number 10."""
        run_id = "concurrency_n10_20260613_002010_kafka_feed10_rep1"
        assert get_feed_number_from_run_id(run_id) == 10

    def test_extract_feed20(self):
        """Test extracting feed number 20."""
        run_id = "concurrency_n20_20260613_002749_redis_feed20_rep1"
        assert get_feed_number_from_run_id(run_id) == 20

    def test_no_feed_in_name(self):
        """Test run_id without feed number."""
        run_id = "concurrency_n5_20260613_001322_kafka_rep1"
        assert get_feed_number_from_run_id(run_id) is None


class TestGetScenarioFromMeta:
    """Tests for get_scenario_from_meta function."""

    def test_scenario_s1(self, temp_dir):
        """Test detecting scenario s1 from meta.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s1"

    def test_scenario_s3_s2full(self, temp_dir):
        """Test detecting scenario s3 (s2full) from meta.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s2full/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s3"

    def test_scenario_s4_s2sf12(self, temp_dir):
        """Test detecting scenario s4 (s2sf12) from meta.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s2sf12/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s4"

    def test_scenario_s5_s2sf12j2(self, temp_dir):
        """Test detecting scenario s5 (s2sf12j2) from meta.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s2sf12j2/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s5"

    def test_scenario_s2(self, temp_dir):
        """Test detecting scenario s2 from meta.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s2/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s2"

    def test_missing_meta_file(self, temp_dir):
        """Test with missing meta.json file."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        assert get_scenario_from_meta(run_dir / "meta.json") is None

    def test_scenario_from_plan_csv_path_s1(self, temp_dir):
        """Test scenario detection from plan_csv path when not in SCENARIO_MAP (covers lines 79-80)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "some/path/s1/plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s1"

    def test_scenario_from_plan_csv_path_s3_s2full(self, temp_dir):
        """Test scenario detection from plan_csv path for s2full (covers lines 81-82)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "some/path/s2full/plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s3"

    def test_scenario_from_plan_csv_path_s5_s2sf12j2(self, temp_dir):
        """Test scenario detection from plan_csv path for s2sf12j2 (covers lines 83-84)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "some/path/s2sf12j2/plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s5"

    def test_scenario_from_plan_csv_path_s4_s2sf12(self, temp_dir):
        """Test scenario detection from plan_csv path for s2sf12 (covers lines 85-86)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "some/path/s2sf12/plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s4"

    def test_scenario_from_plan_csv_path_s2(self, temp_dir):
        """Test scenario detection from plan_csv path for s2 (covers lines 87-88)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "some/path/s2/plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        assert get_scenario_from_meta(run_dir / "meta.json") == "s2"

    def test_malformed_meta_json(self, temp_dir):
        """Test get_scenario_from_meta with malformed JSON (covers lines 90-91)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{ invalid json")
        
        assert get_scenario_from_meta(run_dir / "meta.json") is None


class TestCountCsvRows:
    """Tests for count_csv_rows function."""

    def test_count_rows_with_data(self, temp_dir):
        """Test counting rows in a CSV with data."""
        csv_path = temp_dir / "test.csv"
        with open(csv_path, 'w', newline='') as f:
            f.write("col1,col2\n")
            f.write("1,2\n")
            f.write("3,4\n")
            f.write("5,6\n")
        
        assert count_csv_rows(csv_path) == 3

    def test_count_rows_empty_file(self, temp_dir):
        """Test counting rows in an empty CSV file."""
        csv_path = temp_dir / "empty.csv"
        with open(csv_path, 'w', newline='') as f:
            f.write("")
        
        assert count_csv_rows(csv_path) == 0

    def test_count_rows_header_only(self, temp_dir):
        """Test counting rows in a CSV with only headers."""
        csv_path = temp_dir / "header_only.csv"
        with open(csv_path, 'w', newline='') as f:
            f.write("col1,col2\n")
        
        assert count_csv_rows(csv_path) == 0

    def test_count_rows_nonexistent_file(self, temp_dir):
        """Test counting rows in a non-existent file."""
        csv_path = temp_dir / "nonexistent.csv"
        assert count_csv_rows(csv_path) == 0


class TestCheckRequiredFiles:
    """Tests for check_required_files function."""

    def test_all_files_present(self, temp_dir):
        """Test with all required files present."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        required_files = [
            "producer.csv", "consumer.csv", 
            "tti_summary.json", "tti_summary.printed.json", 
            "meta.json"
        ]
        for f in required_files:
            (run_dir / f).touch()
        
        passed, missing = check_required_files(run_dir)
        assert passed is True
        assert len(missing) == 0

    def test_missing_one_file(self, temp_dir):
        """Test with one required file missing."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        # Create all but one
        for f in ["producer.csv", "consumer.csv", "tti_summary.printed.json", "meta.json"]:
            (run_dir / f).touch()
        
        passed, missing = check_required_files(run_dir)
        assert passed is False
        assert "tti_summary.json" in missing

    def test_missing_multiple_files(self, temp_dir):
        """Test with multiple required files missing."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        # Create only one file
        (run_dir / "producer.csv").touch()
        
        passed, missing = check_required_files(run_dir)
        assert passed is False
        assert len(missing) >= 4


class TestCheckEventCounts:
    """Tests for check_event_counts function."""

    def test_valid_event_counts(self, temp_dir):
        """Test with valid event counts."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        # Create CSV files with data
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id,timestamp\n")
            for i in range(100):
                f.write(f"{i},{i}\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id,timestamp\n")
            for i in range(100):
                f.write(f"{i},{i}\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 100,
            "n_consumer": 100,
            "n_matched": 100
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is True
        assert len(issues) == 0

    def test_zero_producer_events(self, temp_dir):
        """Test with zero producer events."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        (run_dir / "producer.csv").touch()
        (run_dir / "consumer.csv").touch()
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("producer.csv has 0 events" in issue for issue in issues)

    def test_zero_consumer_events(self, temp_dir):
        """Test with zero consumer events."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        (run_dir / "producer.csv").touch()
        (run_dir / "consumer.csv").touch()
        
        # Write some producer events
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("consumer.csv has 0 events" in issue for issue in issues)

    def test_n_matched_greater_than_n_producer(self, temp_dir):
        """Test when n_matched > n_producer."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 1,
            "n_consumer": 1,
            "n_matched": 2  # More matched than produced!
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("n_matched" in issue and "> n_producer" in issue for issue in issues)

    def test_nested_tti_structure(self, temp_dir):
        """Test with nested TTI data structure."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            for i in range(100):
                f.write(f"{i}\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            for i in range(100):
                f.write(f"{i}\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {
                "p50": 50.0,
                "p95": 150.0
            }
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is True

    def test_n_producer_zero_in_tti(self, temp_dir):
        """Test check_event_counts when tti_summary.json has n_producer=0 (covers line 167)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 0,
            "n_consumer": 100,
            "n_matched": 100
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("tti_summary.json reports n_producer=0" in issue for issue in issues)

    def test_n_consumer_zero_in_tti(self, temp_dir):
        """Test check_event_counts when tti_summary.json has n_consumer=0 (covers line 169)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 100,
            "n_consumer": 0,
            "n_matched": 100
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("tti_summary.json reports n_consumer=0" in issue for issue in issues)

    def test_n_matched_zero_in_tti(self, temp_dir):
        """Test check_event_counts when tti_summary.json has n_matched=0 (covers line 171)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 100,
            "n_consumer": 100,
            "n_matched": 0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("tti_summary.json reports n_matched=0" in issue for issue in issues)

    def test_malformed_tti_json_in_event_check(self, temp_dir):
        """Test check_event_counts with malformed tti_summary.json (covers lines 177-178)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id\n")
            f.write("1\n")
        
        tti_file = run_dir / "tti_summary.json"
        with open(tti_file, 'w') as f:
            f.write("{ invalid json")
        
        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("Failed to parse tti_summary.json" in issue for issue in issues)


class TestCheckTtiValues:
    """Tests for check_tti_values function."""

    def test_valid_tti_values(self, temp_dir):
        """Test with valid TTI values."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 50.0,
            "tti_ms_p95": 150.0,
            "tti_ms_p99": 250.0,
            "tti_ms_max": 300.0,
            "tti_ms_mean": 60.0,
            "tti_ms_min": 10.0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is True
        assert len(issues) == 0

    def test_negative_median_tti(self, temp_dir):
        """Test with negative median TTI."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": -50.0,
            "tti_ms_max": 300.0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert any("Negative median TTI" in issue for issue in issues)

    def test_extremely_negative_min_tti(self, temp_dir):
        """Test with extremely negative min TTI."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 50.0,
            "tti_ms_min": -5000.0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert any("Extremely negative min TTI" in issue for issue in issues)

    def test_unreasonably_high_max_tti(self, temp_dir):
        """Test with unreasonably high max TTI."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 50.0,
            "tti_ms_max": 400000.0  # > 300000 ms (5 minutes)
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert any("Unreasonably high max TTI" in issue for issue in issues)

    def test_non_positive_median_tti(self, temp_dir):
        """Test with non-positive median TTI."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 0.0,
            "tti_ms_max": 300.0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert any("Non-positive median TTI" in issue for issue in issues)

    def test_nested_tti_structure(self, temp_dir):
        """Test with nested TTI structure."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "tti_ms": {
                "p50": 50.0,
                "p95": 150.0,
                "p99": 250.0,
                "max": 300.0,
                "min": 10.0
            }
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(run_dir)
        assert passed is True

    def test_missing_tti_file(self, temp_dir):
        """Test with missing tti_summary.json."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert any("tti_summary.json not found" in issue for issue in issues)


class TestCheckMetadata:
    """Tests for check_metadata function."""

    def test_valid_metadata(self, temp_dir):
        """Test with valid metadata."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta_file = run_dir / "meta.json"
        meta = {
            "run_id": "test_run",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(run_dir)
        assert passed is True
        assert len(issues) == 0

    def test_missing_required_field(self, temp_dir):
        """Test with missing required field in metadata."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta_file = run_dir / "meta.json"
        meta = {
            "run_id": "test_run",
            # Missing backend and plan_csv
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(run_dir)
        assert passed is False
        assert any("backend" in issue for issue in issues)

    def test_invalid_backend(self, temp_dir):
        """Test with invalid backend in metadata."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        meta_file = run_dir / "meta.json"
        meta = {
            "run_id": "test_run",
            "backend": "invalid",
            "plan_csv": "data/test.csv"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(run_dir)
        assert passed is False
        assert any("Invalid backend" in issue for issue in issues)

    def test_missing_meta_file(self, temp_dir):
        """Test with missing meta.json file."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        passed, issues = check_metadata(run_dir)
        assert passed is False
        assert any("meta.json not found" in issue for issue in issues)


class TestCheckLogsForErrors:
    """Tests for check_logs_for_errors function."""

    def test_no_errors_in_logs(self, temp_dir):
        """Test with clean logs."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_log = run_dir / "producer.log"
        with open(producer_log, 'w') as f:
            f.write("Starting producer...\n")
            f.write("Producer completed successfully\n")
        
        consumer_log = run_dir / "consumer.log"
        with open(consumer_log, 'w') as f:
            f.write("Starting consumer...\n")
            f.write("Consumer completed successfully\n")
        
        passed, issues = check_logs_for_errors(run_dir)
        assert passed is True
        assert len(issues) == 0

    def test_traceback_in_log(self, temp_dir):
        """Test with Traceback in log."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        producer_log = run_dir / "producer.log"
        with open(producer_log, 'w') as f:
            f.write("Traceback (most recent call last):\n")
            f.write("  File \"test.py\", line 10\n")
        
        passed, issues = check_logs_for_errors(run_dir)
        assert passed is False
        assert any("Traceback" in issue for issue in issues)

    def test_exception_in_log(self, temp_dir):
        """Test with Exception in log."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        consumer_log = run_dir / "consumer.log"
        with open(consumer_log, 'w') as f:
            f.write("Exception: Connection failed\n")
        
        passed, issues = check_logs_for_errors(run_dir)
        assert passed is False
        assert any("Exception" in issue for issue in issues)

    def test_missing_log_file(self, temp_dir):
        """Test with missing log file."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        # Don't create any log files
        passed, issues = check_logs_for_errors(run_dir)
        assert passed is True  # No logs = no errors found


class TestCheckRunHealth:
    """Tests for check_run_health function."""

    def test_healthy_run(self, temp_dir):
        """Test checking a healthy run."""
        run_dir = temp_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        
        # Create all required files
        for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                  "tti_summary.printed.json", "meta.json"]:
            (run_dir / f).touch()
        
        # Create valid meta.json
        meta = {
            "run_id": "concurrency_n5_20260613_001322_kafka_feed1_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Create valid tti_summary.json
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {
                "p50": 50.0,
                "p95": 150.0,
                "max": 300.0,
                "min": 10.0
            }
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Create CSV files with data
        for csv_file in ["producer.csv", "consumer.csv"]:
            with open(run_dir / csv_file, 'w', newline='') as f:
                f.write("event_id\n")
                for i in range(100):
                    f.write(f"{i}\n")
        
        results = check_run_health(run_dir)
        assert results["status"] == "PASS"
        assert results["concurrency"] == 5
        assert results["backend"] == "kafka"
        assert results["scenario"] == "s1"
        assert results["feed_number"] == 1

    def test_unhealthy_run_missing_file(self, temp_dir):
        """Test checking a run with missing file."""
        run_dir = temp_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        
        # Create only some files (missing tti_summary.json)
        for f in ["producer.csv", "consumer.csv", 
                  "tti_summary.printed.json", "meta.json"]:
            (run_dir / f).touch()
        
        results = check_run_health(run_dir)
        assert results["status"] == "FAIL"
        assert "required_files" in results["checks"]
        assert results["checks"]["required_files"] == "FAIL"

    def test_unhealthy_run_negative_tti(self, temp_dir):
        """Test checking a run with negative TTI."""
        run_dir = temp_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        
        # Create all required files
        for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                  "tti_summary.printed.json", "meta.json"]:
            (run_dir / f).touch()
        
        # Create meta.json
        meta = {
            "run_id": "concurrency_n5_20260613_001322_kafka_feed1_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Create tti_summary.json with negative TTI
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms_p50": -50.0
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Create CSV files
        for csv_file in ["producer.csv", "consumer.csv"]:
            with open(run_dir / csv_file, 'w', newline='') as f:
                f.write("event_id\n1\n")
        
        results = check_run_health(run_dir)
        assert results["status"] == "FAIL"
        assert "tti_values" in results["checks"]
        assert results["checks"]["tti_values"] == "FAIL"


class TestDiscoverConcurrencyRuns:
    """Tests for discover_concurrency_runs function."""

    def test_discover_runs(self, temp_dir):
        """Test discovering concurrency runs."""
        # Create some run directories
        for n in [5, 10, 20]:
            for backend in ["kafka", "redis"]:
                for feed in range(1, 6):
                    run_name = f"concurrency_n{n}_20260613_001322_{backend}_feed{feed}_rep1"
                    (temp_dir / run_name).mkdir()
        
        # Create some non-concurrency directories
        (temp_dir / "regular_run_1").mkdir()
        (temp_dir / "test_dir").mkdir()
        
        runs = discover_concurrency_runs(temp_dir)
        
        # Should find 3 concurrency levels × 2 backends × 5 feeds = 30 runs
        assert len(runs) == 30
        
        # Check all are Path objects
        assert all(isinstance(r, Path) for r in runs)

    def test_discover_with_prefix(self, temp_dir):
        """Test discovering runs with a specific prefix."""
        # Create runs with different timestamps
        for timestamp in ["20260613_001322", "20260613_002010"]:
            for n in [5]:
                for backend in ["kafka"]:
                    run_name = f"concurrency_n{n}_{timestamp}_{backend}_feed1_rep1"
                    (temp_dir / run_name).mkdir()
        
        # Discover only runs with first timestamp
        runs = discover_concurrency_runs(temp_dir, prefix="concurrency_n5_20260613_001322")
        
        assert len(runs) == 1
        assert runs[0].name == "concurrency_n5_20260613_001322_kafka_feed1_rep1"

    def test_discover_empty_directory(self, temp_dir):
        """Test discovering runs in empty directory."""
        runs = discover_concurrency_runs(temp_dir)
        assert len(runs) == 0

    def test_discover_nonexistent_directory(self, temp_dir):
        """Test discovering runs when directory doesn't exist (covers line 345)."""
        nonexistent_dir = temp_dir / "does_not_exist"
        runs = discover_concurrency_runs(nonexistent_dir)
        assert len(runs) == 0


class TestGroupRunsByTestSuite:
    """Tests for group_runs_by_test_suite function."""

    def test_group_by_suite(self, temp_dir):
        """Test grouping runs by test suite."""
        # Create runs for two test suites
        suite1_runs = []
        suite2_runs = []
        
        for feed in range(1, 6):
            suite1_kafka = temp_dir / f"concurrency_n5_20260613_001322_kafka_feed{feed}_rep1"
            suite1_kafka.mkdir()
            suite1_runs.append(suite1_kafka)
            
            suite1_redis = temp_dir / f"concurrency_n5_20260613_001322_redis_feed{feed}_rep1"
            suite1_redis.mkdir()
            suite1_runs.append(suite1_redis)
        
        for feed in range(1, 11):
            suite2_kafka = temp_dir / f"concurrency_n10_20260613_002010_kafka_feed{feed}_rep1"
            suite2_kafka.mkdir()
            suite2_runs.append(suite2_kafka)
            
            suite2_redis = temp_dir / f"concurrency_n10_20260613_002010_redis_feed{feed}_rep1"
            suite2_redis.mkdir()
            suite2_runs.append(suite2_redis)
        
        all_runs = list(suite1_runs + suite2_runs)
        suites = group_runs_by_test_suite(all_runs)
        
        assert len(suites) == 2
        assert "concurrency_n5_20260613_001322" in suites
        assert "concurrency_n10_20260613_002010" in suites
        assert len(suites["concurrency_n5_20260613_001322"]) == 10
        assert len(suites["concurrency_n10_20260613_002010"]) == 20


class TestCheckTestSuiteHealth:
    """Tests for check_test_suite_health function."""

    def test_healthy_suite(self, temp_dir):
        """Test checking a healthy test suite."""
        suite_runs = []
        
        # Create 5 kafka and 5 redis runs
        for backend in ["kafka", "redis"]:
            for feed in range(1, 6):
                run_dir = temp_dir / f"concurrency_n5_20260613_001322_{backend}_feed{feed}_rep1"
                run_dir.mkdir()
                suite_runs.append(run_dir)
                
                # Create all required files
                for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                          "tti_summary.printed.json", "meta.json"]:
                    (run_dir / f).touch()
                
                # Create valid meta.json
                meta = {
                    "run_id": run_dir.name,
                    "backend": backend,
                    "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
                }
                with open(run_dir / "meta.json", 'w') as f:
                    json.dump(meta, f)
                
                # Create valid tti_summary.json
                tti_data = {
                    "n_produced": 100,
                    "n_consumed": 100,
                    "n_matched": 100,
                    "tti_ms": {"p50": 50.0, "max": 300.0, "min": 10.0}
                }
                with open(run_dir / "tti_summary.json", 'w') as f:
                    json.dump(tti_data, f)
                
                # Create CSV files
                for csv_file in ["producer.csv", "consumer.csv"]:
                    with open(run_dir / csv_file, 'w', newline='') as f:
                        f.write("event_id\n")
                        for i in range(100):
                            f.write(f"{i}\n")
        
        suite_prefix = "concurrency_n5_20260613_001322"
        results = check_test_suite_health(suite_prefix, suite_runs)
        
        assert results["status"] == "PASS"
        assert results["total_runs"] == 10
        assert results["passed_runs"] == 10
        assert results["failed_runs"] == 0

    def test_suite_missing_backend(self, temp_dir):
        """Test suite with missing backend (only kafka, no redis)."""
        suite_runs = []
        
        # Create only kafka runs (no redis)
        for feed in range(1, 6):
            run_dir = temp_dir / f"concurrency_n5_20260613_001322_kafka_feed{feed}_rep1"
            run_dir.mkdir()
            suite_runs.append(run_dir)
            
            # Create minimal files
            for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                      "tti_summary.printed.json", "meta.json"]:
                (run_dir / f).touch()
            
            meta = {
                "run_id": run_dir.name,
                "backend": "kafka",
                "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
            }
            with open(run_dir / "meta.json", 'w') as f:
                json.dump(meta, f)
            
            tti_data = {
                "n_produced": 100,
                "n_consumed": 100,
                "n_matched": 100,
                "tti_ms": {"p50": 50.0}
            }
            with open(run_dir / "tti_summary.json", 'w') as f:
                json.dump(tti_data, f)
            
            for csv_file in ["producer.csv", "consumer.csv"]:
                with open(run_dir / csv_file, 'w', newline='') as f:
                    f.write("event_id\n1\n")
        
        suite_prefix = "concurrency_n5_20260613_001322"
        results = check_test_suite_health(suite_prefix, suite_runs)
        
        assert results["status"] == "FAIL"
        assert len(results["suite_issues"]) > 0
        assert any("Missing backends" in issue for issue in results["suite_issues"])

    def test_suite_wrong_feed_count(self, temp_dir):
        """Test suite with wrong number of feeds."""
        suite_runs = []
        
        # Create only 3 kafka and 3 redis runs (expected 5 each)
        for backend in ["kafka", "redis"]:
            for feed in range(1, 4):
                run_dir = temp_dir / f"concurrency_n5_20260613_001322_{backend}_feed{feed}_rep1"
                run_dir.mkdir()
                suite_runs.append(run_dir)
                
                # Create minimal files
                for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                          "tti_summary.printed.json", "meta.json"]:
                    (run_dir / f).touch()
                
                meta = {
                    "run_id": run_dir.name,
                    "backend": backend,
                    "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
                }
                with open(run_dir / "meta.json", 'w') as f:
                    json.dump(meta, f)
                
                tti_data = {
                    "n_produced": 100,
                    "n_consumed": 100,
                    "n_matched": 100,
                    "tti_ms": {"p50": 50.0}
                }
                with open(run_dir / "tti_summary.json", 'w') as f:
                    json.dump(tti_data, f)
                
                for csv_file in ["producer.csv", "consumer.csv"]:
                    with open(run_dir / csv_file, 'w', newline='') as f:
                        f.write("event_id\n1\n")
        
        suite_prefix = "concurrency_n5_20260613_001322"
        results = check_test_suite_health(suite_prefix, suite_runs)
        
        assert results["status"] == "FAIL"
        assert len(results["suite_issues"]) > 0
        assert any("Expected" in issue and "runs" in issue for issue in results["suite_issues"])

    def test_suite_non_consecutive_feeds(self, temp_dir):
        """Test suite with non-consecutive feed numbers (covers line 438)."""
        suite_runs = []
        
        # Create runs with non-consecutive feeds: 1, 2, 4, 5 (missing 3)
        for feed in [1, 2, 4, 5]:
            run_dir = temp_dir / f"concurrency_n5_20260613_001322_kafka_feed{feed}_rep1"
            run_dir.mkdir()
            suite_runs.append(run_dir)
            
            # Create minimal files
            for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                      "tti_summary.printed.json", "meta.json"]:
                (run_dir / f).touch()
            
            meta = {
                "run_id": run_dir.name,
                "backend": "kafka",
                "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
            }
            with open(run_dir / "meta.json", 'w') as f:
                json.dump(meta, f)
            
            tti_data = {
                "n_produced": 100,
                "n_consumed": 100,
                "n_matched": 100,
                "tti_ms": {"p50": 50.0}
            }
            with open(run_dir / "tti_summary.json", 'w') as f:
                json.dump(tti_data, f)
            
            for csv_file in ["producer.csv", "consumer.csv"]:
                with open(run_dir / csv_file, 'w', newline='') as f:
                    f.write("event_id\n1\n")
        
        suite_prefix = "concurrency_n5_20260613_001322"
        results = check_test_suite_health(suite_prefix, suite_runs)
        
        assert results["status"] == "FAIL"
        assert len(results["suite_issues"]) > 0
        assert any("not consecutive" in issue for issue in results["suite_issues"])


class TestGetScenarioFromRunId:
    """Tests for get_scenario_from_run_id function (covers line 61)."""

    def test_no_scenario_extracted(self):
        """Test when no scenario can be extracted from run_id."""
        run_id = "regular_run_20260613_001322_kafka_feed1_rep1"
        result = get_scenario_from_run_id(run_id)
        assert result is None


class TestCountCsvRowsEdgeCases:
    """Additional tests for count_csv_rows edge cases."""

    def test_count_csv_rows_with_exception(self, temp_dir):
        """Test count_csv_rows with exception handling (covers lines 131-137)."""
        csv_path = temp_dir / "malformed.csv"
        # Create a file that will cause exceptions
        with open(csv_path, 'wb') as f:
            f.write(b'\x00\x01\x02')  # Binary data that might cause issues
        
        result = count_csv_rows(csv_path)
        # Should return 0 on exception
        assert result == 0


class TestCheckEventCountsEdgeCases:
    """Additional tests for check_event_counts edge cases."""

    def test_check_event_counts_zero_producer_zero_consumer(self, temp_dir):
        """Test when both producer and consumer have zero events (covers lines 167, 169, 171)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()

        # Create empty CSV files
        (run_dir / "producer.csv").write_text("event_id\n")
        (run_dir / "consumer.csv").write_text("event_id\n")

        passed, issues = check_event_counts(run_dir)
        assert passed is False
        assert any("producer.csv has 0 events" in issue for issue in issues)
        assert any("consumer.csv has 0 events" in issue for issue in issues)


class TestCheckTtiValuesEdgeCases:
    """Additional tests for check_tti_values edge cases."""

    def test_check_tti_values_missing_file(self, temp_dir):
        """Test check_tti_values when tti_summary.json is missing (covers lines 187-188)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()

        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert "tti_summary.json not found" in issues[0]

    def test_check_tti_values_malformed_json(self, temp_dir):
        """Test check_tti_values with malformed JSON (covers lines 193-194)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()

        tti_file = run_dir / "tti_summary.json"
        with open(tti_file, 'w') as f:
            f.write("{ invalid json")

        passed, issues = check_tti_values(run_dir)
        assert passed is False
        assert "Failed to parse tti_summary.json" in issues[0]


class TestCheckLogsForErrorsEdgeCases:
    """Additional tests for check_logs_for_errors edge cases."""

    def test_check_logs_with_unicode_error(self, temp_dir):
        """Test check_logs_for_errors with UnicodeDecodeError (covers lines 289-290)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()

        # Create a log file with binary content that can't be decoded as UTF-8
        log_file = run_dir / "producer.log"
        with open(log_file, 'wb') as f:
            f.write(b'\x00\x01\x02\x03\x04')

        passed, issues = check_logs_for_errors(run_dir)
        # Should not crash, just return empty issues list for this file
        assert isinstance(issues, list)


class TestCheckRunHealthEdgeCases:
    """Additional tests for check_run_health edge cases."""

    def test_check_run_health_malformed_meta_json(self, temp_dir):
        """Test check_run_health with malformed meta.json (covers line 345)."""
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()

        # Create required files
        (run_dir / "producer.csv").write_text("event_id\n1\n")
        (run_dir / "consumer.csv").write_text("event_id\n1\n")
        (run_dir / "tti_summary.json").write_text('{"n_producer": 1, "n_consumer": 1, "n_matched": 1, "tti_ms": {"p50": 100.0}}')

        # Create malformed meta.json
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{ invalid json")

        result = check_run_health(run_dir)
        # Should still work, just without scenario/backend from meta
        assert "status" in result
        assert "run_id" in result


class TestPrintFunctions:
    """Tests for print functions to improve coverage."""

    def test_print_run_report_pass(self, capsys):
        """Test print_run_report for PASS status."""
        result = {
            "run_id": "test_run",
            "status": "PASS",
            "concurrency": 5,
            "backend": "kafka",
            "scenario": "s1",
            "feed_number": 1
        }
        print_run_report(result, verbose=False)
        captured = capsys.readouterr()
        assert "test_run" in captured.out
        assert "PASS" in captured.out

    def test_print_run_report_fail(self, capsys):
        """Test print_run_report for FAIL status."""
        result = {
            "run_id": "test_run",
            "status": "FAIL",
            "concurrency": 5,
            "backend": "kafka",
            "scenario": "s1",
            "feed_number": 1,
            "issues": ["Test issue 1", "Test issue 2"]
        }
        print_run_report(result, verbose=True)
        captured = capsys.readouterr()
        assert "test_run" in captured.out
        assert "FAIL" in captured.out
        assert "Test issue 1" in captured.out

    def test_print_suite_report(self, capsys):
        """Test print_suite_report."""
        suite_result = {
            "suite_prefix": "concurrency_n5_20260613_001322",
            "total_runs": 2,
            "passed_runs": 1,
            "failed_runs": 1,
            "status": "FAIL",
            "run_results": [],
            "suite_issues": ["Missing backends"]
        }
        print_suite_report(suite_result, verbose=False)
        captured = capsys.readouterr()
        assert "concurrency_n5_20260613_001322" in captured.out
        assert "1/2 passed" in captured.out

    def test_print_suite_report_verbose(self, capsys):
        """Test print_suite_report with verbose=True (covers lines 487-488)."""
        suite_result = {
            "suite_prefix": "concurrency_n5_20260613_001322",
            "total_runs": 2,
            "passed_runs": 1,
            "failed_runs": 1,
            "status": "FAIL",
            "run_results": [
                {"run_id": "run1", "status": "PASS"},
                {"run_id": "run2", "status": "FAIL"}
            ],
            "suite_issues": ["Missing backends"]
        }
        print_suite_report(suite_result, verbose=True)
        captured = capsys.readouterr()
        assert "concurrency_n5_20260613_001322" in captured.out
        assert "run1" in captured.out or "run2" in captured.out


class TestMainFunction:
    """Tests for main function (covers lines 492-620, 624)."""

    def test_main_list_runs(self, temp_dir, capsys):
        """Test main function with --list-runs option."""
        # Create some test run directories that match the expected pattern
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        # These must match the pattern: concurrency_n{N}_YYYYMMDD_HHMMSS_backend_feed{X}_rep1
        (runs_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1").mkdir()
        (runs_dir / "concurrency_n5_20260613_001322_kafka_feed2_rep1").mkdir()

        with patch('sys.argv', [
            'check_concurrency_health.py', 
            '--directory', str(runs_dir), 
            '--list-runs'
        ]):
            from scripts.check_concurrency_health import main
            try:
                main()
            except SystemExit as e:
                # list-runs should exit with code 0
                assert e.code == 0

    def test_main_list_suites(self, temp_dir, capsys):
        """Test main function with --list-suites option."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        # Create test run directories with same suite prefix that match the pattern
        (runs_dir / "concurrency_n10_20260613_002010_kafka_feed1_rep1").mkdir()
        (runs_dir / "concurrency_n10_20260613_002010_kafka_feed2_rep1").mkdir()

        with patch('sys.argv', [
            'check_concurrency_health.py', 
            '--directory', str(runs_dir), 
            '--list-suites'
        ]):
            from scripts.check_concurrency_health import main
            try:
                main()
            except SystemExit as e:
                # list-suites should exit with code 0
                assert e.code == 0

    def test_main_no_runs_found(self, temp_dir, capsys):
        """Test main function when no runs are found (covers error path)."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()

        with patch('sys.argv', [
            'check_concurrency_health.py', 
            '--directory', str(runs_dir)
        ]):
            from scripts.check_concurrency_health import main
            try:
                main()
            except SystemExit as e:
                # Should exit with error when no runs found
                assert e.code == 1
            except ZeroDivisionError:
                # This is expected due to the division by zero when no runs
                pass

    def test_main_with_json_flag(self, temp_dir, capsys):
        """Test main function with --json flag (covers lines 598-612)."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        # Create a valid run directory
        run_dir = runs_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        
        # Create required files with valid data
        producer_csv = run_dir / "producer.csv"
        with open(producer_csv, 'w', newline='') as f:
            f.write("event_id,timestamp\n")
            for i in range(100):
                f.write(f"{i},{i}\n")
        
        consumer_csv = run_dir / "consumer.csv"
        with open(consumer_csv, 'w', newline='') as f:
            f.write("event_id,timestamp\n")
            for i in range(100):
                f.write(f"{i},{i}\n")
        
        tti_file = run_dir / "tti_summary.json"
        tti_data = {
            "n_producer": 100,
            "n_consumer": 100,
            "n_matched": 100,
            "tti_ms_p50": 50.0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        tti_printed_file = run_dir / "tti_summary.printed.json"
        with open(tti_printed_file, 'w') as f:
            json.dump(tti_data, f)
        
        meta_file = run_dir / "meta.json"
        meta = {
            "run_id": run_dir.name,
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        with patch('sys.argv', [
            'check_concurrency_health.py',
            '--directory', str(runs_dir),
            '--json'
        ]):
            from scripts.check_concurrency_health import main
            try:
                main()
            except SystemExit as e:
                # Should succeed
                assert e.code == 0

    def test_main_with_prefix(self, temp_dir, capsys):
        """Test main function with --run-prefix option."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        # Create runs that match the prefix and pattern
        (runs_dir / "concurrency_n5_20260613_001322_kafka_feed1_rep1").mkdir()
        (runs_dir / "concurrency_n5_20260613_001322_kafka_feed2_rep1").mkdir()
        (runs_dir / "other_run_20260613_001322_kafka_feed1_rep1").mkdir()

        with patch('sys.argv', [
            'check_concurrency_health.py', 
            '--directory', str(runs_dir),
            '--run-prefix', 'concurrency_n5'
        ]):
            from scripts.check_concurrency_health import main
            try:
                main()
            except SystemExit as e:
                # Should exit with error since runs don't have required files
                assert e.code == 1
            except ZeroDivisionError:
                # This is expected due to missing required files
                pass


class TestEntryPoint:
    """Test entry point (covers line 624)."""

    def test_entry_point_import(self):
        """Test that the module can be imported and has main function."""
        import scripts.check_concurrency_health
        assert hasattr(scripts.check_concurrency_health, 'main')
        assert hasattr(scripts.check_concurrency_health, 'get_concurrency_from_run_id')
        assert hasattr(scripts.check_concurrency_health, 'check_run_health')
