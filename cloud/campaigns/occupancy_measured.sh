#!/usr/bin/env bash
# E-A7: measure the quantities we have so far inferred.
#
# Three inferences currently carry weight they have not earned, and each has a direct
# measurement available. A referee can argue with an inference; a measurement has to be
# explained away.
#
#   p, the occupancy      inferred by inverting the model itself, p = (rate-C0)/(S-C0), which
#                         cannot disagree with the model it came from. The kernel counts the
#                         real thing in /proc/<pid>/schedstat field 2 -- time runnable but not
#                         running. Needs kernel.sched_schedstats, which is off by default.
#
#   the clock offset      the OMB argument turns on the producer's host and the consumer's host
#                         disagreeing, and we have never measured by how much. chrony already
#                         tracks it; we just have to write it down. An earlier attempt with ssh
#                         and `date` measured the round-trip, not the offset, and was useless.
#
#   the arms differ in p  E-A5 shows the rate falls 39-54x under SCHED_FIFO and ATTRIBUTES that
#                         to occupancy. With the sampler running in both arms the attribution
#                         becomes an observation: p must fall in the real-time arm, and by
#                         enough to account for the rate. If p does NOT fall, the mechanism is
#                         wrong however clean the rate result looked.
#
# WHY THIS RUNS ON ITS OWN. Enabling sched_schedstats adds accounting to every context switch.
# The overhead is small but it is not nothing, and switching it on midway through another
# campaign would split that campaign's cells into two populations. So this campaign owns the
# setting: it records the prior value, enables it, and restores it on exit whatever happens.
#
# PRE-REGISTERED, before the run:
#   * measured p falls sharply in the real-time arm (at least 10x), at unchanged utilisation.
#     The mechanism is then observed rather than assumed.
#   * measured p in the ORDINARY arm rises with load and tracks the p inferred from the
#     inversion rate. Agreement is evidence for the decomposition; disagreement falsifies it in
#     a way no curve fitting could reveal, and would be reported as such.
#
# Usage:  nohup bash cloud/campaigns/occupancy_measured.sh > occupancy_measured.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea7}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

command -v chrt >/dev/null || { echo "FATAL: chrt not installed"; exit 1; }
sudo -n true 2>/dev/null || { echo "FATAL: needs passwordless sudo"; exit 1; }

# --- the kernel setting, owned and restored ------------------------------------------------
PRIOR_SCHEDSTATS=$(cat /proc/sys/kernel/sched_schedstats 2>/dev/null || echo "unknown")
echo "kernel.sched_schedstats was: $PRIOR_SCHEDSTATS"
restore_schedstats () {
  if [ "$PRIOR_SCHEDSTATS" = "0" ] || [ "$PRIOR_SCHEDSTATS" = "1" ]; then
    sudo sysctl -w "kernel.sched_schedstats=$PRIOR_SCHEDSTATS" >/dev/null 2>&1
    echo "restored kernel.sched_schedstats=$PRIOR_SCHEDSTATS"
  fi
}
trap 'restore_schedstats' EXIT
sudo sysctl -w kernel.sched_schedstats=1 >/dev/null 2>&1
[ "$(cat /proc/sys/kernel/sched_schedstats)" = "1" ] || {
  echo "FATAL: could not enable sched_schedstats"; exit 1; }
echo "kernel.sched_schedstats now: 1"

# --- the clock offset, measured rather than asserted ---------------------------------------
banner "measuring host clock offsets"
{
  echo "host,source,measurement,value,unit,captured_utc"
  NOW=$(date -u +%FT%TZ)
  if command -v chronyc >/dev/null; then
    chronyc tracking 2>/dev/null | while IFS= read -r line; do
      case "$line" in
        "System time"*|"Last offset"*|"RMS offset"*|"Root delay"*|"Root dispersion"*)
          k=$(echo "$line" | cut -d: -f1 | xargs)
          v=$(echo "$line" | cut -d: -f2- | xargs)
          echo "driver,chronyc,\"$k\",\"$v\",,$NOW";;
      esac
    done
  else
    echo "driver,none,chronyc,not-installed,,$NOW"
  fi
  # The broker's own view, fetched the same way. Its clock is the other end of every
  # cross-host difference this paper computes.
  remote_broker "command -v chronyc >/dev/null && chronyc tracking" 2>/dev/null \
    | while IFS= read -r line; do
        case "$line" in
          "System time"*|"Last offset"*|"RMS offset"*)
            k=$(echo "$line" | cut -d: -f1 | xargs)
            v=$(echo "$line" | cut -d: -f2- | xargs)
            echo "broker,chronyc,\"$k\",\"$v\",,$NOW";;
        esac
      done
} > "$OUT/clock_offsets.csv"
cat "$OUT/clock_offsets.csv"

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "occupancy measured: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, ${NCORES} cores"

STAMPERS="kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py"

reap () {
  pkill -f "$STAMPERS" 2>/dev/null
  pkill -f "util_sampler.py|schedstat_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}

run_cell () {
  local pct="$1" arm="$2" wrap="$3"
  local tag="l${pct}_${arm}"
  local stress_pid="" sampler_pid="" sched_pid=""
  mkdir -p "$OUT/$tag"
  reap
  stress-ng --cpu "$NCORES" --cpu-load "$pct" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!
  # The measurement this campaign exists for.
  python3 scripts/schedstat_sampler.py --pattern "$STAMPERS" \
      --out "$OUT/$tag/schedstat.csv" --interval 0.5 > "$OUT/$tag/schedstat.log" 2>&1 &
  sched_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  SBL_SCHED_WRAP="$wrap" timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sched_pid" 2>/dev/null; wait "$sched_pid" 2>/dev/null
  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sudo chown -R "$(id -u):$(id -g)" runs "$OUT" 2>/dev/null
  printf 'tag,requested_cpu_load_pct,arm,sched_wrap,n_feeds,reps,max_t_sim,schedstats\n%s,%s,%s,%s,5,%s,%s,1\n' \
    "$tag" "$pct" "$arm" "${wrap:-none}" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  echo "  schedstat samples: $(( $(wc -l < "$OUT/$tag/schedstat.csv" 2>/dev/null || echo 1) - 1 ))"
  reap
}

for PCT in 75 88; do
  banner "E-A7 cpu-load=${PCT}% BASELINE (ordinary priority, p measured)"
  run_cell "$PCT" "base" ""
  banner "E-A7 cpu-load=${PCT}% ELEVATED (SCHED_FIFO 80, p measured)"
  run_cell "$PCT" "rt" "sudo chrt -f 80"
done

banner "OCCUPANCY_MEASURED_COMPLETE"
