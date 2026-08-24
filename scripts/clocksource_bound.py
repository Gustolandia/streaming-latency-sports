#!/usr/bin/env python3
"""
clocksource_bound.py
Which clocksource the testbed used, bounded from a measurement rather than recorded.

Why this exists. A reviewer asked which clocksource the cloud instances ran, because a
virtualised guest need not be handed a counter that is coherent across its vCPUs, and that
would be a rival explanation for the inversions Section V attributes to scheduling. The
campaign never recorded it and the instances have been reclaimed, so the field cannot be
read back. The honest first answer was "we cannot say".

That answer was wrong. The platform probe did record something that constrains it: the
smallest non-zero increment observable from `clock_gettime(CLOCK_MONOTONIC)`, measured at
90 ns on the machine that produced the reported runs. A clock cannot report an increment
smaller than the cost of reading it twice, so that number is an upper bound on the read cost,
and read cost separates the four candidate clocksources by more than an order of magnitude.

The chain, with every constant taken from the kernel tree rather than from memory:

  acpi_pm   Excluded arithmetically, without reference to speed. The ACPI PM timer counts at
            PMTMR_TICKS_PER_SEC = 3,579,545 Hz (include/linux/acpi_pmtmr.h), a period of
            279 ns. A clock whose tick is 279 ns cannot show a 90 ns increment at all.

  hpet      Excluded on read cost. HPET is memory-mapped I/O to an off-die chipset timer;
            the x86 maintainers describe reads as "exceedingly slow (on the order of several
            microseconds)" in the commit that removed HPET from the vDSO. Published
            measurements put a clock_gettime call on HPET near 1.2 us. Note that HPET's own
            tick (~70 ns at 14.318 MHz) is *below* 90 ns, so granularity does not exclude it
            and we do not pretend it does -- the exclusion rests on cost alone.

  tsc       Admitted. Measured at 33-60 ns per call, comfortably inside the bound.

  kvm-clock Admitted, but only in its vDSO form, at 24-29 ns. Without vDSO acceleration the
            same clock costs about 156 ns, which the bound excludes.

And that last line is the one that answers the reviewer, because of what gates the vDSO path.
In arch/x86/kernel/kvmclock.c the mode is set only under a condition:

    if (!(flags & PVCLOCK_TSC_STABLE_BIT))
            return 0;
    kvm_clock.vdso_clock_mode = VDSO_CLOCKMODE_PVCLOCK;

PVCLOCK_TSC_STABLE_BIT is the flag the KVM guest ABI documents as "time measures taken
across multiple cpus are guaranteed to be monotonic". So a kvm-clock fast enough to fit the
bound is a kvm-clock whose hypervisor asserts cross-vCPU monotonicity.

The other admitted branch closes the same way from the other side. kvm-clock registers at
rating 400 and outranks tsc at 300, so tsc is selected only where the kernel demotes
kvm-clock to 299 -- which kvmclock_init() does exactly when CONSTANT_TSC and NONSTOP_TSC are
present and check_tsc_unstable() is false. And if cross-CPU warp is detected later,
tsc_sync.c prints "Measured %Ld cycles TSC warp between CPUs, turning off TSC clock" and the
clocksource is re-rated away.

Both surviving branches therefore carry a cross-vCPU coherence guarantee: one asserted by the
hypervisor, one verified by the kernel. The rival is closed without the field ever being read.

What this cannot establish, stated plainly: it identifies the *set* of clocksources
consistent with the measurement, not which one was in use. It rests on published read-cost
figures for hardware we no longer have, and those figures vary by roughly a factor of two
across sources; the margin here is an order of magnitude, which is why the conclusion
survives the spread. It is an inference from a measurement, not a recorded fact, and the
manuscript says so.

CLI:
    python scripts/clocksource_bound.py
    python scripts/clocksource_bound.py --json
"""
import argparse
import json
import os
import sys

RESULTS = os.path.join("docs", "results")
PLATFORM = os.path.join(RESULTS, "platform", "platform_linux_e5.json")

# include/linux/acpi_pmtmr.h
PMTMR_TICKS_PER_SEC = 3_579_545

