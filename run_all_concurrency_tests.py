#!/usr/bin/env python3
"""
Run concurrency tests for S1-S5 scenarios with n=5, n=10, n=20.
This script orchestrates the concurrency tests using the existing plan files.

S1-S5 mapping:
  S1 -> s1/combined_plan.csv
  S2 -> s2/combined_plan.csv
  S3 -> s2full/combined_plan.csv
  S4 -> s2sf12/combined_plan.csv
  S5 -> s2sf12j2/combined_plan.csv
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

# S1-S5 scenario mapping to plan files
SCENARIO_MAP = {
    's1': 'data/processed/replay_plans/s1/combined_plan.csv',
    's2': 'data/processed/replay_plans/s2/combined_plan.csv',
    's3': 'data/processed/replay_plans/s2full/combined_plan.csv',
    's4': 'data/processed/replay_plans/s2sf12/combined_plan.csv',
    's5': 'data/processed/replay_plans/s2sf12j2/combined_plan.csv',
}

# Default concurrency levels to test
DEFAULT_N_LEVELS = [5, 10, 20]

# Default number of repetitions
DEFAULT_REPS = 1

def run_concurrency_test(n: int, plan_csv: str, reps: int = 1, speedup: int = 120, 
                         max_t_sim: int = 600) -> bool:
    """Run a single concurrency test."""
    cmd = [
        sys.executable,
        'scripts/run_concurrency_test.py',
        str(n),
        str(plan_csv),
        str(reps),
        '--speedup', str(speedup),
        '--max-t-sim', str(max_t_sim)
    ]
    
    print(f"  Running: python {' '.join(cmd[1:])}")
    
    try:
        result = subprocess.run(cmd, check=True, text=True, 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Print only summary lines to avoid too much output
        output = result.stdout or ''
        for line in output.split('\n'):
            if any(kw in line for kw in ['Starting', 'Prefix:', 'Rep', 'completed', 
                                         'SUCCESS', 'FAILED', 'Total runs', 'Concurrency']):
                print(f"  {line}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [FAILED] Exit code {e.returncode}")
        if e.stderr:
            print(f"  Error: {e.stderr[-200:]}")
        if e.stdout:
            print(f"  Output: {e.stdout[-200:]}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Run concurrency tests for S1-S5 scenarios'
    )
    parser.add_argument('--scenarios', nargs='+', 
                        default=['s1', 's2', 's3', 's4', 's5'],
                        choices=list(SCENARIO_MAP.keys()),
                        help='Scenarios to test (s1-s5, default: all)')
    parser.add_argument('--n-levels', nargs='+', type=int,
                        default=DEFAULT_N_LEVELS,
                        help='Concurrency levels (default: 5 10 20)')
    parser.add_argument('--reps', type=int, default=DEFAULT_REPS,
                        help='Number of repetitions (default: 1)')
    parser.add_argument('--speedup', type=int, default=120,
                        help='Speedup factor (default: 120)')
    parser.add_argument('--max-t-sim', type=int, default=600,
                        help='Max simulation time in seconds (default: 600)')
    
    args = parser.parse_args()
    
    print("="*60)
    print("Concurrency Tests for S1-S5 Scenarios")
    print("="*60)
    print(f"Scenarios: {args.scenarios}")
    print(f"Concurrency levels (n): {args.n_levels}")
    print(f"Repetitions: {args.reps}")
    print(f"Speedup: {args.speedup}")
    print(f"Max sim time: {args.max_t_sim}s")
    print()
    
    all_success = True
    total_tests = 0
    passed_tests = 0
    
    for scenario in args.scenarios:
        if scenario not in SCENARIO_MAP:
            print(f"[WARNING] Unknown scenario: {scenario}, skipping")
            continue
            
        plan_csv = SCENARIO_MAP[scenario]
        if not Path(plan_csv).exists():
            print(f"[WARNING] Plan file not found: {plan_csv}, skipping")
            continue
        
        print(f"\n{'='*60}")
        print(f"Scenario: {scenario} ({plan_csv})")
        print(f"{'='*60}")
        
        for n in args.n_levels:
            total_tests += 1
            print(f"\n[n={n}]")
            success = run_concurrency_test(n, plan_csv, args.reps, 
                                            args.speedup, args.max_t_sim)
            if success:
                passed_tests += 1
            else:
                all_success = False
    
    print(f"\n{'='*60}")
    print(f"Summary: {passed_tests}/{total_tests} tests passed")
    if all_success:
        print("[SUCCESS] All concurrency tests completed!")
    else:
        print("[WARNING] Some tests failed. Check output above.")
    print(f"{'='*60}")
    
    return 0 if all_success else 1

if __name__ == '__main__':
    sys.exit(main())
