"""Tests for scripts/helper_waits.py: P6 on A6's histograms and on A9's event recordings, and A9's
three questions, on runs made up in the shape real runs have on disk.

The made-up A9 runs are built the way the law says negative readings happen: each
acknowledgement's reply wakes the thread that stamps it, which waits for a CPU, runs, stamps and
sleeps again; one message in ten waits long enough that its stamp lands after its arrival. The
files carry what the real ones carry -- the clients' CSV columns, the integrity record, the queue
row, the thread records with both clocks, bpftrace's own lines -- because a reader tested on a
shape the instrument never writes has been caught out here before.
"""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import helper_waits as hw  # noqa: E402

MS = 1000000
#: The tracer's clock at a made-up run's start, and CLOCK_REALTIME's lead over it.
MONO0 = 5000 * 1000 * MS
LEAD = 1789762670 * 1000 * MS
PRODUCER_COLUMNS = ("run_id,backend,stream,event_id,match_id,t_sim_seconds,t_emit_offset_s,"
                    "t_prod_sched_ns,t_prod_send_ns,t_broker_ack_ns,redis_id")
CONSUMER_COLUMNS = ("run_id,backend,stream,redis_id,t_consume_ns,event_id,match_id,t_sim_seconds,"
                    "t_emit_offset_s,t_emit_planned_ns,s3_uid,s3_rev,s3_is_correction")


def campaign(root, name="stage1_a9", pair="matched"):
    """A campaign folder as collect_runs.py leaves one: its runs, and the note naming the pair."""
    folder = root / name
    (folder / "runs").mkdir(parents=True)
    (folder / "COLLECTED.json").write_text(json.dumps({"profile": pair}), encoding="utf-8")
    return folder / "runs"


def run_folder(runs, key, setup, backend="kafka", load=75, point="p09s", trip=2.0, gotit=0.86,
               rate=0.1, verdict="count", slice_ns=3000000):
    where = runs / ("law_%s_%s" % (setup.split("-")[0].lower(), key))
    where.mkdir()
    (where / "queue_row.json").write_text(json.dumps(
        {"attempt": "1", "key": key, "round": key[1:4].lstrip("0") or "1", "setup": setup,
         "params": {"backend": backend, "block": setup.split("-")[0], "load_pct": load,
                    "point": point, "slice_ns": slice_ns, "tick_ms": 1.0, "priority": False,
                    "cpus": None, "trace_half": True, "trace_events": True}}), encoding="utf-8")
    (where / "integrity.json").write_text(json.dumps(
        {"verdict": verdict, "checks": {}, "reasons": [], "run_dir": str(where),
         "recorded": {"trip_median_ms": trip, "gotit_median_ms": gotit,
                      "measured_negative_rate": rate}}), encoding="utf-8")
    return where


def lhist(bins, overflow=0):
    """bpftrace's output for `@usecs = lhist($d, 0, 20000, 100)`, as runqlat.txt holds it."""
    out = ["Attaching 3 probes...", "", "", "@count: %d" % (sum(bins.values()) + overflow), "",
           "@usecs: "]
    for low in sorted(bins):
        out.append("[%d, %d)%s%d |%s|" % (low, low + 100, " " * 10, bins[low], "@" * 10))
    if overflow:
        out.append("[20000, ...)%s%d |@|" % (" " * 7, overflow))
    return "\n".join(out) + "\n"


