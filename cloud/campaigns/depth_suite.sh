#!/usr/bin/env bash
# Campaign D: the depth experiments that turn the measurement failure from a narrated
# accident into a characterised phenomenon. Design and hypotheses: docs/measurement_model.md
#
#   E-A   utilisation sweep      tests H2 (inversion follows scheduler waiting time)
#   E-A2  oversubscription sweep tests H4 (process count, not event rate, drives it)
#   E-B   effect-size sweep      tests H1 (inversion falls as the measured quantity grows)
#   E-C   symmetry intervention  tests H3/H6 (asymmetric stamping is what biases a comparison)
#
# The utilisation axis is obtained by RESTRICTING cores with taskset rather than by adding
# machines: pinning to one core makes rho -> 1 reachable with a modest workload and gives a
# cleaner sweep than a larger VM would.
#
# Usage:  bash cloud/campaigns/depth_suite.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

OUT="${OUT:-docs/results/depth}"
REPS="${REPS:-3}"
MAXT="${MAXT:-300}"
mkdir -p "$OUT"/{ea,ea2,eb,ec,trace}

command -v stress-ng >/dev/null || { echo "installing stress-ng"; sudo apt-get install -y -qq stress-ng >/dev/null 2>&1 || true; }
NCORES=$(nproc)
banner "depth suite starting on $NCORES cores"

# Run one concurrency trial under a controlled utilisation, then stop the load generator.
# BG is the number of stress-ng workers; CORES is the taskset mask width.
run_at_load () {
  local tag="$1" cores="$2" bg="$3" n="$4" extra="${5:-}"
  local stress_pid="" sampler_pid=""
  local util_csv="$OUT/$tag/utilisation.csv"
  mkdir -p "$OUT/$tag"

  if [ "$bg" -gt 0 ]; then
    stress-ng --cpu "$bg" --timeout 3600s >/dev/null 2>&1 &
    stress_pid=$!
    sleep 2
  fi

  # Measure achieved utilisation rather than assuming the nominal setting. H2 is a claim about
  # rho, and near saturation the requested load and the achieved load are different numbers.
  python3 scripts/util_sampler.py --out "$util_csv" --interval 0.5 >/dev/null 2>&1 &
  sampler_pid=$!

  taskset -c "0-$((cores-1))" \
    python3 scripts/run_concurrency_test.py "$n" "$PLAN" "$REPS" \
      --speedup 1 --max-t-sim "$MAXT" \
      --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
      --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
      --out-dir "$OUT/$tag" --trial-timeout 1800 $extra 2>&1 | tail -2

  kill -TERM "$sampler_pid" 2>/dev/null; wait "$sampler_pid" 2>/dev/null
  [ -n "$stress_pid" ] && { kill "$stress_pid" 2>/dev/null; wait "$stress_pid" 2>/dev/null; }
  # Record the manipulated settings alongside the achieved utilisation so the analysis can
  # separate "what we asked for" from "what we got".
  printf 'tag,cores,bg_workers,n_feeds\n%s,%s,%s,%s\n' "$tag" "$cores" "$bg" "$n" \
    > "$OUT/$tag/condition.csv"
  sleep 3
}

# ---- E-A: utilisation sweep -------------------------------------------------
# rho is varied two ways so the two are separable: fewer cores for the same work, and more
# competing work for the same cores.
for CORES in 1 2 4; do
  [ "$CORES" -le "$NCORES" ] || continue
  for BG in 0 1 2 4; do
    banner "E-A cores=$CORES bg=$BG"
    run_at_load "ea/c${CORES}_b${BG}" "$CORES" "$BG" 5
  done
done

# ---- E-A2: oversubscription at constant aggregate rate ----------------------
# Feed count rises while per-feed rate falls, so aggregate events/second is held roughly fixed.
# H4 predicts inversion tracks process count, not aggregate rate.
for N in 1 3 6 12; do
  banner "E-A2 N=$N (constant aggregate rate)"
  run_at_load "ea2/n${N}" 2 0 "$N"
done

# ---- E-B: effect-size sweep -------------------------------------------------
# Hold load fixed, move the true quantity being measured with netem. H1 predicts inversion
# rate falls as the measured quantity grows -- the central claim of the paper.
for D in 0 1 5 20 50; do
  banner "E-B delay=${D}ms"
  netem "$D"
  run_at_load "eb/d${D}" 2 2 5
done
netem 0

# ---- E-C: symmetry intervention --------------------------------------------
# Same load, two stamping designs. H3 predicts the between-system bias shrinks toward zero
# when both sides stamp the same way, while the noise does not.
for MODE in callback inline; do
  banner "E-C stamping=$MODE"
  if [ "$MODE" = inline ]; then
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer_confluent.py
  else
    export KAFKA_PRODUCER_SCRIPT=scripts/kafka_producer.py
  fi
  run_at_load "ec/${MODE}" 2 2 5 "--kafka-producer-extra \"--max-inflight 64 --trace-loop $OUT/trace/${MODE}.csv\""
done
unset KAFKA_PRODUCER_SCRIPT

banner "DEPTH_SUITE_COMPLETE"
