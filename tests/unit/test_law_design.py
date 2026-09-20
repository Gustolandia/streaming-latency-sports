"""Tests for scripts/law_design.py.

A run list decides at which trips the law is tested, so these tests pin the arithmetic that
places them: the points against the slice and the tick, the delays against the session's
calibration or the measured baseline, the unreachable points kept visible, the core-count
block's prediction from the machine's own constant, and the repeats against the measured spread.
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

#: What delay_calibration.py fit gives on a machine like the pilot's, trimmed to what placing
#: reads.
CALIBRATION = {
    "kafka": {"75": {"model": "line", "intercept_ms": 3.5, "slope": 0.89, "gate": {"ok": True},
                     "steps": [[0.0, 3.5], [1.0, 4.39], [2.0, 5.28], [4.0, 7.06], [8.0, 10.62]]}},
    "redis": {"75": {"model": "line", "intercept_ms": 2.2, "slope": 1.25, "gate": {"ok": True},
                     "steps": [[0.0, 2.2], [1.0, 3.45], [2.0, 4.7], [4.0, 7.2], [8.0, 12.2]]}},
}


#: What a session that calibrated twice gives: one fit per client, because the delay's effect on
#: the trip belongs to the client (D4-9). The Java figures are the Python ones shifted, which is
#: the point -- if they were identical the block would not need two.
BY_CLIENT = {
    "python": {"kafka": {"75": {"model": "line", "intercept_ms": 2.2, "slope": 0.89,
                                "gate": {"ok": True},
                                "steps": [[0.0, 2.2], [1.0, 3.09], [2.0, 3.98], [4.0, 5.76],
                                          [8.0, 9.32]]}}},
    "java": {"kafka": {"75": {"model": "line", "intercept_ms": 2.35, "slope": 0.94,
                              "gate": {"ok": True},
                              "steps": [[0.0, 2.35], [1.0, 3.29], [2.0, 4.23], [4.0, 6.11],
                                        [8.0, 9.87]]}}},
}


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

    @pytest.mark.parametrize("block,size", [("B0", 6), ("C0", 12), ("P0", 16), ("A1", 96),
                                            ("A2", 32), ("A3", 36), ("A4", 48), ("A5", 48),
                                            ("A7", 12), ("A8", 24)])
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
        assert setup["placed_by"] == "baseline"

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
        assert setups["A7-kafka-l75-s3000-c05h-rt"]["priority"] is True
        assert setups["A7-kafka-l75-s3000-c05h"]["priority"] is False

    def test_a_campaign_can_take_one_of_the_blocks_core_counts(self):
        """A5 runs a session per core count (D4-6), so a campaign is one core count's share of
        the block, the way an A1 campaign is a share of its slices. Sixteen setups, eight trips
        on each backend: three sessions of a calibration and those setups is the plan's 264."""
        setups, unreachable = ld.make_setups("A5", 1.0, None, AZURE, CALIBRATION, cores=[2])
        assert len(setups) + len(unreachable) == 16
        assert set(setup["cpus"] for setup in setups) == {2}
        assert 3 * (24 + 16 * 4) == 264, "the plan's own count for A5"

    def test_a_block_of_slices_has_no_core_counts_to_share(self):
        with pytest.raises(ValueError, match="runs slices, not core counts"):
            ld.make_setups("A1", 1.0, BASELINE, AZURE, cores=[2])

    def test_a_core_count_the_block_does_not_have_is_refused(self):
        """Asking for 3 CPUs would be a new condition, and the plan fixes the conditions."""
        with pytest.raises(ValueError, match="has no core count 3"):
            ld.make_setups("A5", 1.0, None, AZURE, CALIBRATION, cores=[3])

    def test_a_session_can_calibrate_at_the_core_count_it_will_run_at(self):
        """A5 gives each core count its own session with its own C0: the delay's effect on the
        trip is measured on the machine as the campaign will run it, and a machine with six of
        its CPUs switched off is not the one the 8-CPU calibration was taken on."""
        setups, _ = ld.make_setups("C0", 1.0, cpus=2)
        assert all(setup["cpus"] == 2 for setup in setups)
        assert setups[0]["id"] == "C0-kafka-l75-c2-d0a", "and the id says so"

    def test_a_calibration_with_no_core_count_asked_for_is_as_it_was(self):
        setups, _ = ld.make_setups("C0", 1.0)
        assert all(setup["cpus"] is None for setup in setups)
        assert setups[0]["id"] == "C0-kafka-l75-d0a"

    def test_the_baseline_can_be_measured_at_a_core_count_too(self):
        setups, _ = ld.make_setups("B0", 1.0, cpus=4)
        assert all(setup["cpus"] == 4 for setup in setups)

    @pytest.mark.parametrize("block", ["A1", "A3", "A5", "P0"])
    def test_a_block_that_places_its_trips_refuses_a_core_count(self, block):
        """A5's core counts belong to its own design, one slice each; a core count handed to it
        from outside would mean two answers to the same question."""
        with pytest.raises(ValueError, match="only B0 and C0"):
            ld.make_setups(block, 1.0, BASELINE, AZURE, cpus=2)

    def test_load_is_tested_at_one_slice(self):
        """D4-4: A3 runs at three loads, at the 3 ms slice and 6 trips, in two campaigns, one per
        backend. That is 18 setups a campaign, and the plan's 216 runs over six rounds."""
        assert ld.BLOCKS["A3"]["slices"] == (3.0,)
        setups, unreachable = ld.make_setups("A3", 1.0, BASELINE, AZURE)
        assert (len(setups) + len(unreachable)) // 2 * 6 * 2 == 216

    def test_the_client_block_is_kafka_only_and_comes_to_the_plans_count(self):
        """D4-9: Kafka only, because the official client A8 compares ours with is Kafka's. One
        slice, three trips, ordinary and go-first, two clients, and the got-it note taken both
        where it can be taken: 24 setups, which over two campaigns at five rounds is the plan's
        240 runs."""
        setups, unreachable = ld.make_setups("A8", 1.0, BASELINE, AZURE)
        assert len(setups) + len(unreachable) == 24
        assert set(s["backend"] for s in setups) == {"kafka"}
        assert set(s["language"] for s in setups) == {"python", "java"}
        assert set(s["ack_stamp"] for s in setups) == {"callback", "inline"}
        assert 24 * 5 * 2 == 240, "the plan's own count for A8"

    def test_each_client_places_its_trips_from_its_own_calibration(self):
        """D4-9: the delay's effect on the trip belongs to the client. Two clients aiming at one
        target trip therefore need two different delays to get there."""
        setups, unreachable = ld.make_setups("A8", 1.0, None, AZURE, BY_CLIENT)
        assert len(setups) == 24 and not unreachable
        found = by_id(setups)
        python = found["A8-kafka-l75-s3000-c05h-python-callback"]
        java = found["A8-kafka-l75-s3000-c05h-java-callback"]
        assert python["target_trip_ms"] == java["target_trip_ms"], "the same trip is aimed at"
        assert python["delay_ms"] != java["delay_ms"], "and a different delay gets there"
        assert python["baseline_trip_ms"] != java["baseline_trip_ms"]
        assert python["placed_by"] == "calibration"

    def test_one_calibration_for_both_clients_is_refused(self):
        """Placing one client's trips from the other's would put every one of them in the wrong
        place, and the difference would look like the comparison A8 exists to make."""
        one = BY_CLIENT["python"]
        with pytest.raises(ValueError, match="each client's trips from that client's own"):
            ld.make_setups("A8", 1.0, None, AZURE, one)

    def test_a_trip_can_be_out_of_reach_for_one_client_and_not_the_other(self):
        """Reachability is a property of the client's own floor, so it is decided per client."""
        higher = {"python": BY_CLIENT["python"],
                  "java": {"kafka": {"75": dict(BY_CLIENT["java"]["kafka"]["75"],
                                                intercept_ms=4.2,
                                                steps=[[0.0, 4.2], [1.0, 5.15], [2.0, 6.10],
                                                       [4.0, 8.0], [8.0, 11.8]])}}}
        setups, unreachable = ld.make_setups("A8", 1.0, None, AZURE, higher)
        out = [u["id"] for u in unreachable]
        assert out and all("-java-" in i for i in out), out
        assert all("-python-" in s["id"] or "-java-" in s["id"] for s in setups)

    def test_a_session_can_calibrate_once_per_client(self):
        """A8 gives each client its own calibration, so the session runs C0 twice and each run
        says which client took it."""
        for client in ("python", "java"):
            setups, _ = ld.make_setups("C0", 1.0, language=client, backends=["kafka"])
            assert all(s["language"] == client for s in setups)
            assert setups[0]["id"] == "C0-kafka-l75-%s-d0a" % client

    def test_a_calibration_with_no_client_named_is_as_it_was(self):
        setups, _ = ld.make_setups("C0", 1.0, backends=["kafka"])
        assert all(s["language"] is None for s in setups)
        assert setups[0]["id"] == "C0-kafka-l75-d0a"

    @pytest.mark.parametrize("block", ["A1", "A7", "A8"])
    def test_a_block_that_places_its_trips_refuses_a_client_from_outside(self, block):
        """A8 names its own clients; one handed in from outside would mean two answers to the
        same question, as a core count handed to A5 would."""
        with pytest.raises(ValueError, match="only B0 and C0 are run as one client"):
            ld.make_setups(block, 1.0, BASELINE, AZURE, language="java")

    def test_a_block_with_no_clients_takes_the_calibration_as_it_always_did(self):
        setups, _ = ld.make_setups("A7", 1.0, None, AZURE, CALIBRATION)
        assert setups and all(s["placed_by"] == "calibration" for s in setups)

    def test_the_client_block_refuses_the_backend_it_does_not_run(self):
        with pytest.raises(ValueError, match="A8 does not run redis"):
            ld.make_setups("A8", 1.0, BASELINE, AZURE, CALIBRATION, backends=["redis"])

    def test_a_setup_says_which_client_and_where_the_note_was_taken(self):
        setups, _ = ld.make_setups("A8", 1.0, BASELINE, AZURE)
        found = by_id(setups)
        assert "A8-kafka-l75-s3000-p09s-python-callback" in found
        assert "A8-kafka-l75-s3000-p09s-rt-java-inline" in found
        one = found["A8-kafka-l75-s3000-p09s-rt-java-inline"]
        assert one["priority"] is True and one["language"] == "java"
        assert one["ack_stamp"] == "inline"

    @pytest.mark.parametrize("block", ["A1", "A3", "A4", "A7"])
    def test_a_block_that_names_no_client_carries_none(self, block):
        """Every other block leaves both unset, and its ids are the ones they always were."""
        setups, _ = ld.make_setups(block, 1.0, BASELINE, AZURE)
        assert all(s["language"] is None and s["ack_stamp"] is None for s in setups)
        assert all("-python" not in s["id"] and "-callback" not in s["id"] for s in setups)

    def test_go_first_is_tested_at_one_slice(self):
        """D4-5: A7 tests one slice, 3 ms, both backends, in one campaign, and P4 is judged at
        that slice. The plan's own count, 72 runs, is twelve setups over six rounds; two slices
        would make it 120."""
        assert ld.BLOCKS["A7"]["slices"] == (3.0,)
        setups, unreachable = ld.make_setups("A7", 1.0, BASELINE, AZURE)
        assert len(setups) + len(unreachable) == 12

    def test_the_baseline_block_adds_no_delay_and_keeps_the_kernels_slice(self):
        setups = ld.make_setups("B0", 1.0)[0]
        assert {(s["delay_ms"], s["slice_ns"], s["point"]) for s in setups} == {
            (0.0, None, "base")}

    def test_a_baseline_missing_a_load_is_named(self):
        partial = {"kafka": BASELINE["kafka"], "redis": {"50": 0.2, "75": 0.3}}
        with pytest.raises(ValueError, match="no redis trip at 88% load"):
            ld.make_setups("A3", 1.0, partial, AZURE)


