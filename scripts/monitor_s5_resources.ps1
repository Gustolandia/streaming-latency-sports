# S5 Resource Monitoring Script
# Measures CPU, memory, and other system metrics during streaming runs

param(
    [string]$RunId = "test",
    [int]$IntervalSeconds = 1,
    [int]$DurationMinutes = 5
)

$ErrorActionPreference = "Stop"

# Output directory
$outputDir = "runs\$RunId"
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

$metricsFile = "$outputDir\resource_metrics.csv"
"Timestamp,Backend,CPUPerc,MemUsageMiB,MemPerc,NetIO,DiskIO,ProcessCount" | Out-File -FilePath $metricsFile -Encoding utf8

Write-Host "=== S5 Resource Monitor: $RunId ===" -ForegroundColor Cyan
Write-Host "Monitoring for $DurationMinutes minutes at $IntervalSeconds second intervals" -ForegroundColor Cyan

$endTime = (Get-Date).AddMinutes($DurationMinutes)

# Get container IDs
$kafkaContainer = docker ps --filter "name=broker" --format "{{.ID}}" 2>$null
$redisContainer = docker ps --filter "name=*-redis-1" --format "{{.ID}}" 2>$null

Write-Host "Kafka container: $kafkaContainer" -ForegroundColor Cyan
Write-Host "Redis container: $redisContainer" -ForegroundColor Cyan

while ((Get-Date) -lt $endTime) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    
    # Monitor Kafka
    if ($kafkaContainer) {
        $kafkaStats = docker stats --no-stream --format "{{.CPUPerc}},{{.MemUsage}}" $kafkaContainer 2>$null
        if ($kafkaStats) {
            $kafkaCpu, $kafkaMem = $kafkaStats -split ','
            $kafkaMemMiB = [math]::Round([double]($kafkaMem -replace 'MiB', '') -replace 'GiB', '' * 1024), 2)
            $kafkaLine = "$timestamp,Kafka,$($kafkaCpu.Replace('%', '')),$kafkaMemMiB,,"
            $kafkaLine | Out-File -FilePath $metricsFile -Append -Encoding utf8
        }
    }
    
    # Monitor Redis
    if ($redisContainer) {
        $redisStats = docker stats --no-stream --format "{{.CPUPerc}},{{.MemUsage}}" $redisContainer 2>$null
        if ($redisStats) {
            $redisCpu, $redisMem = $redisStats -split ','
            $redisMemMiB = [math]::Round([double]($redisMem -replace 'MiB', '') -replace 'GiB', '' * 1024), 2)
            $redisLine = "$timestamp,Redis,$($redisCpu.Replace('%', '')),$redisMemMiB,,"
            $redisLine | Out-File -FilePath $metricsFile -Append -Encoding utf8
        }
    }
    
    # Also monitor overall system
    $systemCpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
    $systemMem = (Get-Counter '\Memory\Available MBytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
    $totalMem = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1MB
    $memPerc = [math]::Round((($totalMem - $systemMem) / $totalMem) * 100, 2)
    
    $systemLine = "$timestamp,System,$([math]::Round($systemCpu, 2)),$([math]::Round($systemMem, 2)),$memPerc"
    $systemLine | Out-File -FilePath $metricsFile -Append -Encoding utf8
    
    Start-Sleep -Seconds $IntervalSeconds
}

Write-Host "Monitoring complete. Metrics saved to: $metricsFile" -ForegroundColor Green
