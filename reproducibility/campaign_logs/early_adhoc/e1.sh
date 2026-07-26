#!/usr/bin/env bash
# E1: realistic-concurrency benchmark at the N values DERIVED from real kick-off schedules
# (1, 9, 10, 12 - see docs/results/football/concurrency), each feed a distinct real match,
# replayed at TRUE REAL TIME. Real-time rate is not only ecologically right: the 10x runs
# starve the driver's CPU and produce inverted timestamps that fail clock_integrity.py.
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
for spec in "1 8" "9 3" "10 3" "12 3"; do
  set -- $spec; N=$1; REPS=$2
  echo "=== E1 N=$N reps=$REPS $(date +%H:%M:%S) ==="
  timeout 3000 python3 scripts/run_concurrency_test.py $N "$PLAN" $REPS     --speedup 0.008333 --max-t-sim 2     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --trial-timeout 1200 2>&1 | tail -3
done
echo "E1_COMPLETE $(date +%H:%M:%S)"
