#!/usr/bin/env python3
"""
analyze_phase_quantisation.py
Is the damage set by commensurability, or by *how* commensurate?

Section 6.7 establishes that a producer paced at an interval commensurate with the timestamp
quantum produces bimodal, irreproducible retention, while an incommensurate rate produces a stable
fraction. That is a binary distinction and it is not the whole rule.

Write the producer's interval over the tick as a fraction p/q in lowest terms. After q sends the
phase within the tick returns to where it began, so the producer visits exactly q distinct phases.
The prediction that follows:

    retention takes one of (q+1) values,  and  replicate spread falls roughly as 100/q

`q = 1` (an exact multiple) gives all-or-nothing retention and a spread near 100 points. Large `q`
gives an effectively continuous phase and a spread near zero, with retention at `T_true / tau`.
The interesting region is in between, and it is the region no measurement had covered when this
was written.

This script computes `q` from each campaign's producer rate, groups the measured retentions, and
reports spread against `q` so the relation can be read directly. It does not fit anything: the
prediction is `spread ~ 100/q` and the table either shows that or does not.

CLI:
    python scripts/analyze_phase_quantisation.py --ledger docs/results/external_campaigns_index.csv
"""
import argparse
import csv
import os
from fractions import Fraction

# Campaigns whose cells vary the producer rate at a fixed payload. Others vary something else and
# would contribute rates that differ in more than phase.
RATE_CAMPAIGNS = ("rate_phase", "rate_phase2", "rate_q")

# Below this, a rate is treated as commensurate with the tick. A denominator of 500 means the
# phase pattern repeats only after 500 sends, which within a three-minute run at these rates is
# indistinguishable from never.
MAX_MEANINGFUL_Q = 64


def phase_denominator(rate_hz, tick_ms=1.0):
    """`q` for a producer at `rate_hz` against a tick of `tick_ms`.

    The send interval is 1000/rate ms, so interval/tick = 1000/(rate*tick). Expressed as an exact
    Fraction this gives the denominator directly, without floating-point rounding deciding whether
    a rate is commensurate -- which matters because 2.000 and 2.188 must not both round to "close
    enough to 2".
    """
    if rate_hz <= 0 or tick_ms <= 0:
        return None
    ratio = Fraction(1000, 1) / (Fraction(rate_hz) * Fraction(tick_ms).limit_denominator(10**6))
    return ratio.denominator


def load_rate_cells(path, campaigns=RATE_CAMPAIGNS):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        if r.get("campaign") not in campaigns:
            continue
        if r.get("valid") != "1" or r.get("count_source") != "shutdown_hook":
            continue
        try:
            kept = int(r.get("kept") or 0)
            zero = int(r.get("discarded_zero") or 0)
            neg = int(r.get("discarded_negative") or 0)
            rate = int(r.get("level") or 0)
        except (TypeError, ValueError):
            continue
        seen = kept + zero + neg
        if seen <= 0 or rate <= 0:
            continue
        out.append({"rate": rate, "retention": 100.0 * kept / seen})
    return out


def group_by_rate(cells, tick_ms=1.0):
    by = {}
    for c in cells:
        by.setdefault(c["rate"], []).append(c["retention"])
    out = []
    for rate in sorted(by, reverse=True):
        v = sorted(by[rate])
        q = phase_denominator(rate, tick_ms)
        out.append({
            "rate": rate,
            "interval_ms": 1000.0 / rate,
            "q": q,
            "commensurate": q is not None and q <= MAX_MEANINGFUL_Q,
            "n": len(v),
            "retentions": v,
            "spread": (max(v) - min(v)) if len(v) > 1 else None,
            "predicted_spread": (100.0 / q) if (q and q <= MAX_MEANINGFUL_Q) else 0.0,
        })
    return out


