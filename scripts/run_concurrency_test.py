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
import glob
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


def resolve_plans(plans_dir: str, default_plan: str) -> List[str]:
    """Per-match replay plans for a 'distinct matches' sweep.

    Without --plans-dir every feed replays the same plan, which makes N concurrent feeds N
    copies of one match. Pointing at a directory of per-match plans instead lets each feed
    carry a *different* real match, which is what a live multi-match feed actually looks like.
    Returns [] when no per-match plans are found, so the caller falls back to default_plan.
    """
    if not plans_dir:
        return []
    found = sorted(glob.glob(os.path.join(plans_dir, "**", "replay_plan.csv"), recursive=True))
    if not found:
        found = sorted(glob.glob(os.path.join(plans_dir, "*.csv")))
    return found


def plan_for_feed(plans: List[str], feed: int, default_plan: str) -> str:
    """Plan for feed number `feed` (1-based); wraps if fewer plans than feeds."""
    if not plans:
        return default_plan
    return plans[(feed - 1) % len(plans)]


def trial_command(backend: str, run_id: str, plan_csv: str, speedup: float, max_t_sim: int,
                  platform_name: str = None):
    """Interpreter + script invocation for one trial, chosen by platform.

    Returns a subprocess argv whose LAST element is the command string that callers append
    backend flags to. Windows uses the .ps1 runners, POSIX the .sh runners; both accept the
    same -FLAG names so everything downstream is platform-independent.
    """
    platform_name = platform_name if platform_name is not None else os.name
    if platform_name == 'nt':
        return ['powershell', '-ExecutionPolicy', 'Bypass', '-NoProfile', '-Command',
                f'cd "{os.getcwd()}"; .\\scripts\\run_{backend}_trial.ps1 '
                f'{run_id} "{plan_csv}" {speedup} {max_t_sim}']
    return ['bash', f'scripts/run_{backend}_trial.sh',
            run_id, plan_csv, str(speedup), str(max_t_sim)]


def _append(cmd, text):
    """Append a fragment to the command, handling both invocation styles.

    PowerShell gets one long -Command string; bash gets discrete argv entries. Keeping this
    in one place is what lets run_trial build flags without caring which platform it is on.
    """
    if cmd[0] == 'powershell':
        cmd[-1] += text
    else:
        # shlex, not split(): values like -PRODUCER_EXTRA "--acks all" must stay one argv entry.
        cmd.extend(shlex.split(text))
    return cmd


def run_trial(run_id: str, plan_csv: str, backend: str, speedup: float, max_t_sim: int,
              bootstrap: str = "localhost:9092", redis_host: str = "localhost",
              redis_port: int = 6379, topic: str = None, stream: str = None,
              broker_count: int = 1, cluster_mode: bool = False,
              producer_extra: str = "", trial_timeout: int = 300,
              consumer_extra: str = "", redis_cluster_nodes: str = "") -> Tuple[str, bool, str]:
    """
    Run a single trial (producer + consumer) for a specific backend.
    Returns (run_id, success, error_message)
    """
    if backend not in ('kafka', 'redis'):
        return run_id, False, f"Unknown backend: {backend}"

    # The trial runners exist in two forms with identical flag names: PowerShell for the
    # Windows rig and bash for the Linux cloud hosts. Only the interpreter differs, so the
    # flag-appending code below is shared.
    cmd = trial_command(backend, run_id, plan_csv, speedup, max_t_sim)

    if backend == 'kafka':
        if topic:
            _append(cmd, f' -TOPIC "{topic}"')
        _append(cmd, f' -BOOTSTRAP {bootstrap}')
        _append(cmd, f' -BROKER_COUNT {broker_count}')
        if producer_extra:
            _append(cmd, f' -PRODUCER_EXTRA "{producer_extra}"')
    else:  # redis
        _append(cmd, f' -RedisHost {redis_host} -PORT {redis_port}')
        if stream:
            _append(cmd, f' -STREAM "{stream}"')
        if cluster_mode:
            _append(cmd, ' -CLUSTER_MODE')
        if redis_cluster_nodes:
            _append(cmd, f' -CLUSTER_NODES "{redis_cluster_nodes}"')
        _append(cmd, f' -NODE_COUNT {broker_count}')
        if consumer_extra:
            _append(cmd, f' -CONSUMER_EXTRA "{consumer_extra}"')
    
    # Run the command
    try:
        start_time = time.time()
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=trial_timeout
        )
        elapsed = time.time() - start_time
        
        if result.returncode != 0:
            error_msg = f"Failed with exit code {result.returncode}: {result.stderr[-500:]}"
            return run_id, False, error_msg
        
        return run_id, True, f"Completed in {elapsed:.1f}s"
    except subprocess.TimeoutExpired:
        return run_id, False, f"Trial timed out after {trial_timeout}s"
    except Exception as e:
        return run_id, False, str(e)