class TestCalibrationBlock:

    def test_the_staircase_doubles_from_one_millisecond(self):
        assert ld.c0_steps(8.0) == [1.0, 2.0, 4.0, 8.0]
        assert ld.c0_steps(20.0) == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        assert ld.c0_steps(0.5) == [1.0]

    def test_zero_delay_runs_twice_per_round_at_the_kernels_slice(self):
        setups = by_id(ld.make_setups("C0", 1.0, settings=AZURE)[0])
        kafka = sorted(s["delay_ms"] for s in setups.values() if s["backend"] == "kafka")
        assert kafka == [0.0, 0.0, 1.0, 2.0, 4.0, 8.0]
        assert setups["C0-redis-l75-d0b"]["slice_ns"] is None
        assert setups["C0-kafka-l75-d8000"]["delay_ms"] == 8.0

    def test_a_longer_staircase_at_the_sessions_own_loads(self):
        setups = ld.make_setups("C0", 4.0, loads=(50, 88), up_to_ms=16.0)[0]
        assert len(setups) == 2 * 2 * 7
        assert {s["load_pct"] for s in setups} == {50, 88}

    def test_a_block_that_plans_trips_keeps_its_own_loads(self):
        with pytest.raises(ValueError, match="fixes its own loads"):
            ld.make_setups("A1", 1.0, BASELINE, AZURE, loads=(50,))


