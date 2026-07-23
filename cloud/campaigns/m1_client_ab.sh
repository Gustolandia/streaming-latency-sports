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
# common.sh sets `set -euo pipefail`. Turn both off: a single failing trial must not abort the
# campaign, and -- the bug that silently killed this whole campaign in the resume -- pipefail
# made the manipulation check below inherit the exit 2 of `python --definitely-bad` even though
# grep matched, so the check falsely reported failure and M1 produced no data.
set +e
set +o pipefail

REPS="${REPS:-6}"
LEVELS="${LEVELS:-1 9}"
TRACE_DIR="${TRACE_DIR:-docs/results/m1_client}"
MAXT="${MAXT:-180}"
mkdir -p "$TRACE_DIR/results" "$TRACE_DIR/trace"

# common.sh's PLAN comes from `find data`, which now returns a synthetic uncompressed plan left
# by the arrival campaign. Force a real 120x-compressed match plan.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found}"

python3 -c "import confluent_kafka; print('confluent-kafka', confluent_kafka.version())" \
  || { echo "confluent-kafka not installed: pip3 install confluent-kafka"; exit 1; }

# Manipulation check, capture-then-grep so the failing python exit code (argparse returns 2 for
# the deliberately-bad flag) cannot be mistaken for the check failing.
CHECK=$(KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py \
        python3 scripts/kafka_producer_confluent.py --run-id x --plan-csv /dev/null \
          --out /tmp/x.csv --definitely-bad 2>&1)
if echo "$CHECK" | grep -q "unrecognized arguments: --definitely-bad"; then
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
    # The anomaly lives in the TRUE real-time regime, which is the whole point of this
    # campaign. Derived, not hard-coded: --speedup 1 would replay at 120x and measure
    # the accelerated regime instead -- the exact mistake that cost the first attempt.
    SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
    python3 scripts/run_concurrency_test.py "$N" "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $TRACE_DIR/trace_${CLIENT}_n${N}.csv" \
      --out-dir "$TRACE_DIR/results" \
      --trial-timeout 1800 2>&1 | tail -4
  done
done
unset KAFKA_PRODUCER_SCRIPT
banner "M1_COMPLETE"
