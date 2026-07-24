"""Tests for scripts/analyze_collapse.py - target >=95% branch coverage.

These are the pre-registered H9/H10/F-Delta analyses, so both verdict directions are pinned
with synthetic corpora whose structure is known: a genuine scale family must pass H9, an
equal-core/unequal-tail mixture must falsify it, and the reproduction test must both accept
matching campaigns and reject diverging ones.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_collapse import (  # noqa: E402
    condition_timestamp,
    run_series,
    median_rho,
    condition_stats,
    collect_phase,
    wilson_interval,
    collapse_points,
    h9_verdict,
    h10_verdict,
    reproduction_rows,
    main,
)

T0 = 1_700_000_000_000_000_000

# A core with a known IQR (q1=2, q3=3 -> sigma_core=0.741) and median 2.0.
CORE = [1.0] * 100 + [2.0] * 200 + [3.0] * 100


def _run(runs_dir, run_id, transports_ms):
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(len(transports_ms)):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i, ms in enumerate(transports_ms):
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(ms * 1e6)})
    return d


def _condition(tmp, phase, name, ts, transports, rho=None):
    """One condition, one kafka run; negatives placed first so inversions are clustered."""
    cond = tmp / "depth" / phase / name
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    ordered = sorted(transports)          # negatives first = maximally clustered
    _run(tmp / "runs", f"concurrency_{ts}_kafka_feed1_rep1", ordered)
    if rho is not None:
        with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
            w.writeheader()
            w.writerow({"t_wall": 1, "rho": rho, "loadavg": 1.0})
    return cond


def _mix(negatives_at_minus1):
    return CORE + [-1.0] * negatives_at_minus1


class TestPlumbing:
    def test_run_series_order_and_missing(self, temp_dir):
        d = _run(temp_dir, "r1", [1.0, -2.0, 3.0])
        assert run_series(str(d)) == [1.0, -2.0, 3.0]
        e = temp_dir / "none"
        e.mkdir()
        assert run_series(str(e)) == []

    def test_condition_timestamp(self, temp_dir):
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000000", _mix(6), rho=0.1)
        assert condition_timestamp(
            str(temp_dir / "depth" / "ea3" / "bg0")) == "n5_20260101_000000"
        bare = temp_dir / "bare"
        bare.mkdir()
        assert condition_timestamp(str(bare)) is None

    def test_median_rho_paths(self, temp_dir):
        cond = _condition(temp_dir, "ea3", "bg2", "n5_20260101_000001", _mix(6), rho=0.25)
        assert median_rho(str(cond)) == pytest.approx(0.25)
        bare = temp_dir / "norho"
        bare.mkdir()
        assert median_rho(str(bare)) is None
        (bare / "utilisation.csv").write_text("t_wall,rho,loadavg\n1,xx,1\n", encoding="utf-8")
        assert median_rho(str(bare)) is None


class TestConditionStats:
    def test_core_scale_median_and_tails(self, temp_dir):
        cond = _condition(temp_dir, "ea3", "bg0", "n5_20260101_000002", _mix(10), rho=0.1)
        s = condition_stats(str(cond), str(temp_dir / "runs"))
        assert s["n_events"] == 410
        assert s["mu"] == pytest.approx(2.0)
        assert s["sigma_core"] == pytest.approx(1.0 / 1.349, rel=1e-3)
        assert s["tails"][0.0] == pytest.approx(10 / 410)
        assert s["tails"][0.5] == pytest.approx(10 / 410)   # all negatives sit at -1.0
        assert s["tails"][2.0] == pytest.approx(0.0)
        assert s["runs_z_median"] < -2                      # sorted series clusters inversions

    def test_none_when_too_few_events(self, temp_dir):
        cond = _condition(temp_dir, "ea3", "tiny", "n5_20260101_000003", [1.0] * 20)
        assert condition_stats(str(cond), str(temp_dir / "runs")) is None

    def test_none_without_timestamp(self, temp_dir):
        d = temp_dir / "x"
        d.mkdir()
        assert condition_stats(str(d), str(temp_dir / "runs")) is None

    def test_degenerate_core_falls_back_to_stdev(self, temp_dir):
        vals = [2.0] * 400 + [-1.0] * 10                    # IQR = 0
        cond = _condition(temp_dir, "ea3", "flat", "n5_20260101_000004", vals, rho=0.1)
        s = condition_stats(str(cond), str(temp_dir / "runs"))
        assert s["sigma_core"] > 0


class TestWilson:
    def test_zero_and_full(self):
        lo, hi = wilson_interval(0, 100)
        assert lo == pytest.approx(0.0, abs=1e-12) and hi < 0.05
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_contains_the_point_estimate(self):
        lo, hi = wilson_interval(20, 100)
        assert lo < 0.2 < hi


class TestCollapsePoints:
    def test_excludes_empty_and_median_crossing_tails(self, temp_dir):
        # half the run is negative: the c=0 tail IS the median and must be excluded
        vals = [1.0] * 100 + [-1.0] * 100
        _condition(temp_dir, "ea3", "half", "n5_20260101_000005", vals, rho=0.5)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        pts = collapse_points(stats)
        assert all(p["threshold_ms"] != 0.0 for p in pts)


class TestH9:
    def test_scale_family_is_supported(self, temp_dir):
        base = [2.0] * 400 + [-0.1] * 20 + [-0.6] * 15 + [-1.1] * 12 + [-2.1] * 8 + [-5.1] * 6
        _condition(temp_dir, "ea3", "s1", "n5_20260101_000006", base, rho=0.2)
        _condition(temp_dir, "ea3", "s3", "n5_20260101_000007",
                   [v * 3 for v in base], rho=0.8)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        v = h9_verdict(collapse_points(stats))
        assert v["testable"] and v["supported"], v

    def test_equal_core_unequal_tail_is_falsified(self, temp_dir):
        _condition(temp_dir, "ea3", "lo", "n5_20260101_000008", _mix(10), rho=0.2)
        _condition(temp_dir, "ea3", "hi", "n5_20260101_000009", _mix(60), rho=0.8)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        v = h9_verdict(collapse_points(stats))
        assert v["testable"] and not v["supported"], v
        assert v["worst_ratio"] > 3

    def test_single_condition_is_untestable(self, temp_dir):
        _condition(temp_dir, "ea3", "only", "n5_20260101_000010", _mix(10), rho=0.2)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        v = h9_verdict(collapse_points(stats))
        assert not v["testable"]


class TestH10:
    def test_tail_outgrowing_core_is_supported(self, temp_dir):
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000011", _mix(6), rho=0.1)
        _condition(temp_dir, "ea3", "bg7", "n5_20260101_000012", _mix(60), rho=0.85)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        v = h10_verdict(stats)
        assert v["testable"] and v["supported"], v
        assert v["tail_growth"] > 3 and v["core_growth"] == pytest.approx(1.0, rel=0.15)

    def test_proportional_growth_is_not_supported(self, temp_dir):
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000013", _mix(10), rho=0.1)
        # knee: everything scaled 10x -- core and tail grow together (scale family)
        _condition(temp_dir, "ea3", "bg7", "n5_20260101_000014",
                   [v * 10 for v in _mix(10)], rho=0.85)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        v = h10_verdict(stats)
        assert v["testable"] and not v["supported"], v

    def test_untestable_without_both_ends(self, temp_dir):
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000015", _mix(10), rho=0.1)
        stats = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        assert not h10_verdict(stats)["testable"]


class TestReproduction:
    def test_matching_campaigns_overlap(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg2", "n5_20260101_000016", _mix(12), rho=0.25)
        _condition(temp_dir, "ea3", "bg2", "n5_20260101_000017", _mix(10), rho=0.24)
        old = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea_sat"])
        new = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        rows = reproduction_rows(old, new)
        assert rows and all(r["ci_overlap"] for r in rows)

    def test_diverging_campaigns_fail_to_overlap(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg2", "n5_20260101_000018", _mix(8), rho=0.25)
        _condition(temp_dir, "ea3", "bg2", "n5_20260101_000019", _mix(120), rho=0.25)
        old = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea_sat"])
        new = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        rows = reproduction_rows(old, new)
        assert rows and not all(r["ci_overlap"] for r in rows)

    def test_no_rho_match_gives_no_rows(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg2", "n5_20260101_000020", _mix(10), rho=0.20)
        _condition(temp_dir, "ea3", "bg8", "n5_20260101_000021", _mix(10), rho=0.90)
        old = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea_sat"])
        new = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        assert reproduction_rows(old, new) == []

    def test_conditions_without_rho_are_skipped_on_both_sides(self, temp_dir):
        """A condition whose sampler trace is missing cannot be matched on utilisation."""
        _condition(temp_dir, "ea_sat", "bg2", "n5_20260101_000030", _mix(10), rho=None)
        _condition(temp_dir, "ea_sat", "bgX", "n5_20260101_000031", _mix(10), rho=0.25)
        _condition(temp_dir, "ea3", "bg2", "n5_20260101_000032", _mix(10), rho=0.25)
        _condition(temp_dir, "ea3", "bgY", "n5_20260101_000033", _mix(10), rho=None)
        old = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea_sat"])
        new = collect_phase(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3"])
        rows = reproduction_rows(old, new)
        assert rows and all(r["old_condition"] == "ea_sat/bgX" for r in rows)
        assert all(r["new_condition"] == "ea3/bg2" for r in rows)


class TestMain:
    def test_end_to_end(self, temp_dir, capsys):
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000022", _mix(6), rho=0.1)
        _condition(temp_dir, "ea3", "bg7", "n5_20260101_000023", _mix(60), rho=0.85)
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000024", _mix(7), rho=0.11)
        rc = main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "H9" in out and "H10" in out and "F-Delta reproduction" in out
        assert (temp_dir / "model" / "collapse_points.csv").exists()
        assert (temp_dir / "model" / "fdelta_reproduction.csv").exists()

    def test_missing_new_phase(self, temp_dir, capsys):
        (temp_dir / "depth").mkdir()
        assert main(["--depth-dir", str(temp_dir / "depth"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--out", str(temp_dir / "model")]) == 1
        assert "no usable conditions" in capsys.readouterr().out

    def test_untestable_verdicts_and_no_reproduction_pairs(self, temp_dir, capsys):
        """One new condition, no old campaign: both verdicts untestable, no matched pairs."""
        _condition(temp_dir, "ea3", "bg0", "n5_20260101_000025", _mix(6), rho=0.1)
        rc = main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.count("UNTESTABLE") == 2
        assert "no rho-matched condition pairs" in out
        assert not (temp_dir / "model" / "fdelta_reproduction.csv").exists()
