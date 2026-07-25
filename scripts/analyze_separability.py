#!/usr/bin/env python3
"""
analyze_separability.py
Test the two-state stamping model against the scale family it replaces (docs/two_state_model.md).

The two structures make opposite geometric predictions for how the tail curve moves with load:

    scale family   P(inv) = S(c / sigma(rho))    curves RESCALE horizontally
    two-state      P(inv) = p(rho) * S(c)        curves SHIFT vertically, staying parallel

So the discriminating statistic is simple: take the log ratio of two conditions' tail masses at
several thresholds. Under the two-state model that ratio is log p(rho1) - log p(rho2), a constant
independent of the threshold. Under a scale family it is not.

Two details decide whether this test is honest.

Far-tail estimates are excluded. A tail mass computed from five events carries a log-scale error
larger than the effect, and including such points manufactures apparent structure in either
direction. We require a minimum event count and report how many estimates that removes.

The verdict is a median across condition pairs, not a best case. A model that fits some
conditions and not others is a partial model, and the output says so rather than quoting the
conditions that agree.

CLI:
    python scripts/analyze_separability.py --points docs/results/model/collapse_points.csv \
        --out docs/results/model
"""
import argparse
import csv
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

MIN_EVENTS = 20        # below this a tail mass is noise on a log scale
SEPARABLE = 0.5        # median log-spread below this: separable (factor 1.65)
PARTIAL = 1.0          # any single condition above this fails the pre-registered rule


def load_points(path, min_events=MIN_EVENTS):
    """Tail masses per condition and threshold, keeping only well-supported estimates."""
    kept, dropped = defaultdict(dict), 0
    rho = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                mass = float(r["tail_mass"])
                n = int(r["n_events"])
                thr = float(r["threshold_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            cond = r["condition"]
            try:
                rho[cond] = float(r["rho"])
            except (KeyError, TypeError, ValueError):
                pass
            if mass > 0 and mass * n >= min_events:
                kept[cond][thr] = mass
            else:
                dropped += 1
    return dict(kept), rho, dropped


def pair_spreads(points, min_thresholds=3):
    """Log-ratio spread across thresholds, for every condition against the richest reference."""
    usable = {c: t for c, t in points.items() if len(t) >= min_thresholds}
    if len(usable) < 2:
        return None, []
    ref = max(usable, key=lambda c: len(usable[c]))
    rows = []
    for cond in sorted(usable):
        if cond == ref:
            continue
        shared = sorted(set(usable[cond]) & set(usable[ref]))
        if len(shared) < min_thresholds:
            continue
        ratios = [math.log(usable[cond][t] / usable[ref][t]) for t in shared]
        rows.append({"condition": cond, "reference": ref, "n_thresholds": len(shared),
                     "log_ratios": ratios, "spread": round(max(ratios) - min(ratios), 4),
                     "mean_log_ratio": round(st.mean(ratios), 4)})
    return ref, rows


def verdict(rows, separable=SEPARABLE, partial=PARTIAL):
    """The pre-registered rule: median spread below 0.5, and no condition above 1.0."""
    if len(rows) < 2:
        return {"testable": False, "supported": False,
                "why": "need at least two comparable conditions"}
    spreads = sorted(r["spread"] for r in rows)
    median = st.median(spreads)
    worst = max(spreads)
    ok = median < separable and worst <= partial
    return {
        "testable": True, "median_spread": round(median, 4), "worst_spread": round(worst, 4),
        "n_conditions": len(rows), "supported": bool(ok),
        "why": (f"tail curves are parallel across load: median log-spread {median:.2f} "
                f"(factor {math.exp(median):.2f}), worst {worst:.2f}; load moves the WEIGHT of "
                f"the tail, not its shape"
                if ok else
                f"median log-spread {median:.2f} (factor {math.exp(median):.2f}), worst "
                f"{worst:.2f}: the curves are not parallel, so a single p(rho) with a fixed "
                f"S(c) does not describe the data"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Two-state separability vs the scale family")
    ap.add_argument("--points", default="docs/results/model/collapse_points.csv")
    ap.add_argument("--min-events", type=int, default=MIN_EVENTS)
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.points).is_file():
        print(f"missing points file: {args.points}")
        return 1
    points, rho, dropped = load_points(args.points, args.min_events)
    ref, rows = pair_spreads(points)
    if not rows:
        print(f"insufficient comparable conditions (dropped {dropped} thin estimates)")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "separability.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["condition", "reference", "n_thresholds",
                                           "mean_log_ratio", "spread"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in
                        ("condition", "reference", "n_thresholds", "mean_log_ratio", "spread")})

    print("== Two-state separability: are the tail curves parallel across load? ==")
    print(f"  reference {ref};  {dropped} thin estimates excluded "
          f"(fewer than {args.min_events} events)\n")
    print("  condition        rho     thr   log-ratios                       spread")
    for r in rows:
        vals = " ".join(f"{v:+.2f}" for v in r["log_ratios"])
        rv = rho.get(r["condition"])
        rs = f"{rv:.3f}" if rv is not None else "  -  "
        print(f"  {r['condition']:14s} {rs}   {r['n_thresholds']:2d}   {vals:30s}  "
              f"{r['spread']:.2f}")

    v = verdict(rows)
    print(f"\n== TWO-STATE MODEL: {'SUPPORTED' if v['supported'] else 'NOT SUPPORTED'} ==")
    print(f"  {v['why']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
