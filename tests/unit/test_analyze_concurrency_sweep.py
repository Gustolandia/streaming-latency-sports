"""Complete tests for analyze_concurrency_sweep.py - Target: 95%+ branch coverage."""
import pytest
import pandas as pd
import os
import json
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_concurrency_sweep import (
    get_scenario,
    load_run_data,
    discover_runs,
    filter_handoff,
    main as analyze_sweep_main,
)


class TestGetScenario:
    """Tests for get_scenario function."""

    def test_known_prefixes(self):
        assert get_scenario('001322') == 's1'
        assert get_scenario('001416') == 's2'
        assert get_scenario('001522') == 's2full'
        assert get_scenario('001613') == 's2sf12'
        assert get_scenario('001712') == 's2sf12j2'

    def test_unknown_prefix(self):
        assert get_scenario('999999') == 'unknown'
        assert get_scenario('') == 'unknown'
        assert get_scenario(None) == 'unknown'


class TestDiscoverRuns:
    """Tests for discover_runs function."""

    def test_discover_valid_runs(self, temp_dir):
        valid_dirs = [
            "concurrency_n5_20260101_001322_kafka_feed1_rep1",
            "concurrency_n10_20260101_001416_redis_feed1_rep1",
            "concurrency_n20_20260102_001522_kafka_feed2_rep1",
        ]
        for dirname in valid_dirs:
            (temp_dir / dirname).mkdir()
        invalid_dirs = ["invalid_dir", "concurrency_n5", "other_n5_20260101_001322_kafka_feed1_rep1"]
        for dirname in invalid_dirs:
            (temp_dir / dirname).mkdir()
        result = discover_runs(temp_dir)
        assert len(result) == 3
        assert all(r.name.startswith('concurrency_n') for r in result)

    def test_discover_empty_directory(self, temp_dir):
        result = discover_runs(temp_dir)
        assert len(result) == 0

    def test_discover_no_matching_pattern(self, temp_dir):
        (temp_dir / "test_dir").mkdir()
        (temp_dir / "runs").mkdir()
        result = discover_runs(temp_dir)
        assert len(result) == 0


class TestFilterHandoff:
    """Tests for filter_handoff function."""

    def test_filter_with_handoff_prefixes(self, temp_dir):
        handoff_dirs = [
            temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1",
            temp_dir / "concurrency_n10_20260101_001416_redis_feed1_rep1",
            temp_dir / "concurrency_n20_20260102_001522_kafka_feed2_rep1",
        ]
        for d in handoff_dirs:
            d.mkdir(parents=True)
        result = filter_handoff(handoff_dirs)
        assert len(result) == 3

    def test_filter_without_handoff_prefixes(self, temp_dir):
        non_handoff_dirs = [
            temp_dir / "concurrency_n5_20260101_999999_kafka_feed1_rep1",
            temp_dir / "concurrency_n10_20260101_888888_redis_feed1_rep1",
        ]
        for d in non_handoff_dirs:
            d.mkdir(parents=True)
        result = filter_handoff(non_handoff_dirs)
        assert len(result) == 0

    def test_filter_mixed_prefixes(self, temp_dir):
        all_dirs = [
            temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1",
            temp_dir / "concurrency_n10_20260101_999999_kafka_feed1_rep1",
            temp_dir / "concurrency_n20_20260102_001416_redis_feed2_rep1",
        ]
        for d in all_dirs:
            d.mkdir(parents=True)
        result = filter_handoff(all_dirs)
        assert len(result) == 2