# Published per-call cost of clock_gettime(CLOCK_MONOTONIC), in nanoseconds, as (low, high).
# Ranges rather than points because independent measurements differ by about a factor of two
# and a single number would imply a precision nobody has.
READ_COST_NS = {
    "tsc": (33.0, 60.1),
    "kvm-clock": (23.7, 29.0),          # vDSO-accelerated
    "kvm-clock (no vDSO)": (156.1, 156.1),
    "hpet": (1226.3, 3000.0),
    "acpi_pm": (722.9, 2446.1),
}

# Selection is by highest rating; kernel/time/clocksource.c picks the best registered source.
RATINGS = {"kvm-clock": 400, "tsc": 300, "hpet": 250, "acpi_pm": 200}


def pm_timer_tick_ns():
    """Period of the ACPI PM timer, from the kernel's own calibration constant."""
    return 1e9 / PMTMR_TICKS_PER_SEC


def measured_increment_ns(path=PLATFORM):
    """The smallest non-zero clock increment the probe observed on the reported testbed."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    value = data.get("timer_resolution_ns")
    if value is None:
        raise ValueError("no timer_resolution_ns in %s" % path)
    return float(value)


def admits(increment_ns, name):
    """Is this clocksource consistent with an observed increment that small?

    Two independent grounds for exclusion, applied in order:

      1. Granularity. A clock cannot report a step finer than its own tick. Only the ACPI PM
         timer is coarse enough for this to bite; HPET's tick is finer than the observed
         increment, so this test correctly declines to exclude it.
      2. Read cost. An increment is observed by reading the clock twice, so an increment
         below the cost of a single read is impossible. We compare against the *low* end of
         each published range, which is the conservative direction: it admits a clocksource
         unless even its most favourable measurement is too slow.
    """
    if name == "acpi_pm" and pm_timer_tick_ns() > increment_ns:
        return False, "tick of %.0f ns exceeds the observed increment" % pm_timer_tick_ns()
    low, _ = READ_COST_NS[name]
    if low > increment_ns:
        return False, "fastest published read is %.0f ns" % low
    return True, "read cost %.0f--%.0f ns fits within the bound" % READ_COST_NS[name]


def bound(path=PLATFORM):
    """The set of clocksources consistent with the committed measurement."""
    inc = measured_increment_ns(path)
    verdicts = {name: admits(inc, name) for name in READ_COST_NS}
    admitted = sorted(n for n, (ok, _) in verdicts.items() if ok)
    return {
        "increment_ns": inc,
        "pm_timer_tick_ns": pm_timer_tick_ns(),
        "verdicts": {n: {"admitted": ok, "why": why} for n, (ok, why) in verdicts.items()},
        "admitted": admitted,
        "excluded": sorted(n for n, (ok, _) in verdicts.items() if not ok),
        # Every admitted branch carries a cross-vCPU guarantee: vDSO kvm-clock requires
        # PVCLOCK_TSC_STABLE_BIT, and tsc is only selected where the kernel has verified it.
        "all_admitted_are_coherent": all(
            n in ("tsc", "kvm-clock") for n in admitted) and bool(admitted),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bound the testbed clocksource from a measurement")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--platform", default=PLATFORM)
    args = ap.parse_args(argv)

    b = bound(args.platform)
    if args.json:
        print(json.dumps(b, indent=2, sort_keys=True))
        return 0

    print("observed smallest increment : %.0f ns" % b["increment_ns"])
    print("ACPI PM timer tick          : %.0f ns (%d Hz)"
          % (b["pm_timer_tick_ns"], PMTMR_TICKS_PER_SEC))
    print()
    for name in sorted(READ_COST_NS, key=lambda n: -RATINGS.get(n.split(" ")[0], 0)):
        v = b["verdicts"][name]
        print("  %-22s %-9s %s" % (name, "admitted" if v["admitted"] else "EXCLUDED", v["why"]))
    print()
    print("consistent with : %s" % ", ".join(b["admitted"]))
    print("every admitted branch carries a cross-vCPU guarantee: %s"
          % b["all_admitted_are_coherent"])
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
