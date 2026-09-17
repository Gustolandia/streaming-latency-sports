#!/usr/bin/env bash
# The pilot: the checks a machine must pass before any run of the main campaign counts.
#
# Run on the driver, from the checkout, after cloud/azure/session.sh:
#     nohup bash cloud/azure/pilot.sh > pilot.log 2>&1 &
#
# Five checks, each with a verdict line in $OUT/verdicts.csv:
#   1. settings  the base slice and the tick read back, a hand-set slice is still there a minute
#                later, and the default is put back (scripts/sched_settings.py);
#   2. network   the machines' facts are kept (cloud/azure/machine_facts.sh). With no delay, the
#                receiver's and the host's ping round trips agree within 0.25 ms, over five
#                readings (paths). At each of DELAYS_MS, the broker's own capture shows it held
#                the receiver's replies for the set delay, and the host's not at all, within
#                0.05 ms; and ping sees the delay end to end within 0.25 ms plus 5%, the limit
#                every run is held to (scripts/receiver_delay.py). Ping alone could not decide
#                0.05 ms: on the Arm pair its zero-delay reading drifted by up to 0.1 ms;
#   3. harness   the same, as the harness itself sees it under load: the "got it" delay does not
#                move, arrival minus sending grows by the measured delay, and arrival minus
#                sending is never negative (scripts/pilot_checks.py). Zero-delay runs come before
#                and after the delayed ones, so a drift lands on both sides;
#   4. go-first  the old decisive test at the same load: real-time priority on the timestamping
#                processes must cut the negative rate at least five-fold, with the manipulation
#                check passed (cloud/campaigns/stamping_priority.sh, unchanged);
#   5. retest    nothing extra here. Running the pilot again on another day, after a stop and a
#                start, is the test-retest, and the two output directories are what get compared.
#
# PARTS names the checks to run (default: settings network harness go-first). A pair that passed
# its shakedown runs PARTS=network in each later session, because a start after a stop can put
# its machines on another physical host.
#
# A failing check is reported and the pilot carries on, so one bad check does not hide the rest.
# None of this is a result for the paper. It decides whether this machine can produce results.
. "$(dirname "${BASH_SOURCE[0]}")/../campaigns/common.sh"
set +e

: "${RECEIVER_IP:?hosts.env has no RECEIVER_IP; is this the Azure testbed?}"
OUT="${OUT:-runs/azure/pilot/${AZ_PROFILE:-unknown}_$(date -u +%Y%m%dT%H%M%SZ)}"
LOAD_PCT="${LOAD_PCT:-75}"
REPS="${REPS:-3}"
MAXT="${MAXT:-1800}"
DELAYS_MS="${DELAYS_MS:-0.5 2.0}"
PARTS="${PARTS:-settings network harness go-first}"
: "${DRIVER_PRIV:?hosts.env has no DRIVER_PRIV}"
HARNESS_DELAY_MS="${HARNESS_DELAY_MS:-2.0}"
NCORES=$(nproc)
mkdir -p "$OUT"
echo "check,step,ok,detail" > "$OUT/verdicts.csv"

verdict () {  # check step yes|no detail
  echo "$1,$2,$3,$4" >> "$OUT/verdicts.csv"
  echo "  -> $1 $2: $3 ($4)"
}
broker_delay () {  # delay in ms, on the traffic to the receiver alone
  remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker \
    --dst $RECEIVER_IP --delay-ms $1 --apply"
}
json_field () {  # file key
  python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}
json_ms () {  # file key, to the microsecond
  python3 -c 'import json, sys; print("%.3f" % json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"
}
part () {  # is this part of the pilot asked for?
  case " $PARTS " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}
reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null
  pkill -f "util_sampler.py" 2>/dev/null
  pkill -9 -x stress-ng 2>/dev/null
  sleep 2
}
trap 'reap; remote_broker "cd sbl && sudo python3 scripts/receiver_delay.py broker-clear --apply" >/dev/null 2>&1' EXIT

banner "pilot on ${AZ_PROFILE:-unknown}: ${NCORES} CPUs, load ${LOAD_PCT}%, writing to $OUT"

