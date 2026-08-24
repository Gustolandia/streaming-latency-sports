"""Tests for scripts/priority_pairs.py - target >=95% branch coverage.

The manuscript's mitigation headline is a range: real-time priority collapses the inversion
rate 7-80x. It was taken over eight matched pairs from three campaigns, two of which appeared
in the submission and six of which appeared nowhere -- including the pair at the range's lower
bound, which is the weakest result in the series and the one a sceptic would most want to see.
The range was right and reproduced from the artifacts; there was no path to it.

So these tests are about the two ways the range could go wrong now that it is derived: reading
the wrong files, and reading the wrong rows. A confounded pair is the crux -- the campaign
withheld those deliberately, and a range quietly built from them would be a stronger claim
than the campaign was willing to make.
"""
import csv
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import priority_pairs as pp  # noqa: E402

FIELDS = ["level", "rho_base", "rho_rt", "inv_base", "inv_rt", "ratio", "disjoint",
          "n_base", "n_rt", "confounded"]


def _csv(tmp_path, name, rows):
    path = tmp_path / name
    with open(path, "w", newline="", encoding="utf-8") as handle:
        w = csv.DictWriter(handle, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            full = {k: "" for k in FIELDS}
            full.update(r)
            w.writerow(full)
    return path


def _row(level, rho, base, rt, n=2985, disjoint=True, confounded=False):
    return {"level": level, "rho_base": rho, "rho_rt": rho, "inv_base": base, "inv_rt": rt,
            "ratio": (rt / base) if base else 0, "disjoint": str(disjoint),
            "n_base": n, "n_rt": n, "confounded": str(confounded)}


@pytest.fixture
def campaigns(tmp_path, monkeypatch):
    """Three files under a temporary model directory, as the real layout has."""
    monkeypatch.setattr(pp, "MODEL", str(tmp_path))

    def make(name, rows):
        _csv(tmp_path, name, rows)
        return name

    return make


class TestPairs:

    def test_the_factor_is_ordinary_over_real_time(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002)])
        out = pp.pairs((("E-A5", "a.csv"),))
        assert len(out) == 1
        assert out[0]["factor"] == pytest.approx(50.0)

    def test_the_stored_ratio_is_not_trusted(self, campaigns):
        """`ratio` is the reciprocal of the quoted factor. Two names for one quantity is how
        a sign gets inverted in a revision, so the factor is recomputed."""
        campaigns("a.csv", [dict(_row("l75", 0.75, 0.10, 0.002), ratio="999")])
        assert pp.pairs((("E-A5", "a.csv"),))[0]["factor"] == pytest.approx(50.0)

    def test_pairs_carry_their_campaign(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002)])
        campaigns("b.csv", [_row("l88", 0.88, 0.20, 0.004)])
        out = pp.pairs((("E-A5", "a.csv"), ("E-A5b", "b.csv")))
        assert {p["campaign"] for p in out} == {"E-A5", "E-A5b"}

    def test_pairs_are_ordered_by_load(self, campaigns):
        campaigns("a.csv", [_row("l95", 0.95, 0.30, 0.004), _row("l60", 0.60, 0.05, 0.002)])
        rhos = [p["rho"] for p in pp.pairs((("E-A5", "a.csv"),))]
        assert rhos == sorted(rhos)

    def test_a_missing_file_contributes_nothing(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002)])
        out = pp.pairs((("E-A5", "a.csv"), ("gone", "absent.csv")))
        assert len(out) == 1

    def test_an_unparseable_row_is_skipped(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002),
                            dict(_row("l88", 0.88, 0.20, 0.004), inv_base="not a number")])
        assert len(pp.pairs((("E-A5", "a.csv"),))) == 1

    def test_a_zero_real_time_rate_does_not_divide_by_zero(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.0)])
        assert pp.pairs((("E-A5", "a.csv"),))[0]["factor"] == float("inf")


class TestUsable:

    def test_a_confounded_pair_is_excluded(self, campaigns):
        """The campaign withholds a pair whose manipulation check failed. A range built from
        one would be a stronger claim than the campaign was willing to make."""
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002),
                            _row("l88", 0.88, 0.90, 0.001, confounded=True)])
        out = pp.usable((("E-A5", "a.csv"),))
        assert [p["level"] for p in out] == ["l75"]

    def test_confounded_pairs_are_counted_not_silently_dropped(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002),
                            _row("l88", 0.88, 0.90, 0.001, confounded=True)])
        assert pp.summary((("E-A5", "a.csv"),))["confounded"] == 1


