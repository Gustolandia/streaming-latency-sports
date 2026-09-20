#!/usr/bin/env python3
"""
kernel_checks.py -- what a kernel we built ourselves must show before A2 runs on it.

A2 asks whether the cliff's width follows the tick. The tick is fixed when the kernel is
compiled, so the block builds three kernels from one source that differ in nothing but HZ, and
boots each one. The whole block rests on that "nothing but HZ" being true, and on the machine
really running at the tick its config claims, so the plan puts five checks at every boot, before
any run:

  the tick setting     CONFIG_HZ read back from the kernel that is actually running
  the tick measured    the kernel's own timer interrupt counted on a busy CPU, within 5% of it
  HRTICK off           with the high-resolution slice timer on, the tick would not set the width
                       and the test would be void
  the slice read back  as it was set
  the same NO_HZ       tickless settings identical across the three builds, or they differ in
                       more than the tick

A kernel that fails any of them does not run a campaign. The measured tick is the one that
cannot be faked by a configuration file: a kernel can be configured for 250 Hz and boot at
something else, and only counting says so.

    python3 scripts/kernel_checks.py read --seconds 10
    python3 scripts/kernel_checks.py check --hz 250 --slice-ns 3000000
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sched_settings  # noqa: E402

#: How far the counted tick may sit from the configured one. The plan's figure.
TICK_TOLERANCE = 0.05
#: How long to count for. Ten seconds at 100 Hz is a thousand ticks, so a single missed or extra
#: one moves the answer by a tenth of a percent.
COUNT_SECONDS = 10.0
#: The tickless settings that must match across the three builds. NO_HZ_FULL would stop the timer
#: on a busy CPU, which is the CPU the tick is counted on.
NOHZ_KEYS = ("CONFIG_NO_HZ", "CONFIG_NO_HZ_IDLE", "CONFIG_NO_HZ_FULL", "CONFIG_NO_HZ_COMMON",
             "CONFIG_HIGH_RES_TIMERS")


def hrtick_on(features):
    """Whether the scheduler's high-resolution slice timer is on, or None if it does not say.

    /sys/kernel/debug/sched/features lists every feature, the off ones prefixed NO_. HRTICK and
    HRTICK_DL are separate, and the plan asks about the one that times the slice.
    """
    if not features:
        return None
    if re.search(r"(?<![\w])NO_HRTICK(?![\w])", features):
        return False
    if re.search(r"(?<![\w])HRTICK(?![\w])", features):
        return True
    return None


def nohz_settings(config):
    """The tickless settings a kernel config carries, as {name: value}."""
    found = {}
    for key in NOHZ_KEYS:
        match = re.search(r"^%s=(.*)$" % key, config or "", re.M)
        found[key] = match.group(1).strip() if match else None
    return found


def local_timer_counts(interrupts):
    """{cpu: the kernel's own timer interrupts so far} from /proc/interrupts.

    The LOC line holds one count per CPU. Where a kernel does not carry it -- some Arm builds do
    not -- there is nothing to count and the caller is told so rather than given a zero.
    """
    for line in (interrupts or "").splitlines():
        if line.strip().startswith("LOC:"):
            return dict(enumerate(int(n) for n in re.findall(r"\d+", line.split(":", 1)[1])))
    return {}


def measured_hz(before, after, seconds, cpu=None):
    """The tick actually running, in Hz, from two readings of the timer counts.

    Counted on the busiest CPU of the interval unless one is named: an idle CPU may stop its
    tick altogether, and the answer would say the kernel is slower than it is.
    """
    if not before or not after or seconds <= 0:
        return None
    moved = dict((n, after[n] - before[n]) for n in after if n in before)
    if not moved:
        return None
    if cpu is None:
        cpu = max(moved, key=lambda n: moved[n])
    ticks = moved.get(cpu)
    return None if ticks is None or ticks < 0 else ticks / float(seconds)


def problems(reading, hz=None, slice_ns=None, nohz_like=None):
    """Everything wrong with a booted kernel, in the plan's own words. Empty means it may run."""
    wrong = []
    settings = reading.get("settings") or {}
    running = settings.get("config_hz")
    if hz is not None:
        if running != hz:
            wrong.append("the kernel running reports HZ=%s, and this campaign is for HZ=%s"
                         % (running, hz))
    if reading.get("hrtick_on") is None:
        wrong.append("whether the slice's high-resolution timer is on could not be read, and A2 "
                     "is void if it is on")
    elif reading["hrtick_on"]:
        wrong.append("the slice's high-resolution timer (HRTICK) is on, so the tick would not "
                     "set the cliff's width and this campaign would measure nothing")
    counted = reading.get("measured_hz")
    want = hz if hz is not None else running
    if counted is None:
        wrong.append("the tick could not be counted, and a config file alone does not say what "
                     "the machine is running")
    elif want:
        off_by = abs(counted - want) / float(want)
        if off_by > TICK_TOLERANCE:
            wrong.append("the tick counted %.1f Hz where the kernel says %s, which is %.1f%% "
                         "out and the plan allows %.0f%%"
                         % (counted, want, 100 * off_by, 100 * TICK_TOLERANCE))
    if slice_ns is not None and settings.get("base_slice_ns") != slice_ns:
        wrong.append("the slice reads back as %s ns, not the %s ns it was set to"
                     % (settings.get("base_slice_ns"), slice_ns))
    if nohz_like is not None and reading.get("nohz") != nohz_like:
        wrong.append("the tickless settings differ from the build they are compared with, so "
                     "these kernels differ in more than the tick: %s against %s"
                     % (reading.get("nohz"), nohz_like))
    return wrong


def read(root="/", seconds=COUNT_SECONDS, sleep=time.sleep, now=time.time):
    """Everything the checks need from the machine this runs on."""
    settings = sched_settings.read_settings(root)
    release = settings.get("release")
    config = _slurp(os.path.join(root, "boot", "config-%s" % release)) if release else ""
    features = _slurp(os.path.join(root, "sys/kernel/debug/sched/features"))
    before, started = local_timer_counts(_slurp(os.path.join(root, "proc/interrupts"))), now()
    sleep(seconds)
    after = local_timer_counts(_slurp(os.path.join(root, "proc/interrupts")))
    return {"settings": settings, "nohz": nohz_settings(config),
            "hrtick_on": hrtick_on(features),
            "counted_for_s": round(now() - started, 3),
            "measured_hz": measured_hz(before, after, now() - started)}


def _slurp(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a kernel must show before A2 runs on it")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("read", "check"):
        p = sub.add_parser(name)
        p.add_argument("--root", default="/")
        p.add_argument("--seconds", type=float, default=COUNT_SECONDS)
        if name == "check":
            p.add_argument("--hz", type=int, default=None)
            p.add_argument("--slice-ns", type=int, default=None)
            p.add_argument("--nohz-like", default="",
                           help="a reading from another build, whose tickless settings these "
                                "must match")
    args = ap.parse_args(argv)
    reading = read(args.root, args.seconds)
    if args.command == "read":
        print(json.dumps(reading, indent=2, sort_keys=True), file=out)
        return 0
    like = None
    if args.nohz_like:
        with open(args.nohz_like, encoding="utf-8") as fh:
            like = (json.load(fh).get("nohz"))
    wrong = problems(reading, args.hz, args.slice_ns, like)
    print(json.dumps({"ok": not wrong, "problems": wrong, "reading": reading},
                     indent=2, sort_keys=True), file=out)
    return 0 if not wrong else 1


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
