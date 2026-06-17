"""Tests for scripts/verify_reproducibility.py - target >=95% coverage."""
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from verify_reproducibility import check_meta, verify_run, main


GOOD_META = {
    "run_id": "batch1_kafka_single_s1_n5_rep1",
    "git": {"head": "abc123"},
    "code_sha256": {"scripts/kafka_producer.py": "deadbeef"},
}


class TestCheckMeta:
    def test_complete(self):
        assert check_meta(GOOD_META) == []

    def test_missing_top_field(self):
        m = dict(GOOD_META)
        del m["code_sha256"]
        assert any("code_sha256" in i for i in check_meta(m))

    def test_empty_top_field(self):
        m = dict(GOOD_META, run_id="")
        assert any("run_id" in i for i in check_meta(m))

    def test_git_missing_head(self):
        m = dict(GOOD_META, git={"dirty": False})
        assert any("git.head" in i for i in check_meta(m))

    def test_git_not_object(self):
        m = dict(GOOD_META, git="not-a-dict")
        assert any("git is not an object" in i for i in check_meta(m))

    def test_empty_code_sha(self):
        m = dict(GOOD_META, code_sha256={})
        issues = check_meta(m)
        assert any("code_sha256" in i for i in issues)


def _make_run(runs, name, meta):
    d = runs / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "meta.json", "w") as f:
        json.dump(meta, f)
    return d


class TestVerifyRun:
    def test_good_run(self, temp_dir):
        d = _make_run(temp_dir, "r1", GOOD_META)
        ok, issues = verify_run(d)
        assert ok and issues == []

    def test_missing_meta(self, temp_dir):
        (temp_dir / "r2").mkdir()
        ok, issues = verify_run(temp_dir / "r2")
        assert not ok and "meta.json missing" in issues

    def test_malformed_meta(self, temp_dir):
        d = temp_dir / "r3"
        d.mkdir()
        (d / "meta.json").write_text("{bad json")
        ok, issues = verify_run(d)
        assert not ok and any("invalid" in i for i in issues)


class TestMain:
    def test_all_good(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _make_run(runs, "r1", GOOD_META)
        _make_run(runs, "r2", GOOD_META)
        rc = main(["--runs-dir", str(runs)])
        assert rc == 0
        assert "fully reproducible" in capsys.readouterr().out

    def test_some_incomplete(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _make_run(runs, "r1", GOOD_META)
        _make_run(runs, "r2", {"run_id": "x"})  # incomplete
        rc = main(["--runs-dir", str(runs), "--verbose"])
        assert rc == 1
        assert "INCOMPLETE" in capsys.readouterr().out

    def test_runs_dir_missing(self, temp_dir):
        rc = main(["--runs-dir", str(temp_dir / "nope")])
        assert rc == 1

    def test_no_runs(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        rc = main(["--runs-dir", str(runs), "--pattern", "zzz*"])
        assert rc == 1
