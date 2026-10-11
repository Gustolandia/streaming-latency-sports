"""The step test's clock stepper: when it steps, which way, and that it writes every step down.

The real wall clock can be set only by root on Linux, so these tests hand it a clock of their own:
a monotonic clock that sleeping advances, and a wall clock that the stepper's setter moves.
"""
import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import clock_stepper as cs  # noqa: E402


class FakeClock:
    """A monotonic clock that only sleeping moves, and a wall clock that runs with it plus
    whatever the stepper sets."""

    def __init__(self, wall_at_start=1_791_700_000_000_000_000):
        self.mono = 1_000_000_000
        self.offset = wall_at_start - self.mono
        self.slept = []

    def sleep(self, s):
        self.slept.append(s)
        self.mono += int(round(s * 1e9))

    def mono_ns(self):
        return self.mono

    def wall_ns(self):
        return self.mono + self.offset

    def set_wall_ns(self, ns):
        self.offset = ns - self.mono

    def parts(self):
        return self.sleep, self.mono_ns, self.wall_ns, self.set_wall_ns


class TestTheSchedule:

    def test_back_steps_once_a_period_and_never_at_the_end(self):
        assert cs.schedule("back", 1.0, 4.0) == [(1.0, -1), (2.0, -1), (3.0, -1)]

    def test_alternate_returns_each_step_half_a_period_later(self):
        assert cs.schedule("alternate", 1.0, 3.0) == [(1.0, -1), (1.5, +1), (2.0, -1), (2.5, +1)]

    def test_alternate_never_ends_on_a_back_step(self):
        """A back step whose return would fall at or after the end is not made at all."""
        steps = cs.schedule("alternate", 1.0, 2.4)
        assert steps == [(1.0, -1), (1.5, +1)] and sum(d for _, d in steps) == 0

    @pytest.mark.parametrize("pattern, period, seconds", [("sideways", 1.0, 5.0),
                                                           ("back", 0.0, 5.0),
                                                           ("back", 1.0, 0.0)])
    def test_a_schedule_that_cannot_be_kept_is_refused(self, pattern, period, seconds):
        with pytest.raises(ValueError):
            cs.schedule(pattern, period, seconds)

    def test_drawn_gaps_lie_between_half_a_period_and_one_and_a_half(self):
        """Freeze 34's steps: a fifth of a second apart on average, at no fixed point of a
        twenty-millisecond send cycle, and never at or after the end."""
        steps = cs.schedule("back", 0.2, 60.0, seed=7)
        times = [0.0] + [at for at, _ in steps]
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert all(0.1 <= g <= 0.3 for g in gaps) and all(d == -1 for _, d in steps)
        assert 0.18 < sum(gaps) / len(gaps) < 0.22 and steps[-1][0] < 60.0
        assert len({round((at * 1000) % 20, 3) for at, _ in steps}) > 200

    def test_a_seed_gives_the_same_steps_again_and_another_seed_others(self):
        assert cs.schedule("back", 0.2, 5.0, seed=11) == cs.schedule("back", 0.2, 5.0, seed=11)
        assert cs.schedule("back", 0.2, 5.0, seed=11) != cs.schedule("back", 0.2, 5.0, seed=12)

    def test_drawn_gaps_are_for_back_steps_only(self):
        """An alternate run's forward step is placed by its period; drawn gaps would let it fall
        after the next back step."""
        with pytest.raises(ValueError, match="back steps only"):
            cs.schedule("alternate", 0.2, 5.0, seed=3)


class TestTheSteps:

    def test_each_step_moves_the_wall_clock_and_is_written_down(self):
        clock, out = FakeClock(), io.StringIO()
        net = cs.run(cs.schedule("back", 1.0, 3.0), 20_000_000, *clock.parts(), out=out)
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        assert net == -40_000_000 and len(rows) == 2
        for r in rows:
            assert int(r["wall_after_ns"]) - int(r["wall_before_ns"]) == -20_000_000
            assert r["direction"] == "back" and r["step_ns"] == "20000000"
        assert [int(r["asked_mono_ns"]) for r in rows] == [1_000_000_000, 2_000_000_000]

    def test_alternate_leaves_the_clock_where_it_found_it(self):
        clock, out = FakeClock(), io.StringIO()
        before = clock.wall_ns() - clock.mono_ns()
        net = cs.run(cs.schedule("alternate", 1.0, 3.0), 200_000_000, *clock.parts(), out=out)
        assert net == 0 and clock.wall_ns() - clock.mono_ns() == before
        assert [r["direction"] for r in csv.DictReader(io.StringIO(out.getvalue()))] == \
            ["back", "forward", "back", "forward"]

    def test_a_step_already_late_is_made_without_sleeping(self):
        """If something held the stepper past a step's time, the step is made at once."""
        clock, out = FakeClock(), io.StringIO()

        def held():
            """A monotonic clock read by a stepper held two seconds between every reading."""
            clock.mono += 2_000_000_000
            return clock.mono

        cs.run([(1.0, -1)], 1_000_000, clock.sleep, held, clock.wall_ns, clock.set_wall_ns,
               out=out)
        assert len(list(csv.DictReader(io.StringIO(out.getvalue())))) == 1
        assert clock.slept == [], "the step was due a second before the stepper looked"

    def test_the_command_writes_its_log_and_says_where_the_clock_is(self, tmp_path, capsys):
        clock, log = FakeClock(), tmp_path / "steps.csv"
        assert cs.main(["--step-ms", "20", "--period-s", "1", "--seconds", "3.5",
                        "--pattern", "back", "--log", str(log)], clock=clock.parts()) == 0
        assert len(list(csv.DictReader(log.open(encoding="utf-8")))) == 3
        assert "made 3 steps of 20 ms, back; the wall clock is -60.000 ms" in capsys.readouterr().out

    def test_with_no_clock_given_it_takes_the_machines_and_a_run_too_short_to_step_sets_none(
            self, tmp_path, capsys):
        """The machine's clocks are taken only when asked for, and a run no longer than one
        period asks for no step, so nothing here reads or sets the wall clock."""
        log = tmp_path / "steps.csv"
        assert cs.main(["--step-ms", "20", "--period-s", "1", "--seconds", "1",
                        "--log", str(log)]) == 0
        assert list(csv.DictReader(log.open(encoding="utf-8"))) == []
        assert "made 0 steps of 20 ms, back; the wall clock is +0.000 ms" in capsys.readouterr().out

    def test_a_seeded_command_says_its_seed_and_steps_at_the_drawn_times(self, tmp_path, capsys):
        clock, log = FakeClock(), tmp_path / "steps.csv"
        assert cs.main(["--step-ms", "20", "--period-s", "0.2", "--seconds", "2", "--seed", "5",
                        "--log", str(log)], clock=clock.parts()) == 0
        rows = list(csv.DictReader(log.open(encoding="utf-8")))
        assert len(rows) == len(cs.schedule("back", 0.2, 2.0, seed=5)) > 0
        assert "gaps drawn from seed 5" in capsys.readouterr().out
