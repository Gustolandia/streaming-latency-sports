#!/usr/bin/env python3
"""
analyze_occupancy_law.py
What the pooled data supports once E-A5 has ruled utilisation out as the variable.

E-A5 showed by manipulation that the inversion rate follows stamping-thread occupancy, not
utilisation: holding rho fixed and raising the stamping threads to real-time priority cut the
rate by 39-54x. Every curve in rho -- M/G/1, our own bounded bracket -- then failed against the
knee sweep, which is what a misspecified variable looks like. This script asks what IS supported.

Three candidate laws, each stated so it can fail.

L1  THE FLOOR IS THE IDLE RATE.
    If the two-state picture is right, the real-time arm and an unloaded machine are the same
    state: the stamping thread is running, and the only inversions left are ordinary jitter. So
    the measured floor under load at real-time priority must equal the measured rate at idle
    under ordinary priority. These are two very different experiments and nothing forces them to
    agree, so agreement is evidence and disagreement would falsify the decomposition.

L2  THE RATE HAS A CEILING BELOW ONE, AND THE CEILING IS PHYSICAL.
    P(inv) = p * S with p a probability means the rate cannot exceed S, the chance a preemption
    residual outlasts the true transport. So the rate must saturate strictly below 1 -- and the
    saturation value estimates S rather than being a fitted asymptote. A rate that kept climbing
    toward 1, or that saturated at a level varying wildly between campaigns, would count against.

L3  UTILISATION DOES NOT DETERMINE THE RATE; CORE AVAILABILITY DOES.
    Concentrated load (`--cpu k`, leaving C-k cores genuinely free) and spread load
    (`--cpu C --cpu-load P`, leaving none) can produce the same rho by different means. If the
    mechanism is whether the stamping thread finds a core, spread load must invert more at equal
    rho, and the gap must close as rho approaches 1 where neither leaves a free core.

    E-A6 tested this within one campaign, and it held at all three levels: at matched rho,
    spread load inverts 1.88x, 2.07x and 1.06x more than concentrated. The middle pair sits at
    rho = 0.7531 in BOTH arms -- identical to four decimals -- and the rates differ twofold. A
    function of rho returns one value for one input, so utilisation cannot be the variable.
    The gap closes at the top (1.06x at rho ~ 0.88), which is what "can the thread find a free
    core" predicts: at seven of eight cores busy, one free core is nearly as bad as none.

    Cross-campaign pairs are still reported, separately and as the weaker evidence they are.

Given L1 and L2, occupancy becomes measurable rather than fitted: p = (rate - C0) / (S - C0).
That inversion is only meaningful if p lands in [0,1] and rises monotonically with load, which is
a check on the whole picture rather than a definition, and it is reported as one.

CLI:
    python scripts/analyze_occupancy_law.py --pooled docs/results/model/knee_resolution.csv \
        --priority docs/results/model/stamping_priority.csv --out docs/results/model
"""
import argparse
import csv
import statistics as st
from pathlib import Path

IDLE_RHO = 0.01          # below this the machine is unloaded
FLOOR_TOLERANCE = 2.0    # L1: floor and idle rate must agree within this factor
CEILING_MAX = 0.60       # L2: a "ceiling" above this is not a ceiling worth claiming
SPREAD_PHASES = {"ea4", "ea6"}   # duty-cycle campaigns; everything else is whole-core


def geometry_of(phase, condition):
    """Which load geometry a condition used.

    Two encodings, because they arose from different campaigns and both must be read.

    The condition NAME wins when it says so. E-A6 runs both geometries inside one campaign --
    `k5_conc` against `k5_spread` -- precisely so the comparison is within-campaign rather than
    across days, and a phase-level rule cannot see that distinction at all. Reading geometry
    from the phase alone would have labelled every E-A6 cell identically and silently destroyed
    the only controlled test of L3 we have.

    Otherwise fall back to the campaign: E-A4 used duty-cycled load on every core (spread),
    while the earlier ladders loaded whole cores and left the rest free (concentrated).
    """
    c = (condition or "").lower()
    if c.endswith("_spread"):
        return "spread"
    if c.endswith("_conc"):
        return "concentrated"
    return "spread" if phase in SPREAD_PHASES else "concentrated"


