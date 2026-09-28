"""Tests for scripts/cliff_shape.py: the two shapes worked out by hand, and made-up campaigns laid
out as the final ones are, read through the frozen judges with each shape in place of the data."""
import csv
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import cliff_shape as cs  # noqa: E402

#: The design's eight trips, as law_design.py places them for a slice s and a tick h.
DESIGN = {"p05s": lambda s, h: 0.5 * s, "p09s": lambda s, h: 0.9 * s,
          "c02h": lambda s, h: s + 0.2 * h, "c04h": lambda s, h: s + 0.4 * h,
          "c06h": lambda s, h: s + 0.6 * h, "c08h": lambda s, h: s + 0.8 * h,
          "f15h": lambda s, h: s + 1.5 * h, "f2sh": lambda s, h: 2 * (s + h)}


def write_run(where, backend, s, h, point, trip, rate, gotit=0.5, priority=False, verdict="count",
              language=None):
    where.mkdir(parents=True)
    (where / "queue_row.json").write_text(json.dumps(
        {"round": where.name.split("-r")[-1], "setup": "%s-%g-%g-%s" % (backend, s, h, point),
         "params": {"backend": backend, "slice_ns": int(s * 1e6), "tick_ms": h, "load_pct": 75,
                    "point": point, "priority": priority, "language": language}}),
        encoding="utf-8")
    (where / "integrity.json").write_text(json.dumps(
        {"verdict": verdict, "recorded": {"trip_median_ms": trip, "measured_negative_rate": rate,
                                          "gotit_median_ms": gotit}}), encoding="utf-8")


def campaign(root, name, backend, slices, ticks, rounds=2, shift=0.0):
    """Every design trip at each slice and tick, its rate the rest-of-a-slice shape's, a little
    scatter between rounds, and one go-first run and one run the integrity rule stopped."""
    runs = root / name / "runs"
    for r in range(1, rounds + 1):
        for s in slices:
            for h in ticks:
                for point, where in DESIGN.items():
                    trip = where(s, h) + 0.02 * r + shift
                    rate = 0.001 + 0.05 * cs.residual_rate(trip - 0.5, s, h) + 0.0005 * r
                    write_run(runs / ("%s-%g-%g-%s-r%d" % (backend, s, h, point, r)), backend, s,
                              h, point, trip, rate)
    s, h = slices[0], ticks[0]
    write_run(runs / ("%s-first-r1" % backend), backend, s, h, "p09s", 0.9 * s, 0.0,
              priority=True)
    write_run(runs / ("%s-stopped-r1" % backend), backend, s, h, "p09s", 0.9 * s, 0.9,
              verdict="stop")
    write_run(runs / ("%s-odd-r1" % backend), backend, s, h, "x11", 0.9 * s, 0.2)
    return name


def world(root):
    blocks = {"A1": [campaign(root, "c1", "redis", (3.0, 4.5), (1.0,)),
                     campaign(root, "c2", "redis", (3.0, 4.5), (1.0,), shift=0.05)],
              "A2 redis": [campaign(root, "k1", "redis", (1.5, 3.0), (1.0, 4.0, 10.0))]}
    judged_on = [("P1", "A1", {"tick_ms": 1.0, "anchor_ms": 3.0}),
                 ("P2", "A2 redis", {"tick_ms": 4.0}), ("P2c", "A2 redis", {})]
    return blocks, judged_on


