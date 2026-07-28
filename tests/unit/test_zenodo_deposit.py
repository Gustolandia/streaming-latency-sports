"""Tests for scripts/zenodo_deposit.py - target >=95% branch coverage.

No network is touched: the Zenodo API is stubbed. The important behaviours to pin are that the
token is read from the environment (never a file), that the default path leaves an UNPUBLISHED
draft, and that publishing only happens when explicitly requested.
"""
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import zenodo_deposit as zd


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def _session(dep=None):
    s = MagicMock()
    dep = dep or {"id": 42, "links": {"bucket": "https://b/bucket/1",
                                      "html": "https://zenodo.org/deposit/42"}}
    s.post.return_value = _Resp(dep)
    s.put.return_value = _Resp({"key": "bundle.zip"})
    return s, dep


class TestMetadata:
    def test_wraps_metadata(self, temp_dir):
        p = temp_dir / "z.json"
        p.write_text(json.dumps({"title": "T", "upload_type": "software"}), encoding="utf-8")
        assert zd.load_metadata(p) == {"metadata": {"title": "T", "upload_type": "software"}}


class TestApiCalls:
    def test_create_deposition_posts_metadata(self):
        s, dep = _session()
        out = zd.create_deposition(zd.LIVE, "tok", {"metadata": {}}, session=s)
        assert out == dep
        assert s.post.call_args[1]["params"]["access_token"] == "tok"

    def test_upload_uses_bucket_link(self, temp_dir):
        s, dep = _session()
        f = temp_dir / "bundle.zip"
        f.write_bytes(b"zip")
        zd.upload_file(zd.LIVE, "tok", dep, f, session=s)
        assert s.put.call_args[0][0].endswith("/bundle.zip")

    def test_publish_hits_publish_action(self):
        s, _ = _session()
        s.post.return_value = _Resp({"doi": "10.5281/zenodo.42"})
        out = zd.publish(zd.LIVE, "tok", 42, session=s)
        assert out["doi"] == "10.5281/zenodo.42"
        assert "actions/publish" in s.post.call_args[0][0]


class TestMain:
    def _patch(self, monkeypatch, temp_dir, published=None):
        monkeypatch.setattr(zd, "build_bundle", lambda z, ref="HEAD", prefix="", **kw: _mk(temp_dir))
        monkeypatch.setattr(zd, "create_deposition",
                            lambda *a, **k: {"id": 42, "links": {"bucket": "b",
                                                                 "html": "https://z/deposit/42"}})
        monkeypatch.setattr(zd, "upload_file", lambda *a, **k: {"key": "b.zip"})
        monkeypatch.setattr(zd, "publish", lambda *a, **k: {"doi": "10.5281/zenodo.42"})

    def _meta(self, temp_dir):
        p = temp_dir / ".zenodo.json"
        p.write_text(json.dumps({"title": "T"}), encoding="utf-8")
        return p

    def test_requires_token(self, temp_dir, monkeypatch, capsys):
        monkeypatch.delenv("ZENODO_API_TOKEN", raising=False)
        assert zd.main(["--metadata", str(self._meta(temp_dir))]) == 1
        assert "ZENODO_API_TOKEN" in capsys.readouterr().out

    def test_requires_metadata_file(self, temp_dir, monkeypatch):
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        assert zd.main(["--metadata", str(temp_dir / "missing.json")]) == 1

    def test_default_leaves_unpublished_draft(self, temp_dir, monkeypatch, capsys):
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        self._patch(monkeypatch, temp_dir)
        rc = zd.main(["--metadata", str(self._meta(temp_dir))])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NOT published" in out and "Review and publish here" in out
        assert "PUBLISHED" not in out

    def test_publish_flag_publishes(self, temp_dir, monkeypatch, capsys):
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        self._patch(monkeypatch, temp_dir)
        rc = zd.main(["--metadata", str(self._meta(temp_dir)), "--publish"])
        assert rc == 0 and "PUBLISHED" in capsys.readouterr().out

    def test_sandbox_selects_sandbox_api(self, temp_dir, monkeypatch):
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        seen = {}

        monkeypatch.setattr(zd, "build_bundle", lambda z, ref="HEAD", prefix="", **kw: _mk(temp_dir))
        monkeypatch.setattr(zd, "upload_file", lambda *a, **k: {})

        def cap(api, token, metadata, session=None):
            seen["api"] = api
            return {"id": 1, "links": {"bucket": "b", "html": "h"}}

        monkeypatch.setattr(zd, "create_deposition", cap)
        zd.main(["--metadata", str(self._meta(temp_dir)), "--sandbox"])
        assert seen["api"] == zd.SANDBOX


