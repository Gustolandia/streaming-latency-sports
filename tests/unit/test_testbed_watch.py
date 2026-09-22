"""Tests for scripts/testbed_watch.py.

The watch reads machines it never changes, so everything here runs against recorded probe
output: what each flag fires on, what it stays quiet about, and that a machine which does not
answer is reported with what Azure says about it rather than silently left out.
"""
import datetime
import io
import json
import pathlib
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import azure_testbed  # noqa: E402
import testbed_watch as tw  # noqa: E402

BUSY = "cpu1=cpu  100 0 100 800 0 0 0 0 0 0\ncpu2=cpu  800 0 200 900 0 0 0 10 0 0\n"
QUIET = "cpu1=cpu  100 0 100 800 0 0 0 0 0 0\ncpu2=cpu  102 0 101 1800 0 0 0 0 0 0\n"
MACHINE = ("ncpu=8\nmem_total_kb=32000000\nmem_avail_kb=20000000\ndisk_pct=12\n"
           "clock_offset_s=0.000020\n")
RUN_OK = {"messages": 1200, "trip_negative": 0, "trip_median_ms": 0.42,
          "run_dir": "runs/concurrency_x_kafka_feed1_rep1"}
DRIVER_OK = BUSY + MACHINE + (
    "campaign=3\nstress=8\nnetns=1\nlog=./pilot.log\nlog_tail==== 3/5 harness ===\n"
    "log_age_s=40\nactivity_age_s=30\nfails=0\nverdict_no=0\nrun=%s\n" % json.dumps(RUN_OK))
BROKER_OK = BUSY + MACHINE + "docker=broker:running redis:running \n"
STAMP = datetime.datetime(2026, 9, 14, 23, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def a_ledger_of_its_own(tmp_path, monkeypatch):
    """No test reads or writes the repo's own spending ledger."""
    monkeypatch.setattr(tw.spend, "LEDGER", str(tmp_path / "spend.json"))


class Done:
    """What subprocess.run returns when the output is captured as bytes."""
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout.encode(), returncode, stderr.encode()


def fake_run(driver=DRIVER_OK, broker=BROKER_OK, seen=None):
    """Answers the driver's probe and the broker's (the one that goes through ProxyCommand)."""
    def run(argv, input, capture_output, timeout):
        assert isinstance(input, bytes) and b"\r" not in input, "the script must reach bash as LF"
        if seen is not None:
            seen.append((argv, input.decode("utf-8")))
        answer = broker if any(a.startswith("ProxyCommand=") for a in argv) else driver
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, Done) else Done(answer)
    return run


def facts(text):
    return tw.parse(text)


@pytest.fixture
def hosts_file(tmp_path):
    path = tmp_path / "hosts.env"
    path.write_text("# written by azure_testbed.py\nBROKER_PRIV=10.1.1.21\nAZ_PROFILE=matched\n"
                    "DRIVER_NAME=sbl-az-drv\nDRIVER_PUBLIC=4.223.79.212\n\nnot a pair\n",
                    encoding="utf-8")
    return str(path)


class TestHostsAndSsh:

    def test_hosts_env_is_read_and_its_noise_ignored(self, hosts_file):
        hosts = tw.read_hosts(hosts_file)
        assert hosts["DRIVER_PUBLIC"] == "4.223.79.212" and hosts["AZ_PROFILE"] == "matched"

    def test_a_hosts_file_without_the_machines_is_refused(self, tmp_path):
        path = tmp_path / "hosts.env"
        path.write_text("BROKER_PRIV=10.1.1.21\n", encoding="utf-8")
        with pytest.raises(ValueError, match="lacks DRIVER_PUBLIC, AZ_PROFILE"):
            tw.read_hosts(str(path))

    def test_the_broker_is_reached_through_the_driver(self):
        direct = tw.ssh_argv("ssh", "k", "4.223.79.212")
        assert direct[-2:] == ["ubuntu@4.223.79.212", "bash -s"] and "BatchMode=yes" in direct
        jumped = tw.ssh_argv("ssh", "k", "10.1.1.21", jump="4.223.79.212")
        proxy = [a for a in jumped if a.startswith("ProxyCommand=")][0]
        assert proxy.endswith("-W %h:%p ubuntu@4.223.79.212")

    def test_a_windows_key_path_survives_the_shell_that_runs_the_jump(self):
        jumped = tw.ssh_argv(r"C:\Program\ssh.exe", r"C:\Users\me\.ssh\azure_sbl",
                             "10.1.1.21", jump="4.223.79.212")
        proxy = [a for a in jumped if a.startswith("ProxyCommand=")][0]
        assert proxy.startswith("ProxyCommand=C:/Program/ssh.exe -i C:/Users/me/.ssh/azure_sbl ")
        assert jumped[:3] == ["C:/Program/ssh.exe", "-i", "C:/Users/me/.ssh/azure_sbl"]
        assert "\\" not in " ".join(jumped)


