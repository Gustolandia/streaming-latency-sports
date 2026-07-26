#!/usr/bin/env bash
# Chain 9: retry the cross-host run without the background load.
#
# Six distributed attempts have now failed, all in OMB's own worker protocol -- the latest with
# IllegalArgumentException at HttpWorkerClient:194, after both workers answered and the benchmark
# had produced three publish-rate lines. The coordinator failed parsing a worker response.
#
# Hypothesis: both hosts are pinned at 88% CPU and the worker's HTTP threads are starved, so a
# response arrives malformed or late. It is testable by removing the load.
#
# Removing it does not make the run useless. The background load exists to provoke SCHEDULING
# stalls, which is the occupancy channel. The cross-host question is about the CLOCK channel, and
# the measured bound between these hosts -- 8.7 ms against a 1 ms timestamp -- does not depend on
# CPU load. An unloaded distributed run still tests whether cross-host subtraction produces
# negative samples, which is the open question.
#
# Two attempts: unloaded, then at 50%. If unloaded succeeds and 50% fails, the failure is load
# and that is worth stating; the paper currently says only that the attempts failed.
set -u
cd ~/sbl || exit 1

echo "[chain9] waiting for chain8 to finish..."
while pgrep -f 'omb_chain8.sh' >/dev/null 2>&1; do sleep 60; done
echo "[chain9] chain8 done at $(date -u +%FT%TZ)"
sleep 20

for L in 0 50; do
  echo "[chain9] === distributed, background load ${L}% ==="
  OUT=docs/results/external/dist_load${L} mkdir -p docs/results/external/dist_load${L}
  LOAD_PCT=$L DURATION_MIN=4 OUT=docs/results/external/dist_load${L}     bash cloud/campaigns/omb_distributed.sh 2>&1 | tail -25
  echo "[chain9] load=${L} finished at $(date -u +%FT%TZ)"
  sleep 30
done

echo "[chain9] === re-index ==="
python3 scripts/index_external_campaigns.py --root docs/results/external   --out docs/results/external_campaigns_index.csv 2>&1 | tail -8

echo "[chain9] ALL DONE $(date -u +%FT%TZ)"
