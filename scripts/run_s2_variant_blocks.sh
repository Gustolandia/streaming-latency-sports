#!/usr/bin/env bash
set -euo pipefail

PLAN="${1:?combined_plan.csv path}"
REPS="${2:?n reps}"
SPEEDUP="${3:?speedup (e.g. 120)}"
MAX_T_SIM="${4:?max simulated seconds (e.g. 999999)}"
KAFKA_BOOTSTRAP="${5:?kafka bootstrap (e.g. localhost:9092)}"
REDIS_HOST="${6:?redis host (e.g. localhost)}"
REDIS_PORT="${7:?redis port (e.g. 6379)}"
RUN_PREFIX="${8:-s2full}"

ts() { date +"%Y%m%d_%H%M%S"; }

# Reviewer-proof: keep copies of the per-run meta.json outside runs/
META_DIR="docs/results/run_meta_${RUN_PREFIX}"
mkdir -p "$META_DIR"

for i in $(seq 1 "$REPS"); do
  KID="${RUN_PREFIX}_kafka_rep${i}_$(ts)"
  echo "=== [$i/$REPS] Kafka run: $KID"
  bash scripts/run_kafka_trial.sh "$KID" "$PLAN" "$SPEEDUP" "$MAX_T_SIM" "$KAFKA_BOOTSTRAP"
  test -f "runs/$KID/meta.json" && cp -f "runs/$KID/meta.json" "$META_DIR/${KID}_meta.json" || true
  sleep 2

  RID="${RUN_PREFIX}_redis_rep${i}_$(ts)"
  echo "=== [$i/$REPS] Redis run: $RID"
  # Use stream key = run id for uniqueness
  bash scripts/run_redis_trial.sh "$RID" "$PLAN" "$SPEEDUP" "$MAX_T_SIM" "$REDIS_HOST" "$REDIS_PORT" "$RID"
  test -f "runs/$RID/meta.json" && cp -f "runs/$RID/meta.json" "$META_DIR/${RID}_meta.json" || true
  sleep 2
done

echo "DONE. Meta snapshots in: $META_DIR"
