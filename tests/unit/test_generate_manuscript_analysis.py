"""
Unit tests for generate_manuscript_analysis.py
Tests the manuscript analysis generation script.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.generate_manuscript_analysis import (
    load_run_data,
    create_comparison_table,
    create_boxplot,
    create_violin_plot,
    create_cdf_plot,
    create_concurrency_scaling_plot,
    create_statistical_summary,
    create_event_count_table,
    create_latency_decomposition,
    main,
)


class TestLoadRunData:
    """Tests for load_run_data function."""

    def test_load_run_data_basic(self, temp_dir):
        """Test basic data loading from run directories."""
        # Create a sample run directory with s2_ prefix to match scenario detection
        run_dir = temp_dir / "s2_kafka_rep1_20260612_120000"
        run_dir.mkdir()
        
        # Create meta.json
        meta = {
            "run_id": "s2_kafka_rep1_20260612_120000",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Create tti_summary.json
        tti_data = {
            "tti_ms_p50": 50.0,
            "tti_ms_p95": 150.0,
            "tti_ms_p99": 250.0,
            "tti_ms_max": 300.0,
            "tti_ms_mean": 60.0,
            "tti_ms_std": 20.0,
            "tti_ms_min": 10.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["run_id"] == "s2_kafka_rep1_20260612_120000"
        assert df.iloc[0]["backend"] == "kafka"
        assert df.iloc[0]["scenario"] == "s2"

    def test_load_run_data_nested_tti(self, temp_dir):
        """Test loading nested TTI data structure (S2 format)."""
        run_dir = temp_dir / "test_run_002"
        run_dir.mkdir()
        
        meta = {"run_id": "test_run_002", "backend": "redis", "plan_csv": "data/test.csv"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Nested structure
        tti_data = {
            "tti_ms": {
                "p50": 50.0,
                "p95": 150.0,
                "p99": 250.0,
                "max": 300.0
            },
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["tti_ms_p50"] == 50.0
        assert df.iloc[0]["tti_ms_p95"] == 150.0

    def test_load_run_data_multiple_runs(self, temp_dir):
        """Test loading data from multiple run directories."""
        runs = []
        for i in range(3):
            run_dir = temp_dir / f"test_run_{i:03d}"
            run_dir.mkdir()
            
            meta = {
                "run_id": f"test_run_{i:03d}",
                "backend": "kafka" if i % 2 == 0 else "redis",
                "plan_csv": "data/test.csv"
            }
            with open(run_dir / "meta.json", 'w') as f:
                json.dump(meta, f)
            
            tti_data = {
                "tti_ms_p50": 50.0 + i * 10,
                "n_producer": 1000,
                "n_consumer": 1000,
                "n_matched": 1000
            }
            with open(run_dir / "tti_summary.json", 'w') as f:
                json.dump(tti_data, f)
            
            runs.append(run_dir)
        
        df = load_run_data(runs)
        
        assert len(df) == 3

    def test_load_run_data_concurrency_scenario(self, temp_dir):
        """Test loading concurrency scenario data."""
        run_dir = temp_dir / "concurrency_n5_20260612_120000_kafka_feed1_rep1"
        run_dir.mkdir()
        
        meta = {
            "run_id": "concurrency_n5_20260612_120000_kafka_feed1_rep1",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {
            "tti_ms_p50": 50.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["scenario"] == "concurrency"
        assert df.iloc[0]["concurrency"] == 5

    def test_load_run_data_s3_scenario(self, temp_dir):
        """Test loading S3 scenario data."""
        run_dir = temp_dir / "s3_kafka_rep1_20260612_120000"
        run_dir.mkdir()
        
        meta = {
            "run_id": "s3_kafka_rep1_20260612_120000",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {
            "tti_ms_p50": 50.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["scenario"] == "s3"

    def test_load_run_data_s3_no_underscore(self, temp_dir):
        """Test loading S3 scenario without underscore in run_id."""
        run_dir = temp_dir / "s3kafka"
        run_dir.mkdir()
        
        meta = {
            "run_id": "s3kafka",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {
            "tti_ms_p50": 50.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["scenario"] == "s3"

    def test_load_run_data_concurrency_invalid_number(self, temp_dir):
        """Test loading concurrency with invalid number in name."""
        run_dir = temp_dir / "concurrency_ninvalid_kafka_feed1"
        run_dir.mkdir()
        
        meta = {
            "run_id": "concurrency_ninvalid_kafka_feed1",
            "backend": "kafka",
            "plan_csv": "data/test.csv"
        }
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {
            "tti_ms_p50": 50.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        
        assert len(df) == 1
        assert df.iloc[0]["scenario"] == "concurrency"
        # concurrency should be None because 'ninvalid' can't be parsed as int
        assert df.iloc[0]["concurrency"] is None or pd.isna(df.iloc[0]["concurrency"])

    def test_load_run_data_missing_files(self, temp_dir):
        """Test loading with missing files."""
        run_dir = temp_dir / "test_run_empty"
        run_dir.mkdir()
        
        # Only create meta.json, no tti_summary.json
        meta = {"run_id": "test_run_empty", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        df = load_run_data([run_dir])
        
        # Should skip the run without tti_summary.json
        assert len(df) == 0

    def test_load_run_data_missing_tti_file_explicitly(self, temp_dir):
        """Test loading when tti_summary.json is missing (explicit test for line 60 coverage)."""
        run_dir = temp_dir / "test_run_no_tti"
        run_dir.mkdir()
        
        # Only create meta.json, no tti_summary.json
        meta = {"run_id": "test_run_no_tti", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Verify tti_file doesn't exist
        tti_file = run_dir / "tti_summary.json"
        assert not tti_file.exists()
        
        df = load_run_data([run_dir])
        
        # Should skip the run without tti_summary.json
        assert len(df) == 0

    def test_load_run_data_empty_directory(self, temp_dir):
        """Test loading with no runs."""
        df = load_run_data([])
        
        assert len(df) == 0
        assert isinstance(df, pd.DataFrame)

    def test_load_run_data_json_decode_error(self, temp_dir):
        """Test loading with invalid JSON in tti_summary.json."""
        run_dir = temp_dir / "test_run_invalid_json"
        run_dir.mkdir()
        
        meta = {"run_id": "test_run_invalid_json", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Create invalid JSON in tti_summary.json
        with open(run_dir / "tti_summary.json", 'w') as f:
            f.write("{invalid json}")
        
        # Should skip this run due to JSON decode error
        df = load_run_data([run_dir])
        assert len(df) == 0

    def test_load_run_data_ioerror(self, temp_dir):
        """Test loading with IOError on tti_summary.json."""
        run_dir = temp_dir / "test_run_ioerror"
        run_dir.mkdir()
        
        meta = {"run_id": "test_run_ioerror", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Create a directory instead of a file to trigger IOError
        tti_dir = run_dir / "tti_summary.json"
        tti_dir.mkdir()
        
        # Should skip this run due to IOError
        df = load_run_data([run_dir])
        assert len(df) == 0

    def test_load_run_data_meta_json_decode_error(self, temp_dir):
        """Test loading with invalid JSON in meta.json."""
        run_dir = temp_dir / "test_run_meta_invalid"
        run_dir.mkdir()
        
        # Create invalid JSON in meta.json
        with open(run_dir / "meta.json", 'w') as f:
            f.write("{invalid json}")
        
        tti_data = {"tti_ms_p50": 50.0, "n_producer": 1000, "n_consumer": 1000, "n_matched": 1000}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Should still load with unknown backend
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]["backend"] == "unknown"

    def test_load_run_data_encoding_utf8_sig(self, temp_dir):
        """Test loading with UTF-8-sig encoding."""
        run_dir = temp_dir / "s2_kafka_test"
        run_dir.mkdir()
        
        meta = {"run_id": "s2_kafka_test", "backend": "kafka", "plan_csv": "data/test.csv"}
        # Write with UTF-8-sig BOM
        with open(run_dir / "meta.json", 'w', encoding='utf-8-sig') as f:
            json.dump(meta, f)
        
        tti_data = {"tti_ms_p50": 50.0, "n_producer": 1000, "n_consumer": 1000, "n_matched": 1000}
        with open(run_dir / "tti_summary.json", 'w', encoding='utf-8-sig') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]["backend"] == "kafka"

    def test_load_run_data_transport_latency_nested(self, temp_dir):
        """Test loading transport latency from nested structure (line 140 coverage)."""
        run_dir = temp_dir / "s2_kafka_test"
        run_dir.mkdir()
        
        meta = {"run_id": "s2_kafka_test", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        # Nested transport latency structure
        tti_data = {
            "tti_ms_p50": 50.0,
            "transport_ms": {"p50": 30.0},
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        df = load_run_data([run_dir])
        assert len(df) == 1
        assert df.iloc[0]["transport_latency_ms_p50"] == 30.0


class TestCreateComparisonTable:
    """Tests for create_comparison_table function."""

    def test_create_comparison_table_basic(self, temp_dir):
        """Test basic comparison table creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "scenario": ["s2", "s2", "s2", "s2"],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0],
            "tti_ms_p95": [150.0, 160.0, 140.0, 145.0],
            "tti_ms_p99": [250.0, 260.0, 240.0, 245.0],
            "n_matched": [1000, 1000, 1000, 1000]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_comparison_table(df, output_dir)
        
        # Check files were created
        assert (output_dir / "comparison_table.csv").exists()
        assert (output_dir / "comparison_table.md").exists()
        assert (output_dir / "comparison_table.tex").exists()

    def test_create_comparison_table_empty_df(self, temp_dir):
        """Test comparison table with DataFrame that has no matching scenarios."""
        df = pd.DataFrame({
            "run_id": [],
            "backend": [],
            "scenario": [],
            "tti_ms_p50": []
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_comparison_table(df, output_dir)
        
        # Should handle empty gracefully
        # Files may or may not be created depending on implementation

    def test_create_comparison_table_empty_backend_df(self, temp_dir):
        """Test comparison table when backend_df is empty (line 163 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "scenario": ["s2"],
            "tti_ms_p50": [50.0],
            "tti_ms_p95": [150.0],
            "tti_ms_p99": [250.0],
            "n_matched": [1000]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_comparison_table(df, output_dir)

    def test_create_comparison_table_no_matching_scenarios(self, temp_dir):
        """Test comparison table with no matching scenarios."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "scenario": ["unknown_scenario"],
            "tti_ms_p50": [50.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_comparison_table(df, output_dir)
        
        # Should handle gracefully without matching scenarios


class TestCreateBoxplot:
    """Tests for create_boxplot function."""

    def test_create_boxplot_basic(self, temp_dir):
        """Test basic box plot creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "scenario": ["s2", "s2", "s2", "s2"],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_boxplot(df, output_dir)
            
            # Should have called savefig
            assert mock_plt.savefig.called

    def test_create_boxplot_empty_df(self, temp_dir):
        """Test box plot with DataFrame that has no data."""
        df = pd.DataFrame({
            "run_id": [],
            "backend": [],
            "scenario": [],
            "tti_ms_p50": []
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_boxplot(df, output_dir)
        
        # Should handle empty gracefully


class TestCreateViolinPlot:
    """Tests for create_violin_plot function."""

    def test_create_violin_plot_basic(self, temp_dir):
        """Test basic violin plot creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "scenario": ["s2", "s2", "s2", "s2"],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_violin_plot(df, output_dir)
            
            # Should have called savefig
            assert mock_plt.savefig.called

    def test_create_violin_plot_empty_df(self, temp_dir):
        """Test violin plot with DataFrame that has no data."""
        df = pd.DataFrame({
            "run_id": [],
            "backend": [],
            "scenario": [],
            "tti_ms_p50": []
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_violin_plot(df, output_dir)
        
        # Should handle empty gracefully

    def test_create_violin_plot_no_positions(self, temp_dir):
        """Test violin plot when no positions data (lines 387-388 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["other"],
            "scenario": ["s2"],
            "tti_ms_p50": [50.0]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_violin_plot(df, output_dir)


class TestCreateCDFPlot:
    """Tests for create_cdf_plot function."""

    def test_create_cdf_plot_basic(self, temp_dir):
        """Test basic CDF plot creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_cdf_plot(df, output_dir)
            
            # Should have called savefig
            assert mock_plt.savefig.called

    def test_create_cdf_plot_empty_df(self, temp_dir):
        """Test CDF plot with empty DataFrame (lines 492-493 coverage)."""
        df = pd.DataFrame({
            "run_id": [],
            "backend": [],
            "tti_ms_p50": []
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_cdf_plot(df, output_dir)

    def test_create_cdf_plot_empty_backend_df(self, temp_dir):
        """Test CDF plot when backend_df is empty (line 500 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["other"],
            "tti_ms_p50": [50.0]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_cdf_plot(df, output_dir)


class TestCreateConcurrencyScalingPlot:
    """Tests for create_concurrency_scaling_plot function."""

    def test_create_scaling_plot_basic(self, temp_dir):
        """Test basic concurrency scaling plot creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "concurrency": [1, 5, 1, 5],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0],
            "tti_ms_p95": [150.0, 160.0, 140.0, 145.0],
            "tti_ms_p99": [250.0, 260.0, 240.0, 245.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_concurrency_scaling_plot(df, output_dir)
            
            # Should have called savefig at least twice (p50 and p95)
            assert mock_plt.savefig.call_count >= 2

    def test_create_scaling_plot_no_concurrency(self, temp_dir):
        """Test scaling plot with no concurrency data."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "concurrency": [None],
            "tti_ms_p50": [50.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_concurrency_scaling_plot(df, output_dir)
        
        # Should handle missing concurrency gracefully

    def test_create_scaling_plot_empty_backend_data_p50(self, temp_dir):
        """Test scaling plot when backend_data is empty for p50 (line 296 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["other"],
            "concurrency": [5],
            "tti_ms_p50": [50.0],
            "tti_ms_p95": [150.0],
            "tti_ms_p99": [250.0]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_concurrency_scaling_plot(df, output_dir)

    def test_create_scaling_plot_empty_backend_data_p95(self, temp_dir):
        """Test scaling plot when backend_data is empty for p95 (line 327 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "concurrency": [5],
            "tti_ms_p50": [50.0],
            "tti_ms_p95": [150.0],
            "tti_ms_p99": [250.0]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_concurrency_scaling_plot(df, output_dir)


class TestCreateStatisticalSummary:
    """Tests for create_statistical_summary function."""

    def test_create_statistical_summary_basic(self, temp_dir):
        """Test basic statistical summary creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "scenario": ["s2", "s2", "s2", "s2"],
            "tti_ms_p50": [50.0, 55.0, 45.0, 48.0],
            "tti_ms_p95": [150.0, 160.0, 140.0, 145.0],
            "tti_ms_p99": [250.0, 260.0, 240.0, 245.0],
            "n_matched": [1000, 1000, 1000, 1000]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_statistical_summary(df, output_dir)
        
        # Check files were created
        assert (output_dir / "statistical_summary.csv").exists()
        assert (output_dir / "statistical_summary.md").exists()


class TestCreateEventCountTable:
    """Tests for create_event_count_table function."""

    def test_create_event_count_table_basic(self, temp_dir):
        """Test basic event count table creation."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2", "run3", "run4"],
            "backend": ["kafka", "kafka", "redis", "redis"],
            "scenario": ["s2", "s2", "s2", "s2"],
            "n_producer": [1000, 1000, 1000, 1000],
            "n_consumer": [1000, 1000, 1000, 1000],
            "n_matched": [1000, 1000, 1000, 1000]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_event_count_table(df, output_dir)
        
        # Check files were created
        assert (output_dir / "event_counts.csv").exists()
        assert (output_dir / "event_counts.md").exists()


class TestCreateLatencyDecomposition:
    """Tests for create_latency_decomposition function."""

    def test_create_latency_decomposition_with_data(self, temp_dir):
        """Test latency decomposition with transport data."""
        df = pd.DataFrame({
            "run_id": ["run1", "run2"],
            "backend": ["kafka", "redis"],
            "tti_ms_p50": [100.0, 90.0],
            "transport_latency_ms_p50": [60.0, 50.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        with patch('scripts.generate_manuscript_analysis.plt') as mock_plt:
            create_latency_decomposition(df, output_dir)
            
            # Should have called savefig
            assert mock_plt.savefig.called

    def test_create_latency_decomposition_no_transport_data(self, temp_dir):
        """Test latency decomposition without transport data."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "tti_ms_p50": [100.0]
        })
        
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_latency_decomposition(df, output_dir)
        
        # Should handle missing transport data gracefully

    def test_create_latency_decomposition_empty_df(self, temp_dir):
        """Test latency decomposition with empty df after filtering (lines 531-532 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["kafka"],
            "tti_ms_p50": [None],
            "transport_latency_ms_p50": [None]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_latency_decomposition(df, output_dir)

    def test_create_latency_decomposition_empty_backend_df(self, temp_dir):
        """Test latency decomposition when backend_df is empty (line 539 coverage)."""
        df = pd.DataFrame({
            "run_id": ["run1"],
            "backend": ["other"],
            "tti_ms_p50": [100.0],
            "transport_latency_ms_p50": [60.0]
        })
        output_dir = temp_dir / "output"
        output_dir.mkdir()
        
        create_latency_decomposition(df, output_dir)


class TestMain:
    """Tests for main function."""

    def test_main_no_args(self, temp_dir):
        """Test main with no arguments (uses defaults)."""
        # Create a sample run directory
        run_dir = temp_dir / "runs" / "test_run_001"
        run_dir.mkdir(parents=True)
        
        meta = {"run_id": "test_run_001", "backend": "kafka", "plan_csv": "data/test.csv"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {
            "tti_ms_p50": 50.0,
            "tti_ms_p95": 150.0,
            "tti_ms_p99": 250.0,
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 1000
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        # Change to temp dir and run with default runs-dir
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            with patch('sys.argv', ['generate_manuscript_analysis.py', '--runs-dir', 'runs']):
                with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                    mock_load.return_value = pd.DataFrame({
                        "run_id": ["test_run_001"],
                        "backend": ["kafka"],
                        "scenario": ["s2"],
                        "concurrency": [None],
                        "tti_ms_p50": [50.0],
                        "tti_ms_p95": [150.0],
                        "tti_ms_p99": [250.0],
                        "n_producer": [1000],
                        "n_consumer": [1000],
                        "n_matched": [1000]
                    })
                    
                    with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                        with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                            with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                    with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                        with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                            with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                                with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                    try:
                                                        main()
                                                    except SystemExit:
                                                        pass
        finally:
            os.chdir(original_cwd)

    def test_main_with_run_list(self, temp_dir):
        """Test main with run list file."""
        # Create run list file
        run_list_file = temp_dir / "run_list.txt"
        run_list_file.write_text("runs/test_run_001")
        
        with patch('sys.argv', ['generate_manuscript_analysis.py', '--run-list', str(run_list_file)]):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame({
                    "run_id": ["test_run_001"],
                    "backend": ["kafka"],
                    "scenario": ["s2"],
                    "concurrency": [None],
                    "tti_ms_p50": [50.0],
                    "tti_ms_p95": [150.0],
                    "tti_ms_p99": [250.0],
                    "n_producer": [1000],
                    "n_consumer": [1000],
                    "n_matched": [1000]
                })
                
                with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                    with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                        with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                            with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                    with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                        with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                            with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                try:
                                                    main()
                                                except SystemExit:
                                                    pass

    def test_main_with_concurrency_output(self, temp_dir, capsys):
        """Test main prints concurrency levels (line 688 coverage)."""
        with patch('sys.argv', ['generate_manuscript_analysis.py', '--runs-dir', 'runs']):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame({
                    "run_id": ["test_run_001"],
                    "backend": ["kafka"],
                    "scenario": ["s2"],
                    "concurrency": [5],
                    "tti_ms_p50": [50.0],
                    "tti_ms_p95": [150.0],
                    "tti_ms_p99": [250.0],
                    "n_producer": [1000],
                    "n_consumer": [1000],
                    "n_matched": [1000]
                })
                
                with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                    with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                        with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                            with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                    with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                        with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                            with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                try:
                                                    main()
                                                except SystemExit:
                                                    pass
        captured = capsys.readouterr()
        assert "Concurrency levels:" in captured.out

    def test_main_entry_point(self, temp_dir):
        """Test main entry point (line 692 coverage)."""
        with patch('sys.argv', ['generate_manuscript_analysis.py', '--runs-dir', 'runs']):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame({
                    "run_id": ["test_run_001"],
                    "backend": ["kafka"],
                    "scenario": ["s2"],
                    "concurrency": [None],
                    "tti_ms_p50": [50.0],
                    "tti_ms_p95": [150.0],
                    "tti_ms_p99": [250.0],
                    "n_producer": [1000],
                    "n_consumer": [1000],
                    "n_matched": [1000]
                })
                
                with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                    with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                        with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                            with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                    with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                        with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                            with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                try:
                                                    main()
                                                except SystemExit:
                                                    pass

    def test_main_with_scenarios_filter(self, temp_dir):
        """Test main with scenarios filter."""
        with patch('sys.argv', [
            'generate_manuscript_analysis.py',
            '--runs-dir', 'runs',
            '--scenarios', 's2', 'concurrency'
        ]):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame({
                    "run_id": ["test_run_001"],
                    "backend": ["kafka"],
                    "scenario": ["s2"],
                    "concurrency": [None],
                    "tti_ms_p50": [50.0],
                    "tti_ms_p95": [150.0],
                    "tti_ms_p99": [250.0],
                    "n_producer": [1000],
                    "n_consumer": [1000],
                    "n_matched": [1000]
                })
                
                with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                    with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                        with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                            with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                    with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                        with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                            with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                try:
                                                    main()
                                                except SystemExit:
                                                    pass

    def test_main_empty_data(self, temp_dir):
        """Test main with empty data."""
        with patch('sys.argv', ['generate_manuscript_analysis.py', '--runs-dir', 'runs']):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame()
                
                with pytest.raises(SystemExit) as exc_info:
                    main()
                
                # Should exit with code 1 for empty data
                assert exc_info.value.code == 1

    def test_main_creates_output_directory(self, temp_dir):
        """Test that main creates output directory."""
        with patch('sys.argv', ['generate_manuscript_analysis.py', '--runs-dir', 'runs']):
            with patch('scripts.generate_manuscript_analysis.load_run_data') as mock_load:
                mock_load.return_value = pd.DataFrame({
                    "run_id": ["test_run_001"],
                    "backend": ["kafka"],
                    "scenario": ["s2"],
                    "concurrency": [None],
                    "tti_ms_p50": [50.0],
                    "tti_ms_p95": [150.0],
                    "tti_ms_p99": [250.0],
                    "n_producer": [1000],
                    "n_consumer": [1000],
                    "n_matched": [1000]
                })
                
                with patch('scripts.generate_manuscript_analysis.Path') as mock_path:
                    # Mock the Path to return different things for different calls
                    mock_output_dir = MagicMock()
                    mock_output_dir.exists.return_value = False
                    
                    # First call is for output_dir, second is for runs_dir
                    mock_path.side_effect = [mock_output_dir, Path(temp_dir) / "runs"]
                    
                    with patch('scripts.generate_manuscript_analysis.create_comparison_table'):
                        with patch('scripts.generate_manuscript_analysis.create_boxplot'):
                            with patch('scripts.generate_manuscript_analysis.create_violin_plot'):
                                with patch('scripts.generate_manuscript_analysis.create_cdf_plot'):
                                    with patch('scripts.generate_manuscript_analysis.create_statistical_summary'):
                                        with patch('scripts.generate_manuscript_analysis.create_event_count_table'):
                                            with patch('scripts.generate_manuscript_analysis.create_concurrency_scaling_plot'):
                                                with patch('scripts.generate_manuscript_analysis.create_latency_decomposition'):
                                                    try:
                                                        main()
                                                    except SystemExit:
                                                        pass
                    
                    # Check mkdir was called on the output directory
                    mock_output_dir.mkdir.assert_called()

    def test_main_with_invalid_run_list_encoding(self, temp_dir):
        """Test main with invalid run list encoding (lines 618-619, 622-623 coverage)."""
        # Create run list file with invalid encoding
        run_list_file = temp_dir / "run_list.txt"
        # Write invalid binary data
        run_list_file.write_bytes(b'\xff\xfe\x00\x01invalid')
        
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            with patch('sys.argv', ['generate_manuscript_analysis.py', '--run-list', str(run_list_file)]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 1
        finally:
            os.chdir(original_cwd)

    def test_main_with_run_list_non_runs_path(self, temp_dir):
        """Test main with run list containing non-runs path (line 636 coverage)."""
        # Create run list file
        run_list_file = temp_dir / "run_list.txt"
        run_list_file.write_text("other/test_run_001")
        
        # Create the actual run directory
        run_dir = temp_dir / "runs" / "test_run_001"
        run_dir.mkdir(parents=True)
        
        meta = {"run_id": "test_run_001", "backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta, f)
        
        tti_data = {"tti_ms_p50": 50.0, "n_producer": 1000, "n_consumer": 1000, "n_matched": 1000}
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)
        
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            with patch('sys.argv', ['generate_manuscript_analysis.py', '--run-list', str(run_list_file), '--runs-dir', 'runs']):
                try:
                    main()
                except SystemExit:
                    pass
        finally:
            os.chdir(original_cwd)


# Parametrized tests

@pytest.mark.parametrize("scenario", ["s2", "s2full", "s2sf12", "s2sf12j2", "concurrency"])
def test_load_run_data_various_scenarios(scenario, temp_dir):
    """Parametrized test for various scenario types."""
    run_dir = temp_dir / f"{scenario}_kafka_rep1_20260612_120000"
    run_dir.mkdir()
    
    meta = {
        "run_id": f"{scenario}_kafka_rep1_20260612_120000",
        "backend": "kafka",
        "plan_csv": "data/test.csv"
    }
    with open(run_dir / "meta.json", 'w') as f:
        json.dump(meta, f)
    
    tti_data = {
        "tti_ms_p50": 50.0,
        "n_producer": 1000,
        "n_consumer": 1000,
        "n_matched": 1000
    }
    with open(run_dir / "tti_summary.json", 'w') as f:
        json.dump(tti_data, f)
    
    df = load_run_data([run_dir])
    
    assert len(df) == 1
    if scenario == "concurrency":
        assert df.iloc[0]["scenario"] == "concurrency"
    else:
        assert df.iloc[0]["scenario"] == scenario
