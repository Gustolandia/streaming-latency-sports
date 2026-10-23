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
#
# Plan version 47 (23 Oct 2026): a setup may also name
#   backend          nats or rabbitmq, beside kafka and redis (scripts/run_nats_trial.sh and
#                    scripts/run_rabbitmq_trial.sh), each primed too where the queue holds one;
#   consumer         Kafka's consumer alone, kafka_producer.py sending in every run: kafka-python
#                    (the default), confluent, java or franz; Redis's: redis-py (the default) or
#                    waiting; NATS's: python (the default) or nats-go;
#   depth, one_reply_reads   the requests the waiting consumers keep at the broker, and whether
#                    each read takes one reply (NATS's python consumer, and Redis's waiting one);
#                    prefetch, RabbitMQ's; ack_batch, the Redis and RabbitMQ consumers';
#   fetch_rt         each thread the consumer names as sending its fetches at real-time
#                    priority, once it has written its thread list and before any message is sent;
#   arrival          constant (the default) or poisson, the plan drawn from PLAN_SEED, set on the
#                    job line as RATE and DURATION are (12345 unless set);
#   whole_core       the consumer alone on the first thread of one core, every other process the
#                    run starts kept off both of the core's threads, and the load on every other
#                    CPU; sibling_load, the load on the core's other threads as well;
#   irq_cpus         the CPUs the receiver card's interrupts are given for the run: a list, or
#                    "core", the first thread of the core whole_core would keep, with or without
#                    it; irqbalance_off, irqbalance stopped for the run; rps_off, no receive
#                    packet steering on the receiver's queues for the run. What each moves is
#                    recorded before, as set and after, and put back once the run ends;
#   load_kind        cpu (the default, stress-ng's CPU stressor), sock (its socket stressor over
#                    loopback) or udp (its UDP stressor over loopback, on the CPUs that take the
#                    card's interrupts), the last two heavy in softirq work and held at the duty.
# A row that names none of them is launched exactly as before. The values the settings run with
# are set in one place, below (NATS_STORAGE ... RECEIVER_LINK).
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
#: Plan version 47 (23 Oct 2026): the seed a Poisson plan is drawn from, for every run of the
#: campaign that asks for one (arrival poisson), so that its setups replay one draw of arrivals and
#: differ in nothing else; make_synthetic_plan.py's own default unless the job line sets it.
PLAN_SEED="${PLAN_SEED:-12345}"
POISSON_PLAN="data/synthetic/poisson_r${RATE}_d${DURATION}_s${PLAN_SEED}/replay_plan.csv"
POISSON_SPEEDUP=""
#: Plan version 47 (23 Oct 2026): the values its settings run with, each set here and nowhere
#: else, so that one the pilot finds wrong is changed in one place. The job line may set any of
#: them, as it sets RATE and DURATION.
#:   NATS_STORAGE         where block N's streams keep their messages: memory, or file
#:                        (cloud/campaigns/common.sh, beside NATS's address)
#:   THREADS_WAIT_S       how long a consumer that names its threads has to write its list
#:   FETCH_RT_PRIORITY    the SCHED_FIFO priority each fetch thread is raised to (fetch_rt)
#:   DUTY_PERIOD_MS       the period a socket load's duty is a share of (scripts/duty_cycle.py)
#:   UDP_WORKERS_PER_CPU  stress-ng --udp workers on each CPU that takes the card's interrupts
#:   RECEIVER_LINK        the receiver's own interface in its namespace (receiver_delay.py)
#: NATS's durable consumer is made with room for at least twice its depth; that rule is the
#: client's own (scripts/nats_consumer.py), and the integrity rule holds each run to it.
THREADS_WAIT_S="${THREADS_WAIT_S:-60}"
FETCH_RT_PRIORITY="${FETCH_RT_PRIORITY:-80}"
DUTY_PERIOD_MS="${DUTY_PERIOD_MS:-100}"
UDP_WORKERS_PER_CPU="${UDP_WORKERS_PER_CPU:-1}"
RECEIVER_LINK="sblrecv0"
#: Plan version 47 (23 Oct 2026): what a run has placed, each set by the run that places it and
#: put back by placement_back once the run ends, however it ended: the consumer's CPU and the
#: load's (whole_core); the campaign's own CPUs before the run kept every process it starts off
#: the consumer's core; the record of where the card's interrupts were before they were moved
#: (irq_cpus), and of the receive queues' steering before it was turned off (rps_off); and
#: whether irqbalance was stopped (irqbalance_off).
CORE_CPU=""
LOAD_TASKSET=""
LOAD_CPUS=""
KIT_MASK_BEFORE=""
IRQS_MOVED=""
RPS_MOVED=""
IRQBALANCE_STOPPED=""
#: Plan version 47 (23 Oct 2026): Java 17, which the java consumer's classes are built for (bash
#: cloud/azure/tools.sh clients). Java 11 stays the driver's default for the tools block, so a run
#: whose consumer is java is handed this one by SBL_JAVA, unless the job line names its own.
JAVA17_BIN="/usr/lib/jvm/java-17-openjdk-$(dpkg --print-architecture 2>/dev/null)/bin/java"

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
  # Plan version 47 (23 Oct 2026): its clients, each by a word of its own command line (none is
  # found by the patterns above), the wait on the consumer's thread list, and the socket load's
  # duty cycle, which would otherwise go on stopping and starting a stress-ng the next run starts.
  pkill -f "kafka_consumer_confluent.py|kafka_producer_confluent.py|franz-consumer|natsgo-consumer" 2>/dev/null
  pkill -f "redis_consumer_waiting.py|nats_producer.py|nats_consumer.py" 2>/dev/null
  pkill -f "rabbitmq_producer.py|rabbitmq_consumer.py|consumer_threads.py|duty_cycle.py" 2>/dev/null
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
#: Plan version 47 (23 Oct 2026): what a run placed, put back once it has ended, however it ended,
#: each from the record taken before it was moved, into the run's folder ($1): the campaign's own
#: CPUs, the receive queues' steering, the card's interrupts, and then irqbalance, which would
#: otherwise move the interrupts again as it started. A run that placed nothing changed nothing,
#: and nothing is done for it.
placement_back () {
  if [ -n "${KIT_MASK_BEFORE:-}" ]; then
    taskset -pc "$KIT_MASK_BEFORE" $$ > "$1/kit_mask_restored.txt" 2>&1 \
      || log "the campaign's own CPUs could not be put back to $KIT_MASK_BEFORE"
    KIT_MASK_BEFORE=""
  fi
  if [ -n "${RPS_MOVED:-}" ]; then
    { sudo python3 scripts/cpu_placement.py rps --restore "$RPS_MOVED/rps_before.json" \
        --out "$1/rps_restored.json" \
      && sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps \
        --restore "$RPS_MOVED/rps_receiver_before.json" --out "$1/rps_receiver_restored.json"; } \
      > /dev/null 2>&1 || log "the receive queues' steering could not be put back as $RPS_MOVED recorded it"
    RPS_MOVED=""
  fi
  if [ -n "${IRQS_MOVED:-}" ]; then
    sudo python3 scripts/cpu_placement.py irqs --restore "$IRQS_MOVED" \
      --out "$1/irq_affinity_restored.json" > /dev/null 2>&1 \
      || log "the receiver card's interrupts could not be put back as $IRQS_MOVED recorded them"
    IRQS_MOVED=""
  fi
  if [ -n "${IRQBALANCE_STOPPED:-}" ]; then
    sudo systemctl start irqbalance > /dev/null 2>&1 || log "irqbalance could not be started again"
    systemctl is-active irqbalance > "$1/irqbalance_restored.txt" 2>&1
    IRQBALANCE_STOPPED=""
  fi
}
#: Plan version 47 (23 Oct 2026): the load, in the background, at a duty, on a number of CPUs,
#: stopping by itself after a time; `$!` is then its process. stress-ng's CPU stressor, as every
#: block before has run it (load_kind cpu); or, held at the duty by scripts/duty_cycle.py since
#: only the CPU stressor takes a duty of its own (--cpu-load), its socket stressor over loopback
#: (sock) or its UDP stressor over loopback (udp), each heavy in the kernel's network softirq.
#: One CPU stressor or socket pair a CPU, and UDP_WORKERS_PER_CPU UDP pairs. On every CPU it is
#: given, or on LOAD_CPUS of them, LOAD_TASKSET, where the run places its load: away from the
#: consumer's core (whole_core), or on the CPUs that take the card's interrupts (udp).
load_start () {
  local duty="$1" cpus="${LOAD_CPUS:-$2}" timeout="$3" taskset=()
  [ -n "${LOAD_TASKSET:-}" ] && taskset=(--taskset "$LOAD_TASKSET")
  case "${LOAD_KIND:-}" in
    sock)
      python3 scripts/duty_cycle.py --duty "$duty" --period-ms "$DUTY_PERIOD_MS" -- \
        stress-ng --sock "$cpus" "${taskset[@]}" --timeout "$timeout" >/dev/null 2>&1 & ;;
    udp)
      python3 scripts/duty_cycle.py --duty "$duty" --period-ms "$DUTY_PERIOD_MS" -- \
        stress-ng --udp "$(( cpus * UDP_WORKERS_PER_CPU ))" "${taskset[@]}" --timeout "$timeout" \
        >/dev/null 2>&1 & ;;
    *)
      stress-ng --cpu "$cpus" --cpu-load "$duty" "${taskset[@]}" --timeout "$timeout" \
        >/dev/null 2>&1 & ;;
  esac
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
    load_start "$adjusted" "$cpus" 3600s
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
    load_start "$duty" "$cpus" "$(( 2 * block_s ))s"
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
  placement_back "${RUN_DIR:-runs/azure}"
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

