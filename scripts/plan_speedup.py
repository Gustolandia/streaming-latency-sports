#!/usr/bin/env python3
"""
plan_speedup.py
Compute the --speedup value that gives a wanted replay rate for a given plan.

Why this exists. Replay plans built by make_replay_plan.py carry a baked-in 120x time
compression: `t_emit_offset_s` is already `t_sim_seconds / 120`. So `--speedup 1` does NOT mean
real time against those plans -- it means 120x. Synthetic plans from make_synthetic_plan.py
carry no compression, so for those `--speedup 1` *does* mean real time.

The same flag therefore means different things depending on which plan it is pointed at, and
getting it wrong is silent: the run completes, the numbers look plausible, and the measurement
is of a regime nobody intended. A campaign of ours was lost to exactly that.

This module reads the compression out of the plan rather than assuming it, and returns the
speedup needed for the wanted multiple of real time.

    speedup = wanted_rate / baked_in_compression

CLI:
    python scripts/plan_speedup.py PLAN.csv --rate 1      # true real time
    python scripts/plan_speedup.py PLAN.csv --rate 10     # ten times real time
"""
import argparse
import csv
import sys
from pathlib import Path


def baked_compression(plan_csv):
    """How much faster than real time the plan's emission offsets already are.

    Returns 1.0 for an uncompressed plan. Raises if the plan has no usable time span, because
    silently returning 1.0 there would reintroduce exactly the bug this module exists to stop.
    """
    sim, off = [], []
    with open(plan_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                sim.append(float(row["t_sim_seconds"]))
                off.append(float(row["t_emit_offset_s"]))
            except (KeyError, TypeError, ValueError):
                continue
    if not sim:
        raise ValueError(f"{plan_csv}: no usable rows")

    sim_span = max(sim) - min(sim)
    off_span = max(off) - min(off)
    if off_span <= 0:
        raise ValueError(f"{plan_csv}: zero emission span; cannot infer compression")
    if sim_span <= 0:
        raise ValueError(f"{plan_csv}: zero match-clock span; cannot infer compression")
    return sim_span / off_span


def speedup_for(plan_csv, wanted_rate=1.0):
    """--speedup value giving `wanted_rate` times real time for this plan.

    wanted_rate=1 is true real time; 10 is ten times faster than the real match.
    """
    if wanted_rate <= 0:
        raise ValueError("wanted_rate must be positive")
    return wanted_rate / baked_compression(plan_csv)


def expected_wall_seconds(plan_csv, max_t_sim, wanted_rate=1.0):
    """How long a trial should take, so a campaign can sanity-check its own runtime."""
    if wanted_rate <= 0:
        raise ValueError("wanted_rate must be positive")
    return min(float(max_t_sim), _sim_span(plan_csv)) / wanted_rate


def _sim_span(plan_csv):
    sim = []
    with open(plan_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                sim.append(float(row["t_sim_seconds"]))
            except (KeyError, TypeError, ValueError):
                continue
    return (max(sim) - min(sim)) if sim else 0.0


def achieved_rate(producer_csv):
    """Events per second of wall clock actually emitted by a completed run.

    Read back from the producer's own output rather than assumed from the flags, because the
    whole failure this module prevents is a run whose flags say one rate and whose behaviour is
    another. Returns (events, wall_seconds, events_per_second).
    """
    stamps = []
    with open(producer_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                stamps.append(int(row["t_prod_send_ns"]))
            except (KeyError, TypeError, ValueError):
                continue
    if len(stamps) < 2:
        raise ValueError(f"{producer_csv}: need at least two events to measure a rate")
    wall = (max(stamps) - min(stamps)) / 1e9
    if wall <= 0:
        raise ValueError(f"{producer_csv}: zero wall-clock span")
    return len(stamps), wall, len(stamps) / wall


def verify_rate(producer_csv, plan_csv, max_t_sim, wanted_rate=1.0, tolerance=0.25):
    """Check a completed run replayed at the rate it was asked to.

    Compares elapsed WALL time against the match-clock window divided by the wanted rate. A
    60-second window at real time must take about 60 seconds; at 120x it takes half a second.

    Duration is the right quantity, not event rate. Event rate varies with which part of the
    match the window covers -- football opens with a burst of line-up events, so the first
    minute is roughly twice as dense as the match average -- and comparing against the average
    flags a correct run as wrong. Duration is insensitive to that.
    """
    events, wall, actual_ev_s = achieved_rate(producer_csv)
    sim_span = _sim_span(plan_csv)
    if sim_span <= 0:
        raise ValueError(f"{plan_csv}: cannot establish the plan's match-clock span")

    window = min(float(max_t_sim), sim_span)
    expected_wall = window / wanted_rate
    if expected_wall <= 0:
        raise ValueError("expected duration is zero; check max_t_sim and rate")
    ratio = wall / expected_wall
    return {
        "events": events, "wall_s": wall, "expected_wall_s": expected_wall,
        "actual_ev_s": actual_ev_s, "ratio": ratio,
        "ok": bool(abs(ratio - 1.0) <= tolerance),
    }


def _plan_events(plan_csv):
    with open(plan_csv, newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Speedup needed for a wanted replay rate")
    ap.add_argument("plan")
    ap.add_argument("--verify", metavar="PRODUCER_CSV",
                    help="check a completed run actually replayed at --rate")
    ap.add_argument("--tolerance", type=float, default=0.25)
    ap.add_argument("--rate", type=float, default=1.0,
                    help="wanted multiple of real time (1 = real time)")
    ap.add_argument("--max-t-sim", type=float, default=None,
                    help="if given, also print the expected wall-clock duration of a trial")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the speedup value, for use in a shell substitution")
    args = ap.parse_args(argv)

    if not Path(args.plan).exists():
        print(f"missing plan: {args.plan}", file=sys.stderr)
        return 1

    try:
        baked = baked_compression(args.plan)
        speedup = speedup_for(args.plan, args.rate)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.verify:
        if not Path(args.verify).exists():
            print(f"missing producer csv: {args.verify}", file=sys.stderr)
            return 1
        if args.max_t_sim is None:
            print("--verify needs --max-t-sim (the window the run was given)", file=sys.stderr)
            return 1
        try:
            v = verify_rate(args.verify, args.plan, args.max_t_sim, args.rate, args.tolerance)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        verdict = "OK" if v["ok"] else "WRONG RATE"
        print(f"replay-rate check: {verdict}")
        print(f"  events        : {v['events']} ({v['actual_ev_s']:.3f} ev/s)")
        print(f"  wall elapsed  : {v['wall_s']:.1f}s")
        print(f"  expected wall : {v['expected_wall_s']:.1f}s "
              f"({args.max_t_sim:g}s of match clock at {args.rate:g}x)")
        print(f"  ratio         : {v['ratio']:.2f}x")
        return 0 if v["ok"] else 2

    if args.quiet:
        print(f"{speedup:.6f}")
        return 0

    print(f"plan            : {args.plan}")
    print(f"baked-in factor : {baked:.1f}x")
    print(f"wanted rate     : {args.rate:g}x real time")
    print(f"--speedup       : {speedup:.6f}")
    if args.max_t_sim is not None:
        print(f"expected trial  : {expected_wall_seconds(args.plan, args.max_t_sim, args.rate):.0f}s wall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
