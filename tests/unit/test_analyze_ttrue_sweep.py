"""Tests for scripts/analyze_ttrue_sweep.py - target >=95% branch coverage.

Two of three attempts to manipulate T_true have already failed, so the manipulation check is the
most important thing here and is tested hardest: it must veto the whole comparison when padding
did not lengthen transport, and when padding moved the load instead. The prediction's sign is
awkward -- a SLOWER path should be a MORE reliable measurement -- so the opposite sign and
no-change are tested as first-class outcomes.
"""
import csv
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_ttrue_sweep as ats  # noqa: E402
from analyze_ttrue_sweep import (  # noqa: E402
    load_cells,
    manipulation_check,
    verdict,
    main,
)


def _stats(rho, inv, mu, n=4000):
    return {"rho": rho, "n_events": n, "n_runs": 5, "mu": mu, "sigma_core": 0.2,
            "tails": {0.0: inv}, "runs_z_median": -5.0}


def _cells(tmp, pads):
    for p in pads:
        (tmp / f"pad{p}").mkdir(parents=True, exist_ok=True)
    return tmp


def _rows(triples):
    """(pad, transport_ms, inversion) -> loaded rows with intervals."""
    out = []
    for pad, mu, inv in triples:
        n = 4000
        half = 0.01
        out.append({"pad_bytes": pad, "rho": 0.88, "transport_ms": mu, "inversion": inv,
                    "ci_lo": max(0.0, inv - half), "ci_hi": inv + half, "n_events": n})
    return out


class TestLoadCells:
    def test_orders_by_pad_size_numerically(self, temp_dir):
        """Lexical ordering would put pad262144 before pad4096 and reverse the sweep."""
        _cells(temp_dir, [0, 4096, 65536, 262144])
        with patch.object(ats, "condition_stats", return_value=_stats(0.88, 0.2, 0.5)):
            rows = load_cells(temp_dir, "runs")
        assert [r["pad_bytes"] for r in rows] == [0, 4096, 65536, 262144]

    def test_ignores_non_pad_directories(self, temp_dir):
        _cells(temp_dir, [0, 4096])
        (temp_dir / "padding_notes").mkdir()
        (temp_dir / "notes.txt").write_text("x", encoding="utf-8")
        with patch.object(ats, "condition_stats", return_value=_stats(0.88, 0.2, 0.5)):
            assert len(load_cells(temp_dir, "runs")) == 2

    def test_skips_cells_without_usable_runs(self, temp_dir):
        _cells(temp_dir, [0, 4096])
        with patch.object(ats, "condition_stats", side_effect=[None, _stats(0.88, 0.2, 0.5)]):
            rows = load_cells(temp_dir, "runs")
        assert [r["pad_bytes"] for r in rows] == [4096]


class TestManipulationCheck:
    def test_passes_when_padding_lengthened_transport(self):
        rows = _rows([(0, 0.50, 0.25), (262144, 2.10, 0.06)])
        c = manipulation_check(rows)
        assert c["ok"] and c["rise"] > 4

    def test_fails_when_transport_barely_moves(self):
        """The E-A8 lesson: no movement in T_true means the inversion rates say nothing."""
        rows = _rows([(0, 0.50, 0.25), (262144, 0.55, 0.06)])
        c = manipulation_check(rows)
        assert not c["ok"] and "did not act on T_true" in c["why"]

    def test_fails_when_padding_moved_the_load_instead(self):
        rows = _rows([(0, 0.50, 0.25), (262144, 2.10, 0.06)])
        rows[0]["rho"] = 0.60
        rows[1]["rho"] = 0.95
        c = manipulation_check(rows)
        assert not c["ok"] and "moved load as well" in c["why"]

    def test_needs_two_pad_sizes(self):
        assert not manipulation_check(_rows([(0, 0.5, 0.25)]))["ok"]

    def test_zero_baseline_transport_does_not_divide(self):
        rows = _rows([(0, 0.0, 0.25), (262144, 2.1, 0.06)])
        assert not manipulation_check(rows)["ok"]

    def test_missing_utilisation_does_not_block_the_check(self):
        rows = _rows([(0, 0.50, 0.25), (262144, 2.10, 0.06)])
        for r in rows:
            r["rho"] = None
        c = manipulation_check(rows)
        assert c["ok"] and c["rho_spread"] is None


