#!/usr/bin/env python3
"""
duty_cycle.py -- a command held at a duty: in each period its whole process group runs for the
duty's share of it and is stopped for the rest, by SIGCONT and SIGSTOP.

Plan version 47 (23 Oct 2026). Block S asks where the method's assumptions end under a load heavy
in softirq work. stress-ng holds a duty for its CPU stressor alone (--cpu-load); its socket
stressor (--sock), which block S runs over loopback, has no such setting and runs flat out. So
the kit holds a socket load's duty here, by the share of time the load may run, as stress-ng's
CPU stressor holds its own by the share of each slice it computes: this starts the command in a
process group of its own and, in every period (100 ms unless --period-ms says otherwise), lets
the group run for the duty's share and stops it for the rest. The duty means what it means for
the CPU load, a share of the time, and the integrity rule holds the background it gives to the
setup's load_pct in the same way.

    python3 scripts/duty_cycle.py --duty 70 -- stress-ng --sock 6 --timeout 3600s

It ends when the command does, with its exit status, and never leaves the group stopped: the
group is continued at the end of every period. A TERM or an INT sent to this process is passed on
to the group, continued first so that it can act on it. A SIGKILL cannot be passed on, and a group
it leaves stopped is ended by the runner's own `pkill -9 -x stress-ng`, which reaches a stopped
process as it reaches any other.
"""
import argparse
import os
import signal
import subprocess
import sys
import time

#: Linux's numbers for the two signals, the same on x86-64 and arm64. Windows, where the tests also
#: run, names neither.
SIGSTOP = getattr(signal, "SIGSTOP", 19)
SIGCONT = getattr(signal, "SIGCONT", 18)
#: The period the duty is a share of, in milliseconds: the length of stress-ng's own CPU-load
#: slices, short beside a 5-s block of load and long beside a signal's cost.
PERIOD_MS = 100.0
#: The signals passed on to the group.
PASSED_ON = (signal.SIGTERM, signal.SIGINT)


def held(child, duty, period_s, send, sleep=time.sleep, stopping=lambda: False):
    """Hold `child`'s group at `duty` percent of every `period_s` until the child ends or
    `stopping()` says to; returns how many periods ran. At 100 the group is never stopped."""
    on_s = period_s * duty / 100.0
    off_s = period_s - on_s
    periods = 0
    while child.poll() is None and not stopping():
        sleep(on_s)
        if off_s > 0 and child.poll() is None:
            send(SIGSTOP)
            sleep(off_s)
            send(SIGCONT)
        periods += 1
    return periods


def parse(argv):
    """(the options, the command) from `--duty D [--period-ms P] -- COMMAND...`."""
    ap = argparse.ArgumentParser(
        description="Run a command at a duty, by stopping and continuing its process group",
        usage="%(prog)s --duty D [--period-ms P] -- COMMAND...")
    ap.add_argument("--duty", type=float, required=True,
                    help="the share of each period the command runs, in per cent, above 0 and "
                         "at most 100")
    ap.add_argument("--period-ms", type=float, default=PERIOD_MS)
    if "--" not in argv:
        ap.error("the command goes after --")
    cut = argv.index("--")
    args, command = ap.parse_args(argv[:cut]), argv[cut + 1:]
    if not command:
        ap.error("there is no command after --")
    if not 0 < args.duty <= 100:
        ap.error("--duty is above 0 and at most 100, not %g" % args.duty)
    if args.period_ms <= 0:
        ap.error("--period-ms is above 0, not %g" % args.period_ms)
    return args, command


def main(argv=None, popen=subprocess.Popen, killpg=None, sleep=time.sleep):
    args, command = parse(list(sys.argv[1:] if argv is None else argv))
    killpg = killpg or os.killpg
    child = popen(command, start_new_session=True)

    def send(sig):
        try:
            killpg(child.pid, sig)
        except ProcessLookupError:
            pass  # the group has ended; the loop sees it at its next look

    asked = []
    previous = {sig: signal.signal(sig, lambda signum, _frame: asked.append(signum))
                for sig in PASSED_ON}
    try:
        held(child, args.duty, args.period_ms / 1000.0, send, sleep, lambda: bool(asked))
        if asked:
            send(SIGCONT)
            send(asked[0])
        return child.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
