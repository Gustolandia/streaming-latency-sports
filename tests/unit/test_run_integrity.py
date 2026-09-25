"""Tests for scripts/run_integrity.py, on run directories built to known answers.

Each run below is a small replica of what cloud/azure/campaign.sh leaves: 400 messages sent ten a
second, a 10 s warm-up, and every file the checks read. The defaults describe a run that counts;
each test changes one thing and says what that one thing must decide.
"""
import csv
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import run_integrity as ri  # noqa: E402
import run_queue  # noqa: E402

START = 1_789_000_000_000_000_000
RATE, DURATION, WARMUP = 10.0, 40.0, 10.0
CHRONY = ("A29FC87B,time.cloudflare.com,3,1789000000.1,%s,0.000001,0.000010,1.0,0.0,0.01,"
          "0.02,0.03,64.0,Normal\n")
STAT = "cpu  %d 0 %d %d 0 0 0 %d 0 0\n"
CAL = {"calibration": {"kafka": {"75": {"gotit_zero_median_ms": 0.2}}}}


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def make_run(tmp_path, name="run", n=400, gap_ms=100.0, trip_ms=0.5, gotit_ms=0.2, acks=True,
             negative_at=None, lose=0, load=75.0, load_samples=None, delay_ms=2.0,
             measured_added=2.0, settings_ok=True, problems=None, clock=(0.00002, -0.00003),
             stat=((100, 100, 800, 0), (800, 200, 1500, 10)), params=None, drop=(),
             baseline_added=None, held_added=None, key="r001-s-a1",
             client_line="CONFIG effective max_inflight=64 ack_stamp=callback"):
    run = tmp_path / name
    run.mkdir()
    sends = [START + int(i * gap_ms * 1e6) for i in range(n)]
    write_csv(run / "producer.csv", ["event_id", "t_prod_send_ns", "t_broker_ack_ns"],
              [["e%d" % i, s, s + int(gotit_ms * 1e6) if acks else "None"]
               for i, s in enumerate(sends)])
    write_csv(run / "consumer_events.csv", ["event_id", "t_consume_ns"],
              [["e%d" % i, s + int((-0.1 if i == negative_at else trip_ms) * 1e6)]
               for i, s in enumerate(sends[:n - lose])])
    first, last = sends[0] / 1e9, sends[-1] / 1e9
    if load_samples is None:
        load_samples = [[first + k * (last - first) / 60, load / 100.0, 3.0] for k in range(61)]
    write_csv(run / "utilisation.csv", ["t_wall", "rho", "loadavg"], load_samples)
    row = {"key": key,
           "params": params or {"backend": "kafka", "load_pct": 75, "delay_ms": delay_ms}}
    (run / "queue_row.json").write_text(json.dumps(row), encoding="utf-8")
    if problems is None:
        problems = [] if settings_ok else ["the base slice is 2800000 ns, not 1500000"]
    (run / "settings_after.json").write_text(json.dumps({"ok": settings_ok, "problems": problems}),
                                             encoding="utf-8")
    (run / "delay_measured.json").write_text(json.dumps(
        {"host_median_ms": 0.30, "receiver_median_ms": 0.30 + measured_added}), encoding="utf-8")
    held = delay_ms if held_added is None else held_added
    (run / "delay_hold.json").write_text(json.dumps(
        {"host_hold_ms": 0.015, "receiver_hold_ms": 0.015 + held}), encoding="utf-8")
    if baseline_added is not None:
        (run / "delay_baseline.json").write_text(json.dumps(
            {"host_median_ms": 0.30, "receiver_median_ms": 0.30 + baseline_added}),
            encoding="utf-8")
    for side, value in zip(("before", "after"), clock):
        if value is not None:
            (run / ("clock_%s.txt" % side)).write_text(CHRONY % value, encoding="utf-8")
    for side, (user, system, idle, steal) in zip(("before", "after"), stat):
        (run / ("stat_%s.txt" % side)).write_text(STAT % (user, system, idle, steal),
                                                   encoding="utf-8")
    backend = row["params"].get("backend")
    log = {"kafka": "producer.log", "redis": "consumer.log"}.get(backend)
    if log and client_line is not None:
        (run / log).write_text("starting\n%s\nOK wrote 400 rows\n" % client_line,
                               encoding="utf-8")
    for name_ in drop:
        (run / name_).unlink()
    return str(run)


def evaluate(path, **kwargs):
    return ri.evaluate(path, RATE, DURATION, WARMUP, **kwargs)


class TestARunThatCounts:

    def test_every_check_passes(self, tmp_path):
        found = evaluate(make_run(tmp_path))
        assert found["verdict"] == "count" and found["reasons"] == []
        assert set(found["checks"]) == {"never_negative", "messages_sent", "messages_received",
                                        "send_rate", "load", "settings", "client", "delay",
                                        "clock"}
        assert found["checks"]["client"]["value"] == 64
        assert found["checks"]["send_rate"]["value"] == pytest.approx(10.0)
        assert found["checks"]["load"]["value"] == pytest.approx(75.0)

    def test_what_is_recorded_beside_the_checks(self, tmp_path):
        recorded = evaluate(make_run(tmp_path))["recorded"]
        assert recorded["messages"] == 300 and recorded["trip_median_ms"] == pytest.approx(0.5)
        assert recorded["steal_pct"] == pytest.approx(100 * 10 / 1510)
        assert recorded["delay_held_ms"] == pytest.approx(2.0)
        assert recorded["delay_added_by_ping_ms"] == pytest.approx(2.0)
        assert recorded["clock_offset_max_s"] == pytest.approx(0.00003)
        assert recorded["gotit_median_ms"] == pytest.approx(0.2)


SETUP = "A3-kafka-l75-s3000-c04h"


def earlier_runs(tmp_path, gotits, setup=SETUP, verdict="count", campaign="law_a2_1_"):
    """This campaign's earlier counted runs of one setup, as its own folders hold them.

    The brake compares a run against these and not against the session's calibration (D17-1),
    so a test of the brake has to build a campaign rather than a run.
    """
    for i, gotit in enumerate(gotits, start=1):
        key = "r%03d-%s-a1" % (i, setup)
        run = make_run(tmp_path, name=campaign + key, gotit_ms=gotit, key=key)
        with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
            json.dump({"verdict": verdict, "recorded": {"gotit_median_ms": gotit}}, fh)


