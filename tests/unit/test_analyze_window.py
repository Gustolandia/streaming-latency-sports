"""Tests for scripts/analyze_window.py - target 100% branch coverage.

This script decides whether the paper's ~103 ms offset is a per-event constant or a per-run
start-up cost. That distinction is the paper's second withdrawal, so the classifier is pinned
in both directions rather than only on the happy path.
"""
import csv
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_window import (  # noqa: E402
    condition_timestamp,
    window_stats,
    trace_stats,
    verdict,
    collect,
    main,
)


def _make_condition(tmp, window, ts, backend="kafka", runs=3, p50=1.5, mx=103.5, events=57,
                    slow=5):
    """A window condition directory, the run directories its trials wrote, and its loop traces.

    `slow` is how many of the run's events wake more than 50 ms late: one blocking send plus the
    events that queued behind it.
    """
    cond = tmp / "window" / f"w{window}"
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    runs_dir = tmp / "runs"
    win_dir = tmp / "window"
    for i in range(runs):
        r = runs_dir / f"concurrency_{ts}_{backend}_feed1_rep{i + 1}"
        r.mkdir(parents=True, exist_ok=True)
        (r / "tti_summary.json").write_text(json.dumps({
            "n_matched": events,
            "producer_sched_lag_ms": {"p50": p50, "max": mx},
        }), encoding="utf-8")
        if slow is not None:
            _make_trace(win_dir, window, ts, backend, i + 1, events, slow)
    return cond, runs_dir


def _make_trace(win_dir, window, ts, backend, rep, events, slow):
    """A --trace-loop CSV: one blocking send, `slow`-1 events queued behind it, then steady state."""
    win_dir.mkdir(parents=True, exist_ok=True)
    p = win_dir / f"trace_w{window}_concurrency_{ts}_{backend}_feed1_rep{rep}.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "wake_late_ms", "produce_ms"])
        w.writeheader()
        w.writerow({"event_id": "e0", "wake_late_ms": 0.17, "produce_ms": 102.6})
        for i in range(1, slow + 1):
            w.writerow({"event_id": f"e{i}", "wake_late_ms": 103.0, "produce_ms": 0.05})
        for i in range(slow + 1, max(events, slow + 2)):
            w.writerow({"event_id": f"e{i}", "wake_late_ms": 1.5, "produce_ms": 0.06})
    return p


