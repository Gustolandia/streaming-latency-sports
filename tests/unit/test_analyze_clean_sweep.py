"""Tests for scripts/analyze_clean_sweep.py - target >=95% branch coverage.

The point of this script is that it REFUSES to report a slope when the manipulation is
confounded, so the refusal path matters as much as the reporting path and both are pinned.
"""
import csv
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_clean_sweep import (  # noqa: E402
    condition_timestamp,
    transports,
    collect,
    manipulation_check,
    h1_verdict,
    main,
)

T0 = 1_700_000_000_000_000_000


def _run(runs_dir, run_id, values_ms):
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(len(values_ms)):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i, ms in enumerate(values_ms):
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(ms * 1e6)})
    return d


def _cond(tmp, delay, ts, values):
    cond = tmp / "eb2" / f"d{delay}"
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    _run(tmp / "runs", f"concurrency_{ts}_kafka_feed1_rep1", values)
    return cond


def _offset(delay, spread=0.4, n=100, inversions=0):
    """A clean constant offset: the whole distribution shifts, its width does not change."""
    vals = [delay + 0.5 + (i % 5) * (spread / 4) for i in range(n - inversions)]
    return vals + [-0.2] * inversions


class TestPlumbing:
    def test_timestamp_and_transports(self, temp_dir):
        cond = _cond(temp_dir, 0, "n5_20260101_000000", _offset(0))
        assert condition_timestamp(str(cond)) == "n5_20260101_000000"
        assert len(transports(str(cond), str(temp_dir / "runs"))) == 100

    def test_no_timestamp_gives_nothing(self, temp_dir):
        d = temp_dir / "bare"
        d.mkdir()
        assert transports(str(d), str(temp_dir)) == []

    def test_malformed_rows_do_not_crash(self, temp_dir):
        cond = _cond(temp_dir, 0, "n5_20260101_000001", _offset(0))
        run = temp_dir / "runs" / "concurrency_n5_20260101_000001_kafka_feed1_rep1"
        (run / "consumer_events.csv").write_text("event_id,t_consume_ns\ne0,nope\n",
                                                 encoding="utf-8")
        assert transports(str(cond), str(temp_dir / "runs")) == []

    def test_run_without_csvs_is_skipped(self, temp_dir):
        cond = _cond(temp_dir, 0, "n5_20260101_000002", _offset(0))
        (temp_dir / "runs" / "concurrency_n5_20260101_000002_kafka_feed2_rep1").mkdir()
        assert len(transports(str(cond), str(temp_dir / "runs"))) == 100

    def test_unacknowledged_events_are_skipped(self, temp_dir):
        cond = _cond(temp_dir, 0, "n5_20260101_000003", _offset(0))
        run = temp_dir / "runs" / "concurrency_n5_20260101_000003_kafka_feed1_rep1"
        (run / "producer.csv").write_text("event_id,t_broker_ack_ns\ne0,None\n", encoding="utf-8")
        assert transports(str(cond), str(temp_dir / "runs")) == []

    def test_non_directory_entries_are_ignored(self, temp_dir):
        _cond(temp_dir, 0, "n5_20260101_000004", _offset(0))
        (temp_dir / "eb2" / "d_notes.txt").write_text("x", encoding="utf-8")
        assert len(collect(str(temp_dir / "eb2"), str(temp_dir / "runs"))) == 1


class TestCollect:
    def test_one_row_per_delay_sorted(self, temp_dir):
        for i, d in enumerate((20, 0, 5)):
            _cond(temp_dir, d, f"n5_2026010{i}_000000", _offset(d))
        rows = collect(str(temp_dir / "eb2"), str(temp_dir / "runs"))
        assert [r["delay_ms"] for r in rows] == [0.0, 5.0, 20.0]
        assert rows[2]["median_ms"] > rows[0]["median_ms"]

    def test_thin_conditions_are_dropped(self, temp_dir):
        _cond(temp_dir, 0, "n5_20260101_000000", [1.0] * 10)   # < 50 events
        assert collect(str(temp_dir / "eb2"), str(temp_dir / "runs")) == []


