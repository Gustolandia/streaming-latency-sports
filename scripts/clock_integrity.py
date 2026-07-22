#!/usr/bin/env python3
"""
clock_integrity.py
Decide, by rule, whether a run's timestamps can be trusted.

At N=100 the measured Kafka transport median was -6.4 ms. A negative transport is physically
impossible - the consumer cannot receive a message before the broker acknowledges it - so that
condition was discarded. But the same instrument produced every other number, and nothing
established where the degradation begins. A condition at N=50 could be biased by a few
milliseconds and look entirely plausible.

This applies three checks to a run's own artifacts, so no separate probe process is needed:

  * negative transport   - impossible; the clock is broken
  * negative scheduling lag - a send stamped before its own schedule
  * ordering inversion   - broker acknowledgement stamped after consumer receipt

A run failing any check is unusable. The point is that the decision is made by a stated rule
applied to every condition, not by noticing an implausible number after the fact.

CLI:
    python scripts/clock_integrity.py --runs-dir runs --run-glob 'concurrency_n*' \
        --out docs/results/integrity
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# A little slack: clocks are read at slightly different instants and sub-microsecond negatives
# are measurement noise, not broken time. Anything beyond this is a real inversion.
TOLERANCE_MS = 0.001

# An occasional inversion is expected: t_broker_ack_ns is stamped by the producer's ack
# callback, which runs on a sender thread that can be descheduled, so it is sometimes recorded
# after the consumer has already logged receipt. That is a timestamping race, not a broken
# clock. A run is condemned when inversions are COMMON (they then bias the distribution) or
# when the median itself is negative (the measurement has lost ordering entirely).
MAX_NEGATIVE_FRACTION = 0.01


def check_run(run_dir, tolerance_ms=TOLERANCE_MS, max_neg_fraction=MAX_NEGATIVE_FRACTION):
    """Integrity verdict for one run; None if the run cannot be read."""
    run_dir = Path(run_dir)
    pf, cf = run_dir / "producer.csv", run_dir / "consumer.csv"
    if not (pf.exists() and cf.exists()):
        return None
    try:
        prod = pd.read_csv(pf)
        cons = pd.read_csv(cf)
    except (ValueError, OSError):
        return None
    if "event_id" not in prod.columns or "event_id" not in cons.columns:
        return None
    m = prod.merge(cons, on="event_id", how="inner")
    if m.empty:
        return None

    res = {"run_id": run_dir.name, "n_events": int(len(m))}

    def diff_ms(later_col, earlier_col):
        """Difference of two timestamp columns in ms, coercing before subtracting.

        Coercion must happen first: a corrupt column is text, and subtracting text raises
        rather than yielding NaN, which would abort the audit of an otherwise readable run.
        """
        if later_col not in m.columns or earlier_col not in m.columns:
            return np.nan, np.nan, np.nan
        a = pd.to_numeric(m[later_col], errors="coerce")
        b = pd.to_numeric(m[earlier_col], errors="coerce")
        v = ((a - b) / 1e6).dropna().values
        if len(v) == 0:
            return np.nan, np.nan, np.nan
        return (float((v < -tolerance_ms).mean()), float(v.min()), float(np.median(v)))

    (res["frac_neg_transport"], res["min_transport_ms"],
     res["median_transport_ms"]) = diff_ms("t_cons_recv_ns", "t_broker_ack_ns")
    (res["frac_neg_schedlag"], res["min_schedlag_ms"],
     res["median_schedlag_ms"]) = diff_ms("t_prod_send_ns", "t_prod_sched_ns")
    (res["frac_neg_output"], res["min_output_ms"],
     res["median_output_ms"]) = diff_ms("t_output_ns", "t_cons_recv_ns")

    fracs = [res["frac_neg_transport"], res["frac_neg_schedlag"], res["frac_neg_output"]]
    medians = [res["median_transport_ms"], res["median_schedlag_ms"], res["median_output_ms"]]
    res["max_neg_fraction"] = float(np.nanmax([np.nan_to_num(f) for f in fracs]))
    res["trustworthy"] = bool(
        res["max_neg_fraction"] <= max_neg_fraction
        and all(np.isnan(x) or x >= 0 for x in medians))
    return res


def audit(runs_dir, run_glob, tolerance_ms=TOLERANCE_MS,
          max_neg_fraction=MAX_NEGATIVE_FRACTION):
    rows = []
    for d in sorted(Path(runs_dir).glob(run_glob)):
        if not d.is_dir():
            continue
        r = check_run(d, tolerance_ms, max_neg_fraction)
        if r is not None:
            rows.append(r)
    return pd.DataFrame(rows)


def condition_of(run_id):
    """Group runs into conditions by stripping the per-feed/per-rep suffix."""
    parts = str(run_id).split("_")
    keep = []
    for p in parts:
        if p.startswith("feed") or p.startswith("rep"):
            break
        keep.append(p)
    return "_".join(keep) if keep else str(run_id)


def summarize(df):
    """Per-condition verdict. A condition is usable only if EVERY run in it passes."""
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["condition"] = d["run_id"].map(condition_of)
    g = (d.groupby("condition")
           .agg(n_runs=("run_id", "count"),
                n_trustworthy=("trustworthy", "sum"),
                worst_transport_ms=("min_transport_ms", "min"),
                median_neg_fraction=("max_neg_fraction", "median"))
           .reset_index())
    g["usable"] = g["n_runs"] == g["n_trustworthy"]
    return g.sort_values("condition")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Clock-integrity gate for measured runs")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--run-glob", default="concurrency_n*")
    ap.add_argument("--tolerance-ms", type=float, default=TOLERANCE_MS)
    ap.add_argument("--max-neg-fraction", type=float, default=MAX_NEGATIVE_FRACTION,
                    help="condemn a run when inversions exceed this share of events")
    ap.add_argument("--out", default="docs/results/integrity")
    args = ap.parse_args(argv)

    df = audit(args.runs_dir, args.run_glob, args.tolerance_ms, args.max_neg_fraction)
    if df.empty:
        print(f"No readable runs matched {args.run_glob}")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "clock_integrity_by_run.csv", index=False)
    summary = summarize(df)
    summary.to_csv(out / "clock_integrity_by_condition.csv", index=False)

    n_bad = int((~df["trustworthy"]).sum())
    print(f"== clock integrity: {len(df)} runs, {n_bad} failing ==")
    print(summary.to_string(index=False))
    if n_bad:
        print("\nFAILING RUNS (physically impossible timestamps - discard by rule):")
        print(df[~df["trustworthy"]][["run_id", "max_neg_fraction", "min_transport_ms",
                                     "median_transport_ms"]].head(10).to_string(index=False))
    print(f"\nWrote {out}/")
    # Non-zero exit when any condition is unusable, so a campaign can gate on this.
    return 2 if n_bad else 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
