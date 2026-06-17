"""Complete tests for validate_s3_outputs.py - Target: 95%+ branch coverage."""
import pytest
import json
import csv
import os
import tempfile
from pathlib import Path
from dataclasses import asdict

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from unittest.mock import patch
from validate_s3_outputs import (
    RunValidation,
    ValidationSummary,
    validate_run,
    validate_all_runs,
    print_summary,
    validate_config_consistency,
    main,
)


class TestMain:
    """Tests for the main entry point."""

    @patch("validate_s3_outputs.print_summary", return_value=0)
    @patch("validate_s3_outputs.validate_config_consistency")
    @patch("validate_s3_outputs.validate_all_runs")
    def test_main_returns_exit_code(self, mock_validate_all, mock_config, mock_print_summary):
        mock_validate_all.return_value = ValidationSummary(total_runs=1, passed=1)

        rc = main(["--runlist", "runs/_paper_s3_official_runs.txt"])

        assert rc == 0
        mock_validate_all.assert_called_once()
        mock_config.assert_called_once()
        mock_print_summary.assert_called_once()

    @patch("validate_s3_outputs.print_summary", return_value=1)
    @patch("validate_s3_outputs.validate_config_consistency")
    @patch("validate_s3_outputs.validate_all_runs")
    def test_main_propagates_failure_code(self, mock_validate_all, mock_config, mock_print_summary):
        mock_validate_all.return_value = ValidationSummary(total_runs=1, failed=1)

        rc = main([])

        assert rc == 1


class TestRunValidationDataclass:
    """Tests for RunValidation dataclass."""

    def test_default_values(self):
        result = RunValidation(run_id="test_run")
        assert result.run_id == "test_run"
        assert result.status == "PASS"
        assert result.errors == []
        assert result.warnings == []
        assert result.files == {}
        assert result.event_counts == {}
        assert result.meta is None


class TestValidationSummaryDataclass:
    """Tests for ValidationSummary dataclass."""

    def test_default_values(self):
        summary = ValidationSummary()
        assert summary.total_runs == 0
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.warnings == 0
        assert summary.details == []


