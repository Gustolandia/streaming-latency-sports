#!/usr/bin/env python3
"""
analyze_stamping_priority.py
E-A5: did raising the stamping threads' priority change the inversion rate at fixed utilisation?

The load ladder cannot answer this. There rho and the residual width sigma rise together, so no
fit can attribute the inversions to one rather than the other -- fit_two_state.py demonstrates
the collinearity and declines to claim a winner. E-A5 breaks it by moving occupancy alone.

Pre-registered readings, fixed before the campaign ran (cloud/campaigns/stamping_priority.sh):

    occupancy mechanism   the inversion rate falls by at least a factor of OCCUPANCY_FACTOR,
                          with non-overlapping Wilson intervals, while rho is unchanged.
    utilisation mechanism the rate is a function of rho; rho is unchanged by construction, so
                          the rate is unchanged -- ratio inside EQUIVALENCE_BAND.
    neither               a change too small to be the first and too large to be the second.
                          Reported as such rather than rounded toward whichever we prefer.

THE MANIPULATION CHECK RUNS FIRST AND CAN VETO THE RESULT. The design assumes real-time priority
leaves utilisation alone. E-B2 assumed something similar about netem, was wrong, and cost us a
campaign; so rho is measured in both arms and a discrepancy above MANIP_TOL withholds the
comparison instead of reporting it. A confounded cell yields no finding, not a hedged one.

CLI:
    python scripts/analyze_stamping_priority.py --depth docs/results/depth/ea5 \
        --runs runs --out docs/results/model
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_collapse import condition_stats, wilson_interval  # noqa: E402

MANIP_TOL = 0.05          # |rho_base - rho_rt| above this: confounded, withhold the comparison
OCCUPANCY_FACTOR = 3.0    # fall of at least this much, intervals disjoint: occupancy supported
EQUIVALENCE_BAND = (0.67, 1.5)   # ratio inside this: consistent with no change


def load_arms(depth_dir, runs_dir):
    """Pair the base and rt cells at each load level.

    Cell directories are named l<pct>_<arm>. A level with only one arm is dropped: it carries
    no contrast and including it would let a half-finished campaign look like a result.
    """
    levels, unpaired = {}, []
    for cond in sorted(Path(depth_dir).glob("l*_*")):
        if not cond.is_dir():
            continue
        name = cond.name
        level, _, arm = name.rpartition("_")
        if arm not in ("base", "rt"):
            continue
        s = condition_stats(str(cond), runs_dir)
        if s is None:
            continue
        levels.setdefault(level, {})[arm] = s
    for level in sorted(levels):
        if set(levels[level]) != {"base", "rt"}:
            unpaired.append(level)
    return {k: v for k, v in levels.items() if set(v) == {"base", "rt"}}, unpaired


def compare(level, arms):
    """One load level: manipulation check, then effect."""
    base, rt = arms["base"], arms["rt"]
    p_b = base["tails"][0.0]
    p_r = rt["tails"][0.0]
    n_b, n_r = base["n_events"], rt["n_events"]
    lo_b, hi_b = wilson_interval(round(p_b * n_b), n_b)
    lo_r, hi_r = wilson_interval(round(p_r * n_r), n_r)

    rho_b, rho_r = base["rho"], rt["rho"]
    if rho_b is None or rho_r is None:
        return {"level": level, "confounded": True,
                "why": "utilisation not recorded in one or both arms",
                "rho_base": rho_b, "rho_rt": rho_r, "inv_base": p_b, "inv_rt": p_r,
                "ratio": None, "disjoint": None, "n_base": n_b, "n_rt": n_r}
    if abs(rho_b - rho_r) > MANIP_TOL:
        return {"level": level, "confounded": True,
                "why": f"utilisation differs between arms ({rho_b:.3f} vs {rho_r:.3f}); the "
                       "manipulation moved load as well as occupancy",
                "rho_base": rho_b, "rho_rt": rho_r, "inv_base": p_b, "inv_rt": p_r,
                "ratio": None, "disjoint": None, "n_base": n_b, "n_rt": n_r}

    ratio = p_r / p_b if p_b > 0 else None
    return {"level": level, "confounded": False, "why": "",
            "rho_base": rho_b, "rho_rt": rho_r, "inv_base": p_b, "inv_rt": p_r,
            "ratio": ratio, "disjoint": hi_r < lo_b or hi_b < lo_r,
            "n_base": n_b, "n_rt": n_r}


def verdict(rows):
    """Which mechanism the levels support, or that they do not agree."""
    usable = [r for r in rows if not r["confounded"] and r["ratio"] is not None]
    if not usable:
        return {"decided": False,
                "why": "no level survived the manipulation check", "supports": None}
    occupancy = [r for r in usable
                 if r["ratio"] <= 1.0 / OCCUPANCY_FACTOR and r["disjoint"]]
    unchanged = [r for r in usable
                 if EQUIVALENCE_BAND[0] <= r["ratio"] <= EQUIVALENCE_BAND[1]]
    if len(occupancy) == len(usable):
        return {"decided": True, "supports": "occupancy",
                "why": "the inversion rate collapsed at every level while utilisation held"}
    if len(unchanged) == len(usable):
        return {"decided": True, "supports": "utilisation",
                "why": "the inversion rate did not move when only occupancy changed"}
    return {"decided": False, "supports": None,
            "why": "levels disagree, or the change is too small for one reading and too "
                   "large for the other"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", default="docs/results/depth/ea5")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.depth).is_dir():
        print(f"missing campaign directory: {args.depth}")
        return 1
    levels, unpaired = load_arms(args.depth, args.runs)
    for lv in unpaired:
        print(f"note: {lv} has only one arm; dropped")
    if not levels:
        print("no load level has both arms; nothing to compare")
        return 1

    rows = [compare(lv, levels[lv]) for lv in sorted(levels)]

    print("== manipulation check: utilisation must be equal across arms ==")
    for r in rows:
        if r["rho_base"] is None or r["rho_rt"] is None:
            print(f"  {r['level']}: utilisation missing")
        else:
            flag = "CONFOUNDED" if r["confounded"] else "ok"
            print(f"  {r['level']}: rho {r['rho_base']:.3f} (base) vs {r['rho_rt']:.3f} (rt)"
                  f"  [{flag}]")
        if r["confounded"]:
            print(f"      {r['why']}")

    print("\n== inversion rate, ordinary vs real-time stamping ==")
    for r in rows:
        line = (f"  {r['level']}: {r['inv_base']:.5f} (n={r['n_base']}) -> "
                f"{r['inv_rt']:.5f} (n={r['n_rt']})")
        if r["confounded"]:
            print(line + "   [withheld: manipulation check failed]")
        else:
            print(line + f"   ratio {r['ratio']:.3f}"
                         f"   intervals {'disjoint' if r['disjoint'] else 'overlap'}")

    v = verdict(rows)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
    elif v["supports"] == "occupancy":
        print("OCCUPANCY MECHANISM SUPPORTED")
        print(f"  {v['why']}.")
        print("  Utilisation-only models (M/G/1, exp(k rho)) predict no change here and are")
        print("  contradicted: rho was held fixed and the rate moved anyway.")
    else:
        print("UTILISATION MECHANISM SUPPORTED; the two-state occupancy account is contradicted")
        print(f"  {v['why']}.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "stamping_priority.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["level", "rho_base", "rho_rt", "inv_base", "inv_rt",
                                           "ratio", "disjoint", "n_base", "n_rt", "confounded"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in w.fieldnames})
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
