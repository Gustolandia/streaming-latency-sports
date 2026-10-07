#!/usr/bin/env python3
"""
untraced_control.py
The E-A9 untraced twin's two cells, the comparator of the tracer check.

The first attempt at the traced E-A9 run lost its probe and ran untraced, two hours from the
traced one, with the same design (docs/results/depth/ea9_notrace). Its normal-priority and
real-time cells are what the tracer check holds the traced cells to, and what Section VIII
compares them with. docs/results/model/ea9_notrace/untraced_control.csv was written in July
from these cells by hand-run code; this is its producer, with analyze_knee's own readers, so
that the cells can be recounted the way every other cell is. From 7 Oct 2026 that recount
leaves out the messages a consumer received late behind a stale backlog (stale_backlog.py).

CLI:
    python scripts/untraced_control.py --depth-dir cloud_archive/extracted/docs/results/depth \
        --runs-dir cloud_archive/extracted/runs
"""
import argparse
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_knee  # noqa: E402

PHASE = "ea9_notrace"
DEFAULT_OUT = os.path.join("docs", "results", "model", "ea9_notrace", "untraced_control.csv")
FIELDS = ("condition", "rho", "inversion_rate", "n_inversions", "n_events", "n_runs")


def control_rows(depth_dir, runs_dir, phase=PHASE):
    """One row per usable cell, as the committed table has them: rho to five places."""
    rows = []
    for cond in sorted(glob.glob(os.path.join(depth_dir, phase, "*"))):
        if not os.path.isdir(cond):
            continue
        rho = analyze_knee.median_rho(cond)
        inv = analyze_knee.condition_inversion(cond, runs_dir)
        if rho is None or inv is None:
            continue
        rows.append({"condition": os.path.basename(cond), "rho": round(rho, 5),
                     "inversion_rate": round(inv["inversion_rate"], 5),
                     "n_inversions": inv["n_inversions"], "n_events": inv["n_events"],
                     "n_runs": inv["n_runs"]})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="The E-A9 untraced twin's cells")
    ap.add_argument("--depth-dir", default=os.path.join("docs", "results", "depth"))
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    rows = control_rows(args.depth_dir, args.runs_dir)
    if len(rows) != 2:
        print("found %d usable cells under %s, not the two -- refusing to write"
              % (len(rows), os.path.join(args.depth_dir, PHASE)))
        return 1
    folder = os.path.dirname(args.out)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
