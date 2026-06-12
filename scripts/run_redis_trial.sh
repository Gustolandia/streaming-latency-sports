#!/usr/bin/env bash
set -euo pipefail

# Fix PATH to use Windows docker CLI which sees Docker Desktop containers
export PATH="/mnt/c/PROGRA~1/Docker/Docker/resources/bin:$PATH"

# Usage:
#   scripts/run_redis_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] [HOST] [PORT] [STREAM] [GROUP]
RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
SPEEDUP="${3:-120}"
MAX_T_SIM="${4:-600}"
HOST="${5:-localhost}"
PORT="${6:-6379}"
STREAM="${7:-sb:events:$RUN_ID}"
GROUP="${8:-sb-group:$RUN_ID}"

mkdir -p "runs/$RUN_ID"

# Write per-run provenance (reviewer-proof)
python - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$HOST" "$PORT" "$STREAM" "$GROUP" <<'PY'
import json, os, sys, hashlib, subprocess
from pathlib import Path
run_id, plan_csv, speedup, max_t_sim, host, port, stream, group = sys.argv[1:9]

def sha256(path: str):
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()

def cmd(args):
    try:
        return subprocess.check_output(args, text=True).strip()
    except Exception:
        return None

meta = {
    "run_id": run_id,
    "backend": "redis",
    "plan_csv": plan_csv,
    "speedup": float(speedup),
    "max_t_sim": int(max_t_sim),
    "redis": {
        "host": host,
        "port": int(port),
        "stream": stream,
        "group": group,
    },
    "env": {
        "REDIS_PRODUCER_OPTS": os.environ.get("REDIS_PRODUCER_OPTS", ""),
        "REDIS_CONSUMER_OPTS": os.environ.get("REDIS_CONSUMER_OPTS", ""),
    },
    "git": {
        "head": cmd(["git","rev-parse","HEAD"]),
        "status_short": cmd(["git","status","--porcelain"]),
    },
    "code_sha256": {
        "scripts/run_redis_trial.sh": sha256("scripts/run_redis_trial.sh"),
        "scripts/redis_producer.py": sha256("scripts/redis_producer.py"),
        "scripts/redis_consumer.py": sha256("scripts/redis_consumer.py"),
        "scripts/compute_tti.py": sha256("scripts/compute_tti.py"),
    },
}

out = Path(f"runs/{run_id}/meta.json")
out.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote meta: {out}")
PY

# clean slate for this run
redis-cli -h "$HOST" -p "$PORT" DEL "$STREAM" >/dev/null 2>&1 || true

echo "[1/4] starting consumer..."
python scripts/redis_consumer.py \
  ${REDIS_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" \
  --out "runs/$RUN_ID/consumer.csv" \
  --host "$HOST" --port "$PORT" \
  --stream "$STREAM" --group "$GROUP" \
  --idle-seconds 0 \
  > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

sleep 1

echo "[2/4] running producer..."
python scripts/redis_producer.py \
  ${REDIS_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" \
  --plan-csv "$PLAN_CSV" \
  --out "runs/$RUN_ID/producer.csv" \
  --host "$HOST" --port "$PORT" \
  --stream "$STREAM" \
  --speedup "$SPEEDUP" \
  --max-t-sim "$MAX_T_SIM" \
  > "runs/$RUN_ID/producer.log" 2>&1

echo "[3/4] waiting for consumer to finish..."
wait "$CONS_PID" || true

echo "[4/4] computing TTI..."
python scripts/compute_tti.py \
  --producer "runs/$RUN_ID/producer.csv" \
  --consumer "runs/$RUN_ID/consumer.csv" \
  --out "runs/$RUN_ID/tti_summary.json" \
  | tee "runs/$RUN_ID/tti_summary.printed.json"

echo "DONE. Outputs:"
ls -lh "runs/$RUN_ID"
