#!/usr/bin/env bash
# Chain 8: is the discard rate set by path speed, or by phase against the millisecond grid?
#
# Across 19 unsaturated cells OMB's own publish latency sits at 0.3-0.4 ms -- essentially
# constant -- while retention ranges from 0.36% to 100%. Path speed therefore does not explain
# retention, and the model that retention is simply P(latency >= one tick) is insufficient.
#
# Candidate mechanism: the producer is paced at 500 msg/s, one send every 2.000 ms, an exact
# integer number of millisecond ticks. If sends are phase-locked to the clock grid then every
# sample in a run sits at the same offset within its millisecond, so either nearly all of them
# cross a tick boundary before delivery or nearly none do -- all-or-nothing retention, which is
# what we see. A rate incommensurate with the grid should dephase the samples and give stable
# INTERMEDIATE retention instead.
#
# Predictions, recorded before the run:
#   500 msg/s (2.000 ms, commensurate)  -> retention near 0% or near 100%, unstable across reps
#   457 msg/s (2.188 ms, incommensurate) -> retention intermediate and STABLE across reps
#   383 msg/s (2.611 ms, incommensurate) -> likewise
# If all three behave the same, the phase hypothesis is wrong and I will say so.
set -u
cd ~/sbl || exit 1

echo "[chain8] waiting for chain7 to finish..."
while pgrep -f 'omb_chain7.sh' >/dev/null 2>&1; do sleep 60; done
echo "[chain8] chain7 done at $(date -u +%FT%TZ)"
sleep 20

for RATE in 500 457 383; do
  echo "[chain8] === producer rate ${RATE} msg/s ==="
  for R in 1 2 3 4; do
    CELL=docs/results/external/rate_phase/r${RATE}_rep${R}
    mkdir -p "$CELL"
    PRODUCER_RATE=$RATE LOAD_PCT=0 OUT="$CELL" DURATION_MIN=3 WARMUP_MIN=0       timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -4
    echo "  rate=$RATE rep=$R rc=${PIPESTATUS[0]} $(date -u +%H:%MZ)"
  done
done

echo "[chain8] === re-index and re-join ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -8
python3 scripts/omb_retention_table.py --root docs/results/external --omb-dir ~/omb   --out docs/results/external/omb_retention.csv 2>&1 | tail -50

echo "[chain8] ALL DONE $(date -u +%FT%TZ)"
