#!/usr/bin/env python3
"""
law_design.py -- the run lists for the plateau-cliff-floor experiments, built from the machine.

The law predicts where the negative rate falls off a cliff (at the base slice s) and how wide
the cliff is (one tick h). A run list that tests it must put its trip lengths where the
prediction says the action is, on the machine actually running. That is why the list is
generated rather than typed:

  trip points  for each slice: two on the plateau (0.5s, 0.9s), four across the cliff
               (s + 0.2h to s + 0.8h), two past it (s + 1.5h and 2(s + h)); the smaller blocks
               use subsets of these.
  delays       a run's trip is the machine's own zero-delay trip plus what the receiver-only
               delay adds, and the first Azure pilot showed that is not the delay itself: Kafka's
               trip moved 0.89 ms per millisecond added, Redis's 1.24. So a point's delay is read
               off the session's calibration (block C0, fitted by delay_calibration.py). A design
               made from B0's baseline alone assumes one-for-one, and every setup records which
               way it was placed. A point the placement cannot reach (below the zero-delay trip,
               or beyond the calibration's longest step) is listed as unreachable in the design,
               not quietly dropped.
  repeats      the rounds come from simulating the campaign's own prediction and decision rule at
               the spread the spread pilot measured (rounds_rule.py, the plan's D4-2). This script
               measures that spread and takes the number; it does not invent one. Where no
               prediction is tested the plan fixes the number instead: B0 runs 3, C0 runs 2 and 4
               in the first pair's staircase, P0 runs 5.

Blocks, each a design for scripts/run_queue.py:
  B0  baseline trips: no delay, the kernel's own slice, each backend at 50, 75 and 88% load
  C0  delay calibration: no delay twice, then 1, 2, 4 and 8 ms (doubling up to --up-to-ms),
      each backend at the session's load and the kernel's own slice, 2 rounds (the first
      session's staircase, S0-1, runs up to 16 ms over 4: --up-to-ms 16 --rounds 4)
  P0  the spread pilot: 2 slices x 4 points x 2 backends, 5 rounds
  A1  slice dose-response: 6 slices x 8 points x 2 backends at 75% load
  A2  tick: 2 slices x 8 points x 2 backends, made once per tick session
  A3  load: 3 loads x 2 slices x 6 points x 2 backends
  A4  another machine type: 3 slices x 8 points x 2 backends, made on the arm profile
  A5  the default slice follows the core count: 2, 4 and 8 CPUs online, the kernel's own slice
  A7  go-first priority: 2 slices x 3 points x ordinary and go-first x 2 backends
A6 is not a block of its own. A1 and A3 setups carry trace_half, and the runner traces the half
of those runs whose queue key hashes even.

CLI:
    python3 scripts/law_design.py design --block B0 --settings settings.json --seed 1 --out b0.json
    python3 scripts/law_design.py baseline --queue b0.csv --out baseline.json
    python3 scripts/law_design.py design --block C0 --settings settings.json --seed 2 --out c0.json
    python3 scripts/delay_calibration.py fit --queue c0.csv --out calibration.json
    python3 scripts/law_design.py rounds --queue p0.csv --block A1
    python3 scripts/law_design.py design --block A1 --settings settings.json \\
        --calibration calibration.json --rounds 26 --seed 20260915 --out a1.json
"""
import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import delay_calibration  # noqa: E402
import kernel_constants  # noqa: E402
import pilot_checks  # noqa: E402
import run_queue  # noqa: E402
import sched_settings  # noqa: E402

#: name -> (a, b): the trip a*s + b*h for slice s and tick h. The names stay inside the
#: characters a Kafka topic accepts, because the run id built from them names the topic.
POINT_FORM = {
    "p05s": (0.5, 0.0), "p09s": (0.9, 0.0),
    "c02h": (1.0, 0.2), "c04h": (1.0, 0.4), "c05h": (1.0, 0.5), "c06h": (1.0, 0.6),
    "c08h": (1.0, 0.8),
    "f15h": (1.0, 1.5), "f2sh": (2.0, 2.0),
}
EIGHT = ("p05s", "p09s", "c02h", "c04h", "c06h", "c08h", "f15h", "f2sh")

