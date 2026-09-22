"""Tests for scripts/check_identifiers.py, with the network injected rather than reached.

The script exists because five pinned commit hashes turned out not to be commits, and nothing
had ever asked. Its own tests therefore have to cover the case that matters: an identifier that
looks right, is fetched, and is not there.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import check_identifiers as ci  # noqa: E402


TOOLS = """#!/usr/bin/env bash
PINNED='
vegeta|go|cf5811269046c672a604b1eb352204d30f16ae4a
valkey-benchmark|apt|9.1.2
wrk2|git|44a94c17d8e6a0bac8559b53da76848e430cb7a7
'
"""
AUDIT = ['{"tools": [{"tool": "Vegeta", "version_seen": "master at '
         'cf5811269046c672a604b1eb352204d30f16ae4a, 2026-02-16"},'
         '{"tool": "valkey-benchmark", "version_seen": "release 9.1.2, 2026-09-01"},'
         '{"tool": "wrk2", "version_seen": "44a94c17d8e6a0bac8559b53da76848e430cb7a7"}]}']


def answers(known):
    """A fetcher that answers 200 for the URLs it is told about and 404 for the rest."""
    def fetch(url):
        return 200 if any(k in url for k in known) else 404
    return fetch


class TestWhatTheRepositoryAsserts:

    def test_the_pinned_table_is_read_as_rows(self):
        assert ci.tool_pins(TOOLS) == [
            ("vegeta", "go", "cf5811269046c672a604b1eb352204d30f16ae4a"),
            ("valkey-benchmark", "apt", "9.1.2"),
            ("wrk2", "git", "44a94c17d8e6a0bac8559b53da76848e430cb7a7")]

    def test_a_file_with_no_table_yields_nothing(self):
        assert ci.tool_pins("#!/usr/bin/env bash\necho hello\n") == []

    def test_a_malformed_row_is_skipped_rather_than_guessed(self):
        assert ci.tool_pins("PINNED='\nvegeta|go\n'\n") == []

    def test_dois_are_collected_and_the_url_prefix_dropped(self):
        bib = ('@article{a, doi={10.1109/TC.2022.3215907}}\n'
               '@article{b, DOI = "https://doi.org/10.1145/2670979.2670988"}\n'
               '@article{c, doi={10.1109/TC.2022.3215907}}\n')
        assert ci.dois(bib) == ["10.1109/TC.2022.3215907", "10.1145/2670979.2670988"]

    def test_arxiv_identifiers_are_collected(self):
        bib = ('@article{a, journal={arXiv preprint arXiv:2605.24217}}\n'
               '@article{b, note={arXiv: 2205.09325}}\n')
        assert ci.arxiv_ids(bib) == ["2205.09325", "2605.24217"]

    def test_zenodo_records_are_collected_in_numeric_order(self):
        assert ci.zenodo_ids(["10.5281/zenodo.22307766 and 10.5281/zenodo.9",
                              "10.5281/zenodo.22307766"]) == ["9", "22307766"]

    def test_only_the_audit_json_is_read_from_that_folder(self, tmp_path, monkeypatch):
        """The folder carries a README beside the batches, and reading it as a record would put
        prose where version strings are looked for."""
        folder = tmp_path / "data" / "tools_audit"
        folder.mkdir(parents=True)
        (folder / "batch_01.json").write_text('{"version_seen": "abc123"}', encoding="utf-8")
        (folder / "README.md").write_text("not a record", encoding="utf-8")
        monkeypatch.setattr(ci, "REPO", str(tmp_path))
        found = ci.audited_versions()
        assert "abc123" in found and "not a record" not in found

    def test_records_can_be_handed_in_rather_than_read_from_disk(self):
        """Which is how the tests below give it a table to check without a tree to read."""
        assert ci.audited_versions(AUDIT).count("cf5811269046") == 1

    def test_a_file_that_is_not_there_reads_as_empty(self, monkeypatch):
        monkeypatch.setattr(ci, "REPO", os.path.join(ci.REPO, "no-such-folder"))
        assert ci.read("nothing.txt") == ""
        assert ci.audited_versions() == ""


class TestAskingTheirSources:

    def test_a_url_that_answers_200_is_ok_and_anything_else_is_not(self):
        assert ci.http_ok("https://x/ok", answers(["ok"])) is True
        assert ci.http_ok("https://x/gone", answers(["ok"])) is False

    def test_a_fetcher_that_raises_is_not_ok(self):
        def boom(url):
            raise OSError("no network")
        assert ci.http_ok("https://x", boom) is False

    def test_a_pin_that_is_not_a_commit_anywhere_is_reported(self, monkeypatch):
        """The fault this script was written for."""
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [
            ("vegeta", "go", "cf5811269046c672a604b1eb352204d30f9d5b58")])
        monkeypatch.setattr(ci, "audited_versions", lambda texts=None:
                            "cf5811269046c672a604b1eb352204d30f9d5b58")
        found = ci.check("tools", answers([]))
        assert [(row[2], row[3]) for row in found] == [(False, "not a commit in tsenart/vegeta")]

    def test_a_pin_the_audit_does_not_record_is_reported_even_when_it_is_a_real_commit(
            self, monkeypatch):
        """The other half: a real commit is not the right commit unless the audit read it."""
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [
            ("vegeta", "go", "4b240c3089fa4aa10816542d64a74294d974211f")])
        monkeypatch.setattr(ci, "audited_versions", lambda texts=None: "something else entirely")
        found = ci.check("tools", answers(["commits"]))
        assert found[0][2] is False
        assert "not the version data/tools_audit records" in found[0][3]

    def test_a_tool_with_no_known_repository_cannot_be_confirmed(self, monkeypatch):
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [
            ("something-new", "git", "44a94c17d8e6a0bac8559b53da76848e430cb7a7")])
        monkeypatch.setattr(ci, "audited_versions", lambda texts=None:
                            "44a94c17d8e6a0bac8559b53da76848e430cb7a7")
        found = ci.check("tools", answers(["commits"]))
        assert found[0][2] is False and "not a commit in None" in found[0][3]

    def test_a_version_that_is_not_a_commit_rests_on_the_audit_alone(self, monkeypatch):
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [
            ("valkey-benchmark", "apt", "9.1.2")])
        monkeypatch.setattr(ci, "audited_versions", lambda texts=None: "release 9.1.2, 2026-09-01")
        found = ci.check("tools", answers([]))
        assert found[0][2] is True and "only the audit record can say" in found[0][3]

    @pytest.mark.parametrize("group,known,ident", [
        ("doi", "api.crossref.org", "10.1109/TC.2022.3215907"),
        ("arxiv", "arxiv.org/abs", "2605.24217"),
        ("zenodo", "zenodo.org/api", "22307766")])
    def test_each_group_asks_its_own_source(self, group, known, ident, monkeypatch):
        monkeypatch.setattr(ci, "dois", lambda text=None: [ident])
        monkeypatch.setattr(ci, "arxiv_ids", lambda text=None: [ident])
        monkeypatch.setattr(ci, "zenodo_ids", lambda texts=None: [ident])
        assert ci.check(group, answers([known])) == [(group, ident, True, "")]
        bad = ci.check(group, answers([]))
        assert bad[0][2] is False and bad[0][3]

    def test_asking_for_everything_asks_every_group(self, monkeypatch):
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [])
        monkeypatch.setattr(ci, "dois", lambda text=None: ["10.1/x"])
        monkeypatch.setattr(ci, "arxiv_ids", lambda text=None: ["2605.24217"])
        monkeypatch.setattr(ci, "zenodo_ids", lambda texts=None: ["1"])
        assert sorted({row[0] for row in ci.check(None, answers([]))}) == \
            ["arxiv", "doi", "zenodo"]


class TestTheCommandLine:

    def test_list_asks_nothing_and_names_everything(self, monkeypatch):
        monkeypatch.setattr(ci, "tool_pins", lambda text=None: [("vegeta", "go", "abc1234")])
        monkeypatch.setattr(ci, "dois", lambda text=None: ["10.1/x"])
        monkeypatch.setattr(ci, "arxiv_ids", lambda text=None: ["2605.24217"])
        monkeypatch.setattr(ci, "zenodo_ids", lambda texts=None: ["1"])
        out = io.StringIO()
        assert ci.main(["--list"], out) == 0
        assert "vegeta abc1234" in out.getvalue() and "10.1/x" in out.getvalue()

    def test_it_exits_one_when_something_does_not_exist(self, monkeypatch):
        monkeypatch.setattr(ci, "dois", lambda text=None: ["10.1/gone"])
        out = io.StringIO()
        assert ci.main(["--only", "doi"], out, answers([])) == 1
        assert "resolves to nothing" in out.getvalue()
        assert "1 asked, 1 that do not exist" in out.getvalue()

    def test_it_exits_zero_when_everything_is_there(self, monkeypatch):
        monkeypatch.setattr(ci, "dois", lambda text=None: ["10.1/here"])
        out = io.StringIO()
        assert ci.main(["--only", "doi"], out, answers(["crossref"])) == 0
        assert "0 that do not exist" in out.getvalue()


def test_the_real_repository_states_identifiers_to_check():
    """Not a network test: only that the collectors find what is actually in the tree, so an
    empty run cannot pass for a clean one."""
    assert len(ci.tool_pins()) >= 10, "the ten tools the block runs"
    assert len(ci.dois()) >= 10
    assert len(ci.zenodo_ids()) >= 10
    assert ci.audited_versions(), "data/tools_audit is where the right versions live"
