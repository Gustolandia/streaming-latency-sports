#!/usr/bin/env powershell
# run_concurrency_test.ps1
# Orchestrates N concurrent feeds for Kafka vs Redis comparison
# Usage: .\run_concurrency_test.ps1 <CONCURRENCY_LEVEL> <PLAN_CSV_PATH> <REPS> <SPEEDUP> <MAX_T_SIM> <KAFKA_BOOTSTRAP> <REDIS_HOST> <REDIS_PORT>

param(
    [Parameter(Mandatory=$true)][int]$CONCURRENCY_LEVEL,
    [Parameter(Mandatory=$true)][string]$PLAN_CSV,
    [Parameter(Mandatory=$true)][int]$REPS,
    [Parameter(Mandatory=$true)][int]$SPEEDUP,
    [Parameter(Mandatory=$true)][int]$MAX_T_SIM,
    [Parameter(Mandatory=$true)][string]$KAFKA_BOOTSTRAP,
    [Parameter(Mandatory=$true)][string]$REDIS_HOST,
    [Parameter(Mandatory=$true)][int]$REDIS_PORT
)

$ErrorActionPreference = "Stop"

# Validate concurrency level
if ($CONCURRENCY_LEVEL -notin @(1, 5, 10, 20)) {
    Write-Error "CONCURRENCY_LEVEL must be one of: 1, 5, 10, 20"
}

# Validate plan CSV exists
if (-not (Test-Path $PLAN_CSV)) {
    Write-Error "Plan CSV file not found: $PLAN_CSV"
}

# Timestamp for this test batch
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$PREFIX = "concurrency_n${CONCURRENCY_LEVEL}_${TIMESTAMP}"

Write-Host "=== Starting Concurrency Test: N=$CONCURRENCY_LEVEL ==="
Write-Host "Prefix: $PREFIX"
Write-Host "Plan CSV: $PLAN_CSV"
Write-Host "Reps: $REPS"

# Create meta snapshot directory
$META_SNAP_DIR = "docs\results\concurrency_$PREFIX"
New-Item -ItemType Directory -Force -Path $META_SNAP_DIR | Out-Null

# Run list file
$RUN_LIST = "runs\_concurrency_${PREFIX}_runs.txt"
"" | Out-File -FilePath $RUN_LIST -Encoding utf8

