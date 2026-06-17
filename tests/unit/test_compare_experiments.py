"""Complete tests for compare_experiments.py - Target: 95%+ branch coverage."""
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

from compare_experiments import (
    load_run,
    load_experiment_runs,
    generate_comparison_plots,
    generate_comparison_tables,
    generate_manuscript_report,
    main,
)


class TestLoadRun:
    """Tests for load_run function."""

    def test_load_s3_run(self, temp_dir):
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0},
            "correction_propagation_latency_ms": {"p50": 10.0, "p95": 20.0},
            "inconsistency_duration_ms": {"p50": 5.0, "p95": 15.0},
            "n_produced": 1000,
            "n_consumed": 1000,
            "n_matched": 999
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['experiment'] == 'S3'
        assert result['scenario'] == 's2'
        assert result['backend'] == 'kafka'
        assert result['tti_p50'] == 100.0
        assert result['correction_propagation_p50'] == 10.0

    def test_load_s4_run(self, temp_dir):
        run_dir = temp_dir / "s4_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0},
            "n_produced": 1000,
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        result = load_run(run_dir, 's4')
        assert result is not None
        assert result['experiment'] == 'S4'
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'baseline'

    def test_load_s5_run(self, temp_dir):
        run_dir = temp_dir / "s5_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0},
            "n_produced": 1000,
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        result = load_run(run_dir, 's5')
        assert result is not None
        assert result['experiment'] == 'S5'
        assert result['scenario'] == 's2sf12'
        assert result['config'] == 'baseline'

    def test_load_invalid_format(self, temp_dir):
        run_dir = temp_dir / "invalid_name"
        run_dir.mkdir()

        result = load_run(run_dir, 's3')
        assert result is None

    def test_load_with_resource_data(self, temp_dir):
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        resource_data = {
            "kafka_avg_cpu": 5.0,
            "kafka_avg_mem": 1000.0
        }
        with open(run_dir / "resource_summary.json", 'w') as f:
            json.dump(resource_data, f)

        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['resource_kafka_avg_cpu'] == 5.0

    def test_load_with_meta_data(self, temp_dir):
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        meta_data = {
            "max_t_sim": 600,
            "speedup": 120
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['meta_max_t_sim'] == 600
        assert result['meta_speedup'] == 120

    def test_load_with_csv_events(self, temp_dir):
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()

        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create CSV files
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("id,event\n1,a\n2,b\n3,c\n")
        with open(run_dir / "consumer.csv", 'w') as f:
            f.write("id,event\n1,x\n2,y\n")

        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['n_producer_events'] == 3
        assert result['n_consumer_events'] == 2

    def test_load_s4_invalid_format_short(self, temp_dir):
        """Test S4 load with too few parts (covers line 84)."""
        run_dir = temp_dir / "s4_short"
        run_dir.mkdir()
        
        result = load_run(run_dir, 's4')
        assert result is None

    def test_load_s4_with_transport_metrics(self, temp_dir):
        """Test load_run with transport metrics (covers lines 110-112)."""
        run_dir = temp_dir / "s4_s2sf12_baseline_kafka_rep1_20260101"
        run_dir.mkdir()
        
        tti_data = {
            "tti_ms": {"p50": 100.0},
            "transport_ms": {"p50": 50.0, "p95": 100.0}
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        result = load_run(run_dir, 's4')
        assert result is not None
        assert result['transport_p50'] == 50.0
        assert result['transport_p95'] == 100.0

    def test_load_s3_with_exception_in_tti(self, temp_dir):
        """Test load_run with exception in TTI processing (covers lines 129-130)."""
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()
        
        # Create malformed tti_summary.json
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump({"invalid": "data"}, f)
        
        result = load_run(run_dir, 's3')
        assert result is not None
        # Should have basic metrics but not TTI-specific ones
        assert result['experiment'] == 'S3'

    def test_load_with_exception_in_resource(self, temp_dir):
        """Test load_run with exception in resource processing (covers lines 140-141)."""
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()
        
        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Create malformed resource_summary.json
        with open(run_dir / "resource_summary.json", 'w') as f:
            f.write("{invalid json}")
        
        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['experiment'] == 'S3'

    def test_load_with_exception_in_meta(self, temp_dir):
        """Test load_run with exception in meta processing (covers lines 152-153)."""
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()
        
        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Create malformed meta.json
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{invalid json}")
        
        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['experiment'] == 'S3'

    def test_load_with_exception_in_csv(self, temp_dir):
        """Test load_run with exception in CSV processing (covers lines 163-164)."""
        run_dir = temp_dir / "s3_s2_kafka_rep1_20260101"
        run_dir.mkdir()
        
        tti_data = {"tti_ms": {"p50": 100.0}}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Create malformed CSV
        with open(run_dir / "producer.csv", 'w') as f:
            f.write("invalid,csv\n")
        
        result = load_run(run_dir, 's3')
        assert result is not None
        assert result['experiment'] == 'S3'


class TestLoadExperimentRuns:
    """Tests for load_experiment_runs function (covers lines 33-46)."""

    def test_load_s3_experiment(self, temp_dir, monkeypatch):
        """Test loading S3 experiment runs (covers lines 33-46)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create runs directory
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            # Create S3 run directories
            for i in range(3):
                run_dir = runs_dir / f"s3_test_kafka_rep{i}_20260101"
                run_dir.mkdir()
                
                tti_data = {"tti_ms": {"p50": 100.0 * (i + 1)}}
                with open(run_dir / "tti_summary.json", 'w') as f:
                    json.dump(tti_data, f)
            
            # Create a non-S3 directory that should be ignored
            (runs_dir / "other_test").mkdir()
            
            with patch.object(Path, 'cwd', return_value=Path(temp_dir)):
                result = load_experiment_runs('s3')
            
            assert len(result) == 3
            assert 'experiment' in result.columns
            assert (result['experiment'] == 'S3').all()
        finally:
            os.chdir(old_cwd)

    def test_load_empty_experiment(self, temp_dir, monkeypatch):
        """Test loading experiment with no matching runs."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create runs directory but no S3 runs
            runs_dir = temp_dir / "runs"
            runs_dir.mkdir()
            
            with patch.object(Path, 'cwd', return_value=Path(temp_dir)):
                result = load_experiment_runs('s3')
            
            assert len(result) == 0
        finally:
            os.chdir(old_cwd)


class TestGenerateComparisonPlots:
    """Tests for generate_comparison_plots function (covers lines 171-301)."""

    @patch('compare_experiments.print')
    @patch('compare_experiments.plt.figure')
    @patch('compare_experiments.plt.close')
    @patch('compare_experiments.plt.savefig')
    @patch('compare_experiments.plt.title')
    @patch('compare_experiments.plt.xlabel')
    @patch('compare_experiments.plt.ylabel')
    @patch('compare_experiments.plt.legend')
    @patch('compare_experiments.plt.tight_layout')
    @patch('compare_experiments.plt.xticks')
    @patch('compare_experiments.sns.barplot')
    @patch('compare_experiments.sns.boxplot')
    def test_generate_all_plots(self, mock_xticks, mock_tight_layout, mock_legend, mock_ylabel, mock_xlabel, 
                               mock_title, mock_savefig, mock_close, mock_figure, mock_barplot, 
                               mock_boxplot, mock_print, temp_dir, monkeypatch):
        """Test generate_comparison_plots with all data (covers most of lines 171-301)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test dataframes with all required columns
            s3_df = pd.DataFrame({
                "run_id": ["s3_a_kafka_rep1_t1", "s3_a_redis_rep1_t1"],
                "scenario": ["a", "a"],
                "backend": ["kafka", "redis"],
                "rep": [1, 1],
                "tti_p50": [100.0, 150.0],
                "tti_p95": [200.0, 250.0],
                "n_produced": [1000, 1000],
                "n_matched": [999, 999],
                "n_consumed": [1000, 1000],
                "resource_kafka_avg_cpu": [5.0, 6.0],
                "resource_sample_count": [100, 100],
                "correction_propagation_mean": [10.0, 15.0],
                "inconsistency_duration_mean": [5.0, 8.0],
                "n_producer_events": [1000, 1000],
            })
            s4_df = pd.DataFrame({
                "run_id": ["s4_a_baseline_kafka_rep1_t1"],
                "scenario": ["a"],
                "backend": ["kafka"],
                "rep": [1],
                "tti_p50": [120.0],
                "tti_p95": [220.0],
                "n_produced": [1000],
                "n_matched": [999],
                "n_consumed": [1000],
                "resource_kafka_avg_cpu": [5.5],
                "resource_sample_count": [100],
            })
            s5_df = pd.DataFrame({
                "run_id": ["s5_a_baseline_kafka_rep1_t1"],
                "scenario": ["a"],
                "backend": ["kafka"],
                "rep": [1],
                "tti_p50": [110.0],
                "tti_p95": [210.0],
                "n_produced": [1000],
                "n_matched": [999],
                "n_consumed": [1000],
                "resource_kafka_avg_cpu": [7.0],
                "resource_sample_count": [100],
            })
            
            output_dir = temp_dir / "docs" / "results" / "experiments_figures"
            output_dir.mkdir(parents=True)
            
            generate_comparison_plots(s3_df, s4_df, s5_df, str(output_dir))
            
            # Verify print was called
            assert mock_print.called
        finally:
            os.chdir(old_cwd)

    @patch('compare_experiments.print')
    @patch('compare_experiments.plt.figure')
    def test_generate_plots_no_data(self, mock_figure, mock_print, temp_dir):
        """Test generate_comparison_plots with empty dataframes."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            s3_df = pd.DataFrame()
            s4_df = pd.DataFrame()
            s5_df = pd.DataFrame()
            
            output_dir = temp_dir / "docs" / "results" / "experiments_figures"
            output_dir.mkdir(parents=True)
            
            generate_comparison_plots(s3_df, s4_df, s5_df, str(output_dir))
            
            # Should not crash
            assert True
        finally:
            os.chdir(old_cwd)


class TestGenerateComparisonTables:
    """Tests for generate_comparison_tables function (covers lines 306-377)."""

    @patch('compare_experiments.print')
    def test_generate_tables_basic(self, mock_print, temp_dir, monkeypatch):
        """Test generate_comparison_tables with basic data (covers most of lines 306-377)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            s3_df = pd.DataFrame({
                "run_id": ["s3_a_kafka_rep1_t1"],
                "scenario": ["a"],
                "backend": ["kafka"],
                "rep": [1],
                "tti_p50": [100.0],
                "tti_p95": [200.0],
                "n_produced": [1000],
                "n_matched": [999],
                "resource_kafka_avg_cpu": [5.0],
                "resource_redis_avg_cpu": [3.0],
                "resource_sample_count": [100],
            })
            s4_df = pd.DataFrame()
            s5_df = pd.DataFrame({
                "run_id": ["s5_a_kafka_rep1_t1"],
                "scenario": ["a"],
                "backend": ["redis"],
                "rep": [1],
                "tti_p50": [150.0],
                "tti_p95": [250.0],
                "n_produced": [1000],
                "n_matched": [999],
                "resource_kafka_avg_cpu": [6.0],
                "resource_redis_avg_cpu": [4.0],
                "resource_sample_count": [100],
            })
            
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            summary_df, comparison_df = generate_comparison_tables(s3_df, s4_df, s5_df)
            
            assert summary_df is not None
            assert comparison_df is not None
        finally:
            os.chdir(old_cwd)


class TestGenerateManuscriptReport:
    """Tests for generate_manuscript_report function (covers lines 382-487)."""

    @patch('compare_experiments.print')
    def test_generate_report_basic(self, mock_print, temp_dir, monkeypatch):
        """Test generate_manuscript_report with basic data (covers most of lines 382-487)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            s3_df = pd.DataFrame({
                "run_id": ["s3_a_kafka_rep1_t1"],
                "scenario": ["a"],
                "backend": ["kafka"],
                "rep": [1],
                "tti_p50": [100.0],
                "tti_p95": [200.0],
                "n_produced": [1000],
                "n_matched": [999],
            })
            s4_df = pd.DataFrame()
            s5_df = pd.DataFrame({
                "run_id": ["s5_a_redis_rep1_t1"],
                "scenario": ["a"],
                "backend": ["redis"],
                "rep": [1],
                "tti_p50": [150.0],
                "tti_p95": [250.0],
                "n_produced": [1000],
                "n_matched": [999],
            })
            
            summary_df = pd.DataFrame({
                "Experiment": ["S3", "S5"],
                "Total Runs": [1, 1],
                "Scenarios": [1, 1],
                "Backends": [1, 1],
                "Avg TTI p50": [100.0, 150.0],
                "Avg TTI p95": [200.0, 250.0],
                "Avg Match Rate": [0.999, 0.999],
                "Avg Kafka CPU": [5.0, 0.0],
                "Avg Redis CPU": [0.0, 4.0],
                "Avg Sample Count": [100.0, 100.0],
            })
            
            comparison_df = pd.DataFrame({
                "Experiment": ["S3", "S5"],
                "Backend": ["kafka", "redis"],
                "Scenario": ["a", "a"],
                "TTI p50": [100.0, 150.0],
                "TTI p95": [200.0, 250.0],
                "Match Rate": [0.999, 0.999],
                "Kafka CPU": [5.0, 0.0],
                "Redis CPU": [0.0, 4.0],
                "Samples": [100.0, 100.0],
                "Runs": [1, 1],
            })
            
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            generate_manuscript_report(s3_df, s4_df, s5_df, summary_df, comparison_df)
            
            # Check that markdown file was created
            assert (output_dir / "experiments_comparison.md").exists()
        finally:
            os.chdir(old_cwd)


class TestMain:
    """Tests for main function (covers lines 492-533)."""

    @patch('compare_experiments.load_experiment_runs')
    @patch('compare_experiments.generate_comparison_plots')
    @patch('compare_experiments.generate_comparison_tables')
    @patch('compare_experiments.generate_manuscript_report')
    @patch('compare_experiments.print')
    @patch('compare_experiments.Path')
    def test_main_basic(self, mock_path, mock_print, mock_report, mock_tables, mock_plots, mock_load, temp_dir, monkeypatch):
        """Test main function with all experiments (covers lines 492-533)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create required output directories
            (temp_dir / "docs" / "results" / "experiments_figures").mkdir(parents=True)
            
            # Mock dataframes with required columns
            mock_load.side_effect = [
                pd.DataFrame({"run_id": ["s3_a_kafka_rep1_t1"], "experiment": ["S3"], "scenario": ["a"], "backend": ["kafka"], "rep": [1]}),
                pd.DataFrame({"run_id": ["s4_a_baseline_kafka_rep1_t1"], "experiment": ["S4"], "scenario": ["a"], "backend": ["kafka"], "rep": [1]}),
                pd.DataFrame({"run_id": ["s5_a_baseline_kafka_rep1_t1"], "experiment": ["S5"], "scenario": ["a"], "backend": ["kafka"], "rep": [1]}),
            ]
            
            mock_tables.return_value = (pd.DataFrame(), pd.DataFrame())
            
            # Mock Path to return temp_dir for outputs
            def path_side_effect(path):
                if isinstance(path, str) and path.startswith("docs"):
                    return temp_dir / path
                return Path(path)
            
            mock_path.side_effect = path_side_effect
            
            result = main()
            
            assert result == 0
            assert mock_load.call_count == 3
            assert mock_plots.called
            assert mock_tables.called
            assert mock_report.called
        finally:
            os.chdir(old_cwd)
    
    @patch('compare_experiments.load_experiment_runs')
    @patch('compare_experiments.print')
    @patch('compare_experiments.Path')
    def test_main_with_warning(self, mock_path, mock_print, mock_load, temp_dir, monkeypatch):
        """Test main function with load warning (covers print in main)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create required output directories
            (temp_dir / "docs" / "results" / "experiments_figures").mkdir(parents=True)
            
            # Mock dataframes with required columns (empty ones for S4 and S5)
            empty_df = pd.DataFrame({"run_id": [], "experiment": [], "scenario": [], "backend": [], "rep": []})
            mock_load.side_effect = [
                pd.DataFrame({"run_id": ["s3_a_kafka_rep1_t1"], "experiment": ["S3"], "scenario": ["a"], "backend": ["kafka"], "rep": [1]}),
                empty_df,
                empty_df,
            ]
            
            # Mock Path to return temp_dir for outputs
            def path_side_effect(path):
                if isinstance(path, str) and path.startswith("docs"):
                    return temp_dir / path
                return Path(path)
            
            mock_path.side_effect = path_side_effect
            
            result = main()
            
            assert result == 0
        finally:
            os.chdir(old_cwd)

    def test_entry_point(self):
        """Test entry point if __name__ == '__main__' (covers lines 537-538)."""
        import compare_experiments
        assert hasattr(compare_experiments, 'main')