BLOCKS = {
    "B0": {"loads": (50, 75, 88)},
    "C0": {"loads": (75,)},
    "P0": {"slices": (1.5, 3.0), "points": ("p09s", "c04h", "c08h", "f15h"), "loads": (75,)},
    "A1": {"slices": (0.75, 1.5, 2.25, 3.0, 4.5, 6.0), "points": EIGHT, "loads": (75,),
           "trace_half": True},
    "A2": {"slices": (1.5, 3.0), "points": EIGHT, "loads": (75,)},
    # D4-4: A3 runs at three loads, at the 3 ms slice and 6 trips, in two campaigns, one per
    # backend. Two slices would be 432 runs where the plan's table asks for 216.
    "A3": {"slices": (3.0,), "points": ("p09s", "c02h", "c04h", "c06h", "c08h", "f15h"),
           "loads": (50, 75, 88), "trace_half": True},
    "A4": {"slices": (1.5, 3.0, 4.5), "points": EIGHT, "loads": (75,)},
    "A5": {"cpus": (2, 4, 8), "points": EIGHT, "loads": (75,)},
    # D4-5: A7 tests one slice, 3 ms, both backends, in one campaign, and P4 is judged at that
    # slice. Two slices would be 120 runs where the plan asks for 72.
    "A7": {"slices": (3.0,), "points": ("p09s", "c05h", "f15h"), "loads": (75,),
           "priorities": (False, True)},
    # D4-9: Kafka only, our Python client against Kafka's official Java one, at the 3 ms slice and
    # A7's three trips, ordinary and go-first, with the got-it note taken both where it can be
    # taken. That is 24 setups, and the plan's 240 runs over two campaigns is 24 at five rounds.
    "A8": {"slices": (3.0,), "points": ("p09s", "c05h", "f15h"), "loads": (75,),
           "priorities": (False, True), "languages": ("python", "java"),
           "ack_stamps": ("callback", "inline"), "backends": ("kafka",)},
}
BACKENDS = ("kafka", "redis")
#: Blocks that plan no trip: they need neither a baseline nor a calibration, and they may take
#: the loads of the session they open.
UNPLACED = ("B0", "C0")
FIXED_ROUNDS = {"B0": 3, "C0": 2, "P0": 5}

#: Minutes one run takes end to end with the runner's default plan (warm-up, measurement,
#: settling and checks), as the first Azure pilot measured. For planning only.
RUN_MINUTES = 3.5


def trip_ms(point, slice_ms, tick_ms):
    a, b = POINT_FORM[point]
    return a * slice_ms + b * tick_ms


def c0_steps(up_to_ms):
    """C0's delays other than zero: 1 ms, doubling until up_to_ms is covered."""
    steps = [1.0]
    while steps[-1] < up_to_ms:
        steps.append(steps[-1] * 2)
    return steps


def _slices(block, spec, settings):
    """(slice_ms, hand_set, cpus, predicted_ns) for each slice condition of a block.

    A5 predicts the kernel's own slice at each CPU count. It uses the per-step constant the
    machine reported (sched_settings' normalised_slice_ns) rather than the one its version
    implies, because the first Azure driver ran a 6.8 kernel carrying the 6.15 constant.
    """
    if "cpus" not in spec:
        return [(s, True, None, int(round(s * 1e6))) for s in spec["slices"]]
    normalised = settings.get("normalised_slice_ns")
    scaling = settings.get("tunable_scaling") or "log"
    out = []
    for cpus in spec["cpus"]:
        if normalised:
            predicted = int(normalised) * kernel_constants.sysctl_factor(cpus, scaling)
        else:
            predicted = sched_settings.rule_slice_ns(settings.get("release"), cpus, scaling)
        if predicted is None:
            raise ValueError("block %s predicts the default slice from the machine's own "
                             "constant or its kernel release, and the settings carry neither"
                             % block)
        out.append((predicted / 1e6, False, cpus, predicted))
    return out


