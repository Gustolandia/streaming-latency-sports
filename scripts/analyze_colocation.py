#!/usr/bin/env python3
"""
analyze_colocation.py
E-A8: shrink T_true by removing the network, and see the inversion rate go UP.

The mechanism now reads P(inversion) = P(scheduling stall > T_true). Every manipulation before
this one moved the left-hand side -- load, scheduling priority, load geometry. Co-locating the
broker moves the RIGHT-hand side: it removes the network hop, so the true broker transport falls
several-fold, while the machine's scheduling behaviour is left alone.

THE PREDICTION HAS AN AWKWARD SIGN, WHICH IS WHY IT IS WORTH TESTING.

    co-located   T_true DOWN   ->   inversion rate UP
    remote       T_true UP     ->   inversion rate DOWN

A faster path is a LESS reliable measurement, because the same stall distribution now has a
smaller interval to outrun. Any account in which inversions track how hard the system is working
predicts no change here, since the load is identical; any intuition that "faster is safer"
predicts the opposite sign. Sign is hard to obtain by accident, which is what makes this a test
rather than an illustration.

WHAT IS MEASURED RATHER THAN ASSUMED. The idle co-located cell is the best estimate of T_true
this testbed can produce: one host, one clock, no network, and a stamping thread that is almost
never preempted (the measured floor there is the idle inversion rate, about 0.4%). Everything
else is compared against it.

THE CONFOUND PUSHES THE SAME WAY AS THE EFFECT, so it is checked rather than mentioned. Running
Kafka and Redis on the driver adds CPU to the machine whose scheduling we are measuring, which
raises the inversion rate for a reason that has nothing to do with T_true. Two defences:

  * utilisation is compared across arms and the comparison is WITHHELD if it moved materially;
  * the IDLE pair is primary. At 0.415 events per second the brokers do almost no work, so the
    load difference there is small and the T_true contrast is nearly clean. The loaded pair is
    reported as secondary and is expected to be the dirtier of the two.

CLI:
    python scripts/analyze_colocation.py --depth docs/results/depth/ea8 \
        --runs runs --out docs/results/model
"""
import argparse
import csv
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_collapse import condition_stats, wilson_interval  # noqa: E402

RHO_TOLERANCE = 0.05      # arms differing by more than this are confounded, not comparable
MIN_TRANSPORT_FALL = 1.5  # co-location must actually shorten transport, or nothing follows


def load_cells(depth, runs_dir):
    """{load: {placement: stats}} for every <placement>_l<load> cell present."""
    out = {}
    for d in sorted(Path(depth).glob("*_l*")):
        if not d.is_dir():
            continue
        placement, _, load = d.name.rpartition("_l")
        if placement not in ("remote", "colocated"):
            continue
        s = condition_stats(str(d), runs_dir)
        if s:
            out.setdefault(load, {})[placement] = s
    return {k: v for k, v in out.items() if set(v) == {"remote", "colocated"}}


def compare(load, arms):
    """One load level. mu is the median measured transport, our best handle on T_true."""
    rem, col = arms["remote"], arms["colocated"]
    p_r, p_c = rem["tails"][0.0], col["tails"][0.0]
    n_r, n_c = rem["n_events"], col["n_events"]
    lo_r, hi_r = wilson_interval(round(p_r * n_r), n_r)
    lo_c, hi_c = wilson_interval(round(p_c * n_c), n_c)

    rho_r, rho_c = rem["rho"], col["rho"]
    confounded, why = False, ""
    if rho_r is None or rho_c is None:
        confounded, why = True, "utilisation not recorded in one or both arms"
    elif abs(rho_r - rho_c) > RHO_TOLERANCE:
        confounded = True
        why = (f"utilisation differs between arms ({rho_r:.3f} remote vs {rho_c:.3f} "
               f"co-located); co-location moved load as well as T_true")

    return {"load": load, "confounded": confounded, "why": why,
            "rho_remote": rho_r, "rho_colocated": rho_c,
            "t_remote_ms": rem["mu"], "t_colocated_ms": col["mu"],
            "transport_fall": (rem["mu"] / col["mu"]) if col["mu"] > 0 else float("inf"),
            "inv_remote": p_r, "inv_colocated": p_c,
            "inv_rise": (p_c / p_r) if p_r > 0 else float("inf"),
            "disjoint": hi_c < lo_r or hi_r < lo_c,
            "n_remote": n_r, "n_colocated": n_c}


