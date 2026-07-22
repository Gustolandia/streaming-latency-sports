#!/usr/bin/env bash
# M1: is the ~103 ms producer scheduling lag a property of Kafka, or of kafka-python?
#
# At true real-time replay the multi-host testbed shows Kafka end-to-end TTI ~105 ms, of which
# ~103 ms is scheduling lag -- the interval between an event's planned emission and the producer
# issuing the send. The same code at 10x replay shows 0.2-1 ms. The manuscript could not say
# whether that constant belongs to the broker, the client library, or our replay loop, which
# left its headline recommendation resting on an unexplained number.
#
# This campaign settles it two ways at once:
#   (a) the same experiment against a second, independently implemented client
#       (confluent-kafka / librdkafka) at equivalent settings;
#   (b) --trace-loop on both, which splits scheduling lag into "the sleep returned late" and
#       "the send call blocked".
#
# Redis is run alongside as the unchanged reference arm.
#
# Usage:  bash cloud/campaigns/m1_client_ab.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

REPS="${REPS:-6}"
LEVELS="${LEVELS:-1 9}"
TRACE_DIR="${TRACE_DIR:-docs/results/m1_client}"
mkdir -p "$TRACE_DIR"

python3 -c "import confluent_kafka; print('confluent-kafka', confluent_kafka.version())" \
  || { echo "confluent-kafka not installed: pip3 install confluent-kafka"; exit 1; }

# Manipulation check: the swap must actually take effect. Without this we would be comparing
# kafka-python against itself and reporting a null. This project has produced exactly that
# failure before, from an option that was silently dropped.
if KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py \
   python3 scripts/kafka_producer_confluent.py --run-id x --plan-csv /dev/null \
     --out /tmp/x.csv --definitely-bad 2>&1 | grep -q "unrecognized arguments: --definitely-bad"; then
  echo "MANIPULATION_CHECK_OK: confluent producer parses its own CLI"
else
  echo "MANIPULATION_CHECK_FAILED - aborting"; exit 1
fi

for N in $LEVELS; do
  for CLIENT in kafka-python confluent; do
    if [ "$CLIENT" = confluent ]; then
      export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py
    else
      export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer.py
    fi
    banner "M1 N=$N client=$CLIENT reps=$REPS"
    # --speedup 1 is the regime the anomaly lives in; --max-t-sim 600 keeps a run to ten
    # minutes of match clock so the whole sweep fits comfortably inside the trial credit.
    python3 scripts/run_concurrency_test.py "$N" "$PLAN" "$REPS" \
      --speedup 1 --max-t-sim 600 \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $TRACE_DIR/trace_${CLIENT}_n${N}.csv" \
      --out-dir "$TRACE_DIR/results" \
      --trial-timeout 1800 2>&1 | tail -4
  done
done
unset KAFKA_PRODUCER_SCRIPT
banner "M1_COMPLETE"
