"""Is OMB's reported end-to-end latency quantised to whole milliseconds?

If record.timestamp() is millisecond-resolution and the consumer's read is too, every surviving
sample is an integer number of milliseconds and the sub-millisecond structure is simply absent.
A run whose p50 and p99 are both exactly 1.000 is not a narrow distribution; it is a distribution
with one value in it.
"""
import glob
import json
import os

fs = sorted(glob.glob(os.path.expanduser("~/omb/omb_workload-Kafka-*.json")))[-8:]
hdr = ("run", "p50", "p95", "p99", "max", "avg")
print("{:<22s}{:>8s}{:>8s}{:>8s}{:>9s}{:>9s}".format(*hdr))

vals = []
for f in fs:
    with open(f) as fh:
        d = json.load(fh)

    def last(k):
        v = d.get(k)
        if isinstance(v, list) and v:
            return v[-1]
        return v

    row = [last("endToEndLatency50pct"), last("endToEndLatency95pct"),
           last("endToEndLatency99pct"), last("endToEndLatencyMax"),
           last("endToEndLatencyAvg")]
    vals.extend(x for x in row if isinstance(x, (int, float)))
    name = os.path.basename(f)[-24:-5]
    print("{:<22s}{:>8}{:>8}{:>8}{:>9}{:>9}".format(
        name, *[("-" if x is None else round(x, 3)) for x in row]))

whole = [v for v in vals if abs(v - round(v)) < 1e-9]
print()
print(f"percentile values inspected: {len(vals)}")
print(f"exactly whole milliseconds : {len(whole)}  ({len(whole)/len(vals):.0%})")
print()
print("Whole-millisecond percentiles mean the measurement has no sub-millisecond resolution:")
print("record.timestamp() is ms-grained, so the difference is an integer count of ticks.")
print("Everything faster than one tick computes to 0 and is discarded by the > 0 guard.")
