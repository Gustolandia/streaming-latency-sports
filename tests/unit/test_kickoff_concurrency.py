"""Tests for scripts/kickoff_concurrency.py - target 100% branch coverage."""
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from kickoff_concurrency import (  # noqa: E402
    parse_slots,
    slot_concurrency,
    overlap_concurrency,
    league_matchday_bound,
    recommend_levels,
    summarize,
    main,
)


def _df(rows):
    return pd.DataFrame(rows, columns=["match_id", "match_date", "kick_off",
                                       "competition_name"])


SATURDAY_3PM = [
    (1, "2016-01-02", "15:00:00.000", "Premier League"),
    (2, "2016-01-02", "15:00:00.000", "Premier League"),
    (3, "2016-01-02", "15:00:00.000", "Premier League"),
    (4, "2016-01-02", "17:30:00.000", "Premier League"),
]


class TestParseSlots:
    def test_builds_timestamp(self):
        out = parse_slots(_df(SATURDAY_3PM))
        assert len(out) == 4
        assert str(out["slot_ts"].iloc[0]).startswith("2016-01-02 15:00")

    def test_drops_missing_kick_off(self):
        rows = SATURDAY_3PM + [(5, "2016-01-02", None, "PL")]
        assert len(parse_slots(_df(rows))) == 4

    def test_drops_missing_date(self):
        rows = SATURDAY_3PM + [(5, None, "15:00:00.000", "PL")]
        assert len(parse_slots(_df(rows))) == 4

    def test_drops_unparseable(self):
        rows = SATURDAY_3PM + [(5, "not-a-date", "nonsense", "PL")]
        assert len(parse_slots(_df(rows))) == 4

    def test_whitespace_tolerated(self):
        out = parse_slots(_df([(1, " 2016-01-02 ", " 15:00:00.000 ", "PL")]))
        assert len(out) == 1


class TestSlotConcurrency:
    def test_counts_and_ranks(self):
        out = slot_concurrency(_df(SATURDAY_3PM))
        assert out.iloc[0]["n_matches"] == 3, "the 15:00 slot has three matches"
        assert len(out) == 2

    def test_lists_competitions(self):
        rows = [(1, "2016-01-02", "15:00:00.000", "Premier League"),
                (2, "2016-01-02", "15:00:00.000", "La Liga")]
        out = slot_concurrency(_df(rows))
        assert out.iloc[0]["competitions"] == "La Liga, Premier League"

    def test_empty_input(self):
        out = slot_concurrency(_df([]))
        assert out.empty and list(out.columns) == ["slot_ts", "n_matches", "competitions"]


class TestOverlapConcurrency:
    def test_staggered_kickoffs_still_overlap(self):
        # 15:00 and 16:00 kick-offs overlap for most of an hour: slot concurrency says 1 each,
        # overlap concurrency says 2. This is what a consumer actually sees.
        rows = [(1, "2016-01-02", "15:00:00.000", "PL"),
                (2, "2016-01-02", "16:00:00.000", "PL")]
        _, peak = overlap_concurrency(_df(rows), match_minutes=115)
        assert peak == 2

    def test_non_overlapping(self):
        rows = [(1, "2016-01-02", "12:00:00.000", "PL"),
                (2, "2016-01-02", "20:00:00.000", "PL")]
        _, peak = overlap_concurrency(_df(rows), match_minutes=115)
        assert peak == 1

    def test_timeline_returned(self):
        tl, peak = overlap_concurrency(_df(SATURDAY_3PM))
        assert set(tl.columns) == {"ts", "in_play"}
        assert peak >= 3

    def test_empty_input(self):
        tl, peak = overlap_concurrency(_df([]))
        assert tl.empty and peak == 0


class TestLeagueMatchdayBound:
    @pytest.mark.parametrize("teams,expected", [(20, 10), (18, 9), (2, 1), (0, 0), (None, 0)])
    def test_bound(self, teams, expected):
        assert league_matchday_bound(teams) == expected


class TestRecommendLevels:
    def test_derived_from_distribution(self):
        # median=2, p75=3, max=8 for [1,1,2,3,8]
        slots = pd.DataFrame({"n_matches": [1, 1, 2, 3, 8]})
        assert recommend_levels(slots) == [2, 3, 8]

    def test_includes_structural_bounds(self):
        slots = pd.DataFrame({"n_matches": [1, 2]})
        assert 10 in recommend_levels(slots, extra=[10])

    def test_empty_slots_with_extra(self):
        assert recommend_levels(pd.DataFrame(), extra=[10]) == [10]

    def test_empty_everything(self):
        assert recommend_levels(None) == []

    def test_never_below_one(self):
        assert min(recommend_levels(pd.DataFrame({"n_matches": [0, 0]}))) == 1


class TestSummarize:
    def test_populated(self):
        slots = slot_concurrency(_df(SATURDAY_3PM))
        s = summarize(slots, 3, [1, 3]).iloc[0]
        assert s["max_simultaneous_kickoffs"] == 3
        assert s["recommended_levels"] == "1;3"

    def test_empty(self):
        s = summarize(pd.DataFrame(), 0, []).iloc[0]
        assert s["n_slots"] == 0 and s["max_simultaneous_kickoffs"] == 0


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        idx = temp_dir / "index.csv"
        _df(SATURDAY_3PM).to_csv(idx, index=False)
        out = temp_dir / "conc"
        rc = main(["--index", str(idx), "--out", str(out), "--league-teams", "20"])
        assert rc == 0
        for f in ("kickoff_slots.csv", "in_play_timeline.csv", "concurrency_summary.csv"):
            assert (out / f).exists()
        cap = capsys.readouterr().out
        assert "LOWER BOUND" in cap, "the sampling caveat must always be printed"
        assert "10" in pd.read_csv(out / "concurrency_summary.csv").iloc[0]["recommended_levels"]

    def test_missing_file(self, temp_dir, capsys):
        assert main(["--index", str(temp_dir / "nope.csv")]) == 1
        assert "Could not read" in capsys.readouterr().out

    def test_wrong_schema(self, temp_dir, capsys):
        p = temp_dir / "bad.csv"
        pd.DataFrame({"x": [1]}).to_csv(p, index=False)
        assert main(["--index", str(p), "--out", str(temp_dir / "o")]) == 1
        assert "lacks match_date" in capsys.readouterr().out

    def test_empty_corpus_still_writes(self, temp_dir):
        p = temp_dir / "empty.csv"
        _df([]).to_csv(p, index=False)
        out = temp_dir / "o"
        assert main(["--index", str(p), "--out", str(out)]) == 0
        assert (out / "concurrency_summary.csv").exists()
