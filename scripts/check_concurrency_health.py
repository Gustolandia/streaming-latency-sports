#!/usr/bin/env python3
"""
check_concurrency_health.py
Health check script for concurrency test runs (N=5,10,20 for S1-S5).

Checks:
- Required files exist (tti_summary.json, meta.json, producer.csv, consumer.csv)
- Run completion status (n_producer >= n_matched >= 0)
- TTI values are reasonable (not extremely negative, within bounds)
- No errors in logs
- Metadata is valid

Usage:
    python check_concurrency_health.py --run-prefix <prefix>
    python check_concurrency_health.py --directory <runs_directory>
    python check_concurrency_health.py --list-runs
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# S1-S5 scenario mapping
SCENARIO_MAP = {
    's1': 'data/processed/replay_plans/s1/combined_plan.csv',
    's2': 'data/processed/replay_plans/s2/combined_plan.csv',
    's3': 'data/processed/replay_plans/s2full/combined_plan.csv',
    's4': 'data/processed/replay_plans/s2sf12/combined_plan.csv',
    's5': 'data/processed/replay_plans/s2sf12j2/combined_plan.csv',
}

# Expected concurrency levels
EXPECTED_N_LEVELS = [5, 10, 20]

# Expected number of feeds per concurrency level
EXPECTED_FEED_COUNTS = {
    5: 5,
    10: 10,
    20: 20,
}


def get_concurrency_from_run_id(run_id: str) -> Optional[int]:
    """Extract concurrency level (n) from run_id."""
    match = re.search(r'concurrency_n(\d+)', run_id)
    if match:
        return int(match.group(1))
    return None


def get_scenario_from_run_id(run_id: str) -> Optional[str]:
    """Extract scenario from run_id based on plan_csv in meta.json or naming pattern."""
    # Try to determine from run_id pattern
    # The pattern is: concurrency_n{N}_{YYYYMMDD_HHMMSS}_{backend}_feed{X}_rep1
    # The scenario is determined by the plan_csv which we need to read from meta.json
    return None


def get_scenario_from_meta(meta_path: Path) -> Optional[str]:
    """Extract scenario from meta.json's plan_csv field."""
    if not meta_path.exists():
        return None
    
    try:
        with open(meta_path, 'r', encoding='utf-8-sig') as f:
            meta = json.load(f)
        plan_csv = meta.get('plan_csv', '')
        
        for scenario, expected_plan in SCENARIO_MAP.items():
            if expected_plan in plan_csv:
                return scenario
        
        # Try to extract from path
        if 's1' in plan_csv:
            return 's1'
        elif 's2full' in plan_csv:
            return 's3'
        elif 's2sf12j2' in plan_csv:
            return 's5'
        elif 's2sf12' in plan_csv:
            return 's4'
        elif 's2' in plan_csv:
            return 's2'
        
    except (json.JSONDecodeError, IOError):
        pass
    
    return None


def get_feed_number_from_run_id(run_id: str) -> Optional[int]:
    """Extract feed number from run_id."""
    match = re.search(r'feed(\d+)', run_id)
    if match:
        return int(match.group(1))
    return None


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


def count_csv_rows(csv_path: Path) -> int:
    """Count the number of data rows in a CSV file (excluding header)."""
    if not csv_path.exists():
        return 0
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            return sum(1 for _ in reader)
    except Exception:
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                return sum(1 for _ in reader)
        except Exception:
            return 0


