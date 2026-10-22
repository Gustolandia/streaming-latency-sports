"""Tests for client_quiet.py: freeze 43's three switches for the four Python clients.

Freeze 42's pilot found every client paused for 17-84 ms at about 24, 34, 46 and 60 s into each
70-s run, longer each time, at gaps each about 1.2 times the last: CPython's full collections over
the objects the clients keep for every message. --gc-off switches the collector off once a client
has its connection, --gc-log logs any collection that still happens, and --schedstat samples the
requesting thread's scheduler counters just before each request.

Every test here puts the interpreter's collector back as it found it: --gc-off freezes every
object in the process and switches the collector off, and the rest of the suite runs in this
process too. The counters are read from a file standing in for /proc/thread-self/schedstat, and
where the system has no os.pread (Windows) a seek and a read stand in for it, so that every test
runs the same way on both systems; one test reads the kernel's own counters where it has them.
"""
import argparse
import csv
import gc
import json
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import client_quiet  # noqa: E402


def _seek_and_read(fd, size, offset):
    """os.pread where the system has none: a seek and a read do the same on a descriptor that
    nothing else reads."""
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, size)


@pytest.fixture(autouse=True)
def collector_restored():
    """Whatever a test does to the collector, it is put back: on, unfrozen, and with the hooks it
    had."""
    enabled, callbacks = gc.isenabled(), list(gc.callbacks)
    try:
        yield
    finally:
        gc.callbacks[:] = callbacks
        gc.unfreeze()
        if enabled:
            gc.enable()


@pytest.fixture
def counters(tmp_path, monkeypatch):
    """A file in the place of /proc/thread-self/schedstat, and os.pread wherever it is missing."""
    path = tmp_path / "schedstat"
    path.write_bytes(b"1000 200 3\n")
    monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(path))
    monkeypatch.setattr(os, "pread", getattr(os, "pread", _seek_and_read), raising=False)
    return path


def parse(argv):
    ap = argparse.ArgumentParser()
    client_quiet.add_arguments(ap)
    return ap.parse_args(argv)


