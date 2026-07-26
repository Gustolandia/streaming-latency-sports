#!/usr/bin/env bash
cd ~/sbl
# Discard the contaminated cluster attempt: its Redis half never connected, so those
# runs are not a measurement of anything.
rm -rf runs/concurrency_n5_20260721_211142* runs/clsmoke
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))

for N in 10 25 50 100; do
  echo "=== connections N=$N $(date +%H:%M:%S) ==="
  python3 scripts/run_concurrency_test.py $N "$PLAN" 1     --speedup 0.008333 --max-t-sim 300     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --trial-timeout 2400 2>&1 | tail -4
done
echo "CAMPAIGN3_COMPLETE $(date +%H:%M:%S)"

echo "=== cluster N=5 $(date +%H:%M:%S) ==="
python3 scripts/run_concurrency_test.py 5 "$PLAN" 3   --speedup 10 --max-t-sim 600   --kafka-bootstrap $B:29092 --redis-host $B --redis-port 7000   --broker-count 3 --cluster-mode --redis-cluster-nodes '10.0.1.221:7000,10.0.1.242:7000,10.0.1.140:7000'   --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"   --trial-timeout 1800 2>&1 | tail -4
echo "CAMPAIGN4_COMPLETE $(date +%H:%M:%S)"
echo "ALL_RERUN_DONE $(date +%H:%M:%S)"
