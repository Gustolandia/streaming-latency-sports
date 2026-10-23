#!/usr/bin/env bash
set -euo pipefail

# Linux trial runner for the multi-host cloud testbed. See run_redis_trial.sh for the
# rationale on accepting both the legacy positional form and the -FLAG form.
#
# Usage:
#   scripts/run_kafka_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] \
#       [-BOOTSTRAP host:port] [-TOPIC t] [-BROKER_COUNT n] [-PRODUCER_EXTRA "..."] \
#       [-CONSUMER_EXTRA "..."] [-IDLE_SECONDS n] [-CLIENT python|java] [-ACK_STAMP callback|inline] \
#       [-CONSUMER kafka-python|confluent|java|franz] [-FETCH_RT]
#
# -CLIENT swaps which client sends and receives, and nothing else. A8 compares our Python client
# with Kafka's official Java one, so everything around the client -- the plan, the topic, the
# wrapping, the metadata, the TTI computed afterwards -- has to stay identical, or the block
# compares two harnesses. That is why this is one script with one dispatch and not two scripts.
#
# Plan version 47 (23 Oct 2026): -CONSUMER swaps the consumer alone, and kafka_producer.py sends in
# every run, so that block K compares four consumers behind one producer: kafka-python's (the
# default, scripts/kafka_consumer.py), librdkafka's (scripts/kafka_consumer_confluent.py),
# kafka-clients' (harness/java's LawConsumer) and franz-go's (harness/go's franz-consumer). The
# last three write their threads to runs/<id>/consumer_tids.csv once the group has assigned them
# the partitions, and the producer starts only once that list is there, so that no message is sent
# before the consumer can fetch it; a consumer that writes none within SBL_THREADS_WAIT_S seconds
# (60 unless set) fails the trial. -FETCH_RT then raises each thread the list names as sending the
# fetches to SCHED_FIFO 80 (SBL_FETCH_RT_PRIORITY) before the producer starts, and a list that names none, as franz-go's
# never does, fails the trial too (scripts/consumer_threads.py, which writes what it found and did
# to consumer_threads.json). The Java and Go consumers take none of -CONSUMER_EXTRA's flags, which
# are the Python clients', and the run's own record names the flags they were not handed.

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then SPEEDUP="$1"; shift; fi
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then MAX_T_SIM="$1"; shift; fi

BOOTSTRAP="localhost:9092"; TOPIC=""; BROKER_COUNT=1
PRODUCER_EXTRA=""; CONSUMER_EXTRA=""; IDLE_SECONDS=30
CLIENT="python"; ACK_STAMP=""; CONSUMER=""; FETCH_RT=0
while [ $# -gt 0 ]; do
  case "$1" in
    -BOOTSTRAP) BOOTSTRAP="$2"; shift 2;;
    -TOPIC) TOPIC="$2"; shift 2;;
    -BROKER_COUNT) BROKER_COUNT="$2"; shift 2;;
    -PRODUCER_EXTRA) PRODUCER_EXTRA="$2"; shift 2;;
    -CONSUMER_EXTRA) CONSUMER_EXTRA="$2"; shift 2;;
    -IDLE_SECONDS) IDLE_SECONDS="$2"; shift 2;;
    -CLIENT) CLIENT="$2"; shift 2;;
    -ACK_STAMP) ACK_STAMP="$2"; shift 2;;
    -CONSUMER) CONSUMER="$2"; shift 2;;
    -FETCH_RT) FETCH_RT=1; shift;;
    *) shift;;
  esac
done
[ -n "$TOPIC" ] || TOPIC="sb-events-$RUN_ID"

