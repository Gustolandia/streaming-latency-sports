"""Tests for scripts/make_replay_plan.py - target >=95% branch coverage.

This script regenerates the replay plans the repository ships as data, so these tests pin the
schedule arithmetic (period offsets, speed factor) that the whole corpus depends on.
"""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_replay_plan import safe_int, main


def _raw(tmp, commit="abc123", match_id=1, events=None):
    d = tmp / "raw" / commit / "events"
    d.mkdir(parents=True)
    (d / f"{match_id}.json").write_text(json.dumps(events), encoding="utf-8")
    return tmp / "raw"


def _ev(period, minute, second, eid="e1", etype="Pass", team="A"):
    return {"id": eid, "period": period, "minute": minute, "second": second,
            "type": {"name": etype}, "team": {"name": team},
            "player": {"name": "P"}, "timestamp": "00:00:00.000", "possession": 1}


class TestSafeInt:
    def test_parses_and_defaults(self):
        assert safe_int("7") == 7
        assert safe_int(None) == 0
        assert safe_int("nope", default=3) == 3


class TestMain:
    def test_period_offsets_and_speed_factor(self, temp_dir):
        # 2nd-half events must be offset by 45 minutes of match clock
        evs = [_ev(1, 0, 0, "a"), _ev(2, 0, 30, "b")]
        raw = _raw(temp_dir, events=evs)
        out = temp_dir / "plans"
        rc = main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
                   "--out-root", str(out), "--speed-factor", "10"])
        assert rc == 0
        df = pd.read_csv(out / "abc123" / "match_1" / "replay_plan.csv")
        assert list(df["t_sim_seconds"]) == [0, 45 * 60 + 30]
        # emission offset is match clock divided by the speed factor
        assert list(df["t_emit_offset_s"]) == [0.0, (45 * 60 + 30) / 10]

    def test_rows_sorted_by_match_clock(self, temp_dir):
        # out-of-order input must come back in match order
        evs = [_ev(1, 10, 0, "late"), _ev(1, 1, 0, "early")]
        raw = _raw(temp_dir, events=evs)
        out = temp_dir / "plans"
        main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
              "--out-root", str(out)])
        df = pd.read_csv(out / "abc123" / "match_1" / "replay_plan.csv")
        assert list(df["event_id"]) == ["early", "late"]

    def test_writes_meta_with_provenance(self, temp_dir):
        raw = _raw(temp_dir, events=[_ev(1, 0, 0)])
        out = temp_dir / "plans"
        main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
              "--out-root", str(out), "--speed-factor", "120"])
        meta = json.loads((out / "abc123" / "match_1" / "meta.json").read_text())
        assert meta["commit"] == "abc123" and meta["match_id"] == 1
        assert meta["n_events"] == 1 and meta["speed_factor"] == 120.0

    def test_unknown_period_falls_back_to_zero_offset(self, temp_dir):
        raw = _raw(temp_dir, events=[_ev(9, 1, 0, "odd")])   # period 9 not in the offset table
        out = temp_dir / "plans"
        main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
              "--out-root", str(out)])
        df = pd.read_csv(out / "abc123" / "match_1" / "replay_plan.csv")
        assert df.iloc[0]["t_sim_seconds"] == 60

    def test_missing_events_file(self, temp_dir):
        raw = temp_dir / "raw"
        raw.mkdir()
        with pytest.raises(FileNotFoundError):
            main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
                  "--out-root", str(temp_dir / "plans")])

    def test_rejects_non_list_json(self, temp_dir):
        raw = _raw(temp_dir, events={"not": "a list"})
        with pytest.raises(ValueError):
            main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
                  "--out-root", str(temp_dir / "plans")])

    def test_rejects_empty_events(self, temp_dir):
        raw = _raw(temp_dir, events=[])
        with pytest.raises(ValueError):
            main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
                  "--out-root", str(temp_dir / "plans")])

    def test_parquet_failure_is_not_fatal(self, temp_dir, monkeypatch):
        # the CSV is the artifact the producers consume; a missing parquet engine must not
        # stop the corpus being regenerated
        import make_replay_plan as mrp
        raw = _raw(temp_dir, events=[_ev(1, 0, 0)])
        out = temp_dir / "plans"

        def boom(self, *a, **k):
            raise ImportError("no pyarrow")

        monkeypatch.setattr(mrp.pd.DataFrame, "to_parquet", boom)
        assert main(["--commit", "abc123", "--match-id", "1", "--raw-root", str(raw),
                     "--out-root", str(out)]) == 0
        assert (out / "abc123" / "match_1" / "replay_plan.csv").exists()
        meta = json.loads((out / "abc123" / "match_1" / "meta.json").read_text())
        assert meta["outputs"]["parquet_with_payload"] is None
