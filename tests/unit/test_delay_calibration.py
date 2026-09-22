"""Tests for scripts/delay_calibration.py, on calibration runs built to known answers.

The pilot that motivated the script found a Kafka slope of 0.89 and a Redis slope of 1.24, so
the synthetic runs use those, and the gate is tested against each way it can fail.
"""
import io
import json
import math
import re
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
            negative_at=None, trips=None, first_round=1):
    """Runs whose trip is intercept + slope x + curve x^2, nudged up in odd rounds and down in
    even ones, so that every step has repeats that differ."""
    runs = []
    for rd in range(first_round, first_round + rounds):
        sign = 1 if rd % 2 else -1
        for i, step in enumerate(STEPS):
            key = "r%d-%d" % (rd, i)
            trip = (trips or {}).get(step, intercept + slope * step + curve * step * step)
            trip += sign * wobble
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
        assert [x for x, _ in entry["halfwidths_ms"]] == pytest.approx([0.0, 1.0, 2.0, 4.0, 8.0])
        assert 0.0 < entry["halfwidth_max_ms"] < 0.03

    def test_the_line_is_known_worst_far_from_its_middle(self):
        """t(10) s sqrt(1/n + (x - mean)^2 / Sxx), with s from the scatter about the line."""
        widths = [w for _, w in dc.fit_entry(c0_runs(wobble=0.1), seed=1)["halfwidths_ms"]]
        s = math.sqrt(12 * 0.01 / 10)
        at_8 = dc.t_quantile(0.975, 10) * s * math.sqrt(1 / 12 + (8 - 2.5) ** 2 / 95)
        assert widths[-1] == pytest.approx(at_8) and widths[-1] == max(widths)

    def test_a_curved_relation_is_placed_by_segments(self):
        entry = dc.fit_entry(c0_runs(intercept=2.0, slope=0.5, curve=0.1), seed=1)
        assert entry["model"] == "segments" and entry["gate"]["ok"]
        assert entry["residual_max_ms"] == pytest.approx(0.01)
        assert entry["step_residuals_ms"] == [0.0] * 5, "the segments pass through the steps"

    def test_the_segments_are_known_from_the_scatter_within_steps(self):
        """The zero step holds four runs, so its median counts as sqrt(pi/2) less precise than a
        mean; the other steps hold two, whose median is their mean."""
        entry = dc.fit_entry(c0_runs(intercept=2.0, slope=0.5, curve=0.1, wobble=0.05), seed=1)
        assert entry["model"] == "segments"
        s = math.sqrt(12 * 0.0025 / 7)
        t = dc.t_quantile(0.975, 7)
        widths = [w for _, w in entry["halfwidths_ms"]]
        assert widths[0] == pytest.approx(t * s * math.sqrt(math.pi / 2) / 2)
        assert widths[1:] == pytest.approx([t * s / math.sqrt(2)] * 4)

    def test_runs_that_scatter_need_more_rounds_and_are_still_reported(self):
        """The second x86 pair's runs scattered around its calibration by 0.18 to 0.27 ms.
        Version 5's 0.1 ms on every run could never pass them; two rounds leave the line too
        loosely known at its far end, and four know it well enough."""
        two = dc.fit_entry(c0_runs(wobble=0.25), seed=1)
        assert two["model"] == "line" and not two["gate"]["known_within_the_bound"]
        assert dc.needs_more_rounds({"kafka": {"75": two}})
        assert two["residual_max_ms"] == pytest.approx(0.25)
        assert max(abs(v) for v in two["step_residuals_ms"]) == pytest.approx(0.0, abs=1e-9)
        four = dc.fit_entry(c0_runs(wobble=0.25, rounds=4), seed=1)
        assert four["gate"]["ok"] and four["halfwidth_max_ms"] < dc.KNOWN_WITHIN_MS

    def test_too_few_runs_to_say_how_well_the_line_is_known(self):
        runs = [r for r in c0_runs(rounds=1) if r["step"] in (0.0, 1.0)][1:]
        entry = dc.fit_entry(runs, seed=1)
        assert entry["model"] == "line" and entry["halfwidths_ms"] == [[0.0, None], [1.0, None]]
        assert entry["halfwidth_max_ms"] is None and not entry["gate"]["known_within_the_bound"]

    @pytest.mark.parametrize("failed,more", [
        ((), False),
        (("known_within_the_bound",), True),
        (("known_within_the_bound", "slope_above_half"), False),
        (("never_negative",), False),
    ])
    def test_only_a_calibration_that_lacks_precision_gets_more_rounds(self, failed, more):
        good = {k: True for k in ("never_negative", "slope_above_half", "known_within_the_bound",
                                  "longer_delay_longer_trip", "no_gross_gotit_departure")}
        bad = dict(good, **{k: False for k in failed})
        cal = {"kafka": {"75": {"gate": dict(good, ok=True)}},
               "redis": {"75": {"gate": dict(bad, ok=not failed)}}}
        assert dc.needs_more_rounds(cal) is more

    @pytest.mark.parametrize("kwargs,failed", [
        ({"slope": 0.3}, "slope_above_half"),
        ({"wobble": 0.3}, "known_within_the_bound"),
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

    def test_the_delay_is_read_from_the_brokers_capture(self, tmp_path):
        (tmp_path / "delay_hold.json").write_text(
            json.dumps({"host_hold_ms": 0.015, "receiver_hold_ms": 2.033}), encoding="utf-8")
        assert dc.read_delay_file(str(tmp_path)) == (0.015, 2.033)

    @pytest.mark.parametrize("text", [None, '{"host_hold_ms": 0.015}'])
    def test_a_run_without_its_capture_cannot_be_calibrated(self, tmp_path, text):
        if text is not None:
            (tmp_path / "delay_hold.json").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match="no broker capture of its delay pings"):
            dc.read_delay_file(str(tmp_path))

    def test_backends_are_calibrated_apart(self):
        cal = dc.calibrate(c0_runs() + c0_runs(backend="redis", intercept=2.2, slope=1.24))
        assert set(cal) == {"kafka", "redis"}
        assert cal["redis"]["75"]["slope"] == pytest.approx(1.24)


class TestMain:

    @staticmethod
    def run(argv, **kw):
        out = io.StringIO()
        return dc.main(argv, out=out, **kw), out.getvalue()

    def fit(self, tmp_path, runs, *stages):
        """Fit the runs from one queue, or from one queue per stage when stages are given."""
        summarise, read_delay = readers(runs + [r for stage in stages for r in stage])
        argv = ["fit"]
        for n, part in enumerate((runs,) + stages):
            queue = tmp_path / ("c0_%d.csv" % n)
            rq.write_queue(str(queue), queue_rows(part))
            argv += ["--queue", str(queue)]
        dest = tmp_path / "cal.json"
        code, text = self.run(argv + ["--out", str(dest), "--seed", "4"],
                              summarise=summarise, read_delay=read_delay)
        return code, text, dest

    def test_fit_writes_the_calibration_and_passes(self, tmp_path):
        code, text, dest = self.fit(tmp_path, c0_runs())
        assert code == 0 and "kafka at 75%: trip = 3.500 + 0.890 x delay" in text
        assert re.search(r"line, known within 0\.0\d\d ms, gate passed$", text.rstrip())
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert saved["zero_offset_ms"] == pytest.approx(0.3)
        assert saved["calibration"]["kafka"]["75"]["model"] == "line"
        assert saved["queues"] == [str(tmp_path / "c0_0.csv")]

    def test_a_second_stage_is_fitted_with_the_first(self, tmp_path):
        """Two rounds leave the scattered line too loosely known; the next two mend it."""
        code, text, dest = self.fit(tmp_path, c0_runs(wobble=0.25))
        assert code == 1 and "GATE FAILED: known_within_the_bound" in text
        assert self.run(["needs-rounds", "--calibration", str(dest)]) == (
            0, "more rounds can make the calibration precise enough\n")
        code, text, dest = self.fit(tmp_path, c0_runs(wobble=0.25),
                                    c0_runs(wobble=0.25, first_round=3))
        saved = json.loads(dest.read_text(encoding="utf-8"))
        assert code == 0 and saved["calibration"]["kafka"]["75"]["rounds"] == 4
        assert len(saved["queues"]) == 2
        assert self.run(["needs-rounds", "--calibration", str(dest)]) == (
            1, "more rounds would not change what the gate found\n")

    def test_two_stages_never_share_a_round(self, tmp_path):
        code, text, _ = self.fit(tmp_path, c0_runs(), c0_runs(first_round=2))
        assert code == 2 and "both hold round 2" in text

    def test_a_line_from_too_few_runs_says_so(self, tmp_path):
        runs = [r for r in c0_runs(rounds=1) if r["step"] in (0.0, 1.0)]
        code, text, _ = self.fit(tmp_path, runs[:1] + runs[2:])
        assert code == 1 and "known within ? ms" in text

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


class TestTheBoundFollowsTheTick:
    """A calibration cannot be known to a fraction of the quantum its trips are quantised by.

    0.30 ms was set on the stock kernel, whose tick is 1 ms. A2 boots two kernels where the tick
    is 4 and 10 ms, and on the second x86 pair Kafka came in at 0.410 at HZ=250 and 0.387 at
    HZ=100, against 0.128 to 0.237 for Redis on the same boots. Four rounds did not mend it,
    because it is not imprecision to be averaged away. Three sessions were refused for it on
    22 September before the bound was made to follow the tick.
    """

    def _fit(self, tick_ms, wobble=0.0):
        runs = c0_runs(wobble=wobble)
        for run in runs:
            run["tick_ms"] = tick_ms
        return dc.fit_entry(runs, seed=1)

    @pytest.mark.parametrize("tick_ms,bound", [(1.0, 0.30), (4.0, 0.60), (10.0, 1.50)])
    def test_the_bound_is_the_larger_of_a_floor_and_a_share_of_the_tick(self, tick_ms, bound):
        assert self._fit(tick_ms)["known_within_bound_ms"] == pytest.approx(bound)

    def test_the_bound_it_used_is_written_beside_the_gate(self):
        """So a reader never has to work out which bound applied to a given session."""
        assert "known_within_bound_ms" in self._fit(4.0)

    def test_a_calibration_that_fails_on_a_fine_tick_passes_on_a_coarse_one(self):
        """The same scatter, judged against the tick it was measured on."""
        fine = self._fit(1.0, wobble=0.25)
        coarse = self._fit(10.0, wobble=0.25)
        assert fine["halfwidth_max_ms"] == pytest.approx(coarse["halfwidth_max_ms"])
        assert fine["gate"]["known_within_the_bound"] is False
        assert coarse["gate"]["known_within_the_bound"] is True

    def test_runs_that_carry_no_tick_are_held_to_the_floor(self):
        """Every calibration before 22 September wrote no tick into its rows, and none of them
        ran on anything but a 1 ms tick, so the floor is the bound that applied to them."""
        runs = c0_runs()
        for run in runs:
            run.pop("tick_ms", None)
        assert dc.fit_entry(runs, seed=1)["known_within_bound_ms"] == pytest.approx(0.30)

    def test_a_row_missing_its_tick_cannot_lower_the_bound(self):
        """One run of a coarse-tick session arriving without its tick must not quietly put that
        whole session back on the fine-tick bound."""
        runs = c0_runs()
        for run in runs:
            run["tick_ms"] = 10.0
        runs[0]["tick_ms"] = None
        assert dc.fit_entry(runs, seed=1)["known_within_bound_ms"] == pytest.approx(1.50)
