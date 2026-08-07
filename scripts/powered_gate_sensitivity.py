#!/usr/bin/env python3
"""
powered_gate_sensitivity.py
Apply the audit gate to the powered transport campaigns, and bound the 0.41 ms shift
against the selection the gate introduces.

Two defects this script exists to repair, both surfaced by referee point M5 (TPDS round 1).

First, the powered transport artefacts (transport_rt, transport_rt2) were aggregated
before the audit verdicts were wired into the cloud index, so the TOST and Hodges-Lehmann
numbers the paper quoted were computed over ALL runs, condemned included. The audit's own
rule must be applied to the audit's own headline replication. This script writes the gated
by-run and gated summary, and the gated TOST is produced by running the existing
equivalence_tests.py over the gated by-run (see cite: response letter, M5).

Second, the gate rejects Redis runs far more often than Kafka runs (driver saturation),
and the referee asked whether the reported ~0.41 ms shift in Redis's favour survives that
selection. Unlike E1 -- where the rejected values are unrecoverable and retention_bias.py
can only bound -- here every condemned run's measured value survives in the by-run file,
so three sensitivity statements are computable rather than assumed:

  (1) gate on/off:   the HL shift over usable runs only, against the shift over all runs;
  (2) flip point:    the smallest value V such that imputing EVERY condemned Redis run at
                     V flips the shift's sign -- the worst-case account of what the
                     condemned runs could have contained;
  (3) observed:      what the condemned Redis runs actually measured (median and max of
                     their run-medians), against which the flip point can be judged; a
                     condemned run's own median is displaced by at most its negative
                     fraction f in quantile space (the clean median lies between the
                     observed q(0.5) and q(0.5/(1-f)) quantiles), and f <= 0.071 here.

The script exits non-zero if the gate moves any cell's HL shift by more than DELTA_GATE_MS,
so a materially selection-sensitive shift cannot be quoted as robust.

CLI:
    python scripts/powered_gate_sensitivity.py --corpus docs/results/transport_rt \
        --index reproducibility/runs_index_cloud.csv
"""
import argparse
import csv
import os
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retention_bias import hl_shift  # noqa: E402  (same estimator the paper reports)

DELTA_GATE_MS = 0.05      # gate on/off may move a cell's HL shift by at most this much
FLIP_GRID_MS = [round(0.05 * k, 2) for k in range(2, 1200)]   # 0.10 .. 59.95 ms


def load_gated(by_run_rows, index_by_run):
    """Split by-run rows into (usable, condemned, unknown) using the cloud index."""
    usable, condemned, unknown = [], [], []
    for r in by_run_rows:
        verdict = index_by_run.get(r["run_id"], {}).get("transport_integrity")
        if verdict == "usable":
            usable.append(r)
        elif verdict == "condemned":
            condemned.append(r)
        else:
            unknown.append(r)
    return usable, condemned, unknown


def values(rows, backend, n):
    return [float(r["transport_p50"]) for r in rows
            if r["backend"] == backend and r["n"] == n]


def flip_point(kafka_usable, redis_usable, n_condemned_redis):
    """Smallest imputed value V at which the HL shift crosses zero, or None."""
    if not n_condemned_redis or not kafka_usable or not redis_usable:
        return None
    for v in FLIP_GRID_MS:
        if hl_shift(kafka_usable, redis_usable + [v] * n_condemned_redis) <= 0:
            return v
    return None


