"""Tests for deep_health_check_final.py (repo-root health-check script) - target >=95%."""
import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT))

from deep_health_check_final import _count_data_rows, verify_run_deep, main


def _complete_run(run_dir, n_prod=100, n_cons=100, backend="kafka", p50=10.0, max_tti=50.0):
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "meta.json", "w") as f:
        json.dump({"run_id": run_dir.name, "backend": backend}, f)
    with open(run_dir / "tti_summary.json", "w") as f:
        json.dump({"n_matched": min(n_prod, n_cons),
                   "tti_ms": {"p50": p50, "max": max_tti}}, f)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n_prod)]}).to_csv(run_dir / "producer.csv", index=False)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n_cons)]}).to_csv(run_dir / "consumer.csv", index=False)
    return run_dir


class TestCountDataRows:
    def test_counts_excluding_header(self, temp_dir):
        p = temp_dir / "f.csv"
        pd.DataFrame({"a": [1, 2, 3]}).to_csv(p, index=False)
        assert _count_data_rows(p) == 3


class TestVerifyRunDeep:
    def test_healthy(self, temp_dir):
        ok, errors, warnings = verify_run_deep(_complete_run(temp_dir / "good"))
        assert ok and errors == []

    def test_missing_files(self, temp_dir):
        (temp_dir / "empty").mkdir()
        ok, errors, _ = verify_run_deep(temp_dir / "empty")
        assert not ok and errors

    def test_backend_inferred_from_name(self, temp_dir):
        run = _complete_run(temp_dir / "batch2_redis_cluster_s1", backend="weird")
        ok, errors, _ = verify_run_deep(run)
        # backend not kafka/redis in meta -> inferred from name 'redis'; still valid
        assert ok

    def test_meta_missing_run_id(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "meta.json").write_text(json.dumps({"backend": "kafka"}))
        ok, errors, _ = verify_run_deep(run)
        assert any("run_id" in e for e in errors)

    def test_invalid_meta(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "meta.json").write_text("{bad")
        ok, errors, _ = verify_run_deep(run)
        assert any("meta.json invalid" in e for e in errors)

    def test_negative_median_tti(self, temp_dir):
        run = _complete_run(temp_dir / "r", p50=-5.0)
        ok, errors, _ = verify_run_deep(run)
        assert any("negative median" in e for e in errors)

    def test_max_tti_warning(self, temp_dir):
        run = _complete_run(temp_dir / "r", max_tti=400000.0)
        ok, errors, warnings = verify_run_deep(run)
        assert ok and any("5min" in w for w in warnings)

    def test_zero_matched_warning(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "tti_summary.json").write_text(json.dumps({"n_matched": 0, "tti_ms": {"p50": 1.0}}))
        ok, errors, warnings = verify_run_deep(run)
        assert any("n_matched" in w for w in warnings)

    def test_invalid_tti(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "tti_summary.json").write_text("{bad")
        ok, errors, _ = verify_run_deep(run)
        assert any("tti_summary.json invalid" in e for e in errors)

    def test_count_mismatch_warning(self, temp_dir):
        run = _complete_run(temp_dir / "r", n_prod=100, n_cons=50)
        ok, errors, warnings = verify_run_deep(run)
        assert any("event count mismatch" in w for w in warnings)

    def test_empty_producer_rows(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "producer.csv").write_text("event_id\n")  # header only -> 0 rows
        ok, errors, _ = verify_run_deep(run)
        assert any("no data rows" in e for e in errors)


class TestMain:
    def test_all_pass(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _complete_run(runs / "batch1_a")
        _complete_run(runs / "batch1_b", max_tti=400000.0)  # warning, still passes
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*", "--verbose"])
        assert rc == 0
        assert "with warnings" in capsys.readouterr().out

    def test_failure(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _complete_run(runs / "ok")
        (runs / "bad").mkdir()
        rc = main(["--runs-dir", str(runs), "--verbose"])
        assert rc == 1
        assert "FAIL" in capsys.readouterr().out

    def test_runs_dir_missing(self, temp_dir):
        assert main(["--runs-dir", str(temp_dir / "nope")]) == 1

    def test_no_matching(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--pattern", "zzz*"]) == 1
