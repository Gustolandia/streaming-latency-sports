"""Tests for scripts/analyze_moments.py - target ~100% branch coverage.

The script produces the variance-vs-utilisation table and the inversion-clustering result. The
tests build tiny synthetic conditions whose per-event transport is known, so the pooled variance
and the runs-test sign clustering are checked against hand-computable values.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_moments import (  # noqa: E402
    condition_timestamp,
    run_series,
    condition_series,
    median_rho,
    variance_rows,
    clustering_rows,
    main,
)

T0 = 1_700_000_000_000_000_000


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


def _condition(tmp, phase, name, ts, transports, rho=None, backend="kafka"):
    cond = tmp / "depth" / phase / name
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    _run(tmp / "runs", f"concurrency_{ts}_{backend}_feed1_rep1", transports)
    if rho is not None:
        with (cond / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
            w.writeheader()
            w.writerow({"t_wall": 1, "rho": rho, "loadavg": 1.0})
    return cond


class TestRunSeries:
    def test_returns_transports_in_emission_order(self, temp_dir):
        d = _run(temp_dir, "r1", [1.0, -2.0, 3.0])
        assert run_series(str(d)) == [1.0, -2.0, 3.0]

    def test_missing_files_empty(self, temp_dir):
        d = temp_dir / "none"
        d.mkdir()
        assert run_series(str(d)) == []

    def test_unacknowledged_events_skipped(self, temp_dir):
        d = _run(temp_dir, "r2", [1.0])
        (d / "producer.csv").write_text("event_id,t_broker_ack_ns\ne0,None\n", encoding="utf-8")
        assert run_series(str(d)) == []


class TestConditionLevel:
    def test_timestamp_and_series(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000000", [1.0, -1.0], rho=0.1)
        cond = temp_dir / "depth" / "ea_sat" / "bg0"
        assert condition_timestamp(str(cond)) == "n5_20260101_000000"
        s = condition_series(str(cond), str(temp_dir / "runs"))
        assert s == [[1.0, -1.0]]

    def test_series_empty_without_timestamp(self, temp_dir):
        d = temp_dir / "bare"
        d.mkdir()
        assert condition_series(str(d), str(temp_dir)) == []

    def test_median_rho(self, temp_dir):
        cond = _condition(temp_dir, "ea_sat", "bg4", "n5_x", [1.0], rho=0.5)
        assert median_rho(str(cond)) == pytest.approx(0.5)

    def test_median_rho_missing(self, temp_dir):
        d = temp_dir / "norho"
        d.mkdir()
        assert median_rho(str(d)) is None

    def test_median_rho_unparseable(self, temp_dir):
        d = temp_dir / "bad"
        d.mkdir()
        (d / "utilisation.csv").write_text("t_wall,rho,loadavg\n1,xx,1\n", encoding="utf-8")
        assert median_rho(str(d)) is None


class TestVarianceRows:
    def test_one_row_per_condition_with_rho(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000001", [1.0] * 6 + [5.0] * 6, rho=0.1)
        _condition(temp_dir, "ea_sat", "bg8", "n5_20260101_000002", [1.0] * 6 + [50.0] * 6, rho=0.9)
        rows = variance_rows(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert [r["rho"] for r in rows] == [0.1, 0.9]         # sorted by rho
        assert rows[1]["variance"] > rows[0]["variance"]      # higher load, higher variance

    def test_conditions_without_rho_are_dropped(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000001", [1.0] * 20, rho=None)
        assert variance_rows(str(temp_dir / "depth"), str(temp_dir / "runs")) == []

    def test_too_few_events_dropped(self, temp_dir):
        _condition(temp_dir, "ea_sat", "bg0", "n5_20260101_000001", [1.0, 2.0], rho=0.1)   # <=10 events
        assert variance_rows(str(temp_dir / "depth"), str(temp_dir / "runs")) == []

    def test_falls_back_to_ea_when_no_sat(self, temp_dir):
        _condition(temp_dir, "ea", "c1", "n5_20260101_000001", [1.0] * 12, rho=0.3)
        rows = variance_rows(str(temp_dir / "depth"), str(temp_dir / "runs"))
        assert len(rows) == 1 and rows[0]["rho"] == 0.3


class TestClusteringRows:
    def test_clustered_condition_has_negative_z(self, temp_dir):
        # 30 inversions then 30 non-inversions: maximally clustered
        _condition(temp_dir, "eb", "d0", "n5_20260101_000001", [-1.0] * 30 + [1.0] * 30)
        rows = clustering_rows(str(temp_dir / "depth"), str(temp_dir / "runs"),
                               [("floor", "eb/d0")])
        assert rows[0]["median_z"] < -5

    def test_absent_condition_skipped(self, temp_dir):
        rows = clustering_rows(str(temp_dir / "depth"), str(temp_dir / "runs"),
                               [("missing", "eb/d99")])
        assert rows == []


class TestMain:
    def _corpus(self, tmp):
        for i, (bg, rho, tall_) in enumerate([
                ("bg0", 0.05, [1.0] * 10 + [1.2] * 10),
                ("bg4", 0.5, [1.0] * 10 + [3.0] * 10),
                ("bg8", 0.95, [1.0] * 10 + [40.0] * 10)]):
            _condition(tmp, "ea_sat", bg, f"n5_20260101_00000{i}", tall_, rho=rho)
        _condition(tmp, "eb", "d0", "n5_20260101_000009", [-1.0] * 20 + [1.0] * 20)

    def test_end_to_end_writes_both_csvs(self, temp_dir, capsys):
        self._corpus(temp_dir)
        rc = main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "variance" in out.lower() and "clustered" in out.lower()
        vr = list(csv.DictReader(open(temp_dir / "model" / "variance_law.csv")))
        assert [r["rho"] for r in vr] == ["0.05", "0.5", "0.95"]
        cr = list(csv.DictReader(open(temp_dir / "model" / "inversion_clustering.csv")))
        assert float(cr[0]["median_z"]) < -2
        assert "no single exponent" in out.lower()

    def test_reports_when_variance_data_is_thin(self, temp_dir, capsys):
        _condition(temp_dir, "eb", "d0", "n5_20260101_000009", [-1.0] * 20 + [1.0] * 20)
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        assert "insufficient" in capsys.readouterr().out.lower()

    def test_reports_when_no_clustering_conditions(self, temp_dir, capsys):
        for i, (bg, rho) in enumerate([("bg0", 0.05), ("bg4", 0.5), ("bg8", 0.95)]):
            _condition(temp_dir, "ea_sat", bg, f"n5_20260101_00000{i}", [1.0] * 12, rho=rho)
        main(["--depth-dir", str(temp_dir / "depth"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        assert "no conditions" in capsys.readouterr().out.lower()
