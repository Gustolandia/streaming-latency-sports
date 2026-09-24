#!/usr/bin/env python3
"""
tool_negatives.py -- T2: what a tool does when the arithmetic makes a latency negative.

T2 moves the receiver's clock 0.5 ms and 2 ms early. Nothing about the traffic changes; only the
subtraction does. Every trip shorter than the offset now comes out below zero, and the question
the block asks is what the tool does with those: average over them, drop them, replace them with
zero, crash, or count them.

The answer is not read off the tool's prose. It is read off its own arithmetic. Our program
records the true trip of every message, so for a given offset we can work out the average, the
smallest value and the count each behaviour would have produced:

    keeps every value                 every trip minus the offset
    drops the negatives               those still at or above zero
    drops zero and below              the same, without the zeros
    replaces the negatives with zero  each negative pulled up to zero

The verdict is what survives, not what is nearest. Each behaviour is held against every figure
the tool printed, to within what its printing can express, and a behaviour that misses any of
them is ruled out with its reason. One left standing is the answer; two are a run that did not
answer, which is reported as that.

Naming the nearest was the first version of this, and synthetic runs showed it unsound. A tool
reading a whole-millisecond clock truncates a trip of 1.9 ms under a 2 ms offset to zero, not to
minus a tenth: its clock destroys the negatives before its handling of them ever runs. The
nearest average then belonged to whichever behaviour the rounding happened to favour, and the
script named a tool as replacing negatives with zero when it did nothing of the sort. Comparing
how far each figure *moved*, against the same tool with no offset, cancels that bias -- so the
tool's reading from T1's zero step is passed in where there is one.

    python3 scripts/tool_negatives.py judge --reading reading.json \\
        --reference trips.json --offset-ms 2.0 --plain plain_reading.json
"""
import argparse
import json
import math
import sys

#: The four things a tool can do with a value the subtraction pushed below zero, in the order
#: they are reported. Each is a rule for which values survive into the tool's own average.
BEHAVIOURS = (
    ("keeps every value", lambda v: [x for x in v]),
    ("drops the negatives", lambda v: [x for x in v if x >= 0]),
    ("drops zero and below", lambda v: [x for x in v if x > 0]),
    ("replaces the negatives with zero", lambda v: [max(0.0, x) for x in v]),
)


def measured(trips_ms, offset_ms, step_ms=None):
    """What the tool's own subtraction yields once the receiver's clock reads early.

    Where the tool's own step is known -- T1 measures it, as the smallest added delay the tool
    can report at all -- the values are put through that step first, because that is what its
    rule for odd values actually sees. A tool reading whole milliseconds and truncating toward
    zero maps everything between minus one and plus one onto zero: it never meets a negative, so
    its rule for negatives never runs, however large the offset. Predicting from the true trips
    instead has it dropping values it never saw, and then no behaviour fits what it printed.

    Truncation is toward zero because that is what integer division does in Java and C, where
    these tools are written.
    """
    shown = [trip - offset_ms for trip in trips_ms]
    if step_ms is None:
        return shown
    return [math.trunc(value / step_ms) * step_ms for value in shown]


def _mean(values):
    return sum(values) / len(values) if values else None


def predictions(trips_ms, offset_ms, step_ms=None):
    """The average, the smallest value and the count each behaviour would produce."""
    shown = measured(trips_ms, offset_ms, step_ms)
    out = {}
    for name, surviving in BEHAVIOURS:
        kept = surviving(shown)
        out[name] = {"avg_ms": _mean(kept), "count": len(kept),
                     "min_ms": min(kept) if kept else None}
    return out


def _step_of(reading, figure):
    """What the tool's printing can express for one of its figures."""
    steps = reading.get("steps_ms") or {}
    return steps.get(figure) if figure in steps else reading.get("step_ms")


def ruled_out(reading, said, base, sent, plain=None):
    """Why this behaviour cannot be what the tool did, or None where nothing rules it out.

    Each figure the tool printed is held against what this behaviour would have produced, to
    within what the tool's own printing can express. A behaviour that survives every figure is
    one this run cannot rule out -- which is not the same as one it has shown.

    Where the tool's reading without the offset is given, the *change* is compared rather than
    the value. A tool reading a coarse clock has a bias of its own -- truncating a count of
    nanoseconds toward zero loses up to a whole millisecond off every trip -- and that bias sits
    in both readings and cancels in the difference. Comparing the values instead charges the
    clock's error to the tool's handling of negatives, which is how the first version of this
    named a tool that had done nothing of the sort.
    """
    # A behaviour that would have left the tool nothing predicts no figures at all, so no figure
    # can rule it out. The tool having printed one rules it out by itself.
    if said["count"] == 0 and (reading.get("reported_ms") or {}):
        return "it printed a figure, and this would have left it nothing to print"
    for figure, key in (("avg", "avg_ms"), ("min", "min_ms")):
        reported = (reading.get("reported_ms") or {}).get(figure)
        step = _step_of(reading, figure)
        if reported is None or step is None or said[key] is None:
            continue
        was = (plain.get("reported_ms") or {}).get(figure) if plain else None
        if was is None or base[key] is None:
            gap, allowed, how = abs(reported - said[key]), step, "its %s of %.4f ms" % (
                figure, reported)
        else:
            # Two printed numbers subtracted, so two steps of room.
            gap = abs((reported - was) - (said[key] - base[key]))
            allowed = 2.0 * step
            how = "its %s moving %.4f ms" % (figure, reported - was)
        if gap > allowed:
            return ("%s is %.4f ms from what this would give, more than the %.4f ms it prints in"
                    % (how, gap, allowed))
    # A count is evidence only when it is short of what was sent. A tool whose count matches may
    # be reporting what it sent rather than what it kept, and ruling anything out on that would
    # be reading a decision out of a number that never made one.
    kept = reading.get("kept")
    if kept is not None and sent is not None and kept < sent and kept != said["count"]:
        return "it counted %d where this would count %d" % (kept, said["count"])
    return None


