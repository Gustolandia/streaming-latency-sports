#!/usr/bin/env python3
"""Is `trimodal` a property of the stalls, or of `bpftrace`'s log2 buckets?

A mode count read off a histogram is a joint property of the data and the bin edges, and this
paper of all papers has to say which it is reporting: Section~VI's whole argument is that a
millisecond quantum decides what a benchmark prints and nobody discloses it. Figure~3 reports
local maxima of a bucketed histogram as a property of the scheduler, and the bucket width came
from the tool exactly as the quantum did.

The per-event stall durations were not retained --- `runqlat.txt` is a 27-line summary --- so
the usual answer, rebin the raw data and look again, is not available and never will be. What
*is* available is coarsening. Merging adjacent log2 buckets gives log4 buckets, and the merge
can be phased two ways: pairing from the first bucket or from the second. If the mode count
survives both phasings, the modes are separated by more than one bucket and are not an artifact
of where the tool happened to put its edges. If it does not, the claim was resolution-limited
and has to be stated that way.

This is not as good as rebinning raw data. It is what the archived data supports, and it
answers the part of the objection that can be answered: **a mode that survives a doubling of
the bin width in either phase is not sitting in a single bucket by luck.**

Run by hand; the output is committed and `emit_paper_numbers.py` reads it, so a build needs no
trace files. Same contract as `check_fork_exposure.py` and `literature_census.py`.
"""
import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE = os.path.join(REPO, "docs", "results", "depth", "ea9", "l88_base", "runqlat.txt")
OUT = os.path.join(REPO, "docs", "results", "external", "stall_mode_robustness.json")

#: `[2, 4)   110184` and `[1]   54682` and `[512, 1K)  13160`.
ROW = re.compile(r"^\[(\d+[KM]?)(?:,\s*(\d+[KM]?))?\)?\]?\s+(\d+)\s*\|", re.M)


def _us(token):
    mult = {"K": 1024, "M": 1024 * 1024}.get(token[-1:], 1)
    return int(token.rstrip("KM")) * mult


def read_histogram(path=TRACE):
    """[(low_us, count)], in bucket order, from bpftrace's log2 output."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    bins = [(_us(m.group(1)), int(m.group(3))) for m in ROW.finditer(text)]
    if not bins:                                       
        raise ValueError("no log2 buckets found in %s" % path)
    return bins


def local_maxima(counts):
    """Indices strictly greater than both neighbours; edges compare against one side."""
    out = []
    for i, c in enumerate(counts):
        left = counts[i - 1] if i else None
        right = counts[i + 1] if i + 1 < len(counts) else None
        if (left is None or c > left) and (right is None or c > right):
            out.append(i)
    return out


def coarsen(bins, factor, phase):
    """Merge `factor` adjacent buckets, starting `phase` buckets in.

    Phase is what makes this a test rather than a restatement: pairing from the first bucket
    and pairing from the second put the edges in different places, and a mode that survives
    both is not an artifact of either.
    """
    head = bins[:phase]
    rest = bins[phase:]
    merged = [(head[0][0], sum(c for _, c in head))] if head else []
    for i in range(0, len(rest), factor):
        group = rest[i:i + factor]
        merged.append((group[0][0], sum(c for _, c in group)))
    return merged


def report(path=TRACE):
    bins = read_histogram(path)
    counts = [c for _, c in bins]
    base = local_maxima(counts)
    out = {
        "source": os.path.relpath(path, REPO).replace("\\", "/"),
        "events": sum(counts),
        "buckets": len(bins),
        "base_modes": len(base),
        "base_mode_lows_us": [bins[i][0] for i in base],
        "coarsenings": [],
    }
    for factor in (2, 4):
        for phase in range(factor):
            merged = coarsen(bins, factor, phase)
            m = local_maxima([c for _, c in merged])
            out["coarsenings"].append({
                "factor": factor,
                "phase": phase,
                "buckets": len(merged),
                "modes": len(m),
                "mode_lows_us": [merged[i][0] for i in m],
                "agrees": len(m) == out["base_modes"],
            })
    two = [c for c in out["coarsenings"] if c["factor"] == 2]
    out["survives_doubling"] = all(c["agrees"] for c in two)
    out["doubling_phases"] = len(two)
    four = [c for c in out["coarsenings"] if c["factor"] == 4]
    out["survives_quadrupling"] = all(c["agrees"] for c in four)
    # The width at which the structure is still resolved, in octaves of bin width.
    out["resolved_to_octaves"] = 1 if out["survives_doubling"] else 0
    if out["survives_quadrupling"]:                    
        out["resolved_to_octaves"] = 2
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed record matches the trace, and change nothing")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    got = report()
    if args.check:
        if not os.path.exists(args.out):
            print("no committed record at %s" % args.out)
            return 1
        with open(args.out, encoding="utf-8") as fh:
            have = json.load(fh)
        if have != got:
            print("the committed record disagrees with the trace")
            return 1
        print("the committed record agrees with the trace")
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(got, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("%d buckets, %d modes on the tool's own binning" % (got["buckets"], got["base_modes"]))
    for c in got["coarsenings"]:
        print("  x%d phase %d -> %d buckets, %d modes at %s  %s"
              % (c["factor"], c["phase"], c["buckets"], c["modes"],
                 c["mode_lows_us"], "agrees" if c["agrees"] else "DIFFERS"))
    print("survives doubling: %s; survives quadrupling: %s"
          % (got["survives_doubling"], got["survives_quadrupling"]))
    return 0


if __name__ == "__main__":                              # pragma: no cover - entry point
    sys.exit(main())
