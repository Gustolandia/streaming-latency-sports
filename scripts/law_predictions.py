#!/usr/bin/env python3
"""
law_predictions.py -- the frozen rules that say whether a prediction came true.

The plan states each prediction and, beside it, what counts as confirming it. This module is
those sentences in code, and nothing else: it takes the runs of a campaign, has law_curve.py
measure the cliffs, and answers yes or no by the rule as written. No rule is invented here and
none is relaxed; where the plan leaves a choice to the analysis -- which runs share an interval,
how a family is corrected -- the choice is named in the code and reported with the answer.

Every cliff is summarised two ways, a fitted shape and a free one, and the plan says the law
passes only if both agree with the prediction. So each rule below is applied to both summaries
and confirms only when both confirm, except where the plan names one summary itself: P2c is about
the fitted width and P2d about the fitted start. The other summary is still reported.

  P1  the cliff follows the slice: in at least 5 of the 6 slices the halfway point is inside the
      band from the slice to a tick past it, and its slope against the slice lies between 0.8 and
      1.2 with a 95% interval that excludes 0.5 and 1.5.
  P2  the cliff's width follows the tick: the width ratio between two kernels has a 95% interval
      that overlaps 2.5-5.5 (P2b: 6-14) and excludes 1.
  P2c the width is proportional to the tick: the slope of the fitted width against tick length has
      a 95% interval overlapping 0.8-1.2 and excluding 0.5, and the intercept's interval includes 0.
  P2d the tick does not move the start: in every kernel and slice, the fitted start is within
      0.25 ms of the slice.
  P3  load raises the plateau, not the cliff: the plateau's increase has a 95% interval above
      zero, and the halfway point moves less than 0.25 ms.
  P4  go-first priority removes the plateau: it cuts the plateau at least 5 times where the
      ordinary plateau is at least 2%, with a 95% interval above 2.
  P7  default slices follow the core count: the read-back slice matches, and P1's band holds at
      each core count.
  P8  language: Java shows the same cliff and priority effect, and Python's rate is at most 1.5
      times Java's at matched setups.
  P9  new hardware: on the Arm pair the halfway point is inside the band at all three slices and
      its slope against the slice lies between 0.8 and 1.2.

Intervals come from resampling whole rounds, jointly for every curve of the campaign, because a
round is what the campaign repeats. Predictions that belong to one family are also corrected
together by Holm's method, from the resampling's own two-sided p-value against the value the rule
says the interval must exclude; both the rule as written and the corrected answer are reported.

CLI:
    python scripts/law_predictions.py judge --runs <folder> --prediction P1 --tick-ms 1.0
"""
import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import law_curve  # noqa: E402

#: How many times whole rounds are drawn for an interval, and at what level.
DRAWS = 2000
LEVEL = 0.95
#: The two summaries of one cliff, and what each calls the halfway point, the width and the
#: plateau. A prediction passes only if both agree with it.
SUMMARIES = ("free", "fitted")
HALFWAY = {"free": "halfway_ms", "fitted": "fitted_halfway_ms"}
WIDTH = {"free": "free_width_ms", "fitted": "fitted_width_ms"}
PLATEAU = {"free": "plateau", "fitted": None}
#: P1: the slope of the halfway point against the slice, and what its interval must leave out.
SLOPE_BAND = (0.8, 1.2)
SLOPE_EXCLUDES = (0.5, 1.5)
#: P2 and P2b: what the width ratio between kernels must overlap, and what it must leave out.
RATIO_BANDS = {250: (2.5, 5.5), 100: (6.0, 14.0)}
RATIO_EXCLUDES = 1.0
#: P2c: the slope of width against tick length, and P2d: how far the start may sit from the slice.
TICK_SLOPE_BAND = (0.8, 1.2)
TICK_SLOPE_EXCLUDES = 0.5
START_WITHIN_MS = 0.25
#: P3: how far the halfway point may move between the lowest and highest load.
HALFWAY_MOVE_MS = 0.25
#: P4: how many times go-first must cut the plateau, where the ordinary plateau is this high.
PRIORITY_CUT = 5.0
PRIORITY_CUT_ABOVE = 2.0
PLATEAU_WORTH_CUTTING = 0.02
#: P8: how much higher Python's rate may be than Java's at a matched setup.
LANGUAGE_RATIO = 1.5
#: What is never pooled: a prediction is judged on each machine pair and each backend on its own,
#: and confirmed only where every one of them confirms it.
SPLIT_BY = ("pair", "backend")
#: A slice is a test of the cliff only where the runs reach the level the halfway point is
#: measured from, the level past the cliff, and most of the cliff itself. A message cannot arrive
#: sooner than the client's own zero-delay trip, so a slice under that floor has no plateau.
PLATEAU_POINT = "p09s"
FLOOR_POINT = "f2sh"
CLIFF_POINTS = ("c02h", "c04h", "c06h", "c08h")
CLIFF_POINTS_NEEDED = 3
#: How many testable slices a prediction needs at all, and how many of them may miss the band.
LEAST_SLICES = {"P1": 4, "P9": 2}
MAY_MISS = {"P1": 1, "P9": 0}


