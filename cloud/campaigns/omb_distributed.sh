#!/usr/bin/env bash
# E-X2: run the OpenMessaging Benchmark under the conditions that actually produce the failure.
#
# The first OMB run (omb_discard_count.sh) discarded zero samples, and the paper reports that
# null. But it ran in the easiest possible configuration: one host, one JVM, no competing load.
# E-A5 has since shown that the inversion rate is governed by whether the stamping thread is
# running -- at an idle machine our own rate is 0.4%, and under load it reaches 30%. Testing a
# harness for this failure on an idle single host is close to testing it under conditions chosen
# to hide it, which is why the limitations section named this run as the obvious next step.
#
# Two channels can drive an end-to-end sample negative, and the first run exercised neither:
#
#   OCCUPANCY  the thread that reads the clock is preempted between the event and the read.
#              Needs competing CPU load. E-A5 establishes this is the dominant channel for us.
#   CLOCK      the producer stamps on host A, the consumer reads on host B, and the two clocks
#              disagree. Needs the workers on different machines. OMB's own default,
#              CreateTime, makes the publish timestamp the producer's.
#
# This campaign turns both on: an OMB worker on the driver and another on sbl-client over the
# private network, with background load on both, against the same broker. Everything else is
# unchanged from the first run, including the single added counter in WorkerStats.java.
#
# PRE-REGISTERED, as before, because the interesting outcome must not be chosen afterwards:
#   count > 0  -- the failure occurs in a harness we did not write, on real hardware, and is
#                 invisible in that harness's own output. This is the strongest form of the M1
#                 evidence and it closes the referee's decisive objection.
#   count == 0 -- a second null, now under conditions we have shown are hard rather than easy.
#                 That materially strengthens the negative and we would report it as such: the
#                 design flaw is real and demonstrated at source, but we could not make it bite.
#
# WHAT THIS DOES NOT CONTROL. sbl-client has 2 cores and under 1 GB of RAM, so its worker runs
# with a small heap and the offered rate is kept modest. The load we add to the client competes
# with the OMB worker on a small machine, which is the point, but it also means this is not a
# throughput measurement and must not be read as one. We report discards, nothing else.
#
# Usage:  nohup bash cloud/campaigns/omb_distributed.sh > omb_distributed.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

OMB="${OMB:-$HOME/omb}"
OUT="${OUT:-docs/results/external}"
DURATION_MIN="${DURATION_MIN:-5}"
CLIENT="${CLIENT_PRIV:-10.0.1.122}"
WORKER_PORT="${WORKER_PORT:-8080}"
STATS_PORT="${STATS_PORT:-8081}"
LOAD_PCT="${LOAD_PCT:-88}"     # the level at which E-A5 measured a 30% inversion rate for us
mkdir -p "$OUT"

[ -d "$OMB" ] || { echo "FATAL: no OMB checkout at $OMB"; exit 1; }
JH=$(ls -d /usr/lib/jvm/java-17-openjdk-* 2>/dev/null | head -1)
[ -n "$JH" ] || { echo "FATAL: no JDK 17 on the driver"; exit 1; }
export JAVA_HOME="$JH"; export PATH="$JH/bin:$PATH"

JAR=$(find "$OMB" -name "benchmark-framework-*.jar" -not -name "*sources*" | head -1)
[ -n "$JAR" ] || { echo "FATAL: OMB not built; run omb_discard_count.sh first"; exit 1; }
grep -q "sblNonPositiveLatency" \
  "$OMB/benchmark-framework/src/main/java/io/openmessaging/benchmark/worker/WorkerStats.java" \
  || { echo "FATAL: the discard counter is not in the source; refusing to run"; exit 1; }

remote_client () {
  ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 "ubuntu@$CLIENT" "$@"
}

banner "checking sbl-client"
remote_client "hostname && nproc" || { echo "FATAL: cannot reach client at $CLIENT"; exit 1; }

banner "provisioning JDK 17 on the client (headless, no desktop pulls)"
remote_client "command -v java >/dev/null && java -version 2>&1 | head -1" \
  || remote_client "sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update && \
                    sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y openjdk-17-jre-headless" \
  || { echo "FATAL: JDK install on client failed"; exit 1; }
remote_client "java -version 2>&1 | head -1" || { echo "FATAL: no java on client"; exit 1; }

banner "shipping the built OMB tree to the client"
remote_client "mkdir -p ~/omb" >/dev/null 2>&1
rsync -az --delete -e "ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
  "$OMB/" "ubuntu@$CLIENT:~/omb/" 2>&1 | tail -2 \
  || { echo "FATAL: rsync of OMB to client failed"; exit 1; }

cleanup () {
  echo "cleaning up workers and load"
  pkill -f "benchmark-worker" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  remote_client "pkill -f benchmark-worker; pkill -9 -x stress-ng" >/dev/null 2>&1
  sleep 2
}
trap cleanup EXIT

cleanup

