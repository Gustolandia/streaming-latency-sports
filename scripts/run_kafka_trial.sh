#!/usr/bin/env bash
set -euo pipefail

# Fix PATH to use Docker Desktop's Linux-compatible docker script
export PATH="/mnt/c/Program Files/Docker/Docker/resources/bin:$PATH"

# Usage:
#   scripts/run_kafka_trial.sh <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] [BOOTSTRAP] [TOPIC]
RUN_ID="${1:?run_id required}"
PLAN_CSV="${2:?plan_csv required}"
SPEEDUP="${3:-120}"
MAX_T_SIM="${4:-600}"
BOOTSTRAP="${5:-localhost:9092}"
TOPIC="${6:-sb-events-$RUN_ID}"

mkdir -p "runs/$RUN_ID"

# Write per-run provenance (reviewer-proof)
python - "$RUN_ID" "$PLAN_CSV" "$SPEEDUP" "$MAX_T_SIM" "$BOOTSTRAP" "$TOPIC" <<'PY'
import json, os, sys, hashlib, subprocess
from pathlib import Path
run_id, plan_csv, speedup, max_t_sim, bootstrap, topic = sys.argv[1:7]

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
    "backend": "kafka",
    "plan_csv": plan_csv,
    "speedup": float(speedup),
    "max_t_sim": int(max_t_sim),
    "bootstrap": bootstrap,
    "topic": topic,
    "env": {
        "KAFKA_PRODUCER_OPTS": os.environ.get("KAFKA_PRODUCER_OPTS", ""),
        "KAFKA_CONSUMER_OPTS": os.environ.get("KAFKA_CONSUMER_OPTS", ""),
    },
    "git": {
        "head": cmd(["git","rev-parse","HEAD"]),
        "status_short": cmd(["git","status","--porcelain"]),
    },
    "code_sha256": {
        "scripts/run_kafka_trial.sh": sha256("scripts/run_kafka_trial.sh"),
        "scripts/kafka_producer.py": sha256("scripts/kafka_producer.py"),
        "scripts/kafka_consumer.py": sha256("scripts/kafka_consumer.py"),
        "scripts/compute_tti.py": sha256("scripts/compute_tti.py"),
    },
}

out = Path(f"runs/{run_id}/meta.json")
out.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
print(f"Wrote meta: {out}")
PY

echo "[0/4] ensuring topic exists: $TOPIC"
cmd.exe /c docker exec -w /opt/kafka/bin broker sh -lc "./kafka-topics.sh --bootstrap-server broker:29092 --create --if-not-exists --topic $TOPIC --partitions 3 --replication-factor 1" >/dev/null 2>&1

echo "[1/4] starting consumer..."
python scripts/kafka_consumer.py \
  ${KAFKA_CONSUMER_OPTS:-} \
  --run-id "$RUN_ID" \
  --out "runs/$RUN_ID/consumer.csv" \
  --bootstrap "$BOOTSTRAP" \
  --topic "$TOPIC" \
  --idle-seconds 0 \
  > "runs/$RUN_ID/consumer.log" 2>&1 &
CONS_PID=$!

sleep 2

echo "[2/4] running producer..."
python scripts/kafka_producer.py \
  ${KAFKA_PRODUCER_OPTS:-} \
  --run-id "$RUN_ID" \
  --plan-csv "$PLAN_CSV" \
  --out "runs/$RUN_ID/producer.csv" \
  --bootstrap "$BOOTSTRAP" \
  --topic "$TOPIC" \
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
