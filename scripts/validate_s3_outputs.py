#!/usr/bin/env python3
"""
S3 Output Quality Validator
Validates completeness and correctness of all S3 canonical run outputs.
"""
import json
import csv
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class RunValidation:
    run_id: str
    status: str = "PASS"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    files: Dict[str, bool] = field(default_factory=dict)
    event_counts: Dict[str, int] = field(default_factory=dict)
    meta: Optional[dict] = None


@dataclass
class ValidationSummary:
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    details: List[RunValidation] = field(default_factory=list)


def validate_run(run_dir: Path) -> RunValidation:
    """Validate a single run directory."""
    result = RunValidation(run_id=run_dir.name)
    
    # Required files
    required_files = [
        "meta.json",
        "producer.csv",
        "consumer.csv",
        "consumer_events.csv",
        "tti_summary.json"
    ]
    
    # Check file existence
    for fname in required_files:
        fpath = run_dir / fname
        exists = fpath.exists() and fpath.stat().st_size > 0
        result.files[fname] = exists
        if not exists:
            result.errors.append(f"Missing or empty: {fname}")
            result.status = "FAIL"
    
    # Load and validate meta.json
    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        try:
            with open(meta_path, encoding='utf-8-sig') as f:
                result.meta = json.load(f)
            
            # Check required meta fields
            required_meta = ["run_id", "backend", "plan_csv", "speedup", "max_t_sim"]
            for field_name in required_meta:
                if field_name not in result.meta:
                    result.errors.append(f"meta.json missing field: {field_name}")
                    result.status = "FAIL"
            
            # Validate backend
            if result.meta.get("backend") not in ["kafka", "redis"]:
                result.errors.append(f"Invalid backend: {result.meta.get('backend')}")
                result.status = "FAIL"
                
        except Exception as e:
            result.errors.append(f"meta.json invalid: {e}")
            result.status = "FAIL"
    
    # Check CSV files have data
    csv_files = ["producer.csv", "consumer.csv", "consumer_events.csv"]
    for csv_name in csv_files:
        csv_path = run_dir / csv_name
        if csv_path.exists():
            try:
                with open(csv_path, encoding='utf-8-sig') as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    row_count = sum(1 for _ in reader)
                    result.event_counts[csv_name] = row_count
                    
                    if row_count == 0:
                        result.errors.append(f"{csv_name} has no data rows")
                        result.status = "FAIL"
                        
                    # Check for expected columns
                    if "event_id" not in header and csv_name != "tti_summary.json":
                        result.warnings.append(f"{csv_name} missing event_id column")
                        
            except Exception as e:
                result.errors.append(f"{csv_name} invalid: {e}")
                result.status = "FAIL"
    
    # Validate tti_summary.json
    tti_path = run_dir / "tti_summary.json"
    if tti_path.exists():
        try:
            with open(tti_path, encoding='utf-8-sig') as f:
                tti_data = json.load(f)
            
            if not tti_data:
                result.errors.append("tti_summary.json is empty")
                result.status = "FAIL"
            else:
                result.event_counts["tti_summary.json"] = len(tti_data)
                
        except Exception as e:
            result.errors.append(f"tti_summary.json invalid: {e}")
            result.status = "FAIL"
    
    # Cross-validate event counts
    if "producer.csv" in result.event_counts and "consumer.csv" in result.event_counts:
        prod_count = result.event_counts["producer.csv"]
        cons_count = result.event_counts["consumer.csv"]
        
        # Allow for some difference due to filtering, but not too much
        if abs(prod_count - cons_count) > prod_count * 0.1:
            result.warnings.append(
                f"Event count mismatch: producer={prod_count}, consumer={cons_count} "
                f"(diff: {abs(prod_count - cons_count)})"
            )
    
    return result