class TestPlacingFromTheCalibration:

    def test_a_delay_is_read_off_the_calibration(self):
        setups = by_id(ld.make_setups("A1", 1.0, settings=AZURE, calibration=CALIBRATION)[0])
        setup = setups["A1-redis-l75-s3000-f15h"]
        assert setup["target_trip_ms"] == pytest.approx(4.5)
        assert setup["delay_ms"] == pytest.approx((4.5 - 2.2) / 1.25, abs=1e-3)
        assert setup["placed_by"] == "calibration"
        assert setup["baseline_trip_ms"] == pytest.approx(2.2)

    def test_points_the_calibration_did_not_measure_are_kept_visible(self):
        _, unreachable = ld.make_setups("A1", 1.0, settings=AZURE, calibration=CALIBRATION)
        ids = {u["id"] for u in unreachable}
        assert "A1-kafka-l75-s750-p05s" in ids, "below the zero-delay trip"
        assert "A1-kafka-l75-s6000-f2sh" in ids, "beyond the longest step"
        assert all(u["delay_ms"] is None for u in unreachable)

    def test_a_calibration_missing_a_load_or_failing_its_gate_places_nothing(self):
        with pytest.raises(ValueError, match="no kafka entry at 50% load"):
            ld.make_setups("A3", 1.0, settings=AZURE, calibration=CALIBRATION)
        failed = {"kafka": {"75": dict(CALIBRATION["kafka"]["75"], gate={"ok": False})},
                  "redis": CALIBRATION["redis"]}
        with pytest.raises(ValueError, match="failed its gate"):
            ld.make_setups("A1", 1.0, settings=AZURE, calibration=failed)

    def test_a_design_from_the_calibration_alone(self):
        made = ld.design("A7", AZURE, None, 10, 3, calibration=CALIBRATION)
        assert made["calibration"] is CALIBRATION and made["setups"]