def pooled_spread(tmp_path, spread=0.01, setups=5, campaign="law_a2_1_"):
    """Other setups of the same campaign, so the pooled scatter has degrees of freedom (D18-2).

    Each contributes two counted runs a distance `spread` either side of its own centre, so the
    pool's own scatter is `spread` and its degrees of freedom are one per setup. Without these a
    campaign cannot say how much its got-it moves between runs, and the brake waits.
    """
    for s in range(setups):
        name = "PAD%d-kafka-l75-s3000-c02h" % s
        for i, gotit in enumerate((1.0 - spread, 1.0 + spread), start=1):
            key = "r%03d-%s-a1" % (i, name)
            run = make_run(tmp_path, name=campaign + key, gotit_ms=gotit, key=key)
            with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
                json.dump({"verdict": "count", "recorded": {"gotit_median_ms": gotit}}, fh)


def later_run(tmp_path, gotit_ms, setup=SETUP, round_no=9, attempt=1, campaign="law_a2_1_",
              **kw):
    """The run being judged, placed after those.

    Named the way a driver names them, law_<campaign>_<key>, because the brake has to tell one
    campaign's runs from another's and the campaign is only in the folder name.
    """
    key = "r%03d-%s-a%d" % (round_no, setup, attempt)
    return make_run(tmp_path, name=campaign + key, gotit_ms=gotit_ms, key=key, **kw)


class TestStop:

    def test_a_message_that_arrived_before_it_was_sent(self, tmp_path):
        found = evaluate(make_run(tmp_path, negative_at=150))
        assert found["verdict"] == "stop"
        assert found["reasons"] == ["1 message(s) arrived before they were sent"]

    def test_stopping_reasons_come_before_the_rest(self, tmp_path):
        found = evaluate(make_run(tmp_path, negative_at=150, load=60.0))
        assert found["verdict"] == "stop" and "arrived before" in found["reasons"][0]
        assert "measured load was 60.0%" in found["reasons"][1]

    def test_a_got_it_median_that_moved_too_far(self, tmp_path):
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 0.9), calibration=CAL)
        assert found["verdict"] == "stop"
        assert found["reasons"] == ["the got-it median moved 0.695 ms from this campaign's 2 "
                                    "earlier runs of the same setup, more than 25% of the 2.000 "
                                    "ms added and more than the 0.250 ms this campaign's "
                                    "got-it moves between runs"]

    def test_a_shift_under_the_scatter_of_those_runs_stops_nothing(self, tmp_path):
        """A quarter of a small delay is less than the got-it median moves between runs with
        nothing added at all: on 18 September a pair's Kafka wandered 0.36 ms across four
        zero-delay runs, and a brake set at 0.056 ms stopped a sound session."""
        pooled_spread(tmp_path, spread=0.085)
        earlier_runs(tmp_path, [0.2, 0.32])
        run = later_run(tmp_path, 0.45, delay_ms=0.225, measured_added=0.225)
        assert evaluate(run, calibration=CAL)["verdict"] != "stop"

    def test_a_shift_over_that_scatter_still_stops(self, tmp_path):
        pooled_spread(tmp_path, spread=0.085)
        earlier_runs(tmp_path, [0.2, 0.32])
        run = later_run(tmp_path, 1.0, delay_ms=0.225, measured_added=0.225)
        found = evaluate(run, calibration=CAL)
        assert found["verdict"] == "stop" and "moves between runs" in found["reasons"][0]

    def test_the_scatter_comes_from_the_campaign_and_not_from_the_judged_setup(self, tmp_path):
        """A setup whose two earlier runs happen to agree does not get a tighter brake for it.

        That is what stopped A2's first session: of ten within-setup scatters from 0.053 to
        0.227 ms, the 0.053 was the one being judged against, and a run 0.275 from its centre
        failed a limit the pooled 0.133 would have allowed nearly three times over.
        """
        pooled_spread(tmp_path, spread=0.133)
        earlier_runs(tmp_path, [1.772, 1.775])       # a pair that agrees to 3 thousandths
        found = evaluate(later_run(tmp_path, 1.497, delay_ms=0.081, measured_added=0.081),
                         calibration=CAL)
        assert found["verdict"] == "count", "the campaign's own scatter admits this run"
        assert found["checks"]["gotit_steady"]["ok"]

    def test_the_same_run_stops_when_the_campaign_really_is_that_steady(self, tmp_path):
        """Not switched off: where the whole campaign agrees, that move still stops it."""
        pooled_spread(tmp_path, spread=0.01)
        earlier_runs(tmp_path, [1.772, 1.775])
        found = evaluate(later_run(tmp_path, 1.497, delay_ms=0.081, measured_added=0.081),
                         calibration=CAL)
        assert found["verdict"] == "stop"

    def test_asked_to_record_the_brake_keeps_what_it_would_have_said_and_stops_nothing(
            self, tmp_path):
        """D26-1: A5's 2-CPU session was finished this way after its brake stopped it twice. The
        run that stops under the rule counts, and the brake's own verdict travels with it."""
        pooled_spread(tmp_path, spread=0.01)
        earlier_runs(tmp_path, [1.772, 1.775])
        run = later_run(tmp_path, 1.497, delay_ms=0.081, measured_added=0.081)
        assert evaluate(run, calibration=CAL)["verdict"] == "stop", "the rule is unchanged"
        found = evaluate(run, calibration=CAL, gotit_brake="record")
        assert found["verdict"] == "count" and "gotit_steady" not in found["checks"]
        kept = found["recorded"]["gotit_steady"]
        assert kept["ok"] is False and "moves between runs" in kept["why"]
        assert found["recorded"]["gotit_brake"] == "records and does not stop (D26-1)"

    def test_a_run_the_brake_would_have_passed_is_recorded_as_passing(self, tmp_path):
        pooled_spread(tmp_path, spread=0.133)
        earlier_runs(tmp_path, [1.772, 1.775])
        found = evaluate(later_run(tmp_path, 1.497, delay_ms=0.081, measured_added=0.081),
                         calibration=CAL, gotit_brake="record")
        assert found["verdict"] == "count" and found["recorded"]["gotit_steady"]["ok"] is True

    def test_a_run_the_brake_cannot_judge_yet_carries_the_mode_and_no_verdict(self, tmp_path):
        """The first runs of a setup have nothing to be held against, in either mode."""
        found = evaluate(later_run(tmp_path, 1.497, delay_ms=0.081, measured_added=0.081),
                         calibration=CAL, gotit_brake="record")
        assert found["verdict"] == "count" and "gotit_steady" not in found["recorded"]
        assert found["recorded"]["gotit_brake"] == "records and does not stop (D26-1)"

    def test_a_brake_that_neither_stops_nor_records_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="either stops or records"):
            evaluate(later_run(tmp_path, 1.0), calibration=CAL, gotit_brake="ignore")

    def test_the_brake_waits_until_the_pool_has_enough_behind_it(self, tmp_path):
        """A pool of two or three runs is the same fault one level up (D18-2)."""
        # One short: the judged setup's own two earlier runs are in the pool as well, so the
        # padding supplies two fewer than the threshold.
        pooled_spread(tmp_path, spread=0.01, setups=ri.GOTIT_MIN_POOL_DF - 2)
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 5.0), calibration=CAL)
        assert found["verdict"] == "count" and "gotit_steady" not in found["checks"]
        assert found["recorded"]["gotit_campaign_spread_df"] == ri.GOTIT_MIN_POOL_DF - 1
        assert found["recorded"]["gotit_campaign_spread_ms"] is None

    def test_what_the_allowance_was_built_from_travels_with_the_run(self, tmp_path):
        """A brake that stops a campaign should be arguable from the campaign's own files."""
        pooled_spread(tmp_path, spread=0.02)
        earlier_runs(tmp_path, [0.2, 0.24])
        recorded = evaluate(later_run(tmp_path, 0.22), calibration=CAL)["recorded"]
        assert recorded["gotit_campaign_spread_ms"] == pytest.approx(0.02)
        assert recorded["gotit_campaign_spread_df"] == 6, "five padding setups and the judged one"
        assert recorded["gotit_setup_centre_ms"] == pytest.approx(0.22)

    def test_a_setup_with_too_few_earlier_runs_is_recorded_and_not_braked(self, tmp_path):
        """The first runs of a setup have nothing like themselves to be held against.

        A comparison against a single other run is a comparison against that run's noise as much
        as against this one's, so the brake waits until there are two.
        """
        earlier_runs(tmp_path, [0.2])
        found = evaluate(later_run(tmp_path, 5.0), calibration=CAL)
        assert found["verdict"] == "count" and "gotit_steady" not in found["checks"]
        assert found["recorded"]["gotit_earlier_same_setup"] == 1

    def test_only_runs_that_counted_are_compared_against(self, tmp_path):
        earlier_runs(tmp_path, [0.2, 0.21], verdict="repeat")
        found = evaluate(later_run(tmp_path, 5.0), calibration=CAL)
        assert found["recorded"]["gotit_earlier_same_setup"] == 0
        assert "gotit_steady" not in found["checks"]

    def test_another_setups_runs_are_not_compared_against(self, tmp_path):
        earlier_runs(tmp_path, [0.2, 0.21], setup="A3-kafka-l75-s3000-f15h")
        found = evaluate(later_run(tmp_path, 5.0), calibration=CAL)
        assert found["recorded"]["gotit_earlier_same_setup"] == 0

    def test_a_later_round_is_not_earlier(self, tmp_path):
        """Earlier is the queue's own order for this setup, not the filesystem's.

        A run re-queued as the second attempt at round 2 follows round 1 and the first attempt
        at its own round, and precedes round 3 -- which is on disk already and must not count.
        """
        earlier_runs(tmp_path, [0.2, 0.21, 0.2])
        found = evaluate(later_run(tmp_path, 5.0, round_no=2, attempt=2), calibration=CAL)
        assert found["recorded"]["gotit_earlier_same_setup"] == 2


