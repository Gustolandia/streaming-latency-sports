#!/usr/bin/env python3
"""
law_curve.py -- how one cliff is measured, fixed before the data.

The law says the share of messages that arrive "before" they were sent (the negative rate) sits
on a plateau while the trip is shorter than the scheduler's slice, falls off a cliff around the
slice, and settles on a floor beyond it. A campaign measures that curve by running the same
setup at many trip lengths and counting negatives in each run.

This module turns one such curve into numbers, and only that: it reads the instrument's own
output and says where the fall starts, how wide it is, and where it crosses halfway. It does not
say whether any prediction came true -- law_predictions.py does that, from what this returns.

The plan fixes two summaries, and a prediction passes only if both agree with it:

  fitted shape  a plateau, a straight fall and a floor fitted to the runs, giving the trip at
                which the fall starts and how wide it is. Given where the fall starts and how
                wide it is, the plateau and the floor follow by least squares, so the search is
                over two numbers, on a grid fine enough that the answer does not move.
  free shape    a curve that is only required never to rise, fitted to the runs by pooling
                neighbours that disagree with that (the "pool adjacent violators" method). From
                it come the halfway point and the width of the drop from 90% to 10%. That width
                is read between crossings of a curve drawn straight between the design points, so
                it comes out wider than the fall itself when the nearest points outside the cliff
                sit far from it -- which is why the predictions about width compare ratios of it
                between ticks, where the spacing is the same, rather than the width itself.

Both summaries answer the same two questions -- where the curve crosses halfway, and how wide the
drop is -- and a prediction passes only if both agree with it. They do not answer them alike: the
fitted width is pinned only as far as the design's trip points pin it, and the free width is read
between crossings of a curve drawn straight between those points. Where the points nearest the
cliff sit far from it, both run wide, which is why the predictions about width compare ratios.

Two levels anchor the reading, and the plan names the runs they come from rather than the fit:
the plateau is the level at 0.9 of the slice, and the floor the level at twice the slice plus a
tick. The halfway point is where the curve crosses the middle of those two.

Each run sits at the trip it actually had -- its own measured median trip -- not the trip it was
aimed at. Intervals come from resampling whole rounds, because a round is what the campaign
repeats: runs inside one round share the state the machine was in.

CLI:
    python scripts/law_curve.py read --runs <folder> [--out curve.json]
"""
import argparse
import json
import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import quality_report  # noqa: E402 - a folder of copied runs is what that module already reads

#: The design point whose runs give the plateau level (0.9 of the slice), and the one that gives
#: the floor (twice the slice plus a tick), as law_design.py names them.
PLATEAU_POINT = "p09s"
FLOOR_POINT = "f2sh"
#: The fall's width is read between these shares of the way from the floor up to the plateau.
WIDTH_FROM = 0.9
WIDTH_TO = 0.1
#: How many widths the fitted shape tries, the narrowest it will consider as a share of the trips
#: the runs cover, and how finely it moves the start. One grid, not a search that refines around
#: its own answer: the same rule must apply to the runs and to every resampling of them. The start
#: moves in steps far smaller than the quarter of a millisecond P2d asks about, because a grid no
#: finer than the rule would decide the answer itself; the steps are capped so that a design
#: spanning seconds does not run for ever.
GRID = 96
NARROWEST = 0.005
START_STEP_MS = 0.05
MOST_STARTS = 2000
#: A difference between the plateau and the floor smaller than this is not a fall: on a curve that
#: is flat, least squares still returns two numbers, and they differ in their last bits.
FLAT = 1e-9
#: How many times whole rounds are resampled for an interval, and at what level.
DRAWS = 2000
LEVEL = 0.95


def _levels(runs, point):
    """The negative rates of the runs at one design point."""
    return [run["negative_rate"] for run in runs if run.get("point") == point]


