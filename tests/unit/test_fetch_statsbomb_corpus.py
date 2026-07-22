"""Tests for scripts/fetch_statsbomb_corpus.py - target 100% branch coverage."""
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_statsbomb_corpus as fc  # noqa: E402
from fetch_statsbomb_corpus import (  # noqa: E402
    season_start_year,
    select_seasons,
    competitions_url,
    matches_url,
    events_url,
    fetch_json,
    save_events,
    collect_matches,
    main,
)

SHA = "deadbeef"


def _getter(mapping, fail=()):
    """Fake HTTP: URL substring -> payload. Substrings in `fail` raise."""
    def get(url, timeout=60):
        for bad in fail:
            if bad in url:
                raise OSError("boom")
        for key, payload in mapping.items():
            if key in url:
                return json.dumps(payload).encode("utf-8")
        raise OSError(f"unmapped {url}")
    return get


class TestSeasonStartYear:
    @pytest.mark.parametrize("s,y", [("2015/2016", 2015), ("2022", 2022), ("1999/2000", 1999)])
    def test_parses(self, s, y):
        assert season_start_year(s) == y

    @pytest.mark.parametrize("s", ["", None, "not-a-season", "/2016"])
    def test_unparseable_is_none(self, s):
        assert season_start_year(s) is None


class TestSelectSeasons:
    COMPS = [
        {"competition_id": 2, "season_id": 27, "competition_name": "Premier League",
         "season_name": "2015/2016", "competition_gender": "male", "country_name": "England"},
        {"competition_id": 2, "season_id": 44, "competition_name": "Premier League",
         "season_name": "2003/2004", "competition_gender": "male", "country_name": "England"},
        {"competition_id": 16, "season_id": 4, "competition_name": "Champions League",
         "season_name": "1999/2000", "competition_gender": "male", "country_name": "Europe"},
        {"competition_id": 72, "season_id": 107, "competition_name": "Women's World Cup",
         "season_name": "2023", "competition_gender": "female", "country_name": "International"},
        {"competition_id": 2, "season_id": 27, "competition_name": "Premier League",
         "season_name": "2015/2016", "competition_gender": "male", "country_name": "England"},
    ]

    def test_filters_by_year_window(self):
        out = select_seasons(self.COMPS, 2003, 2023)
        assert (16, 4) not in [(r["competition_id"], r["season_id"]) for r in out]
        assert len(out) == 3, "1999/2000 excluded, duplicate collapsed"

    def test_deduplicates(self):
        out = select_seasons(self.COMPS, 2003, 2023)
        keys = [(r["competition_id"], r["season_id"]) for r in out]
        assert len(keys) == len(set(keys))

    def test_keeps_gender_and_year(self):
        out = select_seasons(self.COMPS, 2003, 2023)
        w = [r for r in out if r["gender"] == "female"][0]
        assert w["season_start_year"] == 2023

    def test_unparseable_season_skipped(self):
        assert select_seasons([{"competition_id": 1, "season_id": 1,
                                "season_name": "unknown"}], 2003, 2023) == []

    def test_empty(self):
        assert select_seasons([], 2003, 2023) == []


class TestUrls:
    def test_shapes(self):
        assert competitions_url(SHA).endswith(f"{SHA}/data/competitions.json")
        assert matches_url(SHA, 2, 27).endswith("/matches/2/27.json")
        assert events_url(SHA, 12345).endswith("/events/12345.json")


class TestFetchJson:
    def test_ok(self):
        assert fetch_json("x/competitions.json",
                          _getter({"competitions.json": [{"a": 1}]})) == [{"a": 1}]

    def test_transport_failure_is_none(self):
        assert fetch_json("x/competitions.json",
                          _getter({}, fail=("competitions.json",))) is None

    def test_bad_json_is_none(self):
        assert fetch_json("u", lambda url, timeout=60: b"{not json") is None


class TestSaveEvents:
    def test_writes(self, temp_dir):
        r = save_events(7, temp_dir, SHA, _getter({"events/7.json": [{"e": 1}]}))
        assert r == "ok"
        assert json.loads((temp_dir / "7.json").read_text()) == [{"e": 1}]

    def test_cached_is_not_refetched(self, temp_dir):
        (temp_dir / "7.json").write_text('[{"e": 1}]')

        def explode(url, timeout=60):
            raise AssertionError("should not refetch a cached match")

        assert save_events(7, temp_dir, SHA, explode) == "cached"

    def test_force_refetches(self, temp_dir):
        (temp_dir / "7.json").write_text('[{"old": 1}]')
        r = save_events(7, temp_dir, SHA, _getter({"events/7.json": [{"new": 1}]}), force=True)
        assert r == "ok"
        assert json.loads((temp_dir / "7.json").read_text()) == [{"new": 1}]

    def test_empty_file_is_refetched(self, temp_dir):
        (temp_dir / "7.json").write_text("")
        assert save_events(7, temp_dir, SHA, _getter({"events/7.json": []})) == "ok"

    def test_failure(self, temp_dir):
        assert save_events(7, temp_dir, SHA, _getter({}, fail=("events/7.json",))) == "fail"


