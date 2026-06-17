"""Complete tests for analyze_s4_results_simple.py - Target: 95%+ branch coverage."""
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

from analyze_s4_results_simple import (
    load_s4_data,
    create_output_dir,
    generate_tables,
    generate_figures,
    generate_report,
    main,
)


class TestLoadS4Data:
    """Tests for load_s4_data function."""

    def test_load_csv_with_run_column(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file with run column
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_high_speedup_redis_rep1_20260101"],
                "tti_p50": [100.0, 150.0],
                "tti_p95": [200.0, 250.0],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_data(csv_path)
            
            assert len(result) == 2
            assert "scenario" in result.columns
            assert "config" in result.columns
            assert "backend" in result.columns
        finally:
            os.chdir(old_cwd)

    def test_load_csv_rename_column(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file with run_id column
            data = {
                "run_id": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
                "tti_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_data(csv_path)
            
            assert "run" in result.columns
            assert "scenario" in result.columns
        finally:
            os.chdir(old_cwd)

    def test_config_mapping(self, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_data(csv_path)
            
            assert len(result) == 1
            assert result["speedup"].iloc[0] == 120
            assert result["corrections_every_k"].iloc[0] == 50
            assert result["correction_delay_s"].iloc[0] == 2.0
        finally:
            os.chdir(old_cwd)


class TestCreateOutputDir:
    """Tests for create_output_dir function."""

    def test_create_dirs(self, temp_dir):
        output_dir = create_output_dir(temp_dir / "test_output")
        
        assert output_dir.exists()
        assert (output_dir / "tables").exists()
        assert (output_dir / "figures").exists()


class TestGenerateTables:
    """Tests for generate_tables function."""

    @patch('analyze_s4_results_simple.print')
    def test_generate_tables(self, mock_print, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with all required columns
            data = {
                "run": ["s4_test1", "s4_test2"],
                "backend": ["kafka", "redis"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
                "tti_p95": [200.0, 250.0],
                "tti_p99": [300.0, 350.0],
                "tti_mean": [150.0, 200.0],
                "n_n_matched": [1000, 2000],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            # Create tables subdirectory
            (output_dir / "tables").mkdir(parents=True, exist_ok=True)
            
            generate_tables(df, output_dir)
            
            # Check that CSV files were created
            assert (output_dir / "tables" / "s4_backend_comparison.csv").exists()
            assert (output_dir / "tables" / "s4_config_comparison.csv").exists()
        finally:
            os.chdir(old_cwd)


class TestGenerateFigures:
    """Tests for generate_figures function."""

    @patch('analyze_s4_results_simple.print')
    @patch('analyze_s4_results_simple.plt.savefig')
    @patch('analyze_s4_results_simple.plt.close')
    @patch('analyze_s4_results_simple.plt.figure')
    @patch('analyze_s4_results_simple.sns.boxplot')
    def test_generate_figures(self, mock_boxplot, mock_figure, mock_close, mock_savefig, mock_print, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data
            data = {
                "run": ["s4_test1", "s4_test2"],
                "backend": ["kafka", "redis"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir(parents=True)
            
            generate_figures(df, output_dir)
            
            # If no exceptions, test passes
            assert True
        finally:
            os.chdir(old_cwd)


class TestGenerateReport:
    """Tests for generate_report function."""

    @patch('analyze_s4_results_simple.print')
    def test_generate_report(self, mock_print, temp_dir, monkeypatch):
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with all required columns
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101", "s4_s2sf12_high_speedup_redis_rep1_20260101"],
                "backend": ["kafka", "redis"],
                "scenario": ["s2sf12", "s2sf12"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            
            generate_report(df, output_dir)
            
            # Check that markdown file was created
            assert (output_dir / "s4_analysis_report.md").exists()
            
            # Check content
            with open(output_dir / "s4_analysis_report.md", "r") as f:
                content = f.read()
            
            assert "S4 Parameter Sweep Analysis Report" in content
            assert "Total Runs:" in content
        finally:
            os.chdir(old_cwd)


class TestEdgeCases:
    """Tests for edge cases to improve coverage."""

    def test_extract_info_invalid_format(self, temp_dir, monkeypatch):
        """Test extract_info with invalid run_id format (covers line 49)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV with invalid run_id that can't be parsed
            data = {
                "run": ["invalid_run_id_without_proper_format"],
                "tti_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            result = load_s4_data(csv_path)
            
            # Should handle invalid format gracefully
            assert len(result) == 1
            # scenario, config, backend should be None for invalid format
            assert pd.isna(result["scenario"].iloc[0]) or result["scenario"].iloc[0] is None
        finally:
            os.chdir(old_cwd)

    def test_generate_figures_with_missed_window(self, temp_dir, monkeypatch):
        """Test generate_figures with missed_window columns (covers lines 236-260)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with missed_window columns
            data = {
                "run": ["s4_test1", "s4_test2"],
                "backend": ["kafka", "redis"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
                "missed_window_100ms_rate": [0.01, 0.02],
                "missed_window_500ms_rate": [0.05, 0.06],
                "missed_window_1000ms_rate": [0.1, 0.15],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir(parents=True)
            
            # Mock matplotlib
            with patch('analyze_s4_results_simple.plt') as mock_plt:
                mock_fig = MagicMock()
                mock_plt.figure.return_value = mock_fig
                mock_plt.savefig = MagicMock()
                mock_plt.close = MagicMock()
                mock_plt.title = MagicMock()
                mock_plt.xlabel = MagicMock()
                mock_plt.ylabel = MagicMock()
                mock_plt.legend = MagicMock()
                mock_plt.grid = MagicMock()
                mock_plt.tight_layout = MagicMock()
                mock_plt.plot = MagicMock()
                
                generate_figures(df, output_dir)
                
                # Verify that plot was called (for missed window rates)
                assert mock_plt.plot.called
        finally:
            os.chdir(old_cwd)

    def test_generate_report_with_missed_window(self, temp_dir, monkeypatch):
        """Test generate_report with missed_window columns (covers line 357)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with missed_window columns
            data = {
                "run": ["s4_test1", "s4_test2"],
                "backend": ["kafka", "redis"],
                "scenario": ["s2sf12", "s2sf12"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
                "missed_window_100ms_rate": [0.01, 0.02],
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            
            generate_report(df, output_dir)
            
            # Check that markdown file was created and contains missed window reference
            assert (output_dir / "s4_analysis_report.md").exists()
            
            with open(output_dir / "s4_analysis_report.md", "r") as f:
                content = f.read()
            
            assert "s4_missed_window_rates.png" in content
        finally:
            os.chdir(old_cwd)

    def test_generate_figures_with_malformed_column(self, temp_dir, monkeypatch):
        """Test generate_figures with malformed missed_window column name (covers lines 247-248)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create test data with a malformed missed_window column
            data = {
                "run": ["s4_test1", "s4_test2"],
                "backend": ["kafka", "redis"],
                "config": ["baseline", "high_speedup"],
                "speedup": [120, 240],
                "corrections_every_k": [50, 50],
                "correction_delay_s": [2.0, 2.0],
                "tti_p50": [100.0, 150.0],
                "missed_window_abc_rate": [0.01, 0.02],  # Malformed - 'abc' is not a number
            }
            df = pd.DataFrame(data)
            
            # Create output directory
            output_dir = temp_dir / "output"
            output_dir.mkdir(parents=True)
            
            # Mock matplotlib
            with patch('analyze_s4_results_simple.plt') as mock_plt:
                mock_fig = MagicMock()
                mock_plt.figure.return_value = mock_fig
                mock_plt.savefig = MagicMock()
                mock_plt.close = MagicMock()
                mock_plt.title = MagicMock()
                mock_plt.xlabel = MagicMock()
                mock_plt.ylabel = MagicMock()
                mock_plt.legend = MagicMock()
                mock_plt.grid = MagicMock()
                mock_plt.tight_layout = MagicMock()
                mock_plt.plot = MagicMock()
                
                generate_figures(df, output_dir)
                
                # Should handle the malformed column gracefully
                assert True
        finally:
            os.chdir(old_cwd)

    @patch('analyze_s4_results_simple.print')
    def test_main_function(self, mock_print, temp_dir, monkeypatch):
        """Test main function (covers lines 363-386)."""
        old_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # Create CSV file
            data = {
                "run": ["s4_s2sf12_baseline_kafka_rep1_20260101"],
                "backend": ["kafka"],
                "scenario": ["s2sf12"],
                "config": ["baseline"],
                "speedup": [120],
                "corrections_every_k": [50],
                "correction_delay_s": [2.0],
                "tti_p50": [100.0],
            }
            df = pd.DataFrame(data)
            
            csv_path = temp_dir / "data" / "processed" / "results" / "paper_s4_parameter_sweep.csv"
            csv_path.parent.mkdir(parents=True)
            df.to_csv(csv_path, index=False)
            
            # Mock the functions that main calls
            with patch('analyze_s4_results_simple.load_s4_data') as mock_load:
                mock_load.return_value = df
                
                with patch('analyze_s4_results_simple.create_output_dir') as mock_create:
                    mock_output_dir = MagicMock()
                    mock_create.return_value = mock_output_dir
                    
                    with patch('analyze_s4_results_simple.generate_tables') as mock_tables:
                        with patch('analyze_s4_results_simple.generate_figures') as mock_figures:
                            with patch('analyze_s4_results_simple.generate_report') as mock_report:
                                # Mock sys.argv
                                old_argv = sys.argv
                                try:
                                    sys.argv = ["analyze_s4_results_simple.py", "--csv", str(csv_path), "--output", "output"]
                                    main()
                                finally:
                                    sys.argv = old_argv
                
                # Verify all functions were called
                assert mock_load.called
                assert mock_create.called
                assert mock_tables.called
                assert mock_figures.called
                assert mock_report.called
        finally:
            os.chdir(old_cwd)
