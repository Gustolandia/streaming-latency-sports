#!/usr/bin/env python3
"""
law_runs.py -- every run of the pre-registered law campaign, each with the marks that say what,
if anything, was aberrant about it and why. Read on 28 September 2026 for the write-up of the
campaign (Supplement Part V). It decides nothing: every verdict stays the frozen judges' own.

Everything here is read from the repository, never from the runs themselves:

  docs/results/registry/runs_<pair>.csv            every run, its settings, its integrity verdict
  docs/results/law/judged-27-sep/quality_by_campaign.csv   the 156 campaigns the judging read
  docs/results/law/judged-27-sep/views/unflagged.json      the runs the got-it brake flagged
  docs/results/law/strange-results-28-sep/pause_runs.csv   the runs a pause held
  docs/results/registry/campaigns_<pair>.csv       which campaigns were false starts

A run's marks, each with the reason it is marked:

  void          set aside before any campaign read it: two calibrations wrote into one folder
                (16 September) or a calibration was opened on top of a running one (21 September)
  false start   its campaign stopped before measuring anything worth keeping and was replaced
                at once by a whole campaign of the same design
  repeated      a condition it was meant to have did not take (load, rate, messages, capture),
                so the integrity rule did not count it and the queue ran it again
  stopped       the instrument was in doubt: a got-it median moved more than the brake allows,
                so the run did not count and its campaign stopped
  unjudged      it ended before the integrity rule could judge it
  flagged       taken while the got-it brake only recorded, and the brake would have stopped on it
  paused        a message in it arrived more than 150 ms late past the warm-up: a stall of the
                driver's disk or of Kafka's broker held it
  far           its trip, got-it or held delay lies far from its fellows' (the quality report's
                rule: past the quantity's floor and more than five robust deviations)
  traced        A9's or M0's traced half, the runs whose scheduling events were recorded: A9's
                event tracer raised the rate it recorded and M0's recording moved the trips it
                recorded, so these describe the machine with the tracing on

The first five keep a run out of every judge; the last four leave it counted.

CLI:
    python scripts/law_runs.py                   a count of every mark, pair by pair
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys

PAIRS = ("matched", "matched-b", "arm")
PAIR_NAMES = {"matched": "first x86", "matched-b": "second x86", "arm": "Arm"}
LAW_BLOCKS = ("A1", "A2", "A3", "A4", "A5", "A7", "A8", "A9")

#: Every mark, in the order a run is described by them, with what it means for the judges.
MARKS = (
    ("void", "set aside before any campaign read it", "out"),
    ("false start", "its campaign stopped before measuring and was replaced whole", "out"),
    ("repeated", "a condition it was meant to have did not take", "out"),
    ("stopped", "a got-it median moved more than the brake allows", "out"),
    ("unjudged", "it ended before the integrity rule could judge it", "out"),
    ("flagged", "the got-it brake, only recording, would have stopped on it", "counted"),
    ("paused", "a message in it was held more than 150 ms by a stall", "counted"),
    ("far", "its trip, got-it or held delay lies far from its fellows'", "counted"),
    ("traced", "its tracing disturbed what it measured (A9, M0)", "counted"),
)
MARK_KEYS = tuple(key for key, _, _ in MARKS)
OUT_MARKS = tuple(key for key, _, effect in MARKS if effect == "out")

#: The quality report's rule for a repeat far from its fellows (quality_report.WAYPOINT_FLOORS
#: and OUTLIER_Z), on the quantities the registry keeps.
FAR_FLOORS = {"trip_median_ms": 0.20, "gotit_median_ms": 0.20, "delay_held_ms": 0.05}
FAR_Z = 5.0
MAD_TO_SD = 1.4826

RUN_NAME = re.compile(r"^law_(?P<folder>.+?)_r\d{3}-")
VERDICT_MARKS = {"repeat": "repeated", "stop": "stopped", "": "unjudged"}


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def folder_of(run_name):
    """The campaign folder a run's name places it in, or None for a name without one."""
    found = RUN_NAME.match(run_name)
    return found.group("folder") if found else None


def far_runs(runs, floors=None, z=FAR_Z):
    """{(pair, run)} whose trip, got-it or held delay lies far from its fellows': the other
    repeats of its setup in its campaign, where there are at least three."""
    floors = FAR_FLOORS if floors is None else floors
    groups = {}
    for run in runs:
        groups.setdefault((run["pair"], run["folder"], run["setup"]), []).append(run)
    found = set()
    for repeats in groups.values():
        for quantity, floor in floors.items():
            values = [(r["run"], r[quantity]) for r in repeats if r.get(quantity) is not None]
            if len(values) < 3:
                continue
            middle = statistics.median(v for _, v in values)
            spread = MAD_TO_SD * statistics.median(abs(v - middle) for _, v in values)
            for name, value in values:
                distance = abs(value - middle)
                if distance >= floor and (spread == 0.0 or distance / spread > z):
                    found.add((repeats[0]["pair"], name))
    return found


