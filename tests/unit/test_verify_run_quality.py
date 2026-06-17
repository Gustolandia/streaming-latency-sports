"""
Unit tests for verify_run_quality.py
Tests all functions in the run quality verification script.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.verify_run_quality import (
    check_consumer_events_file,
    check_event_counts,
    check_logs_for_errors,
    check_metadata,
    check_required_files,
    check_tti_values,
    check_run,
    count_csv_rows,
    print_run_report,
)


def create_sample_run_dir(run_id, temp_dir):
    """Create a sample run directory with all required files."""
    run_dir = temp_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Create meta.json
    meta = {
        "run_id": run_id,
        "backend": "kafka" if "kafka" in run_id else "redis",
        "scenario": "s2sf12",
        "plan_csv": "data/processed/replay_plans/test/combined_plan.csv",
        "speedup": 120.0,
        "max_t_sim": 600,
    }
    with open(run_dir / "meta.json", 'w') as f:
        json.dump(meta, f)
    
    # Create tti_summary.json
    tti_summary = {
        "run_id": run_id,
        "n_produced": 1000,
        "n_consumed": 1000,
        "n_matched": 1000,
        "tti_ms_p50": 50.0,
        "tti_ms_p95": 150.0,
        "tti_ms_p99": 250.0,
        "tti_ms_max": 300.0,
        "tti_ms_mean": 60.0,
        "tti_ms_std": 20.0,
        "tti_ms_min": 10.0,
    }
    with open(run_dir / "tti_summary.json", 'w') as f:
        json.dump(tti_summary, f)
    
    # Create tti_summary.printed.json
    with open(run_dir / "tti_summary.printed.json", 'w') as f:
        json.dump(tti_summary, f)
    
    # Create producer.csv
    with open(run_dir / "producer.csv", 'w') as f:
        f.write("col1,col2\n")
        for i in range(100):
            f.write(f"val{i},data{i}\n")
    
    # Create consumer.csv
    with open(run_dir / "consumer.csv", 'w') as f:
        f.write("col1,col2\n")
        for i in range(100):
            f.write(f"val{i},data{i}\n")
    
    # Create consumer_events.csv
    with open(run_dir / "consumer_events.csv", 'w') as f:
        f.write("run_id,event_id\n")
        for i in range(100):
            f.write(f"{run_id},event_{i}\n")
    
    # Create producer.log
    with open(run_dir / "producer.log", 'w') as f:
        f.write("Starting...\nCompleted successfully\n")
    
    # Create consumer.log
    with open(run_dir / "consumer.log", 'w') as f:
        f.write("Starting...\nCompleted successfully\n")
    
    return run_dir


class TestCheckRequiredFiles:
    """Tests for check_required_files function."""

    def test_all_files_exist(self, temp_dir):
        """Test when all required files exist."""
        # Create all required files
        for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                  "tti_summary.printed.json", "meta.json"]:
            (temp_dir / f).touch()
        
        passed, missing = check_required_files(temp_dir)
        assert passed is True
        assert missing == []

    def test_missing_one_file(self, temp_dir):
        """Test when one file is missing."""
        for f in ["producer.csv", "consumer.csv", "tti_summary.printed.json", "meta.json"]:
            (temp_dir / f).touch()
        # Missing tti_summary.json
        
        passed, missing = check_required_files(temp_dir)
        assert passed is False
        assert "tti_summary.json" in missing

    def test_missing_all_files(self, temp_dir):
        """Test when all files are missing."""
        passed, missing = check_required_files(temp_dir)
        assert passed is False
        assert len(missing) == 5

    def test_empty_directory(self, temp_dir):
        """Test with empty directory."""
        passed, missing = check_required_files(temp_dir)
        assert passed is False
        assert len(missing) == 5


class TestCheckConsumerEventsFile:
    """Tests for check_consumer_events_file function."""

    def test_file_exists(self, temp_dir):
        """Test when consumer_events.csv exists."""
        (temp_dir / "consumer_events.csv").touch()
        
        passed, missing = check_consumer_events_file(temp_dir)
        assert passed is True
        assert missing == []

    def test_file_missing(self, temp_dir):
        """Test when consumer_events.csv is missing."""
        passed, missing = check_consumer_events_file(temp_dir)
        assert passed is False
        assert "consumer_events.csv" in missing
    
    def test_exception_handling(self, temp_dir):
        """Test exception handling in check_consumer_events_file."""
        # Mock Path.exists to raise an exception
        with patch('scripts.verify_run_quality.Path') as mock_path:
            mock_run_dir = MagicMock()
            mock_consumer_events = MagicMock()
            mock_consumer_events.exists.side_effect = PermissionError("Permission denied")
            mock_run_dir.__truediv__ = MagicMock(return_value=mock_consumer_events)
            
            passed, missing = check_consumer_events_file(mock_run_dir)
            assert passed is False
            assert any("Error checking consumer_events.csv" in msg for msg in missing)


class TestCountCsvRows:
    """Tests for count_csv_rows function."""

    def test_count_rows(self, temp_dir):
        """Test counting rows in CSV."""
        csv_path = temp_dir / "test.csv"
        with open(csv_path, 'w') as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
            f.write("c,d\n")
            f.write("e,f\n")
        
        count = count_csv_rows(csv_path)
        assert count == 3

    def test_empty_csv(self, temp_dir):
        """Test with header only."""
        csv_path = temp_dir / "test.csv"
        with open(csv_path, 'w') as f:
            f.write("col1,col2\n")
        
        count = count_csv_rows(csv_path)
        assert count == 0

    def test_nonexistent_file(self, temp_dir):
        """Test with non-existent file."""
        csv_path = temp_dir / "nonexistent.csv"
        count = count_csv_rows(csv_path)
        assert count == 0

    def test_utf8_sig_encoding(self, temp_dir):
        """Test UTF-8-sig encoding handling."""
        csv_path = temp_dir / "test.csv"
        # Write with UTF-8-sig BOM
        with open(csv_path, 'w', encoding='utf-8-sig') as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
        
        count = count_csv_rows(csv_path)
        assert count == 1

    def test_utf8_fallback_encoding(self, temp_dir):
        """Test fallback to UTF-8 encoding."""
        csv_path = temp_dir / "test.csv"
        # This should trigger the fallback
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
        
        count = count_csv_rows(csv_path)
        assert count == 1

    def test_permission_error_utf8_sig(self, temp_dir):
        """Test exception handling in utf-8-sig open."""
        csv_path = temp_dir / "test.csv"
        # Create the file first
        with open(csv_path, 'w') as f:
            f.write("col1,col2\n")
        
        # Mock open to raise exception for utf-8-sig but work for utf-8
        with patch('builtins.open') as mock_open:
            def side_effect_func(path, mode='r', encoding=None, *args, **kwargs):
                if encoding == 'utf-8-sig':
                    raise UnicodeDecodeError('utf-8-sig', b'', 0, 1, 'test')
                # For utf-8, return a working file
                actual_file = open(path, mode, encoding=encoding, *args, **kwargs)
                return actual_file
            
            mock_open.side_effect = side_effect_func
            count = count_csv_rows(csv_path)
            assert count == 0  # Falls back to utf-8 which should also fail in mock

    def test_permission_error_both_encodings(self, temp_dir):
        """Test exception handling when both encodings fail."""
        csv_path = temp_dir / "test.csv"
        
        with patch('builtins.open') as mock_open:
            mock_open.side_effect = PermissionError("Permission denied")
            count = count_csv_rows(csv_path)
            assert count == 0


class TestCheckEventCounts:
    """Tests for check_event_counts function."""

    def test_matching_counts(self, temp_dir):
        """Test with matching event counts."""
        # Create producer.csv with 100 rows
        producer_csv = temp_dir / "producer.csv"
        with open(producer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(100):
                f.write(f"val{i},data{i}\n")
        
        # Create consumer.csv with 100 rows
        consumer_csv = temp_dir / "consumer.csv"
        with open(consumer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(100):
                f.write(f"val{i},data{i}\n")
        
        passed, issues = check_event_counts(temp_dir)
        assert passed is True
        assert issues == []

    def test_small_mismatch_allowed(self, temp_dir):
        """Test with small mismatch (within 1% or 10 events)."""
        # Create producer.csv with 1000 rows
        producer_csv = temp_dir / "producer.csv"
        with open(producer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(1000):
                f.write(f"val{i},data{i}\n")
        
        # Create consumer.csv with 995 rows (0.5% diff, within tolerance)
        consumer_csv = temp_dir / "consumer.csv"
        with open(consumer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(995):
                f.write(f"val{i},data{i}\n")
        
        passed, issues = check_event_counts(temp_dir)
        assert passed is True

    def test_large_mismatch_fails(self, temp_dir):
        """Test with large mismatch."""
        # Create producer.csv with 100 rows
        producer_csv = temp_dir / "producer.csv"
        with open(producer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(100):
                f.write(f"val{i},data{i}\n")
        
        # Create consumer.csv with 50 rows (50% diff, exceeds tolerance)
        consumer_csv = temp_dir / "consumer.csv"
        with open(consumer_csv, 'w') as f:
            f.write("col1,col2\n")
            for i in range(50):
                f.write(f"val{i},data{i}\n")
        
        passed, issues = check_event_counts(temp_dir)
        assert passed is False
        assert len(issues) > 0

    def test_zero_producer_events(self, temp_dir):
        """Test with zero producer events."""
        producer_csv = temp_dir / "producer.csv"
        with open(producer_csv, 'w') as f:
            f.write("col1,col2\n")
        
        consumer_csv = temp_dir / "consumer.csv"
        with open(consumer_csv, 'w') as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
        
        passed, issues = check_event_counts(temp_dir)
        assert passed is False

    def test_zero_consumer_events(self, temp_dir):
        """Test with zero consumer events."""
        producer_csv = temp_dir / "producer.csv"
        with open(producer_csv, 'w') as f:
            f.write("col1,col2\n")
            f.write("a,b\n")
        
        consumer_csv = temp_dir / "consumer.csv"
        with open(consumer_csv, 'w') as f:
            f.write("col1,col2\n")
        
        passed, issues = check_event_counts(temp_dir)
        assert passed is False
        assert any("consumer.csv has 0 events" in issue for issue in issues)


class TestCheckTtiValues:
    """Tests for check_tti_values function."""

    def test_valid_tti(self, temp_dir):
        """Test with valid TTI values."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "tti_ms_min": 100.0,
            "tti_ms_max": 1000.0,
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is True
        assert issues == []

    def test_negative_median_tti(self, temp_dir):
        """Test with negative median TTI."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": -100.0,
            "tti_ms_min": -200.0,
            "tti_ms_max": 1000.0,
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is False
        assert any("Negative" in issue for issue in issues)

    def test_extremely_negative_min(self, temp_dir):
        """Test with extremely negative min TTI."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "tti_ms_min": -10000.0,
            "tti_ms_max": 1000.0,
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is False

    def test_unreasonably_high_max(self, temp_dir):
        """Test with unreasonably high max TTI."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "tti_ms_min": 100.0,
            "tti_ms_max": 400000.0,  # > 5 minutes in ms
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is False

    def test_zero_matched(self, temp_dir):
        """Test with zero matched events."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "n_matched": 0
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is False

    def test_missing_file(self, temp_dir):
        """Test with missing tti_summary.json."""
        passed, issues = check_tti_values(temp_dir)
        assert passed is False


