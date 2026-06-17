#!/usr/bin/env powershell
# Run Batch 3: Redis Single/Cluster for s2full, s2sf12, s2sf12j2 (40 runs)
# 2 backends (Redis single + Redis cluster) × 3 scenarios × 3 concurrency × 2 replications = 36 runs
# Plus 4 missing Redis single runs for s2_n20_rep1 and s2_n20_rep2
# Total: 40 runs

param(
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600
)

$ErrorActionPreference = "Continue"

$plan_paths = @{
    "s1" = "data\processed\replay_plans\s1\combined_plan.csv"
    "s2" = "data\processed\replay_plans\s2\combined_plan.csv"
    "s2full" = "data\processed\replay_plans\s2full\combined_plan.csv"
    "s2sf12" = "data\processed\replay_plans\s2sf12\combined_plan.csv"
    "s2sf12j2" = "data\processed\replay_plans\s2sf12j2\combined_plan.csv"
}

$BATCH3_PREFIX = "batch3_20260616"
$BATCH3_RUN_LIST = "runs\_batch3_runs.txt"
"" | Out-File -FilePath $BATCH3_RUN_LIST -Encoding utf8

Write-Host "=== BATCH 3: Redis remaining runs (40) ==="
$batch3_total = 0
$batch3_target = 40

# Function to check if run has tti_summary.json
function Is-RunComplete($runDir) {
    return (Test-Path (Join-Path $runDir "tti_summary.json"))
}

# Part 1: Missing Redis Single runs (s2_n20_rep1, s2_n20_rep2) - 2 runs
Write-Host "`n--- Part 1: Missing Redis Single runs ---"
$missing_single = @(
    @{scenario="s2"; N=20; rep=1},
    @{scenario="s2"; N=20; rep=2}
)

foreach ($run in $missing_single) {
    if ($batch3_total -ge $batch3_target) { break }
    
    $run_id = "${BATCH3_PREFIX}_redis_single_${run.scenario}_n${run.N}_rep${run.rep}"
    $plan_csv = $plan_paths[$run.scenario]
    $stream = "sb:events:$run_id"
    $group = "sb-group:$run_id"
    $runDir = "runs\$run_id"
    
    # Skip if already complete
    if (Test-Path $runDir -PathType Container) {
        if (Is-RunComplete $runDir) {
            Write-Host "[$($batch3_total+1)/$batch3_target] $run_id [SKIPPED - already complete]"
            $batch3_total++
            "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
            continue
        }
    }
    
    Write-Host "[$($batch3_total+1)/$batch3_target] $run_id"
    
    $process = Start-Process -FilePath pwsh -ArgumentList @("-Command", "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 16379 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE:$false -NODE_COUNT 1") -NoNewWindow -PassThru -Wait
    
    if ($process.ExitCode -eq 0) {
        "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
        Write-Host "  [DONE]"
    } else {
        Write-Host "  [FAILED] exit code: $($process.ExitCode)"
    }
    $batch3_total++
}

# Part 2: Redis Single for s2full, s2sf12, s2sf12j2 - 3 scenarios × 3 concurrency × 2 replications = 18 runs
Write-Host "`n--- Part 2: Redis Single for s2full, s2sf12, s2sf12j2 ---"
foreach ($scenario in @("s2full", "s2sf12", "s2sf12j2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch3_total -ge $batch3_target) { break }
            
            $run_id = "${BATCH3_PREFIX}_redis_single_${scenario}_n${N}_rep${rep}"
            $plan_csv = $plan_paths[$scenario]
            $stream = "sb:events:$run_id"
            $group = "sb-group:$run_id"
            $runDir = "runs\$run_id"
            
            # Skip if already complete
            if (Test-Path $runDir -PathType Container) {
                if (Is-RunComplete $runDir) {
                    Write-Host "[$($batch3_total+1)/$batch3_target] $run_id [SKIPPED - already complete]"
                    $batch3_total++
                    "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
                    continue
                }
            }
            
            Write-Host "[$($batch3_total+1)/$batch3_target] $run_id"
            
            $process = Start-Process -FilePath pwsh -ArgumentList @("-Command", "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 16379 -STREAM '$stream' -GROUP '$group' -NODE_COUNT 1") -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
            }
            $batch3_total++
        }
        if ($batch3_total -ge $batch3_target) { break }
    }
    if ($batch3_total -ge $batch3_target) { break }
}

