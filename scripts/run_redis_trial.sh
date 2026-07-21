#!/usr/bin/env bash
set -euo pipefail

# Linux trial runner for the multi-host cloud testbed.
#
# Accepts BOTH the historical positional form and the -FLAG form used by
# run_concurrency_test.py, so one orchestrator can drive Windows (.ps1) and
# Linux (.sh) by swapping only the interpreter.
#
# Usage:
#   scripts/run_redis_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] \
#       [-RedisHost h] [-PORT p] [-STREAM s] [-GROUP g] [-CONSUMER_EXTRA "..."] \
#       [-CLUSTER_MODE] [-NODE_COUNT n] [-IDLE_SECONDS n]

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
# Leading bare values are the legacy positional SPEEDUP / MAX_T_SIM.
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then SPEEDUP="$1"; shift; fi
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then MAX_T_SIM="$1"; shift; fi

HOST="localhost"; PORT=6379; STREAM=""; GROUP=""
CONSUMER_EXTRA=""; PRODUCER_EXTRA=""; NODE_COUNT=1; CLUSTER_MODE=0; IDLE_SECONDS=30
CLUSTER_NODES=""
while [ $# -gt 0 ]; do
  case "$1" in
    -RedisHost|-REDISHOST) HOST="$2"; shift 2;;
    -PORT) PORT="$2"; shift 2;;
    -STREAM) STREAM="$2"; shift 2;;
    -GROUP) GROUP="$2"; shift 2;;
    -CONSUMER_EXTRA) CONSUMER_EXTRA="$2"; shift 2;;
    -PRODUCER_EXTRA) PRODUCER_EXTRA="$2"; shift 2;;
    -NODE_COUNT) NODE_COUNT="$2"; shift 2;;
    -IDLE_SECONDS) IDLE_SECONDS="$2"; shift 2;;
    -CLUSTER_NODES) CLUSTER_NODES="$2"; shift 2;;
    -CLUSTER_MODE) CLUSTER_MODE=1; shift;;
    *) shift;;
  esac
done
[ -n "$STREAM" ] || STREAM="sb:events:$RUN_ID"
[ -n "$GROUP" ] || GROUP="sb-group:$RUN_ID"

PY="${PYTHON:-python3}"
mkdir -p "runs/$RUN_ID"

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$HOST" "$PORT" "$STREAM" "$GROUP" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
run_id, plan_csv, speedup, max_t_sim, host, port, stream, group = sys.argv[1:9]

def sha256(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def cmd(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return None

meta = {
    "run_id": run_id, "backend": "redis", "plan_csv": plan_csv,
    "speedup": float(speedup), "max_t_sim": int(max_t_sim),
    "redis": {"host": host, "port": int(port), "stream": stream, "group": group},
    # Platform is recorded because the paper's floors (timer granularity, container
    # network path) are host properties, and cloud runs must be distinguishable.
    "host_platform": {"system": platform.system(), "release": platform.release(),
                      "machine": platform.machine(), "node": platform.node(),
                      "python": platform.python_version()},
    "env": {"REDIS_PRODUCER_OPTS": os.environ.get("REDIS_PRODUCER_OPTS", ""),
            "REDIS_CONSUMER_OPTS": os.environ.get("REDIS_CONSUMER_OPTS", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": {f"scripts/{f}": sha256(f"scripts/{f}") for f in
                    ("run_redis_trial.sh","redis_producer.py","redis_consumer.py","compute_tti.py")},
}
Path(f"runs/{run_id}/meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PY

# Clean slate; redis-cli may be absent on the driver, so failure here is non-fatal.
redis-cli -h "$HOST" -p "$PORT" DEL "$STREAM" >/dev/null 2>&1 || true

CLUSTER_FLAG=""
[ "$CLUSTER_MODE" = "1" ] && CLUSTER_FLAG="--cluster-mode"
[ -n "$CLUSTER_NODES" ] && CLUSTER_FLAG="$CLUSTER_FLAG --cluster-nodes $CLUSTER_NODES"

echo "[1/4] $(date +%H:%M:%S) starting consumer..."
# shellcheck disable=SC2086
"$PY" scripts/redis_consumer.py ${REDIS_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
  --host "$HOST" --port "$PORT" --stream "$STREAM" --group "$GROUP" \
  --idle-seconds "$IDLE_SECONDS" --node-count "$NODE_COUNT" $CLUSTER_FLAG \
  $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

sleep 1
echo "[2/4] $(date +%H:%M:%S) running producer..."
# shellcheck disable=SC2086
"$PY" scripts/redis_producer.py ${REDIS_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
  --host "$HOST" --port "$PORT" --stream "$STREAM" \
  --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" --node-count "$NODE_COUNT" $CLUSTER_FLAG \
  $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1

echo "[3/4] $(date +%H:%M:%S) waiting for consumer..."
wait "$CONS_PID" || true

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
