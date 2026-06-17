# S5 Resource Analysis Sweep
# Measures computational resources (CPU, memory) during streaming runs
# Uses run_s5_single_with_monitoring.ps1 for each configuration

param(
    [int]$REPS = 1,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379
)

$ErrorActionPreference = "Stop"

# S5 configurations - test baseline plus edge cases
# Edge cases: high speedup, high frequency, low frequency, long delay, fast corrections
$configs = @(
    @{ name="baseline"; speedup=120; corrections_every_k=50; correction_delay_s=2.0 },
    @{ name="high_speedup"; speedup=240; corrections_every_k=50; correction_delay_s=2.0 },
    @{ name="high_frequency"; speedup=120; corrections_every_k=10; correction_delay_s=2.0 },
    @{ name="low_frequency"; speedup=120; corrections_every_k=100; correction_delay_s=2.0 },
    @{ name="long_delay"; speedup=120; corrections_every_k=50; correction_delay_s=5.0 },
    @{ name="fast_corrections"; speedup=120; corrections_every_k=10; correction_delay_s=0.5 }
)

# Use both S4 scenarios for comprehensive resource analysis
# 6 configs x 2 backends x 2 scenarios = 24 runs, ~10 min each = 4 hours total
$scenarios = @(
    @{ prefix="s2sf12"; plan="data/processed/replay_plans/s2sf12/combined_plan.csv" },
    @{ prefix="s2sf12j2"; plan="data/processed/replay_plans/s2sf12j2/combined_plan.csv" }
)

# Output files
$RUN_LIST = "runs\_paper_s5_resource_analysis.txt"
$RESOURCE_METRICS = "data/processed/results/paper_s5_resource_metrics.csv"
$RESOURCE_SUMMARY = "data/processed/results/paper_s5_resource_summary.csv"

# Header for resource metrics CSV
$header = "run_id,backend,scenario,config,speedup,peak_kafka_cpu_pct,avg_kafka_cpu_pct,peak_kafka_mem_mib,avg_kafka_mem_mib,peak_redis_cpu_pct,avg_redis_cpu_pct,peak_redis_mem_mib,avg_redis_mem_mib"
$header | Out-File -FilePath $RESOURCE_METRICS -Encoding utf8 -Force

"" | Out-File -FilePath $RUN_LIST -Encoding utf8 -Force

$totalRuns = 0
$startTime = Get-Date

Write-Host "=== S5 Resource Analysis Sweep ===" -ForegroundColor Cyan
Write-Host "Measuring CPU and memory usage for each configuration" -ForegroundColor Cyan
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
                $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
                $runId = "s5_$($scenario.prefix)_$($config.name)_$backend" + "_rep${i}_$timestamp"
                $totalRuns++
                
                Write-Host "  [$totalRuns/$($scenarios.Count * $configs.Count * 2 * $REPS)] $(Get-Date -Format 'HH:mm:ss') Starting $runId (speedup=$($config.speedup))" -ForegroundColor Yellow
                
                # Run single trial with monitoring
                & "scripts\run_s5_single_with_monitoring.ps1" $runId $scenario.plan $backend $config.speedup $MAX_T_SIM $KAFKA_BOOTSTRAP $REDIS_HOST $REDIS_PORT $config.name $config.corrections_every_k $config.correction_delay_s
                
                # Record run in list
                "runs\$runId" | Out-File -FilePath $RUN_LIST -Append -Encoding utf8
                
                Write-Host "  [$totalRuns/$($scenarios.Count * $configs.Count * 2 * $REPS)] $(Get-Date -Format 'HH:mm:ss') $backend $($config.name) rep $i DONE" -ForegroundColor Green
                Start-Sleep -Seconds 2
            }
        }
    }
}

# Now aggregate resource metrics from individual run directories
Write-Host "`nAggregating resource metrics from all runs..." -ForegroundColor Cyan

$runListContent = Get-Content $RUN_LIST | Where-Object { $_ -ne "" }
$aggregatedMetrics = @()

foreach ($runPath in $runListContent) {
    $runId = $runPath.Replace("runs\", "")
    $resourceFile = "runs\$runId\resource_summary.json"
    
    if (Test-Path $resourceFile) {
        try {
            $resourceData = Get-Content $resourceFile | ConvertFrom-Json
            
            # Parse run_id: s5_<scenario>_<config>_<backend>_rep<N>_<date>_<time>
            $parts = $runId -split "_"
            $scenario = $parts[1]
            # Find 'rep' to locate backend
            $repIndex = 0
            for ($i = 0; $i -lt $parts.Count; $i++) {
                if ($parts[$i] -like "rep*") {
                    $repIndex = $i
                    break
                }
            }
            $backend = $parts[$repIndex - 1]
            $configName = $parts[2..($repIndex - 2)] -join "_"
            
            # Find speedup from config
            $config = $configs | Where-Object { $_.name -eq $configName } | Select-Object -First 1
            $speedup = if ($config) { $config.speedup } else { 0 }
            
            # Build metric object
            $metric = [PSCustomObject]@{
                run_id = $runId
                backend = $backend
                scenario = $scenario
                config = $configName
                speedup = $speedup
                peak_kafka_cpu_pct = $resourceData.kafka_peak_cpu
                avg_kafka_cpu_pct = $resourceData.kafka_avg_cpu
                peak_kafka_mem_mib = $resourceData.kafka_peak_mem
                avg_kafka_mem_mib = $resourceData.kafka_avg_mem
                peak_redis_cpu_pct = $resourceData.redis_peak_cpu
                avg_redis_cpu_pct = $resourceData.redis_avg_cpu
                peak_redis_mem_mib = $resourceData.redis_peak_mem
                avg_redis_mem_mib = $resourceData.redis_avg_mem
            }
            $aggregatedMetrics += $metric
            
            Write-Host "  Aggregated: $runId - Kafka(avg=$($resourceData.kafka_avg_cpu)%, peak=$($resourceData.kafka_peak_cpu)% | mem=$($resourceData.kafka_avg_mem)MiB), Redis(avg=$($resourceData.redis_avg_cpu)%, peak=$($resourceData.redis_peak_cpu)% | mem=$($resourceData.redis_avg_mem)MiB), Samples=$($resourceData.sample_count)" -ForegroundColor Green
        } catch {
            Write-Host "  Warning: Could not process $runId - $($_.Exception.Message)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Warning: No resource_summary.json found for $runId" -ForegroundColor Yellow
    }
}

# Save aggregated metrics
if ($aggregatedMetrics.Count -gt 0) {
    $aggregatedMetrics | ConvertTo-Csv -NoTypeInformation | Out-File -FilePath $RESOURCE_METRICS -Encoding utf8 -Force
    Write-Host "`nSaved aggregated metrics: $RESOURCE_METRICS" -ForegroundColor Green
}

$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host "`n=== S5 RESOURCE ANALYSIS COMPLETE ===" -ForegroundColor Green
Write-Host "Total runs: $($runListContent.Count)" -ForegroundColor Green
Write-Host "Duration: $($duration.ToString('hh\:mm\:ss'))" -ForegroundColor Green
Write-Host "Run list: $RUN_LIST" -ForegroundColor Green
Write-Host "Resource metrics: $RESOURCE_METRICS" -ForegroundColor Green
