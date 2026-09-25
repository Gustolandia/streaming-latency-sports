#!/usr/bin/env python3
"""
replay_window.py -- what a replay plan sends inside a run's measured window (M0, D29-1).

A steady plan sends its rate times the time, and a run is checked against exactly that. M0 replays
the football match in bursts, as the pilot did, and a burst sends what the match did: nearly half
the gaps are under a millisecond and some are seconds long. So the count a run is held to, and the
rate it is checked at, are read off the plan instead -- the events whose send time, at the speed
the run replays at, falls after the warm-up and within the run -- together with the last match
second the producer must be allowed to reach so that it sends them.

Send times are counted from the plan's first event, as the run's warm-up is counted from its
first send.

CLI (campaign.sh reads the three numbers off its one line):
    python3 scripts/replay_window.py <replay_plan.csv> --speedup 0.188 --duration 130 --warmup-s 30
    -> <max_t_sim> <planned> <rate>
"""
import argparse
import csv
import sys


def window(rows, speedup, duration_s, warmup_s):
    """{max_t_sim, planned, rate} for one run of `duration_s` seconds replayed at `speedup`."""
    if speedup <= 0 or duration_s <= warmup_s:
        raise ValueError("a replay needs a positive speed-up and a run longer than its warm-up")
    sends = sorted((float(row["t_emit_offset_s"]) / speedup, float(row["t_sim_seconds"]))
                   for row in rows)
    if not sends:
        raise ValueError("the plan has no events")
    first = sends[0][0]
    within = [(at - first, sim) for at, sim in sends if at - first <= duration_s]
    after = [at for at, _ in within if at >= warmup_s]
    span = after[-1] - after[0] if after else 0.0
    return {"max_t_sim": int(max(sim for _, sim in within)),
            "planned": len(after),
            "rate": (len(after) - 1) / span if span > 0 else 0.0}


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="What a replay plan sends in a run's window")
    ap.add_argument("plan")
    ap.add_argument("--speedup", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True, help="the run's seconds")
    ap.add_argument("--warmup-s", type=float, default=30.0)
    args = ap.parse_args(argv)
    try:
        with open(args.plan, newline="", encoding="utf-8") as fh:
            found = window(list(csv.DictReader(fh)), args.speedup, args.duration, args.warmup_s)
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    print("%d %d %.4f" % (found["max_t_sim"], found["planned"], found["rate"]), file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