class TestRounds:
    """The number of rounds is not this script's to give: the plan sets it by simulating the
    campaign's own prediction at the spread measured here (D4-2, rounds_rule.py)."""

    def test_it_reports_the_spread_and_who_turns_it_into_rounds(self):
        assert not hasattr(ld, "rounds_for"), "version 3's closed-form rule is gone"


class TestWhichSlicesAPairCanTest:
    """A message cannot arrive sooner than the client's own zero-delay trip, and the plateau lives
    at trips below the slice, so a pair with a high floor cannot test its smallest slices."""

    def calibration(self, zero_ms, up_to_ms=16.0):
        """A calibration that adds the delay one for one, from each client's own floor."""
        return dict((backend, {"75": {
            "slope": 1.0, "intercept_ms": zero, "model": "line", "gate": {"ok": True},
            "steps": [[x, zero + x] for x in (0.0, 1.0, 2.0, 4.0, 8.0, up_to_ms)]}})
            for backend, zero in zero_ms.items())

    def test_a_low_floor_reaches_every_slice(self):
        found = ld.testable("A1", AZURE, calibration=self.calibration({"kafka": 0.4, "redis": 0.4}),
                            up_to_ms=16.0)
        assert all(found["kafka"][s] for s in (1.5, 2.25, 3.0, 4.5, 6.0))

    def test_a_floor_above_a_slices_plateau_puts_it_out_of_reach(self):
        found = ld.testable("A1", AZURE, calibration=self.calibration({"kafka": 2.1, "redis": 0.9}),
                            up_to_ms=16.0)
        assert found["kafka"][0.75] is False and found["kafka"][1.5] is False
        assert found["kafka"][2.25] is False, "its plateau point sits at 2.025 ms"
        assert found["kafka"][3.0] is True and found["kafka"][6.0] is True
        assert found["redis"][1.5] is True

    def test_a_calibration_that_stops_short_puts_the_far_slices_out_of_reach(self):
        near = ld.testable("A1", AZURE,
                           calibration=self.calibration({"kafka": 0.4, "redis": 0.4}, 8.0),
                           up_to_ms=8.0)
        assert near["redis"][6.0] is False, "twice six plus a tick is beyond an 8 ms calibration"
        assert near["redis"][3.0] is True

    def test_a_block_of_core_counts_is_read_by_its_own_slices(self):
        """A5 names its conditions by the cores switched on, not by a slice set by hand."""
        found = ld.testable("A5", AZURE, calibration=self.calibration({"kafka": 2.1,
                                                                       "redis": 0.4}))
        assert found["redis"] and all(isinstance(s, float) for s in found["redis"])
        assert any(ok for ok in found["redis"].values())

    def test_a_block_that_sets_no_slice_has_no_slice_to_judge(self):
        """C0 and B0 run at whatever slice the kernel has; they test no cliff and no prediction."""
        assert ld.testable("C0", AZURE, calibration=self.calibration({"kafka": 2.1,
                                                                      "redis": 0.4})) == {
            "kafka": {}, "redis": {}}

    def test_it_can_be_placed_from_the_baseline_trips_instead(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(AZURE), encoding="utf-8")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
        code, text = self.run(["testable", "--block", "A1", "--settings", str(settings),
                               "--baseline", str(baseline)])
        assert code == 0 and "kafka" in text and "redis" in text

    def test_the_command_says_what_a_pair_can_test(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(AZURE), encoding="utf-8")
        cal = tmp_path / "calibration.json"
        cal.write_text(json.dumps({"calibration": self.calibration({"kafka": 2.1,
                                                                     "redis": 0.9})}),
                       encoding="utf-8")
        code, text = self.run(["testable", "--block", "A1", "--settings", str(settings),
                               "--calibration", str(cal), "--up-to-ms", "16"])
        assert code == 0
        assert "kafka 3,4.5,6" in text and "out of reach: 0.75, 1.5, 2.25" in text
        assert "redis 1.5,2.25,3,4.5,6" in text

    @staticmethod
    def run(argv):
        import io
        out = io.StringIO()
        return ld.main(argv, out=out), out.getvalue()


