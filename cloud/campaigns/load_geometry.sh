#!/usr/bin/env bash
# E-A6: does WHERE the load sits change the inversion rate at equal utilisation?
#
# E-A5 showed the rate follows stamping-thread occupancy, not utilisation. If that is right,
# utilisation cannot be the variable, and two loads with the SAME rho should give different rates
# whenever they differ in how easily the stamping thread can find a core.
#
# There are two natural geometries and we already have accidental evidence they differ:
#
#   CONCENTRATED  `stress-ng --cpu k`            k cores flat out, C-k cores genuinely FREE
#   SPREAD        `stress-ng --cpu C --cpu-load P`  every core busy a fraction P of the time,
#                                                  so no core is ever free, only briefly idle
#
# Pooling the old whole-core ladder with the new duty-cycle one, spread load at rho = 0.703
# inverted MORE (0.111) than concentrated load at rho = 0.753 (0.069-0.076) -- a higher rate at a
# lower utilisation. But those are different campaigns on different days, so the comparison is
# confounded by everything that changed between them. This campaign runs both geometries in one
# campaign, interleaved, at matched utilisation.
#
# WHY THE LEVELS ARE WHAT THEY ARE. Concentrated load can only reach rho = k/C, so on 8 cores it
# is quantised to 0.625, 0.750, 0.875. Spread load is continuous, so it is set to those same
# three values rather than to round numbers. Matching the achieved rho is the entire experiment;
# choosing convenient targets and letting rho differ would destroy it.
#
# PRE-REGISTERED PREDICTIONS, fixed before the run:
#   * At 0.625 and 0.750, SPREAD inverts more than CONCENTRATED -- by at least 1.5x, because
#     concentrated load leaves 3 and 2 cores free respectively while spread leaves none.
#   * At 0.875 the two CONVERGE (within 1.5x), because one free core out of eight is nearly as
#     bad as none.
#   * If instead the two geometries agree at every level, utilisation IS the variable after all,
#     and E-A5's result would need a different explanation. That outcome is reportable and would
#     be reported.
#
# MANIPULATION CHECK. The comparison means nothing unless the achieved rho really matches across
# geometries. util_sampler records it in every cell and the analysis withholds any level whose
# two arms differ by more than 3 percentage points.
#
# Usage:  nohup bash cloud/campaigns/load_geometry.sh > load_geometry.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea6}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

[ "$NCORES" -ge 8 ] || { echo "FATAL: $NCORES cores; the k/C levels assume 8"; exit 1; }

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "load geometry: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}

# $1 = level tag (k value), $2 = geometry, $3.. = stress-ng args
run_cell () {
  local k="$1" geom="$2"; shift 2
  local tag="k${k}_${geom}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  stress-ng "$@" --timeout 3600s >/dev/null 2>&1 &
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

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  printf 'tag,k_cores,geometry,target_rho,n_feeds,reps,max_t_sim\n%s,%s,%s,%s,5,%s,%s\n' \
    "$tag" "$k" "$geom" "$(python3 -c "print($k/$NCORES)")" "$REPS" "$MAXT" \
    > "$OUT/$tag/condition.csv"
  reap
}

# Interleaved by level, so drift over the campaign hits both geometries rather than being
# confounded with the geometry itself.
for K in 5 6 7; do
  PCT=$(python3 -c "print(round(100*$K/$NCORES))")
  banner "E-A6 k=${K}/${NCORES} CONCENTRATED (${K} cores flat out, $((NCORES-K)) free)"
  run_cell "$K" "conc" --cpu "$K"
  banner "E-A6 k=${K}/${NCORES} SPREAD (all ${NCORES} cores at ${PCT}% duty)"
  run_cell "$K" "spread" --cpu "$NCORES" --cpu-load "$PCT"
done

banner "LOAD_GEOMETRY_COMPLETE"
