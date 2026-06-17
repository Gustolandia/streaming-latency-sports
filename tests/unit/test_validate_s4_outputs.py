"""Complete tests for validate_s4_outputs.py - Target: 95%+ branch coverage."""
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
from validate_s4_outputs import (
    RunValidation,
    ValidationSummary,
    validate_run,
    validate_all_s4_runs,
    print_summary,
    save_report,
    find_s4_run_dirs,
    get_expected_events,
    main,
)


class TestMain:
    """Tests for the main entry point."""

    @patch("validate_s4_outputs.save_report")
    @patch("validate_s4_outputs.print_summary")
    @patch("validate_s4_outputs.validate_all_s4_runs")
    def test_main_runs_pipeline(self, mock_validate_all, mock_print_summary, mock_save_report):
        mock_validate_all.return_value = ValidationSummary(total_runs=2, passed=2)

        with patch("sys.argv", ["validate_s4_outputs.py"]):
            main()

        mock_validate_all.assert_called_once()
        mock_print_summary.assert_called_once()
        mock_save_report.assert_called_once()

    @patch("validate_s4_outputs.save_report")
    @patch("validate_s4_outputs.print_summary")
    @patch("validate_s4_outputs.validate_all_s4_runs")
    def test_main_with_custom_args(self, mock_validate_all, mock_print_summary, mock_save_report):
        mock_validate_all.return_value = ValidationSummary(total_runs=1, passed=1)

        argv = ["validate_s4_outputs.py", "--runs-dir", "myruns", "--output", "out.json", "--verbose"]
        with patch("sys.argv", argv):
            main()

        mock_validate_all.assert_called_once()
        mock_print_summary.assert_called_once()


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
        assert result.s4_specific == {}


class TestValidationSummaryDataclass:
    """Tests for ValidationSummary dataclass."""

    def test_default_values(self):
        summary = ValidationSummary()
        assert summary.total_runs == 0
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.warnings == 0
        assert summary.errors == []
        assert summary.details == []
        assert summary.scenario_counts == {}
        assert summary.config_counts == {}
        assert summary.backend_counts == {}


class TestGetExpectedEvents:
    """Tests for get_expected_events function."""

    def test_s2sf12_scenario(self):
        assert get_expected_events("s4_s2sf12_baseline_kafka_rep1_20260101") == 4554

    def test_s2sf12j2_scenario(self):
        assert get_expected_events("s4_s2sf12j2_baseline_kafka_rep1_20260101") == 4554

    def test_fallback_scenario(self):
        assert get_expected_events("s4_unknown_kafka_rep1_20260101") == 4000


