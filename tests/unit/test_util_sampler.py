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


class TestWhatHeldTheMachine:
    """A load that is not the load we set is a fault, and a fault should leave its cause behind."""

    def fake_proc(self, tmp_path, pids):
        """A /proc with one folder per process, as Linux lays it out."""
        proc = tmp_path / "proc"
        proc.mkdir(exist_ok=True)
        for pid, (name, utime, stime) in pids.items():
            where = proc / str(pid)
            where.mkdir(exist_ok=True)
            #: the line is "pid (name) state ppid ...", and utime and stime are the twelfth and
            #: thirteenth fields after the state, which is where the sampler reads them
            fields = ["0"] * 20
            fields[10], fields[11] = str(utime), str(stime)
            (where / "stat").write_text("%s (%s) S %s\n" % (pid, name, " ".join(fields)),
                                        encoding="utf-8")
        return proc

    def test_it_reads_each_process_and_the_time_it_has_used(self, tmp_path):
        proc = self.fake_proc(tmp_path, {7: ("stress-ng-cpu", 100, 20), 9: ("python3", 5, 1)})
        found = util_sampler.process_times(proc)
        assert found["7"] == ("stress-ng-cpu", 120) and found["9"] == ("python3", 6)

    def test_a_process_that_ends_while_it_is_read_is_not_our_business(self, tmp_path):
        proc = self.fake_proc(tmp_path, {7: ("stress-ng-cpu", 100, 20)})
        (proc / "8").mkdir()
        (proc / "notapid").mkdir()
        assert sorted(util_sampler.process_times(proc)) == ["7"]

    def test_a_machine_with_no_proc_at_all_says_nothing(self, tmp_path):
        assert util_sampler.process_times(tmp_path / "nowhere") == {}

    def test_the_busiest_are_the_ones_that_grew_most(self):
        before = {"1": ("a", 10), "2": ("b", 10), "3": ("c", 10)}
        after = {"1": ("a", 60), "2": ("b", 20), "3": ("c", 10), "4": ("d", 99)}
        found = util_sampler.busiest(before, after, kept=2)
        assert [name for _, _, name in found] == ["a", "b"]
        assert found[0][0] == 50, "and by how much"

    def moving_times(self, monkeypatch):
        """A machine whose processor time keeps climbing, so every sample has a utilisation."""
        ticks = {"n": 0}

        def moving(_path=None):
            ticks["n"] += 1
            return (1000 * ticks["n"], 100 * ticks["n"])
        monkeypatch.setattr(util_sampler, "read_cpu_times", moving)
        monkeypatch.setattr(util_sampler.time, "sleep", lambda _s: None)

    def test_it_is_written_down_beside_the_utilisation(self, tmp_path, monkeypatch):
        self.moving_times(monkeypatch)
        load = tmp_path / "loadavg"
        load.write_text("5.0 4.0 3.0 2/300 1\n", encoding="utf-8")
        proc = self.fake_proc(tmp_path, {7: ("stress-ng-cpu", 1, 0)})
        stops = {"n": 0}

        def stop():
            stops["n"] += 1
            if stops["n"] > 2:
                return True
            self.fake_proc(tmp_path, {7: ("stress-ng-cpu", 500 * stops["n"], 0)})
            return False
        util_sampler.sample_loop(tmp_path / "util.csv", 0.0, stop, tmp_path / "stat", load,
                                 proc, busiest_every=1)
        rows = (tmp_path / "util_busiest.csv").read_text(encoding="utf-8").splitlines()
        assert rows[0] == "t_wall,pid,name,jiffies"
        assert any("stress-ng-cpu" in row for row in rows[1:])

    def test_it_can_be_asked_not_to_look_at_all(self, tmp_path, monkeypatch):
        self.moving_times(monkeypatch)
        load = tmp_path / "loadavg"
        load.write_text("5.0 4.0 3.0 2/300 1\n", encoding="utf-8")
        stops = {"n": 0}

        def stop():
            stops["n"] += 1
            return stops["n"] > 2
        util_sampler.sample_loop(tmp_path / "u.csv", 0.0, stop, tmp_path / "stat", load,
                                 tmp_path / "proc", busiest_every=0)
        assert (tmp_path / "u_busiest.csv").read_text(encoding="utf-8").strip() == \
            "t_wall,pid,name,jiffies"


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
