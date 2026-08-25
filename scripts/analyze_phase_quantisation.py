#!/usr/bin/env python3
"""
analyze_phase_quantisation.py
Is the damage set by commensurability, or by *how* commensurate?

The external-campaign section establishes that a producer paced at an interval commensurate with the timestamp
quantum produces bimodal, irreproducible retention, while an incommensurate rate produces a stable
fraction. That is a binary distinction and it is not the whole rule.

Write the producer's interval over the tick as a fraction p/q in lowest terms. After q sends the
phase within the tick returns to where it began, so the producer visits exactly q distinct phases,
and retention -- a count of crossing phases over q -- lands on one of the two grid points that
bracket `T_true / tau`.

`q = 1` (an exact multiple) gives all-or-nothing retention. Large `q` gives an effectively
continuous phase and a stable retention at `T_true / tau`. The interesting region is in between,
and it is the region no measurement had covered when this was written.

WHAT THE SPREAD PREDICTION ACTUALLY IS, because we got it wrong first. The obvious form is
`spread ~ 100/q`, and this script said exactly that. It is not a point prediction: 100/q is the
CELL WIDTH, an upper bound reached only when `T_true / tau` sits midway between two grid points,
because only then do replicates realise both bracketing points. When it sits ON a grid point, one
point takes nearly every run and the spread collapses toward zero:

    spread -> 100/q   when T_true/tau is mid-cell
    spread -> 0       when T_true/tau is on a grid point

Stated as a point prediction, the even-q arms looked like failures and we introduced a degeneracy
exclusion for them -- pre-registered and defensible, but unnecessary. Stated correctly, an on-grid
arm IS a prediction of a flat arm, so q=2 and q=4 became evidence for the model rather than cases
to excuse. One formula covers every arm. `grid_distance_pts` and the `degenerate` flag survive as
descriptive outputs; nothing is excluded on their basis any more.

The verdict is therefore a classification with no tolerance to choose. Each arm is predicted to
show the full cell width or to collapse; "spread above half the cell width" says which it did. The
position is measured against the cell half-width rather than a fixed noise floor, which makes every
call identical whether the continuous value is estimated pooled or separately at each rate -- the
sensitivity that exposed the original error is gone.

One guard remains, and it is about power rather than about the model: spread is a range statistic,
so an arm needs enough replicates to realise both branches before a flat result means anything.
See MIN_REPLICATES_FOR_FULL.

CLI:
    python scripts/analyze_phase_quantisation.py --ledger docs/results/external_campaigns_index.csv
"""
import argparse
import csv
import os
from fractions import Fraction

# Campaigns whose cells vary the producer rate at a fixed payload. Others vary something else and
# would contribute rates that differ in more than phase. chain17's `ultimate` belongs here; its
# payload and duration companions (`ultimate_pay300`, `ultimate_dur1`, `ultimate_dur10`) are
# deliberately absent -- mixing payloads or durations into the rate arms would corrupt exactly the
# spreads this analysis exists to test, and each is analysed against its own prediction instead.
RATE_CAMPAIGNS = ("rate_phase", "rate_phase2", "rate_q", "ultimate")

# Below this, a rate is treated as commensurate with the tick. A denominator of 500 means the
# phase pattern repeats only after 500 sends, which within a three-minute run at these rates is
# indistinguishable from never.
MAX_MEANINGFUL_Q = 64

# Fallback replicate noise, in retention points, used only when there are too few incommensurate
# rates to measure it. The incommensurate pool is the natural yardstick: those rates visit every
# phase, so their replicate scatter is the noise floor against which a grid must be resolved.
DEFAULT_NOISE_PTS = 5.0


