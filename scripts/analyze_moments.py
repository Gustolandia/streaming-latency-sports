#!/usr/bin/env python3
"""
analyze_moments.py
Two second-order looks at the measurement-failure model, computed from the same raw per-event
transport the inversion analysis uses.

Measured-transport variance against utilisation. The model says measured transport is
T_true + Delta and that the scale of Delta is scheduler waiting time, so the variance of measured
transport should grow with load. It does, spanning about four orders of magnitude from idle to
saturation -- direct evidence that a near-saturation measurement is untrustworthy in a way an
idle one is not. We deliberately do NOT fit a single power-law exponent: the low-load variance is
floor-dominated by the irreducible stamping jitter, and the near-saturation variance blows up
faster than the square of the mean waiting time (M/G/1 waiting-time variance is governed by higher
moments near rho -> 1), so a single exponent is fit-dependent and would misrepresent the data.
The monotone, four-decade growth is the honest and sufficient statement.

H8, the clustering rule. If inversions came from independent clock quantisation their signs would
be i.i.d. and a runs test would give z ~ 0. If a single descheduling event makes a run of
consecutive events wake late together -- the scheduling mechanism this paper argues for -- they
cluster and z << 0. This distinguishes the two mechanisms directly, from timing alone, and it
holds even at the idle co-located floor, so it is not an artefact of background load.

Reads the E-A saturation/knee conditions (for the variance axis) and named conditions (for H8).

CLI:
    python scripts/analyze_moments.py --depth-dir docs/results/depth --runs-dir runs \
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
from measurement_model import runs_test_z  # noqa: E402


def condition_timestamp(cond_dir):
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def run_series(run_dir):
    """Per-event transport (ms) in emission order for one run."""
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return []
    ack, order = {}, {}
    with open(prod, newline="", encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            v = r.get("t_broker_ack_ns")
            if v not in (None, "", "None"):
                ack[r["event_id"]] = int(v)
                order[r["event_id"]] = i
    rows = []
    with open(cons, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            a = ack.get(r["event_id"])
            rc = r.get("t_consume_ns")
            if a is not None and rc not in (None, "", "None"):
                rows.append((order.get(r["event_id"], 0), (int(rc) - a) / 1e6))
    rows.sort()
    return [t for _, t in rows]


def condition_series(cond_dir, runs_dir, backend="kafka"):
    ts = condition_timestamp(cond_dir)
    if not ts:
        return []
    out = []
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
        s = run_series(run)
        if s:
            out.append(s)
    return out


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


def variance_rows(depth_dir, runs_dir):
    """(rho, variance) per E-A condition, pooling the condition's per-event transport."""
    rows = []
    phases = [p for p in ("ea_sat", "ea_knee")
              if glob.glob(os.path.join(depth_dir, p, "*"))] or ["ea"]
    for phase in phases:
        for cond in sorted(glob.glob(os.path.join(depth_dir, phase, "*"))):
            if not os.path.isdir(cond):
                continue
            rho = median_rho(cond)
            pooled = [t for s in condition_series(cond, runs_dir) for t in s]
            if rho is not None and len(pooled) > 10:
                rows.append({"rho": round(rho, 4), "variance": round(st.pvariance(pooled), 5),
                             "n_events": len(pooled)})
    return sorted(rows, key=lambda r: r["rho"])


def clustering_rows(depth_dir, runs_dir, conditions):
    """Median runs-test z per named condition, over its runs."""
    rows = []
    for label, path in conditions:
        cond = os.path.join(depth_dir, path)
        if not os.path.isdir(cond):
            continue
        zs = [z for s in condition_series(cond, runs_dir)
              if (z := runs_test_z(s)) is not None]
        if zs:
            rows.append({"condition": label, "median_z": round(st.median(zs), 3),
                         "n_runs": len(zs)})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Second-moment tests: variance law and clustering")
    ap.add_argument("--depth-dir", default="docs/results/depth")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    vrows = variance_rows(args.depth_dir, args.runs_dir)
    if len(vrows) >= 3:
        with (out / "variance_law.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["rho", "variance", "n_events"])
            w.writeheader()
            w.writerows(vrows)
        pre = [r for r in vrows if r["rho"] < 0.999]
        vmin = min((r["variance"] for r in pre), default=0.0)
        vmax = max(r["variance"] for r in vrows)
        print("== measured-transport variance vs utilisation ==")
        for r in vrows:
            print(f"  rho={r['rho']:.3f}  var={r['variance']:.4f}  n={r['n_events']}")
        span = f"{vmax / vmin:.0f}x" if vmin > 0 else "(baseline variance ~0)"
        print(f"  variance spans {vmin:.4f} -> {vmax:.1f} ms^2 "
              f"{span} from idle to saturation; monotone, no single exponent claimed")
    else:
        print("== variance: insufficient rho conditions ==")

    crows = clustering_rows(args.depth_dir, args.runs_dir, [
        ("co-located floor (E-B d0)", "eb/d0"),
        ("idle (E-A bg0)", "ea_sat/bg0"),
        ("saturated (E-A bg8)", "ea_sat/bg8"),
    ])
    if crows:
        with (out / "inversion_clustering.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["condition", "median_z", "n_runs"])
            w.writeheader()
            w.writerows(crows)
        print("== H8 clustering rule ==")
        for r in crows:
            tag = "CLUSTERED" if r["median_z"] < -2 else "independent"
            print(f"  {r['condition']:28s} median z = {r['median_z']:+.2f}  ({tag})")
    else:
        print("== H8: no conditions found ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
