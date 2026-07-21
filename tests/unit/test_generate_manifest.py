"""Tests for scripts/generate_manifest.py - target >=95% branch coverage."""
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from generate_manifest import (
    sha256_file,
    collect_hashes,
    git_commit,
    build_manifest,
    main,
)


def _make_tree(root):
    (root / "scripts").mkdir(parents=True)
    (root / "configs").mkdir()
    (root / "scripts" / "a.py").write_text("print('a')\n")
    (root / "scripts" / "b.py").write_text("print('b')\n")
    (root / "configs" / "c.yaml").write_text("k: v\n")
    (root / "requirements.txt").write_text("pandas\n")
    (root / "docker-compose.yml").write_text("services: {}\n")


class TestHashing:
    def test_sha256_matches_hashlib(self, temp_dir):
        f = temp_dir / "x.txt"
        f.write_bytes(b"hello")
        assert sha256_file(f) == hashlib.sha256(b"hello").hexdigest()

    def test_collect_hashes(self, temp_dir):
        _make_tree(temp_dir)
        h = collect_hashes(temp_dir)
        assert set(h) == {"scripts/a.py", "scripts/b.py", "configs/c.yaml",
                          "requirements.txt", "docker-compose.yml"}
        assert all(len(v) == 64 for v in h.values())

    def test_collect_empty(self, temp_dir):
        assert collect_hashes(temp_dir) == {}


class TestGitCommit:
    def test_returns_hash_or_unknown(self, temp_dir):
        # a plain temp dir is not a git repo -> subprocess returns non-zero / empty
        val = git_commit(temp_dir)
        assert isinstance(val, str) and val  # "unknown" or a real hash

    def test_handles_missing_git(self, temp_dir):
        with patch("generate_manifest.subprocess.run", side_effect=OSError):
            assert git_commit(temp_dir) == "unknown"


class TestBuildAndMain:
    def test_build_manifest_structure(self, temp_dir):
        _make_tree(temp_dir)
        m = build_manifest(temp_dir)
        assert m["n_code_files"] == 5
        assert "protocol" in m and "code_sha256" in m and "git_commit" in m

    def test_main_writes(self, temp_dir):
        _make_tree(temp_dir)
        out = temp_dir / "reproducibility" / "MANIFEST.json"
        rc = main(["--root", str(temp_dir), "--out", str(out)])
        assert rc == 0
        data = json.loads(out.read_text())
        assert data["n_code_files"] == 5

    def test_main_no_files(self, temp_dir):
        out = temp_dir / "M.json"
        assert main(["--root", str(temp_dir), "--out", str(out)]) == 1
