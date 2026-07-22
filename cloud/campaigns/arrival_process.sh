#!/usr/bin/env bash
# Campaign E-H: does the effect follow the arrival RATE, or football specifically?
#
# The paper's sharpest methodological claim is that the difference between the two brokers
# appears at the real workload's sparse arrival rate and vanishes under accelerated replay, so a
# benchmark driven by a dense synthetic publisher measures the regime where the difference is
# absent. That claim currently rests on one workload, which the paper concedes as an
# external-validity threat.
#
# This closes half of it. Three synthetic arrival processes at the SAME mean rate as the
# football feed (0.415 ev/s), differing only in how arrivals are distributed in time:
#
#   constant  perfectly regular   - the implicit model of a fixed-rate publisher
#   poisson   exponential gaps    - the standard stochastic assumption
#   bursty    idle-then-clump     - echoes football's duty cycle
#
# Predictions, stated before running (see docs/preregistration_depth.md for the discipline):
#   - if all three reproduce the ~103 ms producer offset, the effect follows the mean RATE and
#     the finding generalises to any sparse feed.
#   - if only `bursty` does, it follows the idle-then-burst DUTY CYCLE - narrower, but still
#     transferable and arguably more interesting.
#   - if none does, the effect is specific to the real corpus and the claim must be narrowed to
#     the football workload.
#
# Usage:  bash cloud/campaigns/arrival_process.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

OUT="${OUT:-docs/results/arrival}"
REPS="${REPS:-6}"
DURATION="${DURATION:-600}"
RATE="${RATE:-0.415}"
SYN_DIR="${SYN_DIR:-data/synthetic}"
mkdir -p "$OUT"

for ARRIVAL in constant poisson bursty; do
  # One plan directory per arrival process, shaped like the real plans so --plans-dir works.
  PLAN_DIR="$SYN_DIR/$ARRIVAL/match_900000"
  mkdir -p "$PLAN_DIR"
  python3 scripts/make_synthetic_plan.py --arrival "$ARRIVAL" --rate "$RATE" \
    --duration "$DURATION" --out "$PLAN_DIR/replay_plan.csv"

  # Synthetic plans are uncompressed, real ones are 120x. Derive both so the two plan
  # families cannot silently diverge.
  SPEEDUP_RT=$(assert_plan_rate "$PLAN_DIR/replay_plan.csv" 1)
  SPEEDUP_10=$(assert_plan_rate "$PLAN_DIR/replay_plan.csv" 10)
  banner "E-H arrival=$ARRIVAL rate=$RATE speedup=$SPEEDUP_RT"
  # N=1 at true real time: the condition in which the offset was observed. Holding N=1 keeps
  # the driver unsaturated, so this measures the arrival process and not scheduler contention.
  python3 scripts/run_concurrency_test.py 1 "$PLAN_DIR/replay_plan.csv" "$REPS" \
    --speedup "$SPEEDUP_RT" --max-t-sim "$DURATION" \
    --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
    --plans-dir "$SYN_DIR/$ARRIVAL" \
    --kafka-producer-extra "--max-inflight 64 --trace-loop $OUT/trace_${ARRIVAL}.csv" \
    --out-dir "$OUT/$ARRIVAL" --trial-timeout 1800 2>&1 | tail -2

  # The accelerated counterpart. The whole claim is that the offset disappears at 10x; this is
  # the within-campaign control for it rather than a comparison across campaigns.
  banner "E-H arrival=$ARRIVAL accelerated 10x"
  python3 scripts/run_concurrency_test.py 1 "$PLAN_DIR/replay_plan.csv" "$REPS" \
    --speedup "$SPEEDUP_10" --max-t-sim "$DURATION" \
    --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
    --plans-dir "$SYN_DIR/$ARRIVAL" --kafka-producer-extra "--max-inflight 64" \
    --out-dir "$OUT/${ARRIVAL}_10x" --trial-timeout 1800 2>&1 | tail -2
done

banner "ARRIVAL_PROCESS_COMPLETE"
