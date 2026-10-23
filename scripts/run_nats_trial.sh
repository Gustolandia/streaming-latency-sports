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
#       [-CONSUMER_EXTRA "..."] [-PRODUCER_EXTRA "..."] [-IDLE_SECONDS n] [-CONSUMER python|nats-go]
#
# Unless named, the stream and its subject are named after the run and the moment this trial
# began, and the durable consumer after the run: a trial run again under the same run id then
# writes to a stream of its own, and no message of an earlier attempt can be read as this one's.
# -DELETE_STREAM has the consumer delete the stream once it is done; without it the stream stays
# on the broker's disk.
#
# Plan version 47 (23 Oct 2026): -CONSUMER nats-go receives with harness/go-nats's
# natsgo-consumer, nats.go's Consume(), which keeps its own requests waiting (500 messages,
# refilled at 250), and so takes neither -DEPTH nor -ONE_REPLY_READS. It is handed the run's names,
# its storage and its idle time, writes the files the python consumer writes, and writes its
# threads to runs/<id>/consumer_tids.csv once it consumes; the producer starts only once that list
# is there (scripts/consumer_threads.py), and a consumer that writes none within SBL_THREADS_WAIT_S
# seconds (60 unless set) fails the trial. It deletes no stream, so with -DELETE_STREAM the runner
# deletes it once the consumer is done. It takes none of -CONSUMER_EXTRA's flags or
# NATS_CONSUMER_OPTS, which are the python consumer's, and the run's record names what it was not
# handed.

RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
shift 2

SPEEDUP=120; MAX_T_SIM=600
# Leading bare values are the positional SPEEDUP / MAX_T_SIM, as in run_redis_trial.sh.
if [ $# -gt 0 ]; then case "$1" in -*) ;; *) SPEEDUP="$1"; shift;; esac; fi
if [ $# -gt 0 ]; then case "$1" in -*) ;; *) MAX_T_SIM="$1"; shift;; esac; fi

HOST="localhost"; PORT=4222; STREAM=""; SUBJECT=""; DURABLE=""
DEPTH=""; EXPIRES_S=30; STORAGE="file"; ONE_REPLY=0; DELETE_STREAM=0; IDLE_SECONDS=30
CONSUMER_EXTRA=""; PRODUCER_EXTRA=""; CONSUMER=""
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
    -CONSUMER) CONSUMER="$2"; shift 2;;
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

# Plan version 47 (23 Oct 2026): the consumer that receives, python's unless -CONSUMER names
# nats.go's; the depth each keeps, the python consumer's 1 unless given; and nats.go's thread list.
case "$CONSUMER" in
  ""|python|nats-go) ;;
  *) echo "FATAL: -CONSUMER is python or nats-go, not '$CONSUMER'"; exit 2 ;;
esac
RECEIVER="${CONSUMER:-python}"
THREADS=""; NOT_HANDED=""
GO_NATS_BIN="harness/go-nats/out/natsgo-consumer"
if [ "$RECEIVER" = nats-go ]; then
  if [ -n "$DEPTH" ] || [ "$ONE_REPLY" = 1 ]; then
    echo "FATAL: -DEPTH and -ONE_REPLY_READS are the python consumer's; nats.go's Consume() keeps its own requests"
    exit 2
  fi
  [ -x "$GO_NATS_BIN" ] || {
    echo "FATAL: -CONSUMER nats-go, but $GO_NATS_BIN is not built. Run bash cloud/azure/tools.sh clients"
    exit 1; }
  THREADS="runs/$RUN_ID/consumer_tids.csv"
  NOT_HANDED="${NATS_CONSUMER_OPTS:-} $CONSUMER_EXTRA"
else
  DEPTH="${DEPTH:-1}"
fi

"$PY" - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$HOST" "$PORT" "$STREAM" "$SUBJECT" \
  "$DURABLE" "$DEPTH" "$EXPIRES_S" "$STORAGE" "$ONE_REPLY" "$DELETE_STREAM" "$RECEIVER" \
  "$THREADS" "$NOT_HANDED" <<'PY'
