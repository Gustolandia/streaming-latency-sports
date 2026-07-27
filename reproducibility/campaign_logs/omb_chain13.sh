#!/usr/bin/env bash
# Chain 13: recover from the broker outage, decisive cells first.
#
# The broker's disk filled and Kafka died, taking seven cells with it. Retention caps are now in
# place so it cannot recur, but this chain adds the two guards whose absence let it run for hours
# unnoticed: a disk check and a broker reachability check BEFORE each cell. A campaign that cannot
# reach its broker should stop, not spend eight minutes proving it.
#
# Order is by decisiveness, so that if anything fails again the most valuable data already exists:
#   1. 32 KB and 64 KB at 457 msg/s -- these DECIDE retention = min(1, T_true/tick).
#      Predicted 78% and 100% against a 52% baseline. Nothing else tests the law.
#   2. 4 KB and 8 KB, the cells the outage destroyed -- they fill the middle of the curve.
#   3. rate_phase2 -- B2 confirmation at two more exact multiples.
set -u
cd ~/sbl || exit 1

guard () {   # refuse to start a cell unless the broker is reachable and both disks have room
  local free_drv free_brk
  free_drv=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
  if [ "${free_drv:-0}" -lt 5 ]; then echo "[guard] driver disk below 5G -- stopping"; return 1; fi
  free_brk=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no               ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  if [ "${free_brk:-0}" -lt 5 ]; then echo "[guard] BROKER disk below 5G (${free_brk}G) -- stopping"; return 1; fi
  if ! timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null; then
    echo "[guard] broker port 19092 unreachable -- stopping"; return 1; fi
  return 0
}

run_cell () {  # run_cell <outdir> <size> <rate>
  guard || return 1
  mkdir -p "$1"
  MESSAGE_SIZE="$2" PRODUCER_RATE="$3" LOAD_PCT=0 OUT="$1" DURATION_MIN=3 WARMUP_MIN=0     timeout -k 60 1800 bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -3
  return 0
}

echo "[chain13] === 1/3 decisive cells: 32 KB and 64 KB at 457 msg/s ==="
for S in 32768 65536; do
  for R in 1 2 3; do
    run_cell "docs/results/external/tprobe/s${S}_rep${R}" "$S" 457 || exit 1
    echo "  size=$S rep=$R $(date -u +%H:%MZ)"
  done
done

echo "[chain13] === 2/3 refilling the cells the outage destroyed ==="
for S in 2048 4096 8192; do
  for R in 1 2 3; do
    D=docs/results/external/tprobe/s${S}_rep${R}
    if [ -s "$D/omb_loaded_result.csv" ] && grep -q ',1,' "$D/omb_loaded_result.csv" 2>/dev/null; then
      echo "  size=$S rep=$R already valid, skipping"; continue; fi
    run_cell "$D" "$S" 457 || exit 1
    echo "  size=$S rep=$R $(date -u +%H:%MZ)"
  done
done

echo "[chain13] === 3/3 commensurability confirmation ==="
for RATE in 1000 250 333 611; do
  for R in 1 2 3; do
    run_cell "docs/results/external/rate_phase2/r${RATE}_rep${R}" 200 "$RATE" || exit 1
    echo "  rate=$RATE rep=$R $(date -u +%H:%MZ)"
  done
done

echo "[chain13] === re-index and re-join ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -6
python3 scripts/omb_retention_table.py --root docs/results/external --omb-dir ~/omb   --out docs/results/external/omb_retention.csv 2>&1 | tail -10
echo "[chain13] ALL DONE $(date -u +%FT%TZ)"
