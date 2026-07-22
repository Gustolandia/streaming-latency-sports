#!/usr/bin/env bash
# E1: concurrency sweep, each feed carrying a DISTINCT real match at its true event rate.
# Reps chosen so single-feed cells are powered (18) while N=5/10 reach 15/30 runs per backend.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
for spec in "1 18" "5 3" "10 3"; do
  set -- $spec; N=$1; REPS=$2
  banner "concurrency N=$N reps=$REPS"
  python3 scripts/run_concurrency_test.py "$N" "$PLAN" "$REPS" \
    --speedup 10 --max-t-sim 600 \
    --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
    --plans-dir "$PLANS_DIR" --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" \
    --trial-timeout 900 2>&1 | tail -4
done
banner "CONCURRENCY_COMPLETE"
