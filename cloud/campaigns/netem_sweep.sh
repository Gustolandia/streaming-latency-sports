#!/usr/bin/env bash
# E4: injected one-way delay at the broker NIC, on a genuine inter-VM path.
# netem.sh sets a large queue limit deliberately: at the default 1000 packets the shaper
# itself drops and TCP backoff dominates, which is an artefact rather than a network effect.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
for D in ${DELAYS_MS:-0 5 20 50}; do
  netem "$D"
  banner "netem delay=${D}ms"
  python3 scripts/run_concurrency_test.py 5 "$PLAN" 3 \
    --speedup 10 --max-t-sim 600 \
    --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
    --plans-dir "$PLANS_DIR" --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" \
    --trial-timeout 1800 2>&1 | tail -3
done
netem 0
banner "NETEM_COMPLETE"
