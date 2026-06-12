#!/usr/bin/env powershell
# Complete rerun script for streaming-latency-sports
# This script: stops docker, cleans old runs, starts docker, runs all trials, builds outputs

$ErrorActionPreference = "Stop"

$repoRoot = "C:\Users\Gugar\Documents\streaming-latency-sports"
Set-Location $repoRoot

Write-Host "=== Streaming Latency Sports - Complete Rerun ===" -ForegroundColor Cyan
Write-Host "Repository: $repoRoot" -ForegroundColor Cyan

# Step 1: Stop Docker containers
Write-Host "[1/7] Stopping Docker containers..." -ForegroundColor Yellow
docker compose down 2>$null
Write-Host "Docker containers stopped." -ForegroundColor Green

# Step 2: Clean old run data
Write-Host "[2/7] Cleaning old run data..." -ForegroundColor Yellow
$runDirs = Get-ChildItem "runs" -Directory | Where-Object { $_.Name -match '^(s1_|s2_|s2full_|s2sf12_|s2sf12j2_|test_)' }
foreach ($dir in $runDirs) {
    Remove-Item $dir.FullName -Recurse -Force
    Write-Host "  Deleted: $($dir.Name)"
}
# Clean files in runs root
Get-ChildItem "runs" -File | Where-Object { $_.Name -match '^(consumer_events|redis_consumer)\..*$' } | Remove-Item -Force
Write-Host "Old data cleaned." -ForegroundColor Green

# Step 3: Start Docker services
Write-Host "[3/7] Starting Docker services..." -ForegroundColor Yellow
docker compose up -d
Start-Sleep -Seconds 60  # Wait for services to initialize (Kafka needs more time)
Write-Host "Docker services started." -ForegroundColor Green

# Step 4: Define scenarios
$scenarios = @(
    @{ prefix="s1"; plan="data/processed/replay_plans/s1/combined_plan.csv" },
    @{ prefix="s2"; plan="data/processed/replay_plans/s2/combined_plan.csv" },
    @{ prefix="s2full"; plan="data/processed/replay_plans/s2full/combined_plan.csv" },
    @{ prefix="s2sf12"; plan="data/processed/replay_plans/s2sf12/combined_plan.csv" },
    @{ prefix="s2sf12j2"; plan="data/processed/replay_plans/s2sf12j2/combined_plan.csv" }
)

# Step 5: Run trials for each scenario
Write-Host "[4/7] Running trials (this will take a while)..." -ForegroundColor Yellow
foreach ($scenario in $scenarios) {
    Write-Host "  Starting scenario: $($scenario.prefix)" -ForegroundColor Cyan
    & "scripts/run_s2_variant_blocks.ps1" $scenario.plan 5 120 600 "localhost:9092" "localhost" 6379 $scenario.prefix
    Write-Host "  Completed scenario: $($scenario.prefix)" -ForegroundColor Green
}

# Step 6: Update official run lists with interleaved order
Write-Host "[5/7] Updating official run lists..." -ForegroundColor Yellow
# The run_s2_variant_blocks.sh already creates _*_latest_runs.txt with interleaved order
# Copy to official files
$latestFiles = @("s1", "s2", "s2full", "s2sf12", "s2sf12j2")
foreach ($prefix in $latestFiles) {
    $src = "runs/_${prefix}_latest_runs.txt"
    $dest = "runs/_paper_${prefix}_official_runs.txt"
    if (Test-Path $src) {
        # Reorder to interleave kafka and redis
        $content = Get-Content $src
        $kafkaRuns = $content | Where-Object { $_ -match '_kafka_' }
        $redisRuns = $content | Where-Object { $_ -match '_redis_' }
        
        $reordered = @()
        for ($i = 0; $i -lt $kafkaRuns.Count; $i++) {
            $reordered += $kafkaRuns[$i]
            $reordered += $redisRuns[$i]
        }
        
        $reordered | Out-File $dest -Force
        Write-Host "  Created: $dest with $(($reordered.Count)) interleaved runs"
    }
}
Write-Host "Official run lists updated." -ForegroundColor Green

# Step 7: Build paper outputs
Write-Host "[6/7] Building paper outputs..." -ForegroundColor Yellow
& "scripts/build_paper_s2_outputs.ps1"
Write-Host "Paper outputs built." -ForegroundColor Green

# Step 8: Run tests
Write-Host "[7/7] Running tests..." -ForegroundColor Yellow
python -m pytest tests/ -q
Write-Host "Tests completed." -ForegroundColor Green

Write-Host "=== ALL DONE ===" -ForegroundColor Cyan
