#!/usr/bin/env python3
"""
rounds_rule.py -- how many rounds a campaign runs, from its own test.

The plan fixes the rule, not the number: before a campaign's main runs, and after its pair's
spread pilot, the campaign is simulated a thousand times under the law and a thousand times in
the world its own falsifier names. Each simulated campaign goes through the real analysis and the
same "counts as confirmed if" rule as the real data. The rounds are the smallest number, at least
four, for which the rule confirms the prediction in at least 80% of the simulations under the law
and in at most 5% of those where the prediction is false. The ceiling is 40: a campaign that
cannot reach that power at 40 runs 40, and its prediction is reported as underpowered, as its log
says before it runs.

Nothing here decides anything about real data. It reads a design and a spread, and answers with a
number of rounds and the counts behind it -- which are written into the campaign's log before the
campaign runs, so a reader can see what power was expected of it.

Where no prediction is tested the numbers are fixed instead, and this module reports them without
simulating: C0 runs 2 rounds per session and 4 in the first pair's staircase, B0 runs 3, P0 runs
5, M0 runs 10, and tool campaigns run 4.

What the simulation costs is recorded with its answer: how many trials, how many resamplings
inside each, and how finely the shapes were fitted. They are settings of this program, not of the
plan, and a reader can repeat it with the seed that is also recorded.

CLI:
    python scripts/rounds_rule.py for --prediction P1 --slices 1.5,3,4.5,6,7.5,9 --spread 0.18
    python scripts/rounds_rule.py fixed --campaign B0
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import law_predictions  # noqa: E402
import law_world  # noqa: E402

#: The floor, the ceiling, and what the rule asks of the simulations.
FLOOR = 4
CEILING = 40
POWER = 0.80
FALSE_CONFIRM = 0.05
#: How many campaigns are simulated, how many resamplings each one's intervals come from, how
#: finely the fitted shape is searched, and the seed the whole thing starts from. The plan fixes
#: the thousand; the rest are this program's own, recorded with every answer.
TRIALS = 1000
DRAWS = 200
GRID = 48
#: How finely the fitted shape moves the fall's start while simulating. The analysis itself reads
#: it to a twentieth of a millisecond; a simulation asks the same rule two thousand times and the
#: band it decides on is a millisecond wide, so a fifth of a millisecond is finer than the question
#: and twelve times cheaper.
STEP_MS = 0.2
SEED = 20260918
#: The world in which each prediction is false, as its falsifier states it.
FALSIFIERS = {"P1": "cliff_fixed", "P9": "cliff_fixed", "P2": "width_fixed",
              "P2c": "width_fixed", "P2d": "cliff_fixed", "P3": "cliff_moves_with_load",
              "P4": "no_priority_effect", "P7": "cliff_fixed_by_cores",
              "P8": "python_twice_java"}
#: Where no prediction is tested, the plan fixes the number of rounds instead.
FIXED = {"C0": 2, "S0-1": 4, "B0": 3, "P0": 5, "M0": 10, "tools": 4}


def confirms(prediction, design, rounds, world, trials=TRIALS, draws=DRAWS, grid=GRID,
             seed=SEED, tick_ms=1.0, step_ms=STEP_MS):
    """How often the rule confirms the prediction, over `trials` made-up campaigns of that world.

    Each campaign is made up afresh from its own seed, so the count can be repeated exactly.
    """
    said = 0
    for trial in range(trials):
        runs = law_world.campaign(rounds=rounds, world=world, seed=seed + trial,
                                  tick_ms=tick_ms, **design)
        found = law_predictions.judge(runs, prediction, tick_ms, draws=draws,
                                      seed=seed + trial, grid=grid, step_ms=step_ms)
        said += 1 if found["confirmed"] else 0
    return said / float(trials)


def rounds_for(prediction, design, trials=TRIALS, draws=DRAWS, grid=GRID, seed=SEED,
               tick_ms=1.0, floor=FLOOR, ceiling=CEILING, steps=None, step_ms=STEP_MS):
    """The smallest number of rounds that reaches the power the rule asks for.

    The rounds tried climb from the floor to the ceiling; `steps` names them, and defaults to the
    floor, then 6, 8, 12, 16, 24, 32 and the ceiling, so a campaign with plenty of power is
    answered in one or two simulations rather than thirty-seven.
    """
    if prediction not in FALSIFIERS:
        raise ValueError("no falsifier named for %s; the ones the plan names are %s"
                         % (prediction, ", ".join(sorted(FALSIFIERS))))
    steps = [n for n in (steps or (floor, 6, 8, 12, 16, 24, 32, ceiling))
             if floor <= n <= ceiling]
    tried = []
    for rounds in steps:
        power = confirms(prediction, design, rounds, "law", trials, draws, grid, seed, tick_ms,
                         step_ms)
        wrongly = confirms(prediction, design, rounds, FALSIFIERS[prediction], trials, draws,
                           grid, seed + 500000, tick_ms, step_ms)
        tried.append({"rounds": rounds, "power": power, "false_confirm": wrongly})
        if power >= POWER and wrongly <= FALSE_CONFIRM:
            return _answer(prediction, rounds, tried, False, trials, draws, grid, seed, step_ms,
                           design)
    return _answer(prediction, ceiling, tried, True, trials, draws, grid, seed, step_ms, design)


def _answer(prediction, rounds, tried, underpowered, trials, draws, grid, seed, step_ms=STEP_MS,
            design=None):
    """The answer, with the world it was reached in.

    The rounds a campaign runs are written into that campaign's own log before it runs, saying
    they came from the spread this pair measured. The design is recorded here so that claim can
    be checked afterwards against the numbers the simulation actually used.
    """
    return {"prediction": prediction, "rounds": rounds, "underpowered": underpowered,
            "tried": tried, "asked_of_it": {"power": POWER, "false_confirm": FALSE_CONFIRM},
            "design": dict(design or {}),
            "settings": {"trials": trials, "draws": draws, "grid": grid, "seed": seed,
                         "step_ms": step_ms}}


def fixed_rounds(campaign):
    """The rounds the plan fixes where no prediction is tested."""
    if campaign not in FIXED:
        raise ValueError("%s is not a campaign with a fixed number of rounds; the fixed ones are "
                         "%s" % (campaign, ", ".join(sorted(FIXED))))
    return {"campaign": campaign, "rounds": FIXED[campaign], "underpowered": False,
            "why": "no prediction is tested, so the plan fixes the number"}


def lines(found):
    """The answer as it is written into a campaign's log before it runs."""
    if "campaign" in found:
        return ["%s runs %d rounds: %s" % (found["campaign"], found["rounds"], found["why"])]
    out = ["%s: %d rounds%s" % (found["prediction"], found["rounds"],
                                ", and the prediction is reported as underpowered"
                                if found["underpowered"] else "")]
    for step in found["tried"]:
        out.append("  %2d rounds: confirmed in %.0f%% under the law, in %.0f%% where it is false"
                   % (step["rounds"], 100 * step["power"], 100 * step["false_confirm"]))
    out.append("  asked of it: at least %.0f%% power, at most %.0f%% false; from %d simulations "
               "of %d resamplings, the start read every %.2f ms, seed %d"
               % (100 * POWER, 100 * FALSE_CONFIRM, found["settings"]["trials"],
                  found["settings"]["draws"], found["settings"].get("step_ms", STEP_MS),
                  found["settings"]["seed"]))
    spread = (found.get("design") or {}).get("spread")
    if spread is not None:
        out.append("  in a world where a run varies by %.3f on the log of the rate" % spread)
    return out