def load_pooled(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rho, inv = float(r["rho"]), float(r["inversion_rate"])
            except (KeyError, ValueError, TypeError):
                continue
            phase = r.get("phase", "")
            condition = r.get("condition", "")
            rows.append({"phase": phase, "condition": condition,
                         "rho": rho, "inversion": inv,
                         "geometry": geometry_of(phase, condition)})
    return sorted(rows, key=lambda r: r["rho"])


def load_priority(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                if r.get("confounded", "False") == "True":
                    continue
                rows.append({"level": r["level"], "rho": float(r["rho_base"]),
                             "loaded": float(r["inv_base"]), "floor": float(r["inv_rt"])})
            except (KeyError, ValueError, TypeError):
                continue
    return rows


def law_floor(pooled, priority):
    """L1: the real-time floor under load equals the idle rate."""
    idle = [r["inversion"] for r in pooled if r["rho"] < IDLE_RHO]
    floors = [r["floor"] for r in priority]
    if not idle or not floors:
        return {"testable": False, "why": "need both idle conditions and real-time arms"}
    mi, mf = st.median(idle), st.median(floors)
    ratio = max(mi, mf) / min(mi, mf) if min(mi, mf) > 0 else float("inf")
    return {"testable": True, "idle": mi, "floor": mf, "ratio": ratio,
            "holds": ratio <= FLOOR_TOLERANCE, "n_idle": len(idle), "n_floor": len(floors)}


def law_ceiling(pooled):
    """L2: the rate saturates strictly below 1, at a level consistent across campaigns."""
    high = [r for r in pooled if r["rho"] >= 0.95]
    if len(high) < 3:
        return {"testable": False, "why": "too few conditions near saturation"}
    vals = [r["inversion"] for r in high]
    ceiling = max(vals)
    by_phase = {}
    for r in high:
        by_phase.setdefault(r["phase"], []).append(r["inversion"])
    spread_across = (max(map(st.median, by_phase.values()))
                     / min(map(st.median, by_phase.values()))) if len(by_phase) > 1 else 1.0
    return {"testable": True, "ceiling": ceiling, "median": st.median(vals), "n": len(vals),
            "phases": len(by_phase), "consistency": spread_across,
            "holds": ceiling < CEILING_MAX and spread_across <= 2.0}


def law_geometry(pooled, tol=0.02):
    """L3: utilisation does not determine the rate; how the load is arranged does.

    Two kinds of comparison, and only the second carries a logical argument.

    MATCHED pairs (|d rho| <= tol) ask the direct question and are reported for completeness,
    but a difference there could always be attributed to residual mismatch in rho.

    DOMINATING pairs are the ones that matter: a spread condition at LOWER rho that inverts MORE
    than a concentrated condition at HIGHER rho. No monotone function of rho can produce both
    readings, whatever its shape, so a single such pair refutes the whole family rather than
    losing a fit against it. That is the argument E-A5 makes by manipulation and this makes by
    arithmetic.

    Saturated cells are excluded as partners: their rho is pinned at 1.000 and unresolved, so
    "lower rho" would not mean anything against them.
    """
    spread = [r for r in pooled if r["geometry"] == "spread" and r["rho"] < 0.999]
    conc = [r for r in pooled if r["geometry"] == "concentrated" and r["rho"] < 0.999]
    if not spread or not conc:
        return {"testable": False, "why": "need both geometries below saturation"}
    matched, dominating, controlled = [], [], []
    for s in spread:
        for c in conc:
            rec = {"rho_spread": s["rho"], "rho_conc": c["rho"],
                   "inv_spread": s["inversion"], "inv_conc": c["inversion"],
                   "phase": s["phase"] if s["phase"] == c["phase"] else "cross",
                   "ratio": s["inversion"] / c["inversion"] if c["inversion"] else None}
            if abs(c["rho"] - s["rho"]) <= tol:
                rec = dict(rec, spread_worse=s["inversion"] > c["inversion"])
                matched.append(rec)
                # A pair from ONE campaign is the controlled comparison: same day, same
                # machine, same protocol, only the geometry differing. Cross-campaign pairs
                # carry every difference between two days as well, so they are suggestive
                # where these are decisive, and mixing them would understate the evidence.
                if s["phase"] == c["phase"]:
                    controlled.append(rec)
            elif s["rho"] < c["rho"] and s["inversion"] > c["inversion"]:
                dominating.append(rec)
    ctrl_worse = sum(1 for r in controlled if r["spread_worse"])
    return {"testable": True, "matched": matched, "dominating": dominating,
            "controlled": controlled, "n_matched": len(matched),
            "n_dominating": len(dominating), "n_controlled": len(controlled),
            "controlled_spread_worse": ctrl_worse,
            # One dominating pair is enough: it is a contradiction, not a majority vote.
            "holds": len(dominating) >= 1 or ctrl_worse > 0,
            # Only provisional while no single campaign has run both geometries.
            "provisional": not controlled}


def implied_occupancy(pooled, floor, ceiling):
    """p = (rate - C0)/(S - C0). A check on the decomposition, not a definition of p."""
    if ceiling <= floor:
        return [], {"valid": False, "why": "ceiling not above floor"}
    out = []
    for r in pooled:
        p = (r["inversion"] - floor) / (ceiling - floor)
        out.append(dict(r, p=p))
    inrange = sum(1 for r in out if -0.05 <= r["p"] <= 1.05)
    ordered = sorted(out, key=lambda r: r["rho"])
    # Monotone in the loose sense: the low-load half must sit below the high-load half.
    half = len(ordered) // 2
    lo = st.median([r["p"] for r in ordered[:half]])
    hi = st.median([r["p"] for r in ordered[half:]])
    return out, {"valid": True, "in_range": inrange, "n": len(out),
                 "all_in_range": inrange == len(out), "low_half": lo, "high_half": hi,
                 "monotone": hi > lo}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pooled", default="docs/results/model/knee_resolution.csv")
    ap.add_argument("--priority", default="docs/results/model/stamping_priority.csv")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    for p in (args.pooled, args.priority):
        if not Path(p).exists():
            print(f"missing input: {p}")
            return 1
    pooled = load_pooled(args.pooled)
    priority = load_priority(args.priority)
    if not pooled or not priority:
        print("no usable rows in one of the inputs")
        return 1

    print("== L1: the real-time floor is the idle rate ==")
    l1 = law_floor(pooled, priority)
    if not l1["testable"]:
        print(f"  not testable: {l1['why']}")
    else:
        print(f"  idle, ordinary priority   : {l1['idle']:.5f}  (n={l1['n_idle']})")
        print(f"  loaded, real-time priority: {l1['floor']:.5f}  (n={l1['n_floor']})")
        print(f"  ratio {l1['ratio']:.2f}  ->  {'HOLDS' if l1['holds'] else 'FAILS'}")
        if l1["holds"]:
            print("  Two unrelated experiments agree: load with a runnable stamping thread")
            print("  looks exactly like no load at all. That is what 'the failure is a state,")
            print("  not a load' predicts, and nothing else requires it.")

    print("\n== L2: the rate saturates below one ==")
    l2 = law_ceiling(pooled)
    if not l2["testable"]:
        print(f"  not testable: {l2['why']}")
    else:
        print(f"  near-saturation conditions: n={l2['n']} across {l2['phases']} campaign(s)")
        print(f"  ceiling {l2['ceiling']:.4f}, median {l2['median']:.4f}, "
              f"between-campaign spread {l2['consistency']:.2f}x")
        print(f"  -> {'HOLDS' if l2['holds'] else 'FAILS'}")
        if l2["holds"]:
            print(f"  The rate stops near {l2['ceiling']:.2f}, not near 1. Under the two-state")
            print("  reading that ceiling IS S: the chance a preemption residual outlasts the")
            print("  true transport. It is a measured quantity, not a fitted asymptote.")

    # The header used to hard-code "PROVISIONAL", which was right until E-A6 ran both
    # geometries in one campaign. A caveat that cannot be retired is not a caveat, it is
    # boilerplate, so it now follows the data.
    print("\n== L3: geometry, not utilisation ==")
    l3 = law_geometry(pooled)
    if not l3["testable"]:
        print(f"  not testable: {l3['why']}")
    else:
        if l3["n_controlled"]:
            print(f"  CONTROLLED pairs, both geometries in ONE campaign at matched rho: "
                  f"{l3['n_controlled']}")
            for p in l3["controlled"]:
                mark = "spread worse" if p["spread_worse"] else "concentrated worse"
                fac = (p["inv_spread"] / p["inv_conc"]) if p["inv_conc"] else float("inf")
                print(f"    [{p['phase']}] rho {p['rho_spread']:.4f}/{p['rho_conc']:.4f}: "
                      f"spread {p['inv_spread']:.5f} vs conc {p['inv_conc']:.5f}  "
                      f"({fac:.2f}x, {mark})")
        print(f"  other matched pairs (|d rho| <= 0.02, cross-campaign): "
              f"{l3['n_matched'] - l3['n_controlled']}")
        print(f"  DOMINATING pairs (spread at LOWER rho inverts MORE): {l3['n_dominating']}")
        for p in l3["dominating"]:
            print(f"    spread rho={p['rho_spread']:.4f} inv={p['inv_spread']:.5f}  beats  "
                  f"conc rho={p['rho_conc']:.4f} inv={p['inv_conc']:.5f}  "
                  f"({p['ratio']:.2f}x at lower load)")
        print(f"  -> {'SUPPORTED' if l3['holds'] else 'NOT SUPPORTED'}")
        if l3["holds"]:
            if l3["n_controlled"]:
                print(f"  {l3['controlled_spread_worse']}/{l3['n_controlled']} controlled pairs "
                      f"have spread load inverting more at the SAME utilisation.")
                print("  Same day, same machine, same protocol, only the arrangement of the")
                print("  load differing. Utilisation cannot be the variable: at matched rho it")
                print("  predicts one number and two are observed.")
            if l3["n_dominating"]:
                print("  A dominating pair is a contradiction rather than a majority vote: no")
                print("  monotone function of rho gives a higher rate at a lower rho and a")
                print("  lower rate at a higher one. One such pair refutes the whole family.")
        if l3["provisional"]:
            print("  PROVISIONAL: no single campaign has run both geometries, so every pair")
            print("  above carries the differences between two days as well.")

    rows, occ = ([], {"valid": False})
    if l1.get("testable") and l2.get("testable"):
        rows, occ = implied_occupancy(pooled, l1["floor"], l2["ceiling"])
        print("\n== occupancy implied by L1 and L2 ==")
        if not occ["valid"]:
            print(f"  cannot invert: {occ['why']}")
        else:
            print(f"  p within [0,1]: {occ['in_range']}/{occ['n']}"
                  f"   {'all' if occ['all_in_range'] else 'NOT all -- the decomposition leaks'}")
            print(f"  median p, low-load half {occ['low_half']:.3f} vs high-load half "
                  f"{occ['high_half']:.3f}  -> {'monotone' if occ['monotone'] else 'NOT monotone'}")
            print("  p is inferred here, not measured. It is a consistency check on the")
            print("  decomposition; it is not independent evidence for it.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "occupancy_law.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["law", "holds", "detail"])
        w.writerow(["L1_floor_is_idle", l1.get("holds"),
                    f"idle={l1.get('idle')};floor={l1.get('floor')};ratio={l1.get('ratio')}"])
        w.writerow(["L2_ceiling_below_one", l2.get("holds"),
                    f"ceiling={l2.get('ceiling')};consistency={l2.get('consistency')}"])
        w.writerow(["L3_geometry_provisional", l3.get("holds"),
                    f"spread_worse={l3.get('spread_worse')}/{l3.get('n')}"])
    if rows:
        with (out / "implied_occupancy.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["phase", "condition", "rho", "geometry",
                                               "inversion", "p"])
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in w.fieldnames})
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
