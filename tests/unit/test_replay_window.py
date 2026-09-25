"""Tests for scripts/replay_window.py: M0's count and rate, read off the plan it replays."""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import replay_window as rw  # noqa: E402


def rows(offsets, first_sim=100):
    return [{"t_emit_offset_s": str(t), "t_sim_seconds": str(first_sim + i)}
            for i, t in enumerate(offsets)]


class TestWindow:

    def test_the_count_and_rate_are_the_plans_own_after_the_warm_up(self):
        """Offsets in plan seconds, replayed at 0.5: a send every 2 s of the run, from 0 to 20."""
        found = rw.window(rows([t / 2 for t in range(0, 21, 2)]), 0.5, 20.0, 4.0)
        assert found["planned"] == 9            # sends at 4, 6, ..., 20
        assert found["rate"] == pytest.approx(0.5)
        assert found["max_t_sim"] == 110         # the eleventh event, the last within the run

    def test_a_burst_counts_every_message_in_it(self):
        found = rw.window(rows([0.0, 5.0, 5.0, 5.0, 5.0, 9.0]), 1.0, 10.0, 2.0)
        assert found["planned"] == 5 and found["rate"] == pytest.approx(1.0)

    def test_times_are_counted_from_the_first_send(self):
        """The plan's first event is its own zero, as a run's warm-up starts at its first send."""
        assert rw.window(rows([50.0, 52.0, 58.0]), 1.0, 7.0, 1.0)["planned"] == 1

    def test_one_message_after_the_warm_up_has_no_rate(self):
        assert rw.window(rows([0.0, 5.0]), 1.0, 10.0, 2.0) == {
            "max_t_sim": 101, "planned": 1, "rate": 0.0}

    def test_nothing_after_the_warm_up(self):
        assert rw.window(rows([0.0, 1.0]), 1.0, 10.0, 2.0)["planned"] == 0

    @pytest.mark.parametrize("speedup,duration", [(0.0, 10.0), (1.0, 2.0)])
    def test_a_run_that_cannot_be_read(self, speedup, duration):
        with pytest.raises(ValueError, match="positive speed-up"):
            rw.window(rows([0.0]), speedup, duration, 2.0)

    def test_an_empty_plan(self):
        with pytest.raises(ValueError, match="no events"):
            rw.window([], 1.0, 10.0, 2.0)


class TestMain:

    def test_the_line_campaign_sh_reads(self, tmp_path):
        plan = tmp_path / "replay_plan.csv"
        plan.write_text("t_emit_offset_s,t_sim_seconds\n0.0,10\n2.5,40\n5.0,70\n7.5,99\n",
                        encoding="utf-8")
        out = io.StringIO()
        assert rw.main([str(plan), "--speedup", "0.5", "--duration", "12", "--warmup-s", "4"],
                       out=out) == 0
        # At 0.5 the four sends fall at 0, 5, 10 and 15 s of the run: three within its 12 s, the
        # last of them at match second 70, and two after its 4 s warm-up, 5 s apart.
        assert out.getvalue() == "70 2 0.2000\n"

    def test_a_plan_it_cannot_read(self, tmp_path):
        out = io.StringIO()
        assert rw.main([str(tmp_path / "missing.csv"), "--speedup", "1", "--duration", "10"],
                       out=out) == 2
        assert out.getvalue().startswith("ERROR: ")
