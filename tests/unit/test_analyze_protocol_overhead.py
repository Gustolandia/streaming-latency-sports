"""Tests for scripts/analyze_protocol_overhead.py - target >=95% coverage."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_protocol_overhead import (
    event_payload,
    measure_event,
    _agg,
    analyze_run,
    main,
)


class TestEventPayload:
    def test_builds_from_known_cols(self):
        row = {"event_id": "e1", "match_id": 100, "t_sim_seconds": 1.5, "extra": "ignored"}
        payload = event_payload(row)
        assert payload["event_id"] == "e1"
        assert payload["match_id"] == 100
        assert "extra" not in payload

    def test_skips_nan(self):
        row = {"event_id": "e1", "match_id": np.nan}
        payload = event_payload(row)
        assert "match_id" not in payload

    def test_custom_columns(self):
        row = {"event_id": "e1", "match_id": 1}
        payload = event_payload(row, columns=["event_id"])
        assert payload == {"event_id": "e1"}


class TestMeasureEvent:
    def test_returns_metrics(self):
        m = measure_event({"event_id": "e1", "match_id": 1}, iterations=3)
        assert m["size_bytes"] > 0
        assert m["serialize_ns"] >= 0
        assert m["deserialize_ns"] >= 0

    def test_zero_iterations_clamped(self):
        m = measure_event({"a": 1}, iterations=0)
        assert m["size_bytes"] > 0


class TestAgg:
    def test_empty(self):
        a = _agg([])
        assert np.isnan(a["p50"]) and np.isnan(a["mean"])

    def test_values(self):
        a = _agg([1, 2, 3, 4])
        assert a["mean"] == 2.5
        assert a["p50"] == 2.5


def _write_producer(run_dir, n=5):
    run_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "event_id": [f"e{i}" for i in range(n)],
        "match_id": [100 + i for i in range(n)],
        "t_sim_seconds": [float(i) for i in range(n)],
        "t_prod_sched_ns": [1000 * i for i in range(n)],
    })
    df.to_csv(run_dir / "producer.csv", index=False)


class TestAnalyzeRun:
    def test_basic(self, temp_dir):
        run = temp_dir / "batch1_kafka_single_s1_n5_rep1"
        _write_producer(run, 5)
        res = analyze_run(run / "producer.csv", iterations=2)
        assert res["n_events"] == 5
        assert res["message_size_bytes"]["p50"] > 0

    def test_missing_file(self, temp_dir):
        assert analyze_run(temp_dir / "nope.csv") is None

    def test_empty_csv(self, temp_dir):
        p = temp_dir / "empty.csv"
        pd.DataFrame({"event_id": []}).to_csv(p, index=False)
        assert analyze_run(p) is None

    def test_malformed_csv(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_bytes(b"\xff\xfe not, a; valid\x00csv")
        # pandas may parse or raise; either way must not crash
        res = analyze_run(p)
        assert res is None or "n_events" in res

    def test_sample_limit(self, temp_dir):
        run = temp_dir / "batch1_redis_single_s1_n5_rep1"
        _write_producer(run, 20)
        res = analyze_run(run / "producer.csv", iterations=2, sample=5)
        assert res["n_events"] == 5


class TestMain:
    def test_main_writes(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _write_producer(runs / "batch1_kafka_single_s1_n5_rep1", 4)
        _write_producer(runs / "batch1_redis_single_s1_n5_rep1", 4)
        out = temp_dir / "out"
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*",
                   "--iterations", "2", "--out", str(out)])
        assert rc == 0
        assert (out / "protocol_overhead_by_run.csv").exists()
        assert (out / "protocol_overhead_by_backend.csv").exists()

    def test_main_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*"])
        assert rc == 1
