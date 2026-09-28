#!/usr/bin/env python3
"""
brake_views.py -- the runs a prediction is judged on, with and without what the got-it brake
only recorded (plan version 32, D32-1).

From version 32 the got-it brake records rather than stops: what it would have said travels with
each run, and every prediction a recorded run bears on is judged with and without the runs the
brake would have stopped. The judges are frozen, so none of them is taught this. Each reading is
a *view*: the collected campaign folders laid out again with some runs left out, every file a hard
link to the collected one, so each judge runs unchanged on each view and nothing is copied.

A run's state, from its integrity.json:
  stopping   taken while the brake still stopped (no `gotit_brake` in what it recorded);
  recorded   taken while the brake recorded, and the check it would have stopped on held, or
             could not be made;
  flagged    taken while the brake recorded, and the check it would have stopped on failed.

The views:
  all          every run, as collected;
  unflagged    without the flagged runs: D32-1's "without the runs the brake would have stopped";
  stopping     without any run taken while the brake recorded: what a stopping brake leaves, the
               reading D26-1 gave A5 at 2 CPUs ("the runs taken under the rule").

A campaign folder is laid out as collect_runs.py lays one out:
  <campaign>/COLLECTED.json, <campaign>/runs/<run folders>, <campaign>/runs/azure/<stage>/<folder>.

And, read after the fact, a view without any runs a CSV lists -- the runs a pause held, as
pause_census.py lists them in pause_runs.csv -- laid out the same way (`without`).

CLI:
    python scripts/brake_views.py count --campaigns runs/azure/final_campaigns
    python scripts/brake_views.py build --campaigns runs/azure/final_campaigns \\
        --out runs/azure/brake_views
    python scripts/brake_views.py without --campaigns runs/azure/final_campaigns \\
        --out runs/azure/brake_views --view unpaused --runs-csv pause_runs.csv
"""
import argparse
import csv
import json
import os
import sys

STATES = ("stopping", "recorded", "flagged")
VIEWS = {"unflagged": ("stopping", "recorded"), "stopping": ("stopping",)}


def brake_state(run_dir):
    """stopping, recorded or flagged, from what the run's integrity check recorded."""
    try:
        with open(os.path.join(run_dir, "integrity.json"), encoding="utf-8") as fh:
            recorded = json.load(fh).get("recorded") or {}
    except (OSError, ValueError):
        return "stopping"
    if "gotit_brake" not in recorded:
        return "stopping"
    steady = recorded.get("gotit_steady")
    if isinstance(steady, dict) and steady.get("ok") is False:
        return "flagged"
    return "recorded"


def campaigns_under(root):
    """(pair, campaign, folder) for every campaign folder under a root of pairs."""
    found = []
    for pair in sorted(os.listdir(root)):
        pair_dir = os.path.join(root, pair)
        if not os.path.isdir(pair_dir):
            continue
        for campaign in sorted(os.listdir(pair_dir)):
            folder = os.path.join(pair_dir, campaign)
            if os.path.exists(os.path.join(folder, "COLLECTED.json")):
                found.append((pair, campaign, folder))
    return found


def run_folders(folder):
    """The run folders of one campaign folder: those holding a queue row."""
    runs = os.path.join(folder, "runs")
    return sorted(name for name in os.listdir(runs)
                  if os.path.exists(os.path.join(runs, name, "queue_row.json")))


def census(root):
    """Per campaign, how many of its runs are in each state."""
    rows = []
    for pair, campaign, folder in campaigns_under(root):
        states = dict.fromkeys(STATES, 0)
        flagged = []
        for name in run_folders(folder):
            state = brake_state(os.path.join(folder, "runs", name))
            states[state] += 1
            if state == "flagged":
                flagged.append(name)
        rows.append({"pair": pair, "campaign": campaign, "runs": sum(states.values()),
                     "flagged_runs": flagged, **states})
    return rows


def link_tree(src, dst):
    """Hard-link every file under src into the same place under dst; the file count."""
    count = 0
    for top, _dirs, files in os.walk(src):
        rel = os.path.relpath(top, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target, exist_ok=True)
        for name in files:
            os.link(os.path.join(top, name), os.path.join(target, name))
            count += 1
    return count


