"""Tests for scripts/delay_calibration.py, on calibration runs built to known answers.

The pilot that motivated the script found a Kafka slope of 0.89 and a Redis slope of 1.24, so
the synthetic runs use those, and the gate is tested against each way it can fail.
"""
import io
import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import delay_calibration as dc  # noqa: E402
import run_queue as rq  # noqa: E402

#: One C0 round's delay steps, zero twice, as law_design.py makes them.
STEPS = (0.0, 0.0, 1.0, 2.0, 4.0, 8.0)


def c0_runs(intercept=3.5, slope=0.89, curve=0.0, rounds=2, backend="kafka", load="75",
            wobble=0.01, gotit=2.5, gotit_per_ms=0.0, gotit_wobble=0.002, p99=3.0,
            negative_at=None, outlier_at=None, trips=None):
    """Runs whose trip is intercept + slope x + curve x^2, nudged up in odd rounds and down in
    even ones, so that every step has repeats that differ."""
    runs = []
    for rd in range(1, rounds + 1):
        sign = 1 if rd % 2 else -1
        for i, step in enumerate(STEPS):
            key = "r%d-%d" % (rd, i)
            trip = (trips or {}).get(step, intercept + slope * step + curve * step * step)
            trip += sign * wobble + (0.3 if key == outlier_at else 0.0)
            runs.append({"key": key, "round": str(rd), "backend": backend, "load": load,
                         "step": step, "x": step, "trip": trip,
                         "gotit": gotit + gotit_per_ms * step + sign * gotit_wobble,
                         "p99": p99 + sign * 0.005,
                         "negative": 1 if key == negative_at else 0})
    return runs


class TestDistributions:

    @pytest.mark.parametrize("x,expected", [(0.0, 0.0), (0.2, 0.1808), (0.5, 0.6875),
                                            (1.0, 1.0)])
    def test_the_incomplete_beta_function_against_a_closed_form(self, x, expected):
        """I_x(2, 3) = 6x^2 - 8x^3 + 3x^4; 0.2 and 0.5 sit on either side of the switch to the
        symmetric form."""
        assert dc.betainc(2.0, 3.0, x) == pytest.approx(expected, abs=1e-9)

    @pytest.mark.parametrize("df,expected", [(2, 2.919986), (10, 1.812461)])
    def test_t_quantiles_against_the_table(self, df, expected):
        assert dc.t_quantile(0.95, df) == pytest.approx(expected, abs=1e-5)

    def test_the_t_distribution_is_symmetric(self):
        assert dc.t_cdf(-1.3, 7) == pytest.approx(1.0 - dc.t_cdf(1.3, 7))

    def test_the_f_tail_against_the_table(self):
        assert dc.f_pvalue(4.3468, 3, 7) == pytest.approx(0.05, abs=2e-4)
        assert dc.f_pvalue(0.0, 3, 7) == 1.0
        assert dc.f_pvalue(math.inf, 3, 7) == 0.0


class TestTheLine:

    def test_least_squares_recovers_an_exact_line(self):
        assert dc.ols([(0, 3.5), (1, 4.39), (8, 10.62)]) == pytest.approx((3.5, 0.89))

    def test_one_delay_holds_no_slope(self):
        with pytest.raises(ValueError, match="two different delays"):
            dc.ols([(2.0, 4.0), (2.0, 4.1)])

    def test_the_interval_resamples_whole_rounds(self):
        """Each round is shifted as a whole, so every resample of whole rounds has the slope."""
        low, high = dc.slope_interval(c0_runs(), seed=3)
        assert low == pytest.approx(0.89) and high == pytest.approx(0.89)

    def test_rounds_without_two_delays_are_left_out_or_refused(self):
        runs = c0_runs(rounds=1)
        lone = [dict(runs[0], round="9")]
        assert dc.slope_interval(runs + lone, seed=1)[0] == pytest.approx(0.89)
        with pytest.raises(ValueError, match="no round measured two different delays"):
            dc.slope_interval(lone, seed=1)


class TestTheShape:

    def test_a_straight_relation_passes_the_line(self):
        runs = c0_runs()
        a, b = dc.ols([(r["x"], r["trip"]) for r in runs])
        shape = dc.lack_of_fit(runs, a, b)
        assert (shape["df_steps"], shape["df_repeats"]) == (3, 7) and shape["p"] > 0.5

    def test_a_curved_relation_fails_the_line(self):
        runs = c0_runs(intercept=2.0, slope=0.5, curve=0.1)
        a, b = dc.ols([(r["x"], r["trip"]) for r in runs])
        assert dc.lack_of_fit(runs, a, b)["p"] < 0.001

    def test_too_few_steps_cannot_be_tested(self):
        runs = [r for r in c0_runs() if r["step"] in (0.0, 8.0)]
        assert dc.lack_of_fit(runs, 3.5, 0.89) is None

    def test_repeats_that_agree_exactly(self):
        """Slope and intercept in binary fractions, so the arithmetic is exact."""
        runs = c0_runs(intercept=2.0, slope=1.25, wobble=0.0)
        assert dc.lack_of_fit(runs, 2.0, 1.25)["p"] == 1.0
        assert dc.lack_of_fit(runs, 3.0, 1.25) == {"f": None, "df_steps": 3, "df_repeats": 7,
                                                   "p": 0.0}


