"""Tests for scripts/schedstat_sampler.py - target >=95% branch coverage.

This collector runs on Linux and reads /proc, but the test suite must pass on Windows too, so
/proc is faked through the module's PROC path. That is not a shortcut: the failure this sampler
most needs to avoid is recording plausible-looking zeros when kernel.sched_schedstats is off,
and a fake tree is the only way to exercise both states deterministically.
"""
from pathlib import Path
import csv
import sys

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import schedstat_sampler as ss  # noqa: E402
from schedstat_sampler import (  # noqa: E402
    schedstats_enabled,
    matching_pids,
    read_task_schedstat,
    sample_once,
    main,
)


@pytest.fixture
def fake_proc(temp_dir, monkeypatch):
    """A minimal /proc: sysctl flag, plus per-pid cmdline and task/*/schedstat."""
    root = temp_dir / "proc"
    (root / "sys/kernel").mkdir(parents=True)
    (root / "sys/kernel/sched_schedstats").write_text("1\n", encoding="utf-8")
    monkeypatch.setattr(ss, "PROC", root)
    return root


def _add_pid(root, pid, cmdline, threads):
    """threads: list of (on_cpu_ns, wait_ns, slices); a None entry writes a malformed file."""
    d = root / str(pid)
    (d / "task").mkdir(parents=True)
    (d / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode() + b"\0")
    for i, t in enumerate(threads):
        td = d / "task" / str(pid + i)
        td.mkdir()
        td.write_bytes(b"") if False else None
        (td / "schedstat").write_text(
            "malformed\n" if t is None else f"{t[0]} {t[1]} {t[2]}\n", encoding="utf-8")
    return d


class TestSchedstatsEnabled:
    def test_reads_one_as_enabled(self, fake_proc):
        assert schedstats_enabled() is True

    def test_reads_zero_as_disabled(self, fake_proc):
        (fake_proc / "sys/kernel/sched_schedstats").write_text("0\n", encoding="utf-8")
        assert schedstats_enabled() is False

    def test_missing_file_is_disabled_not_a_crash(self, temp_dir, monkeypatch):
        monkeypatch.setattr(ss, "PROC", temp_dir / "nothing")
        assert schedstats_enabled() is False


class TestMatchingPids:
    def test_finds_processes_by_cmdline(self, fake_proc):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py --run-id x", [(1, 2, 3)])
        _add_pid(fake_proc, 200, "python3 scripts/redis_consumer.py", [(4, 5, 6)])
        _add_pid(fake_proc, 300, "stress-ng --cpu 8", [(7, 8, 9)])
        got = sorted(matching_pids("kafka_producer|redis_consumer"))
        assert got == [100, 200]

    def test_excludes_the_sampler_itself(self, fake_proc):
        """Matching our own process would report the collector's occupancy, not the subject's."""
        _add_pid(fake_proc, 100, "python3 scripts/schedstat_sampler.py --pattern kafka_producer",
                 [(1, 2, 3)])
        assert matching_pids("kafka_producer") == []

    def test_ignores_non_numeric_entries(self, fake_proc):
        (fake_proc / "self").mkdir()
        (fake_proc / "uptime").write_text("123", encoding="utf-8")
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(1, 2, 3)])
        assert matching_pids("kafka_producer") == [100]

    def test_unreadable_cmdline_is_skipped(self, fake_proc):
        d = fake_proc / "999"
        (d / "task").mkdir(parents=True)      # no cmdline at all
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(1, 2, 3)])
        assert matching_pids("kafka_producer") == [100]

    def test_empty_cmdline_is_skipped(self, fake_proc):
        d = fake_proc / "888"
        (d / "task").mkdir(parents=True)
        (d / "cmdline").write_bytes(b"")      # kernel threads look like this
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(1, 2, 3)])
        assert matching_pids("kafka_producer") == [100]


class TestReadTaskSchedstat:
    def test_sums_the_whole_thread_group(self, fake_proc):
        """A client library adds helper threads; occupancy of the group is what we want."""
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py",
                 [(10, 20, 3), (5, 7, 2), (1, 3, 1)])
        on_cpu, wait, slices, n = read_task_schedstat(100)
        assert (on_cpu, wait, slices, n) == (16, 30, 6, 3)

    def test_malformed_thread_files_are_skipped_not_fatal(self, fake_proc):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py",
                 [(10, 20, 3), None, (5, 7, 2)])
        on_cpu, wait, slices, n = read_task_schedstat(100)
        assert (on_cpu, wait, n) == (15, 27, 2)

    def test_short_lines_are_skipped(self, fake_proc):
        d = _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        (d / "task" / "101").mkdir()
        (d / "task" / "101" / "schedstat").write_text("1 2\n", encoding="utf-8")
        assert read_task_schedstat(100)[3] == 1

    def test_thread_that_exits_mid_read_is_skipped(self, fake_proc):
        """A task dir with no schedstat file: the thread died between listing and reading.
        Normal under load, and must not lose the siblings' counters."""
        d = _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        (d / "task" / "555").mkdir()          # no schedstat inside
        on_cpu, wait, slices, n = read_task_schedstat(100)
        assert (on_cpu, wait, n) == (10, 20, 1)

    def test_non_numeric_counters_are_skipped(self, fake_proc):
        """Three fields but not numbers: a kernel format change would look like this, and
        must not be summed as garbage."""
        d = _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        (d / "task" / "556").mkdir()
        (d / "task" / "556" / "schedstat").write_text("a b c\n", encoding="utf-8")
        on_cpu, wait, slices, n = read_task_schedstat(100)
        assert (on_cpu, wait, n) == (10, 20, 1)

    def test_missing_task_directory_returns_none(self, fake_proc):
        assert read_task_schedstat(4242) is None

    def test_unreadable_cmdline_raises_no_error(self, fake_proc):
        """A pid whose cmdline cannot be read at all must be skipped silently."""
        d = fake_proc / "777"
        d.mkdir()                              # no cmdline, no task dir
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(1, 2, 3)])
        assert matching_pids("kafka_producer") == [100]

    def test_all_threads_unreadable_returns_none(self, fake_proc):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [None])
        assert read_task_schedstat(100) is None


