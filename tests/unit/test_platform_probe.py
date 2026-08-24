"""Tests for scripts/platform_probe.py - target >=95% branch coverage."""
import json
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import platform_probe as pp  # noqa: E402
from platform_probe import (  # noqa: E402
    timer_resolution,
    sleep_granularity,
    tcp_rtt,
    redis_ping_rtt,
    platform_info,
    parse_ports,
    probe,
    main,
)


class TestParsePorts:
    def test_parses_multiple(self):
        out = parse_ports(["kafka=localhost:19092", "redis=127.0.0.1:16379"])
        assert out == {"kafka": ("localhost", 19092), "redis": ("127.0.0.1", 16379)}

    def test_empty_list(self):
        assert parse_ports([]) == {}

    @pytest.mark.parametrize("bad", ["kafka", "kafka=localhost", "localhost:9092"])
    def test_rejects_malformed(self, bad):
        with pytest.raises(ValueError):
            parse_ports([bad])

    def test_ipv6ish_host_takes_last_colon(self):
        assert parse_ports(["k=a:b:1234"]) == {"k": ("a:b", 1234)}


class TestTimerResolution:
    def test_finds_smallest_positive_step(self):
        # clock advances 5 then 2 then 9 units; smallest positive step is 2
        seq = iter([0.0, 5.0, 7.0, 16.0])
        assert timer_resolution(samples=3, clock=lambda: next(seq)) == pytest.approx(2.0)

    def test_zero_deltas_give_none(self):
        # a clock that never advances has no measurable resolution
        assert timer_resolution(samples=5, clock=lambda: 1.0) is None

    def test_real_clock_returns_positive(self):
        res = timer_resolution(samples=200)
        assert res is None or res > 0


class TestSleepGranularity:
    def test_reports_overshoot(self):
        # simulate a coarse tick: every sleep actually takes 15 ms
        ticks = []

        def fake_clock():
            return ticks[-1] if ticks else 0.0

        state = {"t": 0.0}

        def clock():
            return state["t"]

        def sleep(_d):
            state["t"] += 0.015

        out = sleep_granularity(0.001, trials=4, sleep=sleep, clock=clock)
        assert out["median_ms"] == pytest.approx(15.0)
        assert out["overshoot_median_ms"] == pytest.approx(14.0)
        assert out["requested_ms"] == pytest.approx(1.0)
        assert out["trials"] == 4

    def test_min_max_ordered(self):
        state = {"t": 0.0, "i": 0}
        durations = [0.001, 0.020, 0.005]

        def clock():
            return state["t"]

        def sleep(_d):
            state["t"] += durations[state["i"] % len(durations)]
            state["i"] += 1

        out = sleep_granularity(0.001, trials=3, sleep=sleep, clock=clock)
        assert out["min_ms"] == pytest.approx(1.0)
        assert out["max_ms"] == pytest.approx(20.0)
        assert out["min_ms"] <= out["median_ms"] <= out["max_ms"]


class TestTcpRtt:
    def test_reachable_host(self):
        out = tcp_rtt("h", 1234, trials=5, connect=lambda *a: None)
        assert out["reachable"] is True
        assert out["errors"] == 0
        assert out["min_ms"] <= out["median_ms"] <= out["max_ms"]
        assert out["host"] == "h" and out["port"] == 1234

    def test_unreachable_host(self):
        def boom(*_a):
            raise OSError("refused")

        out = tcp_rtt("h", 1, trials=3, connect=boom)
        assert out["reachable"] is False
        assert out["errors"] == 3
        assert "median_ms" not in out

    def test_partial_failures_still_report(self):
        calls = {"n": 0}

        def flaky(*_a):
            calls["n"] += 1
            if calls["n"] % 2:
                raise OSError("nope")

        out = tcp_rtt("h", 1, trials=4, connect=flaky)
        assert out["reachable"] is True
        assert out["errors"] == 2


class _FakeSock:
    """Socket stub: each PING gets a +PONG, optionally failing or closing early."""

    def __init__(self, replies=None, fail_after=None):
        self.replies = replies
        self.fail_after = fail_after
        self.sent = 0
        self.closed = False

    def sendall(self, _b):
        self.sent += 1
        if self.fail_after is not None and self.sent > self.fail_after:
            raise OSError("broken pipe")

    def recv(self, _n):
        if self.replies is not None and self.sent > self.replies:
            return b""          # server closed the connection
        return b"+PONG\r\n"

    def close(self):
        self.closed = True


