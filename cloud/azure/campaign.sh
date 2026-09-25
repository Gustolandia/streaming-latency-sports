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
#   0. machine   the receiver's address only in its namespace, the broker reachable, and no
#                package manager running; otherwise the run fails before it starts;
#   1. settings  online CPUs (all of them unless the setup names a count), then the base slice
#                unless the setup keeps the kernel's own; both read back, with the tick, and a
#                mismatch fails the run before any traffic;
#   2. delay     the receiver-only delay on the broker, measured by ping from both sides beyond
#                the same ping taken with no delay just before (the measured value is what the
#                analysis uses), while the broker's own capture of those pings times how long it
#                held the receiver's replies (delay_hold.json: to the microsecond, where ping
#                prints 0.1 ms above 10 ms);
#   3. load      stress-ng on every online CPU at the setup's duty, measured by util_sampler;
#   4. trace     A1 and A3 runs whose queue key hashes even record the timestamping processes'
#                run-queue delays with bpftrace (A6);
#   5. run       one trial of one backend on a constant-rate plan, the consumer behind the
#                receiver's address, go-first priority where the setup asks for it, Kafka's
#                producer with 64 requests in flight and Redis's consumer acknowledging in
#                batches of 200 (the paper's own settings); the clock's offset, the CPU counters
#                and the TCP counters of the driver, the receiver's namespace and the broker are
#                logged just before and just after it, and the broker's log for the run is kept;
#   6. checks    scripts/run_integrity.py, on this machine, as soon as the trial ends: the run
#                counts, is repeated, or stops the campaign, and integrity.json says why;
#   7. record    everything lands in the run's own directory, runs/law_<queue>_<key>, with
#                lane.json naming the machine pair and the commit, and the queue marks the run
#                done or failed. A directory that already exists stops the campaign: keys repeat
#                from one queue to the next, and a run never writes into another run's files.
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
QUEUE_NAME="$(basename "$QUEUE" .csv)"
: "${RECEIVER_IP:?hosts.env has no RECEIVER_IP; is this the Azure testbed?}"
: "${DRIVER_PRIV:?hosts.env has no DRIVER_PRIV; is this the Azure testbed?}"
RATE="${RATE:-50}"
DURATION="${DURATION:-130}"
WARMUP_S="${WARMUP_S:-30}"
STOP_FILE="${STOP_FILE:-runs/azure/STOP}"
CALIBRATION="${CALIBRATION:-}"
#: Empty is the rule: the got-it brake stops the campaign. "record" is asked for by name for one
#: campaign's remaining runs, after a stop, and is frozen before those runs begin (D26-1).
GOTIT_BRAKE="${GOTIT_BRAKE:-}"
LANE="${LANE:-${AZ_PROFILE:-unknown}}"
SYN_PLAN="data/synthetic/constant_r${RATE}_d${DURATION}/replay_plan.csv"
TRACE_BT="runs/azure/runqlat.bt"
#: D28-1: every python3 thread's scheduling events, one line each, for A9's traced runs.
EVENTS_BT="runs/azure/waits.bt"
ALL_CPUS=$(nproc --all)
ME=$(id -un)

log () { echo "$(date -u +%FT%TZ) $*"; }
broker_delay () {
  remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker \
    --dst $RECEIVER_IP --delay-ms $1 --apply" >/dev/null 2>&1
}
reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  # A8 runs Kafka's Java client too, and a leftover one would send into the next run's topic.
  pkill -f "LawProducer|LawConsumer" 2>/dev/null
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

if python3 -c 'import csv, json, sys
rows = csv.DictReader(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if any(json.loads(r["params"]).get("trace_events") for r in rows) else 1)' "$QUEUE"; then
  # D28-1: A9 reads each negative reading against the waits of the one thread that stamped its
  # acknowledgement, so it needs every event rather than a histogram: a python3 thread taken off
  # a CPU while it could still run (P) or because it slept (S), put back on one (R) and woken
  # (W), with its id and the kernel's monotonic clock. The clients name the threads that stamp
  # and read both clocks (scripts/thread_record.py). Probed against live traffic first, as above.
  cat > "$EVENTS_BT" <<'BT'