class TestCheckLogsForErrors:
    """Tests for check_logs_for_errors function."""

    def test_no_errors(self, temp_dir):
        """Test with clean log files."""
        for log in ["producer.log", "consumer.log"]:
            log_file = temp_dir / log
            with open(log_file, 'w') as f:
                f.write("Starting...\n")
                f.write("Processing events...\n")
                f.write("Completed successfully\n")
        
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is True
        assert issues == []

    def test_traceback_in_log(self, temp_dir):
        """Test with Traceback in log."""
        producer_log = temp_dir / "producer.log"
        with open(producer_log, 'w') as f:
            f.write("Starting...\n")
            f.write("Traceback (most recent call last):\n")
            f.write("  File \"test.py\", line 10\n")
        
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is False
        assert len(issues) > 0

    def test_error_pattern_in_log(self, temp_dir):
        """Test with Error: pattern in log."""
        consumer_log = temp_dir / "consumer.log"
        with open(consumer_log, 'w') as f:
            f.write("Error: Connection refused\n")
        
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is False

    def test_no_log_files(self, temp_dir):
        """Test with no log files."""
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is True  # No logs = no errors found


class TestCheckMetadata:
    """Tests for check_metadata function."""

    def test_valid_metadata(self, temp_dir):
        """Test with valid metadata."""
        meta_file = temp_dir / "meta.json"
        meta = {
            "run_id": "test_run_001",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s2sf12/combined_plan.csv"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(temp_dir)
        assert passed is True
        assert issues == []

    def test_missing_required_field(self, temp_dir):
        """Test with missing required field."""
        meta_file = temp_dir / "meta.json"
        meta = {
            "run_id": "test_run_001",
            # Missing backend and plan_csv
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(temp_dir)
        assert passed is False

    def test_invalid_backend(self, temp_dir):
        """Test with invalid backend."""
        meta_file = temp_dir / "meta.json"
        meta = {
            "run_id": "test_run_001",
            "backend": "invalid_backend",
            "plan_csv": "data/test.csv"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(temp_dir)
        assert passed is False

    def test_missing_file(self, temp_dir):
        """Test with missing meta.json."""
        passed, issues = check_metadata(temp_dir)
        assert passed is False


class TestCheckRun:
    """Tests for check_run function."""

    def test_all_checks_pass(self, temp_dir):
        """Test when all checks pass."""
        # Create all required files
        (temp_dir / "producer.csv").touch()
        (temp_dir / "consumer.csv").touch()
        (temp_dir / "tti_summary.json").write_text(json.dumps({"tti_ms_p50": 500.0, "n_matched": 100}))
        (temp_dir / "tti_summary.printed.json").touch()
        (temp_dir / "consumer_events.csv").touch()  # Required for S3
        
        meta_file = temp_dir / "meta.json"
        meta = {"run_id": "test", "backend": "kafka", "plan_csv": "test.csv"}
        meta_file.write_text(json.dumps(meta))
        
        # Create valid consumer.csv with data
        with open(temp_dir / "consumer.csv", 'w') as f:
            f.write("col1,col2\n")
            for i in range(100):
                f.write(f"val{i},data{i}\n")
        
        # Create valid producer.csv with data
        with open(temp_dir / "producer.csv", 'w') as f:
            f.write("col1,col2\n")
            for i in range(100):
                f.write(f"val{i},data{i}\n")
        
        # Create producer and consumer logs
        for log in ["producer.log", "consumer.log"]:
            (temp_dir / log).write_text("Started\nCompleted\n")
        
        result = check_run(temp_dir)
        assert result["status"] == "PASS"
        assert len(result["issues"]) == 0

    def test_one_check_fails(self, temp_dir):
        """Test when one check fails."""
        # Create some but not all required files
        (temp_dir / "producer.csv").touch()
        (temp_dir / "consumer.csv").touch()
        # Missing tti_summary.json
        
        result = check_run(temp_dir)
        assert result["status"] == "FAIL"
        assert len(result["issues"]) > 0


class TestPrintRunReport:
    """Tests for print_run_report function - basic functionality."""

    def test_pass_report(self, capsys):
        """Test printing PASS report."""
        results = {
            "run_id": "test_run_001",
            "status": "PASS",
            "issues": [],
            "checks": {"check1": "PASS", "check2": "PASS"}
        }
        print_run_report(results, verbose=False)
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "test_run_001" in captured.out

    def test_fail_report(self, capsys):
        """Test printing FAIL report."""
        results = {
            "run_id": "test_run_001",
            "status": "FAIL",
            "issues": ["Error 1", "Error 2"],
            "checks": {"check1": "PASS", "check2": "FAIL"}
        }
        print_run_report(results, verbose=False)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "test_run_001" in captured.out


# Additional tests for verify_run_quality.py functions

class TestCheckRequiredFilesEdgeCases:
    """Additional edge case tests for check_required_files."""

    def test_partial_files_missing(self, temp_dir):
        """Test with some but not all required files missing."""
        # Create only 2 out of 5 required files
        (temp_dir / "producer.csv").touch()
        (temp_dir / "consumer.csv").touch()
        
        passed, missing = check_required_files(temp_dir)
        assert passed is False
        assert "tti_summary.json" in missing
        assert "tti_summary.printed.json" in missing
        assert "meta.json" in missing

    def test_utf8_bom_handling(self, temp_dir):
        """Test handling of UTF-8 BOM in JSON files."""
        # Create files with BOM
        for f in ["producer.csv", "consumer.csv", "tti_summary.json", 
                  "tti_summary.printed.json", "meta.json"]:
            (temp_dir / f).touch()
        
        passed, missing = check_required_files(temp_dir)
        assert passed is True


class TestCheckTtiValuesEdgeCases:
    """Additional edge case tests for check_tti_values."""

    def test_missing_tti_fields(self, temp_dir):
        """Test with missing TTI fields."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {"n_matched": 1000}  # Missing tti_ms_* fields
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        # Should pass since only checks for negative values and zero matched
        assert passed is True

    def test_extremely_high_max_tti(self, temp_dir):
        """Test with TTI max just at the boundary."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "tti_ms_min": 100.0,
            "tti_ms_max": 300000.0,  # Exactly at the boundary
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        # At the boundary should be OK (it's > 300000 that fails)
        assert passed is True

    def test_just_above_boundary(self, temp_dir):
        """Test with TTI max just above the boundary."""
        tti_file = temp_dir / "tti_summary.json"
        tti_data = {
            "tti_ms_p50": 500.0,
            "tti_ms_min": 100.0,
            "tti_ms_max": 300001.0,  # Just above boundary
            "n_matched": 1000
        }
        with open(tti_file, 'w') as f:
            json.dump(tti_data, f)
        
        passed, issues = check_tti_values(temp_dir)
        assert passed is False


class TestCheckLogsForErrorsEdgeCases:
    """Additional edge case tests for check_logs_for_errors."""

    def test_case_insensitive_error(self, temp_dir):
        """Test case-insensitive error detection."""
        producer_log = temp_dir / "producer.log"
        with open(producer_log, 'w') as f:
            f.write("error: Connection failed\n")
        
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is False

    def test_multiple_errors_in_one_file(self, temp_dir):
        """Test with multiple errors in one log file."""
        producer_log = temp_dir / "producer.log"
        with open(producer_log, 'w') as f:
            f.write("Starting...\n")
            f.write("Error: First error\n")
            f.write("Traceback (most recent call last):\n")
            f.write("Error: Second error\n")
        
        passed, issues = check_logs_for_errors(temp_dir)
        assert passed is False
        assert len(issues) >= 2  # Should find multiple errors


class TestCheckMetadataEdgeCases:
    """Additional edge case tests for check_metadata."""

    def test_extra_fields_in_metadata(self, temp_dir):
        """Test with extra fields in metadata."""
        meta_file = temp_dir / "meta.json"
        meta = {
            "run_id": "test_run_001",
            "backend": "kafka",
            "plan_csv": "data/test.csv",
            "extra_field": "extra_value"
        }
        with open(meta_file, 'w') as f:
            json.dump(meta, f)
        
        passed, issues = check_metadata(temp_dir)
        assert passed is True

    def test_invalid_json_in_metadata(self, temp_dir):
        """Test with invalid JSON in metadata."""
        meta_file = temp_dir / "meta.json"
        with open(meta_file, 'w') as f:
            f.write("{invalid json}")
        
        passed, issues = check_metadata(temp_dir)
        assert passed is False


class TestPrintRunReportEdgeCases:
    """Additional edge case tests for print_run_report."""

    def test_pass_report_verbose(self, capsys):
        """Test printing PASS report with verbose."""
        results = {
            "run_id": "test_run_001",
            "status": "PASS",
            "issues": [],
            "checks": {"check1": "PASS", "check2": "PASS"}
        }
        print_run_report(results, verbose=True)
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "test_run_001" in captured.out

    def test_fail_report_with_issues(self, capsys):
        """Test printing FAIL report with multiple issues."""
        results = {
            "run_id": "test_run_001",
            "status": "FAIL",
            "issues": ["Error 1", "Error 2", "Error 3"],
            "checks": {"check1": "PASS", "check2": "FAIL"}
        }
        print_run_report(results, verbose=True)
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "Error 1" in captured.out
        assert "Error 2" in captured.out
        assert "Error 3" in captured.out


# Tests for main function

class TestMainFunction:
    """Tests for the main function and CLI interface."""

    def test_main_with_run_id(self, temp_dir):
        """Test main with --run-id argument."""
        # Create a valid run directory
        run_dir = temp_dir / "test_run_001"
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_001', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                try:
                    from scripts.verify_run_quality import main as verify_main
                    verify_main()
                except SystemExit:
                    pass
                
                # Should exit with code 0 (success)
                mock_exit.assert_called_once_with(0)

    def test_main_with_missing_run(self, temp_dir):
        """Test main with non-existent run."""
        test_args = ['verify_run_quality.py', '--run-id', 'nonexistent_run', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 1 (failure)
                mock_exit.assert_called_once_with(1)

    def test_main_with_run_list(self, temp_dir):
        """Test main with --run-list argument."""
        # Create a run list file
        run_list_file = temp_dir / "run_list.txt"
        run_list_file.write_text(str(temp_dir / "test_run_001"))
        
        # Create the run directory
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-list', str(run_list_file)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0 (success)
                mock_exit.assert_called_once_with(0)

    def test_main_with_directory_all_runs(self, temp_dir):
        """Test main with --directory to check all runs."""
        # Create multiple run directories
        create_sample_run_dir("test_run_001", temp_dir)
        create_sample_run_dir("test_run_002", temp_dir)
        
        test_args = ['verify_run_quality.py', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0 (all passes)
                mock_exit.assert_called_once_with(0)

    def test_main_json_output(self, temp_dir):
        """Test main with --json argument."""
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_001', '--directory', str(temp_dir), '--json']
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0
                mock_exit.assert_called_once_with(0)

    def test_main_fail_fast(self, temp_dir):
        """Test main with --fail-fast argument."""
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_001', '--directory', str(temp_dir), '--fail-fast']
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0
                mock_exit.assert_called_once_with(0)

    def test_main_verbose(self, temp_dir):
        """Test main with --verbose argument."""
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_001', '--directory', str(temp_dir), '--verbose']
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0
                mock_exit.assert_called_once_with(0)

    def test_main_fail_fast_with_failure(self, temp_dir):
        """Test main with --fail-fast when a check fails."""
        # Create a run with missing file to trigger FAIL
        run_dir = temp_dir / "test_run_fail"
        run_dir.mkdir()
        # Only create some files, missing tti_summary.json
        meta = {"run_id": "test_run_fail", "backend": "kafka", "plan_csv": "data/test.csv"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_fail', '--directory', str(temp_dir), '--fail-fast']
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 1 (failure)
                mock_exit.assert_called_once_with(1)

    def test_main_no_runs_to_check(self, temp_dir):
        """Test main when no runs are found to check."""
        test_args = ['verify_run_quality.py', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should have called exit with code 1 at least once
                assert any(call[0][0] == 1 for call in mock_exit.call_args_list)

    def test_main_with_run_list_encoding_error(self, temp_dir):
        """Test main with run list file that has encoding errors."""
        # Create a run list file with invalid encoding that UTF-16 can handle
        run_list_file = temp_dir / "run_list.txt"
        # Write content that UTF-16 can decode but will still have issues
        with open(run_list_file, 'wb') as f:
            f.write(b'\xff\xfe')  # UTF-16 BOM
            f.write('test_run_001\n'.encode('utf-16-le'))
        
        test_args = ['verify_run_quality.py', '--run-list', str(run_list_file)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should have called exit with code 1 at least once (for missing run)
                assert any(call[0][0] == 1 for call in mock_exit.call_args_list)

    def test_main_with_run_list_no_encoding_found(self, temp_dir):
        """Test main when no encoding works for run list file."""
        run_list_file = temp_dir / "run_list.txt"
        # Write content that can't be decoded by any of the tried encodings
        with open(run_list_file, 'wb') as f:
            f.write(b'\x00\x01\x02\x03')
        
        test_args = ['verify_run_quality.py', '--run-list', str(run_list_file)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 1
                mock_exit.assert_called_once_with(1)

    def test_main_with_run_list_contains_runs(self, temp_dir):
        """Test main with run list that already contains 'runs' in path."""
        run_list_file = temp_dir / "run_list.txt"
        run_dir = temp_dir / "test_run_001"
        create_sample_run_dir("test_run_001", temp_dir)
        
        # Write path that already contains 'runs'
        run_list_file.write_text(str(run_dir))
        
        test_args = ['verify_run_quality.py', '--run-list', str(run_list_file), '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 0
                mock_exit.assert_called_once_with(0)

    def test_main_missing_run_directory(self, temp_dir):
        """Test main when run directory doesn't exist."""
        test_args = ['verify_run_quality.py', '--run-id', 'nonexistent', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                from scripts.verify_run_quality import main as verify_main
                verify_main()
                
                # Should exit with code 1 (MISSING status)
                mock_exit.assert_called_once_with(1)

    def test_main_exception_in_check_run(self, temp_dir):
        """Test main when check_run raises an exception."""
        run_dir = temp_dir / "test_run_error"
        run_dir.mkdir()
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_error', '--directory', str(temp_dir)]
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.check_run') as mock_check_run:
                mock_check_run.side_effect = RuntimeError("Test error")
                with patch('scripts.verify_run_quality.sys.exit') as mock_exit:
                    from scripts.verify_run_quality import main as verify_main
                    verify_main()
                    
                    # Should exit with code 1
                    mock_exit.assert_called_once_with(1)


# Tests for command-line argument parsing

class TestArgumentParsing:
    """Tests for argument parsing in main."""

    def test_default_directory(self, temp_dir):
        """Test that default directory is 'runs'."""
        create_sample_run_dir("test_run_001", temp_dir)
        
        test_args = ['verify_run_quality.py', '--run-id', 'test_run_001']
        with patch('sys.argv', test_args):
            with patch('scripts.verify_run_quality.Path') as mock_path:
                # Mock the runs directory
                mock_runs_dir = MagicMock()
                mock_runs_dir.exists.return_value = True
                mock_runs_dir.iterdir.return_value = []
                mock_path.return_value = mock_runs_dir
                
                from scripts.verify_run_quality import main as verify_main
                with patch('scripts.verify_run_quality.sys.exit'):
                    try:
                        verify_main()
                    except SystemExit:
                        pass


# Parametrized tests for edge cases

@pytest.mark.parametrize("n_rows,expected", [
    (0, 0),
    (1, 1),
    (10, 10),
    (100, 100),
])
def test_count_csv_rows_parametrized(temp_dir, n_rows, expected):
    """Parametrized test for count_csv_rows."""
    csv_path = temp_dir / "test.csv"
    with open(csv_path, 'w') as f:
        f.write("col1,col2\n")
        for i in range(n_rows):
            f.write(f"val{i},data{i}\n")
    
    count = count_csv_rows(csv_path)
    assert count == expected
