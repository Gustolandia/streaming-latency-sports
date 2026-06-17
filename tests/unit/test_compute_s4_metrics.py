"""Complete tests for compute_s4_metrics.py - Target: 95%+ branch coverage."""
import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from compute_s4_metrics import (
    compute_tti_percentiles,
    extract_s4_config_from_runid,
    load_tti_values,
    compute_s4_metrics_for_run,
    main as s4_main
)


class TestComputeTtiPercentiles:
    """Tests for compute_tti_percentiles function."""

    def test_empty_values(self):
        result = compute_tti_percentiles([])
        assert result == {}

    def test_single_value(self):
        result = compute_tti_percentiles([1000.0])
        assert result["p50"] == 1000.0
        assert result["p95"] == 1000.0
        assert result["p99"] == 1000.0
        assert result["max"] == 1000.0
        assert result["mean"] == 1000.0
        assert result["min"] == 1000.0
        assert result["count"] == 1

    def test_multiple_values(self):
        values = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0]
        result = compute_tti_percentiles(values)
        assert result["p50"] == 3000.0
        assert result["p95"] > 4000.0
        assert result["p99"] > 4000.0
        assert result["max"] == 5000.0
        assert result["min"] == 1000.0
        assert result["count"] == 5
        assert result["mean"] == 3000.0


class TestExtractS4ConfigFromRunid:
    """Tests for extract_s4_config_from_runid function."""

    def test_baseline_config(self):
        run_id = "s4_baseline_kafka_single"
        config = extract_s4_config_from_runid(run_id)
        assert config["scenario"] == "s4"
        assert config["config"] == "baseline"
        assert config["backend"] == "kafka"
        assert config["speedup"] == 120

    def test_low_speedup_config(self):
        run_id = "s4_low_speedup_redis_single"
        config = extract_s4_config_from_runid(run_id)
        assert config["config"] == "low_speedup"
        assert config["speedup"] == 60

    def test_high_frequency_config(self):
        run_id = "s4_high_frequency_kafka_single"
        config = extract_s4_config_from_runid(run_id)
        assert config["config"] == "high_frequency"
        assert config["corrections_every_k"] == 10

    def test_unknown_config(self):
        run_id = "s4_unknown_config_kafka_single"
        config = extract_s4_config_from_runid(run_id)
        assert config["config"] == "unknown_config"
        assert "speedup" not in config

    def test_invalid_format(self):
        run_id = "invalid_run_id"
        config = extract_s4_config_from_runid(run_id)
        assert config == {}