def continuous_retention(groups):
    """The retention an incommensurate rate settles at, as a percentage, or None.

    This is the measured `T_true / tau`: with a phase that never repeats, the retained fraction is
    just the fraction of the quantum the true latency spans. It is measured rather than assumed
    because the whole degeneracy test depends on where it actually falls.
    """
    vals = [x for g in groups if not g["commensurate"] for x in g["retentions"]]
    if not vals:
        return None
    vals.sort()
    n = len(vals)
    return vals[n // 2] if n % 2 else 0.5 * (vals[n // 2 - 1] + vals[n // 2])


def continuous_noise_pts(groups, default=DEFAULT_NOISE_PTS):
    """Replicate scatter among incommensurate rates, as a half-range in retention points."""
    spreads = [g["spread"] for g in groups
               if not g["commensurate"] and g["spread"] is not None]
    if not spreads:
        return default
    return max(0.5 * max(spreads), 0.5)


def grid_distance_pts(q, continuous_pct):
    """Distance from the continuous value to the nearest point of the (q+1)-point grid, in points.

    Large means the two hypotheses predict visibly different retentions and the arm can test them.
    Near zero means they predict the same number and the arm cannot, however it lands.
    """
    if not q or q <= 0 or continuous_pct is None:
        return None
    return min(abs(continuous_pct - 100.0 * i / q) for i in range(q + 1))


def cell_position(q, continuous_pct):
    """Where the continuous value sits inside its grid cell: (width, distance, fraction).

    `fraction` is 0 at a grid point and 1 midway between two, i.e. distance expressed against the
    cell *half*-width. It is the quantity that decides how much spread an arm can show, and unlike
    a fixed noise threshold it is scale-free, so the classification does not move when the
    continuous value is re-estimated.
    """
    if not q or q <= 0 or continuous_pct is None:
        return None
    width = 100.0 / q
    d = grid_distance_pts(q, continuous_pct)
    return width, d, min(1.0, d / (width / 2.0))


# Above this fraction of the half-cell, both bracketing grid points are realistically reachable
# and the arm can show its full spread; below it, replicates pile onto one point.
MIDCELL_FRACTION = 0.5

# A "full spread" prediction is only testable if the arm has enough replicates to realise *both*
# bracketing grid points. Spread is a range statistic, so a single branch produces zero spread no
# matter how right the model is: at 300 msg/s only one replicate in five took the upper branch, so
# two replicates would show a flat arm about two thirds of the time by luck alone. Below this
# count a flat observation is uninformative and must be reported as underpowered rather than as a
# refutation -- otherwise an unfinished arm reads as evidence against.
#
# This is a statement about statistical power, not about the model, and the threshold depends only
# on n, which is known before any measurement is taken. A "flat" prediction needs no such guard:
# observing the full cell width when the model says flat is decisive at any n.
MIN_REPLICATES_FOR_FULL = 3


def predicted_spread(q, continuous_pct):
    """Spread this arm can show, in points -- NOT simply 100/q.

    Retention is a count of phases over q, so a replicate lands on one of the two grid points
    bracketing `T_true/tau`. The spread between replicates is therefore the cell width 100/q when
    both points get realised, and collapses toward zero when the continuous value sits on a grid
    point and one of them takes nearly every run.

    This corrects a real error of ours. We wrote the prediction as `spread ~ 100/q` and treated it
    as a point prediction, when it is an upper bound attained only mid-cell. Stated that way the
    even-q arms looked like failures needing an exclusion; stated correctly they are predictions
    of a *small* spread, which is what they show. One formula now covers every arm instead of a
    law for odd q plus a special case for even q.
    """
    pos = cell_position(q, continuous_pct)
    if pos is None:
        return None
    width, _, frac = pos
    return width if frac > MIDCELL_FRACTION else 0.0


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
            "cell_width": (100.0 / q) if (q and q <= MAX_MEANINGFUL_Q) else 0.0,
        })

    # Second pass. Where the continuous value falls inside its grid cell decides how much spread
    # the arm can show, so it cannot be computed until the incommensurate arms have been grouped.
    cont = continuous_retention(out)
    noise = continuous_noise_pts(out)
    for g in out:
        d = grid_distance_pts(g["q"], cont) if g["commensurate"] else None
        pos = cell_position(g["q"], cont) if g["commensurate"] else None
        g["grid_distance"] = d
        g["cell_fraction"] = pos[2] if pos else None
        g["predicted_spread"] = (predicted_spread(g["q"], cont) if g["commensurate"] else 0.0)
        g["degenerate"] = bool(g["commensurate"] and d is not None and d <= noise)
        # Predicted and observed class, the quantity the verdict is actually decided on. An arm
        # shows the full cell width or it collapses; "closer to w than to 0" is the observation
        # that distinguishes them, and needs no tolerance to be chosen.
        g["predicted_full"] = (pos[2] > MIDCELL_FRACTION) if pos else None
        g["observed_full"] = (
            (g["spread"] > g["cell_width"] / 2.0)
            if (g["commensurate"] and g["spread"] is not None and g["cell_width"]) else None)
        # A flat result on a full-predicted arm with too few replicates says nothing either way.
        # Note the asymmetry: a *full* result is always informative, so only the flat case is
        # withheld, and an underpowered arm that shows full spread still counts.
        g["underpowered"] = bool(
            g["predicted_full"] and g["observed_full"] is False
            and g["n"] < MIN_REPLICATES_FOR_FULL)
    return out


