# Powershell script for complete S3 canonical runs
# Generates 50 official S3 runs (5 scenarios × 5 reps × 2 backends)

param(
    [int]$REPS = 5,
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# S3 config - same for both backends
$CORRECTIONS_EVERY_K = 50
$CORRECTION_DELAY_S = 2.0

# All 5 scenarios
$scenarios = @(
    @{ prefix="s1"; plan="data/processed/replay_plans/s1/combined_plan.csv" },
    @{ prefix="s2"; plan="data/processed/replay_plans/s2/combined_plan.csv" },
    @{ prefix="s2full"; plan="data/processed/replay_plans/s2full/combined_plan.csv" },
    @{ prefix="s2sf12"; plan="data/processed/replay_plans/s2sf12/combined_plan.csv" },
    @{ prefix="s2sf12j2"; plan="data/processed/replay_plans/s2sf12j2/combined_plan.csv" }
)

# Output run list
$RUN_LIST = "runs\_paper_s3_official_runs.txt"
"" | Out-File -FilePath $RUN_LIST -Encoding utf8 -Force

$totalRuns = 0
$startTime = Get-Date

Write-Host "=== S3 Canonical Runs: All 5 scenarios, $REPS reps each ===" -ForegroundColor Cyan
Write-Host "Config: every $CORRECTIONS_EVERY_K events, $CORRECTION_DELAY_S s delay" -ForegroundColor Cyan
Write-Host "Expected: $($scenarios.Count * $REPS * 2) total runs" -ForegroundColor Cyan

foreach ($scenario in $scenarios) {
    Write-Host "`n=== Scenario: $($scenario.prefix) ===" -ForegroundColor Cyan
    
    for ($i = 1; $i -le $REPS; $i++) {
        $backendOrder = if ($i % 2 -eq 1) { @("kafka", "redis") } else { @("redis", "kafka") }
        
        foreach ($backend in $backendOrder) {
            $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
            $runId = "s3_${scenario.prefix}_${backend}_rep${i}_$timestamp"
            $totalRuns++
            
            Write-Host "  [$totalRuns/$($scenarios.Count * $REPS * 2)] $(Get-Date -Format 'HH:mm:ss') Starting $runId"
            
            if ($backend -eq "kafka") {
                $streamKey = "sb-events-$runId"
                $groupKey = "sb-consumer-$runId"
                $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
                & "scripts\run_kafka_trial.ps1" $runId $scenario.plan $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP $streamKey -PRODUCER_EXTRA $extra
            } else {
                $streamKey = "sb:events:$runId"
                $groupKey = "sb-group:$runId"
                $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
                & "scripts\run_redis_trial.ps1" $runId $scenario.plan $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $streamKey $groupKey -PRODUCER_EXTRA $extra
            }
            
            "runs\$runId" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
            Write-Host "  [$totalRuns/$($scenarios.Count * $REPS * 2)] $(Get-Date -Format 'HH:mm:ss') $backend rep $i DONE"
            
            Start-Sleep -Seconds 2
        }
    }
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "`n=== ALL S3 CANONICAL RUNS COMPLETE ===" -ForegroundColor Green
Write-Host "Total runs: $totalRuns" -ForegroundColor Green
Write-Host "Duration: $($duration.ToString('hh\)mm\)ss'))" -ForegroundColor Green
Write-Host "Run list: $RUN_LIST" -ForegroundColor Green
Write-Host "`nRun IDs:" -ForegroundColor Cyan
Get-Content $RUN_LIST