class TestOneCampaignOfABlock:
    """A block is not a sitting: the plan runs A1 as six campaigns, three per backend, each
    sharing the 3 ms anchor, and each campaign carries which slice that is."""

    def test_a_campaign_takes_its_share_of_the_slices_and_one_backend(self):
        made = ld.design("A1", AZURE, BASELINE, 4, 5, slices=[3.0, 0.75, 1.5],
                         backends=["kafka"], anchor=3.0)
        assert made["slices"] == [3.0, 0.75, 1.5] and made["backends"] == ["kafka"]
        assert made["anchor_slice"] == 3.0
        assert set(s["backend"] for s in made["setups"]) == {"kafka"}
        assert len(made["setups"]) + len(made["unreachable"]) == 3 * 8, "three slices, eight trips"

    def test_the_whole_block_is_still_what_it_was(self):
        made = ld.design("A1", AZURE, BASELINE, 4, 5)
        assert made["slices"] is None and made["backends"] == ["kafka", "redis"]
        assert len(made["setups"]) + len(made["unreachable"]) == 6 * 8 * 2

    def test_a_slice_the_block_does_not_have_is_refused(self):
        with pytest.raises(ValueError, match="no slice 2.5"):
            ld.design("A1", AZURE, BASELINE, 4, 5, slices=[3.0, 2.5])

    def test_a_backend_that_does_not_exist_is_refused(self):
        with pytest.raises(ValueError, match="A1 does not run pulsar"):
            ld.design("A1", AZURE, BASELINE, 4, 5, backends=["pulsar"])

    def test_a_block_of_core_counts_has_no_slices_to_share(self):
        with pytest.raises(ValueError, match="runs core counts"):
            ld.design("A5", AZURE, BASELINE, 4, 5, slices=[3.0])

    def test_a_campaign_without_the_anchor_is_refused(self):
        with pytest.raises(ValueError, match="anchor slice 3 is not among"):
            ld.design("A1", AZURE, BASELINE, 4, 5, slices=[0.75, 1.5], anchor=3.0)


