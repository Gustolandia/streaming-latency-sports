"""Tests for scripts/plan_speedup.py - target 100% branch coverage.

These exist because a whole campaign was lost to the bug this module prevents: --speedup 1
against a 120x-compressed plan replays at 120x, the run completes, and the numbers look
plausible. Every failure mode below is one that would otherwise be silent.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from plan_speedup import (  # noqa: E402
    baked_compression,
    speedup_for,
    expected_wall_seconds,
    achieved_rate,
    verify_rate,
    main,
)


def _plan(tmp, rows, name="plan.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t_sim_seconds", "t_emit_offset_s"])
        w.writeheader()
        w.writerows(rows)
    return p


def _compressed(tmp, factor=120.0, span=8400.0, n=100):
    """A plan shaped like make_replay_plan.py's output, with a baked-in compression."""
    return _plan(tmp, [{"t_sim_seconds": span * i / (n - 1),
                        "t_emit_offset_s": span * i / (n - 1) / factor} for i in range(n)])


class TestBakedCompression:
    def test_detects_the_real_plans_120x(self, temp_dir):
        assert baked_compression(_compressed(temp_dir)) == pytest.approx(120.0)

    def test_uncompressed_plan_is_one(self, temp_dir):
        assert baked_compression(_compressed(temp_dir, factor=1.0)) == pytest.approx(1.0)

    def test_arbitrary_factor(self, temp_dir):
        assert baked_compression(_compressed(temp_dir, factor=7.5)) == pytest.approx(7.5)

    def test_rows_with_unparseable_fields_are_skipped(self, temp_dir):
        p = _plan(temp_dir, [{"t_sim_seconds": "x", "t_emit_offset_s": "y"},
                             {"t_sim_seconds": 0, "t_emit_offset_s": 0},
                             {"t_sim_seconds": 120, "t_emit_offset_s": 1}])
        assert baked_compression(p) == pytest.approx(120.0)

    def test_empty_plan_raises(self, temp_dir):
        with pytest.raises(ValueError, match="no usable rows"):
            baked_compression(_plan(temp_dir, []))

    def test_zero_emission_span_raises_rather_than_defaulting(self, temp_dir):
        """Returning 1.0 here would silently reintroduce the bug."""
        p = _plan(temp_dir, [{"t_sim_seconds": 0, "t_emit_offset_s": 5},
                             {"t_sim_seconds": 100, "t_emit_offset_s": 5}])
        with pytest.raises(ValueError, match="zero emission span"):
            baked_compression(p)

    def test_zero_match_clock_span_raises(self, temp_dir):
        p = _plan(temp_dir, [{"t_sim_seconds": 7, "t_emit_offset_s": 0},
                             {"t_sim_seconds": 7, "t_emit_offset_s": 3}])
        with pytest.raises(ValueError, match="zero match-clock span"):
            baked_compression(p)


