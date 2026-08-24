"""Tests for scripts/analyze_separability.py - target >=95% branch coverage.

This test discriminates two models, so the decisive property is that it must REJECT a scale
family as firmly as it accepts a two-state one. Both are synthesised from their defining
equations rather than hand-tuned, so the test cannot be satisfied by a statistic that merely
looks agreeable.
"""
import csv
import math
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_separability import (  # noqa: E402
    load_points,
    pair_spreads,
    verdict,
    main,
)

THRESHOLDS = [0.0, 0.5, 1.0, 2.0]


def _write(tmp, rows, name="collapse_points.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["condition", "rho", "threshold_ms", "z",
                                           "tail_mass", "n_events"])
        w.writeheader()
        w.writerows(rows)
    return p


def _two_state(tmp, weights, n_events=5000, survival=lambda c: math.exp(-0.8 * c)):
    """P(inv) = p(rho) * S(c): the SAME S for every condition, only p differs."""
    rows = []
    for i, (rho, p) in enumerate(weights):
        for c in THRESHOLDS:
            rows.append({"condition": f"bg{i}", "rho": rho, "threshold_ms": c, "z": 0,
                         "tail_mass": p * survival(c), "n_events": n_events})
    return _write(tmp, rows)


def _scale_family(tmp, sigmas, n_events=5000):
    """P(inv) = S(c / sigma): one shape, load stretches it. Must be rejected."""
    rows = []
    for i, (rho, s) in enumerate(sigmas):
        for c in THRESHOLDS:
            rows.append({"condition": f"bg{i}", "rho": rho, "threshold_ms": c, "z": 0,
                         "tail_mass": 0.4 * math.exp(-c / s), "n_events": n_events})
    return _write(tmp, rows)


