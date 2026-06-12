# Powershell script for S4 parameter sensitivity analysis
# Tests impact of speedup, corrections_every_k, and correction_delay_s
# on S3 metrics (correction propagation latency, state staleness)

param(
    [int]$REPS = 1,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# S4 Parameter Matrix
# 8 configurations x 2 scenarios x 2 backends = 32 runs
$scenarios = @(
    @{ prefix="s2sf12"; plan="data/processed/replay_plans/s2sf12/combined_plan.csv" },
    @{ prefix="s2sf12j2"; plan="data/processed/replay_plans/s2sf12j2/combined_plan.csv" }
)

# Parameter configurations to test
$configs = @(
    @{ name="baseline"; speedup=120; corrections_every_k=50; correction_delay_s=2.0 },
    @{ name="low_speedup"; speedup=60; corrections_every_k=50; correction_delay_s=2.0 },
    @{ name="high_speedup"; speedup=240; corrections_every_k=50; correction_delay_s=2.0 },
    @{ name="high_frequency"; speedup=120; corrections_every_k=10; correction_delay_s=2.0 },
    @{ name="low_frequency"; speedup=120; corrections_every_k=100; correction_delay_s=2.0 },
    @{ name="long_delay"; speedup=120; corrections_every_k=50; correction_delay_s=5.0 },
    @{ name="short_delay"; speedup=120; corrections_every_k=50; correction_delay_s=0.5 },
    @{ name="fast_corrections"; speedup=120; corrections_every_k=10; correction_delay_s=0.5 }
)

# Output run list
$RUN_LIST = "runs\_paper_s4_parameter_sweep.txt"
"" | Out-File -FilePath $RUN_LIST -Encoding utf8 -Force

$totalRuns = 0
$startTime = Get-Date

Write-Host "=== S4 Parameter Sensitivity Analysis ===" -ForegroundColor Cyan
Write-Host "Testing: speedup, corrections_every_k, correction_delay_s" -ForegroundColor Cyan
$scenarioNames = $scenarios | ForEach-Object { $_.prefix }
Write-Host "Scenarios: $($scenarios.Count) ($($scenarioNames -join ', '))" -ForegroundColor Cyan
Write-Host "Configurations: $($configs.Count)" -ForegroundColor Cyan
Write-Host "Backends: kafka, redis" -ForegroundColor Cyan
Write-Host "Expected: $($scenarios.Count * $configs.Count * 2 * $REPS) total runs" -ForegroundColor Cyan
Write-Host "" 

foreach ($scenario in $scenarios) {
    Write-Host "=== Scenario: $($scenario.prefix) ===" -ForegroundColor Cyan
    
    foreach ($config in $configs) {
        foreach ($backend in @("kafka", "redis")) {
            for ($i = 1; $i -le $REPS; $i++) {
                $timestamp = Get-Date -Format 'yyyyMMdd'
                $runId = "s4_$($scenario.prefix)_$($config.name)_$($backend)_rep$($i)_$timestamp"
                $totalRuns++
                
                Write-Host "  [$totalRuns/$($scenarios.Count * $configs.Count * 2 * $REPS)] $(Get-Date -Format 'HH:mm:ss') Starting $runId (speedup=$($config.speedup), every_k=$($config.corrections_every_k), delay=$($config.correction_delay_s)s)"
                
                if ($backend -eq "kafka") {
                    $streamKey = "sb-events-$runId"
                    $groupKey = "sb-consumer-$runId"
                    $extra = "--s3-mode corrections --corrections-every-k $($config.corrections_every_k) --correction-delay-s $($config.correction_delay_s)"
                    & "scripts\run_kafka_trial.ps1" $runId $scenario.plan $config.speedup $MAX_T_SIM $KAFKA_BOOTSTRAP $streamKey -PRODUCER_EXTRA $extra
                } else {
                    $streamKey = "sb:events:$runId"
                    $groupKey = "sb-group:$runId"
                    $extra = "--s3-mode corrections --corrections-every-k $($config.corrections_every_k) --correction-delay-s $($config.correction_delay_s)"
                    & "scripts\run_redis_trial.ps1" $runId $scenario.plan $config.speedup $MAX_T_SIM $REDIS_HOST $REDIS_PORT $streamKey $groupKey -PRODUCER_EXTRA $extra
                }
                
                "runs\$runId" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
                Write-Host "  [$totalRuns/$($scenarios.Count * $configs.Count * 2 * $REPS)] $(Get-Date -Format 'HH:mm:ss') $backend $($config.name) rep $i DONE"
                
                Start-Sleep -Seconds 2
            }
        }
    }
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "`n=== S4 PARAMETER SWEEP COMPLETE ===" -ForegroundColor Green
Write-Host "Total runs: $totalRuns" -ForegroundColor Green
Write-Host "Duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
Write-Host "Run list: $RUN_LIST" -ForegroundColor Green
Write-Host "`nRun IDs:" -ForegroundColor Cyan
Get-Content $RUN_LIST
