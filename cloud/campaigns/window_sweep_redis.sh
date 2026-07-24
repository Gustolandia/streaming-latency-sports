#!/usr/bin/env bash
# Window sweep, Redis arm, with the loop trace enabled.
#
# Why this is a separate campaign. The first window sweep passed --trace-loop to the Kafka
# producer only, because redis_producer.py had no such flag and run_concurrency_test.py had no
# --redis-producer-extra to carry one. The analysis then defaulted the missing Redis counts to
# zero, and the first draft of the paper's table duly reported "Redis: 0 events >50 ms late,
# 0 blocking sends" -- which was not a measurement, it was the absence of one.
#
# In a paper whose subject is that asymmetric instrumentation manufactures between-system
# differences, reporting a two-arm comparison instrumented on one arm is not acceptable. Both
# producers now write the same trace schema, so this re-runs the Redis arm at all three windows
# and the counts for both systems come from the same instrument.
#
# Kafka is re-run too rather than reusing the earlier files: the two arms must come from the
# same campaign, or a reader has to take on trust that nothing about the host changed between.
#
# Usage:  nohup bash cloud/campaigns/window_sweep_redis.sh > window_redis.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/window2}"
REPS="${REPS:-3}"
NCORES=$(nproc)
mkdir -p "$OUT"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi

# Manipulation check before spending an hour: both producers must accept --trace-loop, and the
# orchestrator must carry it to the Redis arm. pipefail off -- a deliberately-failing command's
# status propagating through a pipe is what silently aborted M1 in zero seconds.
set +o pipefail
for s in scripts/kafka_producer.py scripts/redis_producer.py; do
  python3 "$s" --help 2>&1 | grep -q -- "--trace-loop" || { echo "FATAL: $s lacks --trace-loop"; exit 1; }
done
python3 scripts/run_concurrency_test.py --help 2>&1 | grep -q -- "--redis-producer-extra" \
  || { echo "FATAL: orchestrator lacks --redis-producer-extra"; exit 1; }
echo "manipulation check OK: both producers traceable, orchestrator carries it to both arms"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "window sweep (both arms traced): speedup $SPEEDUP_RT, ${REPS} reps"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  sleep 2
}

for W in 60 180 600; do
  banner "window ${W}s"
  reap
  mkdir -p "$OUT/w${W}"
  ceiling=$(( REPS * 2 * (W + 120) + 180 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 1 "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$W" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $OUT/trace_w${W}.csv" \
      --redis-producer-extra "--trace-loop $OUT/trace_w${W}.csv" \
      --out-dir "$OUT/w${W}" --trial-timeout $(( W + 400 )) 2>&1 | tail -3
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: w${W} hit shell timeout (${ceiling}s)"
  printf 'window_s,reps,traced\n%s,%s,both\n' "$W" "$REPS" > "$OUT/w${W}/condition.csv"
  reap
done

banner "WINDOW_SWEEP_BOTH_ARMS_COMPLETE"