class TestLoadPoints:
    def test_keeps_well_supported_estimates(self, temp_dir):
        p = _two_state(temp_dir, [(0.5, 0.2), (0.9, 0.4)])
        points, rho, dropped = load_points(str(p))
        assert set(points) == {"bg0", "bg1"} and dropped == 0
        assert rho["bg1"] == 0.9

    def test_drops_thin_estimates(self, temp_dir):
        """A tail mass from five events is noise on a log scale and must not be used."""
        rows = [{"condition": "a", "rho": 0.9, "threshold_ms": 0.0, "z": 0,
                 "tail_mass": 0.3, "n_events": 1000},
                {"condition": "a", "rho": 0.9, "threshold_ms": 5.0, "z": 0,
                 "tail_mass": 0.005, "n_events": 1000}]   # 5 events
        p = _write(temp_dir, rows)
        points, _, dropped = load_points(str(p))
        assert dropped == 1 and 5.0 not in points["a"]

    def test_zero_mass_is_dropped(self, temp_dir):
        rows = [{"condition": "a", "rho": 0.9, "threshold_ms": 0.0, "z": 0,
                 "tail_mass": 0.0, "n_events": 5000}]
        points, _, dropped = load_points(str(_write(temp_dir, rows)))
        assert dropped == 1 and points == {}

    def test_malformed_rows_skipped(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_text("condition,rho,threshold_ms,z,tail_mass,n_events\na,x,y,0,z,w\n",
                     encoding="utf-8")
        points, _, _ = load_points(str(p))
        assert points == {}

    def test_missing_rho_does_not_break_loading(self, temp_dir):
        rows = [{"condition": "a", "rho": "", "threshold_ms": c, "z": 0,
                 "tail_mass": 0.2, "n_events": 5000} for c in THRESHOLDS]
        points, rho, _ = load_points(str(_write(temp_dir, rows)))
        assert points["a"] and "a" not in rho


class TestPairSpreads:
    def test_two_state_data_gives_flat_spreads(self, temp_dir):
        p = _two_state(temp_dir, [(0.3, 0.02), (0.6, 0.10), (0.9, 0.30)])
        points, _, _ = load_points(str(p))
        ref, rows = pair_spreads(points)
        assert ref is not None and len(rows) == 2
        assert all(r["spread"] < 1e-6 for r in rows), "identical S means an exact vertical shift"

    def test_scale_family_data_gives_large_spreads(self, temp_dir):
        p = _scale_family(temp_dir, [(0.3, 0.4), (0.9, 4.0)])
        points, _, _ = load_points(str(p))
        _, rows = pair_spreads(points)
        assert rows and max(r["spread"] for r in rows) > 1.0

    def test_needs_two_comparable_conditions(self, temp_dir):
        p = _two_state(temp_dir, [(0.9, 0.3)])
        points, _, _ = load_points(str(p))
        ref, rows = pair_spreads(points)
        assert ref is None and rows == []

    def test_condition_with_too_few_thresholds_is_skipped(self, temp_dir):
        rows = [{"condition": "full", "rho": 0.9, "threshold_ms": c, "z": 0,
                 "tail_mass": 0.3 * math.exp(-0.8 * c), "n_events": 5000} for c in THRESHOLDS]
        rows += [{"condition": "thin", "rho": 0.5, "threshold_ms": 0.0, "z": 0,
                  "tail_mass": 0.1, "n_events": 5000}]
        points, _, _ = load_points(str(_write(temp_dir, rows)))
        _, out = pair_spreads(points)
        assert all(r["condition"] != "thin" for r in out)


class TestVerdict:
    def test_supports_a_two_state_process(self, temp_dir):
        p = _two_state(temp_dir, [(0.3, 0.02), (0.6, 0.10), (0.9, 0.30)])
        points, _, _ = load_points(str(p))
        _, rows = pair_spreads(points)
        v = verdict(rows)
        assert v["testable"] and v["supported"]
        assert "parallel" in v["why"]

    def test_rejects_a_scale_family(self, temp_dir):
        p = _scale_family(temp_dir, [(0.3, 0.4), (0.6, 1.5), (0.9, 4.0)])
        points, _, _ = load_points(str(p))
        _, rows = pair_spreads(points)
        v = verdict(rows)
        assert v["testable"] and not v["supported"]
        assert "not parallel" in v["why"]

    def test_one_bad_condition_fails_the_rule(self):
        """The rule is median AND worst-case, so a single wild condition must fail it."""
        rows = [{"condition": "a", "spread": 0.1}, {"condition": "b", "spread": 0.2},
                {"condition": "c", "spread": 2.5}]
        assert not verdict(rows)["supported"]

    def test_untestable_with_one_condition(self):
        assert not verdict([{"condition": "a", "spread": 0.1}])["testable"]


class TestMain:
    def test_end_to_end_supported(self, temp_dir, capsys):
        p = _two_state(temp_dir, [(0.3, 0.02), (0.6, 0.10), (0.9, 0.30)])
        rc = main(["--points", str(p), "--out", str(temp_dir / "out")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "TWO-STATE MODEL: SUPPORTED" in out
        rows = list(csv.DictReader(open(temp_dir / "out" / "separability.csv")))
        assert len(rows) == 2

    def test_end_to_end_rejects_scale_family(self, temp_dir, capsys):
        p = _scale_family(temp_dir, [(0.3, 0.4), (0.6, 1.5), (0.9, 4.0)])
        main(["--points", str(p), "--out", str(temp_dir / "out")])
        assert "NOT SUPPORTED" in capsys.readouterr().out

    def test_missing_file(self, temp_dir, capsys):
        assert main(["--points", str(temp_dir / "nope.csv")]) == 1
        assert "missing points file" in capsys.readouterr().out

    def test_insufficient_conditions(self, temp_dir, capsys):
        p = _two_state(temp_dir, [(0.9, 0.3)])
        assert main(["--points", str(p), "--out", str(temp_dir / "out")]) == 1
        assert "insufficient comparable conditions" in capsys.readouterr().out


class TestPairsWithTooLittleOverlap:

    def test_a_condition_sharing_too_few_thresholds_is_not_paired(self):
        """A spread computed over one or two thresholds is not evidence of a shape.

        The claim this analysis makes is that two conditions differ by a constant factor
        across the whole threshold ladder. Two points always lie on some line, so a pair with
        fewer than three shared thresholds cannot distinguish a scale family from anything
        else, and admitting it would inflate the count of pairs that agree.
        """
        points = {
            "ref": {0.0: 0.5, 0.5: 0.3, 1.0: 0.2, 2.0: 0.1},
            "thin": {0.0: 0.4, 0.5: 0.25},
            "full": {0.0: 0.4, 0.5: 0.25, 1.0: 0.15, 2.0: 0.08},
        }
        ref, rows = pair_spreads(points, min_thresholds=3)
        assert ref == "ref"
        assert sorted(r["condition"] for r in rows) == ["full"]

    def test_lowering_the_requirement_admits_the_thin_pair(self):
        """The threshold is a choice, so it must be the thing that decides."""
        points = {
            "ref": {0.0: 0.5, 0.5: 0.3},
            "thin": {0.0: 0.4, 0.5: 0.25},
        }
        assert pair_spreads(points, min_thresholds=3) == (None, [])
        assert len(pair_spreads(points, min_thresholds=2)[1]) == 1


class TestAConditionRichEnoughOnItsOwnButNotShared:

    def test_it_is_dropped_when_it_overlaps_the_reference_too_little(self):
        """The pair is what carries the claim, not either condition alone.

        A condition can be well supported at three of its own thresholds and still share only
        one with the reference -- different sweeps stop at different places. A log-ratio over
        one shared point is a single number with no spread, and reporting it as an agreeing
        pair would count a measurement that was never made.
        """
        points = {
            "ref": {0.0: 0.5, 0.5: 0.3, 1.0: 0.2, 2.0: 0.1},
            "elsewhere": {0.0: 0.4, 8.0: 0.05, 16.0: 0.02},
            "overlapping": {0.0: 0.4, 0.5: 0.25, 1.0: 0.15},
        }
        ref, rows = pair_spreads(points, min_thresholds=3)
        assert ref == "ref"
        assert [r["condition"] for r in rows] == ["overlapping"]
