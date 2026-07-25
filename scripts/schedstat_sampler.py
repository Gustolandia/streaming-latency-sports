#!/usr/bin/env python3
"""
schedstat_sampler.py
Measure stamping-thread occupancy directly, instead of inferring it from the inversion rate.

The two-state model says an inversion happens when the thread that reads the clock is not
running. Until now `p`, the fraction of time it is not running, has been INFERRED by inverting
the model itself: p = (rate - C0) / (S - C0). That is circular in the way that matters -- it
cannot disagree with the model it came from, so it is a consistency check and nothing more. A
referee is entitled to say so.

The kernel already counts the quantity we want. `/proc/<pid>/schedstat` exposes three cumulative
figures per task, provided `kernel.sched_schedstats` is enabled:

    field 1  time spent running on the CPU            (ns)
    field 2  time spent waiting on a run queue        (ns)   <- runnable but NOT running
    field 3  timeslices run

Field 2 is exactly the state the model blames. Sampling it across a run turns `p` from something
derived from the inversion rate into something measured beside it, so the two can be compared
rather than one being defined by the other.

WHAT IS RECORDED, AND WHAT IS NOT. This writes raw deltas -- on-CPU, wait, timeslices, and the
wall interval -- and computes no occupancy ratio. There is more than one defensible definition:

    wait / wall              fraction of wall time spent runnable-but-waiting
    wait / (wait + on_cpu)   fraction of the time it WANTED the CPU that it had to wait

and our stamping processes sleep most of the time waiting for sparse events, so the two differ by
a lot and the second is the one the model is about. Choosing between them is an analysis
decision, and baking it into the collector would hide it. The analysis picks; this records.

CAVEAT WE CANNOT REMOVE. schedstat is per-task, and a Python producer using a client library has
helper threads. We sample the whole thread group by walking /proc/<pid>/task/*, and record the
thread count so a reader can see how much aggregation happened.

CLI:
    python scripts/schedstat_sampler.py --pattern "kafka_producer|redis_producer" \
        --out runs/schedstat.csv --interval 0.5
"""
import argparse
import csv
import os
import re
import signal
import sys
import time
from pathlib import Path

PROC = Path("/proc")


def schedstats_enabled():
    """Zero here means every field below reads 0.0 and the whole run is silently useless."""
    try:
        return (PROC / "sys/kernel/sched_schedstats").read_text().strip() == "1"
    except OSError:
        return False


def matching_pids(pattern):
    """PIDs whose cmdline matches, excluding this sampler itself."""
    rx = re.compile(pattern)
    me = os.getpid()
    out = []
    for entry in PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == me:
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except OSError:
            continue
        if cmd and rx.search(cmd) and "schedstat_sampler" not in cmd:
            out.append(pid)
    return out


def read_task_schedstat(pid):
    """Sum the thread group's counters. Returns (on_cpu_ns, wait_ns, slices, n_threads)."""
    on_cpu = wait = slices = 0
    n = 0
    task_dir = PROC / str(pid) / "task"
    try:
        tids = list(task_dir.iterdir())
    except OSError:
        return None
    for t in tids:
        try:
            parts = (t / "schedstat").read_text().split()
        except OSError:
            continue           # thread exited between listing and reading; normal, not an error
        if len(parts) < 3:
            continue
        try:
            on_cpu += int(parts[0]); wait += int(parts[1]); slices += int(parts[2])
        except ValueError:
            continue
        n += 1
    return (on_cpu, wait, slices, n) if n else None


def sample_once(pattern):
    """One observation per matching process."""
    rows = []
    for pid in matching_pids(pattern):
        st = read_task_schedstat(pid)
        if st is None:
            continue
        rows.append({"pid": pid, "on_cpu_ns": st[0], "wait_ns": st[1],
                     "slices": st[2], "n_threads": st[3]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pattern", required=True,
                    help="regex matched against /proc/<pid>/cmdline")
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--allow-disabled", action="store_true",
                    help="record anyway when sched_schedstats is off (fields will be zero)")
    args = ap.parse_args(argv)

    enabled = schedstats_enabled()
    if not enabled and not args.allow_disabled:
        print("FATAL: kernel.sched_schedstats is 0; every counter would read zero. "
              "Enable it or pass --allow-disabled to record the fact.")
        return 1
    if not enabled:
        print("WARNING: sched_schedstats disabled; recording zeros so the gap is visible")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    stop = {"now": False}

    def handle(_sig, _frm):
        stop["now"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle)
        except (ValueError, OSError):
            pass           # not on the main thread, or platform without it; loop still exits

    fields = ["t_wall_ns", "pid", "on_cpu_ns", "wait_ns", "slices", "n_threads",
              "schedstats_enabled"]
    n = 0
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        while not stop["now"]:
            t = time.time_ns()
            for row in sample_once(args.pattern):
                row.update({"t_wall_ns": t, "schedstats_enabled": int(enabled)})
                w.writerow(row)
                n += 1
            fh.flush()
            # Sleep in slices so SIGTERM is honoured promptly rather than after a full interval.
            slept = 0.0
            while slept < args.interval and not stop["now"]:
                time.sleep(min(0.1, args.interval - slept))
                slept += 0.1
    print(f"wrote {n} samples to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
