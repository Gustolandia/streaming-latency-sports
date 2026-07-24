#!/usr/bin/env bash
# E-A3: the collapse suite. A dense utilisation sweep with enough replication to test H9
# (scale-family collapse), H10 (mixture structure) and the between-campaign F-Delta
# reproduction, all pre-registered in docs/preregistration_depth.md BEFORE this ran.
#
# Why a fresh campaign when ea_sat/ea_knee exist: the pilot analyses that motivated H9/H10 were
# run on that corpus, so it cannot also be the test. This campaign is the out-of-sample data,
# and its matched-rho agreement with the old corpus is itself the non-circular F-Delta test.
#
# Design (pre-registered): N=5 distinct real matches, true real-time rate derived from the plan,
# 180 s window, 5 replicates, bg in {0,2,4,5,6,7,8,10,12} workers on 8 cores, no pinning,
# util_sampler recording achieved rho, raw per-event data retained.
#
# Reuses the hardened trial pattern that survived the depth suite: shell timeout per trial,
# reap before/after, never `wait` on stress-ng, set +e throughout.
#
# Usage:  nohup bash cloud/campaigns/collapse_suite.sh > collapse.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

# Pin a real 120x-compressed match plan; `find data` would otherwise pick up synthetic
# uncompressed plans left by the arrival campaign.
PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-400}"
NCORES=$(nproc)
mkdir -p "$OUT/ea3"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "collapse suite: speedup $SPEEDUP_RT, window ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  pkill -f "util_sampler.py" 2>/dev/null || true
  pkill -9 -x stress-ng 2>/dev/null || true
  sleep 2
}

run_at_load () {
  local bg="$1"
  local tag="ea3/bg${bg}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  if [ "$bg" -gt 0 ]; then
    stress-ng --cpu "$bg" --timeout 3600s >/dev/null 2>&1 &
    stress_pid=$!
    sleep 2
  fi
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 120 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$TRIAL_TIMEOUT" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null || true
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null || true
  printf 'tag,bg_workers,n_feeds,reps,max_t_sim\n%s,%s,5,%s,%s\n' \
    "$tag" "$bg" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  reap
}

# Pre-knee (0,2,4), knee (5,6,7), saturation (8,10,12) on 8 cores.
for BG in 0 2 4 5 6 7 8 10 12; do
  banner "E-A3 bg=$BG (of $NCORES cores)"
  run_at_load "$BG"
done

banner "COLLAPSE_SUITE_COMPLETE"