# Plan version 47 (23 Oct 2026): what the queue's runs need beyond Kafka and Redis, asked of the
# machines before the first run: each broker it names answering as its runs will reach it, each
# consumer it names installed, and its Poisson plan drawn. A run that found one missing would
# fail, and so would every attempt after it, until the guard stopped the campaign.
queue_says () {  # the values one parameter takes over the queue's rows, as words
  python3 -c 'import csv, json, sys
rows = csv.DictReader(open(sys.argv[1], encoding="utf-8"))
said = {json.loads(r["params"]).get(sys.argv[2]) for r in rows}
print(" ".join(sorted(str(v) for v in said if v not in (None, "", False))))' "$QUEUE" "$1"
}
QUEUE_BACKENDS=$(queue_says backend)
QUEUE_CONSUMERS=$(queue_says consumer)
QUEUE_ARRIVALS=$(queue_says arrival)
case " $QUEUE_BACKENDS " in
  *" rabbitmq "*)
    echo "$CONTAINERS" | grep -q "^rabbitmq:running" || {
      log "FATAL: rabbitmq is not running on the broker; run sudo bash cloud/brokers.sh there"; exit 1; }
    python3 -c 'import pika' 2>/dev/null || {
      log "FATAL: pika is not installed; run bash cloud/azure/tools.sh clients"; exit 1; } ;;
esac
case " $QUEUE_BACKENDS " in
  *" nats "*)
    # Asked as the clients ask it: the server's first line, its INFO, read from here. The tools
    # block's own NATS listens on the same port with JetStream off, and every client of block N
    # needs JetStream.
    NATS_SAYS=$(python3 - "$NATS_HOST" "$NATS_PORT" <<'PY'
import json, socket, sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), 5) as sock:
        sock.settimeout(5)
        line = sock.makefile("rb").readline().decode("utf-8", "replace")
except OSError as exc:
    print("no answer: %s" % exc)
    sys.exit(1)
