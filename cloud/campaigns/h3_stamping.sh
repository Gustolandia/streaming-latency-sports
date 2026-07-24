#!/usr/bin/env bash
# H3, the asymmetry rule -- the test the first two attempts never actually ran.
#
# H3 says that comparing two systems whose acknowledgement timestamps are taken in different
# execution contexts biases the comparison, because one system's stamp pays a thread-scheduling
# delay the other's does not. Concretely:
#
#   redis_producer.py   t_broker_ack_ns = now_ns() on the CALLING thread, immediately after the
#                       blocking XADD returns. No second thread in the path.
#   kafka_producer.py   t_broker_ack_ns is taken in the delivery CALLBACK, which runs on the
#                       client's I/O thread and therefore waits to be scheduled.
#
# So every Kafka-vs-Redis transport comparison in this paper is partly a comparison of two
# instruments. H3 predicts the between-system gap SHRINKS once both stamp the same way.
#
# The earlier E-C and E-C2 attempts compared kafka-python against confluent-kafka. Both stamp in
# callbacks, so they were two asymmetric implementations and the symmetric condition was never
# created -- which is why the manuscript reports H3 as untested rather than refuted. This
# campaign creates it, using --ack-stamp inline (added to kafka_producer.py for exactly this
# purpose), which stamps on the calling thread the moment the send future resolves.
#
# Design:
#   arm A  kafka --ack-stamp callback  vs redis     the asymmetric comparison (status quo)
#   arm B  kafka --ack-stamp inline    vs redis     the symmetric comparison
# Everything else is held fixed, including --max-inflight 1 in BOTH arms: inline stamping
# requires it, so the callback arm must use it too or the arms differ in two ways at once.
#
# H3 quantity: d = median(kafka transport) - median(redis transport), per arm.
# Supported if |d_inline| < |d_callback|.
#
# Usage:  nohup bash cloud/campaigns/h3_stamping.sh > h3.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

# Pin to a real 120x-compressed match plan; `find data` would otherwise pick up the synthetic
# uncompressed plans the arrival campaign left behind.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-400}"
NCORES=$(nproc)
mkdir -p "$OUT/ec3"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi

# Manipulation check: the flag must actually exist and must actually refuse the unsafe
# combination. Run it before spending an hour on trials. pipefail is off here on purpose --
# an earlier campaign aborted silently in 0 s because a deliberately-failing command's exit
# status propagated through a pipe.
set +o pipefail
CHECK=$(python3 scripts/kafka_producer.py --help 2>&1)
echo "$CHECK" | grep -q -- "--ack-stamp" || { echo "FATAL: --ack-stamp not present"; exit 1; }
REFUSE=$(python3 scripts/kafka_producer.py --run-id x --plan-csv "$PLAN" --out /dev/null \
           --ack-stamp inline --max-inflight 8 2>&1)
echo "$REFUSE" | grep -q "requires --max-inflight 1" || {
  echo "FATAL: --ack-stamp inline did not refuse --max-inflight 8"; exit 1; }
echo "manipulation check OK: flag present and guard fires"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "H3 stamping: speedup $SPEEDUP_RT, window ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -9 -x stress-ng 2>/dev/null || true
  sleep 2
}

# Both arms run under identical load so the only difference is where the stamp is taken. A
# little background load is deliberate: the effect H3 predicts is a thread-scheduling delay, so
# an idle machine is the condition least likely to show it.
run_arm () {
  local mode="$1"
  local tag="ec3/$mode"
  mkdir -p "$OUT/$tag"
  reap
  stress-ng --cpu 2 --timeout 1800s >/dev/null 2>&1 &
  local stress_pid=$!
  sleep 2

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 120 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 2 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" \
        --kafka-producer-extra "--max-inflight 1 --ack-stamp $mode" \
        --out-dir "$OUT/$tag" --trial-timeout "$TRIAL_TIMEOUT" 2>&1 | tail -3
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null || true
  printf 'tag,ack_stamp,max_inflight,n_feeds,reps,bg_workers\n%s,%s,1,2,%s,2\n' \
    "$tag" "$mode" "$REPS" > "$OUT/$tag/condition.csv"
  reap
}

for MODE in callback inline; do
  banner "E-C3 ack-stamp=$MODE"
  run_arm "$MODE"
done

banner "H3_STAMPING_COMPLETE"
