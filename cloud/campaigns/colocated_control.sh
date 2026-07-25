#!/usr/bin/env bash
# E-A8: move the broker onto the driver, and see what the true transport was.
#
# WHAT THIS IS ACTUALLY FOR. An earlier description of this experiment said it would supply a
# "common clock" that the cross-host setup lacks. That was wrong and the correction matters:
# run_kafka_trial.sh launches the producer AND the consumer as local processes on the driver, so
# both stamps already come from one machine's clock. Only the broker is remote. The Delta this
# paper measures has never contained a cross-host clock offset -- it is process-level stamping
# asymmetry, which is exactly what E-A5 demonstrated by manipulation.
#
# What co-location changes is not the clock but T_true. Removing the network hop should cut the
# true broker transport several-fold, and that turns this into a test of L2 rather than a
# calibration.
#
# THE PREDICTION, AND IT IS A STRANGE-LOOKING ONE. L2 says the inversion ceiling is
# S = P(residual > T_true): the chance a preemption residual outlasts the true transport. If
# that is the mechanism, then shrinking T_true must make inversions MORE common, because the
# same residual distribution now has a smaller threshold to beat. So at matched load:
#
#     co-located  ->  T_true DOWN   and   inversion rate UP
#     remote      ->  T_true UP     and   inversion rate DOWN
#
# Two quantities moving in opposite directions, both from one mechanism. A model in which
# inversions simply track "how loaded the machine is" predicts no change at all here, since the
# load is identical. A model in which a faster path is a safer path predicts the opposite sign.
# Few results discriminate as cleanly as one whose sign is counter-intuitive.
#
# THE CONFOUND, NAMED IN ADVANCE. Running Kafka and Redis on the driver adds CPU work to the
# machine whose scheduling we are measuring. That pushes occupancy UP, the same direction as the
# predicted effect, so a naive reading could credit the mechanism for a confound. Two defences:
#   * utilisation is measured in every cell and the analysis withholds any comparison whose arms
#     differ by more than 5 points;
#   * the IDLE pair is the primary comparison. With a 0.415 ev/s feed the brokers do almost no
#     work there, so the load difference is small and the T_true contrast is nearly clean. The
#     loaded pair is secondary and is reported as such.
#
# The idle co-located cell is also the best estimate of T_true this testbed can produce: one
# host, one clock, no network, and a stamping thread that is almost never preempted.
#
# Usage:  nohup bash cloud/campaigns/colocated_control.sh > colocated.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/ea8}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

command -v docker >/dev/null || { echo "FATAL: docker not installed on the driver"; exit 1; }

LOCAL_KAFKA="localhost:19092"
LOCAL_REDIS_HOST="localhost"

start_local_brokers () {
  banner "starting co-located Kafka + Redis on the driver"
  docker rm -f sbl_local_broker sbl_local_redis >/dev/null 2>&1
  docker run -d --name sbl_local_redis -p 6379:6379 redis:7 \
    redis-server --save '' --appendonly no >/dev/null 2>&1
  docker run -d --name sbl_local_broker -p 19092:19092 \
    -e KAFKA_BROKER_ID=1 \
    -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT \
    -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:19092 \
    -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
    -e KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS=0 \
    -e KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=1 \
    -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
    -e KAFKA_PROCESS_ROLES=broker,controller -e KAFKA_NODE_ID=1 \
    -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@localhost:29093 \
    -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:19092,CONTROLLER://localhost:29093 \
    -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
    -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
    -e KAFKA_LOG_DIRS=/tmp/kraft-combined-logs \
    -e CLUSTER_ID=MkU3OEVBNTcwNTJENDM2Qk \
    -e KAFKA_NUM_PARTITIONS=1 -e KAFKA_DEFAULT_REPLICATION_FACTOR=1 \
    -e KAFKA_AUTO_CREATE_TOPICS_ENABLE=true \
    -e KAFKA_HEAP_OPTS="-Xms1G -Xmx1G" \
    apache/kafka:4.1.1 >/dev/null 2>&1
  sleep 25
  docker ps --format '{{.Names}} {{.Status}}' | grep sbl_local
}

stop_local_brokers () {
  docker rm -f sbl_local_broker sbl_local_redis >/dev/null 2>&1
  echo "co-located brokers removed"
}
trap 'stop_local_brokers' EXIT

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "co-located control: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps"

# $1 = placement tag, $2 = load pct (0 = idle), $3 = bootstrap, $4 = redis host
run_cell () {
  local place="$1" pct="$2" boot="$3" rhost="$4"
  local tag="${place}_l${pct}"
  local stress_pid="" sampler_pid=""
  mkdir -p "$OUT/$tag"
  reap
  if [ "$pct" != "0" ]; then
    stress-ng --cpu "$NCORES" --cpu-load "$pct" --timeout 3600s >/dev/null 2>&1 &
    stress_pid=$!
    sleep 3
  fi
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  local ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
        --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
        --kafka-bootstrap "$boot" --redis-host "$rhost" --redis-port "$REDIS_PORT" \
        --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
        --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT + 400 ))" 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: $tag hit shell timeout (${ceiling}s)"

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && kill -9 "$stress_pid" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  printf 'tag,placement,requested_cpu_load_pct,bootstrap,redis_host,n_feeds,reps,max_t_sim\n%s,%s,%s,%s,%s,5,%s,%s\n' \
    "$tag" "$place" "$pct" "$boot" "$rhost" "$REPS" "$MAXT" > "$OUT/$tag/condition.csv"
  reap
}

# Remote first, while the driver is still clean, so the co-located brokers cannot leave
# residue in the arm they are supposed to be compared against.
banner "E-A8 REMOTE broker, idle  (the paper's usual configuration)"
run_cell "remote" 0 "$KAFKA_BOOTSTRAP" "$REDIS_HOST"
banner "E-A8 REMOTE broker, 88% load"
run_cell "remote" 88 "$KAFKA_BOOTSTRAP" "$REDIS_HOST"

start_local_brokers || { echo "FATAL: co-located brokers did not start"; exit 1; }

banner "E-A8 CO-LOCATED broker, idle  (the cleanest T_true this testbed can give)"
run_cell "colocated" 0 "$LOCAL_KAFKA" "$LOCAL_REDIS_HOST"
banner "E-A8 CO-LOCATED broker, 88% load"
run_cell "colocated" 88 "$LOCAL_KAFKA" "$LOCAL_REDIS_HOST"

stop_local_brokers
banner "COLOCATED_CONTROL_COMPLETE"