class TestVerdict:
    OK = {"ok": True, "rise": 4.2}

    def test_supports_when_the_rate_falls(self):
        v = verdict(_rows([(0, 0.50, 0.25), (262144, 2.10, 0.06)]), self.OK)
        assert v["decided"] and v["supports"] and not v["opposite"]

    def test_reports_the_opposite_sign(self):
        """Padding's CPU cost could dominate; that outcome must be reportable."""
        v = verdict(_rows([(0, 0.50, 0.06), (262144, 2.10, 0.25)]), self.OK)
        assert v["decided"] and v["opposite"] and not v["supports"]

    def test_reports_no_change_when_intervals_overlap(self):
        v = verdict(_rows([(0, 0.50, 0.250), (262144, 2.10, 0.252)]), self.OK)
        assert v["decided"] and v["no_change"] and not v["supports"]

    def test_withheld_when_the_manipulation_failed(self):
        v = verdict(_rows([(0, 0.5, 0.25), (262144, 0.55, 0.06)]),
                    {"ok": False, "why": "padding lengthened transport only 1.10x"})
        assert not v["decided"] and "1.10x" in v["why"]

    def test_no_inversions_at_baseline_gives_no_ratio(self):
        v = verdict(_rows([(0, 0.50, 0.0), (262144, 2.10, 0.06)]), self.OK)
        assert not v["decided"] and "no inversions" in v["why"]


class TestMain:
    def _run(self, temp_dir, capsys, cells):
        pads = [c[0] for c in cells]
        _cells(temp_dir, pads)
        stats = [_stats(0.88, inv, mu) for _pad, mu, inv in cells]
        with patch.object(ats, "condition_stats", side_effect=stats):
            rc = main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        return rc, capsys.readouterr().out

    def test_reports_the_mechanism_supported(self, temp_dir, capsys):
        rc, out = self._run(temp_dir, capsys,
                            [(0, 0.50, 0.2500), (4096, 0.90, 0.1800),
                             (65536, 1.40, 0.1100), (262144, 2.10, 0.0400)])
        assert rc == 0 and "MECHANISM SUPPORTED" in out
        assert "SIGN NOTHING ELSE PREDICTS" in out
        rows = list(csv.DictReader(open(temp_dir / "o" / "ttrue_sweep.csv")))
        assert [r["pad_bytes"] for r in rows] == ["0", "4096", "65536", "262144"]

    def test_reports_a_failed_manipulation(self, temp_dir, capsys):
        """The outcome E-A8 produced, and the one this axis keeps producing."""
        _, out = self._run(temp_dir, capsys,
                           [(0, 0.50, 0.2500), (262144, 0.54, 0.2450)])
        assert "FAILED" in out and "UNDECIDED" in out
        assert "resisted three manipulations" in out

    def test_reports_the_opposite_sign(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys,
                           [(0, 0.50, 0.0400), (262144, 2.10, 0.2500)])
        assert "OPPOSITE SIGN" in out

    def test_reports_no_change(self, temp_dir, capsys):
        _, out = self._run(temp_dir, capsys,
                           [(0, 0.50, 0.2500), (262144, 2.10, 0.2505)])
        assert "NO SIGNIFICANT CHANGE" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--depth", str(temp_dir / "nope")]) == 1
        assert "missing campaign directory" in capsys.readouterr().out

    def test_too_few_cells(self, temp_dir, capsys):
        _cells(temp_dir, [0])
        with patch.object(ats, "condition_stats", return_value=_stats(0.88, 0.2, 0.5)):
            rc = main(["--depth", str(temp_dir), "--runs", "runs", "--out", str(temp_dir / "o")])
        assert rc == 1 and "at least two pad sizes" in capsys.readouterr().out