class TestReading:

    def test_probe_lines_become_facts_and_runs(self):
        got = facts("a=1\nno pair here\nrun=%s\nrun=ERROR:nofile\nlog_tail==== x ===\n"
                    % json.dumps(RUN_OK))
        assert got["a"] == "1" and got["log_tail"] == "=== x ==="
        assert got["runs"] == [RUN_OK, {"unreadable": "ERROR:nofile"}]

    def test_probe_answers(self):
        assert tw.probe(fake_run(driver="a=1\n"), ["ssh"], "x")[0]["a"] == "1"

    @pytest.mark.parametrize("answer,fragment", [
        (OSError("no ssh"), "no ssh"),
        (subprocess.TimeoutExpired("ssh", 90), "timed out"),
        (Done("", 255, "banner\nPermission denied (publickey)."), "Permission denied"),
        (Done("", 255, ""), "ssh exited with 255")])
    def test_a_machine_that_cannot_be_read_says_why(self, answer, fragment):
        got, why = tw.probe(fake_run(driver=answer), ["ssh"], "x")
        assert got is None and fragment in why

    def test_cpu_busy_and_steal(self):
        busy, steal = tw.cpu_usage("cpu  100 0 100 800 0 0 0 0", "cpu  800 0 200 900 0 0 0 10")
        assert busy == pytest.approx(100 * 810 / 910) and steal == pytest.approx(100 * 10 / 910)

    @pytest.mark.parametrize("first,second", [
        (None, "cpu 1 2 3 4 5 6 7 8"), ("cpu a b c", "cpu 1 2 3"),
        ("cpu 1 1 1 1 1 1 1 1", "cpu 1 1 1 1 1 1 1 1"), ("cpu 1 2 3", "cpu 4 5 6")])
    def test_unusable_cpu_lines_give_no_number(self, first, second):
        assert tw.cpu_usage(first, second) == (None, None)

    def test_number(self):
        assert tw.number({"a": "3"}, "a", int) == 3
        assert tw.number({}, "a") is None
        assert tw.number({"a": "x"}, "a") is None
        assert tw.number({"a": None}, "a") is None


class TestFlags:

    def test_a_healthy_campaign_raises_nothing(self):
        assert tw.evaluate(facts(DRIVER_OK), facts(BROKER_OK), previous_fails=0) == []

    def test_machines_running_with_nothing_to_do_are_idle(self):
        quiet = facts(QUIET + MACHINE + "campaign=0\nnetns=1\n")
        assert [f[0] for f in tw.evaluate(quiet, None)] == ["IDLE"]
        blind = facts(MACHINE + "campaign=0\nnetns=1\n")
        assert [f[0] for f in tw.evaluate(blind, None)] == ["IDLE"]

    def test_a_busy_machine_without_a_campaign_is_not_idle(self):
        assert tw.evaluate(facts(BUSY + MACHINE + "campaign=0\nnetns=1\n"), None) == []

    def test_a_quiet_machine_with_work_in_hand_is_not_idle(self):
        """A chain waiting on a calibration has no run going and is not idle.

        Deallocating such a pair destroys the thing chain.sh exists to protect, and the pair
        would be quiet: the chain sleeps between looks.
        """
        armed = facts(QUIET + MACHINE + "campaign=0\nqueued=1\nnetns=1\n")
        assert [f[0] for f in tw.evaluate(armed, None)] == []

    def test_work_in_hand_is_not_a_stall(self, ):
        """The rounds rule writes nothing for hours, and that is not a campaign going wrong.

        Alerting every five minutes through a simulation is how a real stall comes to be
        ignored, so the stall alert is about runs being made and this is not.
        """
        long_sim = facts(QUIET + MACHINE
                         + "campaign=0\nqueued=1\nactivity_age_s=5000\nnetns=1\n")
        assert tw.evaluate(long_sim, None) == []

    def test_a_campaign_that_stops_making_runs_is_still_a_stall(self):
        stalled = facts(QUIET + MACHINE
                        + "campaign=1\nqueued=0\nactivity_age_s=5000\nnetns=1\n")
        assert any("stuck" in f[1] for f in tw.evaluate(stalled, None))

    @pytest.mark.parametrize("what", ["cloud/azure/chain.sh", "cloud/azure/stage1.sh",
                                      "cloud/azure/queue.sh", "rounds_rule.py"])
    def test_the_probe_counts_work_that_is_not_yet_a_run(self, what):
        """Named here so the list cannot quietly lose one of them again.

        The queue is the one that matters most: it is idle by design between jobs, having just
        rebooted the machine or being a minute from its next look, and a pair deallocated in
        that gap loses a list of work with nobody left watching it.
        """
        assert what in tw.DRIVER_PROBE
        assert what not in tw.DRIVER_PROBE.split('echo "queued=')[0], \
            "counted as work in hand, not as a campaign making runs"

    @pytest.mark.parametrize("extra,level,fragment", [
        ("activity_age_s=1500\n", "ALERT", "nothing has changed for 25 minutes"),
        ("verdict_no=2\n", "ALERT", "failed 2 settings or network check(s)"),
        ("netns=0\n", "WARN", "namespace is gone")])
    def test_campaign_trouble(self, extra, level, fragment):
        found = tw.evaluate(facts(DRIVER_OK + extra), facts(BROKER_OK), previous_fails=0)
        assert (level, ) == tuple(f[0] for f in found if fragment in f[1])

    def test_stress_without_load_is_reported(self):
        starved = facts(QUIET + MACHINE + "campaign=1\nstress=8\nnetns=1\n")
        assert any(f[0] == "WARN" and "only 0% busy" in f[1]
                   for f in tw.evaluate(starved, facts(BROKER_OK)))

    def test_failures_count_from_the_previous_look_not_from_the_start(self):
        failing = facts(DRIVER_OK + "fails=3\n")
        assert any("2 new failed trials" in f[1] for f in tw.evaluate(failing, None, 1))
        assert not any("failed" in f[1] for f in tw.evaluate(failing, None, None))

    @pytest.mark.parametrize("run,level,fragment", [
        (dict(RUN_OK, trip_negative=3), "ALERT", "3 messages that arrived before they were sent"),
        (dict(RUN_OK, trip_median_ms=80.0), "ALERT", "median trip of 80.0 ms"),
        (dict(RUN_OK, messages=20, run_dir="runs/law_x"), "ALERT", "only 20 messages"),
        ({"unreadable": "ERROR:runs/x"}, "WARN", "could not read")])
    def test_numbers_no_working_harness_produces(self, run, level, fragment):
        found = tw.run_flags([run])
        assert len(found) == 1 and found[0][0] == level and fragment in found[0][1]

    @pytest.mark.parametrize("override,level,fragment", [
        ("disk_pct=85\n", "ALERT", "disk is 85% full"),
        ("mem_avail_kb=1000000\n", "ALERT", "3% of its memory free"),
        ("cpu2=cpu  800 0 200 900 0 0 0 200 0 0\n", "WARN", "another tenant took"),
        ("clock_offset_s=0.002\n", "WARN", "2.00 ms off")])
    def test_machine_health(self, override, level, fragment):
        found = tw.machine_flags("broker", facts(BROKER_OK + override))
        assert [(f[0], fragment in f[1]) for f in found] == [(level, True)]

    def test_a_replay_run_may_carry_few_messages(self):
        """The pilot replays real matches, whose feeds hold 71 to 148 events."""
        assert tw.run_flags([dict(RUN_OK, messages=71)]) == []

    def test_an_unreadable_clock_or_memory_is_not_a_flag(self):
        assert tw.machine_flags("broker", facts(BUSY + "disk_pct=10\n")) == []

    def test_brokers_that_are_not_running(self):
        down = facts(BROKER_OK + "docker=broker:exited redis:running\n")
        assert [f[1] for f in tw.evaluate(None, down)] == [
            "brokers: broker is not running on the broker"]
        assert len(tw.evaluate(None, facts(BUSY + MACHINE))) == 2

    def test_nothing_to_read_raises_nothing(self):
        assert tw.evaluate(None, None) == []


