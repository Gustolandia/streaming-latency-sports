#!/usr/bin/env bash
# E1-REP: replicate the original E1 configuration exactly. Referee issue M2.
#
# The paper currently contains a contradiction it flags but does not resolve. E1 reports broker
# transport as near-equal between the systems (Kafka 0.79-1.00 ms against Redis 0.72-0.86 ms);
# a powered replication at a verified rate reports Kafka 0.54 ms against Redis 0.11 ms, a
# fivefold gap. Both cannot describe the same systems.
#
# Our hypothesis is that the two campaigns measured different EVENTS, not different systems. E1
# matched a median of seven events per run, and Section 7.4 shows those seven are the opening
# burst: the events queued behind Kafka's blocking first send, delivered together once it
# resolves. Transport measured over a burst that was released in a batch need not resemble
# transport measured over 127 events in steady state.
#
# That hypothesis makes a sharp prediction this campaign tests. Replaying E1's configuration
# (600 s window) at a verified rate and retaining every event, transport computed over ALL matched
# events should reproduce the powered result (~0.41 ms shift), while transport computed over only
# the first seven events of each run should reproduce E1's near-equality. If both hold, the
# discrepancy is explained and E1's numbers are re-labelled rather than withdrawn. If the first
# seven do NOT reproduce E1, we have a second unexplained instability and must say so.
#
# Design: N in {1, 9, 12}, 600 s window (E1's), verified true real-time rate, 5 replicates,
# distinct real match per feed, full per-event data retained.
#
# Usage:  nohup bash cloud/campaigns/e1_replication.sh > e1_rep.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/e1_rep}"
REPS="${REPS:-5}"
MAXT="${MAXT:-600}"          # E1's window, deliberately
NCORES=$(nproc)
mkdir -p "$OUT"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "E1 replication: speedup $SPEEDUP_RT, window ${MAXT}s (E1's), ${REPS} reps"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  sleep 2
}

for N in 1 9 12; do
  banner "E1-REP N=$N"
  reap
  mkdir -p "$OUT/n${N}"
  # A 600 s window means 600 s of wall time per trial at true real time.
  ceiling=$(( REPS * 2 * (MAXT + 150) + 300 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py "$N" "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $OUT/trace_n${N}.csv" \
      --redis-producer-extra "--trace-loop $OUT/trace_n${N}.csv" \
      --out-dir "$OUT/n${N}" --trial-timeout $(( MAXT + 400 )) 2>&1 | tail -2
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: N=$N hit shell timeout (${ceiling}s)"
  printf 'n_feeds,reps,max_t_sim,speedup,note\n%s,%s,%s,%s,replicates_E1_configuration\n' \
    "$N" "$REPS" "$MAXT" "$SPEEDUP_RT" > "$OUT/n${N}/condition.csv"
  reap
done

banner "E1_REPLICATION_COMPLETE"
