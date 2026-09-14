"""Tests for scripts/testbed_watch.py.

The watch reads machines it never changes, so everything here runs against recorded probe
output: what each flag fires on, what it stays quiet about, and that a machine which does not
answer is reported with what Azure says about it rather than silently left out.
"""
import datetime
import io
import json
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


class Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def fake_run(driver=DRIVER_OK, broker=BROKER_OK, seen=None):
    """Answers the driver's probe and the broker's (the one that goes through ProxyCommand)."""
    def run(argv, input, capture_output, text, timeout):
        if seen is not None:
            seen.append((argv, input))
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

    @pytest.mark.parametrize("extra,level,fragment", [
        ("activity_age_s=1500\n", "ALERT", "nothing has changed for 25 minutes"),
        ("verdict_no=2\n", "ALERT", "2 check(s) in verdicts.csv are marked no"),
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
        (dict(RUN_OK, trip_median_ms=80.0), "WARN", "median trip of 80.0 ms"),
        (dict(RUN_OK, messages=20), "WARN", "only 20 messages"),
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
