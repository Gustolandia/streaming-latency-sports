# S5 Single Run with Resource Monitoring
# Runs a single trial while monitoring container resources

param(
    [string]$RUN_ID,
    [string]$PLAN_CSV,
    [string]$BACKEND = "kafka",
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$KAFKA_BOOTSTRAP = "localhost:9092",
    [string]$REDIS_HOST = "localhost",
    [int]$REDIS_PORT = 6379,
    [string]$CONFIG_NAME = "baseline",
    [int]$CORRECTIONS_EVERY_K = 50,
    [double]$CORRECTION_DELAY_S = 2.0
)

$ErrorActionPreference = "Stop"

# Output directory
$runDir = "runs\$RUN_ID"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

# Resource metrics file - use absolute path for background job
$resourceFile = (Resolve-Path $runDir).Path + "\resource_metrics.csv"
"timestamp,backend,kafka_cpu_pct,kafka_mem_mib,redis_cpu_pct,redis_mem_mib" | Out-File -FilePath $resourceFile -Encoding utf8

# Get container IDs
$kafkaContainer = docker ps --filter "name=broker" --format "{{.ID}}"
$redisContainer = docker ps --filter "name=redis" --format "{{.ID}}"

Write-Host "S5: $RUN_ID with resource monitoring" -ForegroundColor Cyan
Write-Host "Backend: $BACKEND, Config: $CONFIG_NAME" -ForegroundColor Cyan
Write-Host "Kafka container: $kafkaContainer" -ForegroundColor Cyan
Write-Host "Redis container: $redisContainer" -ForegroundColor Cyan

# Function to parse memory string to MiB
function ConvertTo-MiB {
    param($memStr)
    $memStr = $memStr.Trim()
    if ($memStr -match '(\d+\.?\d*)\s*GiB') {
        return [math]::Round([double]$matches[1] * 1024, 2)
    } elseif ($memStr -match '(\d+\.?\d*)\s*MiB') {
        return [math]::Round([double]$matches[1], 2)
    }
    return 0
}

# Function to get container stats
function Get-ContainerStats {
    param($containerId)
    if (-not $containerId) { return @{ cpu=0; mem_mib=0 } }
    try {
        $stats = docker stats --no-stream --format "{{.CPUPerc}},{{.MemUsage}}" $containerId
        if (-not $stats) { return @{ cpu=0; mem_mib=0 } }
        $cpu, $mem = $stats -split ','
        $cpu = $cpu.Trim().Replace('%', '')
        $cpu = [double]$cpu
        
        $mem_mib = 0
        # Extract the FIRST memory value (used), not the total
        # Format: "X.GiB / Y.GiB" or "X.MiB / Y.GiB"
        # Split by '/' and take the first part
        $memParts = $mem -split '/'
        $usedMem = $memParts[0].Trim()
        $mem_mib = ConvertTo-MiB $usedMem
        
        return @{ cpu=$cpu; mem_mib=$mem_mib }
    } catch {
        return @{ cpu=0; mem_mib=0 }
    }
}

# Function to get system CPU
function Get-SystemCpu {
    try {
        $cpuCounter = Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue
        if ($cpuCounter) {
            return [math]::Round($cpuCounter.CounterSamples.CookedValue, 2)
        }
        return 0
    } catch {
        return 0
    }
}

# Function to record metrics
function Record-Metrics {
    param($backend)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $kafkaStats = Get-ContainerStats $kafkaContainer
    $redisStats = Get-ContainerStats $redisContainer
    $systemCpu = Get-SystemCpu
    
    $line = "$timestamp,$backend,$($kafkaStats.cpu),$($kafkaStats.mem_mib),$($redisStats.cpu),$($redisStats.mem_mib),$systemCpu"
    $line | Out-File -FilePath $resourceFile -Append -Encoding utf8
}

# Start monitoring in background
# Calculate wall-clock duration: MAX_T_SIM / SPEEDUP + buffer
# For SPEEDUP=120, MAX_T_SIM=600: 600/120 = 5 seconds wall-clock
# Add buffer for startup/shutdown
$wallClockDuration = [math]::Ceiling($MAX_T_SIM / $SPEEDUP) + 15
$monitorJob = Start-Job -ScriptBlock {
    param($duration, $backend, $resourceFile, $kafkaId, $redisId)
    
    $endTime = (Get-Date).AddSeconds($duration)
    
    # Define functions inside job
    function ConvertTo-MiB {
        param($memStr)
        $memStr = $memStr.Trim()
        if ($memStr -match '(\d+\.?\d*)\s*GiB') {
            return [math]::Round([double]$matches[1] * 1024, 2)
        } elseif ($memStr -match '(\d+\.?\d*)\s*MiB') {
            return [math]::Round([double]$matches[1], 2)
        }
        return 0
    }
    
    function Parse-ContainerLine {
        param($line)
        $parts = $line -split ','
        if ($parts.Count -lt 2) { return @{ cpu=0; mem_mib=0 } }
        $cpu = $parts[0].Trim().Replace('%', '')
        $cpu = [double]$cpu
        $mem = $parts[1].Trim()
        $memParts = $mem -split '/'
        $usedMem = $memParts[0].Trim()
        $mem_mib = ConvertTo-MiB $usedMem
        return @{ cpu=$cpu; mem_mib=$mem_mib }
    }
    
    while ((Get-Date) -lt $endTime) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
        
        # Get stats for both containers in a single call for efficiency
        $allStats = docker stats --no-stream --format "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}" $kafkaId $redisId 2>$null
        
        $kafkaStats = @{ cpu=0; mem_mib=0 }
        $redisStats = @{ cpu=0; mem_mib=0 }
        
        if ($allStats) {
            $lines = $allStats -split '`n'
            foreach ($line in $lines) {
                $line = $line.Trim()
                if (-not $line) { continue }
                $name, $cpuStr, $memStr = $line -split '\|', 3
                $stats = Parse-ContainerLine "$cpuStr,$memStr"
                
                # Map container name to kafka or redis
                if ($name -eq $kafkaId -or $name -like "*broker*") {
                    $kafkaStats = $stats
                } elseif ($name -eq $redisId -or $name -like "*redis*") {
                    $redisStats = $stats
                }
            }
        }
        
        $line = "$timestamp,$backend,$($kafkaStats.cpu),$($kafkaStats.mem_mib),$($redisStats.cpu),$($redisStats.mem_mib)"
        $line | Out-File -FilePath $resourceFile -Append -Encoding utf8
        
        # Sleep for a short interval - docker stats takes ~1-2s, so effective rate is ~2s
        Start-Sleep -Milliseconds 500
    }
} -ArgumentList $wallClockDuration, $BACKEND, $resourceFile, $kafkaContainer, $redisContainer

