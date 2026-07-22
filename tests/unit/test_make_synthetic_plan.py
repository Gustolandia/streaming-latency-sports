"""Tests for scripts/make_synthetic_plan.py - target 100% branch coverage."""
import csv
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from make_synthetic_plan import (  # noqa: E402
    ARRIVALS,
    constant_offsets,
    poisson_offsets,
    bursty_offsets,
    build_plan,
    write_plan,
    achieved_rate,
    main,
)

RATE, DURATION = 0.415, 600.0


def _rng():
    return np.random.default_rng(7)


class TestConstantOffsets:
    def test_regular_spacing(self):
        off = constant_offsets(2.0, 10.0, _rng())
        gaps = np.diff(off)
        assert np.allclose(gaps, 0.5)

    def test_hits_the_requested_rate(self):
        off = constant_offsets(RATE, DURATION, _rng())
        assert len(off) / DURATION == pytest.approx(RATE, abs=0.01)

    def test_never_empty_even_at_a_very_low_rate(self):
        assert len(constant_offsets(0.0001, 1.0, _rng())) == 1


class TestPoissonOffsets:
    def test_mean_rate_is_approximately_right(self):
        off = poisson_offsets(RATE, 6000.0, _rng())
        assert len(off) / 6000.0 == pytest.approx(RATE, rel=0.15)

    def test_gaps_are_irregular_unlike_constant(self):
        off = poisson_offsets(RATE, DURATION, _rng())
        assert np.std(np.diff(off)) > 0.5

    def test_stays_within_the_duration(self):
        off = poisson_offsets(RATE, DURATION, _rng())
        assert off.max() < DURATION

    def test_degenerate_short_duration_still_returns_a_row(self):
        """A duration shorter than one expected gap must not produce an empty plan."""
        assert len(poisson_offsets(0.001, 0.001, _rng())) == 1


class TestBurstyOffsets:
    def test_holds_the_mean_rate(self):
        off = bursty_offsets(RATE, DURATION, _rng())
        assert len(off) / DURATION == pytest.approx(RATE, rel=0.2)

    def test_arrivals_clump(self):
        """Bursty gaps must be far more dispersed than constant ones at the same rate."""
        bursty = np.diff(bursty_offsets(RATE, DURATION, _rng()))
        constant = np.diff(constant_offsets(RATE, DURATION, _rng()))
        assert np.std(bursty) > 5 * max(np.std(constant), 1e-9)

    def test_short_duration_terminates(self):
        off = bursty_offsets(RATE, 1.0, _rng())
        assert len(off) >= 1 and off.max() <= 1.0

    def test_degenerate_returns_a_row(self):
        assert len(bursty_offsets(1e6, 1e-9, _rng())) == 1


class TestBuildPlan:
    @pytest.mark.parametrize("arrival", ARRIVALS)
    def test_every_arrival_process_builds(self, arrival):
        rows = build_plan(arrival, RATE, DURATION)
        assert rows
        assert set(rows[0]) == {"row_idx", "event_id", "match_id",
                                "t_sim_seconds", "t_emit_offset_s"}

    def test_schema_matches_the_orchestrator_contract(self):
        rows = build_plan("constant", RATE, 60.0)
        assert rows[0]["row_idx"] == 0
        assert all(isinstance(r["t_sim_seconds"], int) for r in rows)
        assert rows[1]["t_emit_offset_s"] > rows[0]["t_emit_offset_s"]

    def test_event_ids_are_unique_and_namespaced(self):
        rows = build_plan("poisson", RATE, DURATION)
        ids = [r["event_id"] for r in rows]
        assert len(set(ids)) == len(ids)
        assert all(i.startswith("poisson-") for i in ids)

    def test_seed_makes_the_stochastic_arms_reproducible(self):
        a = build_plan("poisson", RATE, DURATION, seed=42)
        b = build_plan("poisson", RATE, DURATION, seed=42)
        c = build_plan("poisson", RATE, DURATION, seed=43)
        assert a == b
        assert a != c

    def test_unknown_arrival_process_is_rejected(self):
        with pytest.raises(ValueError, match="unknown arrival process"):
            build_plan("nonsense", RATE, DURATION)

    @pytest.mark.parametrize("rate,duration", [(0, 60), (-1, 60), (0.4, 0), (0.4, -1)])
    def test_non_positive_parameters_are_rejected(self, rate, duration):
        with pytest.raises(ValueError, match="must be positive"):
            build_plan("constant", rate, duration)


class TestWriteAndRate:
    def test_writes_a_readable_plan(self, temp_dir):
        rows = build_plan("constant", RATE, 60.0)
        out = write_plan(rows, temp_dir / "nested" / "plan.csv")
        with open(out, encoding="utf-8") as fh:
            back = list(csv.DictReader(fh))
        assert len(back) == len(rows)
        assert back[0]["event_id"] == rows[0]["event_id"]

    def test_achieved_rate(self):
        assert achieved_rate([{}] * 249, 600.0) == pytest.approx(0.415, abs=0.001)

    def test_achieved_rate_with_zero_duration_is_nan(self):
        assert np.isnan(achieved_rate([{}], 0))


class TestMain:
    def test_end_to_end_reports_achieved_versus_requested(self, temp_dir, capsys):
        out = temp_dir / "p.csv"
        assert main(["--arrival", "bursty", "--out", str(out)]) == 0
        printed = capsys.readouterr().out
        assert "bursty" in printed and "achieved" in printed and "requested" in printed
        assert out.exists()

    def test_defaults_to_the_measured_football_rate(self, temp_dir, capsys):
        assert main(["--out", str(temp_dir / "p.csv")]) == 0
        assert "0.415" in capsys.readouterr().out
