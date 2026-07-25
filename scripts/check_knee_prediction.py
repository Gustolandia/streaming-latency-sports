#!/usr/bin/env python3
"""
check_knee_prediction.py
Score the pre-registered load-dependence predictions against the knee sweep that tested them.

This is a different kind of evidence from analyze_knee.py. That script FITS candidate forms to
the new data and asks which fits best, which is a comparison made after seeing the answer. This
script takes predictions committed to the repository BEFORE the sweep produced a single point
(docs/results/model/two_state_prediction.csv, written by fit_two_state.py from the old ladder)
and asks whether they came true. A form that fits after the fact and a form that predicted the
value in advance are not equally credible, and only the second is worth much here, because the
paper's whole complaint against its own earlier M/G/1 claim was that the test could not fail.

WHAT THE PREDICTIONS ARE. Each is a multiplier on the inversion rate relative to a base
condition near rho = 0.88, the top of the old ladder:

    M/G/1        rate proportional to rho/(1-rho): x13.8 at rho = 0.99. Unbounded.
    two-state    rate = p(rho) * S(T_true/sigma(rho)), both factors bounded: x2.45-3.07.
                 Reported as a bracket because sigma is measured rather than modelled --
                 the low edge freezes sigma, the high edge lets the residual term saturate.

HONEST LIMIT, STATED BEFORE THE RESULT. The two-state bracket and a fitted exponential in rho
overlap almost completely. This test can therefore separate M/G/1 from both, but it CANNOT
separate the two-state account from an exponential. What the two-state model contributes there
is a mechanism for why an exponential fits at all, not a better curve, and the output says so
rather than letting a passing score be read as confirmation.

RE-ANCHORING. The prediction was normalised at rho = 0.8775, the old ladder's top point. The new
sweep's closest condition is used as the base instead, and the substitution is reported, because
a multiplier means nothing without the point it multiplies.

CLI:
    python scripts/check_knee_prediction.py --prediction docs/results/model/two_state_prediction.csv \
        --observed docs/results/model/knee_points.csv --out docs/results/model
"""
import argparse
import csv
from pathlib import Path

BASE_TOLERANCE = 0.02    # the re-anchor point must lie this close to the prediction's base

# How close an observed rho must sit to a predicted one to be scored against it. The duty-cycle
# ladder lands on 0.8812 / 0.9204 / 0.9501 / 0.9701 / 0.9900, so 0.95 and 0.99 are hit almost
# exactly and only 0.90 is off, by about 0.02.
#
# The mismatch is not neutral and the direction is worth stating: scoring the observation at
# rho = 0.9204 against a prediction made for rho = 0.90 compares a rate measured under MORE load
# against a prediction for less, which inflates the observed multiplier. That pushes it toward
# the top of the bounded band and out of it -- against the two-state account, not for it. The
# comparison is therefore conservative for the model this repository proposes.
MATCH_TOLERANCE = 0.025


