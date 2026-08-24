#!/usr/bin/env python3
"""Is OMB's reported end-to-end latency quantised to whole milliseconds?

If record.timestamp() is millisecond-resolution and the consumer's read is too, every surviving
sample is an integer number of milliseconds and the sub-millisecond structure is simply absent.
A run whose p50 and p99 are both exactly 1.000 is not a narrow distribution; it is a distribution
with one value in it.

This produced the corroborating figure quoted in the response to the referee: 36 of the 40
reported latency values across eight runs were exactly whole milliseconds. That number is
evidence, so it must be recomputable by someone who is not the author, which means the
percentile extraction and the whole-millisecond test have to be reachable without a testbed.
Both are functions here, and the input directory is an argument rather than a hard-coded home
directory.

CLI:
    python scripts/check_omb_quantisation.py                    # ~/omb, last 8 runs
    python scripts/check_omb_quantisation.py --dir path --last 4
"""
import argparse
import glob
import json
import os

#: Floating point equality against the nearest integer. The values are milliseconds printed by
#: a Java harness, so anything genuinely quantised lands far inside this.
WHOLE_TOL = 1e-9

PERCENTILE_KEYS = ("endToEndLatency50pct", "endToEndLatency95pct", "endToEndLatency99pct",
                   "endToEndLatencyMax", "endToEndLatencyAvg")

DEFAULT_DIR = os.path.expanduser("~/omb")
PATTERN = "omb_workload-Kafka-*.json"


def run_files(directory=DEFAULT_DIR, last=8):
    """The most recent `last` result files, oldest first."""
    found = sorted(glob.glob(os.path.join(directory, PATTERN)))
    return found[-last:] if last else found


def last_value(report, key):
    """OMB writes either a scalar or a per-interval list; the final interval is the run's."""
    value = report.get(key)
    if isinstance(value, list) and value:
        return value[-1]
    return value


def percentiles(report):
    """The five reported latency values, in a fixed order, `None` where absent."""
    return [last_value(report, key) for key in PERCENTILE_KEYS]


def is_whole(value):
    return abs(value - round(value)) < WHOLE_TOL


def whole_fraction(values):
    """(whole, total, fraction). An empty input has no fraction, not a fraction of zero."""
    numeric = [v for v in values if isinstance(v, (int, float))
               and not isinstance(v, bool)]
    whole = [v for v in numeric if is_whole(v)]
    if not numeric:
        return 0, 0, None
    return len(whole), len(numeric), len(whole) / len(numeric)


def read_report(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=DEFAULT_DIR)
    ap.add_argument("--last", type=int, default=8)
    args = ap.parse_args(argv)

    files = run_files(args.dir, args.last)
    if not files:
        print("no OMB result files under %s" % args.dir)
        return 1

    print("{:<22s}{:>8s}{:>8s}{:>8s}{:>9s}{:>9s}".format(
        "run", "p50", "p95", "p99", "max", "avg"))

    values = []
    for path in files:
        row = percentiles(read_report(path))
        values.extend(row)
        print("{:<22s}{:>8}{:>8}{:>8}{:>9}{:>9}".format(
            os.path.basename(path)[-24:-5],
            *[("-" if x is None else round(x, 3)) for x in row]))

    whole, total, fraction = whole_fraction(values)
    print()
    print("percentile values inspected: %d" % total)
    print("exactly whole milliseconds : %d  (%s)"
          % (whole, "n/a" if fraction is None else "{:.0%}".format(fraction)))
    print()
    print("Whole-millisecond percentiles mean the measurement has no sub-millisecond resolution:")
    print("record.timestamp() is ms-grained, so the difference is an integer count of ticks.")
    print("Everything faster than one tick computes to 0 and is discarded by the > 0 guard.")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