class TestRedisPingRtt:
    def test_measures_and_implies_ceiling(self):
        sock = _FakeSock()
        out = redis_ping_rtt("h", 6379, trials=10, opener=lambda *a: sock)
        assert out["reachable"] is True
        assert out["trials"] == 10
        assert out["implied_ceiling_msgs_per_s"] == pytest.approx(
            1000.0 / out["median_ms"])
        assert sock.closed

    def test_unopenable(self):
        def boom(*_a):
            raise OSError("refused")

        out = redis_ping_rtt("h", 6379, trials=5, opener=boom)
        assert out["reachable"] is False
        assert "median_ms" not in out

    def test_server_closes_early_keeps_partial(self):
        out = redis_ping_rtt("h", 6379, trials=10,
                             opener=lambda *a: _FakeSock(replies=3))
        assert out["reachable"] is True
        assert out["trials"] == 3

    def test_send_error_midway_keeps_partial(self):
        out = redis_ping_rtt("h", 6379, trials=10,
                             opener=lambda *a: _FakeSock(fail_after=4))
        assert out["reachable"] is True
        assert out["trials"] == 4

    def test_immediate_close_is_unreachable(self):
        out = redis_ping_rtt("h", 6379, trials=5,
                             opener=lambda *a: _FakeSock(replies=0))
        assert out["reachable"] is False


class TestPlatformInfo:
    def test_has_expected_keys(self):
        info = platform_info()
        for k in ("python_version", "platform", "system", "machine"):
            assert info[k]


class TestProbe:
    def test_probe_is_json_serialisable(self):
        out = probe(ports={"redis": ("h", 6379)}, trials=2, sleep_trials=2,
                    connect=lambda *a: None)
        json.dumps(out)  # must not raise
        assert out["broker_rtt"]["redis"]["reachable"] is True
        assert "sleep_1ms" in out and "sleep_10ms" in out

    def test_default_ports_used_when_none(self):
        out = probe(ports=None, trials=1, sleep_trials=2, connect=lambda *a: None)
        assert set(out["broker_rtt"]) == {"kafka", "redis"}

    def test_none_timer_resolution_serialises(self, monkeypatch):
        import platform_probe as pp
        monkeypatch.setattr(pp, "timer_resolution", lambda *a, **k: None)
        out = pp.probe(ports={}, trials=1, sleep_trials=2, connect=lambda *a: None)
        assert out["timer_resolution_ns"] is None


class TestMain:
    def test_writes_json_and_prints(self, temp_dir, capsys, monkeypatch):
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        out = temp_dir / "p" / "platform.json"
        rc = main(["--out", str(out), "--trials", "2", "--sleep-trials", "2"])
        assert rc == 0
        data = json.loads(out.read_text())
        assert "platform" in data and "broker_rtt" in data
        cap = capsys.readouterr().out
        assert "platform" in cap and "sleep(1ms)" in cap

    def test_unreachable_broker_path_prints(self, temp_dir, capsys, monkeypatch):
        import platform_probe as pp

        def boom(*_a):
            raise OSError("refused")

        monkeypatch.setattr(pp, "_default_connect", boom)
        out = temp_dir / "platform.json"
        assert main(["--out", str(out), "--trials", "1", "--sleep-trials", "2"]) == 0
        assert "unreachable" in capsys.readouterr().out

    def test_explicit_ports_are_probed(self, temp_dir, capsys, monkeypatch):
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        out = temp_dir / "platform.json"
        rc = main(["--out", str(out), "--trials", "1", "--sleep-trials", "2",
                   "--port", "kafka=localhost:19092", "--port", "redis=localhost:16379"])
        assert rc == 0
        data = json.loads(out.read_text())
        assert data["broker_rtt"]["kafka"]["port"] == 19092
        assert data["broker_rtt"]["redis"]["port"] == 16379

    def test_no_redis_endpoint_skips_ping_line(self, temp_dir, capsys, monkeypatch):
        # only a kafka endpoint => no redis_ping_rtt key => neither PING branch prints
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        out = temp_dir / "platform.json"
        rc = main(["--out", str(out), "--trials", "1", "--sleep-trials", "2",
                   "--port", "kafka=localhost:19092"])
        assert rc == 0
        assert "redis PING" not in capsys.readouterr().out
        assert "redis_ping_rtt" not in json.loads(out.read_text())

    def test_unreachable_redis_ping_prints(self, temp_dir, capsys, monkeypatch):
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)

        def boom(*_a):
            raise OSError("refused")

        monkeypatch.setattr(pp, "_default_socket", boom)
        out = temp_dir / "platform.json"
        rc = main(["--out", str(out), "--trials", "1", "--sleep-trials", "2",
                   "--port", "redis=localhost:16379"])
        assert rc == 0
        assert "redis PING    : unreachable" in capsys.readouterr().out

    def test_bad_port_spec_returns_1(self, temp_dir, capsys):
        out = temp_dir / "platform.json"
        assert main(["--out", str(out), "--port", "nonsense"]) == 1
        assert "bad --port spec" in capsys.readouterr().out

    def test_none_resolution_skips_print(self, temp_dir, capsys, monkeypatch):
        import platform_probe as pp
        monkeypatch.setattr(pp, "timer_resolution", lambda *a, **k: None)
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        out = temp_dir / "platform.json"
        assert main(["--out", str(out), "--trials", "1", "--sleep-trials", "2"]) == 0
        assert "timer resol." not in capsys.readouterr().out


