"""Tests for scripts/analyze_e1_replication.py - target >=95% branch coverage.

This decides whether the paper re-labels E1's transport row or withdraws it, so the
NOT-EXPLAINED path is pinned as carefully as the EXPLAINED one. Synthetic runs are built with a
known prologue so both outcomes can be produced on demand.
"""
import csv
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from analyze_e1_replication import (  # noqa: E402
    condition_timestamp,
    run_transports,
    condition_medians,
    collect,
    verdict,
    main,
)

T0 = 1_700_000_000_000_000_000


def _run(runs_dir, run_id, values_ms):
    """A run whose per-event transports are exactly `values_ms`, in emission order."""
    d = runs_dir / run_id
    d.mkdir(parents=True, exist_ok=True)
    with (d / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_broker_ack_ns"])
        w.writeheader()
        for i in range(len(values_ms)):
            w.writerow({"event_id": f"e{i}", "t_broker_ack_ns": T0})
    # Consumer rows deliberately written in reverse, so a script that ignores emission order
    # would pick the wrong "first seven" and fail these tests.
    with (d / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["event_id", "t_consume_ns"])
        w.writeheader()
        for i in reversed(range(len(values_ms))):
            w.writerow({"event_id": f"e{i}", "t_consume_ns": T0 + int(values_ms[i] * 1e6)})
    return d


def _cond(tmp, n, ts, kafka_vals, redis_vals, reps=3):
    cond = tmp / "e1_rep" / f"n{n}"
    (cond / f"concurrency_concurrency_{ts}").mkdir(parents=True, exist_ok=True)
    for rep in range(1, reps + 1):
        _run(tmp / "runs", f"concurrency_{ts}_kafka_feed1_rep{rep}", kafka_vals)
        _run(tmp / "runs", f"concurrency_{ts}_redis_feed1_rep{rep}", redis_vals)
    return cond


# Prologue (first 7) near-equal between systems; steady state separated by ~0.43 ms.
KAFKA_SERIES = [0.10] * 7 + [0.54] * 93
REDIS_SERIES = [0.09] * 7 + [0.11] * 93


class TestPlumbing:
    def test_emission_order_is_respected(self, temp_dir):
        d = _run(temp_dir, "r1", [1.0, 2.0, 3.0])
        assert run_transports(str(d)) == [1.0, 2.0, 3.0]

    def test_missing_files(self, temp_dir):
        d = temp_dir / "none"
        d.mkdir()
        assert run_transports(str(d)) == []

    def test_malformed_rows(self, temp_dir):
        d = _run(temp_dir, "r2", [1.0, 2.0])
        (d / "consumer_events.csv").write_text("event_id,t_consume_ns\ne0,x\n", encoding="utf-8")
        assert run_transports(str(d)) == []

    def test_condition_timestamp(self, temp_dir):
        cond = _cond(temp_dir, 1, "n1_20260101_000000", KAFKA_SERIES, REDIS_SERIES)
        assert condition_timestamp(str(cond)) == "n1_20260101_000000"
        bare = temp_dir / "bare"
        bare.mkdir()
        assert condition_timestamp(str(bare)) is None

    def test_condition_medians_splits_all_from_prologue(self, temp_dir):
        cond = _cond(temp_dir, 1, "n1_20260101_000001", KAFKA_SERIES, REDIS_SERIES)
        a, p = condition_medians(str(cond), str(temp_dir / "runs"), "kafka")
        assert len(a) == 3 and len(p) == 3
        assert a[0] == 0.54 and p[0] == 0.10

    def test_condition_medians_without_timestamp(self, temp_dir):
        d = temp_dir / "x"
        d.mkdir()
        assert condition_medians(str(d), str(temp_dir), "kafka") == ([], [])


class TestCollect:
    def test_both_views_per_condition(self, temp_dir):
        _cond(temp_dir, 1, "n1_20260101_000002", KAFKA_SERIES, REDIS_SERIES)
        rows = collect(str(temp_dir / "e1_rep"), str(temp_dir / "runs"))
        assert len(rows) == 1
        r = rows[0]
        assert r["shift_all"] == 0.43          # steady state: the powered result
        assert r["shift_prologue"] == 0.01     # prologue: near-equal, as E1 reported

    def test_condition_missing_a_backend_is_dropped(self, temp_dir):
        cond = temp_dir / "e1_rep" / "n1"
        (cond / "concurrency_concurrency_n1_20260101_000003").mkdir(parents=True)
        _run(temp_dir / "runs", "concurrency_n1_20260101_000003_kafka_feed1_rep1", KAFKA_SERIES)
        assert collect(str(temp_dir / "e1_rep"), str(temp_dir / "runs")) == []

    def test_non_directory_and_unparseable_names_ignored(self, temp_dir):
        _cond(temp_dir, 9, "n9_20260101_000004", KAFKA_SERIES, REDIS_SERIES)
        (temp_dir / "e1_rep" / "notes.txt").write_text("x", encoding="utf-8")
        (temp_dir / "e1_rep" / "nXX").mkdir()
        assert len(collect(str(temp_dir / "e1_rep"), str(temp_dir / "runs"))) == 1

    def test_rows_sorted_by_feed_count(self, temp_dir):
        _cond(temp_dir, 12, "n12_20260101_000005", KAFKA_SERIES, REDIS_SERIES)
        _cond(temp_dir, 1, "n1_20260101_000006", KAFKA_SERIES, REDIS_SERIES)
        rows = collect(str(temp_dir / "e1_rep"), str(temp_dir / "runs"))
        assert [r["n_feeds"] for r in rows] == [1, 12]


class TestVerdict:
    @staticmethod
    def _rows(shift_all, shift_pro):
        return [{"n_feeds": 1, "n_runs": 5, "kafka_all": 0.5, "redis_all": 0.1,
                 "shift_all": shift_all, "kafka_prologue": 0.1, "redis_prologue": 0.09,
                 "shift_prologue": shift_pro}]

    def test_explained_when_both_halves_land(self):
        v = verdict(self._rows(0.43, 0.01))
        assert v["testable"] and v["explained"]
        assert "opening burst" in v["why"]

    def test_not_explained_when_the_prologue_still_separates(self):
        """The hypothesis is wrong: the prologue does not reproduce E1's near-equality."""
        v = verdict(self._rows(0.43, 0.40))
        assert not v["explained"] and v["all_reproduces_powered"]
        assert not v["prologue_reproduces_e1"]
        assert "NOT explained" in v["why"]

    def test_not_explained_when_the_campaign_fails_to_replicate(self):
        v = verdict(self._rows(0.02, 0.01))
        assert not v["explained"] and not v["all_reproduces_powered"]
        assert "does not replicate" in v["why"]

    def test_untestable_without_rows(self):
        v = verdict([])
        assert not v["testable"] and not v["explained"]


class TestMain:
    def test_end_to_end_explained(self, temp_dir, capsys):
        _cond(temp_dir, 1, "n1_20260101_000007", KAFKA_SERIES, REDIS_SERIES)
        rc = main(["--rep-dir", str(temp_dir / "e1_rep"), "--runs-dir", str(temp_dir / "runs"),
                   "--out", str(temp_dir / "out")])
        assert rc == 0
        out = capsys.readouterr().out
        assert "DISCREPANCY: EXPLAINED" in out
        rows = list(csv.DictReader(open(temp_dir / "out" / "e1_replication.csv")))
        assert rows[0]["shift_all"] == "0.43" and rows[0]["shift_prologue"] == "0.01"

    def test_end_to_end_not_explained_says_withdraw(self, temp_dir, capsys):
        # prologue separates just as much as steady state: hypothesis fails
        kafka = [0.54] * 100
        redis = [0.11] * 100
        _cond(temp_dir, 1, "n1_20260101_000008", kafka, redis)
        main(["--rep-dir", str(temp_dir / "e1_rep"), "--runs-dir", str(temp_dir / "runs"),
              "--out", str(temp_dir / "out")])
        out = capsys.readouterr().out
        assert "NOT EXPLAINED" in out
        assert "must withdraw" in out

    def test_missing_directory(self, temp_dir, capsys):
        assert main(["--rep-dir", str(temp_dir / "nope")]) == 1
        assert "missing replication directory" in capsys.readouterr().out

    def test_no_usable_conditions(self, temp_dir, capsys):
        (temp_dir / "e1_rep").mkdir()
        assert main(["--rep-dir", str(temp_dir / "e1_rep"),
                     "--runs-dir", str(temp_dir / "runs"),
                     "--out", str(temp_dir / "out")]) == 1
        assert "no usable conditions" in capsys.readouterr().out
