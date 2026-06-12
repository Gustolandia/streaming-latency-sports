# Powershell script to run a single S4 parameter configuration
# Usage: .\run_s4_single.ps1 <scenario> <config_name> <backend> <rep> [speedup] [corrections_every_k] [correction_delay_s]

param(
    [Parameter(Mandatory=$true)][string]$SCENARIO,
    [Parameter(Mandatory=$true)][string]$CONFIG_NAME,
    [Parameter(Mandatory=$true)][string]$BACKEND,
    [Parameter(Mandatory=$true)][int]$REP,
    [int]$SPEEDUP = 120,
    [int]$CORRECTIONS_EVERY_K = 50,
    [double]$CORRECTION_DELAY_S = 2.0,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# Map scenario to plan file
$scenarioPlans = @{
    "s1" = "data/processed/replay_plans/s1/combined_plan.csv"
    "s2" = "data/processed/replay_plans/s2/combined_plan.csv"
    "s2full" = "data/processed/replay_plans/s2full/combined_plan.csv"
    "s2sf12" = "data/processed/replay_plans/s2sf12/combined_plan.csv"
    "s2sf12j2" = "data/processed/replay_plans/s2sf12j2/combined_plan.csv"
}

if (-not $scenarioPlans.ContainsKey($SCENARIO)) {
    Write-Error "Unknown scenario: $SCENARIO. Valid: $($scenarioPlans.Keys -join ', ')"
    exit 1
}

$PLAN_CSV = $scenarioPlans[$SCENARIO]
$timestamp = Get-Date -Format 'yyyyMMdd'
$runId = "s4_${SCENARIO}_${CONFIG_NAME}_${BACKEND}_rep${REP}_$timestamp"

Write-Host "Running S4: $runId" -ForegroundColor Cyan
Write-Host "  Scenario: $SCENARIO" -ForegroundColor Cyan
Write-Host "  Config: $CONFIG_NAME" -ForegroundColor Cyan
Write-Host "  Backend: $BACKEND" -ForegroundColor Cyan
Write-Host "  Rep: $REP" -ForegroundColor Cyan
Write-Host "  Speedup: $SPEEDUP" -ForegroundColor Cyan
Write-Host "  Corrections every K: $CORRECTIONS_EVERY_K" -ForegroundColor Cyan
Write-Host "  Correction delay: $CORRECTION_DELAY_S s" -ForegroundColor Cyan

# Create run directory
$runDir = "runs\$runId"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

if ($BACKEND -eq "kafka") {
    $streamKey = "sb-events-$runId"
    $groupKey = "sb-consumer-$runId"
    $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_kafka_trial.ps1" $runId $PLAN_CSV $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP $streamKey -PRODUCER_EXTRA $extra
} else {
    $streamKey = "sb:events:$runId"
    $groupKey = "sb-group:$runId"
    $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_redis_trial.ps1" $runId $PLAN_CSV $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $streamKey $groupKey -PRODUCER_EXTRA $extra
}

Write-Host "Run $runId completed successfully" -ForegroundColor Green