info = json.loads(line.split(" ", 1)[1]) if line.startswith("INFO ") else {}
print("nats-server %s, JetStream %s" % (info.get("version"), "on" if info.get("jetstream") else "off"))
sys.exit(0 if info.get("jetstream") is True else 1)
PY
) || { log "FATAL: no NATS server with JetStream answers at $NATS_HOST:$NATS_PORT ($NATS_SAYS); run sudo bash cloud/brokers.sh there"; exit 1; }
    log "nats: $NATS_SAYS at $NATS_HOST:$NATS_PORT" ;;
esac
for consumer in $QUEUE_CONSUMERS; do
  case "$consumer" in
    confluent)
      python3 -c 'import confluent_kafka' 2>/dev/null || {
        log "FATAL: confluent-kafka is not installed; run bash cloud/azure/tools.sh clients"; exit 1; } ;;
    java)
      # The consumer's classes are built by Java 17, and run by the Java that runs this self test,
      # which needs no broker.
      export SBL_JAVA="${SBL_JAVA:-$JAVA17_BIN}"
      "$SBL_JAVA" -cp harness/java/out LawSelfTest > runs/azure/java_selftest.txt 2>&1 || {
        log "FATAL: $SBL_JAVA cannot run harness/java/out (runs/azure/java_selftest.txt); run bash cloud/azure/tools.sh clients"
        exit 1; } ;;
    franz)
      [ -x harness/go/out/franz-consumer ] || {
        log "FATAL: harness/go/out/franz-consumer is not built; run bash cloud/azure/tools.sh clients"; exit 1; } ;;
    nats-go)
      [ -x harness/go-nats/out/natsgo-consumer ] || {
        log "FATAL: harness/go-nats/out/natsgo-consumer is not built; run bash cloud/azure/tools.sh clients"; exit 1; } ;;
  esac
done
case " $QUEUE_ARRIVALS " in
  *" poisson "*)
    case "$PLAN_SEED" in
      *[!0-9]*|0?*) log "FATAL: PLAN_SEED is a whole number, not \"$PLAN_SEED\""; exit 1 ;;
    esac
    [ -f "$POISSON_PLAN" ] || python3 scripts/make_synthetic_plan.py --arrival poisson \
      --rate "$RATE" --duration "$DURATION" --seed "$PLAN_SEED" --out "$POISSON_PLAN" || {
      log "FATAL: could not make the plan $POISSON_PLAN"; exit 1; }
    POISSON_SPEEDUP=$(assert_plan_rate "$POISSON_PLAN" 1) || {
      log "FATAL: no speedup for $POISSON_PLAN"; exit 1; }
    log "poisson plan: $POISSON_PLAN, drawn from seed $PLAN_SEED, at speedup $POISSON_SPEEDUP" ;;