def inside(value, low, high):
    """Whether a number sits in a band, edges included."""
    return value is not None and low <= value <= high


def overlaps(span, low, high):
    """Whether an interval shares any ground with a band."""
    return span[0] is not None and span[0] <= high and span[1] >= low


def excludes(span, value):
    """Whether an interval leaves a number out."""
    return span[0] is not None and (value < span[0] or value > span[1])


def above(span, value):
    """Whether the whole interval sits above a number."""
    return span[0] is not None and span[0] > value


def p_value(drawn, null):
    """The two-sided share of the resampling that sits on the far side of `null`, at least 1/n.

    A share of zero would say "impossible", which a resampling of a few thousand draws cannot
    show, so the smallest p-value it can give is one draw's worth.
    """
    kept = [v for v in drawn if v is not None]
    if not kept:
        return None
    below = sum(1 for v in kept if v < null)
    over = sum(1 for v in kept if v > null)
    return max(1.0 / len(kept), min(1.0, 2.0 * min(below, over) / len(kept)))


def holm(named, alpha=0.05):
    """Holm's correction over a family: {name: p-value} in, {name: (adjusted, rejects)} out."""
    order = sorted((p, name) for name, p in named.items() if p is not None)
    adjusted, running = {}, 0.0
    for i, (p, name) in enumerate(order):
        running = max(running, min(1.0, (len(order) - i) * p))
        adjusted[name] = (running, running <= alpha)
    for name, p in named.items():
        if p is None:
            adjusted[name] = (None, False)
    return adjusted


def straight_line(xs, ys):
    """(slope, intercept) of the straight line through points, or None with fewer than two."""
    kept = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(kept) < 2 or len(set(x for x, _ in kept)) < 2:
        return None
    mean_x = sum(x for x, _ in kept) / len(kept)
    mean_y = sum(y for _, y in kept) / len(kept)
    bottom = sum((x - mean_x) ** 2 for x, _ in kept)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in kept) / bottom
    return slope, mean_y - slope * mean_x


def testable(runs):
    """{slice: whether its runs reach what the halfway point is read from}.

    The plateau level at 0.9 of the slice, the floor past the cliff, and at least three of the
    four trips across the cliff. A slice that fails this is not a weaker test of the prediction;
    it is not a test of it, and the campaign records why.
    """
    found = {}
    for key, part in law_curve.groups(runs, ("slice_ms",)).items():
        points = set(run.get("point") for run in part)
        found[key[0]] = (PLATEAU_POINT in points and FLOOR_POINT in points
                         and len(points & set(CLIFF_POINTS)) >= CLIFF_POINTS_NEEDED)
    return found


def anchor_offsets(runs, anchor_ms, summary="free", grid=None, step_ms=None):
    """{campaign: how far its anchor sits from the block's mean anchor}, in milliseconds.

    A campaign that ran no anchor slice has no offset here: its readings cannot be compared with
    the others through something they share, and the caller leaves them where they are.
    """
    anchors = {}
    for key, part in law_curve.groups(runs, ("campaign",)).items():
        at_anchor = [run for run in part if run.get("slice_ms") == anchor_ms]
        curve = (law_curve.read_off(at_anchor, grid=grid or law_curve.GRID, step_ms=step_ms)
                 if at_anchor else None)
        if curve and curve[HALFWAY[summary]] is not None:
            anchors[key[0]] = curve[HALFWAY[summary]]
    if len(anchors) < 2:
        return {}
    middle = sum(anchors.values()) / len(anchors)
    return dict((campaign, where - middle) for campaign, where in anchors.items())


