"""Tests for the three referee-round pipeline scripts (TPDS round 1, M4/M5/Q5).

Each script is tested twice over: against the committed artefacts (the numbers the
manuscript quotes must be reproducible from the repository) and against synthetic
fixtures that force every failure branch the scripts promise to take.
"""
import csv
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import powered_gate_sensitivity as pgs  # noqa: E402
import threshold_condition_sweep as tcs  # noqa: E402
import traced_tail_slope as tts  # noqa: E402


def _write(path, rows, fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- threshold sweep

AUDIT_COLS = ["run_id", "max_neg_fraction", "median_transport_ms",
              "median_schedlag_ms", "median_output_ms"]


def _audit_row(run_id, frac=0.0, med=1.0):
    return dict(zip(AUDIT_COLS, [run_id, str(frac), str(med), "1.0", "0.0"]))


class TestThresholdConditionSweep:
    def test_run_passes_all_three_outcomes(self):
        assert tcs.run_passes(_audit_row("a"), 0.01)
        assert not tcs.run_passes(_audit_row("a", frac=0.5), 0.01)
        assert not tcs.run_passes(_audit_row("a", med=-1.0), 0.01)

    def test_sweep_counts_missing_runs(self):
        first = [{"run_id": "a", "backend": "kafka", "n": "1"},
                 {"run_id": "ghost", "backend": "kafka", "n": "1"}]
        rows, missing = tcs.sweep(first, {"a": _audit_row("a")}, thresholds=(0.01,))
        assert missing == 1
        assert rows == [{"threshold": 0.01, "backend": "kafka", "n": 1,
                         "n_pass": 1, "n_runs": 1, "usable": True}]

    def test_main_confirms_the_papers_sentence_on_the_real_corpus(self, tmp_path):
        out = tmp_path / "sweep.csv"
        assert tcs.main(["--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out)))
        assert len(rows) == len(tcs.THRESHOLDS) * 6
        assert all(r["usable"] == "False" for r in rows), \
            "a first-result cell became usable inside the swept range"
        # The endpoint the manuscript quotes: even at 20%, the best cell is 23/30.
        at_20 = [r for r in rows if r["threshold"] == "0.2"]
        assert max(int(r["n_pass"]) for r in at_20) == 23

    def test_main_fails_loudly_if_a_cell_is_resurrected(self, tmp_path):
        first = tmp_path / "first.csv"
        audit = tmp_path / "audit.csv"
        _write(first, [{"run_id": "a", "backend": "kafka", "n": "1"}])
        _write(audit, [_audit_row("a", frac=0.15)], AUDIT_COLS)
        rc = tcs.main(["--first-result", str(first), "--audit", str(audit),
                       "--out", str(tmp_path / "o.csv")])
        assert rc == 1

    def test_main_fails_loudly_on_missing_audit_rows(self, tmp_path):
        first = tmp_path / "first.csv"
        audit = tmp_path / "audit.csv"
        _write(first, [{"run_id": "ghost", "backend": "kafka", "n": "1"}])
        _write(audit, [_audit_row("a")], AUDIT_COLS)
        rc = tcs.main(["--first-result", str(first), "--audit", str(audit),
                       "--out", str(tmp_path / "o.csv")])
        assert rc == 2


# ---------------------------------------------------------- powered gate sensitivity

BY_RUN_COLS = ["run_id", "backend", "config", "n", "tti_p50", "tti_p95",
               "transport_p50", "transport_p95", "schedlag_p50", "n_matched"]
IDX_COLS = ["run_id", "transport_integrity", "frac_negative_transport"]


def _by_run(run_id, backend, n, p50, matched=100):
    return dict(zip(BY_RUN_COLS,
                    [run_id, backend, "single", n, "1", "2", str(p50), "3", "1",
                     str(matched)]))


class TestPoweredGateSensitivity:
    def _fixture(self, tmp_path, redis_condemned_value="0.1", verdict="condemned"):
        corpus = tmp_path / "corpus"
        by_run, idx = [], []
        for i in range(4):
            by_run.append(_by_run(f"k{i}", "kafka", "1", 0.5))
            idx.append(dict(zip(IDX_COLS, [f"k{i}", "usable", "0.0"])))
        for i in range(4):
            by_run.append(_by_run(f"r{i}", "redis", "1", 0.1))
            idx.append(dict(zip(IDX_COLS, [f"r{i}", "usable", "0.0"])))
        by_run.append(_by_run("rc", "redis", "1", redis_condemned_value))
        idx.append(dict(zip(IDX_COLS, ["rc", verdict, "0.05"])))
        _write(corpus / "transport_realtime_by_run.csv", by_run, BY_RUN_COLS)
        index = tmp_path / "index.csv"
        _write(index, idx, IDX_COLS)
        return corpus, index

    def test_load_gated_splits_three_ways(self, tmp_path):
        corpus, index = self._fixture(tmp_path)
        rows = list(csv.DictReader(open(corpus / "transport_realtime_by_run.csv")))
        idx = {r["run_id"]: r for r in csv.DictReader(open(index))}
        del idx["rc"]
        usable, condemned, unknown = pgs.load_gated(rows, idx)
        assert (len(usable), len(condemned), len(unknown)) == (8, 0, 1)

    def test_flip_point_none_without_condemned_runs(self):
        assert pgs.flip_point([0.5], [0.1], 0) is None
        assert pgs.flip_point([], [0.1], 3) is None

    def test_flip_point_none_when_no_value_flips(self):
        # one condemned run against many usable ones cannot move the HL median sign
        assert pgs.flip_point([0.5] * 9, [0.1] * 9, 1) is None

    def test_flip_point_finds_the_crossing(self):
        v = pgs.flip_point([0.5, 0.5], [0.1], 3)
        assert v is not None and v >= 0.5

    def test_main_ok_path_writes_all_three_artefacts(self, tmp_path):
        corpus, index = self._fixture(tmp_path)
        assert pgs.main(["--corpus", str(corpus), "--index", str(index)]) == 0
        for name in ("transport_realtime_by_run_gated.csv",
                     "transport_realtime_summary_gated.csv", "gate_sensitivity.csv"):
            assert (corpus / name).exists()
        cell = list(csv.DictReader(open(corpus / "gate_sensitivity.csv")))[0]
        assert cell["condemned_redis_median_ms"] == "0.1"
        summ = list(csv.DictReader(open(corpus / "transport_realtime_summary_gated.csv")))
        assert summ[0]["kafka_runs"] == "4" and summ[0]["redis_runs"] == "4"

    def test_main_fails_on_missing_verdict(self, tmp_path):
        corpus, index = self._fixture(tmp_path, verdict="usable")
        idx = [r for r in csv.DictReader(open(index)) if r["run_id"] != "rc"]
        _write(index, idx, IDX_COLS)
        assert pgs.main(["--corpus", str(corpus), "--index", str(index)]) == 2

    def test_main_fails_when_the_gate_moves_the_shift(self, tmp_path):
        # condemned Redis runs at a huge value and in the majority: the ungated HL
        # median crosses into the condemned mass, so gated vs ungated differ materially
        corpus, index = self._fixture(tmp_path)
        by_run = list(csv.DictReader(open(corpus / "transport_realtime_by_run.csv")))
        idx = list(csv.DictReader(open(index)))
        for i in range(5):
            by_run.append(_by_run(f"rc{i}", "redis", "1", 30.0))
            idx.append(dict(zip(IDX_COLS, [f"rc{i}", "condemned", "0.05"])))
        _write(corpus / "transport_realtime_by_run.csv", by_run, BY_RUN_COLS)
        _write(index, idx, IDX_COLS)
        assert pgs.main(["--corpus", str(corpus), "--index", str(index)]) == 1

    def test_real_corpora_reproduce_the_quoted_sensitivity(self):
        idx = {r["run_id"]: r for r in csv.DictReader(
            open(REPO / "reproducibility" / "runs_index_cloud.csv"))}
        for tag, worst_delta in (("transport_rt", 0.003), ("transport_rt2", 0.017)):
            rows = list(csv.DictReader(
                open(REPO / "docs" / "results" / tag / "transport_realtime_by_run.csv")))
            for n in sorted({r["n"] for r in rows}, key=int):
                cell = pgs.analyse_cell(rows, idx, n)
                assert abs(cell["hl_gate_delta_ms"]) <= worst_delta, (tag, n)
                if cell["flip_v_ms"] is not None:
                    assert cell["flip_v_ms"] >= 0.55, (tag, n)
                    # flip point sits far above what condemned runs actually measured
                    assert cell["flip_v_ms"] > 4 * float(cell["condemned_redis_median_ms"])


# ------------------------------------------------------------------ traced tail slope

HIST = """Attaching 3 probes...

@count: 100
@usecs:
[256, 512)      40 |@@@@|
[512, 1K)       30 |@@@|
[1K, 2K)        20 |@@|
[2K, 4K)        10 |@|
"""


class TestTracedTailSlope:
    def test_bound_us_parses_plain_and_suffixed(self):
        assert tts._bound_us("512") == 512
        assert tts._bound_us("1K") == 1024
        assert tts._bound_us("2M") == 2 * 1024 ** 2

    def test_parse_survival_and_local_slopes(self, tmp_path):
        f = tmp_path / "runqlat.txt"
        f.write_text(HIST, encoding="utf-8")
        buckets = tts.parse_histogram(f.read_text().splitlines())
        assert buckets == [(256, 40), (512, 30), (1024, 20), (2048, 10)]
        surv = tts.survival(buckets)
        assert surv[0] == (256, 1.0, 100) and abs(surv[1][1] - 0.6) < 1e-9
        slopes = tts.local_slopes(surv)
        assert slopes[-1][3] is None            # last boundary has no successor
        assert all(sl is not None for _, _, _, sl in slopes[:-1])

    def test_local_slopes_survive_a_zero_survival_point(self):
        slopes = tts.local_slopes([(1, 0.5, 5), (2, 0.0, 0), (4, 0.0, 0)])
        assert slopes[0][3] is None and slopes[1][3] is None

    def test_window_slope_needs_three_points(self):
        surv = [(256, 1.0, 10), (512, 0.5, 5)]
        assert tts.window_slope(surv, 256, 512) is None

    def test_main_ok_on_the_real_capture(self, tmp_path):
        out = tmp_path / "slope.csv"
        assert tts.main(["--out", str(out)]) == 0
        rows = list(csv.DictReader(open(out)))
        windows = {(r["lo_us"], r["hi_us"]): r["index"]
                   for r in rows if r["kind"] == "window"}
        # The two numbers the manuscript quotes: ~0.33 through the co-located decade,
        # steepening past 4 beyond 4 ms.
        assert abs(float(windows[("256", "2048")]) - 0.332) < 0.005
        assert float(windows[("4096", "32768")]) > 4.0
        s512 = [r for r in rows if r["kind"] == "boundary" and r["lo_us"] == "512"][0]
        assert abs(float(s512["survival"]) - 0.1799) < 0.001

    def test_main_fails_without_a_histogram(self, tmp_path):
        f = tmp_path / "runqlat.txt"
        f.write_text("@count: 5\n", encoding="utf-8")
        assert tts.main(["--runqlat", str(f), "--out", str(tmp_path / "o.csv")]) == 2

    def test_main_fails_if_the_far_tail_is_shallower(self, tmp_path):
        # near decade decays fast, far tail nearly flat: steepening statement false
        reversed_shape = """@usecs:
[256, 512)      40 |@@@@|
[512, 1K)       20 |@@|
[1K, 2K)        10 |@|
[2K, 4K)        1 |@|
[4K, 8K)        1 |@|
[8K, 16K)       1 |@|
[16K, 32K)      27 |@@@|
"""
        f = tmp_path / "runqlat.txt"
        f.write_text(reversed_shape, encoding="utf-8")
        assert tts.main(["--runqlat", str(f), "--out", str(tmp_path / "o.csv")]) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
