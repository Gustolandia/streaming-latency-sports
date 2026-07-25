#!/usr/bin/env bash
# E-A9: measure the run-queue delay DISTRIBUTION, which is the quantity the mechanism is about.
#
# WHY THE PREVIOUS MEASUREMENT WAS NOT ENOUGH. E-A7 read /proc/<pid>/schedstat, which carries
# cumulative totals. Everything derived from it is a MEAN: mean occupancy, mean wait per
# scheduling event. Those move 2x and 3-5x respectively between the ordinary and real-time arms,
# against a 40x fall in the inversion rate. Neither accounts for it.
#
# That gap is structural, not bad luck. An inversion is a TAIL event: it happens when ONE stall
# outlasts the true transport, about 0.5 ms here. A mean cannot bound a tail. So the honest
# conclusion from E-A7 was that the counters constrain the explanation without resolving it, and
# the missing quantity is named precisely -- P(run-queue delay > T_true).
#
# This campaign measures that directly. sched_wakeup and sched_switch tracepoints give the delay
# between a task becoming runnable and actually running, per event rather than as a total, so the
# tail is observed instead of averaged away.
#
# THE CLOSING TEST, pre-registered. From the histogram, compute
#
#     P(runqueue delay > T_true)      for the ordinary arm and the real-time arm
#
# and compare each against the inversion rate MEASURED in the same arm (E-A5b at 88%: 0.221
# ordinary, 0.0034 real-time). If the mechanism is right these should agree in magnitude and the
# RATIO between arms should reproduce the ~40-66x fall. If the traced tail moves far less than
# the inversion rate does, the scheduling account is wrong and something else is producing the
# inversions -- which is a real possible outcome and would be reported as one.
#
# THE INSTRUMENT MUST NOT CHANGE WHAT IT MEASURES. A BPF program on sched_switch fires on every
# context switch, and under 88% duty-cycled load that is a lot of them. So this campaign measures
# its own perturbation rather than assuming it away: the ordinary arm's inversion rate is
# compared against the same cell measured WITHOUT tracing (E-A5b l88 base, 0.2214). If tracing
# moves that materially, the histogram describes a machine we have not otherwise studied and the
# comparison above is void. That check is reported whatever it says.
#
# Usage:  nohup bash cloud/campaigns/stall_distribution.sh > stall_distribution.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea9}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
LOAD_PCT="${LOAD_PCT:-88}"
NCORES=$(nproc)
mkdir -p "$OUT"

sudo -n true 2>/dev/null || { echo "FATAL: needs passwordless sudo"; exit 1; }

banner "provisioning bpftrace"
command -v bpftrace >/dev/null || \
  sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update >/dev/null 2>&1
command -v bpftrace >/dev/null || \
  sudo DEBIAN_FRONTEND=noninteractive apt-get -qq install -y bpftrace >/dev/null 2>&1
command -v bpftrace >/dev/null || { echo "FATAL: bpftrace unavailable"; exit 1; }
bpftrace --version 2>&1 | head -1

# Run-queue latency for our stamping processes only. The filter is applied in-kernel so the
# per-event cost stays small even under heavy background switching.
#
# sched_wakeup           records when the task became runnable
# sched_switch, prev     a task preempted while still runnable re-enters the queue, so its
#                        clock restarts -- without this, preemption is invisible and the
#                        histogram would only show wakeup latency
# sched_switch, next     the task actually runs: emit the delay
cat > "$OUT/runqlat.bt" <<'BT'
tracepoint:sched:sched_wakeup,
tracepoint:sched:sched_wakeup_new
{
  if (str(args->comm) == "python3") { @qt[args->pid] = nsecs; }
}

tracepoint:sched:sched_switch
{
  if (args->prev_state == 0 && str(args->prev_comm) == "python3") {
    @qt[args->prev_pid] = nsecs;
  }
  $t = @qt[args->next_pid];
  if ($t != 0) {
    $d = (nsecs - $t) / 1000;
    @usecs = hist($d);
    @count = count();
    if ($d > 500)  { @over_500us  = count(); }
    if ($d > 1000) { @over_1000us = count(); }
    if ($d > 2000) { @over_2000us = count(); }
    delete(@qt[args->next_pid]);
  }
}

END { clear(@qt); }
BT

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  sudo pkill -f "bpftrace" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 3
}
trap 'reap' EXIT

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "stall distribution: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, load ${LOAD_PCT}%"

run_cell () {
  local arm="$1" wrap="$2"
  local tag="l${LOAD_PCT}_${arm}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  stress-ng --cpu "$NCORES" --cpu-load "$LOAD_PCT" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!
  # bpftrace prints its maps at exit, so it is stopped with SIGINT and its stdout kept whole.
  sudo bpftrace "$OUT/runqlat.bt" > "$OUT/$tag/runqlat.txt" 2>"$OUT/$tag/runqlat.err" &
  sleep 8

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  SBL_SCHED_WRAP="$wrap" timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  sudo pkill -INT -f bpftrace 2>/dev/null
  sleep 5
  sudo pkill -9 -f bpftrace 2>/dev/null
  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sudo chown -R "$(id -u):$(id -g)" runs "$OUT" 2>/dev/null
  printf 'tag,arm,sched_wrap,cpu_load_pct,n_feeds,reps,max_t_sim,traced\n%s,%s,%s,%s,5,%s,%s,1\n' \
    "$tag" "$arm" "${wrap:-none}" "$LOAD_PCT" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  echo "  histogram lines: $(wc -l < "$OUT/$tag/runqlat.txt" 2>/dev/null || echo 0)"
  grep -E "over_500us|over_1000us|over_2000us|@count" "$OUT/$tag/runqlat.txt" 2>/dev/null
  reap
}

banner "E-A9 ${LOAD_PCT}% BASELINE (ordinary priority, run-queue delay traced)"
run_cell "base" ""
banner "E-A9 ${LOAD_PCT}% ELEVATED (SCHED_FIFO 80, run-queue delay traced)"
run_cell "rt" "sudo chrt -f 80"

banner "STALL_DISTRIBUTION_COMPLETE"