def a9_world(where, stampers=(101,), period_ms=20.0, messages=2000, gotit_ms=0.8, trip_ms=2.0,
             slow_every=10, slow_ms=1.5, quick_ms=0.05, drift_ns=0, lost=False, crowd_every=0):
    """The files of one recorded A9 run, and how many of its measured messages read negative.

    Message i is sent every `period_ms`; its reply wakes stamper i % len(stampers) at send + g,
    which waits `slow_ms` for every `slow_every`-th message and `quick_ms` otherwise, runs, stamps
    10 us later and sleeps 20 us after that. It arrives at send + trip. `drift_ns` slews
    CLOCK_REALTIME against the tracer's clock over the run, `lost` has bpftrace report dropped
    events, and `crowd_every` puts a second stamper on a CPU at every so many stamps.
    """
    span = messages * period_ms * MS

    def real(mono):
        return mono + LEAD + int(drift_ns * (mono - MONO0) / span)

    sent_rows, got_rows, lines = [], [], ["Attaching 2 probes..."]
    events = [(MONO0 - MS, "S", tid) for tid in stampers]
    for i in range(messages):
        send = MONO0 + int(i * period_ms * MS)
        tid = stampers[i % len(stampers)]
        wait = slow_ms if slow_every and i % slow_every == 0 else quick_ms
        woken = send + int(gotit_ms * MS)
        on = woken + int(wait * MS)
        stamp = on + 10000
        events += [(woken, "W", tid), (on, "R", tid), (on + 30000, "S", tid)]
        if crowd_every and i % crowd_every == 0:
            other = [t for t in stampers if t != tid][0]
            events += [(on - 5000, "W", other), (on - 1000, "R", other),
                       (on + 40000, "S", other)]
        eid = "constant-%06d" % i
        sent_rows.append("r,kafka,t,%s,900000,0,%.2f,%d,%d,%d," % (
            eid, i * period_ms / 1000.0, real(send) - 1000, real(send), real(stamp)))
        got_rows.append("r,kafka,t,,%d,%s,900000,0,0.0,0,900000:%s,1,False" % (
            real(send + int(trip_ms * MS)), eid, eid))
    events.sort()
    lines += ["%s %d %d" % (kind, tid, ns) for ns, kind, tid in events]
    if lost:
        lines.append("Lost 12 events")
    (where / "waits.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (where / "producer.csv").write_text(PRODUCER_COLUMNS + "\n" + "\n".join(sent_rows) + "\n",
                                        encoding="utf-8")
    (where / "consumer_events.csv").write_text(CONSUMER_COLUMNS + "\n" + "\n".join(got_rows)
                                               + "\n", encoding="utf-8")
    ends = [{"realtime_ns": real(MONO0 - 2000 * MS), "monotonic_ns": MONO0 - 2000 * MS},
            {"realtime_ns": real(MONO0 + span + 2000 * MS), "monotonic_ns": MONO0 + span
             + 2000 * MS}]
    (where / "producer_threads.json").write_text(json.dumps(
        {"pid": 900, "roles": {"stamps_ack": list(stampers), "stamps_send": [900]},
         "clocks": ends}), encoding="utf-8")
    (where / "consumer_threads.json").write_text(json.dumps(
        {"pid": 950, "roles": {"stamps_receive": [951]}, "clocks": ends}), encoding="utf-8")
    measured = [i for i in range(messages) if i * period_ms >= 30000.0]
    return sum(1 for i in measured if slow_every and i % slow_every == 0)


class TestTheHistogram:

    def test_it_reads_bpftraces_bins_and_the_open_last_one(self, tmp_path):
        path = tmp_path / "runqlat.txt"
        path.write_text(lhist({0: 900, 100: 50, 1200: 40}, overflow=10), encoding="utf-8")
        assert hw.histogram(str(path)) == [(0, 100, 900), (100, 200, 50), (1200, 1300, 40),
                                           (20000, None, 10)]

    def test_a_bin_across_the_threshold_counts_in_proportion(self):
        bins = [(0, 100, 50), (100, 200, 40), (200, 300, 10)]
        assert hw.share_longer(bins, 150) == pytest.approx((20 + 10) / 100.0)
        assert hw.share_longer(bins, 300) == 0.0

    def test_a_threshold_at_or_under_zero_takes_every_wait(self):
        """T - g at or under nothing: every reading is negative, whatever the thread did."""
        assert hw.share_longer([(0, 100, 5), (100, 200, 5)], -40) == 1.0

    def test_the_open_bin_counts_whole_above_the_threshold_and_refuses_inside_it(self):
        bins = [(0, 100, 90), (20000, None, 10)]
        assert hw.share_longer(bins, 1500) == pytest.approx(0.1)
        assert hw.share_longer(bins, 25000) is None
        assert hw.share_longer([(0, 100, 90), (20000, None, 0)], 25000) == 0.0

    def test_an_empty_histogram_predicts_nothing(self):
        assert hw.share_longer([], 100) is None
        assert hw.share_longer([(0, 100, 0)], 100) is None


