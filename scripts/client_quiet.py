#!/usr/bin/env python3
"""
client_quiet.py -- the interpreter's collector kept out of a benchmark client's run, and the time
the requesting thread spends between two requests split three ways: the switches freeze 43 (plan
version 46) gives the four Python clients.

In freeze 42's pilot every client paused for 17-84 ms at about 24, 34, 46 and 60 s into each 70-s
run, longer each time, at gaps each about 1.2 times the last. CPython's full collection does that.
It waits until the long-lived objects have grown by a quarter since the last one, and then visits
every one of them; and the clients keep objects for every message, in the socket timestamps'
ledger (scripts/so_timestamps.py) and in the producers' rows, for about 140,000 messages in a run
at 2,000 a second. So each full collection comes later and lasts longer than the one before, and
those pauses decide part of the latency's tail. A run can now ask for:

  --gc-off          once the client's connection exists and before its loop: one collection,
                    every object then alive set aside where no collection looks (gc.freeze),
                    and the collector off;
  --gc-log PATH     every collection that still happens, with its generation, start and end,
                    written to PATH as JSON at the end;
  --schedstat PATH  (the consumers) just before each request to the broker, the requesting
                    thread's three counters from /proc/thread-self/schedstat: its time on a
                    processor, its time ready but waiting for one, and how many times it was
                    given one; written to PATH as CSV at the end.

Between two samples the thread's wall time is then the time it ran, the time it waited for a
processor, and the rest, when it was blocked. Every time here is time.time_ns(), which is
clock_gettime(CLOCK_REALTIME) on Linux: the clock of the clients' own stamps and of the kernel's
socket timestamps that the journals hold.

    import client_quiet
    client_quiet.add_arguments(ap)
    quiet = client_quiet.start(args)       # the connection made, the loop not yet begun
    ...
        client_quiet.sample(quiet)         # just before each request
    client_quiet.finish(quiet, args)

Where the counters cannot be read, as on Windows or on a kernel without them, the run goes on:
the CSV holds its header alone, and the reason is in the client's log and in the GC JSON.
"""
import array
import csv
import gc
import json
import os
import sys
import time

#: The calling thread's own counters. /proc/thread-self names the thread that opens it, and the
#: descriptor goes on reading that thread whichever thread reads it, so start() is called from
#: the thread that issues the requests. A module constant, so the tests can point it elsewhere.
#:
#: The first counter, read by the running thread about itself, is the kernel's total as of its
#: last accounting update, made at each tick, switch, and wake-up of another task on its
#: processor: in a loop that never blocked it changed 250 times a second on a CONFIG_HZ=250
#: kernel, standing still 4,000 us at the median (Ubuntu 22.04 under WSL, 22 Oct 2026). The tick
#: is 1 ms on the testbed's CONFIG_HZ=1000. sample() therefore has it brought up to date first;
#: the other two are added as the thread is given a processor, and are current whenever it reads
#: them.
SCHEDSTAT = "/proc/thread-self/schedstat"

#: More than a line of three 20-digit numbers needs.
LINE = 256

#: The CSV's columns, and the JSON's for each collection.
COLUMNS = ["t_ns", "exec_ns", "delay_ns", "slices"]
COLLECTION = ("generation", "start_ns", "stop_ns", "collected", "uncollectable")

#: Samples per block, and the blocks made before the loop. An array that grows as it fills is
#: copied whole each time it outgrows its allocation: over 200,000 samples the slowest single
#: append took 1.6-1.7 ms (Python 3.10.12, Ubuntu 22.04 under WSL), and it would fall inside the
#: turnaround being sampled. A block made once never moves. Sixteen blocks of 16,384 hold 262,144 samples,
#: over three times the 73,708 requests one of freeze 42's pilot consumers made at 2,000 messages
#: a second; a run that fills them all is given one more block at a time.
BLOCK = 1 << 14
BLOCKS = 16


class Quiet(object):
    """What start() set up: read by sample() before every request and by finish() once."""

    def __init__(self):
        self.gc_off = False
        self.frozen = 0
        self.collections = []
        self.callback = None
        self.fd = None
        self.pread = None
        self.unreadable = None
        self.blocks = []
        self.used = 0
        self.block = array.array("q")
        self.at = 0
        self.missed = 0


def add_arguments(ap):
    """The clients' three switches, the same in all four."""
    ap.add_argument("--gc-off", action="store_true",
                    help="once connected and before the loop, collect once, freeze every object "
                         "then alive and switch the collector off")
    ap.add_argument("--gc-log", default=None,
                    help="log every collection that still happens, and write them to this JSON")
    ap.add_argument("--schedstat", default=None,
                    help="just before each request, sample the requesting thread's scheduler "
                         "counters, and write them to this CSV (the consumers)")