class TestAzure:

    def test_power_states(self):
        listing = json.dumps([{"name": "sbl-az-drv", "powerState": "VM running"}])
        assert tw.power_states(lambda a: (0, listing, ""), "sbl-az") == {
            "sbl-az-drv": "VM running"}

    @pytest.mark.parametrize("runner", [
        lambda a: (1, "", "denied"), lambda a: (0, "not json", "")])
    def test_power_states_that_cannot_be_read(self, runner):
        assert tw.power_states(runner, "sbl-az") == {}

    def test_power_states_without_the_cli(self):
        def missing(args):
            raise azure_testbed.AzNotFound("no az")
        assert tw.power_states(missing, "sbl-az") == {}


class TestCycle:

    def test_a_look_at_a_healthy_testbed(self):
        seen, state = [], {}
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "4.223.79.212", "BROKER_PRIV": "10.1.1.21",
                 "AZ_PROFILE": "matched"}
        lines, flags = tw.cycle(hosts, spec, "k", "ssh", fake_run(seen=seen), None, state,
                                "stamp", window_min=15)
        assert flags == [] and lines[-1] == "  all clear"
        assert "about $%.2f an hour" % (0.097 + 0.388) in lines[0]
        assert "runs finished in the last 15 min: 1" in "\n".join(lines)
        assert "-mmin -15" in seen[0][1] and "@WINDOW@" not in seen[0][1]
        assert state["fails"] == 0

    def test_machines_that_do_not_answer_are_reported_with_azures_word(self):
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "4.223.79.212", "BROKER_PRIV": "10.1.1.21",
                 "AZ_PROFILE": "matched"}
        listing = json.dumps([{"name": "sbl-az-drv", "powerState": "VM running"}])
        lines, flags = tw.cycle(hosts, spec, "k", "ssh",
                                fake_run(driver=Done("", 255, "timed out"),
                                         broker=Done("", 255, "")),
                                lambda a: (0, listing, ""), {}, "stamp")
        text = "\n".join(lines)
        assert "the driver does not answer over SSH (timed out); Azure says: VM running" in text
        assert "the broker does not answer over SSH (ssh exited with 255)\n" in text + "\n"

    def test_a_pair_stopped_because_its_work_is_done_is_not_an_alert(self):
        """A stopped pair is the state we want it in. Alerting on it every three minutes would
        bury the alerts that mean something."""
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "51.12.89.77", "BROKER_PRIV": "10.1.1.41",
                 "AZ_PROFILE": "arm"}
        listing = json.dumps([{"name": "sbl-az-arm-drv", "powerState": "VM deallocated"},
                              {"name": "sbl-az-arm-b1", "powerState": "VM deallocated"}])
        lines, flags = tw.cycle(hosts, spec, "k", "ssh",
                                fake_run(driver=Done("", 255, "timed out"),
                                         broker=Done("", 255, "timed out")),
                                lambda a: (0, listing, ""), {}, "stamp")
        assert [level for level, _ in flags] == ["INFO", "INFO"]
        assert "stopped: the driver is deallocated, so it is not billing" in "\n".join(lines)

    def test_one_machine_down_is_flagged_and_the_other_still_summarised(self):
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "4.223.79.212", "BROKER_PRIV": "10.1.1.21",
                 "AZ_PROFILE": "matched"}
        lines, flags = tw.cycle(hosts, spec, "k", "ssh",
                                fake_run(broker=Done("", 255, "Connection refused")),
                                lambda a: (1, "", ""), {}, "stamp")
        assert [f[1] for f in flags] == [
            "unreachable: the broker does not answer over SSH (Connection refused)"]
        assert any(line.startswith("  driver 4.223.79.212:") for line in lines)

    def test_the_summary_of_a_machine_with_little_to_say(self):
        line = tw.summary("broker", "10.1.1.21", facts("docker= \n"))
        assert "CPU ?" in line and "containers none" in line and "memory" not in line

    @pytest.mark.parametrize("state,shown", [
        ("campaign=1\nqueued=0\n", "campaign running"),
        ("campaign=0\nqueued=1\n", "campaign queued"),
        ("campaign=0\nqueued=0\n", "campaign none")])
    def test_a_pair_with_work_in_hand_does_not_read_as_doing_nothing(self, state, shown):
        """"none" on a pair simulating the rounds for the campaign it is about to start reads as
        "nothing is happening here", and the person reading it is the one who would then stop the
        pair by hand."""
        assert shown in tw.summary("driver", "10.1.1.10", facts(state))