class TestRepeat:

    @pytest.mark.parametrize("change,fragment", [
        (dict(n=390), "290 messages were sent after the warm-up, fewer than 99% of the 300"),
        (dict(lose=10), "290 of the 300 messages sent after the warm-up arrived"),
        (dict(gap_ms=110.0), "sent at 9.09 a second against 10"),
        (dict(load=70.0), "the measured load was 70.0% against 75%"),
        (dict(settings_ok=False), "changed during the run: the base slice is 2800000 ns"),
        (dict(settings_ok=False, problems=[]), "sched_settings.py gave no reason"),
        (dict(held_added=1.0), "the broker held 1.000 ms against 2 ms set"),
        (dict(clock=(0.00002, None)), "not logged on one side of the run"),
        (dict(clock=(None, None)), "not logged before or after the run")])
    def test_a_condition_that_did_not_take(self, tmp_path, change, fragment):
        found = evaluate(make_run(tmp_path, **change))
        assert found["verdict"] == "repeat" and any(fragment in r for r in found["reasons"]), found

    def test_too_few_load_samples_and_rows_that_are_not_samples(self, tmp_path):
        inside = START / 1e9 + 15
        rows = [[inside, 0.75, 1.0], ["x", "0.7", "1"], ["", "", ""], [inside]]
        found = evaluate(make_run(tmp_path, load_samples=rows))
        assert found["verdict"] == "repeat"
        assert found["reasons"] == ["only 1 load samples fell while messages were sent"]

    @pytest.mark.parametrize("dropped,fragment", [
        ("utilisation.csv", "the load could not be checked"),
        ("settings_after.json", "settings_after.json cannot be read"),
        ("delay_hold.json", "the delay could not be checked")])
    def test_a_file_a_check_needs_is_missing(self, tmp_path, dropped, fragment):
        found = evaluate(make_run(tmp_path, drop=(dropped,)))
        assert found["verdict"] == "repeat" and any(fragment in r for r in found["reasons"])

    def test_a_capture_without_its_two_holds(self, tmp_path):
        run = make_run(tmp_path)
        with open(os.path.join(run, "delay_hold.json"), "w", encoding="utf-8") as fh:
            fh.write('{"host_hold_ms": 0.015}')
        assert "lacks the two holds" in " ".join(evaluate(run)["reasons"])

    def test_a_broken_json_file(self, tmp_path):
        run = make_run(tmp_path)
        with open(os.path.join(run, "settings_after.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        assert "settings_after.json is not valid JSON" in " ".join(evaluate(run)["reasons"])

    def test_a_run_whose_own_files_cannot_be_read(self, tmp_path):
        found = evaluate(make_run(tmp_path, drop=("queue_row.json",)))
        assert found["verdict"] == "repeat" and list(found["checks"]) == ["run_files"]
        assert found["reasons"][0].startswith("the run's files could not be read: queue_row.json")

    def test_a_producer_file_with_no_send_times(self, tmp_path):
        run = make_run(tmp_path)
        with open(os.path.join(run, "producer.csv"), "w", encoding="utf-8") as fh:
            fh.write("event_id,t_prod_send_ns,t_broker_ack_ns\ne1,,\n")
        assert "producer.csv holds no send times" in evaluate(run)["reasons"][0]

    def test_a_summary_with_nothing_after_the_warm_up(self, tmp_path):
        """What a warm-up longer than the run looks like from every check that counts sends."""
        summary = {"messages": 0, "trip_negative": 0, "trip_median_ms": 0.5}
        found = ri.evaluate(make_run(tmp_path), RATE, 1000.0, 900.0,
                            summarise=lambda run, warmup: summary)
        failed = {name for name, check in found["checks"].items() if not check["ok"]}
        assert {"messages_sent", "messages_received", "send_rate", "load"} <= failed

    def test_nothing_sent_means_nothing_received_either(self):
        check = ri.message_checks([], 0, RATE, DURATION, WARMUP)["messages_received"]
        assert not check["ok"] and check["why"] == "0 of the 0 messages sent after the warm-up arrived"

    def test_a_plan_that_states_its_count_is_held_to_that_count(self):
        """D29-1: M0 replays the football match in bursts, so the count it is held to is the
        plan's own events in the window, not a rate times a time."""
        sends = [START + i for i in range(1350)]
        held = ri.message_checks(sends, 1350, RATE, DURATION, WARMUP, planned=1363)
        assert held["messages_sent"]["ok"] and held["messages_sent"]["limit"] == "at least 1349"
        short = ri.message_checks(sends[:1300], 1300, RATE, DURATION, WARMUP, planned=1363)
        assert not short["messages_sent"]["ok"]
        assert "fewer than 99% of the 1363 planned" in short["messages_sent"]["why"]

    def test_send_times_all_at_one_instant_cannot_give_a_rate(self):
        check = ri.rate_check([START, START, START], RATE)
        assert not check["ok"] and "too few distinct send times" in check["why"]

    @pytest.mark.parametrize("rate,duration", [(0.0, 40.0), (10.0, 10.0)])
    def test_a_plan_that_cannot_be_checked_is_an_error(self, tmp_path, rate, duration):
        with pytest.raises(ValueError, match="positive rate"):
            ri.evaluate(make_run(tmp_path), rate, duration, WARMUP)


class TestTheDelayIsReadWhereItIsApplied:
    """Plan v7. Ping reads about half a millisecond above the round trip our messages take, with a
    tail several times longer, and in the receiver's namespace it shows a 0.28 ms difference that
    TCP does not. The broker's own capture reads the treatment itself, to a few microseconds."""

    def test_the_broker_holding_the_delay_counts(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=2.0, held_added=2.018))
        assert found["verdict"] == "count"
        assert found["recorded"]["delay_held_ms"] == pytest.approx(2.018)

    def test_a_delay_the_broker_did_not_hold_is_repeated(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=2.0, held_added=1.8))
        assert found["verdict"] == "repeat"
        assert "the broker held 1.800 ms against 2 ms set" in found["reasons"]

    def test_a_run_without_its_capture_is_repeated(self, tmp_path):
        found = evaluate(make_run(tmp_path, drop=("delay_hold.json",)))
        assert found["verdict"] == "repeat"
        assert found["checks"]["delay"]["why"].startswith("the delay could not be checked")

    def test_ping_is_recorded_beyond_its_own_zero_reading_and_judges_nothing(self, tmp_path):
        """On the second x86 pair the receiver's ping path was 0.4 ms faster than the host's with
        no delay at all. That is not delay, and it no longer decides anything either."""
        found = evaluate(make_run(tmp_path, delay_ms=0.0, held_added=0.0, measured_added=-0.43,
                                  baseline_added=-0.41))
        assert found["verdict"] == "count"
        assert found["recorded"]["delay_added_by_ping_ms"] == pytest.approx(-0.02)

    @pytest.mark.parametrize("change", [{"drop": ("delay_measured.json",)},
                                        {"baseline_added": 0.0}])
    def test_a_ping_reading_that_cannot_be_read_records_nothing(self, tmp_path, change):
        run = make_run(tmp_path, **change)
        if "baseline_added" in change:
            with open(os.path.join(run, "delay_baseline.json"), "w", encoding="utf-8") as fh:
                fh.write('{"host_median_ms": 0.3}')
        found = evaluate(run)
        assert found["verdict"] == "count"
        assert found["recorded"]["delay_added_by_ping_ms"] is None