def verdict(groups):
    """Does spread track 1/q, or is the rule merely binary?"""
    usable = [g for g in groups if g["spread"] is not None and g["q"]]
    small = [g for g in usable if g["commensurate"] and g["q"] == 1]
    mid = [g for g in usable if g["commensurate"] and 2 <= g["q"] <= MAX_MEANINGFUL_Q]
    large = [g for g in usable if not g["commensurate"]]

    if not small or not large:
        return {"decided": False,
                "why": "need both an exact multiple and an incommensurate rate to compare"}
    if not mid:
        return {"decided": False,
                "why": ("only q=1 and large-q rates measured; the binary distinction is "
                        "established but the quantisation rule is untested")}

    q1 = sum(g["spread"] for g in small) / len(small)
    qn = sum(g["spread"] for g in large) / len(large)
    ordered = sorted(mid, key=lambda g: g["q"])

    # The prediction is specific -- spread ~ 100/q -- so test it directly rather than testing the
    # weaker property of lying somewhere between the extremes. An earlier version checked only
    # "ordered and in range", which called spreads of 97 and 96 quantised because they happen to
    # sit below 99 and above 2. Clustering at an extreme is the binary case and must not pass.
    TOL = 20.0
    near_predicted = sum(abs(g["spread"] - 100.0 / g["q"]) <= TOL for g in ordered)
    near_top = sum(abs(g["spread"] - q1) <= TOL for g in ordered)
    near_bottom = sum(abs(g["spread"] - qn) <= TOL for g in ordered)

    if near_top == len(ordered) and near_predicted < len(ordered):
        return {"decided": True, "outcome": "BINARY (any rational is dangerous)",
                "why": (f"all {len(ordered)} intermediate rates sit within {TOL:.0f} points of the "
                        f"exact-multiple spread ({q1:.1f}), not on a 1/q curve")}
    if near_bottom == len(ordered) and near_predicted < len(ordered):
        return {"decided": True, "outcome": "BINARY (only exact multiples matter)",
                "why": (f"all {len(ordered)} intermediate rates sit within {TOL:.0f} points of the "
                        f"incommensurate spread ({qn:.1f})")}
    if near_predicted == len(ordered):
        return {"decided": True, "outcome": "QUANTISED",
                "why": (f"every intermediate rate's spread falls within {TOL:.0f} points of "
                        f"100/q, across q = "
                        + ", ".join(str(g["q"]) for g in ordered))}
    return {"decided": True, "outcome": "UNCLEAR",
            "why": (f"{near_predicted} of {len(ordered)} intermediate rates match 100/q; the "
                    f"others sit at neither extreme")}


def report(groups):
    print("== retention spread against the phase denominator q ==\n")
    print(f"{'rate':>8s} {'interval':>10s} {'q':>5s} {'n':>3s} "
          f"{'spread':>8s} {'~100/q':>8s}  retentions")
    for g in groups:
        qs = str(g["q"]) if g["commensurate"] else f">{MAX_MEANINGFUL_Q}"
        sp = "-" if g["spread"] is None else f"{g['spread']:.1f}"
        pr = f"{g['predicted_spread']:.1f}" if g["commensurate"] else "~0"
        vals = " ".join(f"{x:.2f}" for x in g["retentions"][:6])
        print(f"{g['rate']:>7d}/s {g['interval_ms']:>9.3f}m {qs:>5s} {g['n']:>3d} "
              f"{sp:>8s} {pr:>8s}  {vals}")

    v = verdict(groups)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"  UNDECIDED: {v['why']}")
        return v
    print(f"  {v['outcome']}")
    print(f"  {v['why']}")
    if v["outcome"] == "QUANTISED":
        print()
        print("  The rule is arithmetic, not categorical. A producer's pacing is dangerous in")
        print("  proportion to how few distinct phases it visits within the clock's quantum, so")
        print("  a rate need not be an exact multiple to damage reproducibility, and safety")
        print("  comes from a large denominator rather than from any particular rate.")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="Spread against the phase denominator")
    ap.add_argument("--ledger", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--tick-ms", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if not os.path.exists(args.ledger):
        print(f"missing: {args.ledger}")
        return 1
    cells = load_rate_cells(args.ledger)
    if not cells:
        print(f"no rate-varying cells in {args.ledger}")
        return 1
    groups = group_by_rate(cells, args.tick_ms)
    report(groups)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["rate_hz", "interval_ms", "q", "commensurate", "n",
                        "spread_pts", "predicted_spread_pts", "retentions"])
            for g in groups:
                w.writerow([g["rate"], round(g["interval_ms"], 4), g["q"], g["commensurate"],
                            g["n"], "" if g["spread"] is None else round(g["spread"], 3),
                            round(g["predicted_spread"], 3),
                            " ".join(f"{x:.3f}" for x in g["retentions"])])
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
