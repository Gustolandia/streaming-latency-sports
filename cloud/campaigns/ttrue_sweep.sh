#!/usr/bin/env bash
# E-A10: move T_true and watch the inversion rate move the other way.
#
# The mechanism now reads P(inversion) = P(scheduling stall > T_true). Everything measured so far
# has moved the LEFT side -- load, scheduling priority, load geometry. This campaign moves the
# RIGHT side, which no experiment here has done, and it is the only manipulation that acts on
# T_true without touching the scheduler at all.
#
# Padding the payload lengthens the true transport: more bytes to serialise, send, and read back.
# Same hosts, same load, same code path, same scheduler behaviour -- only the message size
# differs. If the mechanism is right, that alone must lower the inversion rate.
#
# THE PREDICTION IS COUNTER-INTUITIVE, WHICH IS WHY IT IS WORTH RUNNING. Bigger messages make the
# system slower and the inversion rate FALL. Any account in which inversions track how stressed
# the system is predicts the opposite, because larger payloads mean more work per event. An
# account in which inversions are a measurement artefact -- a stall outrunning a short interval
# -- predicts what we predict. The two differ in SIGN, not in magnitude, and sign is hard to get
# by accident.
#
# Pre-registered, before the run:
#   * median transport RISES monotonically with pad size. If it does not, padding failed to move
#     T_true and nothing below is interpretable; the campaign reports that and stops there.
#   * the inversion rate FALLS as pad size rises, at fixed load.
#   * quantitatively: the inversion rate at pad size b should track the stall distribution
#     measured in E-A9 evaluated at the corresponding T_true. That is a parameter-free
#     prediction once E-A9's histogram is in hand, and it can fail.
#
# CONFOUND, NAMED IN ADVANCE. Larger payloads cost more CPU to serialise, so they raise load
# slightly -- which pushes the inversion rate UP, against the predicted direction. That makes the
# test conservative rather than generous: a confound working against the prediction cannot
# manufacture it. Utilisation is recorded per cell so the size of that effect is visible.
#
# Usage:  nohup bash cloud/campaigns/ttrue_sweep.sh > ttrue_sweep.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea10}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
LOAD_PCT="${LOAD_PCT:-88}"
NCORES=$(nproc)
mkdir -p "$OUT"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "T_true sweep: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, load ${LOAD_PCT}%"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}
trap 'reap' EXIT

run_cell () {
  local pad="$1"
  local tag="pad${pad}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  stress-ng --cpu "$NCORES" --cpu-load "$LOAD_PCT" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" \
        --kafka-producer-extra "--max-inflight 64 --pad-bytes $pad" \
        --redis-producer-extra "--pad-bytes $pad" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  printf 'tag,pad_bytes,cpu_load_pct,n_feeds,reps,max_t_sim\n%s,%s,%s,5,%s,%s\n' \
    "$tag" "$pad" "$LOAD_PCT" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  reap
}

# Spread over three orders of magnitude, because T_true has to move by enough to matter against
# a stall distribution whose interesting region is a few hundred microseconds wide.
for PAD in 0 4096 65536 262144; do
  banner "E-A10 pad=${PAD} bytes at ${LOAD_PCT}% load"
  run_cell "$PAD"
done

banner "TTRUE_SWEEP_COMPLETE"
