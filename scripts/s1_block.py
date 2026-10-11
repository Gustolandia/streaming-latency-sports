#!/usr/bin/env python3
"""
s1_block.py -- S1: what each tool does when the wall clock steps back while it runs (freeze 34).

T2 moves the clock of the process that subtracts by a constant offset, which cannot make a value
below zero in a tool that takes both of its readings in one process, or in two processes on one
machine reading one clock: both readings move together. A step of the clock between the two
readings can. S1 runs each such tool once as it is, the control, and once while
scripts/clock_stepper.py steps the machine's wall clock back every S1 period, chrony stopped
(cloud/azure/tools.sh, `s1`). A message in flight across a step is received at a reading earlier
than the one it left with, by the step less its trip: below zero whenever the step is longer
than the trip, and how many messages are caught is set by how many steps there are, how fast the
tool sends and how long each message is in flight.

Each tool's own figures say what it did with those values, and freeze 34 (D37-4) fixed, from each
one's source, what they would say:

  pkb                   keeps them: a sample below zero in its printed samples
  strimzi-canary        logs them: a duration below zero in its log
  stream-perftest-one   drops them, uncounted: fewer latencies kept than messages consumed
  xinfra-monitor        pins them to its percentiles' floor, which its metrics library says only
                        at debug level, read here from that line
  kafka-end-to-end      times with a monotonic clock, the control: its median and 99th
                        percentile within one printed step of its control's

and that none of them would say it in its control. Freeze 35 (D38-5) added three, each run with
--tools and folded beside the five:

  sbk                   counts them: "invalid latencies" at least one, its control's none
  mqtt-benchmark        never meets one, its clock monotonic: its minimum above zero in both runs,
                        and its mean within a millisecond of its control's
  sarama-producer-perf  never meets one, its clock monotonic: its median and 99th percentile
                        within one printed step of its control's, as Kafka's own tool's

and freeze 36 (D39-5) one:

  artemis-perf          its producer stops: in its stepped run it sends fewer messages than it
                        was asked to and its summary still reads success, a step inside one of its
                        own timed sends making a value its histogram refuses in a thread that
                        catches only JMS exceptions; in its control it sends them all. Prompted by
                        the pilot, and judged on new rounds (D39-5). Its consumer's AMQ132001
                        warnings are its count, shown beside it

A stepped run is judged only if its steps were made and the clock was put back (S1-a); each
prediction holds if it holds in every round.

    python3 scripts/s1_block.py --root runs/azure/collected/matched/v37_<stamp>/x/runs/azure \\
        --out docs/results/tools/s1.csv --verdicts docs/results/tools/s1_verdicts.json
"""
import argparse
import csv
import json
import os
import sys

#: What each tool's stepped run is predicted to show and its control not to (D37-4), by the
#: number this reads from the run's reading: a count of values below zero it reports or logs.
TOOLS = ("pkb", "strimzi-canary", "stream-perftest-one", "xinfra-monitor", "kafka-end-to-end")
#: Freeze 35's three (D38-5).
TOOLS_V38 = ("sbk", "mqtt-benchmark", "sarama-producer-perf")
#: Freeze 36's one (D39-5): Artemis's perf client, judged by its producer stopping short; its
#: consumer's AMQ132001 warnings, a value below zero refused for each, are its count.
TOOLS_V39 = ("artemis-perf",)
#: The tools on a monotonic clock, judged by their figures staying where their control's were,
#: within one printed step (D37-4, D38-5).
STEADY = ("kafka-end-to-end", "sarama-producer-perf")

#: How far, in ms, the put-back clock may sit from the hypervisor's PTP clock (S1-a), and how far
#: one step may land from the step asked for.
CLOCK_BACK_MS = 5.0
STEP_SLACK_MS = 5.0

FIELDS = ("round", "tool", "run", "steps", "stepped_back_ms", "clock_after_ms", "instrument_ok",
          "below_zero", "p50", "p99", "kept", "received", "avg", "min", "sent", "asked",
          "producer_result")


