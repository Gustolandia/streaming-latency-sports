#!/usr/bin/env bash
# Chain 14: what is the rule? Retention quantised by the denominator of interval/tick.
#
# Everything measured so far is at the two extremes. Exact multiples (1000, 500, 250 msg/s ->
# interval/tick = 1, 2, 4) give spreads near 99 points. Incommensurate rates (457, 383) give
# spreads near 2. That establishes THAT commensurability matters and not WHAT the rule is.
#
# The phase account makes a sharper prediction. Write interval/tick as a fraction p/q in lowest
# terms. A producer paced at that interval visits exactly q distinct phases within the tick, so
# retention should be quantised into q+1 possible levels and the replicate spread should fall
# roughly as 100/q:
#
#   q=1  (2.000 = 2/1)   -> all-or-nothing, spread ~99      [measured: 99.5]
#   q=2  (2.500 = 5/2)   -> levels near 0, 50, 100
#   q=3  (3.333 = 10/3)  -> levels near 0, 33, 67, 100
#   q=4  (1.250 = 5/4)   -> levels near 0, 25, 50, 75, 100
#   q=8  (1.125 = 9/8)   -> nearly continuous
#   large (2.188)        -> continuous at T/tick             [measured: 2.1]
#
# Five replicates per rate rather than three: distinguishing q+1 discrete levels from a continuum
# needs enough draws to see the gaps, and three cannot show a gap.
#
# If spread instead stays near 99 for every rational rate regardless of q, the rule is
# integer or not and this prediction is wrong. If it stays near 2 for everything except exact
# integers, likewise. Recorded before the run.
set -u
cd ~/sbl || exit 1

guard () {
  local fb
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no         ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low (${fb}G)"; return 1; }
  timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null || { echo "[guard] broker unreachable"; return 1; }
  return 0
}

echo "[chain14] waiting for chain13..."
while pgrep -f 'bash omb_chain13' >/dev/null 2>&1; do sleep 60; done
sleep 20

# rate : interval/tick : q
for SPEC in 400:2.500:2 300:3.333:3 800:1.250:4 889:1.125:8; do
  RATE=${SPEC%%:*}; REST=${SPEC#*:}; RATIO=${REST%%:*}; Q=${REST##*:}
  echo "[chain14] === ${RATE} msg/s  interval/tick=${RATIO}  q=${Q} ==="
  for R in 1 2 3 4 5; do
    guard || exit 1
    CELL=docs/results/external/rate_q/r${RATE}_rep${R}
    mkdir -p "$CELL"
    MESSAGE_SIZE=200 PRODUCER_RATE=$RATE LOAD_PCT=0 OUT="$CELL" DURATION_MIN=3 WARMUP_MIN=0       timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
    echo "  rate=$RATE q=$Q rep=$R $(date -u +%H:%MZ)"
  done
done

echo "[chain14] === re-index ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -5
echo "[chain14] ALL DONE $(date -u +%FT%TZ)"
