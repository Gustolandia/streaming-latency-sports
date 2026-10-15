#!/usr/bin/env python3
"""
util_sampler.py
Sample CPU utilisation and run-queue length while an experiment runs.

Experiment E-A tests whether measurement failure follows scheduler waiting time (hypothesis H2
in docs/measurement_model.md), which is a claim about utilisation rho. We therefore have to
*measure* rho rather than infer it from how many stress workers we started: the nominal setting
and the achieved utilisation are not the same number, especially near saturation, and reporting
the nominal one would beg the question the experiment exists to answer.

Reads /proc/stat for utilisation and /proc/loadavg for runnable-thread count. Both are Linux
interfaces; on other platforms the sampler reports that it cannot measure and exits non-zero
rather than emitting a plausible-looking guess.

CLI:
    python scripts/util_sampler.py --out util.csv --interval 0.5 &
    ...run the experiment...
    kill %1
"""
import argparse
import csv
import signal
import sys
import time
from pathlib import Path

PROC_STAT = Path("/proc/stat")
PROC_LOADAVG = Path("/proc/loadavg")
PROC = Path("/proc")
#: How often the busiest processes are written down, in samples, and how many of them. A load that
#: is not the load we set is a fault, and a fault should leave behind what caused it.
BUSIEST_EVERY = 60
BUSIEST_KEPT = 6
#: Freeze 41 (15 Oct 2026): the clients' own processes, by a word of their command line. At 500 and
#: 5,000 messages a second the clients use several points of the machine, which the integrity
#: rule's load check counted as background load: the pilot's idle Kafka run at 500 a second read
#: 7.1% against 0%. Their share is now written beside the machine's, so that the load the run set
#: can be read without them.
CLIENT_MARKS = ("kafka_producer.py", "kafka_consumer.py", "redis_producer.py",
                "redis_consumer.py", "LawProducer", "LawConsumer")
#: How often, in samples, the clients' processes are looked for again: they start after the
#: sampler does.
CLIENT_SCAN_EVERY = 4


def read_cpu_times(path=PROC_STAT):
    """Total and idle jiffies from the aggregate 'cpu' line of /proc/stat.

    Fields are: user nice system idle iowait irq softirq steal guest guest_nice. Idle time for
    utilisation purposes is idle + iowait, since a thread waiting on IO is not occupying the CPU.
    """
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("cpu "):
                parts = [int(v) for v in line.split()[1:]]
                total = sum(parts)
                idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                return total, idle
    raise ValueError(f"no aggregate cpu line in {path}")


def read_loadavg(path=PROC_LOADAVG):
    """One-minute load average: the number of runnable-or-waiting threads."""
    with open(path, encoding="utf-8") as fh:
        return float(fh.read().split()[0])


def utilisation(prev, cur):
    """Fraction of CPU time that was not idle between two /proc/stat readings.

    Returns None when no jiffies elapsed, which happens if the sampling interval is shorter
    than the kernel's accounting granularity. Silently reporting 0.0 there would put spurious
    low-utilisation points into the H2 fit.
    """
    d_total = cur[0] - prev[0]
    d_idle = cur[1] - prev[1]
    if d_total <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - d_idle / d_total))


def process_times(proc=PROC):
    """{pid: (name, processor time in jiffies)} for every process that is still there.

    Read from /proc itself: a sampler that needed another program to be installed would be one
    more thing to go wrong on a machine we cannot log into while it is busy.
    """
    found = {}
    try:
        entries = list(proc.iterdir())
    except OSError:
        return found  # no /proc here: the sampler says so elsewhere and this adds nothing
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="utf-8").rsplit(") ", 1)
            name = fields[0].split("(", 1)[1]
            rest = fields[1].split()
            found[entry.name] = (name, int(rest[11]) + int(rest[12]))
        except (OSError, ValueError, IndexError):
            continue  # it ended while we were reading it, which is not our business
    return found


