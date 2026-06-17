#!/usr/bin/env pwsh
# S3 state-staleness corrections, regenerated with corrected code (single-broker infra).
# kafka/redis x S1-S5 x 3 reps, --s3-mode corrections (every 50th event, 2s delay).
# Output: s3c_<DateTag>_* runs (consumer_events.csv carries the correction envelope).
param([string]$DateTag = "20260617", [int[]]$Reps = @(1,2,3), [int]$Idle = 12)
$ErrorActionPreference = "Continue"
$plans = @{
    s1="data\processed\replay_plans\s1\combined_plan.csv"
    s2="data\processed\replay_plans\s2\combined_plan.csv"
    s2full="data\processed\replay_plans\s2full\combined_plan.csv"
    s2sf12="data\processed\replay_plans\s2sf12\combined_plan.csv"
    s2sf12j2="data\processed\replay_plans\s2sf12j2\combined_plan.csv"
}
$scenarios=@("s1","s2","s2full","s2sf12","s2sf12j2")
$prefix="s3c_$DateTag"
$s3extra="--s3-mode corrections --corrections-every-k 50 --correction-delay-s 2.0"
$runList="runs\_${prefix}_runs.txt"; "" | Out-File $runList -Encoding utf8
$total=0;$ok=0
foreach ($backend in @("kafka","redis")) {
  foreach ($scenario in $scenarios) {
    foreach ($rep in $Reps) {
      $total++
      $run_id="${prefix}_${backend}_${scenario}_rep${rep}"
      if (Test-Path "runs\$run_id\tti_summary.json") { Write-Host "$run_id [SKIP]"; "runs/$run_id"|Out-File $runList -Append -Encoding utf8; $ok++; continue }
      Write-Host "[$total] $run_id"
      if ($backend -eq "kafka") {
        & pwsh -Command "scripts\run_kafka_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$($plans[$scenario])' -BOOTSTRAP 'localhost:19092' -TOPIC 'sb-events-$run_id' -BROKER_COUNT 1 -IDLE_SECONDS $Idle -PRODUCER_EXTRA '$s3extra --max-inflight 1000'" *> "runs\$run_id.log" 2>&1
      } else {
        & pwsh -Command "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$($plans[$scenario])' -RedisHost 'localhost' -PORT 16379 -STREAM 'sb:events:$run_id' -GROUP 'sb-group:$run_id' -NODE_COUNT 1 -IDLE_SECONDS $Idle -PRODUCER_EXTRA '$s3extra'" *> "runs\$run_id.log" 2>&1
      }
      if (Test-Path "runs\$run_id\tti_summary.json") { "runs/$run_id"|Out-File $runList -Append -Encoding utf8; $ok++; Write-Host "  [DONE]" } else { Write-Host "  [FAILED]" }
    }
  }
}
Write-Host "=== S3 CORRECTED COMPLETE: $ok/$total ==="