class TestMain:

    def run(self, argv, **kw):
        out = io.StringIO()
        code = tw.main(argv, out=out, clock=lambda: STAMP, **kw)
        return code, out.getvalue()

    def test_one_clean_look(self, hosts_file, tmp_path):
        code, text = self.run(["--hosts", hosts_file, "--log-dir", str(tmp_path / "log"),
                               "--once"], run=fake_run())
        assert code == 0 and "all clear" in text
        assert "all clear" in (tmp_path / "log" / "watch_20260914.log").read_text(encoding="utf-8")

    def test_one_look_with_an_alert_exits_one(self, hosts_file, tmp_path):
        down = BROKER_OK + "docker=broker:exited redis:running\n"
        code, text = self.run(["--hosts", hosts_file, "--log-dir", str(tmp_path), "--once"],
                              run=fake_run(broker=down), runner=lambda a: (1, "", ""))
        assert code == 1 and "ALERT brokers" in text

    def test_repeated_looks_sleep_between_them(self, hosts_file, tmp_path):
        naps = []
        code, text = self.run(["--hosts", hosts_file, "--log-dir", str(tmp_path), "--cycles",
                               "2", "--interval", "7"], run=fake_run(), sleep=naps.append)
        assert code == 0 and naps == [7] and text.count("profile matched") == 2

    def test_ctrl_c_stops_the_watch_quietly(self, hosts_file, tmp_path):
        def interrupt(seconds):
            raise KeyboardInterrupt
        code, text = self.run(["--hosts", hosts_file, "--log-dir", str(tmp_path)],
                              run=fake_run(), sleep=interrupt)
        assert code == 0 and text.rstrip().endswith("stopped")

    def test_a_missing_hosts_file_or_testbed_file_is_an_error_line(self, hosts_file, tmp_path):
        assert self.run(["--hosts", str(tmp_path / "none.env")])[0] == 2
        code, text = self.run(["--hosts", hosts_file, "--spec", str(tmp_path / "none.json")])
        assert code == 2 and text.startswith("ERROR:")

    @staticmethod
    def lanes(tmp_path):
        a = tmp_path / "hosts_a.env"
        a.write_text("BROKER_PRIV=10.1.1.21\nAZ_PROFILE=matched\nDRIVER_PUBLIC=4.223.79.212\n",
                     encoding="utf-8")
        b = tmp_path / "hosts_b.env"
        b.write_text("BROKER_PRIV=10.2.1.21\nAZ_PROFILE=matched-b\nDRIVER_PUBLIC=20.0.0.10\n",
                     encoding="utf-8")
        return ["--lane", "a=%s" % a, "--lane", "b=%s" % b]

    def test_two_lanes_in_one_look_with_a_status_file(self, tmp_path):
        driver = DRIVER_OK + "commit=abc1234\nqueue=runs/azure/queues/a1.csv\n"
        code, text = self.run(self.lanes(tmp_path) + ["--log-dir", str(tmp_path / "log"),
                                                      "--once"],
                              run=fake_run(driver=driver), runner=lambda a: (1, "", ""))
        assert code == 1, "one queue on two pairs is an alert"
        assert "lane a, profile matched," in text and "lane b, profile matched-b," in text
        assert "pairs: lanes a and b both run runs/azure/queues/a1.csv" in text
        with open(tmp_path / "log" / "status.json", encoding="utf-8") as fh:
            status = json.load(fh)
        assert sorted(status["lanes"]) == ["a", "b"] and status["lanes"]["b"]["commit"] == "abc1234"
        assert status["lanes"]["a"]["profile"] == "matched" and status["pairs"][0][0] == "ALERT"

    def test_an_idle_lane_is_stopped_after_the_minutes_given(self, tmp_path):
        quiet = QUIET + MACHINE + "campaign=0\nnetns=1\n"
        times = iter([STAMP, STAMP + datetime.timedelta(minutes=25)])
        calls, out = [], io.StringIO()
        code = tw.main(self.lanes(tmp_path)[:2] + ["--log-dir", str(tmp_path), "--cycles", "2",
                                                   "--stop-idle-min", "20"],
                       run=fake_run(driver=quiet), runner=lambda a: calls.append(a) or (0, "", ""),
                       sleep=lambda seconds: None, clock=lambda: next(times), out=out)
        assert code == 0 and "stopped: lane a had been idle for 25 minutes" in out.getvalue()
        assert [c[1] for c in calls] == ["deallocate", "deallocate"]

    @pytest.mark.parametrize("lane", ["nohosts", "=x.env", "a="])
    def test_a_lane_that_is_not_name_equals_file(self, tmp_path, lane):
        code, text = self.run(["--lane", lane, "--log-dir", str(tmp_path)])
        assert code == 2 and "a lane is NAME=HOSTS_FILE" in text

    def test_lane_names_that_repeat_or_a_profile_the_file_lacks(self, tmp_path):
        good = tmp_path / "h.env"
        good.write_text("BROKER_PRIV=1\nAZ_PROFILE=matched\nDRIVER_PUBLIC=2\n", encoding="utf-8")
        code, text = self.run(["--lane", "a=%s" % good, "--lane", "a=%s" % good])
        assert code == 2 and "lane names repeat" in text
        unknown = tmp_path / "g.env"
        unknown.write_text("BROKER_PRIV=1\nAZ_PROFILE=huge\nDRIVER_PUBLIC=2\n", encoding="utf-8")
        code, text = self.run(["--lane", "x=%s" % unknown])
        assert code == 2 and "no profile 'huge'" in text


