"""Tests for analyze_batches_1_2_3.py - Target: 95%+ coverage."""
import pytest
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

# The script under test already selects the headless Agg backend, so real matplotlib works
# without a display. We must NOT replace matplotlib in sys.modules -- doing so leaked a
# MagicMock into every later test module that uses real matplotlib. Only seaborn (an optional
# dependency that may be absent) is stubbed.
sys.modules.setdefault('seaborn', MagicMock())

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Now import after mocking
from analyze_batches_1_2_3 import (
    extract_config_from_run_id,
    load_all_batch_runs,
    run_hypothesis_tests,
    generate_graphs,
    generate_summary_tables,
    save_results,
    main,
    COLORS,
    SCENARIO_MAP,
    SCENARIO_NAMES,
    HYPOTHESES,
)


class TestExtractConfigFromRunId:
    """Tests for extract_config_from_run_id function."""

    def test_valid_batch1_kafka_single(self):
        run_id = "batch1_20260615_kafka_single_s1_n10_rep1"
        config = extract_config_from_run_id(run_id)
        assert config is not None
        assert config['batch'] == 1
        assert config['backend'] == 'kafka'
        assert config['config'] == 'single'
        assert config['scenario'] == 's1'
        assert config['n'] == 10
        assert config['rep'] == 1

    def test_valid_batch2_redis_cluster(self):
        run_id = "batch2_20260615_redis_cluster_s2_n20_rep2"
        config = extract_config_from_run_id(run_id)
        assert config is not None
        assert config['batch'] == 2
        assert config['backend'] == 'redis'
        assert config['config'] == 'cluster'
        assert config['scenario'] == 's2'
        assert config['n'] == 20
        assert config['rep'] == 2

    def test_valid_batch3(self):
        run_id = "batch3_20260616_redis_single_s2full_n5_rep1"
        config = extract_config_from_run_id(run_id)
        assert config is not None
        assert config['batch'] == 3
        assert config['backend'] == 'redis'
        assert config['config'] == 'single'
        assert config['scenario'] == 's2full'
        assert config['n'] == 5
        assert config['rep'] == 1

    def test_invalid_format(self):
        run_id = "invalid_run_id"
        config = extract_config_from_run_id(run_id)
        assert config is None

    def test_all_scenarios(self):
        scenarios = ['s1', 's2', 's2full', 's2sf12', 's2sf12j2']
        for scenario in scenarios:
            run_id = f"batch1_20260615_kafka_single_{scenario}_n10_rep1"
            config = extract_config_from_run_id(run_id)
            assert config is not None
            assert config['scenario'] == scenario


