"""Tests for scripts/receiver_delay.py, and for the trial runners' consumer hook it relies on.

The receiver-only delay exists because the earlier delay reached both sides of a subtraction and
nobody could tell from the result. So the tests pin the two properties that make it
receiver-only -- a queue band nothing but the filter can reach, and a namespace that gives the
consumer its own address -- and the check that proves it on the machine.
"""
import io
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))

import receiver_delay as rd  # noqa: E402

REPO = Path(__file__).parent.parent.parent


class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def ping_output(times):
    return "".join("64 bytes from 10.1.1.21: icmp_seq=%d ttl=64 time=%.3f ms\n" % (i, t)
                   for i, t in enumerate(times, 1))


class TestTheBrokerQueue:

    def test_the_fourth_band_is_reachable_only_through_the_filter(self):
        commands = [argv for argv, _ in rd.broker_commands("10.1.1.11", 2.0)]
        prio = commands[1]
        assert prio[prio.index("bands") + 1] == "4"
        priomap = prio[prio.index("priomap") + 1:]
        assert len(priomap) == 16 and set(priomap) <= {"0", "1", "2"}, (
            "if the map ever named band 3, ordinary traffic would be delayed too")
        netem = commands[2]
        assert netem[netem.index("parent") + 1] == "1:4" and "netem" in netem
        flt = commands[3]
        assert flt[flt.index("dst") + 1] == "10.1.1.11/32"
        assert flt[flt.index("flowid") + 1] == "1:4"

    @pytest.mark.parametrize("ms,token", [(0.5, "500us"), (2.0, "2000us"), (0, "0us"),
                                          (0.1, "100us")])
    def test_the_delay_reaches_tc_in_whole_microseconds(self, ms, token):
        netem = rd.broker_commands("10.1.1.11", ms)[2][0]
        assert netem[netem.index("delay") + 1] == token

    def test_netem_never_becomes_the_bottleneck(self):
        netem = rd.broker_commands("10.1.1.11", 1)[2][0]
        assert netem[netem.index("limit") + 1] == "200000"

    def test_only_clearing_the_old_queue_may_fail(self):
        flags = [may_fail for _, may_fail in rd.broker_commands("10.1.1.11", 1)]
        assert flags == [True, False, False, False]
        assert rd.broker_clear_commands("eth1") == [(["tc", "qdisc", "del", "dev", "eth1",
                                                      "root"], True)]

    def test_a_typo_is_refused_before_it_becomes_a_filter_that_matches_nothing(self):
        with pytest.raises(ValueError):
            rd.broker_commands("10.1.1", 1)
        with pytest.raises(ValueError, match="cannot be negative"):
            rd.broker_commands("10.1.1.11", -0.5)


class TestTheDriverNamespace:

    def test_the_receiver_gets_its_own_address_and_route(self):
        commands = [argv for argv, _ in rd.driver_commands("10.1.1.11/24", "10.1.1.1")]
        assert ["ip", "link", "add", "sblrecv0", "link", "eth0", "type", "ipvlan", "mode",
                "l2"] in commands
        assert ["ip", "-n", "sblrecv", "addr", "add", "10.1.1.11/24", "dev",
                "sblrecv0"] in commands
        assert commands[-1] == ["ip", "-n", "sblrecv", "route", "add", "default", "via",
                                "10.1.1.1"]

    def test_only_the_cleanup_may_fail(self):
        flags = [may_fail for _, may_fail in rd.driver_commands("10.1.1.11/24", "10.1.1.1")]
        assert flags[:3] == [True, True, True] and not any(flags[3:])
        assert all(may_fail for _, may_fail in rd.driver_clear_commands())

    def test_the_host_gives_the_address_up_before_the_namespace_takes_it(self):
        """Azure's first boot writes every address of the card into netplan, so the first driver
        held 10.1.1.11 itself. Once the namespace owned it, the broker's replies to the driver
        went into the namespace and the session lost the broker. Every boot restores the
        address, so the release runs each time and may find nothing to delete."""
        commands = rd.driver_commands("10.1.1.11/24", "10.1.1.1")
        argvs = [argv for argv, _ in commands]
        release = ["ip", "addr", "del", "10.1.1.11/24", "dev", "eth0"]
        assert argvs.index(release) < argvs.index(["ip", "netns", "add", "sblrecv"])
        assert commands[argvs.index(release)][1] is True

    def test_the_address_also_leaves_netplans_own_settings(self):
        """A package upgrade restarted networkd in the middle of a pilot on 16 September, and
        networkd put the address back from netplan. So netplan forgets the card's static
        addresses, and its networkd files are written again without them, before the namespace
        is built."""
        argvs = [argv for argv, _ in rd.driver_commands("10.1.1.11/24", "10.1.1.1")]
        forget = ["netplan", "set", "--origin-hint", "50-cloud-init",
                  "ethernets.eth0.addresses=null"]
        assert (argvs.index(forget) < argvs.index(["netplan", "generate"])
                < argvs.index(["ip", "netns", "add", "sblrecv"]))

    def test_l3_mode_passes_through(self):
        commands = [argv for argv, _ in
                    rd.driver_commands("10.1.1.11/24", "10.1.1.1", dev="eth1", mode="l3")]
        link = next(argv for argv in commands if argv[:3] == ["ip", "link", "add"])
        assert link[-1] == "l3" and link[link.index("link", 2) + 1] == "eth1"
        assert ["ip", "addr", "del", "10.1.1.11/24", "dev", "eth1"] in commands

    def test_an_address_without_its_prefix_is_refused(self):
        with pytest.raises(ValueError, match="subnet prefix"):
            rd.driver_commands("10.1.1.11", "10.1.1.1")

    def test_a_gateway_outside_the_subnet_is_refused(self):
        with pytest.raises(ValueError, match="not in the receiver's subnet"):
            rd.driver_commands("10.1.1.11/24", "10.1.2.1")