tracepoint:sched:sched_switch
{
  if (args->prev_comm == "python3") {
    if (args->prev_state == 0) { printf("P %d %llu\n", args->prev_pid, nsecs); }
    else { printf("S %d %llu\n", args->prev_pid, nsecs); }
  }
  if (args->next_comm == "python3") { printf("R %d %llu\n", args->next_pid, nsecs); }
}

tracepoint:sched:sched_wakeup,
tracepoint:sched:sched_wakeup_new
{
  if (args->comm == "python3") { printf("W %d %llu\n", args->pid, nsecs); }
}
BT
  python3 -c "
import time
for _ in range(900):
    time.sleep(0.01)
" >/dev/null 2>&1 &
  PROBE_PID=$!
  sleep 1
  sudo timeout 8 bpftrace "$EVENTS_BT" > runs/azure/probe_events.txt 2>&1
  kill "$PROBE_PID" 2>/dev/null
  PROBE_EVENTS=$(grep -cE '^[PSRW] [0-9]+ [0-9]+$' runs/azure/probe_events.txt)
  [ "${PROBE_EVENTS:-0}" -ge 100 ] || {
    log "FATAL: the event probe recorded ${PROBE_EVENTS:-0} events against live traffic"
    exit 1; }
  log "event probe ok: $PROBE_EVENTS events in 8 s"
fi

if python3 -c 'import csv, json, sys
rows = csv.DictReader(open(sys.argv[1], encoding="utf-8"))
sys.exit(0 if any(json.loads(r["params"]).get("plan") == "football" for r in rows) else 1)' "$QUEUE"; then
  # S0-2, D29-1: M0 replays the football match in bursts, as the pilot did at ten messages a
  # second. A burst sends what the match did, so the count a run is held to and the rate it is
  # checked at are the plan's own events in the run's window (scripts/replay_window.py).
  FOOT_PLAN=$(find data/processed/replay_plans -name replay_plan.csv | sort | head -n 1)
  [ -f "$FOOT_PLAN" ] || {
    log "FATAL: no football replay plan under data/processed/replay_plans"; exit 1; }
  FOOT_SPEEDUP=$(assert_plan_rate "$FOOT_PLAN" 10) || {
    log "FATAL: no speedup for $FOOT_PLAN"; exit 1; }
  read -r FOOT_MAXT FOOT_PLANNED FOOT_RATE < <(python3 scripts/replay_window.py "$FOOT_PLAN" \
    --speedup "$FOOT_SPEEDUP" --duration "$DURATION" --warmup-s "$WARMUP_S")
  [ "${FOOT_PLANNED:-0}" -gt 1 ] || {
    log "FATAL: the football plan sends ${FOOT_PLANNED:-nothing} after the warm-up"; exit 1; }
  log "football replay: $FOOT_PLAN at speedup $FOOT_SPEEDUP; $FOOT_PLANNED messages after the warm-up at $FOOT_RATE a second, to match second $FOOT_MAXT"
fi

tcp_counters () {  # before|after: the Tcp lines of /proc/net/snmp on every side of the run
  grep '^Tcp:' /proc/net/snmp > "$RUN_DIR/tcp_$1.txt" 2>&1
  sudo ip netns exec sblrecv grep '^Tcp:' /proc/net/snmp > "$RUN_DIR/receiver_tcp_$1.txt" 2>&1
  remote_broker "grep '^Tcp:' /proc/net/snmp" > "$RUN_DIR/broker_tcp_$1.txt" 2>&1
}

