#!/usr/bin/env python3
"""
tools_block.py -- the tools block's judged results, folded into two committed tables.

The registered law campaign ran eleven benchmarking tools on the first x86 pair, four rounds
each (blocks T1 to T4, plan decision D3-1: "the tools block T1-T4 is in this paper"; the
write-up is docs/results/tools/t1-t4-eleven-tools.md), and a second block ran the five the plan
had registered and version 15 had left unrun, four rounds each on the same pair (freeze 30;
docs/results/tools/t1-t4-five-tools.md). Their raw runs stay outside git, in the
whole runs folders archived with the data record. What the paper says about them is a handful
of counts, and a count the paper prints has to be a fold over committed rows like every other
number in it. So this script reads the judged files the campaign left beside each run and
writes two small tables, which are committed:

  docs/results/tools/tools_t1.csv   round, tool, trip, figure, crossings, slope
  docs/results/tools/tools_t2.csv   round, tool, offset_ms, verdict, standing, sent, kept,
                                    verdict_31, clocks, clocks_why

T1 is the staircase: a known delay added to the path in ten steps, and the slope at which the
tool's figure follows it, on the figure the staircase was read from. T2 moves the clock the tool
reads back by more than its trip and asks what the tool does with the result: the verdict is
the one behaviour still standing, or "undecided" when more than one is.

Every T2 run is also judged again as freeze 31 says (D34-3), from the readings, controls,
reference trips, staircases, counts and measured shifts it left: `verdict_31` under the corrected
clause (D34-1), and `clocks` -- one, two or undecided -- with its reason, from the offset itself
(D34-2). `verdict` stays the verdict the run was given. Before either is written, the run is
judged again under freeze 21 from the same inputs and must give the verdict it was given, so a
reconstruction that does not reproduce the judgement stops the fold.

Which judged file stands for which round is the write-up's decision, not this script's:

  round 1     snapshot_20260925T002916Z. Its T2 verdicts as judged again under freeze 21 as
              written (t2_rejudged_20260925: the judge first held a tool's count against our
              reference instead of against what the tool was asked to send), and hey's
              staircase as read again (hey_reread_20260925: hey's percentiles had never been
              read, so its slope was taken on its average).
  rounds 2-4  snapshot_20260925T141523Z, tools_round2 to tools_round4, judged on the pair by
              the corrected programs.
  the five    v33_20261010T075920Z, tools_v33 and tools_v33_round2 to _round4, judged on the
              pair as each ran.

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
T2_FIELDS = ("round", "tool", "offset_ms", "verdict", "standing", "sent", "kept", "verdict_31",
             "clocks", "clocks_why")

#: What a T2 run was asked to send where it wrote no asked_to_send.txt: round 1 of the eleven ran
#: before D26-2 wrote one, and tools_run.sh's defaults, 50 a second for 60 s, were never
#: overridden -- the figure the round-1 judgement of 25 September was given.
SENT_DEFAULT = 3000

#: (round, folder of its runs, where its T2 verdicts are, staircases read again).
ROUNDS = (
    ("1", "snapshot_20260925T002916Z/runs/azure/tools", "t2_rejudged_20260925",
     {"hey": "hey_reread_20260925"}),
    ("2", "snapshot_20260925T141523Z/runs/azure/tools_round2", None, {}),
    ("3", "snapshot_20260925T141523Z/runs/azure/tools_round3", None, {}),
    ("4", "snapshot_20260925T141523Z/runs/azure/tools_round4", None, {}),
)

#: Freeze 30's block (D33-1): the five tools version 15 left unrun, judged on the pair as each ran.
ROUNDS_V33 = tuple(
    (rnd, "v33_20261010T075920Z/x/runs/azure/" + folder, None, {})
    for rnd, folder in (("1", "tools_v33"), ("2", "tools_v33_round2"), ("3", "tools_v33_round3"),
                        ("4", "tools_v33_round4")))

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
    # Freeze 30's five, as its addendum read their invocations before any of their runs (D33-5).
    "omb": "across two processes",
    "pulsar-perf": "across two processes",
    "emqtt-bench": "across two processes",
    "ycsb": "round trip",
    "nats-bench": "round trip",
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


def _load(path):
    """A JSON file, or None where the run left none."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _number(path, default):
    """The one number a file holds, or the default where the run left no such file."""
    if not os.path.isfile(path):
        return default
    with open(path, encoding="utf-8") as fh:
        return int(fh.read().strip())


def _named(verdict):
    return verdict["behaviour"] if verdict.get("decided") else UNDECIDED


def _recorded_call(path):
    """The judge's arguments as a run's re-judging recorded them in call.json, by flag.

    Round 1 of the eleven was judged again on 25 September by calls recorded beside each verdict
    (t2_rejudged_20260925), and those calls are what its verdicts came from. Paths are as the call
    wrote them, from the repository's root."""
    call = _load(path)
    if call is None:
        return None
    args = {}
    for flag, value in zip(call, call[1:]):
        if flag.startswith("--"):
            args[flag[2:]] = value.replace("\\", "/")
    return args


