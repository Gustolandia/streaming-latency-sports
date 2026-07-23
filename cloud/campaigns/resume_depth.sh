#!/usr/bin/env bash
# Resume the depth suite after the wedge on 2026-07-23.
#
# E-A (H2) and E-A2 (H4) completed and their data is on disk. This runs ONLY the missing
# phases -- E-B (H1, the central claim), E-C (H3), E-F, E-G -- then M1, then the arrival
# extension. It does NOT re-run E-A/E-A2.
#
# Two hardenings against the wedge, whose root cause was: run_concurrency_test.py timed out a
# hung N=12 trial but left orphaned producer children, so the shell call never returned and the
# whole campaign stalled for hours.
#
#   1. Every trial is wrapped in a shell `timeout`. If run_concurrency_test itself hangs, the
#      shell kills it rather than waiting on orphaned children forever.
#   2. After every trial, lingering producer/consumer processes are reaped, so a timed-out
#      trial cannot leave state that stalls the next one. trial-timeout is also cut from 1800s
#      to 400s (a real 180s trial finishes in ~200s), so a genuine per-trial hang fails in
#      minutes, not half an hour.
#
# None of the resumed phases uses N=12 -- the cell that hung -- so this also sidesteps the
# trigger, but the guards are kept as defence in depth.
#
# Usage:  nohup bash cloud/campaigns/resume_depth.sh > resume.log 2>&1 &
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-3}"
MAXT="${MAXT:-180}"
TRIAL_TIMEOUT="${TRIAL_TIMEOUT:-400}"
mkdir -p "$OUT"/{eb,ec,ef,eg,trace}

if [ "$(nproc)" -lt 4 ]; then echo "FATAL: $(nproc) cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "resume: --speedup $SPEEDUP_RT (true real time), window ${MAXT}s, trial-timeout ${TRIAL_TIMEOUT}s"

# Kill any stray producers/consumers from a prior trial. Safe only between trials, never during.
reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  sleep 2
}

# One trial under a controlled utilisation, with the two guards. `reps` is a per-call override
# so E-F can raise it without changing the default.
run_at_load () {
  local tag="$1" cores="$2" bg="$3" n="$4" reps="${5:-$REPS}" extra="${6:-}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"

  reap  # clear anything left by the previous trial before starting

  if [ "$bg" -gt 0 ]; then
    stress-ng --cpu "$bg" --timeout 3600s >/dev/null 2>&1 &
    stress_pid=$!
    sleep 2
  fi
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  # Shell-level ceiling: reps x 2 backends x (window + generous overhead), so even a total hang
  # of run_concurrency_test cannot stall the campaign. `timeout -k` sends KILL if TERM is ignored.
  local ceiling=$(( reps * 2 * (MAXT + 120) + 120 ))
  timeout -k 30 "$ceiling" \
    taskset -c "0-$((cores-1))" \
      python3 scripts/run_concurrency_test.py "$n" "$PLAN" "$reps" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$TRIAL_TIMEOUT" $extra 2>&1 | tail -2
  local rc=${PIPESTATUS[0]}
  [ "$rc" = 124 ] && echo "  NOTE: phase $tag hit its shell timeout (${ceiling}s) and was killed"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && { kill "$stress_pid" 2>/dev/null; wait "$stress_pid" 2>/dev/null; }
  printf 'tag,cores,bg_workers,n_feeds,reps\n%s,%s,%s,%s,%s\n' "$tag" "$cores" "$bg" "$n" "$reps" \
    > "$OUT/$tag/condition.csv"
  reap  # and clean up after, so orphans cannot stall the next trial
}

# ---- E-B: effect-size sweep (H1, the central claim) ------------------------
for D in 0 1 5 20 50; do
  banner "E-B delay=${D}ms"
  netem "$D"
  run_at_load "eb/d${D}" 2 2 5
done
netem 0

# ---- E-C: symmetry intervention (H3, H6) -----------------------------------
for MODE in callback inline; do
  banner "E-C stamping=$MODE"
  if [ "$MODE" = inline ]; then
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py
  else
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer.py
  fi
  run_at_load "ec/${MODE}" 2 2 5 3 "--kafka-producer-extra \"--max-inflight 64 --trace-loop $OUT/trace/${MODE}.csv\""
done
unset KAFKA_PRODUCER_SCRIPT

# ---- E-F: replication boost at N=1 (trimmed 30 -> 15) ----------------------
# 15 raises the cell from 8 surviving runs to ~15, enough to resolve the three-procedure
# disagreement, at half the wall-clock of 30.
banner "E-F N=1 replication boost (15 reps)"
run_at_load "ef/n1_power" 4 0 1 15

# ---- E-G: co-located vs distributed, matched load (construct validity) -----
banner "E-G co-located"
run_at_load "eg/colocated" 2 2 5
banner "E-G distributed"
run_at_load "eg/distributed" 2 2 5

banner "DEPTH_SUITE_COMPLETE"

# ---- then M1, then the arrival extension -----------------------------------
# M1 restricted to N=1: the client-attribution question (is the 103 ms offset kafka-python or
# Kafka?) is answered at N=1 real time, which is where the offset is observed. N=9 risked the
# same oversubscription hang that wedged E-A2, and the offset's concurrency-invariance is
# already established from the E1 corpus, so dropping N=9 costs nothing and removes the risk.
banner "M1 CLIENT A/B (N=1 only)"
LEVELS="1" REPS=6 bash cloud/campaigns/m1_client_ab.sh
banner "M1_DONE"

# Arrival windows cut from 600s to 180s to match every other campaign: at 600s this arm alone
# was seven hours, and it is the external-validity extension rather than load-bearing evidence.
banner "ARRIVAL PROCESS (180s windows)"
DURATION=180 REPS=6 bash cloud/campaigns/arrival_process.sh
banner "ALL_COMPLETE"
