"""Tests for scripts/analyze_window.py - target 100% branch coverage.

This script decides whether the paper's ~103 ms offset is a per-event constant or a per-run
start-up cost. That distinction is the paper's second withdrawal, so the classifier is pinned
in both directions rather than only on the happy path.
"""
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_window import (  # noqa: E402
    condition_timestamp,
    window_stats,
    verdict,
    collect,
    main,
)


def _make_condition(tmp, window, ts, backend="kafka", runs=3, p50=1.5, mx=103.5, events=57):
    """A window condition directory plus the run directories its trials wrote."""
    cond = tmp / "window" / f"w{window}"
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    runs_dir = tmp / "runs"
    for i in range(runs):
        r = runs_dir / f"concurrency_{ts}_{backend}_feed1_rep{i + 1}"
        r.mkdir(parents=True, exist_ok=True)
        (r / "tti_summary.json").write_text(json.dumps({
            "n_matched": events,
            "producer_sched_lag_ms": {"p50": p50, "max": mx},
        }), encoding="utf-8")
    return cond, runs_dir


class TestConditionTimestamp:
    def test_extracts_the_run_id_timestamp(self, temp_dir):
        cond, _ = _make_condition(temp_dir, 60, "n1_20260724_023310")
        assert condition_timestamp(str(cond)) == "n1_20260724_023310"

    def test_none_when_no_concurrency_subdir(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert condition_timestamp(str(d)) is None


class TestWindowStats:
    def test_pools_over_runs(self, temp_dir):
        cond, runs = _make_condition(temp_dir, 60, "n1_20260724_023310", p50=1.5, mx=103.5)
        s = window_stats(str(cond), str(runs), "kafka")
        assert s["runs"] == 3
        assert s["events_per_run"] == 57
        assert s["schedlag_p50"] == pytest.approx(1.5)
        assert s["schedlag_max"] == pytest.approx(103.5)

    def test_none_for_the_other_backend(self, temp_dir):
        cond, runs = _make_condition(temp_dir, 60, "n1_20260724_023310", backend="kafka")
        assert window_stats(str(cond), str(runs), "redis") is None

    def test_none_without_a_timestamp(self, temp_dir):
        d = temp_dir / "nope"
        d.mkdir()
        assert window_stats(str(d), str(temp_dir), "kafka") is None

    def test_runs_without_a_summary_are_skipped(self, temp_dir):
        cond, runs = _make_condition(temp_dir, 60, "n1_20260724_023310", runs=2)
        (runs / "concurrency_n1_20260724_023310_kafka_feed1_rep9").mkdir(parents=True)
        assert window_stats(str(cond), str(runs), "kafka")["runs"] == 2

    def test_malformed_summary_is_skipped(self, temp_dir):
        cond, runs = _make_condition(temp_dir, 60, "n1_20260724_023310", runs=2)
        bad = runs / "concurrency_n1_20260724_023310_kafka_feed1_rep8"
        bad.mkdir(parents=True)
        (bad / "tti_summary.json").write_text("{not json", encoding="utf-8")
        assert window_stats(str(cond), str(runs), "kafka")["runs"] == 2

    def test_summary_missing_the_lag_field_is_skipped(self, temp_dir):
        cond, runs = _make_condition(temp_dir, 60, "n1_20260724_023310", runs=1)
        other = runs / "concurrency_n1_20260724_023310_kafka_feed1_rep7"
        other.mkdir(parents=True)
        (other / "tti_summary.json").write_text(json.dumps({"n_matched": 5}), encoding="utf-8")
        assert window_stats(str(cond), str(runs), "kafka")["runs"] == 1


class TestVerdict:
    """The classifier that decides the paper's second withdrawal."""

    def test_startup_cost_when_the_median_collapses(self):
        rows = [
            {"window_s": 60, "schedlag_p50": 103.0, "schedlag_max": 103.5, "events_per_run": 7},
            {"window_s": 600, "schedlag_p50": 1.5, "schedlag_max": 103.5, "events_per_run": 500},
        ]
        tag, why = verdict(rows)
        assert tag == "START-UP COST"
        assert "once per run" in why

    def test_per_event_constant_when_the_median_holds(self):
        rows = [
            {"window_s": 60, "schedlag_p50": 103.0, "schedlag_max": 110.0, "events_per_run": 7},
            {"window_s": 600, "schedlag_p50": 101.0, "schedlag_max": 110.0, "events_per_run": 500},
        ]
        tag, _ = verdict(rows)
        assert tag == "PER-EVENT CONSTANT"

    def test_inconclusive_with_one_window(self):
        rows = [{"window_s": 60, "schedlag_p50": 1.0, "schedlag_max": 2.0, "events_per_run": 7}]
        assert verdict(rows)[0] == "INCONCLUSIVE"

    def test_inconclusive_when_the_widest_median_is_zero(self):
        rows = [
            {"window_s": 60, "schedlag_p50": 103.0, "schedlag_max": 103.5, "events_per_run": 7},
            {"window_s": 600, "schedlag_p50": 0.0, "schedlag_max": 103.5, "events_per_run": 500},
        ]
        assert verdict(rows)[0] == "INCONCLUSIVE"

    def test_rows_are_ordered_by_window_not_input_order(self):
        rows = [
            {"window_s": 600, "schedlag_p50": 1.5, "schedlag_max": 103.5, "events_per_run": 500},
            {"window_s": 60, "schedlag_p50": 103.0, "schedlag_max": 103.5, "events_per_run": 7},
        ]
        assert verdict(rows)[0] == "START-UP COST"


class TestCollect:
    def test_gathers_every_window(self, temp_dir):
        _make_condition(temp_dir, 60, "n1_20260724_010000")
        _make_condition(temp_dir, 600, "n1_20260724_020000")
        rows = collect(str(temp_dir / "window"), str(temp_dir / "runs"))
        assert sorted(r["window_s"] for r in rows) == [60.0, 600.0]

    def test_ignores_stray_files(self, temp_dir):
        _make_condition(temp_dir, 60, "n1_20260724_010000")
        (temp_dir / "window" / "w_notes.txt").write_text("x", encoding="utf-8")
        assert len(collect(str(temp_dir / "window"), str(temp_dir / "runs"))) == 1


class TestMain:
    def test_end_to_end_reports_a_verdict(self, temp_dir, capsys):
        _make_condition(temp_dir, 60, "n1_20260724_010000", p50=103.0, events=7)
        _make_condition(temp_dir, 600, "n1_20260724_020000", p50=1.5, events=500)
        rc = main(["--window-dir", str(temp_dir / "window"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "out" / "sweep.csv")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "VERDICT: START-UP COST" in out
        assert (temp_dir / "out" / "sweep.csv").exists()

    def test_reports_when_a_backend_has_no_data(self, temp_dir, capsys):
        _make_condition(temp_dir, 60, "n1_20260724_010000", backend="kafka")
        main(["--window-dir", str(temp_dir / "window"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "o.csv")])
        assert "redis: no data" in capsys.readouterr().out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--window-dir", str(temp_dir / "absent")]) == 1
        assert "missing window directory" in capsys.readouterr().out
