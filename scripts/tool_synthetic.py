#!/usr/bin/env python3
"""
tool_synthetic.py -- T1 and T2 run against made-up tools, before any machine runs them.

The tools block predicts how each tool behaves from reading its source, and T1 to T4 then check
those predictions on real machines. This script asks the question that comes before that: on the
traffic the block plans to send, *could* T1 and T2 tell these classes apart at all? A campaign
that cannot separate two behaviours does not produce a weak result. It produces no result, and
it costs the same.

So each class of tool is built here out of the two things that actually make it behave that way:

  how coarsely its clock reads            a nanosecond, a microsecond, or a whole millisecond
  whether it reads that clock once or twice
      once   it measures the difference in fine units and rounds the answer. The error is at
             most one step, and it never depends on when the message was sent.
      twice  it reads a coarse clock at each end and subtracts two rounded numbers. The error is
             up to two steps and it depends on where in the tick the sending fell -- which is
             why the plan predicts this class is within 0.05 ms on evenly spread sends and can be
             half a millisecond out when the sending is paced in step with the tick.
  what it does with a value that comes out at or below zero
  how many digits it prints

Rounding is truncation toward zero, because that is what integer division does in Java and C,
where these tools are written: a count of nanoseconds divided by a million. Truncating toward
minus infinity instead would turn a value just below zero into a whole millisecond of negative
latency, and that is a different prediction about the one thing T2 measures.

    python3 scripts/tool_synthetic.py report --messages 3000
    python3 scripts/tool_synthetic.py t1 --clock millisecond --reads twice
"""
import argparse
import json
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tool_negatives  # noqa: E402

#: How finely a tool's clock reads, in milliseconds.
CLOCKS = {"nanosecond": 1e-6, "microsecond": 1e-3, "millisecond": 1.0}

#: The staircase T1 adds, in milliseconds (the plan's own steps).
STAIRCASE = (0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.1, 1.5, 2.0)

#: The offsets T2 forces, in milliseconds.
OFFSETS = (0.5, 2.0)

#: The classes the audit sorted the ten tools into, as the two things that make them behave so.
#: Each is (how coarsely the clock reads, once or twice, what it does with odd values, digits).
CLASSES = {
    "low, chops after measuring": ("millisecond", "once", "keeps every value", 0),
    "low, reads a millisecond clock twice": ("millisecond", "twice", "keeps every value", 2),
    "low, drops zero and below": ("millisecond", "once", "drops zero and below", 1),
    "low, drops the negatives": ("millisecond", "once", "drops the negatives", 1),
    "medium": ("microsecond", "once", "replaces the negatives with zero", 2),
    "high, keeps all": ("nanosecond", "once", "keeps every value", 3),
}


#: Trips a real campaign measured, as a quantile function. A3's Kafka runs at 75% load and the
#: 3 ms slice, pooled over four rounds.
MEASURED_TRIPS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "measured", "a3_kafka_trips.json")


def measured_quantiles(path=MEASURED_TRIPS):
    """The quantile function of the trips a real campaign measured."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["quantiles_ms"]


def _at(quantiles, where):
    """The trip at a place between 0 and 1 in that quantile function."""
    place = where * (len(quantiles) - 1)
    low = int(place)
    high = min(low + 1, len(quantiles) - 1)
    return quantiles[low] + (quantiles[high] - quantiles[low]) * (place - low)


def trips(rng, count, median_ms, spread, quantiles=None):
    """True trips: the ones a real campaign measured where they are given, and otherwise spread
    about a median on the logarithm.

    The difference is not cosmetic, and it changes what T2 can do. A trip cannot come out below
    the client's own zero-delay trip, so a measured distribution has a hard floor: A3's Kafka
    trips at 75% load stop dead at 2.03 ms, sit at 2.69 in the middle, and run out to 10.67. A
    lognormal about 3 ms has no floor at all and a far shorter tail. T2 asks how many trips an
    offset can push below zero, and a floor is exactly the thing that decides it.
    """
    if quantiles is None:
        return [median_ms * math.exp(rng.gauss(0.0, spread)) for _ in range(count)]
    return [_at(quantiles, rng.random()) for _ in range(count)]


def seen(rng, trip_ms, resolution_ms, reads, paced, offset_ms=0.0):
    """What one message's trip comes out as, through this tool's own clock and subtraction.

    `paced` sends the message exactly on a tick, which is the worst case for a tool that reads
    the clock twice and the best case for one that reads it once.
    """
    start = 0.0 if paced else rng.random() * resolution_ms
    end = start + trip_ms - offset_ms
    if reads == "twice":
        return (math.trunc(end / resolution_ms)
                - math.trunc(start / resolution_ms)) * resolution_ms
    return math.trunc((end - start) / resolution_ms) * resolution_ms


def surviving(values, odd):
    """The values that reach the tool's own average, given what it does with the odd ones."""
    return dict(tool_negatives.BEHAVIOURS)[odd](values)