class TestSummary:

    def test_the_range_spans_the_usable_pairs(self, campaigns):
        campaigns("a.csv", [_row("l60", 0.60, 0.05, 0.005),      # 10x
                            _row("l95", 0.95, 0.30, 0.003)])     # 100x
        s = pp.summary((("E-A5", "a.csv"),))
        assert s["pairs"] == 2
        assert s["factor_low"] == pytest.approx(10.0)
        assert s["factor_high"] == pytest.approx(100.0)

    def test_the_load_range_is_the_nominal_ladder_not_the_achieved_rho(self, campaigns):
        """Achieved rho at l60 is 0.6055; rounding it gives 61, a number nobody chose."""
        campaigns("a.csv", [_row("l60", 0.6055, 0.05, 0.005), _row("l95", 0.9501, 0.30, 0.003)])
        s = pp.summary((("E-A5", "a.csv"),))
        assert (s["level_low"], s["level_high"]) == (60, 95)
        assert s["rho_low"] == pytest.approx(0.6055)

    def test_disjointness_is_reported_over_the_whole_set(self, campaigns):
        campaigns("a.csv", [_row("l75", 0.75, 0.10, 0.002),
                            _row("l88", 0.88, 0.20, 0.004, disjoint=False)])
        assert pp.summary((("E-A5", "a.csv"),))["all_disjoint"] is False

    def test_an_empty_set_returns_zeros_rather_than_raising(self, campaigns):
        campaigns("a.csv", [])
        s = pp.summary((("E-A5", "a.csv"),))
        assert s["pairs"] == 0 and s["factor_low"] == 0.0 and s["level_low"] == 0

    def test_a_non_numeric_level_does_not_break_the_ladder(self, campaigns):
        campaigns("a.csv", [dict(_row("idle", 0.10, 0.01, 0.001)),
                            _row("l95", 0.95, 0.30, 0.003)])
        s = pp.summary((("E-A5", "a.csv"),))
        assert s["level_low"] == 95 and s["level_high"] == 95


class TestAgainstTheCommittedRecord:
    """The values the manuscript now prints, from the files that ship."""

    def test_eight_usable_pairs_from_three_campaigns(self):
        good = pp.usable()
        assert len(good) == 8
        assert {p["campaign"] for p in good} == {"E-A5", "E-A5b", "E-A7"}

    def test_the_range_is_the_one_the_abstract_quotes(self):
        s = pp.summary()
        assert round(s["factor_low"]) == 7
        assert round(s["factor_high"]) == 80
        assert (s["level_low"], s["level_high"]) == (60, 95)

    def test_every_usable_pair_has_disjoint_intervals(self):
        """The manuscript says so; if one stopped being disjoint the claim would weaken."""
        assert pp.summary()["all_disjoint"] is True

    def test_the_two_pairs_of_table_two_are_in_the_set(self):
        """Table II reports E-A5's two pairs; they must be the same rows this reads."""
        ea5 = [p for p in pp.usable() if p["campaign"] == "E-A5"]
        assert sorted(round(p["factor"]) for p in ea5) == [39, 54]


class TestTheReport:
    """`main` prints every matched pair behind the abstract's range.

    Round 17's finding was that six of the eight pairs appeared nowhere a reader could see
    them. This is the rendering that shows all eight, and until now it sat under a pragma.
    """

    def test_it_prints_one_line_per_usable_pair(self, capsys):
        assert pp.main() == 0
        out = capsys.readouterr().out
        assert out.count("\n") >= len(pp.usable()) + 3
        for pair in pp.usable():
            assert pair["level"] in out

    def test_it_prints_the_range_the_abstract_quotes(self, capsys):
        s = pp.summary()
        pp.main()
        out = capsys.readouterr().out
        assert "%d usable pairs" % s["pairs"] in out
        assert "factor %.0f-%.0fx" % (s["factor_low"], s["factor_high"]) in out