def _asked(folder):
    """What the run was asked to send, as tools_run.sh writes it beside the run; "" where absent."""
    try:
        with open(os.path.join(folder, "asked_to_send.txt"), encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return ""


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _clock_ms(path):
    """The clock's offset from the PTP clock, in ms, as clock_step.py's `measure` prints it: a
    bare number on its last line. None where it was not measured."""
    try:
        with open(path, encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        return float(lines[-1])
    except (OSError, ValueError, IndexError):
        return None


def steps_made(path):
    """The steps written down: how many, how far back in all, and whether each landed within
    STEP_SLACK_MS of the step asked for. (0, 0.0, False) where there is no log."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return 0, 0.0, False
    back, landed = 0.0, bool(rows)
    for r in rows:
        asked = int(r["step_ns"]) * (-1 if r["direction"] == "back" else 1)
        moved = int(r["wall_after_ns"]) - int(r["wall_before_ns"])
        landed = landed and abs(moved - asked) <= STEP_SLACK_MS * 1e6
        if r["direction"] == "back":
            back += int(r["step_ns"]) / 1e6
    return len(rows), back, landed


def below_zero(tool, reading):
    """How many values below zero the tool's own output shows, as its prediction reads it; None
    where the reading does not carry the number (the control tool, or a run that reported none).
    """
    if not reading:
        return None
    if tool == "pkb":
        samples = reading.get("samples_ms")
        return None if samples is None else sum(1 for s in samples if s < 0)
    if tool == "strimzi-canary":
        return reading.get("logged_negative")
    if tool == "stream-perftest-one":
        kept, got = reading.get("kept"), reading.get("received")
        return None if kept is None or got is None else got - kept
    if tool == "xinfra-monitor":
        pinned = reading.get("pinned_below_ms")
        return None if pinned is None else len(pinned)
    if tool == "sbk":
        return reading.get("invalid")
    if tool == "artemis-perf":
        return reading.get("refused")
    return None


def run_row(rnd, tool, folder, run):
    reading = _load(os.path.join(folder, "reading.json")) or {}
    figures = reading.get("reported_ms") or {}
    row = {"round": rnd, "tool": tool, "run": run, "steps": "", "stepped_back_ms": "",
           "clock_after_ms": "", "instrument_ok": "", "below_zero": "",
           "p50": figures.get("p50", ""), "p99": figures.get("p99", ""),
           "kept": "" if reading.get("kept") is None else reading["kept"],
           "received": "" if reading.get("received") is None else reading["received"],
           "avg": figures.get("avg", ""), "min": figures.get("min", ""),
           "sent": "" if reading.get("producer_sent") is None else reading["producer_sent"],
           "asked": _asked(folder), "producer_result": reading.get("producer_result") or ""}
    found = below_zero(tool, reading)
    if found is not None:
        row["below_zero"] = found
    if run == "stepped":
        n, back, landed = steps_made(os.path.join(folder, "steps.csv"))
        after = _clock_ms(os.path.join(folder, "clock_after.json"))
        row.update({"steps": n, "stepped_back_ms": "%.1f" % back,
                    "clock_after_ms": "" if after is None else "%.3f" % after,
                    "instrument_ok": bool(n and landed and after is not None
                                          and abs(after) <= CLOCK_BACK_MS)})
    return row


def block_rows(root, rounds, tools=TOOLS):
    rows = []
    for rnd, folder in rounds:
        for tool in tools:
            for run in ("control", "stepped"):
                path = os.path.join(root, folder, "s1-%s-%s" % (tool, run))
                if os.path.isdir(path):
                    rows.append(run_row(rnd, tool, path, run))
    return rows


def _num(value):
    return None if value in ("", None) else float(value)


def judge(rows, rounds, tools=TOOLS):
    """Each prediction of D37-4 and D38-5, round by round, as K1's are judged
    (kafka_clamp.verdicts): it holds or fails only where every round was judged, holding if it
    held in all of them, and is otherwise undecided, with the rounds that were not."""
    by = {(r["round"], r["tool"], r["run"]): r for r in rows}
    found = {}
    for tool in tools:
        held, failed, unjudged = [], [], []
        for rnd in rounds:
            control, stepped = by.get((rnd, tool, "control")), by.get((rnd, tool, "stepped"))
            if not control or not stepped or stepped["instrument_ok"] is not True:
                unjudged.append(rnd)
                continue
            if tool in STEADY:
                pairs = [(_num(stepped[f]), _num(control[f])) for f in ("p50", "p99")]
                if any(a is None or b is None for a, b in pairs):
                    unjudged.append(rnd)
                    continue
                ok = all(abs(a - b) <= 1.0 for a, b in pairs)
            elif tool == "artemis-perf":
                if "" in (stepped["sent"], stepped["asked"], control["sent"], control["asked"]):
                    unjudged.append(rnd)
                    continue
                ok = (int(stepped["sent"]) < int(stepped["asked"])
                      and stepped["producer_result"] == "success"
                      and int(control["sent"]) == int(control["asked"]))
            elif tool == "mqtt-benchmark":
                lows = (_num(stepped["min"]), _num(control["min"]))
                means = (_num(stepped["avg"]), _num(control["avg"]))
                if None in lows or None in means:
                    unjudged.append(rnd)
                    continue
                ok = min(lows) > 0 and abs(means[0] - means[1]) <= 1.0
            else:
                if stepped["below_zero"] == "" or control["below_zero"] == "":
                    unjudged.append(rnd)
                    continue
                ok = int(stepped["below_zero"]) >= 1 and int(control["below_zero"]) == 0
            (held if ok else failed).append(rnd)
        verdict = "undecided" if unjudged else "fails" if failed else "holds"
        found[tool] = {"verdict": verdict, "held_in_rounds": held, "failed_in_rounds": failed,
                       "not_judged_in_rounds": unjudged}
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the block's runs/azure folder")
    ap.add_argument("--rounds", default="1:tools_v37,2:tools_v37_round2,3:tools_v37_round3,"
                    "4:tools_v37_round4", help="round:folder, comma-separated")
    ap.add_argument("--tools", default=",".join(TOOLS),
                    help="the block's tools, comma-separated: freeze 34's five unless named")
    ap.add_argument("--out", required=True)
    ap.add_argument("--verdicts", required=True)
    args = ap.parse_args(argv)
    rounds = [tuple(part.split(":", 1)) for part in args.rounds.split(",")]
    tools = tuple(args.tools.split(","))
    unknown = sorted(set(tools) - set(TOOLS + TOOLS_V38 + TOOLS_V39))
    if unknown:
        print("no S1 prediction for %s" % ", ".join(unknown))
        return 2
    rows = block_rows(args.root, rounds, tools)
    if not rows:
        print("no S1 runs under %s" % args.root)
        return 1
    for path in (args.out, args.verdicts):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    verdicts = judge(rows, [rnd for rnd, _ in rounds], tools)
    with open(args.verdicts, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(verdicts, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for tool, v in verdicts.items():
        print("%-20s %s" % (tool, v["verdict"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
