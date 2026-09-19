#!/usr/bin/env python3
"""
progress.py -- how much of the experiment has been run, as a share of what the plan asks for.

The plan's campaigns table (freeze 04) lists every campaign and the runs it takes at the floor of
four rounds: 47 campaigns and 3,590 runs in all. This counts what has actually been run against
that, so a person watching can see the work move rather than guess from hours and money.

A run counts here only when it counted there: the verdict its own checks gave it as it ended. A
run that was repeated, or that belonged to a session a rule stopped, cost machine time and is
kept, but it is not a run the plan asked for and it is not counted as one.

Two sources, and they cannot overlap: campaigns already copied home, read from the quality report
collect_runs.py leaves beside them, and the campaign running now, read from its own queue. A
campaign is only copied once it has finished, so nothing is counted twice.

The share is honest about what it cannot know. Session calibrations run once per session, and a
session that ends early is repeated, so stage 0 can pass the runs the plan set aside for it;
where a stage passes its own number the share says so rather than reporting more than all of it.

CLI:
    python scripts/progress.py show [--collected runs/azure/collected]
"""
import argparse
import glob
import json
import os
import sys

#: What the plan asks for, at the floor of four rounds: the name a person reads, the campaign
#: labels that belong to it, and the runs it takes. From the campaigns table of freeze 04.
PLAN = (("stage 0, the instrument", ("s0", "c0", "b0", "p0", "m0"), 414),
        ("A1, the slice", ("a1",), 592),
        ("A3, the load", ("a3",), 216),
        ("A7, go-first", ("a7",), 72),
        ("A5, the core count", ("a5",), 264),
        ("A2, the tick", ("a2",), 682),
        ("A4, the Arm pair", ("a4",), 430),
        ("A8, the client", ("a8",), 240),
        ("T1 to T4, the tools", ("t1", "t2", "t3", "t4"), 680))
TOTAL = sum(runs for _, _, runs in PLAN)
COLLECTED = os.path.join("runs", "azure", "collected")

#: Stage 0 is the instrument work on the x86 pairs: S0-1 to S0-4, the last of them on a second
#: x86 pair. The Arm pair's own instrument campaign is the first of A4's five, not a fifth stage-0
#: campaign, so where an instrument campaign ran decides which stage it belongs to.
INSTRUMENT, ARM_BLOCK, ARM_PAIR = PLAN[0][0], "A4, the Arm pair", "arm"


def stage_of(label, profile=None):
    """The stage a campaign belongs to, from its label and the pair that ran it."""
    start = os.path.basename(str(label)).split("_")[0].lower()
    for name, labels, _ in PLAN:
        if start in labels:
            if name == INSTRUMENT and str(profile or "").lower().split("_")[0] == ARM_PAIR:
                return ARM_BLOCK
            return name
    return None


def counted(collected=COLLECTED):
    """{stage: runs that counted} over every campaign copied home.

    collect_runs.py files a campaign under the pair that ran it, so the folder above it is that
    pair, which is what tells an instrument campaign apart from A4's own.
    """
    found = {}
    for report in sorted(glob.glob(os.path.join(collected, "*", "*", "quality_report.json"))):
        where = os.path.dirname(report)
        stage = stage_of(os.path.basename(where), os.path.basename(os.path.dirname(where)))
        if stage is None:
            continue
        try:
            with open(report, encoding="utf-8") as fh:
                verdicts = json.load(fh).get("verdicts") or {}
        except (OSError, ValueError):
            continue
        found[stage] = found.get(stage, 0) + int(verdicts.get("count") or 0)
    return found


def add_live(found, live):
    """The runs a campaign now under way has already counted, added to what came home.

    `live` is (pair, campaign label, runs done) for each campaign running now, as the watch reads
    them from the drivers' own queues.
    """
    found = dict(found)
    for profile, label, done in live or ():
        stage = stage_of(label, profile)
        if stage is not None:
            found[stage] = found.get(stage, 0) + int(done or 0)
    return found


def share(found):
    """(runs done, runs the plan asks for, the share as a percentage).

    A stage never contributes more than the plan set aside for it: repeating a session's
    calibration is work the plan asks for, but it does not make the experiment more complete.
    """
    done = 0
    for name, _, runs in PLAN:
        done += min(found.get(name, 0), runs)
    return done, TOTAL, 100.0 * done / TOTAL


def line(found):
    """One line a person reads as a run begins."""
    done, total, pct = share(found)
    return "progress: %d of %s runs the plan asks for (%.1f%%)" % (done, "{:,}".format(total), pct)


def lines(found):
    """The whole picture, stage by stage."""
    out = [line(found)]
    for name, _, runs in PLAN:
        got = found.get(name, 0)
        out.append("  %-24s %4d of %4d  %s%s"
                   % (name, min(got, runs), runs,
                      "#" * int(round(20.0 * min(got, runs) / runs)),
                      "  (and %d more, which the plan did not set aside)" % (got - runs)
                      if got > runs else ""))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="How much of the experiment has been run")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show")
    p.add_argument("--collected", default=COLLECTED)
    p.add_argument("--quiet", action="store_true", help="the one line, without the stages")
    args = ap.parse_args(argv)
    try:
        found = counted(args.collected)
        for said in ([line(found)] if args.quiet else lines(found)):
            print(said, file=out)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
