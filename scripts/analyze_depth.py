#!/usr/bin/env python3
"""
analyze_depth.py
Turn the depth-suite runs into the H1 and H2 verdicts (see docs/measurement_model.md).

For each condition it computes the inversion rate -- the fraction of events whose broker
transport (consumer receipt minus broker acknowledgement) is negative, which is the physically
impossible measurement the whole paper is about -- then:

  H1 (E-B): inversion rate vs the true latency being measured (the injected netem delay).
            The model predicts it falls as the measured quantity grows.
  H2 (E-A): inversion rate vs achieved CPU utilisation. The model predicts an M/G/1 knee.

Transport is recomputed from the raw per-event data rather than trusted from a summary, because
the summary is exactly what hides the failure.

CLI:
    python scripts/analyze_depth.py --depth-dir docs/results/depth --runs-dir runs \
        --out docs/results/depth/model
"""
import argparse
import csv
import glob
import os
import re
import statistics as st
from pathlib import Path

# measurement_model lives beside this file.
import sys
sys.path.insert(0, str(Path(__file__).parent))
from measurement_model import check_h1, check_h2, spearman  # noqa: E402


def run_inversion(run_dir):
    """(negative events, total events) for one run, from raw per-event transport.

    Joins consumer receipt (t_consume_ns) to broker acknowledgement (t_broker_ack_ns) on
    event_id. A negative difference is an inversion. Returns (0, 0) if the run is unreadable, so
    a broken run contributes nothing rather than crashing the sweep.
    """
    cons = os.path.join(run_dir, "consumer_events.csv")
    prod = os.path.join(run_dir, "producer.csv")
    if not (os.path.exists(cons) and os.path.exists(prod)):
        return 0, 0
    ack = {}
    try:
        with open(prod, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = r.get("t_broker_ack_ns")
                if v not in (None, "", "None"):
                    ack[r["event_id"]] = int(v)
        neg = tot = 0
        with open(cons, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                a = ack.get(r["event_id"])
                recv = r.get("t_consume_ns")
                if a is None or recv in (None, "", "None"):
                    continue
                tot += 1
                if int(recv) - a < 0:
                    neg += 1
        return neg, tot
    except (ValueError, KeyError, OSError):
        return 0, 0


def condition_timestamp(cond_dir):
    """The run-id timestamp a condition's trials share, read from its concurrency subdir."""
    for sub in glob.glob(os.path.join(cond_dir, "concurrency_concurrency_*")):
        m = re.search(r"concurrency_(n\d+_\d{8}_\d{6})", os.path.basename(sub))
        if m:
            return m.group(1)
    return None


def condition_inversion(cond_dir, runs_dir):
    """Pooled inversion rate across every run belonging to a condition."""
    ts = condition_timestamp(cond_dir)
    if not ts:
        return None
    neg = tot = 0
    for run in glob.glob(os.path.join(runs_dir, f"concurrency_{ts}_*")):
        if os.path.isdir(run):
            n, t = run_inversion(run)
            neg += n
            tot += t
    return (neg / tot) if tot else None


def median_rho(cond_dir):
    """Median achieved utilisation from the condition's sampler trace."""
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


def delay_from_tag(cond_dir):
    """Injected one-way delay in ms, parsed from an E-B condition directory name (d0, d20...)."""
    m = re.search(r"d(\d+)$", os.path.basename(cond_dir.rstrip("/")))
    return float(m.group(1)) if m else None


def n_from_tag(cond_dir):
    """Process count parsed from an E-A2 condition directory name (n1, n3, n6, n12)."""
    m = re.search(r"n(\d+)$", os.path.basename(cond_dir.rstrip("/")))
    return int(m.group(1)) if m else None


def collect(depth_dir, runs_dir):
    """Build the E-B (H1), E-A/E-A-sat (H2) and E-A2 (H4) tables from the completed runs.

    E-A-sat supersedes E-A where present: the first E-A never reached saturation, so if the
    saturation rerun exists its data is used for H2 instead.
    """
    eb, ea, ea2 = [], [], []
    for cond in sorted(glob.glob(os.path.join(depth_dir, "eb", "d*"))):
        inv = condition_inversion(cond, runs_dir)
        d = delay_from_tag(cond)
        if inv is not None and d is not None:
            eb.append({"t_true_ms": d, "inversion_rate": inv})

    ea_phase = "ea_sat" if glob.glob(os.path.join(depth_dir, "ea_sat", "*")) else "ea"
    for cond in sorted(glob.glob(os.path.join(depth_dir, ea_phase, "*"))):
        if not os.path.isdir(cond):
            continue
        inv = condition_inversion(cond, runs_dir)
        rho = median_rho(cond)
        if inv is not None and rho is not None:
            ea.append({"rho": rho, "inversion_rate": inv})

    for cond in sorted(glob.glob(os.path.join(depth_dir, "ea2", "n*"))):
        inv = condition_inversion(cond, runs_dir)
        n = n_from_tag(cond)
        if inv is not None and n is not None:
            ea2.append({"n_feeds": n, "inversion_rate": inv})
    return eb, ea, ea2


def _write(rows, path, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    import pandas as pd
    ap = argparse.ArgumentParser(description="Fit H1/H2 from the depth suite")
    ap.add_argument("--depth-dir", default="docs/results/depth")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="docs/results/depth/model")
    args = ap.parse_args(argv)

    eb, ea, ea2 = collect(args.depth_dir, args.runs_dir)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    print("== E-B: effect-size sweep (H1) ==")
    for r in sorted(eb, key=lambda x: x["t_true_ms"]):
        print(f"  delay {r['t_true_ms']:5.0f} ms  ->  inversion rate {r['inversion_rate']:.4f}")
    print("== E-A: utilisation sweep (H2) ==")
    for r in sorted(ea, key=lambda x: x["rho"]):
        print(f"  rho {r['rho']:.3f}  ->  inversion rate {r['inversion_rate']:.4f}")
    print("== E-A2: process-count sweep (H4) ==")
    for r in sorted(ea2, key=lambda x: x["n_feeds"]):
        print(f"  N={r['n_feeds']:2d}  ->  inversion rate {r['inversion_rate']:.4f}")

    verdicts = {}
    if len(eb) >= 3:
        _write(eb, out / "eb_effect_size.csv", ["t_true_ms", "inversion_rate"])
        verdicts["H1"] = check_h1(pd.DataFrame(eb))
    if len(ea) >= 3:
        _write(ea, out / "ea_utilisation.csv", ["rho", "inversion_rate"])
        verdicts["H2"] = check_h2(pd.DataFrame(ea))
    if len(ea2) >= 3:
        _write(ea2, out / "ea2_process_count.csv", ["n_feeds", "inversion_rate"])
        rho = spearman([r["n_feeds"] for r in ea2], [r["inversion_rate"] for r in ea2])
        verdicts["H4"] = {"hypothesis": "H4 oversubscription rule", "n_points": len(ea2),
                          "spearman": rho, "supported": bool(rho > 0)}

    print("\n== VERDICTS ==")
    for key, v in verdicts.items():
        print(f"{key} {v['hypothesis']}: "
              f"{'SUPPORTED' if v['supported'] else 'NOT SUPPORTED'} "
              f"(spearman {v['spearman']:.3f}, n={v['n_points']})")
        if key == "H2":
            print(f"   shape: R^2 M/G/1 {v['r2_mg1']:.3f} vs linear {v['r2_linear']:.3f}")
    if not verdicts:
        print("insufficient data for any hypothesis")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