def check_event_counts(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that producer and consumer have reasonable event counts."""
    producer_csv = run_dir / "producer.csv"
    consumer_csv = run_dir / "consumer.csv"
    
    producer_count = count_csv_rows(producer_csv)
    consumer_count = count_csv_rows(consumer_csv)
    
    issues = []
    
    if producer_count == 0:
        issues.append("producer.csv has 0 events")
    if consumer_count == 0:
        issues.append("consumer.csv has 0 events")
    
    # Check n_matched from tti_summary.json
    tti_file = run_dir / "tti_summary.json"
    if tti_file.exists():
        try:
            with open(tti_file, 'r', encoding='utf-8-sig') as f:
                tti_data = json.load(f)
            
            n_matched = tti_data.get('n_matched') or tti_data.get('n_matched', 0)
            n_producer = tti_data.get('n_producer') or tti_data.get('n_produced', 0)
            n_consumer = tti_data.get('n_consumer') or tti_data.get('n_consumed', 0)
            
            if n_producer is not None and n_producer == 0:
                issues.append("tti_summary.json reports n_producer=0")
            if n_consumer is not None and n_consumer == 0:
                issues.append("tti_summary.json reports n_consumer=0")
            if n_matched is not None and n_matched == 0:
                issues.append("tti_summary.json reports n_matched=0")
            
            # Check sanity: n_producer >= n_matched >= 0
            if n_producer is not None and n_matched is not None:
                if n_matched > n_producer:
                    issues.append(f"n_matched ({n_matched}) > n_producer ({n_producer})")
        except (json.JSONDecodeError, IOError):
            issues.append("Failed to parse tti_summary.json")
    
    return len(issues) == 0, issues


def check_tti_values(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that TTI values are reasonable."""
    tti_file = run_dir / "tti_summary.json"
    
    if not tti_file.exists():
        return False, ["tti_summary.json not found"]
    
    try:
        with open(tti_file, 'r', encoding='utf-8-sig') as f:
            tti_data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        return False, [f"Failed to parse tti_summary.json: {e}"]
    
    issues = []
    
    # Handle both flat and nested TTI structures
    if 'tti_ms' in tti_data and isinstance(tti_data['tti_ms'], dict):
        tti_nested = tti_data['tti_ms']
        p50 = tti_nested.get('p50')
        p95 = tti_nested.get('p95')
        p99 = tti_nested.get('p99')
        max_tti = tti_nested.get('max')
        min_tti = tti_nested.get('min')
    else:
        p50 = tti_data.get('tti_ms_p50')
        p95 = tti_data.get('tti_ms_p95')
        p99 = tti_data.get('tti_ms_p99')
        max_tti = tti_data.get('tti_ms_max')
        min_tti = tti_data.get('tti_ms_min')
    
    # Check for negative TTI
    if p50 is not None and p50 < 0:
        issues.append(f"Negative median TTI: {p50} ms")
    
    if min_tti is not None and min_tti < -1000:
        issues.append(f"Extremely negative min TTI: {min_tti} ms")
    
    # Check for unreasonably high TTI (more than 5 minutes in ms = 300000)
    if max_tti is not None and max_tti > 300000:
        issues.append(f"Unreasonably high max TTI: {max_tti} ms")
    
    # Check for zero or negative percentiles
    if p50 is not None and p50 <= 0:
        issues.append(f"Non-positive median TTI: {p50} ms")
    
    return len(issues) == 0, issues


def check_metadata(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check that meta.json is valid and contains required fields."""
    meta_file = run_dir / "meta.json"
    
    if not meta_file.exists():
        return False, ["meta.json not found"]
    
    try:
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


def check_logs_for_errors(run_dir: Path) -> Tuple[bool, List[str]]:
    """Check log files for critical error messages."""
    log_files = ["producer.log", "consumer.log"]
    issues = []
    
    for log_file in log_files:
        log_path = run_dir / log_file
        if not log_path.exists():
            continue
        
        try:
            with open(log_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            
            # Check for critical error patterns
            error_patterns = [
                "Traceback",
                "Exception:",
                "Error:",
                "failed",
                "timeout",
                "connection refused",
                "ConnectionError",
                "KafkaError",
                "RedisError",
            ]
            
            for pattern in error_patterns:
                if pattern in content:
                    # Count occurrences
                    count = content.count(pattern)
                    issues.append(f"{log_file}: Found {count} occurrence(s) of '{pattern}'")
        except (IOError, UnicodeDecodeError):
            pass
    
    return len(issues) == 0, issues


def check_run_health(run_dir: Path) -> Dict:
    """Check a single run directory for health issues."""
    run_id = run_dir.name
    
    results = {
        "run_id": run_id,
        "status": "PASS",
        "issues": [],
        "checks": {},
        "concurrency": get_concurrency_from_run_id(run_id),
        "scenario": None,
        "backend": None,
        "feed_number": get_feed_number_from_run_id(run_id),
    }
    
    # Get metadata for scenario and backend
    meta_file = run_dir / "meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8-sig') as f:
                meta = json.load(f)
            results["backend"] = meta.get("backend")
            results["scenario"] = get_scenario_from_meta(meta_file)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Run all checks
    checks = [
        ("required_files", check_required_files),
        ("event_counts", check_event_counts),
        ("tti_values", check_tti_values),
        ("metadata", check_metadata),
        ("logs", check_logs_for_errors),
    ]
    
    for check_name, check_func in checks:
        passed, issues = check_func(run_dir)
        results["checks"][check_name] = "PASS" if passed else "FAIL"
        if not passed:
            results["status"] = "FAIL"
            results["issues"].extend(issues)
    
    return results


def discover_concurrency_runs(runs_dir: Path, prefix: str = None) -> List[Path]:
    """Discover concurrency test run directories."""
    runs = []
    
    if not runs_dir.exists():
        return runs
    
    pattern = re.compile(r'concurrency_n\d+_\d{8}_\d{6}_(kafka|redis)_feed\d+_rep\d+')
    
    for item in runs_dir.iterdir():
        if item.is_dir():
            if prefix:
                # If prefix is provided, check if name starts with it AND matches pattern
                if item.name.startswith(prefix) and pattern.match(item.name):
                    runs.append(item)
            elif pattern.match(item.name):
                runs.append(item)
    
    return sorted(runs)


def group_runs_by_test_suite(runs: List[Path]) -> Dict[str, List[Path]]:
    """Group runs by test suite (concurrency level + timestamp prefix)."""
    suites = {}
    
    for run in runs:
        run_id = run.name
        # Extract the prefix: concurrency_n{N}_YYYYMMDD_HHMMSS
        match = re.match(r'(concurrency_n\d+_\d{8}_\d{6})', run_id)
        if match:
            prefix = match.group(1)
            if prefix not in suites:
                suites[prefix] = []
            suites[prefix].append(run)
    
    return suites


def check_test_suite_health(suite_prefix: str, runs: List[Path]) -> Dict:
    """Check health of a complete test suite (all feeds for a concurrency level)."""
    results = {
        "suite_prefix": suite_prefix,
        "total_runs": len(runs),
        "passed_runs": 0,
        "failed_runs": 0,
        "run_results": [],
        "status": "PASS",
    }
    
    # Extract concurrency level from prefix
    match = re.search(r'concurrency_n(\d+)', suite_prefix)
    concurrency = int(match.group(1)) if match else None
    
    # Expected number of feeds
    expected_feeds = EXPECTED_FEED_COUNTS.get(concurrency, concurrency) if concurrency else None
    
    # Track backends and feeds
    backends_seen = set()
    feed_numbers = []
    scenarios_seen = set()
    
    for run in runs:
        run_result = check_run_health(run)
        results["run_results"].append(run_result)
        
        if run_result["status"] == "PASS":
            results["passed_runs"] += 1
        else:
            results["failed_runs"] += 1
            results["status"] = "FAIL"
        
        # Track metadata
        if run_result.get("backend"):
            backends_seen.add(run_result["backend"])
        if run_result.get("scenario"):
            scenarios_seen.add(run_result["scenario"])
        if run_result.get("feed_number") is not None:
            feed_numbers.append(run_result["feed_number"])
    
    # Additional suite-level checks
    suite_issues = []
    
    # Check we have both backends
    if backends_seen != {"kafka", "redis"}:
        suite_issues.append(f"Missing backends. Expected kafka and redis, got: {backends_seen}")
        results["status"] = "FAIL"
    
    # Check we have the expected number of feeds
    if expected_feeds and len(feed_numbers) != expected_feeds * 2:  # *2 for kafka + redis
        actual_feeds = len(feed_numbers)
        suite_issues.append(f"Expected {expected_feeds * 2} runs (2 backends × {expected_feeds} feeds), got {actual_feeds}")
        results["status"] = "FAIL"
    
    # Check feed numbers are consistent
    if feed_numbers:
        min_feed = min(feed_numbers)
        max_feed = max(feed_numbers)
        if max_feed - min_feed + 1 != len(set(feed_numbers)):
            suite_issues.append(f"Feed numbers are not consecutive: {sorted(set(feed_numbers))}")
    
    results["suite_issues"] = suite_issues
    
    return results


def print_run_report(results: Dict, verbose: bool = False) -> None:
    """Print a formatted report for a single run."""
    status_color = "\033[92mPASS\033[0m" if results["status"] == "PASS" else "\033[91mFAIL\033[0m"
    
    run_id = results.get("run_id", "unknown")
    concurrency = results.get("concurrency")
    backend = results.get("backend", "unknown")
    scenario = results.get("scenario", "unknown")
    feed = results.get("feed_number")
    
    info_parts = []
    if concurrency:
        info_parts.append(f"n={concurrency}")
    if backend:
        info_parts.append(f"backend={backend}")
    if scenario:
        info_parts.append(f"scenario={scenario}")
    if feed:
        info_parts.append(f"feed={feed}")
    
    info_str = f" [{', '.join(info_parts)}]" if info_parts else ""
    
    print(f"  {run_id}{info_str}: {status_color}")
    
    if results["status"] == "FAIL" and verbose:
        for issue in results.get("issues", []):
            print(f"    - {issue}")


def print_suite_report(suite_results: Dict, verbose: bool = False) -> None:
    """Print a formatted report for a test suite."""
    status_color = "\033[92mPASS\033[0m" if suite_results["status"] == "PASS" else "\033[91mFAIL\033[0m"
    
    print(f"\n{suite_results['suite_prefix']}: {status_color}")
    print(f"  Runs: {suite_results['passed_runs']}/{suite_results['total_runs']} passed")
    
    if suite_results.get("suite_issues"):
        print(f"  Suite issues:")
        for issue in suite_results["suite_issues"]:
            print(f"    - {issue}")
    
    if verbose:
        for run_result in suite_results["run_results"]:
            print_run_report(run_result, verbose=True)


def main():
    parser = argparse.ArgumentParser(
        description="Check health of concurrency test runs"
    )
    parser.add_argument(
        "--run-prefix",
        type=str,
        help="Run prefix to check (e.g., concurrency_n5_20260613_001322)"
    )
    parser.add_argument(
        "--directory",
        type=str,
        default="runs",
        help="Directory containing run directories (default: runs)"
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List all discovered concurrency runs and exit"
    )
    parser.add_argument(
        "--list-suites",
        action="store_true",
        help="List all discovered test suites and exit"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed information"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    runs_dir = Path(args.directory)
    
    # Discover runs
    if args.run_prefix:
        runs = []
        prefix_pattern = args.run_prefix
        for item in runs_dir.iterdir():
            if item.is_dir() and item.name.startswith(prefix_pattern):
                runs.append(item)
    else:
        runs = discover_concurrency_runs(runs_dir)
    
    if not runs:
        print(f"No concurrency runs found in {runs_dir}")
        sys.exit(1)
    
    # List runs and exit if requested
    if args.list_runs:
        print("Discovered concurrency runs:")
        for run in sorted(runs):
            print(f"  {run.name}")
        print(f"\nTotal: {len(runs)} runs")
        sys.exit(0)
    
    # Group into test suites
    suites = group_runs_by_test_suite(runs)
    
    # List suites and exit if requested
    if args.list_suites:
        print("Discovered test suites:")
        for suite_prefix, suite_runs in sorted(suites.items()):
            print(f"  {suite_prefix}: {len(suite_runs)} runs")
        print(f"\nTotal: {len(suites)} suites")
        sys.exit(0)
    
    print(f"Checking health of {len(runs)} runs in {len(suites)} test suite(s)...")
    
    # Check all runs and group by suite
    all_results = []
    suite_results = {}
    
    for suite_prefix, suite_runs in sorted(suites.items()):
        suite_result = check_test_suite_health(suite_prefix, suite_runs)
        suite_results[suite_prefix] = suite_result
        all_results.extend(suite_result["run_results"])
    
    # Print reports
    for suite_prefix, suite_result in sorted(suite_results.items()):
        print_suite_report(suite_result, args.verbose)
    
    # Summary
    total_runs = sum(sr["total_runs"] for sr in suite_results.values())
    total_passed = sum(sr["passed_runs"] for sr in suite_results.values())
    total_failed = sum(sr["failed_runs"] for sr in suite_results.values())
    total_suites = len(suite_results)
    passed_suites = sum(1 for sr in suite_results.values() if sr["status"] == "PASS")
    
    print("\n" + "=" * 60)
    print("HEALTH CHECK SUMMARY")
    print("=" * 60)
    print(f"Test suites: {passed_suites}/{total_suites} passed")
    print(f"Total runs: {total_passed}/{total_runs} passed")
    print(f"Failure rate: {(total_failed / total_runs * 100):.1f}%")
    
    if all_results:
        pass_rate = (total_passed / total_runs) * 100
        print(f"Overall pass rate: {pass_rate:.1f}%")
    
    if args.json:
        print("\n" + "=" * 60)
        print("JSON Results:")
        print("=" * 60)
        output = {
            "summary": {
                "total_suites": total_suites,
                "passed_suites": passed_suites,
                "total_runs": total_runs,
                "passed_runs": total_passed,
                "failed_runs": total_failed,
                "pass_rate": pass_rate,
            },
            "suites": suite_results,
        }
        print(json.dumps(output, indent=2, default=str))
    
    # Exit code
    if total_failed > 0:
        print("\n[WARNING] Some runs failed health checks")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All runs passed health checks")
        sys.exit(0)


if __name__ == "__main__":
    main()