def _mk(temp_dir):
    f = temp_dir / "bundle.zip"
    f.write_bytes(b"zipcontents")
    return f


class TestBundle:
    def test_build_bundle_invokes_git_archive(self, temp_dir, monkeypatch):
        called = {}

        def fake_run(cmd, **kw):
            called["cmd"] = cmd
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"zip")
            return MagicMock(returncode=0)

        monkeypatch.setattr(zd.subprocess, "run", fake_run)
        out = zd.build_bundle(temp_dir / "d" / "b.zip", ref="v1.0")
        assert out.exists()
        assert "git" in called["cmd"][0] and "v1.0" in called["cmd"]

    def test_nc_derived_data_is_excluded_from_the_record(self, temp_dir, monkeypatch):
        """The record is MIT; StatsBomb-derived replay plans are CC BY-NC and cannot ship in it.

        Enforced through a git pathspec rather than by pruning the zip afterwards, so a file
        added under that path later is excluded automatically instead of silently included.
        """
        called = {}

        def fake_run(cmd, **kw):
            called["cmd"] = cmd
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"zip")
            return MagicMock(returncode=0)

        monkeypatch.setattr(zd.subprocess, "run", fake_run)
        zd.build_bundle(temp_dir / "b.zip")
        cmd = called["cmd"]
        assert "data/processed/replay_plans" in zd.NC_DERIVED_PATHS
        assert ":(exclude)data/processed/replay_plans" in cmd
        assert cmd.index("--") < cmd.index(":(exclude)data/processed/replay_plans"), \
            "pathspecs must follow the -- separator or git treats them as refs"

    def test_exclusions_are_configurable(self, temp_dir, monkeypatch):
        called = {}
        monkeypatch.setattr(zd.subprocess, "run",
                            lambda cmd, **kw: (called.__setitem__("cmd", cmd),
                                               Path(cmd[cmd.index("-o") + 1]).write_bytes(b"z"),
                                               MagicMock(returncode=0))[-1])
        zd.build_bundle(temp_dir / "b.zip", exclude=("secret/",))
        assert ":(exclude)secret/" in called["cmd"]
        assert ":(exclude)data/processed/replay_plans" not in called["cmd"]


class TestPathRestriction:
    """The dataset record archives only the measurement paths; a bundle that silently included
    the whole tree would duplicate the software record and double the licence surface."""

    def test_paths_restrict_the_archive(self, tmp_path):
        import zipfile
        import zenodo_deposit as zd
        out = tmp_path / "data.zip"
        zd.build_bundle(str(out), ref="HEAD", paths=("docs/results",))
        names = zipfile.ZipFile(out).namelist()
        assert names, "the restricted bundle must not be empty"
        assert all("/docs/results/" in n or n.endswith("/") for n in names), \
            "only docs/results content may appear"
        assert not any("/scripts/" in n for n in names)

    def test_default_paths_cover_the_tree(self, tmp_path):
        import zipfile
        import zenodo_deposit as zd
        out = tmp_path / "all.zip"
        zd.build_bundle(str(out), ref="HEAD")
        names = zipfile.ZipFile(out).namelist()
        assert any("/scripts/" in n for n in names)
        assert not any("replay_plans" in n for n in names), \
            "the NC-derived plans must stay excluded"
