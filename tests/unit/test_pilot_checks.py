"""Tests for scripts/pilot_checks.py, on run directories built to known answers."""
import csv
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import pilot_checks as pc  # noqa: E402

START = 1_789_000_000_000_000_000


def make_run(tmp_path, name, n=100, gap_ms=10.0, trip_ms=0.5, gotit_ms=0.2, acks=True,
             negative_trip_at=None):
    """A run whose every message has the same trip and got-it delay, sent gap_ms apart."""
    run = tmp_path / name
    run.mkdir()
    with (run / "producer.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_prod_send_ns", "t_broker_ack_ns"])
        for i in range(n):
            send = START + int(i * gap_ms * 1e6)
            w.writerow(["e%d" % i, send, send + int(gotit_ms * 1e6) if acks else "None"])
    with (run / "consumer_events.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["event_id", "t_consume_ns"])
        for i in range(n):
            send = START + int(i * gap_ms * 1e6)
            trip = -0.1 if i == negative_trip_at else trip_ms
            w.writerow(["e%d" % i, send + int(trip * 1e6)])
        w.writerow(["unmatched", START])
        w.writerow(["e0", ""])
    return str(run)


class TestSpans:

    def test_the_warm_up_is_left_out(self, tmp_path):
        run = make_run(tmp_path, "r", n=100, gap_ms=10.0)
        trip, gotit, measured = pc.spans(run, warmup_s=0.5)
        assert len(trip) == 50, "the first half second holds messages 0 to 49"
        assert trip[0] == pytest.approx(0.5) and gotit[0] == pytest.approx(0.2)
        assert measured[0] == pytest.approx(0.3)

    def test_a_producer_with_no_send_times(self, tmp_path):
        run = tmp_path / "r"
        run.mkdir()
        (run / "producer.csv").write_text("event_id,t_prod_send_ns,t_broker_ack_ns\ne1,,\n",
                                          encoding="utf-8")
        with pytest.raises(ValueError, match="no send times"):
            pc.spans(str(run))


class TestSummary:

    def test_a_late_got_it_note_is_a_negative_measured_span(self, tmp_path):
        s = pc.summarise(make_run(tmp_path, "r", trip_ms=0.5, gotit_ms=0.8), warmup_s=0)
        assert s["messages"] == 100 and s["trip_negative"] == 0
        assert s["measured_negative"] == 100 and s["measured_negative_rate"] == 1.0
        assert s["trip_median_ms"] == pytest.approx(0.5)

    def test_a_negative_trip_is_counted(self, tmp_path):
        s = pc.summarise(make_run(tmp_path, "r", negative_trip_at=70), warmup_s=0)
        assert s["trip_negative"] == 1

    def test_without_acknowledgements_there_is_no_got_it(self, tmp_path):
        s = pc.summarise(make_run(tmp_path, "r", acks=False), warmup_s=0)
        assert s["gotit_median_ms"] is None and s["measured_negative_rate"] is None
        assert s["gotit_p99_ms"] is None

    def test_the_got_it_tail_is_its_99th_percentile(self, tmp_path):
        """The session calibration watches the slowest acknowledgements as well as the median."""
        assert pc.summarise(make_run(tmp_path, "many"), warmup_s=0)["gotit_p99_ms"] == \
            pytest.approx(0.2)
        assert pc.summarise(make_run(tmp_path, "one", n=1), warmup_s=0)["gotit_p99_ms"] == \
            pytest.approx(0.2)

    def test_a_run_shorter_than_its_warm_up(self, tmp_path):
        with pytest.raises(ValueError, match="no message sent after the first 30 s"):
            pc.summarise(make_run(tmp_path, "r", n=10), warmup_s=30)


class TestCompare:

    def summaries(self, tmp_path, **step):
        base = [pc.summarise(make_run(tmp_path, "b%d" % i), warmup_s=0) for i in range(2)]
        moved = [pc.summarise(make_run(tmp_path, "s", **step), warmup_s=0)]
        return base, moved

    def test_a_delay_that_reached_the_receiver_alone(self, tmp_path):
        report = pc.compare(*self.summaries(tmp_path, trip_ms=2.5), added_ms=2.0)
        assert report["ok"] and report["trip_shift_ms"] == pytest.approx(2.0)

    def test_a_delay_that_reached_the_got_it_reply(self, tmp_path):
        report = pc.compare(*self.summaries(tmp_path, trip_ms=2.5, gotit_ms=2.2), added_ms=2.0)
        assert not report["ok"] and not report["gotit_unchanged"]

    def test_a_delay_that_did_not_arrive(self, tmp_path):
        report = pc.compare(*self.summaries(tmp_path, trip_ms=0.5), added_ms=2.0)
        assert not report["ok"] and not report["trip_moved_by_the_delay"]

    def test_a_negative_trip_fails_the_check_whatever_the_medians_say(self, tmp_path):
        report = pc.compare(*self.summaries(tmp_path, trip_ms=2.5, negative_trip_at=3),
                            added_ms=2.0)
        assert not report["ok"] and report["trip_negative_total"] == 1

    def test_no_got_it_values_at_all(self, tmp_path):
        base, step = self.summaries(tmp_path, acks=False)
        with pytest.raises(ValueError, match="no gotit_median_ms"):
            pc.compare(step, step, added_ms=2.0)


def write_cell(tmp_path, runs):
    cell = tmp_path / "cell"
    (cell / "concurrency_x").mkdir(parents=True)
    listing = tmp_path / "runs.txt"
    listing.write_text("\n".join(runs) + "\n\n", encoding="utf-8")
    (cell / "concurrency_x" / "x_summary.json").write_text(
        json.dumps({"run_list_file": str(listing)}), encoding="utf-8")
    return str(cell)


class TestListing:

    def test_runs_come_from_the_invocations_own_list(self, tmp_path):
        cell = write_cell(tmp_path, ["runs/c_kafka_feed1_rep1", "runs/c_redis_feed1_rep1"])
        assert pc.runs_in(cell) == ["runs/c_kafka_feed1_rep1", "runs/c_redis_feed1_rep1"]
        assert pc.runs_in(cell, "redis") == ["runs/c_redis_feed1_rep1"]


def write_table(tmp_path, rows):
    path = tmp_path / "stamping_priority.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["level", "ratio", "disjoint", "confounded"])
        w.writeheader()
        w.writerows(rows)
    return str(path)


class TestGoFirst:

    def test_a_clean_cut_at_every_level(self, tmp_path):
        result = pc.go_first(write_table(tmp_path, [
            {"level": "l75", "ratio": "0.05", "disjoint": "True", "confounded": "False"},
            {"level": "l88", "ratio": "0.0", "disjoint": "True", "confounded": "False"}]))
        assert result["ok"] and "disjoint" in result["levels"][0]["why"]

    @pytest.mark.parametrize("row,fragment", [
        ({"ratio": "0.05", "disjoint": "False", "confounded": "False"}, "overlapping"),
        ({"ratio": "0.5", "disjoint": "True", "confounded": "False"}, "at most 0.2000"),
        ({"ratio": "", "disjoint": "", "confounded": "True"}, "manipulation check failed"),
        ({"ratio": "None", "disjoint": "", "confounded": "False"}, "nothing to cut")])
    def test_anything_less_than_a_clean_cut_fails(self, tmp_path, row, fragment):
        result = pc.go_first(write_table(tmp_path, [dict(row, level="l75")]))
        assert not result["ok"] and fragment in result["levels"][0]["why"]

    def test_an_empty_table(self, tmp_path):
        with pytest.raises(ValueError, match="no load levels"):
            pc.go_first(write_table(tmp_path, []))


class TestMain:

    @staticmethod
    def run(argv):
        out = io.StringIO()
        return pc.main(argv, out=out), out.getvalue()

    def test_run(self, tmp_path):
        assert self.run(["run", make_run(tmp_path, "a"), "--warmup-s", "0"])[0] == 0
        code, text = self.run(["run", make_run(tmp_path, "b", negative_trip_at=5),
                               "--warmup-s", "0"])
        assert code == 1 and json.loads(text)["trip_negative"] == 1

    def test_compare(self, tmp_path):
        base = make_run(tmp_path, "base")
        step = make_run(tmp_path, "step", trip_ms=2.5)
        argv = ["compare", "--warmup-s", "0", "--baseline", base, "--step", step, "--added-ms"]
        assert self.run(argv + ["2.0"])[0] == 0
        assert self.run(argv + ["1.0"])[0] == 1

    def test_list_and_go_first(self, tmp_path):
        code, text = self.run(["list", "--out-dir", write_cell(tmp_path, ["runs/k_kafka_1"])])
        assert code == 0 and text == "runs/k_kafka_1\n"
        table = write_table(tmp_path, [{"level": "l75", "ratio": "0.1", "disjoint": "True",
                                        "confounded": "False"}])
        assert self.run(["go-first", "--table", table])[0] == 0
        assert self.run(["go-first", "--table", table, "--factor", "20"])[0] == 1

    def test_a_missing_run_is_an_error_line(self, tmp_path):
        code, text = self.run(["run", str(tmp_path / "absent")])
        assert code == 2 and text.startswith("ERROR:")


PASSING_VERDICTS = [
    ("settings", "kept", "yes", "1500000 ns still set after 60 s"),
    ("settings", "restored", "yes", "2800000 ns"),
    ("network", "0.5 ms", "yes", "measured 0.515 ms"),
    ("network", "2.0 ms", "yes", "measured 2.03 ms"),
    ("paths", "no delay", "yes", "receiver minus host 0.020 ms"),
    ("harness", "kafka", "no", "see harness_verify_kafka.json"),
    ("go-first", "75%", "yes", "at least five-fold with disjoint intervals")]
CLEAN_REPORTS = {"kafka": json.dumps({"trip_negative_total": 0, "ok": False}),
                 "redis": json.dumps({"trip_negative_total": 0, "ok": False})}
STEADY_LOADS = {"harness_1_d0": ["0.75", "0.76"], "harness_2_d2.0": ["0.74", "0.755"],
                "harness_3_d0": ["0.752"]}


def write_pilot(tmp_path, verdicts=PASSING_VERDICTS, reports=CLEAN_REPORTS, loads=STEADY_LOADS):
    """A pilot's output: its verdicts, one receiver-only report per backend, each cell's load."""
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    with (pilot / "verdicts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["check", "step", "ok", "detail"])
        w.writerows(verdicts)
    for backend, text in reports.items():
        (pilot / ("harness_verify_%s.json" % backend)).write_text(text, encoding="utf-8")
    for cell, rows in loads.items():
        (pilot / cell).mkdir()
        with (pilot / cell / "utilisation.csv").open("w", newline="", encoding="utf-8") as fh:
            fh.write(rows if isinstance(rows, str) else
                     "t_wall,rho\n" + "".join("%d,%s\n" % (i, v) for i, v in enumerate(rows)))
    return str(pilot)


def zero_readings(folder, pairs):
    for n, (host, receiver) in enumerate(pairs, 1):
        (folder / ("net_zero%d.json" % n)).write_text(json.dumps(
            {"host_median_ms": host, "receiver_median_ms": receiver}), encoding="utf-8")


class TestThePathsAgree:

    def test_the_median_of_the_zero_delay_readings_is_held_to_the_limit(self, tmp_path):
        zero_readings(tmp_path, [(0.94, 0.99), (0.95, 1.00), (0.93, 0.95)])
        result = pc.paths(str(tmp_path))
        assert result["ok"] and result["median_difference_ms"] == pytest.approx(0.05)
        assert result["files"] == ["net_zero1.json", "net_zero2.json", "net_zero3.json"]

    def test_the_second_pairs_paths_of_16_september_fail(self, tmp_path):
        zero_readings(tmp_path, [(1.28, 0.84), (1.20, 0.82), (1.30, 0.86)])
        result = pc.paths(str(tmp_path))
        assert not result["ok"] and result["median_difference_ms"] == pytest.approx(-0.44)

    def test_one_odd_reading_does_not_decide(self, tmp_path):
        """The Arm pilot's single zero-delay reading was 0.11 ms off its usual difference."""
        zero_readings(tmp_path, [(0.38, 0.39), (0.535, 0.2), (0.40, 0.41)])
        assert pc.paths(str(tmp_path))["median_difference_ms"] == pytest.approx(0.01)

    def test_a_pilot_without_zero_delay_readings(self, tmp_path):
        with pytest.raises(ValueError, match="no zero-delay reading"):
            pc.paths(str(tmp_path))

    def test_from_the_command_line(self, tmp_path):
        zero_readings(tmp_path, [(1.28, 0.84)])
        code, text = TestMain.run(["paths", "--pilot-dir", str(tmp_path)])
        assert code == 1 and json.loads(text)["limit_ms"] == 0.25
        assert TestMain.run(["paths", "--pilot-dir", str(tmp_path), "--limit-ms", "0.5"])[0] == 0
        assert TestMain.run(["paths", "--pilot-dir", str(tmp_path / "none")])[0] == 2


class TestShakedown:

    def test_a_pair_passes_although_its_trip_is_not_one_for_one(self, tmp_path):
        """The first pilot's harness verdict was no for exactly that reason; C0 judges it now."""
        result = pc.shakedown(write_pilot(tmp_path), 75)
        assert result["ok"], result
        assert result["checks"]["load"]["detail"] == (
            "harness_1_d0 75.5%, harness_2_d2.0 74.8%, harness_3_d0 75.2%")
        assert result["go_first_recorded"] == "75% yes (at least five-fold with disjoint intervals)"

    def test_a_setting_that_did_not_hold(self, tmp_path):
        verdicts = [("settings", "kept", "no", "see settings_after_60s.json")] + PASSING_VERDICTS[2:]
        result = pc.shakedown(write_pilot(tmp_path, verdicts=verdicts), 75)
        assert not result["ok"] and not result["checks"]["settings"]["ok"]
        assert result["checks"]["network"]["ok"]

    def test_a_check_the_pilot_never_wrote(self, tmp_path):
        result = pc.shakedown(write_pilot(tmp_path, verdicts=PASSING_VERDICTS[:2]), 75)
        assert result["checks"]["network"] == {
            "ok": False, "detail": "the pilot wrote no network verdict"}
        assert result["go_first_recorded"] == "the pilot wrote no go-first verdict"

    @pytest.mark.parametrize("reports,detail", [
        (dict(CLEAN_REPORTS, kafka=json.dumps({"trip_negative_total": 2})), "2 negative trip(s)"),
        (dict(CLEAN_REPORTS, redis="ERROR: no gotit_median_ms in runs/x"),
         "0 negative trip(s); unreadable: harness_verify_redis.json"),
        ({"kafka": CLEAN_REPORTS["kafka"]},
         "0 negative trip(s); unreadable: harness_verify_redis.json"),
        (dict(CLEAN_REPORTS, kafka=json.dumps({"ok": True})),
         "0 negative trip(s); unreadable: harness_verify_kafka.json")])
    def test_a_negative_trip_or_a_report_that_cannot_be_read(self, tmp_path, reports, detail):
        result = pc.shakedown(write_pilot(tmp_path, reports=reports), 75)
        assert not result["ok"]
        assert result["checks"]["never_negative"] == {"ok": False, "detail": detail}

    @pytest.mark.parametrize("loads,detail", [
        ({"harness_1_d0": ["0.70"]}, "harness_1_d0 70.0%"),
        ({"harness_1_d0": "t_wall,rho\n0,x\n1,\n2\n"}, "harness_1_d0 no samples"),
        ({"harness_1_d0": "t_wall,cpu\n0,0.75\n"}, "harness_1_d0 no samples"),
        ({}, "no harness cell recorded its load")])
    def test_a_load_off_its_setting_or_never_recorded(self, tmp_path, loads, detail):
        result = pc.shakedown(write_pilot(tmp_path, loads=loads), 75)
        assert not result["ok"]
        assert result["checks"]["load"] == {"ok": False, "detail": detail}

    def test_a_later_session_asks_for_the_network_checks_alone(self, tmp_path):
        """Its pilot runs the network part only, so it has no harness cells to read."""
        pilot = write_pilot(tmp_path, reports={}, loads={})
        assert not pc.shakedown(pilot, 75)["ok"]
        result = pc.shakedown(pilot, 75, wanted=("network", "paths"))
        assert result["ok"] and sorted(result["checks"]) == ["network", "paths"]

    @pytest.mark.parametrize("wanted", [(), ("network", "tick")])
    def test_a_shakedown_asks_for_checks_it_knows(self, tmp_path, wanted):
        with pytest.raises(ValueError, match="a shakedown asks for some of"):
            pc.shakedown(write_pilot(tmp_path), 75, wanted=wanted)

    def test_paths_that_differ_with_no_delay_fail(self, tmp_path):
        """The second x86 pair's paths differed by 0.44 ms on 16 September."""
        verdicts = PASSING_VERDICTS[:4] + [("paths", "no delay", "no", "see net_paths.json")]
        result = pc.shakedown(write_pilot(tmp_path, verdicts=verdicts), 75)
        assert not result["ok"] and not result["checks"]["paths"]["ok"]

    def test_from_the_command_line(self, tmp_path):
        run = TestMain.run
        pilot = write_pilot(tmp_path)
        code, text = run(["shakedown", "--pilot-dir", pilot, "--checks", "network, paths"])
        assert code == 0 and sorted(json.loads(text)["checks"]) == ["network", "paths"]
        code, text = run(["shakedown", "--pilot-dir", pilot])
        assert code == 0 and json.loads(text)["ok"]
        assert run(["shakedown", "--pilot-dir", pilot, "--load-pct", "88"])[0] == 1
        assert run(["shakedown", "--pilot-dir", pilot, "--load-pct", "88",
                    "--load-points", "15"])[0] == 0
        code, text = run(["shakedown", "--pilot-dir", str(tmp_path / "absent")])
        assert code == 2 and text.startswith("ERROR:")