def verdict(groups):
    """Does each arm show the spread its position in the grid cell predicts?

    The test is a classification rather than a tolerance. For every commensurate arm the model
    says the replicate spread is either the full cell width 100/q (the continuous value sits
    mid-cell, so both bracketing grid points get realised) or near zero (it sits on a grid point,
    so one of them takes nearly every run). The observation says the same thing: a spread above
    half the cell width is the full case, below it the collapsed one. Nothing has to be tuned, and
    an arm predicted to collapse counts as evidence when it collapses -- under the earlier
    formulation those arms had to be excluded, which is weaker and easier to abuse.
    """
    usable = [g for g in groups if g["spread"] is not None and g["q"]]
    testable = [g for g in usable if g["commensurate"] and g.get("predicted_full") is not None
                and g.get("observed_full") is not None and not g.get("underpowered")]
    underpowered = [g for g in usable if g.get("underpowered")]
    large = [g for g in usable if not g["commensurate"]]

    if not large:
        return {"decided": False,
                "why": ("no incommensurate rate measured, so the continuous value is unknown and "
                        "no grid position can be computed")}
    if not testable:
        why = "no commensurate rate with replicates; the quantisation rule is untested"
        if underpowered:
            why = ("every commensurate arm is underpowered: " + ", ".join(
                "q=%d at n=%d" % (g["q"], g["n"]) for g in underpowered)
                + " predict a full cell width but have too few replicates to realise both "
                  "bracketing points, so a flat result is uninformative")
        return {"decided": False, "underpowered": underpowered, "why": why}

    ordered = sorted(testable, key=lambda g: g["q"])
    agree = [g for g in ordered if g["predicted_full"] == g["observed_full"]]
    disagree = [g for g in ordered if g["predicted_full"] != g["observed_full"]]

    # An arm set that predicts the same class everywhere cannot discriminate: agreeing with a
    # constant prediction is not evidence for the model that produced it.
    kinds = {g["predicted_full"] for g in ordered}
    if len(kinds) < 2:
        return {"decided": False, "disagree": disagree, "underpowered": underpowered,
                "why": (f"all {len(ordered)} arms predict the same class, so agreement with them "
                        f"would not distinguish this model from a constant")}

    lowpower = (" ; underpowered and set aside: " + ", ".join(
        "q=%d at n=%d" % (g["q"], g["n"]) for g in underpowered)) if underpowered else ""
    detail = ", ".join(
        "q=%d %s/%s" % (g["q"], "full" if g["predicted_full"] else "flat",
                        "full" if g["observed_full"] else "flat") for g in ordered)

    if not disagree:
        return {"decided": True, "outcome": "QUANTISED", "disagree": disagree, "underpowered": underpowered,
                "why": (f"all {len(ordered)} arms show the spread their grid position predicts "
                        f"(predicted/observed: {detail})" + lowpower)}
    if len(agree) <= len(ordered) / 2.0:
        return {"decided": True, "outcome": "REFUTED", "disagree": disagree, "underpowered": underpowered,
                "why": (f"only {len(agree)} of {len(ordered)} arms match "
                        f"(predicted/observed: {detail})" + lowpower)}
    return {"decided": True, "outcome": "UNCLEAR", "disagree": disagree, "underpowered": underpowered,
            "why": (f"{len(agree)} of {len(ordered)} arms match; q = "
                    + ", ".join(str(g["q"]) for g in disagree) + " do not "
                    f"(predicted/observed: {detail})" + lowpower)}