PY="${PYTHON:-python3}"
# SBL_SCHED_WRAP prefixes the two processes that read the clock, so a campaign can change how
# often the stamping thread is preempted WITHOUT changing system utilisation. That separation is
# the whole point: rho and the residual width move together across a load ladder, so no curve fit
# can tell an occupancy mechanism from a utilisation one. Setting this to e.g. "sudo chrt -f 80"
# moves occupancy alone and breaks the collinearity. Empty by default, so every existing campaign
# behaves exactly as before. Applied to producer AND consumer because the measured transport is
# a difference of stamps taken in the two.
SCHED_WRAP="${SBL_SCHED_WRAP:-}"
# SBL_CONSUMER_WRAP prefixes the consumer alone. The receiver-only delay needs it: the consumer
# must connect from its own address, inside the namespace scripts/receiver_delay.py builds, so
# the broker can delay what the consumer receives without delaying the producer's "got it" reply.
# A campaign sets it to "sudo ip netns exec sblrecv sudo -u $USER". Empty by default, so every
# existing campaign behaves exactly as before.
CONSUMER_WRAP="${SBL_CONSUMER_WRAP:-}"
# SBL_PRODUCER_WRAP prefixes the producer alone, after SBL_SCHED_WRAP. Freeze 43 (22 Oct 2026): a
# campaign sets it to "sudo chrt -f 80" so that the producer runs at real-time priority in every
# setup and only the consumer's priority varies: under block U's 70% load at 2,000 messages a
# second, Redis's producer at normal priority sent its messages a median of 24 ms after their
# planned times. Empty by default, so every existing campaign behaves exactly as before.
PRODUCER_WRAP="${SBL_PRODUCER_WRAP:-}"
mkdir -p "runs/$RUN_ID"

# Plan version 47 (23 Oct 2026): the consumer that receives, the client's own unless -CONSUMER
# names another; the thread list of the three that write one; and, for the two that take none of
# the Python clients' flags, which flags they were not handed.
case "$CONSUMER" in
  ""|kafka-python|confluent|java|franz) ;;
  *) echo "FATAL: -CONSUMER is kafka-python, confluent, java or franz, not '$CONSUMER'"; exit 2 ;;
esac
if [ -n "$CONSUMER" ] && [ "$CLIENT" = java ]; then
  echo "FATAL: -CLIENT java swaps both clients and -CONSUMER the consumer alone; a run names one"
  exit 2
fi
RECEIVER="${CONSUMER:-kafka-python}"
[ "$CLIENT" = java ] && RECEIVER=java
THREADS=""
case "$CONSUMER" in confluent|java|franz) THREADS="runs/$RUN_ID/consumer_tids.csv" ;; esac
if [ "$FETCH_RT" = 1 ] && [ -z "$THREADS" ]; then
  echo "FATAL: -FETCH_RT raises the fetch threads a consumer names in its thread list, which only -CONSUMER confluent, java and franz write"
  exit 2
fi
NOT_HANDED=""
if [ "$RECEIVER" = java ] || [ "$RECEIVER" = franz ]; then NOT_HANDED="$CONSUMER_EXTRA"; fi

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$BOOTSTRAP" "$TOPIC" "$RECEIVER" \
  "$THREADS" "$FETCH_RT" "$NOT_HANDED" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
run_id, plan_csv, speedup, max_t_sim, bootstrap, topic = sys.argv[1:7]
receiver, threads, fetch_rt, not_handed = sys.argv[7:11]

