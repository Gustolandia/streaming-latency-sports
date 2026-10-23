#!/usr/bin/env bash
set -euo pipefail

# Linux trial runner for RabbitMQ on the multi-host cloud testbed, in the form of
# run_redis_trial.sh and run_kafka_trial.sh: the legacy positional form and the -FLAG form, the
# same three wraps, the same meta.json, and the same TTI computed afterwards.
#
# Usage:
#   scripts/run_rabbitmq_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] \
#       [-URI amqp://user:password@host:port] [-QUEUE q] [-PREFETCH n] \
#       [-PRODUCER_EXTRA "..."] [-CONSUMER_EXTRA "..."] [-IDLE_SECONDS n]
#
# 23 Oct 2026: -PREFETCH is the consumer's basic.qos prefetch count, the condition the block varies,
# so it is a flag of the runner's own and lands in meta.json, as -ACK_STAMP is Kafka's; it goes after
# -CONSUMER_EXTRA, so that it wins over a --prefetch already there. Empty leaves the consumer's own
# default, which its CONFIG line names.

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then SPEEDUP="$1"; shift; fi
if [ $# -gt 0 ] && [[ "$1" != -* ]]; then MAX_T_SIM="$1"; shift; fi

URI="amqp://guest:guest@localhost:5672"; QUEUE=""; PREFETCH=""
PRODUCER_EXTRA=""; CONSUMER_EXTRA=""; IDLE_SECONDS=30
while [ $# -gt 0 ]; do
  case "$1" in
    -URI) URI="$2"; shift 2;;
    -QUEUE) QUEUE="$2"; shift 2;;
    -PREFETCH) PREFETCH="$2"; shift 2;;
    -PRODUCER_EXTRA) PRODUCER_EXTRA="$2"; shift 2;;
    -CONSUMER_EXTRA) CONSUMER_EXTRA="$2"; shift 2;;
    -IDLE_SECONDS) IDLE_SECONDS="$2"; shift 2;;
    *) shift;;
  esac
done
[ -n "$QUEUE" ] || QUEUE="sb-events-$RUN_ID"
[ -n "$PREFETCH" ] && CONSUMER_EXTRA="$CONSUMER_EXTRA --prefetch $PREFETCH"

PY="${PYTHON:-python3}"
# The three wraps of run_kafka_trial.sh, which says why each exists: SBL_SCHED_WRAP prefixes both
# clients, SBL_CONSUMER_WRAP the consumer alone, SBL_PRODUCER_WRAP the producer alone after
# SBL_SCHED_WRAP; each empty by default.
SCHED_WRAP="${SBL_SCHED_WRAP:-}"
CONSUMER_WRAP="${SBL_CONSUMER_WRAP:-}"
PRODUCER_WRAP="${SBL_PRODUCER_WRAP:-}"
mkdir -p "runs/$RUN_ID"

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$URI" "$QUEUE" "$PREFETCH" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
from urllib.parse import unquote, urlsplit
run_id, plan_csv, speedup, max_t_sim, uri, queue, prefetch = sys.argv[1:8]

def sha256(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None

def cmd(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return None

# 23 Oct 2026: the broker by host and port only; the URI carries the password.
parts = urlsplit(uri)
port = parts.port or (5671 if parts.scheme == "amqps" else 5672)
meta = {
    "run_id": run_id, "backend": "rabbitmq", "plan_csv": plan_csv,
    "speedup": float(speedup), "max_t_sim": int(max_t_sim),
    "rabbitmq": {"broker": "%s:%d" % (parts.hostname, port),
                 "vhost": unquote(parts.path[1:]) or "/", "queue": queue,
                 "prefetch": int(prefetch) if prefetch else None},
    # Plan version 47 (23 Oct 2026): the plan's arrival process and the seed it was drawn from,
    # as the campaign names them, with the plan's own fingerprint.
    "plan": {"path": plan_csv, "sha256": sha256(plan_csv),
             "arrival": os.environ.get("SBL_PLAN_ARRIVAL") or None,
             "seed": int(os.environ["SBL_PLAN_SEED"]) if os.environ.get("SBL_PLAN_SEED") else None},
    "host_platform": {"system": platform.system(), "release": platform.release(),
                      "machine": platform.machine(), "node": platform.node(),
                      "python": platform.python_version()},
    "env": {"RABBITMQ_PRODUCER_OPTS": os.environ.get("RABBITMQ_PRODUCER_OPTS", ""),
            "RABBITMQ_CONSUMER_OPTS": os.environ.get("RABBITMQ_CONSUMER_OPTS", ""),
            "SBL_SCHED_WRAP": os.environ.get("SBL_SCHED_WRAP", ""),
            "SBL_CONSUMER_WRAP": os.environ.get("SBL_CONSUMER_WRAP", ""),
            "SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": {f"scripts/{f}": sha256(f"scripts/{f}") for f in
                    ("run_rabbitmq_trial.sh","rabbitmq_producer.py","rabbitmq_consumer.py",
                     "amqp_frames.py","compute_tti.py")},
}
Path(f"runs/{run_id}/meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
PY

# 23 Oct 2026: no clean slate, as Redis's runner makes with DEL: the queue is the run's own.

echo "[1/4] $(date +%H:%M:%S) starting consumer..."
# shellcheck disable=SC2086
$SCHED_WRAP $CONSUMER_WRAP "$PY" scripts/rabbitmq_consumer.py ${RABBITMQ_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
  --uri "$URI" --queue "$QUEUE" --idle-seconds "$IDLE_SECONDS" \
  $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

# 23 Oct 2026: as long as Kafka's runner waits, for the consumer to declare the queue and subscribe
# before the first message is sent, so that none waits in the queue for a consumer to come.
sleep 2
echo "[2/4] $(date +%H:%M:%S) running producer..."
# shellcheck disable=SC2086
$SCHED_WRAP $PRODUCER_WRAP "$PY" scripts/rabbitmq_producer.py ${RABBITMQ_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" --plan-csv "$PLAN_CSV" --out "runs/$RUN_ID/producer.csv" \
  --uri "$URI" --queue "$QUEUE" --speedup "$SPEEDUP" --max-t-sim "$MAX_T_SIM" \
  $PRODUCER_EXTRA > "runs/$RUN_ID/producer.log" 2>&1

echo "[3/4] $(date +%H:%M:%S) waiting for consumer..."
wait "$CONS_PID" || true

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
