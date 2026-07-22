#!/usr/bin/env bash
# E4b: the acknowledgement-batching intervention, both arms, under injected delay.
#
# MANIPULATION CHECK FIRST. This treatment silently failed to apply three times in this
# project - twice via shell quoting, once via an unmatched edit - and each time produced a
# null indistinguishable from a genuine refutation. The consumer also logs its effective
# ack_batch to consumer.log, so the arm is recoverable from run artefacts alone.
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if python3 scripts/redis_consumer.py --run-id x --out /tmp/x.csv \
     --ack-batch 200 --definitely-bad 2>&1 | grep -q "unrecognized arguments: --definitely-bad"; then
  echo "MANIPULATION_CHECK_OK: --ack-batch accepted, bad flag rejected"
else
  echo "MANIPULATION_CHECK_FAILED - aborting rather than reporting an unapplied treatment"; exit 1
fi

for D in ${DELAYS_MS:-20 50}; do
  for ARM in unbatched batched; do
    EXTRA=(); [ "$ARM" = batched ] && EXTRA=(--redis-consumer-extra "--ack-batch 200")
    netem "$D"
    banner "p4 delay=${D}ms arm=$ARM"
    python3 scripts/run_concurrency_test.py 5 "$PLAN" 3 \
      --speedup 10 --max-t-sim 600 \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" \
      "${EXTRA[@]}" --trial-timeout 1800 2>&1 | tail -3
  done
done
netem 0
banner "P4_COMPLETE"
