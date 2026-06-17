#!/usr/bin/env pwsh
# Persistence variations (corrected code), single-broker infra:
#   H31: Kafka acks=1 vs acks=all   (durability vs latency)
#   H32: Redis AOF everysec vs always (durability vs latency)
# Uses scenario s2sf12, 3 reps each. Output: batch9p_<DateTag>_* runs.
param([string]$DateTag = "20260617", [int[]]$Reps = @(1,2,3), [int]$Idle = 10)
$ErrorActionPreference = "Continue"
$plan = "data\processed\replay_plans\s2sf12\combined_plan.csv"
$prefix = "batch9p_$DateTag"

function Run-One($run_id, $sb) {
  if (Test-Path "runs\$run_id\tti_summary.json") { Write-Host "$run_id [SKIP]"; return }
  Write-Host "RUN $run_id"
  if ($sb -eq "kafka") {
    $extra = $args[0]
    & pwsh -Command "scripts\run_kafka_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan' -BOOTSTRAP 'localhost:19092' -TOPIC 'sb-events-$run_id' -BROKER_COUNT 1 -IDLE_SECONDS $Idle -PRODUCER_EXTRA '$($args[0])'" *> "runs\$run_id.log" 2>&1
  } else {
    & pwsh -Command "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan' -RedisHost 'localhost' -PORT 16379 -STREAM 'sb:events:$run_id' -GROUP 'sb-group:$run_id' -NODE_COUNT 1 -IDLE_SECONDS $Idle" *> "runs\$run_id.log" 2>&1
  }
}

# --- H31: Kafka acks=1 vs acks=all ---
foreach ($acks in @("1","all")) {
  foreach ($rep in $Reps) {
    Run-One "${prefix}_kafka_single_s2sf12_acks${acks}_rep${rep}" "kafka" "--acks $acks --max-inflight 1000"
  }
}

# --- H32: Redis AOF everysec vs always ---
foreach ($fsync in @("everysec","always")) {
  # configure the single redis container's persistence for this batch
  docker exec streaming-latency-sports-redis-1 redis-cli CONFIG SET appendonly yes 2>$null | Out-Null
  docker exec streaming-latency-sports-redis-1 redis-cli CONFIG SET appendfsync $fsync 2>$null | Out-Null
  foreach ($rep in $Reps) {
    Run-One "${prefix}_redis_single_s2sf12_aof${fsync}_rep${rep}" "redis"
  }
}
# restore default (no persistence)
docker exec streaming-latency-sports-redis-1 redis-cli CONFIG SET appendonly no 2>$null | Out-Null
Write-Host "=== PERSISTENCE COMPLETE ==="
