"""Tests for scripts/law_design.py.

A run list decides at which trips the law is tested, so these tests pin the arithmetic that
places them: the points against the slice and the tick, the delays against the measured
baseline, the unreachable points kept visible, the core-count block's prediction from the
machine's own constant, and the repeats against the measured spread.
"""
import io
import json
import math
import os
import re
import statistics
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import law_design as ld  # noqa: E402
import run_queue as rq  # noqa: E402

#: What sched_settings.py read returned on the first Azure driver.
AZURE = {"release": "6.8.0-1064-azure", "tick_ms": 1.0, "config_hz": 1000, "online_cpus": 8,
         "tunable_scaling": "log", "base_slice_ns": 2800000, "normalised_slice_ns": 700000}
BASELINE = {"kafka": {"50": 0.40, "75": 0.45, "88": 0.55},
            "redis": {"50": 0.25, "75": 0.30, "88": 0.40}}


def by_id(setups):
    return {s["id"]: s for s in setups}


class TestPoints:

    def test_the_eight_trips_for_a_slice_and_a_tick(self):
        trips = [ld.trip_ms(p, 1.5, 1.0) for p in ld.EIGHT]
        assert trips == pytest.approx([0.75, 1.35, 1.7, 1.9, 2.1, 2.3, 3.0, 5.0])

    @pytest.mark.parametrize("s,h", [(0.75, 1.0), (3.0, 1.0), (6.0, 4.0)])
    def test_every_point_sits_where_its_name_says(self, s, h):
        for point in ld.POINT_FORM:
            trip = ld.trip_ms(point, s, h)
            if point.startswith("p"):
                assert trip <= s, point
            elif point.startswith("c"):
                assert s < trip < s + h, point
            else:
                assert trip >= s + h, point


class TestBlocks:

    @pytest.mark.parametrize("block,size", [("B0", 6), ("P0", 16), ("A1", 96), ("A2", 32),
                                            ("A3", 72), ("A4", 48), ("A5", 48), ("A7", 24)])
    def test_every_block_is_its_full_product(self, block, size):
        setups, unreachable = ld.make_setups(block, 1.0, BASELINE, AZURE)
        assert len(setups) + len(unreachable) == size

    def test_a_point_below_the_baseline_is_kept_visible_rather_than_dropped(self):
        setups, unreachable = ld.make_setups("A1", 1.0, BASELINE, AZURE)
        assert [u["id"] for u in unreachable] == ["A1-kafka-l75-s750-p05s"]
        assert "A1-redis-l75-s750-p05s" in by_id(setups)

    def test_a_delay_is_the_target_minus_the_measured_baseline(self):
        setup = by_id(ld.make_setups("A1", 1.0, BASELINE, AZURE)[0])["A1-redis-l75-s1500-c04h"]
        assert (setup["target_trip_ms"], setup["baseline_trip_ms"], setup["delay_ms"]) == (
            1.9, 0.3, 1.6)
        assert setup["slice_ns"] == 1500000 and setup["trace_half"] is True

    def test_ids_are_unique_and_can_name_a_kafka_topic(self):
        for block in ld.BLOCKS:
            setups, unreachable = ld.make_setups(block, 1.0, BASELINE, AZURE)
            ids = [s["id"] for s in setups + unreachable]
            assert len(set(ids)) == len(ids), block
            assert all(re.fullmatch(r"[A-Za-z0-9._-]+", i) for i in ids), block

    def test_the_core_count_block_predicts_from_the_machines_own_constant(self):
        setups = by_id(ld.make_setups("A5", 1.0, BASELINE, AZURE)[0])
        assert setups["A5-kafka-l75-c2-c04h"]["predicted_slice_ns"] == 1400000
        assert setups["A5-kafka-l75-c8-c04h"]["predicted_slice_ns"] == 2800000
        assert setups["A5-kafka-l75-c8-c04h"]["slice_ns"] is None, "the kernel keeps its own"
        assert setups["A5-kafka-l75-c4-c04h"]["target_trip_ms"] == pytest.approx(2.5)

    def test_without_that_constant_the_release_rule_is_used(self):
        setups = by_id(ld.make_setups("A5", 1.0, BASELINE, dict(AZURE, normalised_slice_ns=None))[0])
        assert setups["A5-redis-l75-c8-c04h"]["predicted_slice_ns"] == 3000000

    def test_the_core_count_block_refuses_to_guess(self):
        with pytest.raises(ValueError, match="carry neither"):
            ld.make_setups("A5", 1.0, BASELINE, {"tick_ms": 1.0})

    def test_go_first_doubles_its_block(self):
        setups = by_id(ld.make_setups("A7", 1.0, BASELINE, AZURE)[0])
        assert setups["A7-kafka-l75-s1500-c05h-rt"]["priority"] is True
        assert setups["A7-kafka-l75-s1500-c05h"]["priority"] is False

    def test_the_baseline_block_adds_no_delay_and_keeps_the_kernels_slice(self):
        setups = ld.make_setups("B0", 1.0)[0]
        assert {(s["delay_ms"], s["slice_ns"], s["point"]) for s in setups} == {
            (0.0, None, "base")}

    def test_a_baseline_missing_a_load_is_named(self):
        partial = {"kafka": BASELINE["kafka"], "redis": {"50": 0.2, "75": 0.3}}
        with pytest.raises(ValueError, match="no redis trip at 88% load"):
            ld.make_setups("A3", 1.0, partial, AZURE)


