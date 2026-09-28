#!/usr/bin/env python3
"""
cliff_shape.py -- what shape the cliff has, read against two shapes it could have had, through the
frozen judges themselves. Read on 28 September 2026, after the final judging (D32-1). It decides
nothing: every verdict stays the frozen judges' own, and this says what those judges would have
returned had the negative rate followed each shape exactly, run for run.

Every cliff is read two ways by law_curve.py: the free reading (a curve required only never to
rise, its halfway point between the level at 0.9 of the slice and the floor) and the fitted shape
(a plateau, a straight fall and a floor fitted to all eight trips). On Redis for P1 and P7, on
both backends for P9, and in every kernel for P2d, the free reading holds where the fitted shape
does not. The plan's formula has the rate flat for every trip up to the slice. Measured, it is not:
at half the slice the rate is 1.5 to 4 times its level at 0.9 of the slice.

The two shapes, as the rate r at a message's trip T, with slice s, tick h and got-it g:

  plan       the plan's formula, at the trip: r = 1 while T <= s, (s + h - T)/h across the cliff,
             0 past s + h;
  residual   the helper, kept waiting, waits out the rest of the slice another task is running --
             uniform between 0 and s, since it wakes at no particular moment of it -- and then until
             the next tick, uniform between 0 and h; a reading turns negative when that wait
             outlasts the margin T - g. So r = P(R + U > T - g), R ~ U(0, s), U ~ U(0, h):
               1 - x^2/(2sh)          for 0 <= x <= min(s, h)
               1 - (x - m/2)/M        for min <= x <= max, m = min(s, h), M = max(s, h)
               (s + h - x)^2/(2sh)    for max <= x <= s + h,   and 0 beyond, x = T - g.
Neither is fitted: each run keeps its own trip, slice, tick and median got-it, and its measured
rate is replaced by the shape's. A constant scale or floor moves no halfway point, width or start,
so the shapes carry none.

And A2 is read one curve per slice and tick, as its design has it -- two slices in every kernel --
beside the frozen P2, P2b and P2c, which read one curve per tick with both slices in it.

CLI:
    python scripts/cliff_shape.py --root runs/azure/final_campaigns --out <folder>
"""
import argparse
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import law_curve  # noqa: E402
import law_predictions  # noqa: E402
import quality_report  # noqa: E402

#: The campaigns each prediction was judged on in the final judging (judged-27-sep).
BLOCKS = {
    "A1": ["matched/a1_20260918T194622Z", "matched/a1_20260919T000416Z",
           "matched/a1_20260919T030256Z", "matched/a1_20260919T055945Z",
           "matched/a1_20260919T084809Z", "matched/a1_20260926T035408Z",
           "matched/a1_20260927T015829Z"],
    "A4": ["arm/a4_20260918T213410Z", "arm/a4_20260919T001708Z", "arm/a4_20260919T031017Z",
           "arm/a4_20260922T031458Z"],
    "A2 kafka": ["matched/a2_20260923T005640Z", "matched/a2_20260923T174252Z",
                 "matched/a2_20260923T135508Z", "matched/a2_20260924T023016Z",
                 "matched/a2_20260923T211938Z", "matched/a2_20260924T093518Z",
                 "matched/a2_20260923T093827Z"],
    "A2 redis": ["matched-b/a2_20260922T120958Z", "matched-b/a2_20260923T015244Z",
                 "matched-b/a2_20260924T185524Z", "matched-b/a2_20260922T190106Z",
                 "matched-b/a2_20260923T214236Z", "matched-b/a2_20260924T144527Z",
                 "matched-b/a2_20260923T115348Z", "matched-b/a2_20260924T100850Z",
                 "matched-b/a2_20260925T180818Z"]}
