#!/usr/bin/env bash
# E-B2: the clean effect-size sweep. Referee issue M3.
#
# H1 -- "inversion risk falls as the measured quantity grows" -- is the paper's most consequential
# generalisation, and its quantitative support is currently a netem delay sweep we ourselves
# showed is confounded: injecting delay at an accelerated replay rate builds a queue, so measured
# variance climbed from 10 to 9,200 ms^2 across the sweep. A manipulation that changes both the
# mean AND the spread cannot isolate the effect of the mean.
#
# The fix is not a different delay mechanism but a different operating point. The confound came
# from offered load, not from netem: a per-delivery delay only queues when arrivals outpace the
# drain. At the workload's TRUE rate the feed is sparse (0.415 events/s), so a 50 ms one-way delay
# occupies about 2% of the delay pipe and cannot build a backlog. The same instrument that was
# confounded at 10x should be clean at 1x.
#
# That is a testable claim, not an assumption, so this campaign carries its own manipulation
# check: measured transport VARIANCE must stay flat across the delay levels. If it climbs the way
# it did at 10x, the sweep is confounded again and H1's slope stays unreported -- we would rather
# publish "still confounded" than a slope we cannot defend.
#
# Design: delays {0, 1, 5, 20, 50} ms applied identically to both systems, N=5 feeds carrying
# distinct real matches, verified true real-time rate, 180 s window, 5 replicates.
#
# Usage:  nohup bash cloud/campaigns/clean_effect_size.sh > clean_eb2.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/depth/eb2}"
REPS="${REPS:-5}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "clean effect-size sweep: speedup $SPEEDUP_RT (true real time), ${MAXT}s, ${REPS} reps"

# Delay is injected at the broker NIC by common.sh's netem(), which reaches the broker over the
# provisioning key and uses the large queue limit ~/netem.sh sets. Applying it at the broker
# means both systems see the same path, which is what makes the arms comparable.
#
# Manipulation check: netem must actually be in place. A sweep whose treatment silently failed
# would look exactly like a flat effect, and we have been caught by an unapplied treatment once
# already (Section 5.2, defect 6).
verify_netem () {
  local want="$1"
  local got
  got=$(remote_broker "tc qdisc show" 2>/dev/null | grep -c "delay ${want}ms")
  if [ "$want" = "0" ]; then
    remote_broker "tc qdisc show" 2>/dev/null | grep -q netem \
      && { echo "FATAL: netem still present after clear"; exit 1; } || return 0
  fi
  [ "$got" -ge 1 ] || { echo "FATAL: netem ${want}ms not applied at broker"; exit 1; }
}

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  sleep 2
}

trap 'netem 0' EXIT

for D in 0 1 5 20 50; do
  banner "E-B2 delay=${D}ms"
  reap
  mkdir -p "$OUT/d${D}"
  netem "$D"
  sleep 2
  verify_netem "$D"
  ceiling=$(( REPS * 2 * (MAXT + 120) + 180 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py 5 "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
      --out-dir "$OUT/d${D}" --trial-timeout $(( MAXT + 400 )) 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: d${D} hit shell timeout (${ceiling}s)"
  printf 'delay_ms,n_feeds,reps,max_t_sim,speedup,rate\n%s,5,%s,%s,%s,true_real_time\n' \
    "$D" "$REPS" "$MAXT" "$SPEEDUP_RT" > "$OUT/d${D}/condition.csv"
  reap
done

netem 0
banner "CLEAN_EFFECT_SIZE_COMPLETE"
