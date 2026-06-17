#!/usr/bin/env powershell
# Run missing Redis trials for Batches 1 and 2

param(
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600
)

$ErrorActionPreference = "Continue"

$plan_paths = @{
    "s1" = "data\processed\replay_plans\s1\combined_plan.csv"
    "s2" = "data\processed\replay_plans\s2\combined_plan.csv"
}

# ============================================================================
# RUN REDIS SINGLE - 10 runs for Batch 1
# ============================================================================
Write-Host "=== Batch 1: Redis Single (10 runs) ==="
$count = 0
foreach ($scenario in @("s1", "s2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($count -ge 10) { break }
            
            $run_id = "batch1_20260615_redis_single_${scenario}_n${N}_rep${rep}"
            $plan_csv = $plan_paths[$scenario]
            $stream = "sb:events:$run_id"
            $group = "sb-group:$run_id"
            
            Write-Host "[$($count+1)/10] $run_id"
            
            $process = Start-Process -FilePath pwsh -ArgumentList "-Command scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 16379 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE:`$false -NODE_COUNT 1" -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
            }
            $count++
        }
        if ($count -ge 10) { break }
    }
    if ($count -ge 10) { break }
}

Write-Host "Batch 1 Redis: $count/10 runs complete`n"

# ============================================================================
# RUN REDIS CLUSTER - 10 runs for Batch 2
# ============================================================================
Write-Host "=== Batch 2: Redis Cluster (10 runs) ==="
$count = 0
foreach ($scenario in @("s1", "s2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($count -ge 10) { break }
            
            $run_id = "batch2_20260615_redis_cluster_${scenario}_n${N}_rep${rep}"
            $plan_csv = $plan_paths[$scenario]
            $stream = "sb:events:$run_id"
            $group = "sb-group:$run_id"
            
            Write-Host "[$($count+1)/10] $run_id"
            
            $process = Start-Process -FilePath pwsh -ArgumentList "-Command scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 7000 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE -NODE_COUNT 3" -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
            }
            $count++
        }
        if ($count -ge 10) { break }
    }
    if ($count -ge 10) { break }
}

Write-Host "Batch 2 Redis: $count/10 runs complete`n"
Write-Host "All missing Redis runs completed!"
