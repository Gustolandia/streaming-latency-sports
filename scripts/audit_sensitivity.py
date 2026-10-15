#!/usr/bin/env python3
"""
audit_sensitivity.py -- the audit's headline count under each of its own classification choices.

The paper counts the message tools that cut a value at or below zero out of a figure they report:
the registry's silent disposals among the tools that time a message, and SBK, which cuts and counts.
Both referees of the ninth version asked that the count survive the choices behind it (A M5(c),
B M6(1)): a disposal made by a script or notebook the project ships rather than by the tool; one
the tool announces, with a printed line per value or a crash; a zero dropped where no value below
zero can arise (BookKeeper's benchmark); and a replacement made by the order of two calls in a tool
that never computes the span (Kafka's end-to-end tool). docs/results/external/disposal_modes.csv
marks each cutting tool, with where Table III or Supplement S5 says so. This counts the tools left
as each choice is undone in turn, and stops if the file and the registry disagree about which tools
cut.

CLI:
    python scripts/audit_sensitivity.py --modes docs/results/external/disposal_modes.csv \
        --out docs/results/external/audit_sensitivity.csv
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Each step leaves out one more kind of disposal, in the order the table prints them.
STEPS = (("as counted", None),
         ("less a zero dropped where no negative arises", "zero_only"),
         ("less a replacement made by the order of two calls", "order_only"),
         ("less a disposal by a script or notebook the project ships", "by_shipped_script"),
         ("less a disposal the tool announces or crashes on", "loud"))


def read_modes(path):
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for key in ("counted", "by_shipped_script", "loud", "zero_only", "order_only"):
            r[key] = r[key] == "True"
    return rows


def cutting_tools(summary, keep_counts):
    """The tools the paper counts as cutting: the registry's message tools that cut silently, and
    those that cut and count."""
    return sorted(set(summary["message_cut"]) | set(keep_counts))


def check(modes, summary, keep_counts):
    """Raise unless the file marks exactly the tools the registry counts as cutting."""
    marked = sorted(r["tool"] for r in modes)
    wanted = cutting_tools(summary, keep_counts)
    if marked != wanted:
        raise ValueError("disposal_modes.csv marks %s; the registry's cutting tools are %s"
                         % (marked, wanted))


def steps(modes, total):
    """[row per step]: the tools left, those of them that also leave the cut uncounted, out of
    the message tools."""
    out, left = [], list(modes)
    for name, flag in STEPS:
        if flag:
            left = [r for r in left if not r[flag]]
        out.append({"step": name, "cut": len(left),
                    "cut_uncounted": sum(1 for r in left if not r["counted"]),
                    "message_tools": total})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--modes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    import harness_registry
    import emit_paper_numbers as epn
    summary = harness_registry.summary()
    modes = read_modes(args.modes)
    check(modes, summary, epn.MESSAGE_KEEP_COUNTS)
    rows = steps(modes, len(summary["message_tools"]))
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print("OK %d of %d as counted, %d at the strictest -> %s"
          % (rows[0]["cut"], rows[0]["message_tools"], rows[-1]["cut"], args.out))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