def levels(runs):
    """(plateau, floor): the levels the plan reads off named design points, or None if absent."""
    plateau, floor = _levels(runs, PLATEAU_POINT), _levels(runs, FLOOR_POINT)
    return (sum(plateau) / len(plateau) if plateau else None,
            sum(floor) / len(floor) if floor else None)


def _grid(trips, grid, step_ms=START_STEP_MS):
    """The starts and widths the fit tries: across the trips the runs cover, and widths by ratio."""
    low, high = float(min(trips)), float(max(trips))
    span = high - low
    steps = min(MOST_STARTS, max(3, int(span / step_ms) + 1))
    starts = np.linspace(low, high, steps)
    widths = span * np.exp(math.log(NARROWEST) * (1.0 - np.linspace(0.0, 1.0, grid)))
    return starts, widths


def _shares(trips, starts, widths):
    """How far down the fall each run sits, for every start and width the grid tries."""
    trips = np.asarray(trips, dtype=float)
    share = (trips[None, None, :] - starts[:, None, None]) / widths[None, :, None]
    return np.clip(share, 0.0, 1.0).reshape(-1, len(trips))


def _fit_on_grid(shares, rates):
    """The best start and width on the grid, with the plateau and floor least squares gives.

    Where the fall starts and how wide it is are the only two numbers searched for: with those
    fixed, every run's share of the way down is known and the plateau and the floor follow. The
    whole grid is worked out at once, so the same runs always give the same answer and a
    resampling of the runs costs no more than the fit itself.
    """
    rates = np.asarray(rates, dtype=float)
    above = 1.0 - shares
    s11 = (above * above).sum(axis=1)
    s22 = (shares * shares).sum(axis=1)
    s12 = (above * shares).sum(axis=1)
    b1 = (above * rates).sum(axis=1)
    b2 = (shares * rates).sum(axis=1)
    det = s11 * s22 - s12 * s12
    #: Every run on one side of the fall: the level there is all the data can say.
    one_sided = np.abs(det) < 1e-12
    safe = np.where(one_sided, 1.0, det)
    level = float(rates.mean())
    plateau = np.where(one_sided, level, (b1 * s22 - b2 * s12) / safe)
    floor = np.where(one_sided, level, (b2 * s11 - b1 * s12) / safe)
    cost = (rates * rates).sum() - (plateau * b1 + floor * b2)
    cost = np.where(one_sided, ((rates - level) ** 2).sum(), cost)
    best = int(np.argmin(cost))
    return best, float(plateau[best]), float(floor[best]), float(cost[best])