def _base(baseline, backend, load):
    try:
        return baseline[backend][str(load)]
    except KeyError:
        raise ValueError("the baseline has no %s trip at %d%% load; B0 must cover it"
                         % (backend, load))


def _placer(baseline, calibration, backend, load):
    """(zero-delay trip, the delay for a target trip, how it was placed) at one backend and load.

    The calibration, when there is one, is the session's own measurement of what a millisecond
    of delay does to the trip. Without it the baseline is used and one-for-one is assumed.
    """
    if calibration is None:
        base = _base(baseline, backend, load)
        return base, (lambda target: round(target - base, 3) if target >= base else None), \
            "baseline"
    try:
        entry = calibration[backend][str(load)]
    except KeyError:
        raise ValueError("the calibration has no %s entry at %d%% load; C0 must cover it"
                         % (backend, load))
    if not entry["gate"]["ok"]:
        raise ValueError("the %s calibration at %d%% load failed its gate, so it cannot place "
                         "trips" % (backend, load))
    return (delay_calibration.predict(entry, 0.0),
            lambda target: delay_calibration.delay_for(entry, target), "calibration")


def _unplaced(block, backend, load, tick_ms, up_to_ms, cpus=None):
    """B0's single no-delay setup, or C0's delay staircase, for one backend at one load.

    `cpus` switches the machine down to that many CPUs for these runs. A5 gives each core count
    its own session with its own calibration, because the delay's effect on the trip is measured
    on the machine as the campaign will run it, and a machine with six of its CPUs switched off
    is not the machine the 8-CPU calibration was taken on.
    """
    common = {"block": block, "backend": backend, "load_pct": load, "slice_ns": None,
              "predicted_slice_ns": None, "cpus": cpus, "tick_ms": tick_ms,
              "target_trip_ms": None, "baseline_trip_ms": None, "priority": False,
              "trace_half": False}
    if block == "B0":
        steps = [("base", 0.0)]
    else:
        steps = [("d0a", 0.0), ("d0b", 0.0)] + [("d%d" % round(s * 1000), s)
                                               for s in c0_steps(up_to_ms)]
    at = "-c%d" % cpus if cpus else ""
    return [dict(common, id="%s-%s-l%d%s-%s" % (block, backend, load, at, label), point=label,
                 delay_ms=delay) for label, delay in steps]


def _wanted(block, spec, slices, backends, cores=None):
    """The slices, backends and core counts of one campaign, checked against what the block fixes.

    A campaign is a sitting, not a block: the plan runs A1 as six of them, three per backend, each
    including the anchor slice, and A5 as one session per core count. Asking for a condition the
    block does not have would be a new one, which the plan fixes and this script may not invent.
    """
    if cores:
        if "cpus" not in spec:
            raise ValueError("block %s runs slices, not core counts of its own" % block)
        unknown = [c for c in cores if c not in spec["cpus"]]
        if unknown:
            raise ValueError("block %s has no core count %s; its core counts are %s"
                             % (block, ", ".join(str(c) for c in unknown),
                                ", ".join(str(c) for c in spec["cpus"])))
    if slices:
        if "slices" not in spec:
            raise ValueError("block %s runs core counts, not slices of its own" % block)
        unknown = [s for s in slices if s not in spec["slices"]]
        if unknown:
            raise ValueError("block %s has no slice %s; its slices are %s"
                             % (block, ", ".join("%g" % s for s in unknown),
                                ", ".join("%g" % s for s in spec["slices"])))
    # A block may fix its own backends: A8 is Kafka only, because the Java client it compares ours
    # with is Kafka's. Where it does, that is both the default and the limit.
    allowed = tuple(spec.get("backends") or BACKENDS)
    if backends:
        unknown = [b for b in backends if b not in allowed]
        if unknown:
            raise ValueError("block %s does not run %s; it runs %s"
                             % (block, ", ".join(unknown), " and ".join(allowed)))
    return (tuple(slices) if slices else None, tuple(backends) if backends else allowed,
            tuple(cores) if cores else None)


