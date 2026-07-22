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


def sample_loop(out_path, interval, stop, stat_path=PROC_STAT, load_path=PROC_LOADAVG):
    """Append utilisation samples until `stop()` returns True. Returns the number written."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prev = read_cpu_times(stat_path)
    n = 0
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["t_wall", "rho", "loadavg"])
        w.writeheader()
        while not stop():
            time.sleep(interval)
            cur = read_cpu_times(stat_path)
            rho = utilisation(prev, cur)
            prev = cur
            if rho is None:
                continue
            w.writerow({"t_wall": time.time(), "rho": round(rho, 5),
                        "loadavg": read_loadavg(load_path)})
            fh.flush()
            n += 1
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


if __name__ == "__main__":
    sys.exit(main())