def rows_of(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def record_of(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class TestTheSwitches:

    def test_none_is_on_unless_asked(self):
        args = parse([])
        assert (args.gc_off, args.gc_log, args.schedstat) == (False, None, None)

    def test_each_takes_what_it_names(self):
        args = parse(["--gc-off", "--gc-log", "g.json", "--schedstat", "s.csv"])
        assert (args.gc_off, args.gc_log, args.schedstat) == (True, "g.json", "s.csv")


class TestWithNoSwitchNothingChanges:
    """A run that asks for none of them is the run it was before freeze 43."""

    def test_the_collector_is_left_as_it_was_and_nothing_is_written(self, tmp_path, monkeypatch,
                                                                    capsys):
        monkeypatch.chdir(tmp_path)
        before = (gc.isenabled(), gc.get_freeze_count(), list(gc.callbacks))
        args = parse([])
        quiet = client_quiet.start(args)
        assert (gc.isenabled(), gc.get_freeze_count(), list(gc.callbacks)) == before
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert quiet.fd is None and client_quiet.taken(quiet) == []
        assert list(tmp_path.iterdir()) == []
        assert capsys.readouterr() == ("", "")


class TestTheCollectorOff:

    def test_it_collects_then_freezes_then_switches_off(self, monkeypatch):
        """In that order: the collection first, so that only what is alive is set aside, then the
        freeze, so that no later collection visits it, then the collector off."""
        calls = []
        monkeypatch.setattr(gc, "collect", lambda *a: calls.append("collect") or 0)
        monkeypatch.setattr(gc, "freeze", lambda: calls.append("freeze"))
        monkeypatch.setattr(gc, "disable", lambda: calls.append("disable"))
        quiet = client_quiet.start(parse(["--gc-off"]))
        assert calls == ["collect", "freeze", "disable"] and quiet.gc_off is True

    def test_after_it_no_collection_runs_however_much_is_made(self, tmp_path):
        path = tmp_path / "gc.json"
        args = parse(["--gc-off", "--gc-log", str(path)])
        quiet = client_quiet.start(args)
        assert not gc.isenabled()
        assert quiet.frozen == gc.get_freeze_count() > 0
        kept = [[i] for i in range(50000)]          # many times every generation's threshold
        client_quiet.finish(quiet, args)
        record = record_of(path)
        assert len(kept) == 50000
        assert record["gc_off"] is True and record["frozen"] == quiet.frozen
        assert record["collections"] == []

    def test_a_collection_asked_for_is_still_logged(self, tmp_path):
        path = tmp_path / "gc.json"
        args = parse(["--gc-off", "--gc-log", str(path)])
        quiet = client_quiet.start(args)
        before = time.time_ns()
        gc.collect()
        after = time.time_ns()
        client_quiet.finish(quiet, args)
        (logged,) = record_of(path)["collections"]
        assert logged["generation"] == 2
        assert before <= logged["start_ns"] <= logged["stop_ns"] <= after
        assert logged["collected"] >= 0 and logged["uncollectable"] == 0


class TestTheCollectionsLogged:

    def test_with_the_collector_on_each_collection_is_logged(self, tmp_path):
        gc.enable()
        path = tmp_path / "gc.json"
        args = parse(["--gc-log", str(path)])
        quiet = client_quiet.start(args)
        assert gc.isenabled() and quiet.gc_off is False
        kept = [[i] for i in range(50000)]
        client_quiet.finish(quiet, args)
        record = record_of(path)
        assert len(kept) == 50000
        assert record["gc_off"] is False and record["frozen"] == gc.get_freeze_count() == 0
        assert record["collections"], "fifty thousand new lists trip the youngest generation"
        for logged in record["collections"]:
            assert list(logged) == list(client_quiet.COLLECTION)
            assert logged["start_ns"] <= logged["stop_ns"]
            assert logged["generation"] in (0, 1, 2)

    def test_the_record_holds_what_the_reader_reads(self, tmp_path):
        path = tmp_path / "gc.json"
        args = parse(["--gc-log", str(path)])
        client_quiet.finish(client_quiet.start(args), args)
        record = record_of(path)
        assert list(record) == ["gc_off", "frozen", "collections", "count_at_finish", "stats",
                                "schedstat_unreadable"]
        assert len(record["count_at_finish"]) == len(gc.get_count())
        assert all(isinstance(n, int) for n in record["count_at_finish"])
        assert [sorted(s) for s in record["stats"]] == [sorted(s) for s in gc.get_stats()]
        assert record["schedstat_unreadable"] is None

    def test_the_hook_is_taken_out_at_the_finish(self, tmp_path):
        args = parse(["--gc-log", str(tmp_path / "gc.json")])
        quiet = client_quiet.start(args)
        hook = quiet.callback
        assert hook in gc.callbacks
        client_quiet.finish(quiet, args)
        logged = len(quiet.collections)
        gc.collect()
        assert hook not in gc.callbacks and quiet.callback is None
        assert len(quiet.collections) == logged

    def test_the_log_is_written_where_asked_its_folder_made(self, tmp_path, capsys):
        path = tmp_path / "run" / "deeper" / "producer_gc.json"
        args = parse(["--gc-off", "--gc-log", str(path)])
        quiet = client_quiet.start(args)
        client_quiet.finish(quiet, args)
        assert record_of(path)["gc_off"] is True
        assert ("OK collector: off, %d objects frozen, 0 collections logged -> %s"
                % (quiet.frozen, path)) in capsys.readouterr().out


class TestTheCounters:

    def test_a_sample_is_the_clock_then_the_files_three_integers(self, counters, tmp_path):
        out = tmp_path / "consumer_schedstat.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        before = time.time_ns()
        client_quiet.sample(quiet)
        after = time.time_ns()
        client_quiet.finish(quiet, args)
        header, row = rows_of(out)
        assert header == ["t_ns", "exec_ns", "delay_ns", "slices"] == client_quiet.COLUMNS
        assert before <= int(row[0]) <= after
        assert [int(v) for v in row[1:]] == [1000, 200, 3]

    def test_the_clock_is_read_just_before_the_counters_from_the_files_start(self, counters,
                                                                             monkeypatch):
        """t_ns is the moment before the read, and every read starts at offset 0 of the one
        descriptor opened at the start."""
        reads = []
        read_at = os.pread

        def pread(fd, size, offset):
            reads.append((time.time_ns(), fd, offset))
            return read_at(fd, size, offset)

        monkeypatch.setattr(os, "pread", pread)
        quiet = client_quiet.start(parse(["--schedstat", "unused.csv"]))
        client_quiet.sample(quiet)
        client_quiet.sample(quiet)
        samples = client_quiet.taken(quiet)
        os.close(quiet.fd)
        assert [(fd, offset) for _, fd, offset in reads] == [(quiet.fd, 0), (quiet.fd, 0)]
        assert all(s[0] <= r[0] for s, r in zip(samples, reads))

    def test_the_threads_runtime_is_brought_up_to_date_before_each_read(self, counters,
                                                                      monkeypatch):
        """Read alone, the file shows the thread's runtime as of the last tick or switch, and the
        change between two samples was the burst of work before the earlier one. Asked for the
        thread's processor time, the kernel first brings it up to date."""
        order = []
        cpu, pread = time.thread_time_ns, os.pread
        monkeypatch.setattr(time, "thread_time_ns", lambda: order.append("cpu") or cpu())
        monkeypatch.setattr(os, "pread", lambda *a: order.append("read") or pread(*a))
        quiet = client_quiet.start(parse(["--schedstat", "unused.csv"]))
        client_quiet.sample(quiet)
        client_quiet.sample(quiet)
        os.close(quiet.fd)
        assert order == ["cpu", "read", "cpu", "read"]

    def test_each_sample_reads_the_file_again(self, counters, tmp_path):
        """Not a value read once and kept: the counters move, and each sample sees them where
        they are."""
        out = tmp_path / "s.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        client_quiet.sample(quiet)
        with open(counters, "r+b") as fh:
            fh.write(b"5000 600 7\n")
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        _, first, second = rows_of(out)
        assert [int(v) for v in first[1:]] == [1000, 200, 3]
        assert [int(v) for v in second[1:]] == [5000, 600, 7]
        assert int(first[0]) <= int(second[0])

    def test_the_descriptor_is_opened_once_and_closed_at_the_finish(self, counters, tmp_path,
                                                                     monkeypatch):
        opened = []
        open_fd = os.open
        monkeypatch.setattr(os, "open", lambda *a: opened.append(a[0]) or open_fd(*a))
        args = parse(["--schedstat", str(tmp_path / "s.csv")])
        quiet = client_quiet.start(args)
        fd = quiet.fd
        for _ in range(3):
            client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert opened == [str(counters)]
        assert quiet.fd is None
        with pytest.raises(OSError):
            os.fstat(fd)

    def test_without_the_switch_a_sample_reads_nothing(self, counters, monkeypatch):
        monkeypatch.setattr(os, "pread", lambda *a: pytest.fail("read without --schedstat"),
                            raising=False)
        quiet = client_quiet.start(parse([]))
        client_quiet.sample(quiet)
        assert quiet.fd is None and client_quiet.taken(quiet) == []

    def test_the_blocks_are_made_before_the_loop_and_one_more_when_they_are_full(
            self, counters, tmp_path, monkeypatch):
        """A block, once made, never moves: the samples fill the blocks made at the start, in
        order, and a run that fills them all is given one more block at a time."""
        monkeypatch.setattr(client_quiet, "BLOCK", 2)
        monkeypatch.setattr(client_quiet, "BLOCKS", 2)
        out = tmp_path / "s.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        assert [list(b) for b in quiet.blocks] == [[0] * 8, [0] * 8]
        made = list(quiet.blocks)
        for _ in range(5):
            client_quiet.sample(quiet)
        assert quiet.blocks[:2] == made and all(a is b for a, b in zip(quiet.blocks, made))
        assert len(quiet.blocks) == 3
        client_quiet.finish(quiet, args)
        rows = rows_of(out)[1:]
        assert len(rows) == 5
        assert [int(r[0]) for r in rows] == sorted(int(r[0]) for r in rows)
        assert all([int(v) for v in r[1:]] == [1000, 200, 3] for r in rows)

    def test_a_read_that_gives_nothing_usable_is_counted_not_raised(self, counters, tmp_path,
                                                                    capsys):
        out = tmp_path / "s.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        for broken in (b"x y z\n", b"1 2\n"):
            quiet.pread = lambda fd, size, offset, text=broken: text
            client_quiet.sample(quiet)

        def refused(*_):
            raise OSError("the thread has gone")

        quiet.pread = refused
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert quiet.missed == 3 and rows_of(out) == [client_quiet.COLUMNS]
        assert "OK schedstat: 0 samples, 3 unreadable -> %s" % out in capsys.readouterr().out

    def test_the_csv_is_written_where_asked_its_folder_made(self, counters, tmp_path, capsys):
        out = tmp_path / "run" / "consumer_schedstat.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        client_quiet.sample(quiet)
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert len(rows_of(out)) == 3
        assert "OK schedstat: 2 samples, 0 unreadable -> %s" % out in capsys.readouterr().out


class TestWhereThereAreNoCounters:
    """Windows, or a kernel without them: the run goes on and says why."""

    def test_a_file_that_cannot_be_opened_leaves_the_header_and_the_reason(
            self, counters, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(client_quiet, "SCHEDSTAT", str(tmp_path / "absent" / "schedstat"))
        gc_path, out = tmp_path / "gc.json", tmp_path / "s.csv"
        args = parse(["--gc-log", str(gc_path), "--schedstat", str(out)])
        quiet = client_quiet.start(args)
        said = capsys.readouterr().err
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert quiet.fd is None and "absent" in quiet.unreadable
        assert "no scheduler counters to sample (%s)" % quiet.unreadable in said
        assert "header alone" in said
        assert rows_of(out) == [client_quiet.COLUMNS]
        assert record_of(gc_path)["schedstat_unreadable"] == quiet.unreadable

    def test_a_system_without_pread_is_treated_alike_and_opens_nothing(self, counters, tmp_path,
                                                                      monkeypatch, capsys):
        monkeypatch.delattr(os, "pread", raising=False)
        monkeypatch.setattr(os, "open", lambda *a: pytest.fail("opened without os.pread"))
        out = tmp_path / "s.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        assert quiet.fd is None and "pread" in quiet.unreadable
        assert "pread" in capsys.readouterr().err
        assert rows_of(out) == [client_quiet.COLUMNS]

    def test_the_kernels_own_counters_where_the_system_has_them(self, tmp_path):
        """The module's own path, unchanged. On Linux the thread's counters move while it runs;
        on a system without them the run goes on with none."""
        out = tmp_path / "s.csv"
        args = parse(["--schedstat", str(out)])
        quiet = client_quiet.start(args)
        client_quiet.sample(quiet)
        busy_until = time.perf_counter() + 0.05      # fifty ticks at 1000 Hz, a dozen at 250
        while time.perf_counter() < busy_until:
            pass
        client_quiet.sample(quiet)
        client_quiet.finish(quiet, args)
        rows = [[int(v) for v in r] for r in rows_of(out)[1:]]
        if os.path.exists(client_quiet.SCHEDSTAT) and hasattr(os, "pread"):
            first, second = rows
            assert second[0] > first[0] and second[1] > first[1] > 0
            assert second[2] >= first[2] and second[3] >= first[3] >= 1
        else:
            assert rows == [] and quiet.unreadable
