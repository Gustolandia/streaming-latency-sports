# Pytest Configuration and Fixtures for Streaming Latency Sports
# ================================================================
# 
# Usage:
#   pytest tests/ -v
#   pytest tests/unit/test_compare_plans.py -v
#   pytest tests/ --cov=scripts --cov-report=html

import pytest
import os
from pathlib import Path
import pandas as pd
import numpy as np
import json
import tempfile
import shutil

# Set COVERAGE_PROCESS_START for subprocess coverage
os.environ['COVERAGE_PROCESS_START'] = str(Path(__file__).parent.parent / '.coveragerc')

# Mock external dependencies before any imports
import sys
from unittest.mock import MagicMock

# Import coverage for combining data
def pytest_sessionfinish(session, exitstatus):
    """Combine coverage data after all tests."""
    import coverage
    import glob
    # Combine all .coverage files
    cov = coverage.Coverage()
    cov.combine()
    # Also try to find and combine any .coverage.* files from subprocess
    for coverage_file in glob.glob('.coverage.*'):
        cov.combine([coverage_file])
    cov.save()

sys.modules['kafka'] = MagicMock()
sys.modules['kafka.KafkaProducer'] = MagicMock()
sys.modules['kafka.KafkaConsumer'] = MagicMock()
sys.modules['redis'] = MagicMock()
sys.modules['redis.Redis'] = MagicMock()

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# ============================================================
# PATH CONFIGURATION
# ============================================================

REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DATA_DIR = REPO_ROOT / "data"
TESTS_DIR = REPO_ROOT / "tests"
FIXTURES_DIR = TESTS_DIR / "fixtures"

# Ensure fixtures directory exists
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# PYTEST HOOKS
# ============================================================

