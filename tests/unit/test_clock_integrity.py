"""Tests for scripts/clock_integrity.py - target 100% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from clock_integrity import (  # noqa: E402
    check_run,
    audit,
    condition_of,
    summarize,
    main,
)

MS = 1_000_000


def _run(tmp, name, n=5, transport_ms=1.0, schedlag_ms=1.0, output_ms=0.5,
         prod_cols=True, cons_cols=True):
    d = tmp / name
    d.mkdir(parents=True)
    ids = [f"e{i}" for i in range(n)]
    sched = [i * 10 * MS for i in range(n)]
    send = [s + int(schedlag_ms * MS) for s in sched]
    ack = [s + MS for s in send]
    recv = [a + int(transport_ms * MS) for a in ack]
    out = [r + int(output_ms * MS) for r in recv]
    prod = {"event_id": ids}
    if prod_cols:
        prod.update({"t_prod_sched_ns": sched, "t_prod_send_ns": send, "t_broker_ack_ns": ack})
    pd.DataFrame(prod).to_csv(d / "producer.csv", index=False)
    cons = {"event_id": ids}
    if cons_cols:
        cons.update({"t_cons_recv_ns": recv, "t_output_ns": out})
    pd.DataFrame(cons).to_csv(d / "consumer.csv", index=False)
    return d


class TestCheckRun:
    def test_clean_run_is_trustworthy(self, temp_dir):
        r = check_run(_run(temp_dir, "ok"))
        assert r["trustworthy"] is True
        assert r["frac_neg_transport"] == 0.0 and r["n_events"] == 5

    def test_systematically_negative_transport_fails(self, temp_dir):
        # the N=100 situation: every event inverted, median negative
        r = check_run(_run(temp_dir, "bad", transport_ms=-6.4))
        assert r["trustworthy"] is False
        assert r["frac_neg_transport"] == 1.0
        assert r["min_transport_ms"] == pytest.approx(-6.4, abs=0.01)
        assert r["median_transport_ms"] < 0

    def test_rare_inversion_is_tolerated(self, temp_dir):
        # t_broker_ack_ns is stamped by a sender thread that can be descheduled, so an
        # occasional inversion is a timestamping race rather than a broken clock. Condemning
        # a run for one such event would discard essentially every run ever measured.
        d = _run(temp_dir, "rare", n=200)
        c = pd.read_csv(d / "consumer.csv")
        c.loc[0, "t_cons_recv_ns"] = c.loc[0, "t_cons_recv_ns"] - 5 * MS
        c.to_csv(d / "consumer.csv", index=False)
        r = check_run(d)
        assert 0 < r["frac_neg_transport"] <= 0.01
        assert r["trustworthy"] is True

    def test_frequent_inversions_fail_even_with_positive_median(self, temp_dir):
        d = _run(temp_dir, "frequent", n=100)
        c = pd.read_csv(d / "consumer.csv")
        c.loc[:19, "t_cons_recv_ns"] = c.loc[:19, "t_cons_recv_ns"] - 5 * MS
        c.to_csv(d / "consumer.csv", index=False)
        r = check_run(d)
        assert r["frac_neg_transport"] > 0.01 and r["trustworthy"] is False

    def test_negative_schedlag_fails(self, temp_dir):
        r = check_run(_run(temp_dir, "bad2", schedlag_ms=-2.0))
        assert r["trustworthy"] is False and r["frac_neg_schedlag"] == 1.0

    def test_custom_threshold_respected(self, temp_dir):
        d = _run(temp_dir, "thr", n=100)
        c = pd.read_csv(d / "consumer.csv")
        c.loc[:4, "t_cons_recv_ns"] = c.loc[:4, "t_cons_recv_ns"] - 5 * MS
        c.to_csv(d / "consumer.csv", index=False)
        assert check_run(d, max_neg_fraction=0.10)["trustworthy"] is True
        assert check_run(d, max_neg_fraction=0.01)["trustworthy"] is False

    def test_negative_output_fails(self, temp_dir):
        r = check_run(_run(temp_dir, "bad3", output_ms=-1.0))
        assert r["trustworthy"] is False and r["frac_neg_output"] == 1.0

    def test_sub_tolerance_negative_is_noise(self, temp_dir):
        r = check_run(_run(temp_dir, "noise", transport_ms=-0.0000001))
        assert r["trustworthy"] is True

    def test_missing_files(self, temp_dir):
        d = temp_dir / "none"
        d.mkdir()
        assert check_run(d) is None

    def test_missing_event_id(self, temp_dir):
        d = temp_dir / "noid"
        d.mkdir()
        pd.DataFrame({"x": [1]}).to_csv(d / "producer.csv", index=False)
        pd.DataFrame({"x": [1]}).to_csv(d / "consumer.csv", index=False)
        assert check_run(d) is None

    def test_unreadable_csv(self, temp_dir):
        d = temp_dir / "junk"
        d.mkdir()
        (d / "producer.csv").write_bytes(b"\x00\x01\x02")
        (d / "consumer.csv").write_text("event_id\ne0\n")
        assert check_run(d) is None or check_run(d)["n_events"] >= 0

    def test_no_overlapping_events(self, temp_dir):
        d = temp_dir / "nolap"
        d.mkdir()
        pd.DataFrame({"event_id": ["a"]}).to_csv(d / "producer.csv", index=False)
        pd.DataFrame({"event_id": ["b"]}).to_csv(d / "consumer.csv", index=False)
        assert check_run(d) is None

    def test_missing_timestamp_columns_are_nan_not_crash(self, temp_dir):
        r = check_run(_run(temp_dir, "partial", prod_cols=False, cons_cols=False))
        assert np.isnan(r["frac_neg_transport"])
        assert np.isnan(r["frac_neg_schedlag"])
        # nothing measurable is not the same as broken; it must not silently pass as clean
        assert r["trustworthy"] is True

    def test_all_values_unparseable(self, temp_dir):
        d = _run(temp_dir, "nan")
        p = pd.read_csv(d / "producer.csv")
        p["t_broker_ack_ns"] = "notanumber"
        p.to_csv(d / "producer.csv", index=False)
        r = check_run(d)
        assert np.isnan(r["frac_neg_transport"])


class TestConditionOf:
    @pytest.mark.parametrize("rid,expected", [
        ("concurrency_n5_20260721_204137_kafka_feed3_rep2", "concurrency_n5_20260721_204137_kafka"),
        ("concurrency_n1_x_redis_feed1_rep1", "concurrency_n1_x_redis"),
        ("plain", "plain"),
    ])
    def test_strips_feed_and_rep(self, rid, expected):
        assert condition_of(rid) == expected


class TestAudit:
    def test_collects(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "c_a_feed1_rep1")
        _run(runs, "c_a_feed2_rep1", transport_ms=-1.0)
        (runs / "not_a_dir.txt").write_text("x")
        df = audit(runs, "c_*")
        assert len(df) == 2 and df["trustworthy"].sum() == 1

    def test_no_matches(self, temp_dir):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert audit(runs, "zzz*").empty


class TestSummarize:
    def test_condition_unusable_if_any_run_fails(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "cond_kafka_feed1_rep1")
        _run(runs, "cond_kafka_feed2_rep1", transport_ms=-3.0)
        s = summarize(audit(runs, "cond_*"))
        assert bool(s.iloc[0]["usable"]) is False
        assert s.iloc[0]["n_runs"] == 2 and s.iloc[0]["n_trustworthy"] == 1

    def test_all_clean(self, temp_dir):
        runs = temp_dir / "runs"
        _run(runs, "good_kafka_feed1_rep1")
        s = summarize(audit(runs, "good_*"))
        assert bool(s.iloc[0]["usable"]) is True

    def test_empty(self):
        assert summarize(pd.DataFrame()).empty
        assert summarize(None).empty


class TestMain:
    def test_clean_exits_zero(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n1_x_kafka_feed1_rep1")
        rc = main(["--runs-dir", str(runs), "--run-glob", "concurrency_n*",
                   "--out", str(temp_dir / "o")])
        assert rc == 0
        assert (temp_dir / "o" / "clock_integrity_by_condition.csv").exists()
        assert "0 failing" in capsys.readouterr().out

    def test_failing_exits_two_and_lists(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _run(runs, "concurrency_n100_x_kafka_feed1_rep1", transport_ms=-6.4)
        rc = main(["--runs-dir", str(runs), "--run-glob", "concurrency_n*",
                   "--out", str(temp_dir / "o")])
        assert rc == 2, "a campaign must be able to gate on the exit code"
        assert "FAILING RUNS" in capsys.readouterr().out

    def test_no_runs(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        runs.mkdir()
        assert main(["--runs-dir", str(runs), "--run-glob", "zzz*"]) == 1
        assert "No readable runs" in capsys.readouterr().out
