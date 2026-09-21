#!/usr/bin/env python3
"""
sched_settings.py -- read, set and check the scheduler settings the law predicts from.

The plateau-cliff-floor law says the negative rate falls off a cliff that starts at the
scheduler's base slice and is one tick wide. kernel_constants.py had to derive both numbers for
the Oracle driver from public inputs, because nobody read them off the machine while it existed.
On the new testbed they are read off the machine under test, before and after every run, and a
run whose settings drifted does not count.

What is read. Each item is a Linux interface, and an item that cannot be read is listed under
"missing" rather than filled in with a default:

    kernel release     /proc/sys/kernel/osrelease
    tick               CONFIG_HZ in /boot/config-<release>
    base slice         /sys/kernel/debug/sched/base_slice_ns     (root; debugfs)
    tunable scaling    /sys/kernel/debug/sched/tunable_scaling   (how the default grows with CPUs)
    preemption model   /sys/kernel/debug/sched/preempt
    online CPUs        /sys/devices/system/cpu/online
    CPU model          /proc/cpuinfo
    clock source       /sys/devices/system/clocksource/clocksource0/current_clocksource

It also computes the slice the kernel's own rule gives this release on this many CPUs, so a
default that does not follow the rule shows up. The rule's constant fell from 750000 to 700000 ns
in Linux 6.15 ("sched: Reduce the default slice to avoid tasks getting an extra tick").

The slice can be changed without a reboot and the tick cannot. That is why a campaign shuffles
the slice run by run but treats the tick as a session.

CLI:
    sudo python3 scripts/sched_settings.py read
    sudo python3 scripts/sched_settings.py set-slice 1500000
    sudo python3 scripts/sched_settings.py check --slice-ns 1500000 --hz 1000
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kernel_constants  # noqa: E402

FILES = {
    "release": "proc/sys/kernel/osrelease",
    "base_slice_ns": "sys/kernel/debug/sched/base_slice_ns",
    "tunable_scaling": "sys/kernel/debug/sched/tunable_scaling",
    "preempt": "sys/kernel/debug/sched/preempt",
    "online": "sys/devices/system/cpu/online",
    "cpuinfo": "proc/cpuinfo",
    "clocksource": "sys/devices/system/clocksource/clocksource0/current_clocksource",
}

#: tunable_scaling's values, named as kernel/sched/fair.c names them.
SCALING = {"0": "none", "1": "log", "2": "linear"}

#: The first release whose rule starts from 700000 ns instead of 750000.
SMALLER_SLICE_FROM = (6, 15)
SMALLER_SLICE_NS = 700_000

#: Without these a run cannot be checked against the law. The others are recorded for a reader.
ESSENTIAL = ("release", "config_hz", "base_slice_ns", "online_cpus")
RECORDED = ("tunable_scaling", "preempt", "cpu_model", "clocksource")


#: Where the kernel lists each CPU's directory; cpu0 usually has no `online` file and stays on.
CPU_DIR = "sys/devices/system/cpu"


class SliceNotApplied(RuntimeError):
    """The kernel did not keep the base slice that was written."""


class CpusNotApplied(RuntimeError):
    """The kernel did not list the number of online CPUs that was asked for."""


def _read(root, rel):
    """A file's contents, stripped, or None if it cannot be read."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def count_cpu_list(text):
    """How many CPUs a kernel CPU list names: '0-7' is 8, '0-3,6,8-9' is 7."""
    total = 0
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            low, high = part.split("-", 1)
            total += int(high) - int(low) + 1
        elif part:
            total += 1
    return total


def config_hz(text):
    """CONFIG_HZ from a kernel config, or None."""
    m = re.search(r"^CONFIG_HZ=(\d+)$", text or "", re.M)
    return int(m.group(1)) if m else None


def cpu_model(text):
    """The CPU's name from /proc/cpuinfo.

    Arm kernels print no model name, so there the implementer and part numbers stand in for it.
    """
    m = re.search(r"^model name\s*:\s*(.+)$", text or "", re.M)
    if m:
        return m.group(1).strip()
    implementer = re.search(r"^CPU implementer\s*:\s*(\S+)", text or "", re.M)
    part = re.search(r"^CPU part\s*:\s*(\S+)", text or "", re.M)
    if implementer and part:
        return "CPU implementer %s, part %s" % (implementer.group(1), part.group(1))
    return None


def active_choice(text):
    """The bracketed entry of a kernel choice file: 'none (voluntary) full' gives 'voluntary'."""
    m = re.search(r"\(([^)]+)\)", text or "")
    return m.group(1) if m else None


