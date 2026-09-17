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
             baseline_added=None, client_line="CONFIG effective max_inflight=64 ack_stamp=callback"):
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
    row = {"key": "r001-s-a1",
           "params": params or {"backend": "kafka", "load_pct": 75, "delay_ms": delay_ms}}
    (run / "queue_row.json").write_text(json.dumps(row), encoding="utf-8")
    if problems is None:
        problems = [] if settings_ok else ["the base slice is 2800000 ns, not 1500000"]
    (run / "settings_after.json").write_text(json.dumps({"ok": settings_ok, "problems": problems}),
                                             encoding="utf-8")
    (run / "delay_measured.json").write_text(json.dumps(
        {"host_median_ms": 0.30, "receiver_median_ms": 0.30 + measured_added}), encoding="utf-8")
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
        assert recorded["delay_added_ms"] == pytest.approx(2.0)
        assert recorded["clock_offset_max_s"] == pytest.approx(0.00003)
        assert recorded["gotit_median_ms"] == pytest.approx(0.2)


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
        found = evaluate(make_run(tmp_path, gotit_ms=0.9), calibration=CAL)
        assert found["verdict"] == "stop"
        assert found["reasons"] == ["the got-it median moved 0.700 ms, more than 25% of the "
                                    "2.000 ms added"]


class TestRepeat:

    @pytest.mark.parametrize("change,fragment", [
        (dict(n=390), "290 messages were sent after the warm-up, fewer than 99% of the 300"),
        (dict(lose=10), "290 of the 300 messages sent after the warm-up arrived"),
        (dict(gap_ms=110.0), "sent at 9.09 a second against 10"),
        (dict(load=70.0), "the measured load was 70.0% against 75%"),
        (dict(settings_ok=False), "changed during the run: the base slice is 2800000 ns"),
        (dict(settings_ok=False, problems=[]), "sched_settings.py gave no reason"),
        (dict(measured_added=1.0), "ping measured 1.000 ms added against 2 ms set"),
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
        ("delay_measured.json", "the delay could not be checked")])
    def test_a_file_a_check_needs_is_missing(self, tmp_path, dropped, fragment):
        found = evaluate(make_run(tmp_path, drop=(dropped,)))
        assert found["verdict"] == "repeat" and any(fragment in r for r in found["reasons"])

    def test_a_delay_file_without_its_medians(self, tmp_path):
        run = make_run(tmp_path)
        with open(os.path.join(run, "delay_measured.json"), "w", encoding="utf-8") as fh:
            fh.write('{"host_median_ms": 0.3}')
        assert "lacks the two medians" in " ".join(evaluate(run)["reasons"])

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

    def test_send_times_all_at_one_instant_cannot_give_a_rate(self):
        check = ri.rate_check([START, START, START], RATE)
        assert not check["ok"] and "too few distinct send times" in check["why"]

    @pytest.mark.parametrize("rate,duration", [(0.0, 40.0), (10.0, 10.0)])
    def test_a_plan_that_cannot_be_checked_is_an_error(self, tmp_path, rate, duration):
        with pytest.raises(ValueError, match="positive rate"):
            ri.evaluate(make_run(tmp_path), rate, duration, WARMUP)


class TestTheZeroDelayBaseline:
    """On the second x86 pair the receiver's ping path was 0.4 ms faster than the host's with no
    delay at all, so every run read 0.4 ms short. Each run now measures that difference with no
    delay just before it, and the added delay is what lies beyond it, as the pilot measures it."""

    def test_a_path_offset_is_not_delay(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=0.0, measured_added=-0.43,
                                  baseline_added=-0.41))
        assert found["verdict"] == "count"
        assert found["recorded"]["delay_added_ms"] == pytest.approx(-0.02)

    def test_without_a_baseline_the_offset_counts_against_the_run(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=0.0, measured_added=-0.43))
        assert found["verdict"] == "repeat"
        assert "ping measured -0.430 ms added against 0 ms set" in found["reasons"]

    def test_a_delayed_run_is_measured_beyond_its_baseline(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=4.0, measured_added=3.60,
                                  baseline_added=-0.40))
        assert found["checks"]["delay"]["ok"]
        assert found["recorded"]["delay_added_ms"] == pytest.approx(4.0)

    def test_a_baseline_without_its_medians(self, tmp_path):
        run = make_run(tmp_path, baseline_added=0.0)
        with open(os.path.join(run, "delay_baseline.json"), "w", encoding="utf-8") as fh:
            fh.write('{"host_median_ms": 0.3}')
        assert "lacks the two medians" in " ".join(evaluate(run)["reasons"])


class TestTheGotItComparison:

    def test_a_steady_median_counts(self, tmp_path):
        found = evaluate(make_run(tmp_path), calibration=CAL)
        assert found["verdict"] == "count" and found["checks"]["gotit_steady"]["ok"]
        assert found["checks"]["gotit_steady"]["limit"] == "within 0.500 ms"

    def test_a_run_without_a_delay_is_not_compared(self, tmp_path):
        found = evaluate(make_run(tmp_path, delay_ms=0.0, measured_added=0.0), calibration=CAL)
        assert found["verdict"] == "count" and "gotit_steady" not in found["checks"]

    @pytest.mark.parametrize("calibration,change,fragment", [
        ({"calibration": {"redis": {}}}, {}, "no zero-delay got-it median for kafka at 75%"),
        ({"calibration": None}, {}, "no zero-delay got-it median"),
        ({"calibration": {"kafka": {"75": {"gotit_zero_median_ms": None}}}}, {},
         "no zero-delay got-it median"),
        (CAL, {"acks": False}, "the run recorded no got-it times"),
        (CAL, {"drop": ("delay_measured.json",)}, "the added delay was not measured")])
    def test_what_cannot_be_compared_is_a_repeat_not_a_stop(self, tmp_path, calibration, change,
                                                              fragment):
        found = evaluate(make_run(tmp_path, **change), calibration=calibration)
        assert found["verdict"] == "repeat" and not found["checks"]["gotit_compared"]["ok"]
        assert any(fragment in r for r in found["reasons"])


class TestTheClientSettings:
    """The paper's own settings (supplement, "Learned"); the Redis one was missing from the law
    campaign until plan v6, and this treatment failed silently three times in earlier work."""

    def test_redis_acknowledging_in_batches_of_200_counts(self, tmp_path):
        params = {"backend": "redis", "load_pct": 75, "delay_ms": 2.0}
        run = make_run(tmp_path, params=params,
                       client_line="CONFIG effective ack_batch=200 count=200 block_ms=1000")
        assert evaluate(run)["checks"]["client"] == {
            "ok": True, "value": 200, "limit": "ack_batch=200 in consumer.log", "why": ""}

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
        assert ri.delay_held_ms(run) is None
        assert evaluate(run)["recorded"]["delay_held_ms"] is None

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
        path = tmp_path / "calibration.json"
        path.write_text(json.dumps(CAL), encoding="utf-8")
        code, text = self.check(make_run(tmp_path, gotit_ms=0.9), "--calibration", str(path))
        assert code == 3 and "got-it median moved" in text

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