#: Each prediction, the block it reads, and the options the final judging gave it.
JUDGED = [("P1", "A1", {"tick_ms": 1.0, "anchor_ms": 3.0}),
          ("P9", "A4", {"tick_ms": 1.0, "anchor_ms": 3.0}),
          ("P2", "A2 kafka", {"tick_ms": 4.0}), ("P2", "A2 redis", {"tick_ms": 4.0}),
          ("P2b", "A2 kafka", {"tick_ms": 10.0}), ("P2b", "A2 redis", {"tick_ms": 10.0}),
          ("P2c", "A2 kafka", {}), ("P2c", "A2 redis", {})]
#: The block P4 is judged on, read for its plateaus with and without go-first priority.
PRIORITY = {"A7": ["matched/a7_20260919T114044Z"]}
POINTS = ("p05s", "p09s", "c02h", "c04h", "c06h", "c08h", "f15h", "f2sh")
#: The trips a width ratio compares, and the kernel it is compared with.
AGAINST_TICK = 1.0


# --- the two shapes --------------------------------------------------------------------------------

def plan_rate(trip, s, h):
    """The plan's formula at the trip: flat to the slice, straight down across one tick."""
    if trip <= s:
        return 1.0
    if trip >= s + h:
        return 0.0
    return (s + h - trip) / h


def residual_rate(x, s, h):
    """P(R + U > x): the rest of a slice, uniform on [0, s], and then up to a tick, uniform on
    [0, h], outlasting the margin x."""
    if x <= 0:
        return 1.0
    if x >= s + h:
        return 0.0
    low, high = min(s, h), max(s, h)
    if x <= low:
        return 1.0 - x * x / (2.0 * s * h)
    if x <= high:
        return 1.0 - (x - low / 2.0) / high
    return (s + h - x) ** 2 / (2.0 * s * h)


SHAPES = {
    "plan": lambda run, s, h: plan_rate(run["trip_ms"], s, h),
    "residual": lambda run, s, h: residual_rate(run["trip_ms"] - run["gotit_ms"], s, h)}


# --- the runs --------------------------------------------------------------------------------------

def gather(root, names):
    """The counted runs of the named campaigns, each with its median got-it beside it."""
    runs = []
    for name in names:
        folder = os.path.join(root, name, "runs")
        where = dict((os.path.basename(d), d) for d in quality_report.run_dirs_under(folder))
        mine, _ = law_curve.counted(folder)
        for run in mine:
            recorded = quality_report.read_json(
                os.path.join(where[run["run"]], "integrity.json")).get("recorded", {})
            runs.append(dict(run, gotit_ms=recorded.get("gotit_median_ms")))
    return runs


def slice_of(run):
    return run.get("slice_ms") or run.get("predicted_slice_ms")


def shaped(runs, shape, tick_ms=1.0):
    """The runs with each one's measured rate replaced by the shape's at its own trip, slice,
    tick and got-it; a run without a slice or a got-it is left out."""
    out = []
    for run in runs:
        s, h = slice_of(run), run.get("tick_ms") or tick_ms
        if s is None or run.get("gotit_ms") is None:
            continue
        out.append(dict(run, negative_rate=SHAPES[shape](run, float(s), float(h))))
    return out


# --- what the curves say ---------------------------------------------------------------------------

def levels(runs):
    """[{backend, slice_ms, point, trip_ms, rate, of_p09s}]: the mean rate and trip at each design
    point, and the rate as a share of the level at 0.9 of the slice, on the ordinary runs (no
    go-first, the Python client)."""
    table = {}
    for run in runs:
        if run.get("priority") or run.get("language") not in (None, "python"):
            continue
        key = (run["backend"], slice_of(run), run.get("point"))
        table.setdefault(key, []).append(run)
    rows = []
    for (backend, s, point), some in sorted(table.items(), key=lambda kv: str(kv[0])):
        if point not in POINTS:
            continue
        base = table.get((backend, s, "p09s"))
        plateau = statistics.mean(r["negative_rate"] for r in base) if base else None
        rate = statistics.mean(r["negative_rate"] for r in some)
        rows.append({"backend": backend, "slice_ms": s, "point": point,
                     "trip_ms": statistics.mean(r["trip_ms"] for r in some), "rate": rate,
                     "of_p09s": rate / plateau if plateau else None})
    return rows


