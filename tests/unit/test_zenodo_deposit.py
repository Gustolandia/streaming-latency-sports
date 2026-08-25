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

    def test_third_party_papers_are_excluded_from_the_record(self, temp_dir, monkeypatch):
        """`docs/reference_tc` is sixteen other people's papers, thirty-five megabytes of it.

        Readable under whatever each publisher granted, redistributable under none of it.
        Caught when the v2.6.0 bundle came out at 38 MB against v2.5.0's 7 MB: the archive had
        grown five-fold on material the record does not own and the analysis never reads.
        """
        called = {}

        def fake_run(cmd, **kw):
            called["cmd"] = cmd
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"zip")
            return MagicMock(returncode=0)

        monkeypatch.setattr(zd.subprocess, "run", fake_run)
        zd.build_bundle(temp_dir / "b.zip")
        assert "docs/reference_tc" in zd.NC_DERIVED_PATHS
        assert ":(exclude)docs/reference_tc" in called["cmd"]

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


class TestTokenRejection:
    def test_403_prints_site_and_scope_guidance(self, tmp_path, monkeypatch, capsys):
        """A rejected token must explain itself: wrong-site tokens are the usual cause and a
        traceback teaches nothing."""
        import json
        import requests
        import zenodo_deposit as zd
        meta = tmp_path / "m.json"
        meta.write_text(json.dumps({"title": "t"}), encoding="utf-8")
        monkeypatch.setenv("ZENODO_API_TOKEN", "x")
        def fake_bundle(z, ref="HEAD", prefix="", **kw):
            out = tmp_path / "b.zip"
            out.write_bytes(b"z")
            return out
        monkeypatch.setattr(zd, "build_bundle", fake_bundle)
        resp = requests.Response()
        resp.status_code = 403

        def boom(*a, **k):
            raise requests.HTTPError(response=resp)
        monkeypatch.setattr(zd, "create_deposition", boom)
        rc = zd.main(["--sandbox", "--metadata", str(meta), "--zip", str(tmp_path / "b.zip")])
        out = capsys.readouterr().out
        assert rc == 1
        assert "SEPARATE accounts" in out
        assert "deposit:write" in out
        assert "sandbox.zenodo.org" in out


class TestAnErrorThatIsNotARejectedToken:

    def test_it_propagates_rather_than_being_swallowed(self, tmp_path, monkeypatch):
        """Only 401 and 403 have an explanation worth printing. A 500, or a network failure,
        must reach the operator as itself: printing the token guidance for it would send
        someone to mint a new token for a problem a new token cannot fix."""
        import json
        import requests
        import zenodo_deposit as zd
        meta = tmp_path / "m.json"
        meta.write_text(json.dumps({"title": "t"}), encoding="utf-8")
        monkeypatch.setenv("ZENODO_API_TOKEN", "x")

        def fake_bundle(z, ref="HEAD", prefix="", **kw):
            out = tmp_path / "b.zip"
            out.write_bytes(b"z")
            return out

        monkeypatch.setattr(zd, "build_bundle", fake_bundle)
        resp = requests.Response()
        resp.status_code = 500

        def boom(*a, **k):
            raise requests.HTTPError(response=resp)

        monkeypatch.setattr(zd, "create_deposition", boom)
        with pytest.raises(requests.HTTPError):
            zd.main(["--sandbox", "--metadata", str(meta),
                     "--zip", str(tmp_path / "b.zip")])

    def test_an_http_error_with_no_response_also_propagates(self, tmp_path, monkeypatch):
        """A connection that never got a reply has no status code to classify."""
        import json
        import requests
        import zenodo_deposit as zd
        meta = tmp_path / "m.json"
        meta.write_text(json.dumps({"title": "t"}), encoding="utf-8")
        monkeypatch.setenv("ZENODO_API_TOKEN", "x")

        def fake_bundle(z, ref="HEAD", prefix="", **kw):
            out = tmp_path / "b.zip"
            out.write_bytes(b"z")
            return out

        monkeypatch.setattr(zd, "build_bundle", fake_bundle)

        def boom(*a, **k):
            raise requests.HTTPError(response=None)

        monkeypatch.setattr(zd, "create_deposition", boom)
        with pytest.raises(requests.HTTPError):
            zd.main(["--sandbox", "--metadata", str(meta),
                     "--zip", str(tmp_path / "b.zip")])

