#!/usr/bin/env python3
"""
block_v39.py -- the predictions freeze 36 fixed for its three tools beyond T1 to T4's (D39-4).

Freeze 36 (plan version 39) runs Artemis's perf client, RocketMQ's benchmark and BookKeeper's
benchmark through T1 to T4 on the second x86 pair. Besides the answers every tool gets, it fixed
from each one's source what that tool's own output would show:

  T2-a  artemis-perf          at each T2 offset it refuses a value below zero with AMQ132001 at
                              least once and receives more messages than were sent, each refused
                              delivery being rolled back and delivered again, and its summary still
                              reads success; its control logs no AMQ132001 and receives no more
                              than were sent
  T2-r  rocketmq-benchmark    at each T2 offset its B2C average falls by more than half the offset
                              from its control's; its maximum, which starts at 0 and rises only past
                              it, is reported beside it and not judged (a draft clause holding it at
                              0 was dropped after the pilot printed 11 beside an average of -3.09)
  T4-b  bookkeeper-benchmark  its median, from its own latency dump, is above 15 ms at 50 entries a
                              second: each latency carries the wait for its own rate limiter's permit

Each holds if it holds in every round, as K1's and S1's are judged; a round that cannot judge it
leaves it undecided, with the rounds that could not.

    python3 scripts/block_v39.py --root runs/azure/collected/matched-b/v39_<stamp>/x/runs/azure \\
        --out docs/results/tools/v39.csv --verdicts docs/results/tools/v39_verdicts.json
"""
import argparse
import csv
import json
import os
import re
import sys

#: T4-b's threshold, ms: a fiftieth of a second, less what the loop between two calls can take.
T4B_FLOOR_MS = 15.0

FIELDS = ("round", "tool", "run", "offset_ms", "sent", "received", "kept", "refused", "result",
          "avg", "p50", "max", "negative_reports", "zero_max_on_negative")

_OFFSET = re.compile(r"t2-(.+)-(\d+(?:_\d+)?)ms$")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _sent(folder):
    try:
        with open(os.path.join(folder, "asked_to_send.txt"), encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def run_row(rnd, tool, folder, run, offset_ms=""):
    reading = _load(os.path.join(folder, "reading.json")) or {}
    figures = reading.get("reported_ms") or {}
    rows = reading.get("report_rows") or []
    negative = [r for r in rows if r[1] < 0]

    def cell(value):
        return "" if value is None else value

    return {"round": rnd, "tool": tool, "run": run, "offset_ms": offset_ms,
            "sent": cell(_sent(folder)), "received": cell(reading.get("received")),
            "kept": cell(reading.get("kept")), "refused": cell(reading.get("refused")),
            "result": cell(reading.get("result")), "avg": cell(figures.get("avg")),
            "p50": cell(figures.get("p50")), "max": cell(figures.get("max")),
            "negative_reports": len(negative) if reading else "",
            "zero_max_on_negative": (all(r[2] == 0 for r in negative) if negative else "")}


def block_rows(root, rounds):
    """Every T2 run of the two two-process tools, and BookKeeper's T4, round by round."""
    rows = []
    for rnd, folder in rounds:
        base = os.path.join(root, folder)
        names = sorted(os.listdir(base)) if os.path.isdir(base) else []
        for tool in ("artemis-perf", "rocketmq-benchmark"):
            control = os.path.join(base, "t2-%s-control" % tool)
            if os.path.isdir(control):
                rows.append(run_row(rnd, tool, control, "control"))
            for name in names:
                match = _OFFSET.fullmatch(name)
                if match and match.group(1) == tool:
                    rows.append(run_row(rnd, tool, os.path.join(base, name), "offset",
                                        match.group(2).replace("_", ".")))
        t4 = os.path.join(base, "t4-bookkeeper-benchmark")
        if os.path.isdir(t4):
            rows.append(run_row(rnd, "bookkeeper-benchmark", t4, "t4"))
    return rows


def _num(value):
    return None if value in ("", None) else float(value)


def holds_t2a(control, offsets):
    """None where a run lacks what T2-a reads; else whether it held in that round."""
    runs = [control] + offsets
    if not offsets or any(r["refused"] == "" or r["received"] == "" or r["sent"] == "" for r in runs):
        return None
    quiet = int(control["refused"]) == 0 and int(control["received"]) <= int(control["sent"])
    return quiet and all(int(r["refused"]) >= 1 and int(r["received"]) > int(r["sent"])
                         and r["result"] == "success" for r in offsets)


def holds_t2r(control, offsets):
    if not offsets or _num(control["avg"]) is None or any(_num(r["avg"]) is None for r in offsets):
        return None
    return all(_num(r["avg"]) <= _num(control["avg"]) - float(r["offset_ms"]) / 2.0 for r in offsets)


def holds_t4b(row):
    return None if _num(row["p50"]) is None else _num(row["p50"]) > T4B_FLOOR_MS


def judge(rows, rounds):
    found = {}
    for name, tool in (("T2-a", "artemis-perf"), ("T2-r", "rocketmq-benchmark"),
                       ("T4-b", "bookkeeper-benchmark")):
        held, failed, unjudged = [], [], []
        for rnd in rounds:
            mine = [r for r in rows if r["round"] == rnd and r["tool"] == tool]
            if name == "T4-b":
                t4 = [r for r in mine if r["run"] == "t4"]
                ok = holds_t4b(t4[0]) if t4 else None
            else:
                control = [r for r in mine if r["run"] == "control"]
                offsets = [r for r in mine if r["run"] == "offset"]
                rule = holds_t2a if name == "T2-a" else holds_t2r
                ok = rule(control[0], offsets) if control else None
            (unjudged if ok is None else held if ok else failed).append(rnd)
        verdict = "undecided" if unjudged else "fails" if failed else "holds"
        found[name] = {"tool": tool, "verdict": verdict, "held_in_rounds": held,
                       "failed_in_rounds": failed, "not_judged_in_rounds": unjudged}
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the block's runs/azure folder")
    ap.add_argument("--rounds", default="1:tools_v39,2:tools_v39_round2,3:tools_v39_round3,"
                    "4:tools_v39_round4", help="round:folder, comma-separated")
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    rounds = [tuple(part.split(":", 1)) for part in args.rounds.split(",")]
    rows = block_rows(args.root, rounds)
    if not rows:
        print("no runs of freeze 36's three under %s" % args.root)
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
        print("%-5s %-22s %s" % (name, v["tool"], v["verdict"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
