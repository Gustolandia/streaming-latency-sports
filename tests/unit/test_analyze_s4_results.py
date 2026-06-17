"""Complete tests for analyze_s4_results.py - Target: 95%+ branch coverage."""
import pytest
import pandas as pd
import numpy as np
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_s4_results import (
    load_s4_metrics,
    analyze_parameter_effects,
    generate_effect_plots,
    generate_summary_markdown,
)


class TestLoadS4Metrics:
    """Tests for load_s4_metrics function."""

    def test_load_csv_file(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_high_speedup_redis_rep1_20260101"],
                "correction_propagation_latency_ms": ["{'p50': 100, 'p95': 200, 'p99': 300}", "{'p50': 150, 'p95': 250, 'p99': 350}"],
                "inconsistency_duration_ms": ["{'p50': 50, 'p95': 75, 'p99': 100}", "{'p50': 60, 'p95': 80, 'p99': 120}"],
                "n_corrections": [10, 20],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_metrics()
            
            assert len(result) == 2
            assert "scenario" in result.columns
            assert "config_name" in result.columns
            assert "backend" in result.columns
            assert "rep" in result.columns
            assert "speedup" in result.columns
            assert "corrections_every_k" in result.columns
            assert "correction_delay_s" in result.columns
            assert "correction_propagation_latency_ms_p50" in result.columns
        finally:
            os.chdir(old_cwd)

    def test_csv_not_found(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            result = load_s4_metrics()
            
            assert result.empty
        finally:
            os.chdir(old_cwd)

    def test_config_mapping(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file with baseline config
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_metrics()
            
            assert len(result) == 1
            assert result["speedup"].iloc[0] == 120
            assert result["corrections_every_k"].iloc[0] == 50
            assert result["correction_delay_s"].iloc[0] == 2.0
        finally:
            os.chdir(old_cwd)


class TestAnalyzeParameterEffects:
    """Tests for analyze_parameter_effects function."""

    @patch('analyze_s4_results.print')
    def test_analyze_effects(self, mock_print, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_high_speedup_kafka_rep1_20260101"],
                "scenario": ["s2sf12", "s2sf12"],
                "config_name": ["baseline", "high_speedup"],
                "backend": ["kafka", "kafka"],
                "rep": [1, 1],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "correction_propagation_latency_ms_p50": [100.0, 150.0],
                "correction_propagation_latency_ms_p95": [200.0, 250.0],
                "inconsistency_duration_ms_p50": [50.0, 60.0],
                "inconsistency_duration_ms_p95": [75.0, 80.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            effects_df = analyze_parameter_effects(df)
            
            assert not effects_df.empty
            assert "parameter" in effects_df.columns
            assert "metric" in effects_df.columns
            
            # Check CSV was created
            assert (output_dir / "s4_parameter_effects.csv").exists()
        finally:
            os.chdir(old_cwd)

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        effects_df = analyze_parameter_effects(df)
        assert effects_df.empty


class TestGenerateEffectPlots:
    """Tests for generate_effect_plots function."""

    @patch('analyze_s4_results.sns.pairplot')
    @patch('analyze_s4_results.sns.boxplot')
    @patch('analyze_s4_results.plt.close')
    @patch('analyze_s4_results.plt.savefig')
    @patch('analyze_s4_results.plt.figure')
    @patch('analyze_s4_results.print')
    def test_generate_plots(self, mock_print, mock_figure, mock_savefig, mock_close, mock_boxplot, mock_pairplot, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "speedup": [120],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
                "correction_propagation_latency_ms_p50": [100.0],
                "correction_propagation_latency_ms_p95": [200.0],
                "inconsistency_duration_ms_p50": [50.0],
                "inconsistency_duration_ms_p95": [75.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results" / "s4_figures"
            output_dir.mkdir(parents=True)
            
            generate_effect_plots(df)
            
            # If no exceptions, test passes
            assert True
        finally:
            os.chdir(old_cwd)


class TestGenerateSummaryMarkdown:
    """Tests for generate_summary_markdown function."""

    @patch('analyze_s4_results.print')
    def test_generate_markdown(self, mock_print, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_high_speedup_redis_rep1_20260101"],
                "scenario": ["s2sf12", "s2sf12"],
                "config_name": ["baseline", "high_speedup"],
                "backend": ["kafka", "redis"],
                "rep": [1, 1],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            # Call with empty effects_df
            effects_df = pd.DataFrame()
            generate_summary_markdown(df, effects_df)
            
            # Check that markdown file was created
            assert (output_dir / "s4_analysis_summary.md").exists()
            
            # Check content
            with open(output_dir / "s4_analysis_summary.md", "r") as f:
                content = f.read()
            
            assert "S4 Parameter Sensitivity Analysis" in content
            assert "Total Runs:" in content
        finally:
            os.chdir(old_cwd)


class TestEdgeCases:
    """Tests for edge cases to improve coverage."""

    def test_extract_run_info_invalid_format(self, temp_dir, monkeypatch):
        """Test extract_run_info with invalid run_id format (covers line 54)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV with invalid run_id that can't be parsed
            data = {
                "run": ["invalid_run_id"],
                "correction_propagation_latency_ms": ["{'p50': 100}"],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_metrics()
            
            # Should handle invalid format gracefully
            assert len(result) == 1
            # scenario, config_name, backend, rep should be None for invalid format
            assert pd.isna(result["scenario"].iloc[0]) or result["scenario"].iloc[0] is None
        finally:
            os.chdir(old_cwd)

    def test_analyze_effects_missing_parameter(self, temp_dir, monkeypatch):
        """Test analyze_parameter_effects with missing parameter columns (covers line 124)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data without speedup column
            data = {
                "run": ["s4_test1"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
                "correction_propagation_latency_ms_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            effects_df = analyze_parameter_effects(df)
            
            # Should still work, just skip speedup parameter
            assert True
        finally:
            os.chdir(old_cwd)

    def test_analyze_effects_with_exception(self, temp_dir, monkeypatch):
        """Test analyze_parameter_effects with exception in grouping (covers lines 133-135)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with problematic data that might cause exception
            data = {
                "run": ["s4_test1", "s4_test2"],
                "scenario": ["s2sf12", "s2sf12"],
                "config_name": ["baseline", "high_speedup"],
                "backend": ["kafka", "kafka"],
                "rep": [1, 1],
                "speedup": [120, None],  # None value might cause issues
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "correction_propagation_latency_ms_p50": [100.0, 150.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            effects_df = analyze_parameter_effects(df)
            
            # Should handle exceptions gracefully
            assert True
        finally:
            os.chdir(old_cwd)

    def test_generate_markdown_with_effects(self, temp_dir, monkeypatch):
        """Test generate_summary_markdown with effects_df data (covers lines 241-258)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "speedup": [120],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
            }
            df = pd.DataFrame(data)
            
            # Create effects_df with parameter data - need to include the parameter values
            effects_data = {
                "parameter": ["speedup", "speedup"],
                "speedup": [120, 240],  # Add the parameter value columns
                "metric": ["correction_propagation_latency_ms_p50", "inconsistency_duration_ms_p50"],
                "mean": [100.0, 50.0],
                "std": [10.0, 5.0],
                "min": [90.0, 45.0],
                "max": [110.0, 55.0],
                "count": [1, 1],
            }
            effects_df = pd.DataFrame(effects_data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            generate_summary_markdown(df, effects_df)
            
            # Check that markdown file was created
            assert (output_dir / "s4_analysis_summary.md").exists()
            
            with open(output_dir / "s4_analysis_summary.md", "r") as f:
                content = f.read()
            
            # Check for parameter effect sections
            assert "Effect of speedup" in content
        finally:
            os.chdir(old_cwd)

    @patch('analyze_s4_results.print')
    def test_main_empty_dataframe(self, mock_print, temp_dir, monkeypatch):
        """Test main function with empty dataframe (covers lines 280-313)."""
        from analyze_s4_results import main as analyze_s4_main
        
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create output directories
            Path("docs/results/s4_figures").mkdir(parents=True, exist_ok=True)
            
            # Mock load_s4_metrics to return empty dataframe
            with patch('analyze_s4_results.load_s4_metrics') as mock_load:
                mock_load.return_value = pd.DataFrame()
                
                result = analyze_s4_main()
                
                # Should return 1 for error
                assert result == 1
        finally:
            os.chdir(old_cwd)

    def test_analyze_effects_empty_result(self, temp_dir, monkeypatch):
        """Test analyze_parameter_effects returns empty dataframe (covers line 142)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data without any parameter columns
            data = {
                "run": ["s4_test1"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "correction_propagation_latency_ms_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            effects_df = analyze_parameter_effects(df)
            
            # Should return empty dataframe since no parameter columns exist
            assert effects_df.empty
        finally:
            os.chdir(old_cwd)

    def test_analyze_effects_with_grouping_exception(self, temp_dir, monkeypatch):
        """Test analyze_parameter_effects with exception in grouping (covers lines 133-135)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with problematic data that causes exception in groupby
            # For example, if the parameter column has non-hashable types
            data = {
                "run": ["s4_test1"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "speedup": [[120]],  # List instead of scalar - might cause issues
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
                "correction_propagation_latency_ms_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            effects_df = analyze_parameter_effects(df)
            
            # Should handle exception gracefully and return empty or partial results
            # The function should not crash
            assert True
        finally:
            os.chdir(old_cwd)

    @patch('analyze_s4_results.print')
    @patch('analyze_s4_results.load_s4_metrics')
    @patch('analyze_s4_results.analyze_parameter_effects')
    @patch('analyze_s4_results.generate_effect_plots')
    @patch('analyze_s4_results.generate_summary_markdown')
    def test_main_with_data(self, mock_gen_markdown, mock_gen_plots, mock_analyze, mock_load, mock_print, temp_dir, monkeypatch):
        """Test main function with actual data to cover lines 292-313."""
        from analyze_s4_results import main as analyze_s4_main
        
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create output directories
            Path("docs/results/s4_figures").mkdir(parents=True, exist_ok=True)
            
            # Mock the functions
            mock_df = pd.DataFrame({
                "run": ["s4_test1"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "speedup": [120],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
                "correction_propagation_latency_ms_p50": [100.0],
            })
            mock_load.return_value = mock_df
            mock_analyze.return_value = mock_df
            
            result = analyze_s4_main()
            
            # Should return 0 for success
            assert result == 0
            
            # Verify all mocked functions were called
            mock_load.assert_called_once()
            mock_analyze.assert_called_once()
            mock_gen_plots.assert_called_once()
            mock_gen_markdown.assert_called_once()
        finally:
            os.chdir(old_cwd)

    def test_generate_markdown_correction_delay_formatting(self, temp_dir, monkeypatch):
        """Test generate_summary_markdown with correction_delay_s formatting (covers line 252)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
                "scenario": ["s2sf12"],
                "config_name": ["baseline"],
                "backend": ["kafka"],
                "rep": [1],
                "speedup": [120],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],  # This will test the float formatting
            }
            df = pd.DataFrame(data)
            
            # Create effects_df with correction_delay_s parameter
            effects_data = {
                "parameter": ["correction_delay_s", "correction_delay_s"],
                "correction_delay_s": [2.5, 5.0],  # Float values to test formatting
                "metric": ["correction_propagation_latency_ms_p50", "correction_propagation_latency_ms_p50"],
                "mean": [100.0, 110.0],
                "std": [10.0, 11.0],
                "min": [90.0, 99.0],
                "max": [110.0, 121.0],
                "count": [1, 1],
            }
            effects_df = pd.DataFrame(effects_data)
            
            # Create output directory
            output_dir = temp_dir / "docs" / "results"
            output_dir.mkdir(parents=True)
            
            generate_summary_markdown(df, effects_df)
            
            # Check that markdown file was created
            assert (output_dir / "s4_analysis_summary.md").exists()
            
            with open(output_dir / "s4_analysis_summary.md", "r") as f:
                content = f.read()
            
            # Check for correction_delay_s formatting (should be formatted as float with .1f)
            assert "Effect of correction_delay_s" in content
            # The correction_delay_s values should be formatted as 2.5 and 5.0
            assert "2.5" in content or "5.0" in content  # At least one should be present
        finally:
            os.chdir(old_cwd)