class TestLanesAndVerdicts:

    def test_verdict_lines_are_read_and_flagged(self):
        got = facts("verdict=%s\nverdict=%s\nverdict=%s\nverdict=not json\n" % (
            json.dumps({"run_dir": "runs/law_a", "verdict": "stop",
                        "reasons": ["1 message(s) arrived before they were sent"]}),
            json.dumps({"run_dir": "runs/law_b", "verdict": "repeat",
                        "reasons": ["the measured load was 60.0% against 75%"]}),
            json.dumps({"run_dir": "runs/law_c", "verdict": "count", "reasons": []})))
        found = tw.verdict_flags(got["verdicts"])
        assert [f[0] for f in found] == ["ALERT", "WARN", "WARN"]
        assert found[0][1] == "stop: runs/law_a: 1 message(s) arrived before they were sent"
        assert found[1][1].startswith("repeat: runs/law_b will run again: the measured load")
        assert "could not read a run's integrity verdict (not json)" in found[2][1]

    def test_a_campaign_that_stopped_itself_or_finished(self):
        rule = "2026-09-16T10:00:00Z STOP_RULE: the last 3 attempts all failed"
        stopped = facts(QUIET + MACHINE + "campaign=0\nnetns=1\nstop_rule=%s\ncomplete=0\n" % rule)
        assert ("ALERT", "stopped: the campaign stopped itself (%s); find the cause before "
                "starting it again" % rule) in tw.evaluate(stopped, None)
        finished = facts(QUIET + MACHINE + "campaign=0\nnetns=1\nstop_rule=\ncomplete=1\n")
        assert [f[0] for f in tw.evaluate(finished, None)] == ["IDLE", "INFO"]
        running = facts(DRIVER_OK + "stop_rule=old STOP_RULE: x\ncomplete=1\n")
        assert tw.evaluate(running, facts(BROKER_OK), previous_fails=0) == [], (
            "a running campaign's old log lines are not news")

    def test_a_look_names_the_lane_its_commit_and_its_progress(self):
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "4.223.79.212", "BROKER_PRIV": "10.1.1.21",
                 "AZ_PROFILE": "matched"}
        driver = DRIVER_OK + ("commit=abc1234\nqueue=runs/azure/queues/a1.csv\n"
                              "progress=runs: queued 90, running 1, done 19, failed 1\n"
                              'timing={"done": 19, "runs": 110, "left": 91, "cycle_s": 166.0}\n')
        state = {}
        lines, _ = tw.cycle(hosts, spec, "k", "ssh", fake_run(driver=driver), None, state,
                            "stamp", lane="a")
        assert lines[0].startswith("stamp  lane a, profile matched,")
        assert lines[0].endswith(", commit abc1234")
        assert "queue runs/azure/queues/a1.csv: runs: queued 90" in "\n".join(lines)
        assert "queue: 19 of 110 done, 91 left at 166 s each, due" in "\n".join(lines)
        assert state["commit"] == "abc1234" and state["queue"] == "runs/azure/queues/a1.csv"

    def test_a_second_pair_is_read_in_its_own_group(self):
        spec = azure_testbed.load_spec()
        hosts = {"DRIVER_PUBLIC": "20.0.0.10", "BROKER_PRIV": "10.2.1.21",
                 "AZ_PROFILE": "matched-b"}
        asked = []

        def az(args):
            asked.append(args)
            return 0, json.dumps([{"name": "sbl-azb-drv", "powerState": "VM deallocated"}]), ""
        state = {"commit": "old", "queue": "q"}
        lines, _ = tw.cycle(hosts, spec, "k", "ssh",
                            fake_run(driver=Done("", 255, "timed out"), broker=Done("", 255, "")),
                            az, state, "stamp", lane="b")
        assert "about $%.2f an hour" % (0.388 + 0.097) in lines[0]
        assert asked[0][-3:] == ["sbl-azb", "--output", "json"]
        assert "stopped: the driver is deallocated" in "\n".join(lines), \
            "the group's own listing was read, and a stopped machine is not a fault"
        assert state["commit"] is None and state["queue"] is None

    def test_pairs_that_share_a_queue_or_differ_in_code(self):
        states = {"a": {"queue": "runs/azure/queues/a1.csv", "commit": "abc1234"},
                  "b": {"queue": "runs/azure/queues/a1.csv", "commit": "def5678"},
                  "arm": {"queue": None, "commit": None}}
        found = tw.cross_lane_flags(states)
        assert found[0] == ("ALERT", "pairs: lanes a and b both run runs/azure/queues/a1.csv; a "
                            "campaign runs on one pair")
        assert found[1][0] == "WARN" and "(abc1234, def5678)" in found[1][1]
        same = {"a": {"queue": "x", "commit": "c"}, "b": {"queue": "y", "commit": "c"}}
        assert tw.cross_lane_flags(same) == []

    def test_idle_machines_are_stopped_only_after_the_minutes_given(self):
        spec = azure_testbed.load_spec()
        hosts = {"AZ_PROFILE": "matched-b"}
        calls, state = [], {}

        def runner(args):
            calls.append(args)
            return 0, "", ""
        assert tw.stop_idle("b", hosts, spec, runner, state, True, STAMP, 20) == []
        later = STAMP + datetime.timedelta(minutes=19)
        assert tw.stop_idle("b", hosts, spec, runner, state, True, later, 20) == []
        later = STAMP + datetime.timedelta(minutes=21)
        assert tw.stop_idle("b", hosts, spec, runner, state, True, later, 20) == [
            ("INFO", "stopped: lane b had been idle for 21 minutes; its machines were deallocated")]
        assert [c[:2] + [c[3]] for c in calls] == [["vm", "deallocate", "sbl-azb"],
                                                   ["vm", "deallocate", "sbl-azb"]]
        assert "idle_since" not in state

    def test_a_lane_busy_again_starts_its_idle_time_over(self):
        state = {"idle_since": STAMP}
        assert tw.stop_idle("a", {}, None, None, state, False, STAMP, 20) == [] and state == {}

    def test_without_the_flag_idle_machines_are_only_reported(self):
        state = {}
        tw.stop_idle("a", {}, None, None, state, True, STAMP, 0)
        later = STAMP + datetime.timedelta(hours=5)
        assert tw.stop_idle("a", {}, None, None, state, True, later, 0) == []
        assert state == {"idle_since": STAMP}

    @pytest.mark.parametrize("answer,fragment", [
        ((1, "", "AuthorizationFailed"), "(AuthorizationFailed)"),
        (azure_testbed.AzNotFound("the Azure CLI (az) is not installed"), "not installed")])
    def test_stopping_that_fails_is_an_alert(self, answer, fragment):
        def runner(args):
            if isinstance(answer, Exception):
                raise answer
            return answer
        state = {"idle_since": STAMP}
        found = tw.stop_idle("a", {"AZ_PROFILE": "matched"}, azure_testbed.load_spec(), runner,
                             state, True, STAMP + datetime.timedelta(minutes=30), 20)
        assert found[0][0] == "ALERT" and fragment in found[0][1]
        assert "could not be stopped" in found[0][1]


