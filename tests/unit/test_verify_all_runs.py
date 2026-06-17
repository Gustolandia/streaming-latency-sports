"""Tests for verify_all_runs.py (repo-root health-check script) - target >=95%."""
import json
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT))

from verify_all_runs import verify_run, main, REQUIRED_FILES


def _complete_run(run_dir, prod_rows=5, cons_rows=5):
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "meta.json", "w") as f:
        json.dump({"run_id": run_dir.name, "backend": "kafka"}, f)
    with open(run_dir / "tti_summary.json", "w") as f:
        json.dump({"tti_ms": {"p50": 10.0}}, f)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(prod_rows)]}).to_csv(run_dir / "producer.csv", index=False)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(cons_rows)]}).to_csv(run_dir / "consumer.csv", index=False)
    return run_dir


class TestVerifyRun:
    def test_complete_run_ok(self, temp_dir):
        ok, issues = verify_run(_complete_run(temp_dir / "good"))
        assert ok and issues == []

    def test_missing_files(self, temp_dir):
        (temp_dir / "empty").mkdir()
        ok, issues = verify_run(temp_dir / "empty")
        assert not ok
        assert len(issues) >= len(REQUIRED_FILES)

    def test_empty_file_flagged(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "tti_summary.json").write_text("")  # empty
        ok, issues = verify_run(run)
        assert not ok and any("empty" in i for i in issues)

    def test_invalid_meta_json(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "meta.json").write_text("{bad")
        ok, issues = verify_run(run)
        assert any("meta.json invalid" in i for i in issues)

    def test_meta_missing_run_id(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "meta.json").write_text(json.dumps({"backend": "kafka"}))
        ok, issues = verify_run(run)
        assert any("run_id" in i for i in issues)

    def test_invalid_tti_json(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "tti_summary.json").write_text("{bad")
        ok, issues = verify_run(run)
        assert any("tti_summary.json invalid" in i for i in issues)

    def test_csv_no_data_rows(self, temp_dir):
        run = _complete_run(temp_dir / "r")
        (run / "producer.csv").write_text("event_id\n")  # header only
        ok, issues = verify_run(run)
        assert any("no data rows" in i for i in issues)


class TestMain:
    def test_all_pass(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _complete_run(runs / "batch1_a")
        _complete_run(runs / "batch1_b")
        rc = main(["--runs-dir", str(runs), "--pattern", "batch*"])
        assert rc == 0
        assert "120" not in capsys.readouterr().out  # sanity: not hardcoded

    def test_some_fail_verbose(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _complete_run(runs / "ok")
        (runs / "bad").mkdir()
        rc = main(["--runs-dir", str(runs), "--verbose"])
        assert rc == 1
        assert "FAIL" in capsys.readouterr().out

    def test_runs_dir_missing(self, temp_dir):
        assert main(["--runs-dir", str(temp_dir / "nope")]) == 1

    def test_no_matching_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--pattern", "zzz*"]) == 1