class TestClockProvenance:
    """Which clock a timestamp came from, and what it promises across CPUs.

    Added because a referee asked which clocksource the testbed used and the campaign had
    no answer: the field was never captured and the instances were reclaimed before anyone
    thought to ask. The past runs cannot be repaired. This makes sure the question is
    answerable for every run after it, which is the only part still in our control.
    """

    def _reader(self, mapping):
        return lambda path: mapping.get(path)

    def test_reads_the_current_clocksource(self):
        got = pp.clock_provenance(reader=self._reader({
            pp.CLOCKSOURCE_CURRENT: "kvm-clock\n"}))
        assert got["current_clocksource"] == "kvm-clock"

    def test_reads_the_available_clocksources_as_a_list(self):
        got = pp.clock_provenance(reader=self._reader({
            pp.CLOCKSOURCE_AVAILABLE: "kvm-clock tsc acpi_pm\n"}))
        assert got["available_clocksource"] == ["kvm-clock", "tsc", "acpi_pm"]

    def test_reports_the_tsc_flags_the_referee_asked_about(self):
        got = pp.clock_provenance(reader=self._reader({
            pp.CPUINFO: "processor\t: 0\nflags\t\t: fpu constant_tsc nonstop_tsc hypervisor\n"}))
        assert got["cpu_flags"]["constant_tsc"] is True
        assert got["cpu_flags"]["nonstop_tsc"] is True
        assert got["cpu_flags"]["hypervisor"] is True
        assert got["cpu_flags"]["tsc_reliable"] is False

    def test_a_flag_absent_from_cpuinfo_reads_false_not_missing(self):
        """A silent omission is what produced the gap in the first place."""
        got = pp.clock_provenance(reader=self._reader({
            pp.CPUINFO: "flags\t\t: fpu vme\n"}))
        assert set(got["cpu_flags"]) == set(pp.TSC_FLAGS)
        assert not any(got["cpu_flags"].values())

    def test_a_platform_without_sysfs_returns_nones_rather_than_raising(self):
        got = pp.clock_provenance(reader=self._reader({}))
        assert got["current_clocksource"] is None
        assert got["available_clocksource"] is None
        assert got["cpu_flags"] == {}

    def test_flags_are_read_from_every_processor_block(self):
        blob = ("processor\t: 0\nflags\t\t: fpu constant_tsc\n"
                "processor\t: 1\nflags\t\t: fpu nonstop_tsc\n")
        got = pp.clock_provenance(reader=self._reader({pp.CPUINFO: blob}))
        assert got["cpu_flags"]["constant_tsc"] and got["cpu_flags"]["nonstop_tsc"]

    def test_the_probe_carries_clock_provenance(self, monkeypatch):
        monkeypatch.setattr(pp, "clock_provenance", lambda *a, **k: {"current_clocksource": "tsc"})
        out = pp.probe(ports={}, trials=1, sleep_trials=1)
        assert out["clock_provenance"]["current_clocksource"] == "tsc"


