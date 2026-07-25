"""Tests for scripts/fit_tail_index.py - target >=95% branch coverage.

This turns a mechanism into a rule, so the tests are built around the ways a power-law fit
flatters itself: too few points, too narrow a range, and a cross-check that agrees because it
was never really independent. Data is synthesised from a known alpha so the fit has to recover
it rather than merely produce something plausible.
"""
import csv
import math
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from fit_tail_index import (  # noqa: E402
    load_sweep,
    fit_power_law,
    moments_exist,
    cross_check,
    main,
)


def _sweep(tmp, points, name="sweep.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pad_bytes", "transport_ms", "inversion"])
        w.writeheader()
        for pad, t, inv in points:
            w.writerow({"pad_bytes": pad, "transport_ms": t, "inversion": inv})
    return p


def _from_alpha(alpha, C=0.24, ts=(0.7, 2.4, 14.6, 53.9)):
    return [(i * 4096, t, C * t ** (-alpha)) for i, t in enumerate(ts)]


def _traced(tmp, p_tail, arm="base", name="traced.csv"):
    p = tmp / name
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["tag", "arm", "p_tail", "inversion"])
        w.writeheader()
        w.writerow({"tag": "l88_" + arm, "arm": arm, "p_tail": p_tail, "inversion": 0.23})
    return p


class TestLoadSweep:
    def test_sorted_by_transport(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, [(0, 53.9, 0.06), (1, 0.7, 0.26)])))
        assert [r["transport_ms"] for r in rows] == [0.7, 53.9]

    def test_nonpositive_rows_dropped(self, temp_dir):
        """A zero rate has no logarithm and a zero transport has no ratio."""
        rows = load_sweep(str(_sweep(temp_dir, [(0, 0.7, 0.0), (1, 0.0, 0.2), (2, 2.4, 0.19)])))
        assert len(rows) == 1

    def test_malformed_rows_skipped(self, temp_dir):
        p = temp_dir / "bad.csv"
        p.write_text("pad_bytes,transport_ms,inversion\n0,notanumber,0.2\n", encoding="utf-8")
        assert load_sweep(str(p)) == []


class TestFit:
    def test_recovers_a_known_index(self, temp_dir):
        """Synthesised from alpha = 0.34; the fit must find it, not merely fit well."""
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        f = fit_power_law(rows)
        assert f["alpha"] == pytest.approx(0.34, abs=0.01)
        assert f["C"] == pytest.approx(0.24, rel=0.02)
        assert f["r2_log"] > 0.999

    def test_recovers_a_light_tail_too(self, temp_dir):
        """The estimator must not be biased toward the heavy answer we happen to want."""
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(2.5))))
        assert fit_power_law(rows)["alpha"] == pytest.approx(2.5, abs=0.01)

    def test_too_few_points_gives_nothing(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, [(0, 0.7, 0.26), (1, 2.4, 0.19)])))
        assert fit_power_law(rows) is None

    def test_identical_transports_cannot_be_fitted(self, temp_dir):
        """No spread on the x axis means no slope, and dividing would raise rather than warn."""
        rows = load_sweep(str(_sweep(temp_dir, [(0, 2.0, 0.2), (1, 2.0, 0.19), (2, 2.0, 0.18)])))
        assert fit_power_law(rows) is None

    def test_span_is_reported(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        assert fit_power_law(rows)["span"] == pytest.approx(53.9 / 0.7, rel=1e-6)


class TestMoments:
    def test_alpha_below_one_has_no_mean(self):
        m = moments_exist(0.339)
        assert not m["mean"] and not m["variance"]

    def test_alpha_between_one_and_two_has_a_mean_but_no_variance(self):
        m = moments_exist(1.5)
        assert m["mean"] and not m["variance"]

    def test_alpha_above_two_has_both(self):
        m = moments_exist(2.5)
        assert m["mean"] and m["variance"]


class TestCrossCheck:
    def test_agrees_when_the_rule_matches_the_trace(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        fit = fit_power_law(rows)
        expected = fit["C"] * 0.5 ** (-fit["alpha"])
        x = cross_check(fit, str(_traced(temp_dir, expected)), 0.5)
        assert x["checked"] and x["agree"] and x["ratio"] == pytest.approx(1.0, abs=0.01)

    def test_disagrees_when_the_trace_is_far_off(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        x = cross_check(fit_power_law(rows), str(_traced(temp_dir, 0.001)), 0.5)
        assert x["checked"] and not x["agree"]

    def test_needs_an_ordinary_priority_arm(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        x = cross_check(fit_power_law(rows), str(_traced(temp_dir, 0.18, arm="rt")), 0.5)
        assert not x["checked"] and "ordinary-priority" in x["why"]

    def test_missing_traced_artefact_is_not_fatal(self, temp_dir):
        rows = load_sweep(str(_sweep(temp_dir, _from_alpha(0.34))))
        assert not cross_check(fit_power_law(rows), str(temp_dir / "nope.csv"), 0.5)["checked"]

    def test_no_fit_means_no_check(self):
        assert not cross_check(None, "anything.csv", 0.5)["checked"]


class TestMain:
    def test_end_to_end_reports_the_rule_and_the_missing_mean(self, temp_dir, capsys):
        sweep = _sweep(temp_dir, _from_alpha(0.34))
        fit = fit_power_law(load_sweep(str(sweep)))
        traced = _traced(temp_dir, fit["C"] * 0.5 ** (-fit["alpha"]))
        rc = main(["--sweep", str(sweep), "--traced", str(traced),
                   "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert rc == 0
        assert "finite mean:     NO" in out and "STRUCTURALLY blind" in out
        assert "AGREE" in out
        vals = {r["quantity"]: r["value"]
                for r in csv.DictReader(open(temp_dir / "o" / "tail_index.csv"))}
        assert float(vals["alpha"]) == pytest.approx(0.34, abs=0.01)
        assert vals["finite_mean"] == "False"

    def test_a_light_tail_does_not_claim_a_missing_mean(self, temp_dir, capsys):
        sweep = _sweep(temp_dir, _from_alpha(2.5))
        _, = (None,)
        main(["--sweep", str(sweep), "--traced", str(temp_dir / "none.csv"),
              "--out", str(temp_dir / "o")])
        out = capsys.readouterr().out
        assert "finite mean:     yes" in out and "STRUCTURALLY blind" not in out

    def test_warns_when_the_span_is_too_narrow(self, temp_dir, capsys):
        """A slope over a 2x range is not a tail index, however well it fits."""
        sweep = _sweep(temp_dir, _from_alpha(0.34, ts=(1.0, 1.4, 2.0)))
        main(["--sweep", str(sweep), "--traced", str(temp_dir / "none.csv"),
              "--out", str(temp_dir / "o")])
        assert "too narrow to call this a tail index" in capsys.readouterr().out

    def test_missing_sweep(self, temp_dir, capsys):
        assert main(["--sweep", str(temp_dir / "nope.csv")]) == 1
        assert "missing sweep artefact" in capsys.readouterr().out

    def test_too_few_usable_points(self, temp_dir, capsys):
        sweep = _sweep(temp_dir, [(0, 0.7, 0.26), (1, 2.4, 0.19)])
        assert main(["--sweep", str(sweep), "--out", str(temp_dir / "o")]) == 1
        assert "at least 3 usable points" in capsys.readouterr().out