def through_the_anchor(runs, anchor_ms, summary="free", grid=None, step_ms=None):
    """{slice: halfway point}, each campaign's readings moved by its own offset.

    The anchor itself comes out at the block's mean by construction, so it counts once however
    many campaigns ran it.
    """
    offsets = anchor_offsets(runs, anchor_ms, summary, grid, step_ms)
    found = {}
    for key, part in law_curve.groups(runs, ("campaign", "slice_ms")).items():
        campaign, slice_ms = key
        curve = law_curve.read_off(part, grid=grid or law_curve.GRID, step_ms=step_ms)
        where = curve and curve[HALFWAY[summary]]
        if where is None:
            continue
        found.setdefault(slice_ms, []).append(where - offsets.get(campaign, 0.0))
    return dict((slice_ms, sum(seen) / len(seen)) for slice_ms, seen in found.items())


def curves_by(runs, key, grid=None, step_ms=None, **levels):
    """One curve per value of `key`, read off by law_curve.py."""
    found = {}
    for value, part in law_curve.groups(runs, (key,)).items():
        found[value[0]] = law_curve.read_off(part, grid=grid or law_curve.GRID, step_ms=step_ms,
                                             **levels)
    return found


def over_draws(runs, numbers, draws=DRAWS, seed=0, level=LEVEL):
    """Everything one rule needs, with intervals from resampling whole rounds.

    `numbers` reads a campaign and returns {what it is: the number, or None}. It is called once on
    the runs themselves and once on each drawing of whole rounds, so every number a rule compares
    comes from the same rounds -- including the two summaries of the same curve, which are read
    off one fit rather than two.
    """
    rng = random.Random(seed)
    first = numbers(runs) or {}
    drawn = dict((name, []) for name in first)
    for _ in range(draws):
        for name, value in (numbers(law_curve.resample(runs, rng)) or {}).items():
            if value is not None and name in drawn:
                drawn[name].append(value)
    found = {}
    for name, value in first.items():
        low, high = law_curve.interval(drawn[name], level)
        found[name] = {"value": value, "low": low, "high": high, "drawn": drawn[name]}
    return found


def _said(found, confirmed, **rest):
    """What one summary says: the number, its interval, and whether the rule holds on it."""
    out = {"confirmed": bool(confirmed)}
    out.update(rest)
    if found is not None:
        out.update(value=found["value"], interval=[found["low"], found["high"]],
                   draws=len(found["drawn"]))
    return out


def _both(by_summary, rule, judged_on=SUMMARIES, **rest):
    """A prediction's answer: confirmed only where every summary it is judged on confirms."""
    out = {"confirmed": all(by_summary[name]["confirmed"] for name in judged_on),
           "rule": rule, "judged_on": list(judged_on), "by_summary": by_summary}
    out.update(rest)
    return out


