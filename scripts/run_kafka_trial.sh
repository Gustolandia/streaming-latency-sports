#!/usr/bin/env bash
set -euo pipefail

# Linux trial runner for the multi-host cloud testbed. See run_redis_trial.sh for the
# rationale on accepting both the legacy positional form and the -FLAG form.
#
# Usage:
#   scripts/run_kafka_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] \
#       [-BOOTSTRAP host:port] [-TOPIC t] [-BROKER_COUNT n] [-PRODUCER_EXTRA "..."] \
#       [-CONSUMER_EXTRA "..."] [-IDLE_SECONDS n]

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then SPEEDUP="$1"; shift; fi
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then MAX_T_SIM="$1"; shift; fi

BOOTSTRAP="localhost:9092"; TOPIC=""; BROKER_COUNT=1
PRODUCER_EXTRA=""; CONSUMER_EXTRA=""; IDLE_SECONDS=30
while [ $# -gt 0 ]; do
  case "$1" in
    -BOOTSTRAP) BOOTSTRAP="$2"; shift 2;;
    -TOPIC) TOPIC="$2"; shift 2;;
    -BROKER_COUNT) BROKER_COUNT="$2"; shift 2;;
    -PRODUCER_EXTRA) PRODUCER_EXTRA="$2"; shift 2;;
    -CONSUMER_EXTRA) CONSUMER_EXTRA="$2"; shift 2;;
    -IDLE_SECONDS) IDLE_SECONDS="$2"; shift 2;;
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
mkdir -p "runs/$RUN_ID"

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$BOOTSTRAP" "$TOPIC" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
run_id, plan_csv, speedup, max_t_sim, bootstrap, topic = sys.argv[1:7]

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
    # Platform is recorded because the paper's floors (timer granularity, container
    # network path) are host properties, and cloud runs must be distinguishable.
    "host_platform": {"system": platform.system(), "release": platform.release(),
                      "machine": platform.machine(), "node": platform.node(),
                      "python": platform.python_version()},
    "env": {"KAFKA_PRODUCER_OPTS": os.environ.get("KAFKA_PRODUCER_OPTS", ""),
            "KAFKA_CONSUMER_OPTS": os.environ.get("KAFKA_CONSUMER_OPTS", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": {f"scripts/{f}": sha256(f"scripts/{f}") for f in
                    ("run_kafka_trial.sh","kafka_producer.py","kafka_consumer.py","compute_tti.py")},
}
Path(f"runs/{run_id}/meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PY

echo "[1/4] $(date +%H:%M:%S) starting consumer..."
# shellcheck disable=SC2086
$SCHED_WRAP "$PY" scripts/kafka_consumer.py ${KAFKA_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
  --bootstrap "$BOOTSTRAP" --topic "$TOPIC" --idle-seconds "$IDLE_SECONDS" \
  --broker-count "$BROKER_COUNT" $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

sleep 2
echo "[2/4] $(date +%H:%M:%S) running producer..."
# KAFKA_PRODUCER_SCRIPT lets a campaign swap the client library without touching the
# orchestrator. Used by cloud/campaigns/m1_client_ab.sh to run the identical experiment
# against confluent-kafka, which is how "Kafka" is separated from "kafka-python".
KAFKA_PRODUCER_SCRIPT="${KAFKA_PRODUCER_SCRIPT:-scripts/kafka_producer.py}"
# shellcheck disable=SC2086
$SCHED_WRAP "$PY" "$KAFKA_PRODUCER_SCRIPT" ${KAFKA_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
  --bootstrap "$BOOTSTRAP" --topic "$TOPIC" \
  --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" --broker-count "$BROKER_COUNT" \
  $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1

echo "[3/4] $(date +%H:%M:%S) waiting for consumer..."
wait "$CONS_PID" || true

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