def sha256(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def cmd(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return None

meta = {
    "run_id": run_id, "backend": "kafka", "plan_csv": plan_csv,
    "speedup": float(speedup), "max_t_sim": int(max_t_sim),
    "bootstrap": bootstrap, "topic": topic,
    # Plan version 47 (23 Oct 2026): which consumer received, its thread list, whether its fetch
    # threads were to be raised, and the flags a consumer that takes none was not handed.
    "consumer": {"client": receiver, "threads_out": threads or None,
                 "fetch_rt": fetch_rt == "1", "extra_not_handed": not_handed.strip() or None},
    # Plan version 47 (23 Oct 2026): the plan's arrival process and the seed it was drawn from,
    # as the campaign names them, with the plan's own fingerprint.
    "plan": {"path": plan_csv, "sha256": sha256(plan_csv),
             "arrival": os.environ.get("SBL_PLAN_ARRIVAL") or None,
             "seed": int(os.environ["SBL_PLAN_SEED"]) if os.environ.get("SBL_PLAN_SEED") else None},
    # Platform is recorded because the paper's floors (timer granularity, container
    # network path) are host properties, and cloud runs must be distinguishable.
    "host_platform": {"system": platform.system(), "release": platform.release(),
                      "machine": platform.machine(), "node": platform.node(),
                      "python": platform.python_version()},
    "env": {"KAFKA_PRODUCER_OPTS": os.environ.get("KAFKA_PRODUCER_OPTS", ""),
            "KAFKA_CONSUMER_OPTS": os.environ.get("KAFKA_CONSUMER_OPTS", ""),
            # Which arm a run belonged to must be readable from the run itself.
            "SBL_SCHED_WRAP": os.environ.get("SBL_SCHED_WRAP", ""),
            "SBL_CONSUMER_WRAP": os.environ.get("SBL_CONSUMER_WRAP", ""),
            "SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": dict({f"scripts/{f}": sha256(f"scripts/{f}") for f in
                         ("run_kafka_trial.sh","kafka_producer.py","kafka_consumer.py",
                          "kafka_consumer_confluent.py","consumer_threads.py","compute_tti.py")},
                        # Plan version 47 (23 Oct 2026): the Java and Go consumers, by their
                        # sources and what was built from them.
                        **{f: sha256(f) for f in
                           ("harness/java/src/LawConsumer.java", "harness/java/src/LawProducer.java",
                            "harness/go/main.go", "harness/go/out/franz-consumer")}),
}
Path(f"runs/{run_id}/meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PY

# Where the got-it note is taken is a condition A8 varies, so it reaches both clients the same
# way: one option on the producer, named the same in each.
#
# Taking it inline also forces one request in flight, in both clients, and they refuse otherwise:
# above one, the blocking wait resolves an older event and the stamp would belong to a different
# message. The campaign's standing setting is 64, so it is overridden here rather than in the
# campaign, and run_integrity.py knows to expect 1 for an inline run. Both options are later, so
# they win over anything PRODUCER_EXTRA already carried.
if [ -n "$ACK_STAMP" ]; then
  PRODUCER_EXTRA="$PRODUCER_EXTRA --ack-stamp $ACK_STAMP"
  if [ "$ACK_STAMP" = inline ]; then
    PRODUCER_EXTRA="$PRODUCER_EXTRA --max-inflight 1"
  fi
fi

JAVA_BIN="${SBL_JAVA:-java}"
JAVA_CP="harness/java/out:harness/java/lib/kafka-clients.jar:harness/java/lib/slf4j-api.jar"
if [ "$RECEIVER" = java ] && [ ! -d harness/java/out ]; then
  echo "FATAL: the java consumer runs, but harness/java/out is not built. Run bash harness/java/build.sh" >&2
  exit 1
fi
FRANZ_BIN="harness/go/out/franz-consumer"
if [ "$RECEIVER" = franz ] && [ ! -x "$FRANZ_BIN" ]; then
  echo "FATAL: -CONSUMER franz, but $FRANZ_BIN is not built. Run bash harness/go/build.sh" >&2
  exit 1
fi

echo "[1/4] $(date +%H:%M:%S) starting consumer ($RECEIVER)..."
# shellcheck disable=SC2086
case "$RECEIVER" in
  java)
    $SCHED_WRAP $CONSUMER_WRAP "$JAVA_BIN" -cp "$JAVA_CP" LawConsumer \
      --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
      --bootstrap "$BOOTSTRAP" --topic "$TOPIC" --idle-seconds "$IDLE_SECONDS" \
      ${THREADS:+--threads-out "$THREADS"} > "runs/$RUN_ID/consumer.log" 2>&1 &
    ;;
  confluent)
    # Not KAFKA_CONSUMER_OPTS: its knobs are kafka-python's, and this consumer refuses them.
    $SCHED_WRAP $CONSUMER_WRAP "$PY" scripts/kafka_consumer_confluent.py \
      --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
      --bootstrap "$BOOTSTRAP" --topic "$TOPIC" --idle-seconds "$IDLE_SECONDS" \
      --broker-count "$BROKER_COUNT" --threads-out "$THREADS" $CONSUMER_EXTRA \
      > "runs/$RUN_ID/consumer.log" 2>&1 &
    ;;
  franz)
    $SCHED_WRAP $CONSUMER_WRAP "$FRANZ_BIN" \
      --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
      --bootstrap "$BOOTSTRAP" --topic "$TOPIC" --idle-seconds "$IDLE_SECONDS" \
      --threads-out "$THREADS" > "runs/$RUN_ID/consumer.log" 2>&1 &
    ;;
  *)
    $SCHED_WRAP $CONSUMER_WRAP "$PY" scripts/kafka_consumer.py ${KAFKA_CONSUMER_OPTS:-} \
      --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
      --bootstrap "$BOOTSTRAP" --topic "$TOPIC" --idle-seconds "$IDLE_SECONDS" \
      --broker-count "$BROKER_COUNT" $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
    ;;
