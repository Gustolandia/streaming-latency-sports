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
#                mismatch fails the run before any traffic. Freeze 41: a setup that names a
#                scheduler feature has it set the same way, and every other run is held to
#                RUN_TO_PARITY on, the kernel's default, wherever the kernel shows its features;
#                a setup that names a boot (idle=poll or not) is held to /proc/cmdline; and a
#                setup that asks for what this runner cannot give as written fails here;
#   2. delay     the receiver-only delay on the broker, measured by ping from both sides beyond
#                the same ping taken with no delay just before (the measured value is what the
#                analysis uses), while the broker's own capture of those pings times how long it
#                held the receiver's replies (delay_hold.json: to the microsecond, where ping
#                prints 0.1 ms above 10 ms);
#   3. load      stress-ng on every online CPU at the setup's duty, measured by util_sampler;
#                freeze 43: at a duty frozen from the pilot where the setup names one, or
#                switched on and off in blocks from the trial's start where it asks;
#   4. trace     A1 and A3 runs whose queue key hashes even record the timestamping processes'
#                run-queue delays with bpftrace (A6);
#   5. run       one trial of one backend on a constant-rate plan, the consumer behind the
#                receiver's address, go-first priority where the setup asks for it, Kafka's
#                producer with 64 requests in flight and Redis's consumer acknowledging in
#                batches of 200 (the paper's own settings); the clock's offset, the CPU counters
#                and the TCP counters of the driver, the receiver's namespace and the broker are
#                logged just before and just after it, and the broker's log for the run is kept;
#                freeze 42: where the setup asks, the broker captures its own port meanwhile;
#                freeze 43: where the setup asks, the producer alone runs at real-time priority,
#                the clients' collector is off or logged, the consumer samples its own waits,
#                and the run's interrupt and scheduler facts are kept before, during and after;
#   6. checks    scripts/run_integrity.py, on this machine, as soon as the trial ends: the run
#                counts, is repeated, or stops the campaign, and integrity.json says why;
#   7. record    everything lands in the run's own directory, runs/law_<queue>_<key>, with
#                lane.json naming the machine pair and the commit, and the queue marks the run
#                done or failed. A directory that already exists stops the campaign: keys repeat
#                from one queue to the next, and a run never writes into another run's files.
#                A run that set a scheduler feature puts the kernel's default back once it has
#                ended, whichever way it ended.
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
#
# Freeze 43 (22 Oct 2026): PRIME_S=S on the campaign's job line runs one unjudged trial of S
# seconds on each broker, Kafka then Redis, before the queue's first run (prime_brokers).
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e

QUEUE="${1:?usage: bash cloud/azure/campaign.sh QUEUE.csv}"
QUEUE_NAME="$(basename "$QUEUE" .csv)"
: "${RECEIVER_IP:?hosts.env has no RECEIVER_IP; is this the Azure testbed?}"
: "${DRIVER_PRIV:?hosts.env has no DRIVER_PRIV; is this the Azure testbed?}"
RATE="${RATE:-50}"
DURATION="${DURATION:-130}"
WARMUP_S="${WARMUP_S:-30}"
#: Freeze 43 (22 Oct 2026): the seconds of one unjudged trial on each broker before the queue's
#: first run (prime_brokers). Empty primes nothing, as every campaign before it.
PRIME_S="${PRIME_S:-}"
STOP_FILE="${STOP_FILE:-runs/azure/STOP}"
CALIBRATION="${CALIBRATION:-}"
#: Until version 32 empty was the rule, and the got-it brake stopped the campaign; "record" was
#: asked for by name for one campaign's remaining runs (D26-1). From version 32 every campaign
#: records (D32-1), and a pair is told so by the one word in runs/azure/gotit_brake, so that a
#: campaign its queue starts after a reboot records as well. Asked for by name, it still wins.
GOTIT_BRAKE="${GOTIT_BRAKE:-$(cat runs/azure/gotit_brake 2>/dev/null)}"
LANE="${LANE:-${AZ_PROFILE:-unknown}}"
SYN_PLAN="data/synthetic/constant_r${RATE}_d${DURATION}/replay_plan.csv"
TRACE_BT="runs/azure/runqlat.bt"
#: D28-1: every python3 thread's scheduling events, one line each, for A9's traced runs.
EVENTS_BT="runs/azure/waits.bt"
ALL_CPUS=$(nproc --all)
ME=$(id -un)
#: Freeze 41 (15 Oct 2026): the running boot's own command line, which a setup that names a boot
#: is held to (block I: idle=poll or not).
BOOT_CMDLINE="/proc/cmdline"
#: Freeze 43 (22 Oct 2026): eth0's own address, which the card's capture is pinned to, and the
#: kernel's process files, where a run that asks reads its interrupt counters. The tests point
#: both at files of their own.
ETH0_ADDRESS="/sys/class/net/eth0/address"
PROC_DIR="/proc"
#: Freeze 43 (22 Oct 2026): the process that switches a run's load on and off in blocks, while
#: such a run's trial runs, so that whatever ends the run or the campaign can stop it.
BLOCKS_PID=""

log () { echo "$(date -u +%FT%TZ) $*"; }
broker_delay () {
  remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker \
    --dst $RECEIVER_IP --delay-ms $1 --apply" >/dev/null 2>&1
}
reap () {
  # Freeze 43 (22 Oct 2026): the load's blocks first, so that none starts a stress-ng after the
  # one below is stopped; a campaign stopped in the middle of such a run stops them here.
  stop_load_blocks
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  # A8 runs Kafka's Java client too, and a leftover one would send into the next run's topic.
  pkill -f "LawProducer|LawConsumer" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  sudo pkill -INT -x bpftrace 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}
