#!/usr/bin/env python3
"""
kernel_constants.py
The scheduler constants the mechanism argument needs, derived rather than measured.

Why this exists, and why it is a derivation. Section V-G explains the mode in the traced
stall distribution by the EEVDF base slice. That claim needs two numbers: the timer tick and
the base slice. Neither was captured from the running machines during the campaign, and the
machines are Oracle Cloud instances in a free-trial tenancy that reclaims them after
2026-09-18.

The obvious repair -- boot a restored image and read the values -- is the wrong one twice
over. First, `base_slice_ns` is computed at boot from the online CPU count, so reading it on
any shape other than the original eight-vCPU instance returns a different number: on a
one-vCPU shape the same image yields 0.75 ms rather than 3 ms. Second, and worse, it would
produce a number no reader could check. A paper arguing that an unverifiable number is not
yet a measurement cannot close its own last open question with a private `cat`.

So every input here is public and every step is arithmetic a reader can repeat:

  CONFIG_HZ            from the published Ubuntu package for the exact kernel the campaign
                       ran, committed with its SHA256 at
                       docs/results/env/kernel_config_6.8.0-1057-oracle.txt

  online CPU count     from two independent sources that agree. The campaigns wrote the
                       count down as they ran ("(of 8 cores)", "k=7/8 CONCENTRATED (7 cores
                       flat out, 1 free)"), 29 such statements across the logs; and the
                       geometry conditions imply it, since each loads k cores and records
                       the achieved utilisation rho, so k/rho recovers the total six times
                       over (7.95-8.00). One is what the operator told stress-ng, the other
                       is what the utilisation measurement implies.

                       This machine is the cloud driver (sbl-drv), not the workstation that
                       produced the withdrawn first result: every mechanism campaign runs
                       from cloud/campaigns/ and every cloud run records node=sbl-drv with
                       kernel 6.8.0-1057-oracle. The distinction matters because the two
                       testbeds have different CPU counts and different kernels, and the
                       constants below belong to the machine that produced the histogram.

  base slice           from the kernel's own formula in v6.8 kernel/sched/fair.c, applied to
                       that CPU count.

What this cannot establish, stated plainly: it gives what the kernel *would* compute at
boot, not what the machine *did* report. The supporting evidence that nothing overrode it is
negative -- no write to `base_slice_ns`, to a `sched_*` sysctl, or to `tunable_scaling`
appears anywhere in the archived campaign, scripts or logs. That is strong, and it is not
proof. The manuscript therefore says "derived", never "measured".

CLI:
    python scripts/kernel_constants.py
    python scripts/kernel_constants.py --json
"""
import argparse
import csv
import json
import os
import re
import sys

RESULTS = os.path.join("docs", "results")
CONFIG_FILE = os.path.join(RESULTS, "env", "kernel_config_6.8.0-1057-oracle.txt")
GEOMETRY = os.path.join(RESULTS, "model", "ea6", "knee_resolution.csv")

# kernel/sched/fair.c, Linux v6.8:
#     unsigned int sysctl_sched_base_slice = 750000ULL;
#     unsigned int normalized_sysctl_sched_base_slice = 750000ULL;
# and update_sysctl() sets sysctl = factor * normalized.
NORMALISED_BASE_SLICE_NS = 750_000

# get_update_sysctl_factor(), same file: the CPU count entering the factor is clamped.
SYSCTL_FACTOR_CPU_CAP = 8


def _ilog2(n):
    """Kernel ilog2: floor of the base-2 logarithm, for n >= 1."""
    if n < 1:
        raise ValueError("ilog2 needs a positive integer")
    return n.bit_length() - 1


def sysctl_factor(ncpus, scaling="log"):
    """get_update_sysctl_factor() from kernel/sched/fair.c.

    LOG is the kernel's default (SCHED_TUNABLESCALING_LOG). The other two are implemented
    because a reader checking this against the source should find the whole function, not
    the branch that happened to apply here.
    """
    cpus = min(ncpus, SYSCTL_FACTOR_CPU_CAP)
    if scaling == "none":
        return 1
    if scaling == "linear":
        return cpus
    if scaling == "log":
        return 1 + _ilog2(cpus)
    raise ValueError("unknown tunable scaling: %r" % scaling)


def base_slice_ns(ncpus, scaling="log", normalised=NORMALISED_BASE_SLICE_NS):
    """The EEVDF base slice the kernel computes at boot for this many online CPUs."""
    return sysctl_factor(ncpus, scaling) * normalised