class TestValidateRun:
    """Tests for validate_run function."""

    def test_valid_run(self, temp_dir):
        run_dir = temp_dir / "s4_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()
        
        # Create meta.json
        meta = {
            "run_id": "s4_s2sf12_baseline_kafka_rep1_20260101",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s4/plan.csv",
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
        tti_data = {"matched_events": 4554, "p50": 1000, "p95": 2000, "p99": 3000}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = validate_run(run_dir)
        
        assert result.run_id == "s4_s2sf12_baseline_kafka_rep1_20260101"
        assert result.status == "PASS"
        assert len(result.errors) == 0
        assert result.meta == meta
        assert result.event_counts["producer.csv"] == 100
        assert result.event_counts["consumer.csv"] == 100
        assert result.files["meta.json"] is True
        assert result.files["tti_summary.json"] is True
        assert "scenario" in result.s4_specific
        assert result.s4_specific["scenario"] == "s2sf12"
        assert result.s4_specific["config"] == "baseline"
        assert result.s4_specific["backend"] == "kafka"

    def test_missing_meta_json(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert "Missing or empty: meta.json" in result.errors
        assert result.files["meta.json"] is False

    def test_missing_required_meta_field(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {"run_id": "test"}
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("missing field: backend" in e for e in result.errors)

    def test_invalid_backend(self, temp_dir):
        run_dir = temp_dir / "s4_test_invalid_rep1_20260101"
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
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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

    def test_event_count_mismatch_warning(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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
            json.dump({"matched_events": 50, "p50": 1000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("Event count mismatch" in w for w in result.warnings)

    def test_matched_events_mismatch_warning(self, temp_dir):
        run_dir = temp_dir / "s4_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "s4_s2sf12_baseline_kafka_rep1_20260101",
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
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"matched_events": 100, "p50": 1000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("Matched events" in w and "!= expected" in w for w in result.warnings)

    def test_missing_percentile_warning(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"matched_events": 1, "p50": 1000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("Missing percentile: p95" in w or "Missing percentile: p99" in w for w in result.warnings)

    def test_corrupt_meta_json(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
        run_dir.mkdir()
        
        with open(run_dir / "meta.json", "w") as f:
            f.write("{ invalid json")
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("meta.json invalid" in e for e in result.errors)

    def test_empty_tti_summary(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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
        
        # Create required CSV files
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        # Create empty tti_summary.json
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "FAIL"
        assert any("tti_summary.json is empty" in e for e in result.errors)

    def test_corrupt_tti_summary(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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
        run_dir = temp_dir / "s4_test_kafka_rep1_20260101"
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
        assert any("producer.csv" in e and ("empty" in e.lower() or "no data" in e) for e in result.errors)

    def test_unknown_config_warning(self, temp_dir):
        run_dir = temp_dir / "s4_s2sf12_unknown_config_kafka_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "s4_s2sf12_unknown_config_kafka_rep1_20260101",
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
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"matched_events": 1, "p50": 1000, "p95": 2000, "p99": 3000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert len(result.warnings) > 0
        assert any("Unknown config" in w for w in result.warnings)

    def test_complex_config_name_parsing(self, temp_dir):
        run_dir = temp_dir / "s4_s2sf12j2_fast_corrections_redis_rep1_20260101"
        run_dir.mkdir()
        
        meta = {
            "run_id": "s4_s2sf12j2_fast_corrections_redis_rep1_20260101",
            "backend": "redis",
            "plan_csv": "test.csv",
            "speedup": 120,
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        with open(run_dir / "producer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "consumer_events.csv", "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["run_id", "event_id"])
            writer.writerow(["test", "e1"])
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"matched_events": 4554, "p50": 1000, "p95": 2000, "p99": 3000}, f)
        
        result = validate_run(run_dir)
        
        assert result.status == "PASS"
        assert result.s4_specific["scenario"] == "s2sf12j2"
        assert result.s4_specific["config"] == "fast_corrections"
        assert result.s4_specific["backend"] == "redis"




class TestFindS4RunDirs:
    """Tests for find_s4_run_dirs function."""

    def test_find_s4_dirs(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            # Create S4 run directories
            (runs_dir / "s4_test1_kafka_rep1_20260101").mkdir()
            (runs_dir / "s4_test2_redis_rep1_20260101").mkdir()
            # Create non-S4 directory
            (runs_dir / "s3_test_kafka_rep1_20260101").mkdir()
            
            s4_dirs = find_s4_run_dirs(runs_dir)
            
            assert len(s4_dirs) == 2
            assert all(d.name.startswith("s4_") for d in s4_dirs)
        finally:
            os.chdir(old_cwd)

    def test_empty_directory(self, temp_dir):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        s4_dirs = find_s4_run_dirs(runs_dir)
        
        assert len(s4_dirs) == 0


class TestValidateAllS4Runs:
    """Tests for validate_all_s4_runs function."""

    def test_valid_runs(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            run_ids = ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_baseline_redis_rep1_20260101"]
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
                    json.dump({"matched_events": 4554, "p50": 1000, "p95": 2000, "p99": 3000}, f)
            
            summary = validate_all_s4_runs(runs_dir)
            
            assert summary.total_runs == 2
            assert summary.passed == 2
            assert summary.failed == 0
            assert summary.scenario_counts.get("s2sf12", 0) == 2
            assert summary.backend_counts.get("kafka", 0) == 1
            assert summary.backend_counts.get("redis", 0) == 1
        finally:
            os.chdir(old_cwd)

    def test_failed_run(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            run_dir = runs_dir / "s4_test_kafka_rep1_20260101"
            run_dir.mkdir()
            
            # Create an invalid run (missing required meta fields)
            meta = {"run_id": "test"}
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta, f)
            
            summary = validate_all_s4_runs(runs_dir)
            
            assert summary.total_runs == 1
            assert summary.failed == 1
            assert summary.passed == 0
        finally:
            os.chdir(old_cwd)

    def test_no_s4_dirs(self, temp_dir):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        summary = validate_all_s4_runs(runs_dir)
        
        assert summary.total_runs == 0


class TestPrintSummary:
    """Tests for print_summary function."""

    def test_print_summary_all_passed(self, capsys):
        detail1 = RunValidation(run_id="test1", status="PASS")
        detail2 = RunValidation(run_id="test2", status="PASS")
        summary = ValidationSummary(
            total_runs=2,
            passed=2,
            failed=0,
            warnings=0,
            details=[detail1, detail2]
        )
        print_summary(summary)
        
        captured = capsys.readouterr()
        assert "Total runs: 2" in captured.out
        assert "Passed: 2" in captured.out
        assert "Failed: 0" in captured.out
        assert "ALL S4 RUN OUTPUTS VALIDATED SUCCESSFULLY" in captured.out

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
        
        with pytest.raises(SystemExit) as exc_info:
            print_summary(summary)
        
        captured = capsys.readouterr()
        assert "Total runs: 5" in captured.out
        assert "Passed: 3" in captured.out
        assert "Failed: 2" in captured.out
        assert "FAILED RUNS:" in captured.out
        assert "test1" in captured.out
        assert "test2" in captured.out
        assert "error1" in captured.out
        assert exc_info.value.code == 1

    def test_print_summary_with_warnings_verbose(self, capsys):
        detail = RunValidation(run_id="test", warnings=["test warning"])
        summary = ValidationSummary(
            total_runs=1,
            passed=1,
            failed=0,
            warnings=1,
            details=[detail]
        )
        print_summary(summary, verbose=True)
        
        captured = capsys.readouterr()
        assert "With warnings: 1" in captured.out or "Warnings: 1" in captured.out
        assert "ALL S4 RUN OUTPUTS VALIDATED SUCCESSFULLY" in captured.out


class TestSaveReport:
    """Tests for save_report function."""

    def test_save_report(self, temp_dir):
        detail1 = RunValidation(run_id="test1", status="PASS")
        detail2 = RunValidation(run_id="test2", status="FAIL", errors=["error1"])
        summary = ValidationSummary(
            total_runs=2,
            passed=1,
            failed=1,
            warnings=0,
            details=[detail1, detail2],
            scenario_counts={"s2sf12": 2},
            config_counts={"baseline": 2},
            backend_counts={"kafka": 1, "redis": 1}
        )
        
        output_path = temp_dir / "report.json"
        save_report(summary, output_path)
        
        assert output_path.exists()
        with open(output_path, encoding='utf-8') as f:
            report = json.load(f)
        
        assert report["summary"]["total_runs"] == 2
        assert report["summary"]["passed"] == 1
        assert report["summary"]["failed"] == 1
        assert len(report["runs"]) == 2
