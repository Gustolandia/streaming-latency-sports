#!/usr/bin/env bash
set -euo pipefail

RUNLIST="runs/_paper_s3_official_runs.txt"
OUT_MAIN="data/processed/results/paper_s3_official.csv"

if [ ! -s "" ]; then
  echo "Missing "
  exit 1
fi

echo "Official runs: "

# Validate required per-run artifacts
missing=0
while IFS= read -r rid; do
  for f in "meta.json" "tti_summary.json" "consumer_events.csv"; do
    p="runs//"
    if [ ! -s "" ]; then
      echo "MISSING_OR_EMPTY: "
      missing=1
    fi
  done
done < ""
if [ "" -ne 0 ]; then
  exit 1
fi
echo "OK: official run artifacts present."

python scripts/compute_s3_metrics.py

# TODO: write summary CSVs analogous to S2 once metrics are defined
# docs/results/paper_s3_official_overall_summary.csv, etc.

# Env snapshot (freeze-time artifact; do not overwrite on rebuild)
ENV_OUT="docs/results/paper_s3_env_snapshot.txt"
mkdir -p docs/results
if [ -s "" ] && [ "0" != "1" ]; then
  echo "SKIP:  already exists (freeze artifact). Set RECAPTURE_ENV=1 to overwrite."
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
} > ""
fi

echo "DONE: built paper S3 outputs."