def main():
    parser = argparse.ArgumentParser(
        description='Run concurrent Kafka vs Redis streaming benchmarks'
    )
    parser.add_argument('concurrency', type=int,
                        help='Number of concurrent feeds. Unrestricted: the high-connection '
                             'sweep needs N in the hundreds to test per-client overhead, which '
                             'a fixed choice list would have silently forbidden.')
    parser.add_argument('plan_csv', type=str,
                        help='Path to the replay plan CSV file')
    parser.add_argument('reps', type=int, default=1,
                        help='Number of repetitions per concurrency level')
    parser.add_argument('--speedup', type=float, default=120,
                        help='Speedup factor applied on top of any factor already baked into the '
                             'plan (float, so e.g. 1/120 = 0.00833 replays a 120x plan in true '
                             'real time).')
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
    parser.add_argument('--redis-cluster-nodes', type=str, default='',
                        help='host:port list for a genuinely distributed Redis Cluster; '
                             'without it the legacy single-host 7000/7001/7002 layout is used.')
    parser.add_argument('--kafka-producer-extra', type=str, default='',
                        help='Extra args appended to the Kafka producer (e.g. "--max-inflight 64") '
                             'so its load generator is pipelined comparably to the Redis worker pool.')
    parser.add_argument('--out-dir', type=str,
                        default=os.environ.get('SBL_OUT_DIR', 'docs/results'),
                        help='Directory for the run summary; configurable so tests do not write into the repo.')
    parser.add_argument('--trial-timeout', type=int, default=300,
                        help='Per-trial subprocess timeout in seconds. Raise it for true '
                             'real-time replays, where wall time equals the replayed window.')
    parser.add_argument('--redis-consumer-extra', type=str, default='',
                        help='Extra args appended to the Redis consumer (e.g. "--ack-batch 200") '
                             'to test whether batching acknowledgements removes the RTT bound.')
    parser.add_argument('--plans-dir', type=str, default='',
                        help='Directory of per-match replay plans (searched for **/replay_plan.csv). '
                             'When set, each feed replays a DIFFERENT match instead of N copies of '
                             'the same plan, so concurrency means concurrent *matches*.')

    args = parser.parse_args()

    plans = resolve_plans(args.plans_dir, args.plan_csv)
    if args.plans_dir and not plans:
        print(f"[WARNING] no per-match plans under {args.plans_dir}; falling back to {args.plan_csv}")
    elif plans:
        print(f"Distinct-match mode: {len(plans)} per-match plans "
              f"({'wrapping, ' if args.concurrency > len(plans) else ''}"
              f"{min(args.concurrency, len(plans))} distinct per rep)")
    
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
                # In distinct-match mode each feed carries a different real match.
                feed_plan = plan_for_feed(plans, feed, args.plan_csv)
                # Kafka trial
                kafka_run_id = f"{prefix}_kafka_feed{feed}_rep{rep}"
                kafka_topic = f"sb-events-n{args.concurrency}-feed{feed}-rep{rep}"
                futures.append(executor.submit(
                    run_trial,
                    kafka_run_id,
                    feed_plan,
                    'kafka',
                    args.speedup,
                    args.max_t_sim,
                    args.kafka_bootstrap,
                    args.redis_host,
                    args.redis_port,
                    topic=kafka_topic,
                    broker_count=args.broker_count,
                    cluster_mode=args.cluster_mode,
                    producer_extra=args.kafka_producer_extra,
                    trial_timeout=args.trial_timeout
                ))
                
                # Redis trial
                redis_run_id = f"{prefix}_redis_feed{feed}_rep{rep}"
                redis_stream = f"sb:events:n{args.concurrency}:feed{feed}:rep{rep}"
                futures.append(executor.submit(
                    run_trial,
                    redis_run_id,
                    feed_plan,
                    'redis',
                    args.speedup,
                    args.max_t_sim,
                    args.kafka_bootstrap,
                    args.redis_host,
                    args.redis_port,
                    stream=redis_stream,
                    broker_count=args.broker_count,
                    cluster_mode=args.cluster_mode,
                    trial_timeout=args.trial_timeout,
                    consumer_extra=args.redis_consumer_extra,
                        redis_cluster_nodes=args.redis_cluster_nodes
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
        'plans_dir': args.plans_dir,
        'distinct_match_plans': plans,
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
        'cluster_mode': args.cluster_mode,
        'trial_timeout': args.trial_timeout
    }
    
    output_dir = Path(args.out_dir) / f"concurrency_{prefix}"
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
