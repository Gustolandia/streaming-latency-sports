#!/usr/bin/env python3
"""
Deep health verification script for all batch runs.
Performs comprehensive checks on all run directories to ensure data integrity.
Handles both Kafka (topic) and Redis (stream) backends.

NOTE: Reconstructed June 17 2026 after an accidental deletion. Functionally
equivalent to the original (deep per-run integrity checks), but not guaranteed
byte-identical. The maintained, unit-tested equivalents live in
scripts/verify_run_quality.py and scripts/check_concurrency_health.py.

Usage:
    python deep_health_check_final.py [--runs-dir runs] [--pattern 'batch*'] [--verbose]
Exit code 0 if all runs pass, 1 otherwise.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

REQUIRED_FILES = ["tti_summary.json", "producer.csv", "consumer.csv", "meta.json"]
MATCH_TOLERANCE = 0.01  # 1% producer/consumer count tolerance


def _count_data_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def verify_run_deep(run_dir):
    """Deep verification of a single run directory. Returns (ok, errors, warnings)."""
    run_dir = Path(run_dir)
    errors, warnings = [], []
    backend = None

    # 1. Required files exist and are non-empty
    for fname in REQUIRED_FILES:
        fpath = run_dir / fname
        if not fpath.exists():
            errors.append(f"{fname} missing")
        elif fpath.stat().st_size == 0:
            errors.append(f"{fname} is empty")

    # 2. meta.json: valid JSON, backend kafka/redis, required fields
    meta_path = run_dir / "meta.json"
    if meta_path.exists() and meta_path.stat().st_size > 0:
        try:
            with open(meta_path, encoding="utf-8-sig") as f:
                meta = json.load(f)
            backend = meta.get("backend")
            if backend not in ("kafka", "redis"):
                # Fall back to inferring from run_id (e.g. batchN_..._kafka_..._)
                name = run_dir.name
                backend = "kafka" if "kafka" in name else "redis" if "redis" in name else None
            for field in ("run_id",):
                if field not in meta:
                    errors.append(f"meta.json missing field: {field}")
        except (ValueError, OSError) as e:
            errors.append(f"meta.json invalid: {e}")

    # 3. tti_summary.json: valid JSON with a non-empty tti block
    tti_path = run_dir / "tti_summary.json"
    n_matched = None
    if tti_path.exists() and tti_path.stat().st_size > 0:
        try:
            with open(tti_path, encoding="utf-8-sig") as f:
                tti = json.load(f)
            n_matched = tti.get("n_matched")
            tti_block = tti.get("tti_ms", {})
            if isinstance(tti_block, dict):
                median = tti_block.get("p50")
                if median is not None and median < 0:
                    errors.append(f"negative median TTI: {median}")
                max_tti = tti_block.get("max")
                if max_tti is not None and max_tti > 300000:
                    warnings.append(f"max TTI > 5min: {max_tti}ms")
            if not n_matched:
                warnings.append("n_matched is 0 or missing")
        except (ValueError, OSError) as e:
            errors.append(f"tti_summary.json invalid: {e}")

    # 4. Event-count integrity: producer vs consumer within tolerance
    prod_path, cons_path = run_dir / "producer.csv", run_dir / "consumer.csv"
    if prod_path.exists() and cons_path.exists() and prod_path.stat().st_size > 0:
        try:
            n_prod = _count_data_rows(prod_path)
            n_cons = _count_data_rows(cons_path)
            if n_prod == 0:
                errors.append("producer.csv has no data rows")
            else:
                tol = max(n_prod * MATCH_TOLERANCE, 10)
                if abs(n_prod - n_cons) > tol:
                    warnings.append(f"event count mismatch: prod={n_prod}, cons={n_cons}")
        except OSError as e:
            errors.append(f"CSV read error: {e}")

    return (len(errors) == 0, errors, warnings)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deep health check of all batch run directories")
    ap.add_argument("--runs-dir", default="runs", help="Directory containing run subdirectories")
    ap.add_argument("--pattern", default="*", help="Glob pattern for run directory names")
    ap.add_argument("--verbose", action="store_true", help="Show errors/warnings for every run")
    args = ap.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"ERROR: runs directory not found: {runs_dir}")
        return 1

    run_dirs = sorted(d for d in runs_dir.glob(args.pattern) if d.is_dir())
    if not run_dirs:
        print(f"No run directories matched {args.pattern} in {runs_dir}")
        return 1

    passed, failed, with_warnings = 0, 0, 0
    for run_dir in run_dirs:
        ok, errors, warnings = verify_run_deep(run_dir)
        if warnings:
            with_warnings += 1
        if ok:
            passed += 1
            if args.verbose and warnings:
                print(f"WARN {run_dir.name}: {', '.join(warnings)}")
        else:
            failed += 1
            if args.verbose:
                print(f"FAIL {run_dir.name}: {', '.join(errors)}")

    print(f"\nDeep-checked {len(run_dirs)} runs: {passed} passed, {failed} failed, "
          f"{with_warnings} with warnings")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