def make_setups(block, tick_ms, baseline=None, settings=None, calibration=None, loads=None,
                up_to_ms=8.0, slices=None, backends=None, cpus=None, cores=None):
    """(setups, unreachable) for one campaign of a block. `settings` is sched_settings' read of
    the machine, and `calibration` is delay_calibration.py's fit, which places the trips when it
    is given. `slices` and `backends` take one campaign's share of the block, and `cpus` runs a
    session's instrument campaign at the core count the campaign after it will run at."""
    settings = settings or {}
    spec = BLOCKS[block]
    if loads and block not in UNPLACED:
        raise ValueError("block %s fixes its own loads; only %s take other loads"
                         % (block, " and ".join(UNPLACED)))
    if cpus and block not in UNPLACED:
        raise ValueError("block %s takes its core counts from its own design; only %s are run "
                         "at a core count given to them" % (block, " and ".join(UNPLACED)))
    slices, backends, cores = _wanted(block, spec, slices, backends, cores)
    if slices:
        spec = dict(spec, slices=slices)
    if cores:
        spec = dict(spec, cpus=cores)
    setups, unreachable = [], []
    for backend in backends:
        for load in loads or spec["loads"]:
            if block in UNPLACED:
                setups += _unplaced(block, backend, load, tick_ms, up_to_ms, cpus)
                continue
            base, delay_for, placed_by = _placer(baseline, calibration, backend, load)
            for slice_ms, hand_set, cpus, predicted in _slices(block, spec, settings):
                label = "c%d" % cpus if cpus else "s%d" % round(slice_ms * 1000)
                for point in spec["points"]:
                    target = trip_ms(point, slice_ms, tick_ms)
                    delay = delay_for(target)
                    for priority in spec.get("priorities", (False,)):
                      for language in spec.get("languages", (None,)):
                        for ack_stamp in spec.get("ack_stamps", (None,)):
                            # A8 varies the client and where the got-it note is taken; every other
                            # block leaves both unset and the id is the one it always was.
                            marks = "".join(part for part in (
                                "-rt" if priority else "",
                                "-%s" % language if language else "",
                                "-%s" % ack_stamp if ack_stamp else "") if part)
                            setup = {
                                "id": "%s-%s-l%d-%s-%s%s" % (block, backend, load, label, point,
                                                             marks),
                                "block": block, "backend": backend, "load_pct": load,
                                "slice_ns": predicted if hand_set else None,
                                "predicted_slice_ns": predicted, "cpus": cpus, "tick_ms": tick_ms,
                                "point": point, "target_trip_ms": round(target, 4),
                                "baseline_trip_ms": round(base, 4), "delay_ms": delay,
                                "placed_by": placed_by, "priority": priority,
                                "language": language, "ack_stamp": ack_stamp,
                                "trace_half": bool(spec.get("trace_half")),
                            }
                            (setups if delay is not None else unreachable).append(setup)
    return setups, unreachable


#: A slice tests the cliff only where these are reachable: the level the halfway point is
#: measured from, the level past the cliff, and at least this many of the four trips across it
#: (the plan's D8-1).
PLATEAU_POINT = "p09s"
FLOOR_POINT = "f2sh"
CLIFF_POINTS = ("c02h", "c04h", "c06h", "c08h")
CLIFF_POINTS_NEEDED = 3