class TestA6:

    def test_a_run_is_predicted_from_the_waits_longer_than_t_less_g(self, tmp_path):
        runs = campaign(tmp_path, "stage1_a1")
        where = run_folder(runs, "r001-x", "A1-kafka-l75-s3000-p09s", trip=2.0, gotit=0.86)
        (where / "runqlat.txt").write_text(lhist({0: 800, 1100: 100, 1500: 100}),
                                           encoding="utf-8")
        run = {"run_dir": str(where), "trip_ms": 2.0, "gotit_ms": 0.86}
        share, why = hw.a6_prediction(run)
        # T - g = 1.14 ms: the whole 1.5 ms bin and 60 of the 1.1 ms bin's 100 us lie above it.
        assert why is None and share == pytest.approx((100 * 0.6 + 100) / 1000.0)

    def test_a_run_without_a_recording_or_a_got_it_median_is_said_so(self, tmp_path):
        where = run_folder(campaign(tmp_path), "r001-x", "A1-kafka-l75-s3000-p09s")
        assert hw.a6_prediction({"run_dir": str(where), "trip_ms": 2.0, "gotit_ms": 0.8}) == \
            (None, hw.NOT_RECORDED)
        (where / "runqlat.txt").write_text(lhist({0: 10}), encoding="utf-8")
        assert hw.a6_prediction({"run_dir": str(where), "trip_ms": 2.0,
                                 "gotit_ms": None})[1] == "no median got-it delay"
        (where / "runqlat.txt").write_text(lhist({}), encoding="utf-8")
        assert "no wait" in hw.a6_prediction({"run_dir": str(where), "trip_ms": 2.0,
                                               "gotit_ms": 0.8})[1]

    def one_campaign(self, tmp_path, rates, backend="kafka", pair="matched", name="stage1_a3"):
        """One setup per rate, each with a recorded run predicting 0.1 and an unrecorded one."""
        runs = campaign(tmp_path, name, pair)
        for i, rate in enumerate(rates):
            setup = "A3-%s-l75-s3000-%s" % (backend, "p%02ds" % i)
            recorded = run_folder(runs, "r001-%s-%d" % (backend, i), setup, backend=backend,
                                  trip=2.0, gotit=0.86, rate=rate)
            (recorded / "runqlat.txt").write_text(lhist({0: 900, 1500: 100}), encoding="utf-8")
            run_folder(runs, "r002-%s-%d" % (backend, i), setup, backend=backend, rate=0.2)
        return runs

    def test_two_thirds_within_the_band_and_the_median_confirm(self, tmp_path):
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.1, 0.12, 0.3)))], ("A3",))
        found = hw.judge_p6(runs)
        part = found["by_part"]["matched, kafka"]
        assert part["within_band"] == 2 and part["setups_with_a_ratio"] == 3
        assert part["median_ratio"] == pytest.approx(0.1 / 0.12)
        assert found["confirmed"] is True and found["tested"] is True
        setup = part["setups"]["stage1_a3/A3-kafka-l75-s3000-p00s"]
        assert setup["unrecorded_rate"] == 0.2 and setup["recorded_runs"] == 1

    def test_one_in_three_within_the_band_is_not_enough(self, tmp_path):
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.1, 0.3, 0.3)))], ("A3",))
        assert hw.judge_p6(runs)["confirmed"] is False

    def test_too_high_at_two_setups_of_three_fails_on_the_share_alone(self, tmp_path):
        """Ratios of 1, 2 and 3: the median, 2, clears 0.8, and one setup in three is inside."""
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.1, 0.05, 0.1 / 3)))],
                               ("A3",))
        part = hw.judge_p6(runs)["by_part"]["matched, kafka"]
        assert part["median_ratio"] == pytest.approx(2.0) and part["within_band"] == 1
        assert part["confirmed"] is False

    def test_a_prediction_systematically_too_low_is_caught_by_the_median(self, tmp_path):
        """Within 0.67 of the rate at every setup, and all of them on the low side."""
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.14, 0.14, 0.14)))], ("A3",))
        part = hw.judge_p6(runs)["by_part"]["matched, kafka"]
        assert part["within_band"] == 3 and part["median_ratio"] < hw.MEDIAN_AT_LEAST
        assert part["confirmed"] is False

    def test_a_setup_that_measured_no_negative_has_no_ratio_and_is_reported(self, tmp_path):
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.1, 0.0)))], ("A3",))
        part = hw.judge_p6(runs)["by_part"]["matched, kafka"]
        assert part["setups_with_a_ratio"] == 1
        assert part["setups_without_a_rate"] == ["stage1_a3/A3-kafka-l75-s3000-p01s"]

    def test_nothing_is_pooled_across_backends(self, tmp_path):
        runs = self.one_campaign(tmp_path, (0.1, 0.1, 0.1))
        self.one_campaign(tmp_path, (0.3, 0.3, 0.3), backend="redis", name="stage1_a3r")
        found = hw.judge_p6(hw.counted_runs(
            [str(runs), str(tmp_path / "stage1_a3r" / "runs")], ("A3",)))
        assert sorted(found["by_part"]) == ["matched, kafka", "matched, redis"]
        assert found["by_part"]["matched, kafka"]["confirmed"] is True
        assert found["confirmed"] is False

    def test_a_part_with_no_ratio_at_all_is_out_of_reach(self, tmp_path):
        runs = hw.counted_runs([str(self.one_campaign(tmp_path, (0.0,)))], ("A3",))
        found = hw.judge_p6(runs)
        assert found["tested"] is False and found["confirmed"] is False
        assert hw.lines(found)[0] == "P6 on A6's recording: out of reach"

    def test_only_the_blocks_the_recording_rides_in_and_only_counted_runs(self, tmp_path):
        runs = self.one_campaign(tmp_path, (0.1,))
        run_folder(runs, "r003-x", "A2-kafka-l75-s3000-p09s")
        run_folder(runs, "r004-x", "A3-kafka-l75-s3000-p00s", verdict="stop")
        found = hw.counted_runs([str(runs)], ("A1", "A3"))
        assert sorted(run["run"] for run in found) == ["law_a3_r001-kafka-0", "law_a3_r002-kafka-0"]
        assert all(run["gotit_ms"] == 0.86 for run in found)


