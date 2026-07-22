"""Tests for scripts/characterize_feed.py - target 100% branch coverage."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from characterize_feed import (  # noqa: E402
    event_times,
    peak_rate,
    match_profile,
    load_match,
    profile_corpus,
    summarize,
    main,
)


def ev(period, minute, second, **kw):
    d = {"period": period, "minute": minute, "second": second}
    d.update(kw)
    return d


class TestEventTimes:
    def test_orders_and_offsets_periods(self):
        # Second-half clock restarts at 45:00 in StatsBomb; without a period offset the
        # halves would interleave and every gap would be wrong.
        t = event_times([ev(1, 0, 0), ev(1, 45, 0), ev(2, 45, 0), ev(2, 90, 0)])
        assert list(t) == sorted(t)
        assert t[-1] > t[1], "second half must follow the first"

    def test_skips_incomplete_events(self):
        t = event_times([ev(1, 0, 0), {"period": 1, "minute": None, "second": 3},
                         {"foo": "bar"}, ev(1, 0, 5)])
        assert len(t) == 2

    def test_empty(self):
        assert len(event_times([])) == 0

    def test_all_unusable(self):
        assert len(event_times([{"foo": 1}, {"period": None}])) == 0

    def test_single_period_needs_no_offset(self):
        # exercises the offset loop with exactly one period present
        t = event_times([ev(1, 0, 0), ev(1, 0, 10)])
        assert list(t) == [0.0, 10.0]


class TestPeakRate:
    def test_dense_burst_detected(self):
        # ten events inside one second, then nothing for a minute
        times = np.array([0.0] * 0 + [i * 0.1 for i in range(10)] + [60.0])
        assert peak_rate(times, window_s=1.0) == pytest.approx(10.0)

    def test_uniform_stream(self):
        times = np.arange(0, 100, 1.0)
        assert peak_rate(times, window_s=10.0) == pytest.approx(1.1, abs=0.15)

    def test_empty_or_bad_window(self):
        assert peak_rate(np.array([]), 10) == 0.0
        assert peak_rate(None, 10) == 0.0
        assert peak_rate(np.array([1.0, 2.0]), 0) == 0.0


class TestMatchProfile:
    def test_profiles(self):
        events = [ev(1, 0, i) for i in range(0, 60, 2)]
        p = match_profile(events, window_s=10)
        assert p["n_events"] == 30
        assert p["mean_rate_evs"] == pytest.approx(30 / 58.0, rel=0.01)
        assert p["burstiness"] >= 1.0

    def test_too_few_events(self):
        assert match_profile([ev(1, 0, 0)]) is None
        assert match_profile([]) is None

    def test_zero_duration(self):
        assert match_profile([ev(1, 0, 0), ev(1, 0, 0)]) is None

    def test_gap_stats_present(self):
        p = match_profile([ev(1, 0, i) for i in range(0, 30)], window_s=5)
        for k in ("gap_p50_s", "gap_p05_s", "gap_min_s"):
            assert k in p

    def test_all_gaps_zero_guarded(self):
        # duplicate timestamps -> no positive gaps; gap_min_s must not blow up
        events = [ev(1, 0, 0), ev(1, 0, 0), ev(1, 1, 0)]
        p = match_profile(events)
        assert p is not None and p["gap_min_s"] >= 0.0


class TestLoadMatch:
    def test_reads(self, temp_dir):
        p = temp_dir / "1.json"
        p.write_text(json.dumps([ev(1, 0, 0)]))
        assert load_match(p) == [ev(1, 0, 0)]

    def test_missing(self, temp_dir):
        assert load_match(temp_dir / "nope.json") is None

    def test_malformed(self, temp_dir):
        p = temp_dir / "bad.json"
        p.write_text("{not json")
        assert load_match(p) is None


def _corpus(tmp, n=3):
    d = tmp / "events"
    d.mkdir(parents=True)
    for i in range(1, n + 1):
        (d / f"{i}.json").write_text(json.dumps([ev(1, 0, s) for s in range(0, 40, 2)]))
    return d


class TestProfileCorpus:
    def test_joins_metadata(self, temp_dir):
        d = _corpus(temp_dir)
        idx = pd.DataFrame([{"match_id": 1, "competition_name": "PL", "season_name": "2015/2016",
                             "gender": "male", "season_start_year": 2015}])
        df = profile_corpus(d, idx)
        assert len(df) == 3
        assert df[df.match_id == "1"].iloc[0]["competition_name"] == "PL"

    def test_without_index(self, temp_dir):
        df = profile_corpus(_corpus(temp_dir), None)
        assert len(df) == 3 and df.iloc[0]["competition_name"] is None

    def test_index_without_match_id_column(self, temp_dir):
        df = profile_corpus(_corpus(temp_dir), pd.DataFrame({"x": [1]}))
        assert len(df) == 3

    def test_limit(self, temp_dir):
        assert len(profile_corpus(_corpus(temp_dir, 5), None, limit=2)) == 2

    def test_skips_unreadable_and_unprofilable(self, temp_dir):
        d = _corpus(temp_dir, 1)
        (d / "bad.json").write_text("{oops")
        (d / "thin.json").write_text(json.dumps([ev(1, 0, 0)]))
        assert len(profile_corpus(d, None)) == 1

    def test_empty_dir(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert profile_corpus(d, None).empty


class TestSummarize:
    def _df(self):
        return pd.DataFrame([
            {"n_events": 100, "duration_s": 100.0, "mean_rate_evs": 1.0, "peak_rate_evs": 3.0,
             "gap_p50_s": 1.0, "gap_p05_s": 0.2, "burstiness": 3.0,
             "competition_name": "PL", "gender": "male"},
            {"n_events": 200, "duration_s": 100.0, "mean_rate_evs": 2.0, "peak_rate_evs": 8.0,
             "gap_p50_s": 0.5, "gap_p05_s": 0.1, "burstiness": 4.0,
             "competition_name": "PL", "gender": "male"},
        ])

    def test_overall(self):
        out = summarize(self._df())
        assert out.iloc[0]["n_matches"] == 2
        assert out.iloc[0]["mean_rate_evs"] == pytest.approx(1.5)

    def test_grouped(self):
        out = summarize(self._df(), "competition_name")
        assert out.iloc[0]["competition_name"] == "PL" and out.iloc[0]["n_matches"] == 2

    def test_missing_group_column_falls_back(self):
        out = summarize(self._df(), "nonexistent")
        assert "n_matches" in out.columns and len(out) == 1

    def test_empty(self):
        assert summarize(pd.DataFrame()).empty
        assert summarize(None).empty


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        d = _corpus(temp_dir)
        idx = temp_dir / "idx.csv"
        pd.DataFrame([{"match_id": i, "competition_name": "PL", "season_name": "2015/2016",
                       "gender": "male", "season_start_year": 2015}
                      for i in (1, 2, 3)]).to_csv(idx, index=False)
        out = temp_dir / "feed"
        rc = main(["--events-dir", str(d), "--index", str(idx), "--out", str(out)])
        assert rc == 0
        for f in ("match_profiles.csv", "feed_summary.csv", "feed_by_competition.csv",
                  "feed_by_gender.csv", "feed_by_year.csv"):
            assert (out / f).exists(), f
        assert "feed characterisation" in capsys.readouterr().out

    def test_missing_index_still_runs(self, temp_dir, capsys):
        d = _corpus(temp_dir)
        rc = main(["--events-dir", str(d), "--index", str(temp_dir / "nope.csv"),
                   "--out", str(temp_dir / "feed")])
        assert rc == 0
        assert "no match index" in capsys.readouterr().out

    def test_no_usable_matches(self, temp_dir, capsys):
        d = temp_dir / "events"
        d.mkdir()
        assert main(["--events-dir", str(d), "--out", str(temp_dir / "o")]) == 1
        assert "No usable matches" in capsys.readouterr().out