class TestDesign:

    def test_a_design_becomes_a_queue(self):
        made = ld.design("A7", AZURE, BASELINE, 12, 7)
        assert len(rq.make_rows(made)) == 12 * 12, "A7's twelve setups, each round"
        assert made["normalised_slice_ns"] == 700000 and made["unreachable"] == []

    def test_the_pilot_blocks_keep_their_own_rounds(self):
        assert ld.design("P0", AZURE, BASELINE, 99, 1)["rounds"] == 5
        assert ld.design("B0", AZURE, None, 0, 1)["rounds"] == 3
        assert ld.design("C0", AZURE, None, 0, 1)["rounds"] == 2

    def test_the_first_sessions_staircase_runs_more_rounds(self):
        """S0-1 is C0 up to 16 ms over 4 rounds; asking B0 or P0 for more changes nothing."""
        made = ld.design("C0", AZURE, None, 4, 1, up_to_ms=16.0)
        assert made["rounds"] == 4 and len(made["setups"]) == 14
        assert ld.design("B0", AZURE, None, 4, 1)["rounds"] == 3

    def test_a_second_stage_of_the_calibration_carries_on_its_rounds(self):
        made = ld.design("C0", AZURE, None, 2, 1, first_round=3)
        assert made["first_round"] == 3
        assert sorted({r["round"] for r in rq.make_rows(made)}) == ["3", "4"]
        assert ld.design("B0", AZURE, None, 0, 1)["first_round"] == 1
        with pytest.raises(ValueError, match="only C0 runs in two stages"):
            ld.design("B0", AZURE, None, 0, 1, first_round=3)

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

    def backends(self, table, rows):
        return ld.spread_by_backend(rows, 30, lambda d, w: {
            "measured_negative": table[d][0], "measured_spans": table[d][1]})

    def test_each_backend_has_its_own_spread(self):
        """D10-1: a campaign runs one backend, so the spread it is simulated at is that
        backend's. Pooling a quiet backend with a noisy one describes neither."""
        rows = [{"status": "done", "run_dir": "k0", "setup": "P0-kafka-l75-s3000-p09s"},
                {"status": "done", "run_dir": "k1", "setup": "P0-kafka-l75-s3000-p09s"},
                {"status": "done", "run_dir": "r0", "setup": "P0-redis-l75-s3000-p09s"},
                {"status": "done", "run_dir": "r1", "setup": "P0-redis-l75-s3000-p09s"}]
        table = {"k0": (9, 1000), "k1": (10, 1000), "r0": (9, 1000), "r1": (99, 1000)}
        found = self.backends(table, rows)
        assert sorted(found) == ["kafka", "redis"]
        assert found["redis"] > found["kafka"], "the noisy backend must not be averaged away"
        assert found["kafka"] == pytest.approx(
            statistics.stdev([math.log(9.5 / 1001), math.log(10.5 / 1001)]))

    def test_a_setup_whose_name_names_no_backend_is_left_out(self):
        rows = [{"status": "done", "run_dir": "a", "setup": "oddly-named"},
                {"status": "done", "run_dir": "b", "setup": "oddly-named"},
                {"status": "done", "run_dir": "k0", "setup": "P0-kafka-l75-s3000-p09s"},
                {"status": "done", "run_dir": "k1", "setup": "P0-kafka-l75-s3000-p09s"}]
        table = dict((d, (9, 1000)) for d in ("a", "b", "k0"))
        table["k1"] = (10, 1000)
        assert sorted(self.backends(table, rows)) == ["kafka"]

    def test_a_setup_with_one_run_gives_that_backend_nothing(self):
        rows = [{"status": "done", "run_dir": "k0", "setup": "P0-kafka-l75-s3000-p09s"},
                {"status": "done", "run_dir": "r0", "setup": "P0-redis-l75-s3000-p09s"},
                {"status": "done", "run_dir": "r1", "setup": "P0-redis-l75-s3000-p09s"}]
        table = {"k0": (9, 1000), "r0": (9, 1000), "r1": (99, 1000)}
        assert sorted(self.backends(table, rows)) == ["redis"]

    def test_no_backend_at_all_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="no backend has a setup"):
            ld.spread_by_backend([{"status": "done", "run_dir": "c0", "setup": "P0-kafka-x"}], 30,
                                 lambda d, w: {"measured_negative": 1, "measured_spans": 10})