class TestTheGotItComparison:

    def test_a_steady_median_counts(self, tmp_path):
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 0.2), calibration=CAL)
        assert found["verdict"] == "count" and found["checks"]["gotit_steady"]["ok"]
        assert found["checks"]["gotit_steady"]["limit"] == "within 0.500 ms"

    def test_a_run_without_a_delay_is_not_compared(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=0.0, measured_added=0.0), calibration=CAL)
        assert found["verdict"] == "count" and "gotit_steady" not in found["checks"]

    def test_the_brake_no_longer_needs_a_calibration_at_all(self, tmp_path):
        """It compares a run with its own campaign, so a missing calibration stops nothing.

        Under version 16 a calibration that held no zero-delay median for this backend made the
        run a repeat. The brake does not read it any more; only the recorded shift does, and
        that is allowed to be absent.
        """
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 0.2), calibration={"calibration": {"redis": {}}})
        assert found["verdict"] == "count" and found["checks"]["gotit_steady"]["ok"]
        assert found["recorded"]["gotit_shift_from_calibration_ms"] is None

    @pytest.mark.parametrize("change,fragment", [
        ({"acks": False}, "the run recorded no got-it times"),
        ({"drop": ("delay_hold.json",)}, "the added delay was not measured")])
    def test_what_cannot_be_compared_is_a_repeat_not_a_stop(self, tmp_path, change, fragment):
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 0.2, **change), calibration=CAL)
        assert found["verdict"] == "repeat" and not found["checks"]["gotit_compared"]["ok"]
        assert any(fragment in r for r in found["reasons"])


