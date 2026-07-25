#!/usr/bin/env python3
"""
analyze_knee.py
The pre-registered analysis for E-A4, the knee-resolution sweep (referee issue M4).

We withdrew the M/G/1 functional form because a fitted exponential matched our data as well or
better. That withdrawal reflects our sampling, not necessarily the mechanism: the two forms are
nearly indistinguishable below rho = 0.9 and diverge sharply above it (about eightfold at
rho = 0.99), and our ladder had no points above 0.878. E-A4 places conditions in that interval
using duty-cycled background load.

This script pools the old and new conditions on the ACHIEVED utilisation, refits M/G/1 against
both fitted alternatives, and applies the rule fixed before the run:

  * M/G/1 beats the power law AND the exponential, by more than the margin we treat as noise
    -> the functional form is RESTORED, and we report it as restored by measurement after having
       been withdrawn.
  * otherwise -> the withdrawal STANDS, and we report that the shape is not resolvable even with
       points placed where the forms disagree most.

The margin matters. With a handful of conditions a hair's-breadth win is not evidence, so a
minimum R^2 margin is required rather than a bare inequality.

CLI:
    python scripts/analyze_knee.py --depth-dir docs/results/depth --runs-dir runs \
        --out docs/results/model
"""
import argparse
import csv
import glob
import os
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measurement_model import fit_mg1, spearman  # noqa: E402

# A win smaller than this in R^2 is not a discrimination, it is noise.
MARGIN = 0.02
# A loss this large is not 'we could not tell': the sweep reached the interval where the
# forms diverge and M/G/1 came last. Reported as a refutation rather than a null.
DECISIVE_LOSS = 0.20