class TestClockOnlyCapture:
    """One command, no brokers, for a restored image.

    A restored boot volume has no Kafka and no Redis running, so the full probe would block
    on connections that will never open. This path records only what the referee asked for.
    """

    def test_writes_clock_provenance_without_touching_a_socket(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pp, "clock_provenance",
                            lambda *a, **k: {"current_clocksource": "kvm-clock",
                                             "available_clocksource": ["kvm-clock", "tsc"],
                                             "cpu_flags": {"constant_tsc": True}})
        def _boom(*a, **k):
            raise AssertionError("clock-only must not open a socket")
        monkeypatch.setattr(pp, "tcp_rtt", _boom)
        monkeypatch.setattr(pp, "redis_ping_rtt", _boom)
        out = tmp_path / "clock.json"
        assert pp.main(["--clock-only", "--out", str(out)]) == 0
        got = json.loads(out.read_text(encoding="utf-8"))
        assert got["clock_provenance"]["current_clocksource"] == "kvm-clock"
        assert "broker_rtt" not in got

    def test_reports_an_unpublished_clocksource_plainly(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(pp, "clock_provenance",
                            lambda *a, **k: {"current_clocksource": None,
                                             "available_clocksource": None, "cpu_flags": {}})
        assert pp.main(["--clock-only", "--out", str(tmp_path / "c.json")]) == 0
        assert "not published" in capsys.readouterr().out


class TestInterpreterSerialisation:
    """What stands between a woken thread and its next bytecode, beside the scheduler.

    Section V-E names the interpreter lock as a rival and bounds it. That argument is only
    checkable if a run records what the interpreter was configured to do, which no campaign
    of ours did until the referee asked for it.
    """

    def test_it_reports_the_implementation_and_the_switch_interval(self):
        info = pp.interpreter_serialisation()
        assert info["implementation"]
        assert isinstance(info["switch_interval_s"], float)
        assert info["switch_interval_s"] > 0

    def test_it_reports_whether_the_lock_is_in_force(self):
        info = pp.interpreter_serialisation()
        assert info["gil_disabled"] in (True, False)

    def test_a_build_without_the_getter_degrades_rather_than_raises(self, monkeypatch):
        monkeypatch.delattr("sys.getswitchinterval", raising=False)
        info = pp.interpreter_serialisation()
        assert info["switch_interval_s"] is None

    def test_the_probe_carries_it(self):
        out = pp.probe(ports={}, trials=1, sleep_trials=5)
        assert "interpreter_serialisation" in out
        assert out["interpreter_serialisation"]["implementation"]


class TestTheReachableRedisPingLine:

    def test_a_reachable_ping_reports_the_implied_ceiling(self, temp_dir, capsys,
                                                          monkeypatch):
        """The established-connection RTT is what bounds the achievable send rate, so the
        ceiling it implies is the number the campaign plans against. Only the unreachable
        branch had ever been printed."""
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        monkeypatch.setattr(pp, "redis_ping_rtt", lambda *a, **kw: {
            "reachable": True, "median_ms": 0.12, "implied_ceiling_msgs_per_s": 8333.0,
            "trials": 20})
        out = temp_dir / "platform.json"
        assert main(["--out", str(out), "--trials", "1", "--sleep-trials", "2"]) == 0
        printed = capsys.readouterr().out
        assert "established-connection RTT median 0.120 ms" in printed
        assert "ceiling 8333 msg/s" in printed

    def test_an_unreachable_ping_says_so_and_claims_no_ceiling(self, temp_dir, capsys,
                                                               monkeypatch):
        """A ceiling computed from an unreachable host would be a number from nothing."""
        import platform_probe as pp
        monkeypatch.setattr(pp, "_default_connect", lambda *a: None)
        monkeypatch.setattr(pp, "redis_ping_rtt", lambda *a, **kw: {
            "reachable": False, "errors": 20})
        out = temp_dir / "platform.json"
        assert main(["--out", str(out), "--trials", "1", "--sleep-trials", "2"]) == 0
        printed = capsys.readouterr().out
        assert "redis PING    : unreachable" in printed
        assert "ceiling" not in printed.split("redis PING")[1]