class TestFindingACampaignsOwnEarlierRuns:
    """What the brake compares against, and what it refuses to compare against (D17-1)."""

    def test_a_key_that_is_not_a_queue_key_names_no_setup(self):
        assert ri.setup_of("not-a-key") is None
        assert ri.setup_of("") is None and ri.setup_of(None) is None

    def test_a_key_gives_its_round_setup_and_attempt(self):
        assert ri.setup_of("r012-A3-kafka-l50-s3000-c08h-a2") == (
            12, "A3-kafka-l50-s3000-c08h", 2)

    def test_a_run_whose_own_key_cannot_be_read_compares_against_nothing(self, tmp_path):
        bare = tmp_path / "bare"
        bare.mkdir()
        assert ri.earlier_same_setup(str(bare)) == []

    def test_a_run_whose_key_is_not_a_queue_key_compares_against_nothing(self, tmp_path):
        run = make_run(tmp_path, key="handmade")
        assert ri.earlier_same_setup(run) == []

    def test_a_sibling_that_counted_but_recorded_no_got_it_is_skipped(self, tmp_path):
        earlier_runs(tmp_path, [0.2])
        key = "r002-%s-a1" % SETUP
        run = make_run(tmp_path, name="law_a2_1_" + key, key=key)
        with open(os.path.join(run, "integrity.json"), "w", encoding="utf-8") as fh:
            json.dump({"verdict": "count", "recorded": {}}, fh)
        assert ri.earlier_same_setup(later_run(tmp_path, 0.2)) == [0.2]

    def test_another_campaigns_runs_of_the_same_setup_are_not_compared_against(self, tmp_path):
        """A2 runs each kernel with each backend on two different days, so its own later
        sessions carry the very same keys -- on another boot, behind another calibration. That
        is the drift this brake was moved off the calibration to escape."""
        earlier_runs(tmp_path, [0.2, 0.21], campaign="law_a2_OTHER_")
        found = evaluate(later_run(tmp_path, 5.0), calibration=CAL)
        assert found["recorded"]["gotit_earlier_same_setup"] == 0
        assert "gotit_steady" not in found["checks"]

    def test_a_later_attempt_at_the_same_round_is_still_earlier(self, tmp_path):
        """A run re-queued as a2 follows a1, and both precede the next round."""
        earlier_runs(tmp_path, [0.2, 0.21])
        assert len(ri.earlier_same_setup(later_run(tmp_path, 0.2, round_no=3))) == 2


class TestARunThatTakesItsNoteAnotherWay:
    """A8 varies where the "got it" note is taken, and taking it inline forces the producer to
    one message in flight where the calibration ran with sixty-four. Those are two different
    producers on purpose. Holding such a run against the calibration's median asks what that
    treatment did, not what the added delay did, and P5(c) asks only the second.

    On the Arm pair this stopped A8 on its first Python run: 0.167 ms against a 0.145 ms brake,
    moved by the note's place and not by the delay. The Java runs, whose two medians happen to
    lie 0.06 ms apart, went through the same brake untouched."""

    def test_a_callback_run_is_still_held_against_the_calibration(self):
        assert ri.gotit_comparable({"ack_stamp": "callback"})
        assert ri.gotit_comparable({}), "every block but A8 leaves it unset, which is callback"

    def test_an_inline_run_has_no_like_for_like_baseline(self):
        assert not ri.gotit_comparable({"ack_stamp": "inline"})

    def test_an_inline_run_counts_instead_of_being_stopped(self, tmp_path):
        """The shift that stopped A8 on the Arm pair, with the note taken inline."""
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "ack_stamp": "inline"}
        run = make_run(tmp_path, params=params, gotit_ms=0.9,
                       client_line="CONFIG effective max_inflight=1 ack_stamp=inline")
        found = evaluate(run, calibration=CAL)
        assert found["verdict"] == "count"
        assert "gotit_steady" not in found["checks"]
        assert "gotit_compared" not in found["checks"], "nothing failed; there was nothing to fail"

    def test_the_same_shift_taken_the_other_runs_way_still_stops(self, tmp_path):
        """The brake is not loosened. A run that takes its note the way the runs it is held
        against took theirs, and moves that far, stops exactly as before."""
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        found = evaluate(later_run(tmp_path, 0.9), calibration=CAL)
        assert found["verdict"] == "stop" and "moved" in found["reasons"][0]

    def test_every_run_says_whether_the_brake_could_judge_it(self, tmp_path):
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "ack_stamp": "inline"}
        inline = evaluate(make_run(tmp_path, name="a", params=params,
                                   client_line="CONFIG effective max_inflight=1 ack_stamp=inline"),
                          calibration=CAL)["recorded"]
        assert inline["gotit_compared_with_calibration"] is False
        assert inline["gotit_note_at"] == "inline"
        callback = evaluate(make_run(tmp_path, name="b"), calibration=CAL)["recorded"]
        assert callback["gotit_compared_with_calibration"] is True
        assert callback["gotit_note_at"] == "callback"

    def test_a_run_with_no_delay_is_not_claimed_to_have_been_compared(self, tmp_path):
        run = make_run(tmp_path, delay_ms=0.0, measured_added=0.0)
        assert evaluate(run, calibration=CAL)["recorded"][
            "gotit_compared_with_calibration"] is False

    def test_a_run_judged_without_a_calibration_says_so_too(self, tmp_path):
        assert evaluate(make_run(tmp_path))["recorded"][
            "gotit_compared_with_calibration"] is False