import json, os, sys, hashlib, subprocess, platform
from pathlib import Path
(run_id, plan_csv, speedup, max_t_sim, host, port, stream, subject, durable, depth, expires_s,
 storage, one_reply, delete_stream, receiver, threads, not_handed) = sys.argv[1:18]

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
             "durable": durable, "depth": int(depth) if depth else None,
             "expires_s": float(expires_s), "storage": storage,
             "one_reply_reads": one_reply == "1", "delete_stream": delete_stream == "1"},
    # Plan version 47 (23 Oct 2026): which consumer received, its thread list, and the flags a
    # consumer that takes none of the python consumer's was not handed.
    "consumer": {"client": receiver, "threads_out": threads or None,
                 "extra_not_handed": not_handed.strip() or None},
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
    "env": {"NATS_PRODUCER_OPTS": os.environ.get("NATS_PRODUCER_OPTS", ""),
            "NATS_CONSUMER_OPTS": os.environ.get("NATS_CONSUMER_OPTS", ""),
            # Which arm a run belonged to must be readable from the run itself.
            "SBL_SCHED_WRAP": os.environ.get("SBL_SCHED_WRAP", ""),
            "SBL_CONSUMER_WRAP": os.environ.get("SBL_CONSUMER_WRAP", ""),
            "SBL_PRODUCER_WRAP": os.environ.get("SBL_PRODUCER_WRAP", "")},
    "git": {"head": cmd(["git","rev-parse","HEAD"]),
            "status_short": cmd(["git","status","--porcelain"])},
    "code_sha256": dict({f"scripts/{f}": sha256(f"scripts/{f}") for f in
                         ("run_nats_trial.sh","nats_wire.py","nats_producer.py","nats_consumer.py",
                          "consumer_threads.py","compute_tti.py")},
                        # Plan version 47 (23 Oct 2026): nats.go's consumer, as it was built.
                        **{f: sha256(f) for f in
                           ("harness/go-nats/main.go", "harness/go-nats/out/natsgo-consumer")}),
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

echo "[1/4] $(date +%H:%M:%S) starting consumer ($RECEIVER)..."
# shellcheck disable=SC2086
if [ "$RECEIVER" = nats-go ]; then
  $SCHED_WRAP $CONSUMER_WRAP "$GO_NATS_BIN" \
    --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
    --host "$HOST" --port "$PORT" --stream "$STREAM" --subject "$SUBJECT" --durable "$DURABLE" \
    --storage "$STORAGE" --idle-seconds "$IDLE_SECONDS" \
    --threads-out "$THREADS" > "runs/$RUN_ID/consumer.log" 2>&1 &
else
  $SCHED_WRAP $CONSUMER_WRAP "$PY" scripts/nats_consumer.py ${NATS_CONSUMER_OPTS:-} \
    --run-id "$RUN_ID" --out "runs/$RUN_ID/consumer.csv" \
    --host "$HOST" --port "$PORT" --stream "$STREAM" --subject "$SUBJECT" --durable "$DURABLE" \
    --storage "$STORAGE" --depth "$DEPTH" --expires-s "$EXPIRES_S" \
    --idle-seconds "$IDLE_SECONDS" $CONSUMER_FLAGS \
    $CONSUMER_EXTRA > "runs/$RUN_ID/consumer.log" 2>&1 &
fi
CONS_PID=$!
[ -z "${NOT_HANDED// /}" ] || echo "NOTE: the nats-go consumer takes none of the python consumer's flags; not handed: $NOT_HANDED"

# Plan version 47 (23 Oct 2026): nats.go's thread list before the producer starts, as
# run_kafka_trial.sh waits for its consumers'; a trial without it is stopped here, its consumer
# with it, before a message is sent.
if [ -n "$THREADS" ]; then
  "$PY" scripts/consumer_threads.py --threads "$THREADS" --pid "$CONS_PID" \
    --timeout-s "${SBL_THREADS_WAIT_S:-60}" --out "runs/$RUN_ID/consumer_threads.json" || {
    echo "FATAL: the consumer's threads were not listed before the producer; see runs/$RUN_ID/consumer_threads.json"
    pkill -f "runs/$RUN_ID/consumer.csv" 2>/dev/null || true
    wait "$CONS_PID" 2>/dev/null || true
    exit 3
  }
fi

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
# Plan version 47 (23 Oct 2026): nats.go's consumer deletes no stream, so where the run asks the
# runner deletes it once the consumer is done, as the python consumer deletes its own, so that a
# block's streams do not fill the server's memory run by run.
if [ "$RECEIVER" = nats-go ] && [ "$DELETE_STREAM" = 1 ]; then
  "$PY" - "$HOST" "$PORT" "$STREAM" <<'PY' || echo "NOTE: the stream $STREAM could not be deleted; it stays on the server"
import socket, sys
sys.path.insert(0, "scripts")
import nats_wire
link = nats_wire.Link.open(socket.create_connection, sys.argv[1], int(sys.argv[2]), "sbl-cleanup")
nats_wire.api(link, *nats_wire.stream_delete(sys.argv[3]))
link.close()
print("OK stream deleted: %s" % sys.argv[3])
PY
fi

echo "[4/4] $(date +%H:%M:%S) computing TTI..."
"$PY" scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" | tee "runs/$RUN_ID/tti_summary.printed.json"
echo "DONE $RUN_ID"