def negatives_made(trips_ms, offset_ms, step_ms=None):
    """How many values the offset pushes below zero, as the tool itself would see them."""
    return sum(1 for value in measured(trips_ms, offset_ms, step_ms) if value < 0)


#: The verdict D23-1 adds. It is not one of the four behaviours: those are things a tool does
#: with a value below zero, and this is a tool in which no such value can arise.
ONE_CLOCK = "times against one clock"


def figures_moved(reading, control, step_ms=None):
    """How far each figure moved from the control run, and whether any moved past the tool's step.

    The control is the same tool on the same traffic at no offset, taken in the same session
    minutes earlier (D23-1). Comparing against it rather than against T1's zero-delay step keeps
    the comparison inside one session, where the machine is in one state.

    Returns (moved_by, moved): the distance for every figure both runs report, and whether any of
    them is larger than the step the tool can report in. `moved` is None where there is nothing
    to compare, which is not the same as nothing having moved.
    """
    said = reading.get("reported_ms") or {}
    was = (control or {}).get("reported_ms") or {}
    moved_by = {}
    for name in sorted(set(said) & set(was)):
        try:
            moved_by[name] = abs(float(said[name]) - float(was[name]))
        except (TypeError, ValueError):
            continue
    if not moved_by:
        return {}, None
    return moved_by, any(gap > (step_ms or 0.0) for gap in moved_by.values())


def what_it_did(reading, trips_ms, offset_ms, sent=None, exit_code=0, plain=None,
                step_ms=None, control=None, shift_ms=None):
    """Which behaviour this run rules out, and whether one alone is left standing.

    `reading` is one of tool_readings' readings, taken from the tool's output under the offset.
    `trips_ms` are our own program's true trips for the same messages. `plain` is the tool's
    reading of the same traffic with no offset, from T1's zero step; given it, the comparison is
    made on how far each figure moved, which cancels the tool's own clock bias.

    The verdict is what survives, not what is nearest. Something is always nearest, and on a tool
    whose clock is coarser than the difference between two behaviours the nearest is decided by
    the rounding rather than by the tool. A run that leaves two standing has not answered.
    """
    sent = len(trips_ms) if sent is None else sent
    expected = predictions(trips_ms, offset_ms, step_ms)
    base = predictions(trips_ms, 0.0, step_ms)["keeps every value"]
    verdict = {"offset_ms": offset_ms, "sent": sent, "exit_code": exit_code,
               "step_ms": step_ms, "shift_ms": shift_ms, "moved_from_control_ms": {},
               "negatives_made": negatives_made(trips_ms, offset_ms, step_ms),
               "expected": expected, "behaviour": None, "decided": False,
               "reported_avg_ms": (reading.get("reported_ms") or {}).get("avg"),
               "still_standing": [], "ruled_out": {},
               "count_reported": reading.get("kept"), "count_matches_sent": None,
               "count_agrees_with": [], "why": ""}

    if reading.get("kept") is not None:
        verdict["count_matches_sent"] = reading["kept"] == sent
        verdict["count_agrees_with"] = sorted(
            name for name, said in expected.items() if said["count"] == reading["kept"])

    if not (reading.get("reported_ms") or {}):
        verdict["why"] = ("it reported nothing under the offset: it crashed, refused the run, or "
                          "printed nothing to read" if exit_code != 0 else
                          "it ran to the end but printed no latency under the offset")
        return verdict
    if not trips_ms:
        verdict["why"] = "there are no reference trips, so there is nothing to compare"
        return verdict

    #: D23-1. Asked first, because a tool whose figures did not move is not a tool that did
    #: something strange with negatives: it is a tool in which no negative can arise, and the
    #: four behaviours have nothing to say about it. The clock is known to have moved because
    #: the harness measures the shift and refuses to run an offset it cannot confirm.
    moved_by, moved = figures_moved(reading, control, step_ms)
    verdict["moved_from_control_ms"] = moved_by
    if moved is False and shift_ms:
        verdict["behaviour"] = ONE_CLOCK
        verdict["decided"] = True
        verdict["why"] = (
            "it %s: the clock it reads moved %.3f ms and none of its figures moved from the "
            "no-offset run by more than the %s ms it can report in. Both of its timestamps "
            "moved together, so no value below zero can arise in it and the artifact cannot "
            "appear in what it reports"
            % (ONE_CLOCK, shift_ms, "%g" % step_ms if step_ms else "0"))
        return verdict

    for name, said in expected.items():
        why = ruled_out(reading, said, base, sent, plain)
        if why is None:
            verdict["still_standing"].append(name)
        else:
            verdict["ruled_out"][name] = why
    verdict["still_standing"].sort()

    if not verdict["still_standing"]:
        #: D23-1: this used to carry the whole of "either it times against one clock or it does
        #: something unforeseen", which are not the same finding and read identically. The first
        #: is now decided above, from the control run, so what is left here is the second -- and
        #: the two numbers a reader needs to see it are printed beside it.
        verdict["why"] = ("no behaviour accounts for what it printed, and its figures did move: "
                          "the clock moved %s and its figures moved %s. So the offset reached "
                          "its subtraction and it did something with the values below zero that "
                          "none of the four describes"
                          % ("%.3f ms" % shift_ms if shift_ms else "by an unrecorded amount",
                             ", ".join("%s by %.3f ms" % (name, gap)
                                       for name, gap in sorted(moved_by.items()))
                             if moved_by else "by an amount no control run was taken to measure"))
        return verdict
    if verdict["negatives_made"] == 0:
        verdict["why"] = ("the offset made no negative value, so every behaviour predicts the "
                          "same figures and this run cannot tell them apart")
        return verdict
    if len(verdict["still_standing"]) > 1:
        verdict["why"] = ("its own figures are consistent with %s, so this run does not say "
                          "which" % " and ".join(verdict["still_standing"]))
        return verdict
    verdict["behaviour"] = verdict["still_standing"][0]
    verdict["decided"] = True
    verdict["why"] = ("only %s accounts for what it printed; the others are ruled out"
                      % verdict["behaviour"])
    return verdict


