#!/usr/bin/env python3
"""
block_v40.py -- the prediction freeze 37 fixed for Quiver beyond T1 to T4's (D40-4).

Freeze 37 (plan version 40) runs Quiver and the Pravega benchmark through T1 to T4 on the second x86
pair. Besides the answers every tool gets, it fixed from Quiver's source what its own output would
show when T2 moves its receiving arrow's clock:

  T2-q  quiver   at each T2 offset the transfers its receiver writes hold differences below zero, and
                 its summary's maximum and its average each exceed 10^18 ms, its wrapper subtracting
                 in unsigned 64-bit integers (arrow.py:264-265, 301), so that each value below zero
                 becomes 2^64 less its size; its control's transfers hold none below zero, and
                 neither its maximum nor its average reaches 10^18 ms: nothing in it wrapped

It holds if it holds in every round, as K1's and S1's are judged; a round that cannot judge it leaves
it undecided, with the rounds that could not. The Pravega benchmark's T2, on one clock, is judged with
every tool's (tools_block.py); its runs are written beside Quiver's, judged by nothing here, because
the supplement says what its figures and its count did there, and a sentence that quotes them
quotes this table (added at the fold, after the runs).

    python3 scripts/block_v40.py --root runs/azure/collected/matched-b/v40_<stamp>/x/runs/azure \\
        --out docs/results/tools/v40.csv --verdicts docs/results/tools/v40_verdicts.json
"""
import argparse
import csv
import json
import os
import re
import sys

#: T2-q's bound, ms: a figure past it is one the unsigned subtraction wrapped. The design held the
#: control under 1,000 ms; in two staircase runs of the third pilot of 12 October nothing reached
#: the receiver for up to 17 s, after which what had been held arrived at once, so a control can
#: reach seconds with nothing below zero, and the control is held only under the wrap (D40-4).
WRAPPED_MS = 1e18

FIELDS = ("round", "tool", "run", "offset_ms", "sent", "received", "below_zero", "avg", "p50", "max",
          "wrapped", "kept")

#: The tools whose T2 runs are written here: Quiver, judged by T2-q, and the Pravega benchmark,
#: described.
TOOLS = ("quiver", "pravega-benchmark")

_OFFSET = re.compile(r"t2-(.+)-(\d+(?:_\d+)?)ms$")


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def run_row(rnd, folder, run, offset_ms="", tool="quiver"):
    reading = _load(os.path.join(folder, "reading.json")) or {}
    figures = reading.get("reported_ms") or {}

    def cell(value):
        return "" if value is None else value

    return {"round": rnd, "tool": tool, "run": run, "offset_ms": offset_ms,
            "sent": cell(reading.get("sent")), "received": cell(reading.get("received")),
            "below_zero": cell(reading.get("below_zero")), "avg": cell(figures.get("avg")),
            "p50": cell(figures.get("p50")), "max": cell(figures.get("max")),
            "wrapped": "+".join(reading.get("wrapped") or []), "kept": cell(reading.get("kept"))}


def block_rows(root, rounds):
    """Every T2 run of each tool here, round by round: its control, then its offsets."""
    rows = []
    for rnd, folder in rounds:
        base = os.path.join(root, folder)
        names = sorted(os.listdir(base)) if os.path.isdir(base) else []
        for tool in TOOLS:
            control = os.path.join(base, "t2-%s-control" % tool)
            if os.path.isdir(control):
                rows.append(run_row(rnd, control, "control", tool=tool))
            for name in names:
                match = _OFFSET.fullmatch(name)
                if match and match.group(1) == tool:
                    rows.append(run_row(rnd, os.path.join(base, name), "offset",
                                        match.group(2).replace("_", "."), tool=tool))
    return rows


def _num(value):
    return None if value in ("", None) else float(value)


def holds_t2q(control, offsets):
    """None where a run lacks what T2-q reads; else whether it held in that round."""
    runs = [control] + offsets
    if not offsets or any(r["below_zero"] == "" or _num(r["max"]) is None or _num(r["avg"]) is None
                          for r in runs):
        return None
    quiet = (int(control["below_zero"]) == 0 and _num(control["max"]) < WRAPPED_MS
             and _num(control["avg"]) < WRAPPED_MS)
    return quiet and all(int(r["below_zero"]) >= 1 and _num(r["max"]) > WRAPPED_MS
                         and _num(r["avg"]) > WRAPPED_MS for r in offsets)


def judge(rows, rounds):
    held, failed, unjudged = [], [], []
    for rnd in rounds:
        mine = [r for r in rows if r["round"] == rnd and r["tool"] == "quiver"]
        control = [r for r in mine if r["run"] == "control"]
        offsets = [r for r in mine if r["run"] == "offset"]
        ok = holds_t2q(control[0], offsets) if control else None
        (unjudged if ok is None else held if ok else failed).append(rnd)
    verdict = "undecided" if unjudged else "fails" if failed else "holds"
    return {"T2-q": {"tool": "quiver", "verdict": verdict, "held_in_rounds": held,
                     "failed_in_rounds": failed, "not_judged_in_rounds": unjudged}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the block's runs/azure folder")
    ap.add_argument("--rounds", default="1:tools_v40,2:tools_v40_round2,3:tools_v40_round3,"
                    "4:tools_v40_round4", help="round:folder, comma-separated")
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    rounds = [tuple(part.split(":", 1)) for part in args.rounds.split(",")]
    rows = block_rows(args.root, rounds)
    if not rows:
        print("no T2 runs of Quiver under %s" % args.root)
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
        print("%-5s %-8s %s" % (name, v["tool"], v["verdict"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
