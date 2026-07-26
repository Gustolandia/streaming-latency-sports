#!/usr/bin/env bash
# Campaign 1: M1 re-test on clean Linux, cross-VM. Same fair protocol as the Windows
# corpus (10x replay, Kafka producer pipelined) so the only change is the platform.
cd ~/sbl
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
for spec in "1 18" "5 3" "10 3"; do
  set -- $spec; N=$1; REPS=$2
  echo "=== N=$N reps=$REPS $(date +%H:%M:%S) ==="
  python3 scripts/run_concurrency_test.py $N "$PLAN" $REPS     --speedup 10 --max-t-sim 600     --kafka-bootstrap 10.0.1.221:19092 --redis-host 10.0.1.221 --redis-port 6379     --plans-dir "$PLANS"     --kafka-producer-extra "--max-inflight 64"     --trial-timeout 900 2>&1 | tail -6
done
echo "CAMPAIGN1_COMPLETE $(date +%H:%M:%S)"
