#!/usr/bin/env python3
"""
judge_campaigns.py -- one prediction's answer over the campaigns it is judged on, each read from
its own collected folder.

Each campaign is read by law_curve.counted() from its own folder, so every run keeps its
campaign's name -- the anchor correction groups by it (D30-4) -- and what the integrity rule left
out is named before the answer. The runs are then judged together by law_predictions.judge(),
which splits by pair and backend itself. This is the runner every verdict from 21 September on
was given by, until 27 September from a copy outside the repository; it is kept here so that each
verdict can be run again from the repository alone. It decides nothing: the rules are the judge's.

The views brake_views.py lays out (D32-1) are campaign folders like any other, so a prediction is
judged with and without the runs the got-it brake only recorded by pointing this at each view.

CLI:
    python scripts/judge_campaigns.py P1 --tick-ms 1.0 --anchor-ms 3.0 \\
        runs/azure/collected/matched/a1_20260918T194622Z/runs ... [--out answer.json]
    python scripts/judge_campaigns.py P7 --read-back 2=1.4,4=2.1,8=2.8 <folders>
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import law_curve  # noqa: E402
import law_predictions  # noqa: E402


def read_back_pairs(text):
    """'2=1.4,4=2.1' as {2: 1.4, 4: 2.1}: the slice each core count reads back, for P7."""
    return dict((int(part.split("=")[0]), float(part.split("=")[1]))
                for part in text.split(",") if "=" in part)


def gather(folders, out):
    """Every counted run of every folder, each folder's count said, and what was left out."""
    runs, left = [], []
    for folder in folders:
        mine, skipped = law_curve.counted(folder)
        print("%s: %d runs counted, %d left out" % (folder, len(mine), len(skipped)), file=out)
        runs += mine
        left += skipped
    said = law_curve.left_out(left)
    if said:
        print(said, file=out)
    return runs


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="One prediction over the campaigns it is judged on")
    ap.add_argument("prediction")
    ap.add_argument("folders", nargs="+", help="each a campaign's folder of copied runs")
    ap.add_argument("--tick-ms", type=float, default=1.0)
    ap.add_argument("--anchor-ms", type=float, default=None)
    ap.add_argument("--read-back", default="", help="P7's read-back slices, e.g. 2=1.4,4=2.1")
    ap.add_argument("--draws", type=int, default=law_predictions.DRAWS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="", help="write the answer here as JSON")
    args = ap.parse_args(argv)
    try:
        runs = gather(args.folders, out)
        found = law_predictions.judge(runs, args.prediction, args.tick_ms, args.draws,
                                      args.seed, read_back=read_back_pairs(args.read_back),
                                      anchor_ms=args.anchor_ms)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(found, indent=2, sort_keys=True, default=str) + "\n")
    for line in law_predictions.lines(args.prediction, found):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
