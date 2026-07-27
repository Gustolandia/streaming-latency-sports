#!/usr/bin/env bash
# Chain 16: the same q at a different rate -- separating q from the rate that carries it.
#
# Every q measured so far appears at exactly one rate, so "retention is set by q" and "300 msg/s
# happens to give 33%" are not separated by any measurement we have. That is a hole in the design
# rather than a further extension of it.
#
# 600 msg/s gives an interval of 1.667 ms = 5/3, so q=3 -- the same denominator as 300 msg/s but
# at HALF the interval. The phase set is identical (0, 1/3, 2/3), so the prediction is identical:
#
#   600 msg/s, q=3  ->  retention ~ 1/3 = 33%, matching 300 msg/s
#
# If it lands near 33% the governing variable is q and not the rate. If it lands near 50% like the
# incommensurate rates, or anywhere off the thirds grid, then q=3 at 300 msg/s was a property of
# that rate and quantisation does not generalise.
#
# Higher odd q are deliberately NOT run. The prediction converges on 50% as q grows
# (1/3=33, 2/5=40, 3/7=43, 4/9=44), so q=9 and beyond fall inside the incommensurate range of
# 46.5-53.8 and cannot discriminate however they land. Power falls as q rises; small odd q are
# the informative ones.
set -u
cd ~/sbl || exit 1

guard () {
  local fb
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
        ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low"; return 1; }
  timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null \
    || { echo "[guard] broker unreachable"; return 1; }
}

echo "[chain16] waiting for chains 14 and 15..."
while pgrep -f 'bash omb_chain1[45]' >/dev/null 2>&1; do sleep 60; done
sleep 20

echo "[chain16] === 600 msg/s  1.667 ms = 5/3  q=3  predicted ~33%, same as 300 msg/s ==="
for R in 1 2 3 4 5; do
  guard || exit 1
  CELL=docs/results/external/rate_q/r600_rep${R}
  mkdir -p "$CELL"
  MESSAGE_SIZE=200 PRODUCER_RATE=600 LOAD_PCT=0 OUT="$CELL" DURATION_MIN=3 WARMUP_MIN=0 \
    timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
  echo "  rate=600 q=3 rep=$R $(date -u +%H:%MZ)"
done

echo "[chain16] === re-index ==="
python3 scripts/index_external_campaigns.py --root docs/results/external \
  --out docs/results/external_campaigns_index.csv 2>&1 | tail -5
echo "[chain16] ALL DONE $(date -u +%FT%TZ)"