esac
CONS_PID=$!
[ -z "$NOT_HANDED" ] || echo "NOTE: the $RECEIVER consumer takes none of the Python clients' flags; not handed: $NOT_HANDED"

# Plan version 47 (23 Oct 2026): the consumer's thread list before the producer starts, and its
# fetch threads raised where the run asks. A trial that cannot have either is stopped here, its
# consumer with it, before a message is sent.
if [ -n "$THREADS" ]; then
  RAISE=()
  [ "$FETCH_RT" = 1 ] && RAISE=(--priority "${SBL_FETCH_RT_PRIORITY:-80}")
  "$PY" scripts/consumer_threads.py --threads "$THREADS" --pid "$CONS_PID" \
    --timeout-s "${SBL_THREADS_WAIT_S:-60}" --out "runs/$RUN_ID/consumer_threads.json" \
    "${RAISE[@]}" || {
    echo "FATAL: the consumer's threads were not settled before the producer; see runs/$RUN_ID/consumer_threads.json"
    pkill -f "runs/$RUN_ID/consumer.csv" 2>/dev/null || true
    wait "$CONS_PID" 2>/dev/null || true
    exit 3
  }
fi

sleep 2
echo "[2/4] $(date +%H:%M:%S) running producer..."
# KAFKA_PRODUCER_SCRIPT lets a campaign swap the client library without touching the
# orchestrator. Used by cloud/campaigns/m1_client_ab.sh to run the identical experiment
# against confluent-kafka, which is how "Kafka" is separated from "kafka-python".
KAFKA_PRODUCER_SCRIPT="${KAFKA_PRODUCER_SCRIPT:-scripts/kafka_producer.py}"
# shellcheck disable=SC2086
if [ "$CLIENT" = java ]; then
  $SCHED_WRAP $PRODUCER_WRAP "$JAVA_BIN" -cp "$JAVA_CP" LawProducer \
    --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
    --bootstrap "$BOOTSTRAP" --topic "$TOPIC" \
    --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" \
    $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1
else
  $SCHED_WRAP $PRODUCER_WRAP "$PY" "$KAFKA_PRODUCER_SCRIPT" ${KAFKA_PRODUCER_OPTS:-} \
    --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
    --bootstrap "$BOOTSTRAP" --topic "$TOPIC" \
    --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" --broker-count "$BROKER_COUNT" \
    $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1
fi

echo "[3/4] $(date +%H:%M:%S) waiting for consumer..."
wait "$CONS_PID" || true

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
