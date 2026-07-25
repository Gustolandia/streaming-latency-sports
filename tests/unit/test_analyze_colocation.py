"""Tests for scripts/analyze_colocation.py - target >=95% branch coverage.

The prediction under test has an awkward sign -- a FASTER path should be a LESS reliable
measurement -- so the tests are built to confirm the script reports the opposite sign, and no
change at all, just as readily. A script that can only produce the result its author wants is
not a test of anything.
"""
import csv
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_colocation as ac  # noqa: E402
from analyze_colocation import load_cells, compare, verdict, main  # noqa: E402


def _stats(rho, inv, mu, n=4000):
    return {"rho": rho, "n_events": n, "n_runs": 5, "mu": mu, "sigma_core": 0.2,
            "tails": {0.0: inv}, "runs_z_median": -5.0}


def _cells(tmp, names):
    for n in names:
        (tmp / n).mkdir(parents=True, exist_ok=True)
    return tmp


class TestLoadCells:
    def test_pairs_placements_by_load(self, temp_dir):
        _cells(temp_dir, ["remote_l0", "colocated_l0", "remote_l88", "colocated_l88"])
        with patch.object(ac, "condition_stats", return_value=_stats(0.1, 0.01, 0.5)):
            cells = load_cells(temp_dir, "runs")
        assert set(cells) == {"0", "88"}
        assert set(cells["0"]) == {"remote", "colocated"}

    def test_drops_a_load_with_only_one_placement(self, temp_dir):
        _cells(temp_dir, ["remote_l0", "remote_l88", "colocated_l88"])
        with patch.object(ac, "condition_stats", return_value=_stats(0.1, 0.01, 0.5)):
            assert set(load_cells(temp_dir, "runs")) == {"88"}

    def test_ignores_unknown_placements_and_files(self, temp_dir):
        _cells(temp_dir, ["remote_l0", "colocated_l0", "wibble_l0"])
        (temp_dir / "notes.txt").write_text("x", encoding="utf-8")
        with patch.object(ac, "condition_stats", return_value=_stats(0.1, 0.01, 0.5)):
            assert set(load_cells(temp_dir, "runs")["0"]) == {"remote", "colocated"}

    def test_skips_cells_without_usable_runs(self, temp_dir):
        _cells(temp_dir, ["remote_l0", "colocated_l0"])
        with patch.object(ac, "condition_stats", side_effect=[None, _stats(0.1, 0.01, 0.5)]):
            assert load_cells(temp_dir, "runs") == {}


class TestCompare:
    def test_detects_shorter_transport_and_a_higher_rate(self):
        r = compare("0", {"remote": _stats(0.02, 0.0037, 0.520),
                          "colocated": _stats(0.03, 0.0180, 0.095)})
        assert not r["confounded"]
        assert r["transport_fall"] > 5 and r["inv_rise"] > 1 and r["disjoint"]

    def test_vetoes_when_co_location_moved_the_load(self):
        """Broker CPU on the driver raises the rate for reasons unrelated to T_true."""
        r = compare("0", {"remote": _stats(0.02, 0.0037, 0.520),
                          "colocated": _stats(0.40, 0.0900, 0.095)})
        assert r["confounded"] and "moved load as well as T_true" in r["why"]

    def test_vetoes_when_utilisation_is_missing(self):
        r = compare("0", {"remote": _stats(None, 0.0037, 0.52),
                          "colocated": _stats(0.03, 0.018, 0.095)})
        assert r["confounded"] and "not recorded" in r["why"]

    def test_zero_transport_does_not_divide(self):
        r = compare("0", {"remote": _stats(0.02, 0.004, 0.5),
                          "colocated": _stats(0.02, 0.004, 0.0)})
        assert r["transport_fall"] == float("inf")

    def test_zero_remote_rate_does_not_divide(self):
        r = compare("0", {"remote": _stats(0.02, 0.0, 0.5),
                          "colocated": _stats(0.02, 0.01, 0.1)})
        assert r["inv_rise"] == float("inf")