def load_prediction(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append({"rho": float(r["rho"]), "lo": float(r["two_state_lo"]),
                             "hi": float(r["two_state_hi"]), "mg1": float(r["mg1"])})
            except (KeyError, ValueError, TypeError):
                continue
    rows.sort(key=lambda x: x["rho"])
    return rows


def load_observed(path):
    """Read (rho, inversion rate) from the knee sweep, dropping unusable cells."""
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                rho, inv = float(r["rho"]), float(r["inversion"])
            except (KeyError, ValueError, TypeError):
                continue
            if 0 < rho < 0.999 and inv > 0:
                rows.append({"rho": rho, "inversion": inv,
                             "condition": r.get("condition", "")})
    rows.sort(key=lambda x: x["rho"])
    return rows


def pick_base(observed, target=0.8775):
    """The observed condition nearest the prediction's normalising point."""
    if not observed:
        return None
    return min(observed, key=lambda r: abs(r["rho"] - target))


def score(prediction, observed, base):
    """One row per predicted rho that the sweep actually reached.

    The base condition is excluded from matching. It is the normalising point, so its multiplier
    is 1.0 by construction and carries no information -- but it sits at rho = 0.8812, which is
    nearer the 0.90 prediction than the 0.9204 cell is. Left in, it would silently score every
    model against a value that cannot discriminate anything and report agreement wherever a
    prediction happened to sit near 1.
    """
    candidates = [r for r in observed if r is not base]
    out = []
    for p in prediction:
        if not candidates:
            out.append({"rho": p["rho"], "observed_rho": None, "observed_mult": None,
                        "two_state_lo": p["lo"], "two_state_hi": p["hi"], "mg1": p["mg1"],
                        "in_two_state": None, "mg1_error": None, "reached": False})
            continue
        match = min(candidates, key=lambda r: abs(r["rho"] - p["rho"]))
        if abs(match["rho"] - p["rho"]) > MATCH_TOLERANCE:
            out.append({"rho": p["rho"], "observed_rho": None, "observed_mult": None,
                        "two_state_lo": p["lo"], "two_state_hi": p["hi"], "mg1": p["mg1"],
                        "in_two_state": None, "mg1_error": None, "reached": False})
            continue
        mult = match["inversion"] / base["inversion"]
        out.append({"rho": p["rho"], "observed_rho": match["rho"], "observed_mult": mult,
                    "two_state_lo": p["lo"], "two_state_hi": p["hi"], "mg1": p["mg1"],
                    "in_two_state": p["lo"] <= mult <= p["hi"],
                    "mg1_error": abs(mult - p["mg1"]) / p["mg1"],
                    "reached": True})
    return out


def verdict(rows):
    """Which prediction survived. Both can fail; that outcome has its own branch."""
    scored = [r for r in rows if r["reached"]]
    if not scored:
        return {"decided": False, "why": "the sweep reached none of the predicted conditions",
                "two_state_held": None, "mg1_held": None}
    ts = sum(1 for r in scored if r["in_two_state"])
    # M/G/1 counts as holding where the observed multiplier is within half its prediction --
    # a generous band, since the point of the comparison is an order-of-magnitude split.
    mg = sum(1 for r in scored if r["mg1_error"] <= 0.5)
    return {"decided": True, "n": len(scored), "two_state_hits": ts, "mg1_hits": mg,
            "two_state_held": ts == len(scored), "mg1_held": mg == len(scored),
            "why": ""}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prediction", default="docs/results/model/two_state_prediction.csv")
    ap.add_argument("--observed", default="docs/results/model/knee_points.csv")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    for p in (args.prediction, args.observed):
        if not Path(p).exists():
            print(f"missing input: {p}")
            return 1
    prediction = load_prediction(args.prediction)
    observed = load_observed(args.observed)
    if not prediction or not observed:
        print("prediction or observation file has no usable rows")
        return 1

    base = pick_base(observed)
    print(f"base condition: rho = {base['rho']:.4f}, inversion = {base['inversion']:.5f}")
    if abs(base["rho"] - 0.8775) > BASE_TOLERANCE:
        print(f"  NOTE: re-anchored from the prediction's rho = 0.8775; the multipliers below")
        print(f"  are relative to {base['rho']:.4f} instead, which is not exactly what was")
        print(f"  predicted. Treat the comparison as indicative rather than exact.")

    rows = score(prediction, observed, base)
    print("\n== pre-registered multipliers against what happened ==")
    print(f"  {'rho':>6} {'observed':>10} {'two-state':>16} {'M/G/1':>9}   verdict")
    for r in rows:
        if not r["reached"]:
            print(f"  {r['rho']:>6.2f} {'not reached':>10}")
            continue
        band = f"{r['two_state_lo']:.2f}-{r['two_state_hi']:.2f}"
        mark = "in band" if r["in_two_state"] else "OUTSIDE band"
        print(f"  {r['rho']:>6.2f} {r['observed_mult']:>10.2f} {band:>16} "
              f"{r['mg1']:>9.2f}   {mark}")

    v = verdict(rows)
    print("\n== verdict ==")
    if not v["decided"]:
        print(f"UNDECIDED: {v['why']}")
    else:
        print(f"two-state bracket: {v['two_state_hits']}/{v['n']} conditions inside")
        print(f"M/G/1 (within 50%): {v['mg1_hits']}/{v['n']} conditions")
        if v["two_state_held"] and not v["mg1_held"]:
            print("\nThe bounded prediction held where the divergent one did not.")
            print("This is a prediction made before the data existed, not a fit after it.")
            print("It does NOT separate the two-state account from a fitted exponential:")
            print("their predictions overlap across this whole range. What it rules out is")
            print("the unbounded M/G/1 growth, which is the form the paper withdrew.")
        elif v["mg1_held"] and not v["two_state_held"]:
            print("\nM/G/1 held and the bounded prediction failed. The two-state account is")
            print("contradicted on the load axis and must be withdrawn there.")
        elif v["two_state_held"] and v["mg1_held"]:
            print("\nBoth survive: the sweep did not separate them after all.")
        else:
            print("\nNEITHER prediction held. Both accounts are wrong about the load axis,")
            print("and that is the result to report rather than the nearer miss.")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "knee_prediction_check.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["rho", "observed_rho", "observed_mult",
                                           "two_state_lo", "two_state_hi", "mg1",
                                           "in_two_state", "mg1_error", "reached"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
