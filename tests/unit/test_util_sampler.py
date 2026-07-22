"""Tests for scripts/util_sampler.py - target 100% branch coverage.

The sampler reads Linux /proc interfaces, so the tests supply fake /proc files rather than
depending on the host. That also lets us drive the edge cases (zero elapsed jiffies, saturation)
which are the ones that would otherwise silently corrupt the H2 fit.
"""
from pathlib import Path
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import util_sampler  # noqa: E402
from util_sampler import (  # noqa: E402
    read_cpu_times,
    read_loadavg,
    utilisation,
    sample_loop,
    main,
)


def _stat(tmp, total_user=100, idle=900, iowait=0):
    """A /proc/stat whose aggregate line has the given user/idle/iowait jiffies."""
    p = tmp / "stat"
    p.write_text(
        "cpu  {u} 0 0 {i} {w} 0 0 0 0 0\ncpu0 1 2 3 4 5 6 7 8 9 10\nintr 12345\n".format(
            u=total_user, i=idle, w=iowait),
        encoding="utf-8")
    return p


def _loadavg(tmp, value=2.5):
    p = tmp / "loadavg"
    p.write_text(f"{value} 1.20 0.90 3/512 9999\n", encoding="utf-8")
    return p


class TestReadCpuTimes:
    def test_totals_and_idle(self, temp_dir):
        total, idle = read_cpu_times(_stat(temp_dir, total_user=100, idle=900))
        assert total == 1000 and idle == 900

    def test_iowait_counts_as_idle(self, temp_dir):
        """A thread blocked on IO is not occupying the CPU."""
        _, idle = read_cpu_times(_stat(temp_dir, total_user=100, idle=800, iowait=100))
        assert idle == 900

    def test_short_line_without_iowait(self, temp_dir):
        p = temp_dir / "stat"
        p.write_text("cpu  10 0 0 90\n", encoding="utf-8")
        total, idle = read_cpu_times(p)
        assert total == 100 and idle == 90

    def test_missing_aggregate_line_raises(self, temp_dir):
        p = temp_dir / "stat"
        p.write_text("cpu0 1 2 3 4\nintr 5\n", encoding="utf-8")
        with pytest.raises(ValueError, match="no aggregate cpu line"):
            read_cpu_times(p)


class TestReadLoadavg:
    def test_reads_the_one_minute_figure(self, temp_dir):
        assert read_loadavg(_loadavg(temp_dir, 3.75)) == pytest.approx(3.75)


class TestUtilisation:
    def test_fully_idle(self):
        assert utilisation((0, 0), (100, 100)) == pytest.approx(0.0)

    def test_fully_busy(self):
        assert utilisation((0, 0), (100, 0)) == pytest.approx(1.0)

    def test_half_busy(self):
        assert utilisation((0, 0), (100, 50)) == pytest.approx(0.5)

    def test_no_elapsed_jiffies_is_none_not_zero(self):
        """Reporting 0.0 here would inject false low-utilisation points into the fit."""
        assert utilisation((100, 50), (100, 50)) is None

    def test_counters_going_backwards_is_none(self):
        assert utilisation((200, 100), (100, 50)) is None

    def test_clamped_into_range(self):
        assert utilisation((0, 0), (100, 200)) == pytest.approx(0.0)


class TestSampleLoop:
    def test_writes_samples_until_stopped(self, temp_dir, monkeypatch):
        monkeypatch.setattr(util_sampler.time, "sleep", lambda _s: None)
        stat, load = _stat(temp_dir), _loadavg(temp_dir)
        calls = {"n": 0}

        def stop():
            calls["n"] += 1
            return calls["n"] > 3

        out = temp_dir / "u" / "util.csv"
        n = sample_loop(out, 0.01, stop, stat_path=stat, load_path=load)
        assert n == 0, "a static /proc/stat yields no elapsed jiffies, so no samples"
        assert out.exists(), "the header must still be written"

    def test_records_changing_utilisation(self, temp_dir, monkeypatch):
        monkeypatch.setattr(util_sampler.time, "sleep", lambda _s: None)
        load = _loadavg(temp_dir, 4.0)
        readings = iter([(1000, 500), (2000, 500), (3000, 700)])
        monkeypatch.setattr(util_sampler, "read_cpu_times",
                            lambda _p=None: next(readings, (3000, 700)))
        stops = iter([False, False, True, True])
        out = temp_dir / "util.csv"
        n = sample_loop(out, 0.01, lambda: next(stops, True), load_path=load)
        assert n == 2
        rows = out.read_text(encoding="utf-8").strip().split("\n")
        assert rows[0] == "t_wall,rho,loadavg"
        assert float(rows[1].split(",")[1]) == pytest.approx(1.0), "no idle time elapsed"
        assert float(rows[2].split(",")[2]) == pytest.approx(4.0)


class TestMain:
    def test_refuses_on_a_platform_without_proc(self, monkeypatch, capsys, temp_dir):
        monkeypatch.setattr(util_sampler, "PROC_STAT", temp_dir / "absent")
        assert main(["--out", str(temp_dir / "u.csv")]) == 2
        assert "cannot measure utilisation" in capsys.readouterr().out

    def test_runs_for_a_bounded_duration(self, monkeypatch, capsys, temp_dir):
        monkeypatch.setattr(util_sampler, "PROC_STAT", _stat(temp_dir))
        monkeypatch.setattr(util_sampler, "sample_loop",
                            lambda out, interval, stop, **kw: 7)
        registered = []
        monkeypatch.setattr(util_sampler.signal, "signal",
                            lambda s, h: registered.append((s, h)))
        out = temp_dir / "u.csv"
        assert main(["--out", str(out), "--duration", "0.01"]) == 0
        assert "wrote 7 utilisation samples" in capsys.readouterr().out
        assert len(registered) == 2, "SIGINT and SIGTERM must both be handled"

    def test_signal_handler_stops_the_loop(self, monkeypatch, temp_dir):
        """The handler must flip the flag the loop's stop() consults."""
        monkeypatch.setattr(util_sampler, "PROC_STAT", _stat(temp_dir))
        handlers = {}
        monkeypatch.setattr(util_sampler.signal, "signal",
                            lambda s, h: handlers.setdefault(s, h))
        captured = {}

        def fake_loop(out, interval, stop, **kw):
            captured["before"] = stop()
            handlers[util_sampler.signal.SIGTERM](None, None)
            captured["after"] = stop()
            return 0

        monkeypatch.setattr(util_sampler, "sample_loop", fake_loop)
        assert main(["--out", str(temp_dir / "u.csv")]) == 0
        assert captured == {"before": False, "after": True}
