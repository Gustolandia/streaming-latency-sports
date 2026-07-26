#!/usr/bin/env bash
# Chain 7: characterise the bimodality at ONE fixed configuration.
#
# Five runs at 200 B and 0% background load have retained 1.51%, 0.83%, 100%, 100% and 0.36% of
# their samples. Those are two modes with nothing between them, which is what a threshold looks
# like rather than a noisy rate: either the median latency falls below one millisecond tick and
# nearly every sample computes to zero, or it reaches one tick and nearly none do.
#
# Five observations cannot establish that, and the claim it supports is worth establishing: at a
# fixed configuration this benchmark's reported latency summary is a coin flip between being
# computed from ~100% of its samples and ~0.4% of them, with nothing in its output to say which.
#
# Ten more reps at the identical configuration, giving fifteen in total. Deliberately no sweep --
# the variable under study is the run-to-run variation itself, so nothing else may move.
set -u
cd ~/sbl || exit 1

echo "[chain7] waiting for chain6 to finish..."
while pgrep -f 'omb_chain6.sh' >/dev/null 2>&1; do sleep 60; done
echo "[chain7] chain6 done at $(date -u +%FT%TZ)"
sleep 20

echo "[chain7] === 10 reps, 200 B, 0% load, nothing else varying ==="
LEVELS='0' REPS=10 DURATION_MIN=3 SWEEP_OUT=docs/results/external/bimodality   bash cloud/campaigns/omb_load_sweep.sh 2>&1 | tail -40
echo "[chain7] sweep exit=$? at $(date -u +%FT%TZ)"

echo "[chain7] === re-index and re-join ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -8
python3 scripts/omb_retention_table.py --root docs/results/external --omb-dir ~/omb   --out docs/results/external/omb_retention.csv 2>&1 | tail -50

echo "[chain7] ALL DONE $(date -u +%FT%TZ)"
