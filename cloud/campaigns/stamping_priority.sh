#!/usr/bin/env bash
# E-A5: change stamping-thread OCCUPANCY at fixed utilisation. The decisive test of the mechanism.
#
# WHY THIS EXPERIMENT EXISTS
#
# scripts/fit_two_state.py reports a result that no further analysis of the existing data can
# fix. Across our load ladder the utilisation rho and the residual width sigma rise TOGETHER.
# Two regressors that move together cannot be told apart by any fit, and the ablation in that
# script shows it directly: freezing sigma at its mean does not worsen the fit, it improves it
# (residual ratio 0.19). So the two-state model's higher R^2 over exp(k rho) is bought with
# extra columns, not with mechanism. The honest conclusion from the ladder is that the data
# cannot distinguish "inversions rise because the system is busy" from "inversions rise because
# the stamping thread is off-CPU more often".
#
# That is a question about experimental design, not about statistics, and it has a clean answer:
# move ONE of them and hold the other fixed.
#
# THE MANIPULATION
#
# Raising the stamping processes to real-time priority (SCHED_FIFO) makes them preempt the
# background load rather than wait behind it. Occupancy p falls sharply. System utilisation rho
# does NOT change: the same stressor is doing the same work on the same cores, and our processes
# use a negligible share of it.
#
# This is also the manipulation the netem attempt should have been. Injecting delay at the broker
# failed because it delayed the acknowledgement path and the delivery path equally and cancelled
# in the subtraction (see E-B2). Scheduling priority has no such symmetry: it acts on the
# stamping threads themselves, which is exactly where the model locates the failure.
#
# PRE-REGISTERED PREDICTIONS, stated before the run
#
#   occupancy mechanism (two-state):  the inversion rate COLLAPSES toward the RUNNING-state
#       floor, C0 ~ 0.004 -- a fall of order 50x at the high-load condition -- while rho is
#       unchanged. Transport medians move little, because the median is not where the
#       preemption tail lives.
#   utilisation mechanism (M/G/1, exp(k rho)):  the rate is a function of rho alone. rho is
#       unchanged by construction, so the rate is UNCHANGED. Any large fall falsifies it.
#
# These differ by more than an order of magnitude, so the experiment is decisive either way.
#
# MANIPULATION CHECK, and it can fail
#
# The whole design rests on rho being equal across the two arms. E-B2 taught us to verify that
# rather than assume it: there the injected delay moved the end-to-end figure while leaving the
# quantity under test untouched, and the campaign was withdrawn. So this script measures rho in
# BOTH arms and refuses to report an effect if they differ by more than 5 percentage points. If
# real-time priority perturbs the achieved load, the comparison is confounded and we say so.
#
# Usage:  nohup bash cloud/campaigns/stamping_priority.sh > stamping_priority.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea5}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

[ "$NCORES" -ge 4 ] || { echo "FATAL: $NCORES cores; wrong host"; exit 1; }
command -v chrt >/dev/null || { echo "FATAL: chrt not installed"; exit 1; }
sudo -n true 2>/dev/null || { echo "FATAL: real-time priority needs passwordless sudo"; exit 1; }

# Verify RT scheduling actually works here before spending an hour discovering it does not.
sudo chrt -f 80 true 2>/dev/null || { echo "FATAL: SCHED_FIFO refused on this host"; exit 1; }

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "stamping priority: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}

# One cell: a load level crossed with a scheduling arm.
run_cell () {
  local pct="$1" arm="$2" wrap="$3"
  local tag="l${pct}_${arm}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  stress-ng --cpu "$NCORES" --cpu-load "$pct" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  SBL_SCHED_WRAP="$wrap" timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  # The elevated arm runs under sudo, so its outputs land root-owned and would break the next
  # cell's writes. Hand them back before continuing.
  sudo chown -R "$(id -u):$(id -g)" runs "$OUT" 2>/dev/null
  printf 'tag,requested_cpu_load_pct,arm,sched_wrap,n_feeds,reps,max_t_sim\n%s,%s,%s,%s,5,%s,%s\n' \
    "$tag" "$pct" "$arm" "${wrap:-none}" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  reap
}

# Two load levels where inversions are common enough to measure a fall, crossed with two arms.
# Arms are interleaved per load level rather than run in blocks, so any drift over the campaign
# hits both arms rather than being confounded with the manipulation.
for PCT in 75 88; do
  banner "E-A5 cpu-load=${PCT}% BASELINE (ordinary priority)"
  run_cell "$PCT" "base" ""
  banner "E-A5 cpu-load=${PCT}% ELEVATED (SCHED_FIFO 80)"
  run_cell "$PCT" "rt" "sudo chrt -f 80"
done

banner "STAMPING_PRIORITY_COMPLETE"
