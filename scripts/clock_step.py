"""Moving this machine's clock by a known, measured amount, and putting it back (T2, Go tools).

libfaketime moves the clock a C, Java or Python program reads and nothing else. A Go program reads
the clock without the C library, so the preload never reaches it, and the plan has said since
D15-1 what T2 does instead: a machine whose own clock is offset for the run and restored after.
This is that, for vegeta, hey, k6 and nats-latency.

The shift is measured, not assumed (D23-1). chrony keeps this machine's clock on the Hyper-V PTP
clock, /dev/ptp_hyperv, to about a microsecond, and stepping the system clock does not move the
hypervisor's. So the shift achieved is read against it directly, on this machine, with no network
between: the system clock less the PTP clock, before the step and after, each the median of
paired readings.

It needs root, for the PTP device and for the step, and chrony stopped around it: left running,
chrony would pull the clock back while the tool ran.
"""
import argparse
import json
import os
import statistics
import sys
import time

PHC = "/dev/ptp_hyperv"

#: CLOCK_REALTIME's number on Linux, where this runs. Named here, and the clock functions looked
#: up only when called, because Windows -- where the tests also run -- has neither.
REALTIME = getattr(time, "CLOCK_REALTIME", 0)

#: Paired readings per measurement, and the fastest share of them that is kept. Each pair costs
#: tens of microseconds on Hyper-V; the fastest are the least disturbed.
READS = 60
KEEP = 12


def phc_clock_id(fd):
    """The POSIX dynamic clock id of an open PTP device, which the kernel defines this way."""
    return ((~fd) << 3) | 3


def offset_ns(phc_id, reads=READS, keep=KEEP, gettime=None):
    """The system clock less the PTP clock, in nanoseconds, from the fastest paired readings.

    Each pair is read system, PTP, system, and the PTP reading set against the mean of the two
    system ones, so that the time the readings take cancels -- if the PTP was read in the middle.
    It was not always: a read of the Hyper-V clock takes tens of microseconds, and one that was
    preempted puts its midpoint anywhere. Taken as the plain median, measurements a second apart
    on the first x86 pair disagreed by 60 microseconds where chrony put the clocks 0.15 apart. So
    only the pairs that took least time are kept, as clock synchronisation has always done: the
    shorter the read, the less room for it to be lopsided.
    """
    gettime = gettime or time.clock_gettime_ns
    pairs = []
    for _ in range(reads):
        before = gettime(REALTIME)
        ptp = gettime(phc_id)
        after = gettime(REALTIME)
        pairs.append((after - before, (before + after) // 2 - ptp))
    pairs.sort()
    return statistics.median(offset for _, offset in pairs[:keep])


def shift(ms, phc_id, gettime=None, settime=None):
    """Move the system clock by `ms` (negative reads early), measuring what moved against the PTP.

    One read and one write of the system clock, so the step itself is what was asked to within
    the microsecond those two calls take -- and the answer says what it actually was.
    """
    gettime = gettime or time.clock_gettime_ns
    settime = settime or time.clock_settime_ns
    before = offset_ns(phc_id, gettime=gettime)
    settime(REALTIME, gettime(REALTIME) + int(round(ms * 1e6)))
    after = offset_ns(phc_id, gettime=gettime)
    return {"asked_ms": ms, "before_ms": before / 1e6, "after_ms": after / 1e6,
            "moved_ms": (after - before) / 1e6}


def main(argv=None, out=None, opener=os.open, closer=os.close,
         gettime=None, settime=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Move this machine's clock against its PTP clock")
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="the system clock less the PTP clock, in ms")
    m.add_argument("--device", default=PHC)
    s = sub.add_parser("shift", help="move the system clock by --ms and say what moved")
    s.add_argument("--ms", type=float, required=True)
    s.add_argument("--device", default=PHC)
    s.add_argument("--out", default="")
    args = ap.parse_args(argv)
    fd = opener(args.device, os.O_RDONLY)
    try:
        phc_id = phc_clock_id(fd)
        if args.command == "measure":
            print("%.6f" % (offset_ns(phc_id, gettime=gettime) / 1e6), file=out)
            return 0
        found = shift(args.ms, phc_id, gettime=gettime, settime=settime)
    finally:
        closer(fd)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(found, fh, indent=2, sort_keys=True)
    print(json.dumps(found, sort_keys=True), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
