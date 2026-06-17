# Concurrency Sweep Analysis

## Overview
- **Date**: 2026-06-13
- **Total Runs**: 250
- **Scenarios**: 5
- **Backends**: Kafka, Redis
- **Concurrency Levels**: [5, 10, 20]

## Key Metrics
- **Avg TTI p50**: 13442.31 ms
- **Avg TTI p95**: 21273.31 ms
- **Avg Match Rate**: 100.00%

## Scenario Definitions
- **S1**: s1
- **S2**: s2
- **S3**: s2full
- **S4**: s2sf12
- **S5**: s2sf12j2

## Generated Files
- `scenario_comparison.csv`
- `scaling_analysis.csv`
- `statistical_comparison.csv`
- `event_analysis.csv`
- `tti_scaling.png`
- `backend_boxplot.png`
- `match_rate_bars.png`