class TestTheTimeline:

    def test_each_event_moves_the_thread_into_the_state_it_names(self):
        line = hw.Timeline([(10, "S"), (20, "W"), (25, "R"), (40, "P"), (45, "R"), (60, "S")])
        assert line.times == [10, 20, 25, 40, 45, 60]
        assert line.states == ["asleep", "waiting", "running", "waiting", "running", "asleep"]
        assert line.at(5) == "unknown" and line.at(22) == "waiting" and line.at(50) == "running"
        assert line.wakes == [20]

    def test_a_wake_up_of_a_running_or_waiting_thread_changes_nothing(self):
        line = hw.Timeline([(10, "R"), (12, "W"), (20, "P"), (22, "W"), (30, "R")])
        assert line.states == ["running", "waiting", "running"]

    def test_a_first_wake_up_finds_a_thread_that_was_asleep(self):
        assert hw.Timeline([(10, "W"), (15, "R")]).states == ["waiting", "running"]

    def test_the_time_in_each_state_adds_up_to_the_interval(self):
        line = hw.Timeline([(10, "S"), (20, "W"), (25, "R"), (40, "P"), (45, "R")])
        spent = line.spent(15, 50)
        assert spent == {"asleep": 5, "waiting": 10, "running": 20, "unknown": 0}
        assert hw.Timeline([(10, "R")]).spent(0, 20) == {"asleep": 0, "waiting": 0,
                                                         "running": 10, "unknown": 10}

    def test_a_wait_is_counted_where_it_begins(self):
        line = hw.Timeline([(10, "S"), (20, "W"), (25, "R"), (40, "P"), (45, "R"), (50, "P")])
        assert line.waits(0, 100) == [5, 5], "the last wait has no end and is not a wait yet"
        assert line.waits(30, 100) == [5]

    def test_an_acknowledgements_own_wait_runs_from_its_wake_or_its_last_stamp(self):
        line = hw.Timeline([(10, "S"), (20, "W"), (25, "R"), (40, "P"), (45, "R")])
        assert line.own_wait(46, None) == 10, "woken at 20: waited 5 then 5 more"
        assert line.own_wait(46, 42) == 3, "stamped at 42 already: only the wait since"
        assert hw.Timeline([(10, "R"), (20, "P"), (24, "R")]).own_wait(30, None) is None