class TestRunningCommands:

    def test_without_apply_it_only_prints(self):
        out, calls = io.StringIO(), []
        code = rd.run_commands([(["tc", "a"], True), (["tc", "b"], False)],
                               run=lambda *a, **k: calls.append(a), out=out)
        assert code == 0 and calls == []
        assert out.getvalue() == "tc a    # may fail harmlessly\ntc b\n"

    def test_a_harmless_failure_is_passed_and_a_real_one_stops_everything(self):
        out, calls = io.StringIO(), []
        answers = {"a": Done(2, stderr="no qdisc"), "b": Done(1, stderr="RTNETLINK: busy"),
                   "c": Done()}

        def run(argv, **kwargs):
            calls.append(argv[-1])
            return answers[argv[-1]]

        code = rd.run_commands([(["tc", "a"], True), (["tc", "b"], False), (["tc", "c"], False)],
                               apply=True, run=run, out=out)
        assert code == 1 and calls == ["a", "b"]
        assert "FAILED (1): RTNETLINK: busy" in out.getvalue()


class TestMeasuring:

    @staticmethod
    def fake_ping(host_times, receiver_times, calls=None):
        def run(argv, **kwargs):
            if calls is not None:
                calls.append(argv[0])
            return Done(stdout=ping_output(receiver_times if argv[0] == "ip" else host_times))
        return run

    def test_medians_from_both_sides_in_alternating_blocks(self):
        calls = []
        result = rd.measure("10.1.1.21", count=12, run=self.fake_ping(
            [0.30, 0.31, 0.29], [0.80, 0.81, 0.79], calls))
        assert result["host_median_ms"] == pytest.approx(0.30)
        assert result["receiver_median_ms"] == pytest.approx(0.80)
        assert result["replies_host"] == result["replies_receiver"] == 12
        assert calls == ["ping", "ip"] * 4

    def test_the_receiver_pings_from_inside_its_namespace(self):
        assert rd.ping_command("10.1.1.21", 5, 0.01, "sblrecv")[:4] == ["ip", "netns", "exec",
                                                                        "sblrecv"]
        assert rd.ping_command("10.1.1.21", 5, 0.01)[0] == "ping"

    def test_a_failed_ping_names_its_side(self):
        def run(argv, **kwargs):
            return Done(1, stderr="Cannot open network namespace") if argv[0] == "ip" \
                else Done(stdout=ping_output([0.3]))
        with pytest.raises(RuntimeError, match="from sblrecv failed"):
            rd.measure("10.1.1.21", count=4, run=run)
        with pytest.raises(RuntimeError, match="from the host failed: unreachable"):
            rd.measure("10.1.1.21", run=lambda argv, **k: Done(1, stdout="unreachable"))

    def test_a_ping_with_no_replies_printed_is_not_a_measurement(self):
        with pytest.raises(RuntimeError, match="no round-trip times"):
            rd.measure("10.1.1.21", count=4, run=lambda argv, **k: Done(stdout="PING ...\n"))


