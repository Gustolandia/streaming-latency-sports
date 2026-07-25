#!/usr/bin/env bash
# E-X2: run the OpenMessaging Benchmark under the conditions that actually produce the failure.
#
# The first OMB run (omb_discard_count.sh) discarded zero, and the paper reports that null. But
# it ran in the easiest possible configuration: one host, one JVM, no competing load. E-A5 has
# since shown the inversion rate is governed by whether the stamping thread is running -- 0.4% at
# idle, 30% under load. Testing a harness for this failure on an idle single host is close to
# testing under conditions chosen to hide it.
#
# Two channels can drive an end-to-end sample negative, and the first run exercised neither:
#   OCCUPANCY  the thread reading the clock is preempted. Needs competing CPU load.
#   CLOCK      producer stamps on host A, consumer reads on host B, clocks disagree. Needs
#              workers on different machines. OMB's default CreateTime makes the publish stamp
#              the producer's.
# This campaign turns both on.
#
# ---------------------------------------------------------------------------------------------
# THE FIRST ATTEMPT PRODUCED A NUMBER THAT MEANT NOTHING, AND THIS VERSION EXISTS TO PREVENT IT.
#
# On 2026-07-25 this script shipped OMB's built jars to the client with rsync but NOT its Maven
# dependency tree, which bin/benchmark-worker puts on the classpath. The client worker died with
# NoClassDefFoundError, the coordinator aborted with "Connection refused", no latency was ever
# measured -- and the script then wrote discarded_nonpositive=0, because a harness that never ran
# discards nothing. That zero would have been read as a second null under hard conditions. It is
# precisely the failure this paper is about: a number that looks like a measurement and is an
# artefact of the instrument failing.
#
# Three defences, in order of importance:
#   1. VALIDATE THE OUTPUT BEFORE WRITING ANY RESULT. The benchmark must have produced real
#      latency output. If it did not, this script writes a row marked invalid and exits non-zero.
#      No run, no number.
#   2. VERIFY BOTH WORKERS ARE ALIVE FIRST. Poll each worker's HTTP endpoint and abort before
#      the benchmark rather than discovering it afterwards.
#   3. SHIP A SELF-CONTAINED DISTRIBUTION. The packaged tarball carries its own dependencies, so
#      the classpath cannot be half-present.
# ---------------------------------------------------------------------------------------------
#
# PRE-REGISTERED, unchanged:
#   count > 0  -- the failure occurs in a harness we did not write, on real hardware, invisibly.
#   count == 0 -- a second null, now under conditions we have shown are hard rather than easy.
#                 That strengthens the negative and would be reported as such.
#   no valid run -- reported as no result. Not as a zero.
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
LOAD_PCT="${LOAD_PCT:-88}"
mkdir -p "$OUT"

WS="$OMB/benchmark-framework/src/main/java/io/openmessaging/benchmark/worker/WorkerStats.java"
[ -d "$OMB" ] || { echo "FATAL: no OMB checkout at $OMB"; exit 1; }
grep -q "sblNonPositiveLatency" "$WS" || { echo "FATAL: discard counter not in source"; exit 1; }
JH=$(ls -d /usr/lib/jvm/java-17-openjdk-* 2>/dev/null | head -1)
[ -n "$JH" ] || { echo "FATAL: no JDK 17 on the driver"; exit 1; }
export JAVA_HOME="$JH"; export PATH="$JH/bin:$PATH"
MVN="${MVN:-$(command -v /usr/local/bin/mvn || command -v mvn)}"

# Every remote call is bounded in time and gets -n. On 2026-07-25 the worker-start ssh hung for
# 33 minutes: both workers had in fact come up (Javalin logged "has started" on each), but the
# ssh that launched the client one never returned, so the campaign never reached its polling
# stage. Meanwhile the background load timed out, so even an unblocked run would have measured
# an UNLOADED machine -- the one condition this campaign exists to avoid. A hang is a different
# failure from a bad result, and the output-validation guard does not cover it.
#
# -n detaches stdin. The timeout means no single remote call can stall the campaign again.
remote_client () {
  timeout 120 ssh -n -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      "ubuntu@$CLIENT" "$@"
}

