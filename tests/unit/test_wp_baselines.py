"""Tests for scripts/wp_baselines.py - target 100% branch coverage."""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from wp_baselines import (  # noqa: E402
    rps,
    base_rates,
    score_only_table,
    lookup,
    skill_score,
    evaluate,
    match_states,
    collect_samples,
    main,
)

UNIFORM = (1 / 3.0, 1 / 3.0, 1 / 3.0)


class TestRps:
    def test_perfect_forecast_scores_zero(self):
        assert rps(1.0, 0.0, 0.0, 1) == pytest.approx(0.0)

    def test_worst_forecast_scores_one(self):
        assert rps(0.0, 0.0, 1.0, 1) == pytest.approx(1.0)

    def test_uniform_is_between(self):
        assert 0 < rps(*UNIFORM, 1) < 1


class TestBaseRates:
    def test_counts_frequencies(self):
        assert base_rates([1, 1, 0, -1]) == pytest.approx((0.5, 0.25, 0.25))

    def test_empty_is_uniform(self):
        assert base_rates([]) == pytest.approx(UNIFORM)

    def test_unrecognised_outcomes_ignored(self):
        assert base_rates(["nonsense", 7]) == pytest.approx(UNIFORM)


class TestScoreOnlyTable:
    def test_buckets_by_goal_difference(self):
        tbl = score_only_table([(1, 1), (1, 1), (-1, -1), (0, 0)])
        assert tbl[1] == pytest.approx((1.0, 0.0, 0.0))
        assert tbl[-1] == pytest.approx((0.0, 0.0, 1.0))

    def test_empty(self):
        assert score_only_table([]) == {}


class TestLookup:
    def test_hit_and_miss(self):
        tbl = {0: (0.4, 0.3, 0.3)}
        assert lookup(tbl, 0) == (0.4, 0.3, 0.3)
        assert lookup(tbl, 9) == pytest.approx(UNIFORM)


class TestSkillScore:
    def test_better_than_reference_is_positive(self):
        assert skill_score(0.1, 0.2) == pytest.approx(0.5)

    def test_equal_is_zero(self):
        assert skill_score(0.2, 0.2) == pytest.approx(0.0)

    def test_worse_is_negative(self):
        assert skill_score(0.3, 0.2) < 0

    @pytest.mark.parametrize("ref", [0.0, -1.0, None, float("nan")])
    def test_degenerate_reference(self, ref):
        assert np.isnan(skill_score(0.1, ref))


def _events(goals=(), reds=(), length_min=90):
    """Minimal StatsBomb-shaped match: a Shot/Goal per entry, plus a final clock event."""
    ev = []
    for minute, team in goals:
        ev.append({"period": 1, "minute": minute, "second": 0,
                   "type": {"name": "Shot"}, "team": {"name": team},
                   "shot": {"outcome": {"name": "Goal"}}})
    for minute, team in reds:
        ev.append({"period": 1, "minute": minute, "second": 0,
                   "type": {"name": "Bad Behaviour"}, "team": {"name": team},
                   "bad_behaviour": {"card": {"name": "Red Card"}}})
    ev.append({"period": 2, "minute": length_min, "second": 0,
               "type": {"name": "Half End"}, "team": {"name": "Home"}})
    return ev


class TestMatchStates:
    def test_samples_across_the_match(self):
        st = match_states(_events(goals=[(10, "Home")]), grid_seconds=600)
        assert len(st) >= 2
        diffs = [s[0] for s in st]
        assert max(diffs) >= 1, "the home goal must appear in some state"
        assert all(0.0 <= s[1] <= 1.0 for s in st)

    def test_zero_length_match_yields_nothing(self, monkeypatch):
        # parse_match supplies a default match length, so the guard is only reachable when the
        # parsed length really is zero; patch it rather than pretend a real match can be.
        import wp_baselines as wb
        monkeypatch.setattr(wb.wp, "parse_match",
                            lambda ev: ("Home", "Away", [], [], 0))
        assert match_states(_events(), grid_seconds=60) == []

    def test_red_cards_enter_the_state(self):
        st = match_states(_events(reds=[(20, "Away")]), grid_seconds=600)
        assert max(s[2] for s in st) >= 1, "an away dismissal is a +1 home red difference"


class TestEvaluate:
    def test_returns_all_three_references(self):
        samples = [(0, 0.5, 0, 1), (1, 0.4, 0, 1), (-1, 0.3, 0, -1), (0, 0.2, 0, 0)] * 5
        df = evaluate(samples)
        assert set(df["reference"]) == {"uniform", "base_rate", "score_only"}
        assert (df["n_states"] == len(samples)).all()

    def test_model_beats_uniform_on_decided_matches(self):
        samples = [(3, 0.1, 0, 1)] * 20
        df = evaluate(samples).set_index("reference")
        assert df.loc["uniform", "skill_score"] > 0

    def test_empty(self):
        assert evaluate([]).empty


class TestCollectSamples:
    def _corpus(self, tmp, n=2):
        d = tmp / "events"
        d.mkdir(parents=True)
        for i in range(n):
            (d / f"{i}.json").write_text(json.dumps(_events(goals=[(10, "Home")])))
        return d

    def test_collects(self, temp_dir):
        s = collect_samples(self._corpus(temp_dir), grid_seconds=600)
        assert len(s) > 0 and len(s[0]) == 4

    def test_limit(self, temp_dir):
        d = self._corpus(temp_dir, n=4)
        assert len(collect_samples(d, 600, limit=1)) < len(collect_samples(d, 600))

    def test_skips_unreadable_empty_and_malformed(self, temp_dir):
        d = self._corpus(temp_dir, n=1)
        (d / "bad.json").write_text("{oops")
        (d / "empty.json").write_text("[]")
        (d / "weird.json").write_text(json.dumps([{"no": "fields"}]))
        assert len(collect_samples(d, 600)) > 0

    def test_empty_dir(self, temp_dir):
        d = temp_dir / "none"
        d.mkdir()
        assert collect_samples(d) == []


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        d = temp_dir / "events"
        d.mkdir()
        for i in range(3):
            (d / f"{i}.json").write_text(json.dumps(_events(goals=[(10, "Home")])))
        out = temp_dir / "wp"
        rc = main(["--events-dir", str(d), "--grid-seconds", "600", "--out", str(out)])
        assert rc == 0
        df = pd.read_csv(out / "wp_baselines.csv")
        assert len(df) == 3
        assert "skill > 0" in capsys.readouterr().out

    def test_no_usable_states(self, temp_dir, capsys):
        d = temp_dir / "events"
        d.mkdir()
        assert main(["--events-dir", str(d), "--out", str(temp_dir / "o")]) == 1
        assert "No usable game states" in capsys.readouterr().out
