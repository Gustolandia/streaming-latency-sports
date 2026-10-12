#!/usr/bin/env python3
"""
rocketmq_post_hoc.py -- RocketMQ's benchmark in freeze 36's block, read after its runs.

No plan registered this reading; it answers a question the runs raised, and the verdicts the frozen
programs gave stand beside it unchanged. Freeze 36 predicted that RocketMQ's B2C average would
follow T1's staircase at 0.5 to 1.5 ms per millisecond added (D39-4). In every round it did not:
its slopes ran from under two to thousands.

**Some runs waited in the broker.** The benchmark's Producer has no rate of its own: one thread
sends and waits for each reply, so it sends its 3,000 messages in about three seconds. Its Consumer
starts ten seconds earlier, on a topic made for the run, and is given the topic's queue only when
its client next balances its queues, which it does every 20 s (RebalanceService.java:25-27 at
5.5.1). A run whose Producer finished before
that held every message in the broker until then, and its consumer then took them all at once. Its
B2C, the consumer's clock less the producer's stamp, and its S2C, the consumer's clock less the
time the broker stored the message, are then both the time the message waited after the broker
stored it, and so equal. A run is read here as having waited where its B2C average passes LATE_MS:
the slowest run that did not wait averaged under 6 ms, and the runs that did, seconds.

**The others still rose by about two crossings.** Over the steps that did not wait, B2C rose by
about two milliseconds per millisecond added, and so did S2C, which leaves the producer out. The
consumer pulls: it asks the broker for messages and asks again when the answer arrives, the answer
crossing the delay. A message stored just after an answer has left waits for the next request,
which comes only after that answer has crossed, and then crosses itself.

    python3 scripts/rocketmq_post_hoc.py --root runs/azure/collected/matched-b/v39_<stamp>/x/runs/azure \\
        --runs docs/results/tools/rocketmq_waits.csv --slopes docs/results/tools/rocketmq_t1.csv
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tool_readings  # noqa: E402

TOOL = "rocketmq-benchmark"

#: A run whose B2C average passes this waited in the broker for its queue, ms.
LATE_MS = 100.0

#: Freeze 36's four rounds, by the folder each ran in under the block's root.
ROUNDS = (("1", "tools_v39"), ("2", "tools_v39_round2"), ("3", "tools_v39_round3"),
          ("4", "tools_v39_round4"))

RUN_FIELDS = ("round", "stage", "run", "added_ms", "b2c_avg_ms", "s2c_avg_ms", "max_ms", "reports",
              "sent", "waited")
SLOPE_FIELDS = ("round", "steps", "waited", "slope_all", "slope_b2c", "slope_s2c")

_STEP = re.compile(r"t1-%s-(\d+)_?(\d*)ms$" % re.escape(TOOL))


def _row(rnd, stage, run, reading, added=""):
    figures = reading.get("reported_ms") or {}
    b2c, s2c = figures.get("avg"), reading.get("s2c_avg_ms")

    def cell(value):
        return "" if value is None else value

    return {"round": rnd, "stage": stage, "run": run, "added_ms": added, "b2c_avg_ms": cell(b2c),
            "s2c_avg_ms": cell(s2c), "max_ms": cell(figures.get("max")),
            "reports": cell(reading.get("reports")), "sent": cell(reading.get("sent")),
            "waited": "" if b2c is None else b2c > LATE_MS}


def runs(root, rounds=ROUNDS):
    """Every run of the tool with a reading, each round's reference run among them: the stage, its
    added delay where it is a T1 step, its B2C and S2C averages, and whether it waited."""
    rows = []
    for rnd, folder in rounds:
        base = os.path.join(root, folder)
        for path in sorted(glob.glob(os.path.join(base, "t*-%s*" % TOOL, "reading.json"))):
            run = os.path.basename(os.path.dirname(path))
            with open(path, encoding="utf-8") as fh:
                reading = json.load(fh)
            step = _STEP.fullmatch(run)
            added = "%s.%s" % (step.group(1), step.group(2) or "0") if step else ""
            rows.append(_row(rnd, run.split("-", 1)[0], run, reading, added))
        reference = os.path.join(base, "t1-%s-0ms" % TOOL, "reference.log")
        if os.path.isfile(reference):
            with open(reference, encoding="utf-8", errors="replace") as fh:
                reading = tool_readings.read_tool(TOOL, fh.read())
            rows.append(_row(rnd, "reference", "t1-%s-0ms/reference_tool" % TOOL, reading))
    return rows


def _slope(points):
    """The least-squares slope of (added, figure) points, as T1 takes it; None with too few."""
    staircase = [(added, {"reported_ms": {"avg": figure}}) for added, figure in points]
    return tool_readings.slope_against_delay(staircase, TOOL)["slope"]


def slopes(rows):
    """Each round's staircase three ways: B2C over every step, as T1 read it; B2C over the steps
    that did not wait; and S2C over the same steps."""
    found = []
    for rnd in sorted({r["round"] for r in rows}):
        steps = [r for r in rows if r["round"] == rnd and r["stage"] == "t1" and r["b2c_avg_ms"] != ""]
        clean = [r for r in steps if not r["waited"]]
        found.append({
            "round": rnd, "steps": len(steps), "waited": len(steps) - len(clean),
            "slope_all": _slope([(float(r["added_ms"]), r["b2c_avg_ms"]) for r in steps]),
            "slope_b2c": _slope([(float(r["added_ms"]), r["b2c_avg_ms"]) for r in clean]),
            "slope_s2c": _slope([(float(r["added_ms"]), r["s2c_avg_ms"]) for r in clean
                                 if r["s2c_avg_ms"] != ""])})
    return found


def _write(rows, fields, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row[k] is None else "%.4f" % row[k] if isinstance(row[k], float)
                            else row[k]) for k in fields})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="freeze 36's runs/azure folder")
    ap.add_argument("--runs", required=True)
    ap.add_argument("--slopes", required=True)
    args = ap.parse_args(argv)
    found = runs(args.root)
    if not found:
        print("no runs of %s under %s" % (TOOL, args.root))
        return 1
    _write(found, RUN_FIELDS, args.runs)
    table = slopes(found)
    _write(table, SLOPE_FIELDS, args.slopes)
    waited = [r for r in found if r["waited"] is True]
    print("%d runs, %d waited in the broker" % (len(found), len(waited)))
    for r in table:
        print("round %s: %d steps, %d waited; slope %s over all, %s over the rest, %s by S2C" % (
            r["round"], r["steps"], r["waited"], r["slope_all"], r["slope_b2c"], r["slope_s2c"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
