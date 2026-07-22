#!/usr/bin/env bash
# E2: vary CONNECTION COUNT at a realistic per-feed event rate.
# speedup 1/120 cancels the factor baked into the plans, giving true real-time arrival;
# max-t-sim bounds wall time so every level is comparable and N is the only variable.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
for N in ${CONN_LEVELS:-10 25 50 100}; do
  banner "connections N=$N"
  timeout "${LEVEL_TIMEOUT:-2400}" python3 scripts/run_concurrency_test.py "$N" "$PLAN" 1 \
    --speedup 0.008333 --max-t-sim 3 \
    --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
    --plans-dir "$PLANS_DIR" --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" \
    --trial-timeout 2000 2>&1 | tail -3
done
banner "CONNSWEEP_COMPLETE"
