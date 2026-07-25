"""Tests for scripts/analyze_stall_duration.py - target >=95% branch coverage.

This script reports that a pre-registered prediction failed, so the tests must confirm it can
also report the prediction HOLDING, and that it does not announce a correction on data where
neither quantity moved. A script that can only deliver the interesting answer is not evidence.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_stall_duration import (  # noqa: E402
    load_cell,
    load_cells,
    compare,
    verdict,
    main,
)

FIELDS = ["t_wall_ns", "pid", "on_cpu_ns", "wait_ns", "slices", "n_threads",
          "schedstats_enabled"]


def _write_cell(d, procs, n_samples=3, dt_ns=500_000_000):
    """procs: {pid: (cpu_per_step, wait_per_step, slices_per_step)}. Cumulative counters."""
    d.mkdir(parents=True, exist_ok=True)
    p = d / "schedstat.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for i in range(n_samples):
            for pid, (c, wt, s) in procs.items():
                w.writerow({"t_wall_ns": i * dt_ns, "pid": pid,
                            "on_cpu_ns": c * i, "wait_ns": wt * i, "slices": s * i,
                            "n_threads": 3, "schedstats_enabled": 1})
    return p


def _arms(tmp, level, base, rt):
    _write_cell(tmp / f"{level}_base", base)
    _write_cell(tmp / f"{level}_rt", rt)
    return tmp


# Shaped after the measured l75 cells, because the effect only appears with heterogeneity:
# under real-time priority MOST processes get very short waits while one is stalled badly (the
# real run showed a 126 ms outlier, most likely RT throttling). So the per-process MEDIAN falls
# far more than the aggregate occupancy does -- which is the whole finding. Identical processes
# would make median and mean the same number and hide it.
BASE = {100: (1_000_000, 1_250_000, 5), 101: (1_000_000, 1_250_000, 5),
        102: (1_000_000, 1_250_000, 5), 103: (1_000_000, 1_250_000, 5)}
RT = {200: (1_000_000, 50_000, 5), 201: (1_000_000, 50_000, 5),
      202: (1_000_000, 50_000, 5), 203: (1_000_000, 3_000_000, 5),   # the throttled one
      900: (0, 0, 0), 901: (0, 0, 0)}      # the sudo wrappers: never on CPU


class TestLoadCell:
    def test_computes_occupancy_and_stall_duration(self, temp_dir):
        c = load_cell(_write_cell(temp_dir / "x", BASE))
        assert c["occupancy"] == pytest.approx(1.25 / 2.25, rel=1e-3)
        assert c["mean_wait_ms"] == pytest.approx(1.25 / 5, rel=1e-3)
        assert c["active"] == 4 and c["static"] == 0

    def test_wrappers_that_never_run_are_dropped_and_counted(self, temp_dir):
        """A sudo parent blocks on its child, so it is not runnable and its counters never
        move. It must not dilute the averages, and the drop must be visible, not silent."""
        c = load_cell(_write_cell(temp_dir / "x", RT))
        assert c["active"] == 4 and c["static"] == 2
        assert c["median_wait_ms"] == pytest.approx(0.01, rel=1e-3),             "the median must follow the many short waits, not the one long one"

    def test_missing_file_returns_none(self, temp_dir):
        assert load_cell(temp_dir / "nope.csv") is None

    def test_malformed_rows_skipped(self, temp_dir):
        d = temp_dir / "x"; d.mkdir()
        (d / "schedstat.csv").write_text(
            ",".join(FIELDS) + "\n0,notanint,1,1,1,1,1\n", encoding="utf-8")
        assert load_cell(d / "schedstat.csv") is None

    def test_single_sample_process_cannot_give_a_delta(self, temp_dir):
        assert load_cell(_write_cell(temp_dir / "x", BASE, n_samples=1)) is None

    def test_all_static_returns_none(self, temp_dir):
        assert load_cell(_write_cell(temp_dir / "x", {900: (0, 0, 0)})) is None

    def test_zero_slices_does_not_divide(self, temp_dir):
        """CPU time but no recorded timeslices: mean-per-slice is undefined, not infinite."""
        assert load_cell(_write_cell(temp_dir / "x", {100: (1_000_000, 500_000, 0)})) is None


class TestLoadCells:
    def test_pairs_arms_and_drops_unpaired(self, temp_dir):
        _arms(temp_dir, "l75", BASE, RT)
        _write_cell(temp_dir / "l88_base", BASE)          # no rt arm
        cells = load_cells(temp_dir)
        assert set(cells) == {"l75"}

    def test_ignores_unknown_arms_and_files(self, temp_dir):
        _arms(temp_dir, "l75", BASE, RT)
        _write_cell(temp_dir / "l75_other", BASE)
        (temp_dir / "notes.txt").write_text("x", encoding="utf-8")
        assert set(load_cells(temp_dir)["l75"]) == {"base", "rt"}


class TestVerdict:
    """The verdict rests on the AGGREGATE, not the per-process median.

    The median falls 20-143x on the real data while the aggregate falls 3-5x. Judging on the
    median would let skew across processes masquerade as a stronger mechanism, so these tests
    pin the conservative choice in place.
    """

    def test_a_high_median_does_not_rescue_a_low_aggregate(self):
        """The real case: median moves a lot, aggregate does not. Must NOT be called sufficient."""
        v = verdict([{"occ_fall": 1.95, "agg_fall": 4.19, "med_fall": 81.5, "slice_ratio": 2.5}])
        assert v["decided"] and not v["aggregate_explains"]
        assert v["skewed"], "a median 20x the aggregate must be flagged as skewed"
        assert not v["occupancy_prediction_held"]

    def test_a_large_aggregate_fall_is_sufficient(self):
        v = verdict([{"occ_fall": 1.9, "agg_fall": 25.0, "med_fall": 30.0, "slice_ratio": 1.1}])
        assert v["aggregate_explains"] and not v["skewed"]

    def test_reports_the_occupancy_prediction_holding(self):
        v = verdict([{"occ_fall": 15.0, "agg_fall": 20.0, "med_fall": 22.0, "slice_ratio": 1.0}])
        assert v["occupancy_prediction_held"]

    def test_flags_when_the_thread_is_scheduled_less_often(self):
        """'It waits as often, just more briefly' is false when the slice count drops."""
        v = verdict([{"occ_fall": 2.0, "agg_fall": 5.0, "med_fall": 10.0, "slice_ratio": 3.99}])
        assert not v["scheduled_as_often"]

    def test_equal_slice_counts_are_reported_as_scheduled_as_often(self):
        v = verdict([{"occ_fall": 2.0, "agg_fall": 5.0, "med_fall": 10.0, "slice_ratio": 1.0}])
        assert v["scheduled_as_often"]

    def test_undecided_without_rows(self):
        assert not verdict([])["decided"]

    def test_uses_the_median_across_levels(self):
        rows = [{"occ_fall": 1.5, "agg_fall": 3.0, "med_fall": 30.0, "slice_ratio": 1.0},
                {"occ_fall": 2.0, "agg_fall": 5.0, "med_fall": 10.0, "slice_ratio": 1.0},
                {"occ_fall": 1.8, "agg_fall": 4.0, "med_fall": 20.0, "slice_ratio": 1.0}]
        v = verdict(rows)
        assert v["occupancy_fall"] == pytest.approx(1.8)
        assert v["aggregate_fall"] == pytest.approx(4.0)

    def test_target_fall_is_adjustable(self):
        """If the inversion result were smaller, a 5x aggregate would suffice."""
        row = [{"occ_fall": 2.0, "agg_fall": 5.0, "med_fall": 6.0, "slice_ratio": 1.0}]
        assert not verdict(row)["aggregate_explains"]
        assert verdict(row, target_fall=8.0)["aggregate_explains"]


class TestCompare:
    def test_ratios_are_base_over_rt(self, temp_dir):
        cells = load_cells(_arms(temp_dir, "l75", BASE, RT))
        r = compare("l75", cells["l75"])
        assert r["occ_fall"] > 1 and r["med_fall"] == pytest.approx(25.0, rel=1e-3)
        assert r["agg_fall"] > 1 and r["wait_fall"] > 1
        assert r["slice_ratio"] == pytest.approx(1.0, rel=1e-6)

    def test_zero_denominator_gives_infinity_not_a_crash(self, temp_dir):
        base = {100: (1_000_000, 1_000_000, 5)}
        rt = {200: (1_000_000, 0, 5)}          # no waiting at all in the real-time arm
        cells = load_cells(_arms(temp_dir, "l75", base, rt))
        r = compare("l75", cells["l75"])
        assert r["med_fall"] == float("inf")


class TestMain:
    def test_end_to_end_reports_the_correction(self, temp_dir, capsys):
        _arms(temp_dir, "l75", BASE, RT)
        rc = main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "NEITHER QUANTITY ACCOUNTS" in out and "FAILED" in out
        assert "SKEWED" in out, "the median/aggregate divergence must be flagged"
        rows = list(csv.DictReader(open(temp_dir / "o" / "stall_duration.csv")))
        assert rows[0]["level"] == "l75"

    def test_end_to_end_reports_the_prediction_holding(self, temp_dir, capsys):
        base = {100: (1_000_000, 20_000_000, 5)}   # occupancy 0.952
        rt = {200: (1_000_000, 50_000, 5)}         # occupancy 0.048 -> a 20x fall
        _arms(temp_dir, "l75", base, rt)
        main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert "prediction held" in out

    def test_end_to_end_reports_no_mechanism(self, temp_dir, capsys):
        base = {100: (1_000_000, 1_000_000, 5)}
        rt = {200: (1_000_000, 900_000, 5)}
        _arms(temp_dir, "l75", base, rt)
        main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")])
        assert "NEITHER QUANTITY ACCOUNTS" in capsys.readouterr().out

    def test_end_to_end_reports_stall_length_carrying_the_result(self, temp_dir, capsys):
        """Occupancy fails but the AGGREGATE stall length is large: the corrected model wins
        on the conservative statistic, which is the only way it is allowed to win."""
        base = {100: (1_000_000, 1_000_000, 1), 101: (1_000_000, 1_000_000, 1)}
        rt = {200: (1_000_000, 900_000, 50), 201: (1_000_000, 900_000, 50)}
        _arms(temp_dir, "l75", base, rt)
        main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert "stall length carries the result" in out
        assert "NEITHER QUANTITY" not in out

    def test_end_to_end_notes_a_dropped_slice_count(self, temp_dir, capsys):
        base = {100: (1_000_000, 1_250_000, 20)}
        rt = {200: (1_000_000, 500_000, 5)}      # scheduled 4x less often
        _arms(temp_dir, "l75", base, rt)
        main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")])
        assert "LESS often" in capsys.readouterr().out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--depth", str(temp_dir / "nope")]) == 1
        assert "missing campaign directory" in capsys.readouterr().out

    def test_no_paired_cells(self, temp_dir, capsys):
        _write_cell(temp_dir / "l75_base", BASE)
        assert main(["--depth", str(temp_dir), "--out", str(temp_dir / "o")]) == 1
        assert "no load level has both arms" in capsys.readouterr().out