def report(groups):
    cont = continuous_retention(groups)
    noise = continuous_noise_pts(groups)
    print("== retention spread against the phase denominator q ==\n")
    if cont is not None:
        print(f"continuous value (incommensurate median): {cont:.1f}%   "
              f"replicate noise: {noise:.1f} pts")
        print("each arm's spread is predicted by where that value falls inside its grid cell\n")
    print(f"{'rate':>8s} {'q':>5s} {'n':>3s} {'width':>7s} {'incell':>7s} "
          f"{'pred':>7s} {'spread':>7s} {'call':>10s}  retentions")
    for g in groups:
        qs = str(g["q"]) if g["commensurate"] else f">{MAX_MEANINGFUL_Q}"
        sp = "-" if g["spread"] is None else f"{g['spread']:.1f}"
        w = f"{g['cell_width']:.1f}" if g["commensurate"] else "-"
        fr = "-" if g.get("cell_fraction") is None else f"{g['cell_fraction']:.2f}"
        # With no incommensurate arm there is no continuous value, so no cell position and no
        # prediction. That is a missing measurement, not a prediction of zero, and must print as
        # such rather than formatting None or quietly showing 0.0.
        pr = ("~0" if not g["commensurate"]
              else "-" if g["predicted_spread"] is None
              else f"{g['predicted_spread']:.1f}")
        if g.get("predicted_full") is None or g.get("observed_full") is None:
            call = "-"
        else:
            call = "%s/%s%s" % ("full" if g["predicted_full"] else "flat",
                                "full" if g["observed_full"] else "flat",
                                "" if g["predicted_full"] == g["observed_full"] else " MISS")
        vals = " ".join(f"{x:.2f}" for x in g["retentions"][:6])
        print(f"{g['rate']:>7d}/s {qs:>5s} {g['n']:>3d} {w:>7s} {fr:>7s} "
              f"{pr:>7s} {sp:>7s} {call:>10s}  {vals}")
    print()
    print("  incell: 0 = the continuous value sits on a grid point (predict a flat arm),")
    print("          1 = midway between two (predict the full cell width of spread).")
    print("  call:   predicted/observed class. This is what the verdict is decided on.")

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
            w.writerow(["rate_hz", "interval_ms", "q", "commensurate", "cell_width_pts",
                        "grid_distance_pts", "cell_fraction", "predicted_full", "observed_full",
                        "n", "spread_pts", "predicted_spread_pts", "retentions"])
            for g in groups:
                gd, cf = g.get("grid_distance"), g.get("cell_fraction")
                w.writerow([g["rate"], round(g["interval_ms"], 4), g["q"], g["commensurate"],
                            round(g["cell_width"], 3),
                            "" if gd is None else round(gd, 3),
                            "" if cf is None else round(cf, 4),
                            "" if g.get("predicted_full") is None else g["predicted_full"],
                            "" if g.get("observed_full") is None else g["observed_full"],
                            g["n"], "" if g["spread"] is None else round(g["spread"], 3),
                            round(g["predicted_spread"], 3),
                            " ".join(f"{x:.3f}" for x in g["retentions"])])
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
