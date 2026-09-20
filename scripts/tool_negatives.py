#!/usr/bin/env python3
"""
tool_negatives.py -- T2: what a tool does when the arithmetic makes a latency negative.

T2 moves the receiver's clock 0.5 ms and 2 ms early. Nothing about the traffic changes; only the
subtraction does. Every trip shorter than the offset now comes out below zero, and the question
the block asks is what the tool does with those: average over them, drop them, replace them with
zero, crash, or count them.

The answer is not read off the tool's prose. It is read off its own arithmetic. Our program
records the true trip of every message, so for a given offset we can work out the average each
behaviour would have produced:

    keeps every value                 the mean of every trip minus the offset
    drops the negatives               the mean over those still at or above zero
    drops zero and below              the same, without the zeros
    replaces the negatives with zero  the mean with each negative pulled up to zero

Those four are different numbers, and the tool reported one of them. Naming the nearest is the
verdict -- but only when the tool could have told them apart in the first place. Two behaviours
whose averages differ by less than the tool's own printing step are not distinguishable by that
tool, and an offset that made no negatives leaves all four identical. In both cases this reports
that the run cannot decide, rather than naming whichever number happened to be nearest. That is
the same rule the law's own predictions are held to: a point estimate inside a band is not a
result when the instrument could not have put it anywhere else.

    python3 scripts/tool_negatives.py judge --reading reading.json \\
        --reference trips.json --offset-ms 2.0
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tool_readings  # noqa: E402

#: The four things a tool can do with a value the subtraction pushed below zero, in the order
#: they are reported. Each is a rule for which values survive into the tool's own average.
BEHAVIOURS = (
    ("keeps every value", lambda v: [x for x in v]),
    ("drops the negatives", lambda v: [x for x in v if x >= 0]),
    ("drops zero and below", lambda v: [x for x in v if x > 0]),
    ("replaces the negatives with zero", lambda v: [max(0.0, x) for x in v]),
)


def measured(trips_ms, offset_ms):
    """What the tool's own subtraction yields once the receiver's clock reads early."""
    return [trip - offset_ms for trip in trips_ms]


def _mean(values):
    return sum(values) / len(values) if values else None


def predictions(trips_ms, offset_ms):
    """The average and the count each behaviour would produce on these trips at this offset."""
    shown = measured(trips_ms, offset_ms)
    out = {}
    for name, surviving in BEHAVIOURS:
        kept = surviving(shown)
        out[name] = {"avg_ms": _mean(kept), "count": len(kept)}
    return out


def negatives_made(trips_ms, offset_ms):
    """How many of the trips the offset pushes below zero."""
    return sum(1 for value in measured(trips_ms, offset_ms) if value < 0)


def what_it_did(reading, trips_ms, offset_ms, sent=None, exit_code=0):
    """Which behaviour the tool's reported average matches, or why this run cannot say.

    `reading` is one of tool_readings' readings, taken from the tool's output under the offset.
    `trips_ms` are our own program's true trips for the same messages.
    """
    sent = len(trips_ms) if sent is None else sent
    expected = predictions(trips_ms, offset_ms)
    verdict = {"offset_ms": offset_ms, "sent": sent, "exit_code": exit_code,
               "negatives_made": negatives_made(trips_ms, offset_ms),
               "expected": expected, "behaviour": None, "decided": False,
               "reported_avg_ms": None, "off_by_ms": None,
               "count_reported": reading.get("kept"), "count_matches_sent": None,
               "count_agrees_with": [], "why": ""}

    if reading.get("kept") is not None:
        verdict["count_matches_sent"] = reading["kept"] == sent
        verdict["count_agrees_with"] = sorted(
            name for name, said in expected.items() if said["count"] == reading["kept"])

    reported = (reading.get("reported_ms") or {}).get("avg")
    if reported is None:
        verdict["why"] = ("it reported no average under the offset: it crashed, refused the run, "
                          "or printed nothing to read" if exit_code != 0 else
                          "it ran to the end but printed no average under the offset")
        return verdict
    verdict["reported_avg_ms"] = reported

    ranked = sorted(((abs(reported - said["avg_ms"]), name)
                     for name, said in expected.items() if said["avg_ms"] is not None),
                    key=lambda pair: (pair[0], pair[1]))
    if not ranked:
        verdict["why"] = "no reference trip survives this offset, so there is nothing to compare"
        return verdict

    off_by, nearest = ranked[0]
    verdict["behaviour"], verdict["off_by_ms"] = nearest, off_by

    # A tool that writes both timestamps itself, in one process, has both of them moved by
    # libfaketime together, and its subtraction never sees the offset at all. Its average comes
    # out where it was. That is a fact about whether T2 can be asked of the tool this way, not an
    # answer about negatives, and the plan says to check it on each tool first.
    # There is at least one trip here, or `ranked` would have been empty above.
    unmoved = _mean(trips_ms)
    if abs(reported - unmoved) < off_by:
        verdict["behaviour"], verdict["off_by_ms"] = None, None
        verdict["why"] = ("its average did not move with the offset, so the offset never reached "
                          "its subtraction and T2 cannot be asked of it this way")
        return verdict

    if verdict["negatives_made"] == 0:
        verdict["why"] = ("the offset made no negative value, so every behaviour predicts the "
                          "same average and this run cannot tell them apart")
        return verdict
    # The nearest is only an answer if something else predicts a different number. Two of the
    # four often coincide -- dropping the negatives and dropping zero with them agree whenever no
    # trip lands exactly on the offset -- so the runner-up is the nearest behaviour predicting a
    # *different* average. There is always one: with at least one negative, keeping every value
    # and pulling the negatives up to zero cannot give the same mean.
    apart = [name for _, name in ranked[1:]
             if expected[name]["avg_ms"] != expected[nearest]["avg_ms"]]
    runner_up = apart[0]
    if tool_readings.below_its_step(reading, expected[nearest]["avg_ms"],
                                    expected[runner_up]["avg_ms"], "avg"):
        verdict["why"] = ("%s and %s differ by less than the step this tool prints, so its own "
                          "figures cannot separate them" % (nearest, runner_up))
        return verdict
    verdict["decided"] = True
    verdict["why"] = "its average is nearest what %s would give, by %.4f ms" % (nearest, off_by)
    return verdict


def lines(verdict):
    """The verdict as a person reads it."""
    out = ["T2 at an offset of %.3f ms: %d of %d trips go below zero"
           % (verdict["offset_ms"], verdict["negatives_made"], verdict["sent"])]
    for name, said in verdict["expected"].items():
        shown = "nothing survives" if said["avg_ms"] is None else "%.4f ms" % said["avg_ms"]
        out.append("   %-34s would average %s over %d values" % (name, shown, said["count"]))
    if verdict["reported_avg_ms"] is None:
        out.append("   the tool reported no average")
    else:
        out.append("   the tool reported %.4f ms" % verdict["reported_avg_ms"])
    if verdict["count_reported"] is None:
        out.append("   it reports no count, so nothing can be checked against what was sent")
    else:
        out.append("   it counted %d of %d sent%s" % (
            verdict["count_reported"], verdict["sent"],
            "" if verdict["count_matches_sent"] else " -- they do not match"))
    out.append("   %s: %s" % ("VERDICT" if verdict["decided"] else "UNDECIDED", verdict["why"]))
    return out


def reference_trips(path):
    """Our own program's true trips, as a JSON list or one number per line."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith(".json"):
        loaded = json.loads(text)
        return [float(v) for v in (loaded["trips_ms"] if isinstance(loaded, dict) else loaded)]
    return [float(line) for line in text.split() if line]


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="T2: what a tool did with the negatives")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("judge")
    p.add_argument("--reading", required=True, help="the tool's reading under the offset")
    p.add_argument("--reference", required=True, help="our own trips for the same messages")
    p.add_argument("--offset-ms", type=float, required=True)
    p.add_argument("--sent", type=int, default=None)
    p.add_argument("--exit-code", type=int, default=0)
    p.add_argument("--out", default="")
    args = ap.parse_args(argv)
    with open(args.reading, encoding="utf-8") as fh:
        reading = json.load(fh)
    verdict = what_it_did(reading, reference_trips(args.reference), args.offset_ms,
                          sent=args.sent, exit_code=args.exit_code)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(verdict, fh, indent=2, sort_keys=True)
    print("\n".join(lines(verdict)), file=out)
    return 0 if verdict["decided"] else 1


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