def client_pids(proc=PROC, marks=CLIENT_MARKS):
    """The ids of the processes whose command line names one of the clients."""
    found = set()
    try:
        entries = list(proc.iterdir())
    except OSError:
        return found  # no /proc here, as in process_times
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            line = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8",
                                                                                 "replace")
        except OSError:
            continue  # it ended while we were reading it
        if any(mark in line for mark in marks):
            found.add(entry.name)
    return found


def jiffies_of(pids, proc=PROC):
    """{pid: processor time in jiffies} for those of `pids` that are still there."""
    found = {}
    for pid in pids:
        try:
            rest = (proc / pid / "stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
            found[pid] = int(rest[11]) + int(rest[12])
        except (OSError, ValueError, IndexError):
            continue
    return found


def busiest(before, after, kept=BUSIEST_KEPT):
    """The processes that used the most processor time between two readings."""
    grew = []
    for pid, (name, ticks) in after.items():
        was = before.get(pid)
        if was is not None and ticks > was[1]:
            grew.append((ticks - was[1], pid, name))
    grew.sort(reverse=True)
    return grew[:kept]


def sample_loop(out_path, interval, stop, stat_path=PROC_STAT, load_path=PROC_LOADAVG,
                proc=PROC, busiest_every=BUSIEST_EVERY):
    """Append utilisation samples until `stop()` returns True. Returns the number written.

    Every `busiest_every` samples it also writes down the processes that used the most processor
    time since the last such look, beside the utilisation, so that a load which is not the load we
    set can be explained afterwards rather than guessed at.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    who_path = out_path.with_name(out_path.stem + "_busiest.csv")
    prev = read_cpu_times(stat_path)
    seen = process_times(proc) if busiest_every else {}
    clients, client_seen, looks = set(), {}, 0
    n = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh, \
            who_path.open("w", newline="", encoding="utf-8") as who_fh:
        w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg", "rho_clients"])
        w.writeheader()
        who = csv.DictWriter(who_fh, fieldnames=["t_wall", "pid", "name", "jiffies"])
        who.writeheader()
        while not stop():
            time.sleep(interval)
            cur = read_cpu_times(stat_path)
            rho = utilisation(prev, cur)
            elapsed = cur[0] - prev[0]
            prev = cur
            # The clients' share of the same interval: the processor time their processes used,
            # over all the machine's processor time. A process seen for the first time counts
            # from its next sample on.
            if looks % CLIENT_SCAN_EVERY == 0:
                clients |= client_pids(proc)
            looks += 1
            client_now = jiffies_of(clients, proc)
            used = sum(client_now[p] - client_seen[p] for p in client_now
                       if p in client_seen and client_now[p] >= client_seen[p])
            client_seen = client_now
            if rho is None:
                continue
            w.writerow({"t_wall": time.time(), "rho": round(rho, 5),
                        "loadavg": read_loadavg(load_path),
                        "rho_clients": round(min(1.0, used / float(elapsed)), 5)})
            fh.flush()
            n += 1
            if busiest_every and n % busiest_every == 0:
                now = process_times(proc)
                when = time.time()
                for ticks, pid, name in busiest(seen, now):
                    who.writerow({"t_wall": when, "pid": pid, "name": name, "jiffies": ticks})
                who_fh.flush()
                seen = now
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sample CPU utilisation during an experiment")
    ap.add_argument("--out", required=True)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--duration", type=float, default=0.0,
                    help="stop after this many seconds; 0 means run until signalled")
    args = ap.parse_args(argv)

    if not PROC_STAT.exists():
        print("cannot measure utilisation: /proc/stat is unavailable on this platform")
        return 2

    stopping = {"flag": False}

    def handle(_signum, _frame):
        stopping["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle)

    deadline = time.time() + args.duration if args.duration > 0 else None

    def stop():
        return stopping["flag"] or (deadline is not None and time.time() >= deadline)

    n = sample_loop(args.out, args.interval, stop)
    print(f"wrote {n} utilisation samples -> {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
