# Powershell version of run_kafka_trial.sh
# Usage: run_kafka_trial.ps1 <RUN_ID> <PLAN_CSV> [SPEEDUP] [MAX_T_SIM] [BOOTSTRAP] [TOPIC]

param(
    [Parameter(Mandatory=$true)][string]$RUN_ID,
    [Parameter(Mandatory=$true)][string]$PLAN_CSV,
    [int]$SPEEDUP = 120,
    [int]$MAX_T_SIM = 600,
    [string]$BOOTSTRAP = "localhost:9092",
    [string]$TOPIC = "sb-events",
    [int]$BROKER_COUNT = 1,
    [string]$PRODUCER_EXTRA = "",
    [int]$IDLE_SECONDS = 30
)

$ErrorActionPreference = "Stop"

# If TOPIC not provided, use default
if ($TOPIC -eq "sb-events") {
    $TOPIC = "sb-events-$RUN_ID"
}

# Create run directory
$runDir = "runs\$RUN_ID"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# Write per-run provenance (reviewer-proof)
$meta = @{
    run_id = $RUN_ID
    backend = "kafka"
    plan_csv = $PLAN_CSV
    speedup = $SPEEDUP
    max_t_sim = $MAX_T_SIM
    bootstrap = $BOOTSTRAP
    topic = $TOPIC
    env = @{
        KAFKA_PRODUCER_OPTS = $env:KAFKA_PRODUCER_OPTS
        KAFKA_CONSUMER_OPTS = $env:KAFKA_CONSUMER_OPTS
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

$meta.code_sha256.Add("scripts/run_kafka_trial.ps1", (Get-FileSHA256 "scripts\run_kafka_trial.ps1"))
$meta.code_sha256.Add("scripts/kafka_producer.py", (Get-FileSHA256 "scripts\kafka_producer.py"))
$meta.code_sha256.Add("scripts/kafka_consumer.py", (Get-FileSHA256 "scripts\kafka_consumer.py"))
$meta.code_sha256.Add("scripts/compute_tti.py", (Get-FileSHA256 "scripts\compute_tti.py"))

# Save meta.json
$metaPath = "runs\$RUN_ID\meta.json"
# Sort keys and write JSON
$json = $meta | ConvertTo-Json -Depth 10
$json | Out-File -FilePath $metaPath -Encoding utf8
Write-Host "Wrote meta: $metaPath"

# [0/4] ensuring topic exists
Write-Host "[0/4] $(Get-Date -Format 'HH:mm:ss') ensuring topic exists: $TOPIC"
if ($BROKER_COUNT -gt 1) {
    # Multi-broker: use kafka1 container and replication factor 3
    # try/catch so best-effort topic-create stderr doesn't trip ErrorActionPreference=Stop
    try { docker exec -w /opt/kafka/bin kafka1 sh -lc "./kafka-topics.sh --bootstrap-server kafka1:29092 --create --if-not-exists --topic '$TOPIC' --partitions 3 --replication-factor 3" 2>$null } catch {}
} else {
    # Single broker: container is named 'broker', listener localhost:19092, RF=1
    try { docker exec broker /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:19092 --create --if-not-exists --topic "$TOPIC" --partitions 3 --replication-factor 1 2>$null } catch {}
}
Write-Host "  [0/4] Topic ensured"

# [1/4] starting consumer...
Write-Host "[1/4] $(Get-Date -Format 'HH:mm:ss') starting consumer..."
$consumerLog = "runs\$RUN_ID\consumer.log"

# Build consumer command with output redirection
$consumerCmd = "python scripts\kafka_consumer.py --run-id $RUN_ID --out runs\$RUN_ID\consumer.csv --bootstrap $BOOTSTRAP --topic $TOPIC --idle-seconds $IDLE_SECONDS --broker-count $BROKER_COUNT"
if ($env:KAFKA_CONSUMER_OPTS) {
    $consumerCmd = "$env:KAFKA_CONSUMER_OPTS $consumerCmd"
}
$consumerCmd = "$consumerCmd > runs\$RUN_ID\consumer.log 2>&1"

$consumerProcess = Start-Process -FilePath cmd.exe -ArgumentList "/c $consumerCmd" -NoNewWindow -PassThru
Write-Host "  [1/4] Consumer started, PID: $($consumerProcess.Id)"

# [2/4] running producer...
Start-Sleep -Seconds 2
Write-Host "[2/4] $(Get-Date -Format 'HH:mm:ss') running producer..."
$producerLog = "runs\$RUN_ID\producer.log"

# Build producer command with output redirection
$producerCmd = "python scripts\kafka_producer.py --run-id $RUN_ID --plan-csv $PLAN_CSV --out runs\$RUN_ID\producer.csv --bootstrap $BOOTSTRAP --topic $TOPIC --speedup $SPEEDUP --max-t-sim $MAX_T_SIM --broker-count $BROKER_COUNT $PRODUCER_EXTRA"
if ($env:KAFKA_PRODUCER_OPTS) {
    $producerCmd = "$env:KAFKA_PRODUCER_OPTS $producerCmd"
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
