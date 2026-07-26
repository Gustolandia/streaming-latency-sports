#!/usr/bin/env bash
# Campaign 4: the 3-node cluster arm, with each broker node on its OWN host.
# The paper specified this arm but never reported it, because co-locating six broker
# containers with the load generator saturated the single host. That confound is gone here.
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
echo "=== cluster N=5 $(date +%H:%M:%S) ==="
python3 scripts/run_concurrency_test.py 5 "$PLAN" 3   --speedup 10 --max-t-sim 600   --kafka-bootstrap $B:29092 --redis-host $B --redis-port 7000   --broker-count 3 --cluster-mode   --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"   --trial-timeout 1800 2>&1 | tail -5
echo "CAMPAIGN4_COMPLETE $(date +%H:%M:%S)"
