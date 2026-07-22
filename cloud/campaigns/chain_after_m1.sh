#!/usr/bin/env bash
# Wait for the M1 client A/B to finish, then run the depth suite.
#
# The driver saturates during the concurrency phases, to the point where sshd cannot complete a
# handshake, so the two campaigns cannot be supervised interactively. This chains them on the
# machine itself: launch with nohup and it will run both to completion unattended.
#
# Usage:  nohup bash cloud/campaigns/chain_after_m1.sh > chain.log 2>&1 &
set -uo pipefail
cd "${REPO_ROOT:-$HOME/sbl}"

echo "=== chain start $(date -u +%FT%TZ) ==="

# Wait for M1 rather than assuming it is done. The two campaigns must not overlap: the depth
# suite deliberately saturates the CPU, which would contaminate M1's measurements.
if pgrep -f run_m1 >/dev/null; then
  echo "M1 still running; waiting for it to finish"
  while pgrep -f run_m1 >/dev/null; do sleep 60; done
fi
echo "M1 complete at $(date -u +%FT%TZ)"

if ! grep -q "M1_COMPLETE" m1.log 2>/dev/null; then
  echo "WARNING: m1.log has no completion marker - M1 may have died early."
  echo "Continuing to the depth suite anyway; M1's partial output is still on disk."
fi

echo "=== depth suite start $(date -u +%FT%TZ) ==="
bash cloud/campaigns/depth_suite.sh
echo "=== chain complete $(date -u +%FT%TZ) ==="
