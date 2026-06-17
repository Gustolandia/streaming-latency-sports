"""Complete tests for compute_s3_metrics.py - 100% branch coverage."""
import pytest
import pandas as pd
import numpy as np
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

from compute_s3_metrics import now_ms, compute_percentiles, compute_s3_metrics_for_run, main as s3_main


class TestNowMs:
    def test_converts_ns_to_ms(self):
        assert now_ms(1_000_000) == 1.0
        assert now_ms(500_000) == 0.5
        assert now_ms(0) == 0.0


class TestComputePercentiles:
    def test_with_values(self):
        result = compute_percentiles([10.0, 20.0, 30.0, 40.0, 50.0])
        assert result is not None
        assert "p50" in result
        assert "p95" in result
        assert "p99" in result
        assert "max" in result
        assert "min" in result
        assert "mean" in result
        assert "std" in result
        assert "count" in result

    def test_with_empty(self):
        assert compute_percentiles([]) is None

    def test_with_none(self):
        assert compute_percentiles(None) is None

    def test_with_single_value(self):
        result = compute_percentiles([50.0])
        assert result["p50"] == 50.0
        assert result["max"] == 50.0
        assert result["min"] == 50.0
        assert result["std"] == 0.0
        assert result["count"] == 1


class TestComputeS3MetricsForRun:
    def test_with_corrections(self):
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000,"t_emit_planned_ns":1000000},
            {"event_id":"e1r2","s3_uid":"m1:e1","s3_rev":2,"s3_is_correction":True,"t_consume_ns":2000000,"t_emit_planned_ns":1500000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["run"] == "r1"
        assert result["n_corrections"] == 1
        assert result["n_base_events"] == 1
        assert result["n_base_events_with_corrections"] == 1
        assert "correction_propagation_latency_ms" in result
        assert "inconsistency_duration_ms" in result
        assert "correction_planned_to_consume_latency_ms" in result

    def test_no_corrections(self):
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e2","s3_uid":"m1:e2","s3_rev":1,"s3_is_correction":False,"t_consume_ns":2000000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 0
        assert result["n_base_events"] == 2
        assert result["n_base_events_with_corrections"] == 0
        assert "correction_propagation_latency_ms" not in result
        assert "inconsistency_duration_ms" not in result

    def test_single_revision(self):
        data = [{"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000}]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 0
        assert result["n_base_events_with_corrections"] == 0

    def test_empty_df(self):
        df = pd.DataFrame(columns=["s3_is_correction"])
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 0
        assert result["n_base_events"] == 0
        assert result["n_base_events_with_corrections"] == 0

    def test_missing_t_consume_ns(self):
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e1r2","s3_uid":"m1:e1","s3_rev":2,"s3_is_correction":True,"t_consume_ns":0,"t_emit_planned_ns":1500000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        # Should handle 0 t_consume_ns
        assert result["n_corrections"] == 1

    def test_multiple_revisions(self):
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000,"t_emit_planned_ns":1000000},
            {"event_id":"e1r2","s3_uid":"m1:e1","s3_rev":2,"s3_is_correction":True,"t_consume_ns":2000000,"t_emit_planned_ns":1500000},
            {"event_id":"e1r3","s3_uid":"m1:e1","s3_rev":3,"s3_is_correction":True,"t_consume_ns":3000000,"t_emit_planned_ns":2500000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 2
        assert result["n_base_events_with_corrections"] == 1
        assert result["correction_propagation_latency_ms"]["count"] == 2

    def test_missing_s3_uid(self):
        """Test line 81: continue when s3_uid is None."""
        data = [
            {"event_id":"e1","s3_uid":None,"s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e2","s3_uid":"m1:e2","s3_rev":1,"s3_is_correction":False,"t_consume_ns":2000000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 0
        # Both rows are base events (s3_is_correction=False), but only e2 has valid s3_uid for matching
        assert result["n_base_events"] == 2
        assert result["n_base_events_with_corrections"] == 0

    def test_all_s3_uid_none(self):
        """Test line 81: all rows have None s3_uid."""
        data = [
            {"event_id":"e1","s3_uid":None,"s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e2","s3_uid":None,"s3_rev":1,"s3_is_correction":False,"t_consume_ns":2000000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert result["n_corrections"] == 0
        assert result["n_base_events"] == 2
        assert result["n_base_events_with_corrections"] == 0
        # All rows skipped in uid_to_events loop, so no metrics
        assert "correction_propagation_latency_ms" not in result

    def test_no_t_emit_planned_ns(self):
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e1r2","s3_uid":"m1:e1","s3_rev":2,"s3_is_correction":True,"t_consume_ns":2000000,"t_emit_planned_ns":None},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        assert "correction_planned_to_consume_latency_ms" not in result

    def test_correction_planned_to_consume_latency(self):
        """Test lines 134->140: branch when len(corr_consume) == len(corr_planned)."""
        data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000,"t_emit_planned_ns":1000000},
            {"event_id":"e1r2","s3_uid":"m1:e1","s3_rev":2,"s3_is_correction":True,"t_consume_ns":2000000,"t_emit_planned_ns":1500000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        # Both have t_emit_planned_ns and t_consume_ns, so the branch should be taken
        assert "correction_planned_to_consume_latency_ms" in result
        assert result["correction_planned_to_consume_latency_ms"]["count"] == 1

    def test_with_none_s3_uid(self):
        """Test line 90: continue when s3_uid is None."""
        data = [
            {"event_id":"e1","s3_uid":None,"s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e2","s3_uid":"m1:e2","s3_rev":1,"s3_is_correction":False,"t_consume_ns":2000000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        # Both are base events (s3_is_correction=False), but only e2 has valid s3_uid
        # n_base_events counts all non-correction events regardless of s3_uid
        assert result["n_base_events"] == 2
        # But only e2 with valid s3_uid is in uid_to_events, so no corrections to match
        assert result["n_base_events_with_corrections"] == 0

    def test_with_nan_s3_uid(self):
        """Test line 90: continue when s3_uid is NaN."""
        data = [
            {"event_id":"e1","s3_uid":np.nan,"s3_rev":1,"s3_is_correction":False,"t_consume_ns":1000000},
            {"event_id":"e2","s3_uid":"m1:e2","s3_rev":1,"s3_is_correction":False,"t_consume_ns":2000000},
        ]
        df = pd.DataFrame(data)
        result = compute_s3_metrics_for_run("r1", df)
        # Both are base events (s3_is_correction=False), but only e2 has valid s3_uid
        assert result["n_base_events"] == 2
        assert result["n_base_events_with_corrections"] == 0


class TestMain:
    def test_main_with_runlist(self, temp_dir, monkeypatch):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run1"
        run_dir.mkdir()
        events_data = [
            {"run_id":"run1","backend":"kafka","topic":"t","partition":0,"offset":1,
             "t_consume_ns":1000000,"event_id":"e1","match_id":1,"t_sim_seconds":0.0,
             "t_emit_offset_s":0.0,"t_emit_planned_ns":1000000,"s3_uid":"1:e1","s3_rev":1,"s3_is_correction":False},
        ]
        pd.DataFrame(events_data).to_csv(run_dir / "consumer_events.csv", index=False)
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\n")
        
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            s3_main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv
        # Files are written relative to temp_dir
        assert (temp_dir / "data" / "processed" / "results" / "paper_s3_official.csv").exists()

    def test_main_missing_runlist(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            with pytest.raises(SystemExit):
                s3_main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

    def test_main_missing_consumer_events(self, temp_dir, monkeypatch):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run1"
        run_dir.mkdir()
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\n")
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            with pytest.raises(SystemExit):
                s3_main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

    def test_main_skips_comments(self, temp_dir, monkeypatch):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("# comment\n\n")
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            s3_main([])  # Should not fail
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

    def test_main_empty_runlist(self, temp_dir, monkeypatch):
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("\n\n")
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            s3_main([])  # Should handle empty list gracefully
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

    def test_main_missing_t_consume_ns(self, temp_dir, monkeypatch):
        """Test line 164: SystemExit when t_consume_ns is missing."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run1"
        run_dir.mkdir()
        
        # Create events file without t_consume_ns
        events_data = [
            {"event_id":"e1","s3_uid":"m1:e1","s3_rev":1,"s3_is_correction":False},
        ]
        pd.DataFrame(events_data).to_csv(run_dir / "consumer_events.csv", index=False)
        
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\n")
        
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            with pytest.raises(SystemExit):
                s3_main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

    def test_main_aggregates_correction_latency(self, temp_dir, monkeypatch):
        """Test lines 191-205: aggregation of correction propagation latency across runs."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()

        # Create two runs with corrections
        for run_name in ["run1", "run2"]:
            run_dir = runs_dir / run_name
            run_dir.mkdir()
            events_data = [
                {"run_id": run_name, "backend": "kafka", "topic": "t", "partition": 0, "offset": 1,
                 "t_consume_ns": 1000000, "event_id": "e1", "match_id": 1, "t_sim_seconds": 0.0,
                 "t_emit_offset_s": 0.0, "t_emit_planned_ns": 1000000, "s3_uid": f"{run_name}:e1", "s3_rev": 1, "s3_is_correction": False},
                {"run_id": run_name, "backend": "kafka", "topic": "t", "partition": 0, "offset": 2,
                 "t_consume_ns": 2000000, "event_id": "e1r2", "match_id": 1, "t_sim_seconds": 0.0,
                 "t_emit_offset_s": 0.0, "t_emit_planned_ns": 1500000, "s3_uid": f"{run_name}:e1", "s3_rev": 2, "s3_is_correction": True},
            ]
            pd.DataFrame(events_data).to_csv(run_dir / "consumer_events.csv", index=False)

        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\nrun2\n")

        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            s3_main([])
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

        # Check that aggregation happened
        summary_path = temp_dir / "docs" / "results" / "paper_s3_official_summary.json"
        assert summary_path.exists()
        with open(summary_path) as f:
            summary = json.load(f)
        assert "correction_propagation_latency_p50_ms" in summary
        assert "correction_propagation_latency_mean_ms" in summary
        assert summary["total_corrections"] == 2

    def test_main_aggregates_invalid_json_string(self, temp_dir, monkeypatch):
        """Test lines 195-198: exception handling when prop_metrics is an invalid JSON string."""
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        run_dir = runs_dir / "run1"
        run_dir.mkdir()
        
        events_data = [
            {"run_id": "run1", "backend": "kafka", "topic": "t", "partition": 0, "offset": 1,
             "t_consume_ns": 1000000, "event_id": "e1", "match_id": 1, "t_sim_seconds": 0.0,
             "t_emit_offset_s": 0.0, "t_emit_planned_ns": 1000000, "s3_uid": "run1:e1", "s3_rev": 1, "s3_is_correction": False},
            {"run_id": "run1", "backend": "kafka", "topic": "t", "partition": 0, "offset": 2,
             "t_consume_ns": 2000000, "event_id": "e1r2", "match_id": 1, "t_sim_seconds": 0.0,
             "t_emit_offset_s": 0.0, "t_emit_planned_ns": 1500000, "s3_uid": "run1:e1", "s3_rev": 2, "s3_is_correction": True},
        ]
        pd.DataFrame(events_data).to_csv(run_dir / "consumer_events.csv", index=False)

        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\n")

        # We need to patch the DataFrame so that correction_propagation_latency_ms is a string
        # This simulates reading from a previously-written CSV
        original_dataframe = pd.DataFrame
        
        def patched_dataframe(*args, **kwargs):
            df = original_dataframe(*args, **kwargs)
            # Convert correction_propagation_latency_ms dict to string
            if "correction_propagation_latency_ms" in df.columns:
                df["correction_propagation_latency_ms"] = df["correction_propagation_latency_ms"].apply(
                    lambda x: "{invalid json" if isinstance(x, dict) else x
                )
            return df
        
        old_cwd = os.getcwd()
        old_argv = sys.argv
        try:
            os.chdir(temp_dir)
            sys.argv = ["s3m"]
            with patch('compute_s3_metrics.pd.DataFrame', side_effect=patched_dataframe):
                s3_main([])  # Should not crash, just skip the invalid JSON
        finally:
            os.chdir(old_cwd)
            sys.argv = old_argv

        summary_path = temp_dir / "docs" / "results" / "paper_s3_official_summary.json"
        assert summary_path.exists()
        with open(summary_path) as f:
            summary = json.load(f)
        # Should not have aggregation metrics since JSON was invalid
        assert "correction_propagation_latency_p50_ms" not in summary

    def test_main_as_script(self, temp_dir):
        """Test line 214: if __name__ == '__main__' block by running as subprocess with coverage."""
        # The script has hardcoded paths, so we need to create files at the expected locations
        # runs/_paper_s3_official_runs.txt is the hardcoded runlist
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        runlist_path = runs_dir / "_paper_s3_official_runs.txt"
        runlist_path.write_text("run1\n")
        
        run_dir = runs_dir / "run1"
        run_dir.mkdir()
        consumer_path = run_dir / "consumer_events.csv"
        pd.DataFrame({
            "event_id": ["e1"], "s3_uid": ["uid1"], "s3_rev": [1], 
            "t_consume_ns": [1000000], "s3_is_correction": [False]
        }).to_csv(consumer_path, index=False)
        
        env = os.environ.copy()
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        repo_root = str(Path(__file__).parent.parent.parent)
        env["PYTHONPATH"] = scripts_dir + ";" + env.get("PYTHONPATH", "")
        coveragerc_path = str(Path(repo_root) / ".coveragerc")
        env["COVERAGE_PROCESS_START"] = coveragerc_path
        
        result = subprocess.run(
            [sys.executable, str(Path(scripts_dir) / "compute_s3_metrics.py")],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result.returncode == 0