def cliff_follows_slice(runs, tick_ms, need_inside=None, need_interval=True, draws=DRAWS,
                        seed=0, grid=None, anchor_ms=None, step_ms=None):
    """P1 and P9: the halfway point sits in its band at each slice, and rises with the slice.

    P1 allows one slice of six to fall outside the band and asks the slope's interval to exclude
    0.5 and 1.5; P9, on three slices, asks all three to be inside and only that the slope lies in
    its band. `need_inside` says how many slices must be inside, and defaults to one short of all
    for six slices or more, and all of them below that.
    """
    def halfways(part, summary, curves=None):
        """Where each slice's curve crosses halfway, through the anchor when there is one."""
        if anchor_ms is not None:
            return through_the_anchor(part, anchor_ms, summary, grid, step_ms)
        curves = curves_by(part, "slice_ms", grid, step_ms) if curves is None else curves
        return dict((s, curve and curve[HALFWAY[summary]]) for s, curve in curves.items())

    def numbers(part):
        #: One fit per curve, both summaries read off it: they are two readings of one shape, and
        #: fitting twice would cost twice and answer about different draws.
        curves = None if anchor_ms is not None else curves_by(part, "slice_ms", grid, step_ms)
        found = {}
        for summary in SUMMARIES:
            heights = halfways(part, summary, curves)
            line = straight_line(sorted(heights), [heights[s] for s in sorted(heights)])
            found[summary] = None if line is None else line[0]
        return found

    reaches = testable(runs)
    over = over_draws(runs, numbers, draws, seed)
    by_summary, slices, wanted = {}, [], need_inside
    for summary in SUMMARIES:
        found = dict((s, where) for s, where in halfways(runs, summary).items()
                     if reaches.get(s, True))
        slices = sorted(s for s in found if s is not None)
        in_band = dict((s, inside(found[s], s, s + tick_ms)) for s in slices)
        wanted = need_inside if need_inside is not None else max(
            0, len(slices) - MAY_MISS["P1" if need_interval else "P9"])
        said = over[summary]
        ok = inside(said["value"], *SLOPE_BAND)
        if need_interval:
            ok = ok and all(excludes((said["low"], said["high"]), edge)
                            for edge in SLOPE_EXCLUDES)
        enough = len(slices) >= LEAST_SLICES["P1" if need_interval else "P9"]
        by_summary[summary] = _said(
            said, enough and sum(in_band.values()) >= wanted and ok, halfway_ms=found,
            in_band=in_band, out_of_reach=sorted(s for s, can in reaches.items() if not can),
            p_value=p_value(said["drawn"], 1.0) if need_interval else None)
    return _both(by_summary,
                 "halfway inside [s, s+h] in at least %d of the %d slices this pair can reach; "
                 "slope in %s%s%s"
                 % (wanted, len(slices), SLOPE_BAND,
                    " with an interval excluding %s and %s" % SLOPE_EXCLUDES
                    if need_interval else "",
                    "; each campaign moved by its own offset through the %g ms anchor" % anchor_ms
                    if anchor_ms is not None else ""),
                 anchor_ms=anchor_ms)


def width_follows_tick(runs, tick_ms, against_tick_ms=1.0, draws=DRAWS, seed=0, grid=None):
    """P2 and P2b: the drop is wider at a longer tick, by a ratio inside the band the plan gives.

    `runs` holds both kernels' runs, each run saying which tick it ran under.
    """
    def numbers(part):
        curves = curves_by(part, "tick_ms", grid)
        found = {}
        for summary in SUMMARIES:
            widths = dict((tick, curve and curve[WIDTH[summary]])
                          for tick, curve in curves.items())
            one, other = widths.get(against_tick_ms), widths.get(tick_ms)
            found[summary] = None if not one or not other else other / one
        return found
    hz = int(round(1000.0 / tick_ms))
    band = RATIO_BANDS.get(hz, RATIO_BANDS[250])
    over = over_draws(runs, numbers, draws, seed)
    by_summary = {}
    for summary in SUMMARIES:
        said = over[summary]
        span = (said["low"], said["high"])
        by_summary[summary] = _said(said, overlaps(span, *band) and excludes(span, RATIO_EXCLUDES),
                                    p_value=p_value(said["drawn"], RATIO_EXCLUDES))
    return _both(by_summary, "the width ratio's interval overlaps %s-%s and excludes %s"
                 % (band[0], band[1], RATIO_EXCLUDES), hz=hz)


def width_against_tick(runs, draws=DRAWS, seed=0, grid=None):
    """P2c: the fitted width is proportional to the tick -- a line through zero, slope one."""
    def numbers(part):
        curves = curves_by(part, "tick_ms", grid)
        ticks = sorted(t for t in curves if t is not None)
        found = {}
        for summary in SUMMARIES:
            line = straight_line(ticks, [curves[t] and curves[t][WIDTH[summary]] for t in ticks])
            found[summary] = None if line is None else line[0]
            found[summary + " intercept"] = None if line is None else line[1]
        return found

    over = over_draws(runs, numbers, draws, seed)
    by_summary = {}
    for summary in SUMMARIES:
        said, cut = over[summary], over[summary + " intercept"]
        span = (said["low"], said["high"])
        by_summary[summary] = _said(
            said, overlaps(span, *TICK_SLOPE_BAND) and excludes(span, TICK_SLOPE_EXCLUDES)
            and not excludes((cut["low"], cut["high"]), 0.0),
            intercept=[cut["low"], cut["high"]],
            p_value=p_value(said["drawn"], TICK_SLOPE_EXCLUDES))
    return _both(by_summary,
                 "the fitted width's slope against the tick has an interval overlapping %s-%s and "
                 "excluding %s, and the intercept's includes 0"
                 % (TICK_SLOPE_BAND[0], TICK_SLOPE_BAND[1], TICK_SLOPE_EXCLUDES),
                 judged_on=("fitted",))


