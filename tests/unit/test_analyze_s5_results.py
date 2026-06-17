"""Complete tests for analyze_s5_results.py - Target: 95%+ branch coverage."""
import pytest
import pandas as pd
import numpy as np
import os
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_s5_results import (
    parse_s5_run_id,
    extract_config_params,
    load_s5_run,
    compute_quality_metrics,
    generate_quality_plots,
    generate_summary_markdown,
    main as analyze_s5_main,
)


class TestParseS5RunId:
    """Tests for parse_s5_run_id function."""

    def test_baseline_config(self):
        run_id = "s5_s2sf12_baseline_kafka_rep1_20260101"
        result = parse_s5_run_id(run_id)
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'baseline'
        assert result['backend'] == 'kafka'
        assert result['rep'] == 'rep1'

    def test_high_speedup_config(self):
        run_id = "s5_s2sf12_high_speedup_redis_rep1_20260101"
        result = parse_s5_run_id(run_id)
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'high_speedup'
        assert result['backend'] == 'redis'
        assert result['rep'] == 'rep1'

    def test_config_with_multiple_underscores(self):
        run_id = "s5_s2sf12_fast_corrections_kafka_rep1_20260101_120000"
        result = parse_s5_run_id(run_id)
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'fast_corrections'
        assert result['backend'] == 'kafka'

    def test_invalid_format_no_rep(self):
        run_id = "s5_s2sf12_baseline_kafka_20260101"
        result = parse_s5_run_id(run_id)
        # Should use fallback
        assert result['scenario'] == 's2sf12'

    def test_invalid_format_too_short(self):
        run_id = "s5_s2sf12_kafka"
        result = parse_s5_run_id(run_id)
        # Should use fallback
        assert result['scenario'] == 's2sf12'


class TestExtractConfigParams:
    """Tests for extract_config_params function."""

    def test_baseline(self):
        params = extract_config_params('baseline')
        assert params == {'speedup': 120, 'corrections_every_k': 50, 'correction_delay_s': 2.0}

    def test_high_speedup(self):
        params = extract_config_params('high_speedup')
        assert params == {'speedup': 240, 'corrections_every_k': 50, 'correction_delay_s': 2.0}

    def test_high_frequency(self):
        params = extract_config_params('high_frequency')
        assert params == {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 2.0}

    def test_fast_corrections(self):
        params = extract_config_params('fast_corrections')
        assert params == {'speedup': 120, 'corrections_every_k': 10, 'correction_delay_s': 0.5}

    def test_unknown_config(self):
        params = extract_config_params('unknown_config')
        assert params == {}


