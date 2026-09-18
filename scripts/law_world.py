#!/usr/bin/env python3
"""
law_world.py -- made-up runs, from a world where the law holds and from worlds where it fails.

Two things need data whose answer is known in advance. The analysis code is written and tested
before the first real run it reads, which means it must be fed curves someone built. And the
number of rounds a campaign runs is set by simulating that campaign a thousand times, both under
the law and under the way its prediction could be false, and counting how often the rule answers
yes (scripts/rounds_rule.py).

Both get their data here, so the world the tests trust and the world the rounds are chosen in are
the same world.

What a made-up campaign is built from, as the plan fixes it:
  the law        a plateau while the trip is under the slice, a straight fall one tick wide, and
                 a floor past it. The plateau height and the floor are what the pair's spread
                 pilot and baseline measured at the campaign's load.
  the design     the campaign's own slices, trips, loads and tick, and the planned messages a run
                 keeps.
  what varies    run to run, on the logarithm of the rate, by the spread the spread pilot measured
                 on that pair for that backend; and between campaigns and sessions, by 0.1 ms in
                 trip and 20% in plateau height.

The worlds where a prediction is false are the ones its falsifier names, and no others:
  cliff_fixed          the cliff sits at the same trip whatever the slice (against P1, P9)
  width_fixed          the fall is the same width whatever the tick (against P2, P2b, P2c)
  cliff_moves_with_load  the halfway point moves 0.5 ms between 50% and 88% load (against P3)
  no_priority_effect   go-first changes nothing (against P4)
  cliff_fixed_by_cores the cliff stays put as CPUs are switched off (against P7)
  python_twice_java    Python's rate is twice Java's (against P8)
"""
import math
import random

#: Where a campaign puts its runs, as law_design.py names them: two on the plateau, four across
#: the cliff, two past it.
POINTS = {"p05s": (0.5, 0.0), "p09s": (0.9, 0.0), "c02h": (1.0, 0.2), "c04h": (1.0, 0.4),
          "c06h": (1.0, 0.6), "c08h": (1.0, 0.8), "f15h": (1.0, 1.5), "f2sh": (2.0, 2.0)}
#: What the first pair's pilot measured, and what the plan fixes for shifts between sittings.
SPREAD = 0.18
TRIP_SHIFT_MS = 0.1
PLATEAU_SHIFT = 0.20
#: The worlds this module can build.
WORLDS = ("law", "cliff_fixed", "width_fixed", "cliff_moves_with_load", "no_priority_effect",
          "cliff_fixed_by_cores", "python_twice_java")


def trip_of(point, slice_ms, tick_ms):
    """Where a design point puts a run's trip, for one slice and tick."""
    of_slice, of_tick = POINTS[point]
    return of_slice * slice_ms + of_tick * tick_ms


def rate_of(trip, cliff_ms, width_ms, plateau, floor):
    """The law: a plateau, a straight fall, a floor."""
    share = min(1.0, max(0.0, (trip - cliff_ms) / width_ms)) if width_ms > 0 else (
        0.0 if trip < cliff_ms else 1.0)
    return plateau * (1.0 - share) + floor * share


def _cliff(world, slice_ms, fixed_at, cpus, load_pct, loads):
    """Where the cliff sits in this world: at the slice, or wherever the falsifier puts it."""
    if world == "cliff_fixed":
        return fixed_at
    if world == "cliff_fixed_by_cores" and cpus is not None:
        return fixed_at
    if world == "cliff_moves_with_load" and loads:
        low, high = min(loads), max(loads)
        share = 0.0 if high == low else (load_pct - low) / float(high - low)
        return slice_ms + 0.5 * share
    return slice_ms


def campaign(slices=(3.0,), rounds=4, tick_ms=1.0, plateau=0.30, floor=0.01, spread=SPREAD,
             backends=("kafka",), loads=(75,), points=None, priorities=(False,), cores=(None,),
             languages=(None,), world="law", seed=0, fixed_at=3.0, width_ms=None,
             session_shift=False, python_share=1.0):
    """A campaign's runs, made up in the world named.

    Every run carries what the analysis reads: the trip it actually had, the share of its messages
    that arrived before they were sent, and the setup it belonged to.
    """
    if world not in WORLDS:
        raise ValueError("no such world: %s; the worlds here are %s" % (world, ", ".join(WORLDS)))
    rng = random.Random(seed)
    points = points or list(POINTS)
    runs = []
    for round_ in range(1, rounds + 1):
        trip_shift, plateau_shift = 0.0, 1.0
        if session_shift:
            trip_shift = rng.gauss(0.0, TRIP_SHIFT_MS)
            plateau_shift = math.exp(rng.gauss(0.0, PLATEAU_SHIFT))
        for slice_ms in slices:
            for backend in backends:
                for load_pct in loads:
                    for priority in priorities:
                        for cpus in cores:
                            for language in languages:
                                runs.append(_run(
                                    rng, round_, slice_ms, tick_ms, backend, load_pct, priority,
                                    cpus, language, points, world, plateau, floor, spread,
                                    fixed_at, width_ms, trip_shift, plateau_shift, loads,
                                    python_share))
    return [run for group in runs for run in group]


def _run(rng, round_, slice_ms, tick_ms, backend, load_pct, priority, cpus, language, points,
         world, plateau, floor, spread, fixed_at, width_ms, trip_shift, plateau_shift, loads,
         python_share):
    """The runs of one setup in one round: one per design point."""
    cliff = _cliff(world, slice_ms, fixed_at, cpus, load_pct, loads)
    width = width_ms if width_ms is not None else (
        tick_ms if world != "width_fixed" else 1.0)
    height = plateau * plateau_shift * (1.0 + 0.004 * (load_pct - 75))
    if priority and world != "no_priority_effect":
        height = height / 10.0
    if language == "python" and world == "python_twice_java":
        height = height * 2.0
    elif language == "python":
        height = height * python_share
    made = []
    for point in points:
        trip = trip_of(point, slice_ms, tick_ms) + trip_shift
        rate = rate_of(trip, cliff, width, height, floor)
        if spread:
            rate = rate * math.exp(rng.gauss(0.0, spread))
        made.append({"round": str(round_), "point": point, "backend": backend,
                     "slice_ms": slice_ms, "tick_ms": tick_ms, "load_pct": load_pct,
                     "priority": priority, "cpus": cpus, "language": language,
                     "trip_ms": trip, "negative_rate": min(1.0, max(0.0, rate))})
    return made