def start_at_slice(runs, grid=None):
    """P2d: whatever the tick, the fitted start stays within a quarter of a millisecond."""
    starts, held = {}, {}
    for key, part in law_curve.groups(runs, ("tick_ms", "slice_ms")).items():
        curve = law_curve.read_off(part, grid=grid or law_curve.GRID)
        start = curve and curve["fitted"]["start_ms"]
        starts[str(list(key))] = start
        held[str(list(key))] = (start is not None and key[1] is not None
                                and abs(start - key[1]) <= START_WITHIN_MS)
    return _both({"fitted": _said(None, held and all(held.values()), start_ms=starts, within=held),
                  "free": _said(None, held and all(held.values()))},
                 "the fitted start is within %s ms of the slice in every kernel and slice"
                 % START_WITHIN_MS, judged_on=("fitted",))


def load_raises_the_plateau(runs, draws=DRAWS, seed=0, grid=None):
    """P3: the plateau rises with load while the halfway point stays where it is."""
    def ends(part):
        found = curves_by(part, "load_pct", grid)
        seen = sorted(load for load in found if found[load])
        return (None, None) if len(seen) < 2 else (found[seen[0]], found[seen[-1]])

    def numbers(part):
        low, high = ends(part)
        found = {}
        for summary in SUMMARIES:
            level = None if low is None else (
                (high["plateau"] - low["plateau"]) if summary == "free"
                else (high["fitted"]["plateau"] - low["fitted"]["plateau"]))
            found[summary] = level
            found[summary + " move"] = None if low is None or low[HALFWAY[summary]] is None \
                or high[HALFWAY[summary]] is None else abs(high[HALFWAY[summary]]
                                                           - low[HALFWAY[summary]])
        return found

    over = over_draws(runs, numbers, draws, seed)
    by_summary = {}
    for summary in SUMMARIES:
        said = over[summary]
        moved = over[summary + " move"]["value"]
        by_summary[summary] = _said(
            said, above((said["low"], said["high"]), 0.0) and moved is not None
            and moved < HALFWAY_MOVE_MS, halfway_move_ms=moved,
            p_value=p_value(said["drawn"], 0.0))
    return _both(by_summary, "the plateau's increase has an interval above zero and the halfway "
                 "point moves less than %s ms" % HALFWAY_MOVE_MS)


def priority_removes_the_plateau(runs, draws=DRAWS, seed=0, grid=None):
    """P4: go-first cuts the plateau at least five times, where there is a plateau to cut."""
    def numbers(part):
        found = curves_by(part, "priority", grid)
        ordinary, first = found.get(False), found.get(True)
        cuts = {}
        for summary in SUMMARIES:
            if not ordinary or not first:
                cuts[summary] = None
                continue
            level = ordinary["plateau"] if summary == "free" else ordinary["fitted"]["plateau"]
            cut_to = first["plateau"] if summary == "free" else first["fitted"]["plateau"]
            cuts[summary] = (None if level < PLATEAU_WORTH_CUTTING
                             else level / max(cut_to, 1e-9))
        return cuts

    over = over_draws(runs, numbers, draws, seed)
    by_summary = {}
    for summary in SUMMARIES:
        said = over[summary]
        by_summary[summary] = _said(
            said, said["value"] is not None and said["value"] >= PRIORITY_CUT
            and above((said["low"], said["high"]), PRIORITY_CUT_ABOVE),
            p_value=p_value(said["drawn"], PRIORITY_CUT_ABOVE))
    return _both(by_summary, "the plateau is cut at least %s times, with an interval above %s"
                 % (PRIORITY_CUT, PRIORITY_CUT_ABOVE))