def fitted_shape(trips, rates, grid=GRID, step_ms=START_STEP_MS):
    """Plateau, floor, where the fall starts and how wide it is, fitted to the runs."""
    if len(trips) < 3 or len(set(trips)) < 2:
        return None
    starts, widths = _grid(trips, grid, step_ms)
    best, plateau, floor, cost = _fit_on_grid(_shares(trips, starts, widths), rates)
    return {"start_ms": float(starts[best // grid]), "width_ms": float(widths[best % grid]),
            "plateau": plateau, "floor": floor, "falls": plateau - floor > FLAT, "cost": cost}


def free_shape(trips, rates):
    """A curve that never rises, fitted by pooling neighbours that disagree with that.

    Returns (trips in order, the fitted level at each). Runs at the same trip are averaged first,
    so the curve has one level per trip.
    """
    together = {}
    for trip, rate in zip(trips, rates):
        together.setdefault(trip, []).append(rate)
    order = sorted(together)
    blocks = [[together[t][0] if len(together[t]) == 1 else sum(together[t]) / len(together[t]),
               1.0] for t in order]
    out = []
    for level, weight in blocks:
        out.append([level, weight])
        while len(out) > 1 and out[-2][0] < out[-1][0]:  # a rise: pool it with what came before
            level, weight = out.pop()
            before = out.pop()
            pooled = (before[0] * before[1] + level * weight) / (before[1] + weight)
            out.append([pooled, before[1] + weight])
    fitted = []
    for level, weight in out:
        fitted += [level] * int(round(weight))
    return order, fitted


def crossing(trips, fitted, level):
    """The trip at which the fitted curve first reaches `level`, straight between its points."""
    if not trips or fitted[0] < level:
        return None
    for i in range(1, len(trips)):
        if fitted[i] <= level:
            before, after = fitted[i - 1], fitted[i]
            if before == after:
                return trips[i]
            share = (before - level) / (before - after)
            return trips[i - 1] + share * (trips[i] - trips[i - 1])
    return None


def read_off(runs, plateau=None, floor=None, grid=GRID):
    """Everything one curve says: both shapes, the halfway point and the width of the drop.

    The plateau and the floor come from the named design points when the campaign ran them, and
    from the fitted shape when it did not.
    """
    trips = [run["trip_ms"] for run in runs]
    rates = [run["negative_rate"] for run in runs]
    fitted = fitted_shape(trips, rates, grid)
    if fitted is None:
        return None
    named_plateau, named_floor = levels(runs)
    plateau = plateau if plateau is not None else (
        named_plateau if named_plateau is not None else fitted["plateau"])
    floor = floor if floor is not None else (
        named_floor if named_floor is not None else fitted["floor"])
    order, curve = free_shape(trips, rates)
    drop = plateau - floor
    #: No fall, no halfway point: where the plateau and the floor are the same level, every trip
    #: is as far down as every other, and a number read off it would only follow the design.
    fell = drop > FLAT
    found = {"runs": len(runs), "fitted": fitted, "plateau": plateau, "floor": floor,
             "halfway_ms": crossing(order, curve, floor + drop / 2.0) if fell else None,
             "from_ms": crossing(order, curve, floor + drop * WIDTH_FROM) if fell else None,
             "to_ms": crossing(order, curve, floor + drop * WIDTH_TO) if fell else None}
    found["free_width_ms"] = (None if found["from_ms"] is None or found["to_ms"] is None
                              else found["to_ms"] - found["from_ms"])
    #: The fitted shape falls straight from the plateau to the floor, so it crosses halfway at the
    #: middle of that fall. The plan asks both summaries to agree, and this is the second one's
    #: answer to the same two questions the free shape answers.
    found["fitted_halfway_ms"] = (fitted["start_ms"] + fitted["width_ms"] / 2.0
                                  if fitted["falls"] else None)
    found["fitted_width_ms"] = fitted["width_ms"] if fitted["falls"] else None
    return found


def by_round(runs):
    """The runs of each round, in the order the rounds were run."""
    rounds = {}
    for run in runs:
        rounds.setdefault(str(run.get("round")), []).append(run)
    return [rounds[key] for key in sorted(rounds, key=lambda k: (len(k), k))]


def resample(runs, rng):
    """Whole rounds drawn with replacement: a round is what the campaign repeats."""
    rounds = by_round(runs)
    drawn = []
    for _ in rounds:
        drawn += rounds[rng.randrange(len(rounds))]
    return drawn


def interval(values, level=LEVEL):
    """The middle `level` of what the resampling gave, as (low, high)."""
    kept = sorted(v for v in values if v is not None)
    if not kept:
        return (None, None)
    edge = (1.0 - level) / 2.0
    #: Rounded, not cut: (1 - 0.95) / 2 is a hair under 0.025 in binary, and cutting would drop
    #: the interval a whole place on each side.
    return (kept[max(0, int(round(edge * (len(kept) - 1))))],
            kept[min(len(kept) - 1, int(round((1.0 - edge) * (len(kept) - 1))))])


def bootstrap(runs, statistic, draws=DRAWS, seed=0, level=LEVEL):
    """(value, low, high, how many resamples the statistic could be read from).

    The statistic is whatever a caller reads off one curve, and the interval comes from drawing
    whole rounds with replacement.
    """
    rng = random.Random(seed)
    value = statistic(runs)
    drawn = []
    for _ in range(draws):
        got = statistic(resample(runs, rng))
        if got is not None:
            drawn.append(got)
    low, high = interval(drawn, level)
    return {"value": value, "low": low, "high": high, "draws": len(drawn)}


def groups(runs, keys=("backend", "slice_ms")):
    """The runs of each curve: one curve per backend and slice, or whatever keys are given."""
    found = {}
    for run in runs:
        found.setdefault(tuple(run.get(key) for key in keys), []).append(run)
    return found


def read_runs(folder, pair=None, campaign=None):
    """The runs of a campaign as this module reads them, from a folder of copied run directories.

    Each run gives the trip it actually had and the share of its messages that arrived before they
    were sent, with the setup it belonged to and the machine pair it ran on. The pair is read from
    the note collect_runs.py leaves beside the runs, because nothing may be pooled across pairs.
    """
    #: The campaign a run belonged to: collect_runs.py copies each one into a folder of its own,
    #: and the block's campaigns are compared through their anchor, so a run has to know which
    #: sitting it came from.
    campaign = campaign or os.path.basename(os.path.dirname(os.path.abspath(folder)))
    if pair is None:
        try:
            pair = quality_report.read_json(
                os.path.join(os.path.dirname(os.path.abspath(folder)), "COLLECTED.json")
            ).get("profile")
        except (OSError, ValueError, KeyError, TypeError):
            pair = None
    found = []
    for run_dir in quality_report.run_dirs_under(folder):
        try:
            row = quality_report.read_json(os.path.join(run_dir, "queue_row.json"))
            params = row["params"] if isinstance(row["params"], dict) else json.loads(row["params"])
            judged = quality_report.read_json(os.path.join(run_dir, "integrity.json"))
            recorded = judged.get("recorded", {})
        except (OSError, ValueError, KeyError, TypeError):
            continue
        found.append({"run": os.path.basename(run_dir), "setup": row.get("setup"), "pair": pair,
                      "campaign": campaign,
                      "round": row.get("round"), "backend": params.get("backend"),
                      "slice_ms": params.get("slice_ns") and params["slice_ns"] / 1e6,
                      "tick_ms": params.get("tick_ms"), "load_pct": params.get("load_pct"),
                      "point": params.get("point"), "priority": params.get("priority"),
                      "cpus": params.get("cpus"), "verdict": judged.get("verdict"),
                      "trip_ms": recorded.get("trip_median_ms"),
                      "negative_rate": recorded.get("measured_negative_rate")})
    return [run for run in found
            if run["trip_ms"] is not None and run["negative_rate"] is not None]


def lines(found):
    """The curves as a person reads them."""
    out = []
    for key in sorted(found, key=str):
        curve = found[key]
        if curve is None:
            out.append("%s: too few runs to read a curve" % (", ".join(str(k) for k in key)))
            continue
        out.append("%s: %d runs, plateau %.3f, floor %.3f, fall starts %.2f ms over %.2f ms, "
                   "halfway %s, drop %s"
                   % (", ".join(str(k) for k in key), curve["runs"], curve["plateau"],
                      curve["floor"], curve["fitted"]["start_ms"], curve["fitted"]["width_ms"],
                      "none" if curve["halfway_ms"] is None else "%.2f ms" % curve["halfway_ms"],
                      "none" if curve["free_width_ms"] is None
                      else "%.2f ms" % curve["free_width_ms"]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a campaign's runs say about one cliff")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("read")
    p.add_argument("--runs", required=True, help="a folder holding the copied run directories")
    p.add_argument("--out", default="", help="write the curves here as JSON")
    args = ap.parse_args(argv)
    try:
        runs = read_runs(args.runs)
        if not runs:
            raise ValueError("no runs with a trip and a negative rate under %s" % args.runs)
        found = dict((key, read_off(part)) for key, part in groups(runs).items())
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(dict((str(k), v) for k, v in found.items()),
                                    indent=2, sort_keys=True) + "\n")
        for line in lines(found):
            print(line, file=out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
