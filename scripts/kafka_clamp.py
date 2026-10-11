#!/usr/bin/env python3
"""
kafka_clamp.py -- K1: what Kafka's own end-to-end tool does with a message that arrives first.

Kafka's EndToEndLatency sends each record synchronously, waits for the broker's acknowledgment,
and only then polls its consumer for the record (3.7.1, EndToEndLatency.java:110-114). A record
that a consumer could already read before the acknowledgment came back is therefore timed no
earlier than the acknowledgment: the receipt-minus-acknowledgment difference this paper measures
is held at zero by the order of two calls, and nothing in the tool's output says so.

K1 shows how often that happens and what it does to the figures. A copy of the tool, changed only
to write down for each record its offset and the wall-clock instants at which it began, at which
`get()` returned the acknowledgment and at which the poll returned (external/kafka_e2e), runs
beside an independent consumer on the same host and the same wall clock that writes down when each
offset became readable to it. Paired by offset, each record gives

    S          = arrival - acknowledgment       below zero: the record was readable first
    tool       = the tool's own elapsed time    what it prints, and what its percentiles use
    observed   = arrival - begin                the end to end time the observer saw

and a record with S below zero is one the tool timed late, by -S plus whatever its own poll took.

    python3 scripts/kafka_clamp.py judge --trace e2e_trace.csv --arrivals arrivals.csv \\
        --out k1.json
"""
import argparse
import csv
import json
import statistics
import sys


def _rows(path):
    """A file's complete rows, and how many were torn.

    A row is complete when its line ends: a writer stopped in the middle of a line leaves its last
    field cut short, and a cut timestamp is still a number -- in the pilot of 11 October one put the
    observed average at minus 735 million ms. A row missing a field is torn the same way."""
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    torn = 0
    if text and not text.endswith("\n"):
        text, torn = text[:text.rfind("\n") + 1], 1
    rows = [r for r in csv.DictReader(text.splitlines())]
    whole = [r for r in rows if None not in r.values() and None not in r and all(r.values())]
    return whole, torn + len(rows) - len(whole)


def kafka_percentile(values_ms, q):
    """A percentile as EndToEndLatency prints it: whole milliseconds, sorted, indexed at n * q
    (EndToEndLatency.java:122 and 167-170 in 3.7.1)."""
    whole = sorted(int(v) for v in values_ms)
    return whole[int(len(whole) * q)]


def _quantile(values, q):
    """The q-th quantile by linear interpolation between order statistics."""
    v = sorted(values)
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def pair(trace, arrivals):
    """Each traced record with the instant the observer read it, by (partition, offset).

    Returns the paired records and how many traced records the observer never read, which is
    reported rather than dropped: an observer that missed records would bias the share."""
    seen = {}
    for a in arrivals:
        key = (a["partition"], a["offset"])
        at = int(a["arrival_us"])
        seen[key] = min(at, seen.get(key, at))
    out, missed = [], 0
    for t in trace:
        key = (t["partition"], t["offset"])
        if key not in seen:
            missed += 1
            continue
        begin, ack, poll = int(t["begin_us"]), int(t["ack_us"]), int(t["poll_us"])
        out.append({"i": int(t["i"]), "s_ms": (seen[key] - ack) / 1000.0,
                    "tool_ms": int(t["elapsed_ns"]) / 1e6,
                    "observed_ms": (seen[key] - begin) / 1000.0,
                    "late_by_ms": (poll - seen[key]) / 1000.0,
                    "ack_ms": (ack - begin) / 1000.0})
    return out, missed


def judge(trace, arrivals):
    """K1's figures for one run."""
    paired, missed = pair(trace, arrivals)
    if not paired:
        return {"traced": len(trace), "paired": 0, "missed_by_observer": missed,
                "why": "no traced record was read by the observer, so nothing can be paired"}
    early = [p for p in paired if p["s_ms"] < 0]
    tool = [p["tool_ms"] for p in paired]
    observed = [p["observed_ms"] for p in paired]
    s = [p["s_ms"] for p in paired]
    out = {
        "traced": len(trace),
        "paired": len(paired),
        "missed_by_observer": missed,
        "early": len(early),
        "early_share": len(early) / len(paired),
        "s_ms": {"p01": _quantile(s, 0.01), "p50": _quantile(s, 0.5), "p99": _quantile(s, 0.99)},
        "tool_prints": {"avg": statistics.mean(tool), "p50": kafka_percentile(tool, 0.5),
                        "p99": kafka_percentile(tool, 0.99)},
        "observed_ms": {"avg": statistics.mean(observed), "p50": _quantile(observed, 0.5),
                        "p99": _quantile(observed, 0.99)},
        #: Every record's elapsed time covers its own acknowledgment: the instrument's check that
        #: the trace is the tool's own order of events, not a prediction.
        "elapsed_covers_ack": all(p["tool_ms"] + 0.001 >= p["ack_ms"] for p in paired),
    }
    if early:
        late = [p["late_by_ms"] for p in early]
        out["early_reported_late_by_ms"] = {"p50": _quantile(late, 0.5),
                                            "p99": _quantile(late, 0.99), "max": max(late)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="K1: Kafka's end-to-end tool against an observer")
    sub = ap.add_subparsers(dest="command", required=True)
    j = sub.add_parser("judge")
    j.add_argument("--trace", required=True, help="the traced tool's e2e_trace.csv")
    j.add_argument("--arrivals", required=True, help="the observer's arrivals.csv")
    j.add_argument("--out", default="")
    args = ap.parse_args(argv)
    trace, torn_trace = _rows(args.trace)
    arrivals, torn_arrivals = _rows(args.arrivals)
    got = judge(trace, arrivals)
    #: Left out, and said to be: a torn row is never read as a short number.
    got["torn_rows"] = {"trace": torn_trace, "arrivals": torn_arrivals}
    text = json.dumps(got, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    return 0 if got.get("paired") else 1


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
