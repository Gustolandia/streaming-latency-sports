#!/usr/bin/env python3
"""
verify_run_quality.py
Verifies the quality and completeness of benchmark run outputs.
Checks for: required files, matching event counts, valid TTI values, no errors in logs.

Usage:
    python verify_run_quality.py --run-id <run_id>
    python verify_run_quality.py --run-list <run_list_file>
    python verify_run_quality.py --directory <runs_directory>
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def check_required_files(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that all required files exist in the run directory."""
    required_files = [
        "producer.csv",
        "consumer.csv",
        "tti_summary.json",
        "tti_summary.printed.json",
        "meta.json",
    ]
    
    missing = []
    for f in required_files:
        file_path = run_dir / f
        if not file_path.exists():
            missing.append(f)
    
    return len(missing) == 0, missing


def check_consumer_events_file(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that consumer_events.csv exists (for S3 runs)."""
    consumer_events = run_dir / "consumer_events.csv"
    try:
        if not consumer_events.exists():
            return False, ["consumer_events.csv"]
    except Exception as e:
        return False, [f"Error checking consumer_events.csv: {e}"]
    return True, []


def count_csv_rows(csv_path: Path) -> int:
    """Count the number of data rows in a CSV file (excluding header)."""
    if not csv_path.exists():
        return 0
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            return sum(1 for _ in reader)
    except Exception as e:
        # Try with utf-8 if utf-8-sig fails
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return sum(1 for _ in reader)
        except Exception:
            return 0


def check_event_counts(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that producer and consumer have matching event counts."""
    producer_csv = run_dir / "producer.csv"
    consumer_csv = run_dir / "consumer.csv"
    
    producer_count = count_csv_rows(producer_csv)
    consumer_count = count_csv_rows(consumer_csv)
    
    if producer_count == 0:
        return False, ["producer.csv has 0 events"]
    if consumer_count == 0:
        return False, ["consumer.csv has 0 events"]
    
    # Allow small difference due to filtering or timing
    diff = abs(producer_count - consumer_count)
    max_allowed_diff = max(10, producer_count * 0.01)  # 1% or 10 events, whichever is larger
    
    if diff > max_allowed_diff:
        return False, [
            f"Event count mismatch: producer={producer_count}, consumer={consumer_count}, diff={diff}"
        ]
    
    return True, []


def check_tti_values(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that TTI values are reasonable (not negative, within expected ranges)."""
    tti_file = run_dir / "tti_summary.json"
    
    if not tti_file.exists():
        return False, ["tti_summary.json not found"]
    
    try:
        # Handle UTF-8 BOM
        with open(tti_file, 'r', encoding='utf-8-sig') as f:
            tti_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, [f"Failed to parse tti_summary.json: {e}"]
    
    issues = []
    
    # Check for negative TTI
    if 'tti_ms_p50' in tti_data and tti_data['tti_ms_p50'] < 0:
        issues.append(f"Negative median TTI: {tti_data['tti_ms_p50']} ms")
    
    if 'tti_ms_min' in tti_data and tti_data['tti_ms_min'] < -1000:  # Allow small negative due to clock skew
        issues.append(f"Extremely negative min TTI: {tti_data['tti_ms_min']} ms")
    
    # Check for unreasonably high TTI (more than 5 minutes in ms)
    if 'tti_ms_max' in tti_data and tti_data['tti_ms_max'] > 300000:
        issues.append(f"Unreasonably high max TTI: {tti_data['tti_ms_max']} ms")
    
    # Check n_matched
    if 'n_matched' in tti_data:
        if tti_data['n_matched'] == 0:
            issues.append("No events matched between producer and consumer")
    
    return len(issues) == 0, issues


def check_logs_for_errors(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check log files for error messages."""
    log_files = ["producer.log", "consumer.log"]
    issues = []
    
    for log_file in log_files:
        log_path = run_dir / log_file
        if not log_path.exists():
            continue
        
        try:
            with open(log_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            
            # Check for common error patterns
            error_patterns = [
                "Traceback",
                "Error:",
                "Exception",
                "failed",
                "timeout",
                "connection refused",
                "ConnectionError",
                "KafkaError",
                "RedisError",
            ]
            
            for pattern in error_patterns:
                if pattern in content:
                    # Get context around the error
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if pattern in line:
                            start = max(0, i - 2)
                            end = min(len(lines), i + 3)
                            issues.append(f"{log_file}:{i+1} - {' '.join(lines[start:end])}")
        except (IOError, UnicodeDecodeError):
            pass
    
    return len(issues) == 0, issues


def check_metadata(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that meta.json is valid and contains required fields."""
    meta_file = run_dir / "meta.json"
    
    if not meta_file.exists():
        return False, ["meta.json not found"]
    
    try:
        # Handle UTF-8 BOM
        with open(meta_file, 'r', encoding='utf-8-sig') as f:
            meta = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, [f"Failed to parse meta.json: {e}"]
    
    required_fields = ["run_id", "backend", "plan_csv"]
    missing = [f for f in required_fields if f not in meta]
    
    if missing:
        return False, [f"Missing required fields in meta.json: {missing}"]
    
    # Check backend is valid
    if meta.get("backend") not in ["kafka", "redis"]:
        return False, [f"Invalid backend in meta.json: {meta.get('backend')}"]
    
    return True, []


def check_run(run_dir: Path) -> Dict:
    """Check a single run directory for quality issues."""
    results = {
        "run_id": run_dir.name,
        "status": "PASS",
        "issues": [],
        "checks": {}
    }
    
    # Run all checks
    checks = [
        ("required_files", check_required_files),
        ("consumer_events", check_consumer_events_file),
        ("event_counts", check_event_counts),
        ("tti_values", check_tti_values),
        ("logs", check_logs_for_errors),
        ("metadata", check_metadata),
    ]
    
    for check_name, check_func in checks:
        passed, issues = check_func(run_dir)
        results["checks"][check_name] = "PASS" if passed else "FAIL"
        if not passed:
            results["status"] = "FAIL"
            results["issues"].extend(issues)
    
    return results


def print_run_report(results: Dict, verbose: bool = False) -> None:
    """Print a formatted report for a single run."""
    status_color = "\033[92mPASS\033[0m" if results["status"] == "PASS" else "\033[91mFAIL\033[0m"
    
    print(f"\n{results['run_id']}: {status_color}")
    
    if results["status"] == "FAIL":
        print(f"  Issues: {len(results['issues'])}")
        if verbose:
            for issue in results["issues"]:
                print(f"    - {issue}")
        
        print("  Check results:")
        for check_name, status in results["checks"].items():
            check_color = "\033[92m" if status == "PASS" else "\033[91m"
            print(f"    {check_name}: {check_color}{status}\033[0m")
    else:
        print(f"  All checks passed")


def main():
    ap = argparse.ArgumentParser(description="Verify the quality of benchmark run outputs")
    ap.add_argument("--run-id", type=str, help="Single run ID to verify")
    ap.add_argument("--run-list", type=str, help="File containing list of run directories (one per line)")
    ap.add_argument("--directory", type=str, default="runs", help="Directory containing run directories (default: runs)")
    ap.add_argument("--verbose", action="store_true", help="Show detailed error information")
    ap.add_argument("--json", action="store_true", help="Output results as JSON")
    ap.add_argument("--fail-fast", action="store_true", help="Exit on first failure")
    
    args = ap.parse_args()
    
    # Determine which runs to check
    runs_to_check = []
    
    if args.run_id:
        runs_to_check = [Path(args.directory) / args.run_id]
    elif args.run_list:
        # Try different encodings for the run list file
        encodings = ['utf-8-sig', 'utf-16', 'utf-8']
        found_encoding = None
        for encoding in encodings:
            try:
                with open(args.run_list, 'r', encoding=encoding) as test_f:
                    test_f.read()
                found_encoding = encoding
                break
            except (UnicodeDecodeError, IOError):
                continue
        
        if found_encoding is None:
            print(f"Cannot read run list file with any encoding: {args.run_list}")
            sys.exit(1)
        
        with open(args.run_list, 'r', encoding=found_encoding) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Handle both "runs/run_id", "run_id", and Windows paths with backslashes
                    # Replace backslashes with forward slashes for Path
                    line = line.replace('\\', '/')
                    run_path = Path(line)
                    if not run_path.is_absolute():
                        # If the path already contains "runs", don't duplicate it
                        if 'runs' in str(run_path).lower():
                            run_path = run_path
                        else:
                            run_path = Path(args.directory) / run_path
                    runs_to_check.append(run_path)
    else:
        # Check all subdirectories in the runs directory
        runs_dir = Path(args.directory)
        if runs_dir.exists():
            for item in sorted(runs_dir.iterdir()):
                if item.is_dir() and not item.name.startswith('_'):
                    runs_to_check.append(item)
    
    if not runs_to_check:
        print("No runs to check. Please specify --run-id, --run-list, or ensure --directory exists.")
        sys.exit(1)
    
    print(f"Verifying {len(runs_to_check)} run(s)...")
    
    all_results = []
    passed_count = 0
    failed_count = 0
    
    for run_dir in runs_to_check:
        if not run_dir.exists():
            print(f"\n{run_dir.name}: \033[91mMISSING\033[0m")
            all_results.append({
                "run_id": run_dir.name,
                "status": "MISSING",
                "issues": [f"Directory not found: {run_dir}"]
            })
            failed_count += 1
            continue
        
        try:
            results = check_run(run_dir)
            all_results.append(results)
            
            if results["status"] == "PASS":
                passed_count += 1
            else:
                failed_count += 1
            
            print_run_report(results, args.verbose)
            
            if args.fail_fast and results["status"] == "FAIL":
                print("\nFailing fast due to --fail-fast flag")
                break
        except Exception as e:
            import traceback
            print(f"\n{run_dir.name}: \033[91mERROR\033[0m - {e}")
            if args.verbose:
                traceback.print_exc()
            all_results.append({
                "run_id": run_dir.name,
                "status": "ERROR",
                "issues": [str(e)]
            })
            failed_count += 1
    
    # Print summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total runs checked: {len(all_results)}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    
    if all_results:
        pass_rate = (passed_count / len(all_results)) * 100
        print(f"Pass rate: {pass_rate:.1f}%")
    
    if args.json:
        print("\n" + "=" * 60)
        print("JSON Results:")
        print("=" * 60)
        print(json.dumps(all_results, indent=2))
    
    # Return appropriate exit code
    if failed_count > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
