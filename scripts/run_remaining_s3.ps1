# Powershell script to run remaining 46 S3 canonical runs
# Skips the 4 already completed runs

param(
    [int]$REPS = 5,
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# S3 config
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

# Already completed runs (4 runs)
$completedRuns = @(
    "s3_s2sf12_kafka_rep1_20260612",
    "s3_s2sf12_redis_rep1_20260612",
    "s3_s2_kafka_rep1_20260612",
    "s3_s2_redis_rep1_20260612"
)

# Load existing run list
$RUN_LIST = "runs\_paper_s3_official_runs.txt"
if (Test-Path $RUN_LIST) {
    $existingRuns = Get-Content $RUN_LIST | ForEach-Object { $_ -replace '^runs[\\/]', '' }
} else {
    $existingRuns = @()
}

$totalRuns = $existingRuns.Count
$targetRuns = $scenarios.Count * $REPS * 2  # 50 total

Write-Host "=== S3 Canonical Runs: Continuing from $totalRuns/$targetRuns ===" -ForegroundColor Cyan

foreach ($scenario in $scenarios) {
    foreach ($i in 1..$REPS) {
        foreach ($backend in @("kafka", "redis")) {
            $runId = "s3_${scenario.prefix}_${backend}_rep${i}_20260612"
            
            # Skip if already completed
            if ($runId -in $completedRuns -or $runId -in $existingRuns) {
                Write-Host "  SKIP: $runId (already exists)" -ForegroundColor Yellow
                continue
            }
            
            $totalRuns++
            Write-Host "  [$totalRuns/$targetRuns] $(Get-Date -Format 'HH:mm:ss') Starting $runId"
            
            if ($backend -eq "kafka") {
                $streamKey = "sb-events-$runId"
                $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
                & "scripts\run_kafka_trial.ps1" $runId $scenario.plan $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP $streamKey -PRODUCER_EXTRA $extra
            } else {
                $streamKey = "sb:events:$runId"
                $groupKey = "sb-group:$runId"
                $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
                & "scripts\run_redis_trial.ps1" $runId $scenario.plan $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $streamKey $groupKey -PRODUCER_EXTRA $extra
            }
            
            "runs\$runId" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
            Write-Host "  [$totalRuns/$targetRuns] $(Get-Date -Format 'HH:mm:ss') $runId DONE"
            
            Start-Sleep -Seconds 2
        }
    }
}

Write-Host "`n=== ALL S3 CANONICAL RUNS COMPLETE ===" -ForegroundColor Green
Write-Host "Total runs: $(Get-Content $RUN_LIST | Measure-Object -Line).Lines" -ForegroundColor Green
