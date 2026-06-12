#!/usr/bin/env bash
set -euo pipefail

RUNLIST="runs/_paper_s3_official_runs.txt"
OUT_MAIN="data/processed/results/paper_s3_official.csv"

# 1) Validate official run list exists
if [ ! -f "$RUNLIST" ]; then
  echo "ERROR: Missing $RUNLIST"
  exit 1
fi

# 2) Read run list
mapfile -t RUN_IDS < "$RUNLIST"

if [ ${#RUN_IDS[@]} -eq 0 ]; then
  echo "ERROR: No runs in $RUNLIST"
  exit 1
fi

echo "Official runs: ${#RUN_IDS[@]}"

# 3) Validate required per-run artifacts
missing=0
for rid in "${RUN_IDS[@]}"; do
  for f in "meta.json" "tti_summary.json" "consumer_events.csv"; do
    p="runs/$rid/$f"
    if [ ! -f "$p" ] || [ ! -s "$p" ]; then
      echo "MISSING_OR_EMPTY: $p"
      missing=1
    fi
  done
done

if [ $missing -ne 0 ]; then
  exit 1
fi
echo "OK: official run artifacts present."

# 4) Compute S3 metrics
python scripts/compute_s3_metrics.py

# 5) Build summary CSVs analogous to S2
# TODO: write summary CSVs once metrics are defined
# docs/results/paper_s3_official_overall_summary.csv, etc.

# 6) Env snapshot (freeze-time artifact; do not overwrite on rebuild)
ENV_OUT="docs/results/paper_s3_env_snapshot.txt"
mkdir -p docs/results
if [ -f "$ENV_OUT" ] && [ "${RECAPTURE_ENV:-0}" != "1" ]; then
  echo "SKIP: $ENV_OUT already exists (freeze artifact). Set RECAPTURE_ENV=1 to overwrite."
else
  {
    echo "=== GIT ==="
    git rev-parse HEAD
    git status --porcelain
    echo
    echo "=== PYTHON ==="
    python --version
    pip --version
    echo
    echo "=== PIP FREEZE ==="
    pip freeze
    echo
    echo "=== DOCKER ==="
    docker --version
    docker compose version
    echo
    echo "=== OS/WSL ==="
    uname -a
    (lsb_release -a 2>/dev/null || true)
  } > "$ENV_OUT"
fi

echo "DONE: built paper S3 outputs."
