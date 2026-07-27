#!/usr/bin/env bash
# Chain 17b -- the theta probe at the high-rate end, queued the moment P2's arm landed.
#
# P2 (1250/s, q=5) came out FLAT at the 2/5 grid point: 40.66 40.90 41.28 42.00 48.26. The
# pre-registered prediction (full spread, branches {40,60}) was computed from the POOLED
# continuous value theta = 0.495; the measured rate-local trend (51.2% at 333/s falling to 47.5%
# at 889/s) extrapolates to theta ~ 0.44 at 1250/s, and frac(5*0.44) = 0.20 predicts exactly the
# observed pinning. But no incommensurate arm exists above 889/s, so that extrapolation is
# unmeasured. This chain measures it.
#
#   1053/s: 1000/1053, gcd=1, q=1053 -> incommensurate. Interval 0.950 ms.
#   1219/s: 1000/1219, gcd=1, q=1219 -> incommensurate. Interval 0.820 ms -- right beside 1250/s.
#
# Reading, recorded in advance:
#   theta(1219) ~ 47%+ : the pooled prediction was right where it was made, and P2 genuinely
#                        missed -- the model loses a point, as pre-registered.
#   theta(1219) ~ 44%  : the trend holds; quantised predicts flat-at-40 (P(upper)=0.2) which is
#                        what P2 showed, and the miss was the extrapolation, not the grid.
#   theta(1219) ~ 41-42%: the 1250/s cluster is indistinguishable from continuous scatter and the
#                        P2 arm is degenerate in the corrected sense -- uninformative either way.
set -u
cd ~/sbl || exit 1

guard () {
  local fb db
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
        ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low"; return 1; }
  db=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
  [ "${db:-0}" -ge 5 ] || { echo "[guard] driver disk low"; return 1; }
  timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null \
    || { echo "[guard] broker unreachable"; return 1; }
}

echo "[chain17b] waiting for chain17..."
while pgrep -f "bash omb_chain17.sh" >/dev/null 2>&1; do sleep 120; done
sleep 30

for RATE in 1053 1219; do
  echo "[chain17b] === ${RATE}/s incommensurate theta probe ==="
  for R in 1 2 3 4; do
    guard || exit 1
    OUTD=docs/results/external/ultimate/r${RATE}_rep${R}
    mkdir -p "$OUTD"
    MESSAGE_SIZE=200 PRODUCER_RATE=$RATE LOAD_PCT=0 OUT="$OUTD" DURATION_MIN=3 WARMUP_MIN=0 \
      timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
    echo "  [ultimate/r${RATE}_rep${R}] $(date -u +%H:%MZ)"
  done
done
python3 scripts/index_external_campaigns.py --root docs/results/external \
  --out docs/results/external_campaigns_index.csv 2>&1 | tail -2
echo "[chain17b] ALL DONE $(date -u +%FT%TZ)"