class TestNewVersion:
    """Adding a version to an existing record, which keeps its concept DOI.

    Until round 40 this script could only `POST /deposit/depositions`, which mints a *new*
    concept DOI and orphans the citation chain. The paper cites the concept DOIs precisely so
    that "the DOI stays the same" survives every release, and that promise is only kept if a
    release goes through the newversion action.
    """

    def _stub(self, files=(("f1", "streaming-latency-sports-v2.5.0.zip"),)):
        """A session recording every call, shaped like Zenodo's newversion flow."""
        calls = []

        class S:
            def post(self, url, params=None, json=None):
                calls.append(("POST", url))
                if url.endswith("/actions/newversion"):
                    return _Resp({"links":
                                  {"latest_draft": "https://z/api/deposit/depositions/99"}})
                return _Resp({"id": 99})

            def get(self, url, params=None):
                calls.append(("GET", url))
                return _Resp({"id": 99, "links": {"bucket": "https://z/bucket/99"},
                              "files": [{"id": i, "filename": n} for i, n in files]})

            def delete(self, url, params=None):
                calls.append(("DELETE", url))
                return _Resp({})

            def put(self, url, params=None, json=None, data=None):
                calls.append(("PUT", url))
                return _Resp({"id": 99})

        return S(), calls

    def test_it_uses_the_newversion_action_and_fetches_the_draft(self):
        s, calls = self._stub()
        dep = zd.new_version("https://z/api", "tok", "22044877", session=s)
        assert ("POST",
                "https://z/api/deposit/depositions/22044877/actions/newversion") in calls
        assert ("GET", "https://z/api/deposit/depositions/99") in calls
        assert dep["id"] == 99

    def test_inherited_files_are_deleted(self):
        """Zenodo copies the previous version's files in; shipping both zips is a defect."""
        s, calls = self._stub(files=(("f1", "old.zip"), ("f2", "old-SHA256SUMS.txt")))
        dep = zd.new_version("https://z/api", "tok", "22044877", session=s)
        assert zd.clear_files("https://z/api", "tok", dep, session=s) == [
            "old.zip", "old-SHA256SUMS.txt"]
        assert sum(1 for m, _ in calls if m == "DELETE") == 2

    def test_a_draft_with_no_inherited_files_deletes_nothing(self):
        s, _ = self._stub(files=())
        dep = zd.new_version("https://z/api", "tok", "22044877", session=s)
        assert zd.clear_files("https://z/api", "tok", dep, session=s) == []

    def test_a_file_without_a_filename_is_reported_by_id(self):
        s, _ = self._stub(files=())
        dep = {"id": 99, "files": [{"id": "abc"}]}
        assert zd.clear_files("https://z/api", "tok", dep, session=s) == ["abc"]

    def test_metadata_is_written_over_what_was_inherited(self):
        s, calls = self._stub()
        zd.update_metadata("https://z/api", "tok", 99, {"metadata": {"version": "2.6.0"}},
                           session=s)
        assert ("PUT", "https://z/api/deposit/depositions/99") in calls


class TestMainNewVersion:

    def _common(self, monkeypatch, temp_dir, cleared):
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        monkeypatch.setattr(zd, "build_bundle",
                            lambda z, ref="HEAD", prefix="", **kw: _mk(temp_dir))
        monkeypatch.setattr(zd, "new_version",
                            lambda *a, **k: {"id": 99, "links": {"bucket": "b",
                                                                 "html": "https://z/deposit/99"}})
        monkeypatch.setattr(zd, "clear_files", lambda *a, **k: cleared)
        monkeypatch.setattr(zd, "update_metadata", lambda *a, **k: {"id": 99})
        monkeypatch.setattr(zd, "upload_file", lambda *a, **k: {"key": "b.zip"})
        p = temp_dir / ".zenodo.json"
        p.write_text('{"title": "T", "version": "2.6.0"}', encoding="utf-8")
        return p

    def test_the_flag_takes_the_newversion_route_and_still_leaves_a_draft(self, temp_dir,
                                                                          monkeypatch, capsys):
        meta = self._common(monkeypatch, temp_dir, ["old.zip"])
        assert zd.main(["--metadata", str(meta), "--new-version", "22044877"]) == 0
        out = capsys.readouterr().out
        assert "Cleared inherited file(s): old.zip" in out
        assert "concept DOI unchanged" in out
        assert "NOT published" in out and "PUBLISHED" not in out

    def test_an_empty_draft_reports_nothing_cleared(self, temp_dir, monkeypatch, capsys):
        meta = self._common(monkeypatch, temp_dir, [])
        assert zd.main(["--metadata", str(meta), "--new-version", "22044877"]) == 0
        assert "Cleared inherited" not in capsys.readouterr().out

    def test_without_the_flag_a_fresh_record_is_still_created(self, temp_dir, monkeypatch):
        """The default must not change: a new record, and so a new concept DOI."""
        monkeypatch.setenv("ZENODO_API_TOKEN", "tok")
        monkeypatch.setattr(zd, "build_bundle",
                            lambda z, ref="HEAD", prefix="", **kw: _mk(temp_dir))
        monkeypatch.setattr(zd, "upload_file", lambda *a, **k: {})
        monkeypatch.setattr(zd, "new_version",
                            lambda *a, **k: pytest.fail("newversion must not be used"))
        used = []
        monkeypatch.setattr(zd, "create_deposition",
                            lambda *a, **k: used.append(1) or
                            {"id": 1, "links": {"bucket": "b", "html": "h"}})
        p = temp_dir / ".zenodo.json"
        p.write_text('{"title": "T"}', encoding="utf-8")
        assert zd.main(["--metadata", str(p)]) == 0
        assert used == [1]