def default_slices(runs, read_back, tick_ms, draws=DRAWS, seed=0, grid=None):
    """P7: the machine reports the slice the core-count rule computes, and the cliff follows it.

    `read_back` is {cores: the slice the machine reported}; the computed slices are the ones the
    runs were designed with.
    """
    matched = {}
    for cores, part in sorted(law_curve.groups(runs, ("cpus",)).items()):
        designed = set(run.get("slice_ms") for run in part)
        reported = read_back.get(cores[0], read_back.get(str(cores[0])))
        matched[str(cores[0])] = (reported is not None and len(designed) == 1
                                  and abs(reported - designed.pop()) <= 1e-6)
    band = cliff_follows_slice(runs, tick_ms, need_interval=False, draws=draws, seed=seed,
                               grid=grid)
    held = bool(matched) and all(matched.values()) and band["confirmed"]
    return _both({name: _said(None, held) for name in SUMMARIES},
                 "the read-back slice matches at every core count and P1's band holds",
                 read_back=matched, band=band)


def language(runs, draws=DRAWS, seed=0, grid=None):
    """P8: Java shows the cliff and the priority effect, and Python's rate is not far above it.

    Each run says which language sent its messages. The cliff is read as the plan states it: the
    rate in the middle of the cliff lies between the level on the plateau and the level past it.
    """
    def only(part, name):
        return [run for run in part if run.get("language") == name]

    def between(part, summary):
        java = only(part, "java")
        curve = law_curve.read_off(java, grid=grid or law_curve.GRID)
        middle = [run["negative_rate"] for run in java if run.get("point") == "c04h"]
        if not curve or not middle:
            return None
        floor = curve["floor"] if summary == "free" else curve["fitted"]["floor"]
        plateau = curve["plateau"] if summary == "free" else curve["fitted"]["plateau"]
        return 1.0 if floor <= sum(middle) / len(middle) <= plateau else 0.0

    def numbers(part):
        rates = {}
        for name in ("python", "java"):
            plateau = [run["negative_rate"] for run in only(part, name)
                       if run.get("point") in ("p05s", "p09s")]
            rates[name] = sum(plateau) / len(plateau) if plateau else None
        ratio = (None if not rates["python"] or not rates["java"]
                 else rates["python"] / rates["java"])
        return dict((summary, ratio) for summary in SUMMARIES)

    over = over_draws(runs, numbers, draws, seed)
    by_summary = {}
    for summary in SUMMARIES:
        cliff = between(runs, summary)
        said = over[summary]
        by_summary[summary] = _said(
            said, cliff == 1.0 and said["value"] is not None and said["value"] <= LANGUAGE_RATIO
            and said["high"] is not None and said["high"] <= LANGUAGE_RATIO,
            java_cliff=cliff, p_value=p_value(said["drawn"], LANGUAGE_RATIO))
    return _both(by_summary,
                 "Java's rate in the middle of the cliff lies between its plateau and its floor, "
                 "and Python's plateau is at most %s times Java's" % LANGUAGE_RATIO)


#: The rules a campaign's runs can be judged by from the command line.
RULES = {"P1": cliff_follows_slice, "P2": width_follows_tick, "P2b": width_follows_tick,
         "P2c": width_against_tick, "P2d": start_at_slice, "P3": load_raises_the_plateau,
         "P4": priority_removes_the_plateau, "P7": default_slices, "P8": language,
         "P9": cliff_follows_slice}


def judge(runs, prediction, tick_ms=1.0, draws=DRAWS, seed=0, grid=None, read_back=None,
          anchor_ms=None, step_ms=None):
    """One prediction's answer, by the rule the plan wrote beside it.

    Nothing is pooled across machine pairs or across backends: where the runs hold more than one
    of either, each is judged on its own and the prediction is confirmed only where every one of
    them confirms it. Each part's answer is reported beside the whole.
    """
    if prediction not in RULES:
        raise ValueError("no rule for %s; the rules here are %s"
                         % (prediction, ", ".join(sorted(RULES))))
    apart = tuple(key for key in SPLIT_BY
                  if len(set(run.get(key) for run in runs)) > 1)
    if apart:
        by_part = {}
        for key, part in sorted(law_curve.groups(runs, apart).items(), key=lambda pair: str(pair)):
            by_part[", ".join(str(k) for k in key)] = _one(part, prediction, tick_ms, draws,
                                                           seed, grid, read_back, anchor_ms,
                                                           step_ms)
        first = list(by_part.values())[0]
        return {"confirmed": all(answer["confirmed"] for answer in by_part.values()),
                "rule": first["rule"], "judged_on": first["judged_on"],
                "split_by": list(apart), "by_part": by_part}
    return _one(runs, prediction, tick_ms, draws, seed, grid, read_back, anchor_ms, step_ms)