# --- 1. settings -----------------------------------------------------------------------------
if part settings; then
banner "1/5 settings"
sudo python3 scripts/sched_settings.py read > "$OUT/settings_before.json"
DEFAULT_SLICE=$(json_field "$OUT/settings_before.json" base_slice_ns)
TEST_SLICE=1500000
[ "$DEFAULT_SLICE" = "$TEST_SLICE" ] && TEST_SLICE=2250000
if sudo python3 scripts/sched_settings.py set-slice "$TEST_SLICE" > "$OUT/set_slice.txt" 2>&1; then
  sleep 60
  if sudo python3 scripts/sched_settings.py check --slice-ns "$TEST_SLICE" \
      > "$OUT/settings_after_60s.json"; then
    verdict settings kept yes "$TEST_SLICE ns still set after 60 s"
  else
    verdict settings kept no "see settings_after_60s.json"
  fi
else
  verdict settings set no "see set_slice.txt"
fi
if sudo python3 scripts/sched_settings.py set-slice "$DEFAULT_SLICE" >> "$OUT/set_slice.txt" 2>&1; then
  verdict settings restored yes "$DEFAULT_SLICE ns"
else
  verdict settings restored no "see set_slice.txt"
fi
fi

# --- 2. network ------------------------------------------------------------------------------
if part network; then
banner "2/5 network: the facts, the two paths, and the delay the broker holds"
bash cloud/azure/machine_facts.sh > "$OUT/facts_driver.txt" 2>&1
remote_broker "cd sbl && bash cloud/azure/machine_facts.sh" > "$OUT/facts_broker.txt" 2>&1
reading () {  # tag delay_ms: ping from both sides while the broker captures the same pings
  local capture
  broker_delay "$2" > "$OUT/net_apply_$1.txt" 2>&1
  sleep 2
  remote_broker "sudo timeout 60 tcpdump -i eth0 -nn -tt --time-stamp-precision=nano -c 800 \
    'icmp and (host $DRIVER_PRIV or host $RECEIVER_IP)'" \
    > "$OUT/net_capture_$1.txt" 2> "$OUT/net_capture_$1.err" &
  capture=$!
  sleep 2
  sudo python3 scripts/receiver_delay.py measure --broker "$BROKER_PRIV" \
    --out "$OUT/net_$1.json" > /dev/null 2>&1
  wait "$capture"
  python3 scripts/receiver_delay.py holds --capture "$OUT/net_capture_$1.txt" \
    --host "$DRIVER_PRIV" --receiver "$RECEIVER_IP" --out "$OUT/net_hold_$1.json" \
    > "$OUT/net_hold_$1.log" 2>&1
}
for i in 1 2 3 4 5; do
  reading "zero$i" 0
done
if python3 scripts/pilot_checks.py paths --pilot-dir "$OUT" > "$OUT/net_paths.json" 2>&1; then
  verdict paths "no delay" yes "receiver minus host $(json_ms "$OUT/net_paths.json" median_difference_ms) ms"
else
  verdict paths "no delay" no "see net_paths.json"
fi
for D in $DELAYS_MS; do
  reading "$D" "$D"
  TOL=$(python3 -c 'import sys; print(0.25 + 0.05 * float(sys.argv[1]))' "$D")
  python3 scripts/receiver_delay.py verify-hold --baseline "$OUT/net_hold_zero5.json" \
    --step "$OUT/net_hold_$D.json" --added-ms "$D" > "$OUT/net_hold_verify_$D.json" 2>&1
  HELD=$?
  python3 scripts/receiver_delay.py verify --baseline "$OUT/net_zero5.json" \
    --step "$OUT/net_$D.json" --added-ms "$D" --tolerance-ms "$TOL" \
    > "$OUT/net_verify_$D.json" 2>&1
  SEEN=$?
  if [ "$HELD" = 0 ] && [ "$SEEN" = 0 ]; then
    verdict network "$D ms" yes "the broker held $(json_ms "$OUT/net_hold_verify_$D.json" added_ms_held) ms; ping saw $(json_ms "$OUT/net_verify_$D.json" added_ms_measured) ms"
  else
    verdict network "$D ms" no "see net_hold_verify_$D.json and net_verify_$D.json"
  fi
done
broker_delay 0 > /dev/null 2>&1
fi

