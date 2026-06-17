"""Backup of the original test file."""
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

from analyze_concurrency_sweep import (
    get_scenario,
    load_run_data,
    discover_runs,
    filter_handoff,
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
        # Create test directories
        valid_dirs = [
            "concurrency_n5_20260101_001322_kafka_feed1_rep1",
            "concurrency_n10_20260101_001416_redis_feed1_rep1",
            "concurrency_n20_20260102_001522_kafka_feed2_rep1",
        ]
        for dirname in valid_dirs:
            (temp_dir / dirname).mkdir()

        # Create invalid directories
        invalid_dirs = [
            "invalid_dir",
            "concurrency_n5",  # Too short
            "other_n5_20260101_001322_kafka_feed1_rep1",  # Wrong prefix
        ]
        for dirname in invalid_dirs:
            (temp_dir / dirname).mkdir()

        result = discover_runs(temp_dir)
        assert len(result) == 3
        assert all(r.name.startswith('concurrency_n') for r in result)

    def test_discover_empty_directory(self, temp_dir):
        result = discover_runs(temp_dir)
        assert len(result) == 0

    def test_discover_no_matching_pattern(self, temp_dir):
        # Create directories that don't match pattern
        (temp_dir / "test_dir").mkdir()
        (temp_dir / "runs").mkdir()

        result = discover_runs(temp_dir)
        assert len(result) == 0


class TestFilterHandoff:
    """Tests for filter_handoff function."""

    def test_filter_with_handoff_prefixes(self, temp_dir):
        # Create paths with handoff prefixes
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
        # Create paths without handoff prefixes
        non_handoff_dirs = [
            temp_dir / "concurrency_n5_20260101_999999_kafka_feed1_rep1",
            temp_dir / "concurrency_n10_20260101_888888_redis_feed1_rep1",
        ]
        for d in non_handoff_dirs:
            d.mkdir(parents=True)

        result = filter_handoff(non_handoff_dirs)
        assert len(result) == 0

    def test_filter_mixed_prefixes(self, temp_dir):
        # Create mix of handoff and non-handoff
        all_dirs = [
            temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1",  # handoff
            temp_dir / "concurrency_n10_20260101_999999_kafka_feed1_rep1",  # not handoff
            temp_dir / "concurrency_n20_20260102_001416_redis_feed2_rep1",  # handoff
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

        # Create tti_summary.json
        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0, "p99": 300.0, "max": 500.0, "mean": 150.0},
            "n_producer": 1000,
            "n_consumer": 1000,
            "n_matched": 999
        }
        with open(run_dir / "tti_summary.json", 'w') as f:
            json.dump(tti_data, f)

        # Create meta.json
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

        # Create only meta.json
        meta_data = {"backend": "kafka"}
        with open(run_dir / "meta.json", 'w') as f:
            json.dump(meta_data, f)

        df = load_run_data([run_dir])
        assert len(df) == 0

    def test_load_missing_meta_file(self, temp_dir):
        run_dir = temp_dir / "concurrency_n5_20260101_001322_kafka_feed1_rep1"
        run_dir.mkdir()

        # Create only tti_summary.json
        tti_data = {
            "tti_ms": {"p50": 100.0, "p95": 200.0}
        }
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

        # Create tti_summary.json with flat structure
        tti_data = {
            "tti_ms_p50": 100.0,
            "tti_ms_p95": 200.0,
            "n_produced": 1000,
            "n_consumed": 1000,
        }
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

        # Create corrupted tti_summary.json
        with open(run_dir / "tti_summary.json", 'w') as f:
            f.write("invalid json")

        df = load_run_data([run_dir])
        assert len(df) == 0