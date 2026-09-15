#!/usr/bin/env bash
# The law campaign's runner. It takes runs one at a time from a queue made by
# scripts/run_queue.py, sets each run's conditions, runs it, checks it, and records the outcome.
#
# Run on the driver, from the checkout, after cloud/azure/session.sh and a passing pilot:
#     nohup bash cloud/azure/campaign.sh runs/azure/queues/a1.csv > campaign_a1.log 2>&1 &
# and, once the session's delay calibration (C0) has been fitted, with it:
#     CALIBRATION=runs/azure/calibration.json nohup bash cloud/azure/campaign.sh QUEUE > LOG 2>&1 &
# To stop after the run in progress:  touch runs/azure/STOP
#
# One run, in order:
#   1. settings  online CPUs (all of them unless the setup names a count), then the base slice
#                unless the setup keeps the kernel's own; both read back, with the tick, and a
#                mismatch fails the run before any traffic;
#   2. delay     the receiver-only delay on the broker, then measured by ping from both sides
#                (the measured value is what the analysis uses);
#   3. load      stress-ng on every online CPU at the setup's duty, measured by util_sampler;
#   4. trace     A1 and A3 runs whose queue key hashes even record the timestamping processes'
#                run-queue delays with bpftrace (A6);
#   5. run       one trial of one backend on a constant-rate plan, the consumer behind the
#                receiver's address, go-first priority where the setup asks for it; the clock's
#                offset and the CPU counters are logged just before and just after it;
#   6. checks    scripts/run_integrity.py, on this machine, as soon as the trial ends: the run
#                counts, is repeated, or stops the campaign, and integrity.json says why;
#   7. record    everything lands in the run's directory, with lane.json naming the machine pair
#                and the commit, and the queue marks the run done or failed.
#
# A run is repeated only when a step failed or a condition it was meant to have did not take:
# too few messages, the send rate or the load off target, the delay or the settings not as set,
# the clock not logged. A run whose conditions held is done whatever it measured. Two things stop
# the campaign, with a STOP_RULE line in this log: a run that puts the instrument in doubt (a
# message that arrived before it was sent, or a "got it" median that left the session's
# calibration), and a queue whose attempts keep failing (scripts/run_integrity.py guard).
#
# RATE and DURATION set the plan. The default, 50 messages a second for 130 s, keeps 5,000
# messages after the 30 s warm-up. The effect is strongest at sparse rates, so the spread pilot
# is where to learn whether the plateau is still measurable at this one.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e

QUEUE="${1:?usage: bash cloud/azure/campaign.sh QUEUE.csv}"
: "${RECEIVER_IP:?hosts.env has no RECEIVER_IP; is this the Azure testbed?}"
RATE="${RATE:-50}"
DURATION="${DURATION:-130}"
WARMUP_S="${WARMUP_S:-30}"
STOP_FILE="${STOP_FILE:-runs/azure/STOP}"
CALIBRATION="${CALIBRATION:-}"
LANE="${LANE:-${AZ_PROFILE:-unknown}}"
SYN_PLAN="data/synthetic/constant_r${RATE}_d${DURATION}/replay_plan.csv"
TRACE_BT="runs/azure/runqlat.bt"
ALL_CPUS=$(nproc --all)
ME=$(id -un)

log () { echo "$(date -u +%FT%TZ) $*"; }
broker_delay () {
  remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker \
    --dst $RECEIVER_IP --delay-ms $1 --apply" >/dev/null 2>&1
}
reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  sudo pkill -INT -x bpftrace 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}
finish_campaign () {
  reap
  sudo python3 scripts/sched_settings.py set-cpus "$ALL_CPUS" >/dev/null 2>&1
  remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply" \
    >/dev/null 2>&1
}
trap finish_campaign EXIT

# --- before the first run: refuse to spend runs on a testbed that is not ready -----------------
mkdir -p runs/azure
[ -f "$QUEUE" ] || { log "FATAL: no queue at $QUEUE"; exit 1; }
if [ -n "$CALIBRATION" ] && [ ! -f "$CALIBRATION" ]; then
  log "FATAL: CALIBRATION names $CALIBRATION, which does not exist"; exit 1
fi
sudo -n true 2>/dev/null || { log "FATAL: the runner needs passwordless sudo"; exit 1; }
command -v chrt >/dev/null || { log "FATAL: chrt is not installed"; exit 1; }
ip netns list | grep -q '^sblrecv' || {
  log "FATAL: the receiver's namespace is missing; run cloud/azure/session.sh"; exit 1; }
CONTAINERS=$(remote_broker "docker ps --format '{{.Names}}:{{.State}}'" 2>/dev/null)
for c in broker redis; do
  echo "$CONTAINERS" | grep -q "^$c:running" || {
    log "FATAL: $c is not running on the broker; run cloud/azure/session.sh"; exit 1; }
done
[ -f "$SYN_PLAN" ] || python3 scripts/make_synthetic_plan.py --arrival constant \
  --rate "$RATE" --duration "$DURATION" --out "$SYN_PLAN" || {
  log "FATAL: could not make the plan $SYN_PLAN"; exit 1; }