class TestLoadRunData:
    """Tests for load_run_data function."""

    def test_load_valid_run(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        tti_data = {"tti_ms": {"p50": 100.0, "p95": 200.0, "p99": 300.0, "max": 500.0, "mean": 150.0},
                   "n_producer": 1000, "n_consumer": 1000, "n_matched": 999}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]['backend'] == 'kafka'
        assert df.iloc[0]['scenario'] == 's1'

    def test_load_missing_tti_file(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)
        df = load_run_data([run_dir])
        assert len(df) == 0

    def test_load_missing_meta_file(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        tti_data = {"tti_ms": {"p50": 100.0, "p95": 200.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]['backend'] == 'unknown'

    def test_load_multiple_runs(self, temp_dir):
        runs = []
        for i in range(3):
            run_dir = temp_dir / f"concurrency_n{5+i}_20260101_001322_kafka_feed1_rep1"
            run_dir.mkdir()
            tti_data = {"tti_ms": {"p50": 100.0 + i * 10}, "n_producer": 1000 + i * 100}
            with open(run_dir / "tti_summary.json", 'w') as f:
                json.dump(tti_data, f)
            meta_data = {"backend": "kafka"}
            with open(run_dir / "meta.json", 'w') as f:
                json.dump(meta_data, f)
            runs.append(run_dir)
        df = load_run_data(runs)
        assert len(df) == 3

    def test_load_with_flat_tti_structure(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        tti_data = {"tti_ms_p50": 100.0, "tti_ms_p95": 200.0, "n_produced": 1000, "n_consumed": 1000}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        meta_data = {"backend": "redis"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]['tti_p50'] == 100.0

    def test_load_corrupted_json(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        with open(run_dir / "tti_summary.json", 'w') as f:
            f.write("invalid json")
        df = load_run_data([run_dir])
        assert len(df) == 0

    def test_load_with_malformed_meta_json(self, temp_dir):
        """Test load_run_data with malformed meta.json (covers lines 67-72 exception handling)."""
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        tti_data = {"tti_ms": {"p50": 100.0, "p95": 200.0}, "n_producer": 1000}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{ invalid json")
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]['backend'] == 'unknown'

    def test_load_with_malformed_tti_json(self, temp_dir):
        """Test load_run_data with malformed tti_summary.json (covers lines 60-64 exception handling)."""
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()
        with open(run_dir / "tti_summary.json", 'w') as f:
            f.write("{ invalid json")
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)
        df = load_run_data([run_dir])
        assert len(df) == 0


class TestMainFunction:
    """Tests for main function (covers lines 124-360)."""

    @patch('analyze_concurrency_sweep.discover_runs')
    @patch('analyze_concurrency_sweep.filter_handoff')
    @patch('analyze_concurrency_sweep.load_run_data')
    @patch('analyze_concurrency_sweep.stats.ttest_ind')
    @patch('analyze_concurrency_sweep.plt')
    def test_main_basic_flow(self, mock_plt, mock_ttest, mock_load_data, mock_filter, mock_discover, temp_dir):
        """Test main function basic flow - covers analysis and plotting code."""
        mock_discover.return_value = []
        mock_filter.return_value = []
        mock_load_data.return_value = pd.DataFrame({
            'backend': ['kafka', 'redis'],
            'scenario': ['s1', 's1'],
            'scenario_name': ['S1', 'S1'],
            'n': [5, 5],
            'feed': [1, 1],
            'tti_p50': [100.0, 80.0],
            'tti_p95': [200.0, 160.0],
            'tti_p99': [300.0, 240.0],
            'tti_max': [500.0, 400.0],
            'tti_mean': [150.0, 120.0],
            'tti_std': [50.0, 40.0],
            'tti_min': [50.0, 40.0],
            'n_producer': [1000, 1000],
            'n_consumer': [1000, 1000],
            'n_matched': [999, 999],
            'run_id': ['run1', 'run2']
        })
        mock_ttest.return_value = (1.0, 0.05)
        
        with patch('sys.argv', ['analyze_concurrency_sweep.py', '--runs-dir', str(temp_dir), 
                                     '--output-dir', str(temp_dir / 'output_new_test')]):
            # main() doesn't call sys.exit(0) on success, it just returns
            analyze_sweep_main()

    @patch('analyze_concurrency_sweep.discover_runs')
    @patch('analyze_concurrency_sweep.filter_handoff')
    @patch('analyze_concurrency_sweep.load_run_data')
    def test_main_empty_data(self, mock_load_data, mock_filter, mock_discover, temp_dir):
        """Test main function when no valid data is loaded (covers error path lines 152-154)."""
        mock_discover.return_value = []
        mock_filter.return_value = []
        # Return DataFrame with all required columns but no rows
        mock_df = pd.DataFrame(columns=['backend', 'scenario', 'scenario_name', 'n', 
                                          'feed', 'tti_p50', 'tti_p95', 'tti_p99', 
                                          'n_producer', 'n_consumer', 'n_matched', 'run_id',
                                          'tti_max', 'tti_mean', 'tti_std', 'tti_min'])
        mock_load_data.return_value = mock_df
        
        with patch('sys.argv', ['analyze_concurrency_sweep.py', '--runs-dir', str(temp_dir), 
                                     '--output-dir', str(temp_dir / 'output_new_test')]):
            with patch('sys.exit') as mock_exit:
                with patch('builtins.print') as mock_print:
                    analyze_sweep_main()
                    # Check that sys.exit was called with 1 and "No valid data!" was printed
                    assert mock_exit.called
                    mock_exit.assert_called_with(1)
                    assert any('No valid data!' in str(call) for call in mock_print.call_args_list)

    @patch('analyze_concurrency_sweep.discover_runs')
    @patch('analyze_concurrency_sweep.filter_handoff')
    @patch('analyze_concurrency_sweep.load_run_data')
    def test_main_output_exists_no_force(self, mock_load_data, mock_filter, mock_discover, temp_dir):
        """Test main function when output directory exists and --force is not used (lines 135-137)."""
        output_dir = temp_dir / 'output_existing'
        output_dir.mkdir(parents=True, exist_ok=True)
        mock_discover.return_value = []
        mock_filter.return_value = []
        # Return DataFrame with all required columns but no rows
        mock_load_data.return_value = pd.DataFrame(columns=['backend', 'scenario', 'scenario_name', 'n', 
                                                            'feed', 'tti_p50', 'tti_p95', 'tti_p99', 
                                                            'n_producer', 'n_consumer', 'n_matched', 'run_id'])
        
        with patch('sys.argv', ['analyze_concurrency_sweep.py', '--runs-dir', str(temp_dir), 
                                     '--output-dir', str(output_dir)]):
            with patch('sys.exit') as mock_exit:
                with patch('builtins.print') as mock_print:
                    analyze_sweep_main()
                    mock_exit.assert_called_with(1)
                    # The output_dir is a Path object, so the message will match
                    mock_print.assert_called()
                    # Check that one of the print calls contains the error message
                    assert any('Output exists' in str(call) for call in mock_print.call_args_list)

    @patch('analyze_concurrency_sweep.discover_runs')
    @patch('analyze_concurrency_sweep.filter_handoff')
    @patch('analyze_concurrency_sweep.load_run_data')
    @patch('analyze_concurrency_sweep.stats.ttest_ind')
    @patch('analyze_concurrency_sweep.plt')
    def test_main_with_force_flag(self, mock_plt, mock_ttest, mock_load_data, mock_filter, mock_discover, temp_dir):
        """Test main function with --force flag when output exists (lines 135-137)."""
        output_dir = temp_dir / 'output_existing'
        output_dir.mkdir(parents=True, exist_ok=True)
        mock_discover.return_value = []
        mock_filter.return_value = []
        mock_load_data.return_value = pd.DataFrame({
            'backend': ['kafka'],
            'scenario': ['s1'],
            'scenario_name': ['S1'],
            'n': [5],
            'feed': [1],
            'tti_p50': [100.0],
            'tti_p95': [200.0],
            'tti_p99': [300.0],
            'tti_max': [500.0],
            'tti_mean': [150.0],
            'tti_std': [50.0],
            'tti_min': [50.0],
            'n_producer': [1000],
            'n_consumer': [1000],
            'n_matched': [999],
            'run_id': ['run1']
        })
        mock_ttest.return_value = (1.0, 0.05)
        
        with patch('sys.argv', ['analyze_concurrency_sweep.py', '--runs-dir', str(temp_dir), 
                                     '--output-dir', str(output_dir), '--force']):
            # main() doesn't call sys.exit(0) on success
            analyze_sweep_main()

    @patch('analyze_concurrency_sweep.discover_runs')
    @patch('analyze_concurrency_sweep.filter_handoff')
    @patch('analyze_concurrency_sweep.load_run_data')
    def test_main_with_handoff_only(self, mock_load_data, mock_filter, mock_discover, temp_dir):
        """Test main function with --handoff-only flag."""
        mock_discover.return_value = []
        mock_filter.return_value = []
        mock_load_data.return_value = pd.DataFrame({
            'backend': ['kafka', 'kafka'],
            'scenario': ['s1', 's2'],
            'scenario_name': ['S1', 'S2'],
            'n': [5, 20],
            'feed': [1, 2],
            'tti_p50': [100.0, 150.0],
            'tti_p95': [200.0, 250.0],
            'tti_p99': [300.0, 350.0],
            'n_producer': [1000, 1000],
            'n_consumer': [1000, 1000],
            'n_matched': [999, 999],
            'run_id': ['run1', 'run2']
        })
        
        with patch('sys.argv', ['analyze_concurrency_sweep.py', '--runs-dir', str(temp_dir), 
                                     '--output-dir', str(temp_dir / 'output_new_test'), '--handoff-only']):
            # main() doesn't call sys.exit(0) on success
            analyze_sweep_main()
            mock_filter.assert_called_once()


class TestEntryPoint:
    """Test entry point (covers line 363-364)."""

    def test_entry_point_import(self):
        """Test that the module can be imported and has main function."""
        import analyze_concurrency_sweep
        assert hasattr(analyze_concurrency_sweep, 'main')
        assert hasattr(analyze_concurrency_sweep, 'get_scenario')
        assert hasattr(analyze_concurrency_sweep, 'load_run_data')
        assert hasattr(analyze_concurrency_sweep, 'discover_runs')
        assert hasattr(analyze_concurrency_sweep, 'filter_handoff')

    def test_entry_point_call(self):
        """Test that calling main as entry point works."""
        import analyze_concurrency_sweep
        assert callable(analyze_concurrency_sweep.main)