def read_config(path=CONFIG_FILE):
    """The committed CONFIG_* lines, as a dict. Comment lines carry the provenance."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("CONFIG_") and "=" in line:
                k, v = line.split("=", 1)
                out[k] = v
    return out


def cpus_from_geometry(path=GEOMETRY):
    """Recover the machine's online CPU count from the campaign's own measurements.

    Each geometry condition loads k cores and records the achieved system-wide utilisation
    rho, so k/rho is the total. Six conditions give six independent estimates; the spread
    between them is the honest error bar on this number, and it is small.
    """
    est = []
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            m = re.match(r"k(\d+)_", row["condition"])
            rho = float(row["rho"])
            if m and rho > 0:
                est.append(int(m.group(1)) / rho)
    if not est:
        raise ValueError("no k*_ conditions with a positive rho in %s" % path)
    return est


CAMPAIGN_LOGS = os.path.join("reproducibility", "campaign_logs")

# The cloud campaigns announce the machine they are loading, e.g.
#   "=== E-A6 k=7/8 CONCENTRATED (7 cores flat out, 1 free) ==="
#   "=== E-A4 cpu-load=70% (of 8 cores) ==="
_STATED_TOTAL = re.compile(r"\(of (\d+) cores\)|k=\d+/(\d+)")


def cores_from_campaign_logs(log_dir=CAMPAIGN_LOGS):
    """The core count the campaigns wrote down while they were running.

    This is direct evidence rather than inference, and it is the reason the CPU count does
    not rest on k/rho alone. The two are independent: one is what the operator told
    stress-ng, the other is what the utilisation measurement implies. They agree.

    Returns a Counter of stated totals, so a disagreement between campaigns would be
    visible rather than averaged away.
    """
    import collections
    counts = collections.Counter()
    if not os.path.isdir(log_dir):
        return counts
    for name in sorted(os.listdir(log_dir)):
        if not name.endswith(".log"):
            continue
        with open(os.path.join(log_dir, name), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for a, b in _STATED_TOTAL.findall(line):
                    counts[int(a or b)] += 1
    return counts


def constants():
    """Every derived quantity, with the inputs it came from."""
    cfg = read_config()
    hz = int(cfg["CONFIG_HZ"])
    est = cpus_from_geometry()
    ncpus = int(round(sum(est) / len(est)))
    stated = cores_from_campaign_logs()
    stated_total = stated.most_common(1)[0][0] if stated else None
    factor = sysctl_factor(ncpus)
    slice_ns = base_slice_ns(ncpus)
    return {
        "config_hz": hz,
        "tick_ms": 1000.0 / hz,
        "hrtick_compiled": cfg.get("CONFIG_SCHED_HRTICK") == "y",
        "cpus": ncpus,
        "cpu_estimates": est,
        "cpu_spread": max(est) - min(est),
        "cpus_stated_in_logs": stated_total,
        "cpus_stated_mentions": sum(stated.values()),
        "cpus_agree": stated_total is None or stated_total == ncpus,
        "sysctl_factor": factor,
        "base_slice_ns": slice_ns,
        "base_slice_ms": slice_ns / 1e6,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Derive the testbed's scheduler constants")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    c = constants()
    if args.json:
        print(json.dumps(c, indent=2))
        return 0
    print("CONFIG_HZ = %d  ->  tick = %.2f ms" % (c["config_hz"], c["tick_ms"]))
    print("CONFIG_SCHED_HRTICK compiled in: %s  (runtime default is off in v6.8,"
          % c["hrtick_compiled"])
    print("    SCHED_FEAT(HRTICK, false), so slice expiry is observed at the tick)")
    print("online CPUs = %d  (from k/rho over %d geometry conditions: %s, spread %.2f)"
          % (c["cpus"], len(c["cpu_estimates"]),
             ", ".join("%.2f" % e for e in c["cpu_estimates"]), c["cpu_spread"]))
    print("sysctl factor = 1 + ilog2(min(%d, %d)) = %d"
          % (c["cpus"], SYSCTL_FACTOR_CPU_CAP, c["sysctl_factor"]))
    print("base slice = %d x %d ns = %d ns = %.2f ms"
          % (c["sysctl_factor"], NORMALISED_BASE_SLICE_NS, c["base_slice_ns"],
             c["base_slice_ms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
