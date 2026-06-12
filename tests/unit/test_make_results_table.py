"""Complete tests for make_results_table.py - 100% branch coverage."""
import pytest
import pandas as pd
import json
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Mock external dependencies
sys.modules['kafka'] = MagicMock()
sys.modules['kafka.KafkaProducer'] = MagicMock()
sys.modules['kafka.KafkaConsumer'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['redis.Redis'] = MagicMock()

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_results_table import get_nested, load_summary, main as mrt_main


class TestGetNested:
    def test_simple_path(self):
        d = {"a": {"b": {"c": 42}}}
        assert get_nested(d, ["a", "b", "c"]) == 42

    def test_missing_key(self):
        d = {"a": {"b": {}}}
        assert get_nested(d, ["a", "b", "c"]) is None

    def test_custom_default(self):
        d = {"a": {"b": {}}}
        assert get_nested(d, ["a", "b", "c"], default="default") == "default"

    def test_empty_path(self):
        d = {"a": 42}
        assert get_nested(d, []) == d

    def test_non_dict_intermediate(self):
        d = {"a": "string"}
        assert get_nested(d, ["a", "b"]) is None

    def test_top_level_missing(self):
        d = {"b": 42}
        assert get_nested(d, ["a"]) is None

    def test_deep_path(self):
        d = {"a": {"b": {"c": {"d": {"e": "value"}}}}}
        assert get_nested(d, ["a", "b", "c", "d", "e"]) == "value"


class TestLoadSummary:
    def test_load_valid_summary(self, temp_dir):
        run_dir = temp_dir / "kafka_run1"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {
                "p50": 100.5,
                "p95": 200.5,
                "p99": 300.5,
                "max": 500.5,
                "missed_window_rate": {"100": 0.0, "250": 0.1}
            },
            "transport_ms": {
                "p50": 10.5,
                "p95": 20.5,
                "p99": 30.5,
                "max": 50.5
            },
            "producer_sched_lag_ms": {
                "p50": 1.5,
                "p95": 2.5,
                "p99": 3.5,
                "max": 5.5,
                "missed_window_rate": {"100": 0.0, "250": 0.0}
            }
        }
        summary_path = run_dir / "tti_summary.json"
        summary_path.write_text(json.dumps(tti_data))
        
        row = load_summary(run_dir)
        
        assert row["run"] == "kafka_run1"
        assert row["backend"] == "kafka"
        assert row["n_produced"] == 100
        assert row["n_consumed"] == 100
        assert row["n_matched"] == 100
        assert row["tti_p50_ms"] == 100.5
        assert row["tti_p95_ms"] == 200.5
        assert row["tti_p99_ms"] == 300.5
        assert row["tti_max_ms"] == 500.5
        assert row["tti_miss_100ms"] == 0.0
        assert row["tti_miss_250ms"] == 0.1
        assert row["transport_p50_ms"] == 10.5
        assert row["schedlag_p50_ms"] == 1.5

    def test_load_redis_summary(self, temp_dir):
        run_dir = temp_dir / "redis_run1"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 50,
            "n_consumed": 50,
            "n_matched": 50,
            "tti_ms": {"p50": 150.0, "p95": 250.0, "p99": 350.0, "max": 450.0}
        }
        summary_path = run_dir / "tti_summary.json"
        summary_path.write_text(json.dumps(tti_data))
        
        row = load_summary(run_dir)
        
        assert row["run"] == "redis_run1"
        assert row["backend"] == "redis"
        assert row["n_produced"] == 50

    def test_load_unknown_backend(self, temp_dir):
        run_dir = temp_dir / "unknown_run1"
        run_dir.mkdir()
        
        tti_data = {"n_produced": 10}
        summary_path = run_dir / "tti_summary.json"
        summary_path.write_text(json.dumps(tti_data))
        
        row = load_summary(run_dir)
        
        assert row["run"] == "unknown_run1"
        assert row["backend"] == "unknown"

    def test_missing_summary_file(self, temp_dir):
        run_dir = temp_dir / "no_summary"
        run_dir.mkdir()
        
        row = load_summary(run_dir)
        assert row is None

    def test_missing_nested_values(self, temp_dir):
        run_dir = temp_dir / "missing_values"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 10,
            "tti_ms": {"p50": 100.0}
        }
        summary_path = run_dir / "tti_summary.json"
        summary_path.write_text(json.dumps(tti_data))
        
        row = load_summary(run_dir)
        
        assert row["n_produced"] == 10
        assert row["tti_p50_ms"] == 100.0
        assert row["tti_p95_ms"] is None
        assert row["transport_p50_ms"] is None

    def test_all_missed_window_fields(self, temp_dir):
        run_dir = temp_dir / "missed_windows"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 100,
            "tti_ms": {
                "missed_window_rate": {"100": 0.1, "250": 0.2, "500": 0.3, "1000": 0.4, "2000": 0.5, "5000": 0.6}
            },
            "producer_sched_lag_ms": {
                "missed_window_rate": {"100": 0.05, "250": 0.15, "500": 0.25, "1000": 0.35, "2000": 0.45, "5000": 0.55}
            }
        }
        summary_path = run_dir / "tti_summary.json"
        summary_path.write_text(json.dumps(tti_data))
        
        row = load_summary(run_dir)
        
        assert row["tti_miss_100ms"] == 0.1
        assert row["tti_miss_250ms"] == 0.2
        assert row["tti_miss_500ms"] == 0.3
        assert row["tti_miss_1000ms"] == 0.4
        assert row["tti_miss_2000ms"] == 0.5
        assert row["tti_miss_5000ms"] == 0.6
        assert row["schedlag_miss_100ms"] == 0.05
        assert row["schedlag_miss_5000ms"] == 0.55


