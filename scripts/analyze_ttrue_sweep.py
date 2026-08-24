#!/usr/bin/env python3
"""
analyze_ttrue_sweep.py
E-A10: lengthen the true transport, and watch the inversion rate fall.

The mechanism reads P(inversion) = P(scheduling stall > T_true). Load, scheduling priority and
load geometry all move the LEFT side. Only this campaign moves the right side, and it does so
without touching the scheduler: padding the payload adds serialisation and transfer time, so
T_true grows while the machine's scheduling behaviour is left alone.

It matters that this is the last route available. Two earlier attempts on this axis failed for
structurally similar reasons, and both failures are instructive rather than embarrassing:

  netem at the broker     delayed the acknowledgement path and the delivery path equally, so it
                          cancelled in the difference that defines transport.
  co-locating the broker  removed the network hop but added CPU contention, which lengthened
                          transport again. Measured: 0.512 -> 0.573 ms, the wrong direction.

Padding avoids both because it acts on the measured interval directly rather than on a component
of it, and it adds work to the message rather than to the machine.

THE PREDICTION HAS THE AWKWARD SIGN. Bigger messages make everything slower, and the inversion
rate should FALL. Any account in which inversions track how hard the system is working predicts
the opposite, because larger payloads mean more work per event. The two differ in sign, which is
hard to obtain by accident.

THE MANIPULATION CHECK COMES FIRST AND CAN VETO EVERYTHING. If median transport does not rise
with pad size, padding did not act on T_true and the inversion rates say nothing about it -- the
same precondition that made E-A8 report UNDECIDED rather than a spurious finding. Given that two
of three attempts on this axis have already failed, this check is the most important line here.

THE CONFOUND RUNS AGAINST THE PREDICTION, which is the safe direction. Serialising a larger
payload costs CPU, raising load and pushing the inversion rate UP. So a confounded experiment
would weaken the predicted effect, never manufacture it.

CLI:
    python scripts/analyze_ttrue_sweep.py --depth docs/results/depth/ea10 \
        --runs runs --out docs/results/model
"""
import argparse
import csv
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_collapse import condition_stats, wilson_interval  # noqa: E402

MIN_TRANSPORT_RISE = 1.5   # largest pad must lengthen transport by at least this, or no test
RHO_TOLERANCE = 0.08       # cells differing more than this in load are not comparable


def load_cells(depth, runs_dir):
    """One row per pad size, ordered by pad. Cells without usable runs are dropped."""
    rows = []
    for d in sorted(Path(depth).glob("pad*")):
        if not d.is_dir():
            continue
        m = re.match(r"^pad(\d+)$", d.name)
        if not m:
            continue
        s = condition_stats(str(d), runs_dir)
        if s is None:
            continue
        n = s["n_events"]
        p = s["tails"][0.0]
        lo, hi = wilson_interval(round(p * n), n)
        rows.append({"pad_bytes": int(m.group(1)), "rho": s["rho"],
                     "transport_ms": s["mu"], "inversion": p,
                     "ci_lo": lo, "ci_hi": hi, "n_events": n})
    return sorted(rows, key=lambda r: r["pad_bytes"])


def manipulation_check(rows):
    """Did padding actually lengthen the true transport?

    Judged on the endpoints rather than on strict monotonicity: intermediate cells carry run to
    run variation, and demanding a perfectly ordered sequence would fail a real effect for
    noise. What must hold is that the largest payload is materially slower than the smallest.
    """
    if len(rows) < 2:
        return {"ok": False, "why": "need at least two pad sizes"}
    base, top = rows[0], rows[-1]
    rise = (top["transport_ms"] / base["transport_ms"]) if base["transport_ms"] > 0 else 0.0
    rhos = [r["rho"] for r in rows if r["rho"] is not None]
    spread = (max(rhos) - min(rhos)) if rhos else None
    if spread is not None and spread > RHO_TOLERANCE:
        return {"ok": False, "rise": rise, "rho_spread": spread,
                "why": (f"utilisation drifts {spread:.3f} across the sweep; padding moved load "
                        "as well as T_true and the cells are not comparable")}
    if rise < MIN_TRANSPORT_RISE:
        return {"ok": False, "rise": rise, "rho_spread": spread,
                "why": (f"padding lengthened transport only {rise:.2f}x "
                        f"({base['transport_ms']:.4f} -> {top['transport_ms']:.4f} ms); it did "
                        "not act on T_true, so the inversion rates say nothing about it")}
    return {"ok": True, "rise": rise, "rho_spread": spread,
            "base_ms": base["transport_ms"], "top_ms": top["transport_ms"]}


