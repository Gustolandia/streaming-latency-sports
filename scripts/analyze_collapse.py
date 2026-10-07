#!/usr/bin/env python3
"""
analyze_collapse.py
The pre-registered analyses for the E-A3 collapse suite (docs/preregistration_depth.md, S4):

H9, the scale-family collapse. If Delta is a scale family across load, inversion probability
depends on the measured quantity only through the standardised distance z = T/sigma_core, so
per-condition standardised left tails coincide. Tested by bucketing (z, tail-mass) points from
every condition into z bands and measuring the spread within a band: one curve means small
spread; a mixture means the tail mass at matched z differs across load. The pilot on the earlier
corpus showed a ~25x spread, so falsification is the expected outcome, and it was pre-registered
as such.

H10, the mixture structure. Delta = a narrow core (stamping jitter) plus a rare heavy tail
(descheduling). Load should move the tail WEIGHT faster than the core WIDTH: from idle to the
knee the tail mass grows sharply while sigma_core barely moves, and inversions stay temporally
clustered (H8) at every load.

F-Delta reproduction. Recovering the left tail of Delta from inversion rates is circular against
the same events; the non-circular test is agreement between INDEPENDENT campaigns at matched
utilisation. Old corpus (ea_sat + ea_knee) against new (ea3), conditions matched on rho within
+/-0.05, tail masses compared with Wilson intervals -- and, since 27 September 2026, with
intervals that resample whole runs, because negative spans cluster within a run (H8) and an
interval over events treats them as independent draws. A run-level interval of the difference
is the direct test beside the overlap of the two.

CLI:
    python scripts/analyze_collapse.py --depth-dir docs/results/depth --runs-dir runs \
        --out docs/results/model
"""
import argparse
import csv
import glob
import math
import os
import random
import re
import statistics as st
import sys
import zlib
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measurement_model import runs_test_z  # noqa: E402
import stale_backlog  # noqa: E402

THRESHOLDS_MS = [0.0, 0.5, 1.0, 2.0, 5.0]

#: Resamples behind every run-level interval, and the seed they start from. Each condition, and
#: each compared pair, draws from its own stream (the seed plus a checksum of its name), so adding
#: a condition moves no other interval.
BOOT_DRAWS = 20000
BOOT_SEED = 20260927


# ---------------------------------------------------------------- raw data access
def condition_timestamp(cond_dir):
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def run_series(run_dir):
    """Per-event transport (ms) in emission order for one run.

    7 Oct 2026: without the messages the consumer received late behind a stale backlog, the
    ids stale_backlog.late_ids_in reads from the run's consumer.csv, as every reader of the July
    runs leaves them out. The Azure pilot's go-first check reads runs through here too; its
    runs cleared their streams, and it writes no result.
    """
    prod = os.path.join(run_dir, "producer.csv")
    cons = os.path.join(run_dir, "consumer_events.csv")
    if not (os.path.exists(prod) and os.path.exists(cons)):
        return []
    late = stale_backlog.late_ids_in(run_dir)
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
            if a is not None and rc not in (None, "", "None") and r["event_id"] not in late:
                rows.append((order.get(r["event_id"], 0), (int(rc) - a) / 1e6))
    rows.sort()
    return [t for _, t in rows]


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


def condition_stats(cond_dir, runs_dir, backend="kafka"):
    """Everything the three analyses need for one condition, or None if unusable."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return None
    series = []
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_{backend}_*")):
        s = run_series(run)
        if s:
            series.append(s)
    pooled = [t for s in series for t in s]
    if len(pooled) < 50:
        return None
    vs = sorted(pooled)
    mu = st.median(vs)
    q1, q3 = vs[len(vs) // 4], vs[3 * len(vs) // 4]
    sigma_core = (q3 - q1) / 1.349
    if sigma_core <= 0:
        sigma_core = st.pstdev(pooled) or float("nan")
    zs = [z for s in series if (z := runs_test_z(s)) is not None]
    return {
        "rho": median_rho(cond_dir),
        "n_events": len(pooled),
        "n_runs": len(series),
        "mu": mu,
        "sigma_core": sigma_core,
        "tails": {c: sum(1 for t in pooled if t < -c) / len(pooled) for c in THRESHOLDS_MS},
        "runs_z_median": st.median(zs) if zs else None,
        # Per run: its events, and how many fall past each threshold. The run-level intervals
        # resample these pairs, so a run's clustered negatives travel together.
        "run_counts": [(len(s), {c: sum(1 for t in s if t < -c) for c in THRESHOLDS_MS})
                       for s in series],
    }


def collect_phase(depth_dir, runs_dir, phases):
    out = {}
    for phase in phases:
        for cond in sorted(glob.glob(os.path.join(depth_dir, phase, "*"))):
            if os.path.isdir(cond):
                s = condition_stats(cond, runs_dir)
                if s:
                    out[f"{phase}/{os.path.basename(cond)}"] = s
    return out


# ---------------------------------------------------------------- statistics
def wilson_interval(k, n, z=1.6449):
    """90% Wilson score interval for a binomial proportion (z = Phi^-1(0.95))."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def _stream(name):
    return random.Random(BOOT_SEED + zlib.crc32(name.encode("utf-8")))


