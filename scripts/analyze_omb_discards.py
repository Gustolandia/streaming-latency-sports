#!/usr/bin/env python3
"""
analyze_omb_discards.py
What does the OpenMessaging Benchmark actually discard, and does it match our failure mode?

Section 6.7 of the manuscript reported that an instrumented OMB "discarded 6,000 end-to-end
samples" under load and read that as the same causality violation our own harness produced. The
counter behind it did not distinguish sign. A sample of exactly 0 microseconds means publish and
receive landed in the same millisecond tick -- `record.timestamp()` is millisecond-resolution
under Kafka's CreateTime semantics -- and is a resolution artefact. A sample below zero is the
causality violation. Both fail OMB's `if (endToEndLatencyMicros > 0)` guard and both were counted
as one number.

This script reads the sign-separated sweep and decides between three readings, on evidence rather
than on which is more convenient:

  RESOLUTION   discards are overwhelmingly zeros, and their share FALLS as latency rises (with
               load, or with message size). OMB's defect is real and serious -- it reports a
               latency distribution computed from a small fraction of its samples -- but it is
               not the failure this paper is about, and Section 6.7 must say so.
  CAUSALITY    a material number of discards are negative, and they rise with load the way our
               own inversion rate does. The original claim stands, with the zeros separated out.
  BOTH         zeros dominate but negatives are present and load-dependent. The single counter
               was hiding the interesting failure behind the boring one.

CLI:
    python scripts/analyze_omb_discards.py --sweep docs/results/external/load_sweep/omb_load_sweep.csv
    python scripts/analyze_omb_discards.py --resolution docs/results/external/resolution/omb_resolution.csv
"""
import argparse
import csv
import os
import statistics as st

# A share of negatives below this is treated as absent rather than as a small positive signal:
# at these sample counts a handful of negatives is not distinguishable from a scheduling blip.
NEGATIVE_FLOOR = 0.001


def _num(row, key, default=0):
    try:
        return int(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def summarise(rows, axis):
    """Per level of `axis`: totals, the zero share, and the negative share."""
    by = {}
    for r in rows:
        key = r.get(axis)
        if key is None:
            continue
        zero, neg, kept = _num(r, "discarded_zero"), _num(r, "discarded_negative"), _num(r, "kept")
        seen = zero + neg + kept
        if not seen:
            continue
        by.setdefault(key, []).append({
            "zero": zero, "negative": neg, "kept": kept, "seen": seen,
            "zero_share": zero / seen, "neg_share": neg / seen,
            "kept_share": kept / seen,
            "most_negative": _num(r, "most_negative_micros"),
        })
    out = []
    def _sort_key(k):
        """Numeric levels in numeric order, anything else after them alphabetically.

        A plain `float(k) if numeric else k` compares float against str the moment a level is
        non-numeric, which raises rather than sorting. The leading flag keeps the two kinds apart.
        """
        text = str(k)
        try:
            return (0, float(text), "")
        except ValueError:
            return (1, 0.0, text)

    for key in sorted(by, key=_sort_key):
        cells = by[key]
        out.append({
            "level": key, "n": len(cells),
            "zero_share": st.median(c["zero_share"] for c in cells),
            "neg_share": st.median(c["neg_share"] for c in cells),
            "kept_share": st.median(c["kept_share"] for c in cells),
            "negatives": sum(c["negative"] for c in cells),
            "most_negative": min((c["most_negative"] for c in cells), default=0),
        })
    return out


def verdict(summary):
    """Which reading the data support. Undecided is a permitted answer."""
    if len(summary) < 2:
        return {"decided": False, "why": "need at least two levels to see a direction"}
    neg_total = sum(s["negatives"] for s in summary)
    max_neg_share = max(s["neg_share"] for s in summary)
    zero_first, zero_last = summary[0]["zero_share"], summary[-1]["zero_share"]
    # Does the zero share fall as the axis rises? That is the resolution signature.
    zero_falls = zero_last < zero_first - 0.05

    if max_neg_share < NEGATIVE_FLOOR:
        outcome = "RESOLUTION" if zero_falls else "RESOLUTION (direction untested)"
        why = (f"no level shows more than {NEGATIVE_FLOOR:.1%} negative samples; "
               f"{neg_total} negatives in total across the sweep")
    elif zero_first < 0.5:
        outcome = "CAUSALITY"
        why = "negatives are material and zeros do not dominate"
    else:
        outcome = "BOTH"
        why = ("zeros dominate but negatives are present above the floor; the single counter was "
               "hiding the second behind the first")
    return {"decided": True, "outcome": outcome, "why": why,
            "neg_total": neg_total, "max_neg_share": max_neg_share,
            "zero_first": zero_first, "zero_last": zero_last, "zero_falls": zero_falls}


def report(summary, axis, label):
    print(f"== OMB discards by {label} ==\n")
    print(f"{axis:>10s} {'n':>3s} {'kept':>8s} {'zero':>8s} {'negative':>9s} {'worst neg':>10s}")
    for s in summary:
        print(f"{s['level']:>10s} {s['n']:3d} {s['kept_share']:7.2%} {s['zero_share']:7.2%} "
              f"{s['neg_share']:8.3%} {s['most_negative']:9d}us")
    v = verdict(summary)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"  UNDECIDED: {v['why']}")
        return v
    print(f"  {v['outcome']}")
    print(f"  {v['why']}")
    if v["outcome"].startswith("RESOLUTION"):
        print()
        print("  OMB's guard drops every sample whose end-to-end latency computes to zero, which")
        print("  happens whenever publish and receive share a millisecond tick. On a sub-millisecond")
        print("  path that is most of them. The benchmark then reports a latency distribution from")
        print("  what survives, and counts nothing. That is a real and serious defect -- and it is")
        print("  not the causality violation this paper is about.")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify what OMB discards")
    ap.add_argument("--sweep", default=None, help="the load sweep CSV")
    ap.add_argument("--resolution", default=None, help="the message-size sweep CSV")
    ap.add_argument("--out", default=None, help="write the per-level summary here")
    args = ap.parse_args(argv)

    if not args.sweep and not args.resolution:
        print("nothing to do: pass --sweep and/or --resolution")
        return 1

    results = []
    for path, axis, label in ((args.sweep, "load_pct", "background load"),
                              (args.resolution, "message_size", "message size")):
        if not path:
            continue
        if not os.path.exists(path):
            print(f"missing: {path}")
            return 1
        rows = load(path)
        if not rows:
            print(f"{path} has no data rows -- every cell failed, which is not a result")
            return 1
        summary = summarise(rows, axis)
        results.append((label, summary, report(summary, axis, label)))
        print()

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["axis", "level", "n_cells", "kept_share", "zero_share",
                        "negative_share", "negatives", "most_negative_micros"])
            for label, summary, _v in results:
                for s in summary:
                    w.writerow([label, s["level"], s["n"], round(s["kept_share"], 5),
                                round(s["zero_share"], 5), round(s["neg_share"], 6),
                                s["negatives"], s["most_negative"]])
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