banner "starting background load on BOTH hosts (${LOAD_PCT}% duty, all cores)"
stress-ng --cpu "$(nproc)" --cpu-load "$LOAD_PCT" --timeout $(( DURATION_MIN * 60 + 600 ))s \
  >/dev/null 2>&1 &
remote_client "nohup stress-ng --cpu 2 --cpu-load $LOAD_PCT \
  --timeout $(( DURATION_MIN * 60 + 600 ))s >/dev/null 2>&1 &" >/dev/null 2>&1
sleep 5

banner "starting OMB workers: driver and $CLIENT"
( cd "$OMB" && nohup bin/benchmark-worker -p "$WORKER_PORT" -sp "$STATS_PORT" \
    > "$PWD/../sbl/$OUT/omb_worker_driver.log" 2>&1 & )
remote_client "cd ~/omb && JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
  HEAP_OPTS='-Xms256m -Xmx384m' nohup bin/benchmark-worker -p $WORKER_PORT -sp $STATS_PORT \
  > ~/omb_worker_client.log 2>&1 &" >/dev/null 2>&1
sleep 25

DRV_PRIV=$(ip -4 addr show | grep -oE 'inet 10\.[0-9.]+' | head -1 | awk '{print $2}')
echo "driver private ip: $DRV_PRIV"
for w in "$DRV_PRIV:$WORKER_PORT" "$CLIENT:$WORKER_PORT"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://$w/counters-stats" 2>/dev/null)
  echo "  worker $w -> HTTP ${code:-none}"
done

cat > "$OUT/omb_driver_dist.yaml" <<EOF
name: Kafka
driverClass: io.openmessaging.benchmark.driver.kafka.KafkaBenchmarkDriver
replicationFactor: 1
topicConfig: |
  min.insync.replicas=1
commonConfig: |
  bootstrap.servers=${KAFKA_BOOTSTRAP}
producerConfig: |
  acks=all
  linger.ms=0
consumerConfig: |
  auto.offset.reset=earliest
  enable.auto.commit=false
EOF

# One producer and one consumer, forced onto separate workers by OMB's round-robin assignment,
# so the publish stamp and the receive stamp are taken on different machines.
cat > "$OUT/omb_workload_dist.yaml" <<EOF
name: sbl-audit-distributed
topics: 1
partitionsPerTopic: 1
messageSize: 200
subscriptionsPerTopic: 1
consumerPerSubscription: 1
producersPerTopic: 1
producerRate: 500
consumerBacklogSizeGB: 0
testDurationMinutes: ${DURATION_MIN}
EOF

banner "running distributed OMB for ${DURATION_MIN} min under ${LOAD_PCT}% load on both hosts"
( cd "$OMB" && timeout $(( DURATION_MIN * 60 + 420 )) \
    bin/benchmark --drivers "$PWD/../sbl/$OUT/omb_driver_dist.yaml" \
      --workers "http://$DRV_PRIV:$WORKER_PORT,http://$CLIENT:$WORKER_PORT" \
      "$PWD/../sbl/$OUT/omb_workload_dist.yaml" 2>&1 ) \
  | tee "$OUT/omb_dist_stdout.log" | tail -20

banner "collecting discards from both workers"
remote_client "cat ~/omb_worker_client.log" > "$OUT/omb_worker_client.log" 2>/dev/null
D_DRV=$(grep -o "SBL_DISCARDED_NONPOSITIVE total=[0-9]*" "$OUT/omb_worker_driver.log" 2>/dev/null \
        | tail -1 | grep -o "[0-9]*$")
D_CLI=$(grep -o "SBL_DISCARDED_NONPOSITIVE total=[0-9]*" "$OUT/omb_worker_client.log" 2>/dev/null \
        | tail -1 | grep -o "[0-9]*$")
D_RUN=$(grep -o "SBL_DISCARDED_NONPOSITIVE total=[0-9]*" "$OUT/omb_dist_stdout.log" 2>/dev/null \
        | tail -1 | grep -o "[0-9]*$")
D_DRV=${D_DRV:-0}; D_CLI=${D_CLI:-0}; D_RUN=${D_RUN:-0}
TOTAL=$(( D_DRV > D_CLI ? D_DRV : D_CLI )); [ "$D_RUN" -gt "$TOTAL" ] && TOTAL=$D_RUN

printf 'harness,mode,discarded_nonpositive,driver_worker,client_worker,duration_min,load_pct,bootstrap\n%s,%s,%s,%s,%s,%s,%s,%s\n' \
  "OpenMessaging Benchmark" "distributed+loaded" "$TOTAL" "$D_DRV" "$D_CLI" \
  "$DURATION_MIN" "$LOAD_PCT" "$KAFKA_BOOTSTRAP" > "$OUT/omb_discards_distributed.csv"
echo "DISCARDED NON-POSITIVE SAMPLES: $TOTAL  (driver $D_DRV, client $D_CLI)"
cat "$OUT/omb_discards_distributed.csv"

banner "OMB_DISTRIBUTED_COMPLETE"
