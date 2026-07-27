#!/usr/bin/env bash
# Chain 17 -- the comprehensive run. Every defected cell repeated, every arm filled to n>=5, and
# one block per pre-registered prediction of the general model (docs/general_model.md).
#
# The model: retention is the occupancy of an arc of width theta = T_true/tau by the orbit of the
# rotation phi -> phi + Delta mod tau. Rational Delta/tau = p/q gives a q-point orbit, so a run
# retains floor(q*theta)/q or ceil(q*theta)/q with P(upper) = frac(q*theta); irrational
# equidistributes to theta (B1); pacing drift eps crosses branches mid-run once N*eps*Delta spans
# a grid cell (threshold eps* ~ 1/(pN)).
#
# Blocks and their pre-registered predictions (falsifiers in docs/general_model.md):
#   A fill    -- complete existing arms to n>=5; repeats the one defected cell (r600_rep5,
#                shutdown hook lost). No new claims; closes the record.
#   B newq    -- P2: 1250/s = 4/5 (q=5, first arm with Delta < tau and p < q) -> full, {40,60}.
#                P3:  700/s = 10/7 (q=7 second rate) -> full, {42.9,57.1}.
#                P4:  900/s = 10/9 (q=9) -> full, spread ~11.1. The superseded median test said
#                     q>=9 cannot discriminate; the corrected class test says it can.
#   C branch  -- P1: q=3 pooled to n~20; upper-branch count ~ Binomial(n, frac(3*theta_local)).
#   D payload -- P6: theta moves with payload (457/s measured: .685 at 32K, .853 at 64K).
#                At 300/s (q=3): 32K -> frac(q*theta)=.055 -> FLAT pinned at 66.7;
#                                64K -> frac=.56 -> FULL again, branches {66.7,100}.
#                One manipulation, onto the grid point and off it.
#   E duration-- P5: drift crossover. 500/s at 1 min -> purer branches than 3 min; at 10 min ->
#                more mid-run crossings (replicates >5 pts from both branches).
#
# Campaign layout (ledger keys on campaign+cell, so numbering restarts cleanly):
#   ultimate/            pure rate cells (merged into the rate arms by the analyser)
#   ultimate_pay300/     s{bytes}_rep{k} at PRODUCER_RATE=300
#   ultimate_dur1/       r500_rep{k} at DURATION_MIN=1
#   ultimate_dur10/      r500_rep{k} at DURATION_MIN=10
# ultimate_pay300/_dur* are deliberately NOT in the analyser's RATE_CAMPAIGNS: mixing payloads or
# durations into the rate arms would corrupt the spreads they exist to test.
set -u
cd ~/sbl || exit 1

guard () {
  local fb db
  fb=$(ssh -i ~/.ssh/oci_sbl -o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=no \
        ubuntu@10.0.1.221 "df --output=avail -BG / | tail -1 | tr -dc '0-9'" 2>/dev/null)
  [ "${fb:-0}" -ge 5 ] || { echo "[guard] broker disk low (${fb:-?}G)"; return 1; }
  db=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
  [ "${db:-0}" -ge 5 ] || { echo "[guard] driver disk low (${db:-?}G)"; return 1; }
  timeout 8 bash -c "echo > /dev/tcp/10.0.1.221/19092" 2>/dev/null \
    || { echo "[guard] broker unreachable"; return 1; }
}

cell () {  # cell CAMPAIGN NAME RATE SIZE DUR
  local camp=$1 name=$2 rate=$3 size=$4 dur=$5
  guard || exit 1
  local out=docs/results/external/$camp/$name
  mkdir -p "$out"
  MESSAGE_SIZE=$size PRODUCER_RATE=$rate LOAD_PCT=0 OUT="$out" DURATION_MIN=$dur WARMUP_MIN=0 \
    timeout -k 60 $(( (dur+27)*60 )) bash cloud/campaigns/omb_discard_count.sh 2>&1 | tail -2
  echo "  [$camp/$name] rate=$rate size=$size dur=${dur}m $(date -u +%H:%MZ)"
}

reindex () {
  python3 scripts/index_external_campaigns.py --root docs/results/external \
    --out docs/results/external_campaigns_index.csv 2>&1 | tail -2
}

echo "[chain17] START $(date -u +%FT%TZ)"

echo "[chain17] === A: fill every arm to n>=5 (incl. the defected r600 rep) ==="
for R in 1 2; do cell ultimate r1000_rep$R 1000 200 3; done
for R in 1 2; do cell ultimate r250_rep$R   250 200 3; done
cell ultimate r500_rep1  500 200 3
cell ultimate r600_rep1  600 200 3
cell ultimate r457_rep1  457 200 3
cell ultimate r383_rep1  383 200 3
for R in 1 2; do cell ultimate r611_rep$R   611 200 3; done
for R in 1 2; do cell ultimate r333_rep$R   333 200 3; done
reindex

echo "[chain17] === B: new denominators -- P2 (1250/s q=5), P3 (700/s q=7), P4 (900/s q=9) ==="
for R in 1 2 3 4 5; do cell ultimate r1250_rep$R 1250 200 3; done
for R in 1 2 3 4 5; do cell ultimate r700_rep$R   700 200 3; done
for R in 1 2 3 4 5; do cell ultimate r900_rep$R   900 200 3; done
reindex

echo "[chain17] === C: branch-probability power at q=3 and q=5 -- P1 ==="
for R in 1 2 3 4 5; do cell ultimate r300_rep$R 300 200 3; done
for R in 1 2 3 4 5; do cell ultimate r625_rep$R 625 200 3; done
reindex

echo "[chain17] === D: payload x q -- P6 (32K pins q=3 at 66.7; 64K frees it) ==="
for R in 1 2 3 4 5; do cell ultimate_pay300 s32768_rep$R 300 32768 3; done
for R in 1 2 3 4 5; do cell ultimate_pay300 s65536_rep$R 300 65536 3; done
reindex

echo "[chain17] === E: drift crossover -- P5 (duration sweep at 500/s) ==="
for R in 1 2 3 4 5; do cell ultimate_dur1  r500_rep$R 500 200 1;  done
for R in 1 2 3;     do cell ultimate_dur10 r500_rep$R 500 200 10; done
reindex

echo "[chain17] ALL DONE $(date -u +%FT%TZ)"
