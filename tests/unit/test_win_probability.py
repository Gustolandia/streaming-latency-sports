"""Tests for scripts/win_probability.py - target >=95% coverage."""
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
import sys
sys.path.insert(0, str(SCRIPTS_DIR))

from win_probability import (
    clock_seconds,
    parse_match,
    win_probability,
    wp_timeline,
    final_outcome,
    ranked_probability_score,
    main,
)


def _ev(minute, second, team, etype="Pass", **extra):
    e = {"minute": minute, "second": second, "team": {"name": team}, "type": {"name": etype}}
    e.update(extra)
    return e


def _goal(minute, second, team):
    return _ev(minute, second, team, "Shot", shot={"outcome": {"name": "Goal"}, "statsbomb_xg": 0.4})


def _match_events():
    # Home=A, Away=B. A scores at 10', B never -> home win.
    return [
        _ev(0, 0, "A", "Starting XI"),
        _ev(0, 1, "B", "Starting XI"),
        _ev(5, 0, "A", "Shot", shot={"outcome": {"name": "Saved"}, "statsbomb_xg": 0.1}),
        _goal(10, 0, "A"),
        _ev(60, 0, "B", "Bad Behaviour", bad_behaviour={"card": {"name": "Red Card"}}),
        _ev(90, 0, "A"),
    ]


class TestClock:
    def test_cumulative(self):
        assert clock_seconds(45, 30) == 45 * 60 + 30


class TestParseMatch:
    def test_basic(self):
        home, away, goals, reds, mlen = parse_match(_match_events())
        assert home == "A" and away == "B"
        assert goals == [(600, "A")]
        assert reds == [(3600, "B")]
        assert mlen >= 90 * 60

    def test_own_goal(self):
        ev = [_ev(0, 0, "A", "Starting XI"), _ev(0, 1, "B", "Starting XI"),
              _ev(20, 0, "A", "Own Goal Against")]
        home, away, goals, _, _ = parse_match(ev)
        assert goals == [(1200, "B")]  # own goal credited to opponent

    def test_second_yellow_is_red(self):
        ev = [_ev(0, 0, "A"), _ev(0, 1, "B"),
              _ev(30, 0, "A", "Foul Committed", bad_behaviour={"card": {"name": "Second Yellow"}})]
        _, _, _, reds, _ = parse_match(ev)
        assert reds == [(1800, "A")]


class TestWinProbability:
    def test_probabilities_sum_to_one(self):
        pw, pd, pl = win_probability(0, 1.0)
        assert abs(pw + pd + pl - 1.0) < 1e-6

    def test_leading_late_high_winprob(self):
        pw, _, _ = win_probability(2, 0.02)  # 2-up, ~2% left
        assert pw > 0.95

    def test_match_over_leading(self):
        pw, pd, pl = win_probability(1, 0.0)
        assert pw == 1.0 and pd == 0.0 and pl == 0.0

    def test_match_over_level(self):
        pw, pd, pl = win_probability(0, 0.0)
        assert pd == 1.0

    def test_trailing_lower_than_leading(self):
        lead, _, _ = win_probability(1, 0.5)
        trail, _, _ = win_probability(-1, 0.5)
        assert lead > trail

    def test_red_card_against_home_lowers_winprob(self):
        base, _, _ = win_probability(0, 0.5, red_diff=0)
        down, _, _ = win_probability(0, 0.5, red_diff=1)  # home a man down
        assert down < base


class TestTimelineAndOutcome:
    def test_wp_timeline(self):
        home, away, pts = wp_timeline(_match_events(), grid_seconds=300)
        assert home == "A"
        assert len(pts) > 1
        assert pts[-1][1] > 0.9  # home led at the end

    def test_final_outcome_home_win(self):
        assert final_outcome(_match_events()) == 1

    def test_final_outcome_draw(self):
        ev = [_ev(0, 0, "A"), _ev(0, 1, "B")]
        assert final_outcome(ev) == 0


class TestRPS:
    def test_perfect_forecast(self):
        assert ranked_probability_score(1.0, 0.0, 0.0, 1) == 0.0

    def test_worst_forecast(self):
        # predicted loss with certainty, actual win
        assert ranked_probability_score(0.0, 0.0, 1.0, 1) == pytest.approx(1.0)

    def test_uncertain_forecast_between(self):
        s = ranked_probability_score(1/3, 1/3, 1/3, 1)
        assert 0.0 < s < 1.0


class TestMain:
    def test_main_on_synthetic_dir(self, temp_dir, capsys):
        ev_dir = temp_dir / "events"
        ev_dir.mkdir()
        (ev_dir / "1.json").write_text(json.dumps(_match_events()))
        (ev_dir / "2.json").write_text(json.dumps([_ev(0, 0, "X"), _ev(0, 1, "Y"), _goal(30, 0, "Y")]))
        out = temp_dir / "wp"
        rc = main(["--events-dir", str(ev_dir), "--out", str(out)])
        assert rc == 0
        assert (out / "win_probability_summary.json").exists()
        data = json.loads((out / "win_probability_summary.json").read_text())
        assert data["n_matches"] == 2

    def test_main_no_files(self, temp_dir):
        ev_dir = temp_dir / "empty"
        ev_dir.mkdir()
        assert main(["--events-dir", str(ev_dir)]) == 1

    def test_main_skips_bad_json(self, temp_dir):
        ev_dir = temp_dir / "events"
        ev_dir.mkdir()
        (ev_dir / "bad.json").write_text("{not valid")
        (ev_dir / "empty.json").write_text("[]")
        (ev_dir / "ok.json").write_text(json.dumps(_match_events()))
        out = temp_dir / "wp"
        rc = main(["--events-dir", str(ev_dir), "--out", str(out)])
        assert rc == 0
        assert json.loads((out / "win_probability_summary.json").read_text())["n_matches"] == 1