SPEEDUP=$(assert_plan_rate "$SYN_PLAN" 1) || { log "FATAL: no speedup for $SYN_PLAN"; exit 1; }

if python3 -c 'import csv, json, sys
rows = csv.DictReader(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if any(json.loads(r["params"]).get("trace_half") for r in rows) else 1)' "$QUEUE"; then
  # The same probe as cloud/campaigns/stall_distribution.sh, smoke-tested against live traffic
  # first: an instrument that records nothing is not a null result, it is no experiment.
  cat > "$TRACE_BT" <<'BT'
tracepoint:sched:sched_wakeup,
tracepoint:sched:sched_wakeup_new
{
  if (args->comm == "python3") { @qt[args->pid] = nsecs; }
}

tracepoint:sched:sched_switch
{
  if (args->prev_state == 0 && args->prev_comm == "python3") {
    @qt[args->prev_pid] = nsecs;
  }
  $t = @qt[args->next_pid];
  if ($t != 0) {
    $d = (nsecs - $t) / 1000;
    @usecs = lhist($d, 0, 20000, 100);
    @count = count();
    delete(@qt[args->next_pid]);
  }
}
BT
  python3 -c "
import time
for _ in range(900):
    time.sleep(0.01)
" >/dev/null 2>&1 &
  PROBE_PID=$!
  sleep 1
  sudo timeout 8 bpftrace "$TRACE_BT" > runs/azure/probe_check.txt 2>&1
  kill "$PROBE_PID" 2>/dev/null
  PROBE_COUNT=$(grep -oE '^@count: [0-9]+' runs/azure/probe_check.txt | grep -oE '[0-9]+$')
  [ "${PROBE_COUNT:-0}" -ge 100 ] || {
    log "FATAL: the run-queue probe recorded ${PROBE_COUNT:-0} events against live traffic"
    exit 1; }
  log "run-queue probe ok: $PROBE_COUNT events in 8 s"
fi

# --- one run ---------------------------------------------------------------------------------
run_one () {
  local want_cpus="${CPUS:-$ALL_CPUS}" stress_pid sampler_pid rc traced=0 wrap_sched="" verdict
  local check_args=() calibration_args=()
  reap
  sudo python3 scripts/sched_settings.py set-cpus "$want_cpus" > "$RUN_DIR/set_cpus.txt" 2>&1 || {
    REASON="online CPUs did not become $want_cpus"; return; }
  if [ -n "$SLICE_NS" ]; then
    sudo python3 scripts/sched_settings.py set-slice "$SLICE_NS" > "$RUN_DIR/set_slice.txt" 2>&1 || {
      REASON="the base slice did not take $SLICE_NS ns"; return; }
    check_args+=(--slice-ns "$SLICE_NS")
  fi
  [ -n "$HZ" ] && check_args+=(--hz "$HZ")
  sudo python3 scripts/sched_settings.py check "${check_args[@]}" > "$RUN_DIR/settings_before.json" || {
    REASON="the settings before the run do not match the setup"; return; }

  broker_delay "$DELAY_MS" || { REASON="the receiver-only delay did not apply"; return; }
  sleep 1
  sudo python3 scripts/receiver_delay.py measure --broker "$BROKER_PRIV" --count 100 \
    --out "$RUN_DIR/delay_measured.json" >/dev/null 2>&1 || {
    REASON="the receiver-only delay could not be measured"; return; }

  stress-ng --cpu "$want_cpus" --cpu-load "$LOAD" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$RUN_DIR/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  if [ -n "$TRACE_HALF" ] && [ "$TRACE" = 1 ]; then
    sudo bpftrace "$TRACE_BT" > "$RUN_DIR/runqlat.txt" 2>"$RUN_DIR/runqlat.err" &
    traced=1
    sleep 8
  fi

  [ -n "$PRIORITY" ] && wrap_sched="sudo chrt -f 80"
  chronyc -c tracking > "$RUN_DIR/clock_before.txt" 2>/dev/null
  head -n 1 /proc/stat > "$RUN_DIR/stat_before.txt"
  if [ "$BACKEND" = kafka ]; then
    SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" SBL_SCHED_WRAP="$wrap_sched" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_kafka_trial.sh "$RUN_ID" "$SYN_PLAN" \
      "$SPEEDUP" "$DURATION" -BOOTSTRAP "$KAFKA_BOOTSTRAP" -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA" \
      -IDLE_SECONDS 15 > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  else
    SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" SBL_SCHED_WRAP="$wrap_sched" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_redis_trial.sh "$RUN_ID" "$SYN_PLAN" \
      "$SPEEDUP" "$DURATION" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
      -IDLE_SECONDS 15 > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  fi
  head -n 1 /proc/stat > "$RUN_DIR/stat_after.txt"
  chronyc -c tracking > "$RUN_DIR/clock_after.txt" 2>/dev/null

  if [ "$traced" = 1 ]; then sudo pkill -INT -x bpftrace 2>/dev/null; sleep 3; fi
  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sudo chown -R "$(id -u):$(id -g)" "$RUN_DIR" 2>/dev/null

  [ "$rc" = 0 ] || { REASON="the trial exited with $rc; see $RUN_DIR/trial.log"; return; }
  if [ ! -f "$RUN_DIR/producer.csv" ] || [ ! -f "$RUN_DIR/consumer_events.csv" ]; then
    REASON="the run's producer or consumer file is missing"; return
  fi

  python3 scripts/pilot_checks.py run "$RUN_DIR" --warmup-s "$WARMUP_S" > "$RUN_DIR/checks.json" 2>&1
  local negative_exit=$?
  sudo python3 scripts/sched_settings.py check "${check_args[@]}" > "$RUN_DIR/settings_after.json"
  local drift_exit=$?
  printf '{"never_negative_exit": %d, "settings_after_exit": %d, "traced": %d}\n' \
    "$negative_exit" "$drift_exit" "$traced" > "$RUN_DIR/checks_exit.json"

  [ -n "$CALIBRATION" ] && calibration_args=(--calibration "$CALIBRATION")
  verdict=$(python3 scripts/run_integrity.py check "$RUN_DIR" --rate "$RATE" \
    --duration "$DURATION" --warmup-s "$WARMUP_S" "${calibration_args[@]}" \
    2> "$RUN_DIR/integrity.err")
  case $? in
    0) ;;
    3) STOP_REASON="${verdict#stop: }"; REASON="$verdict" ;;
    *) verdict="${verdict#repeat: }"
       REASON="integrity: ${verdict:-the check itself failed; see $RUN_DIR/integrity.err}" ;;
  esac
}