def lay_out(root, out, view, keeps, about):
    """Lay out every campaign under root into out/<view>, keeping the runs `keeps(pair,
    run_dir)` says to; what it kept and left, also written to out/<view>/VIEW.json with
    `about` beside it."""
    rows = []
    for pair, campaign, folder in campaigns_under(root):
        dest = os.path.join(out, view, pair, campaign)
        if os.path.exists(dest):
            raise ValueError("%s already exists; a view is laid out once" % dest)
        kept, left = [], []
        for name in run_folders(folder):
            (kept if keeps(pair, os.path.join(folder, "runs", name)) else left).append(name)
        for name in kept:
            link_tree(os.path.join(folder, "runs", name), os.path.join(dest, "runs", name))
        stages = os.path.join(folder, "runs", "azure")
        if os.path.isdir(stages):
            link_tree(stages, os.path.join(dest, "runs", "azure"))
        os.makedirs(dest, exist_ok=True)
        os.link(os.path.join(folder, "COLLECTED.json"), os.path.join(dest, "COLLECTED.json"))
        rows.append({"pair": pair, "campaign": campaign, "kept": len(kept), "left_out": left})
    with open(os.path.join(out, view, "VIEW.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(about, view=view, campaigns=rows, **{"from": os.path.abspath(root)}), fh,
                  indent=1)
        fh.write("\n")
    return rows


def build(root, out, view):
    """Lay out one view of every campaign under root into out/<view>; what it kept and left."""
    if view not in VIEWS:
        raise ValueError("the views are %s, not %r" % (", ".join(sorted(VIEWS)), view))
    keep = VIEWS[view]
    return lay_out(root, out, view, lambda pair, run_dir: brake_state(run_dir) in keep,
                   {"keeps": list(keep)})


def listed_runs(path, column="paused"):
    """{(pair, run)} for the rows of a CSV whose `column` says True, as pause_census.py writes
    pause_runs.csv: the runs a view without them leaves out."""
    with open(path, newline="", encoding="utf-8") as fh:
        return set((row["pair"], row["run"]) for row in csv.DictReader(fh)
                   if row.get(column) == "True")


def build_without(root, out, view, leave_out, why):
    """Lay out every campaign under root into out/<view>, without the (pair, run) pairs in
    `leave_out`; `why` says in VIEW.json what they are."""
    return lay_out(root, out, view,
                   lambda pair, run_dir: (pair, os.path.basename(run_dir)) not in leave_out,
                   {"without": why})


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Views of the runs with and without what the "
                                             "got-it brake only recorded (D32-1)")
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("count")
    c.add_argument("--campaigns", required=True)
    b = sub.add_parser("build")
    b.add_argument("--campaigns", required=True)
    b.add_argument("--out", required=True)
    w = sub.add_parser("without", help="a view without the runs a CSV lists (post hoc)")
    w.add_argument("--campaigns", required=True)
    w.add_argument("--out", required=True)
    w.add_argument("--view", required=True, help="the view's name, its folder under --out")
    w.add_argument("--runs-csv", required=True, help="pair,run,...,<column> rows")
    w.add_argument("--column", default="paused", help="the column whose True leaves a run out")
    w.add_argument("--why", default="", help="what the runs left out are, for VIEW.json")
    args = ap.parse_args(argv)
    try:
        if args.command == "without":
            leave_out = listed_runs(args.runs_csv, args.column)
            rows = build_without(args.campaigns, args.out, args.view, leave_out,
                                 args.why or "the runs %s marks %s" % (args.runs_csv,
                                                                       args.column))
            print("%s: %d campaigns, %d runs kept, %d left out" % (
                args.view, len(rows), sum(r["kept"] for r in rows),
                sum(len(r["left_out"]) for r in rows)), file=out)
            return 0
        if args.command == "count":
            for row in census(args.campaigns):
                if row["recorded"] or row["flagged"]:
                    print("%s %s: %d runs, %d taken while the brake stopped, %d recorded, "
                          "%d flagged %s" % (row["pair"], row["campaign"], row["runs"],
                                             row["stopping"], row["recorded"], row["flagged"],
                                             ", ".join(row["flagged_runs"])), file=out)
            return 0
        for view in sorted(VIEWS):
            rows = build(args.campaigns, args.out, view)
            print("%s: %d campaigns, %d runs kept, %d left out" % (
                view, len(rows), sum(r["kept"] for r in rows),
                sum(len(r["left_out"]) for r in rows)), file=out)
        return 0
    except (OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
