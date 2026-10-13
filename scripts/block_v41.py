#!/usr/bin/env python3
"""
block_v41.py -- the predictions freeze 38 fixed for Google's Pub/Sub load test beyond T1 to T4's
(D41-4).

Freeze 38 (plan version 41) runs Google's Cloud Pub/Sub load test framework, its driver in local
mode on the second x86 pair's driver against Google's own Pub/Sub, through T1 to T4 and S1. Besides
the answers every tool gets, it fixed from the framework's source what its own output would show:

  T2-l  at each T2 offset at least half of its subscriber's values fall in bucket 0, where 0, 1 and
        every value below zero land together (MetricsHandler.java:72-73), so its controller throws
        "Programming error: negative values appear in buckets." when it computes the subscriber's
        50th percentile (LatencyTracker.java:37-52), with no try around it (Driver.java:153,
        239-246): no subscriber percentile is printed, no output.csv is written, and the driver
        does not exit with status 0. Its control, at no offset, prints the subscriber's percentiles
        and writes output.csv, and the driver exits with status 0.
  T4-l  with the subscriber's clock one second ahead, every subscriber latency is raised by exactly
        1,000 ms, and the 50% range its controller prints for the subscriber lies wholly below
        1,000 ms: it labels bucket n [1.5^(n-1), 1.5^n), one bucket below the values in it
        (LatencyTracker.java:28-30, 54-59), so its upper bound is 1.5^17 = 985.3 ms for any trip
        under 478 ms.

Each holds if it holds in every round, as K1's and S1's are judged; a round that cannot judge it
leaves it undecided, with the rounds that could not.

    python3 scripts/block_v41.py --root runs/azure/collected/matched-b/v41_<stamp>/x/runs/azure \\
        --out docs/results/tools/v41.csv --verdicts docs/results/tools/v41_verdicts.json
"""
import argparse
import csv
import json
import os
import re
import sys

TOOL = "pubsub-loadtest"
#: T4-l's bound, ms: the second the subscriber's clock was set ahead by.
AHEAD_MS = 1000.0

FIELDS = ("round", "tool", "run", "offset_ms", "sub_p50_low", "sub_p50_high", "sub_p99_high",
          "pub_p50_low", "pub_p50_high", "thrown", "wrote_csv", "exit", "missing", "kept", "sent")

_OFFSET = re.compile(r"t2-(.+)-(\d+(?:_\d+)?)ms$")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def run_row(rnd, folder, run, offset_ms=""):
    reading = _load(os.path.join(folder, "reading.json")) or {}
    ranges = reading.get("ranges") or {}
    sub, pub = ranges.get("subscriber") or {}, ranges.get("publisher") or {}

    def cell(value):
        return "" if value is None else value

    def bound(side, key, at):
        printed = side.get(key)
        return "" if not printed else printed[at]

    return {"round": rnd, "tool": TOOL, "run": run, "offset_ms": offset_ms,
            "sub_p50_low": bound(sub, "p50", 0), "sub_p50_high": bound(sub, "p50", 1),
            "sub_p99_high": bound(sub, "p99", 1), "pub_p50_low": bound(pub, "p50", 0),
            "pub_p50_high": bound(pub, "p50", 1), "thrown": cell(reading.get("thrown")),
            "wrote_csv": cell(reading.get("wrote_csv")), "exit": cell(reading.get("exit")),
            "missing": cell(reading.get("missing")), "kept": cell(reading.get("kept")),
            "sent": cell(reading.get("sent"))}


def block_rows(root, rounds):
    """Every T2 run of the tool, round by round, its control then its offsets, then its T4 run with
    the subscriber's clock ahead."""
    rows = []
    for rnd, folder in rounds:
        base = os.path.join(root, folder)
        names = sorted(os.listdir(base)) if os.path.isdir(base) else []
        control = os.path.join(base, "t2-%s-control" % TOOL)
        if os.path.isdir(control):
            rows.append(run_row(rnd, control, "control"))
        for name in names:
            match = _OFFSET.fullmatch(name)
            if match and match.group(1) == TOOL:
                rows.append(run_row(rnd, os.path.join(base, name), "offset",
                                    match.group(2).replace("_", ".")))
        ahead = os.path.join(base, "t4-%s" % TOOL)
        if os.path.isdir(ahead):
            rows.append(run_row(rnd, ahead, "ahead", "-1000"))
    return rows


def holds_t2l(control, offsets):
    """None where a run lacks what T2-l reads; else whether it held in that round."""
    runs = [control] + offsets
    if not offsets or any(r["exit"] == "" or r["thrown"] == "" or r["wrote_csv"] == ""
                          for r in runs):
        return None
    printed = (control["sub_p50_high"] != "" and control["wrote_csv"] is True
               and int(control["exit"]) == 0)
    return printed and all(r["sub_p50_high"] == "" and int(r["thrown"]) >= 1
                           and r["wrote_csv"] is False and int(r["exit"]) != 0 for r in offsets)


def holds_t4l(ahead):
    """None where the run printed no subscriber range; else whether it lay wholly below a second."""
    if ahead["sub_p50_high"] == "":
        return None
    return float(ahead["sub_p50_high"]) < AHEAD_MS


def judge(rows, rounds):
    verdicts = {}
    for name in ("T2-l", "T4-l"):
        held, failed, unjudged = [], [], []
        for rnd in rounds:
            mine = [r for r in rows if r["round"] == rnd]
            if name == "T2-l":
                control = [r for r in mine if r["run"] == "control"]
                offsets = [r for r in mine if r["run"] == "offset"]
                ok = holds_t2l(control[0], offsets) if control else None
            else:
                ahead = [r for r in mine if r["run"] == "ahead"]
                ok = holds_t4l(ahead[0]) if ahead else None
            (unjudged if ok is None else held if ok else failed).append(rnd)
        verdict = "undecided" if unjudged else "fails" if failed else "holds"
        verdicts[name] = {"tool": TOOL, "verdict": verdict, "held_in_rounds": held,
                          "failed_in_rounds": failed, "not_judged_in_rounds": unjudged}
    return verdicts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the block's runs/azure folder")
    ap.add_argument("--rounds", default="1:tools_v41,2:tools_v41_round2,3:tools_v41_round3,"
                    "4:tools_v41_round4", help="round:folder, comma-separated")
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    rounds = [tuple(part.split(":", 1)) for part in args.rounds.split(",")]
    rows = block_rows(args.root, rounds)
    if not rows:
        print("no T2 or T4 runs of the Pub/Sub load test under %s" % args.root)
        return 1
    for path in (args.out, args.verdicts):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    verdicts = judge(rows, [rnd for rnd, _ in rounds])
    with open(args.verdicts, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for name, v in sorted(verdicts.items()):
        print("%-5s %-16s %s" % (name, v["tool"], v["verdict"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
