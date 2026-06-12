# Powershell version of build_paper_s2_outputs.sh

$ErrorActionPreference = "Stop"

# 1) Validate official list exists
if (-not (Test-Path "runs/_paper_s2_official_runs.txt")) {
    Write-Error "Missing runs/_paper_s2_official_runs.txt"
    exit 2
}

# 2) Validate every official run has meta.json + tti_summary.json
$lst = Get-Content "runs/_paper_s2_official_runs.txt" | Where-Object { $_ -ne "" }
$missing_meta = @()
$missing_tti = @()
foreach ($line in $lst) {
    $rid = $line.Trim().Replace("runs/", "").Replace("runs\", "")
    if (-not (Test-Path "runs\$rid\meta.json")) {
        $missing_meta += $rid
    }
    if (-not (Test-Path "runs\$rid\tti_summary.json")) {
        $missing_tti += $rid
    }
}
Write-Host "Official runs: $($lst.Count)"
Write-Host "Missing meta.json: $($missing_meta.Count)"
Write-Host "Missing tti_summary.json: $($missing_tti.Count)"
if ($missing_meta.Count -gt 0) {
    Write-Host "Runs missing meta.json:`n$($missing_meta -join "`n")"
    exit 2
}
if ($missing_tti.Count -gt 0) {
    Write-Host "Runs missing tti_summary.json:`n$($missing_tti -join "`n")"
    exit 3
}
Write-Host "OK: official run artifacts present."

# Create output directories
New-Item -ItemType Directory -Force -Path "data/processed/results" | Out-Null
New-Item -ItemType Directory -Force -Path "docs/results" | Out-Null

# 3) Build official results CSV
$runsRaw = Get-Content "runs/_paper_s2_official_runs.txt" -Raw
# Remove BOM if present
if ($runsRaw -match "\xFE\xFF") {
    $runsRaw = $runsRaw.Substring(1)
}
$runs = $runsRaw -split "`n" | Where-Object { $_ -ne "" } | ForEach-Object { $_.Trim().Replace("runs/", "").Replace("runs\\", "") }
$runArgs = @("--runs") + $runs + @("--out", "data/processed/results/paper_s2_official.csv")
python scripts/make_results_table.py $runArgs

# 4) Build summaries - use a temp Python script
$pythonScript1 = @'
import pandas as pd
from pathlib import Path

df = pd.read_csv("data/processed/results/paper_s2_official.csv")
df["scenario"] = df["run"].astype(str).str.extract(r"^(s2[^_]+)")[0]

group_cols = [c for c in ["scenario","backend"] if c in df.columns]
exclude = set(["run","backend","scenario"])
num_cols = [c for c in df.columns if c not in exclude and pd.api.types.is_numeric_dtype(df[c])]

def iqr(s): 
    return s.quantile(0.75) - s.quantile(0.25)

by = df.groupby(group_cols, dropna=False)[num_cols].agg(["median", iqr]).reset_index()
by.columns = ["_".join([x for x in col if x]).rstrip("_") for col in by.columns.to_flat_index()]
Path("docs/results").mkdir(parents=True, exist_ok=True)
by.to_csv("docs/results/paper_s2_official_by_scenario_summary.csv", index=False)

overall = df.groupby(["backend"], dropna=False)[num_cols].agg(["median", iqr]).reset_index()
overall.columns = ["_".join([x for x in col if x]).rstrip("_") for col in overall.columns.to_flat_index()]
overall.to_csv("docs/results/paper_s2_official_overall_summary.csv", index=False)

print("Wrote official summary CSVs.")
'@
$tempPy1 = "_temp_s2_summaries.py"
$pythonScript1 | Out-File -FilePath $tempPy1 -Encoding utf8
python $tempPy1
Remove-Item $tempPy1 -Force -ErrorAction SilentlyContinue

# 5) Build meta matrix - use a temp Python script
$pythonScript2 = @'
import json
import pandas as pd
from pathlib import Path

# Read runs file with proper encoding (handle UTF-16 LE with BOM)
with open("runs/_paper_s2_official_runs.txt", "r", encoding="utf-16") as f:
    lines = f.read().splitlines()

runs = []
for line in lines:
    r = line.strip()
    if r:
        # Remove runs/ or runs\ prefix
        r_clean = r.replace("runs/", "").replace("runs\\", "")
        # Replace any remaining backslashes with forward slashes
        r_clean = r_clean.replace("\\", "/")
        runs.append(r_clean)

rows = []
for rid in runs:
    meta_path = Path("runs") / rid / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
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
'@
$tempPy2 = "_temp_s2_meta.py"
$pythonScript2 | Out-File -FilePath $tempPy2 -Encoding utf8 -Force
python $tempPy2
Remove-Item $tempPy2 -Force -ErrorAction SilentlyContinue

# 6) Environment snapshot (freeze-time artifact; do not overwrite on rebuild)
$ENV_OUT = "docs/results/paper_env_snapshot.txt"
if ((Test-Path $ENV_OUT) -and (Get-Item $ENV_OUT).Length -gt 0 -and ($env:RECAPTURE_ENV -ne "1")) {
    Write-Host "SKIP: $ENV_OUT already exists (freeze artifact). Set RECAPTURE_ENV=1 to overwrite."
} else {
    $envContent = "=== GIT ===`n"
    $envContent += git rev-parse HEAD 2>`$null
    $envContent += "`n`n"
    $envContent += git status --porcelain 2>`$null
    $envContent += "`n`n=== PYTHON ===`n"
    $envContent += python --version 2>`$null
    $envContent += "`n`n"
    $envContent += pip --version 2>`$null
    $envContent += "`n`n=== PIP FREEZE ===`n"
    $envContent += pip freeze 2>`$null
    $envContent += "`n`n=== DOCKER ===`n"
    $envContent += docker --version 2>`$null
    $envContent += "`n`n"
    $envContent += docker compose version 2>`$null
    $envContent += "`n`n=== OS ===`n"
    $envContent += systeminfo | Select-String -Pattern "OS Name" 2>`$null
    $envContent += "`n"
    
    $envContent | Out-File -FilePath $ENV_OUT -Encoding utf8
}

Write-Host "DONE: built paper S2 outputs + meta matrix + env snapshot."