class TestSpeedupFor:
    def test_real_time_against_a_compressed_plan(self, temp_dir):
        assert speedup_for(_compressed(temp_dir), 1.0) == pytest.approx(1 / 120.0)

    def test_ten_times_real_time(self, temp_dir):
        assert speedup_for(_compressed(temp_dir), 10.0) == pytest.approx(10 / 120.0)

    def test_uncompressed_plan_needs_no_correction(self, temp_dir):
        assert speedup_for(_compressed(temp_dir, factor=1.0), 1.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("rate", [0, -1])
    def test_non_positive_rate_rejected(self, temp_dir, rate):
        with pytest.raises(ValueError, match="must be positive"):
            speedup_for(_compressed(temp_dir), rate)


class TestExpectedWallSeconds:
    def test_real_time_window_takes_its_own_length(self, temp_dir):
        assert expected_wall_seconds(_compressed(temp_dir), 180, 1.0) == pytest.approx(180)

    def test_accelerated_is_proportionally_shorter(self, temp_dir):
        assert expected_wall_seconds(_compressed(temp_dir), 600, 10.0) == pytest.approx(60)

    def test_window_longer_than_the_plan_is_capped_by_the_plan(self, temp_dir):
        p = _compressed(temp_dir, span=100.0)
        assert expected_wall_seconds(p, 9999, 1.0) == pytest.approx(100)

    def test_non_positive_rate_rejected(self, temp_dir):
        with pytest.raises(ValueError, match="must be positive"):
            expected_wall_seconds(_compressed(temp_dir), 100, 0)

    def test_plan_without_usable_rows_spans_zero(self, temp_dir):
        assert expected_wall_seconds(_plan(temp_dir, []), 100, 1.0) == pytest.approx(0.0)


def _producer(tmp, n=30, wall_s=60.0, name="producer.csv"):
    """A producer.csv whose send timestamps span `wall_s` seconds."""
    p = tmp / name
    t0 = 1_700_000_000_000_000_000
    step = int(wall_s * 1e9 / max(1, n - 1))
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t_prod_send_ns"])
        w.writeheader()
        w.writerows([{"t_prod_send_ns": t0 + i * step} for i in range(n)])
    return p


class TestAchievedRate:
    def test_measures_events_per_wall_second(self, temp_dir):
        events, wall, rate = achieved_rate(_producer(temp_dir, n=61, wall_s=60.0))
        assert events == 61 and wall == pytest.approx(60.0, abs=0.1)
        assert rate == pytest.approx(61 / 60.0, rel=0.01)

    def test_unparseable_rows_are_skipped(self, temp_dir):
        p = temp_dir / "p.csv"
        p.write_text("t_prod_send_ns\nxxx\n1000000000\n2000000000\n", encoding="utf-8")
        events, _, _ = achieved_rate(p)
        assert events == 2

    def test_too_few_events_raises(self, temp_dir):
        p = temp_dir / "p.csv"
        p.write_text("t_prod_send_ns\n1000000000\n", encoding="utf-8")
        with pytest.raises(ValueError, match="at least two events"):
            achieved_rate(p)

    def test_zero_span_raises(self, temp_dir):
        p = temp_dir / "p.csv"
        p.write_text("t_prod_send_ns\n1000000000\n1000000000\n", encoding="utf-8")
        with pytest.raises(ValueError, match="zero wall-clock span"):
            achieved_rate(p)


class TestVerifyRate:
    """The check that would have caught the lost campaign.

    Duration-based: a 60 s match-clock window at real time takes ~60 s of wall clock; at 120x
    it takes half a second. Event rate is deliberately NOT the test, because window density
    varies across a match and an early window is roughly twice the match average.
    """

    def test_correct_real_time_run_passes(self, temp_dir):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        prod = _producer(temp_dir, n=60, wall_s=60.0)
        v = verify_rate(prod, plan, max_t_sim=60, wanted_rate=1.0)
        assert v["ok"] and v["ratio"] == pytest.approx(1.0, rel=0.05)

    def test_a_120x_run_masquerading_as_real_time_is_caught(self, temp_dir):
        """The actual failure: flags said 1x, machine did 120x."""
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        prod = _producer(temp_dir, n=60, wall_s=0.5)
        v = verify_rate(prod, plan, max_t_sim=60, wanted_rate=1.0)
        assert not v["ok"] and v["ratio"] < 0.05

    def test_a_dense_window_does_not_trip_the_check(self, temp_dir):
        """A correct run whose window is twice the match average must still pass.

        This is the false alarm the rate-based version produced against real data.
        """
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(600)])
        prod = _producer(temp_dir, n=120, wall_s=60.0)   # 2 ev/s vs 1 ev/s average
        assert verify_rate(prod, plan, max_t_sim=60, wanted_rate=1.0)["ok"]

    def test_intentional_ten_times_is_accepted_when_asked_for(self, temp_dir):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        prod = _producer(temp_dir, n=60, wall_s=6.0)     # 60 s window at 10x
        assert verify_rate(prod, plan, max_t_sim=60, wanted_rate=10.0)["ok"]

    def test_window_longer_than_the_plan_is_capped(self, temp_dir):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(30)])
        prod = _producer(temp_dir, n=29, wall_s=29.0)
        assert verify_rate(prod, plan, max_t_sim=9999, wanted_rate=1.0)["ok"]

    def test_unusable_plan_raises(self, temp_dir):
        prod = _producer(temp_dir)
        with pytest.raises(ValueError, match="match-clock span"):
            verify_rate(prod, _plan(temp_dir, [], name="empty.csv"), max_t_sim=60)

    def test_zero_window_raises(self, temp_dir):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        with pytest.raises(ValueError, match="expected duration is zero"):
            verify_rate(_producer(temp_dir), plan, max_t_sim=0)