esac

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
  # Plan version 47 (23 Oct 2026): and read: each CPU's time_squeeze, softnet_stat's third column,
  # and each ksoftirqd thread's own time, which no counter above keeps (scripts/run_facts.py).
  python3 scripts/run_facts.py --root "${PROC_DIR%/proc}/" softirq \
    --out "$RUN_DIR/softirq_$1.json" > /dev/null 2>&1
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
  # Plan version 47 (23 Oct 2026): so does a setup that names one of version 47's settings in a
  # form this runner cannot give, or for a broker or a consumer that does not take it. Each would
  # otherwise run, and be filed, under a setting it did not have: a depth no request kept, a
  # prefetch no consumer was given, or a fetch thread that nothing raised.
  case "$BACKEND" in
    kafka|redis|nats|rabbitmq) ;;
    *) REASON="backend is kafka, redis, nats or rabbitmq, not \"$BACKEND\""; return ;;
  esac
  case "${CONSUMER:-}" in
    "") ;;
    kafka-python|confluent|java|franz)
      [ "$BACKEND" = kafka ] || {
        REASON="consumer $CONSUMER is one of Kafka's consumers, and this run is $BACKEND"; return; } ;;
    redis-py|waiting)
      [ "$BACKEND" = redis ] || {
        REASON="consumer $CONSUMER is one of Redis's consumers, and this run is $BACKEND"; return; } ;;
    python|nats-go)
      [ "$BACKEND" = nats ] || {
        REASON="consumer $CONSUMER is one of NATS's consumers, and this run is $BACKEND"; return; } ;;
    *) REASON="consumer is kafka-python, confluent, java or franz for Kafka, redis-py or waiting for Redis, or python or nats-go for NATS, not \"$CONSUMER\""; return ;;
  esac
  if [ -n "${CONSUMER:-}" ] && [ -n "${CLIENT:-}" ]; then
    REASON="consumer swaps Kafka's consumer alone and language both clients, so a setup names one of them, not both"; return
  fi
  # The two consumers that keep their own requests waiting at the broker take a depth and a way
  # of reading: NATS's python consumer, and Redis's waiting one. nats.go's Consume() keeps its own
  # requests, 500 messages refilled at 250.
  local waiting=""
  [ "$BACKEND:${CONSUMER:-python}" = nats:python ] && waiting=1
  [ "$BACKEND:${CONSUMER:-}" = redis:waiting ] && waiting=1
  if [ -n "${DEPTH:-}" ]; then
    case "$DEPTH" in
      *[!0-9]*|0*) REASON="depth is a whole number of requests of at least one, not \"$DEPTH\""; return ;;
    esac
    [ -n "$waiting" ] || {
      REASON="depth is the waiting consumers' setting, NATS's python consumer's and Redis's waiting consumer's, and this run's consumer keeps no requests of its own waiting"; return; }
  fi
  if [ -n "${ONE_REPLY:-}" ] && [ -z "$waiting" ]; then
    REASON="one_reply_reads is the waiting consumers' setting, NATS's python consumer's and Redis's waiting consumer's, and this run's consumer reads as its library does"; return
  fi
  if [ -n "${PREFETCH:-}" ]; then
    case "$PREFETCH" in
      *[!0-9]*|0?*) REASON="prefetch is a whole number of messages, 0 for no limit, not \"$PREFETCH\""; return ;;
    esac
    [ "$BACKEND" = rabbitmq ] || {
      REASON="prefetch is RabbitMQ's consumer's setting, and this run is $BACKEND"; return; }
  fi
  if [ -n "${ACK_BATCH:-}" ]; then
    case "$ACK_BATCH" in
      *[!0-9]*|0*) REASON="ack_batch is a whole number of at least one, not \"$ACK_BATCH\""; return ;;
    esac
    case "$BACKEND" in
      redis|rabbitmq) ;;
      *) REASON="ack_batch is the Redis and RabbitMQ consumers' setting, and this run is $BACKEND"; return ;;
    esac
    # RabbitMQ's consumer refuses a batch its prefetch could never fill, 1 unless the setup names it.
    if [ "$BACKEND" = rabbitmq ] && [ "${PREFETCH:-1}" != 0 ] && [ "$ACK_BATCH" -gt "${PREFETCH:-1}" ]; then
      REASON="ack_batch $ACK_BATCH is more than the ${PREFETCH:-1} messages the prefetch lets the broker send unacknowledged, so a batch would never fill"; return
    fi
  fi
  if [ -n "${FETCH_RT:-}" ]; then
    case "${CONSUMER:-}" in
      confluent|java) ;;
      franz) REASON="fetch_rt raises the thread that sends the fetches, and franz-go sends them from none of its own: only its whole process can be raised"; return ;;
      *) REASON="fetch_rt raises the fetch threads a consumer names in its thread list, which only the confluent and java consumers write, and this run's consumer is ${CONSUMER:-the default one}"; return ;;
    esac
  fi
  case "${SCHEDSTAT:-}:${CONSUMER:-}" in
    1:java|1:franz|1:nats-go)
      REASON="schedstat samples the Python consumer's own thread, and this run's consumer is $CONSUMER"; return ;;
  esac
  case "${ARRIVAL:-}" in
    ""|constant) ;;
    poisson)
      [ "${PLAN_KIND:-}" != football ] || {
        REASON="arrival sets the steady plan's arrivals, and this run replays the football plan"; return; } ;;
    *) REASON="arrival is constant or poisson, not \"$ARRIVAL\""; return ;;
  esac
  case "${LOAD_KIND:-}" in
    ""|cpu) ;;
    sock|udp) [ "$LOAD" != 0 ] || {
            REASON="load_kind sets what the load runs, and a load of 0 starts none"; return; } ;;
    *) REASON="load_kind is cpu, sock or udp, not \"$LOAD_KIND\""; return ;;
  esac
  if [ -n "${SIBLING_LOAD:-}" ]; then
    [ -n "${WHOLE_CORE:-}" ] || {
      REASON="sibling_load loads the other threads of the core whole_core keeps, and this setup keeps none"; return; }
    [ "$LOAD" != 0 ] || {
      REASON="sibling_load runs the load on the core's other threads too, and a load of 0 starts none"; return; }
    [ "${LOAD_KIND:-}" != udp ] || {
      REASON="sibling_load runs the load on the core's other threads, and a udp load runs where the card's interrupts go"; return; }
  fi
  # "core", the first thread of the core whole_core would keep, or a list read by the parser that
  # later writes it to the kernel (scripts/cpu_placement.py).
  if [ -n "${IRQ_CPUS:-}" ] && [ "$IRQ_CPUS" != core ] && ! python3 -c 'import sys