class TestTheShapes:

    @pytest.mark.parametrize("trip,rate", [(2.0, 1.0), (3.0, 1.0), (3.25, 0.75), (4.0, 0.0),
                                           (9.0, 0.0)])
    def test_the_plans_formula(self, trip, rate):
        assert cs.plan_rate(trip, 3.0, 1.0) == pytest.approx(rate)

    @pytest.mark.parametrize("x,rate", [(-1.0, 1.0), (0.0, 1.0), (0.5, 1 - 0.25 / 6),
                                        (1.0, 1 - 1 / 6.0), (2.0, 0.5), (3.5, 0.25 / 6),
                                        (4.0, 0.0), (5.0, 0.0)])
    def test_the_rest_of_a_slice_and_a_tick(self, x, rate):
        """s = 3, h = 1: a rounded start over the first millisecond, a straight fall of a third
        per millisecond to the slice, and a rounded end over the last."""
        assert cs.residual_rate(x, 3.0, 1.0) == pytest.approx(rate)

    def test_when_the_tick_is_longer_than_the_slice_the_roles_swap(self):
        assert cs.residual_rate(1.0, 1.5, 10.0) == pytest.approx(1 - 1 / 30.0)
        assert cs.residual_rate(5.75, 1.5, 10.0) == pytest.approx(0.5)
        assert cs.residual_rate(11.0, 1.5, 10.0) == pytest.approx(0.25 / 30.0)

    def test_a_shape_replaces_each_runs_rate_at_its_own_trip(self):
        runs = [{"trip_ms": 3.5, "gotit_ms": 0.5, "slice_ms": 3.0, "tick_ms": None},
                {"trip_ms": 3.5, "gotit_ms": None, "slice_ms": 3.0},
                {"trip_ms": 3.5, "gotit_ms": 0.5, "slice_ms": None, "predicted_slice_ms": None}]
        plan = cs.shaped(runs, "plan")
        assert len(plan) == 1 and plan[0]["negative_rate"] == pytest.approx(0.5)
        assert cs.shaped(runs, "residual")[0]["negative_rate"] == pytest.approx(
            cs.residual_rate(3.0, 3.0, 1.0))
        a5 = [{"trip_ms": 2.0, "gotit_ms": 0.5, "slice_ms": None, "predicted_slice_ms": 2.8,
               "tick_ms": 4.0}]
        assert cs.shaped(a5, "plan")[0]["negative_rate"] == 1.0