class TestTheRecordsAndTheClock:

    def test_the_clock_offset_is_drawn_straight_between_the_two_readings(self):
        record = {"clocks": [{"realtime_ns": 1000, "monotonic_ns": 100},
                             {"realtime_ns": 2000, "monotonic_ns": 1080}]}
        convert = hw.to_monotonic(record)
        assert convert(1000) == 100 and convert(2000) == 1080
        assert convert(1500) == pytest.approx(590)
        same = {"clocks": [{"realtime_ns": 1000, "monotonic_ns": 100}] * 2}
        assert hw.to_monotonic(same)(1500) == 600

    def test_each_record_is_found_by_the_role_it_names(self, tmp_path):
        (tmp_path / "a_threads.json").write_text(json.dumps(
            {"roles": {"stamps_ack": [1]}, "clocks": []}), encoding="utf-8")
        (tmp_path / "b_threads.json").write_text(json.dumps(
            {"roles": {"stamps_receive": [2]}, "clocks": []}), encoding="utf-8")
        (tmp_path / "c_threads.json").write_text(json.dumps({"roles": {}}), encoding="utf-8")
        (tmp_path / "producer.csv").write_text("x\n", encoding="utf-8")
        found = hw.thread_records(str(tmp_path))
        assert found["producer"]["roles"] == {"stamps_ack": [1]}
        assert found["consumer"]["roles"] == {"stamps_receive": [2]}

    def test_the_messages_are_the_ones_the_integrity_rule_measures(self, tmp_path):
        """The same files, the same warm-up and the same sign as pilot_checks.summarise."""
        where = run_folder(campaign(tmp_path), "r001-x", "A9-kafka-l75-s3000-p09s")
        negatives = a9_world(where)
        found = hw.messages(str(where))
        summary = hw.pilot_checks.summarise(str(where))
        assert len(found) == summary["measured_spans"] == 500
        assert sum(1 for _, ack, arrival in found if arrival - ack < 0) == negatives == \
            summary["measured_negative"] == 50

    def test_a_producer_that_sent_nothing_measures_nothing(self, tmp_path):
        (tmp_path / "producer.csv").write_text(PRODUCER_COLUMNS + "\n", encoding="utf-8")
        assert hw.messages(str(tmp_path)) == []

    def test_the_events_of_other_threads_and_lines_that_are_not_events_are_passed_over(
            self, tmp_path):
        path = tmp_path / "waits.txt"
        path.write_text("Attaching 2 probes...\nR 7 30\nW 7 10\nR 8 11\nX 7 12\nR 7\n"
                        "PS 7 13\nR 7 abc\n", encoding="utf-8")
        assert hw.events(str(path), [7]) == ({7: [(10, "W"), (30, "R")]}, False)
        path.write_text("R 7 30\nLost 3 events\n", encoding="utf-8")
        assert hw.events(str(path), [7])[1] is True