def judged(runs, prediction, options):
    """{part: {free, fitted}}: the frozen judge's two numbers, read without resampling."""
    found = law_predictions.judge(runs, prediction, options.get("tick_ms", 1.0), 0, 0,
                                  anchor_ms=options.get("anchor_ms"))
    parts = found.get("by_part") or {"": found}
    return dict((name, dict((summary, part["by_summary"][summary].get("value"))
                            for summary in ("free", "fitted")))
                for name, part in parts.items())


def widths(runs):
    """[{backend, tick_ms, slice_ms, free_width_ms, fitted_width_ms, fitted_start_ms}]: one curve
    per slice and tick, as A2's design has them."""
    rows = []
    for key, part in sorted(law_curve.groups(runs, ("backend", "tick_ms", "slice_ms")).items(),
                            key=lambda kv: str(kv[0])):
        curve = law_curve.read_off(part, grid=law_curve.GRID)
        rows.append({"backend": key[0], "tick_ms": key[1], "slice_ms": key[2],
                     "free_width_ms": curve and curve["free_width_ms"],
                     "fitted_width_ms": curve and curve["fitted_width_ms"],
                     "fitted_start_ms": curve and curve["fitted"]["start_ms"]})
    return rows


def width_lines(rows):
    """{backend, slice: {free, fitted: {ratio_250, ratio_100, intercept, slope}}}: each slice's
    width at HZ=250 and HZ=100 against HZ=1000, and its straight line on the tick."""
    found = {}
    for backend, s in sorted(set((r["backend"], r["slice_ms"]) for r in rows)):
        mine = dict((r["tick_ms"], r) for r in rows if r["backend"] == backend
                    and r["slice_ms"] == s)
        entry = {}
        for summary in ("free", "fitted"):
            w = dict((tick, r[summary + "_width_ms"]) for tick, r in mine.items())
            one = w.get(AGAINST_TICK)
            line = law_predictions.straight_line(sorted(w), [w[t] for t in sorted(w)])
            entry[summary] = {
                "ratio_250": w[4.0] / one if one and w.get(4.0) else None,
                "ratio_100": w[10.0] / one if one and w.get(10.0) else None,
                "intercept": line and line[1], "slope": line and line[0]}
        found["%s, %g" % (backend, s)] = entry
    return found


def plateaus(runs):
    """{backend: {ordinary, go_first}}: the mean rate at 0.9 of the slice without and with
    go-first priority -- the level P4 cuts, where it is at least 2%, and what it is cut to."""
    found = {}
    for run in runs:
        if run.get("point") == "p09s":
            side = "go_first" if run.get("priority") else "ordinary"
            found.setdefault(run["backend"], {}).setdefault(side, []).append(
                run["negative_rate"])
    return dict((backend, dict((side, statistics.mean(rates)) for side, rates in sides.items()))
                for backend, sides in sorted(found.items()))


def misfit(by_view):
    """{shape: {points, mean_gap, mean_gap_past_half}}: how far each shape's level at each design
    point, as a share of the level at 0.9 of the slice, sits from the measured one -- over every
    point but that one, and over those past half the slice."""
    data = dict(((block, r["backend"], r["slice_ms"], r["point"]), r["of_p09s"])
                for block, rows in by_view["data"].items() for r in rows)
    found = {}
    for shape in sorted(SHAPES):
        gaps = []
        for block, rows in by_view[shape].items():
            for r in rows:
                seen = data.get((block, r["backend"], r["slice_ms"], r["point"]))
                if r["point"] != "p09s" and r["of_p09s"] is not None and seen is not None:
                    gaps.append((r["point"], abs(r["of_p09s"] - seen)))
        past = [gap for point, gap in gaps if point != "p05s"]
        found[shape] = {"points": len(gaps),
                        "mean_gap": statistics.mean(g for _, g in gaps) if gaps else None,
                        "mean_gap_past_half": statistics.mean(past) if past else None}
    return found


