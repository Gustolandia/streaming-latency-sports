"""Tests for scripts/analyze_stamping_priority.py - target >=95% branch coverage.

This analysis can contradict the paper's own model, so the tests are written to check that it
CAN. Each mechanism's data is synthesised from its own prediction and must be recognised, and
the manipulation check is tested for its ability to veto a large, tempting effect.
"""
import csv
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_stamping_priority as asp  # noqa: E402
from analyze_stamping_priority import compare, load_arms, verdict, main  # noqa: E402


def _stats(rho, inv, n=4000):
    return {"rho": rho, "n_events": n, "n_runs": 5, "mu": 0.6, "sigma_core": 0.2,
            "tails": {0.0: inv}, "runs_z_median": -5.0}


def _cells(tmp, names):
    for n in names:
        (tmp / n).mkdir(parents=True, exist_ok=True)
    return tmp


class TestLoadArms:
    def test_pairs_arms_by_level(self, temp_dir):
        _cells(temp_dir, ["l75_base", "l75_rt", "l88_base", "l88_rt"])
        with patch.object(asp, "condition_stats", return_value=_stats(0.75, 0.05)):
            levels, unpaired = load_arms(str(temp_dir), "runs")
        assert set(levels) == {"l75", "l88"} and unpaired == []
        assert set(levels["l75"]) == {"base", "rt"}

    def test_drops_levels_with_one_arm(self, temp_dir):
        _cells(temp_dir, ["l75_base", "l88_base", "l88_rt"])
        with patch.object(asp, "condition_stats", return_value=_stats(0.8, 0.05)):
            levels, unpaired = load_arms(str(temp_dir), "runs")
        assert set(levels) == {"l88"} and unpaired == ["l75"]

    def test_ignores_unknown_arm_names_and_files(self, temp_dir):
        _cells(temp_dir, ["l75_base", "l75_rt", "l75_wibble"])
        (temp_dir / "l99_base").write_text("not a directory", encoding="utf-8")
        with patch.object(asp, "condition_stats", return_value=_stats(0.75, 0.05)):
            levels, _ = load_arms(str(temp_dir), "runs")
        assert set(levels["l75"]) == {"base", "rt"}

    def test_skips_cells_with_unusable_stats(self, temp_dir):
        _cells(temp_dir, ["l75_base", "l75_rt"])
        with patch.object(asp, "condition_stats", side_effect=[None, _stats(0.75, 0.05)]):
            levels, unpaired = load_arms(str(temp_dir), "runs")
        assert levels == {} and unpaired == ["l75"]


class TestCompare:
    def test_detects_a_collapse_at_matched_utilisation(self):
        r = compare("l88", {"base": _stats(0.877, 0.224), "rt": _stats(0.881, 0.004)})
        assert not r["confounded"] and r["ratio"] < 1 / 3 and r["disjoint"]

    def test_vetoes_when_the_manipulation_moved_load(self):
        """A big effect must still be withheld if rho did not hold. This is the E-B2 lesson."""
        r = compare("l88", {"base": _stats(0.877, 0.224), "rt": _stats(0.60, 0.004)})
        assert r["confounded"] and r["ratio"] is None
        assert "moved load as well as occupancy" in r["why"]

    def test_vetoes_when_utilisation_was_not_recorded(self):
        r = compare("l88", {"base": _stats(None, 0.224), "rt": _stats(0.88, 0.004)})
        assert r["confounded"] and "not recorded" in r["why"]

    def test_unchanged_rate_is_not_flagged_as_an_effect(self):
        r = compare("l75", {"base": _stats(0.75, 0.076), "rt": _stats(0.752, 0.075)})
        assert not r["confounded"] and 0.9 < r["ratio"] < 1.1 and not r["disjoint"]

    def test_zero_baseline_gives_no_ratio_rather_than_dividing(self):
        r = compare("l10", {"base": _stats(0.1, 0.0), "rt": _stats(0.1, 0.0)})
        assert r["ratio"] is None and not r["confounded"]


class TestVerdict:
    def test_supports_occupancy_when_every_level_collapses(self):
        rows = [{"confounded": False, "ratio": 0.02, "disjoint": True},
                {"confounded": False, "ratio": 0.05, "disjoint": True}]
        v = verdict(rows)
        assert v["decided"] and v["supports"] == "occupancy"

    def test_supports_utilisation_when_nothing_moves(self):
        """The verdict must be able to go against the paper's own model."""
        rows = [{"confounded": False, "ratio": 1.02, "disjoint": False},
                {"confounded": False, "ratio": 0.95, "disjoint": False}]
        v = verdict(rows)
        assert v["decided"] and v["supports"] == "utilisation"

    def test_a_large_fall_without_disjoint_intervals_is_not_enough(self):
        rows = [{"confounded": False, "ratio": 0.05, "disjoint": False}]
        assert not verdict(rows)["decided"]

    def test_intermediate_effect_is_reported_as_undecided(self):
        rows = [{"confounded": False, "ratio": 0.5, "disjoint": True}]
        v = verdict(rows)
        assert not v["decided"] and "too small" in v["why"]

    def test_levels_disagreeing_is_undecided(self):
        rows = [{"confounded": False, "ratio": 0.02, "disjoint": True},
                {"confounded": False, "ratio": 1.01, "disjoint": False}]
        assert not verdict(rows)["decided"]

    def test_all_confounded_is_undecided(self):
        assert not verdict([{"confounded": True, "ratio": None, "disjoint": None}])["decided"]


class TestMain:
    def _run(self, temp_dir, capsys, base, rt, names=("l88_base", "l88_rt")):
        _cells(temp_dir, list(names))
        with patch.object(asp, "condition_stats", side_effect=[base, rt]):
            rc = main(["--depth", str(temp_dir), "--runs", "runs",
                       "--out", str(temp_dir / "o")])
        return rc, capsys.readouterr().out

    def test_reports_occupancy_support(self, temp_dir, capsys):
        rc, out = self._run(temp_dir, capsys, _stats(0.877, 0.224), _stats(0.881, 0.004))
        assert rc == 0 and "OCCUPANCY MECHANISM SUPPORTED" in out
        rows = list(csv.DictReader(open(temp_dir / "o" / "stamping_priority.csv")))
        assert rows[0]["level"] == "l88" and float(rows[0]["ratio"]) < 0.1

    def test_reports_utilisation_support(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(0.877, 0.224), _stats(0.879, 0.223))
        assert "UTILISATION MECHANISM SUPPORTED" in out

    def test_withholds_a_confounded_comparison(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(0.877, 0.224), _stats(0.55, 0.004))
        assert "CONFOUNDED" in out and "withheld" in out
        assert "UNDECIDED" in out

    def test_notes_dropped_single_arm_levels(self, temp_dir, capsys):
        _cells(temp_dir, ["l75_base", "l88_base", "l88_rt"])
        with patch.object(asp, "condition_stats", return_value=_stats(0.88, 0.05)):
            main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        assert "l75 has only one arm" in capsys.readouterr().out

    def test_missing_utilisation_is_printed_not_crashed(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(None, 0.2), _stats(0.88, 0.004))
        assert "utilisation missing" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--depth", str(temp_dir / "nope")]) == 1
        assert "missing campaign directory" in capsys.readouterr().out

    def test_no_paired_levels(self, temp_dir, capsys):
        _cells(temp_dir, ["l75_base"])
        with patch.object(asp, "condition_stats", return_value=_stats(0.75, 0.05)):
            rc = main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        assert rc == 1 and "nothing to compare" in capsys.readouterr().out