def testable(block, settings, baseline=None, calibration=None, backends=BACKENDS, up_to_ms=8.0):
    """{backend: {slice: whether this pair can test the cliff at it}}.

    A slice a pair cannot reach is not a weaker test of the prediction; it is not a test of it,
    and the campaign is not run. What puts a slice out of reach is the client's own zero-delay
    trip, below which no message can arrive, or a trip beyond the calibration's longest step.
    """
    found = {}
    for backend in backends:
        setups, unreachable = make_setups(block, settings.get("tick_ms"), baseline, settings,
                                          calibration, None, up_to_ms, None, [backend])
        points = {}
        for setup in setups:
            #: A5 does not set a slice by hand: its condition is the cores switched on, and the
            #: slice is the one the kernel's own rule predicts for that count.
            ns = setup["slice_ns"] or setup["predicted_slice_ns"]
            if ns:
                points.setdefault(ns / 1e6, set()).add(setup["point"])
        for entry in unreachable:
            #: A point the placement cannot reach still names its slice, and the slice has to
            #: appear here or a slice with nothing reachable at all would go unmentioned.
            name = entry["id"]
            if "-s" in name:
                points.setdefault(float(name.split("-s")[1].split("-")[0]) / 1000.0, set())
        found[backend] = dict(
            (slice_ms, PLATEAU_POINT in seen and FLOOR_POINT in seen
             and len(seen & set(CLIFF_POINTS)) >= CLIFF_POINTS_NEEDED)
            for slice_ms, seen in points.items())
    return found


def design(block, settings, baseline, rounds, seed, calibration=None, loads=None, up_to_ms=8.0,
           first_round=1, slices=None, backends=None, anchor=None, cpus=None, cores=None):
    """The run_queue design for one campaign of a block, with what it was made from."""
    if block not in BLOCKS:
        raise ValueError("no block %r; the blocks are %s" % (block, ", ".join(sorted(BLOCKS))))
    if first_round != 1 and block != "C0":
        raise ValueError("only C0 runs in two stages; block %s starts at round 1" % block)
    tick = settings.get("tick_ms")
    if not tick:
        raise ValueError("the settings carry no tick; read them on the machine that will run "
                         "the block with sched_settings.py read")
    if block not in UNPLACED and not baseline and not calibration:
        raise ValueError("block %s places its trips from the session's calibration (C0) or "
                         "from the baseline trips B0 measured" % block)
    # B0 and P0 run their plan's rounds whatever is asked. C0 runs 2 unless asked for more: the
    # first session's staircase (S0-1) runs 4.
    if block == "C0":
        rounds = rounds or FIXED_ROUNDS[block]
    else:
        rounds = FIXED_ROUNDS.get(block, rounds)
    if not rounds:
        raise ValueError("block %s needs --rounds, from law_design.py rounds" % block)
    if anchor is not None and slices and anchor not in slices:
        raise ValueError("the anchor slice %g is not among this campaign's slices %s; every "
                         "campaign of a block shares the anchor" % (anchor, ", ".join(
                             "%g" % s for s in slices)))
    setups, unreachable = make_setups(block, tick, baseline, settings, calibration, loads,
                                      up_to_ms, slices, backends, cpus, cores)
    return {"block": block, "seed": seed, "rounds": rounds, "first_round": first_round,
            "tick_ms": tick, "slices": list(slices) if slices else None,
            "backends": list(backends) if backends else list(BACKENDS),
            "anchor_slice": anchor,
            "release": settings.get("release"),
            "normalised_slice_ns": settings.get("normalised_slice_ns"), "baseline": baseline,
            "calibration": calibration, "setups": setups,
            "unreachable": [u["id"] for u in unreachable]}


def baseline_from_rows(rows, warmup_s=30.0, summarise=pilot_checks.summarise):
    """{backend: {load: median of per-run median trips}} from a finished B0 queue."""
    groups = {}
    for row in rows:
        if row["status"] != "done" or not row["run_dir"]:
            continue
        params = json.loads(row["params"])
        trip = summarise(row["run_dir"], warmup_s)["trip_median_ms"]
        groups.setdefault(params["backend"], {}).setdefault(
            str(params["load_pct"]), []).append(trip)
    if not groups:
        raise ValueError("the queue has no finished baseline runs")
    return {backend: {load: statistics.median(trips) for load, trips in sorted(loads.items())}
            for backend, loads in sorted(groups.items())}