class TestManipulationCheck:
    def test_a_clean_offset_passes(self):
        rows = [{"delay_ms": d, "median_ms": d + 0.5, "iqr_ms": 0.4,
                 "inversion_rate": 0.05, "n_events": 100} for d in (0, 5, 20, 50)]
        c = manipulation_check(rows)
        assert c["clean"] and c["offset_ok"] and c["spread_ok"]

    def test_a_queue_is_caught(self):
        """The original confound: the spread explodes with the injected delay."""
        rows = [{"delay_ms": d, "median_ms": d + 0.5, "iqr_ms": 0.4 * (1 + d),
                 "inversion_rate": 0.05, "n_events": 100} for d in (0, 5, 20, 50)]
        c = manipulation_check(rows)
        assert not c["clean"] and not c["spread_ok"]
        assert "queue" in c["reason"]

    def test_an_offset_that_did_not_land_is_caught(self):
        """netem silently not applied would look like this."""
        rows = [{"delay_ms": d, "median_ms": 0.5, "iqr_ms": 0.4,
                 "inversion_rate": 0.05, "n_events": 100} for d in (0, 5, 20, 50)]
        c = manipulation_check(rows)
        assert not c["clean"] and not c["offset_ok"]
        assert "did not track" in c["reason"]

    def test_too_few_levels(self):
        assert not manipulation_check([{"delay_ms": 0, "median_ms": 1, "iqr_ms": 1,
                                        "inversion_rate": 0.1, "n_events": 60}])["clean"]


class TestH1Verdict:
    @staticmethod
    def _rows(rates):
        return [{"delay_ms": d, "median_ms": d + 0.5, "iqr_ms": 0.4,
                 "inversion_rate": r, "n_events": 100}
                for d, r in zip((0, 5, 20, 50), rates)]

    def test_reported_and_supported_when_clean(self):
        rows = self._rows([0.20, 0.10, 0.04, 0.01])
        v = h1_verdict(rows, manipulation_check(rows))
        assert v["reported"] and v["supported"] and v["spearman"] < 0

    def test_reported_but_not_supported_when_rising(self):
        rows = self._rows([0.01, 0.04, 0.10, 0.20])
        v = h1_verdict(rows, manipulation_check(rows))
        assert v["reported"] and not v["supported"]

    def test_withheld_when_confounded(self):
        """The whole point: no slope is reported against a confounded manipulation."""
        rows = [{"delay_ms": d, "median_ms": d + 0.5, "iqr_ms": 0.4 * (1 + d),
                 "inversion_rate": r, "n_events": 100}
                for d, r in zip((0, 5, 20, 50), (0.20, 0.10, 0.04, 0.01))]
        v = h1_verdict(rows, manipulation_check(rows))
        assert not v["reported"] and not v["supported"]
        assert "manipulation check failed" in v["why"]


class TestMain:
    def test_end_to_end_clean(self, temp_dir, capsys):
        for i, d in enumerate((0, 5, 20, 50)):
            inv = {0: 20, 5: 10, 20: 4, 50: 1}[d]
            _cond(temp_dir, d, f"n5_2026010{i}_000000", _offset(d, inversions=inv))
        rc = main(["--sweep-dir", str(temp_dir / "eb2"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "model")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "MANIPULATION CHECK: CLEAN" in out
        rows = list(csv.DictReader(open(temp_dir / "model" / "clean_effect_size.csv")))
        assert [r["delay_ms"] for r in rows] == ["0.0", "5.0", "20.0", "50.0"]

    def test_end_to_end_confounded_withholds_the_slope(self, temp_dir, capsys):
        for i, d in enumerate((0, 5, 20, 50)):
            # spread grows with delay: a queue, exactly what the original sweep did
            _cond(temp_dir, d, f"n5_2026010{i}_000000", _offset(d, spread=0.4 * (1 + d)))
        main(["--sweep-dir", str(temp_dir / "eb2"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "model")])
        out = capsys.readouterr().out
        assert "CONFOUNDED" in out and "NOT REPORTED" in out
        assert "withheld" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--sweep-dir", str(temp_dir / "nope")]) == 1
        assert "missing sweep directory" in capsys.readouterr().out

    def test_too_few_levels_is_an_error(self, temp_dir, capsys):
        _cond(temp_dir, 0, "n5_20260101_000000", _offset(0))
        assert main(["--sweep-dir", str(temp_dir / "eb2"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--out", str(temp_dir / "model")]) == 1
        assert "insufficient delay levels" in capsys.readouterr().out