def validate_all_runs(run_list_path: Path) -> ValidationSummary:
    """Validate all runs from a run list file."""
    summary = ValidationSummary()
    
    if not run_list_path.exists():
        print(f"ERROR: Run list not found: {run_list_path}")
        sys.exit(1)
    
    with open(run_list_path, encoding='utf-8-sig') as f:
        run_ids = [line.strip() for line in f if line.strip()]
    
    summary.total_runs = len(run_ids)
    
    for run_id in run_ids:
        run_dir = Path("runs") / run_id
        
        if not run_dir.exists():
            result = RunValidation(run_id=run_id, status="FAIL")
            result.errors.append(f"Directory not found: {run_dir}")
            summary.details.append(result)
            summary.failed += 1
            continue
        
        result = validate_run(run_dir)
        summary.details.append(result)
        
        if result.status == "PASS":
            if result.warnings:
                summary.warnings += 1
            summary.passed += 1
        else:
            summary.failed += 1
        
        # Print progress
        status_icon = "[PASS]" if result.status == "PASS" else "[FAIL]"
        print(f"  {status_icon} {run_id}: {result.status} ({len(result.errors)} errors, {len(result.warnings)} warnings)")
    
    return summary


def print_summary(summary: ValidationSummary):
    """Print validation summary."""
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total runs:  {summary.total_runs}")
    print(f"Passed:      {summary.passed} ({100*summary.passed/summary.total_runs:.1f}%)")
    print(f"Failed:      {summary.failed} ({100*summary.failed/summary.total_runs:.1f}%)")
    print(f"With warnings: {summary.warnings}")
    
    if summary.failed > 0:
        print("\nFAILED RUNS:")
        for detail in summary.details:
            if detail.status == "FAIL":
                print(f"\n  {detail.run_id}:")
                for error in detail.errors:
                    print(f"    ERROR: {error}")
    
    if summary.warnings > 0:
        print("\nRUNS WITH WARNINGS:")
        for detail in summary.details:
            if detail.warnings:
                print(f"\n  {detail.run_id}:")
                for warning in detail.warnings:
                    print(f"    WARNING: {warning}")
    
    print("\n" + "=" * 80)
    
    # Return exit code
    return 0 if summary.failed == 0 else 1


def validate_config_consistency(details: List[RunValidation]):
    """Check that configs are consistent across runs."""
    print("\n" + "=" * 80)
    print("CONFIG CONSISTENCY CHECK")
    print("=" * 80)
    
    issues = []
    
    # Group by scenario
    scenarios = {}
    for detail in details:
        if not detail.meta:
            continue
        
        run_id = detail.run_id
        # Extract scenario from run_id: s3_<scenario>_<backend>_rep<N>_<date>
        parts = run_id.split("_")
        if len(parts) >= 3:
            scenario = parts[1]
            backend = parts[2]
            rep = parts[3]
            
            if scenario not in scenarios:
                scenarios[scenario] = {}
            if rep not in scenarios[scenario]:
                scenarios[scenario][rep] = {}
            scenarios[scenario][rep][backend] = detail.meta
    
    # Check each scenario
    for scenario, reps in scenarios.items():
        print(f"\nScenario: {scenario}")
        
        for rep, backends in reps.items():
            kafka_config = backends.get("kafka")
            redis_config = backends.get("redis")
            
            if kafka_config and redis_config:
                # Compare key configs
                key_fields = ["speedup", "max_t_sim", "plan_csv"]
                for field in key_fields:
                    kafka_val = kafka_config.get(field)
                    redis_val = redis_config.get(field)
                    if kafka_val != redis_val:
                        issues.append(
                            f"  {scenario} {rep}: {field} mismatch - "
                            f"kafka={kafka_val}, redis={redis_val}"
                        )
                
                # Check S3-specific configs
                if kafka_config.get("s3_mode") != redis_config.get("s3_mode"):
                    issues.append(
                        f"  {scenario} {rep}: s3_mode mismatch"
                    )
    
    if issues:
        print("\nCONFIG ISSUES FOUND:")
        for issue in issues:
            print(issue)
    else:
        print("\n[OK] All configs are consistent between Kafka and Redis")
    
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Validate S3 output quality")
    parser.add_argument(
        "--runlist", 
        default="runs/_paper_s3_official_runs.txt",
        help="Path to run list file"
    )
    args = parser.parse_args()
    
    print("Validating S3 outputs...")
    print(f"Run list: {args.runlist}")
    
    summary = validate_all_runs(Path(args.runlist))
    validate_config_consistency(summary.details)
    
    exit_code = print_summary(summary)
    sys.exit(exit_code)
