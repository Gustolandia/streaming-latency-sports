#!/usr/bin/env pwsh
# Regenerate the multi-broker matrix with the CORRECTED code (time.time_ns clock +
# non-blocking producer). One infra phase at a time (cluster OR single), because the
# single-broker Kafka collides with the cluster on port 9092.
#
#   Cluster phase (cluster compose up):  .\scripts\regenerate_corpus.ps1 -Phase cluster
#   Single phase  (single compose up):   .\scripts\regenerate_corpus.ps1 -Phase single
#
# Runs are tagged batch9_<DateTag> so they are distinct from the old contaminated
# batch1/2/3 dirs and still match the analyze_batches_1_2_3 / statistical_analysis regex.
param(
    [Parameter(Mandatory=$true)][ValidateSet("cluster","single")][string]$Phase,
    [string]$DateTag = "20260617",
    [int[]]$Reps = @(1,2,3),
    [int]$Idle = 10
)
# Each run is a single producer/consumer feed (labelled n1). The legacy "concurrency"
# N=5/10/20 batch labels were a single feed each anyway; true concurrency is measured
# separately via run_concurrency_test.py. Here we vary backend x config x scenario x rep.
$ErrorActionPreference = "Continue"

$plans = @{
    s1       = "data\processed\replay_plans\s1\combined_plan.csv"
    s2       = "data\processed\replay_plans\s2\combined_plan.csv"
    s2full   = "data\processed\replay_plans\s2full\combined_plan.csv"
    s2sf12   = "data\processed\replay_plans\s2sf12\combined_plan.csv"
    s2sf12j2 = "data\processed\replay_plans\s2sf12j2\combined_plan.csv"
}
$scenarios = @("s1","s2","s2full","s2sf12","s2sf12j2")
$prefix = "batch9_$DateTag"
$runList = "runs\_${prefix}_${Phase}_runs.txt"
"" | Out-File -FilePath $runList -Encoding utf8

$total = 0; $ok = 0; $fail = 0
$plannedCount = 2 * $scenarios.Count * $Reps.Count
Write-Host "=== REGENERATE ($Phase) : $plannedCount runs, idle=$Idle ==="

foreach ($backend in @("kafka","redis")) {
  foreach ($scenario in $scenarios) {
      foreach ($rep in $Reps) {
        $total++
        $run_id = "${prefix}_${backend}_${Phase}_${scenario}_n1_rep${rep}"
        $runDir = "runs\$run_id"
        $plan   = $plans[$scenario]
        if (Test-Path "$runDir\tti_summary.json") {
          Write-Host "[$total/$plannedCount] $run_id [SKIP - done]"
          "runs/$run_id" | Out-File -FilePath $runList -Append -Encoding utf8
          $ok++; continue
        }
        Write-Host "[$total/$plannedCount] $run_id"
        if ($backend -eq "kafka") {
          if ($Phase -eq "cluster") { $boot = "localhost:9092,localhost:9093,localhost:9094"; $bc = 3 }
          else                      { $boot = "localhost:19092"; $bc = 1 }
          & pwsh -Command "scripts\run_kafka_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan' -BOOTSTRAP '$boot' -TOPIC 'sb-events-$run_id' -BROKER_COUNT $bc -IDLE_SECONDS $Idle -PRODUCER_EXTRA '--max-inflight 1000'" *> "$runDir.log" 2>&1
        } else {
          if ($Phase -eq "cluster") {
            & pwsh -Command "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan' -RedisHost 'localhost' -PORT 7000 -STREAM 'sb:events:$run_id' -GROUP 'sb-group:$run_id' -CLUSTER_MODE -NODE_COUNT 3 -IDLE_SECONDS $Idle" *> "$runDir.log" 2>&1
          } else {
            & pwsh -Command "scripts\run_redis_trial.ps1 -RUN_ID '$run_id' -PLAN_CSV '$plan' -RedisHost 'localhost' -PORT 16379 -STREAM 'sb:events:$run_id' -GROUP 'sb-group:$run_id' -NODE_COUNT 1 -IDLE_SECONDS $Idle" *> "$runDir.log" 2>&1
          }
        }
        if (Test-Path "$runDir\tti_summary.json") {
          "runs/$run_id" | Out-File -FilePath $runList -Append -Encoding utf8
          $ok++; Write-Host "  [DONE]"
        } else {
          $fail++; Write-Host "  [FAILED] (see $runDir.log)"
        }
      }
  }
}
Write-Host "=== $Phase COMPLETE: $ok ok, $fail failed of $total ==="
