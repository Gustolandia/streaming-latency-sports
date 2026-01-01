#!/usr/bin/env bash
set -euo pipefail

mkdir -p data/processed/results docs/results

# 1) Validate official list exists
test -f runs/_paper_s2_official_runs.txt || { echo "Missing runs/_paper_s2_official_runs.txt"; exit 2; }

# 2) Validate every official run has meta.json + tti_summary.json
python - <<'PY'
from pathlib import Path
lst = [x.strip().replace("runs/","") for x in Path("runs/_paper_s2_official_runs.txt").read_text().splitlines() if x.strip()]
missing_meta = [rid for rid in lst if not (Path("runs")/rid/"meta.json").exists()]
missing_tti  = [rid for rid in lst if not (Path("runs")/rid/"tti_summary.json").exists()]
print(f"Official runs: {len(lst)}")
print(f"Missing meta.json: {len(missing_meta)}")
print(f"Missing tti_summary.json: {len(missing_tti)}")
if missing_meta:
    print("Runs missing meta.json:\n" + "\n".join(missing_meta))
    raise SystemExit(2)
if missing_tti:
    print("Runs missing tti_summary.json:\n" + "\n".join(missing_tti))
    raise SystemExit(3)
print("OK: official run artifacts present.")
PY

# 3) Build official results CSV
python scripts/make_results_table.py \
  --runs $(paste -sd' ' runs/_paper_s2_official_runs.txt) \
  --out data/processed/results/paper_s2_official.csv

# 4) Build summaries
python - <<'PY'
import pandas as pd
from pathlib import Path

df = pd.read_csv("data/processed/results/paper_s2_official.csv")
df["scenario"] = df["run"].astype(str).str.extract(r'^(s2[^_]+)')[0]

group_cols = [c for c in ["scenario","backend"] if c in df.columns]
exclude = set(["run","backend","scenario"])
num_cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

def iqr(s): return s.quantile(0.75) - s.quantile(0.25)

by = df.groupby(group_cols, dropna=False)[num_cols].agg(["median", iqr]).reset_index()
by.columns = ["_".join([x for x in col if x]).rstrip("_") for col in by.columns.to_flat_index()]
Path("docs/results").mkdir(parents=True, exist_ok=True)
by.to_csv("docs/results/paper_s2_official_by_scenario_summary.csv", index=False)

overall = df.groupby(["backend"], dropna=False)[num_cols].agg(["median", iqr]).reset_index()
overall.columns = ["_".join([x for x in col if x]).rstrip("_") for col in overall.columns.to_flat_index()]
overall.to_csv("docs/results/paper_s2_official_overall_summary.csv", index=False)

print("Wrote official summary CSVs.")
PY

# 5) Build meta matrix
python - <<'PY'
import json
import pandas as pd
from pathlib import Path

runs = [r.strip().replace("runs/","") for r in Path("runs/_paper_s2_official_runs.txt").read_text().splitlines() if r.strip()]
rows = []
for rid in runs:
    meta = json.loads((Path("runs")/rid/"meta.json").read_text())
    rows.append({
        "run": rid,
        "scenario": rid.split("_",1)[0] if rid.startswith("s2") else None,
        "backend": meta.get("backend"),
        "plan_csv": meta.get("plan_csv"),
        "speedup": meta.get("speedup"),
        "max_t_sim": meta.get("max_t_sim"),
        "bootstrap": meta.get("bootstrap"),
        "git_head": meta.get("git",{}).get("head"),
        "git_dirty": meta.get("git",{}).get("dirty"),
        "kafka_producer_opts": meta.get("env",{}).get("KAFKA_PRODUCER_OPTS"),
        "kafka_consumer_opts": meta.get("env",{}).get("KAFKA_CONSUMER_OPTS"),
        "redis_opts": meta.get("env",{}).get("REDIS_OPTS") or meta.get("env",{}).get("REDIS_STREAM_OPTS"),
    })

df = pd.DataFrame(rows).sort_values(["scenario","backend","run"])
Path("docs/results").mkdir(parents=True, exist_ok=True)
df.to_csv("docs/results/paper_s2_meta_matrix.csv", index=False)
print("Wrote docs/results/paper_s2_meta_matrix.csv")
PY

# 6) Environment snapshot
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
} > docs/results/paper_env_snapshot.txt

echo "DONE: built paper S2 outputs + meta matrix + env snapshot."