def _spread_logs(rows, warmup_s, summarise):
    """{setup: [log rate per run]} over a finished spread pilot's queue.

    The rate is (negatives + 0.5) / (spans + 1), so a run with no negative span still has a
    logarithm, and the shrinkage it adds is the same for every run.
    """
    logs = {}
    for row in rows:
        if row["status"] != "done" or not row["run_dir"]:
            continue
        summary = summarise(row["run_dir"], warmup_s)
        if not summary.get("measured_spans"):
            continue
        logs.setdefault(row["setup"], []).append(
            math.log((summary["measured_negative"] + 0.5) / (summary["measured_spans"] + 1)))
    return logs


def spread_from_rows(rows, warmup_s=30.0, summarise=pilot_checks.summarise):
    """(median SD, {setup: SD}) of log negative rate across the repeat runs of each setup."""
    logs = _spread_logs(rows, warmup_s, summarise)
    sds = {setup: statistics.stdev(values) for setup, values in logs.items() if len(values) >= 2}
    if not sds:
        raise ValueError("no setup has two finished runs, so the spread cannot be estimated")
    return statistics.median(sds.values()), sds


def spread_by_backend(rows, warmup_s=30.0, summarise=pilot_checks.summarise):
    """{backend: median SD of the log rate} over the setups that backend ran.

    A campaign runs one backend and a prediction is judged on one backend, so the spread a
    campaign is simulated at is the spread of the backend that campaign runs. Pooling the two
    describes neither: on the second x86 pair the spread pilot measured 0.213 for Kafka and 0.701
    for Redis, and their pooled median, 0.457, is too many rounds for one and too few for the
    other -- and the simulation would report a power the noisier campaign does not have (D10-1).

    A setup's backend is read from the setup's own name, which begins with the block and the
    backend, as law_design writes it.
    """
    logs = _spread_logs(rows, warmup_s, summarise)
    by = {}
    for setup, values in logs.items():
        if len(values) < 2:
            continue
        parts = str(setup).split("-")
        if len(parts) < 2 or parts[1] not in BACKENDS:
            continue
        by.setdefault(parts[1], []).append(statistics.stdev(values))
    if not by:
        raise ValueError("no backend has a setup with two finished runs, so no spread can be "
                         "estimated for it")
    return dict((backend, statistics.median(sds)) for backend, sds in sorted(by.items()))