class TestLoadTtiValues:
    """Tests for load_tti_values function."""

    def test_load_from_tti_all_ms(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        tti_data = {"tti_all_ms": [1000, 2000, 3000]}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = load_tti_values(run_dir)
        assert result == [1000, 2000, 3000]

    def test_load_from_tti_values(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        tti_data = {"tti_values": [1000, 2000, 3000]}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = load_tti_values(run_dir)
        assert result == [1000, 2000, 3000]

    def test_load_from_tti_list(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        tti_data = {"tti_list": [1000, 2000, 3000]}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = load_tti_values(run_dir)
        assert result == [1000, 2000, 3000]

    def test_missing_file(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        
        result = load_tti_values(run_dir)
        assert result == []

    def test_empty_file(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({}, f)
        
        result = load_tti_values(run_dir)
        assert result == []

    def test_corrupt_json_file(self, temp_dir):
        run_dir = temp_dir / "test_run"
        run_dir.mkdir()
        with open(run_dir / "tti_summary.json", "w") as f:
            f.write("{ invalid json")
        
        result = load_tti_values(run_dir)
        assert result == []


class TestComputeS4MetricsForRun:
    """Tests for compute_s4_metrics_for_run function."""

    def test_basic_run(self, temp_dir):
        run_dir = temp_dir / "s4_baseline_kafka_single_test"
        run_dir.mkdir()
        
        tti_data = {
            "tti_all_ms": [1000, 2000, 3000],
            "n_matched": 100,
            "n_produced": 100,
            "n_consumed": 100
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {
            "plan_csv": "data/processed/replay_plans/s4/plan.csv",
            "max_t_sim": 100.0
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with open(run_dir / "producer.csv", "w") as f:
            f.write("run_id,event_id,match_id,t_sim_seconds\n")
            for i in range(10):
                f.write(f"test_run,e{i},1,{i}.0\n")
        
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,event_id,match_id,t_sim_seconds\n")
            for i in range(10):
                f.write(f"test_run,e{i},1,{i}.0\n")
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["run"] == "s4_baseline_kafka_single_test"
        assert result["scenario"] == "s4"
        assert result["config"] == "baseline"
        assert result["backend"] == "kafka"
        assert result["speedup"] == 120
        assert result["n_producer_events"] == 10
        assert result["n_consumer_events"] == 10
        assert result["n_tti_values"] == 3

    def test_run_with_tti_ms_dict(self, temp_dir):
        run_dir = temp_dir / "s4_test_redis_cluster"
        run_dir.mkdir()
        
        tti_data = {
            "tti_ms": {
                "p50": 1500.0,
                "p95": 2500.0,
                "p99": 3000.0,
                "max": 3500.0,
                "mean": 1800.0,
                "std": 500.0,
                "min": 1000.0
            },
            "n_matched": 50
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["tti_p50"] == 1500.0
        assert result["tti_p95"] == 2500.0
        assert result["n_matched"] == 50

    def test_run_with_missed_window_rates(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_single"
        run_dir.mkdir()
        
        tti_data = {
            "tti_ms": {
                "p50": 1500.0,
                "missed_window_rate": {"100": 0.05, "500": 0.02}
            },
            "n_matched": 50
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["missed_window_100ms_rate"] == 0.05
        assert result["missed_window_500ms_rate"] == 0.02

    def test_run_with_transport_ms(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_single"
        run_dir.mkdir()
        
        tti_data = {
            "tti_ms": {"p50": 1500.0},
            "transport_ms": {"p50": 500.0, "p95": 800.0},
            "n_matched": 50
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["tti_p50"] == 1500.0
        assert result["tti_transport_ms_p50"] == 500.0
        assert result["tti_transport_ms_p95"] == 800.0

    def test_run_with_n_consumed_fallback(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_single"
        run_dir.mkdir()
        
        tti_data = {"n_consumed": 75}
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["n_tti_values"] == 75
        assert result["n_consumed"] == 75

    def test_run_with_corrupt_tti_summary(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_single"
        run_dir.mkdir()
        
        with open(run_dir / "tti_summary.json", "w") as f:
            f.write("{ invalid json")
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["n_tti_values"] == 0
        assert result["scenario"] == "s4"

    def test_run_with_corrupt_meta(self, temp_dir):
        run_dir = temp_dir / "s4_test_kafka_single"
        run_dir.mkdir()
        
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump({"tti_all_ms": [1000]}, f)
        with open(run_dir / "meta.json", "w") as f:
            f.write("{ invalid json")
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert "meta_plan_csv" not in result
        assert result["n_tti_values"] == 1

    def test_run_with_correction_delay(self, temp_dir):
        run_dir = temp_dir / "s4_long_delay_kafka_single"
        run_dir.mkdir()
        
        result = compute_s4_metrics_for_run(run_dir)
        
        assert result["correction_delay_s"] == 5.0


class TestMain:
    """Tests for main function."""

    def test_main_with_missing_runlist(self, temp_dir, monkeypatch):
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            sys.argv = ["compute_s4", "--runlist", "nonexistent.txt"]
            
            with pytest.raises(SystemExit) as exc_info:
                s4_main()
            assert exc_info.value.code == 1
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

    def test_main_with_missing_run_dir(self, temp_dir, monkeypatch):
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            runlist_path = temp_dir / "runlist.txt"
            runlist_path.write_text("nonexistent_run\n")
            
            os.chdir(temp_dir)
            sys.argv = ["compute_s4", "--runlist", str(runlist_path)]
            
            with pytest.raises(SystemExit) as exc_info:
                s4_main()
            assert exc_info.value.code == 1
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

    def test_main_basic(self, temp_dir, monkeypatch):
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            run_dir = runs_dir / "s4_baseline_kafka_single_test"
            run_dir.mkdir()
            
            tti_data = {"tti_all_ms": [1000, 2000, 3000], "n_matched": 100}
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump(tti_data, f)
            
            meta_data = {"plan_csv": "plan.csv", "max_t_sim": 100.0}
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta_data, f)
            
            with open(run_dir / "producer.csv", "w") as f:
                f.write("run_id,event_id\nrun1,e1\n")
            
            with open(run_dir / "consumer.csv", "w") as f:
                f.write("run_id,event_id\nrun1,e1\n")
            
            runlist_path = temp_dir / "runlist.txt"
            runlist_path.write_text("s4_baseline_kafka_single_test\n")
            
            out_csv = temp_dir / "output.csv"
            
            os.chdir(temp_dir)
            sys.argv = ["compute_s4", "--runlist", str(runlist_path), "--out", str(out_csv)]
            
            s4_main()
            
            assert out_csv.exists()
            
            summary_path = temp_dir / "output_summary.json"
            assert summary_path.exists()
        
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

    def test_main_with_runs_backslash_path(self, temp_dir, monkeypatch):
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            run_dir = runs_dir / "s4_baseline_kafka_single_test"
            run_dir.mkdir()
            tti_data = {"tti_all_ms": [1000, 2000, 3000], "n_matched": 100}
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump(tti_data, f)
            runlist_path = temp_dir / "runlist.txt"
            runlist_path.write_text("runs\\s4_baseline_kafka_single_test\n")
            out_csv = temp_dir / "output.csv"
            os.chdir(temp_dir)
            sys.argv = ["compute_s4", "--runlist", str(runlist_path), "--out", str(out_csv)]
            s4_main()
            assert out_csv.exists()
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)

    def test_main_with_runs_forward_slash_path(self, temp_dir, monkeypatch):
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            run_dir = runs_dir / "s4_baseline_kafka_single_test"
            run_dir.mkdir()
            tti_data = {"tti_all_ms": [1000, 2000, 3000], "n_matched": 100}
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump(tti_data, f)
            runlist_path = temp_dir / "runlist.txt"
            runlist_path.write_text("runs/s4_baseline_kafka_single_test\n")
            out_csv = temp_dir / "output.csv"
            os.chdir(temp_dir)
            sys.argv = ["compute_s4", "--runlist", str(runlist_path), "--out", str(out_csv)]
            s4_main()
            assert out_csv.exists()
        finally:
            sys.argv = old_argv
            os.chdir(old_cwd)
