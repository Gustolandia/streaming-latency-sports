#!/usr/bin/env python3
"""
Complete verification script for all runs.
Checks all required files exist, are non-empty, and contain valid data.

NOTE: Reconstructed June 17 2026 after an accidental deletion. Functionally
equivalent to the original (required-file presence + basic validity checks),
but not guaranteed byte-identical. See also scripts/verify_run_quality.py and
scripts/check_concurrency_health.py for the maintained, unit-tested versions.

Usage:
    python verify_all_runs.py [--runs-dir runs] [--pattern '*'] [--verbose]
Exit code 0 if all runs pass, 1 otherwise.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

REQUIRED_FILES = ["tti_summary.json", "producer.csv", "consumer.csv", "meta.json"]


def verify_run(run_dir):
    """Verify a single run directory. Returns (ok, issues)."""
    run_dir = Path(run_dir)
    issues = []

    # 1. Required files exist and are non-empty
    for fname in REQUIRED_FILES:
        fpath = run_dir / fname
        if not fpath.exists():
            issues.append(f"{fname} missing")
        elif fpath.stat().st_size == 0:
            issues.append(f"{fname} is empty")

    # 2. meta.json is valid JSON with a backend
    meta_path = run_dir / "meta.json"
    if meta_path.exists() and meta_path.stat().st_size > 0:
        try:
            with open(meta_path, encoding="utf-8-sig") as f:
                meta = json.load(f)
            if "run_id" not in meta:
                issues.append("meta.json missing run_id")
        except (ValueError, OSError) as e:
            issues.append(f"meta.json invalid: {e}")

    # 3. tti_summary.json is valid JSON
    tti_path = run_dir / "tti_summary.json"
    if tti_path.exists() and tti_path.stat().st_size > 0:
        try:
            with open(tti_path, encoding="utf-8-sig") as f:
                json.load(f)
        except (ValueError, OSError) as e:
            issues.append(f"tti_summary.json invalid: {e}")

    # 4. producer.csv / consumer.csv have at least a header + one data row
    for fname in ("producer.csv", "consumer.csv"):
        fpath = run_dir / fname
        if fpath.exists() and fpath.stat().st_size > 0:
            try:
                with open(fpath, encoding="utf-8-sig", newline="") as f:
                    rows = sum(1 for _ in csv.reader(f))
                if rows < 2:
                    issues.append(f"{fname} has no data rows")
            except OSError as e:
                issues.append(f"{fname} unreadable: {e}")

    return (len(issues) == 0, issues)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify all run directories are complete and valid")
    ap.add_argument("--runs-dir", default="runs", help="Directory containing run subdirectories")
    ap.add_argument("--pattern", default="*", help="Glob pattern for run directory names")
    ap.add_argument("--verbose", action="store_true", help="List issues for every failing run")
    args = ap.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"ERROR: runs directory not found: {runs_dir}")
        return 1

    run_dirs = sorted(d for d in runs_dir.glob(args.pattern) if d.is_dir())
    if not run_dirs:
        print(f"No run directories matched {args.pattern} in {runs_dir}")
        return 1

    passed, failed = 0, 0
    for run_dir in run_dirs:
        ok, issues = verify_run(run_dir)
        if ok:
            passed += 1
        else:
            failed += 1
            if args.verbose:
                print(f"FAIL {run_dir.name}: {', '.join(issues)}")

    print(f"\nVerified {len(run_dirs)} runs: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
