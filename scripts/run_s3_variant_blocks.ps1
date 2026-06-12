# Powershell script for S3 correction scenarios
# Runs all scenarios with S3 mode (correction injection)

param(
    [int]$REPS = 5,
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# S3 config from configs/s3_injections.yaml
$CORRECTIONS_EVERY_K = 50
$CORRECTION_DELAY_S = 2.0

# Scenarios to run (same as S2)
$scenarios = @(
    @{ prefix="s1"; plan="data/processed/replay_plans/s1/combined_plan.csv" },
    @{ prefix="s2"; plan="data/processed/replay_plans/s2/combined_plan.csv" },
    @{ prefix="s2full"; plan="data/processed/replay_plans/s2full/combined_plan.csv" },
    @{ prefix="s2sf12"; plan="data/processed/replay_plans/s2sf12/combined_plan.csv" },
    @{ prefix="s2sf12j2"; plan="data/processed/replay_plans/s2sf12j2/combined_plan.csv" }
)

foreach ($scenario in $scenarios) {
    Write-Host "=== Scenario: $($scenario.prefix) ===" -ForegroundColor Cyan
    
    # Create meta snapshot directory
    $META_SNAP_DIR = "docs\results\run_meta_s3_$($scenario.prefix)"
    New-Item -ItemType Directory -Force -Path $META_SNAP_DIR | Out-Null
    
    # Run list file
    $RUN_LIST = "runs\_s3_${scenario.prefix}_latest_runs.txt"
    "" | Out-File -FilePath $RUN_LIST -Encoding utf8

    for ($i = 1; $i -le $REPS; $i++) {
        Write-Host "  [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Starting rep $i"
        
        # Kafka run with S3 corrections
        $KID = "s3_${scenario.prefix}_kafka_rep${i}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Write-Host "    Kafka: $KID"
        
        $kafkaExtra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
        & "scripts\run_kafka_trial.ps1" $KID $scenario.plan $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP -PRODUCER_EXTRA $kafkaExtra
        
        # Copy meta.json to snapshot dir
        $srcMeta = "runs\$KID\meta.json"
        $dstMeta = "$META_SNAP_DIR\${KID}_meta.json"
        if (Test-Path $srcMeta) {
            Copy-Item -Path $srcMeta -Destination $dstMeta -Force -ErrorAction SilentlyContinue
        }
        
        "runs\$KID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
        Write-Host "    [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Kafka rep $i DONE"
        
        Start-Sleep -Seconds 2

        # Redis run with S3 corrections
        $RID = "s3_${scenario.prefix}_redis_rep${i}_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
        Write-Host "    Redis: $RID"
        
        # Use stream key = run id for uniqueness
        $redisExtra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
        & "scripts\run_redis_trial.ps1" $RID $scenario.plan $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $RID -PRODUCER_EXTRA $redisExtra
        
        # Copy meta.json to snapshot dir
        $srcMeta = "runs\$RID\meta.json"
        $dstMeta = "$META_SNAP_DIR\${RID}_meta.json"
        if (Test-Path $srcMeta) {
            Copy-Item -Path $srcMeta -Destination $dstMeta -Force -ErrorAction SilentlyContinue
        }
        
        "runs\$RID" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
        Write-Host "    [$i/$REPS] $(Get-Date -Format 'HH:mm:ss') Redis rep $i DONE"
        
        Start-Sleep -Seconds 2
    }
    
    Write-Host "  DONE: Scenario $($scenario.prefix) - $REPS reps" -ForegroundColor Green
}

Write-Host "=== ALL S3 SCENARIOS COMPLETE ===" -ForegroundColor Cyan