def design_from(args):
    """The campaign to simulate, as the command line describes it."""
    design = {"slices": tuple(float(s) for s in args.slices.split(",")) if args.slices else (3.0,),
              "plateau": args.plateau, "floor": args.floor, "spread": args.spread,
              "session_shift": args.session_shift}
    if args.loads:
        design["loads"] = tuple(int(load) for load in args.loads.split(","))
    if args.cores:
        design["cores"] = tuple(int(core) for core in args.cores.split(","))
    if args.slice_by_core:
        # A5 switches CPUs off and takes the slice the kernel's rule then gives, so each core
        # count has one slice. Simulating the cross would make a campaign three times the size.
        design["slice_by_core"] = dict(
            (int(cores), float(slice_ms))
            for cores, slice_ms in (pair.split("=") for pair in args.slice_by_core.split(",")))
    if args.priorities:
        design["priorities"] = (False, True)
    if args.languages:
        design["languages"] = ("python", "java")
    if args.fixed_at is not None:
        design["fixed_at"] = args.fixed_at
    return design


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="How many rounds a campaign runs, from its own test")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("for", help="simulate a campaign and answer with its rounds")
    p.add_argument("--prediction", required=True)
    p.add_argument("--slices", default="3.0")
    p.add_argument("--tick-ms", type=float, default=1.0)
    p.add_argument("--loads", default="")
    p.add_argument("--cores", default="")
    p.add_argument("--slice-by-core", default="",
                   help="the slice each core count gives, as 2=1.4,4=2.1,8=2.8; the campaign "
                        "then walks those pairs instead of crossing slices with core counts")
    p.add_argument("--priorities", action="store_true")
    p.add_argument("--languages", action="store_true")
    p.add_argument("--plateau", type=float, default=0.30)
    p.add_argument("--floor", type=float, default=0.01)
    p.add_argument("--spread", type=float, default=law_world.SPREAD)
    p.add_argument("--fixed-at", type=float, default=None,
                   help="where the cliff sits in the world where the prediction is false")
    p.add_argument("--session-shift", action="store_true",
                   help="add the shifts between sittings the plan fixes")
    p.add_argument("--trials", type=int, default=TRIALS)
    p.add_argument("--draws", type=int, default=DRAWS)
    p.add_argument("--grid", type=int, default=GRID)
    p.add_argument("--step-ms", type=float, default=STEP_MS,
                   help="how finely the fit moves the fall's start while simulating")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--steps", default="", help="the round counts to try, in order")
    p.add_argument("--out", default="", help="write the answer here as JSON")
    p = sub.add_parser("fixed", help="the rounds the plan fixes where no prediction is tested")
    p.add_argument("--campaign", required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == "fixed":
            found = fixed_rounds(args.campaign)
        else:
            found = rounds_for(args.prediction, design_from(args), args.trials, args.draws,
                               args.grid, args.seed, args.tick_ms,
                               steps=[int(n) for n in args.steps.split(",")] if args.steps
                               else None, step_ms=args.step_ms)
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(found, indent=2, sort_keys=True) + "\n")
        for line in lines(found):
            print(line, file=out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
