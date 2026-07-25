"""Tests for scripts/analyze_knee.py - target >=95% branch coverage.

This decides whether a withdrawn claim is restored, so the bar is set by tests rather than by
whoever reads the output. Both verdicts are pinned, and so is the precondition that the sweep
actually reached the interval where the two forms disagree -- a fit on points below rho=0.9
cannot discriminate no matter how good its R^2 looks.
"""
import csv
import math
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_knee import (  # noqa: E402
    condition_timestamp,
    median_rho,
    condition_inversion,
    collect,
    coverage,
    verdict,
    main,
)

T0 = 1_700_000_000_000_000_000


def _run(runs_dir, run_id, n_events, n_negative):
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(n_events):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i in range(n_events):
            delta = -1.0 if i < n_negative else 1.0
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(delta * 1e6)})
    return d


def _cond(tmp, phase, name, ts, rho, inversion, n_events=200):
    cond = tmp / "depth" / phase / name
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    _run(tmp / "runs", f"concurrency_{ts}_kafka_feed1_rep1",
         n_events, round(inversion * n_events))
    with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
        w.writeheader()
        w.writerow({"t_wall": 1, "rho": rho, "loadavg": 1.0})
    return cond


def _ladder(tmp, rhos, shape, phase="ea4", scale=0.004):
    """Build conditions whose inversion rate follows a chosen functional form."""
    for i, r in enumerate(rhos):
        y = scale * (r / (1 - r)) if shape == "mg1" else scale * math.exp(4.7 * r)
        y = min(y, 0.49)
        _cond(tmp, phase, f"l{i}", f"n5_2026010{i % 10}_00000{i % 10}", r, y)


class TestPlumbing:
    def test_timestamp_rho_and_inversion(self, temp_dir):
        cond = _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.95, 0.25)
        assert condition_timestamp(str(cond)) == "n5_20260101_000000"
        assert median_rho(str(cond)) == 0.95
        assert condition_inversion(str(cond), str(temp_dir / "runs")) == 0.25

    def test_missing_pieces_are_none(self, temp_dir):
        d = temp_dir / "bare"
        d.mkdir()
        assert condition_timestamp(str(d)) is None
        assert median_rho(str(d)) is None
        assert condition_inversion(str(d), str(temp_dir)) is None

    def test_unparseable_rho(self, temp_dir):
        d = temp_dir / "bad"
        d.mkdir()
        (d / "utilisation.csv").write_text("t_wall,rho,loadavg\n1,x,1\n", encoding="utf-8")
        assert median_rho(str(d)) is None

    def test_malformed_run_is_skipped(self, temp_dir):
        cond = _cond(temp_dir, "ea4", "l0", "n5_20260101_000001", 0.9, 0.2)
        run = temp_dir / "runs" / "concurrency_n5_20260101_000001_kafka_feed1_rep1"
        (run / "consumer_events.csv").write_text("event_id,t_consume_ns\ne0,x\n", encoding="utf-8")
        assert condition_inversion(str(cond), str(temp_dir / "runs")) is None


class TestCollect:
    def test_pools_phases_sorted_by_rho(self, temp_dir):
        _cond(temp_dir, "ea3", "bg0", "n5_20260101_000000", 0.25, 0.004)
        _cond(temp_dir, "ea4", "l99", "n5_20260101_000001", 0.98, 0.30)
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea3", "ea4"])
        assert [r["rho"] for r in rows] == [0.25, 0.98]
        assert rows[1]["phase"] == "ea4"

    def test_conditions_without_rho_are_dropped(self, temp_dir):
        cond = temp_dir / "depth" / "ea4" / "l0"
        (cond / "concurrency_concurrency_n5_20260101_000000").mkdir(parents=True)
        _run(temp_dir / "runs", "concurrency_n5_20260101_000000_kafka_feed1_rep1", 100, 10)
        assert collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"]) == []

    def test_non_directories_ignored(self, temp_dir):
        _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.9, 0.2)
        (temp_dir / "depth" / "ea4" / "notes.txt").write_text("x", encoding="utf-8")
        assert len(collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])) == 1


class TestCoverage:
    def test_detects_reaching_the_interval(self):
        rows = [{"rho": r} for r in (0.5, 0.88, 0.95, 0.98)]
        c = coverage(rows)
        assert c["sufficient"] and c["n_high"] == 2 and c["max_rho"] == 0.98

    def test_detects_not_reaching_it(self):
        c = coverage([{"rho": r} for r in (0.25, 0.5, 0.878)])
        assert not c["sufficient"] and c["n_high"] == 0


class TestVerdict:
    def test_restored_when_mg1_wins_with_high_points(self, temp_dir):
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "mg1")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert v["restored"], v["reason"]
        assert "beats the best alternative" in v["reason"]

    def test_withdrawal_stands_when_the_data_is_exponential(self, temp_dir):
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "exp")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert not v["restored"]
        assert "indistinguishable" in v["reason"]

    def test_cannot_discriminate_without_high_points(self, temp_dir):
        """Even perfectly M/G/1-shaped data below the knee must not restore the claim."""
        _ladder(temp_dir, [0.1, 0.3, 0.5, 0.7, 0.85], "mg1")
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert not v["restored"]
        assert "did not reach the interval" in v["reason"]

    def test_saturated_points_are_excluded_from_the_fit(self, temp_dir):
        _ladder(temp_dir, [0.25, 0.5, 0.88, 0.95, 0.98], "mg1")
        _cond(temp_dir, "ea4", "sat", "n5_20260102_000000", 1.0, 0.40)
        rows = collect(str(temp_dir / "depth"), str(temp_dir / "runs"), ["ea4"])
        v = verdict(rows)
        assert v["coverage"]["max_rho"] == 0.98, "rho=1 must not count as coverage"


class TestMain:
    def test_end_to_end_reports_a_verdict(self, temp_dir, capsys):
        _ladder(temp_dir, [0.25, 0.5, 0.75, 0.88, 0.95, 0.98], "mg1")
        rc = main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
                   "--phases", "ea4", "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "FUNCTIONAL FORM:" in out and "<- new" in out
        rows = list(csv.DictReader(open(temp_dir / "model" / "knee_resolution.csv")))
        assert len(rows) == 6

    def test_too_few_conditions(self, temp_dir, capsys):
        _cond(temp_dir, "ea4", "l0", "n5_20260101_000000", 0.9, 0.2)
        assert main(["--depth-dir", str(temp_dir / "depth"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--phases", "ea4", "--out", str(temp_dir / "model")]) == 1
        assert "insufficient conditions" in capsys.readouterr().out