def read(root, blocks=None, judged_on=None, priority=None):
    """Everything this reads, for the data and for each shape."""
    blocks = blocks or BLOCKS
    judged_on = JUDGED if judged_on is None else judged_on
    priority = PRIORITY if priority is None else priority
    runs = dict((name, gather(root, names)) for name, names in sorted(blocks.items()))
    views = {"data": runs}
    for shape in SHAPES:
        views[shape] = dict((name, shaped(some, shape)) for name, some in runs.items())
    found = {"levels": {}, "judged": [], "widths": {}, "width_lines": {}}
    for view, by_block in sorted(views.items()):
        found["levels"][view] = dict((name, levels(some)) for name, some in by_block.items()
                                     if not name.startswith("A2"))
        rows = [row for name, some in sorted(by_block.items()) if name.startswith("A2")
                for row in widths(some)]
        found["widths"][view] = rows
        found["width_lines"][view] = width_lines(rows)
        for prediction, block, options in judged_on:
            for part, values in sorted(judged(by_block[block], prediction, options).items()):
                found["judged"].append(dict(values, view=view, prediction=prediction,
                                            block=block, part=part))
    found["misfit"] = misfit(found["levels"])
    found["plateaus"] = dict((name, plateaus(gather(root, names)))
                             for name, names in sorted(priority.items()))
    return found


# --- the command -------------------------------------------------------------------------------------

def _r(value, places=6):
    return round(value, places) if isinstance(value, float) else value


def write(found, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "cliff_levels.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["view", "block", "backend", "slice_ms", "point",
                                           "trip_ms", "rate", "of_p09s"], lineterminator="\n")
        w.writeheader()
        for view, by_block in sorted(found["levels"].items()):
            for block, rows in sorted(by_block.items()):
                for row in rows:
                    w.writerow(dict(((k, _r(v)) for k, v in row.items()), view=view, block=block))
    with open(os.path.join(out_dir, "cliff_judged.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["prediction", "block", "part", "view", "free",
                                           "fitted"], lineterminator="\n")
        w.writeheader()
        for row in found["judged"]:
            w.writerow(dict((k, _r(v)) for k, v in row.items()))
    with open(os.path.join(out_dir, "cliff_widths.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["view", "backend", "tick_ms", "slice_ms",
                                           "free_width_ms", "fitted_width_ms", "fitted_start_ms"],
                           lineterminator="\n")
        w.writeheader()
        for view, rows in sorted(found["widths"].items()):
            for row in rows:
                w.writerow(dict(((k, _r(v)) for k, v in row.items()), view=view))
    with open(os.path.join(out_dir, "cliff_summary.json"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(json.dumps({"width_lines": found["width_lines"], "misfit": found["misfit"],
                             "plateaus": found["plateaus"]}, indent=2, sort_keys=True) + "\n")


def lines(found):
    out = ["The cliff's shape through the frozen judges (decides nothing)"]
    for row in found["judged"]:
        out.append("  %-3s %-8s %-6s %-8s free %s, fitted %s"
                   % (row["prediction"], row["block"], row["part"] or "-", row["view"],
                      _r(row["free"], 3), _r(row["fitted"], 3)))
    for shape, gap in sorted(found["misfit"].items()):
        out.append("  %s shape: levels off the measured ones by %s on average, %s past half the "
                   "slice (%d points)" % (shape, _r(gap["mean_gap"], 3),
                                          _r(gap["mean_gap_past_half"], 3), gap["points"]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="The cliff's shape through the frozen judges")
    ap.add_argument("--root", default=os.path.join("runs", "azure", "final_campaigns"))
    ap.add_argument("--out", default="", help="write the levels, readings and widths here")
    args = ap.parse_args(argv)
    try:
        found = read(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    if args.out:
        write(found, args.out)
    for line in lines(found):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