def lines(verdict):
    """The verdict as a person reads it."""
    out = ["T2 at an offset of %.3f ms: %d of %d trips go below zero"
           % (verdict["offset_ms"], verdict["negatives_made"], verdict["sent"])]
    for name, said in verdict["expected"].items():
        shown = "nothing survives" if said["avg_ms"] is None else "%.4f ms" % said["avg_ms"]
        out.append("   %-34s would average %s over %d values%s"
                   % (name, shown, said["count"],
                      "" if name in verdict["still_standing"]
                      else " -- ruled out: %s" % verdict["ruled_out"].get(name, "not compared")))
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
    #: The two numbers D23-1 tells the one-clock verdict apart by, printed whether or not that
    #: verdict was reached, so a reader can see what it was decided on.
    if verdict.get("shift_ms"):
        out.append("   the clock it reads was measured to move %.3f ms" % verdict["shift_ms"])
    if verdict.get("moved_from_control_ms"):
        out.append("   from the no-offset run its figures moved %s" % ", ".join(
            "%s by %.3f ms" % (name, gap)
            for name, gap in sorted(verdict["moved_from_control_ms"].items())))
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
    p.add_argument("--plain", default="", help="the same tool's reading with no offset (T1's "
                                               "zero step), which cancels its own clock bias")
    p.add_argument("--step-ms", type=float, default=None,
                   help="the tool's own step, as T1 measured it: the smallest added delay it "
                        "can report. Without it a coarse tool's rule for odd values is "
                        "predicted from values that tool never saw")
    p.add_argument("--control", default="", help="the same tool's reading at no offset, taken in "
                                                 "this T2 session minutes before this run "
                                                 "(D23-1). Its figures are what this run's are "
                                                 "held against")
    p.add_argument("--shift-ms", type=float, default=None,
                   help="how far the clock was measured to actually move under this offset, not "
                        "how far it was asked to. A run whose shift is not confirmed is not made")
    p.add_argument("--out", default="")
    args = ap.parse_args(argv)
    with open(args.reading, encoding="utf-8") as fh:
        reading = json.load(fh)
    plain = None
    if args.plain:
        with open(args.plain, encoding="utf-8") as fh:
            plain = json.load(fh)
    control = None
    if args.control:
        with open(args.control, encoding="utf-8") as fh:
            control = json.load(fh)
    verdict = what_it_did(reading, reference_trips(args.reference), args.offset_ms,
                          sent=args.sent, exit_code=args.exit_code, plain=plain,
                          step_ms=args.step_ms, control=control, shift_ms=args.shift_ms)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(verdict, fh, indent=2, sort_keys=True)
    print("\n".join(lines(verdict)), file=out)
    return 0 if verdict["decided"] else 1


if __name__ == "__main__":  # pragma: no cover - the dispatch is exercised through main()
    sys.exit(main())