class TestPlacing:

    LINE = {"model": "line", "intercept_ms": 3.5, "slope": 0.89,
            "steps": [[0.0, 3.5], [1.0, 4.39], [2.0, 5.28], [4.0, 7.06], [8.0, 10.62]]}
    SEGMENTS = {"model": "segments", "intercept_ms": 1.7, "slope": 1.28,
                "steps": [[-0.02, 2.0], [1.0, 2.6], [2.0, 3.4], [4.0, 5.6], [8.0, 12.4]]}

    def test_a_line_places_a_trip_and_refuses_what_it_did_not_measure(self):
        assert dc.delay_for(self.LINE, 5.28) == pytest.approx(2.0)
        assert dc.delay_for(self.LINE, 3.0) is None, "below the zero-delay trip"
        assert dc.delay_for(self.LINE, 12.0) is None, "beyond the longest step"
        assert dc.predict(self.LINE, 2.0) == pytest.approx(5.28)

    def test_segments_place_by_interpolation(self):
        assert dc.delay_for(self.SEGMENTS, 4.5) == pytest.approx(3.0)
        assert dc.delay_for(self.SEGMENTS, 2.0) == 0.0, "the zero step's own trip needs no delay"
        assert dc.delay_for(self.SEGMENTS, 13.0) is None
        assert dc.predict(self.SEGMENTS, -1.0) == 2.0
        assert dc.predict(self.SEGMENTS, 6.0) == pytest.approx(9.0)
        assert dc.predict(self.SEGMENTS, 9.0) == 12.4


class TestGotIt:

    def test_a_difference_needs_two_runs_on_each_side_for_an_interval(self):
        assert dc._difference([1.0], [1.0, 2.0]) == (0.5, None)

    def test_identical_repeats_give_a_point_interval(self):
        assert dc._difference([1.0, 1.0], [2.0, 2.0]) == (1.0, [1.0, 1.0])

    def test_the_welch_interval(self):
        diff, ci = dc._difference([0.0, 0.2], [0.1, 0.3])
        half = 2.919986 * math.sqrt(0.02)
        assert diff == pytest.approx(0.1)
        assert ci == pytest.approx([0.1 - half, 0.1 + half], abs=1e-5)

    def test_an_unmoved_got_it_is_equivalent_at_every_step(self):
        checks = dc.gotit_checks(c0_runs())
        assert [c["step_ms"] for c in checks] == [1.0, 2.0, 4.0, 8.0]
        assert all(c["median_equivalent"] and c["p99_equivalent"] and not c["gross"]
                   for c in checks)

    def test_a_noisy_got_it_is_not_shown_equivalent_but_is_not_gross(self):
        checks = dc.gotit_checks(c0_runs(gotit_wobble=0.3))
        assert not any(c["median_equivalent"] for c in checks)
        assert not any(c["gross"] for c in checks)

    def test_a_got_it_that_follows_the_delay_is_gross(self):
        assert all(c["gross"] for c in dc.gotit_checks(c0_runs(gotit_per_ms=-0.5)))

    def test_without_got_it_values_there_is_nothing_to_check(self):
        assert dc.gotit_checks([dict(r, gotit=None) for r in c0_runs()]) == []


class TestTheGate:

    def test_the_pilots_kafka_slope_passes(self):
        entry = dc.fit_entry(c0_runs(), seed=1)
        assert entry["model"] == "line" and entry["gate"]["ok"]
        assert entry["slope"] == pytest.approx(0.89)
        assert entry["intercept_ms"] == pytest.approx(3.5)
        assert (entry["runs"], entry["rounds"]) == (12, 2)
        assert entry["residual_max_ms"] == pytest.approx(0.01)

    def test_a_curved_relation_is_placed_by_segments(self):
        entry = dc.fit_entry(c0_runs(intercept=2.0, slope=0.5, curve=0.1), seed=1)
        assert entry["model"] == "segments" and entry["gate"]["ok"]
        assert entry["residual_max_ms"] == pytest.approx(0.01)

    @pytest.mark.parametrize("kwargs,failed", [
        ({"slope": 0.3}, "slope_above_half"),
        ({"outlier_at": "r1-0"}, "runs_within_0_1_ms"),
        ({"trips": {4.0: 4.0}}, "longer_delay_longer_trip"),
        ({"negative_at": "r2-3"}, "never_negative"),
        ({"gotit_per_ms": -0.5}, "no_gross_gotit_departure"),
    ])
    def test_each_way_the_gate_fails(self, kwargs, failed):
        gate = dc.fit_entry(c0_runs(**kwargs), seed=1)["gate"]
        assert not gate["ok"] and not gate[failed]

    def test_the_zero_delay_got_it_median_later_runs_are_held_against(self):
        """run_integrity.py compares each main run's "got it" median with this one."""
        assert dc.fit_entry(c0_runs(), seed=1)["gotit_zero_median_ms"] == pytest.approx(2.5)
        no_zero = [dict(r, gotit=None) if r["step"] == 0.0 else r for r in c0_runs()]
        assert dc.fit_entry(no_zero, seed=1)["gotit_zero_median_ms"] is None