# --- one run ---------------------------------------------------------------------------------
run_one () {
  local want_cpus="${CPUS:-$ALL_CPUS}" stress_pid sampler_pid rc traced=0 wrap_sched="" verdict
  local capture_pid measured began ended container
  local check_args=() calibration_args=() gotit_args=()
  reap
  # The machine must still be the one the session built. On 16 September a package upgrade
  # restarted the network service mid-pilot, the receiver's address came back on the card, and
  # the driver lost its broker; session.sh now switches upgrades off, and this catches the rest.
  if ip -o -4 addr show dev eth0 | grep -q " ${RECEIVER_IP}/"; then
    REASON="the receiver's address is back on the driver's card; run cloud/azure/session.sh"; return
  fi
  sudo ip netns exec sblrecv ip -o -4 addr show | grep -q " ${RECEIVER_IP}/" || {
    REASON="the receiver's namespace does not hold its address; run cloud/azure/session.sh"; return; }
  ping -n -c 2 -W 1 "$BROKER_PRIV" >/dev/null 2>&1 || {
    REASON="the driver cannot reach the broker at $BROKER_PRIV"; return; }
  if sudo fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1; then
    REASON="a package manager is running on the driver"; return
  fi
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

  # The two ping paths can differ with no delay at all (by 0.4 ms on the second x86 pair), so the
  # same measurement is taken with no delay first, and run_integrity.py counts what lies beyond it.
  broker_delay 0 || { REASON="the broker's delay could not be set to zero"; return; }
  sleep 1
  sudo python3 scripts/receiver_delay.py measure --broker "$BROKER_PRIV" --count 100 \
    --out "$RUN_DIR/delay_baseline.json" >/dev/null 2>&1 || {
    REASON="the zero-delay ping baseline could not be measured"; return; }
  broker_delay "$DELAY_MS" || { REASON="the receiver-only delay did not apply"; return; }
  remote_broker "sudo timeout 60 tcpdump -i eth0 -nn -tt --time-stamp-precision=nano -c 400 \
    'icmp and (host $DRIVER_PRIV or host $RECEIVER_IP)'" \
    > "$RUN_DIR/delay_capture.txt" 2> "$RUN_DIR/delay_capture.err" &
  capture_pid=$!
  sleep 2
  sudo python3 scripts/receiver_delay.py measure --broker "$BROKER_PRIV" --count 100 \
    --out "$RUN_DIR/delay_measured.json" >/dev/null 2>&1
  measured=$?
  wait "$capture_pid" 2>/dev/null
  [ "$measured" = 0 ] || { REASON="the receiver-only delay could not be measured"; return; }
  python3 scripts/receiver_delay.py holds --capture "$RUN_DIR/delay_capture.txt" \
    --host "$DRIVER_PRIV" --receiver "$RECEIVER_IP" --out "$RUN_DIR/delay_hold.json" \
    > "$RUN_DIR/delay_hold.log" 2>&1

  stress-ng --cpu "$want_cpus" --cpu-load "$LOAD" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$RUN_DIR/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  #: stress-ng is told a duty, and what the machine then shows is that duty plus whatever the
  #: harness itself is using -- the client, the receiver's namespace, the sampler. On eight CPUs
  #: that share is under a point and nobody noticed. On two it is over three, and A5's two-CPU
  #: calibration failed its own runs at 78.1% against a 75% design, three times over, before it
  #: had measured anything.
  #:
  #: Widening the check was the wrong answer: A5 compares core counts at one load, so letting two
  #: CPUs sit at 78 while eight sit at 75 puts a difference in load exactly where the difference
  #: in cores is meant to be. So the duty is corrected instead, once, against what the machine
  #: actually shows, before the warm-up ends and well before any message is counted. What it was
  #: corrected to is written beside the run.
  sleep 4
  local shown adjusted
  shown=$(python3 -c 'import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
rho = [float(r["rho"]) for r in rows[-6:] if r.get("rho")]
print("%.2f" % (100 * statistics.fmean(rho)) if rho else "")' "$RUN_DIR/utilisation.csv" 2>/dev/null)
  if [ -n "$shown" ]; then
    adjusted=$(python3 -c 'import sys
want, shown, duty = (float(x) for x in sys.argv[1:4])
out = duty - (shown - want)
print("%d" % round(min(100.0, max(1.0, out))))' "$LOAD" "$shown" "$LOAD")
    printf '{"designed_pct": %s, "shown_before_pct": %s, "duty_used_pct": %s}\n' \
      "$LOAD" "$shown" "$adjusted" > "$RUN_DIR/load_correction.json"
    if [ "$adjusted" != "$LOAD" ]; then
      #: -9, not a polite TERM. stress-ng does not stop for TERM here, so the wait below sat
      #: until the first one reached its own --timeout 3600s: four runs of matched's A2 on
      #: 23 September took 62.7 minutes each instead of 2.8, and matched-b's took four of the
      #: twelve hours its job was given, leaving 24 of its 60 runs unmeasured. Every stalled run
      #: was a run that took this branch and no other run stalled, on either pair. The cleanup at
      #: the end of the run already kills this same process with -9 and has never hung.
      kill -9 "$stress_pid" 2>/dev/null; wait "$stress_pid" 2>/dev/null
      pkill -9 -x stress-ng 2>/dev/null
      stress-ng --cpu "$want_cpus" --cpu-load "$adjusted" --timeout 3600s >/dev/null 2>&1 &
      stress_pid=$!
      sleep 3
    fi
  fi

  # M0 replays the football plan and is held to that plan's own count and rate (D29-1); every
  # other block runs the steady one.
  local run_plan="$SYN_PLAN" run_speedup="$SPEEDUP" run_maxt="$DURATION" run_rate="$RATE"
  local plan_args=()
  if [ "$PLAN_KIND" = football ]; then
    run_plan="$FOOT_PLAN"; run_speedup="$FOOT_SPEEDUP"; run_maxt="$FOOT_MAXT"
    run_rate="$FOOT_RATE"; plan_args=(--planned "$FOOT_PLANNED")
  fi

  local record_args="" read_args="" receiver_capture=""
  if [ -n "$TRACE_HALF" ] && [ "$TRACE" = 1 ]; then
    if [ -n "$TRACE_EVENTS" ]; then
      sudo bpftrace "$EVENTS_BT" > "$RUN_DIR/waits.txt" 2>"$RUN_DIR/waits.err" &
      record_args="--thread-record"
    else
      sudo bpftrace "$TRACE_BT" > "$RUN_DIR/runqlat.txt" 2>"$RUN_DIR/runqlat.err" &
    fi
    if [ -n "$CAPTURE" ]; then
      # M0's recorded half (S0-2): the packets at both ends, for M-H1 and M-H4, and the receive
      # loop's own cycle, for M-H2. Each capture is stopped by its own process id below.
      read_args="--read-trace"
      sudo ip netns exec sblrecv tcpdump -i any -s 200 -w "$RUN_DIR/receiver.pcap" \
        host "$BROKER_PRIV" > "$RUN_DIR/receiver_capture.err" 2>&1 &
      receiver_capture=$!
      # A capture a crashed run left behind is stopped by its own id first, so no two write one file.
      remote_broker "sudo sh -c 'kill -INT \$(cat /tmp/sbl_m0.pid 2>/dev/null) 2>/dev/null; nohup tcpdump -i eth0 -s 200 -w /tmp/sbl_m0.pcap host $RECEIVER_IP > /tmp/sbl_m0.err 2>&1 & echo \$! > /tmp/sbl_m0.pid'" \
        > /dev/null 2>&1
    fi
    traced=1
    sleep 8
  fi

  [ -n "$PRIORITY" ] && wrap_sched="sudo chrt -f 80"
  chronyc -c tracking > "$RUN_DIR/clock_before.txt" 2>/dev/null
  head -n 1 /proc/stat > "$RUN_DIR/stat_before.txt"
  tcp_counters before
  began=$(date -u +%s)
  if [ "$BACKEND" = kafka ]; then
    client_args=()
    [ -n "${CLIENT:-}" ] && client_args+=(-CLIENT "$CLIENT")
    [ -n "${ACK_STAMP:-}" ] && client_args+=(-ACK_STAMP "$ACK_STAMP")
    SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" SBL_SCHED_WRAP="$wrap_sched" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_kafka_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
      -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA $record_args" \
      -CONSUMER_EXTRA "$record_args $read_args" \
      -IDLE_SECONDS 15 "${client_args[@]}" > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  else
    SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" SBL_SCHED_WRAP="$wrap_sched" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_redis_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
      -PRODUCER_EXTRA "$record_args" \
      -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA${ACK_BATCH:+ --ack-batch $ACK_BATCH} $record_args" \
      -IDLE_SECONDS 15 > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  fi
  ended=$(date -u +%s)
  head -n 1 /proc/stat > "$RUN_DIR/stat_after.txt"
  chronyc -c tracking > "$RUN_DIR/clock_after.txt" 2>/dev/null
  tcp_counters after
  container=redis
  [ "$BACKEND" = kafka ] && container=broker
  remote_broker "docker logs --timestamps --since $began --until $(( ended + 1 )) $container" \
    > "$RUN_DIR/broker_log.txt" 2>&1

  if [ -n "$receiver_capture" ]; then
    sudo kill -INT "$receiver_capture" 2>/dev/null; wait "$receiver_capture" 2>/dev/null
    remote_broker "sudo kill -INT \$(cat /tmp/sbl_m0.pid) 2>/dev/null; sleep 1; sudo cat /tmp/sbl_m0.pcap; sudo rm -f /tmp/sbl_m0.pcap /tmp/sbl_m0.pid /tmp/sbl_m0.err" \
      > "$RUN_DIR/broker.pcap" 2>/dev/null
  fi
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
  [ -n "$GOTIT_BRAKE" ] && gotit_args=(--gotit-brake "$GOTIT_BRAKE")
  verdict=$(python3 scripts/run_integrity.py check "$RUN_DIR" --rate "$run_rate" \
    --duration "$DURATION" --warmup-s "$WARMUP_S" "${calibration_args[@]}" "${gotit_args[@]}" \
    "${plan_args[@]}" 2> "$RUN_DIR/integrity.err")
  case $? in
    0) ;;
    3) STOP_REASON="${verdict#stop: }"; REASON="$verdict" ;;
    *) verdict="${verdict#repeat: }"
       REASON="integrity: ${verdict:-the check itself failed; see $RUN_DIR/integrity.err}" ;;
  esac
}