class TestCollectMatches:
    SEASONS = [{"competition_id": 2, "season_id": 27, "competition_name": "PL",
                "season_name": "2015/2016", "gender": "male", "season_start_year": 2015}]
    PAYLOAD = [{"match_id": 1, "match_date": "2015-08-15", "kick_off": "16:00:00.000",
                "home_team": {"home_team_name": "A"}, "away_team": {"away_team_name": "B"},
                "home_score": 1, "away_score": 0,
                "competition_stage": {"name": "Regular Season"}}]

    def test_flattens_and_tags(self):
        out = collect_matches(self.SEASONS, SHA, _getter({"matches/2/27.json": self.PAYLOAD}))
        assert len(out) == 1
        m = out[0]
        assert m["kick_off"] == "16:00:00.000" and m["competition_name"] == "PL"
        assert m["home_team"] == "A" and m["competition_stage"] == "Regular Season"

    def test_missing_season_file_skipped(self):
        assert collect_matches(self.SEASONS, SHA, _getter({}, fail=("matches",))) == []

    def test_empty_season_payload_skipped(self):
        assert collect_matches(self.SEASONS, SHA, _getter({"matches/2/27.json": []})) == []

    def test_missing_nested_team_fields(self):
        payload = [{"match_id": 2, "match_date": "d", "kick_off": "k"}]
        out = collect_matches(self.SEASONS, SHA, _getter({"matches/2/27.json": payload}))
        assert out[0]["home_team"] is None and out[0]["competition_stage"] is None


class TestMain:
    COMPS = [{"competition_id": 2, "season_id": 27, "competition_name": "PL",
              "season_name": "2015/2016", "competition_gender": "male",
              "country_name": "England"}]
    MATCHES = [{"match_id": 1, "match_date": "2015-08-15", "kick_off": "16:00:00.000",
                "home_team": {"home_team_name": "A"}, "away_team": {"away_team_name": "B"}},
               {"match_id": 2, "match_date": "2015-08-15", "kick_off": "16:00:00.000",
                "home_team": {"home_team_name": "C"}, "away_team": {"away_team_name": "D"}}]

    def _patch(self, monkeypatch, fail=()):
        monkeypatch.setattr(fc, "_default_get", _getter(
            {"competitions.json": self.COMPS, "matches/2/27.json": self.MATCHES,
             "events/1.json": [{"e": 1}], "events/2.json": [{"e": 2}]}, fail=fail))

    def test_dry_run_writes_index_only(self, temp_dir, capsys, monkeypatch):
        self._patch(monkeypatch)
        idx = temp_dir / "idx.csv"
        rc = main(["--sha", SHA, "--dry-run", "--index-out", str(idx),
                   "--out", str(temp_dir / "raw")])
        assert rc == 0
        assert idx.exists() and "kick_off" in idx.read_text()
        assert not (temp_dir / "raw").exists()
        assert "dry run" in capsys.readouterr().out

    def test_full_fetch(self, temp_dir, capsys, monkeypatch):
        self._patch(monkeypatch)
        rc = main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv"),
                   "--out", str(temp_dir / "raw"), "--sleep", "0"])
        assert rc == 0
        assert (temp_dir / "raw" / SHA / "events" / "1.json").exists()
        assert "ok=2" in capsys.readouterr().out

    def test_max_matches_limits(self, temp_dir, monkeypatch):
        self._patch(monkeypatch)
        main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv"),
              "--out", str(temp_dir / "raw"), "--max-matches", "1"])
        assert (temp_dir / "raw" / SHA / "events" / "1.json").exists()
        assert not (temp_dir / "raw" / SHA / "events" / "2.json").exists()

    def test_competitions_unreachable_returns_1(self, temp_dir, capsys, monkeypatch):
        self._patch(monkeypatch, fail=("competitions.json",))
        assert main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv")]) == 1
        assert "Could not fetch" in capsys.readouterr().out

    def test_all_events_fail_returns_1(self, temp_dir, monkeypatch):
        self._patch(monkeypatch, fail=("events/",))
        assert main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv"),
                     "--out", str(temp_dir / "raw")]) == 1

    def test_no_matches_writes_empty_index(self, temp_dir, monkeypatch):
        monkeypatch.setattr(fc, "_default_get", _getter(
            {"competitions.json": self.COMPS, "matches/2/27.json": []}))
        idx = temp_dir / "i.csv"
        assert main(["--sha", SHA, "--index-out", str(idx), "--out", str(temp_dir / "raw")]) == 0
        assert idx.read_text() == ""

    def test_progress_line_every_100(self, temp_dir, capsys, monkeypatch):
        many = [{"match_id": i, "match_date": "d", "kick_off": "k"} for i in range(1, 101)]
        monkeypatch.setattr(fc, "_default_get", _getter(
            {"competitions.json": self.COMPS, "matches/2/27.json": many,
             "events/": [{"e": 1}]}))
        main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv"),
              "--out", str(temp_dir / "raw")])
        assert "100/100" in capsys.readouterr().out

    def test_sleep_between_fetches_is_honoured(self, temp_dir, monkeypatch):
        # --sleep exists to be polite to the CDN on a multi-thousand-match fetch;
        # verify it is actually applied rather than silently ignored.
        self._patch(monkeypatch)
        calls = []
        monkeypatch.setattr(fc.time, "sleep", lambda s: calls.append(s))
        main(["--sha", SHA, "--index-out", str(temp_dir / "i.csv"),
              "--out", str(temp_dir / "raw"), "--sleep", "0.25"])
        assert calls == [0.25, 0.25]