# For each repetition
for ($rep = 1; $rep -le $REPS; $rep++) {
    Write-Host "`n=== Rep $rep/$REPS ==="
    
    # For each feed index (1 to N)
    $jobs = @()
    
    for ($feed = 1; $feed -le $CONCURRENCY_LEVEL; $feed++) {
        $KID = "${PREFIX}_kafka_feed${feed}_rep${rep}"
        $RID = "${PREFIX}_redis_feed${feed}_rep${rep}"
        
        # Unique topic/stream per feed
        $KAFKA_TOPIC = "sb-events-n${CONCURRENCY_LEVEL}-feed${feed}-rep${rep}"
        $REDIS_STREAM = "sb:events:n${CONCURRENCY_LEVEL}:feed${feed}:rep${rep}"
        $REDIS_GROUP = "sb-group-n${CONCURRENCY_LEVEL}-feed${feed}-rep${rep}"
        
        Write-Host "  Starting Kafka feed $feed : $KID (topic: $KAFKA_TOPIC)"
        $kafkaJob = Start-Job -ScriptBlock {
            param($KID, $PLAN_CSV, $SPEEDUP, $MAX_T_SIM, $KAFKA_BOOTSTRAP, $KAFKA_TOPIC)
            Set-Location -Path "$using:PWD"
            & "scripts\run_kafka_trial.ps1" -RUN_ID $KID -PLAN_CSV $PLAN_CSV -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -BOOTSTRAP $KAFKA_BOOTSTRAP -TOPIC $KAFKA_TOPIC
        } -ArgumentList $KID, $PLAN_CSV, $SPEEDUP, $MAX_T_SIM, $KAFKA_BOOTSTRAP, $KAFKA_TOPIC
        $jobs += $kafkaJob
        
        Write-Host "  Starting Redis feed $feed : $RID (stream: $REDIS_STREAM)"
        $redisJob = Start-Job -ScriptBlock {
            param($RID, $PLAN_CSV, $SPEEDUP, $MAX_T_SIM, $REDIS_HOST, $REDIS_PORT, $REDIS_STREAM, $REDIS_GROUP)
            Set-Location -Path "$using:PWD"
            & "scripts\run_redis_trial.ps1" -RUN_ID $RID -PLAN_CSV $PLAN_CSV -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost $REDIS_HOST -PORT $REDIS_PORT -STREAM $REDIS_STREAM -GROUP $REDIS_GROUP
        } -ArgumentList $RID, $PLAN_CSV, $SPEEDUP, $MAX_T_SIM, $REDIS_HOST, $REDIS_PORT, $REDIS_STREAM, $REDIS_GROUP
        $jobs += $redisJob
    }
    
    # Wait for all jobs in this rep to complete
    Write-Host "  Waiting for all $($CONCURRENCY_LEVEL * 2) jobs to complete..."
    
    try {
        $allJobs = $jobs | Wait-Job -Timeout 7200  # 2 hour timeout
        
        # Check for errors
        $errors = @()
        foreach ($job in $allJobs) {
            if ($job.JobStateInfo.State -ne "Completed") {
                Write-Host "  Job $($job.Id) failed with state: $($job.JobStateInfo.State)"
                $errors += $job
            }
        }
        
        if ($errors.Count -gt 0) {
            Write-Error "Errors occurred in $($errors.Count) jobs"
        }
        
        # Collect run IDs for this rep
        foreach ($job in $allJobs) {
            if ($job.JobStateInfo.State -eq "Completed") {
                $runId = $job.Arguments[0]  # First argument is run-id
                "runs\$runId" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
                
                # Copy meta.json to snapshot dir
                $srcMeta = "runs\$runId\meta.json"
                $dstMeta = "$META_SNAP_DIR\${runId}_meta.json"
                if (Test-Path $srcMeta) {
                    Copy-Item -Path $srcMeta -Destination $dstMeta -Force -ErrorAction SilentlyContinue
                }
            }
        }
    } catch {
        Write-Error "Error waiting for jobs: $_"
    } finally {
        # Clean up jobs
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
    }
    
    Write-Host "  Rep $rep DONE`n"
}

Write-Host "`n=== Concurrency Test Complete: N=$CONCURRENCY_LEVEL ==="
Write-Host "Run list: $RUN_LIST"

if (Test-Path $RUN_LIST) {
    $total_runs = (Get-Content $RUN_LIST | Measure-Object -Line).Lines
    Write-Host "Total runs: $total_runs"
} else {
    Write-Host "Run list file not created - no runs may have completed"
}

# Create summary file
$SUMMARY = @{
    concurrency_level = $CONCURRENCY_LEVEL
    plan_csv = $PLAN_CSV
    reps = $REPS
    speedup = $SPEEDUP
    max_t_sim = $MAX_T_SIM
    timestamp = $TIMESTAMP
    prefix = $PREFIX
    run_list_file = $RUN_LIST
    total_runs = if (Test-Path $RUN_LIST) { (Get-Content $RUN_LIST | Measure-Object -Line).Lines } else { 0 }
    kafka_bootstrap = $KAFKA_BOOTSTRAP
    redis_host = $REDIS_HOST
    redis_port = $REDIS_PORT
}

$SUMMARY | ConvertTo-Json -Depth 10 | Out-File -FilePath "docs\results\${PREFIX}_summary.json" -Encoding utf8

Write-Host "Summary saved to: docs\results\${PREFIX}_summary.json"
