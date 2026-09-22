"""Tests for scripts/law_curve.py, on made-up data whose answer is known.

The plan requires the analysis code to be written and tested on made-up data before the first real
run it reads. So every curve here is built from a plateau, a fall and a floor we chose, and the
test asks whether the module reads back what was put in -- with the runs sitting where they
actually landed, with noise, with a round missing, and with the cliff off the end of the design.
"""
import io
import json
import os
import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_curve as lc  # noqa: E402

SLICE, TICK = 3.0, 1.0
PLATEAU, FLOOR = 0.30, 0.01
#: Where a campaign puts its runs: two on the plateau, four across the cliff, two past it.
POINTS = {"p05s": 0.5 * SLICE, "p09s": 0.9 * SLICE, "c02h": SLICE + 0.2 * TICK,
          "c04h": SLICE + 0.4 * TICK, "c06h": SLICE + 0.6 * TICK, "c08h": SLICE + 0.8 * TICK,
          "f15h": SLICE + 1.5 * TICK, "f2sh": 2 * (SLICE + TICK)}


def rate_at(trip, slice_ms=SLICE, tick_ms=TICK, plateau=PLATEAU, floor=FLOOR):
    """The law exactly: a plateau, a straight fall one tick wide, and a floor."""
    share = min(1.0, max(0.0, (trip - slice_ms) / tick_ms))
    return plateau * (1 - share) + floor * share


def campaign(rounds=4, noise=0.0, seed=1, backend="kafka", **law):
    """A campaign's runs, each sitting at the trip it actually had."""
    rng = random.Random(seed)
    runs = []
    for round_ in range(1, rounds + 1):
        for point, trip in POINTS.items():
            landed = trip + (rng.gauss(0, 0.02) if noise else 0.0)
            rate = rate_at(landed, **law) + (rng.gauss(0, noise) if noise else 0.0)
            runs.append({"round": str(round_), "point": point, "backend": backend,
                         "slice_ms": law.get("slice_ms", SLICE), "trip_ms": landed,
                         "negative_rate": max(0.0, rate)})
    return runs


class TestTheFittedShape:

    def test_it_reads_back_the_plateau_fall_and_floor_it_was_given(self):
        runs = campaign()
        found = lc.fitted_shape([r["trip_ms"] for r in runs], [r["negative_rate"] for r in runs])
        assert found["start_ms"] == pytest.approx(SLICE, abs=0.1)
        assert found["width_ms"] == pytest.approx(TICK, abs=0.15)
        assert found["plateau"] == pytest.approx(PLATEAU, abs=0.01)
        assert found["floor"] == pytest.approx(FLOOR, abs=0.01)
        assert found["falls"] is True

    def test_a_wider_cliff_is_read_as_wider(self):
        runs = campaign()
        wide = campaign()
        for run in wide:
            run["negative_rate"] = rate_at(run["trip_ms"], tick_ms=3.0)
        found = lc.fitted_shape([r["trip_ms"] for r in wide], [r["negative_rate"] for r in wide])
        assert found["width_ms"] > lc.fitted_shape(
            [r["trip_ms"] for r in runs], [r["negative_rate"] for r in runs])["width_ms"]

    def test_noise_moves_the_answer_a_little_not_a_lot(self):
        runs = campaign(noise=0.02, seed=7)
        found = lc.fitted_shape([r["trip_ms"] for r in runs], [r["negative_rate"] for r in runs])
        assert found["start_ms"] == pytest.approx(SLICE, abs=0.35)
        assert found["plateau"] == pytest.approx(PLATEAU, abs=0.03)

    def test_a_curve_that_never_falls_is_reported_as_not_falling(self):
        flat = [{"trip_ms": t, "negative_rate": 0.2} for t in (1.0, 2.0, 3.0, 4.0, 5.0)]
        found = lc.fitted_shape([r["trip_ms"] for r in flat], [r["negative_rate"] for r in flat])
        assert found["plateau"] == pytest.approx(0.2, abs=1e-6)
        assert found["falls"] is False

    def test_too_few_runs_or_one_trip_is_no_shape_at_all(self):
        assert lc.fitted_shape([1.0, 2.0], [0.2, 0.1]) is None
        assert lc.fitted_shape([2.0, 2.0, 2.0], [0.2, 0.1, 0.15]) is None


