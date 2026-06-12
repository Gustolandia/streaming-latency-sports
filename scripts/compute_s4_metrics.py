#!/usr/bin/env python3
"""
Compute S4 per-run metrics from parameter sweep.
Wrapper around compute_s3_metrics for S4 runs.

Usage:
    python scripts/compute_s4_metrics.py [--runlist RUNLIST] [--out OUTPUT]
"""
import subprocess
import sys
from pathlib import Path


def main():
    """Compute S4 metrics."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Compute S4 parameter sweep metrics")
    parser.add_argument(
        "--runlist",
        default="runs/_paper_s4_parameter_sweep.txt",
        help="Path to S4 run list file (default: runs/_paper_s4_parameter_sweep.txt)"
    )
    parser.add_argument(
        "--out",
        default="data/processed/results/paper_s4_parameter_sweep.csv",
        help="Output CSV path (default: data/processed/results/paper_s4_parameter_sweep.csv)"
    )
    
    args = parser.parse_args()
    
    # Run compute_s3_metrics with S4 paths
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "compute_s3_metrics.py"),
        "--runlist", args.runlist,
        "--out", args.out
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print("Error computing S4 metrics:")
        print(result.stderr)
        sys.exit(result.returncode)
    
    print(result.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