Write-Host "Started resource monitoring job..." -ForegroundColor Gray

# Run the trial
if ($BACKEND -eq "kafka") {
    $TOPIC = "sb-events-$RUN_ID"
    $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_kafka_trial.ps1" $RUN_ID $PLAN_CSV $SPEEDUP $MAX_T_SIM $KAFKA_BOOTSTRAP $TOPIC -PRODUCER_EXTRA $extra
} else {
    $STREAM = "sb:events:$RUN_ID"
    $GROUP = "sb-group:$RUN_ID"
    $extra = "--s3-mode corrections --corrections-every-k $CORRECTIONS_EVERY_K --correction-delay-s $CORRECTION_DELAY_S"
    & "scripts\run_redis_trial.ps1" $RUN_ID $PLAN_CSV $SPEEDUP $MAX_T_SIM $REDIS_HOST $REDIS_PORT $STREAM $GROUP -PRODUCER_EXTRA $extra
}

# Stop monitoring
Start-Sleep -Seconds 2
Stop-Job $monitorJob -ErrorAction SilentlyContinue
Remove-Job $monitorJob -ErrorAction SilentlyContinue

Write-Host "Resource monitoring stopped." -ForegroundColor Gray

# Compute summary statistics from collected metrics
if (Test-Path $resourceFile) {
    $metricsData = Import-Csv $resourceFile
    
    if ($metricsData.Count -gt 0) {
        # Skip first few samples (warmup)
        $samples = $metricsData | Select-Object -Skip 5
        
        if ($samples.Count -gt 0) {
            $kafkaCpus = $samples | ForEach-Object { [double]$_.kafka_cpu_pct } | Where-Object { $_ -gt 0 }
            $kafkaMems = $samples | ForEach-Object { [double]$_.kafka_mem_mib } | Where-Object { $_ -gt 0 }
            $redisCpus = $samples | ForEach-Object { [double]$_.redis_cpu_pct } | Where-Object { $_ -gt 0 }
            $redisMems = $samples | ForEach-Object { [double]$_.redis_mem_mib } | Where-Object { $_ -gt 0 }
            
            $summary = @{
                run_id = $RUN_ID
                backend = $BACKEND
                config = $CONFIG_NAME
                speedup = $SPEEDUP
                kafka_avg_cpu = if ($kafkaCpus) { [math]::Round(($kafkaCpus | Measure-Object -Average).Average, 2) } else { 0 }
                kafka_peak_cpu = if ($kafkaCpus) { [math]::Round(($kafkaCpus | Sort-Object -Descending | Select-Object -First 1), 2) } else { 0 }
                kafka_avg_mem = if ($kafkaMems) { [math]::Round(($kafkaMems | Measure-Object -Average).Average, 2) } else { 0 }
                kafka_peak_mem = if ($kafkaMems) { [math]::Round(($kafkaMems | Sort-Object -Descending | Select-Object -First 1), 2) } else { 0 }
                redis_avg_cpu = if ($redisCpus) { [math]::Round(($redisCpus | Measure-Object -Average).Average, 2) } else { 0 }
                redis_peak_cpu = if ($redisCpus) { [math]::Round(($redisCpus | Sort-Object -Descending | Select-Object -First 1), 2) } else { 0 }
                redis_avg_mem = if ($redisMems) { [math]::Round(($redisMems | Measure-Object -Average).Average, 2) } else { 0 }
                redis_peak_mem = if ($redisMems) { [math]::Round(($redisMems | Sort-Object -Descending | Select-Object -First 1), 2) } else { 0 }
                sample_count = $samples.Count
            }
            
            # Save summary
            $summary | ConvertTo-Json | Out-File -FilePath ((Resolve-Path $runDir).Path + "\resource_summary.json") -Encoding utf8
            
            Write-Host "`nS5 Resource Summary for $RUN_ID ($BACKEND):" -ForegroundColor Green
            Write-Host "  Kafka: avg=$($summary.kafka_avg_cpu)%, peak=$($summary.kafka_peak_cpu)% | mem=$($summary.kafka_avg_mem)MiB (peak=$($summary.kafka_peak_mem)MiB)" -ForegroundColor Green
            Write-Host "  Redis: avg=$($summary.redis_avg_cpu)%, peak=$($summary.redis_peak_cpu)% | mem=$($summary.redis_avg_mem)MiB (peak=$($summary.redis_peak_mem)MiB)" -ForegroundColor Green
            Write-Host "  Samples: $($summary.sample_count)" -ForegroundColor Green
        }
    }
}

Write-Host "S5 run complete: $RUN_ID" -ForegroundColor Green