def verdict(rows, check):
    """Did the inversion rate fall as T_true grew?"""
    if not check.get("ok"):
        return {"decided": False, "why": check.get("why", "manipulation check failed")}
    base, top = rows[0], rows[-1]
    if base["inversion"] <= 0:
        return {"decided": False, "why": "no inversions at the smallest payload to compare"}
    ratio = top["inversion"] / base["inversion"]
    disjoint = top["ci_hi"] < base["ci_lo"] or base["ci_hi"] < top["ci_lo"]
    return {"decided": True, "ratio": ratio, "disjoint": disjoint,
            "transport_rise": check["rise"],
            "supports": ratio < 1.0 and disjoint,
            "opposite": ratio > 1.0 and disjoint,
            "no_change": not disjoint}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--depth", default="docs/results/depth/ea10")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.depth).is_dir():
        print(f"missing campaign directory: {args.depth}")
        return 1
    rows = load_cells(args.depth, args.runs)
    if len(rows) < 2:
        print("need at least two pad sizes with usable runs")
        return 1

    print("== the sweep ==")
    print(f"  {'pad':>8} {'rho':>7} {'transport':>10} {'inversion':>10} {'events':>8}")
    for r in rows:
        rho = "n/a" if r["rho"] is None else f"{r['rho']:.4f}"
        print(f"  {r['pad_bytes']:>8} {rho:>7} {r['transport_ms']:>10.4f} "
              f"{r['inversion']:>10.5f} {r['n_events']:>8}")

    check = manipulation_check(rows)
    print("\n== manipulation check: did padding lengthen T_true? ==")
    if check["ok"]:
        print(f"  transport {check['base_ms']:.4f} -> {check['top_ms']:.4f} ms "
              f"({check['rise']:.2f}x)   [ok]")
        if check["rho_spread"] is not None:
            print(f"  utilisation spread across the sweep: {check['rho_spread']:.3f}")
    else:
        print(f"  FAILED: {check['why']}")

    v = verdict(rows, check)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
        print("  This axis has now resisted three manipulations -- netem cancelled in the")
        print("  subtraction, co-location traded network delay for CPU contention, and this.")
        print("  That difficulty is itself a reportable property of the measurement.")
    else:
        print(f"  transport rose {v['transport_rise']:.2f}x, inversion rate moved "
              f"{v['ratio']:.2f}x   intervals {'disjoint' if v['disjoint'] else 'overlap'}")
        if v["supports"]:
            print("\nMECHANISM SUPPORTED ON A SIGN NOTHING ELSE PREDICTS.")
            print("  A slower path is a MORE reliable measurement: the same stall distribution")
            print("  now has a longer interval to outrun. An account in which inversions track")
            print("  system stress predicts the opposite, since bigger payloads are more work.")
        elif v["opposite"]:
            print("\nOPPOSITE SIGN: lengthening transport RAISED the inversion rate.")
            print("  That contradicts P(stall > T_true). Either the padding's own CPU cost")
            print("  dominates, or the mechanism is wrong; both need saying.")
        else:
            print("\nNO SIGNIFICANT CHANGE. T_true moved and the inversion rate did not,")
            print("  which the mechanism does not permit.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "ttrue_sweep.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
