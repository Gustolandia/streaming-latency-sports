"""Complete tests for compute_tti.py - 100% branch coverage."""
import pytest
import pandas as pd
import numpy as np
import json
import csv
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

from compute_tti import now_ms, compute_metrics, main as tti_main


class TestNowMs:
    def test_converts_ns_to_ms(self):
        assert now_ms(1_000_000) == 1.0
        assert now_ms(500_000) == 0.5
        assert now_ms(0) == 0.0
        assert now_ms(1_500_000) == 1.5


class TestComputeMetrics:
    def test_with_all_values(self):
        tti = [10.0, 20.0, 30.0, 40.0, 50.0]
        transport = [1.0, 2.0, 3.0, 4.0, 5.0]
        schedlag = [0.5, 1.0, 1.5, 2.0, 2.5]
        result = compute_metrics(tti, transport, schedlag)
        
        assert "tti_ms" in result
        assert "transport_ms" in result
        assert "producer_sched_lag_ms" in result
        
        # Check TTI stats
        assert result["tti_ms"]["p50"] == 30.0
        assert result["tti_ms"]["max"] == 50.0
        assert result["tti_ms"]["min"] == 10.0
        assert "missed_window_rate" in result["tti_ms"]
        assert "100" in result["tti_ms"]["missed_window_rate"]
        assert "250" in result["tti_ms"]["missed_window_rate"]
        assert "500" in result["tti_ms"]["missed_window_rate"]
        
        # Check transport stats
        assert result["transport_ms"]["p50"] == 3.0
        
        # Check schedlag stats
        assert result["producer_sched_lag_ms"]["p50"] == 1.5
        assert "missed_window_rate" in result["producer_sched_lag_ms"]

    def test_with_empty_lists(self):
        result = compute_metrics([], [], [])
        assert result == {}

    def test_with_none_values(self):
        result = compute_metrics(None, None, None)
        assert result == {}

    def test_with_only_tti(self):
        tti = [10.0, 20.0, 30.0]
        result = compute_metrics(tti, [], [])
        assert "tti_ms" in result
        assert "transport_ms" not in result
        assert "producer_sched_lag_ms" not in result

    def test_with_only_transport(self):
        transport = [1.0, 2.0, 3.0]
        result = compute_metrics([], transport, [])
        assert "transport_ms" in result
        assert "tti_ms" not in result
        assert "producer_sched_lag_ms" not in result

    def test_with_only_schedlag(self):
        schedlag = [0.5, 1.0, 1.5]
        result = compute_metrics([], [], schedlag)
        assert "producer_sched_lag_ms" in result
        assert "tti_ms" not in result
        assert "transport_ms" not in result

    def test_missed_window_rate_all_exceed(self):
        tti = [1000.0, 2000.0, 3000.0]  # All exceed 100ms
        result = compute_metrics(tti, [], [])
        assert result["tti_ms"]["missed_window_rate"]["100"] == 1.0
        assert result["tti_ms"]["missed_window_rate"]["250"] == 1.0
        assert result["tti_ms"]["missed_window_rate"]["500"] == 1.0

    def test_missed_window_rate_none_exceed(self):
        tti = [10.0, 20.0, 30.0]  # None exceed 100ms
        result = compute_metrics(tti, [], [])
        assert result["tti_ms"]["missed_window_rate"]["100"] == 0.0
        assert result["tti_ms"]["missed_window_rate"]["250"] == 0.0

    def test_missed_window_rate_some_exceed(self):
        tti = [50.0, 150.0, 250.0]  # 2 out of 3 exceed 100ms
        result = compute_metrics(tti, [], [])
        assert abs(result["tti_ms"]["missed_window_rate"]["100"] - 2/3) < 0.001

    def test_single_value(self):
        result = compute_metrics([50.0], [1.0], [0.5])
        assert result["tti_ms"]["p50"] == 50.0
        assert result["tti_ms"]["max"] == 50.0
        assert result["tti_ms"]["min"] == 50.0
        assert result["tti_ms"]["std"] == 0.0