def rejudge(runs, tool, run, given, verdicts=None):
    """One T2 offset run judged again as freeze 31 says (D34-3), with the inputs tools.sh gave it.

    The inputs are read from the folders the run and its T1 staircase left: the reading, the
    control taken in the same session, our reference's trips from T1's zero step, the staircase
    for each figure's noise, the step T1 measured or the one the tool prints in, the offset
    measured at the clock, what the tool was asked to send and how it exited. The run is judged
    again under freeze 21 first and must give `given`, the verdict it was given; then under
    freeze 31's clause (D34-1), and its clocks are answered from the offset itself (D34-2).
    Returns the five columns, empty where the run left no reading to judge.
    """
    import tool_negatives
    path = os.path.join(runs, run)
    call = _recorded_call(os.path.join(verdicts, run, "call.json")) if verdicts else None
    if call is not None:
        reading, trips_path = _load(call["reading"]), call["reference"]
        control, plain = _load(call.get("control", "")), _load(call.get("plain", ""))
        step = float(call["step-ms"]) if "step-ms" in call else None
        shift = float(call["shift-ms"]) if "shift-ms" in call else None
        asked, sent = float(call["offset-ms"]), int(call["sent"]) if "sent" in call else None
        inputs = dict(sent=sent, exit_code=int(call.get("exit-code", 0)), plain=plain,
                      step_ms=step, control=control, shift_ms=shift,
                      noise=tool_negatives.noise_from_staircase(
                          tool_negatives.staircase(call["staircase"], call["tool"])))
    else:
        reading = _load(os.path.join(path, "reading.json"))
        trips_path = os.path.join(runs, "t1-%s-0ms" % tool, "reference_trips.json")
        control = _load(os.path.join(runs, "t2-%s-control" % tool, "reading.json"))
        plain = _load(os.path.join(runs, "t1-%s-0ms" % tool, "reading.json"))
        step = (_load(os.path.join(runs, "t1-%s-step.json" % tool)) or {}).get(
            "smallest_reported_ms") or (plain or {}).get("step_ms")
        shift = (_load(os.path.join(path, "offset_measured.json")) or {}).get("measured_ms")
        asked = float(_OFFSET.match(run).group(2).replace("_", "."))
        sent = _number(os.path.join(path, "asked_to_send.txt"), SENT_DEFAULT)
        inputs = dict(sent=sent, exit_code=_number(os.path.join(path, "exit_code.txt"), 0),
                      plain=plain, step_ms=step, control=control, shift_ms=shift,
                      noise=tool_negatives.noise_from_staircase(
                          tool_negatives.staircase(runs, tool)))
    if reading is None or not os.path.isfile(trips_path):
        return {"sent": "", "kept": "", "verdict_31": "", "clocks": "", "clocks_why": ""}
    trips = tool_negatives.reference_trips(trips_path)
    again = tool_negatives.what_it_did(reading, trips, asked, **inputs)
    if _named(again) != given:
        raise ValueError("%s judged again under freeze 21 gives %s, not the %s it was given; the "
                         "inputs are not the ones it was judged on" % (path, _named(again), given))
    corrected = tool_negatives.what_it_did(reading, trips, asked, rule=tool_negatives.FREEZE_31,
                                           **inputs)
    answer, why = tool_negatives.clocks(reading, control, shift or asked, sent=sent)
    kept = reading.get("kept")
    return {"sent": "" if sent is None else str(sent), "kept": "" if kept is None else str(kept),
            "verdict_31": _named(corrected), "clocks": answer, "clocks_why": why}


def t2_rows(rnd, folder, runs=None):
    """One row per T2 offset run: the behaviour its judge left standing, or undecided, and the
    same run judged again as freeze 31 says. `folder` holds the verdicts the rounds were given,
    `runs` the runs themselves, where they differ (round 1 of the eleven)."""
    rows = []
    for path in sorted(glob.glob(os.path.join(folder, "t2-*ms", "verdict.json"))):
        run = os.path.basename(os.path.dirname(path))
        m = _OFFSET.match(run)
        if not m:
            continue
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        row = {"round": rnd, "tool": m.group(1), "offset_ms": "%.4f" % v["offset_ms"],
               "verdict": _named(v), "standing": "; ".join(v.get("still_standing") or [])}
        row.update(rejudge(runs or folder, m.group(1), run, row["verdict"], folder))
        rows.append(row)
    return rows


def collect(collected, rounds=None):
    """Both tables, every round, from the folders the write-up names."""
    t1, t2 = [], []
    for rnd, runs, verdicts, read_again in (ROUNDS + ROUNDS_V33 if rounds is None else rounds):
        again = {tool: os.path.join(collected, d, "t1-%s-step.json" % tool)
                 for tool, d in read_again.items()}
        t1 += t1_rows(rnd, os.path.join(collected, runs), again)
        t2 += t2_rows(rnd, os.path.join(collected, verdicts or runs),
                      os.path.join(collected, runs))
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