class TestConditionTimestamp:
    def test_extracts_the_run_id_timestamp(self, temp_dir):
        cond, _ = _make_condition(temp_dir, 60, "n1_20260724_023310")
        assert condition_timestamp(str(cond)) == "n1_20260724_023310"

    def test_none_when_no_concurrency_subdir(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert condition_timestamp(str(d)) is None

    def test_skips_subdirs_without_a_run_id(self, temp_dir):
        """The stray is created first, so the scan must walk past it rather than stop."""
        d = temp_dir / "w60"
        (d / "concurrency_concurrency_aborted").mkdir(parents=True)
        (d / "concurrency_concurrency_n1_20260724_023310").mkdir()
        assert condition_timestamp(str(d)) == "n1_20260724_023310"


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


class TestTraceStats:
    def test_counts_the_affected_events(self, temp_dir):
        for rep in (1, 2, 3):
            _make_trace(temp_dir / "window", 60, "n1_20260724_023310", "kafka", rep, 57, 4)
        s = trace_stats(str(temp_dir / "window"), 60.0)
        assert s["trace_runs"] == 3
        assert s["trace_events"] == 57
        assert s["slow_wake"] == 4          # the events that queued behind the blocking send
        assert s["slow_produce"] == 1       # exactly one send blocks

    def test_none_when_no_traces_exist(self, temp_dir):
        (temp_dir / "window").mkdir()
        assert trace_stats(str(temp_dir / "window"), 60.0) is None

    def test_unparseable_rows_are_skipped(self, temp_dir):
        d = temp_dir / "window"
        d.mkdir()
        (d / "trace_w60_concurrency_n1_x_kafka_feed1_rep1.csv").write_text(
            "event_id,wake_late_ms,produce_ms\na,xx,0.1\nb,103.0,0.1\n", encoding="utf-8")
        assert trace_stats(str(d), 60.0)["trace_events"] == 1

    def test_a_trace_with_no_usable_rows_is_ignored(self, temp_dir):
        d = temp_dir / "window"
        d.mkdir()
        (d / "trace_w60_concurrency_n1_x_kafka_feed1_rep1.csv").write_text(
            "event_id,wake_late_ms,produce_ms\n", encoding="utf-8")
        assert trace_stats(str(d), 60.0) is None

    def test_an_unreadable_trace_is_skipped(self, temp_dir):
        """A campaign that died mid-write can leave a name where a file should be."""
        d = temp_dir / "window"
        _make_trace(d, 60, "n1_x", "kafka", 1, 57, 4)
        (d / "trace_w60_concurrency_n1_x_kafka_feed1_rep2.csv").mkdir()
        assert trace_stats(str(d), 60.0)["trace_runs"] == 1

    def test_other_backends_are_not_pooled_in(self, temp_dir):
        _make_trace(temp_dir / "window", 60, "n1_x", "kafka", 1, 57, 4)
        _make_trace(temp_dir / "window", 60, "n1_x", "redis", 1, 57, 0)
        assert trace_stats(str(temp_dir / "window"), 60.0, "kafka")["trace_runs"] == 1


class TestVerdict:
    """The classifier that decides the paper's second withdrawal.

    It turns on the COUNT of affected events, not on the median: the median only reveals the
    cost when the run is short enough for it to dominate, which is the original error.
    """

    @staticmethod
    def _row(window_s, events, slow):
        return {"window_s": window_s, "trace_events": events, "slow_wake": slow,
                "slow_produce": 1, "schedlag_p50": 1.6, "schedlag_max": 103.5}

    def test_startup_cost_when_the_count_stays_fixed(self):
        """What the real sweep gives: five affected events whether the run holds 57 or 500."""
        tag, why = verdict([self._row(60, 57, 5), self._row(600, 500, 5)])
        assert tag == "START-UP COST"
        assert "once per run" in why
        assert "8.8% to 1.0%" in why

    def test_per_event_constant_when_the_count_scales(self):
        tag, why = verdict([self._row(60, 57, 5), self._row(600, 500, 44)])
        assert tag == "PER-EVENT CONSTANT"
        assert "every event pays" in why

    def test_inconclusive_when_the_count_grows_but_not_in_proportion(self):
        tag, why = verdict([self._row(60, 57, 5), self._row(600, 500, 15)])
        assert tag == "INCONCLUSIVE"
        assert "neither in proportion nor flat" in why

    def test_inconclusive_with_one_window(self):
        assert verdict([self._row(60, 57, 5)])[0] == "INCONCLUSIVE"

    def test_inconclusive_when_no_window_has_affected_events(self):
        tag, why = verdict([self._row(60, 57, 0), self._row(600, 500, 0)])
        assert tag == "INCONCLUSIVE"
        assert "per-event traces" in why

    def test_inconclusive_when_the_run_barely_grew(self):
        tag, why = verdict([self._row(60, 57, 5), self._row(180, 80, 5)])
        assert tag == "INCONCLUSIVE"
        assert "only grew" in why

    def test_rows_are_ordered_by_window_not_input_order(self):
        assert verdict([self._row(600, 500, 5), self._row(60, 57, 5)])[0] == "START-UP COST"


class TestCollect:
    def test_gathers_every_window(self, temp_dir):
        _make_condition(temp_dir, 60, "n1_20260724_010000")
        _make_condition(temp_dir, 600, "n1_20260724_020000")
        rows = collect(str(temp_dir / "window"), str(temp_dir / "runs"))
        assert sorted(r["window_s"] for r in rows) == [60.0, 600.0]

    def test_carries_the_trace_counts_alongside_the_percentiles(self, temp_dir):
        _make_condition(temp_dir, 60, "n1_20260724_010000", events=57, slow=5)
        row = collect(str(temp_dir / "window"), str(temp_dir / "runs"))[0]
        assert row["trace_events"] == 57 and row["slow_wake"] == 5

    def test_an_untraced_window_reports_percentiles_but_no_counts(self, temp_dir):
        """None, not zero: an untraced backend has not been measured to have no late events.

        Defaulting to 0 is how the paper's first window table came to report Redis as having
        zero blocking sends, which nobody had observed -- Redis simply had no loop trace.
        """
        _make_condition(temp_dir, 60, "n1_20260724_010000", slow=None)
        row = collect(str(temp_dir / "window"), str(temp_dir / "runs"))[0]
        assert row["schedlag_p50"] == pytest.approx(1.5)
        assert row["trace_runs"] == 0
        assert row["slow_wake"] is None and row["slow_produce"] is None
        assert row["trace_events"] is None

    def test_an_untraced_window_prints_as_untraced_not_as_zero(self, temp_dir, capsys):
        _make_condition(temp_dir, 60, "n1_20260724_010000", slow=None)
        _make_condition(temp_dir, 600, "n1_20260724_020000", slow=None)
        main(["--window-dir", str(temp_dir / "window"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "o.csv")])
        out = capsys.readouterr().out
        assert "(no loop trace)" in out
        assert "blocking sends=" not in out
        assert "VERDICT: INCONCLUSIVE" in out

    def test_ignores_stray_files(self, temp_dir):
        _make_condition(temp_dir, 60, "n1_20260724_010000")
        (temp_dir / "window" / "w_notes.txt").write_text("x", encoding="utf-8")
        assert len(collect(str(temp_dir / "window"), str(temp_dir / "runs"))) == 1


class TestMain:
    def test_end_to_end_reports_a_verdict(self, temp_dir, capsys):
        _make_condition(temp_dir, 60, "n1_20260724_010000", p50=103.0, events=57, slow=5)
        _make_condition(temp_dir, 600, "n1_20260724_020000", p50=1.5, events=500, slow=5)
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


class TestTheSecondBackendGetsNoVerdict:

    def test_redis_is_tabulated_but_not_judged(self, temp_dir, capsys):
        """The window hypothesis is about the Kafka producer's scheduling lag.

        Redis is carried as a control and is printed, but a verdict on it would assert a
        finding for a system the pre-registered prediction says nothing about.
        """
        for w, ts in ((60, "n5_20260101_000000"), (600, "n5_20260101_000001")):
            _make_condition(temp_dir, w, ts, backend="kafka")
            _make_condition(temp_dir, w, ts, backend="redis")
        main(["--window-dir", str(temp_dir / "window"),
              "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "out.json")])
        out = capsys.readouterr().out
        assert out.count("VERDICT") == 1, "exactly one backend carries the hypothesis"
        assert "redis" in out
