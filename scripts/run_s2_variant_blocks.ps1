# Powershell version of run_s2_variant_blocks.sh
# Usage: run_s2_variant_blocks.ps1 <PLAN> <REPS> <SPEEDUP> <MAX_T_SIM> <KAFKA_BOOTSTRAP> <REDIS_HOST> <REDIS_PORT> <PREFIX>

param(
    [Parameter(Mandatory=$true)][string]$PLAN,
    [Parameter(Mandatory=$true)][int]$REPS,
    [Parameter(Mandatory=$true)][int]$SPEEDUP,
    [Parameter(Mandatory=$true)][int]$MAX_T_SIM,
    [Parameter(Mandatory=$true)][string]$KAFKA_BOOTSTRAP,
    [Parameter(Mandatory=$true)][string]$REDIS_HOST,
    [Parameter(Mandatory=$true)][int]$REDIS_PORT,
    [Parameter(Mandatory=$true)][string]$PREFIX
)

$ErrorActionPreference = "Stop"

# Create meta snapshot directory
$META_SNAP_DIR = "docs\results\run_meta_$PREFIX"
New-Item -ItemType Directory -Force -Path $META_SNAP_DIR | Out-Null

# Run list file
$RUN_LIST = "runs\_${PREFIX}_latest_runs.txt"
"" | Out-File -FilePath $RUN_LIST -Encoding utf8

# Get timestamp function
function Get-Timestamp {
    return Get-Date -Format "yyyyMMdd_HHmmss"
}

for ($i = 1; $i -le $REPS; $i++) {
    Write-Host "=== [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Starting rep $i ==="
    
    # Kafka run
    $KID = "${PREFIX}_kafka_rep${i}_$(Get-Timestamp)"
    Write-Host "  [$i/$REPS] Kafka run: $KID"
    
    & "scripts\run_kafka_trial.ps1" $KID $PLAN $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP
    
    # Copy meta.json to snapshot dir
    $srcMeta = "runs\$KID\meta.json"
    $dstMeta = "$META_SNAP_DIR\${KID}_meta.json"
    if (Test-Path $srcMeta) {
        Copy-Item -Path $srcMeta -Destination $dstMeta -Force -ErrorAction SilentlyContinue
    }
    
    "runs\$KID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
    Write-Host "  [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Kafka rep $i DONE"
    
    Start-Sleep -Seconds 2

    # Redis run
    $RID = "${PREFIX}_redis_rep${i}_$(Get-Timestamp)"
    Write-Host "  [$i/$REPS] Redis run: $RID"
    
    # Use stream key = run id for uniqueness
    & "scripts\run_redis_trial.ps1" $RID $PLAN $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $RID
    
    # Copy meta.json to snapshot dir
    $srcMeta = "runs\$RID\meta.json"
    $dstMeta = "$META_SNAP_DIR\${RID}_meta.json"
    if (Test-Path $srcMeta) {
        Copy-Item -Path $srcMeta -Destination $dstMeta -Force -ErrorAction SilentlyContinue
    }
    
    "runs\$RID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
    Write-Host "  [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Redis rep $i DONE"
    
    Start-Sleep -Seconds 2
}

Write-Host "DONE. Run list: $RUN_LIST"
Write-Host "DONE. Meta snapshots in: $META_SNAP_DIR"