# Part 3: Redis Cluster for s2full, s2sf12, s2sf12j2 - 3 scenarios × 3 concurrency × 2 replications = 18 runs
Write-Host "`n--- Part 3: Redis Cluster for s2full, s2sf12, s2sf12j2 ---"
foreach ($scenario in @("s2full", "s2sf12", "s2sf12j2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch3_total -ge $batch3_target) { break }
            
            $run_id = "${BATCH3_PREFIX}_redis_cluster_${scenario}_n${N}_rep${rep}"
            $plan_csv = $plan_paths[$scenario]
            $stream = "sb:events:$run_id"
            $group = "sb-group:$run_id"
            $runDir = "runs\$run_id"
            
            # Skip if already complete
            if (Test-Path $runDir -PathType Container) {
                if (Is-RunComplete $runDir) {
                    Write-Host "[$($batch3_total+1)/$batch3_target] $run_id [SKIPPED - already complete]"
                    $batch3_total++
                    "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
                    continue
                }
            }
            
            Write-Host "[$($batch3_total+1)/$batch3_target] $run_id"
            
            $process = Start-Process -FilePath pwsh -ArgumentList @("-Command", "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 7000 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE -NODE_COUNT 3") -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
            }
            $batch3_total++
        }
        if ($batch3_total -ge $batch3_target) { break }
    }
    if ($batch3_total -ge $batch3_target) { break }
}

# Part 4: Missing Redis Cluster runs (s2_n20_rep1, s2_n20_rep2) - 2 runs
Write-Host "`n--- Part 4: Missing Redis Cluster runs ---"
$missing_cluster = @(
    @{scenario="s2"; N=20; rep=1},
    @{scenario="s2"; N=20; rep=2}
)

foreach ($run in $missing_cluster) {
    if ($batch3_total -ge $batch3_target) { break }
    
    $run_id = "${BATCH3_PREFIX}_redis_cluster_${run.scenario}_n${run.N}_rep${run.rep}"
    $plan_csv = $plan_paths[$run.scenario]
    $stream = "sb:events:$run_id"
    $group = "sb-group:$run_id"
    $runDir = "runs\$run_id"
    
    # Skip if already complete
    if (Test-Path $runDir -PathType Container) {
        if (Is-RunComplete $runDir) {
            Write-Host "[$($batch3_total+1)/$batch3_target] $run_id [SKIPPED - already complete]"
            $batch3_total++
            "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
            continue
        }
    }
    
    Write-Host "[$($batch3_total+1)/$batch3_target] $run_id"
    
    $process = Start-Process -FilePath pwsh -ArgumentList @("-Command", "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 7000 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE -NODE_COUNT 3") -NoNewWindow -PassThru -Wait
    
    if ($process.ExitCode -eq 0) {
        "runs\$run_id" | Out-File -FilePath $BATCH3_RUN_LIST -Append -Encoding utf8
        Write-Host "  [DONE]"
    } else {
        Write-Host "  [FAILED] exit code: $($process.ExitCode)"
    }
    $batch3_total++
}

Write-Host "`n=== BATCH 3 COMPLETE ==="
Write-Host "Total runs executed: $batch3_total/$batch3_target"

# Create summary
$SUMMARY = @{
    batch = 3
    total_runs = $batch3_total
    target = $batch3_target
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    run_list = $BATCH3_RUN_LIST
}
$SUMMARY | ConvertTo-Json -Depth 10 | Out-File -FilePath "docs\results\batch3_summary.json" -Encoding utf8
Write-Host "Summary saved to: docs\results\batch3_summary.json"