def main(argv=None, out=None, summarise=pilot_checks.summarise):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Run lists for the plateau-cliff-floor experiments")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("design")
    p.add_argument("--block", required=True, choices=sorted(BLOCKS))
    p.add_argument("--settings", required=True, help="JSON from sched_settings.py read or check")
    p.add_argument("--baseline", default="")
    p.add_argument("--calibration", default="", help="JSON from delay_calibration.py fit")
    p.add_argument("--loads", default="", help="comma-separated loads, for B0 or C0 only")
    p.add_argument("--up-to-ms", type=float, default=8.0, help="C0's longest delay step")
    p.add_argument("--rounds", type=int, default=0)
    p.add_argument("--slices", default="",
                   help="this campaign's share of the block's slices, for example 3,0.75,1.5")
    p.add_argument("--backend", action="append", default=[],
                   help="run one backend in this campaign; may be given twice")
    p.add_argument("--anchor-slice", type=float, default=None,
                   help="the slice every campaign of the block shares, for example 3")
    p.add_argument("--cores", default="",
                   help="this campaign's share of the block's core counts, for example 2; A5 "
                        "runs one session per core count")
    p.add_argument("--cpus", type=int, default=None,
                   help="run B0 or C0 at this many CPUs, for a session that opens a campaign at "
                        "a reduced core count (A5)")
    p.add_argument("--first-round", type=int, default=1,
                   help="C0's second stage carries on from the first stage's rounds")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("baseline")
    p.add_argument("--queue", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--warmup-s", type=float, default=30.0)
    p = sub.add_parser("testable", help="which slices this pair can test, and which it cannot")
    p.add_argument("--block", required=True)
    p.add_argument("--settings", required=True)
    p.add_argument("--calibration", default="")
    p.add_argument("--baseline", default="")
    p.add_argument("--up-to-ms", type=float, default=8.0)
    p = sub.add_parser("rounds")
    p.add_argument("--queue", required=True)
    p.add_argument("--block", required=True, choices=sorted(BLOCKS))
    p.add_argument("--warmup-s", type=float, default=30.0)
    args = ap.parse_args(argv)
    try:
        if args.command == "baseline":
            result = baseline_from_rows(run_queue.read_queue(args.queue), args.warmup_s,
                                        summarise)
            text = json.dumps(result, indent=2, sort_keys=True)
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(text, file=out)
            return 0
        if args.command == "testable":
            with open(args.settings, encoding="utf-8") as fh:
                settings = json.load(fh)
            settings = settings.get("settings", settings)
            calibration = baseline = None
            if args.calibration:
                with open(args.calibration, encoding="utf-8") as fh:
                    calibration = json.load(fh)
                calibration = calibration.get("calibration", calibration)
            if args.baseline:
                with open(args.baseline, encoding="utf-8") as fh:
                    baseline = json.load(fh)
            found = testable(args.block, settings, baseline, calibration, up_to_ms=args.up_to_ms)
            for backend in sorted(found):
                can = sorted(s for s, ok in found[backend].items() if ok)
                cannot = sorted(s for s, ok in found[backend].items() if not ok)
                print("%s %s%s" % (backend, ",".join("%g" % s for s in can) or "none",
                                   "" if not cannot else "  (out of reach: %s)"
                                   % ", ".join("%g" % s for s in cannot)), file=out)
            return 0
        if args.command == "rounds":
            sigma, sds = spread_from_rows(run_queue.read_queue(args.queue), args.warmup_s,
                                          summarise)
            #: The number itself comes from simulating this campaign's own prediction and
            #: decision rule at this spread, which is the plan's D4-2 and is what rounds_rule.py
            #: does. What belongs here is the spread that simulation is run at.
            print(json.dumps({"block": args.block, "sigma_median": sigma,
                              "setups_measured": len(sds),
                              "rounds_from": "python scripts/rounds_rule.py for --prediction "
                                             "<the campaign's> --spread %.4f" % sigma},
                             sort_keys=True), file=out)
            return 0
        with open(args.settings, encoding="utf-8") as fh:
            settings = json.load(fh)
        baseline = calibration = None
        if args.baseline:
            with open(args.baseline, encoding="utf-8") as fh:
                baseline = json.load(fh)
        if args.calibration:
            with open(args.calibration, encoding="utf-8") as fh:
                calibration = json.load(fh)["calibration"]
        loads = [int(v) for v in args.loads.split(",")] if args.loads else None
        made = design(args.block, settings.get("settings", settings), baseline, args.rounds,
                      args.seed, calibration, loads, args.up_to_ms, args.first_round,
                      [float(s) for s in args.slices.split(",")] if args.slices else None,
                      args.backend or None, args.anchor_slice, args.cpus,
                      [int(c) for c in args.cores.split(",")] if args.cores else None)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(made, indent=2, sort_keys=True) + "\n")
        runs = len(made["setups"]) * made["rounds"]
        print("%s: %d setups x %d rounds = %d runs, about %.0f hours; %d unreachable point(s)%s"
              % (args.block, len(made["setups"]), made["rounds"], runs,
                 runs * RUN_MINUTES / 60, len(made["unreachable"]),
                 (": " + ", ".join(made["unreachable"])) if made["unreachable"] else ""),
              file=out)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
