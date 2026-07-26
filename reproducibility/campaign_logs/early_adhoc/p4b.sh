#!/usr/bin/env bash
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
stats () { ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B   'DEV=$(ip route show default | awk "{print \}" | head -1); tc -s qdisc show dev $DEV | head -3'; }
arm () {  # tag  extra
  TAG=$1; EXTRA=$2
  ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh 20" >/dev/null 2>&1
  echo "=== arm $TAG $(date +%H:%M:%S) ==="
  ARGS=()
  [ -n "$EXTRA" ] && ARGS=(--redis-consumer-extra "$EXTRA")
  timeout 2400 python3 scripts/run_concurrency_test.py 5 "$PLAN" 3     --speedup 10 --max-t-sim 600     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     "${ARGS[@]}" --trial-timeout 1800 2>&1 | tail -2
  echo "--- netem stats after $TAG:"; stats
}
arm unbatched ""
arm batched "--ack-batch 200"
ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh 0" >/dev/null 2>&1
echo "P4B_DONE $(date +%H:%M:%S)"
