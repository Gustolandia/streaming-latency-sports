#!/usr/bin/env bash
# Reruns for the two hypotheses the first depth suite did not settle:
#
#   H2 (E-A-sat): the first E-A never reached saturation -- achieved utilisation topped out at
#     0.50 because the trial was taskset-pinned to 1-2 cores while util_sampler measured all 8,
#     and the M/G/1 knee lives near rho -> 1. This version removes the core restriction and
#     sweeps background load from idle to oversubscription so system utilisation sweeps 0 -> ~1,
#     with util_sampler now measuring the right denominator.
#
#   H3 (E-C): the first E-C broke instantly on a nested-quote --trace-loop argument. This drops
#     the trace (it was only a diagnostic) and compares the two Kafka stamping paths cleanly.
#
# Reuses the hardened trial wrapper from the successful resume: shell timeout per trial, reap
# before and after, never wait on stress-ng, set +e.
#
# Usage:  nohup bash cloud/campaigns/rerun_h2_h3.sh > rerun.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

# common.sh picks PLAN from `find data -name replay_plan.csv | head -1`, which now returns a
# SYNTHETIC uncompressed plan left under data/synthetic/ by the arrival campaign. Force a real
# 120x-compressed match plan so this rerun uses the same feed as the first depth suite. Without
# this the reruns would replay a constant-rate synthetic feed and not be comparable.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-3}"
MAXT="${MAXT:-180}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-400}"
NCORES=$(nproc)
mkdir -p "$OUT"/{ea_sat,ec2,trace}

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "reruns: speedup $SPEEDUP_RT, window ${MAXT}s, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -f "util_sampler.py" 2>/dev/null || true
  pkill -9 -x stress-ng 2>/dev/null || true
  sleep 2
}

# cores=0 means no taskset restriction (use all cores); otherwise pin to 0..cores-1.
run_at_load () {
  local tag="$1" cores="$2" bg="$3" n="$4" reps="${5:-$REPS}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  if [ "$bg" -gt 0 ]; then
    stress-ng --cpu "$bg" --timeout 900s >/dev/null 2>&1 &
    stress_pid=$!
    sleep 2
  fi
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local pin=(); [ "$cores" -gt 0 ] && pin=(taskset -c "0-$((cores-1))")
  local ceiling=$(( reps * 2 * (MAXT + 120) + 120 ))
  timeout -k 30 "$ceiling" \
    "${pin[@]}" python3 scripts/run_concurrency_test.py "$n" "$PLAN" "$reps" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$TRIAL_TIMEOUT" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null || true
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null || true
  printf 'tag,cores,bg_workers,n_feeds,reps\n%s,%s,%s,%s,%s\n' "$tag" "$cores" "$bg" "$n" "$reps" \
    > "$OUT/$tag/condition.csv"
  reap
}

# ---- H2: saturation sweep --------------------------------------------------
# No core restriction (cores=0). Background load 0..2xNCORES so system utilisation spans idle
# to oversubscribed. util_sampler's all-core reading is now the correct denominator.
for BG in 0 2 4 $NCORES $((NCORES + NCORES/2)) $((NCORES * 2)); do
  banner "E-A-sat bg=$BG (of $NCORES cores)"
  run_at_load "ea_sat/bg${BG}" 0 "$BG" 5
done

# ---- H3: symmetry / stamping comparison ------------------------------------
# callback = kafka_producer.py (async send-callback stamp); inline = confluent (poll-served).
# The Kafka-vs-Redis transport difference under each stamping path is the H3 quantity.
for MODE in callback inline; do
  banner "E-C2 stamping=$MODE"
  if [ "$MODE" = inline ]; then
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py
  else
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer.py
  fi
  run_at_load "ec2/${MODE}" 2 2 5
done
unset KAFKA_PRODUCER_SCRIPT

banner "RERUNS_COMPLETE"
