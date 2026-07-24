#!/usr/bin/env bash
# E4: broker transport at a VERIFIED true real-time replay rate, properly powered.
#
# Why this run exists. The paper's surviving claim is that Kafka and Redis broker transport are
# equivalent within 1 ms and that neither degrades with concurrency. That rests on the E1 corpus
# (164 runs, medians 0.79-1.00 ms for Kafka against 0.72-0.86 ms for Redis).
#
# Two problems with E1 surfaced while checking its provenance.
#
#   1. Its replay rate is not recoverable. The per-run summaries record `speedup`, but E1's raw
#      runs are gone from both hosts and only the aggregated CSVs survive. The commit that added
#      them says "TRUE real-time rate"; the campaign script reconstructed afterwards says
#      --speedup 10; and the plans carry a baked-in 120x compression, so --speedup 1 would also
#      have meant 120x. The flag's semantics were corrected 21 hours after those runs. E1 was
#      therefore replayed at 1x, 120x or 1200x and the artefacts do not say which.
#
#   2. Three N=1 runs at a verified true real-time rate (speedup derived from the plan and the
#      achieved rate checked against wall time) do not reproduce the equivalence: Kafka
#      transport reads 0.452 ms against Redis's 0.091 ms, a five-fold gap, with both systems
#      well BELOW their E1 values. That is what an idle machine would look like if E1 had been
#      accelerated enough to load the driver.
#
# Three runs cannot settle a headline claim, so this powers the comparison properly at a rate
# that is derived, verified before the campaign starts, and recorded per condition.
#
# Design: N in {1, 9, 12} -- the single feed plus the two extremes of the kickoff-derived range
# E1 used -- at 180 s of match time, 15 replicates. Everything else matches E1: same plans
# directory, same --max-inflight 64, distinct real match per feed.
#
# Pre-registered: the quantity is median broker transport per run; the comparison is the
# Hodges-Lehmann shift between backends at each N, with the 1 ms equivalence margin the paper
# already uses. We report whichever way it falls, including if it contradicts Section 7.1.
#
# Usage:  nohup bash cloud/campaigns/transport_realtime.sh > transport_rt.log 2>&1 &
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
set +e

PLAN=$(find data/processed/replay_plans -name replay_plan.csv | head -1)
PLANS_DIR="$(dirname "$(dirname "$PLAN")")"
: "${PLAN:?no real match plan found under data/processed/replay_plans}"

OUT="${OUT:-docs/results/transport_rt}"
REPS="${REPS:-15}"
MAXT="${MAXT:-180}"
NCORES=$(nproc)
mkdir -p "$OUT"

if [ "$NCORES" -lt 4 ]; then echo "FATAL: $NCORES cores; wrong host"; exit 1; fi

SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
banner "transport at true real time: speedup $SPEEDUP_RT, ${MAXT}s, ${REPS} reps, ${NCORES} cores"

reap () {
  pkill -f "kafka_producer.py|redis_producer.py|kafka_consumer.py|redis_consumer.py" 2>/dev/null || true
  sleep 2
}

for N in 1 9 12; do
  banner "N=$N"
  reap
  mkdir -p "$OUT/n${N}"
  # Feeds run concurrently, so wall time per replicate is one window plus start-up.
  ceiling=$(( REPS * 2 * (MAXT + 90) + 300 ))
  timeout -k 30 "$ceiling" \
    python3 scripts/run_concurrency_test.py "$N" "$PLAN" "$REPS" \
      --speedup "$SPEEDUP_RT" --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" \
      --kafka-producer-extra "--max-inflight 64 --trace-loop $OUT/trace_n${N}.csv" \
      --redis-producer-extra "--trace-loop $OUT/trace_n${N}.csv" \
      --out-dir "$OUT/n${N}" --trial-timeout $(( MAXT + 400 )) 2>&1 | tail -3
  [ "${PIPESTATUS[0]}" = 124 ] && echo "  NOTE: N=$N hit shell timeout (${ceiling}s)"
  printf 'n_feeds,reps,max_t_sim,speedup,verified\n%s,%s,%s,%s,yes\n' \
    "$N" "$REPS" "$MAXT" "$SPEEDUP_RT" > "$OUT/n${N}/condition.csv"
  reap
done

banner "TRANSPORT_REALTIME_COMPLETE"