class TestACalibrationFittedPerClient:
    """A8 fits one calibration per client and joins them under the client's name, so its file is
    a level deeper than every other session's. Read as though it were flat it yields no entry,
    every run of the block is a repeat, and the repeat fails in exactly the same way -- a whole
    campaign run twice for nothing. This is what that costs, held down by tests."""

    #: The shape stage 0 writes when CLIENTS is set: client, then backend, then load.
    PER_CLIENT = {"calibration": {
        "java": {"kafka": {"75": {"gotit_zero_median_ms": 0.2}}},
        "python": {"kafka": {"75": {"gotit_zero_median_ms": 0.9}}}}}

    def test_a_java_runs_recorded_shift_is_taken_from_the_java_fit(self, tmp_path):
        """The brake no longer reads this file (D17-3), but the recorded shift still does, and
        reading it at the wrong level would record another client's instrument."""
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "language": "java"}
        found = evaluate(make_run(tmp_path, params=params, gotit_ms=0.5),
                         calibration=self.PER_CLIENT)
        assert found["verdict"] == "count"
        assert found["recorded"]["gotit_shift_from_calibration_ms"] == pytest.approx(0.3)

    def test_each_client_is_held_against_its_own_and_not_the_others(self):
        """The two fits differ by 0.7 ms here. Reading the wrong one would pass or fail the run
        on another client's instrument."""
        for language, expected in (("java", 0.2), ("python", 0.9)):
            entry = ri.calibration_entry(
                self.PER_CLIENT, {"backend": "kafka", "load_pct": 75, "language": language})
            assert entry["gotit_zero_median_ms"] == expected

    def test_a_session_with_one_fit_per_backend_still_reads_flat(self):
        entry = ri.calibration_entry(CAL, {"backend": "kafka", "load_pct": 75})
        assert entry["gotit_zero_median_ms"] == 0.2

    def test_a_run_naming_a_client_the_file_does_not_have_falls_back(self):
        """Every block but A8 leaves the client unset, and a flat file has no client level at
        all; naming one must not lose the entry that is there."""
        entry = ri.calibration_entry(
            CAL, {"backend": "kafka", "load_pct": 75, "language": "java"})
        assert entry["gotit_zero_median_ms"] == 0.2

    @pytest.mark.parametrize("calibration", [
        None, {}, {"calibration": None}, {"calibration": "not a mapping"},
        {"calibration": {"java": {"kafka": {"88": {"gotit_zero_median_ms": 0.2}}}}},
        {"calibration": {"java": {"kafka": {"75": {"gotit_zero_median_ms": None}}}}},
        {"calibration": {"java": "not a mapping"}}])
    def test_anything_else_is_no_entry_rather_than_a_guess(self, calibration):
        assert ri.calibration_entry(
            calibration, {"backend": "kafka", "load_pct": 75, "language": "java"}) is None


class TestTheClientSettings:
    """The paper's own settings (supplement, "Learned"); the Redis one was missing from the law
    campaign until plan v6, and this treatment failed silently three times in earlier work."""

    def test_redis_acknowledging_in_batches_of_200_counts(self, tmp_path):
        params = {"backend": "redis", "load_pct": 75, "delay_ms": 2.0}
        run = make_run(tmp_path, params=params,
                       client_line="CONFIG effective ack_batch=200 count=200 block_ms=1000")
        assert evaluate(run)["checks"]["client"] == {
            "ok": True, "value": 200, "limit": "ack_batch=200 in consumer.log", "why": ""}

    def test_a_run_that_takes_the_note_inline_is_expected_to_run_one_in_flight(self):
        """A8 takes the got-it note two ways. Taken inline it forces one request in flight --
        above one the blocking wait resolves an older event and the stamp would belong to a
        different message -- so a run that asked for inline and reported 1 did as it was told,
        where the standing setting for every other Kafka run is 64."""
        assert ri.client_check.__defaults__ == (None, None)
        assert ri.INLINE_MAX_INFLIGHT == 1

    def test_an_m0_setup_that_acknowledges_one_at_a_time_is_held_to_one(self, tmp_path):
        """S0-2, D29-1: M0's intervention on M-H2. Asked for 1 and reporting 1 did as it was
        told; asked for 1 and reporting the standing 200 is the fault this check catches."""
        params = {"backend": "redis", "load_pct": 75, "delay_ms": 2.0, "ack_batch": 1}
        run = make_run(tmp_path, name="a", params=params,
                       client_line="CONFIG effective ack_batch=1 count=200 block_ms=1000")
        assert evaluate(run)["checks"]["client"]["ok"] is True
        run = make_run(tmp_path, name="b", params=params,
                       client_line="CONFIG effective ack_batch=200 count=200 block_ms=1000")
        check = evaluate(run)["checks"]["client"]
        assert check["ok"] is False and check["why"] == \
            "the redis client ran with ack_batch=200, not 1"

    def test_taking_the_note_inline_and_reporting_one_counts(self, tmp_path):
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "ack_stamp": "inline"}
        run = make_run(tmp_path, params=params,
                       client_line="CONFIG effective max_inflight=1 ack_stamp=inline client=java")
        assert evaluate(run)["checks"]["client"]["ok"] is True

    def test_taking_it_inline_and_reporting_sixty_four_does_not(self, tmp_path):
        """Which is the fault this check exists to catch: the note would name another message."""
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "ack_stamp": "inline"}
        run = make_run(tmp_path, params=params,
                       client_line="CONFIG effective max_inflight=64 ack_stamp=inline")
        found = evaluate(run)["checks"]["client"]
        assert found["ok"] is False and "not 1" in found["why"]

    def test_taking_it_in_the_callback_expects_the_standing_setting(self, tmp_path):
        params = {"backend": "kafka", "load_pct": 75, "delay_ms": 2.0, "ack_stamp": "callback"}
        run = make_run(tmp_path, params=params,
                       client_line="CONFIG effective max_inflight=64 ack_stamp=callback client=java")
        assert evaluate(run)["checks"]["client"]["ok"] is True

    @pytest.mark.parametrize("backend,line,why", [
        ("redis", "CONFIG effective ack_batch=1 count=200 block_ms=1000",
         "the redis client ran with ack_batch=1, not 200"),
        ("kafka", "CONFIG effective max_inflight=1 ack_stamp=callback",
         "the kafka client ran with max_inflight=1, not 64"),
        ("kafka", "OK kafka producer: wrote 400 rows",
         "the kafka client ran with max_inflight=an unlogged value, not 64")])
    def test_a_client_not_set_as_the_campaign_sets_it_is_repeated(self, tmp_path, backend, line,
                                                                  why):
        run = make_run(tmp_path, params={"backend": backend, "load_pct": 75, "delay_ms": 2.0},
                       client_line=line)
        found = evaluate(run)
        assert found["verdict"] == "repeat" and found["reasons"] == [why]

    def test_a_missing_client_log_is_repeated(self, tmp_path):
        found = evaluate(make_run(tmp_path, client_line=None))
        assert found["verdict"] == "repeat"
        assert found["checks"]["client"]["why"].startswith("the client could not be checked")


