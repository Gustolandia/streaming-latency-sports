#!/usr/bin/env python3
"""
pubsub_post_hoc.py -- Google's Pub/Sub load test in freeze 38's block, read after its runs.

No plan registered this reading; it answers questions the runs raised, and the verdicts the frozen
programs gave stand beside it unchanged (scripts/block_v41.py, scripts/s1_block.py).

**Where its subscriber's values fell.** Its controller prints ranges rather than values, and under
T2's offsets it throws before printing any for its subscriber. Its driver logs every check
response from each client with the count the response carries in each bucket
(Client.java:232-236). Summed as its controller sums them, those counts show where the values
fell, and its own percentile search, run on them here, gives the bucket each printed range names.
Each run's search is held to what the run printed: the range, or the exception where bucket 0
alone holds the percentile's share. A run where the two disagree stops this reading.

**What its stepped runs counted.** Its controller adds a response's counts only where the running
duration the client reports is longer than the burn-in (Client.java:246-250), and the client times
that duration on its wall clock from a start given on the same clock. Under S1's steps that clock
runs about a quarter slow, so each stepped run's first burst arrived with its duration still below
zero, and its controller counted two of the five bursts where its controls counted three. The
reader that ran on the pair took a duration below zero for one past the burn-in; read again with
that corrected, the counts every run kept sum to the count its controller printed.

**Why S1-l failed in one round.** Its median is searched again over the counts outside bucket 0,
where the steps put the values they made below zero: a stepped run whose median stays where it was
without them was moved by the service, not by the steps.

    python3 scripts/pubsub_post_hoc.py --root runs/azure/collected/matched-b/v41_<stamp>/x/runs/azure \\
        --out docs/results/tools/pubsub_runs.csv
"""
import argparse
import csv
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tool_readings  # noqa: E402

TOOL = "pubsub-loadtest"

#: Freeze 38's four rounds, by the folder each ran in under the block's root.
ROUNDS = (("1", "tools_v41"), ("2", "tools_v41_round2"), ("3", "tools_v41_round3"),
          ("4", "tools_v41_round4"))

FIELDS = ("round", "stage", "run", "printed_p50_low", "printed_p50_high", "kept", "counted",
          "bucket0", "low_bucket", "high_bucket", "median_bucket", "median_throws",
          "median_bucket_without_0", "burn_in_counted", "first_burst_s", "set_aside", "thrown")

#: A run's folder, as tools.sh names it: the stage, the tool, and what the run was, where the
#: stage has more than one (T4's one run has none).
_RUN = re.compile(r"(t1|t2|t3|t4|s1)-%s(?:-(.+))?$" % re.escape(TOOL))

#: How close a bound computed here must lie to the one printed: its JVM's Math.pow(1.5, 16) gives
#: 656.8408355712891, where 1.5^16 is 656.8408203125.
REL_TOL = 1e-6


def controller_bucket(counts, percentile):
    """The bucket its controller reads a percentile from (LatencyTracker.java:37-52): the highest
    bucket above 0 below which the counts fall short of floor(N p / 100), N their total; None where
    bucket 0 alone holds that many, where its search throws. No counts at all give bucket 0."""
    total = sum(counts)
    if total == 0:
        return 0
    share = int(total * percentile / 100.0)
    for i in range(len(counts) - 1, 0, -1):
        total -= counts[i]
        if total < share:
            return i
    return None


def _bound(index):
    """A bucket's bound as its controller prints it: 1.5 to the index, and 0 below bucket 0."""
    return 0.0 if index < 0 else 1.5 ** index


def _row(rnd, folder, text):
    """One run read again: where its subscriber's counted values fell, the bucket its controller's
    search gives, and the duration its first burst arrived with; the search held to what it printed."""
    m = _RUN.match(folder)
    reading = tool_readings.read_tool(TOOL, text)
    after = reading["buckets"].get("subscriber", [])
    burn_in = reading["buckets_burn_in"].get("subscriber", [])
    printed = reading["ranges"].get("subscriber", {}).get("p50")
    median = controller_bucket(after, 50.0)
    if printed:
        agrees = median is not None and all(
            math.isclose(_bound(at), shown, rel_tol=REL_TOL, abs_tol=0.0)
            for at, shown in ((median - 1, printed[0]), (median, printed[1])))
    else:
        agrees = median is None and reading["thrown"] > 0
    if not agrees:
        raise ValueError("%s/%s: its controller's search on its counts gives bucket %s, and it "
                         "printed %s" % (rnd, folder, median, printed or "nothing for its subscriber"))
    held = [i for i, n in enumerate(after) if n]
    firsts = [r["seconds"] for r in tool_readings.pubsub_responses(text)
              if r["side"] == "subscriber" and any(r["counts"])]
    return {"round": rnd, "stage": m.group(1), "run": m.group(2) or "ahead",
            "printed_p50_low": printed[0] if printed else "",
            "printed_p50_high": printed[1] if printed else "",
            "kept": "" if reading["kept"] is None else reading["kept"],
            "counted": sum(after), "bucket0": after[0] if after else 0,
            "low_bucket": min(held) if held else "", "high_bucket": max(held) if held else "",
            "median_bucket": "" if median is None else median, "median_throws": median is None,
            "median_bucket_without_0": controller_bucket([0] + after[1:], 50.0) if after else "",
            "burn_in_counted": sum(burn_in),
            "first_burst_s": "%.3f" % firsts[0] if firsts else "",
            "set_aside": "" if reading["set_aside"] is None else reading["set_aside"],
            "thrown": reading["thrown"]}


def runs(root, rounds=ROUNDS):
    """Every run of the block that left its printed output, round by round, in its folder's order,
    then the round's reference: the tool itself run at no offset, from which T2 took its offsets,
    its printed output kept beside its zero step's (D41-3)."""
    rows = []
    for rnd, folder in rounds:
        here = os.path.join(root, folder)
        if not os.path.isdir(here):
            continue
        for name in sorted(os.listdir(here)):
            path = os.path.join(here, name, "tool.txt")
            if _RUN.match(name) and os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    rows.append(_row(rnd, name, fh.read()))
        reference = os.path.join(here, "t1-%s-0ms" % TOOL, "reference.log")
        if os.path.isfile(reference):
            with open(reference, encoding="utf-8") as fh:
                rows.append(_row(rnd, "t1-%s-reference" % TOOL, fh.read()))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze 38's Pub/Sub load test, read after its runs")
    ap.add_argument("--root", required=True, help="freeze 38's runs/azure folder")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows = runs(args.root)
    if not rows:
        print("no Pub/Sub load test runs under %s" % args.root)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print("%d runs read again; each controller's search agrees with what it printed" % len(rows))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