# --- the queue -------------------------------------------------------------------------------
log "campaign: $QUEUE on lane $LANE; plan $SYN_PLAN at speedup $SPEEDUP; warm-up ${WARMUP_S} s; $ALL_CPUS CPUs${CALIBRATION:+; calibration $CALIBRATION}"
RECOVER="--recover"
while true; do
  if [ -f "$STOP_FILE" ]; then
    rm -f "$STOP_FILE"
    log "STOPPED at $STOP_FILE"
    break
  fi
  ROW=$(python3 scripts/run_queue.py next --queue "$QUEUE" $RECOVER)
  NEXT_EXIT=$?
  RECOVER=""
  if [ "$NEXT_EXIT" = 3 ]; then log "CAMPAIGN_COMPLETE"; break; fi
  [ "$NEXT_EXIT" = 0 ] || { log "FATAL: the queue refused: $ROW"; exit 1; }
  eval "$(python3 - "$ROW" <<'PY'
import hashlib, json, shlex, sys
row = json.loads(sys.argv[1])
p = row["params"]
tick = p.get("tick_ms")
values = {
    "KEY": row["key"], "BACKEND": p["backend"], "LOAD": p["load_pct"],
    "SLICE_NS": p.get("slice_ns") or "", "DELAY_MS": p["delay_ms"],
    "PRIORITY": "1" if p.get("priority") else "", "CPUS": p.get("cpus") or "",
    "TRACE_HALF": "1" if p.get("trace_half") else "",
    "TRACE": 1 if int(hashlib.sha256(row["key"].encode()).hexdigest(), 16) % 2 == 0 else 0,
    "HZ": round(1000 / tick) if tick else "",
}
print("\n".join("%s=%s" % (k, shlex.quote(str(v))) for k, v in values.items()))
PY
)"
  RUN_ID="law_$KEY"
  RUN_DIR="runs/$RUN_ID"
  mkdir -p "$RUN_DIR"
  echo "$ROW" > "$RUN_DIR/queue_row.json"
  printf '{"lane": "%s", "profile": "%s", "driver": "%s", "commit": "%s"}\n' "$LANE" \
    "${AZ_PROFILE:-unknown}" "$(hostname)" "$(git rev-parse HEAD 2>/dev/null)" > "$RUN_DIR/lane.json"
  log "run $KEY: $BACKEND, load $LOAD%, slice ${SLICE_NS:-kernel default}, delay $DELAY_MS ms${PRIORITY:+, go-first}${CPUS:+, $CPUS CPUs online}"
  REASON=""
  STOP_REASON=""
  run_one
  if [ -n "$REASON" ]; then
    echo "  [FAIL] $KEY: $REASON"
    python3 scripts/run_queue.py finish --queue "$QUEUE" --key "$KEY" --status failed \
      --reason "$REASON" --run-dir "$RUN_DIR"
  else
    python3 scripts/run_queue.py finish --queue "$QUEUE" --key "$KEY" --status done \
      --run-dir "$RUN_DIR"
  fi
  if [ -n "$STOP_REASON" ]; then
    log "STOP_RULE: $STOP_REASON"
    break
  fi
  GUARD=$(python3 scripts/run_integrity.py guard --queue "$QUEUE")
  if [ "$?" = 3 ]; then
    log "STOP_RULE: $GUARD"
    break
  fi
done
