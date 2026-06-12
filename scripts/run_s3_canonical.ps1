# Powershell script for S3 canonical runs
# Generates official S3 runs for paper

param(
    [int]$REPS = 3,
    [string]$SCENARIO = "s2sf12",
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

# Plan file
$plan = "data/processed/replay_plans/$SCENARIO/combined_plan.csv"

# Output run list
$RUN_LIST = "runs\_paper_s3_official_runs.txt"

# Clear/create run list
"" | Out-File -FilePath $RUN_LIST -Encoding utf8 -Force

Write-Host "=== S3 Canonical Runs: $SCENARIO scenario, $REPS reps ===" -ForegroundColor Cyan

for ($i = 1; $i -le $REPS; $i++) {
    Write-Host "[$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Starting S3 canonical runs"
    
    # Kafka run
    $KID = "s3_${SCENARIO}_kafka_rep${i}_20260612"
    Write-Host "  Kafka: $KID"
    
    $kafkaExtra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_kafka_trial.ps1" $KID $plan $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP -PRODUCER_EXTRA $kafkaExtra
    
    "runs\$KID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
    Write-Host "  Kafka rep $i DONE"
    
    Start-Sleep -Seconds 3
    
    # Redis run
    $RID = "s3_${SCENARIO}_redis_rep${i}_20260612"
    Write-Host "  Redis: $RID"
    
    $redisExtra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_redis_trial.ps1" $RID $plan $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $RID -PRODUCER_EXTRA $redisExtra
    
    "runs\$RID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
    Write-Host "  Redis rep $i DONE"
    
    Start-Sleep -Seconds 3
}

Write-Host "=== S3 CANONICAL RUNS COMPLETE ===" -ForegroundColor Green
Write-Host "Run list: $RUN_LIST"
Get-Content $RUN_LIST
