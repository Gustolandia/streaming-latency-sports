#!/usr/bin/env bash
# E-W: is the paper's ~103 ms Kafka producer offset a per-event constant, or a one-time
# startup cost that a short window mistakes for one?
#
# The E1 corpus behind the paper's headline matched a MEDIAN OF 7 EVENTS PER RUN (745 events
# across 100 Kafka runs). Those events are the match's opening burst, all scheduled at t_sim=0
# and sent immediately after producer start. Kafka's first send blocks on metadata fetch and
# topic auto-creation; Redis's XADD to a new stream does not. With 7 events, that one-time cost
# IS the median -- which is why E1 reads 103 ms for Kafka and 1.75 ms for Redis on the very same
# events. A later run at a 180 s window (148 events) put the median at 1.6 ms with a 103.5 ms
# MAXIMUM: the same cost, paid once.
#
# This sweeps only the window length, holding everything else fixed. If the startup-artefact
# account is right, Kafka's median scheduling lag must FALL as the window grows and more
# steady-state events dilute the one-time cost, while Redis's stays flat and low:
#
#   60 s   ~7 events    -> Kafka median near 103 ms  (reproduces E1)
#   180 s  ~150 events  -> Kafka median near 1.5 ms  (reproduces M1)
#   600 s  ~500 events  -> Kafka median lower still
#
# If instead the median stays near 103 ms at every window, the offset is a genuine per-event
# constant and the paper's original claim stands.
#
# Usage:  nohup bash cloud/campaigns/window_sweep.sh > window.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e
set +o pipefail

# The arrival campaign left synthetic uncompressed plans under data/synthetic that shadow the
# real ones in common.sh's `find data`. Pin a real 120x-compressed match plan.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found}"

OUT="${OUT:-docs/results/window}"
REPS="${REPS:-3}"
WINDOWS="${WINDOWS:-60 180 600}"
mkdir -p "$OUT"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "window sweep: speedup $SPEEDUP_RT (true real time), windows: $WINDOWS"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -f "util_sampler.py" 2>/dev/null || true
  sleep 2
}

for W in $WINDOWS; do
  banner "E-W window=${W}s"
  reap
  # Ceiling scales with the window: reps x 2 backends x (window + startup slack).
  CEIL=$(( REPS * 2 * (W + 150) + 180 ))
  timeout -k 30 "$CEIL" \
    python3 scripts/run_concurrency_test.py 1 "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$W" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $OUT/trace_w${W}.csv" \
      --out-dir "$OUT/w${W}" --trial-timeout $(( W + 400 )) 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: window ${W}s hit its ceiling (${CEIL}s)"
  printf 'window_s,reps\n%s,%s\n' "$W" "$REPS" > "$OUT/w${W}/condition.csv"
  reap
done

banner "WINDOW_SWEEP_COMPLETE"