def _registry(registry_dir):
    runs = []
    for pair in PAIRS:
        with open(os.path.join(registry_dir, "runs_%s.csv" % pair), newline="",
                  encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                runs.append(row)
    return runs


def _false_starts(registry_dir):
    found = set()
    for pair in PAIRS:
        with open(os.path.join(registry_dir, "campaigns_%s.csv" % pair), newline="",
                  encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["complete"] != "True":
                    found.add((pair, row["campaign"]))
    return found


def load(registry_dir=os.path.join("docs", "results", "registry"),
         judged_dir=os.path.join("docs", "results", "law", "judged-27-sep"),
         pause_csv=os.path.join("docs", "results", "law", "strange-results-28-sep",
                                "pause_runs.csv")):
    """Every run of the registry, with its campaign folder, its numbers and its marks."""
    with open(os.path.join(judged_dir, "quality_by_campaign.csv"), newline="",
              encoding="utf-8") as fh:
        judged = set((r["pair"], r["campaign"]) for r in csv.DictReader(fh))
    with open(os.path.join(judged_dir, "views", "unflagged.json"), encoding="utf-8") as fh:
        view = json.load(fh)
    flagged = set((c["pair"], name) for c in view["campaigns"] for name in c["left_out"])
    with open(pause_csv, newline="", encoding="utf-8") as fh:
        paused = set((r["pair"], r["run"]) for r in csv.DictReader(fh) if r["paused"] == "True")
    false_starts = _false_starts(registry_dir)
    runs = []
    for row in _registry(registry_dir):
        folder = folder_of(row["run"])
        run = {"run": row["run"], "pair": row["pair"], "folder": folder,
               "block": row["block"], "setup": row["setup"], "backend": row["backend"],
               "point": row["point"], "verdict": row["verdict"],
               "load_pct": _number(row["load_pct"]),
               "slice_ms": (_number(row["slice_set_ns"]) or 0.0) / 1e6 or None,
               "tick_ms": _number(row["tick_ms"]), "cpus": _number(row["cpus"]),
               "language": row["language"] or "python", "priority": row["priority"] == "True",
               "recorded_half": row["recorded_half"] == "True",
               "trip_median_ms": _number(row["trip_median_ms"]),
               "gotit_median_ms": _number(row["gotit_median_ms"]),
               "delay_held_ms": _number(row["delay_held_ms"]),
               "rate": _number(row["measured_negative_rate"]),
               "reasons": row["reasons"], "marks": []}
        key = (row["pair"], folder)
        if folder is None or key not in judged:
            run["marks"].append("void")
        elif (row["pair"], row["campaign"]) in false_starts:
            run["marks"].append("false start")
        if row["verdict"] in VERDICT_MARKS:
            run["marks"].append(VERDICT_MARKS[row["verdict"]])
        if (row["pair"], row["run"]) in flagged:
            run["marks"].append("flagged")
        if (row["pair"], row["run"]) in paused:
            run["marks"].append("paused")
        if run["recorded_half"] and row["block"] in ("A9", "M0"):
            run["marks"].append("traced")
        runs.append(run)
    # A repeat is held against the runs its setup's judges read, so only counted runs are.
    counted = [r for r in runs if not set(r["marks"]) & set(OUT_MARKS)]
    far = far_runs(counted)
    for run in runs:
        if (run["pair"], run["run"]) in far:
            run["marks"].append("far")
    for run in runs:
        run["marks"].sort(key=MARK_KEYS.index)
    return runs


def counts(runs, blocks=None):
    """{mark: {pair: n}} over the runs of the named blocks (every block when None)."""
    found = dict((mark, dict.fromkeys(PAIRS, 0)) for mark in MARK_KEYS)
    for run in runs:
        if blocks is not None and run["block"] not in blocks:
            continue
        for mark in run["marks"]:
            found[mark][run["pair"]] += 1
    return found


def lines(runs):
    out = ["Every run of the law campaign and its marks (decides nothing)",
           "  runs: %d, of them in the law's blocks: %d"
           % (len(runs), sum(1 for r in runs if r["block"] in LAW_BLOCKS))]
    every, law = counts(runs), counts(runs, LAW_BLOCKS)
    for mark, meaning, effect in MARKS:
        out.append("  %-12s %s; all blocks %s; the law's blocks %s  (%s)" % (
            mark, effect, ", ".join("%s %d" % (PAIR_NAMES[p], every[mark][p]) for p in PAIRS),
            sum(law[mark].values()), meaning))
    return out


def main(argv=None, out=None):
    out = out or sys.stdout
    ap = argparse.ArgumentParser(description="Every run of the law campaign, and its marks")
    ap.add_argument("--registry", default=os.path.join("docs", "results", "registry"))
    ap.add_argument("--judged", default=os.path.join("docs", "results", "law", "judged-27-sep"))
    ap.add_argument("--pauses", default=os.path.join("docs", "results", "law",
                                                     "strange-results-28-sep", "pause_runs.csv"))
    args = ap.parse_args(argv)
    try:
        runs = load(args.registry, args.judged, args.pauses)
    except (OSError, ValueError, KeyError) as exc:
        print("ERROR: %s" % exc, file=out)
        return 2
    for line in lines(runs):
        print(line, file=out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
