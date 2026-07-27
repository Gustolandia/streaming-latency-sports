#!/usr/bin/env bash
# Chain 15: odd q only, because only odd q can discriminate.
#
# The q sweep chose q = 2, 3, 4, 8. Three of those are EVEN, and with T_true near 0.5 ms an even
# grid contains the point 0.5 exactly -- q=2 predicts 1/2, q=4 predicts 2/4, q=8 predicts 4/8, all
# of which equal the continuous prediction T_true/tick. Those arms cannot separate the two
# accounts and duly returned ~50% with small deviations. q=3 was the only discriminating arm in
# the sweep, and it separated cleanly: five of five outside the incommensurate range.
#
# One discriminating point is thin for a law. Two more exist at integer rates:
#
#   625 msg/s -> 1.600 ms = 8/5, q=5. Phases 0,.2,.4,.6,.8; with T~0.5 the .6 and .8 phases cross
#                a boundary, so retention ~ 2/5 = 40%, well clear of 50%.
#   875 msg/s -> 1.143 ms = 8/7, q=7. Retention ~ 3/7 = 43%, again clear of 50%.
#
# Predicted before the run: both land near 40% and 43% respectively, outside the incommensurate
# range of 46.5-53.8. If either sits at ~50% instead, the q=3 result was a coincidence and
# quantisation is withdrawn.
set -u
cd ~/sbl || exit 1

guard () {
  local fb
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no         ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low"; return 1; }
  timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null || { echo "[guard] broker unreachable"; return 1; }
}

echo "[chain15] waiting for chain14..."
while pgrep -f 'bash omb_chain14' >/dev/null 2>&1; do sleep 60; done
sleep 20

for SPEC in 625:5:40 875:7:43; do
  RATE=${SPEC%%:*}; REST=${SPEC#*:}; Q=${REST%%:*}; PRED=${REST##*:}
  echo "[chain15] === ${RATE} msg/s  q=${Q}  predicted ~${PRED}% ==="
  for R in 1 2 3 4 5; do
    guard || exit 1
    CELL=docs/results/external/rate_q/r${RATE}_rep${R}
    mkdir -p "$CELL"
    MESSAGE_SIZE=200 PRODUCER_RATE=$RATE LOAD_PCT=0 OUT="$CELL" DURATION_MIN=3 WARMUP_MIN=0       timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
    echo "  rate=$RATE q=$Q rep=$R $(date -u +%H:%MZ)"
  done
done

echo "[chain15] === re-index ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -5
echo "[chain15] ALL DONE $(date -u +%FT%TZ)"
