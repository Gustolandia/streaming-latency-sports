"""Tests for scripts/diagnose_tail.py - target 100% branch coverage."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from diagnose_tail import (  # noqa: E402
    load_trace,
    mode_share,
    warmup_effect,
    classify,
    analyze,
    main,
)


def _run(tmp, name, latencies_ms):
    d = tmp / name
    d.mkdir(parents=True)
    n = len(latencies_ms)
    sched = [i * 1_000_000 for i in range(n)]
    out = [s + int(l * 1e6) for s, l in zip(sched, latencies_ms)]
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n)],
                  "t_prod_sched_ns": sched}).to_csv(d / "producer.csv", index=False)
    pd.DataFrame({"event_id": [f"e{i}" for i in range(n)],
                  "t_output_ns": out}).to_csv(d / "consumer.csv", index=False)
    return d


class TestLoadTrace:
    def test_orders_and_computes(self, temp_dir):
        d = _run(temp_dir, "r", [1.0, 2.0, 3.0])
        t = load_trace(d)
        assert list(t["latency_ms"]) == pytest.approx([1.0, 2.0, 3.0])
        assert list(t["ordinal"]) == [0, 1, 2]

    def test_missing_files(self, temp_dir):
        d = temp_dir / "empty"
        d.mkdir()
        assert load_trace(d) is None

    def test_bad_schema(self, temp_dir):
        d = temp_dir / "bad"
        d.mkdir()
        (d / "producer.csv").write_text("x\n1\n")
        (d / "consumer.csv").write_text("x\n1\n")
        assert load_trace(d) is None

    def test_no_overlap(self, temp_dir):
        d = temp_dir / "r"
        d.mkdir()
        pd.DataFrame({"event_id": ["a"], "t_prod_sched_ns": [0]}).to_csv(
            d / "producer.csv", index=False)
        pd.DataFrame({"event_id": ["b"], "t_output_ns": [1]}).to_csv(
            d / "consumer.csv", index=False)
        assert load_trace(d) is None


class TestModeShare:
    def test_counts_and_locates(self, temp_dir):
        # slow events only at the very start => start-up shaped
        lat = [200.0] * 5 + [1.0] * 95
        t = load_trace(_run(temp_dir, "r", lat))
        s = mode_share(t, 50.0)
        assert s["n_above"] == 5
        assert s["share_above"] == pytest.approx(0.05)
        assert s["above_within_first_5pct"] == pytest.approx(1.0)

    def test_no_events_above(self, temp_dir):
        t = load_trace(_run(temp_dir, "r", [1.0] * 10))
        s = mode_share(t, 50.0)
        assert s["n_above"] == 0 and s["max_ordinal_above"] == -1
        assert np.isnan(s["median_ordinal_above"])

    def test_none_trace(self):
        assert mode_share(None, 50.0) is None

    def test_empty_trace(self):
        assert mode_share(pd.DataFrame(), 50.0) is None


class TestWarmupEffect:
    def test_excluding_startup_moves_mean_not_median(self, temp_dir):
        # This is the diagnostic that matters: if the excluded events are a tail artifact the
        # mean drops sharply while the median barely moves.
        lat = [500.0] * 10 + [1.0] * 190
        t = load_trace(_run(temp_dir, "r", lat))
        e = warmup_effect(t, 10)
        assert e["mean_delta"] < -20, "mean should fall a lot"
        assert abs(e["median_delta"]) < 0.5, "median should barely move"
        assert e["n_kept"] == 190

    def test_warmup_larger_than_run(self, temp_dir):
        t = load_trace(_run(temp_dir, "r", [1.0] * 5))
        assert warmup_effect(t, 100) is None

    def test_none_and_empty(self):
        assert warmup_effect(None, 10) is None
        assert warmup_effect(pd.DataFrame(), 10) is None


class TestClassify:
    def test_startup(self):
        assert classify({"n_above": 5, "above_within_first_5pct": 1.0}) == "startup-artifact"

    def test_steady_state(self):
        assert classify({"n_above": 50, "above_within_first_5pct": 0.1}) == "steady-state"

    def test_mixed(self):
        assert classify({"n_above": 50, "above_within_first_5pct": 0.5}) == "mixed"

    def test_no_mode(self):
        assert classify({"n_above": 0, "above_within_first_5pct": 0.0}) == "no-mode"

    def test_no_data(self):
        assert classify(None) == "no-data"


class TestAnalyze:
    def test_multiple_runs(self, temp_dir):
        a = _run(temp_dir, "a", [200.0] * 5 + [1.0] * 95)
        b = _run(temp_dir, "b", [1.0] * 100)
        df = analyze([a, b], 50.0, 10)
        assert set(df["verdict"]) == {"startup-artifact", "no-mode"}

    def test_skips_unreadable(self, temp_dir):
        bad = temp_dir / "bad"
        bad.mkdir()
        good = _run(temp_dir, "g", [1.0] * 50)
        assert len(analyze([bad, good], 50.0, 5)) == 1


class TestMain:
    def test_explicit_run_dir(self, temp_dir, capsys):
        d = _run(temp_dir, "r", [200.0] * 5 + [1.0] * 95)
        out = temp_dir / "tail"
        rc = main(["--run-dir", str(d), "--threshold-ms", "50", "--warmup", "5",
                   "--out", str(out)])
        assert rc == 0
        assert (out / "tail_diagnosis.csv").exists()
        cap = capsys.readouterr().out
        assert "startup-artifact" in cap and "verdicts" in cap

    def test_glob_selection(self, temp_dir, capsys):
        runs = temp_dir / "runs"
        _run(runs, "kafka_a", [1.0] * 40)
        _run(runs, "kafka_b", [1.0] * 40)
        _run(runs, "redis_c", [1.0] * 40)
        rc = main(["--runs-dir", str(runs), "--run-glob", "kafka_*",
                   "--out", str(temp_dir / "o")])
        assert rc == 0
        assert len(pd.read_csv(temp_dir / "o" / "tail_diagnosis.csv")) == 2

    def test_no_dirs_selected(self, capsys):
        assert main(["--runs-dir", "nowhere", "--run-glob", "zzz*"]) == 1
        assert "No run directories" in capsys.readouterr().out

    def test_no_readable_runs(self, temp_dir, capsys):
        d = temp_dir / "empty"
        d.mkdir()
        assert main(["--run-dir", str(d), "--out", str(temp_dir / "o")]) == 1
        assert "No readable runs" in capsys.readouterr().out
