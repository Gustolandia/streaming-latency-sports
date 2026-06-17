#!/usr/bin/env python3
"""
run_concurrency_test.py
Orchestrates N concurrent feeds for Kafka vs Redis comparison using Python subprocess.
Faster and more reliable than PowerShell Start-Job for concurrent execution.

Usage:
    python run_concurrency_test.py <N> <plan_csv> <reps> [speedup] [max_t_sim] [kafka_bootstrap] [redis_host] [redis_port]
    
    python run_concurrency_test.py 5 data/processed/replay_plans/s2sf12/combined_plan.csv 1 120 600 localhost:9092 localhost 6379
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


def run_trial(run_id: str, plan_csv: str, backend: str, speedup: int, max_t_sim: int, 
              bootstrap: str = "localhost:9092", redis_host: str = "localhost", 
              redis_port: int = 6379, topic: str = None, stream: str = None,
              broker_count: int = 1, cluster_mode: bool = False) -> Tuple[str, bool, str]:
    """
    Run a single trial (producer + consumer) for a specific backend.
    Returns (run_id, success, error_message)
    """
    script_map = {
        'kafka': 'run_kafka_trial.ps1',
        'redis': 'run_redis_trial.ps1'
    }
    
    script = script_map.get(backend)
    if not script:
        return run_id, False, f"Unknown backend: {backend}"
    
    # Build command
    cmd = [
        'powershell', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command',
        f'cd "{os.getcwd()}"; .\\scripts\\{script} {run_id} "{plan_csv}" {speedup} {max_t_sim}'
    ]
    
    if backend == 'kafka':
        if topic:
            cmd[-1] += f' -TOPIC "{topic}"'
        else:
            cmd[-1] += f' -BOOTSTRAP {bootstrap}'
        cmd[-1] += f' --broker-count {broker_count}'
    else:  # redis
        cmd[-1] += f' -RedisHost {redis_host} -PORT {redis_port}'
        if stream:
            cmd[-1] += f' -STREAM "{stream}"'
        if cluster_mode:
            cmd[-1] += ' --cluster-mode'
        cmd[-1] += f' --node-count {broker_count}'
    
    # Run the command
    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes per trial
        )
        elapsed = time.time() - start_time
        
        if result.returncode != 0:
            error_msg = f"Failed with exit code {result.returncode}: {result.stderr[-500:]}"
            return run_id, False, error_msg
        
        return run_id, True, f"Completed in {elapsed:.1f}s"
    except subprocess.TimeoutExpired:
        return run_id, False, "Trial timed out after 5 minutes"
    except Exception as e:
        return run_id, False, str(e)


def main():
    parser = argparse.ArgumentParser(
        description='Run concurrent Kafka vs Redis streaming benchmarks'
    )
    parser.add_argument('concurrency', type=int, choices=[1, 5, 10, 20],
                        help='Number of concurrent feeds (1, 5, 10, 20)')
    parser.add_argument('plan_csv', type=str,
                        help='Path to the replay plan CSV file')
    parser.add_argument('reps', type=int, default=1,
                        help='Number of repetitions per concurrency level')
    parser.add_argument('--speedup', type=int, default=120,
                        help='Speedup factor (default: 120)')
    parser.add_argument('--max-t-sim', type=int, default=600,
                        help='Max simulation time in seconds (default: 600)')
    parser.add_argument('--kafka-bootstrap', type=str, default='localhost:9092',
                        help='Kafka bootstrap servers (default: localhost:9092)')
    parser.add_argument('--redis-host', type=str, default='localhost',
                        help='Redis host (default: localhost)')
    parser.add_argument('--redis-port', type=int, default=6379,
                        help='Redis port (default: 6379)')
    parser.add_argument('--broker-count', type=int, default=1, choices=[1, 3],
                        help='Number of brokers/nodes (1 or 3)')
    parser.add_argument('--cluster-mode', action='store_true',
                        help='Use cluster configuration')
    
    args = parser.parse_args()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"concurrency_n{args.concurrency}_{timestamp}"
    
    print(f"Starting concurrency test: N={args.concurrency}, Reps={args.reps}")
    print(f"Prefix: {prefix}")
    print(f"Plan: {args.plan_csv}")
    
    # Create output tracking
    run_list = []
    results = []
    
    for rep in range(1, args.reps + 1):
        print(f"\n=== Rep {rep}/{args.reps} ===")
        
        # For this rep, run all N feeds concurrently
        with ThreadPoolExecutor(max_workers=args.concurrency * 2) as executor:
            futures = []
            
            for feed in range(1, args.concurrency + 1):
                # Kafka trial
                kafka_run_id = f"{prefix}_kafka_feed{feed}_rep{rep}"
                kafka_topic = f"sb-events-n{args.concurrency}-feed{feed}-rep{rep}"
                futures.append(executor.submit(
                    run_trial,
                    kafka_run_id,
                    args.plan_csv,
                    'kafka',
                    args.speedup,
                    args.max_t_sim,
                    args.kafka_bootstrap,
                    args.redis_host,
                    args.redis_port,
                    topic=kafka_topic,
                    broker_count=args.broker_count,
                    cluster_mode=args.cluster_mode
                ))
                
                # Redis trial
                redis_run_id = f"{prefix}_redis_feed{feed}_rep{rep}"
                redis_stream = f"sb:events:n{args.concurrency}:feed{feed}:rep{rep}"
                futures.append(executor.submit(
                    run_trial,
                    redis_run_id,
                    args.plan_csv,
                    'redis',
                    args.speedup,
                    args.max_t_sim,
                    args.kafka_bootstrap,
                    args.redis_host,
                    args.redis_port,
                    stream=redis_stream,
                    broker_count=args.broker_count,
                    cluster_mode=args.cluster_mode
                ))
            
            # Wait for all to complete
            for future in as_completed(futures):
                run_id, success, message = future.result()
                status = "[OK]" if success else "[FAIL]"
                print(f"  {status} {run_id}: {message}")
                run_list.append(f"runs/{run_id}")
                results.append({
                    'run_id': run_id,
                    'success': success,
                    'message': message
                })
        
        print(f"  Rep {rep} completed")
    
    # Save run list
    run_list_file = f"runs/_concurrency_{prefix}_runs.txt"
    with open(run_list_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(run_list))
    
    # Save summary
    summary = {
        'concurrency': args.concurrency,
        'reps': args.reps,
        'plan_csv': args.plan_csv,
        'speedup': args.speedup,
        'max_t_sim': args.max_t_sim,
        'prefix': prefix,
        'timestamp': timestamp,
        'run_list_file': run_list_file,
        'total_runs': len(run_list),
        'success_count': sum(1 for r in results if r['success']),
        'failure_count': sum(1 for r in results if not r['success']),
        'kafka_bootstrap': args.kafka_bootstrap,
        'redis_host': args.redis_host,
        'redis_port': args.redis_port,
        'broker_count': args.broker_count,
        'cluster_mode': args.cluster_mode
    }
    
    output_dir = Path(f"docs/results/concurrency_{prefix}")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / f"{prefix}_summary.json", 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n=== Concurrency Test Complete ===")
    print(f"Prefix: {prefix}")
    print(f"Total runs: {len(run_list)}")
    print(f"Successful: {summary['success_count']}")
    print(f"Failed: {summary['failure_count']}")
    print(f"Run list: {run_list_file}")
    print(f"Summary: {output_dir / f'{prefix}_summary.json'}")
    
    if summary['failure_count'] > 0:
        print(f"\n[WARNING] {summary['failure_count']} runs failed. Check logs for details.")
        sys.exit(1)
    else:
        print("\n[SUCCESS] All runs completed successfully!")
        sys.exit(0)


if __name__ == '__main__':
    main()
