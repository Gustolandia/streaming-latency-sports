#!/usr/bin/env bash
# Campaign 3 (M2): vary CONNECTION COUNT at a realistic per-feed event rate.
# The paper extrapolated "thousands of simultaneous matches" from varying replay SPEED on ten
# feeds, which cannot capture per-client overhead - exactly what matters for a single-threaded
# server. Here N is the manipulated variable and the per-feed rate stays real-time.
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
for N in 10 25 50 100; do
  echo "=== connections N=$N $(date +%H:%M:%S) ==="
  python3 scripts/run_concurrency_test.py $N "$PLAN" 1     --speedup 0.008333 --max-t-sim 300     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --trial-timeout 1800 2>&1 | tail -4
done
echo "CAMPAIGN3_COMPLETE $(date +%H:%M:%S)"