def release_version(release):
    """(major, minor) of a kernel release string, or None."""
    m = re.match(r"(\d+)\.(\d+)", release or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def rule_slice_ns(release, cpus, scaling):
    """The base slice the kernel's rule gives at boot, or None if any input is unknown."""
    version = release_version(release)
    if version is None or cpus is None or scaling is None:
        return None
    normalised = (SMALLER_SLICE_NS if version >= SMALLER_SLICE_FROM
                  else kernel_constants.NORMALISED_BASE_SLICE_NS)
    return kernel_constants.base_slice_ns(cpus, scaling, normalised)


def normalised_slice_ns(settings):
    """The per-step constant the kernel's rule multiplies, recovered from the slice it reports.

    It means something only while the slice is still the kernel's own default. The first Azure
    driver (6.8.0-1064-azure, 8 CPUs) reported 2800000 ns, a constant of 700000: the smaller
    one from Linux 6.15, carried in a 6.8 kernel. Its version number alone predicted 3 ms.
    """
    cpus, scaling, base = (settings["online_cpus"], settings["tunable_scaling"],
                           settings["base_slice_ns"])
    if not (cpus and scaling and base):
        return None
    return int(round(base / kernel_constants.sysctl_factor(cpus, scaling)))


def read_settings(root="/"):
    """Everything above, as a dict, with the unreadable items named under "missing"."""
    raw = {key: _read(root, rel) for key, rel in FILES.items()}
    release = raw["release"] or None
    hz = config_hz(_read(root, "boot/config-%s" % release)) if release else None
    slice_text = raw["base_slice_ns"] or ""
    settings = {
        "release": release,
        "config_hz": hz,
        "tick_ms": 1000.0 / hz if hz else None,
        "base_slice_ns": int(slice_text) if slice_text.isdigit() else None,
        "tunable_scaling": SCALING.get(raw["tunable_scaling"] or ""),
        "preempt": active_choice(raw["preempt"]),
        "online_cpus": count_cpu_list(raw["online"]) if raw["online"] else None,
        "cpu_model": cpu_model(raw["cpuinfo"]),
        "clocksource": raw["clocksource"] or None,
    }
    settings["rule_slice_ns"] = rule_slice_ns(release, settings["online_cpus"],
                                              settings["tunable_scaling"])
    settings["normalised_slice_ns"] = normalised_slice_ns(settings)
    settings["missing"] = [k for k in ESSENTIAL + RECORDED if settings[k] is None]
    return settings


def set_base_slice(ns, root="/"):
    """Write the base slice and read it back; returns the value read."""
    if ns <= 0:
        raise ValueError("a base slice must be a positive number of nanoseconds, not %d" % ns)
    path = os.path.join(root, FILES["base_slice_ns"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("%d\n" % ns)
    got = _read(root, FILES["base_slice_ns"])
    if got != str(ns):
        raise SliceNotApplied("wrote %d ns to %s and read back %r" % (ns, path, got))
    return ns


def set_online_cpus(n, root="/"):
    """Keep CPUs 0 to n-1 online and take the rest offline, then read back the online list.

    Taking CPUs offline makes the kernel recompute its default slice from the new count, which
    is what the core-count experiment tests on one machine instead of three. It also resets a
    hand-set slice, so a runner sets the CPUs first and the slice after.
    """
    base = os.path.join(root, CPU_DIR)
    present = sorted(int(name[3:]) for name in os.listdir(base) if re.fullmatch(r"cpu\d+", name))
    if not 1 <= n <= len(present):
        raise ValueError("cannot have %d CPUs online on a machine with %d" % (n, len(present)))
    for cpu in present[1:]:
        with open(os.path.join(base, "cpu%d" % cpu, "online"), "w", encoding="utf-8") as fh:
            fh.write("1\n" if cpu < n else "0\n")
    got = _read(root, FILES["online"])
    if got is None or count_cpu_list(got) != n:
        raise CpusNotApplied("asked for %d CPUs online and the kernel lists %r" % (n, got))
    return n


def problems(settings, slice_ns=None, hz=None, cpus=None):
    """Why these settings cannot back a run expecting `slice_ns`, `hz` and `cpus`; empty if they can.

    The core count is checked here and not only where it is set, because on Azure it cannot be set
    at all: a session reaches its count at boot, so by the time anything runs there is nobody left
    to have failed. What is left is to read the machine and refuse if it is not the one asked for.
    Booting with `maxcpus=N` gives a machine that agrees for about a second and then does not, so
    this is the check that catches it.
    """
    out = ["%s could not be read" % k for k in ESSENTIAL if k in settings["missing"]]
    if slice_ns is not None and settings["base_slice_ns"] != slice_ns:
        out.append("the base slice is %s ns, not %d" % (settings["base_slice_ns"], slice_ns))
    if hz is not None and settings["config_hz"] != hz:
        out.append("CONFIG_HZ is %s, not %d" % (settings["config_hz"], hz))
    if cpus is not None and settings["online_cpus"] != cpus:
        out.append("%s CPUs are online, not %d" % (settings["online_cpus"], cpus))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Read, set and check the scheduler settings")
    ap.add_argument("--root", default="/",
                    help="filesystem root; the tests point it at a fake tree")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("read")
    p = sub.add_parser("set-slice")
    p.add_argument("ns", type=int)
    p = sub.add_parser("set-cpus")
    p.add_argument("n", type=int)
    p = sub.add_parser("check")
    p.add_argument("--slice-ns", type=int)
    p.add_argument("--hz", type=int)
    p.add_argument("--cpus", type=int,
                   help="how many CPUs this session is meant to be running on")
    args = ap.parse_args(argv)
    if args.command in ("set-slice", "set-cpus"):
        try:
            if args.command == "set-slice":
                set_base_slice(args.ns, args.root)
                print("base slice set to %d ns, and read back" % args.ns, file=out)
            else:
                set_online_cpus(args.n, args.root)
                print("%d CPUs online, and read back" % args.n, file=out)
        except (OSError, ValueError, SliceNotApplied, CpusNotApplied) as exc:
            print("ERROR: %s" % exc, file=out)
            return 1
        return 0
    settings = read_settings(args.root)
    if args.command == "read":
        print(json.dumps(settings, indent=2, sort_keys=True), file=out)
        return 0
    found = problems(settings, args.slice_ns, args.hz, args.cpus)
    print(json.dumps({"ok": not found, "problems": found, "settings": settings},
                     indent=2, sort_keys=True), file=out)
    return 1 if found else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
