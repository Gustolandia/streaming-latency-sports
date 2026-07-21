"""Tests for scripts/wp_calibration.py - target >=95% branch coverage."""
import json
from pathlib import Path
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wp_calibration import (
    collect_calibration_pairs,
    reliability_bins,
    expected_calibration_error,
    main,
)


def _ev(minute, second, team, etype="Pass", **extra):
    e = {"minute": minute, "second": second, "team": {"name": team}, "type": {"name": etype}}
    e.update(extra)
    return e


def _goal(minute, second, team):
    return _ev(minute, second, team, "Shot", shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.4})


def _home_win_match():
    return [_ev(0, 0, "A", "Starting XI"), _ev(0, 1, "B", "Starting XI"),
            _goal(10, 0, "A"), _goal(80, 0, "A"), _ev(90, 0, "A")]


def _draw_match():
    return [_ev(0, 0, "X", "Starting XI"), _ev(0, 1, "Y", "Starting XI"), _ev(90, 0, "X")]


class TestCollect:
    def test_pairs_have_prob_and_binary_outcome(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "1.json").write_text(json.dumps(_home_win_match()))
        pairs = collect_calibration_pairs(d, grid_seconds=300)
        assert pairs and all(0 <= p <= 1 for p, _ in pairs)
        assert set(o for _, o in pairs) <= {0, 1}
        assert pairs[-1][1] == 1  # home won

    def test_skips_bad_and_empty(self, temp_dir):
        d = temp_dir / "events"
        d.mkdir()
        (d / "bad.json").write_text("{nope")
        (d / "empty.json").write_text("[]")
        (d / "notlist.json").write_text("{}")  # valid JSON but not a list -> skipped
        (d / "ok.json").write_text(json.dumps(_draw_match()))
        pairs = collect_calibration_pairs(d, grid_seconds=300)
        assert pairs and all(o == 0 for _, o in pairs)  # draw -> not a home win


class TestBins:
    def test_empty_pairs(self):
        assert reliability_bins([]).empty

    def test_bins_and_ece(self):
        # perfectly calibrated toy: p=0.0 never wins, p=1.0 always wins
        pairs = [(0.0, 0)] * 5 + [(1.0, 1)] * 5
        bins = reliability_bins(pairs, n_bins=10)
        assert len(bins) == 2
        ece = expected_calibration_error(bins, len(pairs))
        assert ece == pytest.approx(0.0, abs=1e-9)

    def test_miscalibrated_ece_positive(self):
        # predict 0.9 but only wins half the time -> nonzero ECE
        pairs = [(0.9, 1)] * 5 + [(0.9, 0)] * 5
        bins = reliability_bins(pairs, n_bins=10)
        ece = expected_calibration_error(bins, len(pairs))
        assert ece > 0.3

    def test_ece_nan_on_empty(self):
        import numpy as np
        assert np.isnan(expected_calibration_error(reliability_bins([]), 0))


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        d = temp_dir / "events"
        d.mkdir()
        (d / "1.json").write_text(json.dumps(_home_win_match()))
        (d / "2.json").write_text(json.dumps(_draw_match()))
        out = temp_dir / "wp"
        rc = main(["--events-dir", str(d), "--grid-seconds", "120", "--out", str(out)])
        assert rc == 0
        assert (out / "wp_calibration_bins.csv").exists()
        assert (out / "wp_calibration.json").exists()
        assert (out / "wp_calibration.png").exists()
        data = json.loads((out / "wp_calibration.json").read_text())
        assert data["n_states"] > 0

    def test_no_pairs(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert main(["--events-dir", str(d)]) == 1
