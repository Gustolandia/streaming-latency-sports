#!/usr/bin/env bash
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
# Manipulation check FIRST: prove the treatment string reaches the consumer's parser.
# A silently-dropped treatment yields a null indistinguishable from a real refutation.
if python3 scripts/redis_consumer.py --run-id x --out /tmp/x.csv --ack-batch 200 --definitely-bad 2>&1 | grep -q "unrecognized arguments: --definitely-bad"; then
  echo "MANIPULATION_CHECK_OK: --ack-batch accepted, bad flag rejected"
else
  echo "MANIPULATION_CHECK_FAILED"; exit 1
fi
for d in 20 50; do
  ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh $d" >/dev/null 2>&1
  echo "=== p4 delay=${d}ms $(date +%H:%M:%S) ==="
  timeout 2400 python3 scripts/run_concurrency_test.py 5 "$PLAN" 3     --speedup 10 --max-t-sim 600     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --redis-consumer-extra "--ack-batch 200"     --trial-timeout 1800 2>&1 | tail -3
done
ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh 0" >/dev/null 2>&1
echo "P4_DONE $(date +%H:%M:%S)"