class TestTheFreeShape:
    """A curve only required never to rise, which is the plan's second summary."""

    def test_a_falling_curve_is_left_as_it_is(self):
        trips, fitted = lc.free_shape([1.0, 2.0, 3.0], [0.3, 0.2, 0.1])
        assert trips == [1.0, 2.0, 3.0] and fitted == [0.3, 0.2, 0.1]

    def test_a_rise_is_pooled_with_what_came_before(self):
        trips, fitted = lc.free_shape([1.0, 2.0, 3.0], [0.3, 0.1, 0.3])
        assert fitted == [0.3, pytest.approx(0.2), pytest.approx(0.2)]
        assert all(b <= a for a, b in zip(fitted, fitted[1:])), "it never rises"

    def test_runs_at_the_same_trip_are_averaged_first(self):
        trips, fitted = lc.free_shape([1.0, 1.0, 2.0], [0.4, 0.2, 0.1])
        assert trips == [1.0, 2.0] and fitted == [pytest.approx(0.3), 0.1]

    def test_a_whole_campaign_never_rises(self):
        runs = campaign(noise=0.03, seed=3)
        _, fitted = lc.free_shape([r["trip_ms"] for r in runs], [r["negative_rate"] for r in runs])
        assert all(b <= a + 1e-12 for a, b in zip(fitted, fitted[1:]))


class TestReadingOffTheCurve:

    def test_the_halfway_point_lands_between_the_slice_and_a_tick_past_it(self):
        found = lc.read_off(campaign())
        assert SLICE <= found["halfway_ms"] <= SLICE + TICK
        assert found["plateau"] == pytest.approx(PLATEAU, abs=0.01)
        assert found["floor"] == pytest.approx(FLOOR, abs=0.01)

    def test_the_drop_is_wider_than_the_fall_when_the_points_beside_it_sit_far_away(self):
        """A straight fall crosses 90% and 10% 0.8 ticks apart; the curve drawn between the design
        points crosses them further apart, because the nearest points outside the cliff are 0.5
        and 0.7 ms away. The predictions about width compare ratios, where that spacing cancels."""
        found = lc.read_off(campaign())
        assert found["free_width_ms"] == pytest.approx(1.2, abs=0.2)

    def test_a_wider_tick_gives_a_wider_drop(self):
        runs = campaign()
        for run in runs:
            run["negative_rate"] = rate_at(run["trip_ms"], tick_ms=4.0)
        assert lc.read_off(runs)["free_width_ms"] > lc.read_off(campaign())["free_width_ms"]

    def test_the_levels_come_from_the_runs_the_plan_names(self):
        runs = campaign()
        plateau, floor = lc.levels(runs)
        assert plateau == pytest.approx(rate_at(POINTS["p09s"]), abs=1e-9)
        assert floor == pytest.approx(rate_at(POINTS["f2sh"]), abs=1e-9)

    def test_without_those_runs_the_fit_supplies_the_levels(self):
        runs = [r for r in campaign() if r["point"] not in ("p09s", "f2sh")]
        assert lc.levels(runs) == (None, None)
        found = lc.read_off(runs)
        assert found["plateau"] == pytest.approx(PLATEAU, abs=0.02)

    def test_levels_given_by_a_caller_win(self):
        found = lc.read_off(campaign(), plateau=0.5, floor=0.0)
        assert found["plateau"] == 0.5 and found["floor"] == 0.0

    def test_a_curve_that_never_falls_has_no_halfway_point(self):
        """Every trip is as far down as every other, so a number read off it would say nothing."""
        flat = [{"round": "1", "trip_ms": t, "negative_rate": 0.01}
                for t in (1.5, 2.7, 3.2, 3.4, 3.6, 3.8, 4.5, 8.0)]
        found = lc.read_off(flat)
        assert found["halfway_ms"] is None and found["free_width_ms"] is None
        assert found["plateau"] == pytest.approx(found["floor"])

    def test_too_few_runs_read_nothing(self):
        assert lc.read_off([{"trip_ms": 1.0, "negative_rate": 0.2}]) is None