class TestA9:

    def recorded(self, tmp_path, **world):
        runs = campaign(tmp_path)
        where = run_folder(runs, "r001-x", "A9-kafka-l75-s3000-p09s", trip=2.0, gotit=0.86,
                           rate=0.1)
        a9_world(where, **world)
        return runs, where

    def test_each_negative_reading_finds_its_stamper_waiting_for_a_cpu(self, tmp_path):
        runs, where = self.recorded(tmp_path)
        found, why = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert why is None and found["identified"] == found["acknowledgements"] == 500
        assert len(found["readings"]) == 50
        # From arrival at send + 2.0 to the stamp at send + 2.31 it waited until 2.3, then ran.
        assert all(r["waiting"] == pytest.approx(0.3 / 0.31, abs=1e-6) for r in found["readings"])

    def test_a9_2_counts_the_time_a_random_message_would_find_it_stalled(self, tmp_path):
        """Fifty waits of 1.5 ms over a margin T - g of 1.14 ms, in a window of 9.98 s."""
        runs, _ = self.recorded(tmp_path)
        found, _ = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert found["predicted"] == pytest.approx(50 * 0.36 / 9980.0, rel=1e-3)

    def test_a9_2b_counts_the_acknowledgements_whose_own_wait_outlasted_the_margin(self, tmp_path):
        runs, _ = self.recorded(tmp_path)
        found, _ = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert found["predicted_own"] == pytest.approx(0.1)
        assert max(found["waits_ms"]) == pytest.approx(1.5)
        assert len(found["waits_ms"]) == 499, "the last wait begins after the last send"

    def test_where_several_threads_stamp_each_is_found_by_being_on_a_cpu(self, tmp_path):
        runs, _ = self.recorded(tmp_path, stampers=(201, 202, 203))
        found, why = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert why is None and found["identified"] == 500 and found["stamping_threads"] == 3
        assert found["predicted_own"] == pytest.approx(0.1)
        assert found["predicted"] == pytest.approx(50 * 0.36 / 9980.0 / 3, rel=0.05), \
            "each thread's waits weighed by the third of the stamps it made"

    def test_a_run_whose_stampers_cannot_be_told_apart_is_not_read(self, tmp_path):
        runs, _ = self.recorded(tmp_path, stampers=(201, 202), crowd_every=1)
        assert "was identified, under 90%" in hw.a9_run(
            hw.counted_runs([str(runs)], ("A9",))[0])[1]

    def test_readings_the_recording_cannot_show_count_against_a9_1(self, tmp_path):
        """One stamp in twenty finds both stampers on a CPU: the run is read, and the negative
        readings among those are not shown to be waiting, so they count against A9-1."""
        runs, _ = self.recorded(tmp_path, stampers=(201, 202), crowd_every=20)
        found, why = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert why is None and found["identified"] == 475
        said = hw.a9_1(found["readings"])
        assert said["not_shown"] == 25 and said["mostly_waiting"] == 25
        assert said["holds"] is False

    def test_a_reading_whose_interval_is_empty_on_the_tracers_clock_is_not_shown(self, tmp_path):
        """The consumer's clocks laid half a millisecond late put every arrival after its stamp."""
        runs, where = self.recorded(tmp_path)
        record = json.loads((where / "consumer_threads.json").read_text(encoding="utf-8"))
        for pair in record["clocks"]:
            pair["monotonic_ns"] += 500000
        (where / "consumer_threads.json").write_text(json.dumps(record), encoding="utf-8")
        found, why = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert why is None and found["readings"] == [None] * 50

    def test_a_clock_slewed_over_the_run_is_followed(self, tmp_path):
        """200 us of slew puts the late stamps off their thread's 30 us on a CPU, unless the
        offset is drawn between both readings."""
        runs, _ = self.recorded(tmp_path, drift_ns=200000)
        found, why = hw.a9_run(hw.counted_runs([str(runs)], ("A9",))[0])
        assert why is None and found["identified"] == 500

    def test_a_recording_that_lost_events_is_reported_and_not_read(self, tmp_path):
        runs, where = self.recorded(tmp_path, lost=True)
        run = hw.counted_runs([str(runs)], ("A9",))[0]
        assert hw.a9_run(run) == (None, "the recording lost events")
        runs2, where2 = TestA9().recorded(tmp_path / "second")
        (where2 / "waits.err").write_text("Lost 2 events\n", encoding="utf-8")
        assert hw.a9_run(hw.counted_runs([str(runs2)], ("A9",))[0])[1] == \
            "the recording lost events"

    def test_what_stops_a_run_being_read_is_said(self, tmp_path):
        runs, where = self.recorded(tmp_path)
        run = hw.counted_runs([str(runs)], ("A9",))[0]
        (where / "consumer_threads.json").unlink()
        assert hw.a9_run(run)[1] == "no thread record from both clients"
        assert hw.a9_run(dict(run, gotit_ms=None, run_dir=str(where)))[1] == \
            "no thread record from both clients"
        runs2, where2 = TestA9().recorded(tmp_path / "second")
        run2 = hw.counted_runs([str(runs2)], ("A9",))[0]
        assert hw.a9_run(dict(run2, gotit_ms=None))[1] == "no median got-it delay"
        (where2 / "producer.csv").write_text(PRODUCER_COLUMNS + "\n", encoding="utf-8")
        assert hw.a9_run(run2)[1] == "no message measured"
        (where2 / "waits.txt").unlink()
        assert hw.a9_run(run2) == (None, hw.NOT_RECORDED)

    def test_a_reading_whose_stamper_is_unknown_counts_against_a9_1(self, tmp_path):
        readings = [{"waiting": 0.9, "asleep": 0.0, "running": 0.1, "unknown": 0.0}] * 9
        assert hw.a9_1(readings + [None])["holds"] is True
        said = hw.a9_1(readings + [None, None])
        assert said["holds"] is False and said["not_shown"] == 2
        assert hw.a9_1([])["holds"] is False and hw.a9_1([None])["mean_shares"] is None

    def test_the_whole_answer_holds_each_question_to_its_own_rule(self, tmp_path):
        runs, _ = self.recorded(tmp_path)
        run_folder(runs, "r002-x", "A9-kafka-l75-s3000-p09s", rate=0.12)
        found = hw.judge_a9(hw.counted_runs([str(runs)], ("A9",)))
        part = found["by_part"]["matched, kafka"]
        assert found["a9_1_holds"] is True and part["loads"]["75"]["a9_1"]["holds"] is True
        assert found["confirmed"] is False, "A9-2's sum sees 2% of the rate in this world"
        assert found["a9_2b_confirmed"] is True
        setup = part["a9_2b"]["setups"]["stage1_a9/A9-kafka-l75-s3000-p09s"]
        assert setup["ratio"] == pytest.approx(1.0) and setup["unrecorded_rate"] == 0.12
        waits = part["loads"]["75"]["a9_3"]
        assert waits["waits_ms"]["longest"] == pytest.approx(1.5)
        assert waits["slices_ms"] == [3.0] and waits["ticks_ms"] == [1.0]
        text = "\n".join(hw.lines(found))
        assert "A9-2b" in text and "A9-1: holds" in text and "load 75: A9-1 holds" in text

    def test_a_run_not_read_is_reported_and_decides_nothing(self, tmp_path):
        runs, _ = self.recorded(tmp_path, lost=True)
        found = hw.judge_a9(hw.counted_runs([str(runs)], ("A9",)))
        assert found["not_read"][0]["why"] == "the recording lost events"
        assert found["a9_1_holds"] is False and found["tested"] is False
        assert "  not read: law_a9_r001-x -- the recording lost events" in hw.lines(found)
        assert hw.percentiles([]) is None and hw.percentiles([2.0])["p99"] == 2.0