class TestVerdict:
    IDLE_OK = {"load": "0", "confounded": False, "transport_fall": 5.5,
               "inv_rise": 4.9, "disjoint": True}

    def test_supports_the_mechanism_when_the_rate_rises(self):
        v = verdict([dict(self.IDLE_OK)])
        assert v["decided"] and v["supports_mechanism"] and v["on_idle"]

    def test_reports_the_opposite_sign(self):
        """Shorter transport LOWERING the rate would contradict P(stall > T_true)."""
        v = verdict([dict(self.IDLE_OK, inv_rise=0.2)])
        assert v["decided"] and v["opposite_sign"] and not v["supports_mechanism"]

    def test_reports_no_change(self):
        v = verdict([dict(self.IDLE_OK, inv_rise=1.02, disjoint=False)])
        assert v["decided"] and v["no_change"]

    def test_undecided_when_transport_did_not_move(self):
        """If co-location did not shorten transport, it did not act on T_true at all."""
        v = verdict([dict(self.IDLE_OK, transport_fall=1.05)])
        assert not v["decided"] and "did not shorten transport" in v["why"]

    def test_undecided_when_every_level_is_confounded(self):
        v = verdict([dict(self.IDLE_OK, confounded=True)])
        assert not v["decided"] and "utilisation check" in v["why"]

    def test_prefers_the_idle_pair(self):
        """The loaded pair carries the broker-CPU confound, so idle decides when present."""
        rows = [dict(self.IDLE_OK, load="88", inv_rise=0.5),
                dict(self.IDLE_OK, load="0", inv_rise=4.9)]
        v = verdict(rows)
        assert v["primary"] == "0" and v["supports_mechanism"]

    def test_falls_back_to_a_loaded_pair_and_flags_it(self):
        v = verdict([dict(self.IDLE_OK, load="88")])
        assert v["decided"] and not v["on_idle"] and v["primary"] == "88"


class TestMain:
    def _run(self, temp_dir, capsys, remote, colocated, loads=("0",)):
        # load_cells globs and sorts, so "colocated_l0" is visited before "remote_l0". The
        # side_effect sequence has to follow that order or the two arms swap silently and the
        # test asserts against a comparison that never happened.
        by_name = {}
        for lv in loads:
            by_name[f"remote_l{lv}"] = remote
            by_name[f"colocated_l{lv}"] = colocated
        _cells(temp_dir, list(by_name))
        stats = [by_name[n] for n in sorted(by_name)]
        with patch.object(ac, "condition_stats", side_effect=stats):
            rc = main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        return rc, capsys.readouterr().out

    def test_reports_the_mechanism_supported(self, temp_dir, capsys):
        rc, out = self._run(temp_dir, capsys, _stats(0.02, 0.0037, 0.520),
                            _stats(0.03, 0.0180, 0.095))
        assert rc == 0 and "MECHANISM SUPPORTED" in out
        assert "SIGN NOTHING ELSE PREDICTS" in out
        rows = list(csv.DictReader(open(temp_dir / "o" / "colocation.csv")))
        assert rows[0]["load"] == "0" and float(rows[0]["transport_fall"]) > 5

    def test_reports_the_opposite_sign(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(0.02, 0.0180, 0.520),
                           _stats(0.03, 0.0037, 0.095))
        assert "OPPOSITE SIGN" in out

    def test_reports_no_change(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(0.02, 0.0100, 0.520),
                           _stats(0.03, 0.0102, 0.095))
        assert "NO SIGNIFICANT CHANGE" in out

    def test_withholds_a_confounded_level(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys, _stats(0.02, 0.0037, 0.520),
                           _stats(0.45, 0.0900, 0.095))
        assert "CONFOUNDED" in out and "withheld" in out and "UNDECIDED" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--depth", str(temp_dir / "nope")]) == 1
        assert "missing campaign directory" in capsys.readouterr().out

    def test_no_paired_levels(self, temp_dir, capsys):
        _cells(temp_dir, ["remote_l0"])
        with patch.object(ac, "condition_stats", return_value=_stats(0.02, 0.004, 0.5)):
            rc = main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        assert rc == 1 and "no load level has both" in capsys.readouterr().out
