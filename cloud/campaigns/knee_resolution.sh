#!/usr/bin/env bash
# E-A4: resolve the knee. Referee issue M4.
#
# We withdrew the M/G/1 functional form because an exponential fits our data as well or better.
# That withdrawal is honest but it is a statement about our SAMPLING, not about the mechanism: the
# two forms are nearly indistinguishable below rho = 0.9 and diverge sharply above it, and we have
# no points there. Our pre-saturation ladder stops at 0.878, and every heavier load collapses onto
# a degenerate rho = 1.000 because whole-core stressors saturate the measured utilisation.
#
# Normalised at our last usable point, the predictions separate like this:
#
#     rho     M/G/1 rho/(1-rho)   exponential     ratio
#     0.90        1.25x              1.11x         1.1
#     0.95        2.64x              1.40x         1.9
#     0.98        6.81x              1.62x         4.2
#     0.99       13.76x              1.69x         8.1
#
# An eight-fold gap is decisive if we can put points in it. The obstacle was never the physics but
# the load generator: `stress-ng --cpu N` runs flat out, so the smallest step it can take near the
# top is enormous. `--cpu-load P` runs a duty cycle instead, which buys the fine control we need
# to place conditions between 0.88 and 0.99.
#
# We do NOT assume the requested load equals the achieved rho. util_sampler records the achieved
# value and the fit uses that; the duty-cycle percentages below are only a means of spreading the
# conditions across the interesting interval.
#
# Pre-registered decision rule, stated before the run:
#   * If, with these points included, the M/G/1 form beats BOTH fitted alternatives (power law and
#     exponential), the functional form is restored -- and we say it was restored by measurement
#     after having been withdrawn, not that it was right all along.
#   * If an alternative still wins or the margin is within noise, the withdrawal stands and we
#     report that the knee's shape is not resolvable even with points placed where the forms
#     disagree most. That is the more interesting negative and it closes the question.
#
# Usage:  nohup bash cloud/campaigns/knee_resolution.sh > knee.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea4}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "knee resolution: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -f "util_sampler.py" 2>/dev/null || true
  pkill -9 -x stress-ng 2>/dev/null || true
  sleep 2
}

# Duty-cycle percentages chosen to spread the ACHIEVED rho across roughly 0.88-0.99. The mapping
# from requested load to achieved rho is not linear and not assumed; it is measured.
run_at_duty () {
  local pct="$1"
  local tag="l${pct}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  # All cores, partial duty: this is what buys resolution near saturation.
  stress-ng --cpu "$NCORES" --cpu-load "$pct" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null || true
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null || true
  printf 'tag,requested_cpu_load_pct,n_feeds,reps,max_t_sim\n%s,%s,5,%s,%s\n' \
    "$tag" "$pct" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  reap
}

# Dense where the forms disagree, with two lower anchors to tie the new ladder to the old one.
for PCT in 70 80 88 92 95 97 99; do
  banner "E-A4 cpu-load=${PCT}% (of ${NCORES} cores)"
  run_at_duty "$PCT"
done

banner "KNEE_RESOLUTION_COMPLETE"