def verdict(rows):
    """Did T_true fall, and did the inversion rate rise as a result?

    Judged on the IDLE level when one exists, because that is where the added broker CPU is
    smallest and the T_true contrast is cleanest. A loaded-only result is reported but flagged.
    """
    usable = [r for r in rows if not r["confounded"]]
    if not usable:
        return {"decided": False, "why": "no load level survived the utilisation check"}
    primary = next((r for r in usable if r["load"] == "0"), usable[0])
    if primary["transport_fall"] < MIN_TRANSPORT_FALL:
        return {"decided": False, "primary": primary["load"],
                "why": (f"co-location did not shorten transport "
                        f"({primary['transport_fall']:.2f}x); the manipulation did not act on "
                        f"T_true and nothing about the inversion rate follows")}
    rose = primary["inv_rise"] > 1.0 and primary["disjoint"]
    fell = primary["inv_rise"] < 1.0 and primary["disjoint"]
    return {"decided": True, "primary": primary["load"],
            "on_idle": primary["load"] == "0",
            "transport_fall": primary["transport_fall"],
            "inv_rise": primary["inv_rise"],
            "supports_mechanism": rose,
            "opposite_sign": fell,
            "no_change": not rose and not fell}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", default="docs/results/depth/ea8")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.depth).is_dir():
        print(f"missing campaign directory: {args.depth}")
        return 1
    cells = load_cells(args.depth, args.runs)
    if not cells:
        print("no load level has both a remote and a co-located arm")
        return 1
    rows = [compare(lv, cells[lv]) for lv in sorted(cells, key=lambda x: int(x))]

    print("== manipulation check: co-location must not also move the load ==")
    for r in rows:
        rr = "n/a" if r["rho_remote"] is None else f"{r['rho_remote']:.3f}"
        rc = "n/a" if r["rho_colocated"] is None else f"{r['rho_colocated']:.3f}"
        print(f"  load {r['load']}%: rho {rr} remote vs {rc} co-located"
              f"   [{'CONFOUNDED' if r['confounded'] else 'ok'}]")
        if r["confounded"]:
            print(f"      {r['why']}")

    print("\n== T_true and the inversion rate, which should move OPPOSITE ways ==")
    for r in rows:
        print(f"  load {r['load']}%:")
        print(f"      transport  {r['t_remote_ms']:.4f} -> {r['t_colocated_ms']:.4f} ms"
              f"   ({r['transport_fall']:.2f}x SHORTER co-located)")
        if r["confounded"]:
            print("      inversion  withheld: manipulation check failed")
        else:
            print(f"      inversion  {r['inv_remote']:.5f} -> {r['inv_colocated']:.5f}"
                  f"   ({r['inv_rise']:.2f}x)"
                  f"   intervals {'disjoint' if r['disjoint'] else 'overlap'}")

    v = verdict(rows)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
    else:
        scope = "idle" if v["on_idle"] else f"{v['primary']}% load (no idle pair available)"
        print(f"  judged on the {scope} pair")
        print(f"  transport fell {v['transport_fall']:.2f}x, "
              f"inversion rate moved {v['inv_rise']:.2f}x")
        if v["supports_mechanism"]:
            print("\nMECHANISM SUPPORTED, ON A SIGN NOTHING ELSE PREDICTS.")
            print("  A shorter true transport makes the measurement LESS reliable: the same")
            print("  stall distribution now has a smaller interval to outrun. Accounts in")
            print("  which inversions track system load predict no change here, because the")
            print("  load is unchanged; 'faster is safer' predicts the opposite sign.")
        elif v["opposite_sign"]:
            print("\nOPPOSITE SIGN: shortening transport LOWERED the inversion rate.")
            print("  That contradicts P(stall > T_true) and the mechanism must be reconsidered.")
        else:
            print("\nNO SIGNIFICANT CHANGE. T_true moved and the inversion rate did not,")
            print("  which the mechanism does not permit. Reported as it stands.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "colocation.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
