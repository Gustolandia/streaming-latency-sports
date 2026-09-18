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
    "A3": {"slices": (1.5, 3.0), "points": ("p09s", "c02h", "c04h", "c06h", "c08h", "f15h"),
           "loads": (50, 75, 88), "trace_half": True},
    "A4": {"slices": (1.5, 3.0, 4.5), "points": EIGHT, "loads": (75,)},
    "A5": {"cpus": (2, 4, 8), "points": EIGHT, "loads": (75,)},
    "A7": {"slices": (1.5, 3.0), "points": ("p09s", "c05h", "f15h"), "loads": (75,),
           "priorities": (False, True)},
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


def _unplaced(block, backend, load, tick_ms, up_to_ms):
    """B0's single no-delay setup, or C0's delay staircase, for one backend at one load."""
    common = {"block": block, "backend": backend, "load_pct": load, "slice_ns": None,
              "predicted_slice_ns": None, "cpus": None, "tick_ms": tick_ms,
              "target_trip_ms": None, "baseline_trip_ms": None, "priority": False,
              "trace_half": False}
    if block == "B0":
        steps = [("base", 0.0)]
    else:
        steps = [("d0a", 0.0), ("d0b", 0.0)] + [("d%d" % round(s * 1000), s)
                                               for s in c0_steps(up_to_ms)]
    return [dict(common, id="%s-%s-l%d-%s" % (block, backend, load, label), point=label,
                 delay_ms=delay) for label, delay in steps]


def make_setups(block, tick_ms, baseline=None, settings=None, calibration=None, loads=None,
                up_to_ms=8.0):
    """(setups, unreachable) for one block. `settings` is sched_settings' read of the machine,
    and `calibration` is delay_calibration.py's fit, which places the trips when it is given."""
    settings = settings or {}
    spec = BLOCKS[block]
    if loads and block not in UNPLACED:
        raise ValueError("block %s fixes its own loads; only %s take other loads"
                         % (block, " and ".join(UNPLACED)))
    setups, unreachable = [], []
    for backend in BACKENDS:
        for load in loads or spec["loads"]:
            if block in UNPLACED:
                setups += _unplaced(block, backend, load, tick_ms, up_to_ms)
                continue
            base, delay_for, placed_by = _placer(baseline, calibration, backend, load)
            for slice_ms, hand_set, cpus, predicted in _slices(block, spec, settings):
                label = "c%d" % cpus if cpus else "s%d" % round(slice_ms * 1000)
                for point in spec["points"]:
                    target = trip_ms(point, slice_ms, tick_ms)
                    delay = delay_for(target)
                    for priority in spec.get("priorities", (False,)):
                        setup = {
                            "id": "%s-%s-l%d-%s-%s%s" % (block, backend, load, label, point,
                                                        "-rt" if priority else ""),
                            "block": block, "backend": backend, "load_pct": load,
                            "slice_ns": predicted if hand_set else None,
                            "predicted_slice_ns": predicted, "cpus": cpus, "tick_ms": tick_ms,
                            "point": point, "target_trip_ms": round(target, 4),
                            "baseline_trip_ms": round(base, 4), "delay_ms": delay,
                            "placed_by": placed_by, "priority": priority,
                            "trace_half": bool(spec.get("trace_half")),
                        }
                        (setups if delay is not None else unreachable).append(setup)
    return setups, unreachable


def design(block, settings, baseline, rounds, seed, calibration=None, loads=None, up_to_ms=8.0,
           first_round=1):
    """The run_queue design for one block, with what it was made from."""
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
    setups, unreachable = make_setups(block, tick, baseline, settings, calibration, loads,
                                      up_to_ms)
    return {"block": block, "seed": seed, "rounds": rounds, "first_round": first_round,
            "tick_ms": tick,
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


def spread_from_rows(rows, warmup_s=30.0, summarise=pilot_checks.summarise):
    """(median SD, {setup: SD}) of log negative rate across the repeat runs of each setup.

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
    sds = {setup: statistics.stdev(values) for setup, values in logs.items() if len(values) >= 2}
    if not sds:
        raise ValueError("no setup has two finished runs, so the spread cannot be estimated")
    return statistics.median(sds.values()), sds


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
    p.add_argument("--first-round", type=int, default=1,
                   help="C0's second stage carries on from the first stage's rounds")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("baseline")
    p.add_argument("--queue", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--warmup-s", type=float, default=30.0)
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
                      args.seed, calibration, loads, args.up_to_ms, args.first_round)
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