#: Freeze 41 (15 Oct 2026): RUN_TO_PARITY back on, the kernel's default, after a run whose setup
#: set a scheduler feature, however that run ended, so that the next run starts where the kernel
#: does. A run that names no feature changed none, and nothing is done for it. Where the default
#: cannot be put back, the next run's settings check finds the feature off and fails that run.
features_back () {
  [ -n "${SCHED_FEATURES:-}" ] || return 0
  sudo python3 scripts/sched_settings.py set-feature RUN_TO_PARITY > "$1" 2>&1 \
    || log "RUN_TO_PARITY could not be put back on; the next run's settings check will say so"
}
#: Freeze 42 (22 Oct 2026): the duty corrected a second time, once, with the clients running.
#: The first correction is made before the clients start. Block U's pilot found that clients
#: sending 2,000 messages a second, at real-time priority above all, cost stress-ng more of its
#: duty than they use themselves: 70% asked held 63.3-64.5% with the machine 78-86% busy, so the
#: duty cycle lost the time, not the machine its room. Where the setup asks, this waits ten
#: seconds into the trial, inside its warm-up and before any message is counted, reads the
#: background load the machine shows less the clients' own share (what the integrity rule reads),
#: corrects the duty against it and restarts stress-ng there. What it did is written beside the
#: run. Run in the background by the run that asks for it, which stops it if the trial ends first.
recorrect_load () {
  local run_dir="$1" want="$2" duty="$3" cpus="$4" shown adjusted
  sleep "${RECORRECT_AFTER_S:-10}"
  shown=$(python3 -c 'import csv, statistics, sys
rows = list(csv.DictReader(open(sys.argv[1], newline="", encoding="utf-8")))
bg = []
for r in rows[-6:]:
    try:
        bg.append(float(r["rho"]) - float(r.get("rho_clients") or 0))
    except (KeyError, TypeError, ValueError):
        pass
print("%.2f" % (100 * statistics.fmean(bg)) if bg else "")' "$run_dir/utilisation.csv" 2>/dev/null)
  [ -n "$shown" ] || return 0
  adjusted=$(python3 -c 'import sys
want, shown, duty = (float(x) for x in sys.argv[1:4])
print("%d" % round(min(100.0, max(1.0, duty - (shown - want)))))' "$want" "$shown" "$duty")
  printf '{"designed_pct": %s, "shown_running_pct": %s, "duty_before_pct": %s, "duty_used_pct": %s}\n' \
    "$want" "$shown" "$duty" "$adjusted" > "$run_dir/load_recorrection.json"
  if [ "$adjusted" != "$duty" ]; then
    pkill -9 -x stress-ng 2>/dev/null
    stress-ng --cpu "$cpus" --cpu-load "$adjusted" --timeout 3600s >/dev/null 2>&1 &
  fi
}
#: Freeze 43 (22 Oct 2026): the load switched on and off in blocks within one run, where the setup
#: asks (load_blocks_s). Each TCP connection on these pairs keeps its own fixed delay for its whole
#: life, so two runs differ by their draws of the network as well as by their loads: in block L,
#: Redis's kernel-timed latency at 50 messages a second had run medians of 445, 473, 456 and
#: 854 us idle and 706, 443, 462 and 848 us at 88% load. Within one run the loaded and the
#: unloaded blocks share the same connections. From the trial's start stress-ng runs for a block
#: and stops for a block, beginning on, until the run stops this, and each switch is written to
#: load_blocks.csv with the time it was made, to the nanosecond. A block's stress-ng stops by
#: itself at twice the block's length should anything leave it behind, and no block starts once
#: the campaign that started them is gone.
load_blocks () {
  local run_dir="$1" duty="$2" cpus="$3" block_s="$4" campaign="$$" stress=""
  echo "t_ns,state" > "$run_dir/load_blocks.csv"
  while kill -0 "$campaign" 2>/dev/null; do
    echo "$(date +%s%N),on" >> "$run_dir/load_blocks.csv"
    stress-ng --cpu "$cpus" --cpu-load "$duty" --timeout "$(( 2 * block_s ))s" >/dev/null 2>&1 &
    stress=$!
    sleep "$block_s"
    echo "$(date +%s%N),off" >> "$run_dir/load_blocks.csv"
    kill -9 "$stress" 2>/dev/null; wait "$stress" 2>/dev/null
    pkill -9 -x stress-ng 2>/dev/null
    sleep "$block_s"
  done
}
#: Freeze 43 (22 Oct 2026): the blocks stopped by a signal they cannot decline, then every
#: stress-ng they started, as the end of a run stops its load. A trial that has ended, early or
#: not, leaves no block to start under the next run's setup.
stop_load_blocks () {
  [ -n "$BLOCKS_PID" ] || return 0
  kill -9 "$BLOCKS_PID" 2>/dev/null; wait "$BLOCKS_PID" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  BLOCKS_PID=""
}
#: Freeze 43 (22 Oct 2026): how the kernel schedules the clients' threads and the load's, read
#: once while the clients run, where the setup asks (run_facts): RUN_FACTS_AFTER_S seconds after
#: the trial starts, 15 unless set, inside block U's 20 s warm-up. Run in the background by the run
#: that asks for it, which stops it if the trial ends first.
run_facts_later () {
  sleep "${RUN_FACTS_AFTER_S:-15}"
  python3 scripts/run_facts.py clients --out "$1/run_facts_clients.json" \
    > "$1/run_facts_clients.err" 2>&1
}
finish_campaign () {
  reap
  # A campaign stopped in the middle of such a run is put back here, into no run's folder.
  features_back /dev/null
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
#: Freeze 43 (22 Oct 2026): before|after, where the interrupts and softirqs fell and what the
#: network's receive queues held, as the kernel counts them, in a run whose setup asks
#: (run_facts). Block U's pilot did not record where the network's interrupts ran.
interrupt_counters () {
  cat "$PROC_DIR/interrupts" > "$RUN_DIR/interrupts_$1.txt" 2>&1
  cat "$PROC_DIR/softirqs" > "$RUN_DIR/softirqs_$1.txt" 2>&1
  cat "$PROC_DIR/net/softnet_stat" > "$RUN_DIR/softnet_$1.txt" 2>&1
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
  # Freeze 43 (22 Oct 2026): so does a setup that names one of freeze 43's settings in a form
  # this runner cannot give. stress-ng takes a whole percentage, the blocks a whole number of
  # seconds; a load of 0 starts no stress-ng, so neither a frozen duty nor the blocks can apply
  # to it; and the collector's two switches and the schedstat are the Python clients' own.
  case "${DUTY:-}" in
    ""|[1-9]|[1-9][0-9]|100) ;;
    *) REASON="duty_pct is a whole percentage from 1 to 100, not \"$DUTY\""; return ;;
  esac
  case "${LOAD_BLOCKS:-}" in
    *[!0-9]*|0*) REASON="load_blocks_s is a whole number of seconds of at least one, not \"$LOAD_BLOCKS\""; return ;;
  esac
  if [ -n "${DUTY:-}${LOAD_BLOCKS:-}" ] && [ "$LOAD" = 0 ]; then
    REASON="duty_pct and load_blocks_s set how a load runs, and a load of 0 starts none"; return
  fi
  if [ -n "${GC_OFF:-}${GC_LOG:-}${SCHEDSTAT:-}" ] && [ "${CLIENT:-python}" != python ]; then
    REASON="gc_off, gc_log and schedstat are the Python clients' settings, and this run's client is $CLIENT"; return
  fi
  # Freeze 41 (15 Oct 2026): a setup that asks for what this runner cannot give as written fails
  # here, before it changes anything on the machine. The journal is kept by the socket
  # timestamps, so it needs them; both directions widen the sender's capture, so they need that
  # capture; the send workers are the Redis producer's; and the one scheduler feature a run sets
  # is the one it knows how to put back.
  case "$SO_JOURNAL" in
    ""|1|consumer) ;;
    *) REASON="so_journal is true, for both clients, or \"consumer\", not \"$SO_JOURNAL\""; return ;;
  esac
  if [ -n "$SO_JOURNAL" ] && [ -z "$SO_STAMPS" ]; then
    REASON="so_journal needs so_timestamps: the journal is written by the socket timestamps"; return
  fi
  if [ -n "$SEND_CAPTURE_BOTH" ] && [ -z "$SEND_CAPTURE" ]; then
    REASON="send_capture_both needs send_capture: it widens the sender's capture"; return
  fi
  if [ -n "$SEND_WORKERS" ]; then
    case "$SEND_WORKERS" in
      *[!0-9]*|0*) REASON="send_workers is a whole number of at least one, not \"$SEND_WORKERS\""; return ;;
    esac
    [ "$BACKEND" = redis ] || {
      REASON="send_workers is the Redis producer's setting, and this run is $BACKEND"; return; }
  fi
  case "$SCHED_FEATURES" in
    ""|RUN_TO_PARITY|NO_RUN_TO_PARITY) ;;
    *) REASON="sched_features is RUN_TO_PARITY or NO_RUN_TO_PARITY, not \"$SCHED_FEATURES\""; return ;;
  esac
  # Freeze 41 (15 Oct 2026): block I runs on two boots of the stock kernel, its default and one with
  # idle=poll on the command line (cloud/azure/idle.sh), and a run counts for the boot its setup
  # names only if this boot's own command line says so. Read as idle.sh reads it, as a word.
  if [ -n "$IDLE_POLL" ]; then
    [ -r "$BOOT_CMDLINE" ] || {
      REASON="$BOOT_CMDLINE could not be read, so the boot the setup names cannot be confirmed"; return; }
    local boot_args polls=0
    boot_args=" $(cat "$BOOT_CMDLINE") "
    case "$boot_args" in *" idle=poll "*) polls=1 ;; esac
    if [ "$IDLE_POLL" = 1 ] && [ "$polls" != 1 ]; then
      REASON="the setup asks for idle=poll and this boot's command line does not hold it"; return
    fi
    if [ "$IDLE_POLL" != 1 ] && [ "$polls" != 0 ]; then
      REASON="the setup asks for the default boot and this boot's command line holds idle=poll"; return
    fi
  fi
  sudo python3 scripts/sched_settings.py set-cpus "$want_cpus" > "$RUN_DIR/set_cpus.txt" 2>&1 || {
    REASON="online CPUs did not become $want_cpus"; return; }
  if [ -n "$SLICE_NS" ]; then
    sudo python3 scripts/sched_settings.py set-slice "$SLICE_NS" > "$RUN_DIR/set_slice.txt" 2>&1 || {
      REASON="the base slice did not take $SLICE_NS ns"; return; }
    check_args+=(--slice-ns "$SLICE_NS")
  fi
  # Freeze 41 (15 Oct 2026): block R's runs are made with the scheduler's RUN_TO_PARITY feature on
  # or off, written through debugfs here and held by the checks before and after the run, as the
  # slice is; the default goes back once the run has ended (features_back). Every other run is held
  # to that default wherever the kernel shows its features, so that a feature a crashed run left
  # off fails the next run instead of contaminating it.
  if [ -n "$SCHED_FEATURES" ]; then
    sudo python3 scripts/sched_settings.py set-feature "$SCHED_FEATURES" > "$RUN_DIR/set_feature.txt" 2>&1 || {
      REASON="the scheduler feature $SCHED_FEATURES did not take"; return; }
    check_args+=(--feature "$SCHED_FEATURES")
  else
    check_args+=(--feature-if-known RUN_TO_PARITY)
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

  # Freeze 39 (13 Oct 2026): a load of 0 is idle, with no stress-ng at all, rather than the duty of
  # one percent the correction below would set. The sampler still runs, so the integrity rule
  # holds the measured load to zero within its points. stress_pid is set empty first: the runner
  # treats an unset variable as an error, and an idle run starts nothing to set it.
  stress_pid=""
  # Freeze 43 (22 Oct 2026): at the setup's frozen duty where it names one (duty_pct), and not
  # before the clients at all where the load runs in blocks within the trial (load_blocks_s).
  if [ "$LOAD" != 0 ] && [ -z "${LOAD_BLOCKS:-}" ]; then
    stress-ng --cpu "$want_cpus" --cpu-load "${DUTY:-$LOAD}" --timeout 3600s >/dev/null 2>&1 &
    stress_pid=$!
  fi
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
  local shown="" adjusted
  # Freeze 43 (22 Oct 2026): a duty frozen from the pilot is used as it stands, with no
  # correction here and none once the clients run. Block U's pilot corrected the duty against
  # what the machine showed, and the real-time setups ended at a heavier stress-ng than the
  # normal ones: 76-77 against 72 at 2,000 messages a second. Each setup's duty is now frozen
  # from the pilot and the load runs open-loop; the integrity rule still holds the background
  # the machine shows to the design within its points.
  [ -n "${DUTY:-}" ] && printf '{"designed_pct": %s, "duty_frozen_pct": %s}\n' "$LOAD" "$DUTY" \
    > "$RUN_DIR/load_correction.json"
  [ -n "$stress_pid" ] && [ -z "${DUTY:-}" ] && shown=$(python3 -c 'import csv, statistics, sys
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
  # R1 (3 Oct 2026, exploratory): go-first priority for the consumer alone, so that what it
  # removes from the send-timed latency is the receiving thread's own wait and nothing on the
  # producer's side; and, in every run, the packets as the receiver's kernel took them in, at
  # full length, so that each message's receipt can be timed from the kernel's own timestamp.
  local consumer_wrap="sudo ip netns exec sblrecv sudo -u $ME" recv_full=""
  [ -n "$CONSUMER_PRIORITY" ] && consumer_wrap="sudo chrt -f 80 $consumer_wrap"
  # Freeze 43 (22 Oct 2026): the producer alone at real-time priority where the setup asks
  # (producer_priority), so that only the consumer's priority varies between setups. Under block
  # U's 70% load at 2,000 messages a second, Redis's producer at normal priority sent its messages
  # a median of 24 ms and a 99th percentile of 272 ms after their planned times, so the load
  # changed what the broker was sent as well as how the consumer ran. Left empty where go-first
  # already raises both clients.
  local producer_wrap=""
  [ -n "${PRODUCER_PRIORITY:-}" ] && [ -z "$PRIORITY" ] && producer_wrap="sudo chrt -f 80"
  # Freeze 41 (15 Oct 2026): a 32 MiB capture buffer (tcpdump -B, in KiB) where a setup captures
  # both directions of the sender, or asks for it, so that the kernel drops none of the packets the
  # journal is checked against. It goes after the file name, so each capture's own command line
  # still starts with the pattern that stops it below; every earlier block's captures start
  # exactly as before.
  local capture_buffer=()
  if [ -n "$SEND_CAPTURE_BOTH" ] || [ -n "$CAPTURE_BUFFER" ]; then capture_buffer=(-B 32768); fi
  if [ -n "$RECV_CAPTURE" ]; then
    sudo ip netns exec sblrecv tcpdump -i any -s 0 --time-stamp-precision=nano \
      -w "$RUN_DIR/receiver_full.pcap" "${capture_buffer[@]}" host "$BROKER_PRIV" \
      > "$RUN_DIR/receiver_full.err" 2>&1 &
    recv_full=$!
    sleep 2
  fi
  # Freeze 39 (13 Oct 2026): the producer's packets as the driver's kernel sends them, at full
  # length and to the nanosecond, so that each message's departure is timed from the kernel's own
  # timestamp as R1 timed its arrival. The driver's own connections to the broker, the commands
  # this script sends it over ssh, are left out.
  # Freeze 41 (15 Oct 2026): block K keeps the broker's packets to the driver as well, the
  # acknowledgments among them, so that the journal's t_rx_ack can be checked against the arrival
  # the capture saw. Still the driver's own traffic with the broker, and still without ssh.
  local send_full="" send_filter=(src host "$DRIVER_PRIV" and dst host "$BROKER_PRIV" and not port 22)
  if [ -n "$SEND_CAPTURE_BOTH" ]; then
    send_filter=(host "$DRIVER_PRIV" and host "$BROKER_PRIV" and not port 22)
  fi
  if [ -n "$SEND_CAPTURE" ]; then
    sudo tcpdump -i eth0 -s 0 --time-stamp-precision=nano -w "$RUN_DIR/sender_full.pcap" \
      "${capture_buffer[@]}" "${send_filter[@]}" > "$RUN_DIR/sender_full.err" 2>&1 &
    send_full=$!
    sleep 2
  fi
  # Freeze 39 (13 Oct 2026), described and not judged: the receiver's packets as the network card
  # stamped them on its own clock, on the accelerated-networking device that carries them, and
  # that clock sampled against the system's twice a second, so that each stamp can be put on the
  # system's clock. What the card saw first and the kernel stamped later is the kernel's own delay,
  # the part of the host the kernel's timestamp keeps.
  # Freeze 42 (22 Oct 2026): where the setup takes the larger buffer, the card's capture takes it
  # too, after the file name as the others do: block U runs it on a loaded driver at 2,000 messages
  # a second, and a packet dropped from a capture leaves every later byte of its stream unread.
  local hw_full="" hw_clock="" hw_dev=""
  if [ -n "$HW_CAPTURE" ]; then
    # Freeze 43 (22 Oct 2026): the device is the SLAVE that carries eth0's own address, no longer
    # the first SLAVE `ip -br link` lists, so that a second device, or the kernel listing them in
    # another order, cannot put the capture on a card that does not carry the receiver's packets.
    # Where none carries eth0's address, nothing is captured, as on a machine with no card.
    local eth0_mac
    eth0_mac=$(cat "$ETH0_ADDRESS" 2>/dev/null)
    hw_dev=$(ip -br link | awk -v mac="$eth0_mac" \
      'mac != "" && $4 ~ /SLAVE/ && tolower($3) == tolower(mac) {print $1; exit}')
    [ -n "$hw_dev" ] && hw_clock=$(sudo ethtool -T "$hw_dev" 2>/dev/null \
      | awk '/PTP Hardware Clock:/ && $4 ~ /^[0-9]+$/ {print "/dev/ptp" $4}')
    echo "${hw_dev:-none} ${hw_clock:-none}" > "$RUN_DIR/hw_device.txt"
    if [ -n "$hw_clock" ]; then
      sudo tcpdump -i "$hw_dev" -j adapter_unsynced -s 0 --time-stamp-precision=nano \
        -w "$RUN_DIR/receiver_hw.pcap" "${capture_buffer[@]}" src host "$BROKER_PRIV" \
        and dst host "$RECEIVER_IP" > "$RUN_DIR/receiver_hw.err" 2>&1 &
      hw_full=$!
      sudo python3 scripts/phc_offset.py --device "$hw_clock" --interval 0.5 \
        --out "$RUN_DIR/phc_offset.csv" > "$RUN_DIR/phc_offset.err" 2>&1 &
      sleep 2
    fi
  fi
  # Freeze 42 (22 Oct 2026): the broker's own capture of its port, both directions, at full length
  # and to the nanosecond, on the broker's clock: when each request reached the broker and when
  # each answer left it, so that the broker's own time can be split from the client's without the
  # two machines' clocks ever meeting. A capture a crashed run left behind is stopped by its own id
  # first, so no two write one file; the larger buffer keeps the kernel from dropping packets.
  local broker_full="" broker_port="${KAFKA_BOOTSTRAP##*:}"
  [ "$BACKEND" = redis ] && broker_port="$REDIS_PORT"
  if [ -n "$BROKER_CAPTURE" ]; then
    remote_broker "sudo sh -c 'kill -INT \$(cat /tmp/sbl_bfull.pid 2>/dev/null) 2>/dev/null; rm -f /tmp/sbl_bfull.pcap /tmp/sbl_bfull.err; nohup tcpdump -i eth0 -s 0 --time-stamp-precision=nano -B 32768 -w /tmp/sbl_bfull.pcap tcp port $broker_port > /tmp/sbl_bfull.err 2>&1 & echo \$! > /tmp/sbl_bfull.pid'" \
      > /dev/null 2>&1 && broker_full=1
    sleep 2
  fi
  chronyc -c tracking > "$RUN_DIR/clock_before.txt" 2>/dev/null
  head -n 1 /proc/stat > "$RUN_DIR/stat_before.txt"
  tcp_counters before
  # Freeze 43 (22 Oct 2026): where the setup asks (run_facts), the interrupt counters and the
  # machine's own facts before the clients start: which CPUs the card's interrupts may and do run
  # on, the kernel's preemption and accounting options and real-time throttle, and stress-ng's
  # version and command lines (scripts/run_facts.py).
  if [ -n "${RUN_FACTS:-}" ]; then
    interrupt_counters before
    python3 scripts/run_facts.py host --out "$RUN_DIR/run_facts.json" > "$RUN_DIR/run_facts.err" 2>&1
  fi
  # Freeze 40 (14 Oct 2026): the clients read the kernel's own timestamps on their connections to
  # the broker through SO_TIMESTAMPING, each into its own file beside the run (so_timestamps.py),
  # with the transmit timestamp taken where the row says.
  local so_prod="" so_cons=""
  if [ -n "$SO_STAMPS" ]; then
    so_prod="--so-timestamps $RUN_DIR/producer_so.csv --so-transmit $SO_STAMPS"
    so_cons="--so-timestamps $RUN_DIR/consumer_so.csv --so-transmit $SO_STAMPS"
    # Freeze 41 (15 Oct 2026): and, where the setup asks, every read and write those connections
    # make, with their kernel timestamps, under a path stem beside the run: both clients' for
    # blocks K, R and I, the consumer's alone for block L.
    [ "$SO_JOURNAL" = 1 ] && so_prod="$so_prod --so-journal $RUN_DIR/producer_journal"
    [ -n "$SO_JOURNAL" ] && so_cons="$so_cons --so-journal $RUN_DIR/consumer_journal"
  fi
  # Freeze 43 (22 Oct 2026): the clients' own garbage collector, and the consumer's waits for a
  # core. In block U's pilot, leaving out the 0.25-0.53% of messages delivered after a consumer
  # turnaround of more than 10 ms lowered the kernel-timed latency's 99th percentile by 4-16%.
  # Where the setup asks, each client freezes what it holds once it has connected and turns its
  # collector off (gc_off), or keeps it on and logs every collection (gc_log), each into its own
  # file beside the run, which tells whether CPython's collections make those long turnarounds;
  # and the consumer samples its main thread's schedstat before each request (schedstat), so that
  # each turnaround splits into the time it ran and the time it waited for a core. A setup that
  # asks for none hands the clients exactly what freeze 42 did.
  local prod_flags="" cons_flags=""
  if [ -n "${GC_OFF:-}" ]; then
    prod_flags=" --gc-off --gc-log $RUN_DIR/producer_gc.json"
    cons_flags=" --gc-off --gc-log $RUN_DIR/consumer_gc.json"
  elif [ -n "${GC_LOG:-}" ]; then
    prod_flags=" --gc-log $RUN_DIR/producer_gc.json"
    cons_flags=" --gc-log $RUN_DIR/consumer_gc.json"
  fi
  [ -n "${SCHEDSTAT:-}" ] && cons_flags="$cons_flags --schedstat $RUN_DIR/consumer_schedstat.csv"
  began=$(date -u +%s)
  local recorrect_pid=""
  if [ -n "${LOAD_RECORRECT:-}" ] && [ -n "${stress_pid:-}" ]; then
    recorrect_load "$RUN_DIR" "$LOAD" "${adjusted:-$LOAD}" "$want_cpus" &
    recorrect_pid=$!
  fi
  # Freeze 43 (22 Oct 2026): the load's blocks from the trial's start, at the frozen duty where
  # the setup names one, and the clients' facts once they run; each in the background, and each
  # stopped once the trial ends.
  if [ -n "${LOAD_BLOCKS:-}" ]; then
    load_blocks "$RUN_DIR" "${DUTY:-$LOAD}" "$want_cpus" "$LOAD_BLOCKS" &
    BLOCKS_PID=$!
  fi
  local facts_pid=""
  if [ -n "${RUN_FACTS:-}" ]; then
    run_facts_later "$RUN_DIR" &
    facts_pid=$!
  fi
  if [ "$BACKEND" = kafka ]; then
    client_args=()
    [ -n "${CLIENT:-}" ] && client_args+=(-CLIENT "$CLIENT")
    [ -n "${ACK_STAMP:-}" ] && client_args+=(-ACK_STAMP "$ACK_STAMP")
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_kafka_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
      -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA $record_args $so_prod$prod_flags" \
      -CONSUMER_EXTRA "$record_args $read_args $so_cons$cons_flags" \
      -IDLE_SECONDS 15 "${client_args[@]}" > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  else
    # Freeze 41 (15 Oct 2026): block K's two one-worker setups send through one XADD worker instead
    # of the producer's sixteen; a setup that names no count keeps the producer's own.
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_redis_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
      -PRODUCER_EXTRA "$record_args $so_prod${SEND_WORKERS:+ --send-workers $SEND_WORKERS}$prod_flags" \
      -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA${ACK_BATCH:+ --ack-batch $ACK_BATCH} $record_args $so_cons$cons_flags" \
      -IDLE_SECONDS 15 > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  fi
  ended=$(date -u +%s)
  # A trial that ended before the second correction came due must not have stress-ng restarted
  # after it, under the next run's setup.
  if [ -n "$recorrect_pid" ]; then kill "$recorrect_pid" 2>/dev/null; wait "$recorrect_pid" 2>/dev/null; fi
  # Freeze 43 (22 Oct 2026): nor may a block of load start after it, and the clients' facts are
  # read while the clients run or not at all.
  stop_load_blocks
  if [ -n "$facts_pid" ]; then kill "$facts_pid" 2>/dev/null; wait "$facts_pid" 2>/dev/null; fi
  head -n 1 /proc/stat > "$RUN_DIR/stat_after.txt"
  chronyc -c tracking > "$RUN_DIR/clock_after.txt" 2>/dev/null
  tcp_counters after
  [ -z "${RUN_FACTS:-}" ] || interrupt_counters after
  container=redis
  [ "$BACKEND" = kafka ] && container=broker
  remote_broker "docker logs --timestamps --since $began --until $(( ended + 1 )) $container" \
    > "$RUN_DIR/broker_log.txt" 2>&1

  if [ -n "$recv_full" ]; then
    # Stopped by its own command line, as M0's capture below is, for the reasons given there.
    sudo pkill -INT -f "[t]cpdump -i any -s 0 --time-stamp-precision=nano -w $RUN_DIR/receiver_full.pcap" 2>/dev/null
    for _ in $(seq 1 20); do ps -p "$recv_full" > /dev/null || break; sleep 0.5; done
    sudo pkill -KILL -f "[t]cpdump -i any -s 0 --time-stamp-precision=nano -w $RUN_DIR/receiver_full.pcap" 2>/dev/null
    wait "$recv_full" 2>/dev/null
  fi
  if [ -n "$hw_full" ]; then
    # Stopped by their own command lines, as the captures below are.
    sudo pkill -INT -f "[t]cpdump -i $hw_dev -j adapter_unsynced -s 0 --time-stamp-precision=nano -w $RUN_DIR/receiver_hw.pcap" 2>/dev/null
    sudo pkill -INT -f "[p]hc_offset.py --device $hw_clock --interval 0.5 --out $RUN_DIR/phc_offset.csv" 2>/dev/null
    for _ in $(seq 1 20); do ps -p "$hw_full" > /dev/null || break; sleep 0.5; done
    sudo pkill -KILL -f "[t]cpdump -i $hw_dev -j adapter_unsynced -s 0 --time-stamp-precision=nano -w $RUN_DIR/receiver_hw.pcap" 2>/dev/null
    wait "$hw_full" 2>/dev/null
  fi
  if [ -n "$send_full" ]; then
    # Stopped by its own command line, as the receiver's capture above is.
    sudo pkill -INT -f "[t]cpdump -i eth0 -s 0 --time-stamp-precision=nano -w $RUN_DIR/sender_full.pcap" 2>/dev/null
    for _ in $(seq 1 20); do ps -p "$send_full" > /dev/null || break; sleep 0.5; done
    sudo pkill -KILL -f "[t]cpdump -i eth0 -s 0 --time-stamp-precision=nano -w $RUN_DIR/sender_full.pcap" 2>/dev/null
    wait "$send_full" 2>/dev/null
  fi
  if [ -n "$broker_full" ]; then
    # Stopped by its own id, then waited for, so that tcpdump has written its last packets and its
    # count of drops before either file is copied back into the run's folder.
    remote_broker "sudo kill -INT \$(cat /tmp/sbl_bfull.pid) 2>/dev/null; for _ in \$(seq 1 40); do sudo kill -0 \$(cat /tmp/sbl_bfull.pid) 2>/dev/null || break; sleep 0.5; done" \
      > /dev/null 2>&1
    remote_broker "sudo cat /tmp/sbl_bfull.pcap" > "$RUN_DIR/broker_full.pcap" 2>/dev/null
    remote_broker "sudo cat /tmp/sbl_bfull.err; sudo rm -f /tmp/sbl_bfull.pcap /tmp/sbl_bfull.err /tmp/sbl_bfull.pid" \
      > "$RUN_DIR/broker_full.err" 2>/dev/null
  fi
  if [ -n "$receiver_capture" ]; then
    # Stopped by its own command line, not through the sudo that started it: sudo does not relay
    # a signal sent from its own process group, so `sudo kill -INT <that sudo>` never reached
    # tcpdump, and the wait held M0's first recorded run for six hours on 26 September. The [t]
    # keeps the pattern from matching the command line of the sudo that runs pkill, which holds
    # the pattern itself: written plainly, the forced stop killed that sudo, and every one of R1's
    # 53 runs logged it (3 October).
    sudo pkill -INT -f "[t]cpdump -i any -s 200 -w $RUN_DIR/receiver.pcap" 2>/dev/null
    for _ in $(seq 1 20); do ps -p "$receiver_capture" > /dev/null || break; sleep 0.5; done
    sudo pkill -KILL -f "[t]cpdump -i any -s 200 -w $RUN_DIR/receiver.pcap" 2>/dev/null
    wait "$receiver_capture" 2>/dev/null
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

#: Freeze 43 (22 Oct 2026): one unjudged trial on each broker, Kafka then Redis, before the
#: queue's first run, where the campaign's job line asks (PRIME_S). Every session starts both
#: brokers afresh, and block U's pilot found its first run after a broker start contaminated:
#: Kafka made its __consumer_offsets topic during it, and the broker's log for that run ran to
#: 314 lines against 11 for a later one. Each trial runs the campaign's plan at its rate for
#: PRIME_S seconds, idle and with no capture, the consumer behind the receiver's address as in
#: every run and each client with the campaign's own settings, into a folder of its own that
#: nothing reads. Whatever a trial exits with, the campaign carries on.
prime_brokers () {
  local backend prime_id rc
  for backend in kafka redis; do
    reap
    prime_id="law_${QUEUE_NAME}_prime_${backend}_$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "runs/$prime_id"
    if [ "$backend" = kafka ]; then
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_kafka_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
        -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA" -IDLE_SECONDS 15 > "runs/$prime_id/trial.log" 2>&1
    else
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_redis_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
        -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA" -IDLE_SECONDS 15 > "runs/$prime_id/trial.log" 2>&1
    fi
    rc=$?
    log "PRIME $backend: runs/$prime_id exit $rc"
  done
}

# --- the queue -------------------------------------------------------------------------------
case "$GOTIT_BRAKE" in
  ""|stop|record) ;;
  *) log "FATAL: the got-it brake either stops or records, not \"$GOTIT_BRAKE\""; exit 1 ;;
