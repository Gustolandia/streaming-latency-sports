#!/usr/bin/env python3
"""
S4 Parameter Sweep Output Quality Validator
Validates completeness, correctness, and S4-specific metrics for all 32 S4 runs.
"""
import json
import csv
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import argparse


EXPECTED_EVENTS_S2SF12 = 4554  # From S3 runs
EXPECTED_EVENTS_S2SF12J2 = 4554  # From S3 runs


@dataclass
class RunValidation:
    run_id: str
    status: str = "PASS"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    files: Dict[str, bool] = field(default_factory=dict)
    event_counts: Dict[str, int] = field(default_factory=dict)
    meta: Optional[dict] = None
    s4_specific: Dict[str, any] = field(default_factory=dict)


@dataclass 
class ValidationSummary:
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    details: List[RunValidation] = field(default_factory=list)
    scenario_counts: Dict[str, int] = field(default_factory=dict)
    config_counts: Dict[str, int] = field(default_factory=dict)
    backend_counts: Dict[str, int] = field(default_factory=dict)


def get_expected_events(scenario: str) -> int:
    """Get expected event count for scenario."""
    if "s2sf12j2" in scenario:
        return EXPECTED_EVENTS_S2SF12J2
    elif "s2sf12" in scenario:
        return EXPECTED_EVENTS_S2SF12
    return 4000  # Fallback


def validate_run(run_dir: Path) -> RunValidation:
    """Validate a single S4 run directory."""
    result = RunValidation(run_id=run_dir.name)
    
    # Required files for S4 (same as S3)
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
    
    # Load and validate meta.json with S4-specific checks
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
            
            # S4-specific: check for S3 mode parameters
            s4_params = ["corrections_every_k", "correction_delay_s"]
            # These should be in producer/consumer configs, check tti_summary for S4 metadata
            
        except Exception as e:
            result.errors.append(f"meta.json invalid: {e}")
            result.status = "FAIL"
    else:
        result.errors.append("meta.json missing")
        result.status = "FAIL"
    
    # Check CSV files have data
    csv_files = ["producer.csv", "consumer.csv", "consumer_events.csv"]
    total_producer_events = 0
    total_consumer_events = 0
    
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
                    
                    if csv_name == "producer.csv":
                        total_producer_events = row_count
                    elif csv_name == "consumer.csv":
                        total_consumer_events = row_count
                        
            except Exception as e:
                result.errors.append(f"{csv_name} invalid: {e}")
                result.status = "FAIL"
    
    # S4-specific validation: event counts should match
    if total_producer_events > 0 and total_consumer_events > 0:
        if total_producer_events != total_consumer_events:
            result.warnings.append(
                f"Event count mismatch: producer={total_producer_events}, consumer={total_consumer_events}"
            )
    
    # Validate tti_summary.json
    tti_path = run_dir / "tti_summary.json"
    if tti_path.exists():
        try:
            with open(tti_path, encoding='utf-8-sig') as f:
                tti_data = json.load(f)
            
            # Check for S4-relevant metrics
            result.s4_specific["tti_summary"] = True
            
            # Check matched events count
            if "matched_events" in tti_data:
                result.s4_specific["matched_events"] = tti_data["matched_events"]
                expected = get_expected_events(run_dir.name)
                if tti_data["matched_events"] != expected:
                    result.warnings.append(
                        f"Matched events ({tti_data['matched_events']}) != expected ({expected})"
                    )
            
            # Check for percentiles
            for p in ["p50", "p95", "p99"]:
                if p in tti_data:
                    result.s4_specific[p] = tti_data[p]
                else:
                    result.warnings.append(f"Missing percentile: {p}")
                    
        except Exception as e:
            result.errors.append(f"tti_summary.json invalid: {e}")
            result.status = "FAIL"
    else:
        result.errors.append("tti_summary.json missing")
        result.status = "FAIL"
    
    # Extract S4 configuration from run_id
    # Format: s4_<scenario>_<config>_<backend>_rep<N>_<date>
    # Config names can have underscores: low_speedup, high_frequency, etc.
    try:
        parts = result.run_id.split("_")
        # parts[0] = 's4', parts[1] = scenario (s2sf12 or s2sf12j2)
        # Need to find where config ends and backend begins
        # Backend is either 'kafka' or 'redis', then 'repN' follows
        valid_backends = ["kafka", "redis"]
        backend_idx = None
        for i, part in enumerate(parts):
            if part in valid_backends:
                backend_idx = i
                break
        
        if backend_idx is not None and backend_idx >= 3:
            result.s4_specific["scenario"] = parts[1]
            # Config is everything between scenario and backend
            result.s4_specific["config"] = "_".join(parts[2:backend_idx])
            result.s4_specific["backend"] = parts[backend_idx]
        else:
            result.warnings.append(f"Could not parse run_id {result.run_id}")
    except Exception as e:
        result.warnings.append(f"Error parsing run_id: {e}")
    
    # Validate config name
    valid_configs = [
        "baseline", "low_speedup", "high_speedup",
        "high_frequency", "low_frequency", "long_delay",
        "short_delay", "fast_corrections"
    ]
    if "config" in result.s4_specific:
        if result.s4_specific["config"] not in valid_configs:
            result.warnings.append(f"Unknown config: {result.s4_specific['config']}")
    
    return result