# --- the queue -------------------------------------------------------------------------------
log "campaign: $QUEUE on lane $LANE; plan $SYN_PLAN at speedup $SPEEDUP; warm-up ${WARMUP_S} s; $ALL_CPUS CPUs${CALIBRATION:+; calibration $CALIBRATION}${GOTIT_BRAKE:+; the got-it brake: $GOTIT_BRAKE (D26-1)}"
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
    # A8 varies which client sends and where it takes the got-it note; every other block leaves
    # both unset and the run is launched exactly as it always was.
    "CLIENT": p.get("language") or "", "ACK_STAMP": p.get("ack_stamp") or "",
    "TRACE_HALF": "1" if p.get("trace_half") else "",
    "TRACE_EVENTS": "1" if p.get("trace_events") else "",
    # M0 (D29-1): its plan, the Redis consumer's acknowledgement batch, and whether its recorded
    # half captures packets. Every other block leaves all three unset.
    "PLAN_KIND": p.get("plan") or "", "ACK_BATCH": p.get("ack_batch") or "",
    "CAPTURE": "1" if p.get("capture") else "",
    "TRACE": 1 if int(hashlib.sha256(row["key"].encode()).hexdigest(), 16) % 2 == 0 else 0,
    "HZ": round(1000 / tick) if tick else "",
}
print("\n".join("%s=%s" % (k, shlex.quote(str(v))) for k, v in values.items()))
PY
)"
  # On 16 September a restarted calibration wrote its first run into the folder of the attempt
  # before it, because the folder was named by the key alone.
  RUN_ID="law_${QUEUE_NAME}_$KEY"
  RUN_DIR="runs/$RUN_ID"
  if [ -e "$RUN_DIR" ]; then
    log "FATAL: $RUN_DIR already exists, and a run never writes into another run's folder"
    exit 1
  fi
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