class TestMain:
    def test_verify_passes(self, temp_dir, capsys):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        prod = _producer(temp_dir, n=60, wall_s=60.0)
        assert main([str(plan), "--rate", "1", "--verify", str(prod),
                     "--max-t-sim", "60"]) == 0
        assert "replay-rate check: OK" in capsys.readouterr().out

    def test_verify_fails_with_exit_code_two(self, temp_dir, capsys):
        """Exit 2 is what makes run_all.sh refuse to start the campaigns."""
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(120)])
        prod = _producer(temp_dir, n=60, wall_s=0.5)
        assert main([str(plan), "--rate", "1", "--verify", str(prod),
                     "--max-t-sim", "60"]) == 2
        assert "WRONG RATE" in capsys.readouterr().out

    def test_verify_missing_producer(self, temp_dir, capsys):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(10)])
        assert main([str(plan), "--verify", str(temp_dir / "gone.csv"),
                     "--max-t-sim", "60"]) == 1
        assert "missing producer csv" in capsys.readouterr().err

    def test_verify_with_unusable_producer(self, temp_dir, capsys):
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(10)])
        bad = temp_dir / "bad.csv"
        bad.write_text("t_prod_send_ns\n1\n", encoding="utf-8")
        assert main([str(plan), "--verify", str(bad), "--max-t-sim", "60"]) == 1
        assert "at least two events" in capsys.readouterr().err

    def test_verify_requires_a_window(self, temp_dir, capsys):
        """Without the window there is nothing to compare the duration against."""
        plan = _plan(temp_dir, [{"t_sim_seconds": i, "t_emit_offset_s": i / 120.0}
                                for i in range(10)])
        prod = _producer(temp_dir)
        assert main([str(plan), "--verify", str(prod)]) == 1
        assert "needs --max-t-sim" in capsys.readouterr().err

    def test_reports_the_correction(self, temp_dir, capsys):
        assert main([str(_compressed(temp_dir)), "--rate", "1"]) == 0
        out = capsys.readouterr().out
        assert "120.0x" in out and "0.008333" in out

    def test_quiet_prints_only_the_number(self, temp_dir, capsys):
        assert main([str(_compressed(temp_dir)), "--rate", "10", "--quiet"]) == 0
        assert capsys.readouterr().out.strip() == "0.083333"

    def test_includes_expected_duration_when_asked(self, temp_dir, capsys):
        assert main([str(_compressed(temp_dir)), "--max-t-sim", "180"]) == 0
        assert "180s wall" in capsys.readouterr().out

    def test_missing_plan(self, temp_dir, capsys):
        assert main([str(temp_dir / "nope.csv")]) == 1
        assert "missing plan" in capsys.readouterr().err

    def test_unusable_plan_reports_and_exits_nonzero(self, temp_dir, capsys):
        assert main([str(_plan(temp_dir, []))]) == 1
        assert "no usable rows" in capsys.readouterr().err


class TestPlansWithDamagedRows:

    def test_a_row_with_no_usable_sim_time_is_skipped(self, temp_dir):
        """Plans are generated files, and a generator that died mid-row leaves one behind.

        `_sim_span` sets the expected wall time of a trial, so a damaged row must cost that
        row rather than the estimate.
        """
        import plan_speedup as ps
        p = temp_dir / "plan.csv"
        p.write_text("t_sim_seconds\n0\nnot-a-number\n600\n", encoding="utf-8")
        assert ps._sim_span(str(p)) == 600.0

    def test_a_plan_with_no_sim_column_at_all_spans_nothing(self, temp_dir):
        """No span is not a zero-length match; it is a plan this cannot speak about. The
        caller takes the minimum with max_t_sim, so zero is the conservative answer."""
        import plan_speedup as ps
        p = temp_dir / "plan.csv"
        p.write_text("other\n1\n", encoding="utf-8")
        assert ps._sim_span(str(p)) == 0.0

    def test_the_event_count_is_rows_not_lines(self, temp_dir):
        """The header is not an event; counting it would overstate the plan by one."""
        import plan_speedup as ps
        p = temp_dir / "plan.csv"
        p.write_text("event_id,t_sim_seconds\na,0\nb,1\nc,2\n", encoding="utf-8")
        assert ps._plan_events(str(p)) == 3