def start(args):
    """Apply what the run asked for, and return the state sample() and finish() take. Called once
    the client's connection exists and before its loop, from the thread that issues its requests.
    With none of the switches it changes nothing."""
    quiet = Quiet()
    if args.gc_off:
        gc.collect()
        gc.freeze()
        gc.disable()
        quiet.gc_off = True
    quiet.frozen = gc.get_freeze_count()
    if args.gc_log:
        # After the collection above, so that the log holds only what still happens.
        quiet.callback = _logger(quiet.collections)
        gc.callbacks.append(quiet.callback)
    if args.schedstat:
        _open(quiet)
    return quiet


def _logger(collections):
    """A gc.callbacks hook keeping (generation, start, stop, collected, uncollectable) for each
    collection, in whichever thread it runs: a collection runs in the thread that triggers it,
    holding the interpreter lock, so a start is always followed by its own stop."""
    began = 0

    def log(phase, info):
        nonlocal began
        if phase == "start":
            began = time.time_ns()
        else:
            stopped = time.time_ns()
            collections.append((info["generation"], began, stopped, info["collected"],
                                info["uncollectable"]))
    return log


def _open(quiet):
    """The descriptor sample() reads, kept open for the run, and the blocks the samples go into;
    where there is no descriptor to open, the reason, in the client's log now and in the outputs
    at the end."""
    try:
        quiet.pread = os.pread
        quiet.fd = os.open(SCHEDSTAT, os.O_RDONLY)
    except (AttributeError, OSError) as exc:
        quiet.unreadable = str(exc)
        print("client_quiet: no scheduler counters to sample (%s); the schedstat CSV will hold "
              "its header alone" % exc, file=sys.stderr, flush=True)
        return
    quiet.blocks = [array.array("q", bytes(32 * BLOCK)) for _ in range(BLOCKS)]
    quiet.block = quiet.blocks[0]


def sample(quiet):
    """One sample of the counters, just before a request: the wall clock, then the file's three
    integers, read again from its start through the descriptor kept open. Without --schedstat,
    or where there are no counters, nothing. A read that gives nothing usable is counted, not
    raised: an instrument may not stop the run it measures."""
    if quiet.fd is None:
        return
    # Asked for this thread's processor time, the kernel first brings its runtime up to date,
    # which the file alone shows as of the last tick, switch or wake-up. Without this, the change
    # in exec_ns between two samples was the burst of work before the earlier sample, not the one
    # between them: 400 us of work read as 65 us and 50 us as 417 us, at the median of 1,000
    # each; with it, 417 us and 67 us (Python 3.10.12, Ubuntu 22.04 under WSL, 22 Oct 2026).
    time.thread_time_ns()
    t_ns = time.time_ns()
    try:
        exec_ns, delay_ns, slices = quiet.pread(quiet.fd, LINE, 0).split()[:3]
        row = (t_ns, int(exec_ns), int(delay_ns), int(slices))
    except (OSError, ValueError):
        quiet.missed += 1
        return
    at = quiet.at
    if at == len(quiet.block):
        _next_block(quiet)
        at = 0
    block = quiet.block
    block[at], block[at + 1], block[at + 2], block[at + 3] = row
    quiet.at = at + 4


def _next_block(quiet):
    """Move to the next block, made now if every block made before the loop is full."""
    quiet.used += 1
    if quiet.used == len(quiet.blocks):
        quiet.blocks.append(array.array("q", bytes(32 * BLOCK)))
    quiet.block = quiet.blocks[quiet.used]
    quiet.at = 0


def taken(quiet):
    """Every sample taken, in order, as (t_ns, exec_ns, delay_ns, slices)."""
    values = array.array("q")
    for block in quiet.blocks[:quiet.used]:
        values.extend(block)
    values.extend(quiet.block[:quiet.at])
    return [tuple(values[i:i + 4]) for i in range(0, len(values), 4)]


def finish(quiet, args):
    """Take the hook out and close the descriptor, then write what the run asked for, and say so
    in the client's log."""
    if quiet.callback is not None:
        gc.callbacks.remove(quiet.callback)
        quiet.callback = None
    if quiet.fd is not None:
        os.close(quiet.fd)
        quiet.fd = None
    if args.gc_log:
        _folder(args.gc_log)
        record = {"gc_off": quiet.gc_off, "frozen": quiet.frozen,
                  "collections": [dict(zip(COLLECTION, c)) for c in quiet.collections],
                  "count_at_finish": list(gc.get_count()), "stats": gc.get_stats(),
                  "schedstat_unreadable": quiet.unreadable}
        with open(args.gc_log, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2)
            fh.write("\n")
        print("OK collector: %s, %d objects frozen, %d collections logged -> %s"
              % ("off" if quiet.gc_off else "on", quiet.frozen, len(quiet.collections),
                 args.gc_log), flush=True)
    if args.schedstat:
        rows = taken(quiet)
        _folder(args.schedstat)
        with open(args.schedstat, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(COLUMNS)
            w.writerows(rows)
        print("OK schedstat: %d samples, %d unreadable -> %s"
              % (len(rows), quiet.missed, args.schedstat), flush=True)


def _folder(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