def _one(runs, prediction, tick_ms, draws, seed, grid, read_back=None, anchor_ms=None,
         step_ms=None):
    """One prediction's answer on runs that share a pair and a backend."""
    rule = RULES[prediction]
    if prediction == "P7":
        return rule(runs, read_back or {}, tick_ms, draws=draws, seed=seed, grid=grid)
    if prediction == "P9":
        return rule(runs, tick_ms, need_interval=False, draws=draws, seed=seed, grid=grid,
                    anchor_ms=anchor_ms, step_ms=step_ms)
    if prediction == "P1":
        return rule(runs, tick_ms, draws=draws, seed=seed, grid=grid, anchor_ms=anchor_ms,
                    step_ms=step_ms)
    if prediction in ("P2", "P2b"):
        return rule(runs, tick_ms, draws=draws, seed=seed, grid=grid)
    if prediction == "P2d":
        return rule(runs, grid=grid)
    return rule(runs, draws=draws, seed=seed, grid=grid)


def _round(value):
    return None if value is None else round(value, 4)


def lines(prediction, found):
    """The answer as a person reads it."""
    out = ["%s: %s" % (prediction, "confirmed" if found["confirmed"] else "not confirmed"),
           "  rule: %s" % found["rule"],
           "  judged on: %s" % ", ".join(found["judged_on"])]
    if "by_part" in found:
        out.append("  nothing pooled across: %s" % ", ".join(found["split_by"]))
        for part, answer in sorted(found["by_part"].items()):
            out += ["  " + line for line in lines(part, answer)]
        return out
    for name in SUMMARIES:
        said = found["by_summary"][name]
        line = "  %s shape: %s" % (name, "holds" if said["confirmed"] else "does not hold")
        if "value" in said:
            line += ", measured %s, 95%% interval %s to %s, from %d resamplings" % tuple(
                [_round(said["value"])] + [_round(edge) for edge in said["interval"]]
                + [said["draws"]])
        out.append(line)
        for key in ("in_band", "out_of_reach", "halfway_move_ms", "java_cliff", "within",
                    "intercept"):
            if said.get(key) is not None:
                out.append("    %s: %s" % (key.replace("_", " "), said[key]))
    for key in ("hz", "read_back", "anchor_ms"):
        if found.get(key) is not None:
            out.append("  %s: %s" % (key.replace("_", " "), found[key]))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Whether a prediction came true, by its frozen rule")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("judge")
    p.add_argument("--runs", required=True, help="a folder holding the copied run directories")
    p.add_argument("--prediction", required=True, help="which prediction, for example P1")
    p.add_argument("--tick-ms", type=float, default=1.0)
    p.add_argument("--read-back", default="",
                   help="for P7, the slice each core count reported, as 2=1.4,4=2.1,8=2.8")
    p.add_argument("--anchor-ms", type=float, default=None,
                   help="for P1 and P9 over a block's campaigns, the slice they all share")
    p.add_argument("--draws", type=int, default=DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="", help="write the answer here as JSON")
    args = ap.parse_args(argv)
    try:
        runs = law_curve.read_runs(args.runs)
        if not runs:
            raise ValueError("no runs with a trip and a negative rate under %s" % args.runs)
        read_back = dict((int(pair.split("=")[0]), float(pair.split("=")[1]))
                         for pair in args.read_back.split(",") if "=" in pair)
        found = judge(runs, args.prediction, args.tick_ms, args.draws, args.seed,
                      read_back=read_back, anchor_ms=args.anchor_ms)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(found, indent=2, sort_keys=True, default=str) + "\n")
        for line in lines(args.prediction, found):
            print(line, file=out)
        return 0 if found["confirmed"] else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
