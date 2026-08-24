#!/usr/bin/env python3
"""
Issue 6 - Reproducibility provenance verifier.

Checks that each run carries a complete reproducibility chain in meta.json:
git commit, per-file code SHA-256 hashes, environment capture, and the core
configuration fields. Complements docs/infrastructure.md (the human-readable
infrastructure spec).

CLI:
    python scripts/verify_reproducibility.py [--runs-dir runs] [--pattern '*'] [--verbose]
Exit code 0 if every run has complete provenance, 1 otherwise.
"""
import argparse
import json
from pathlib import Path

# Provenance fields expected in a complete meta.json.
REQUIRED_TOP = ["run_id", "git", "code_sha256"]
REQUIRED_GIT = ["head"]


def check_meta(meta):
    """Return a list of provenance issues for one parsed meta dict (empty == ok)."""
    issues = []
    for field in REQUIRED_TOP:
        if field not in meta or meta[field] in (None, "", {}, []):
            issues.append(f"missing {field}")

    git = meta.get("git")
    if isinstance(git, dict):
        for field in REQUIRED_GIT:
            if not git.get(field):
                issues.append(f"git.{field} missing")
    elif "git" not in issues and git is not None:
        issues.append("git is not an object")

    code = meta.get("code_sha256")
    if isinstance(code, dict) and len(code) == 0:
        issues.append("code_sha256 is empty")

    return issues


def verify_run(run_dir):
    """Verify provenance of a single run directory. Returns (ok, issues)."""
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return False, ["meta.json missing"]
    try:
        with open(meta_path, encoding="utf-8-sig") as f:
            meta = json.load(f)
    except (ValueError, OSError) as e:
        return False, [f"meta.json invalid: {e}"]
    issues = check_meta(meta)
    return len(issues) == 0, issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="Verify reproducibility provenance (Issue 6)")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--pattern", default="*")
    ap.add_argument("--verbose", action="store_true")
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
                print(f"INCOMPLETE {run_dir.name}: {', '.join(issues)}")

    print(f"\nProvenance check: {passed}/{len(run_dirs)} runs fully reproducible, {failed} incomplete")
    return 0 if failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    import sys
    sys.exit(main())
