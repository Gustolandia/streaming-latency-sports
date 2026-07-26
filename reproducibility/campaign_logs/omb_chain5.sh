#!/usr/bin/env bash
# Chain 5: the cross-host case, then close the ledger.
#
# Every discard the single-host sweep found was a zero -- a millisecond-tick collision. Cross-host
# is the case the paper's claim is actually about: two stamps from two clocks that can genuinely
# disagree. The measured bound on this testbed is 12.3 ms against a 1 ms timestamp, so a negative
# is possible here; whether one occurs is the open question.
#
# Clocks are captured either side of the run. A negative is only interpretable against the offset
# that produced it, and chrony's own bound moves over hours.
set -u
cd ~/sbl || exit 1

echo "[chain5] waiting for chain4 to finish..."
while pgrep -f 'omb_chain4.sh' >/dev/null 2>&1; do sleep 60; done
echo "[chain5] chain4 done at $(date -u +%FT%TZ)"
sleep 30

snap_clocks () {
  D=docs/results/external/$1; mkdir -p "$D"
  chronyc tracking > "$D/driver.txt" 2>&1
  for h in 10.0.1.221 10.0.1.242 10.0.1.140; do
    ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=8 -o BatchMode=yes -o StrictHostKeyChecking=no       ubuntu@$h 'chronyc tracking' > "$D/$h.txt" 2>&1 || true
  done
  python3 scripts/clock_offset_report.py     --tracking driver="$D/driver.txt" --tracking broker1="$D/10.0.1.221.txt"     --tracking broker2="$D/10.0.1.242.txt" --tracking broker3="$D/10.0.1.140.txt"     --resolution-ms 1.0 --out "$D/clock_offsets.csv" 2>&1 | tail -12
}

echo "[chain5] === clocks before ==="
snap_clocks clocks_pre

echo "[chain5] === distributed run ==="
LOAD_PCT=88 DURATION_MIN=5 bash cloud/campaigns/omb_distributed.sh 2>&1 | tail -40
echo "[chain5] distributed step finished at $(date -u +%FT%TZ)"

echo "[chain5] === clocks after ==="
snap_clocks clocks_post

echo "[chain5] === full index, with hashes ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -10

echo "[chain5] === final analysis, from the ledger ==="
python3 scripts/analyze_omb_discards.py --ledger docs/results/external_campaigns_index.csv   --out docs/results/external/omb_discard_summary.csv 2>&1 | tail -40

echo "[chain5] ALL DONE $(date -u +%FT%TZ)"