class TestVerifying:

    BASE = {"host_median_ms": 0.30, "receiver_median_ms": 0.30}

    def test_a_clean_step(self):
        ok, report = rd.verify(self.BASE, {"host_median_ms": 0.31, "receiver_median_ms": 0.81},
                               0.5)
        assert ok and report["added_ms_measured"] == pytest.approx(0.5)

    def test_a_delay_that_reached_the_sender_fails(self):
        ok, report = rd.verify(self.BASE, {"host_median_ms": 0.80, "receiver_median_ms": 0.80},
                               0.5)
        assert not ok and report["sender_path_unchanged"] is False

    def test_a_delay_that_did_not_reach_the_receiver_fails(self):
        ok, report = rd.verify(self.BASE, {"host_median_ms": 0.30, "receiver_median_ms": 0.60},
                               0.5)
        assert not ok and report["receiver_path_moved_by_the_delay"] is False


class TestMain:

    def run(self, argv, run=None):
        out = io.StringIO()
        code = rd.main(argv, run=run or (lambda *a, **k: Done()), out=out)
        return code, out.getvalue()

    def test_every_setup_command_prints_by_default(self):
        assert self.run(["broker", "--dst", "10.1.1.11", "--delay-ms", "0.5"])[0] == 0
        assert self.run(["broker-clear"])[0] == 0
        code, text = self.run(["driver", "--address", "10.1.1.11/24", "--gateway", "10.1.1.1",
                               "--apply"])
        assert code == 0 and text.startswith("$ ip netns del sblrecv")
        assert self.run(["driver-clear", "--apply"])[0] == 0

    def test_a_bad_address_is_an_error_line(self):
        code, text = self.run(["driver", "--address", "10.1.1.11", "--gateway", "10.1.1.1"])
        assert code == 2 and text.startswith("ERROR:")

    def test_measure_prints_and_can_write(self, tmp_path):
        ping = TestMeasuring.fake_ping([0.3], [0.8])
        code, text = self.run(["measure", "--broker", "10.1.1.21", "--count", "4"], run=ping)
        assert code == 0 and json.loads(text)["receiver_median_ms"] == 0.8
        dest = tmp_path / "step.json"
        self.run(["measure", "--broker", "10.1.1.21", "--count", "4", "--out", str(dest)],
                 run=ping)
        assert json.loads(dest.read_text(encoding="utf-8"))["host_median_ms"] == 0.3

    def test_verify_exit_codes(self, tmp_path):
        base, good, bad = tmp_path / "b.json", tmp_path / "g.json", tmp_path / "x.json"
        base.write_text(json.dumps(TestVerifying.BASE), encoding="utf-8")
        good.write_text(json.dumps({"host_median_ms": 0.3, "receiver_median_ms": 2.3}),
                        encoding="utf-8")
        bad.write_text(json.dumps({"host_median_ms": 2.3, "receiver_median_ms": 2.3}),
                       encoding="utf-8")
        argv = ["verify", "--baseline", str(base), "--added-ms", "2.0", "--step"]
        assert self.run(argv + [str(good)])[0] == 0
        assert self.run(argv + [str(bad)])[0] == 1
        assert self.run(argv + [str(tmp_path / "missing.json")])[0] == 2


@pytest.mark.parametrize("runner,consumer", [("run_kafka_trial.sh", "kafka_consumer.py"),
                                             ("run_redis_trial.sh", "redis_consumer.py")])
class TestTheTrialRunnersCarryTheConsumerHook:
    """The namespace is useless unless the consumer, and only the consumer, is started in it."""

    @staticmethod
    def text(runner):
        return (REPO / "scripts" / runner).read_text(encoding="utf-8")

    def test_the_hook_is_empty_unless_a_campaign_sets_it(self, runner, consumer):
        assert 'CONSUMER_WRAP="${SBL_CONSUMER_WRAP:-}"' in self.text(runner)

    def test_it_prefixes_the_consumer_and_nothing_else(self, runner, consumer):
        wrapped = [line for line in self.text(runner).splitlines()
                   if "$CONSUMER_WRAP" in line and not line.lstrip().startswith("#")]
        assert len(wrapped) == 1 and "scripts/%s" % consumer in wrapped[0]

    def test_a_run_records_which_arm_it_belonged_to(self, runner, consumer):
        """p4_ack_batching's lesson: the treatment must be recoverable from the run alone."""
        text = self.text(runner)
        assert '"SBL_CONSUMER_WRAP": os.environ.get("SBL_CONSUMER_WRAP", "")' in text
        assert '"SBL_SCHED_WRAP": os.environ.get("SBL_SCHED_WRAP", "")' in text
