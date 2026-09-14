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
  delays       a run's trip is the machine's own baseline trip plus the receiver-only delay, so
               a point's delay is its target minus the baseline measured for that backend at
               that load. A point below the baseline cannot be reached by adding delay. It is
               listed as unreachable in the design, not quietly dropped.
  repeats      the rounds that give 80% power to see a two-fold difference at the run-to-run
               spread the spread pilot measured: never fewer than 15 for A1 to A4 or 10 for the
               rest, never more than 40.

Blocks, each a design for scripts/run_queue.py:
  B0  baseline trips: no delay, the kernel's own slice, each backend at 50, 75 and 88% load
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
    python3 scripts/law_design.py rounds --queue p0.csv --block A1
    python3 scripts/law_design.py design --block A1 --settings settings.json \\
        --baseline baseline.json --rounds 26 --seed 20260915 --out a1.json
"""
import argparse
import json
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
FIXED_ROUNDS = {"B0": 3, "P0": 5}
MIN_ROUNDS = {"A1": 15, "A2": 15, "A3": 15, "A4": 15}
DEFAULT_MIN_ROUNDS = 10
MAX_ROUNDS = 40
ALPHA, POWER, FOLD = 0.05, 0.80, 2.0

#: Minutes one run takes end to end with the runner's default plan (warm-up, measurement,
#: settling and checks). For planning only.
RUN_MINUTES = 3.5


def trip_ms(point, slice_ms, tick_ms):
    a, b = POINT_FORM[point]
    return a * slice_ms + b * tick_ms


def rounds_for(sigma, block):
    """Rounds per setup for 80% power to see a FOLD-fold difference at log-rate spread sigma."""
    z = statistics.NormalDist().inv_cdf
    need = 2 * (z(1 - ALPHA / 2) + z(POWER)) ** 2 * sigma ** 2 / math.log(FOLD) ** 2
    return max(MIN_ROUNDS.get(block, DEFAULT_MIN_ROUNDS), min(MAX_ROUNDS, math.ceil(need)))


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


def make_setups(block, tick_ms, baseline=None, settings=None):
    """(setups, unreachable) for one block. `settings` is sched_settings' read of the machine."""
    settings = settings or {}
    spec = BLOCKS[block]
    setups, unreachable = [], []
    for backend in BACKENDS:
        for load in spec["loads"]:
            if block == "B0":
                setups.append({"id": "B0-%s-l%d-base" % (backend, load), "block": block,
                               "backend": backend, "load_pct": load, "slice_ns": None,
                               "predicted_slice_ns": None, "cpus": None, "tick_ms": tick_ms,
                               "point": "base", "target_trip_ms": None,
                               "baseline_trip_ms": None, "delay_ms": 0.0, "priority": False,
                               "trace_half": False})
                continue
            base = _base(baseline, backend, load)
            for slice_ms, hand_set, cpus, predicted in _slices(block, spec, settings):
                label = "c%d" % cpus if cpus else "s%d" % round(slice_ms * 1000)
                for point in spec["points"]:
                    target = trip_ms(point, slice_ms, tick_ms)
                    for priority in spec.get("priorities", (False,)):
                        setup = {
                            "id": "%s-%s-l%d-%s-%s%s" % (block, backend, load, label, point,
                                                        "-rt" if priority else ""),
                            "block": block, "backend": backend, "load_pct": load,
                            "slice_ns": predicted if hand_set else None,
                            "predicted_slice_ns": predicted, "cpus": cpus, "tick_ms": tick_ms,
                            "point": point, "target_trip_ms": round(target, 4),
                            "baseline_trip_ms": round(base, 4),
                            "delay_ms": round(target - base, 3), "priority": priority,
                            "trace_half": bool(spec.get("trace_half")),
                        }
                        (setups if setup["delay_ms"] >= 0 else unreachable).append(setup)
    return setups, unreachable


def design(block, settings, baseline, rounds, seed):
    """The run_queue design for one block, with what it was made from."""
    if block not in BLOCKS:
        raise ValueError("no block %r; the blocks are %s" % (block, ", ".join(sorted(BLOCKS))))
    tick = settings.get("tick_ms")
    if not tick:
        raise ValueError("the settings carry no tick; read them on the machine that will run "
                         "the block with sched_settings.py read")
    if block != "B0" and not baseline:
        raise ValueError("block %s places its trips from the baseline trips B0 measured"
                         % block)
    rounds = FIXED_ROUNDS.get(block, rounds)
    if not rounds:
        raise ValueError("block %s needs --rounds, from law_design.py rounds" % block)
    setups, unreachable = make_setups(block, tick, baseline, settings)
    return {"block": block, "seed": seed, "rounds": rounds, "tick_ms": tick,
            "release": settings.get("release"),
            "normalised_slice_ns": settings.get("normalised_slice_ns"), "baseline": baseline,
            "setups": setups, "unreachable": [u["id"] for u in unreachable]}


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
    p.add_argument("--rounds", type=int, default=0)
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
            print(json.dumps({"block": args.block, "sigma_median": sigma,
                              "rounds": rounds_for(sigma, args.block),
                              "setups_measured": len(sds)}, sort_keys=True), file=out)
            return 0
        with open(args.settings, encoding="utf-8") as fh:
            settings = json.load(fh)
        baseline = None
        if args.baseline:
            with open(args.baseline, encoding="utf-8") as fh:
                baseline = json.load(fh)
        made = design(args.block, settings.get("settings", settings), baseline, args.rounds,
                      args.seed)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(made, indent=2, sort_keys=True) + "\n")
        runs = len(made["setups"]) * made["rounds"]
        print("%s: %d setups x %d rounds = %d runs, about %.0f hours; %d unreachable point(s)%s"
              % (args.block, len(made["setups"]), made["rounds"], runs,
                 runs * RUN_MINUTES / 60, len(made["unreachable"]),
                 (": " + ", ".join(made["unreachable"])) if made["unreachable"] else ""),
              file=out)
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