def analyse_cell(by_run_rows, index_by_run, n):
    usable, condemned, _ = load_gated(by_run_rows, index_by_run)
    k_all, r_all = values(by_run_rows, "kafka", n), values(by_run_rows, "redis", n)
    k_use, r_use = values(usable, "kafka", n), values(usable, "redis", n)
    r_cond = values(condemned, "redis", n)
    hl_all = hl_shift(k_all, r_all)
    hl_gated = hl_shift(k_use, r_use)
    frac_max = max((float(index_by_run[r["run_id"]]["frac_negative_transport"] or 0)
                    for r in by_run_rows if r["run_id"] in index_by_run), default=0.0)
    return {
        "n": n,
        "kafka_usable": len(k_use), "kafka_total": len(k_all),
        "redis_usable": len(r_use), "redis_total": len(r_all),
        "redis_retention_pct": round(100.0 * len(r_use) / len(r_all), 1) if r_all else "",
        "hl_all_ms": round(hl_all, 4),
        "hl_gated_ms": round(hl_gated, 4),
        "hl_gate_delta_ms": round(hl_gated - hl_all, 4),
        "flip_v_ms": flip_point(k_use, r_use, len(r_cond)),
        "condemned_redis_median_ms": round(st.median(r_cond), 3) if r_cond else "",
        "condemned_redis_max_ms": round(max(r_cond), 3) if r_cond else "",
        "max_frac_negative": round(frac_max, 4),
    }


def summarise(rows):
    """Gated summary in the same schema as transport_realtime_summary.csv."""
    ns = sorted({r["n"] for r in rows}, key=int)
    out = []
    for n in ns:
        k = values(rows, "kafka", n)
        r = values(rows, "redis", n)
        k_matched = [int(x["n_matched"]) for x in rows
                     if x["backend"] == "kafka" and x["n"] == n]
        r_matched = [int(x["n_matched"]) for x in rows
                     if x["backend"] == "redis" and x["n"] == n]
        out.append({
            "n": n,
            "kafka_transport_p50": round(st.median(k), 3) if k else "",
            "kafka_runs": len(k),
            "kafka_matched_med": int(st.median(k_matched)) if k_matched else "",
            "redis_transport_p50": round(st.median(r), 3) if r else "",
            "redis_runs": len(r),
            "redis_matched_med": int(st.median(r_matched)) if r_matched else "",
        })
    return out


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--corpus", default="docs/results/transport_rt",
                    help="directory holding transport_realtime_by_run.csv")
    ap.add_argument("--index", default="reproducibility/runs_index_cloud.csv")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus)
    by_run_rows = list(csv.DictReader(
        open(corpus / "transport_realtime_by_run.csv", encoding="utf-8")))
    index_by_run = {r["run_id"]: r
                    for r in csv.DictReader(open(args.index, encoding="utf-8"))}

    usable, condemned, unknown = load_gated(by_run_rows, index_by_run)
    if unknown:
        print(f"FATAL: {len(unknown)} runs missing an audit verdict in {args.index}")
        return 2

    ns = sorted({r["n"] for r in by_run_rows}, key=int)
    cells = [analyse_cell(by_run_rows, index_by_run, n) for n in ns]

    write_csv(corpus / "transport_realtime_by_run_gated.csv", usable)
    write_csv(corpus / "transport_realtime_summary_gated.csv", summarise(usable))
    write_csv(corpus / "gate_sensitivity.csv", cells)

    bad = [c for c in cells if abs(c["hl_gate_delta_ms"]) > DELTA_GATE_MS]
    for c in cells:
        print(f"N={c['n']:>2}: redis retention {c['redis_retention_pct']}% | "
              f"HL gated {c['hl_gated_ms']} vs all {c['hl_all_ms']} "
              f"(delta {c['hl_gate_delta_ms']}) | flip V*={c['flip_v_ms']} ms | "
              f"condemned redis medians: median {c['condemned_redis_median_ms']}, "
              f"max {c['condemned_redis_max_ms']}")
    if bad:
        print(f"FATAL: gate moves the HL shift by more than {DELTA_GATE_MS} ms in "
              f"{len(bad)} cell(s); the shift may not be quoted as selection-robust")
        return 1
    print(f"OK: gate moves no cell's shift by more than {DELTA_GATE_MS} ms; "
          f"wrote gated by-run, gated summary and gate_sensitivity.csv under {corpus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