class TestTimeItTakes:
    """Runs take the same time to the second, so a late run is not slow, it is wrong."""

    @staticmethod
    def driver(**timing):
        return {"timing": json.dumps(timing) if timing else "", "campaign": "1",
                "runs": [], "verdicts": [], "numbers": []}

    def test_the_queue_says_where_it_is_and_when_it_is_due(self):
        line = tw.due_line(self.driver(done=11, runs=56, left=45, cycle_s=166.0,
                                       run_key="r012-C0-kafka", run_age_s=95.0))
        assert "queue: 11 of 56 done, 45 left at 166 s each, due" in line
        assert "r012-C0-kafka running 1.6 min" in line

    def test_a_campaign_with_nothing_left_says_nothing(self):
        assert tw.due_line(self.driver(done=56, runs=56, left=0)) is None
        assert tw.due_line({"timing": ""}) is None

    def test_a_queue_it_could_not_read_says_nothing(self):
        assert tw.timing({"timing": "not json"}) == {}
        assert tw.timing({"timing": json.dumps({"unreadable": "OSError"})}) == {}

    def test_a_run_over_its_time_is_an_alert(self):
        found = tw.evaluate(self.driver(left=40, cycle_s=166.0, run_key="r012",
                                        run_age_s=600.0), None)
        assert any(kind == "ALERT" and "late: r012 has been running 10.0 minutes" in text
                   for kind, text in found)

    def test_a_run_inside_its_time_is_not(self):
        assert tw.late_run(self.driver(left=40, cycle_s=166.0, run_age_s=200.0)) is None

    def test_a_quick_campaign_still_gets_the_floor(self):
        """Four minutes, however short the runs, before anyone is told."""
        assert tw.late_run(self.driver(left=9, cycle_s=20.0, run_age_s=200.0)) is None
        assert "limit is 240 s" in tw.late_run(self.driver(left=9, cycle_s=20.0, run_age_s=300.0))

    def test_without_a_cycle_it_uses_what_runs_take(self):
        assert tw.late_run(self.driver(left=9, run_age_s=200.0)) is None
        assert "take 170 s" in tw.late_run(self.driver(left=9, run_age_s=600.0))

    def test_every_look_says_where_the_queue_is(self):
        """cycle() prints it, so a person reading the log sees the campaign's progress."""
        assert "due = due_line(driver)" in pathlib.Path(
            "scripts/testbed_watch.py").read_text(encoding="utf-8")

    def test_the_probe_reads_the_queue_with_a_reader_it_has_already_set(self):
        """A shell variable used above where it is set is empty, and the queue would say nothing."""
        assert tw.DRIVER_PROBE.index("TIMING='") < tw.DRIVER_PROBE.index('python3 -c "$TIMING"')

    def test_the_probe_asks_the_queue_for_its_timing(self):
        assert 'echo "timing=$(python3 -c "$TIMING" "$queue"' in tw.DRIVER_PROBE
        assert "out[\"run_age_s\"]" in tw.DRIVER_PROBE