class TestTheCommand:

    def test_it_judges_p6_from_the_folders_it_is_given(self, tmp_path):
        runs = TestA6().one_campaign(tmp_path, (0.1, 0.1, 0.12))
        out, where = io.StringIO(), str(tmp_path / "p6.json")
        assert hw.main(["p6", "--runs", str(runs), "--out", where], out=out) == 0
        assert "P6 on A6's recording: confirmed" in out.getvalue()
        with open(where, encoding="utf-8") as fh:
            assert json.load(fh)["confirmed"] is True

    def test_it_reads_a9_and_leaves_with_one_where_the_prediction_misses(self, tmp_path):
        runs, _ = TestA9().recorded(tmp_path)
        out = io.StringIO()
        assert hw.main(["a9", "--runs", str(runs)], out=out) == 1
        assert "P6 on A9's recording: not confirmed" in out.getvalue()

    def test_a_campaign_that_could_not_test_it_leaves_with_three(self, tmp_path):
        runs = TestA6().one_campaign(tmp_path, (0.0,))
        assert hw.main(["p6", "--runs", str(runs)], out=io.StringIO()) == 3

    def test_no_run_of_the_block_is_an_error_line(self, tmp_path):
        out = io.StringIO()
        assert hw.main(["a9", "--runs", str(campaign(tmp_path))], out=out) == 2
        assert out.getvalue().startswith("ERROR: no counted run of A9")
