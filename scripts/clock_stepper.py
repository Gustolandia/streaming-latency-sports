#!/usr/bin/env python3
"""
clock_stepper.py -- step this machine's wall clock while a tool runs (the step test, freeze 34).

A tool that takes both of its timestamps in one process meets a value below zero only when the
wall clock steps back between them: a message in flight across the step is received at a reading
earlier than the one it left with. That is how a user of RabbitMQ Stream PerfTest saw -105 ms
during a cluster's rolling restart (its issue 418). T2's constant offset cannot make such a value,
because it moves both readings together; this steps the clock itself, so the tool's own handling
of the value can be read off what it prints.

The clock stepped is CLOCK_REALTIME, the wall clock, and nothing else: a monotonic clock, which
the tools that time with System.nanoTime() or Go's monotonic reading use, does not move, and
those tools are the test's controls. Every step is written down: when it was asked for on the
monotonic clock, the wall clock just before and just after, and its direction.

Two patterns:

  back        every period, the wall clock goes back by the step; the clock ends behind by the
              number of steps times the step, and the caller puts it back
  alternate   every period, back by the step, and half a period later forward by it again, so the
              clock ends where it would have been; a message in flight across a forward step
              comes out longer by the step instead

    sudo python3 scripts/clock_stepper.py --step-ms 20 --period-s 1 --seconds 60 \\
        --pattern back --log steps.csv

Only a process allowed to set the clock can run it (root, or CAP_SYS_TIME), and the caller stops
anything that would correct the clock under it (chrony) and starts it again after.
"""
import argparse
import csv
import sys
import time

FIELDS = ("i", "asked_mono_ns", "wall_before_ns", "wall_after_ns", "direction", "step_ns")


def schedule(pattern, period_s, seconds):
    """When each step is asked for, in seconds from the start, and which way it goes.

    `back` steps once a period; `alternate` adds a forward step half a period after each back
    step. No step is asked for at or after the end, and an `alternate` run never ends on a back
    step, so the clock it leaves is the clock it found."""
    if pattern not in ("back", "alternate"):
        raise ValueError("pattern is back or alternate, not %r" % pattern)
    if period_s <= 0 or seconds <= 0:
        raise ValueError("the period and the duration must be above zero")
    steps, k = [], 0
    while (k + 1) * period_s < seconds:
        at = (k + 1) * period_s
        if pattern == "back":
            steps.append((at, -1))
        elif at + period_s / 2.0 < seconds:
            steps += [(at, -1), (at + period_s / 2.0, +1)]
        k += 1
    return steps


def run(steps, step_ns, sleep, mono_ns, wall_ns, set_wall_ns, out):
    """Make each step at its time and write it down; return the net change made to the clock."""
    w = csv.DictWriter(out, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    start, net = mono_ns(), 0
    for i, (at, direction) in enumerate(steps):
        wait = start + int(at * 1e9) - mono_ns()
        if wait > 0:
            sleep(wait / 1e9)
        asked = mono_ns()
        before = wall_ns()
        set_wall_ns(before + direction * step_ns)
        after = wall_ns()
        net += direction * step_ns
        w.writerow({"i": i, "asked_mono_ns": asked - start, "wall_before_ns": before,
                    "wall_after_ns": after, "direction": "back" if direction < 0 else "forward",
                    "step_ns": step_ns})
        out.flush()
    return net


def main(argv=None, clock=None):
    ap = argparse.ArgumentParser(description="Step the wall clock while a tool runs")
    ap.add_argument("--step-ms", type=float, required=True)
    ap.add_argument("--period-s", type=float, required=True)
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--pattern", choices=("back", "alternate"), default="back")
    ap.add_argument("--log", required=True, help="where each step is written down")
    args = ap.parse_args(argv)
    steps = schedule(args.pattern, args.period_s, args.seconds)
    step_ns = int(round(args.step_ms * 1e6))
    if clock is None:
        #: The machine's clocks: only Linux, and only root, can set the wall clock.
        clock = (time.sleep, time.monotonic_ns,
                 lambda: time.clock_gettime_ns(time.CLOCK_REALTIME),
                 lambda ns: time.clock_settime_ns(time.CLOCK_REALTIME, ns))
    with open(args.log, "w", encoding="utf-8", newline="") as fh:
        net = run(steps, step_ns, *clock, out=fh)
    print("made %d steps of %g ms, %s; the wall clock is %+.3f ms from where it began"
          % (len(steps), args.step_ms, args.pattern, net / 1e6))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