class TestMoney:
    """Azure bills a day late, so the watch keeps its own count of the machine time it sees."""

    @staticmethod
    def state(**timing):
        return {"timing": json.dumps(timing) if timing else ""}

    def test_a_run_the_queue_has_just_begun_is_reported_once(self):
        state = {}
        driver = self.state(run_key="r012-C0-kafka", run_started="2026-09-18T12:03:00Z")
        assert tw.began_a_run(driver, state) == ("r012-C0-kafka", "2026-09-18T12:03:00Z")
        assert tw.began_a_run(driver, state) is None, "the same run is not begun twice"

    def test_a_queue_that_names_no_run_begins_nothing(self):
        assert tw.began_a_run({}, {}) is None
        assert tw.began_a_run(None, {}) is None

    def test_a_run_without_a_key_is_still_reported(self):
        assert tw.began_a_run(self.state(run_started="2026-09-18T12:03:00Z"), {})[0] == "a run"

    def lanes(self, tmp_path, **states):
        hosts = {"a": {"AZ_PROFILE": "matched"}, "arm": {"AZ_PROFILE": "arm"}}
        status = {}
        lines = tw.money_lines([("a", None), ("arm", None)], hosts, states,
                               str(tmp_path / "spend.json"), 200.0, STAMP, status)
        return lines, status

    def test_the_first_look_starts_the_count(self, tmp_path):
        lines, status = self.lanes(tmp_path, a={"hourly_usd": 0.48}, arm={"hourly_usd": 0.37})
        assert lines == ["  money: spent about $0.00 of $200; since 2026-09-14"]
        assert status["spend"]["credit_usd"] == 200.0

    def test_the_second_look_pays_for_the_time_between(self, tmp_path):
        path = str(tmp_path / "spend.json")
        hosts = {"a": {"AZ_PROFILE": "matched"}}
        states = {"a": {"hourly_usd": 0.48}}
        tw.money_lines([("a", None)], hosts, states, path, 200.0,
                       STAMP - datetime.timedelta(minutes=10), {})
        lines = tw.money_lines([("a", None)], hosts, states, path, 200.0, STAMP, {})
        assert "spent about $0.08 of $200" in lines[0] and "matched $0.08" in lines[0]

    def test_a_pair_that_does_not_answer_is_counted_at_nothing(self, tmp_path):
        lines, status = self.lanes(tmp_path, a={"hourly_usd": 0.0}, arm={})
        assert status["spend"]["by_profile"] == {} and "of $200" in lines[0]

    def test_a_run_that_begins_is_also_told_how_far_along_the_work_is(self, tmp_path,
                                                                       monkeypatch):
        """The other question a person watching wants answered, on the same event."""
        monkeypatch.setattr(tw.progress, "counted", lambda *a, **k: {"A1, the slice": 296})
        states = {"a": {"hourly_usd": 0.48, "began": ("r012", "2026-09-14T23:00:00Z"),
                        "queue": "runs/azure/stage1/matched_x/a1_20260918T194622Z.csv",
                        "timing": {"done": 41}},
                  "arm": {}}
        lines, _ = self.lanes(tmp_path, **states)
        assert any("progress: 337 of 3,590 runs the plan asks for" in line for line in lines)

    def test_the_campaign_running_now_is_counted_once(self, monkeypatch):
        monkeypatch.setattr(tw.progress, "counted", lambda *a, **k: {"A1, the slice": 92})
        said = tw.far_along({"a": {"queue": "runs/azure/stage1/m/a1_two.csv",
                                   "timing": {"done": 41}}})
        assert "133 of 3,590" in said

    def test_a_lane_with_no_queue_adds_nothing(self, monkeypatch):
        monkeypatch.setattr(tw.progress, "counted", lambda *a, **k: {"A1, the slice": 92})
        assert "92 of 3,590" in tw.far_along({"a": {}, "b": {"queue": "", "timing": {}}})

    def test_the_queue_says_which_pair_is_running_it(self, monkeypatch):
        """An instrument campaign counts for stage 0 or for A4 depending on the pair that runs
        it, so the pair has to travel with the label."""
        monkeypatch.setattr(tw.progress, "counted", lambda *a, **k: {})
        said = tw.far_along({"arm": {"queue": "runs/azure/stage1/arm_20260919T031017Z/c0_x.csv",
                                     "timing": {"done": 12}}})
        assert "progress: 12 of 3,590" in said, "counted for A4, whose first campaign it is"

    def test_a_run_that_began_is_told_what_had_been_spent(self, tmp_path):
        path = str(tmp_path / "spend.json")
        hosts = {"a": {"AZ_PROFILE": "matched"}}
        states = {"a": {"hourly_usd": 0.48}}
        tw.money_lines([("a", None)], hosts, states, path, 200.0,
                       STAMP - datetime.timedelta(minutes=10), {})
        states["a"]["began"] = ("r012-C0-kafka", STAMP.strftime("%Y-%m-%dT%H:%M:%SZ"))
        lines = tw.money_lines([("a", None)], hosts, states, path, 200.0, STAMP, {})
        assert lines[1] == ("  money: lane a began r012-C0-kafka at 2026-09-14T23:00:00Z, "
                            "with about $0.08 spent by then")

    def test_a_run_older_than_the_ledger_takes_everything_spent(self, tmp_path):
        """A run that began before the first look still knows the bill the ledger was seeded with."""
        path = tmp_path / "spend.json"
        path.write_text(json.dumps({"before_usd": 8.49}), encoding="utf-8")
        states = {"a": {"hourly_usd": 0.48, "began": ("r001", "2020-01-01T00:00:00Z")},
                  "arm": {}}
        lines, _ = self.lanes(tmp_path, **states)
        assert "with about $8.49 spent by then" in lines[1]

    def test_the_look_counts_the_money_and_the_probe_asks_when_a_run_began(self, hosts_file,
                                                                          tmp_path):
        out = io.StringIO()
        code = tw.main(["--hosts", hosts_file, "--log-dir", str(tmp_path / "log"),
                        "--ledger", str(tmp_path / "spend.json"), "--once"],
                       out=out, clock=lambda: STAMP, run=fake_run())
        assert code == 0 and "money: spent about $0.00 of $200" in out.getvalue()
        assert "out[\"run_started\"]" in tw.DRIVER_PROBE
        with open(tmp_path / "log" / "status.json", encoding="utf-8") as fh:
            assert json.load(fh)["spend"]["total_usd"] == 0.0