class TestRounds:

    def test_the_spread_the_old_data_showed_needs_about_26(self):
        assert ld.rounds_for(0.89, "A1") == 26

    def test_the_floor_and_the_cap(self):
        assert ld.rounds_for(0.1, "A1") == 15
        assert ld.rounds_for(0.1, "A7") == 10
        assert ld.rounds_for(3.0, "A3") == 40


class TestDesign:

    def test_a_design_becomes_a_queue(self):
        made = ld.design("A7", AZURE, BASELINE, 12, 7)
        assert len(rq.make_rows(made)) == 24 * 12
        assert made["normalised_slice_ns"] == 700000 and made["unreachable"] == []

    def test_the_pilot_blocks_keep_their_own_rounds(self):
        assert ld.design("P0", AZURE, BASELINE, 99, 1)["rounds"] == 5
        assert ld.design("B0", AZURE, None, 0, 1)["rounds"] == 3

    @pytest.mark.parametrize("args,fragment", [
        (("Z9", AZURE, BASELINE, 5, 1), "no block 'Z9'"),
        (("A1", {"release": "x"}, BASELINE, 5, 1), "carry no tick"),
        (("A1", AZURE, None, 5, 1), "baseline trips B0 measured"),
        (("A1", AZURE, BASELINE, 0, 1), "needs --rounds")])
    def test_designs_that_cannot_be_made(self, args, fragment):
        with pytest.raises(ValueError, match=fragment):
            ld.design(*args)


