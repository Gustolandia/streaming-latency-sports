#!/usr/bin/env python3
"""
threshold_condition_sweep.py
Verify, at condition level, that the audit threshold cannot resurrect the first result set.

The consistency-check section reports the threshold's run-level sensitivity (92.5% of runs rejected at zero
tolerance, 19.2% at a permissive 20%) and claims that no choice of threshold in that range
returns any cell of the first result set to usability. The run-level curve was always
artefact-checked; the condition-level half of the claim was not, and a referee (TPDS round 1,
Q5) asked for it explicitly. This script is that check.

The first result set is the distinct-plans accelerated sweep whose per-run aggregate is
docs/results/realtime_concurrency_distinct/realtime_concurrency_by_run.csv -- six cells,
backend x N in {1, 5, 10}, 15-30 runs per cell. A run passes at threshold t iff its worst
per-component negative fraction is <= t and no component median is negative (the audit rule
with its 1% constant replaced by t). A cell is usable iff every one of its runs passes: the
same all-runs rule the audit applies at its operative threshold.

Output: one row per (threshold, cell) with the pass count, plus an `usable` flag. The script
exits non-zero if any first-result cell is fully usable at any swept threshold, so the
paper's sentence cannot silently outlive the data that supports it.

CLI:
    python scripts/threshold_condition_sweep.py \
        --first-result docs/results/realtime_concurrency_distinct/realtime_concurrency_by_run.csv \
        --audit docs/results/integrity_windows/clock_integrity_by_run.csv \
        --out docs/results/integrity_windows/first_result_threshold_sweep.csv
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

# The swept grid: the operative threshold, its neighbours, and the permissive extreme the
# paper quotes. Kept as a module constant so the test and the paper quote the same grid.
THRESHOLDS = (0.0, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20)
MEDIAN_COLS = ("median_transport_ms", "median_schedlag_ms", "median_output_ms")


def run_passes(audit_row, threshold):
    """The audit rule with a variable threshold: worst component fraction and any median."""
    if float(audit_row["max_neg_fraction"]) > threshold:
        return False
    return all(float(audit_row[c]) >= 0 for c in MEDIAN_COLS)


def sweep(first_rows, audit_by_run, thresholds=THRESHOLDS):
    """Return (rows, n_missing): one output row per threshold x cell, sorted."""
    cells = defaultdict(list)
    missing = 0
    for r in first_rows:
        a = audit_by_run.get(r["run_id"])
        if a is None:
            missing += 1
            continue
        cells[(r["backend"], int(r["n"]))].append(a)
    out = []
    for t in thresholds:
        for key in sorted(cells):
            runs = cells[key]
            n_pass = sum(run_passes(a, t) for a in runs)
            out.append({
                "threshold": t,
                "backend": key[0],
                "n": key[1],
                "n_pass": n_pass,
                "n_runs": len(runs),
                "usable": n_pass == len(runs),
            })
    return out, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--first-result",
                    default="docs/results/realtime_concurrency_distinct/"
                            "realtime_concurrency_by_run.csv")
    ap.add_argument("--audit",
                    default="docs/results/integrity_windows/clock_integrity_by_run.csv")
    ap.add_argument("--out",
                    default="docs/results/integrity_windows/first_result_threshold_sweep.csv")
    args = ap.parse_args(argv)

    first_rows = list(csv.DictReader(open(args.first_result, encoding="utf-8")))
    audit_by_run = {r["run_id"]: r
                    for r in csv.DictReader(open(args.audit, encoding="utf-8"))}
    rows, missing = sweep(first_rows, audit_by_run)
    if missing:
        print(f"FATAL: {missing} first-result runs missing from the audit file")
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    resurrected = [r for r in rows if r["usable"]]
    for t in THRESHOLDS:
        at_t = [r for r in rows if r["threshold"] == t]
        best = max(at_t, key=lambda r: r["n_pass"] / r["n_runs"])
        print(f"t={t:>4}: 0/{len(at_t)} cells usable; best cell "
              f"{best['backend']} N={best['n']} at {best['n_pass']}/{best['n_runs']}"
              if not [r for r in at_t if r["usable"]] else
              f"t={t:>4}: RESURRECTED: "
              + ", ".join(f"{r['backend']} N={r['n']}" for r in at_t if r["usable"]))
    if resurrected:
        print("FATAL: a first-result cell became usable inside the swept range; "
              "the consistency check's sensitivity sentence no longer holds")
        return 1
    print(f"OK: no first-result cell usable at any threshold in "
          f"[{THRESHOLDS[0]}, {THRESHOLDS[-1]}]; wrote {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
