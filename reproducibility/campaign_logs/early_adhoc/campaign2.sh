#!/usr/bin/env bash
# Campaign 2: RQ5 on a REAL inter-VM network. Delay is injected at the broker NIC, so the
# path carries genuine jitter and queueing rather than tc netem looped back on one host.
cd ~/sbl
B=10.0.1.221
PLAN=$(find data -name replay_plan.csv | head -1)
PLANS=$(dirname $(dirname $PLAN))
run_phase () {   # delay_ms  consumer_extra  tag
  D=$1; EXTRA=$2; TAG=$3
  ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh $D" >/dev/null 2>&1
  echo "=== phase $TAG delay=${D}ms $(date +%H:%M:%S) ==="
  ARGS=""
  [ -n "$EXTRA" ] && ARGS="--redis-consumer-extra $EXTRA"
  python3 scripts/run_concurrency_test.py 5 "$PLAN" 3     --speedup 10 --max-t-sim 600     --kafka-bootstrap $B:19092 --redis-host $B --redis-port 6379     --plans-dir "$PLANS" --kafka-producer-extra "--max-inflight 64"     --trial-timeout 1800 $ARGS 2>&1 | tail -4
  echo "$TAG $(ls -d runs/concurrency_n5_* | tail -1)" >> ~/phase_map.txt
}
: > ~/phase_map.txt
for d in 0 5 20 50; do run_phase $d "" "d${d}"; done
# P4 intervention: batch the acknowledgements at the delays where Redis collapsed
for d in 20 50; do run_phase $d "--ack-batch 200" "p4_d${d}"; done
ssh -i ~/.ssh/oci_sbl -o BatchMode=yes ubuntu@$B "~/netem.sh 0" >/dev/null 2>&1
echo "CAMPAIGN2_COMPLETE $(date +%H:%M:%S)"
