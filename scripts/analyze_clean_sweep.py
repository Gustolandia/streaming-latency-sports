#!/usr/bin/env python3
"""
analyze_clean_sweep.py
The pre-registered analysis for E-B2, the clean effect-size sweep (referee issue M3).

H1 says inversion risk falls as the measured quantity grows. Its quantitative support was a netem
delay sweep run at an accelerated replay rate, where injecting delay also built a queue: measured
variance climbed from 10 to 9,200 ms^2 across the sweep, so the manipulation moved the spread as
well as the mean and could not isolate either. E-B2 repeats it at the workload's true rate, where
the feed is sparse enough that the delay pipe cannot backlog.

Whether that worked is a question, not an assumption, so this script decides it before it reports
any slope:

  MANIPULATION CHECK -- did the delay behave as a constant offset? The median measured transport
  must rise roughly one-for-one with the injected delay (the offset landed), and the spread must
  stay flat (no queue built). We use the IQR rather than the variance because a handful of
  descheduling outliers inflate a variance without indicating a backlog.

  Only if that passes do we report the H1 slope. If it fails the honest output is "still
  confounded", and the paper says so rather than quoting a number it cannot defend.

CLI:
    python scripts/analyze_clean_sweep.py --sweep-dir docs/results/depth/eb2 --runs-dir runs \
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
from measurement_model import spearman  # noqa: E402

# A clean constant offset should move the median about 1:1 with the injected delay and leave the
# spread alone. Both bands are generous: this is a check for a queue, not a calibration.
OFFSET_TOLERANCE = 0.5      # measured rise within 50% of the injected delay
SPREAD_GROWTH_MAX = 4.0     # IQR may not grow more than 4x across the whole sweep


def condition_timestamp(cond_dir):
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def transports(cond_dir, runs_dir, backend="kafka"):
    """Every per-event measured transport (ms) pooled over a condition's runs."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return []
    vals = []
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
                    if a is not None and rc not in (None, "", "None"):
                        vals.append((int(rc) - a) / 1e6)
        except (ValueError, KeyError, OSError):
            continue
    return vals


def collect(sweep_dir, runs_dir, backend="kafka"):
    """One row per injected-delay level: centre, spread and inversion rate."""
    rows = []
    for cond in sorted(glob.glob(os.path.join(sweep_dir, "d*"))):
        if not os.path.isdir(cond):
            continue
        m = re.search(r"d(\d+)$", os.path.basename(cond))
        vals = transports(cond, runs_dir, backend)
        if not (m and len(vals) >= 50):
            continue
        vs = sorted(vals)
        q1, q3 = vs[len(vs) // 4], vs[3 * len(vs) // 4]
        rows.append({
            "delay_ms": float(m.group(1)),
            "n_events": len(vs),
            "median_ms": round(st.median(vs), 4),
            "iqr_ms": round(q3 - q1, 4),
            "inversion_rate": round(sum(1 for x in vs if x < 0) / len(vs), 5),
        })
    return sorted(rows, key=lambda r: r["delay_ms"])


def manipulation_check(rows):
    """Did the delay act as a constant offset, or did it build a queue again?"""
    if len(rows) < 3:
        return {"clean": False, "reason": "need at least three delay levels"}
    base, top = rows[0], rows[-1]
    injected = top["delay_ms"] - base["delay_ms"]
    observed = top["median_ms"] - base["median_ms"]
    offset_ok = injected > 0 and abs(observed - injected) <= OFFSET_TOLERANCE * injected
    spreads = [r["iqr_ms"] for r in rows if r["iqr_ms"] > 0]
    growth = (max(spreads) / min(spreads)) if spreads else float("inf")
    spread_ok = growth <= SPREAD_GROWTH_MAX
    return {
        "clean": bool(offset_ok and spread_ok),
        "injected_ms": injected, "observed_rise_ms": round(observed, 3),
        "offset_ok": bool(offset_ok),
        "spread_growth": round(growth, 2), "spread_ok": bool(spread_ok),
        "reason": ("offset landed and spread stayed flat" if offset_ok and spread_ok else
                   "median did not track the injected delay" if not offset_ok else
                   f"spread grew {growth:.1f}x: a queue formed, so the sweep is confounded"),
    }


def h1_verdict(rows, check):
    """Only reported when the manipulation is clean; otherwise explicitly withheld."""
    if not check["clean"]:
        return {"hypothesis": "H1 effect-size rule (clean sweep)", "reported": False,
                "spearman": float("nan"), "supported": False,
                "why": "manipulation check failed: " + check["reason"]}
    rho = spearman([r["delay_ms"] for r in rows], [r["inversion_rate"] for r in rows])
    return {"hypothesis": "H1 effect-size rule (clean sweep)", "reported": True,
            "spearman": rho, "n_points": len(rows),
            "supported": bool(rho < 0),
            "why": ("inversion rate falls as the measured quantity grows"
                    if rho < 0 else "inversion rate does not fall with the measured quantity")}


def main(argv=None):
    ap = argparse.ArgumentParser(description="E-B2: clean effect-size sweep (referee M3)")
    ap.add_argument("--sweep-dir", default="docs/results/depth/eb2")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="docs/results/model")
    args = ap.parse_args(argv)

    if not Path(args.sweep_dir).is_dir():
        print(f"missing sweep directory: {args.sweep_dir}")
        return 1
    rows = collect(args.sweep_dir, args.runs_dir)
    if len(rows) < 3:
        print(f"insufficient delay levels ({len(rows)}) for a sweep")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "clean_effect_size.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["delay_ms", "n_events", "median_ms", "iqr_ms",
                                           "inversion_rate"])
        w.writeheader()
        w.writerows(rows)

    print("== E-B2: injected delay at a verified true real-time rate ==")
    for r in rows:
        print(f"  delay {r['delay_ms']:5.0f} ms  n={r['n_events']:6d}  "
              f"median={r['median_ms']:9.3f} ms  IQR={r['iqr_ms']:8.3f} ms  "
              f"inversion={r['inversion_rate']:.5f}")

    check = manipulation_check(rows)
    print(f"\n== MANIPULATION CHECK: {'CLEAN' if check['clean'] else 'CONFOUNDED'} ==")
    print(f"  injected {check['injected_ms']:.0f} ms, median rose "
          f"{check['observed_rise_ms']:.1f} ms; spread grew {check['spread_growth']}x")
    print(f"  {check['reason']}")

    v = h1_verdict(rows, check)
    print(f"\n== H1: {'SUPPORTED' if v['supported'] else 'NOT REPORTED' if not v['reported'] else 'NOT SUPPORTED'} ==")
    if v["reported"]:
        print(f"  spearman {v['spearman']:.3f} over {v['n_points']} levels; {v['why']}")
    else:
        print(f"  {v['why']}")
        print("  The slope is withheld rather than reported against a confounded manipulation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