class TestRunNumbers:
    """Every finished run is shown with its numbers, and numbers no working setup produces are
    alerts, so a pair doing something absurd is seen, and stopped, at once."""

    NUMBERS = {"run_dir": "runs/law_c0-r001-a1", "verdict": "count", "messages": 4990,
               "trip_ms": 3.412, "gotit_ms": 0.214, "negative_rate": 0.123, "load_pct": 75.24,
               "load_target": 75, "target_trip_ms": 3.8}
    HOSTS = {"DRIVER_PUBLIC": "4.223.79.212", "BROKER_PRIV": "10.1.1.21", "AZ_PROFILE": "matched"}

    def test_the_probe_reads_each_campaign_runs_numbers(self):
        assert 'echo "numbers=$(python3 -c "$NUMBERS" "$d" 2>/dev/null)"' in tw.DRIVER_PROBE

    def test_numbers_lines_are_read(self):
        got = facts("numbers=%s\nnumbers=\n" % json.dumps(self.NUMBERS))
        assert got["numbers"] == [self.NUMBERS, {"unreadable": ""}]

    def test_a_campaign_run_shows_the_numbers_its_verdict_was_given_on(self):
        run = {"run_dir": "runs/law_c0-r001-a1", "messages": 6500, "trip_median_ms": 3.5,
               "gotit_median_ms": 0.3, "measured_negative_rate": 0.2}
        assert tw.run_line(run, self.NUMBERS) == (
            "run law_c0-r001-a1: messages 4,990, trip 3.41 ms (planned 3.80 ms), "
            "got-it 0.21 ms, negative 12.3%, load 75.2%, count")

    def test_another_run_shows_what_the_probe_read(self):
        assert tw.run_line(RUN_OK, {}) == (
            "run concurrency_x_kafka_feed1_rep1: messages 1,200, trip 0.42 ms, got-it ?, "
            "negative ?")

    def test_a_look_has_a_line_for_each_finished_run_it_can_read(self):
        driver = facts("run=%s\nrun=not json\nnumbers=%s\nnumbers=broken\n" % (
            json.dumps(dict(RUN_OK, run_dir="runs/law_c0-r001-a1")), json.dumps(self.NUMBERS)))
        lines = tw.run_lines(driver)
        assert len(lines) == 1 and lines[0].endswith("negative 12.3%, load 75.2%, count")

    @pytest.mark.parametrize("change,level,fragment", [
        ({"load_pct": 20.0}, "ALERT", "ran at 20% load where 75% was set"),
        ({"trip_ms": 9.5}, "WARN", "measured a 9.50 ms trip where 3.80 ms was planned"),
        ({"unreadable": "KeyError"}, "WARN", "could not read the numbers of runs/law_c0-r001-a1")])
    def test_numbers_no_working_setup_produces(self, change, level, fragment):
        found = tw.numbers_flags([dict(self.NUMBERS, **change)])
        assert [(f[0], fragment in f[1]) for f in found] == [(level, True)]

    def test_numbers_within_reason_raise_nothing(self):
        near = dict(self.NUMBERS, load_pct=73.0, trip_ms=4.6)
        unplanned = dict(self.NUMBERS, target_trip_ms=None, load_target=None, load_pct="x")
        assert tw.numbers_flags([near, unplanned]) == []

    def test_an_alert_comes_with_the_command_that_stops_the_pair(self):
        driver = DRIVER_OK + "numbers=%s\n" % json.dumps(dict(self.NUMBERS, load_pct=20.0))
        lines, _ = tw.cycle(self.HOSTS, azure_testbed.load_spec(), "k", "ssh",
                            fake_run(driver=driver), None, {}, "stamp")
        assert "  run concurrency_x_kafka_feed1_rep1: messages 1,200, trip 0.42 ms, " \
            "got-it ?, negative ?" in lines
        assert lines[-1].startswith("  to stop this pair after the run in progress: ssh -i k ")
        assert lines[-1].endswith(" ubuntu@4.223.79.212 'touch sbl/runs/azure/STOP'")

    def test_an_unreachable_machine_alone_brings_no_stop_command(self):
        lines, flags = tw.cycle(self.HOSTS, azure_testbed.load_spec(), "k", "ssh",
                                fake_run(broker=Done("", 255, "refused")),
                                lambda a: (1, "", ""), {}, "stamp")
        assert [f[0] for f in flags] == ["ALERT"]
        assert not any("to stop this pair" in line for line in lines)