def _percentiles(values, level):
    values.sort()
    tail = (1 - level) / 2
    return values[int(tail * len(values))], values[int((1 - tail) * len(values)) - 1]


def run_intervals(run_counts, name, draws=BOOT_DRAWS, level=0.90):
    """Percentile intervals for a condition's pooled tail masses, resampling whole runs.

    Negative spans cluster within a run (the runs test), so a run's events are not independent
    draws and an interval over events is too narrow. This resamples the runs themselves. A
    threshold that no run reaches gets None rather than an interval: every resample of zeros is
    zero, and a zero-width interval would claim a certainty the runs do not give. The caller
    keeps Wilson's there, which does bound a zero.
    """
    rng, m = _stream(name), len(run_counts)
    samples = {c: [] for c in THRESHOLDS_MS}
    for _ in range(draws):
        pick = [run_counts[rng.randrange(m)] for _ in range(m)]
        n = sum(p[0] for p in pick)
        for c in THRESHOLDS_MS:
            samples[c].append(sum(p[1][c] for p in pick) / n)
    return {c: (_percentiles(v, level) if any(k[c] for _, k in run_counts) else None)
            for c, v in samples.items()}


def run_difference(new_counts, old_counts, c, name, draws=BOOT_DRAWS, level=0.90):
    """Percentile interval of new minus old tail mass at threshold `c`, resampling the runs of
    each campaign independently: the direct test of a difference, beside the overlap of the two
    intervals, which is the more lenient of the two."""
    rng, mn, mo = _stream(name), len(new_counts), len(old_counts)
    diffs = []
    for _ in range(draws):
        a = [new_counts[rng.randrange(mn)] for _ in range(mn)]
        b = [old_counts[rng.randrange(mo)] for _ in range(mo)]
        diffs.append(sum(p[1][c] for p in a) / sum(p[0] for p in a)
                     - sum(p[1][c] for p in b) / sum(p[0] for p in b))
    return _percentiles(diffs, level)


def collapse_points(stats_by_cond):
    """(z, tail_mass, condition) for every informative threshold of every condition."""
    pts = []
    for name, s in stats_by_cond.items():
        for c, mass in s["tails"].items():
            k = round(mass * s["n_events"])
            if 5 <= k < s["n_events"] // 2:      # informative: neither empty nor the median
                z = (s["mu"] + c) / s["sigma_core"]
                pts.append({"condition": name, "rho": s["rho"], "threshold_ms": c,
                            "z": round(z, 3), "tail_mass": round(mass, 5),
                            "n_events": s["n_events"]})
    return pts