sys.path.insert(0, "scripts"); import cpu_placement; cpu_placement.parse_list(sys.argv[1])' \
      "$IRQ_CPUS" 2>/dev/null; then
    REASON="irq_cpus is core, or a list of CPUs as the kernel writes one, 2-3 or 1,3, not \"$IRQ_CPUS\""; return
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
  # Plan version 47 (23 Oct 2026): where the setup places the run, once the online CPUs are set.
  # Each thing moved is written down before it is moved, as it was set and again after the run, and
  # placement_back puts it back once the run ends, however it ends; nothing is moved that the
  # setup does not name.
  #   whole_core, or irq_cpus core: the core chosen from the online CPUs' own topology, and the
  #     choice written beside the run (core_choice.json): the consumer on the core's first thread,
  #     every other process the run starts off both of its threads, the load on every other CPU
  #     and, with sibling_load, on the core's other threads as well;
  #   irqbalance_off: irqbalance stopped, which would otherwise move the card's interrupts back;
  #   irq_cpus: the card's interrupts given their CPUs, "core" being the core's first thread;
  #   load_kind udp: the UDP load on the CPUs that take the card's interrupts, as given or as the
  #     kernel was found running them;
  #   rps_off: no receive packet steering on the receiver's queues, the card's and its own;
  #   whole_core: the campaign's own CPUs narrowed to the others, so that every process it starts
  #     from here on, through sudo or not, runs off the core; the consumer's wrap pins it there.
  local placed="" core_first="" core_list="" kit_list="" irq_target=""
  if [ -n "${WHOLE_CORE:-}" ] || [ "${IRQ_CPUS:-}" = core ]; then
    placed=$(python3 scripts/cpu_placement.py core ${SIBLING_LOAD:+--sibling-load} \
      --out "$RUN_DIR/core_choice.json" 2> "$RUN_DIR/core_choice.err") || {
      REASON="no core could be chosen for the consumer: $placed"; return; }
    local siblings load_list load_count
    read -r core_first siblings kit_list load_list load_count <<< "$placed"
    core_list="$core_first"
    [ "$siblings" = - ] || core_list="$core_first,$siblings"
    if [ -n "${WHOLE_CORE:-}" ]; then
      CORE_CPU="$core_first"
      [ "$load_list" = - ] || { LOAD_TASKSET="$load_list"; LOAD_CPUS="$load_count"; }
      if [ "$LOAD" != 0 ] && [ -z "$LOAD_TASKSET" ]; then
        REASON="whole_core keeps the only core for the consumer, and leaves no CPU for the load"; return
      fi
      [ "$kit_list" != - ] || {
        REASON="whole_core keeps the only core for the consumer, and leaves no CPU for the run's other processes"; return; }
    fi
  fi
  [ "${IRQ_CPUS:-}" = core ] && irq_target="$core_first"
  [ -n "${IRQ_CPUS:-}" ] && [ "$IRQ_CPUS" != core ] && irq_target="$IRQ_CPUS"
  local placing=""
  [ -n "${WHOLE_CORE:-}${IRQ_CPUS:-}${IRQBALANCE_OFF:-}${RPS_OFF:-}" ] && placing=1
  [ "${LOAD_KIND:-}" = udp ] && placing=1
  if [ -n "$placing" ]; then
    python3 scripts/cpu_placement.py irqs --out "$RUN_DIR/irq_affinity_before.json" \
      > "$RUN_DIR/placement.log" 2>&1
    systemctl is-active irqbalance > "$RUN_DIR/irqbalance_before.txt" 2>&1
  fi
  if [ -n "${IRQBALANCE_OFF:-}" ] && systemctl is-active --quiet irqbalance 2>/dev/null; then
    IRQBALANCE_STOPPED=1
    sudo systemctl stop irqbalance >> "$RUN_DIR/placement.log" 2>&1 || {
      REASON="irqbalance could not be stopped for the run"; return; }
  fi
  if [ -n "$irq_target" ]; then
    # irqbalance would move them back while the run went on, so the run stops here instead.
    if systemctl is-active --quiet irqbalance 2>/dev/null; then
      REASON="irq_cpus moves the receiver card's interrupts, and irqbalance is running, which moves them back; the setup names irqbalance_off for that"; return
    fi
    IRQS_MOVED="$RUN_DIR/irq_affinity_before.json"
    sudo python3 scripts/cpu_placement.py irqs --set "$irq_target" \
      --out "$RUN_DIR/irq_affinity_set.json" >> "$RUN_DIR/placement.log" 2>&1 || {
      REASON="the receiver card's interrupts did not all take $irq_target; see $RUN_DIR/irq_affinity_set.json"; return; }
  fi
  if [ "${LOAD_KIND:-}" = udp ]; then
    local udp_cpus
    udp_cpus=$(python3 scripts/cpu_placement.py irq-cpus --irqs "$RUN_DIR/irq_affinity_before.json" \
      ${irq_target:+--given "$irq_target"} ${CORE_CPU:+--avoid "$core_list"} 2>> "$RUN_DIR/placement.log") || {
      REASON="the udp load has no CPU of its own: $udp_cpus"; return; }
    read -r LOAD_TASKSET LOAD_CPUS <<< "$udp_cpus"
  fi
  if [ -n "${RPS_OFF:-}" ]; then
    # eth0 and each accelerated device that carries its address, and the receiver's own link,
    # whose queues only its namespace shows.
    local eth0_mac dev
    eth0_mac=$(cat "$ETH0_ADDRESS" 2>/dev/null)
    RPS_DEVICES="--dev eth0"
    for dev in $(ip -br link | awk -v mac="$eth0_mac" \
        'mac != "" && $4 ~ /SLAVE/ && tolower($3) == tolower(mac) {print $1}'); do
      RPS_DEVICES="$RPS_DEVICES --dev $dev"
    done
    # shellcheck disable=SC2086
    python3 scripts/cpu_placement.py rps $RPS_DEVICES --out "$RUN_DIR/rps_before.json" \
      >> "$RUN_DIR/placement.log" 2>&1
    sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --dev "$RECEIVER_LINK" \
      --out "$RUN_DIR/rps_receiver_before.json" >> "$RUN_DIR/placement.log" 2>&1
    RPS_MOVED="$RUN_DIR"
    # shellcheck disable=SC2086
    { sudo python3 scripts/cpu_placement.py rps $RPS_DEVICES --set 0 --out "$RUN_DIR/rps_set.json" \
      && sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --dev "$RECEIVER_LINK" \
        --set 0 --out "$RUN_DIR/rps_receiver_set.json"; } >> "$RUN_DIR/placement.log" 2>&1 || {
      REASON="receive steering could not be turned off on the receiver's queues; see $RUN_DIR/rps_set.json"; return; }
  fi
  if [ -n "${WHOLE_CORE:-}" ]; then
    taskset -pc $$ > "$RUN_DIR/kit_mask_before.txt" 2>&1
    KIT_MASK_BEFORE=$(sed -n 's/.*current affinity list: //p' "$RUN_DIR/kit_mask_before.txt")
    KIT_MASK_BEFORE="${KIT_MASK_BEFORE:-0-$(( ALL_CPUS - 1 ))}"
    taskset -pc "$kit_list" $$ > "$RUN_DIR/kit_mask_set.txt" 2>&1 || {
      REASON="the campaign's own processes could not be kept off the consumer's core: $(cat "$RUN_DIR/kit_mask_set.txt")"; return; }
  fi

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
  # Plan version 47 (23 Oct 2026): as the setup names the load (load_start).
  if [ "$LOAD" != 0 ] && [ -z "${LOAD_BLOCKS:-}" ]; then
    load_start "${DUTY:-$LOAD}" "$want_cpus" 3600s
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
      load_start "$adjusted" "$want_cpus" 3600s
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
  # Plan version 47 (23 Oct 2026): a setup that asks for Poisson arrivals replays the campaign's
  # one Poisson draw at the same rate, held to the same count and rate as the steady plan. Each
  # trial runner writes the plan's process and seed into meta.json, beside its path.
  local run_arrival="${ARRIVAL:-constant}" run_seed=""
  [ "$PLAN_KIND" = football ] && run_arrival=football
  if [ "${ARRIVAL:-}" = poisson ]; then
    run_plan="$POISSON_PLAN"; run_speedup="$POISSON_SPEEDUP"; run_seed="$PLAN_SEED"
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
  # Plan version 47 (23 Oct 2026): where the run keeps a core for the consumer (whole_core), the
  # consumer's process, and every thread it starts, on that core's first thread alone: taskset
  # sets its own mask and runs the rest of the wrap, which inherits it.
  [ -n "${CORE_CPU:-}" ] && consumer_wrap="taskset -c $CORE_CPU $consumer_wrap"
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
  # Pilot round a of plan version 47 (23 Oct 2026): the capture is written to the broker's memory
  # (/dev/shm), not to its disk. It writes about 2 MB a second, 150 to 190 MB a run. On the Arm
  # pair, whose broker writes to a slower disk than the x86 pair's, all seven Kafka runs with the
  # capture on that disk had their acknowledgements held for 190 to 610 ms about 30 s and 60 s
  # into the capture, as the kernel writes back pages 30 s old, and the producer fell behind;
  # the broker's run without a capture held none longer than 24 ms. The memory file system
  # holds 3.9 GB on both brokers.
  local broker_full="" broker_port="${KAFKA_BOOTSTRAP##*:}"
  [ "$BACKEND" = redis ] && broker_port="$REDIS_PORT"
  # Plan version 47 (23 Oct 2026): NATS's port and RabbitMQ's, for their blocks. The client-host
  # captures above name the broker's address alone, so they take every port already.
  [ "$BACKEND" = nats ] && broker_port="$NATS_PORT"
  [ "$BACKEND" = rabbitmq ] && broker_port="$RABBITMQ_PORT"
  if [ -n "$BROKER_CAPTURE" ]; then
    remote_broker "sudo sh -c 'kill -INT \$(cat /dev/shm/sbl_bfull.pid 2>/dev/null) 2>/dev/null; rm -f /dev/shm/sbl_bfull.pcap /dev/shm/sbl_bfull.err; nohup tcpdump -i eth0 -s 0 --time-stamp-precision=nano -B 32768 -w /dev/shm/sbl_bfull.pcap tcp port $broker_port > /dev/shm/sbl_bfull.err 2>&1 & echo \$! > /dev/shm/sbl_bfull.pid'" \
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
  # Plan version 47 (23 Oct 2026): a load heavy in softirq work keeps the kernel's own counters
  # before and after as well, with or without the run's facts: the softirq's time_squeeze, the
  # times it ran out of budget with packets still waiting, and ksoftirqd's own time among them.
  case "${RUN_FACTS:-}:${LOAD_KIND:-}" in :sock|:udp) interrupt_counters before ;; esac
  # Plan version 47 (23 Oct 2026): every broker's image and its digest, and its server's own
  # version, read on the broker in every run (scripts/run_facts.py broker); the integrity rule
  # repeats a run whose own broker's were not read.
  remote_broker "cd sbl && python3 scripts/run_facts.py broker --out -" \
    > "$RUN_DIR/broker_facts.json" 2> "$RUN_DIR/broker_facts.err"
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
  # Plan version 47 (23 Oct 2026): and where the run keeps a core for its consumer, so that the CPUs
  # each client thread may run on, as the kernel holds them, show the pin took (whole_core).
  if [ -n "${RUN_FACTS:-}${WHOLE_CORE:-}" ]; then
    run_facts_later "$RUN_DIR" &
    facts_pid=$!
  fi
  # Plan version 47 (23 Oct 2026): one trial runner for each backend, each handed the three wraps
  # and the plan's arrival process and seed, which it writes into meta.json beside the plan's path.
  if [ "$BACKEND" = kafka ]; then
    client_args=()
    [ -n "${CLIENT:-}" ] && client_args+=(-CLIENT "$CLIENT")
    [ -n "${ACK_STAMP:-}" ] && client_args+=(-ACK_STAMP "$ACK_STAMP")
    # Plan version 47 (23 Oct 2026): the consumer alone, kafka_producer.py sending in every run,
    # and the threads it names as sending its fetches raised where the setup asks.
    [ -n "${CONSUMER:-}" ] && client_args+=(-CONSUMER "$CONSUMER")
    [ -n "${FETCH_RT:-}" ] && client_args+=(-FETCH_RT)
    SBL_PLAN_ARRIVAL="$run_arrival" SBL_PLAN_SEED="$run_seed" \
    SBL_THREADS_WAIT_S="$THREADS_WAIT_S" SBL_FETCH_RT_PRIORITY="$FETCH_RT_PRIORITY" \
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_kafka_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
      -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA $record_args $so_prod$prod_flags" \
      -CONSUMER_EXTRA "$record_args $read_args $so_cons$cons_flags" \
      -IDLE_SECONDS 15 "${client_args[@]}" > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  elif [ "$BACKEND" = redis ]; then
    # Plan version 47 (23 Oct 2026): the waiting consumer where the setup names it, at its depth
    # and with its reads; its acknowledgment batch comes as redis-py's does.
    redis_args=()
    [ -n "${CONSUMER:-}" ] && redis_args+=(-CONSUMER "$CONSUMER")
    [ -n "${DEPTH:-}" ] && redis_args+=(-DEPTH "$DEPTH")
    [ -n "${ONE_REPLY:-}" ] && redis_args+=(-ONE_REPLY_READS)
    # Freeze 41 (15 Oct 2026): block K's two one-worker setups send through one XADD worker instead
    # of the producer's sixteen; a setup that names no count keeps the producer's own.
    SBL_PLAN_ARRIVAL="$run_arrival" SBL_PLAN_SEED="$run_seed" \
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_redis_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
      -PRODUCER_EXTRA "$record_args $so_prod${SEND_WORKERS:+ --send-workers $SEND_WORKERS}$prod_flags" \
      -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA${ACK_BATCH:+ --ack-batch $ACK_BATCH} $record_args $so_cons$cons_flags" \
      -IDLE_SECONDS 15 "${redis_args[@]}" > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  elif [ "$BACKEND" = nats ]; then
    # Plan version 47 (23 Oct 2026): block N, its streams kept as NATS_STORAGE says. The runner
    # names the stream after the run and the moment it began, so a run made again gets a stream of
    # its own, and the consumer deletes it once it is done, so that the broker does not fill run by
    # run. Neither NATS client takes M0's read trace; nats.go's consumer takes the runner's own
    # flags alone, as franz-go's does.
    nats_args=()
    [ -n "${CONSUMER:-}" ] && nats_args+=(-CONSUMER "$CONSUMER")
    [ -n "${DEPTH:-}" ] && nats_args+=(-DEPTH "$DEPTH")
    [ -n "${ONE_REPLY:-}" ] && nats_args+=(-ONE_REPLY_READS)
    SBL_PLAN_ARRIVAL="$run_arrival" SBL_PLAN_SEED="$run_seed" SBL_THREADS_WAIT_S="$THREADS_WAIT_S" \
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_nats_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -NatsHost "$NATS_HOST" -PORT "$NATS_PORT" \
      -STORAGE "$NATS_STORAGE" -DELETE_STREAM \
      -PRODUCER_EXTRA "$record_args $so_prod$prod_flags" \
      -CONSUMER_EXTRA "$record_args $so_cons$cons_flags" \
      -IDLE_SECONDS 15 "${nats_args[@]}" > "$RUN_DIR/trial.log" 2>&1
    rc=$?
  else
    # Plan version 47 (23 Oct 2026): block P, RabbitMQ, at the setup's prefetch, which the runner
    # hands the consumer last so that it wins; the acknowledgment batch where the setup names one.
    # Kafka's producer settings and Redis's send workers are neither client's.
    rabbit_args=()
    [ -n "${PREFETCH:-}" ] && rabbit_args+=(-PREFETCH "$PREFETCH")
    SBL_PLAN_ARRIVAL="$run_arrival" SBL_PLAN_SEED="$run_seed" \
    SBL_CONSUMER_WRAP="$consumer_wrap" SBL_SCHED_WRAP="$wrap_sched" SBL_PRODUCER_WRAP="$producer_wrap" \
      timeout -k 30 $(( DURATION + 300 )) bash scripts/run_rabbitmq_trial.sh "$RUN_ID" "$run_plan" \
      "$run_speedup" "$run_maxt" -URI "$RABBITMQ_URI" \
      -PRODUCER_EXTRA "$record_args $so_prod$prod_flags" \
      -CONSUMER_EXTRA "$record_args $so_cons$cons_flags${ACK_BATCH:+ --ack-batch $ACK_BATCH}" \
      -IDLE_SECONDS 15 "${rabbit_args[@]}" > "$RUN_DIR/trial.log" 2>&1
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
  case "${RUN_FACTS:-}:${LOAD_KIND:-}" in :sock|:udp) interrupt_counters after ;; esac
  # Plan version 47 (23 Oct 2026): what the run placed, as it stands once the run has ended,
  # beside how it stood before and as it was set; placement_back then puts it back.
  if [ -n "${placing:-}" ]; then
    python3 scripts/cpu_placement.py irqs --out "$RUN_DIR/irq_affinity_after.json" \
      >> "$RUN_DIR/placement.log" 2>&1
    systemctl is-active irqbalance > "$RUN_DIR/irqbalance_after.txt" 2>&1
  fi
  if [ -n "${RPS_MOVED:-}" ]; then
    # shellcheck disable=SC2086
    python3 scripts/cpu_placement.py rps $RPS_DEVICES --out "$RUN_DIR/rps_after.json" \
      >> "$RUN_DIR/placement.log" 2>&1
    sudo ip netns exec sblrecv python3 scripts/cpu_placement.py rps --dev "$RECEIVER_LINK" \
      --out "$RUN_DIR/rps_receiver_after.json" >> "$RUN_DIR/placement.log" 2>&1
  fi
  [ -z "${KIT_MASK_BEFORE:-}" ] || taskset -pc $$ > "$RUN_DIR/kit_mask_after.txt" 2>&1
  container=redis
  [ "$BACKEND" = kafka ] && container=broker
  # Plan version 47 (23 Oct 2026): RabbitMQ is a container as Kafka and Redis are; NATS is a unit
  # of the broker's own (cloud/brokers.sh), whose log is the journal's.
  [ "$BACKEND" = rabbitmq ] && container=rabbitmq
  if [ "$BACKEND" = nats ]; then
    remote_broker "sudo journalctl -u sbl-nats-js -o short-iso-precise --since @$began --until @$(( ended + 1 ))" \
      > "$RUN_DIR/broker_log.txt" 2>&1
  else
    remote_broker "docker logs --timestamps --since $began --until $(( ended + 1 )) $container" \
      > "$RUN_DIR/broker_log.txt" 2>&1
  fi

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
    remote_broker "sudo kill -INT \$(cat /dev/shm/sbl_bfull.pid) 2>/dev/null; for _ in \$(seq 1 40); do sudo kill -0 \$(cat /dev/shm/sbl_bfull.pid) 2>/dev/null || break; sleep 0.5; done" \
      > /dev/null 2>&1
    remote_broker "sudo cat /dev/shm/sbl_bfull.pcap" > "$RUN_DIR/broker_full.pcap" 2>/dev/null
    remote_broker "sudo cat /dev/shm/sbl_bfull.err; sudo rm -f /dev/shm/sbl_bfull.pcap /dev/shm/sbl_bfull.err /dev/shm/sbl_bfull.pid" \
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

  # Plan version 47 (23 Oct 2026): a runner that refused the run says why on a FATAL line, as
  # run_kafka_trial.sh does when the consumer's fetch threads could not be raised, and the reason
  # the ledger keeps is that line.
  if [ "$rc" != 0 ]; then
    local fatal
    fatal=$(grep -m 1 '^FATAL: ' "$RUN_DIR/trial.log" 2>/dev/null)
    REASON="the trial exited with $rc${fatal:+: ${fatal#FATAL: }}; see $RUN_DIR/trial.log"; return
  fi
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
#: Plan version 47 (23 Oct 2026): then NATS and RabbitMQ, each where the queue holds a run of its,
#: with its own client's default settings; a queue of Kafka and Redis primes as it always did.
prime_brokers () {
  local backend prime_id rc primed="kafka redis"
  case " ${QUEUE_BACKENDS:-} " in *" nats "*) primed="$primed nats" ;; esac
  case " ${QUEUE_BACKENDS:-} " in *" rabbitmq "*) primed="$primed rabbitmq" ;; esac
  for backend in $primed; do
    reap
    prime_id="law_${QUEUE_NAME}_prime_${backend}_$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "runs/$prime_id"
    if [ "$backend" = kafka ]; then
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_kafka_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -BOOTSTRAP "$KAFKA_BOOTSTRAP" \
        -PRODUCER_EXTRA "$KAFKA_PRODUCER_EXTRA" -IDLE_SECONDS 15 > "runs/$prime_id/trial.log" 2>&1
    elif [ "$backend" = redis ]; then
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_redis_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -RedisHost "$REDIS_HOST" -PORT "$REDIS_PORT" \
        -CONSUMER_EXTRA "$REDIS_CONSUMER_EXTRA" -IDLE_SECONDS 15 > "runs/$prime_id/trial.log" 2>&1
    elif [ "$backend" = nats ]; then
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_nats_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -NatsHost "$NATS_HOST" -PORT "$NATS_PORT" \
        -STORAGE "$NATS_STORAGE" -DELETE_STREAM -IDLE_SECONDS 15 > "runs/$prime_id/trial.log" 2>&1
    else
      SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $ME" \
        timeout -k 30 $(( PRIME_S + 300 )) bash scripts/run_rabbitmq_trial.sh "$prime_id" \
        "$SYN_PLAN" "$SPEEDUP" "$PRIME_S" -URI "$RABBITMQ_URI" -IDLE_SECONDS 15 \
        > "runs/$prime_id/trial.log" 2>&1
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
    # Plan version 47 (23 Oct 2026): the batch is handed on whatever it is, for the runner to
    # refuse one it cannot give, where a batch of none used to be dropped for the default.
    "PLAN_KIND": p.get("plan") or "",
    "ACK_BATCH": "" if p.get("ack_batch") is None else str(p["ack_batch"]),
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
    # Plan version 47 (23 Oct 2026): the consumer alone; the waiting consumers' depth and reads;
    # RabbitMQ's prefetch; the fetch threads at real-time priority; the plan's arrival process;
    # the consumer alone on a core, and its sibling loaded; the CPUs the card's interrupts are
    # given, irqbalance off and the receive queues' steering off; and what the load runs. A row
    # that names none of them leaves all twelve empty, and its run is launched exactly as before;
    # a value of none is handed on for the runner to refuse.
    "CONSUMER": str(p.get("consumer") or ""),
    "DEPTH": "" if p.get("depth") is None else str(p["depth"]),
    "ONE_REPLY": "1" if p.get("one_reply_reads") else "",
    "PREFETCH": "" if p.get("prefetch") is None else str(p["prefetch"]),
    "FETCH_RT": "1" if p.get("fetch_rt") else "",
    "ARRIVAL": str(p.get("arrival") or ""),
    "WHOLE_CORE": "1" if p.get("whole_core") else "",
    "SIBLING_LOAD": "1" if p.get("sibling_load") else "",
    "IRQ_CPUS": "" if p.get("irq_cpus") is None else str(p["irq_cpus"]),
    "IRQBALANCE_OFF": "1" if p.get("irqbalance_off") else "",
    "RPS_OFF": "1" if p.get("rps_off") else "",
    "LOAD_KIND": str(p.get("load_kind") or ""),
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
  log "run $KEY: $BACKEND, load $LOAD%, slice ${SLICE_NS:-kernel default}, delay $DELAY_MS ms${PRIORITY:+, go-first}${CONSUMER_PRIORITY:+, go-first consumer}${RECV_CAPTURE:+, receiver capture}${SEND_CAPTURE:+, sender capture}${HW_CAPTURE:+, card capture}${SO_STAMPS:+, socket timestamps ($SO_STAMPS)}${SO_JOURNAL:+, journal=$SO_JOURNAL}${SEND_CAPTURE_BOTH:+, both directions of the sender}${SEND_WORKERS:+, $SEND_WORKERS send workers}${SCHED_FEATURES:+, $SCHED_FEATURES}${IDLE_POLL:+, idle_poll=$IDLE_POLL}${BROKER_CAPTURE:+, broker capture}${LOAD_RECORRECT:+, the load corrected again with the clients running}${PRODUCER_PRIORITY:+, go-first producer}${GC_OFF:+, collectors off}${GC_LOG:+, collections logged}${SCHEDSTAT:+, consumer schedstat}${DUTY:+, duty frozen at $DUTY%}${LOAD_BLOCKS:+, load in $LOAD_BLOCKS s blocks}${RUN_FACTS:+, run facts}${CONSUMER:+, consumer $CONSUMER}${DEPTH:+, depth $DEPTH}${ONE_REPLY:+, one-reply reads}${PREFETCH:+, prefetch $PREFETCH}${FETCH_RT:+, fetch threads at real-time priority}${ARRIVAL:+, $ARRIVAL arrivals}${WHOLE_CORE:+, the consumer alone on a core}${SIBLING_LOAD:+, its sibling loaded}${IRQ_CPUS:+, card interrupts on $IRQ_CPUS}${IRQBALANCE_OFF:+, irqbalance off}${RPS_OFF:+, receive steering off}${LOAD_KIND:+, $LOAD_KIND load}${CPUS:+, $CPUS CPUs online}"
  REASON=""
  STOP_REASON=""
  CORE_CPU=""; LOAD_TASKSET=""; LOAD_CPUS=""
  run_one
  features_back "$RUN_DIR/feature_back.txt"
  placement_back "$RUN_DIR"
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