class TestCrossing:

    def test_it_lands_between_the_two_points_it_falls_between(self):
        assert lc.crossing([1.0, 2.0], [0.3, 0.1], 0.2) == pytest.approx(1.5)

    def test_a_level_above_the_whole_curve_is_never_reached(self):
        assert lc.crossing([1.0, 2.0], [0.3, 0.1], 0.4) is None
        assert lc.crossing([], [], 0.1) is None

    def test_a_level_below_the_whole_curve_is_never_reached(self):
        assert lc.crossing([1.0, 2.0], [0.3, 0.1], 0.05) is None

    def test_a_flat_stretch_is_taken_at_its_end(self):
        assert lc.crossing([1.0, 2.0, 3.0], [0.2, 0.2, 0.1], 0.2) == 2.0


class TestResamplingWholeRounds:
    """A round is what a campaign repeats, so a round is what the resampling draws."""

    def test_the_rounds_are_kept_whole(self):
        runs = campaign(rounds=3)
        rounds = lc.by_round(runs)
        assert len(rounds) == 3 and all(len(r) == len(POINTS) for r in rounds)
        assert [r[0]["round"] for r in rounds] == ["1", "2", "3"]

    def test_ten_rounds_sort_in_the_order_they_ran(self):
        runs = campaign(rounds=11)
        assert [r[0]["round"] for r in lc.by_round(runs)][-2:] == ["10", "11"]

    def test_a_draw_has_as_many_rounds_as_the_campaign(self):
        runs = campaign(rounds=4)
        drawn = lc.resample(runs, random.Random(0))
        assert len(drawn) == len(runs)
        assert len(set(r["round"] for r in drawn)) <= 4

    def test_the_interval_holds_the_answer_and_the_same_seed_repeats_it(self):
        runs = campaign(noise=0.02, seed=5)
        found = lc.bootstrap(runs, lambda part: lc.read_off(part)["halfway_ms"], draws=60, seed=3)
        again = lc.bootstrap(runs, lambda part: lc.read_off(part)["halfway_ms"], draws=60, seed=3)
        assert found == again
        assert found["low"] <= found["value"] <= found["high"] and found["draws"] == 60

    def test_a_draw_the_statistic_cannot_be_read_from_is_left_out(self):
        """A resampling can leave a curve too short to read; it counts for nothing, not for zero."""
        asked = []

        def now_and_then(part):
            asked.append(len(part))
            return None if len(asked) % 2 == 0 else 1.0
        found = lc.bootstrap(campaign(rounds=4), now_and_then, draws=10, seed=1)
        assert found["value"] == 1.0 and found["draws"] == 5 and found["low"] == 1.0

    def test_an_interval_of_nothing_is_nothing(self):
        assert lc.interval([]) == (None, None)
        assert lc.interval([None, None]) == (None, None)

    def test_the_interval_is_the_middle_of_what_was_drawn(self):
        assert lc.interval(list(range(101)), level=0.90) == (5, 95)


class TestGrouping:

    def test_one_curve_per_backend_and_slice(self):
        runs = campaign(backend="kafka") + campaign(backend="redis")
        found = lc.groups(runs)
        assert sorted(found) == [("kafka", SLICE), ("redis", SLICE)]
        assert len(found[("kafka", SLICE)]) == 4 * len(POINTS)