class TestLoadS5Run:
    """Tests for load_s5_run function."""

    def test_load_valid_run(self, temp_dir):
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create tti_summary.json
        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0, "p99": 300.0, "max": 500.0, "mean": 150.0},
            "n_produced": 1000,
            "n_consumed": 1000,
            "n_matched": 999
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create meta.json
        meta_data = {"backend": "kafka", "max_t_sim": 600}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        # Create resource_summary.json
        resource_data = {
            "kafka_avg_cpu": 5.0,
            "kafka_avg_mem": 1000.0,
            "sample_count": 100
        }
        with open(run_dir / "resource_summary.json", 'w') as f:
            json.dump(resource_data, f)

        # Create CSV files
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id,event\n1,a\n2,b\n")
        with open(run_dir / "consumer.csv", 'w') as f:
            f.write("id,event\n1,a\n2,b\n")

        result = load_s5_run(run_dir)
        assert result is not None
        assert result['run_id'] == 's5_s2sf12_baseline_kafka_rep1_20260101'
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'baseline'
        assert result['backend'] == 'kafka'
        assert result['tti_p50'] == 100.0
        assert result['n_producer_events'] == 2
        assert result['n_consumer_events'] == 2

    def test_load_missing_tti_file(self, temp_dir):
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create only meta.json
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        result = load_s5_run(run_dir)
        # Without tti_summary.json, it still returns partial data from run_id parsing
        assert result is not None
        assert result['run_id'] == 's5_s2sf12_baseline_kafka_rep1_20260101'

    def test_load_with_transport_metrics(self, temp_dir):
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {
            "tti_ms": {"p50": 100.0},
            "transport_ms": {"p50": 10.0, "p95": 20.0}
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        result = load_s5_run(run_dir)
        assert result is not None
        assert result['tti_p50'] == 100.0
        assert result['transport_p50'] == 10.0

    def test_load_with_flat_tti_structure(self, temp_dir):
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {
            "tti_ms_p50": 100.0,
            "tti_ms_p95": 200.0
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        # Create CSV files to avoid None return
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id\n1\n")

        result = load_s5_run(run_dir)
        assert result is not None
        assert result['tti_p50'] == 100.0


class TestComputeQualityMetrics:
    """Tests for compute_quality_metrics function."""

    def test_compute_basic_metrics(self):
        df = pd.DataFrame({
            'backend': ['kafka', 'kafka', 'redis'],
            'config': ['baseline', 'high_speedup', 'baseline'],
            'tti_p50': [100.0, 150.0, 80.0],
            'tti_p95': [200.0, 250.0, 160.0],
            'tti_mean': [120.0, 180.0, 90.0],
            'n_producer_events': [1000, 1000, 1000],
            'n_consumer_events': [1000, 1000, 1000],
            'n_matched': [999, 998, 999],
            'n_produced': [1000, 1000, 1000],
            'speedup': [120, 240, 120],
            'resource_kafka_avg_cpu': [5.0, 6.0, 0.0],
            'resource_redis_avg_cpu': [0.0, 0.0, 4.0],
        })

        result = compute_quality_metrics(df)
        assert len(result) == 3  # kafka-baseline, kafka-high_speedup, redis-baseline
        assert 'match_rate' in result.columns
        assert 'avg_tti_p50' in result.columns

    def test_compute_empty_dataframe(self):
        df = pd.DataFrame()
        result = compute_quality_metrics(df)
        assert len(result) == 0

    def test_compute_missing_columns(self):
        df = pd.DataFrame({
            'backend': ['kafka'],
            'config': ['baseline'],
        })
        result = compute_quality_metrics(df)
        assert len(result) == 1
        assert pd.isna(result.iloc[0]['avg_tti_p50'])


class TestLoadS5RunEdgeCases:
    """Additional tests for load_s5_run edge cases to improve coverage."""

    def test_load_with_malformed_tti_json(self, temp_dir):
        """Test load_s5_run with malformed tti_summary.json (covers lines 95-96)."""
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create malformed tti_summary.json
        with open(run_dir / "tti_summary.json", 'w') as f:
            f.write("{ invalid json")

        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        # Create CSV files to avoid None return
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id\n1\n")

        # Should not crash, just print warning
        result = load_s5_run(run_dir)
        assert result is not None
        assert result['run_id'] == 's5_s2sf12_baseline_kafka_rep1_20260101'

    def test_load_with_malformed_meta_json(self, temp_dir):
        """Test load_s5_run with malformed meta.json (covers lines 105-106)."""
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create tti_summary.json
        tti_data = {"tti_ms_p50": 100.0}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create malformed meta.json
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{ invalid json")

        # Create CSV files to avoid None return
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id\n1\n")

        # Should not crash, just return empty meta
        result = load_s5_run(run_dir)
        assert result is not None
        assert result['run_id'] == 's5_s2sf12_baseline_kafka_rep1_20260101'

    def test_load_with_malformed_csv_files(self, temp_dir):
        """Test load_s5_run with malformed CSV files (covers lines 121-122)."""
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create tti_summary.json
        tti_data = {"tti_ms_p50": 100.0}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create meta.json
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        # Create malformed CSV files
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("invalid,csv,file\n")
        with open(run_dir / "consumer.csv", 'w') as f:
            f.write("invalid,csv,file\n")

        # Should not crash, just return 0 counts
        result = load_s5_run(run_dir)
        assert result is not None
        assert result['n_producer_events'] == 0
        assert result['n_consumer_events'] == 0

    def test_load_with_malformed_resource_json(self, temp_dir):
        """Test load_s5_run with malformed resource_summary.json (covers lines 131-132)."""
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create tti_summary.json
        tti_data = {"tti_ms_p50": 100.0}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create meta.json
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        # Create malformed resource_summary.json
        with open(run_dir / "resource_summary.json", 'w') as f:
            f.write("{ invalid json")

        # Create CSV files
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id\n1\n")

        # Should not crash, just return empty resource data
        result = load_s5_run(run_dir)
        assert result is not None
        assert result['run_id'] == 's5_s2sf12_baseline_kafka_rep1_20260101'

    def test_load_with_flat_transport_structure(self, temp_dir):
        """Test load_s5_run with flat transport_ms structure (covers line 171)."""
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        # Create tti_summary.json with flat transport structure (no nested transport_ms)
        tti_data = {
            "tti_ms_p50": 100.0,
            "transport_ms_p50": 10.0,
            "transport_ms_p95": 20.0
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id\n1\n")

        result = load_s5_run(run_dir)
        assert result is not None
        # Should have transport_p50 and transport_p95 from flat structure
        assert result.get('transport_p50') == 10.0
        assert result.get('transport_p95') == 20.0


@patch('analyze_s5_results.print')
@patch('analyze_s5_results.plt.close')
@patch('analyze_s5_results.plt.savefig')
@patch('analyze_s5_results.plt.figure')
@patch('analyze_s5_results.sns.barplot')
class TestGenerateQualityPlots:
    """Tests for generate_quality_plots function (covers lines 228-276)."""

    def test_generate_plots_with_all_data(self, mock_barplot, mock_figure, mock_savefig, mock_close, mock_print, temp_dir, monkeypatch):
        """Test generate_quality_plots with all required data columns."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with all required columns
            df = pd.DataFrame({
                'backend': ['kafka', 'kafka', 'redis'],
                'config': ['baseline', 'high_speedup', 'baseline'],
                'run_id': ['run1', 'run2', 'run3'],
                'tti_p50': [100.0, 150.0, 80.0],
                'tti_p95': [200.0, 250.0, 160.0],
                'n_producer_events': [1000, 1000, 1000],
                'n_consumer_events': [1000, 1000, 1000],
            })
            
            quality_df = pd.DataFrame({
                'backend': ['kafka', 'redis'],
                'config': ['baseline', 'baseline'],
                'count': [2, 1],
                'avg_tti_p50': [125.0, 80.0],
                'avg_tti_p95': [225.0, 160.0],
            })
            
            # Create output directory
            Path("docs/results/s5_figures").mkdir(parents=True)
            
            generate_quality_plots(df, quality_df)
            
            # Should have called plotting functions
            assert mock_figure.call_count >= 3  # At least 3 plots
            assert mock_savefig.call_count >= 3
            assert mock_close.call_count >= 3
            assert mock_barplot.call_count >= 3
        finally:
            os.chdir(old_cwd)

    def test_generate_plots_with_missing_columns(self, mock_barplot, mock_figure, mock_savefig, mock_close, mock_print, temp_dir, monkeypatch):
        """Test generate_quality_plots with missing optional data columns."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data without optional columns
            df = pd.DataFrame({
                'backend': ['kafka'],
                'config': ['baseline'],
                'run_id': ['run1'],
            })
            
            quality_df = pd.DataFrame({
                'backend': ['kafka'],
                'config': ['baseline'],
                'count': [1],
            })
            
            # Create output directory
            Path("docs/results/s5_figures").mkdir(parents=True)
            
            generate_quality_plots(df, quality_df)
            
            # Should not crash even with missing columns
            assert True
        finally:
            os.chdir(old_cwd)


@patch('analyze_s5_results.print')
class TestGenerateSummaryMarkdown:
    """Tests for generate_summary_markdown function (covers lines 281-336)."""

    def test_generate_markdown_basic(self, mock_print, temp_dir, monkeypatch):
        """Test generate_summary_markdown with basic data."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            df = pd.DataFrame({
                'backend': ['kafka', 'redis'],
                'config': ['baseline', 'baseline'],
                'scenario': ['s2sf12', 's2sf12'],
                'speedup': [120, 120],
                'corrections_every_k': [50, 50],
                'correction_delay_s': [2.0, 2.0],
                'tti_p50': [100.0, 80.0],
            })
            
            quality_df = pd.DataFrame({
                'backend': ['kafka', 'redis'],
                'config': ['baseline', 'baseline'],
                'count': [1, 1],
                'avg_tti_p50': [100.0, 80.0],
                'avg_tti_p95': [200.0, 160.0],
                'avg_tti_mean': [120.0, 90.0],
                'speedup': [120, 120],
            })
            
            # Create output directory
            Path("docs/results").mkdir(parents=True)
            
            generate_summary_markdown(df, quality_df)
            
            # Check that markdown file was created
            markdown_path = Path("docs/results/s5_quality_summary.md")
            assert markdown_path.exists()
            
            with open(markdown_path, 'r') as f:
                content = f.read()
            
            assert "S5 Resource Analysis" in content
            assert "Total Runs:" in content
            assert "Quality Metrics" in content
        finally:
            os.chdir(old_cwd)

    def test_generate_markdown_with_resource_metrics(self, mock_print, temp_dir, monkeypatch):
        """Test generate_summary_markdown with resource metrics (covers resource columns)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            df = pd.DataFrame({
                'backend': ['kafka', 'redis'],
                'config': ['baseline', 'baseline'],
                'scenario': ['s2sf12', 's2sf12'],
            })
            
            quality_df = pd.DataFrame({
                'backend': ['kafka', 'redis'],
                'config': ['baseline', 'baseline'],
                'count': [1, 1],
                'avg_tti_p50': [100.0, 80.0],
                'avg_kafka_avg_cpu': [5.0, 0.0],
                'avg_redis_avg_cpu': [0.0, 4.0],
            })
            
            # Create output directory
            Path("docs/results").mkdir(parents=True)
            
            generate_summary_markdown(df, quality_df)
            
            # Check that markdown file was created
            markdown_path = Path("docs/results/s5_quality_summary.md")
            assert markdown_path.exists()
            
            with open(markdown_path, 'r') as f:
                content = f.read()
            
            # Check for resource metrics section
            assert "Resource Metrics" in content
        finally:
            os.chdir(old_cwd)


@patch('analyze_s5_results.print')
@patch('analyze_s5_results.load_s5_run')
@patch('analyze_s5_results.compute_quality_metrics')
@patch('analyze_s5_results.generate_quality_plots')
@patch('analyze_s5_results.generate_summary_markdown')
class TestMainFunction:
    """Tests for main function (covers lines 341-402)."""

    def test_main_with_data(self, mock_gen_markdown, mock_gen_plots, mock_compute, mock_load, mock_print, temp_dir, monkeypatch):
        """Test main function with valid S5 run data."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create output directories
            Path("docs/results/s5_figures").mkdir(parents=True)
            Path("data/processed/results").mkdir(parents=True)
            Path("runs").mkdir()
            
            # Mock the functions
            mock_run_dir = temp_dir / "runs" / "s5_test_run"
            mock_run_dir.mkdir()
            
            mock_load.return_value = {
                'run_id': 's5_test_run',
                'backend': 'kafka',
                'config': 'baseline',
                'scenario': 's2sf12',
                'tti_p50': 100.0,
                'n_producer_events': 1000,
                'n_consumer_events': 1000,
            }
            
            mock_compute.return_value = pd.DataFrame({
                'backend': ['kafka'],
                'config': ['baseline'],
                'avg_tti_p50': [100.0],
                'count': [1]
            })
            
            result = analyze_s5_main()
            
            # Should return 0 for success
            assert result == 0
            
            # Verify all mocked functions were called
            mock_load.assert_called()
            mock_compute.assert_called()
            mock_gen_plots.assert_called()
            mock_gen_markdown.assert_called()
        finally:
            os.chdir(old_cwd)

    def test_main_no_s5_runs(self, mock_gen_markdown, mock_gen_plots, mock_compute, mock_load, mock_print, temp_dir, monkeypatch):
        """Test main function when no S5 runs are found (covers error path)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create output directories
            Path("docs/results/s5_figures").mkdir(parents=True)
            Path("data/processed/results").mkdir(parents=True)
            Path("runs").mkdir()
            
            # Mock to return no S5 runs
            mock_load.side_effect = [
                {
                    'run_id': 's5_test_run',
                    'backend': 'kafka',
                    'config': 'baseline',
                    'scenario': 's2sf12',
                    'tti_p50': 100.0,
                    'n_producer_events': 1000,
                    'n_consumer_events': 1000,
                }
            ]
            
            # But first discovery should find no s5_ directories
            # Mock the listdir to return non-S5 directories
            with patch('pathlib.Path.iterdir') as mock_iterdir:
                mock_iterdir.return_value = [
                    Path(temp_dir / "runs" / "non_s5_run")
                ]
                
                result = analyze_s5_main()
                
                # Should return 1 for error when no S5 runs found
                assert result == 1
        finally:
            os.chdir(old_cwd)

    def test_main_load_errors_all_fail(self, mock_gen_markdown, mock_gen_plots, mock_compute, mock_load, mock_print, temp_dir, monkeypatch):
        """Test main function when all load calls fail (covers error path)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create output directories
            Path("docs/results/s5_figures").mkdir(parents=True)
            Path("data/processed/results").mkdir(parents=True)
            Path("runs").mkdir()
            
            # Create an S5 run directory
            s5_run_dir = temp_dir / "runs" / "s5_test_run"
            s5_run_dir.mkdir()
            
            # Mock load_s5_run to always raise exception
            mock_load.side_effect = Exception("Test load error")
            
            result = analyze_s5_main()
            
            # Should return 1 for error when all loads fail
            assert result == 1
        finally:
            os.chdir(old_cwd)


class TestEntryPoint:
    """Tests for entry point (covers lines 406-407)."""

    def test_import_module(self):
        """Test that the module can be imported and has expected functions."""
        import analyze_s5_results
        assert hasattr(analyze_s5_results, 'main')
        assert hasattr(analyze_s5_results, 'parse_s5_run_id')
        assert hasattr(analyze_s5_results, 'load_s5_run')
        assert hasattr(analyze_s5_results, 'compute_quality_metrics')
        assert hasattr(analyze_s5_results, 'generate_quality_plots')
        assert hasattr(analyze_s5_results, 'generate_summary_markdown')