class TestMain:
    def test_main_with_matched_events(self, temp_dir):
        # Create producer CSV
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": "1002000"},
            {"event_id": "e2", "t_prod_sched_ns": 2000000, "t_prod_send_ns": 2001000, "t_broker_ack_ns": None},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        # Create consumer CSV
        consumer_data = [
            {"event_id": "e1", "t_cons_recv_ns": 1010000, "t_output_ns": 1015000},
            {"event_id": "e2", "t_cons_recv_ns": 2010000, "t_output_ns": 2015000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        assert out_path.exists()
        result = json.loads(out_path.read_text())
        assert result["n_produced"] == 2
        assert result["n_consumed"] == 2
        assert result["n_matched"] == 2
        assert "tti_ms" in result
        assert "transport_ms" in result
        assert "producer_sched_lag_ms" in result

    def test_main_with_unmatched_events(self, temp_dir):
        # Producer has e1, e2; consumer only has e1
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": None},
            {"event_id": "e2", "t_prod_sched_ns": 2000000, "t_prod_send_ns": 2001000, "t_broker_ack_ns": None},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        consumer_data = [
            {"event_id": "e1", "t_cons_recv_ns": 1010000, "t_output_ns": 1015000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        result = json.loads(out_path.read_text())
        assert result["n_produced"] == 2
        assert result["n_consumed"] == 1
        assert result["n_matched"] == 1

    def test_main_no_matching_events(self, temp_dir):
        # Producer and consumer have different event IDs
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": None},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        consumer_data = [
            {"event_id": "e2", "t_cons_recv_ns": 1010000, "t_output_ns": 1015000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        result = json.loads(out_path.read_text())
        assert result["n_produced"] == 1
        assert result["n_consumed"] == 1
        assert result["n_matched"] == 0
        assert "tti_ms" not in result

    def test_main_empty_producer(self, temp_dir):
        # Empty producer CSV
        producer_path = temp_dir / "producer.csv"
        producer_path.write_text("event_id,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns\n")
        
        consumer_data = [
            {"event_id": "e1", "t_cons_recv_ns": 1010000, "t_output_ns": 1015000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        result = json.loads(out_path.read_text())
        assert result["n_produced"] == 0
        assert result["n_consumed"] == 1
        assert result["n_matched"] == 0

    def test_main_empty_consumer(self, temp_dir):
        # Empty consumer CSV
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": None},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        consumer_path = temp_dir / "consumer.csv"
        consumer_path.write_text("event_id,t_cons_recv_ns,t_output_ns\n")
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        result = json.loads(out_path.read_text())
        assert result["n_produced"] == 1
        assert result["n_consumed"] == 0
        assert result["n_matched"] == 0

    def test_main_creates_parent_dirs(self, temp_dir):
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": None},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        consumer_data = [
            {"event_id": "e1", "t_cons_recv_ns": 1010000, "t_output_ns": 1015000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "subdir" / "nested" / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        assert out_path.exists()

    def test_main_uses_broker_ack_when_available(self, temp_dir):
        # Test that transport latency uses t_broker_ack_ns when available
        producer_data = [
            {"event_id": "e1", "t_prod_sched_ns": 1000000, "t_prod_send_ns": 1001000, "t_broker_ack_ns": "1000000"},
        ]
        producer_df = pd.DataFrame(producer_data)
        producer_path = temp_dir / "producer.csv"
        producer_df.to_csv(producer_path, index=False)
        
        consumer_data = [
            {"event_id": "e1", "t_cons_recv_ns": 6000000, "t_output_ns": 6005000},
        ]
        consumer_df = pd.DataFrame(consumer_data)
        consumer_path = temp_dir / "consumer.csv"
        consumer_df.to_csv(consumer_path, index=False)
        
        out_path = temp_dir / "tti_summary.json"
        
        old_argv = sys.argv
        try:
            sys.argv = ["tti", "--producer", str(producer_path), "--consumer", str(consumer_path), "--out", str(out_path)]
            tti_main()
        finally:
            sys.argv = old_argv
        
        result = json.loads(out_path.read_text())
        # transport = t_cons_recv_ns - t_broker_ack_ns = 6000000 - 1000000 = 5000000 ns = 5.0 ms
        assert abs(result["transport_ms"]["max"] - 5.0) < 0.001

    def test_main_as_script(self, temp_dir):
        """Test line 179: if __name__ == '__main__' block by running as subprocess with coverage."""
        producer_path = temp_dir / "producer.csv"
        consumer_path = temp_dir / "consumer.csv"
        out_path = temp_dir / "tti.json"
        
        pd.DataFrame({
            "event_id": ["e1"], 
            "t_prod_sched_ns": [1000000], 
            "t_prod_send_ns": [1100000],
            "t_broker_ack_ns": [1200000]
        }).to_csv(producer_path, index=False)
        pd.DataFrame({
            "event_id": ["e1"], 
            "t_consume_ns": [2000000],
            "t_cons_recv_ns": [2100000],
            "t_output_ns": [2200000]
        }).to_csv(consumer_path, index=False)
        
        env = os.environ.copy()
        scripts_dir = str(Path(__file__).parent.parent.parent / "scripts")
        repo_root = str(Path(__file__).parent.parent.parent)
        env["PYTHONPATH"] = scripts_dir + ";" + env.get("PYTHONPATH", "")
        coveragerc_path = str(Path(repo_root) / ".coveragerc")
        env["COVERAGE_PROCESS_START"] = coveragerc_path
        
        result = subprocess.run(
            [sys.executable, str(Path(scripts_dir) / "compute_tti.py"),
             "--producer", str(producer_path), "--consumer", str(consumer_path),
             "--out", str(out_path)],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )
        assert result.returncode == 0