def pytest_configure(config):
    """Configure pytest options."""
    config.addinivalue_line("markers", 'slow: marks tests as slow (deselect with \'-m not slow\')')
    config.addinivalue_line("markers", "integration: marks integration tests")
    config.addinivalue_line("markers", "requires_docker: marks tests requiring Docker services")
    config.addinivalue_line("markers", "requires_kafka: marks tests requiring Kafka")
    config.addinivalue_line("markers", "requires_redis: marks tests requiring Redis")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on names."""
    for item in items:
        if "slow" in item.nodeid.lower():
            item.add_marker(pytest.mark.slow)
        if "integration" in item.nodeid.lower():
            item.add_marker(pytest.mark.integration)


# ============================================================
# FIXTURES: FILE SYSTEM
# ============================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_csv_file(temp_dir):
    """Create a temporary CSV file."""
    def _create_csv(data, filename="test.csv"):
        df = pd.DataFrame(data)
        path = temp_dir / filename
        df.to_csv(path, index=False)
        return path
    return _create_csv


@pytest.fixture
def temp_json_file(temp_dir):
    """Create a temporary JSON file."""
    def _create_json(data, filename="test.json"):
        path = temp_dir / filename
        with open(path, "w") as f:
            json.dump(data, f)
        return path
    return _create_json


@pytest.fixture
def sample_replay_plan_csv(temp_dir):
    """Create a sample replay plan CSV for testing."""
    data = {
        "row_idx": [0, 1, 2, 3, 4],
        "match_id": [3895052, 3895052, 3895052, 3895060, 3895060],
        "event_id": ["event_001", "event_002", "event_003", "event_004", "event_005"],
        "t_sim_seconds": [0.0, 0.5, 1.0, 1.5, 2.0],
        "t_emit_offset_s": [0.0, 0.5, 1.0, 1.5, 2.0],
        "event_type": ["Pass", "Shot", "Pass", "Pass", "Pressure"],
    }
    df = pd.DataFrame(data)
    path = temp_dir / "sample_replay_plan.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def sample_consumer_events_csv(temp_dir):
    """Create a sample consumer events CSV for S3 testing."""
    data = [
        {
            "run_id": "test_run_001",
            "backend": "kafka",
            "topic": "sb-events",
            "partition": 0,
            "offset": 1,
            "t_consume_ns": 1000000,
            "event_id": "event_001",
            "match_id": 3895052,
            "t_sim_seconds": 0.0,
            "t_emit_offset_s": 0.0,
            "t_emit_planned_ns": 1000000,
            "s3_uid": "3895052:event_001",
            "s3_rev": 1,
            "s3_is_correction": False,
        },
        {
            "run_id": "test_run_001",
            "backend": "kafka",
            "topic": "sb-events",
            "partition": 0,
            "offset": 2,
            "t_consume_ns": 2000000,
            "event_id": "event_001__rev2",
            "match_id": 3895052,
            "t_sim_seconds": 0.0,
            "t_emit_offset_s": 0.0,
            "t_emit_planned_ns": 3000000,  # Correction emitted later
            "s3_uid": "3895052:event_001",
            "s3_rev": 2,
            "s3_is_correction": True,
        },
    ]
    df = pd.DataFrame(data)
    path = temp_dir / "consumer_events.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def sample_tti_summary_json(temp_dir):
    """Create a sample TTI summary JSON."""
    data = {
        "run_id": "test_run_001",
        "n_produced": 1000,
        "n_consumed": 1000,
        "n_matched": 1000,
        "tti_ms": {
            "p50": 50.0,
            "p95": 150.0,
            "p99": 250.0,
            "max": 300.0,
            "mean": 60.0,
            "std": 20.0,
            "min": 10.0,
            "missed_window_rate": {
                "100": 0.1,
                "250": 0.05,
                "500": 0.01,
                "1000": 0.0,
            },
        },
        "transport_ms": {
            "p50": 20.0,
            "p95": 40.0,
            "p99": 60.0,
            "max": 80.0,
        },
        "producer_sched_lag_ms": {
            "p50": 2.0,
            "p95": 5.0,
            "p99": 10.0,
            "max": 15.0,
        },
    }
    path = temp_dir / "tti_summary.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


@pytest.fixture
def sample_meta_json(temp_dir):
    """Create a sample run metadata JSON."""
    data = {
        "run_id": "test_run_001",
        "backend": "kafka",
        "scenario": "s2sf12",
        "plan_csv": "data/processed/replay_plans/test/combined_plan.csv",
        "speedup": 120.0,
        "max_t_sim": 600,
        "git": {
            "head": "abc123def456",
            "dirty": False,
        },
        "env": {
            "python_version": "3.9.13",
            "platform": "Linux",
        },
        "timestamp": "2026-01-01T12:00:00Z",
    }
    path = temp_dir / "meta.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


# ============================================================
# FIXTURES: MOCK DATA
# ============================================================

@pytest.fixture
def mock_replay_plan_df():
    """Create a mock replay plan DataFrame."""
    return pd.DataFrame({
        "row_idx": [0, 1, 2, 3, 4],
        "match_id": [3895052, 3895052, 3895052, 3895060, 3895060],
        "event_id": ["event_001", "event_002", "event_003", "event_004", "event_005"],
        "t_sim_seconds": [0.0, 0.5, 1.0, 1.5, 2.0],
        "t_emit_offset_s": [0.0, 0.5, 1.0, 1.5, 2.0],
        "event_type": ["Pass", "Shot", "Pass", "Pass", "Pressure"],
    })


@pytest.fixture
def mock_consumer_events_df():
    """Create a mock consumer events DataFrame."""
    return pd.DataFrame([
        {
            "run_id": "test_run_001",
            "backend": "kafka",
            "topic": "sb-events",
            "partition": 0,
            "offset": 1,
            "t_consume_ns": 1000000,
            "event_id": "event_001",
            "match_id": 3895052,
            "t_sim_seconds": 0.0,
            "t_emit_offset_s": 0.0,
            "t_emit_planned_ns": 1000000,
            "s3_uid": "3895052:event_001",
            "s3_rev": 1,
            "s3_is_correction": False,
        },
        {
            "run_id": "test_run_001",
            "backend": "kafka",
            "topic": "sb-events",
            "partition": 0,
            "offset": 2,
            "t_consume_ns": 2000000,
            "event_id": "event_001__rev2",
            "match_id": 3895052,
            "t_sim_seconds": 0.0,
            "t_emit_offset_s": 0.0,
            "t_emit_planned_ns": 3000000,
            "s3_uid": "3895052:event_001",
            "s3_rev": 2,
            "s3_is_correction": True,
        },
    ])


# ============================================================
# FIXTURES: SAMPLE PLAN FILES FOR compare_plans.py
# ============================================================

@pytest.fixture
def sample_plan_a_csv(temp_dir):
    """Create sample plan A CSV."""
    data = {
        "row_idx": [0, 1, 2, 3, 4],
        "match_id": [1, 1, 2, 2, 3],
        "event_id": ["e1", "e2", "e3", "e4", "e5"],
        "t_emit_offset_s": [0.0, 1.0, 0.0, 1.0, 0.0],
        "event_type": ["Pass", "Shot", "Pass", "Pressure", "Pass"],
    }
    df = pd.DataFrame(data)
    path = temp_dir / "plan_a.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def sample_plan_b_csv(temp_dir):
    """Create sample plan B CSV."""
    data = {
        "row_idx": [0, 1, 2, 3, 4, 5],
        "match_id": [1, 1, 2, 2, 3, 3],
        "event_id": ["e1", "e2", "e3", "e4", "e5", "e6"],
        "t_emit_offset_s": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
        "event_type": ["Pass", "Shot", "Pass", "Pressure", "Pass", "Shot"],
    }
    df = pd.DataFrame(data)
    path = temp_dir / "plan_b.csv"
    df.to_csv(path, index=False)
    return path


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_sample_run_dir(run_id, temp_dir):
    """Create a sample run directory with all required files."""
    run_dir = temp_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Create meta.json
    meta = {
        "run_id": run_id,
        "backend": "kafka" if "kafka" in run_id else "redis",
        "scenario": "s2sf12",
        "plan_csv": "data/processed/replay_plans/test/combined_plan.csv",
        "speedup": 120.0,
        "max_t_sim": 600,
        "git": {"head": "abc123", "dirty": False},
        "env": {"python_version": "3.9.13"},
        "timestamp": "2026-01-01T12:00:00Z",
    }
    with open(run_dir / "meta.json", "w") as f:
        json.dump(meta, f)
    
    # Create tti_summary.json
    tti_summary = {
        "run_id": run_id,
        "n_produced": 1000,
        "n_consumed": 1000,
        "n_matched": 1000,
        "tti_ms": {"p50": 50.0, "p95": 150.0, "p99": 250.0, "max": 300.0},
        "transport_ms": {"p50": 20.0, "p95": 40.0, "p99": 60.0, "max": 80.0},
        "producer_sched_lag_ms": {"p50": 2.0, "p95": 5.0, "p99": 10.0, "max": 15.0},
    }
    with open(run_dir / "tti_summary.json", "w") as f:
        json.dump(tti_summary, f)
    
    # Create consumer_events.csv
    consumer_data = [
        {"run_id": run_id, "backend": meta["backend"], "event_id": f"event_{i:03d}", 
         "t_consume_ns": 1000000 * (i + 1)} for i in range(100)
    ]
    pd.DataFrame(consumer_data).to_csv(run_dir / "consumer_events.csv", index=False)
    
    return run_dir


# ============================================================
# MARKERS FOR CONDITIONAL TEST EXECUTION
# ============================================================

requires_docker = pytest.mark.skipif(
    not shutil.which("docker"),
    reason="Docker not available"
)

requires_kafka = pytest.mark.skipif(
    not shutil.which("kafka-topics"),
    reason="Kafka not available"
)

requires_redis = pytest.mark.skipif(
    not shutil.which("redis-cli"),
    reason="Redis not available"
)