esac
# Freeze 43 (22 Oct 2026): the priming trials replay the campaign's own plan, which runs for
# DURATION seconds, so PRIME_S is a whole number of seconds within it.
case "$PRIME_S" in
  "") ;;
  *[!0-9]*|0*) log "FATAL: PRIME_S is a whole number of seconds of at least one, not \"$PRIME_S\""; exit 1 ;;
  *) [ "$PRIME_S" -le "$DURATION" ] || {
       log "FATAL: PRIME_S is at most the plan's $DURATION s, not $PRIME_S"; exit 1; } ;;
esac
log "campaign: $QUEUE on lane $LANE; plan $SYN_PLAN at speedup $SPEEDUP; warm-up ${WARMUP_S} s; $ALL_CPUS CPUs${CALIBRATION:+; calibration $CALIBRATION}${GOTIT_BRAKE:+; the got-it brake: $GOTIT_BRAKE (D26-1, D32-1)}${PRIME_S:+; each broker primed for $PRIME_S s first}"
[ -z "$PRIME_S" ] || prime_brokers
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
    # R1 (3 Oct 2026): go-first for the consumer alone, and the receiver's packets in every run.
    "CONSUMER_PRIORITY": "1" if p.get("consumer_priority") else "",
    "RECV_CAPTURE": "1" if p.get("recv_capture") else "",
    # Freeze 39 (13 Oct 2026): the producer's packets as well, in every run of its block.
    "SEND_CAPTURE": "1" if p.get("send_capture") else "",
    "HW_CAPTURE": "1" if p.get("hw_capture") else "",
    # Freeze 40 (14 Oct 2026): where the clients' socket timestamps take the transmit time, or none.
    "SO_STAMPS": str(p.get("so_timestamps") or ""),
    # Freeze 41 (15 Oct 2026): the clients' journal of their broker connections (true for both,
    # "consumer" for the consumer alone); both directions of the sender's capture; the larger
    # capture buffer; the Redis producer's send workers; the scheduler feature the run is made
    # under; and the boot it needs, with idle=poll (1) or without (0). A row that names none of
    # them leaves all six empty, and its run is launched exactly as before.
    "SO_JOURNAL": "1" if p.get("so_journal") is True else str(p.get("so_journal") or ""),
    "SEND_CAPTURE_BOTH": "1" if p.get("send_capture_both") else "",
    "CAPTURE_BUFFER": "1" if p.get("capture_buffer") else "",
    "SEND_WORKERS": "" if p.get("send_workers") is None else str(p["send_workers"]),
    "SCHED_FEATURES": str(p.get("sched_features") or ""),
    "IDLE_POLL": "" if p.get("idle_poll") is None else ("1" if p["idle_poll"] else "0"),
    # Freeze 42 (22 Oct 2026): the broker's own capture of its port, and the duty corrected a
    # second time with the clients running, where the setup asks for either.
    "BROKER_CAPTURE": "1" if p.get("broker_capture") else "",
    # Freeze 43 (22 Oct 2026): never where the duty is frozen or the load runs in blocks, so that
    # a row naming either with it runs, and is logged, without the second correction.
    "LOAD_RECORRECT": "1" if (p.get("load_recorrect") and p.get("duty_pct") is None
                              and p.get("load_blocks_s") is None) else "",
    # Freeze 43 (22 Oct 2026): the producer alone at real-time priority; the clients' collector
    # off, or on and logged; the consumer's schedstat; the duty frozen from the pilot; the load in
    # on and off blocks of this many seconds; and the run's interrupt and scheduler facts. A row
    # that names none of them leaves all seven empty, and its run is launched exactly as before.
    "PRODUCER_PRIORITY": "1" if p.get("producer_priority") else "",
    "GC_OFF": "1" if p.get("gc_off") else "",
    "GC_LOG": "1" if p.get("gc_log") else "",
    "SCHEDSTAT": "1" if p.get("schedstat") else "",
    "DUTY": "" if p.get("duty_pct") is None else str(p["duty_pct"]),
    "LOAD_BLOCKS": "" if p.get("load_blocks_s") is None else str(p["load_blocks_s"]),
    "RUN_FACTS": "1" if p.get("run_facts") else "",
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
  log "run $KEY: $BACKEND, load $LOAD%, slice ${SLICE_NS:-kernel default}, delay $DELAY_MS ms${PRIORITY:+, go-first}${CONSUMER_PRIORITY:+, go-first consumer}${RECV_CAPTURE:+, receiver capture}${SEND_CAPTURE:+, sender capture}${HW_CAPTURE:+, card capture}${SO_STAMPS:+, socket timestamps ($SO_STAMPS)}${SO_JOURNAL:+, journal=$SO_JOURNAL}${SEND_CAPTURE_BOTH:+, both directions of the sender}${SEND_WORKERS:+, $SEND_WORKERS send workers}${SCHED_FEATURES:+, $SCHED_FEATURES}${IDLE_POLL:+, idle_poll=$IDLE_POLL}${BROKER_CAPTURE:+, broker capture}${LOAD_RECORRECT:+, the load corrected again with the clients running}${PRODUCER_PRIORITY:+, go-first producer}${GC_OFF:+, collectors off}${GC_LOG:+, collections logged}${SCHEDSTAT:+, consumer schedstat}${DUTY:+, duty frozen at $DUTY%}${LOAD_BLOCKS:+, load in $LOAD_BLOCKS s blocks}${RUN_FACTS:+, run facts}${CPUS:+, $CPUS CPUs online}"
  REASON=""
  STOP_REASON=""
  run_one
  features_back "$RUN_DIR/feature_back.txt"
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