class TestMain:
    def test_main_with_valid_runs(self, temp_dir):
        # Create run directories with tti_summary.json files
        run1_dir = temp_dir / "runs" / "kafka_run1"
        run1_dir.mkdir(parents=True)
        tti_data1 = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {"p50": 100.0, "p95": 200.0, "p99": 300.0, "max": 400.0}
        }
        (run1_dir / "tti_summary.json").write_text(json.dumps(tti_data1))
        
        run2_dir = temp_dir / "runs" / "redis_run1"
        run2_dir.mkdir()
        tti_data2 = {
            "n_produced": 50,
            "n_consumed": 50,
            "n_matched": 50,
            "tti_ms": {"p50": 150.0, "p95": 250.0, "p99": 350.0, "max": 450.0}
        }
        (run2_dir / "tti_summary.json").write_text(json.dumps(tti_data2))
        
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        try:
            sys.argv = ["mrt", "--runs", str(run1_dir), str(run2_dir), "--out", str(out_path)]
            mrt_main()
        finally:
            sys.argv = old_argv
        
        assert out_path.exists()
        df = pd.read_csv(out_path)
        assert len(df) == 2
        assert "run" in df.columns
        assert "backend" in df.columns
        assert "n_produced" in df.columns

    def test_main_with_alt_paths(self, temp_dir, monkeypatch):
        # Test that it tries runs/<RUN_ID> as alternative
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        run_dir = runs_dir / "test_run"
        run_dir.mkdir()
        tti_data = {
            "n_produced": 10,
            "n_consumed": 10,
            "n_matched": 10,
            "tti_ms": {"p50": 50.0, "p95": 100.0, "p99": 150.0, "max": 200.0}
        }
        (run_dir / "tti_summary.json").write_text(json.dumps(tti_data))
        
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            sys.argv = ["mrt", "--runs", "test_run", "--out", str(out_path)]
            mrt_main()
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        
        assert out_path.exists()
        df = pd.read_csv(out_path)
        assert len(df) == 1
        assert df.iloc[0]["run"] == "test_run"

    def test_main_alt_path_not_exists(self, temp_dir, monkeypatch):
        # Test when alt path doesn't exist either
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            sys.argv = ["mrt", "--runs", "nonexistent", "--out", str(out_path)]
            mrt_main()
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        
        # Should have skipped the run
        assert not out_path.exists()
        # But shouldn't crash

    def test_main_all_skipped(self, temp_dir, capsys):
        # All runs don't have tti_summary.json
        run1_dir = temp_dir / "runs" / "run1"
        run1_dir.mkdir(parents=True)
        
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        try:
            sys.argv = ["mrt", "--runs", str(run1_dir), "--out", str(out_path)]
            mrt_main()
        finally:
            sys.argv = old_argv
        
        captured = capsys.readouterr()
        assert "No runs loaded" in captured.out
        assert not out_path.exists()

    def test_main_empty_runs_list(self, temp_dir, capsys):
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        try:
            sys.argv = ["mrt", "--runs", "--out", str(out_path)]
            with pytest.raises(SystemExit):
                mrt_main()
        finally:
            sys.argv = old_argv

    def test_main_creates_parent_dirs(self, temp_dir):
        run_dir = temp_dir / "runs" / "test_run"
        run_dir.mkdir(parents=True)
        tti_data = {"n_produced": 10}
        (run_dir / "tti_summary.json").write_text(json.dumps(tti_data))
        
        out_path = temp_dir / "subdir" / "nested" / "results.csv"
        
        old_argv = sys.argv
        try:
            sys.argv = ["mrt", "--runs", str(run_dir), "--out", str(out_path)]
            mrt_main()
        finally:
            sys.argv = old_argv
        
        assert out_path.exists()

    def test_main_skipped_count(self, temp_dir, capsys):
        # One run has summary, one doesn't
        run1_dir = temp_dir / "runs" / "run1"
        run1_dir.mkdir(parents=True)
        tti_data = {"n_produced": 10}
        (run1_dir / "tti_summary.json").write_text(json.dumps(tti_data))
        
        run2_dir = temp_dir / "runs" / "run2"
        run2_dir.mkdir()
        
        out_path = temp_dir / "results.csv"
        
        old_argv = sys.argv
        try:
            sys.argv = ["mrt", "--runs", str(run1_dir), str(run2_dir), "--out", str(out_path)]
            mrt_main()
        finally:
            sys.argv = old_argv
        
        captured = capsys.readouterr()
        assert "skipped 1 run" in captured.out
        assert out_path.exists()
        df = pd.read_csv(out_path)
        assert len(df) == 1

    def test_main_as_script(self, temp_dir):
        """Test line 90: if __name__ == '__main__' block by running as subprocess with coverage."""
        import subprocess
        
        run_dir = temp_dir / "runs" / "run1"
        run_dir.mkdir(parents=True)
        
        tti_summary = {
            "run_id": "run1", "n_produced": 100, "n_consumed": 100, "n_matched": 100,
            "tti_ms": {"p50": 50.0}, "transport_ms": {"p50": 20.0}, "producer_sched_lag_ms": {"p50": 2.0},
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_summary, f)
        
        meta = {"run_id": "run1", "backend": "kafka"}
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta, f)
        
        env = os.environ.copy()
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        repo_root = str(Path(__file__).parent.parent.parent)
        env["PYTHONPATH"] = scripts_dir + ";" + env.get("PYTHONPATH", "")
        coveragerc_path = str(Path(repo_root) / ".coveragerc")
        env["COVERAGE_PROCESS_START"] = coveragerc_path
        
        result = subprocess.run(
            [sys.executable, str(Path(scripts_dir) / "make_results_table.py"),
             "--runs", str(temp_dir / "runs" / "run1"),
             "--out", str(temp_dir / "results.csv")],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result.returncode == 0