def queue_rows(runs):
    """The runs as a finished C0 queue holds them."""
    return [{"key": r["key"], "round": r["round"], "setup": "C0-%s" % r["key"],
             "params": json.dumps({"backend": r["backend"], "load_pct": int(r["load"]),
                                   "delay_ms": r["step"]}),
             "status": "done", "attempt": "1", "reason": "", "started_utc": "",
             "finished_utc": "", "run_dir": "runs/%s-%s" % (r["backend"], r["key"]),
             "seed": "1"}
            for r in runs]


def readers(runs, offset=0.3):
    """Stand-ins for summarise and read_delay that give back the runs' own numbers."""
    by_dir = {"runs/%s-%s" % (r["backend"], r["key"]): r for r in runs}

    def summarise(run_dir, warmup_s):
        r = by_dir[run_dir]
        return {"trip_median_ms": r["trip"], "gotit_median_ms": r["gotit"],
                "gotit_p99_ms": r["p99"], "trip_negative": r["negative"]}

    def read_delay(run_dir):
        return 0.5, 0.5 + offset + by_dir[run_dir]["step"]

    return summarise, read_delay


class TestFromTheQueue:

    def test_the_measured_delay_is_taken_against_the_zero_delay_runs(self):
        runs = c0_runs()
        rows = queue_rows(runs) + [dict(queue_rows(runs)[0], key="x", status="failed",
                                        run_dir="")]
        got, offset = dc.runs_from_queue(rows, *readers(runs))
        assert offset == pytest.approx(0.3) and len(got) == 12
        assert sorted({round(r["x"], 6) for r in got}) == [0.0, 1.0, 2.0, 4.0, 8.0]

    def test_a_queue_with_nothing_finished(self):
        runs = c0_runs()
        rows = [dict(r, status="queued", run_dir="") for r in queue_rows(runs)]
        with pytest.raises(ValueError, match="no finished calibration runs"):
            dc.runs_from_queue(rows, *readers(runs))

    def test_a_queue_without_a_zero_delay_run(self):
        runs = [r for r in c0_runs() if r["step"] > 0]
        with pytest.raises(ValueError, match="no finished zero-delay run"):
            dc.runs_from_queue(queue_rows(runs), *readers(runs))

    def test_the_delay_file_is_read(self, tmp_path):
        (tmp_path / "delay_measured.json").write_text(
            json.dumps({"host_median_ms": 1.1, "receiver_median_ms": 3.2}), encoding="utf-8")
        assert dc.read_delay_file(str(tmp_path)) == (1.1, 3.2)

    def test_backends_are_calibrated_apart(self):
        cal = dc.calibrate(c0_runs() + c0_runs(backend="redis", intercept=2.2, slope=1.24))
        assert set(cal) == {"kafka", "redis"}
        assert cal["redis"]["75"]["slope"] == pytest.approx(1.24)


class TestMain:

    @staticmethod
    def run(argv, **kw):
        out = io.StringIO()
        return dc.main(argv, out=out, **kw), out.getvalue()

    def fit(self, tmp_path, runs):
        queue = tmp_path / "c0.csv"
        rq.write_queue(str(queue), queue_rows(runs))
        dest = tmp_path / "cal.json"
        summarise, read_delay = readers(runs)
        code, text = self.run(["fit", "--queue", str(queue), "--out", str(dest), "--seed", "4"],
                              summarise=summarise, read_delay=read_delay)
        return code, text, dest

    def test_fit_writes_the_calibration_and_passes(self, tmp_path):
        code, text, dest = self.fit(tmp_path, c0_runs())
        assert code == 0 and "kafka at 75%: trip = 3.500 + 0.890 x delay" in text
        assert text.rstrip().endswith("line, gate passed")
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert saved["zero_offset_ms"] == pytest.approx(0.3)
        assert saved["calibration"]["kafka"]["75"]["model"] == "line"

    def test_fit_names_the_part_of_the_gate_that_failed(self, tmp_path):
        code, text, _ = self.fit(tmp_path, c0_runs(slope=0.3))
        assert code == 1 and "GATE FAILED: slope_above_half" in text

    def test_place(self, tmp_path):
        _, _, dest = self.fit(tmp_path, c0_runs())
        argv = ["place", "--calibration", str(dest), "--backend", "kafka", "--load", "75",
                "--trip-ms"]
        code, text = self.run(argv + ["5.28"])
        assert code == 0 and json.loads(text)["delay_ms"] == pytest.approx(2.0)
        code, text = self.run(argv + ["1.0"])
        assert code == 1 and json.loads(text)["delay_ms"] is None

    def test_errors_are_lines(self, tmp_path):
        code, text = self.run(["fit", "--queue", str(tmp_path / "none.csv"),
                               "--out", str(tmp_path / "c.json")])
        assert code == 2 and text.startswith("ERROR:")