def printed(value, digits):
    """A figure as the tool would print it, which is a ceiling on what it can tell anyone."""
    return None if value is None else round(value, digits)


def reading(values, digits, tool="synthetic"):
    """What such a tool would print, in the shape scripts/tool_readings.py produces."""
    step = 10.0 ** (-digits)
    got, steps = {}, {}
    if values:
        ordered = sorted(values)
        for key, figure in (("avg", statistics.fmean(values)),
                            ("min", ordered[0]),
                            ("p50", ordered[len(ordered) // 2]),
                            ("p99", ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))])):
            got[key] = printed(figure, digits)
            steps[key] = step
    return {"tool": tool, "reported_ms": got, "steps_ms": steps,
            "step_ms": step if got else None, "kept": len(values), "unit": None}


def a_run(rng, true_ms, clock, reads, odd, digits, paced=False, offset_ms=0.0):
    """One synthetic run of one tool over one set of true trips."""
    resolution = CLOCKS[clock]
    values = [seen(rng, trip, resolution, reads, paced, offset_ms) for trip in true_ms]
    return reading(surviving(values, odd), digits)


def t1(rng, clock, reads, odd, digits, messages=3000, median_ms=3.0, spread=0.25, paced=False,
       quantiles=None):
    """T1: which of the staircase's steps this tool could report at all.

    The tool is run at each added delay and its average compared with its own average at zero.
    A step it moves by less than its own printing step is one it could not have reported, however
    good its clock -- which is the finding, not a failure of the run.
    """
    base = None
    out = []
    for step_ms in STAIRCASE:
        said = a_run(rng, [t + step_ms for t in trips(rng, messages, median_ms, spread,
                                                      quantiles)],
                     clock, reads, odd, digits, paced)
        avg = said["reported_ms"].get("avg")
        if base is None:
            base = avg
        moved = None if (avg is None or base is None) else avg - base
        out.append({"added_ms": step_ms, "reported_avg_ms": avg, "moved_ms": moved,
                    "seen": bool(moved is not None and abs(moved) >= said["step_ms"]),
                    "off_by_ms": None if moved is None else moved - step_ms})
    return out


def t2(rng, clock, reads, odd, digits, messages=3000, median_ms=3.0, spread=0.25, paced=False,
       offsets=OFFSETS, quantiles=None):
    """T2: whether the forced offsets let the block name what this tool did with the negatives.

    The verdict is taken by the same script the real campaign uses, against the same true trips
    our own program would have recorded, so what this reports is the campaign's own arithmetic on
    traffic whose answer is known.

    The tool's own step is handed to it, as T1 measures it on the real thing. Without that, a
    coarse tool's rule for odd values is predicted from values the tool never saw: a whole
    millisecond truncated toward zero puts everything between minus one and plus one at zero, so
    a tool that drops negatives meets none and drops nothing.
    """
    out = []
    for offset_ms in offsets:
        true_ms = trips(rng, messages, median_ms, spread, quantiles)
        # The same tool on the same traffic with nothing moved: T1's zero step, which is what
        # cancels this tool's own clock bias out of the comparison.
        plain = a_run(rng, true_ms, clock, reads, odd, digits, paced, 0.0)
        said = a_run(rng, true_ms, clock, reads, odd, digits, paced, offset_ms)
        verdict = tool_negatives.what_it_did(said, true_ms, offset_ms, sent=messages,
                                             plain=plain, step_ms=CLOCKS[clock])
        out.append({"offset_ms": offset_ms, "decided": verdict["decided"],
                    "named": verdict["behaviour"], "truth": odd,
                    "right": bool(verdict["decided"] and verdict["behaviour"] == odd),
                    "negatives_made": verdict["negatives_made"], "why": verdict["why"]})
    return out