def find_s4_run_dirs(runs_dir: Path) -> List[Path]:
    """Find all S4 run directories."""
    s4_dirs = []
    if runs_dir.exists():
        for item in runs_dir.iterdir():
            if item.is_dir() and item.name.startswith("s4_"):
                s4_dirs.append(item)
    return sorted(s4_dirs)


def validate_all_s4_runs(runs_dir: Path = Path("runs")) -> ValidationSummary:
    """Validate all S4 runs."""
    summary = ValidationSummary()
    run_dirs = find_s4_run_dirs(runs_dir)
    
    if not run_dirs:
        summary.errors.append("No S4 run directories found")
        return summary
    
    summary.total_runs = len(run_dirs)
    
    for run_dir in run_dirs:
        result = validate_run(run_dir)
        summary.details.append(result)
        
        if result.status == "PASS":
            summary.passed += 1
        else:
            summary.failed += 1
        
        summary.warnings += len(result.warnings)
        
        # Track counts
        if "scenario" in result.s4_specific:
            scen = result.s4_specific["scenario"]
            summary.scenario_counts[scen] = summary.scenario_counts.get(scen, 0) + 1
        if "config" in result.s4_specific:
            cfg = result.s4_specific["config"]
            summary.config_counts[cfg] = summary.config_counts.get(cfg, 0) + 1
        if "backend" in result.s4_specific:
            be = result.s4_specific["backend"]
            summary.backend_counts[be] = summary.backend_counts.get(be, 0) + 1
    
    return summary


def print_summary(summary: ValidationSummary, verbose: bool = False) -> None:
    """Print validation summary."""
    print("=" * 80)
    print("S4 PARAMETER SWEEP OUTPUT VALIDATION")
    print("=" * 80)
    print(f"\nTotal runs: {summary.total_runs}")
    print(f"Passed: {summary.passed}")
    print(f"Failed: {summary.failed}")
    print(f"Warnings: {summary.warnings}")
    
    print(f"\nScenarios: {dict(summary.scenario_counts)}")
    print(f"Configs: {dict(summary.config_counts)}")
    print(f"Backends: {dict(summary.backend_counts)}")
    
    if summary.failed > 0:
        print(f"\n{'FAILED RUNS:':-^80}")
        for detail in summary.details:
            if detail.status == "FAIL":
                print(f"\n{detail.run_id}:")
                for error in detail.errors:
                    print(f"  ERROR: {error}")
    
    if summary.warnings > 0 and verbose:
        print(f"\n{'WARNINGS:':-^80}")
        for detail in summary.details:
            if detail.warnings:
                print(f"\n{detail.run_id}:")
                for warning in detail.warnings:
                    print(f"  WARN: {warning}")
    
    if summary.failed == 0:
        print(f"\n{'ALL S4 RUN OUTPUTS VALIDATED SUCCESSFULLY':-^80}")
    else:
        print(f"\n{'VALIDATION FAILED':-^80}")
        sys.exit(1)


def save_report(summary: ValidationSummary, output_path: Path) -> None:
    """Save detailed report to JSON."""
    report = {
        "summary": {
            "total_runs": summary.total_runs,
            "passed": summary.passed,
            "failed": summary.failed,
            "warnings": summary.warnings,
        },
        "scenarios": summary.scenario_counts,
        "configs": summary.config_counts,
        "backends": summary.backend_counts,
        "runs": []
    }
    
    for detail in summary.details:
        run_report = {
            "run_id": detail.run_id,
            "status": detail.status,
            "errors": detail.errors,
            "warnings": detail.warnings,
            "files": detail.files,
            "event_counts": detail.event_counts,
            "s4_specific": detail.s4_specific
        }
        report["runs"].append(run_report)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\nDetailed report saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Validate S4 parameter sweep outputs")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"), help="Runs directory")
    parser.add_argument("--output", type=Path, default=Path("validation_s4_report.json"), help="Output report path")
    parser.add_argument("--verbose", action="store_true", help="Show warnings")
    args = parser.parse_args()
    
    summary = validate_all_s4_runs(args.runs_dir)
    print_summary(summary, args.verbose)
    save_report(summary, args.output)


if __name__ == "__main__":
    main()