# --- 3. harness ------------------------------------------------------------------------------
# The football replay at ten times its speed sends in bursts, and in bursts the trip does not grow
# one-for-one with the delay; the campaign's own steady traffic is judged by each session's C0.
# Redis acknowledges in batches of 200, as every campaign run does.
if part harness; then
banner "3/5 receiver-only delay, seen by the harness at ${LOAD_PCT}% load"
SPEEDUP=$(assert_plan_rate "$PLAN" 10)
harness_cell () {  # index delay_ms
  local tag="harness_$1_d$2" stress_pid sampler_pid
  mkdir -p "$OUT/$tag"
  reap
  broker_delay "$2" > "$OUT/$tag/apply.txt" 2>&1
  stress-ng --cpu "$NCORES" --cpu-load "$LOAD_PCT" --timeout 3600s >/dev/null 2>&1 &
  stress_pid=$!
  sleep 3
  python3 scripts/util_sampler.py --out "$OUT/$tag/utilisation.csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!
  SBL_CONSUMER_WRAP="sudo ip netns exec sblrecv sudo -u $(id -un)" \
    timeout -k 30 $(( REPS * (MAXT / 10 + 240) + 180 )) \
    python3 scripts/run_concurrency_test.py 1 "$PLAN" "$REPS" \
      --speedup "$SPEEDUP" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --kafka-producer-extra "$KAFKA_PRODUCER_EXTRA" --redis-consumer-extra "$REDIS_CONSUMER_EXTRA" \
      --out-dir "$OUT/$tag" --trial-timeout "$(( MAXT / 10 + 400 ))" 2>&1 | tail -2
  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  kill -9 "$stress_pid" 2>/dev/null
  reap
}
harness_cell 1 0
harness_cell 2 "$HARNESS_DELAY_MS"
harness_cell 3 0
broker_delay 0 > /dev/null 2>&1
ADDED=$(json_field "$OUT/net_hold_verify_$HARNESS_DELAY_MS.json" added_ms_held 2>/dev/null)
NOTE="the delay the broker held"
if [ -z "$ADDED" ]; then
  ADDED="$HARNESS_DELAY_MS"
  NOTE="the delay as set; the broker's capture did not measure this step"
fi
for B in kafka redis; do
  BASE=$(python3 scripts/pilot_checks.py list --out-dir "$OUT/harness_1_d0" --backend "$B"
         python3 scripts/pilot_checks.py list --out-dir "$OUT/harness_3_d0" --backend "$B")
  STEP=$(python3 scripts/pilot_checks.py list --out-dir "$OUT/harness_2_d$HARNESS_DELAY_MS" \
         --backend "$B")
  # shellcheck disable=SC2086
  if python3 scripts/pilot_checks.py compare --baseline $BASE --step $STEP --added-ms "$ADDED" \
      > "$OUT/harness_verify_$B.json" 2>&1; then
    verdict harness "$B" yes "got-it steady; trip moved by $ADDED ms, $NOTE; never negative"
  else
    verdict harness "$B" no "see harness_verify_$B.json"
  fi
done
fi

# --- 4. go-first -----------------------------------------------------------------------------
# The earlier campaign's own script, unchanged, with its own settings: this replicates its result.
if part go-first; then
banner "4/5 go-first priority at ${LOAD_PCT}% load"
LEVELS="$LOAD_PCT" REPS=5 OUT="$OUT/go_first" bash cloud/campaigns/stamping_priority.sh \
  > "$OUT/go_first.log" 2>&1
python3 scripts/analyze_stamping_priority.py --depth "$OUT/go_first" --runs runs \
  --out "$OUT/go_first_model" > "$OUT/go_first_analysis.txt" 2>&1
if python3 scripts/pilot_checks.py go-first --table "$OUT/go_first_model/stamping_priority.csv" \
    > "$OUT/go_first_verdict.json" 2>&1; then
  verdict go-first "$LOAD_PCT%" yes "at least five-fold with disjoint intervals"
else
  verdict go-first "$LOAD_PCT%" no "see go_first_verdict.json and go_first_analysis.txt"
fi
fi

# --- 5. retest -------------------------------------------------------------------------------
banner "5/5 retest"
echo "  Run the pilot again on another day, after a stop and a start, and compare $OUT with"
echo "  that run's directory."
sudo python3 scripts/sched_settings.py read > "$OUT/settings_after.json"
sudo chown -R "$(id -u):$(id -g)" "$OUT" runs 2>/dev/null

banner "PILOT_COMPLETE"
cat "$OUT/verdicts.csv"
! grep -q ',no,' "$OUT/verdicts.csv"