def condition_timestamp(cond_dir):
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def median_rho(cond_dir):
    u = os.path.join(cond_dir, "utilisation.csv")
    if not os.path.exists(u):
        return None
    vals = []
    with open(u, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                vals.append(float(r["rho"]))
            except (KeyError, TypeError, ValueError):
                continue
    return st.median(vals) if vals else None


def condition_inversion(cond_dir, runs_dir, backend="kafka"):
    ts = condition_timestamp(cond_dir)
    if not ts:
        return None
    neg = tot = 0
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
        prod = os.path.join(run, "producer.csv")
        cons = os.path.join(run, "consumer_events.csv")
        if not (os.path.exists(prod) and os.path.exists(cons)):
            continue
        ack = {}
        try:
            with open(prod, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    v = r.get("t_broker_ack_ns")
                    if v not in (None, "", "None"):
                        ack[r["event_id"]] = int(v)
            with open(cons, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    a = ack.get(r["event_id"])
                    rc = r.get("t_consume_ns")
                    if a is None or rc in (None, "", "None"):
                        continue
                    # Parse before counting. Incrementing the denominator and then failing to
                    # parse would leave an event in the total but out of the numerator, which
                    # silently biases the inversion rate downward.
                    delta = int(rc) - a
                    tot += 1
                    if delta < 0:
                        neg += 1
        except (ValueError, KeyError, OSError):
            continue
    return (neg / tot) if tot else None


def collect(depth_dir, runs_dir, phases):
    """(rho, inversion rate) for every usable condition across the named phases."""
    rows = []
    for phase in phases:
        for cond in sorted(glob.glob(os.path.join(depth_dir, phase, "*"))):
            if not os.path.isdir(cond):
                continue
            rho = median_rho(cond)
            inv = condition_inversion(cond, runs_dir)
            if rho is not None and inv is not None:
                rows.append({"phase": phase, "condition": os.path.basename(cond),
                             "rho": round(rho, 4), "inversion_rate": round(inv, 5)})
    return sorted(rows, key=lambda r: r["rho"])


def coverage(rows, threshold=0.90):
    """Did we actually get points where the forms disagree? A precondition, not a result."""
    high = [r for r in rows if threshold <= r["rho"] < 1.0]
    return {"n_high": len(high), "max_rho": max((r["rho"] for r in rows), default=float("nan")),
            "sufficient": len(high) >= 2}


def verdict(rows, margin=MARGIN):
    usable = [r for r in rows if 0.0 < r["rho"] < 1.0]
    cov = coverage(usable)
    fit = fit_mg1([r["rho"] for r in usable], [r["inversion_rate"] for r in usable])
    rho_s = spearman([r["rho"] for r in usable], [r["inversion_rate"] for r in usable])
    best = fit["r2_best_alternative"]
    decisive = (not any(v != v for v in (fit["r2_mg1"], best))  # NaN check
                and fit["r2_mg1"] - best >= margin)
    if not cov["sufficient"]:
        return {"restored": False, "reason": (
            f"only {cov['n_high']} condition(s) above rho=0.90 (max {cov['max_rho']}): the sweep "
            f"did not reach the interval where the forms disagree, so it cannot discriminate"),
            "coverage": cov, "fit": fit, "spearman": rho_s}
    if decisive:
        return {"restored": True, "reason": (
            f"with points up to rho={cov['max_rho']}, M/G/1 beats the best alternative "
            f"({fit['best_alternative']}) by {fit['r2_mg1'] - best:.3f} in R^2, above the "
            f"{margin} margin"), "coverage": cov, "fit": fit, "spearman": rho_s}
    # Two very different outcomes both fail the restoration rule, and reporting them with one
    # sentence would understate the stronger one. "Indistinguishable" was the pre-sweep situation:
    # too few points above rho=0.90 for the forms to separate. Once the sweep DOES reach that
    # interval and M/G/1 loses by a wide margin, the forms have been distinguished -- against
    # M/G/1. Saying "indistinguishable" there would be a weaker and less accurate claim than the
    # data supports, in our own favour, which is the direction that most needs guarding.
    if best - fit["r2_mg1"] >= DECISIVE_LOSS:
        return {"restored": False, "refuted": True, "reason": (
            f"M/G/1 R^2 {fit['r2_mg1']:.3f} against {fit['best_alternative']} {best:.3f}: with "
            f"points up to rho={cov['max_rho']} the forms ARE now distinguished, and M/G/1 is "
            f"the one refuted -- it fits worse than the alternative by "
            f"{best - fit['r2_mg1']:.3f} in R^2 where the two should diverge most"),
            "coverage": cov, "fit": fit, "spearman": rho_s}
    return {"restored": False, "refuted": False, "reason": (
        f"M/G/1 R^2 {fit['r2_mg1']:.3f} against {fit['best_alternative']} {best:.3f}: margin "
        f"{fit['r2_mg1'] - best:+.3f} does not exceed {margin}, so the forms remain "
        f"indistinguishable even where they should diverge"),
        "coverage": cov, "fit": fit, "spearman": rho_s}


def main(argv=None):
    ap = argparse.ArgumentParser(description="E-A4: can the knee discriminate the form?")
    ap.add_argument("--depth-dir", default="docs/results/depth")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--phases", default="ea_sat,ea_knee,ea3,ea4")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    phases = [p for p in args.phases.split(",") if p]
    rows = collect(args.depth_dir, args.runs_dir, phases)
    if len(rows) < 4:
        print(f"insufficient conditions ({len(rows)}) to fit a shape")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "knee_resolution.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["phase", "condition", "rho", "inversion_rate"])
        w.writeheader()
        w.writerows(rows)

    print("== E-A4: pooled utilisation ladder ==")
    for r in rows:
        marker = "  <- new" if r["phase"] == "ea4" else ""
        print(f"  rho={r['rho']:.4f}  inversion={r['inversion_rate']:.5f}  "
              f"({r['phase']}/{r['condition']}){marker}")

    v = verdict(rows)
    f = v["fit"]
    print(f"\n  points above rho=0.90: {v['coverage']['n_high']}  (max rho {v['coverage']['max_rho']})")
    print(f"  R^2  M/G/1 {f['r2_mg1']:.4f} | linear {f['r2_linear']:.4f} | "
          f"power {f['r2_power']:.4f} | exponential {f['r2_exponential']:.4f}")
    print(f"  rank correlation with utilisation: {v['spearman']:.3f}")
    print(f"\n== FUNCTIONAL FORM: {'RESTORED' if v['restored'] else 'WITHDRAWAL STANDS'} ==")
    print(f"  {v['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
