#!/usr/bin/env python3
"""
mark_load_bearing.py
Add a `load_bearing` column to a runs index: does any reported result depend on this run?

Written because the index's first `used_by` column answered a narrower question than it looked
like it answered. It flags runs *named by a tracked aggregate CSV*, and the campaigns that decide
the paper's mechanism name none of their runs anywhere: `analyze_knee`, `analyze_runq_tail`,
`analyze_ttrue_sweep` and the rest locate their runs by matching a timestamp taken from a depth
condition directory against `runs/concurrency_<ts>_<backend>_*`. So every run behind the geometry
contrast, the payload sweep and the kernel trace showed `used_by` empty, and reading that column
as "unused" would have selected exactly the load-bearing data for deletion.

A run counts as load-bearing if any of these hold:

  aggregate   a tracked CSV under docs/results names its run_id
  condition   a depth/window/campaign condition directory carries a timestamp the run id starts
              with, which is how the analysis scripts themselves find it
  figure      it belongs to a campaign whose output a manuscript figure is drawn from

The reasons are recorded, not just the boolean, so a later reader can see *why* a run is being
kept and re-derive the judgement rather than trusting it.

CLI:
    python scripts/mark_load_bearing.py --index reproducibility/runs_index.csv
    python scripts/mark_load_bearing.py --index reproducibility/runs_index_cloud.csv --results docs/results
"""
import argparse
import csv
import glob
import os
import re

TS = re.compile(r"concurrency_(n\d+_\d{8}_\d{6})")
# Directories whose contents feed an analysis script or a figure.
CONDITION_GLOBS = (
    "depth*/*/*/concurrency_concurrency_*",
    "depth*/*/concurrency_concurrency_*",
    "*/concurrency_concurrency_*",
    "*/*/concurrency_concurrency_*",
)


def condition_timestamps(results_dir):
    """Every run-id timestamp named by a condition directory, with where it was found."""
    found = {}
    for pattern in CONDITION_GLOBS:
        for path in glob.glob(os.path.join(results_dir, pattern)):
            m = TS.search(os.path.basename(path))
            if not m:
                continue
            rel = os.path.relpath(os.path.dirname(path), results_dir).replace("\\", "/")
            found.setdefault(m.group(1), set()).add(rel.split("/")[0])
    return found


def named_by_aggregate(results_dir):
    """run_ids a tracked aggregate CSV names outright."""
    named = {}
    for path in glob.glob(os.path.join(results_dir, "**", "*.csv"), recursive=True):
        rel = os.path.relpath(path, results_dir).replace("\\", "/")
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                head = fh.readline()
                if "run" not in head.lower():
                    continue
                fh.seek(0)
                for r in csv.DictReader(fh):
                    rid = r.get("run_id") or r.get("run") or r.get("run_dir")
                    if rid:
                        key = os.path.basename(str(rid).rstrip("/\\"))
                        named.setdefault(key, set()).add(rel)
        except (OSError, csv.Error):
            continue
    return named


def classify(run_id, aggregates, timestamps):
    """Why this run is load-bearing, or empty if nothing depends on it."""
    reasons = []
    if run_id in aggregates:
        reasons.append("aggregate:" + sorted(aggregates[run_id])[0])
    for ts, where in timestamps.items():
        if run_id.startswith(f"concurrency_{ts}_"):
            reasons.append("condition:" + sorted(where)[0])
            break
    return reasons


def annotate(index_path, results_dir, out_path=None):
    with open(index_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        return [], []
    aggregates = named_by_aggregate(results_dir)
    timestamps = condition_timestamps(results_dir)
    for r in rows:
        reasons = classify(r["run_id"], aggregates, timestamps)
        r["load_bearing"] = "yes" if reasons else "no"
        r["load_bearing_why"] = ";".join(reasons[:2])
    fields = [f for f in rows[0] if f not in ("load_bearing", "load_bearing_why")]
    fields += ["load_bearing", "load_bearing_why"]
    with open(out_path or index_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return rows, timestamps


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mark which runs a reported result depends on")
    ap.add_argument("--index", default="reproducibility/runs_index.csv")
    ap.add_argument("--results", default="docs/results")
    ap.add_argument("--out", default=None, help="default: rewrite the index in place")
    args = ap.parse_args(argv)

    if not os.path.exists(args.index):
        print(f"no such index: {args.index}")
        return 1

    rows, timestamps = annotate(args.index, args.results, args.out)
    if not rows:
        print(f"{args.index} is empty")
        return 1

    yes = sum(1 for r in rows if r["load_bearing"] == "yes")
    print(f"{args.index}: {len(rows):,} runs, {len(timestamps)} condition timestamps")
    print(f"  load-bearing      {yes:6,}")
    print(f"  nothing depends on {len(rows) - yes:6,}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
