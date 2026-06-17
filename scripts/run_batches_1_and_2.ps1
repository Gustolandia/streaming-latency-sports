#!/usr/bin/env powershell
# Execute Batch 1 (40 runs) and Batch 2 (40 runs) sequentially
# Reports only when both are fully complete

param(
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600
)

$ErrorActionPreference = "Continue"

# Plan CSV paths
$plan_paths = @{
    "s1" = "data\processed\replay_plans\s1\combined_plan.csv"
    "s2" = "data\processed\replay_plans\s2\combined_plan.csv"
    "s2full" = "data\processed\replay_plans\s2full\combined_plan.csv"
    "s2sf12" = "data\processed\replay_plans\s2sf12\combined_plan.csv"
    "s2sf12j2" = "data\processed\replay_plans\s2sf12j2\combined_plan.csv"
}

# ============================================================================
# HELPER FUNCTION: Run a single Kafka trial
# ============================================================================
function Run-KafkaTrial {
    param($run_id, $scenario, $N, $rep, $broker_count, $bootstrap)
    
    $plan_csv = $plan_paths[$scenario]
    $topic = "sb-events-$run_id"
    
    $process = Start-Process -FilePath pwsh -ArgumentList "-Command scripts\run_kafka_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -BOOTSTRAP '$bootstrap' -TOPIC '$topic' -BROKER_COUNT $broker_count" -NoNewWindow -PassThru -Wait
    return $process.ExitCode -eq 0
}

# ============================================================================
# HELPER FUNCTION: Run a single Redis trial
# ============================================================================
function Run-RedisTrial {
    param($run_id, $scenario, $N, $rep, $redis_host, $port, $cluster_mode, $node_count)
    
    $plan_csv = $plan_paths[$scenario]
    $stream = "sb:events:$run_id"
    $group = "sb-group:$run_id"
    
    $process = Start-Process -FilePath pwsh -ArgumentList "-Command scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost '$redis_host' -PORT $port -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE:$cluster_mode -NODE_COUNT $node_count" -NoNewWindow -PassThru -Wait
    return $process.ExitCode -eq 0
}

# ============================================================================
# BATCH 1: 40 runs - Kafka Single (30) + Redis Single (10)
# ============================================================================
$BATCH1_PREFIX = "batch1_20260615"
$BATCH1_RUN_LIST = "runs\_batch1_runs.txt"
"" | Out-File -FilePath $BATCH1_RUN_LIST -Encoding utf8

Write-Host "`n=== BATCH 1: Kafka Single (30) + Redis Single (10) ==="
$batch1_total = 0
$batch1_target = 40

# Kafka Single: All 5 scenarios × 3 concurrency × 2 replications = 30 runs
foreach ($scenario in @("s1", "s2", "s2full", "s2sf12", "s2sf12j2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch1_total -ge $batch1_target) { break }
            
            $run_id = "${BATCH1_PREFIX}_kafka_single_${scenario}_n${N}_rep${rep}"
            Write-Host "[Batch1: $($batch1_total+1)/$batch1_target] $run_id"
            
            $success = Run-KafkaTrial -run_id $run_id -scenario $scenario -N $N -rep $rep -broker_count 1 -bootstrap "localhost:19092"
            
            if ($success) {
                "runs\$run_id" | Out-File -FilePath $BATCH1_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED]"
            }
            $batch1_total++
        }
        if ($batch1_total -ge $batch1_target) { break }
    }
    if ($batch1_total -ge $batch1_target) { break }
}

# Redis Single: s1 (6) + s2 (4) = 10 runs to reach 40
foreach ($scenario in @("s1", "s2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch1_total -ge $batch1_target) { break }
            
            $run_id = "${BATCH1_PREFIX}_redis_single_${scenario}_n${N}_rep${rep}"
            Write-Host "[Batch1: $($batch1_total+1)/$batch1_target] $run_id"
            
            $success = Run-RedisTrial -run_id $run_id -scenario $scenario -N $N -rep $rep -redis_host "localhost" -port 16379 -cluster_mode $false -node_count 1
            
            if ($success) {
                "runs\$run_id" | Out-File -FilePath $BATCH1_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED]"
            }
            $batch1_total++
        }
        if ($batch1_total -ge $batch1_target) { break }
    }
    if ($batch1_total -ge $batch1_target) { break }
}