class TestValidateRun:
    """Tests for validate_run function."""

    def test_valid_run(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        # Create meta.json
        meta = {
            "run_id": "s3_test_kafka_rep1_20260101",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s3/plan.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        # Create producer.csv
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id", "match_id", "t_sim_seconds"])
            for i in range(100):
                writer.writerow(["test", f"e{i}", "1", str(i)])
        
        # Create consumer.csv
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id", "match_id", "t_sim_seconds"])
            for i in range(100):
                writer.writerow(["test", f"e{i}", "1", str(i)])
        
        # Create consumer_events.csv
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id", "match_id", "t_sim_seconds"])
            for i in range(100):
                writer.writerow(["test", f"e{i}", "1", str(i)])
        
        # Create tti_summary.json
        tti_data = {"p50": 1000, "p95": 2000, "p99": 3000}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = validate_run(run_dir)
        
        assert result.run_id == "s3_test_kafka_rep1_20260101"
        assert result.status == "PASS"
        assert len(result.errors) == 0
        assert result.meta == meta
        assert result.event_counts["producer.csv"] == 100
        assert result.event_counts["consumer.csv"] == 100
        assert result.files["meta.json"] is True
        assert result.files["tti_summary.json"] is True

    def test_missing_meta_json(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert "Missing or empty: meta.json" in result.errors
        assert result.files["meta.json"] is False

    def test_missing_required_meta_field(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {"run_id": "test"}
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("missing field: backend" in e for e in result.errors)

    def test_invalid_backend(self, temp_dir):
        run_dir = temp_dir / "s3_test_invalid_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "invalid",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("Invalid backend: invalid" in e for e in result.errors)

    def test_empty_csv(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("producer.csv has no data rows" in e for e in result.errors)

    def test_missing_event_id_column_warning(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "other_id"])
            writer.writerow(["test", "1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"p50": 1000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("missing event_id column" in w for w in result.warnings)

    def test_event_count_mismatch_warning(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            for i in range(100):
                writer.writerow(["test", f"e{i}"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            for i in range(50):
                writer.writerow(["test", f"e{i}"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"p50": 1000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("Event count mismatch" in w for w in result.warnings)

    def test_corrupt_meta_json(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        with open(run_dir / "meta.json", "w") as f:
            f.write("{ invalid json")
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("meta.json invalid" in e for e in result.errors)

    def test_empty_tti_summary(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("tti_summary.json is empty" in e for e in result.errors)

    def test_corrupt_tti_summary(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "tti_summary.json", "w") as f:
            f.write("{ invalid json")
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("tti_summary.json invalid" in e for e in result.errors)

    def test_empty_producer_csv(self, temp_dir):
        run_dir = temp_dir / "s3_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "test",
            "backend": "kafka",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "producer.csv", "w") as f:
            f.write("")
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("producer.csv" in e and "empty" in e.lower() or "no data" in e for e in result.errors)


class TestValidateAllRuns:
    """Tests for validate_all_runs function."""

    def test_missing_runlist(self, temp_dir):
        with pytest.raises(SystemExit) as exc_info:
            validate_all_runs(Path("nonexistent.txt"))
        assert exc_info.value.code == 1

    def test_failed_run_increments_failed_count(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runlist_path = temp_dir / "runlist.txt"
            runlist_path.write_text("s3_fail_kafka_rep1_20260101\n")
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            run_dir = runs_dir / "s3_fail_kafka_rep1_20260101"
            run_dir.mkdir()
            
            # Create an invalid run (missing required meta fields)
            meta = {"run_id": "test"}
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta, f)
            
            summary = validate_all_runs(runlist_path)
            
            assert summary.total_runs == 1
            assert summary.failed == 1
            assert summary.passed == 0
        finally:
            os.chdir(old_cwd)

    def test_missing_run_directory(self, temp_dir):
        runlist_path = temp_dir / "runlist.txt"
        runlist_path.write_text("nonexistent_run\n")
        
        summary = validate_all_runs(runlist_path)
        
        assert summary.total_runs == 1
        assert summary.failed == 1
        assert summary.passed == 0
        assert summary.details[0].status == "FAIL"
        assert "Directory not found" in summary.details[0].errors[0]

    def test_run_with_warnings_increments_warning_count(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runlist_path = temp_dir / "runlist.txt"
            
            run_ids = ["s3_warning_kafka_rep1_20260101"]
            runlist_path.write_text("\n".join(run_ids) + "\n")
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            run_dir = runs_dir / "s3_warning_kafka_rep1_20260101"
            run_dir.mkdir()
            
            meta = {
                "run_id": "s3_warning_kafka_rep1_20260101",
                "backend": "kafka",
                "plan_csv": "test.csv",
                "speedup": 120,
                "max_t_sim": 100.0
            }
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta, f)
            
            with open(run_dir / "producer.csv", "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["run_id", "other_id"])
                writer.writerow(["test", "1"])
            
            with open(run_dir / "consumer.csv", "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["run_id", "event_id"])
                writer.writerow(["test", "e1"])
            
            with open(run_dir / "consumer_events.csv", "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["run_id", "event_id"])
                writer.writerow(["test", "e1"])
            
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump({"p50": 1000}, f)
            
            summary = validate_all_runs(runlist_path)
            
            assert summary.total_runs == 1
            assert summary.passed == 1
            assert summary.warnings == 1
        finally:
            os.chdir(old_cwd)

    def test_valid_runs(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runlist_path = temp_dir / "runlist.txt"
            
            # Create two valid runs
            run_ids = ["s3_test1_kafka_rep1_20260101", "s3_test2_redis_rep1_20260101"]
            runlist_path.write_text("\n".join(run_ids) + "\n")
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            for run_id in run_ids:
                run_dir = runs_dir / run_id
                run_dir.mkdir()
                
                backend = "kafka" if "kafka" in run_id else "redis"
                meta = {
                    "run_id": run_id,
                    "backend": backend,
                    "plan_csv": "test.csv",
                    "speedup": 120,
                    "max_t_sim": 100.0
                }
                with open(run_dir / "meta.json", "w") as f:
                    json.dump(meta, f)
                
                for csv_name in ["producer.csv", "consumer.csv", "consumer_events.csv"]:
                    with open(run_dir / csv_name, "w", newline='') as f:
                        writer = csv.writer(f)
                        writer.writerow(["run_id", "event_id"])
                        for i in range(10):
                            writer.writerow([run_id, f"e{i}"])
                
                with open(run_dir / "tti_summary.json", "w") as f:
                    json.dump({"p50": 1000}, f)
            
            summary = validate_all_runs(runlist_path)
            
            assert summary.total_runs == 2
            assert summary.passed == 2
            assert summary.failed == 0
        finally:
            os.chdir(old_cwd)

    def test_missing_run_in_list(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runlist_path = temp_dir / "runlist.txt"
            
            run_ids = ["s3_exists_kafka_rep1_20260101", "s3_missing_redis_rep1_20260101"]
            runlist_path.write_text("\n".join(run_ids) + "\n")
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            # Only create the first run
            run_dir = runs_dir / "s3_exists_kafka_rep1_20260101"
            run_dir.mkdir()
            
            meta = {
                "run_id": "s3_exists_kafka_rep1_20260101",
                "backend": "kafka",
                "plan_csv": "test.csv",
                "speedup": 120,
                "max_t_sim": 100.0
            }
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta, f)
            
            for csv_name in ["producer.csv", "consumer.csv", "consumer_events.csv"]:
                with open(run_dir / csv_name, "w", newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["run_id", "event_id"])
                    writer.writerow(["test", "e1"])
            
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump({"p50": 1000}, f)
            
            summary = validate_all_runs(runlist_path)
            
            assert summary.total_runs == 2
            assert summary.passed == 1
            assert summary.failed == 1
        finally:
            os.chdir(old_cwd)


class TestPrintSummary:
    """Tests for print_summary function."""

    def test_print_summary_all_passed(self, capsys):
        summary = ValidationSummary(
            total_runs=5,
            passed=5,
            failed=0,
            warnings=0
        )
        exit_code = print_summary(summary)
        
        captured = capsys.readouterr()
        assert "Total runs:  5" in captured.out
        assert "Passed:      5" in captured.out
        assert "Failed:      0" in captured.out
        assert exit_code == 0

    def test_print_summary_with_failures(self, capsys):
        detail1 = RunValidation(run_id="test1", status="FAIL", errors=["error1", "error2"])
        detail2 = RunValidation(run_id="test2", status="FAIL", errors=["error3"])
        summary = ValidationSummary(
            total_runs=5,
            passed=3,
            failed=2,
            warnings=0,
            details=[detail1, detail2]
        )
        exit_code = print_summary(summary)
        
        captured = capsys.readouterr()
        assert "Total runs:  5" in captured.out
        assert "Passed:      3" in captured.out
        assert "Failed:      2" in captured.out
        assert "FAILED RUNS:" in captured.out
        assert "test1" in captured.out
        assert "test2" in captured.out
        assert "error1" in captured.out
        assert exit_code == 1

    def test_print_summary_with_warnings(self, capsys):
        detail = RunValidation(run_id="test", warnings=["test warning"])
        summary = ValidationSummary(
            total_runs=1,
            passed=1,
            failed=0,
            warnings=1,
            details=[detail]
        )
        exit_code = print_summary(summary)
        
        captured = capsys.readouterr()
        assert "With warnings: 1" in captured.out
        assert exit_code == 0


class TestValidateConfigConsistency:
    """Tests for validate_config_consistency function."""

    def test_consistent_configs(self, capsys):
        kafka_meta = {"speedup": 120, "max_t_sim": 100, "plan_csv": "s3.csv", "backend": "kafka", "s3_mode": "test"}
        redis_meta = {"speedup": 120, "max_t_sim": 100, "plan_csv": "s3.csv", "backend": "redis", "s3_mode": "test"}
        
        details = [
            RunValidation(run_id="s3_test_kafka_rep1_20260101", meta=kafka_meta),
            RunValidation(run_id="s3_test_redis_rep1_20260101", meta=redis_meta)
        ]
        
        validate_config_consistency(details)
        
        captured = capsys.readouterr()
        assert "All configs are consistent" in captured.out

    def test_inconsistent_speedup(self, capsys):
        kafka_meta = {"speedup": 120, "max_t_sim": 100, "plan_csv": "s3.csv", "backend": "kafka"}
        redis_meta = {"speedup": 60, "max_t_sim": 100, "plan_csv": "s3.csv", "backend": "redis"}
        
        details = [
            RunValidation(run_id="s3_test_kafka_rep1_20260101", meta=kafka_meta),
            RunValidation(run_id="s3_test_redis_rep1_20260101", meta=redis_meta)
        ]
        
        validate_config_consistency(details)
        
        captured = capsys.readouterr()
        assert "CONFIG ISSUES FOUND" in captured.out
        assert "speedup mismatch" in captured.out

    def test_missing_meta(self, capsys):
        details = [
            RunValidation(run_id="s3_test_kafka_rep1_20260101", meta=None),
            RunValidation(run_id="s3_test_redis_rep1_20260101", meta=None)
        ]
        
        validate_config_consistency(details)
        
        captured = capsys.readouterr()
        assert "CONFIG CONSISTENCY CHECK" in captured.out

    def test_s3_mode_mismatch(self, capsys):
        kafka_meta = {
            "speedup": 120, 
            "max_t_sim": 100, 
            "plan_csv": "s3.csv", 
            "backend": "kafka", 
            "s3_mode": "mode1"
        }
        redis_meta = {
            "speedup": 120, 
            "max_t_sim": 100, 
            "plan_csv": "s3.csv", 
            "backend": "redis",
            "s3_mode": "mode2"
        }
        
        details = [
            RunValidation(run_id="s3_test_kafka_rep1_20260101", meta=kafka_meta),
            RunValidation(run_id="s3_test_redis_rep1_20260101", meta=redis_meta)
        ]
        
        validate_config_consistency(details)
        
        captured = capsys.readouterr()
        assert "CONFIG ISSUES FOUND" in captured.out
        assert "s3_mode mismatch" in captured.out