class TestReadingACopiedCampaign:

    def write_run(self, folder, name, point, trip, rate, round_="1", slice_ns=3_000_000):
        run = folder / name
        run.mkdir(parents=True, exist_ok=True)
        (run / "queue_row.json").write_text(json.dumps(
            {"key": name, "round": round_, "setup": "A1-kafka-l75-%s" % point,
             "params": {"backend": "kafka", "point": point, "slice_ns": slice_ns,
                        "tick_ms": 1.0, "load_pct": 75, "priority": False, "cpus": None}}),
            encoding="utf-8")
        (run / "integrity.json").write_text(json.dumps(
            {"verdict": "count", "reasons": [],
             "recorded": {"trip_median_ms": trip, "measured_negative_rate": rate}}),
            encoding="utf-8")
        return run

    def campaign_on_disk(self, tmp_path, rounds=4):
        for round_ in range(1, rounds + 1):
            for point, trip in POINTS.items():
                self.write_run(tmp_path / "runs", "law_a1_r%03d-%s" % (round_, point), point,
                               trip, rate_at(trip), str(round_))
        return str(tmp_path / "runs")

    def test_every_field_a_judge_asks_a_run_for_is_one_this_gives_it(self, tmp_path):
        """The contract between what the judges read and what a run off the driver carries.

        A field this does not extract is None on every real run, silently, and the judge reading
        it has no way to know the difference between "the campaign did not do that" and "nobody
        wrote it down". Two predictions were lost that way. P7 compared the slice a machine
        reported against the slice each run was designed with, and A5 sets none, so it raised on
        every run of a finished campaign. P8 filters runs by which client sent them, and the
        language was never extracted, so it reported that A8's campaign had not tested P8 at all
        -- a silent null after eight hours of machine time.

        Both survived a suite at 100% branch coverage, because every test of a judge builds its
        runs from the made-up world, and that world sets fields this reader never reads. Coverage
        says the branch ran; it says nothing about whether the input can occur.
        """
        asked = set()
        for name in ("law_predictions.py", "law_curve.py"):
            text = (Path(lc.__file__).parent / name).read_text(encoding="utf-8")
            asked |= set(re.findall(r'run\.get\("(\w+)"', text))
        given = set(lc.read_runs(self.campaign_on_disk(tmp_path, rounds=1))[0])
        assert not (asked - given), (
            "the judges read %s off a run, and read_runs never puts it there"
            % ", ".join(sorted(asked - given)))

    def test_a_run_says_which_client_sent_it_and_where_it_took_its_note(self, tmp_path):
        """A8 is judged by the client and nothing else, so a run without it is invisible to P8.

        Where the note was taken decides no prediction, but plan version 16 asks P5(c) of the
        runs the got-it brake cannot judge by comparing the ones that share a note's place
        across the delays they ran at (D16-2). That comparison cannot be made from runs that do
        not say which place they used, and A8 is half inline.
        """
        run = self.write_run(tmp_path / "runs", "law_a8_r001-p09s", "p09s", 2.7, 0.03)
        row = json.loads((run / "queue_row.json").read_text(encoding="utf-8"))
        row["params"].update(language="java", ack_stamp="inline")
        (run / "queue_row.json").write_text(json.dumps(row), encoding="utf-8")
        found = lc.read_runs(str(tmp_path / "runs"))[0]
        assert found["language"] == "java" and found["ack_stamp"] == "inline"

    def test_a_run_of_any_other_block_carries_neither(self, tmp_path):
        """Every block but A8 leaves both unset, and an unset one is None rather than absent."""
        found = lc.read_runs(self.campaign_on_disk(tmp_path, rounds=1))[0]
        assert found["language"] is None and found["ack_stamp"] is None

    def test_it_reads_the_runs_the_driver_wrote(self, tmp_path):
        runs = lc.read_runs(self.campaign_on_disk(tmp_path, rounds=1))
        assert len(runs) == len(POINTS)
        assert runs[0]["slice_ms"] == 3.0 and runs[0]["backend"] == "kafka"

    def test_the_pair_it_ran_on_travels_with_the_runs(self, tmp_path):
        """Nothing may be pooled across pairs, so every run has to know which pair it ran on."""
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        (tmp_path / "COLLECTED.json").write_text(json.dumps({"profile": "matched"}),
                                                 encoding="utf-8")
        assert all(run["pair"] == "matched" for run in lc.read_runs(folder))
        assert lc.read_runs(folder, pair="arm")[0]["pair"] == "arm"

    def test_without_that_note_the_pair_is_simply_unknown(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        assert lc.read_runs(folder)[0]["pair"] is None

    def test_a_run_missing_its_numbers_is_left_out(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        run = self.write_run(tmp_path / "runs", "law_a1_r001-broken", "c02h", 3.2, 0.1)
        (run / "integrity.json").write_text(json.dumps({"recorded": {}}), encoding="utf-8")
        assert len(lc.read_runs(folder)) == len(POINTS)

    def test_a_run_whose_files_cannot_be_read_is_left_out(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        run = self.write_run(tmp_path / "runs", "law_a1_r001-bad", "c02h", 3.2, 0.1)
        (run / "queue_row.json").write_text("{oh dear", encoding="utf-8")
        assert len(lc.read_runs(folder)) == len(POINTS)

    def judged(self, tmp_path, verdict, name="law_a1_r001-stopped", rate=0.1):
        run = self.write_run(tmp_path / "runs", name, "c02h", 3.2, rate)
        found = json.loads((run / "integrity.json").read_text(encoding="utf-8"))
        found["verdict"] = verdict
        (run / "integrity.json").write_text(json.dumps(found), encoding="utf-8")
        return run

    def test_a_run_the_integrity_rule_stopped_decides_nothing(self, tmp_path):
        """A stopped run is one whose own instrument was in doubt, so it is not a measurement.

        run_integrity.py has always refused to compare a run against neighbours that did not
        count. The judges did not: read_runs kept anything with a trip and a rate, and every
        prediction so far was decided on curves that included them.
        """
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        self.judged(tmp_path, "stop")
        assert len(lc.read_runs(folder)) == len(POINTS)
        assert len(lc.read_runs(folder, counted_only=False)) == len(POINTS) + 1

    def test_a_run_marked_for_repeat_decides_nothing_either(self, tmp_path):
        """It was run again, so counting it counts one sitting of that setup twice."""
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        self.judged(tmp_path, "repeat")
        assert len(lc.read_runs(folder)) == len(POINTS)

    def test_the_split_names_every_run_it_leaves_out(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        self.judged(tmp_path, "stop")
        keep, skipped = lc.counted(folder)
        assert len(keep) == len(POINTS)
        assert [run["run"] for run in skipped] == ["law_a1_r001-stopped"]
        assert lc.left_out(skipped) == (
            "left out 1 run the integrity rule did not pass: law_a1_r001-stopped (stop)")

    def test_a_campaign_with_nothing_left_out_says_nothing(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path, rounds=1)
        keep, skipped = lc.counted(folder)
        assert len(keep) == len(POINTS) and skipped == []
        assert lc.left_out(skipped) is None

    def test_more_than_one_reads_as_more_than_one_and_in_order(self):
        """Named, and in a fixed order: a reader comparing two runs of the judge needs the same
        line for the same campaign."""
        assert lc.left_out([{"run": "law_a1_r002-b", "verdict": "repeat"},
                            {"run": "law_a1_r001-a", "verdict": "stop"}]) == (
            "left out 2 runs the integrity rule did not pass: "
            "law_a1_r001-a (stop), law_a1_r002-b (repeat)")

    def test_the_command_says_what_it_left_out_before_it_answers(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path)
        self.judged(tmp_path, "stop")
        out = io.StringIO()
        assert lc.main(["read", "--runs", folder], out=out) == 0
        assert "left out 1 run" in out.getvalue()

    def test_the_command_reads_a_campaign_and_writes_the_curves(self, tmp_path):
        folder = self.campaign_on_disk(tmp_path)
        out = io.StringIO()
        where = str(tmp_path / "curve.json")
        assert lc.main(["read", "--runs", folder, "--out", where], out=out) == 0
        assert "fall starts 3." in out.getvalue() and "halfway 3." in out.getvalue()
        with open(where, encoding="utf-8") as fh:
            assert "('kafka', 3.0)" in json.load(fh)

    def test_the_command_can_just_say_it(self, tmp_path):
        out = io.StringIO()
        assert lc.main(["read", "--runs", self.campaign_on_disk(tmp_path, rounds=1)],
                       out=out) == 0
        assert "kafka, 3.0: 8 runs" in out.getvalue()
        assert not list(tmp_path.glob("*.json")), "nothing is written unless it is asked for"

    def test_a_folder_with_no_runs_is_an_error_line(self, tmp_path):
        out = io.StringIO()
        assert lc.main(["read", "--runs", str(tmp_path)], out=out) == 2
        assert out.getvalue().startswith("ERROR:")

    def test_a_curve_too_short_to_read_says_so(self):
        assert lc.lines({("kafka", 3.0): None}) == ["kafka, 3.0: too few runs to read a curve"]