class TestLoadAllBatchRuns:
    """Tests for load_all_batch_runs function."""

    def test_load_single_run(self, temp_dir):
        """Test loading a single valid run directory."""
        run_dir = temp_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        run_dir.mkdir()
        
        # Create tti_summary.json
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {
                "p50": 5000.0,
                "p95": 7000.0,
                "p99": 8000.0,
                "max": 9000.0,
                "mean": 5500.0,
                "std": 500.0,
                "min": 4000.0,
            }
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        # Create meta.json
        meta_data = {
            "run_id": "batch1_20260615_kafka_single_s1_n10_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
            "topic": "sb-events-test"
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        # Create producer.csv
        with open(run_dir / "producer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns\n")
            for i in range(10):
                f.write(f"batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e{i},1,10.0,0.0,1000,2000,3000\n")
        
        # Create consumer.csv
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns\n")
            for i in range(10):
                f.write(f"batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e{i},1,10.0,5000,6000\n")
        
        # Mock Path.glob to return our test directory
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        assert len(df) == 1
        assert df.iloc[0]['run_id'] == 'batch1_20260615_kafka_single_s1_n10_rep1'
        assert df.iloc[0]['backend'] == 'kafka'
        assert df.iloc[0]['config'] == 'single'
        assert df.iloc[0]['scenario'] == 's1'
        assert df.iloc[0]['n'] == 10
        assert df.iloc[0]['rep'] == 1
        assert df.iloc[0]['p50'] == 5000.0
        assert df.iloc[0]['match_rate_pct'] == 100.0

    def test_load_redis_run(self, temp_dir):
        """Test loading a Redis run (uses stream instead of topic)."""
        run_dir = temp_dir / "batch1_20260615_redis_single_s1_n10_rep1"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {"p50": 4000.0, "p95": 6000.0, "p99": 7000.0, "max": 8000.0, "mean": 4500.0, "std": 400.0, "min": 3000.0}
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {
            "run_id": "batch1_20260615_redis_single_s1_n10_rep1",
            "backend": "redis",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
            "redis": {"host": "localhost", "port": 7000, "stream": "sb-stream"}
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        # Create CSV with stream column instead of topic
        with open(run_dir / "producer.csv", "w") as f:
            f.write("run_id,backend,stream,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns,redis_id\n")
            for i in range(10):
                f.write(f"batch1_20260615_redis_single_s1_n10_rep1,redis,sb-stream,e{i},1,10.0,0.0,1000,2000,3000,rid-{i}\n")
        
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,backend,stream,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns,redis_id\n")
            for i in range(10):
                f.write(f"batch1_20260615_redis_single_s1_n10_rep1,redis,sb-stream,e{i},1,10.0,5000,6000,rid-{i}\n")
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        assert len(df) == 1
        assert df.iloc[0]['backend'] == 'redis'

    def test_load_missing_tti_file(self, temp_dir):
        """Test that missing tti_summary.json is handled."""
        run_dir = temp_dir / "batch1_test_missing_tti"
        run_dir.mkdir()
        
        # Create only meta.json, no tti_summary.json
        meta_data = {"run_id": "batch1_test_missing_tti", "backend": "kafka"}
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        # Should be empty since tti_summary.json is missing
        assert len(df) == 0

    def test_load_empty_run_directory(self, temp_dir):
        """Test loading an empty directory."""
        run_dir = temp_dir / "batch1_test_empty"
        run_dir.mkdir()
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        # Should handle empty directory gracefully
        assert len(df) == 0

    def test_load_invalid_config_run(self, temp_dir):
        """Test that invalid run_id format is handled."""
        run_dir = temp_dir / "invalid_run_name"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {"p50": 5000.0, "p95": 7000.0, "p99": 8000.0, "max": 9000.0}
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {"run_id": "invalid_run_name", "backend": "kafka"}
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        # Should skip invalid config
        assert len(df) == 0

    def test_load_non_dict_tti_format(self, temp_dir):
        """Test loading with non-dict tti_ms format."""
        run_dir = temp_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        run_dir.mkdir()
        
        # Use non-dict format for tti_ms
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms_p50": 5000.0,
            "tti_ms_p95": 7000.0,
            "tti_ms_p99": 8000.0,
            "tti_ms_max": 9000.0,
            "tti_ms_mean": 5500.0,
            "tti_ms_std": 500.0,
            "tti_ms_min": 4000.0,
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {
            "run_id": "batch1_20260615_kafka_single_s1_n10_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
            "topic": "sb-events-test"
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with open(run_dir / "producer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns\n")
            f.write("batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e0,1,10.0,0.0,1000,2000,3000\n")
        
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns\n")
            f.write("batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e0,1,10.0,5000,6000\n")
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        assert len(df) == 1
        assert df.iloc[0]['p50'] == 5000.0


class TestRunHypothesisTests:
    """Tests for run_hypothesis_tests function."""

    def test_basic_hypothesis_tests(self):
        """Test that hypothesis tests run without errors on valid data."""
        # Create sample dataframe with multiple concurrency levels
        data = {
            'run_id': ['run1', 'run2', 'run3', 'run4', 'run5', 'run6'],
            'backend': ['kafka', 'kafka', 'redis', 'redis', 'kafka', 'redis'],
            'config': ['single', 'single', 'single', 'single', 'single', 'single'],
            'scenario': ['s1', 's1', 's1', 's1', 's1', 's1'],
            'scenario_name': ['S1 (Simple)'] * 6,
            'n': [5, 10, 5, 10, 20, 20],
            'rep': [1, 2, 1, 2, 1, 1],
            'p50': [10000.0, 10500.0, 7000.0, 7200.0, 11000.0, 8000.0],
            'p95': [15000.0, 15500.0, 12000.0, 12200.0, 16000.0, 13000.0],
            'p99': [18000.0, 18500.0, 15000.0, 15200.0, 19000.0, 16000.0],
            'max': [20000.0, 20500.0, 18000.0, 18200.0, 22000.0, 19000.0],
            'mean': [11000.0, 11500.0, 8000.0, 8200.0, 12000.0, 9000.0],
            'std': [2000.0, 2100.0, 1500.0, 1600.0, 2500.0, 2000.0],
            'min': [8000.0, 8500.0, 5000.0, 5500.0, 9000.0, 6000.0],
            'n_produced': [100, 100, 100, 100, 100, 100],
            'n_consumed': [100, 100, 100, 100, 100, 100],
            'n_matched': [100, 100, 100, 100, 100, 100],
            'match_rate_pct': [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            'producer_size_bytes': [1000, 1000, 1000, 1000, 1000, 1000],
            'consumer_size_bytes': [1000, 1000, 1000, 1000, 1000, 1000],
            'avg_msg_size_bytes': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            'throughput_events_per_sec': [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            'pct_under_100ms': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_500ms': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_1s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_5s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
        df = pd.DataFrame(data)
        
        # Run hypothesis tests - should not raise errors
        results = run_hypothesis_tests(df)
        
        # Verify results structure
        assert 'RQ1' in results
        assert 'RQ2' in results  # Now we have multiple n values
        assert 'RQ3' in results
        
        # Check RQ1 has expected fields
        if 'RQ1' in results:
            assert 'test' in results['RQ1']
            assert 'u_statistic' in results['RQ1']
            assert 'p_value' in results['RQ1']

    def test_rq1_redis_lower_tti(self):
        """Test RQ1 when Redis has lower TTI than Kafka."""
        # Use more samples to ensure significance
        # Need multiple n values for RQ2 Kruskal-Wallis test
        # Use 5 samples per group with extreme differences
        data = {
            'run_id': ['kafka1', 'kafka2', 'kafka3', 'kafka4', 'kafka5', 
                      'redis1', 'redis2', 'redis3', 'redis4', 'redis5'],
            'backend': ['kafka'] * 5 + ['redis'] * 5,
            'config': ['single'] * 10,
            'scenario': ['s1'] * 10,
            'scenario_name': ['S1 (Simple)'] * 10,
            'n': [5, 5, 10, 10, 20, 5, 5, 10, 10, 20],
            'rep': [1, 2, 1, 2, 1, 1, 2, 1, 2, 1],
            'p50': [10000.0, 10500.0, 10200.0, 10300.0, 10100.0, 
                    2000.0, 2100.0, 2050.0, 2070.0, 2020.0],
            'p95': [15000.0, 15500.0, 15200.0, 15300.0, 15100.0,
                    3000.0, 3100.0, 3050.0, 3070.0, 3020.0],
            'p99': [18000.0, 18500.0, 18200.0, 18300.0, 18100.0,
                    4000.0, 4100.0, 4050.0, 4070.0, 4020.0],
            'max': [20000.0, 20500.0, 20200.0, 20300.0, 20100.0,
                   5000.0, 5100.0, 5050.0, 5070.0, 5020.0],
            'mean': [11000.0, 11500.0, 11200.0, 11300.0, 11100.0,
                    2500.0, 2600.0, 2550.0, 2570.0, 2520.0],
            'std': [2000.0, 2100.0, 2000.0, 2050.0, 2020.0,
                   500.0, 550.0, 500.0, 520.0, 510.0],
            'min': [8000.0, 8500.0, 8200.0, 8300.0, 8100.0,
                   1500.0, 1600.0, 1550.0, 1570.0, 1520.0],
            'n_produced': [100] * 10,
            'n_consumed': [100] * 10,
            'n_matched': [100] * 10,
            'match_rate_pct': [100.0] * 10,
            'producer_size_bytes': [1000] * 10,
            'consumer_size_bytes': [1000] * 10,
            'avg_msg_size_bytes': [10.0] * 10,
            'throughput_events_per_sec': [5.0] * 10,
            'pct_under_100ms': [0.0] * 10,
            'pct_under_500ms': [0.0] * 10,
            'pct_under_1s': [0.0] * 10,
            'pct_under_5s': [0.0] * 10,
        }
        df = pd.DataFrame(data)
        
        results = run_hypothesis_tests(df)
        
        # Kafka mean should be higher
        assert results['RQ1']['kafka_mean_p50'] > results['RQ1']['redis_mean_p50']
        # Improvement should be positive
        assert results['RQ1']['improvement_pct'] > 0
        # Conclusion should favor Redis (with significant difference)
        # With 5 samples per group and extreme differences, p-value should be < 0.05
        assert 'Redis' in results['RQ1']['conclusion']

    def test_rq3_perfect_match_rate(self):
        """Test RQ3 with perfect match rates."""
        data = {
            'run_id': ['run1', 'run2', 'run3', 'run4', 'run5', 'run6'],
            'backend': ['kafka', 'redis', 'kafka', 'redis', 'kafka', 'redis'],
            'config': ['single', 'single', 'cluster', 'cluster', 'single', 'cluster'],
            'scenario': ['s1', 's1', 's1', 's1', 's1', 's1'],
            'scenario_name': ['S1 (Simple)'] * 6,
            'n': [5, 10, 5, 10, 20, 20],
            'rep': [1, 1, 1, 1, 1, 1],
            'p50': [10000.0, 7000.0, 10500.0, 7500.0, 11000.0, 8000.0],
            'n_produced': [100, 100, 100, 100, 100, 100],
            'n_consumed': [100, 100, 100, 100, 100, 100],
            'n_matched': [100, 100, 100, 100, 100, 100],
            'match_rate_pct': [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            'throughput_events_per_sec': [5.0, 5.0, 5.0, 5.0, 5.0, 5.0],
            'avg_msg_size_bytes': [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            'pct_under_100ms': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_500ms': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_1s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_5s': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        }
        df = pd.DataFrame(data)
        
        results = run_hypothesis_tests(df)
        
        assert results['RQ3']['mean_match_rate'] == 100.0
        assert results['RQ3']['min_match_rate'] == 100.0
        assert results['RQ3']['match_rate_all_100'] == True

    def test_rq4_with_multiple_scenarios(self):
        """Test RQ4 with multiple scenarios including S5."""
        data = {
            'run_id': ['s1_k1', 's1_k2', 's1_r1', 's5_k1', 's5_r1'],
            'backend': ['kafka', 'kafka', 'redis', 'kafka', 'redis'],
            'config': ['single', 'single', 'single', 'single', 'single'],
            'scenario': ['s1', 's1', 's1', 's2sf12j2', 's2sf12j2'],
            'scenario_name': ['S1 (Simple)', 'S1 (Simple)', 'S1 (Simple)', 'S5 (Resource)', 'S5 (Resource)'],
            'n': [5, 10, 5, 5, 10],
            'rep': [1, 2, 1, 1, 1],
            'p50': [5000.0, 5100.0, 4000.0, 8000.0, 7500.0],
            'p95': [7000.0, 7100.0, 6500.0, 10000.0, 9500.0],
            'p99': [8000.0, 8100.0, 7500.0, 12000.0, 11500.0],
            'max': [9000.0, 9100.0, 8500.0, 14000.0, 13500.0],
            'mean': [5500.0, 5600.0, 5000.0, 8500.0, 8000.0],
            'std': [500.0, 510.0, 450.0, 800.0, 750.0],
            'min': [4000.0, 4100.0, 3500.0, 6000.0, 5500.0],
            'n_produced': [100, 100, 100, 100, 100],
            'n_consumed': [100, 100, 100, 100, 100],
            'n_matched': [100, 100, 100, 100, 100],
            'match_rate_pct': [100.0, 100.0, 100.0, 100.0, 100.0],
            'producer_size_bytes': [1000, 1000, 1000, 1000, 1000],
            'consumer_size_bytes': [1000, 1000, 1000, 1000, 1000],
            'avg_msg_size_bytes': [10.0, 10.0, 10.0, 10.0, 10.0],
            'throughput_events_per_sec': [5.0, 5.0, 5.0, 5.0, 5.0],
            'pct_under_100ms': [0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_500ms': [0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_1s': [0.0, 0.0, 0.0, 0.0, 0.0],
            'pct_under_5s': [0.0, 0.0, 0.0, 0.0, 0.0],
        }
        df = pd.DataFrame(data)
        
        results = run_hypothesis_tests(df)
        
        # RQ4 should have H4_1 and H4_2 results
        assert 'RQ4_H4_1' in results
        assert 'RQ4_H4_2' in results
        assert results['RQ4_H4_1']['test'] == 'Welch t-test'
        assert results['RQ4_H4_2']['test'] == 'Levene test'

    def test_rq3_with_actionability_metrics(self):
        """Test RQ3 with actionability metrics from tti_summary."""
        data = {
            'run_id': ['run1', 'run2', 'run3', 'run4'],
            'backend': ['kafka', 'kafka', 'redis', 'redis'],
            'config': ['single', 'single', 'single', 'single'],
            'scenario': ['s1', 's1', 's1', 's1'],
            'scenario_name': ['S1 (Simple)', 'S1 (Simple)', 'S1 (Simple)', 'S1 (Simple)'],
            'n': [5, 10, 5, 10],
            'rep': [1, 2, 1, 2],
            'p50': [5000.0, 5100.0, 4000.0, 4100.0],
            'p95': [7000.0, 7100.0, 6000.0, 6100.0],
            'p99': [8000.0, 8100.0, 7000.0, 7100.0],
            'max': [9000.0, 9100.0, 8000.0, 8100.0],
            'mean': [5500.0, 5600.0, 4500.0, 4600.0],
            'std': [500.0, 510.0, 400.0, 410.0],
            'min': [4000.0, 4100.0, 3000.0, 3100.0],
            'n_produced': [100, 100, 100, 100],
            'n_consumed': [100, 100, 100, 100],
            'n_matched': [100, 100, 100, 100],
            'match_rate_pct': [100.0, 100.0, 100.0, 100.0],
            'producer_size_bytes': [1000, 1000, 1000, 1000],
            'consumer_size_bytes': [1000, 1000, 1000, 1000],
            'avg_msg_size_bytes': [10.0, 10.0, 10.0, 10.0],
            'throughput_events_per_sec': [5.0, 5.0, 5.0, 5.0],
            'pct_under_100ms': [10.0, 20.0, 15.0, 25.0],
            'pct_under_500ms': [20.0, 30.0, 25.0, 35.0],
            'pct_under_1s': [30.0, 40.0, 35.0, 45.0],
            'pct_under_5s': [40.0, 50.0, 45.0, 55.0],
        }
        df = pd.DataFrame(data)
        
        results = run_hypothesis_tests(df)
        
        # RQ3 should have actionability metrics
        assert 'RQ3' in results
        assert results['RQ3']['mean_match_rate'] == 100.0


class TestGenerateGraphs:
    """Tests for generate_graphs function."""

    def test_generate_graphs_basic(self, temp_dir):
        """Test that graphs are generated without errors."""
        data = {
            'run_id': ['run1', 'run2'],
            'backend': ['kafka', 'redis'],
            'config': ['single', 'single'],
            'scenario': ['s1', 's1'],
            'scenario_name': ['S1 (Simple)', 'S1 (Simple)'],
            'n': [10, 10],
            'rep': [1, 1],
            'p50': [10000.0, 7000.0],
            'p95': [15000.0, 12000.0],
            'p99': [18000.0, 15000.0],
            'max': [20000.0, 18000.0],
            'mean': [11000.0, 8000.0],
            'std': [2000.0, 1500.0],
            'min': [8000.0, 5000.0],
            'n_produced': [100, 100],
            'n_consumed': [100, 100],
            'n_matched': [100, 100],
            'match_rate_pct': [100.0, 100.0],
            'throughput_events_per_sec': [5.0, 5.0],
            'avg_msg_size_bytes': [10.0, 10.0],
            'pct_under_100ms': [0.0, 0.0],
            'pct_under_500ms': [0.0, 0.0],
            'pct_under_1s': [0.0, 0.0],
            'pct_under_5s': [0.0, 0.0],
        }
        df = pd.DataFrame(data)
        
        output_dir = temp_dir / "graphs"
        output_dir.mkdir()
        
        # Mock matplotlib to prevent display issues
        with patch('analyze_batches_1_2_3.plt') as mock_plt:
            mock_fig = MagicMock()
            mock_plt.figure.return_value = mock_fig
            mock_plt.savefig = MagicMock()
            mock_plt.close = MagicMock()
            mock_plt.title = MagicMock()
            mock_plt.ylabel = MagicMock()
            mock_plt.xlabel = MagicMock()
            mock_plt.xticks = MagicMock()
            mock_plt.legend = MagicMock()
            mock_plt.tight_layout = MagicMock()
            mock_plt.ylim = MagicMock()
            
            # Mock seaborn
            with patch('analyze_batches_1_2_3.sns') as mock_sns:
                mock_sns.boxplot = MagicMock()
                mock_sns.lineplot = MagicMock()
                mock_sns.barplot = MagicMock()
                mock_sns.set_style = MagicMock()
                
                # Should not raise errors
                generate_graphs(df, str(output_dir))
        
        # Verify savefig was called multiple times
        assert mock_plt.savefig.call_count >= 8


class TestGenerateSummaryTables:
    """Tests for generate_summary_tables function."""

    def test_generate_tables_basic(self, temp_dir):
        """Test that summary tables are generated."""
        data = {
            'run_id': ['run1', 'run2'],
            'backend': ['kafka', 'redis'],
            'config': ['single', 'single'],
            'scenario': ['s1', 's1'],
            'scenario_name': ['S1 (Simple)', 'S1 (Simple)'],
            'n': [10, 10],
            'rep': [1, 1],
            'p50': [10000.0, 7000.0],
            'p95': [15000.0, 12000.0],
            'p99': [18000.0, 15000.0],
            'max': [20000.0, 18000.0],
            'mean': [11000.0, 8000.0],
            'std': [2000.0, 1500.0],
            'min': [8000.0, 5000.0],
            'n_produced': [100, 100],
            'n_consumed': [100, 100],
            'n_matched': [100, 100],
            'match_rate_pct': [100.0, 100.0],
            'throughput_events_per_sec': [5.0, 5.0],
            'avg_msg_size_bytes': [10.0, 10.0],
            'pct_under_100ms': [0.0, 0.0],
            'pct_under_500ms': [0.0, 0.0],
            'pct_under_1s': [0.0, 0.0],
            'pct_under_5s': [0.0, 0.0],
        }
        df = pd.DataFrame(data)
        
        output_dir = temp_dir / "tables"
        output_dir.mkdir()
        
        generate_summary_tables(df, str(output_dir))
        
        # Verify CSV files were created
        expected_files = [
            'overall_performance_summary.csv',
            'scenario_performance_summary.csv',
            'concurrency_performance_summary.csv',
            'actionability_summary.csv',
            'config_comparison_summary.csv',
        ]
        
        for file in expected_files:
            assert (output_dir / file).exists(), f"File {file} not created"


class TestSaveResults:
    """Tests for save_results function."""

    def test_save_results_json(self, temp_dir):
        """Test saving results to JSON."""
        results = {
            'RQ1': {
                'test': 'Mann-Whitney U',
                'u_statistic': 100.0,
                'p_value': 0.0001,
                'conclusion': 'H1: Redis has significantly lower TTI'
            }
        }
        
        output_dir = temp_dir / "results"
        output_dir.mkdir()
        
        save_results(results, str(output_dir))
        
        json_file = output_dir / 'hypothesis_tests_results.json'
        assert json_file.exists()
        
        with open(json_file) as f:
            loaded = json.load(f)
        
        assert loaded == results

    def test_save_results_markdown(self, temp_dir):
        """Test saving results to markdown."""
        results = {
            'RQ1': {
                'test': 'Mann-Whitney U',
                'u_statistic': 100.0,
                'p_value': 0.0001,
                'cohen_d': 0.5,
                'kafka_mean_p50': 10000.0,
                'redis_mean_p50': 7000.0,
                'improvement_pct': 30.0,
                'conclusion': 'H1: Redis has significantly lower TTI'
            },
            'RQ3': {
                'mean_match_rate': 100.0,
                'min_match_rate': 100.0,
                'match_rate_all_100': True,
                'conclusion_match': 'All configs =100%'
            }
        }
        
        output_dir = temp_dir / "results"
        output_dir.mkdir()
        
        save_results(results, str(output_dir))
        
        md_file = output_dir / 'HYPOTHESIS_RESULTS.md'
        assert md_file.exists()
        
        with open(md_file) as f:
            content = f.read()
        
        assert '# Hypothesis Test Results' in content
        assert 'RQ1' in content
        assert 'RQ3' in content
        assert 'Mann-Whitney U' in content


class TestMain:
    """Tests for main function."""

    def test_main_with_mock_data(self, temp_dir, monkeypatch):
        """Test main function with mocked run data."""
        # Create a temporary runs directory
        runs_dir = temp_dir / "runs"
        runs_dir.mkdir()
        
        # Create mock run directories - need both Kafka and Redis for hypothesis tests
        # Also need multiple n values for RQ2 Kruskal-Wallis test
        kafka_run_dir1 = runs_dir / "batch1_20260615_kafka_single_s1_n5_rep1"
        kafka_run_dir1.mkdir()
        kafka_run_dir2 = runs_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        kafka_run_dir2.mkdir()
        redis_run_dir1 = runs_dir / "batch1_20260615_redis_single_s1_n5_rep1"
        redis_run_dir1.mkdir()
        redis_run_dir2 = runs_dir / "batch1_20260615_redis_single_s1_n10_rep1"
        redis_run_dir2.mkdir()
        
        # Create required files for all runs
        all_runs = [
            (kafka_run_dir1, 'kafka', 'sb-events-test'),
            (kafka_run_dir2, 'kafka', 'sb-events-test'),
            (redis_run_dir1, 'redis', 'sb-stream'),
            (redis_run_dir2, 'redis', 'sb-stream')
        ]
        
        for run_dir, backend, stream_topic in all_runs:
            # Vary p50 by n value and backend to avoid identical values
            n_val = 5 if 'n5' in run_dir.name else 10
            p50_val = 5000.0 if backend == 'kafka' else 3000.0
            p50_val += n_val * 100  # Add variation based on n
            
            tti_data = {
                "n_produced": 100,
                "n_consumed": 100,
                "n_matched": 100,
                "tti_ms": {"p50": p50_val, "p95": 7000.0, "p99": 8000.0, "max": 9000.0, "mean": 5500.0, "std": 500.0, "min": 4000.0}
            }
            with open(run_dir / "tti_summary.json", "w") as f:
                json.dump(tti_data, f)
            
            meta_data = {
                "run_id": run_dir.name,
                "backend": backend,
                "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
                "topic": stream_topic if backend == 'kafka' else None,
                "stream": stream_topic if backend == 'redis' else None
            }
            if backend == 'kafka':
                meta_data["topic"] = stream_topic
            else:
                meta_data["stream"] = stream_topic
            with open(run_dir / "meta.json", "w") as f:
                json.dump(meta_data, f)
            
            if backend == 'kafka':
                with open(run_dir / "producer.csv", "w") as f:
                    f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns\n")
                    for i in range(10):
                        f.write(f"{run_dir.name},kafka,sb-events-test,e{i},1,10.0,0.0,1000,2000,3000\n")
                
                with open(run_dir / "consumer.csv", "w") as f:
                    f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns\n")
                    for i in range(10):
                        f.write(f"{run_dir.name},kafka,sb-events-test,e{i},1,10.0,5000,6000\n")
            else:
                with open(run_dir / "producer.csv", "w") as f:
                    f.write("run_id,backend,stream,event_id,match_id,t_sim_seconds,t_emit_offset_s,t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns,redis_id\n")
                    for i in range(10):
                        f.write(f"{run_dir.name},redis,sb-stream,e{i},1,10.0,0.0,1000,2000,3000,rid-{i}\n")
                
                with open(run_dir / "consumer.csv", "w") as f:
                    f.write("run_id,backend,stream,event_id,match_id,t_sim_seconds,t_cons_recv_ns,t_output_ns,redis_id\n")
                    for i in range(10):
                        f.write(f"{run_dir.name},redis,sb-stream,e{i},1,10.0,5000,6000,rid-{i}\n")
        
        # Change to the temp directory
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            # Mock sys.argv
            test_args = [
                'analyze_batches_1_2_3.py',
                '--output-dir', str(temp_dir / 'output'),
                '--batch-pattern', 'batch1_*'
            ]
            
            # Mock Path.glob and sys.argv
            with patch('pathlib.Path.glob') as mock_path_glob:
                from pathlib import Path as RealPath
                mock_path_glob.return_value = [RealPath(str(kafka_run_dir1)), 
                                              RealPath(str(kafka_run_dir2)),
                                              RealPath(str(redis_run_dir1)),
                                              RealPath(str(redis_run_dir2))]
                
                with patch('sys.argv', test_args):
                    # Mock all plotting functions
                    with patch('matplotlib.pyplot') as mock_plt:
                        mock_fig = MagicMock()
                        mock_plt.figure.return_value = mock_fig
                        mock_plt.savefig = MagicMock()
                        mock_plt.close = MagicMock()
                        mock_plt.title = MagicMock()
                        mock_plt.ylabel = MagicMock()
                        mock_plt.xlabel = MagicMock()
                        mock_plt.xticks = MagicMock()
                        mock_plt.legend = MagicMock()
                        mock_plt.tight_layout = MagicMock()
                        mock_plt.ylim = MagicMock()
                        
                        with patch('analyze_batches_1_2_3.sns') as mock_sns:
                            mock_sns.boxplot = MagicMock()
                            mock_sns.lineplot = MagicMock()
                            mock_sns.barplot = MagicMock()
                            mock_sns.set_style = MagicMock()
                            
                            # Run main - should complete without errors
                            main()
        
        finally:
            os.chdir(original_cwd)
        
        # Verify output directory was created
        output_dir = temp_dir / 'output'
        assert output_dir.exists()


class TestConstants:
    """Tests for module constants."""

    def test_colors_exist(self):
        assert 'kafka' in COLORS
        assert 'redis' in COLORS

    def test_scenario_map_exist(self):
        assert 's1' in SCENARIO_MAP
        assert 's2' in SCENARIO_MAP
        assert 's2full' in SCENARIO_MAP

    def test_scenario_names_exist(self):
        assert 's1' in SCENARIO_NAMES
        assert 's2' in SCENARIO_NAMES
        assert 's2full' in SCENARIO_NAMES

    def test_hypotheses_structure(self):
        assert 'RQ1' in HYPOTHESES
        assert 'RQ2' in HYPOTHESES
        assert 'RQ3' in HYPOTHESES
        assert 'RQ4' in HYPOTHESES
        
        # Check RQ1 and RQ2 have H0/H1/H2
        for rq in ['RQ1', 'RQ2']:
            assert 'H0' in HYPOTHESES[rq]
            assert 'H1' in HYPOTHESES[rq]
            assert 'H2' in HYPOTHESES[rq]
        
        # Check RQ3 has match_rate and consistency hypotheses
        assert 'match_rate_H0' in HYPOTHESES['RQ3']
        assert 'consistency_H3_1' in HYPOTHESES['RQ3']
        
        # Check RQ4 has H0/H1 and H4_1/H4_2
        assert 'H0' in HYPOTHESES['RQ4']
        assert 'H1' in HYPOTHESES['RQ4']
        assert 'H4_1' in HYPOTHESES['RQ4']
        assert 'H4_2' in HYPOTHESES['RQ4']


class TestEdgeCases:
    """Tests for edge cases to improve coverage."""

    def test_load_with_actionability_metrics(self, temp_dir):
        """Test loading with actionability metrics present."""
        run_dir = temp_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        run_dir.mkdir()
        
        # Create tti_summary.json with actionability metrics
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {
                "p50": 5000.0,
                "p95": 7000.0,
                "p99": 8000.0,
                "max": 9000.0,
                "mean": 5500.0,
                "std": 500.0,
                "min": 4000.0,
            },
            "actionability": {
                "100": 0.1,
                "500": 0.2,
                "1000": 0.3,
                "5000": 0.4,
            }
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {
            "run_id": "batch1_20260615_kafka_single_s1_n10_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
            "topic": "sb-events-test"
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with open(run_dir / "producer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds\n")
            for i in range(10):
                f.write(f"batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e{i},1,10.0\n")
        
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds\n")
            for i in range(10):
                f.write(f"batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e{i},1,10.0\n")
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        assert len(df) == 1
        assert df.iloc[0]['pct_under_100ms'] == 10.0
        assert df.iloc[0]['pct_under_500ms'] == 20.0
        assert df.iloc[0]['pct_under_1s'] == 30.0
        assert df.iloc[0]['pct_under_5s'] == 40.0

    def test_load_with_malformed_producer_csv(self, temp_dir):
        """Test loading with malformed producer CSV (triggers exception)."""
        run_dir = temp_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        run_dir.mkdir()
        
        tti_data = {
            "n_produced": 100,
            "n_consumed": 100,
            "n_matched": 100,
            "tti_ms": {"p50": 5000.0, "p95": 7000.0, "p99": 8000.0, "max": 9000.0, "mean": 5500.0, "std": 500.0, "min": 4000.0}
        }
        with open(run_dir / "tti_summary.json", "w") as f:
            json.dump(tti_data, f)
        
        meta_data = {
            "run_id": "batch1_20260615_kafka_single_s1_n10_rep1",
            "backend": "kafka",
            "plan_csv": "data/processed/replay_plans/s1/combined_plan.csv",
            "topic": "sb-events-test"
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        # Create malformed producer CSV (will trigger exception when reading)
        with open(run_dir / "producer.csv", "w") as f:
            f.write("invalid,csv,format\nthis,will, cause,error\n")
        
        with open(run_dir / "consumer.csv", "w") as f:
            f.write("run_id,backend,topic,event_id,match_id,t_sim_seconds\n")
            f.write("batch1_20260615_kafka_single_s1_n10_rep1,kafka,sb-events-test,e0,1,10.0\n")
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            # Should handle the exception gracefully
            df = load_all_batch_runs('batch[123]_*')
        
        # Should still load the run, just with default values for throughput
        assert len(df) == 1

    def test_load_with_error_in_run(self, temp_dir):
        """Test that errors during individual run loading are handled."""
        run_dir = temp_dir / "batch1_20260615_kafka_single_s1_n10_rep1"
        run_dir.mkdir()
        
        # Create a corrupted tti_summary.json that will cause an error
        with open(run_dir / "tti_summary.json", "w") as f:
            f.write("{invalid json}")
        
        meta_data = {
            "run_id": "batch1_20260615_kafka_single_s1_n10_rep1",
            "backend": "kafka"
        }
        with open(run_dir / "meta.json", "w") as f:
            json.dump(meta_data, f)
        
        with patch('pathlib.Path.glob') as mock_path_glob:
            from pathlib import Path as RealPath
            mock_path_glob.return_value = [RealPath(str(run_dir))]
            df = load_all_batch_runs('batch[123]_*')
        
        # Should skip the errored run
        assert len(df) == 0

    def test_save_results_with_rq4_h4_1(self, temp_dir):
        """Test save_results with RQ4_H4_1 results."""
        results = {
            'RQ1': {'test': 'Mann-Whitney U', 'u_statistic': 100.0, 'p_value': 0.0001},
            'RQ4_H4_1': {
                'test': 'Welch t-test',
                't_statistic': 5.0,
                'p_value': 0.001,
                'conclusion': 'S5 has higher TTI than S1'
            }
        }
        
        output_dir = temp_dir / "results"
        output_dir.mkdir()
        
        save_results(results, str(output_dir))
        
        md_file = output_dir / 'HYPOTHESIS_RESULTS.md'
        assert md_file.exists()
        
        with open(md_file) as f:
            content = f.read()
        
        # The markdown uses "H4_1 Test" not "RQ4_H4_1"
        assert 'H4_1 Test' in content
        assert 'Welch t-test' in content

    def test_main_with_empty_dataframe(self, temp_dir, monkeypatch):
        """Test main function when no runs are loaded (empty dataframe)."""
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            test_args = [
                'analyze_batches_1_2_3.py',
                '--output-dir', str(temp_dir / 'output'),
                '--batch-pattern', 'batch1_*'
            ]
            
            with patch('sys.argv', test_args):
                with patch('analyze_batches_1_2_3.load_all_batch_runs') as mock_load:
                    # Mock to return empty dataframe
                    mock_load.return_value = pd.DataFrame()
                    
                    with patch('analyze_batches_1_2_3.sys.exit') as mock_exit:
                        # Make sys.exit raise SystemExit with the code so the function actually exits
                        def exit_with_code(code):
                            raise SystemExit(code)
                        
                        mock_exit.side_effect = exit_with_code
                        
                        with pytest.raises(SystemExit) as exc_info:
                            main()
                        
                        # Should exit with error code 1
                        assert exc_info.value.code == 1
                        mock_exit.assert_called_once_with(1)
        finally:
            os.chdir(original_cwd)