def h9_verdict(points, band=1.0, max_ratio=3.0):
    """One curve, or a spread? Bucket by z and measure within-band spread across conditions."""
    bands = {}
    for p in points:
        bands.setdefault(int(p["z"] // band), {}).setdefault(p["condition"], []).append(
            p["tail_mass"])
    worst = 0.0
    worst_band = None
    for b, by_cond in bands.items():
        if len(by_cond) < 2:
            continue
        reps = [min(v) for v in by_cond.values()]
        lo, hi = min(reps), max(reps)
        if lo > 0 and hi / lo > worst:
            worst, worst_band = hi / lo, b
    if worst_band is None:
        return {"hypothesis": "H9 scale-family collapse", "testable": False,
                "supported": False, "worst_ratio": float("nan")}
    return {"hypothesis": "H9 scale-family collapse", "testable": True,
            "worst_ratio": round(worst, 2), "worst_band_z": worst_band,
            "supported": bool(worst <= max_ratio)}


def h10_verdict(stats_by_cond, knee_rho=(0.6, 0.95), growth_factor=3.0):
    """Tail weight must outgrow core width from idle to the knee, and clustering must persist."""
    usable = [s for s in stats_by_cond.values() if s["rho"] is not None]
    pre = [s for s in usable if s["rho"] < 0.3]
    knee = [s for s in usable if knee_rho[0] <= s["rho"] <= knee_rho[1]]
    if not pre or not knee:
        return {"hypothesis": "H10 mixture structure", "testable": False, "supported": False}
    idle = min(pre, key=lambda s: s["rho"])
    top = max(knee, key=lambda s: s["rho"])
    tail_growth = (top["tails"][0.0] / idle["tails"][0.0]) if idle["tails"][0.0] > 0 else float("inf")
    core_growth = top["sigma_core"] / idle["sigma_core"]
    zs = [s["runs_z_median"] for s in usable if s["runs_z_median"] is not None]
    clustered = bool(zs) and all(z < -2 for z in zs)
    ratio = tail_growth / core_growth if core_growth > 0 else float("inf")
    return {"hypothesis": "H10 mixture structure", "testable": True,
            "idle_rho": idle["rho"], "knee_rho": top["rho"],
            "tail_growth": round(tail_growth, 2), "core_growth": round(core_growth, 2),
            "ratio": round(ratio, 2), "clustered_everywhere": clustered,
            "supported": bool(ratio > growth_factor and clustered)}


def reproduction_rows(old_stats, new_stats, tol_rho=0.05, draws=BOOT_DRAWS):
    """Matched-rho tail comparison between campaigns, one row per (pair, threshold).

    Each row carries two tests: the overlap of the two campaigns' Wilson intervals over events,
    as first registered, and the same overlap with intervals that resample whole runs, beside a
    run-level interval of the difference.
    """
    rows = []
    cache = {}

    def intervals(name, stats):
        if name not in cache:
            cache[name] = run_intervals(stats["run_counts"], name, draws)
        return cache[name]

    for new_name, ns in new_stats.items():
        if ns["rho"] is None:
            continue
        best = None
        for old_name, os_ in old_stats.items():
            if os_["rho"] is None:
                continue
            d = abs(os_["rho"] - ns["rho"])
            if d <= tol_rho and (best is None or d < best[0]):
                best = (d, old_name, os_)
        if not best:
            continue
        _, old_name, os_ = best
        for c in THRESHOLDS_MS:
            k_new = round(ns["tails"][c] * ns["n_events"])
            k_old = round(os_["tails"][c] * os_["n_events"])
            if k_new < 5 and k_old < 5:
                continue
            lo_n, hi_n = wilson_interval(k_new, ns["n_events"])
            lo_o, hi_o = wilson_interval(k_old, os_["n_events"])
            rn = intervals(new_name, ns)[c] or (lo_n, hi_n)
            ro = intervals(old_name, os_)[c] or (lo_o, hi_o)
            d_lo, d_hi = run_difference(ns["run_counts"], os_["run_counts"], c,
                                        f"{new_name}|{old_name}|{c}", draws)
            rows.append({
                "new_condition": new_name, "old_condition": old_name,
                "rho_new": round(ns["rho"], 3), "rho_old": round(os_["rho"], 3),
                "threshold_ms": c,
                "tail_new": round(ns["tails"][c], 5), "tail_old": round(os_["tails"][c], 5),
                "ci_overlap": bool(max(lo_n, lo_o) <= min(hi_n, hi_o)),
                "runs_new": ns["n_runs"], "runs_old": os_["n_runs"],
                "run_lo_new": round(rn[0], 5), "run_hi_new": round(rn[1], 5),
                "run_lo_old": round(ro[0], 5), "run_hi_old": round(ro[1], 5),
                "ci_overlap_runs": bool(max(rn[0], ro[0]) <= min(rn[1], ro[1])),
                "diff_lo_runs": round(d_lo, 5), "diff_hi_runs": round(d_hi, 5),
                "differs_runs": bool(d_lo > 0 or d_hi < 0),
            })
    return rows


# ---------------------------------------------------------------- driver
def main(argv=None):
    ap = argparse.ArgumentParser(description="Pre-registered collapse-suite analyses")
    ap.add_argument("--depth-dir", default="docs/results/depth")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--new-phase", default="ea3")
    ap.add_argument("--old-phases", default="ea_sat,ea_knee")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    new = collect_phase(args.depth_dir, args.runs_dir, [args.new_phase])
    old = collect_phase(args.depth_dir, args.runs_dir, args.old_phases.split(","))
    if not new:
        print(f"no usable conditions under {args.depth_dir}/{args.new_phase}")
        return 1
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "collapse_conditions.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["condition", "rho", "n_events", "n_runs", "mu",
                                           "sigma_core", "inversion", "runs_z_median"])
        w.writeheader()
        for name, s in sorted(new.items(), key=lambda kv: kv[1]["rho"] or 0):
            w.writerow({"condition": name, "rho": s["rho"], "n_events": s["n_events"],
                        "n_runs": s["n_runs"], "mu": round(s["mu"], 4),
                        "sigma_core": round(s["sigma_core"], 4),
                        "inversion": round(s["tails"][0.0], 5),
                        "runs_z_median": round(s["runs_z_median"], 3)
                        if s["runs_z_median"] is not None else ""})

    pts = collapse_points(new)
    with (out / "collapse_points.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["condition", "rho", "threshold_ms", "z",
                                           "tail_mass", "n_events"])
        w.writeheader()
        w.writerows(pts)

    print("== E-A3 conditions ==")
    for name, s in sorted(new.items(), key=lambda kv: kv[1]["rho"] or 0):
        print(f"  {name:14s} rho={s['rho'] if s['rho'] is not None else float('nan'):.3f} "
              f"n={s['n_events']:5d} mu={s['mu']:.3f} sigma_core={s['sigma_core']:.3f} "
              f"inv={s['tails'][0.0]:.4f} runs_z={s['runs_z_median']}")

    h9 = h9_verdict(pts)
    print(f"\nH9 {h9['hypothesis'].split(' ', 1)[1]}: ", end="")
    if not h9["testable"]:
        print("UNTESTABLE (no z band holds two conditions with informative tails)")
    else:
        print(f"{'SUPPORTED' if h9['supported'] else 'FALSIFIED'} "
              f"(worst within-band spread {h9['worst_ratio']}x at z band {h9['worst_band_z']}; "
              f"threshold 3x)")

    h10 = h10_verdict(new)
    print("H10 mixture structure: ", end="")
    if not h10["testable"]:
        print("UNTESTABLE (need idle and knee conditions)")
    else:
        print(f"{'SUPPORTED' if h10['supported'] else 'NOT SUPPORTED'} "
              f"(tail x{h10['tail_growth']} vs core x{h10['core_growth']} from "
              f"rho={h10['idle_rho']:.2f} to {h10['knee_rho']:.2f}; ratio {h10['ratio']}; "
              f"clustered everywhere: {h10['clustered_everywhere']})")

    rows = reproduction_rows(old, new)
    if rows:
        with (out / "fdelta_reproduction.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["new_condition", "old_condition", "rho_new",
                                               "rho_old", "threshold_ms", "tail_new",
                                               "tail_old", "ci_overlap", "runs_new", "runs_old",
                                               "run_lo_new", "run_hi_new", "run_lo_old",
                                               "run_hi_old", "ci_overlap_runs", "diff_lo_runs",
                                               "diff_hi_runs", "differs_runs"])
            w.writeheader()
            w.writerows(rows)
        agree = sum(1 for r in rows if r["ci_overlap"])
        print(f"F-Delta reproduction: {agree}/{len(rows)} matched tail masses overlap "
              f"(90% Wilson)  -> {'SUPPORTED' if agree == len(rows) else 'PARTIAL' if agree else 'FALSIFIED'}")
        agree_runs = sum(1 for r in rows if r["ci_overlap_runs"])
        differ = sum(1 for r in rows if r["differs_runs"])
        print(f"  resampling whole runs: {agree_runs}/{len(rows)} overlap; the run-level interval "
              f"of the difference excludes zero for {differ}")
    else:
        print("F-Delta reproduction: no rho-matched condition pairs between campaigns")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
