#!/usr/bin/env bash
set -euo pipefail

# Linux trial runner for block N's NATS JetStream runs, as run_redis_trial.sh is for Redis's: the
# consumer started first, in the background; the producer a second later, in the foreground; the
# consumer waited for; and compute_tti.py over the two CSVs. The server is the kit's: this starts
# and stops only the two clients.
#
# Usage:
#   scripts/run_nats_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] \
#       [-NatsHost h] [-PORT p] [-STREAM s] [-SUBJECT x] [-DURABLE d] [-DEPTH n] \
#       [-EXPIRES_S s] [-STORAGE file|memory] [-ONE_REPLY_READS] [-DELETE_STREAM] \
#       [-CONSUMER_EXTRA "..."] [-PRODUCER_EXTRA "..."] [-IDLE_SECONDS n]
#
# Unless named, the stream and its subject are named after the run and the moment this trial
# began, and the durable consumer after the run: a trial run again under the same run id then
# writes to a stream of its own, and no message of an earlier attempt can be read as this one's.
# -DELETE_STREAM has the consumer delete the stream once it is done; without it the stream stays
# on the broker's disk.

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
# Leading bare values are the positional SPEEDUP / MAX_T_SIM, as in run_redis_trial.sh.
if [ $# -gt 0 ]; then case "$1" in -*) ;; *) SPEEDUP="$1"; shift;; esac; fi
if [ $# -gt 0 ]; then case "$1" in -*) ;; *) MAX_T_SIM="$1"; shift;; esac; fi

HOST="localhost"; PORT=4222; STREAM=""; SUBJECT=""; DURABLE=""
DEPTH=1; EXPIRES_S=30; STORAGE="file"; ONE_REPLY=0; DELETE_STREAM=0; IDLE_SECONDS=30
CONSUMER_EXTRA=""; PRODUCER_EXTRA=""
while [ $# -gt 0 ]; do
  case "$1" in
    -NatsHost|-NATSHOST) HOST="$2"; shift 2;;
    -PORT) PORT="$2"; shift 2;;
    -STREAM) STREAM="$2"; shift 2;;
    -SUBJECT) SUBJECT="$2"; shift 2;;
    -DURABLE) DURABLE="$2"; shift 2;;
    -DEPTH) DEPTH="$2"; shift 2;;
    -EXPIRES_S) EXPIRES_S="$2"; shift 2;;
    -STORAGE) STORAGE="$2"; shift 2;;
    -CONSUMER_EXTRA) CONSUMER_EXTRA="$2"; shift 2;;
    -PRODUCER_EXTRA) PRODUCER_EXTRA="$2"; shift 2;;
    -IDLE_SECONDS) IDLE_SECONDS="$2"; shift 2;;
    -ONE_REPLY_READS) ONE_REPLY=1; shift;;
    -DELETE_STREAM) DELETE_STREAM=1; shift;;
    *) shift;;
  esac
done
# A name JetStream takes whatever the run id holds: letters, digits, '_' and '-'.
SAFE_ID=$(printf '%s' "$RUN_ID" | tr -c 'A-Za-z0-9_-' '_')
BEGAN=$(date -u +%Y%m%d%H%M%S)
[ -n "$STREAM" ] || STREAM="SBL_${SAFE_ID}_$BEGAN"
[ -n "$SUBJECT" ] || SUBJECT="sbl.$SAFE_ID.$BEGAN"
[ -n "$DURABLE" ] || DURABLE="sbl-$SAFE_ID"

PY="${PYTHON:-python3}"
mkdir -p "runs/$RUN_ID"

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$HOST" "$PORT" "$STREAM" "$SUBJECT" \
  "$DURABLE" "$DEPTH" "$EXPIRES_S" "$STORAGE" "$ONE_REPLY" "$DELETE_STREAM" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
(run_id, plan_csv, speedup, max_t_sim, host, port, stream, subject, durable, depth, expires_s,
 storage, one_reply, delete_stream) = sys.argv[1:15]

def sha256(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def cmd(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return None

meta = {
    "run_id": run_id, "backend": "nats", "plan_csv": plan_csv,
    "speedup": float(speedup), "max_t_sim": int(max_t_sim),
    "nats": {"host": host, "port": int(port), "stream": stream, "subject": subject,
             "durable": durable, "depth": int(depth), "expires_s": float(expires_s),
             "storage": storage, "one_reply_reads": one_reply == "1",
             "delete_stream": delete_stream == "1"},
    # Platform is recorded because the paper's floors (timer granularity, container
    # network path) are host properties, and cloud runs must be distinguishable.
    "host_platform": {"system": platform.system(), "release": platform.release(),
                      "machine": platform.machine(), "node": platform.node(),
                      "python": platform.python_version()},
    "env": {"NATS_PRODUCER_OPTS": os.environ.get("NATS_PRODUCER_OPTS", ""),
            "NATS_CONSUMER_OPTS": os.environ.get("NATS_CONSUMER_OPTS", ""),
            # Which arm a run belonged to must be readable from the run itself.
            "SBL_SCHED_WRAP": os.environ.get("SBL_SCHED_WRAP", ""),
            "SBL_CONSUMER_WRAP": os.environ.get("SBL_CONSUMER_WRAP", ""),
            "SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": {f"scripts/{f}": sha256(f"scripts/{f}") for f in
                    ("run_nats_trial.sh","nats_wire.py","nats_producer.py","nats_consumer.py",
                     "compute_tti.py")},
}
Path(f"runs/{run_id}/meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PY

# As in run_redis_trial.sh: SBL_SCHED_WRAP prefixes both clients, SBL_CONSUMER_WRAP the consumer
# alone (behind the receiver's own address) and SBL_PRODUCER_WRAP the producer alone, after
# SBL_SCHED_WRAP. Each is empty by default.
SCHED_WRAP="${SBL_SCHED_WRAP:-}"
CONSUMER_WRAP="${SBL_CONSUMER_WRAP:-}"
PRODUCER_WRAP="${SBL_PRODUCER_WRAP:-}"

CONSUMER_FLAGS=""
[ "$ONE_REPLY" = "1" ] && CONSUMER_FLAGS="--one-reply-reads"
[ "$DELETE_STREAM" = "1" ] && CONSUMER_FLAGS="$CONSUMER_FLAGS --delete-stream"

echo "[1/4] $(date +%H:%M:%S) starting consumer..."
# shellcheck disable=SC2086
$SCHED_WRAP $CONSUMER_WRAP "$PY" scripts/nats_consumer.py ${NATS_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
  --host "$HOST" --port "$PORT" --stream "$STREAM" --subject "$SUBJECT" --durable "$DURABLE" \
  --storage "$STORAGE" --depth "$DEPTH" --expires-s "$EXPIRES_S" \
  --idle-seconds "$IDLE_SECONDS" $CONSUMER_FLAGS \
  $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

sleep 1
echo "[2/4] $(date +%H:%M:%S) running producer..."
# shellcheck disable=SC2086
$SCHED_WRAP $PRODUCER_WRAP "$PY" scripts/nats_producer.py ${NATS_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
  --host "$HOST" --port "$PORT" --stream "$STREAM" --subject "$SUBJECT" --storage "$STORAGE" \
  --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" \
  $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1

echo "[3/4] $(date +%H:%M:%S) waiting for consumer..."
wait "$CONS_PID" || true

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