Write-Host "Batch 1 Complete: $batch1_total/$batch1_target runs`n"

# ============================================================================
# BATCH 2: 40 runs - Kafka Cluster (30) + Redis Cluster (10)
# ============================================================================
$BATCH2_PREFIX = "batch2_20260615"
$BATCH2_RUN_LIST = "runs\_batch2_runs.txt"
"" | Out-File -FilePath $BATCH2_RUN_LIST -Encoding utf8

Write-Host "=== BATCH 2: Kafka Cluster (30) + Redis Cluster (10) ==="
$batch2_total = 0
$batch2_target = 40

# Kafka Cluster: All 5 scenarios × 3 concurrency × 2 replications = 30 runs
foreach ($scenario in @("s1", "s2", "s2full", "s2sf12", "s2sf12j2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch2_total -ge $batch2_target) { break }
            
            $run_id = "${BATCH2_PREFIX}_kafka_cluster_${scenario}_n${N}_rep${rep}"
            Write-Host "[Batch2: $($batch2_total+1)/$batch2_target] $run_id"
            
            $success = Run-KafkaTrial -run_id $run_id -scenario $scenario -N $N -rep $rep -broker_count 3 -bootstrap "kafka1:29092,kafka2:29092,kafka3:29092"
            
            if ($success) {
                "runs\$run_id" | Out-File -FilePath $BATCH2_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED]"
            }
            $batch2_total++
        }
        if ($batch2_total -ge $batch2_target) { break }
    }
    if ($batch2_total -ge $batch2_target) { break }
}

# Redis Cluster: s1 (6) + s2 (4) = 10 runs to reach 40
foreach ($scenario in @("s1", "s2")) {
    foreach ($N in @(5, 10, 20)) {
        foreach ($rep in @(1, 2)) {
            if ($batch2_total -ge $batch2_target) { break }
            
            $run_id = "${BATCH2_PREFIX}_redis_cluster_${scenario}_n${N}_rep${rep}"
            Write-Host "[Batch2: $($batch2_total+1)/$batch2_target] $run_id"
            
            $success = Run-RedisTrial -run_id $run_id -scenario $scenario -N $N -rep $rep -redis_host "sbl_redis1" -port 7000 -cluster_mode $true -node_count 3
            
            if ($success) {
                "runs\$run_id" | Out-File -FilePath $BATCH2_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED]"
            }
            $batch2_total++
        }
        if ($batch2_total -ge $batch2_target) { break }
    }
    if ($batch2_total -ge $batch2_target) { break }
}

Write-Host "Batch 2 Complete: $batch2_total/$batch2_target runs`n"

# ============================================================================
# FINAL SUMMARY
# ============================================================================
Write-Host "`n=========================================="
Write-Host "= BATCHES 1 & 2 COMPLETE ="
Write-Host "=========================================="
Write-Host "Batch 1: $batch1_total runs saved to $BATCH1_RUN_LIST"
Write-Host "Batch 2: $batch2_total runs saved to $BATCH2_RUN_LIST"
Write-Host "Total: $($batch1_total + $batch2_total) runs"
Write-Host "=========================================="

# Create combined summary
$SUMMARY = @{
    batch1 = @{
        total = $batch1_total
        target = $batch1_target
        run_list = $BATCH1_RUN_LIST
    }
    batch2 = @{
        total = $batch2_total
        target = $batch2_target
        run_list = $BATCH2_RUN_LIST
    }
    overall = @{
        total = $batch1_total + $batch2_total
        target = $batch1_target + $batch2_target
    }
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
}
$SUMMARY | ConvertTo-Json -Depth 10 | Out-File -FilePath "docs\results\batches_1_2_summary.json" -Encoding utf8
Write-Host "Summary saved to: docs\results\batches_1_2_summary.json"
