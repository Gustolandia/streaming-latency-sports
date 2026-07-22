#!/usr/bin/env bash
# Full campaign sequence, in the order requested: depth suite, then M1, then the extra runs.
#
# Runs a PRE-FLIGHT first and refuses to continue if it fails. The pre-flight exists because
# the previous attempt burned eight hours producing data at 120x real time while its flags said
# 1x: the plans carry a baked-in 120x compression, the run completed normally, and the numbers
# looked plausible. Deriving the speedup is not enough on its own -- the derivation has to be
# checked against what the machine actually did.
#
# Usage:  nohup bash cloud/campaigns/run_all.sh > run_all.log 2>&1 &
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

echo "=== run_all start $(date -u +%FT%TZ) on $(hostname) ==="
echo "cores=$(nproc)  mem=$(free -g | awk '/^Mem:/{print $2}')GB"

# A four-core box is the driver; anything smaller means we are on the wrong machine again.
if [ "$(nproc)" -lt 4 ]; then
  echo "FATAL: only $(nproc) core(s). This is not the driver - check the target host."
  exit 1
fi

# ---- pre-flight ------------------------------------------------------------
banner "PRE-FLIGHT"
SPEEDUP_RT=$(assert_plan_rate "$PLAN" 1)
echo "plan            : $PLAN"
echo "derived speedup : $SPEEDUP_RT (true real time)"

PF_ID="preflight_$(date +%H%M%S)"
echo "running one short real-time trial to verify the rate..."
python3 scripts/run_concurrency_test.py 1 "$PLAN" 1 \
  --speedup "$SPEEDUP_RT" --max-t-sim 60 \
  --kafka-bootstrap "$KAFKA_BOOTSTRAP" --redis-host "$REDIS_HOST" --redis-port "$REDIS_PORT" \
  --plans-dir "$PLANS_DIR" --kafka-producer-extra "--max-inflight 64" \
  --out-dir "docs/results/preflight" --trial-timeout 300 2>&1 | tail -3

PROD=$(ls -t runs/*/producer.csv 2>/dev/null | head -1)
if [ -z "$PROD" ]; then
  echo "FATAL: pre-flight produced no producer.csv - the harness is not working."
  exit 1
fi

if ! python3 scripts/plan_speedup.py "$PLAN" --rate 1 --max-t-sim 60 --verify "$PROD"; then
  echo "FATAL: pre-flight replayed at the wrong rate. Refusing to run the campaigns."
  echo "Fix the speedup derivation before spending machine time."
  exit 1
fi
banner "PRE-FLIGHT PASSED"

# ---- 1. depth suite --------------------------------------------------------
banner "1/3 DEPTH SUITE"
bash cloud/campaigns/depth_suite.sh
echo "=== depth suite finished $(date -u +%FT%TZ) ==="

# ---- 2. M1 client A/B ------------------------------------------------------
banner "2/3 M1 CLIENT A/B"
bash cloud/campaigns/m1_client_ab.sh
echo "=== M1 finished $(date -u +%FT%TZ) ==="

# ---- 3. arrival-process extension -----------------------------------------
# Last because it is the external-validity extension rather than load-bearing evidence: if
# credit or machine time runs out, this is the arm to lose.
banner "3/3 ARRIVAL PROCESS"
bash cloud/campaigns/arrival_process.sh

echo "=== run_all complete $(date -u +%FT%TZ) ==="