# Launching a long-lived remote process is the case that hung, so it gets -f as well: ssh
# backgrounds itself after authenticating and returns immediately, instead of waiting for a
# channel the detached JVM may keep open.
remote_client_detached () {
  timeout 60 ssh -n -f -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 "ubuntu@$CLIENT" "$@"
}

write_invalid () {   # $1 = why
  printf 'harness,mode,valid,discarded_nonpositive,reason,duration_min,load_pct\n%s,%s,0,,%s,%s,%s\n' \
    "OpenMessaging Benchmark" "distributed+loaded" "\"$1\"" "$DURATION_MIN" "$LOAD_PCT" \
    > "$OUT/omb_distributed_result.csv"
  echo "NO VALID RUN: $1"
  echo "wrote $OUT/omb_distributed_result.csv marked invalid; no count is reported"
}

cleanup () {
  pkill -f "io.openmessaging.benchmark.worker.BenchmarkWorker" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  remote_client "pkill -f io.openmessaging.benchmark.worker.BenchmarkWorker; pkill -9 -x stress-ng" \
    >/dev/null 2>&1
  sleep 2
}
trap cleanup EXIT
cleanup

banner "rebuilding the packaged distribution so the patch is definitely in it"
( cd "$OMB" && "$MVN" -q -B -DskipTests package 2>&1 | tail -5 )
TARBALL=$(ls -t "$OMB"/package/target/*-bin.tar.gz 2>/dev/null | head -1)
[ -n "$TARBALL" ] || { write_invalid "packaged tarball not produced"; exit 1; }
echo "tarball: $TARBALL ($(du -h "$TARBALL" | cut -f1))"

banner "provisioning the client"
remote_client "command -v java >/dev/null" \
  || remote_client "sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update && \
       sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y openjdk-17-jre-headless" \
  || { write_invalid "JDK install on client failed"; exit 1; }
remote_client "java -version 2>&1 | head -1" || { write_invalid "no java on client"; exit 1; }

# A self-contained distribution: its lib/ carries every dependency, so the classpath cannot be
# half-present the way the rsync of a build tree left it.
scp -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
    "$TARBALL" "ubuntu@$CLIENT:/tmp/omb-bin.tar.gz" >/dev/null 2>&1 \
  || { write_invalid "could not copy the distribution to the client"; exit 1; }
remote_client "rm -rf ~/ombdist && mkdir -p ~/ombdist && \
               tar xzf /tmp/omb-bin.tar.gz -C ~/ombdist --strip-components=1 && \
               ls ~/ombdist/lib | wc -l" \
  || { write_invalid "could not unpack the distribution on the client"; exit 1; }

banner "background load on both hosts (${LOAD_PCT}% duty)"
stress-ng --cpu "$(nproc)" --cpu-load "$LOAD_PCT" \
  --timeout $(( DURATION_MIN * 60 + 600 ))s >/dev/null 2>&1 &
remote_client_detached "nohup stress-ng --cpu 2 --cpu-load $LOAD_PCT \
  --timeout $(( DURATION_MIN * 60 + 600 ))s >/dev/null 2>&1 & echo started" >/dev/null 2>&1
sleep 5

DRV_PRIV=$(ip -4 addr show | grep -oE 'inet 10\.[0-9.]+' | head -1 | awk '{print $2}')
banner "starting workers: driver $DRV_PRIV and client $CLIENT"
( cd "$OMB" && setsid nohup bin/benchmark-worker -p "$WORKER_PORT" -sp "$STATS_PORT" \
    > "$PWD/../sbl/$OUT/omb_worker_driver.log" 2>&1 < /dev/null & )
remote_client_detached "cd ~/ombdist && HEAP_OPTS='-Xms192m -Xmx320m' setsid nohup \
  bin/benchmark-worker -p $WORKER_PORT -sp $STATS_PORT > ~/omb_worker_client.log 2>&1 < /dev/null &" \
  >/dev/null 2>&1

# DEFENCE 2: neither worker may be assumed up. Poll until both answer or give up loudly.
banner "waiting for both workers to answer"
UP_DRV=0; UP_CLI=0
for i in $(seq 1 30); do
  sleep 5
  [ "$UP_DRV" = 1 ] || curl -sf --max-time 4 "http://$DRV_PRIV:$WORKER_PORT/counters-stats" \
      >/dev/null 2>&1 && UP_DRV=1
  [ "$UP_CLI" = 1 ] || curl -sf --max-time 4 "http://$CLIENT:$WORKER_PORT/counters-stats" \
      >/dev/null 2>&1 && UP_CLI=1
  [ "$UP_DRV" = 1 ] && [ "$UP_CLI" = 1 ] && break
done
echo "  driver worker up: $UP_DRV   client worker up: $UP_CLI"
if [ "$UP_DRV" != 1 ] || [ "$UP_CLI" != 1 ]; then
  echo "--- client worker log ---"; remote_client "tail -15 ~/omb_worker_client.log" 2>/dev/null
  write_invalid "a worker never came up (driver=$UP_DRV client=$UP_CLI); benchmark not attempted"
  exit 1
fi

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

# OMB's distributed mode reads the payload from a FILE; messageSize alone is only honoured by
# the embedded single-worker path. Attempt 4 died with a NullPointerException inside
# FilePayloadReader.load because payloadFile was unset -- the benchmark ran for fifteen seconds
# and produced no latency at all. The validation guard caught it and wrote valid=0 rather than a
# zero discard count, which is the behaviour that matters, but the run was still lost.
PAYLOAD="$PWD/$OUT/omb_payload_200b.data"
python3 -c "open('$PAYLOAD','wb').write(b'x' * 200)"
[ -s "$PAYLOAD" ] || { write_invalid "could not create the payload file"; exit 1; }
echo "payload file: $PAYLOAD ($(stat -c %s "$PAYLOAD") bytes)"

cat > "$OUT/omb_workload_dist.yaml" <<EOF
name: sbl-audit-distributed
topics: 1
partitionsPerTopic: 1
messageSize: 200
payloadFile: "${PAYLOAD}"
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

# DEFENCE 1: no valid run, no number. A benchmark that aborted discards nothing, and that zero
# would be indistinguishable from a real negative in the CSV.
banner "validating that the benchmark actually ran"
PUB=$(grep -c "Pub rate" "$OUT/omb_dist_stdout.log" 2>/dev/null)
AGG=$(grep -c "Aggregated" "$OUT/omb_dist_stdout.log" 2>/dev/null)
FAIL=$(grep -c "Failed to run the workload\|ConnectException" "$OUT/omb_dist_stdout.log" 2>/dev/null)
echo "  'Pub rate' lines: $PUB   'Aggregated' lines: $AGG   failure lines: $FAIL"
if [ "${PUB:-0}" -lt 1 ] || [ "${FAIL:-0}" -gt 0 ]; then
  write_invalid "benchmark produced no latency output (pub=$PUB agg=$AGG failures=$FAIL)"
  exit 1
fi

banner "collecting discards from both workers"
remote_client "cat ~/omb_worker_client.log" > "$OUT/omb_worker_client.log" 2>/dev/null
d_of () { grep -o "SBL_DISCARDED_NONPOSITIVE total=[0-9]*" "$1" 2>/dev/null \
            | tail -1 | grep -o "[0-9]*$"; }
D_DRV=$(d_of "$OUT/omb_worker_driver.log"); D_CLI=$(d_of "$OUT/omb_worker_client.log")
D_RUN=$(d_of "$OUT/omb_dist_stdout.log")
D_DRV=${D_DRV:-0}; D_CLI=${D_CLI:-0}; D_RUN=${D_RUN:-0}
TOTAL=$D_DRV; [ "$D_CLI" -gt "$TOTAL" ] && TOTAL=$D_CLI; [ "$D_RUN" -gt "$TOTAL" ] && TOTAL=$D_RUN

printf 'harness,mode,valid,discarded_nonpositive,driver_worker,client_worker,pub_lines,duration_min,load_pct,bootstrap\n%s,%s,1,%s,%s,%s,%s,%s,%s,%s\n' \
  "OpenMessaging Benchmark" "distributed+loaded" "$TOTAL" "$D_DRV" "$D_CLI" "$PUB" \
  "$DURATION_MIN" "$LOAD_PCT" "$KAFKA_BOOTSTRAP" > "$OUT/omb_distributed_result.csv"
echo "VALID RUN. DISCARDED NON-POSITIVE SAMPLES: $TOTAL  (driver $D_DRV, client $D_CLI)"
cat "$OUT/omb_distributed_result.csv"

banner "OMB_DISTRIBUTED_COMPLETE"