class TestTheLevelsTheRoundsRuleIsSimulatedAt:
    """The pilot measures the plateau and the floor, instead of the rule assuming 0.30 and 0.01.

    Those two were figures from the machines this work began on. On the first x86 pair the pilot
    measures 0.0345 and 0.0092 for Kafka: a fall of under four times where the simulation assumed
    thirty. A shallower cliff is harder to find, so the rounds the simulation asked for were too
    few -- A3 was given 16 and needs 24 at the levels its own runs measured.
    """

    def levels(self, table, rows, anchor_ms=3.0):
        return ld.levels_by_backend(rows, 30, lambda d, w: {
            "measured_negative": table[d][0], "measured_spans": table[d][1]}, anchor_ms)

    def rows(self, *setups):
        return [{"status": "done", "run_dir": "d%d" % i, "setup": s}
                for i, s in enumerate(setups)]

    BOTH = ("P0-kafka-l75-s3000-p09s", "P0-kafka-l75-s3000-f15h")

    def test_each_backend_reads_its_own_plateau_and_floor(self):
        rows = self.rows(*self.BOTH, "P0-redis-l75-s3000-p09s", "P0-redis-l75-s3000-f15h")
        table = {"d0": (30, 1000), "d1": (9, 1000), "d2": (5, 1000), "d3": (1, 1000)}
        found = self.levels(table, rows)
        assert found["kafka"]["read_from"] == ["p09s", "f15h"]
        assert found["kafka"]["slice_ms"] == 3.0
        assert found["kafka"]["plateau"] == pytest.approx(30.5 / 1001)
        assert found["kafka"]["floor"] == pytest.approx(9.5 / 1001)
        assert found["redis"]["plateau"] == pytest.approx(5.5 / 1001)
        assert found["redis"]["floor"] == pytest.approx(1.5 / 1001)

    def test_the_levels_are_medians_over_the_runs_of_a_setup(self):
        rows = self.rows("P0-kafka-l75-s3000-p09s", "P0-kafka-l75-s3000-p09s",
                         "P0-kafka-l75-s3000-p09s", "P0-kafka-l75-s3000-f15h")
        table = {"d0": (10, 1000), "d1": (30, 1000), "d2": (50, 1000), "d3": (9, 1000)}
        assert self.levels(table, rows)["kafka"]["plateau"] == pytest.approx(30.5 / 1001)

    def test_a_slice_that_is_not_the_anchor_is_not_read(self):
        """Both levels are trips defined from the slice, so they are not one quantity at two
        slices: on the first x86 pair Kafka's floor is 0.0092 at 3 ms and 0.0321 at 1.5 ms, and
        their median, 0.0166, is no slice's floor."""
        rows = self.rows(*self.BOTH, "P0-kafka-l75-s1500-p09s", "P0-kafka-l75-s1500-f15h")
        table = {"d0": (30, 1000), "d1": (9, 1000), "d2": (900, 1000), "d3": (800, 1000)}
        found = self.levels(table, rows)
        assert found["kafka"]["plateau"] == pytest.approx(30.5 / 1001)
        assert found["kafka"]["floor"] == pytest.approx(9.5 / 1001)

    def test_it_reads_the_slice_it_is_asked_for(self):
        rows = self.rows("P0-kafka-l75-s1500-p09s", "P0-kafka-l75-s1500-f15h")
        table = {"d0": (60, 1000), "d1": (20, 1000)}
        found = self.levels(table, rows, anchor_ms=1.5)
        assert found["kafka"]["slice_ms"] == 1.5
        assert found["kafka"]["plateau"] == pytest.approx(60.5 / 1001)
        assert found["kafka"]["floor"] == pytest.approx(20.5 / 1001)

    def test_the_second_choice_point_is_used_where_the_first_was_not_run(self):
        """f2sh is further past the cliff and flatter, so it is preferred; P0 runs f15h."""
        rows = self.rows("P0-kafka-l75-s3000-p05s", "P0-kafka-l75-s3000-f2sh")
        table = {"d0": (40, 1000), "d1": (2, 1000)}
        found = self.levels(table, rows)
        assert found["kafka"]["read_from"] == ["p05s", "f2sh"]
        assert found["kafka"]["plateau"] == pytest.approx(40.5 / 1001)
        assert found["kafka"]["floor"] == pytest.approx(2.5 / 1001)

    def test_the_first_choice_wins_where_both_were_run(self):
        rows = self.rows("P0-kafka-l75-s3000-p09s", "P0-kafka-l75-s3000-p05s",
                         "P0-kafka-l75-s3000-f2sh", "P0-kafka-l75-s3000-f15h")
        table = {"d0": (30, 1000), "d1": (70, 1000), "d2": (2, 1000), "d3": (9, 1000)}
        found = self.levels(table, rows)
        assert found["kafka"]["read_from"] == ["p09s", "f2sh"]

    def test_a_backend_missing_one_of_the_two_levels_is_left_out(self):
        """Half a cliff is not a cliff: without a floor there is nothing to fall to."""
        rows = self.rows(*self.BOTH, "P0-redis-l75-s3000-p09s")
        table = {"d0": (30, 1000), "d1": (9, 1000), "d2": (5, 1000)}
        assert sorted(self.levels(table, rows)) == ["kafka"]

    def test_neither_level_anywhere_is_refused_rather_than_guessed(self):
        with pytest.raises(ValueError, match="no backend ran both a plateau point"):
            self.levels({"d0": (9, 1000)}, self.rows("P0-kafka-l75-s3000-c04h"))

    def test_it_names_the_anchor_it_looked_at_when_it_finds_nothing(self):
        with pytest.raises(ValueError, match="4.5 ms anchor"):
            self.levels({"d0": (9, 1000)}, self.rows("P0-kafka-l75-s3000-p09s"), anchor_ms=4.5)

    def test_a_level_no_run_could_resolve_is_marked_as_a_bound(self):
        """The Arm pair's Redis floor: no floor run saw a single negative. The shrunk figure
        stands in for a rate below what the pilot resolves, and a cliff falling to a bound is at
        least as deep as the real one, so the rounds it gives are a floor on what is needed."""
        rows = self.rows(*self.BOTH)
        found = self.levels({"d0": (30, 1000), "d1": (0, 1000)}, rows)
        assert found["kafka"]["below_resolution"] == ["floor"]
        assert found["kafka"]["floor"] == pytest.approx(0.5 / 1001)

    def test_a_level_something_was_seen_at_is_not_marked(self):
        found = self.levels({"d0": (30, 1000), "d1": (1, 1000)}, self.rows(*self.BOTH))
        assert "below_resolution" not in found["kafka"]

    def test_one_run_seeing_nothing_does_not_make_the_level_a_bound(self):
        """It is a bound only where no run saw anything; one quiet run among several is data."""
        rows = self.rows("P0-kafka-l75-s3000-p09s", "P0-kafka-l75-s3000-f15h",
                         "P0-kafka-l75-s3000-f15h")
        found = self.levels({"d0": (30, 1000), "d1": (0, 1000), "d2": (4, 1000)}, rows)
        assert "below_resolution" not in found["kafka"]

    @pytest.mark.parametrize("rows,why", [
        ([{"status": "failed", "run_dir": "d0", "setup": "P0-kafka-l75-s3000-p09s"}],
         "a run that did not finish"),
        ([{"status": "done", "run_dir": "", "setup": "P0-kafka-l75-s3000-p09s"}],
         "a run with no directory"),
        ([{"status": "done", "run_dir": "empty", "setup": "P0-kafka-l75-s3000-p09s"}],
         "a run that measured no span"),
        ([{"status": "done", "run_dir": "d0", "setup": "short-name"}],
         "a setup name with too few parts"),
        ([{"status": "done", "run_dir": "d0", "setup": "P0-mystery-l75-s3000-p09s"}],
         "a backend this plan does not run"),
        ([{"status": "done", "run_dir": "d0", "setup": "P0-kafka-l75-3000-p09s"}],
         "a slice field that is not a slice"),
        ([{"status": "done", "run_dir": "d0", "setup": "P0-kafka-l75-sxyz-p09s"}],
         "a slice field that is not a number"),
    ])
    def test_a_row_that_says_nothing_about_a_level_is_passed_over(self, rows, why):
        table = {"d0": (9, 1000), "empty": (0, 0)}
        kept = ld._level_rates(rows, 30, lambda d, w: {
            "measured_negative": table[d][0], "measured_spans": table[d][1]})
        assert kept == {}, why

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
        # The rounds are read off the spread pilot, which is the queue this is documented for:
        # B0 plans no trip, so it has neither a plateau nor a floor to read.
        code, text = self.run(["rounds", "--queue", str(queue), "--block", "A1"],
                              summarise=lambda d, w: summary)
        assert code == 2 and "no backend ran both a plateau point" in text, (
            "a queue that cannot give the levels must be refused, not simulated at 0.30 and 0.01")

    def test_the_rounds_reading_gives_each_backend_its_spread_and_its_levels(self, tmp_path):
        """What the simulation is run at is three numbers, not one. A cliff falling from 0.03 to
        0.01 is harder to find than one falling from 0.30 to 0.01, at any spread."""
        rows = rq.make_rows(ld.design("P0", AZURE, None, 5, 1, calibration=CALIBRATION))
        for row in rows:
            row.update(status="done", run_dir=row["key"])
        queue = tmp_path / "p0.csv"
        rq.write_queue(str(queue), rows)

        def summarise(run_dir, warmup_s):
            # Negatives by where the trip sits: high on the plateau, low past the cliff.
            negatives = 30 if "p09s" in run_dir else 9 if "f15h" in run_dir else 20
            return {"trip_median_ms": 0.4, "measured_negative": negatives + len(run_dir) % 3,
                    "measured_spans": 1000}

        code, text = self.run(["rounds", "--queue", str(queue), "--block", "A1"],
                              summarise=summarise)
        found = json.loads(text)
        assert code == 0 and "rounds" not in found, "the number is not this script's to give"
        assert found["sigma_median"] is not None
        for backend, one in found["by_backend"].items():
            assert one["plateau"] > one["floor"], backend
            assert one["slice_ms"] == 3.0 and one["read_from"] == ["p09s", "f15h"]
            assert "spread" in one
            assert found["rounds_from"][backend].startswith("python scripts/rounds_rule.py for")
            assert "--plateau" in found["rounds_from"][backend]
            assert "--floor" in found["rounds_from"][backend]

    def test_design_places_from_a_calibration_file_and_c0_takes_loads(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(AZURE), encoding="utf-8")
        cal = tmp_path / "cal.json"
        cal.write_text(json.dumps({"calibration": CALIBRATION}), encoding="utf-8")
        code, text = self.run(["design", "--block", "A7", "--settings", str(settings),
                               "--calibration", str(cal), "--rounds", "10", "--seed", "2",
                               "--out", str(tmp_path / "a7.json")])
        assert code == 0 and text.startswith("A7: ")
        code, text = self.run(["design", "--block", "C0", "--settings", str(settings),
                               "--loads", "50,88", "--up-to-ms", "16", "--seed", "2",
                               "--out", str(tmp_path / "c0.json")])
        assert code == 0 and text.startswith("C0: 28 setups x 2 rounds = 56 runs")

    def test_errors_are_lines(self, tmp_path):
        code, text = self.run(["design", "--block", "A1", "--settings",
                               str(tmp_path / "none.json"), "--seed", "1",
                               "--out", str(tmp_path / "x.json")])
        assert code == 2 and text.startswith("ERROR:")