class TestTheReading:

    def test_levels_as_shares_of_the_plateau(self, tmp_path):
        blocks, _ = world(tmp_path)
        runs = cs.gather(str(tmp_path), blocks["A1"])
        assert all(run["gotit_ms"] == 0.5 for run in runs)
        rows = cs.levels(runs)
        at = dict(((r["slice_ms"], r["point"]), r) for r in rows)
        assert at[(3.0, "p09s")]["of_p09s"] == pytest.approx(1.0)
        assert at[(4.5, "p05s")]["of_p09s"] > 1.5, "the rate falls before the slice"
        assert (3.0, "x11") not in at
        no_plateau = cs.levels([dict(runs[0], point="c02h")])
        assert no_plateau[0]["of_p09s"] is None

    def test_a_block_read_one_curve_per_slice_and_tick(self, tmp_path):
        blocks, _ = world(tmp_path)
        rows = cs.widths(cs.gather(str(tmp_path), blocks["A2 redis"]))
        assert sorted((r["tick_ms"], r["slice_ms"]) for r in rows) == [
            (1.0, 1.5), (1.0, 3.0), (4.0, 1.5), (4.0, 3.0), (10.0, 1.5), (10.0, 3.0)]
        lines = cs.width_lines(rows)
        assert set(lines) == {"redis, 1.5", "redis, 3"}
        assert lines["redis, 1.5"]["fitted"]["slope"] > 0.5
        assert lines["redis, 1.5"]["free"]["ratio_250"] > 1.0

    def test_a_width_missing_at_a_tick_gives_no_ratio(self):
        rows = [{"backend": "redis", "tick_ms": 1.0, "slice_ms": 3.0, "free_width_ms": None,
                 "fitted_width_ms": 1.0},
                {"backend": "redis", "tick_ms": 4.0, "slice_ms": 3.0, "free_width_ms": 3.0,
                 "fitted_width_ms": None}]
        found = cs.width_lines(rows)["redis, 3"]
        assert found["free"] == {"ratio_250": None, "ratio_100": None, "intercept": None,
                                 "slope": None}
        assert found["fitted"]["ratio_250"] is None and found["fitted"]["slope"] is None

    def test_a_curve_too_short_to_read_has_no_width(self):
        runs = [{"backend": "redis", "tick_ms": 1.0, "slice_ms": 3.0, "trip_ms": 2.7,
                 "negative_rate": 0.01, "point": "p09s"}]
        assert cs.widths(runs)[0]["free_width_ms"] is None

    def test_the_whole_reading_and_its_misfit(self, tmp_path):
        blocks, judged_on = world(tmp_path)
        found = cs.read(str(tmp_path), blocks, judged_on, {"A7": ["c1"]})
        assert found["plateaus"]["A7"]["redis"]["go_first"] == 0.0
        assert found["plateaus"]["A7"]["redis"]["ordinary"] == pytest.approx(0.020222, abs=1e-6)
        views = set(row["view"] for row in found["judged"])
        assert views == {"data", "plan", "residual"}
        p1 = [row for row in found["judged"] if row["prediction"] == "P1"]
        assert set(row["part"] for row in p1) == {""}
        plan = next(row for row in p1 if row["view"] == "plan")
        assert plan["free"] == pytest.approx(1.0, abs=0.05)
        assert found["misfit"]["residual"]["mean_gap"] < found["misfit"]["plan"]["mean_gap"]
        assert found["misfit"]["residual"]["points"] == found["misfit"]["plan"]["points"] == 14

    def test_a_split_answer_is_read_part_by_part(self, tmp_path):
        blocks, _ = world(tmp_path)
        runs = cs.gather(str(tmp_path), blocks["A1"])
        both = runs + [dict(run, backend="kafka") for run in runs]
        found = cs.judged(both, "P1", {"tick_ms": 1.0, "anchor_ms": 3.0})
        assert set(found) == {"kafka", "redis"}

    def test_no_points_leave_no_misfit(self):
        found = cs.misfit({"data": {}, "plan": {}, "residual": {}})
        assert found["plan"] == {"points": 0, "mean_gap": None, "mean_gap_past_half": None}


class TestTheCommand:

    def test_it_writes_every_table(self, tmp_path, capsys, monkeypatch):
        blocks, judged_on = world(tmp_path / "w")
        monkeypatch.setattr(cs, "BLOCKS", blocks)
        monkeypatch.setattr(cs, "JUDGED", judged_on)
        monkeypatch.setattr(cs, "PRIORITY", {"A7": ["c1"]})
        out = tmp_path / "out"
        assert cs.main(["--root", str(tmp_path / "w"), "--out", str(out)]) == 0
        said = capsys.readouterr().out
        assert "P1  A1" in said and "residual shape: levels off" in said
        judged = list(csv.DictReader(open(out / "cliff_judged.csv", encoding="utf-8")))
        assert len(judged) == 9
        levels = list(csv.DictReader(open(out / "cliff_levels.csv", encoding="utf-8")))
        assert {r["view"] for r in levels} == {"data", "plan", "residual"}
        widths = list(csv.DictReader(open(out / "cliff_widths.csv", encoding="utf-8")))
        assert len(widths) == 18
        summary = json.loads((out / "cliff_summary.json").read_text(encoding="utf-8"))
        assert set(summary) == {"misfit", "plateaus", "width_lines"}

    def test_it_prints_without_writing(self, tmp_path, capsys, monkeypatch):
        blocks, judged_on = world(tmp_path)
        monkeypatch.setattr(cs, "BLOCKS", blocks)
        monkeypatch.setattr(cs, "JUDGED", judged_on)
        assert cs.main(["--root", str(tmp_path)]) == 0
        assert "decides nothing" in capsys.readouterr().out

    def test_campaigns_that_are_not_there_are_an_error(self, tmp_path, capsys):
        assert cs.main(["--root", str(tmp_path)]) == 2
        assert "ERROR:" in capsys.readouterr().out
