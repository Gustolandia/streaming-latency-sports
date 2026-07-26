#!/usr/bin/env bash
# E-X4: is OMB's discard a millisecond-tick collision, or a causality violation?
#
# The split counter says every discarded sample on this path is exactly zero microseconds and
# none is negative: 50,000 zeros, 0 negatives, 975 kept, on an idle machine. Two explanations
# survive that observation and they make opposite predictions.
#
#   RESOLUTION.  OMB computes end-to-end latency in microseconds from record.timestamp(), which
#                is millisecond-resolution under Kafka's default CreateTime semantics. Whenever
#                publish and receive land in the same millisecond the difference is 0 us, fails
#                the `> 0` guard, and is dropped. On a 0.2-0.5 ms path most samples collide.
#                PREDICTION: lengthen the latency past 1 ms and the zeros collapse.
#
#   CAUSALITY.   The zeros are inversions that happen to round to zero.
#                PREDICTION: lengthening the latency does nothing, because a stall long enough to
#                invert a 0.3 ms interval will also invert a 3 ms one.
#
# This sweeps message size, which lengthens transport without touching the scheduler -- the same
# manipulation as E-A10, for the same reason. It is the cleanest discriminator available, because
# the two accounts differ in sign of response rather than in magnitude.
#
# A third possibility is worth stating so it is not mistaken for either: if the zeros collapse AND
# negatives appear at the larger sizes, both mechanisms are present and the original single counter
# was hiding the interesting one behind the boring one.
#
# Usage:
#   nohup bash cloud/campaigns/omb_resolution_test.sh > omb_res.log 2>&1 &
#   SIZES="200 65536" REPS=1 bash cloud/campaigns/omb_resolution_test.sh
set -u

cd ~/sbl || exit 1

SIZES="${SIZES:-200 4096 65536 262144}"
REPS="${REPS:-2}"
DURATION_MIN="${DURATION_MIN:-3}"
LOAD_PCT="${LOAD_PCT:-0}"
SWEEP_OUT="${SWEEP_OUT:-docs/results/external/resolution}"
COMBINED="$SWEEP_OUT/omb_resolution.csv"

case "$SWEEP_OUT" in
  /*) echo "FATAL: SWEEP_OUT must be relative to ~/sbl (got '$SWEEP_OUT')"; exit 1 ;;
esac

mkdir -p "$SWEEP_OUT"
printf 'message_size,rep,load_pct,discarded_total,discarded_zero,discarded_negative,most_negative_micros,kept,zero_share\n' > "$COMBINED"

echo "=== OMB resolution test starting $(date -u +%FT%TZ) ==="
echo "    sizes: $SIZES   reps: $REPS   load: ${LOAD_PCT}%   ${DURATION_MIN}min per cell"

for S in $SIZES; do
  for R in $(seq 1 "$REPS"); do
    CELL="$SWEEP_OUT/s${S}_rep${R}"
    echo "--- size ${S}B rep ${R}  $(date -u +%FT%TZ) ---"
    while pgrep -x stress-ng >/dev/null || pgrep -f 'run_concurrency_test\.py' >/dev/null; do
      sleep 30
    done
    mkdir -p "$CELL"

    # MESSAGE_SIZE is threaded through to the workload yaml by omb_discard_count.sh.
    MESSAGE_SIZE="$S" LOAD_PCT="$LOAD_PCT" OUT="$CELL" DURATION_MIN="$DURATION_MIN" \
      timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -5
    rc=${PIPESTATUS[0]}

    RES="$CELL/omb_loaded_result.csv"
    if [ "$rc" != "0" ] || [ ! -s "$RES" ]; then
      echo "CELL FAILED size=${S} rep=${R} rc=$rc -- no row written"
      continue
    fi

    python3 - "$RES" "$S" "$R" "$LOAD_PCT" "$COMBINED" <<'PY'
import csv, sys
res, size, rep, load, combined = sys.argv[1:6]
with open(res, newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
if not rows:
    sys.exit(0)
r = rows[0]


def n(k):
    try:
        return int(r.get(k) or 0)
    except ValueError:
        return 0


zero, neg, kept = n("discarded_zero"), n("discarded_negative"), n("kept")
seen = zero + neg + kept
# The share of everything the harness saw that it dropped for being exactly zero. This is the
# number the resolution account predicts will fall as the message grows.
share = round(zero / seen, 4) if seen else ""
with open(combined, "a", newline="", encoding="utf-8") as fh:
    csv.writer(fh).writerow([size, rep, load, n("discarded_total"), zero, neg,
                             n("most_negative_micros"), kept, share])
PY
    echo "recorded: $(tail -1 "$COMBINED")"
  done
done

echo
echo "=== resolution test complete $(date -u +%FT%TZ) ==="
cat "$COMBINED"
echo
echo "Reading it: zero_share falling with size supports RESOLUTION; flat supports CAUSALITY;"
echo "negatives appearing at the larger sizes means both are present."
echo "=== OMB_RESOLUTION_COMPLETE ==="
