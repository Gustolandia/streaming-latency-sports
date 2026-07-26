#!/usr/bin/env bash
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
# Connection sweep: per-feed rate held at true real time (speedup 1/120), duration bounded by
# max-t-sim so every level is directly comparable and N is the only manipulated variable.
for N in 10 50 100; do
  echo "=== connections N=$N $(date +%H:%M:%S) ==="
  timeout 2400 python3 scripts/run_concurrency_test.py $N "$PLAN" 1     --speedup 0.008333 --max-t-sim 3     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --trial-timeout 2000 2>&1 | tail -3
done
echo "CONNSWEEP_COMPLETE $(date +%H:%M:%S)"

echo "=== cluster N=5 $(date +%H:%M:%S) ==="
timeout 2400 python3 scripts/run_concurrency_test.py 5 "$PLAN" 3   --speedup 10 --max-t-sim 600   --kafka-bootstrap $B:29092 --redis-host $B --redis-port 7000   --broker-count 3 --cluster-mode --redis-cluster-nodes '10.0.1.221:7000,10.0.1.242:7000,10.0.1.140:7000'   --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"   --trial-timeout 1800 2>&1 | tail -3
echo "ALL_FINAL_DONE $(date +%H:%M:%S)"