class TestSampleOnce:
    def test_one_row_per_matching_process(self, fake_proc):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        _add_pid(fake_proc, 200, "python3 scripts/kafka_consumer.py", [(1, 2, 1), (3, 4, 1)])
        rows = sorted(sample_once("kafka_"), key=lambda r: r["pid"])
        assert [r["pid"] for r in rows] == [100, 200]
        assert rows[1]["wait_ns"] == 6 and rows[1]["n_threads"] == 2

    def test_process_that_exits_between_listing_and_reading(self, fake_proc, monkeypatch):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        monkeypatch.setattr(ss, "read_task_schedstat", lambda pid: None)
        assert sample_once("kafka_") == []


class TestMain:
    def test_refuses_to_record_zeros_when_disabled(self, fake_proc, temp_dir, capsys):
        """The failure mode this guard exists for: a full run of plausible zeros."""
        (fake_proc / "sys/kernel/sched_schedstats").write_text("0\n", encoding="utf-8")
        rc = main(["--pattern", "kafka_", "--out", str(temp_dir / "o.csv")])
        assert rc == 1 and not (temp_dir / "o.csv").exists()
        assert "would read zero" in capsys.readouterr().out

    def test_allow_disabled_records_the_gap_explicitly(self, fake_proc, temp_dir, capsys,
                                                       monkeypatch):
        (fake_proc / "sys/kernel/sched_schedstats").write_text("0\n", encoding="utf-8")
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(0, 0, 0)])
        monkeypatch.setattr(ss.time, "sleep", lambda *_: None)
        calls = {"n": 0}
        real = ss.sample_once

        def once(pattern):
            calls["n"] += 1
            if calls["n"] > 1:
                raise KeyboardInterrupt
            return real(pattern)
        monkeypatch.setattr(ss, "sample_once", once)
        try:
            main(["--pattern", "kafka_", "--out", str(temp_dir / "o.csv"),
                  "--allow-disabled", "--interval", "0.01"])
        except KeyboardInterrupt:
            pass
        rows = list(csv.DictReader(open(temp_dir / "o.csv")))
        assert rows and rows[0]["schedstats_enabled"] == "0"
        assert "disabled" in capsys.readouterr().out

    def test_writes_samples_and_stops_on_signal(self, fake_proc, temp_dir, monkeypatch):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(10, 20, 3)])
        monkeypatch.setattr(ss.time, "sleep", lambda *_: None)
        state = {"n": 0, "stop": None}
        real_signal = ss.signal.signal

        def fake_signal(sig, handler):
            state["stop"] = handler
            return real_signal(sig, handler) if False else None
        monkeypatch.setattr(ss.signal, "signal", fake_signal)
        real = ss.sample_once

        def once(pattern):
            state["n"] += 1
            rows = real(pattern)
            if state["n"] >= 2:
                state["stop"](None, None)     # simulate SIGTERM after two sweeps
            return rows
        monkeypatch.setattr(ss, "sample_once", once)
        rc = main(["--pattern", "kafka_", "--out", str(temp_dir / "o.csv"), "--interval", "0.01"])
        rows = list(csv.DictReader(open(temp_dir / "o.csv")))
        assert rc == 0 and len(rows) == 2
        assert rows[0]["wait_ns"] == "20" and rows[0]["schedstats_enabled"] == "1"

    def test_survives_a_platform_without_signal_handlers(self, fake_proc, temp_dir, monkeypatch):
        _add_pid(fake_proc, 100, "python3 scripts/kafka_producer.py", [(1, 2, 3)])
        monkeypatch.setattr(ss.time, "sleep", lambda *_: None)
        monkeypatch.setattr(ss.signal, "signal",
                            lambda *_: (_ for _ in ()).throw(ValueError("not main thread")))
        state = {"n": 0}
        real = ss.sample_once

        def once(pattern):
            state["n"] += 1
            if state["n"] > 1:
                raise KeyboardInterrupt
            return real(pattern)
        monkeypatch.setattr(ss, "sample_once", once)
        with pytest.raises(KeyboardInterrupt):
            main(["--pattern", "kafka_", "--out", str(temp_dir / "o.csv"), "--interval", "0.01"])
        assert (temp_dir / "o.csv").exists()