TCP = ("Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails "
       "EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors\n"
       "Tcp: 1 200 120000 -1 10 5 0 0 3 1000 2000 %d 0 0 0\n")


class TestRecordedOnly:

    def test_the_brokers_hold_and_the_resent_segments(self, tmp_path):
        run = make_run(tmp_path)
        with open(os.path.join(run, "delay_hold.json"), "w", encoding="utf-8") as fh:
            json.dump({"host_hold_ms": 0.015, "receiver_hold_ms": 2.023}, fh)
        for prefix, (before, after) in (("", (5, 9)), ("broker_", (40, 40))):
            for when, value in (("before", before), ("after", after)):
                with open(os.path.join(run, "%stcp_%s.txt" % (prefix, when)), "w",
                          encoding="utf-8") as fh:
                    fh.write(TCP % value)
        recorded = evaluate(run)["recorded"]
        assert recorded["delay_held_ms"] == pytest.approx(2.008)
        assert recorded["retransmitted"] == {"driver": 4, "receiver": None, "broker": 0}

    def test_counters_that_cannot_be_read_record_nothing(self, tmp_path):
        run = make_run(tmp_path)
        for name, text in (("tcp_before.txt", "Tcp: RetransSegs\n"),
                           ("tcp_after.txt", "Tcp: RetransSegs\nTcp: 3\n"),
                           ("delay_hold.json", json.dumps({"host_hold_ms": 0.01}))):
            with open(os.path.join(run, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        assert ri.retransmitted(run, "driver") is None
        found = evaluate(run)
        assert found["recorded"]["delay_held_ms"] is None and found["verdict"] == "repeat"

    @pytest.mark.parametrize("stat", [((1, 1, 1, 1), (1, 1, 1, 1))])
    def test_no_time_passing_gives_no_steal(self, tmp_path, stat):
        assert ri.steal_pct(make_run(tmp_path, stat=stat)) is None

    def test_a_missing_or_short_or_broken_stat_line_gives_no_steal(self, tmp_path):
        run = make_run(tmp_path, drop=("stat_after.txt",))
        assert ri.steal_pct(run) is None
        for text in ("cpu 1 2\n", "cpu a b c d e f g h\n"):
            for side in ("before", "after"):
                with open(os.path.join(run, "stat_%s.txt" % side), "w", encoding="utf-8") as fh:
                    fh.write(text)
            assert ri.steal_pct(run) is None

    def test_a_clock_line_that_is_not_chronys(self, tmp_path):
        path = tmp_path / "clock.txt"
        path.write_text("no offset here\n", encoding="utf-8")
        assert ri.clock_offset_s(str(path)) is None


def ledger(*rows):
    """(status, finished minute, reason) rows, in the order a queue holds them."""
    return [{"key": "k%d" % i, "status": status,
             "finished_utc": "" if minute is None else "2026-09-16T10:%02d:00Z" % minute,
             "reason": reason} for i, (status, minute, reason) in enumerate(rows)]


class TestGuard:

    def test_a_campaign_that_is_going_well(self):
        stop, why = ri.guard(ledger(("done", 1, ""), ("done", 2, ""), ("queued", None, ""),
                                    ("running", None, "")))
        assert not stop and why == "2 attempts finished, 0 of them failed"

    def test_three_failed_attempts_in_a_row_in_the_order_they_finished(self):
        rows = ledger(("failed", 5, "load off"), ("done", 1, ""), ("failed", 3, "x"),
                      ("abandoned", 4, "y"))
        stop, why = ri.guard(rows)
        assert stop and why == "the last 3 attempts all failed; the latest because: load off"

    def test_a_failure_without_a_reason(self):
        stop, why = ri.guard(ledger(("failed", 1, ""), ("failed", 2, ""), ("failed", 3, "")))
        assert stop and why.endswith("no reason was recorded")

    def test_too_large_a_share_of_recent_attempts_failed(self):
        pattern = ["done", "failed", "done", "failed", "done", "failed", "done", "done", "done",
                   "done"]
        stop, why = ri.guard(ledger(*[(s, i, "r") for i, s in enumerate(pattern)]))
        assert stop and why == "3 of the last 10 attempts failed, more than 20%"

    def test_the_share_waits_for_ten_attempts(self):
        pattern = ["done", "failed", "done", "failed", "done", "failed"]
        stop, _ = ri.guard(ledger(*[(s, i, "r") for i, s in enumerate(pattern)]))
        assert not stop


def write_queue(tmp_path, rows):
    path = tmp_path / "queue.csv"
    full = [dict({f: "" for f in run_queue.FIELDS}, **row) for row in rows]
    run_queue.write_queue(str(path), full)
    return str(path)


class TestMain:

    @staticmethod
    def run(argv):
        out = io.StringIO()
        return ri.main(argv, out=out), out.getvalue()

    def check(self, run, *extra):
        return self.run(["check", run, "--rate", "10", "--duration", "40", "--warmup-s", "10"]
                        + list(extra))

    def test_a_run_that_counts_writes_its_verdict_next_to_it(self, tmp_path):
        run = make_run(tmp_path)
        code, text = self.check(run)
        assert code == 0 and text == "count\n"
        with open(os.path.join(run, "integrity.json"), encoding="utf-8") as fh:
            assert json.load(fh)["verdict"] == "count"

    def test_repeat_and_stop_exit_differently(self, tmp_path):
        code, text = self.check(make_run(tmp_path, name="a", load=60.0))
        assert code == 1 and text.startswith("repeat: the measured load was 60.0%")
        code, text = self.check(make_run(tmp_path, name="b", negative_at=150))
        assert code == 3 and text.startswith("stop: 1 message(s) arrived")

    def test_a_calibration_file_is_read(self, tmp_path):
        """It no longer brakes anything, so what it must do is reach the recorded shift."""
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps(CAL), encoding="utf-8")
        run = make_run(tmp_path, gotit_ms=0.9)
        code, _ = self.check(run, "--calibration", str(path))
        assert code == 0
        with open(os.path.join(run, "integrity.json"), encoding="utf-8") as fh:
            shift = json.load(fh)["recorded"]["gotit_shift_from_calibration_ms"]
        assert shift == pytest.approx(0.7)

    def test_a_campaign_stops_itself_through_the_command(self, tmp_path):
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        code, text = self.check(later_run(tmp_path, 0.9))
        assert code == 3 and "got-it median moved" in text

    def test_the_command_takes_a_count_the_plan_states(self, tmp_path):
        """D29-1, as campaign.sh passes it for M0. The fixture sends 300 after its warm-up:
        enough for a plan of 10 a second, not for one that says it planned 400."""
        code, _ = self.check(make_run(tmp_path, name="a"))
        assert code == 0
        code, text = self.check(make_run(tmp_path, name="b"), "--planned", "400")
        assert code == 1 and "fewer than 99% of the 400 planned" in text

    def test_the_command_can_be_asked_to_record_rather_than_stop(self, tmp_path):
        """D26-1, as campaign.sh passes it when GOTIT_BRAKE is set."""
        pooled_spread(tmp_path)
        earlier_runs(tmp_path, [0.2, 0.21])
        run = later_run(tmp_path, 0.9)
        code, text = self.check(run, "--gotit-brake", "record")
        assert code == 0 and text == "count\n"
        with open(os.path.join(run, "integrity.json"), encoding="utf-8") as fh:
            recorded = json.load(fh)["recorded"]
        assert recorded["gotit_steady"]["ok"] is False and "D26-1" in recorded["gotit_brake"]

    @pytest.mark.parametrize("extra", [["--calibration", "no-such-file.json"]])
    def test_errors_are_one_line(self, tmp_path, extra):
        code, text = self.check(make_run(tmp_path), *extra)
        assert code == 2 and text.startswith("ERROR:")
        code, text = self.run(["check", make_run(tmp_path, name="z"), "--rate", "0",
                               "--duration", "40"])
        assert code == 2 and "positive rate" in text

    def test_show_gives_the_watch_one_line(self, tmp_path):
        run = make_run(tmp_path, load=60.0)
        self.check(run)
        code, text = self.run(["show", run])
        assert code == 0 and json.loads(text)["verdict"] == "repeat"
        assert self.run(["show", str(tmp_path / "none")])[0] == 2

    def test_guard_from_the_command_line(self, tmp_path):
        failing = write_queue(tmp_path, [{"key": "k%d" % i, "status": "failed",
                                          "finished_utc": "2026-09-16T10:0%d:00Z" % i,
                                          "reason": "load off"} for i in range(3)])
        code, text = self.run(["guard", "--queue", failing])
        assert code == 3 and "all failed" in text
        fine = write_queue(tmp_path, [{"key": "k1", "status": "done",
                                       "finished_utc": "2026-09-16T10:00:00Z"}])
        assert self.run(["guard", "--queue", fine])[0] == 0
        assert self.run(["guard", "--queue", str(tmp_path / "none.csv")])[0] == 2


class TestTheFloorIsAboveTheDriftAWorkingCampaignShows:
    """The floor was 0.10 ms, P5(c)'s equivalence margin, which is the right size for the
    question P5(c) asks and the wrong size for this one.

    Within-campaign drift has been measured on two sound campaigns: A8 moved 0.124 ms on the Arm
    pair and 0.134 on the x86 pair, over hours, with nothing else wrong. The x86 stop is the one
    to read closely: the campaign's own pooled scatter put the allowance at 0.132 ms and the move
    was 0.134, so an eight-hour campaign stopped at 86 of 144 runs on an overshoot of two
    microseconds. Three times a very tight scatter is a very tight allowance -- A8's within-setup
    scatter is 0.012 to 0.036 ms -- and the floor is what stops the allowance collapsing onto the
    noise. At 0.10 it sat below the drift sound campaigns show, so it never did that job.
    """

    def _judged(self, shift_ms, added_ms=0.5, scatter=0.02):
        summary = {"gotit_median_ms": 1.0 + shift_ms}
        params = {"delay_ms": added_ms, "ack_stamp": None}
        return ri.gotit_checks(summary, params, added_ms, earlier=[1.0, 1.0], spread=scatter)

    def test_the_drift_that_stopped_a8_on_both_pairs_no_longer_stops_a_campaign(self):
        for drift in (0.124, 0.134):
            found = self._judged(drift)
            assert found["gotit_steady"]["ok"] is True, drift

    def test_a_campaign_that_really_moves_still_stops(self):
        assert self._judged(0.40)["gotit_steady"]["ok"] is False

    def test_the_floor_is_above_every_drift_measured_on_a_sound_campaign(self):
        assert ri.GOTIT_FLOOR_MS > 0.134

    def test_a_noisy_campaign_is_still_judged_against_its_own_scatter(self):
        """The floor is a floor. Three times a wide scatter is still what a wide campaign gets."""
        assert self._judged(0.40, scatter=0.20)["gotit_steady"]["ok"] is True
        assert self._judged(0.70, scatter=0.20)["gotit_steady"]["ok"] is False

    def test_a_long_delay_is_still_judged_against_its_own_share(self):
        assert self._judged(0.40, added_ms=2.0)["gotit_steady"]["ok"] is True
        assert self._judged(0.60, added_ms=2.0)["gotit_steady"]["ok"] is False