class TestFromRuns:

    def test_the_baseline_is_the_median_of_the_runs_medians(self):
        rows = rq.make_rows(ld.design("B0", AZURE, None, 0, 1))
        trips = {}
        for row in rows:
            row.update(status="done", run_dir="runs/%s" % row["key"])
            base = 0.4 if "kafka" in row["setup"] else 0.3
            trips[row["run_dir"]] = {"trip_median_ms": base + (0.0, 0.02, 0.01)[int(row["round"]) - 1]}
        rows[0].update(status="failed")
        rows.append(dict(rows[1], status="running", run_dir=""))
        got = ld.baseline_from_rows(rows, 30, lambda d, w: trips[d])
        assert set(got) == {"kafka", "redis"} and set(got["redis"]) == {"50", "75", "88"}
        assert got["redis"]["88"] == pytest.approx(0.31)

    def test_a_queue_with_nothing_finished_has_no_baseline(self):
        rows = rq.make_rows(ld.design("B0", AZURE, None, 0, 1))
        with pytest.raises(ValueError, match="no finished baseline runs"):
            ld.baseline_from_rows(rows, 30, lambda d, w: {})

    def test_the_spread_is_the_median_sd_of_log_rates(self):
        rows = ([{"status": "done", "run_dir": "a%d" % i, "setup": "S1"} for i in range(2)]
                + [{"status": "done", "run_dir": "b%d" % i, "setup": "S2"} for i in range(2)]
                + [{"status": "done", "run_dir": "c0", "setup": "S3"},
                   {"status": "failed", "run_dir": "", "setup": "S1"},
                   {"status": "done", "run_dir": "z0", "setup": "S4"}])
        table = {"a0": (9, 1000), "a1": (99, 1000), "b0": (9, 1000), "b1": (9, 1000),
                 "c0": (5, 1000), "z0": (0, 0)}
        sigma, sds = ld.spread_from_rows(rows, 30, lambda d, w: {
            "measured_negative": table[d][0], "measured_spans": table[d][1]})
        expected = statistics.stdev([math.log(9.5 / 1001), math.log(99.5 / 1001)])
        assert sds == {"S1": pytest.approx(expected), "S2": 0.0}
        assert sigma == pytest.approx(expected / 2)

    def test_no_setup_with_two_runs_has_no_spread(self):
        with pytest.raises(ValueError, match="cannot be estimated"):
            ld.spread_from_rows([{"status": "done", "run_dir": "c0", "setup": "S"}], 30,
                                lambda d, w: {"measured_negative": 1, "measured_spans": 10})


class TestMain:

    @staticmethod
    def run(argv, **kw):
        out = io.StringIO()
        return ld.main(argv, out=out, **kw), out.getvalue()

    def test_design_writes_its_file_and_names_what_it_left_out(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"ok": True, "settings": AZURE}), encoding="utf-8")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
        dest = tmp_path / "a1.json"
        code, text = self.run(["design", "--block", "A1", "--settings", str(settings),
                               "--baseline", str(baseline), "--rounds", "26", "--seed", "5",
                               "--out", str(dest)])
        assert code == 0 and text.startswith("A1: 95 setups x 26 rounds = 2470 runs")
        assert "1 unreachable point(s): A1-kafka-l75-s750-p05s" in text
        assert json.loads(dest.read_text(encoding="utf-8"))["rounds"] == 26

    def test_the_baseline_block_needs_no_baseline(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(AZURE), encoding="utf-8")
        code, text = self.run(["design", "--block", "B0", "--settings", str(settings),
                               "--seed", "1", "--out", str(tmp_path / "b0.json")])
        assert code == 0 and text.endswith("0 unreachable point(s)\n")

    def test_baseline_and_rounds_come_from_finished_queues(self, tmp_path):
        rows = rq.make_rows(ld.design("B0", AZURE, None, 0, 1))
        for row in rows:
            row.update(status="done", run_dir=row["key"])
        queue = tmp_path / "b0.csv"
        rq.write_queue(str(queue), rows)
        summary = {"trip_median_ms": 0.4, "measured_negative": 3, "measured_spans": 100}
        code, _ = self.run(["baseline", "--queue", str(queue), "--out", str(tmp_path / "b.json")],
                           summarise=lambda d, w: summary)
        assert code == 0
        assert json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))["kafka"]["75"] == 0.4
        code, text = self.run(["rounds", "--queue", str(queue), "--block", "A1"],
                              summarise=lambda d, w: summary)
        assert code == 0 and json.loads(text)["rounds"] == 15

    def test_errors_are_lines(self, tmp_path):
        code, text = self.run(["design", "--block", "A1", "--settings",
                               str(tmp_path / "none.json"), "--seed", "1",
                               "--out", str(tmp_path / "x.json")])
        assert code == 2 and text.startswith("ERROR:")
