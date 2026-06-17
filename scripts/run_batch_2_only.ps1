#!/usr/bin/env powershell
# Run Batch 2: 40 runs - Kafka Cluster (30) + Redis Cluster (10)

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
            $plan_csv = $plan_paths[$scenario]
            $topic = "sb-events-$run_id"
            Write-Host "[$($batch2_total+1)/$batch2_target] $run_id"
            
            # Use localhost with mapped ports for Kafka cluster
            $process = Start-Process -FilePath pwsh -ArgumentList @("-Command", "scripts\run_kafka_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -BOOTSTRAP 'localhost:9092,localhost:9093,localhost:9094' -TOPIC '$topic' -BROKER_COUNT 3") -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                "runs\$run_id" | Out-File -FilePath $BATCH2_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
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
            $plan_csv = $plan_paths[$scenario]
            $stream = "sb:events:$run_id"
            $group = "sb-group:$run_id"
            Write-Host "[$($batch2_total+1)/$batch2_target] $run_id"
            
            # Use localhost with mapped ports for Redis cluster
            $process = Start-Process -FilePath pwsh -ArgumentList "-Command scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan_csv' -SPEEDUP $SPEEDUP -MAX_T_SIM $MAX_T_SIM -RedisHost 'localhost' -PORT 7000 -STREAM '$stream' -GROUP '$group' -CLUSTER_MODE -NODE_COUNT 3" -NoNewWindow -PassThru -Wait
            
            if ($process.ExitCode -eq 0) {
                "runs\$run_id" | Out-File -FilePath $BATCH2_RUN_LIST -Append -Encoding utf8
                Write-Host "  [DONE]"
            } else {
                Write-Host "  [FAILED] exit code: $($process.ExitCode)"
            }
            $batch2_total++
        }
        if ($batch2_total -ge $batch2_target) { break }
    }
    if ($batch2_total -ge $batch2_target) { break }
}

Write-Host "`n=== BATCH 2 COMPLETE ==="
Write-Host "Total runs executed: $batch2_total/$batch2_target"

# Create summary
$SUMMARY = @{
    batch = 2
    total_runs = $batch2_total
    target = $batch2_target
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    run_list = $BATCH2_RUN_LIST
}
$SUMMARY | ConvertTo-Json -Depth 10 | Out-File -FilePath "docs\results\batch2_summary.json" -Encoding utf8
Write-Host "Summary saved to: docs\results\batch2_summary.json"
