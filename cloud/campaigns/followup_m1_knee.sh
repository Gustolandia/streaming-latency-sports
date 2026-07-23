#!/usr/bin/env bash
# Follow-up: (1) M1 client attribution, (2) the H2 knee-fill.
#
# M1 first: it failed silently in the resume (pipefail defeated its manipulation check) and is
# the experiment that decides whether the paper's ~103 ms producer offset belongs to Kafka or
# to kafka-python. Section 7.2 currently says "inferred, comparison in progress".
#
# Then E-A-knee: the saturation sweep confirmed H2's *relationship* (spearman 0.941, inversion
# rising from 0.007 at idle to ~0.24 at saturation) but could not test its *functional form*.
# fit_mg1 excludes rho >= 1 because M/G/1 waiting is infinite there, so the three saturated
# points drop out and only three pre-knee points remain -- where M/G/1 and a straight line are
# indistinguishable (R^2 0.609 vs 0.610). This fills 0.5 < rho < 1, the region where the two
# forms actually differ, with bg = 5,6,7 on 8 cores.
#
# Usage:  nohup bash cloud/campaigns/followup_m1_knee.sh > followup.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e
set +o pipefail

# The arrival campaign left synthetic uncompressed plans under data/synthetic that shadow the
# real ones in common.sh's `find data`. Pin a real 120x-compressed match plan.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found}"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-3}"
MAXT="${MAXT:-180}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-400}"
NCORES=$(nproc)
mkdir -p "$OUT/ea_knee"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "follow-up: speedup $SPEEDUP_RT, window ${MAXT}s, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -f "util_sampler.py" 2>/dev/null || true
  pkill -9 -x stress-ng 2>/dev/null || true
  sleep 2
}

run_at_load () {
  local tag="$1" bg="$2" n="$3" reps="${4:-$REPS}"
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

  local ceiling=$(( reps * 2 * (MAXT + 120) + 120 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py "$n" "$PLAN" "$reps" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
      --out-dir "$OUT/$tag" --trial-timeout "$TRIAL_TIMEOUT" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null || true
  # Never wait on stress-ng: a missed graceful kill blocks for its whole timeout.
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null || true
  printf 'tag,bg_workers,n_feeds,reps\n%s,%s,%s,%s\n' "$tag" "$bg" "$n" "$reps" \
    > "$OUT/$tag/condition.csv"
  reap
}

# ---- 1. M1 client attribution (N=1, the regime the offset lives in) --------
banner "1/2 M1 CLIENT A/B"
LEVELS="1" REPS=6 bash cloud/campaigns/m1_client_ab.sh
banner "M1_DONE"

# ---- 2. H2 knee-fill: populate 0.5 < rho < 1 -------------------------------
# bg 5,6,7 of 8 cores targets roughly rho 0.62, 0.75, 0.87 -- the region where M/G/1's
# rho/(1-rho) curvature separates it from a straight line.
for BG in 5 6 7; do
  banner "E-A-knee bg=$BG (of $NCORES cores)"
  run_at_load "ea_knee/bg${BG}" "$BG" 5
done

banner "FOLLOWUP_COMPLETE"
