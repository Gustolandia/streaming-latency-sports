#!/usr/bin/env bash
set -euo pipefail

# Fix PATH to use Windows docker CLI which sees Docker Desktop containers
export PATH="/mnt/c/PROGRA~1/Docker/Docker/resources/bin:$PATH"

PLAN="${1:?combined_plan.csv path}"
REPS="${2:?n reps}"
SPEEDUP="${3:?speedup (e.g. 120)}"
MAX_T_SIM="${4:?max simulated seconds (e.g. 999999)}"
KAFKA_BOOTSTRAP="${5:?kafka bootstrap (e.g. localhost:9092)}"
REDIS_HOST="${6:?redis host (e.g. localhost)}"
REDIS_PORT="${7:?redis port (e.g. 6379)}"
PREFIX="${8:?run prefix (e.g. s2sf12)}"

ts() { date +"%Y%m%d_%H%M%S"; }

META_SNAP_DIR="docs/results/run_meta_${PREFIX}"
mkdir -p "$META_SNAP_DIR"

RUN_LIST="runs/_${PREFIX}_latest_runs.txt"
: > "$RUN_LIST"

for i in $(seq 1 "$REPS"); do
  KID="${PREFIX}_kafka_rep${i}_$(ts)"
  echo "=== [$i/$REPS] Kafka run: $KID"
  bash scripts/run_kafka_trial.sh "$KID" "$PLAN" "$SPEEDUP" "$MAX_T_SIM" "$KAFKA_BOOTSTRAP"
  cp -f "runs/$KID/meta.json" "$META_SNAP_DIR/${KID}_meta.json" 2>/dev/null || true
  echo "runs/$KID" >> "$RUN_LIST"
  sleep 2

  RID="${PREFIX}_redis_rep${i}_$(ts)"
  echo "=== [$i/$REPS] Redis run: $RID"
  # Use stream key = run id for uniqueness
  bash scripts/run_redis_trial.sh "$RID" "$PLAN" "$SPEEDUP" "$MAX_T_SIM" "$REDIS_HOST" "$REDIS_PORT" "$RID"
  cp -f "runs/$RID/meta.json" "$META_SNAP_DIR/${RID}_meta.json" 2>/dev/null || true
  echo "runs/$RID" >> "$RUN_LIST"
  sleep 2
done

echo "DONE. Run list: $RUN_LIST"
echo "DONE. Meta snapshots in: $META_SNAP_DIR"