def reachable_offsets(median_ms):
    """Offsets that put a negative past a whole-millisecond clock, from the trip they act on.

    The plan fixed 0.5 and 2 ms. On the 3 ms trips these campaigns run, 0.5 ms makes no negative
    at all, and 2 ms makes none that a millisecond clock can hold: truncation toward zero needs
    the value past minus one before it is a negative to the tool. These are the offsets that do.
    """
    return (round(median_ms + 1.0, 3), round(median_ms + 3.0, 3))


def report(seed=20260920, messages=3000, median_ms=3.0, spread=0.25, offsets=None,
           quantiles=None):
    """Every class, through both experiments, on evenly spread sends and on paced ones."""
    offsets = OFFSETS if offsets is None else offsets
    out = {}
    for name, (clock, reads, odd, digits) in CLASSES.items():
        out[name] = {}
        for pacing, paced in (("spread evenly", False), ("paced with the tick", True)):
            rng = random.Random(seed)
            out[name][pacing] = {
                "t1": t1(rng, clock, reads, odd, digits, messages, median_ms, spread, paced,
                         quantiles),
                "t2": t2(rng, clock, reads, odd, digits, messages, median_ms, spread, paced,
                         offsets, quantiles)}
    return out


def lines(found):
    """The report as a person reads it: the smallest step each class can see, and T2's verdicts."""
    out = []
    for name in sorted(found):
        out.append(name)
        for pacing in sorted(found[name]):
            steps = found[name][pacing]["t1"]
            seen_at = [s["added_ms"] for s in steps if s["seen"]]
            smallest = "%.1f ms" % min(seen_at) if seen_at else "none of them"
            worst = max((abs(s["off_by_ms"]) for s in steps if s["off_by_ms"] is not None),
                        default=None)
            out.append("   %-20s T1: smallest step it reports %s; furthest its average sits from "
                       "the truth %s" % (pacing, smallest,
                                         "unknown" if worst is None else "%.3f ms" % worst))
            for said in found[name][pacing]["t2"]:
                out.append("   %-20s T2 at %.1f ms: %s" % (
                    "", said["offset_ms"],
                    "names it" if said["right"] else
                    ("names the wrong one (%s)" % said["named"]) if said["decided"] else
                    "undecided -- %s" % said["why"]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="T1 and T2 on made-up tools, before any machine")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("report")
    p.add_argument("--seed", type=int, default=20260920)
    p.add_argument("--messages", type=int, default=3000)
    p.add_argument("--median-ms", type=float, default=3.0)
    p.add_argument("--spread", type=float, default=0.25)
    p.add_argument("--offsets", default="", help="the offsets to force, in milliseconds, comma "
                                                 "separated; the plan's own by default")
    p.add_argument("--made-up-trips", action="store_true",
                   help="draw trips from a lognormal instead of from the ones a campaign "
                        "measured; the measured ones carry a floor that a lognormal has not")
    p.add_argument("--out", default="")
    args = ap.parse_args(argv)
    offsets = tuple(float(v) for v in args.offsets.split(",")) if args.offsets else None
    quantiles = None if args.made_up_trips else measured_quantiles()
    found = report(seed=args.seed, messages=args.messages, median_ms=args.median_ms,
                   spread=args.spread, offsets=offsets, quantiles=quantiles)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(found, fh, indent=2, sort_keys=True)
    print("\n".join(lines(found)), file=out)
    # Every class must be named by T2 at one of the two offsets, or the block cannot tell them
    # apart on this traffic and the plan needs changing before any machine runs it.
    named = all(any(said["right"] for pacing in found[name].values() for said in pacing["t2"])
                for name in found)
    return 0 if named else 1


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
