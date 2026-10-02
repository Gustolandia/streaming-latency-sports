#!/usr/bin/env python3
"""
tools_block.py -- the tools block's judged results, folded into two committed tables.

The registered law campaign ran eleven benchmarking tools on the first x86 pair, four rounds
each (blocks T1 to T4, plan decision D3-1: "the tools block T1-T4 is in this paper"; the
write-up is docs/results/tools/t1-t4-eleven-tools.md). Their raw runs stay outside git, in the
whole runs folders archived with the data record. What the paper says about them is a handful
of counts, and a count the paper prints has to be a fold over committed rows like every other
number in it. So this script reads the judged files the campaign left beside each run and
writes two small tables, which are committed:

  docs/results/tools/tools_t1.csv   round, tool, trip, figure, crossings, slope
  docs/results/tools/tools_t2.csv   round, tool, offset_ms, verdict, standing

T1 is the staircase: a known delay added to the path in ten steps, and the slope at which the
tool's figure follows it, on the figure the staircase was read from. T2 moves the clock the tool
reads back by more than its trip and asks what the tool does with the result: the verdict is
the one behaviour still standing, or "undecided" when more than one is.

Which judged file stands for which round is the write-up's decision, not this script's:

  round 1     snapshot_20260925T002916Z. Its T2 verdicts as judged again under freeze 21 as
              written (t2_rejudged_20260925: the judge first held a tool's count against our
              reference instead of against what the tool was asked to send), and hey's
              staircase as read again (hey_reread_20260925: hey's percentiles had never been
              read, so its slope was taken on its average).
  rounds 2-4  snapshot_20260925T141523Z, tools_round2 to tools_round4, judged on the pair by
              the corrected programs.

    python scripts/tools_block.py --collected runs/azure/collected/matched
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

#: What a T2 run is recorded as when more than one behaviour survives its judge.
UNDECIDED = "undecided"

T1_FIELDS = ("round", "tool", "trip", "figure", "crossings", "slope")
T2_FIELDS = ("round", "tool", "offset_ms", "verdict", "standing")

#: (round, folder of its runs, where its T2 verdicts are, staircases read again).
ROUNDS = (
    ("1", "snapshot_20260925T002916Z/runs/azure/tools", "t2_rejudged_20260925",
     {"hey": "hey_reread_20260925"}),
    ("2", "snapshot_20260925T141523Z/runs/azure/tools_round2", None, {}),
    ("3", "snapshot_20260925T141523Z/runs/azure/tools_round3", None, {}),
    ("4", "snapshot_20260925T141523Z/runs/azure/tools_round4", None, {}),
)

#: The interval each tool times, as the plan read its invocation before any run (the addendum
#: of freeze 21, "How each tool keeps time"). It is how the tool was run, not a measurement, and
#: T2 is its test: every tool read as one clock was found on one, and the tool read as spanning
#: two was found on two. A tool missing from this map stops the fold rather than printing a gap.
TRIPS = {
    "valkey-benchmark": "round trip",
    "memtier_benchmark": "round trip",
    "wrk2": "round trip",
    "vegeta": "round trip",
    "hey": "round trip",
    "k6": "round trip",
    "kafka-producer-perf": "send to acknowledgment",
    "kafka-end-to-end": "in one process",
    "rabbitmq-perftest": "in one process",
    "nats-latency": "in one process",
    "rdkafka_performance": "across two processes",
}

_STEP = re.compile(r"t1-(.+)-step\.json$")
#: An offset run, as tools.sh names it: the tool, then the offset asked for, `_` for the point.
#: The controls (`t2-<tool>-control`) carry no verdict and do not match.
_OFFSET = re.compile(r"t2-(.+)-(\d+(?:_\d+)?)ms$")


def t1_rows(rnd, folder, read_again=None):
    """One row per tool: the slope its staircase found, and the figure it was read on."""
    read_again = read_again or {}
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "t1-*-step.json"))):
        tool = _STEP.search(os.path.basename(path)).group(1)
        path = read_again.get(tool, path)
        with open(path, encoding="utf-8") as fh:
            s = json.load(fh)["slope"]
        rows.append({"round": rnd, "tool": tool, "trip": TRIPS[tool], "figure": s["figure"],
                     "crossings": s["crossings"],
                     "slope": "" if s["slope"] is None else "%.4f" % s["slope"]})
    return rows


def t2_rows(rnd, folder):
    """One row per T2 offset run: the behaviour its judge left standing, or undecided."""
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "t2-*ms", "verdict.json"))):
        m = _OFFSET.match(os.path.basename(os.path.dirname(path)))
        if not m:
            continue
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        rows.append({"round": rnd, "tool": m.group(1), "offset_ms": "%.4f" % v["offset_ms"],
                     "verdict": v["behaviour"] if v.get("decided") else UNDECIDED,
                     "standing": "; ".join(v.get("still_standing") or [])})
    return rows


def collect(collected, rounds=None):
    """Both tables, every round, from the folders the write-up names."""
    t1, t2 = [], []
    for rnd, runs, verdicts, read_again in (ROUNDS if rounds is None else rounds):
        again = {tool: os.path.join(collected, d, "t1-%s-step.json" % tool)
                 for tool, d in read_again.items()}
        t1 += t1_rows(rnd, os.path.join(collected, runs), again)
        t2 += t2_rows(rnd, os.path.join(collected, verdicts or runs))
    return t1, t2


def write(rows, fields, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fold the tools block's judged runs into tables")
    ap.add_argument("--collected", default=os.path.join("runs", "azure", "collected", "matched"))
    ap.add_argument("--out", default=os.path.join("docs", "results", "tools"))
    args = ap.parse_args(argv)
    t1, t2 = collect(args.collected)
    if not t1 or not t2:
        print("no judged tool runs under %s" % args.collected)
        return 1
    write(t1, T1_FIELDS, os.path.join(args.out, "tools_t1.csv"))
    write(t2, T2_FIELDS, os.path.join(args.out, "tools_t2.csv"))
    print("%d T1 rows and %d T2 rows from %d rounds"
          % (len(t1), len(t2), len({r["round"] for r in t1})))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
