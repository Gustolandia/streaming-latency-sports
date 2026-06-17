# Powershell version of run_redis_trial.sh
# Usage: run_redis_trial.ps1 <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] [HOST] [PORT] [STREAM] [GROUP]

param(
    [Parameter(Mandatory=$true)][string]$RUN_ID,
    [Parameter(Mandatory=$true)][string]$PLAN_CSV,
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$RedisHost = "localhost",
    [int]$PORT = 6379,
    [string]$STREAM = "sb:events:$RUN_ID",
    [string]$GROUP = "sb-group:$RUN_ID",
    [switch]$CLUSTER_MODE = $false,
    [int]$NODE_COUNT = 1,
    [string]$PRODUCER_EXTRA = "",
    [int]$IDLE_SECONDS = 30
)

$ErrorActionPreference = "Stop"

# Create run directory
$runDir = "runs\$RUN_ID"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# Write per-run provenance (reviewer-proof)
$meta = @{
    run_id = $RUN_ID
    backend = "redis"
    plan_csv = $PLAN_CSV
    speedup = $SPEEDUP
    max_t_sim = $MAX_T_SIM
    redis = @{
        host = $RedisHost
        port = $PORT
        stream = $STREAM
        group = $GROUP
    }
    env = @{
        REDIS_PRODUCER_OPTS = $env:REDIS_PRODUCER_OPTS
        REDIS_CONSUMER_OPTS = $env:REDIS_CONSUMER_OPTS
    }
    git = @{
        head = git rev-parse HEAD 2>$null
        status_short = git status --porcelain 2>$null
    }
    code_sha256 = @{}
}

# Compute SHA256 for code files
function Get-FileSHA256($path) {
    if (Test-Path $path) {
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $stream = [System.IO.File]::OpenRead($path)
        $hash = $sha.ComputeHash($stream)
        $stream.Close()
        return [System.BitConverter]::ToString($hash).ToLower() -replace '-', ''
    }
    return $null
}

$meta.code_sha256.Add("scripts/run_redis_trial.ps1", (Get-FileSHA256 "scripts\run_redis_trial.ps1"))
$meta.code_sha256.Add("scripts/redis_producer.py", (Get-FileSHA256 "scripts\redis_producer.py"))
$meta.code_sha256.Add("scripts/redis_consumer.py", (Get-FileSHA256 "scripts\redis_consumer.py"))
$meta.code_sha256.Add("scripts/compute_tti.py", (Get-FileSHA256 "scripts\compute_tti.py"))

# Save meta.json
$metaPath = "runs\$RUN_ID\meta.json"
# Sort keys and write JSON
$json = $meta | ConvertTo-Json -Depth 10
$json | Out-File -FilePath $metaPath -Encoding utf8
Write-Host "Wrote meta: $metaPath"

# Clean slate for this run
Write-Host "[0/4] $(Get-Date -Format 'HH:mm:ss') cleaning Redis stream: $STREAM"
# Use docker exec to run redis-cli since redis-cli is not available on Windows
if ($CLUSTER_MODE -or $NODE_COUNT -eq 3) {
    # Cluster mode: use redis1 container and cluster port
    # try/catch so best-effort cleanup stderr doesn't trip ErrorActionPreference=Stop
    try { docker exec sbl_redis1 redis-cli --port 7000 DEL $STREAM 2>$null } catch {}
} else {
    # Single node: use standard container
    try { docker exec streaming-latency-sports-redis-1 redis-cli DEL $STREAM 2>$null } catch {}
}
Write-Host "  [0/4] Stream cleaned"

# [1/4] starting consumer...
Write-Host "[1/4] $(Get-Date -Format 'HH:mm:ss') starting consumer..."
$consumerLog = "runs\$RUN_ID\consumer.log"

# Build consumer command with output redirection
$consumerCmd = "python scripts\redis_consumer.py --run-id $RUN_ID --out runs\$RUN_ID\consumer.csv --host $RedisHost --port $PORT --stream $STREAM --group $GROUP --idle-seconds $IDLE_SECONDS"
if ($CLUSTER_MODE -or $NODE_COUNT -eq 3) {
    $consumerCmd += " --cluster-mode"
}
if ($NODE_COUNT -ne 1) {
    $consumerCmd += " --node-count $NODE_COUNT"
}
if ($env:REDIS_CONSUMER_OPTS) {
    $consumerCmd = "$env:REDIS_CONSUMER_OPTS $consumerCmd"
}
$consumerCmd = "$consumerCmd > runs\$RUN_ID\consumer.log 2>&1"

$consumerProcess = Start-Process -FilePath cmd.exe -ArgumentList "/c $consumerCmd" -NoNewWindow -PassThru
Write-Host "  [1/4] Consumer started, PID: $($consumerProcess.Id)"

# [2/4] running producer...
Start-Sleep -Seconds 2
Write-Host "[2/4] $(Get-Date -Format 'HH:mm:ss') running producer..."
$producerLog = "runs\$RUN_ID\producer.log"

# Build producer command with output redirection
$producerCmd = "python scripts\redis_producer.py --run-id $RUN_ID --plan-csv $PLAN_CSV --out runs\$RUN_ID\producer.csv --host $RedisHost --port $PORT --stream $STREAM --speedup $SPEEDUP --max-t-sim $MAX_T_SIM"
if ($CLUSTER_MODE -or $NODE_COUNT -eq 3) {
    $producerCmd += " --cluster-mode"
}
if ($NODE_COUNT -ne 1) {
    $producerCmd += " --node-count $NODE_COUNT"
}
$producerCmd += " $PRODUCER_EXTRA"
if ($env:REDIS_PRODUCER_OPTS) {
    $producerCmd = "$env:REDIS_PRODUCER_OPTS $producerCmd"
}
$producerCmd = "$producerCmd >> runs\$RUN_ID\producer.log 2>&1"

try {
    Invoke-Expression $producerCmd
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Producer failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    Write-Host "  [2/4] Producer completed"
} catch {
    Write-Error "Producer failed: $_"
    exit 1
}

# [3/4] waiting for consumer to finish...
Write-Host "[3/4] $(Get-Date -Format 'HH:mm:ss') waiting for consumer to finish..."
$consumerProcess.WaitForExit()
Write-Host "  [3/4] Consumer finished"

# [4/4] computing TTI...
Write-Host "[4/4] $(Get-Date -Format 'HH:mm:ss') computing TTI..."
$ttiOut = "runs\$RUN_ID\tti_summary.json"
$ttiPrinted = "runs\$RUN_ID\tti_summary.printed.json"
python scripts\compute_tti.py --producer "runs\$RUN_ID\producer.csv" --consumer "runs\$RUN_ID\consumer.csv" --out $ttiOut | Tee-Object -FilePath $ttiPrinted

Write-Host "DONE. Outputs:"
Get-ChildItem "runs\$RUN_ID"
