#!/usr/bin/env python3
"""
compare_campaign_passes.py
Does a per-level summary reproduce when the whole sweep is run again?

The load sweep was run twice with an identical configuration: `load_sweep` is replicates 1-3 and
`load_sweep_p2` is replicates 4-6. Both report a median retention per load level. The question
this asks is not whether OMB's retention varies run to run -- that is established -- but whether
the *summary statistic a careful experimenter would publish* varies: the median of three
replicates, which is the standard defence against exactly this kind of noise.

If the per-level medians agree between passes, three replicates are enough and the sweep is
reportable as a curve. If they do not, then a three-replicate median of this quantity is itself
not reproducible, and no per-level number from this benchmark should be published at that n --
including the ones in our own first sweep.

The second outcome is the more interesting and the more likely, given retention at a fixed
configuration has already been observed spanning 0.36% to 100%. It is also the more awkward, so
the comparison is written before the second pass finishes and reports whichever it finds.

CLI:
    python scripts/compare_campaign_passes.py --ledger docs/results/external_campaigns_index.csv \\
        --pass-a load_sweep --pass-b load_sweep_p2 --axis load_pct
"""
import argparse
import csv
import os
import statistics as st

# A per-level median that moves by more than this between passes is not a number to publish at
# this replicate count. Ten points is already generous for a quantity reported as a percentage.
REPRODUCIBLE_PTS = 10.0


def load(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def retention_by_level(rows, campaign, axis):
    """{level: [retention%, ...]} for one campaign, from cells with exact counts."""
    out = {}
    for r in rows:
        if r.get("campaign") != campaign or r.get("axis") != axis:
            continue
        if r.get("valid") != "1" or r.get("count_source") != "shutdown_hook":
            continue
        try:
            zero_share = float(r["zero_share"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(r.get("level", ""), []).append(100.0 * (1.0 - zero_share))
    return out


def _level_key(level):
    try:
        return (0, float(level), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(level))


def compare(rows, campaign_a, campaign_b, axis):
    a = retention_by_level(rows, campaign_a, axis)
    b = retention_by_level(rows, campaign_b, axis)
    levels = sorted(set(a) | set(b), key=_level_key)
    out = []
    for lv in levels:
        va, vb = a.get(lv, []), b.get(lv, [])
        ma = st.median(va) if va else None
        mb = st.median(vb) if vb else None
        delta = None if (ma is None or mb is None) else abs(ma - mb)
        out.append({"level": lv, "n_a": len(va), "n_b": len(vb),
                    "median_a": ma, "median_b": mb, "delta_pts": delta,
                    "spread_a": (max(va) - min(va)) if len(va) > 1 else None,
                    "spread_b": (max(vb) - min(vb)) if len(vb) > 1 else None})
    return out


def verdict(comparison):
    """Do the two passes agree well enough for a per-level number to be publishable?"""
    deltas = [c["delta_pts"] for c in comparison if c["delta_pts"] is not None]
    if not deltas:
        return {"decided": False, "why": "no level has replicates in both passes"}
    worst = max(deltas)
    if worst <= REPRODUCIBLE_PTS:
        return {"decided": True, "outcome": "REPRODUCIBLE", "worst": worst,
                "why": (f"every per-level median moved by at most {worst:.1f} points between "
                        f"passes, so three replicates suffice at this level of detail")}
    return {"decided": True, "outcome": "NOT REPRODUCIBLE", "worst": worst,
            "why": (f"a per-level median moved by {worst:.1f} points between two passes of an "
                    f"identical configuration; a three-replicate median of this quantity is not "
                    f"a number to publish")}


def report(comparison, campaign_a, campaign_b, axis):
    print(f"== per-level retention: {campaign_a} vs {campaign_b} ==\n")
    print(f"{axis:>12s}{'n':>4s}{'median A':>11s}{'spread A':>11s}"
          f"{'n':>4s}{'median B':>11s}{'spread B':>11s}{'|delta|':>10s}")
    for c in comparison:
        print(f"{c['level']:>12s}{c['n_a']:>4d}{_p(c['median_a']):>11s}{_p(c['spread_a']):>11s}"
              f"{c['n_b']:>4d}{_p(c['median_b']):>11s}{_p(c['spread_b']):>11s}"
              f"{_p(c['delta_pts']):>10s}")

    v = verdict(comparison)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"  UNDECIDED: {v['why']}")
        return v
    print(f"  {v['outcome']}")
    print(f"  {v['why']}")
    if v["outcome"] == "NOT REPRODUCIBLE":
        print()
        print("  This applies to our own first sweep as much as to anyone else's. The per-level")
        print("  discard shares from a single pass should be reported as what they are -- three")
        print("  draws from a quantity that does not settle -- and not as a response curve.")
    return v


def _p(v):
    return "-" if v is None else f"{v:.2f}%"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare two passes of the same sweep")
    ap.add_argument("--ledger", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--pass-a", default="load_sweep")
    ap.add_argument("--pass-b", default="load_sweep_p2")
    ap.add_argument("--axis", default="load_pct")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if not os.path.exists(args.ledger):
        print(f"missing: {args.ledger}")
        return 1
    rows = load(args.ledger)
    comparison = compare(rows, args.pass_a, args.pass_b, args.axis)
    if not comparison:
        print(f"no cells for {args.pass_a} or {args.pass_b} on axis {args.axis}")
        return 1
    report(comparison, args.pass_a, args.pass_b, args.axis)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["level", "n_a", "n_b", "median_a", "median_b",
                                               "delta_pts", "spread_a", "spread_b"])
            w.writeheader()
            for c in comparison:
                w.writerow({k: ("" if c[k] is None else
                                (round(c[k], 4) if isinstance(c[k], float) else c[k]))
                            for k in w.fieldnames})
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
