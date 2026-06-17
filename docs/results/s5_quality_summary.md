# S5 Resource Analysis - Quality Metrics

**Date:** 2026-06-12

**Objective:** Analyze computational resource usage and quality metrics for S5 parameter sweep

## Overview

- **Total Runs:** 24
- **Scenarios:** 2 (s2sf12, s2sf12j2)
- **Configurations:** 6 (baseline, fast_corrections, high_frequency, high_speedup, long_delay, low_frequency)
- **Backends:** 2 (kafka, redis)

## Parameter Space

| Parameter | Values Tested |
|-----------|----------------|
| speedup | 120, 240|
| corrections_every_k | 10, 50, 100|
| correction_delay_s | 0.5, 2.0, 5.0|

## Quality Metrics

### Average TTI Metrics

| Backend | Config | Speedup | Count | TTI p50 | TTI p95 | TTI Mean |
|---------|--------|---------|-------|---------|---------|----------|
| kafka | baseline | 120 | 2 | 3858.93 | 5416.49 | 3860.99 |
| kafka | fast_corrections | 120 | 2 | 5176.56 | 7932.96 | 5174.98 |
| kafka | high_frequency | 120 | 2 | 3767.06 | 5366.14 | 3762.67 |
| kafka | high_speedup | 240 | 2 | 3872.54 | 5432.94 | 3866.66 |
| kafka | long_delay | 120 | 2 | 5041.14 | 7842.28 | 5072.02 |
| kafka | low_frequency | 120 | 2 | 3845.30 | 5367.97 | 3838.66 |
| redis | baseline | 120 | 2 | 2631.88 | 3179.59 | 2628.97 |
| redis | fast_corrections | 120 | 2 | 3088.48 | 4077.91 | 3089.27 |
| redis | high_frequency | 120 | 2 | 2575.25 | 3242.78 | 2592.34 |
| redis | high_speedup | 240 | 2 | 2668.97 | 3278.55 | 2676.09 |
| redis | long_delay | 120 | 2 | 3087.62 | 4043.27 | 3084.32 |
| redis | low_frequency | 120 | 2 | 3070.24 | 4007.20 | 3068.65 |

### Resource Metrics

| Backend | Config | Kafka Cpu | Kafka Peak Mem | Kafka Mem | Redis Peak Cpu | System Cpu | System Peak Cpu | Redis Mem | Sample Count | Speedup | Kafka Peak Cpu | Redis Cpu | Redis Peak Mem |
|---------|--------| |  |  |  |  |  |  |  |  |  |  |  | |
| kafka | baseline | 1.65 | 1115.65 | 1114.77 | 0.25 | 19.32 | 22.30 | 124.98 | 9.00 | 120.00 | 1.88 | 0.23 | 125.00 |
| kafka | fast_corrections | 4.10 | 1118.21 | 1118.08 | 0.24 | 19.54 | 26.30 | 129.80 | 5.00 | 120.00 | 16.33 | 0.23 | 129.80 |
| kafka | high_frequency | 1.57 | 1116.16 | 1116.16 | 0.24 | 17.74 | 24.83 | 126.95 | 9.00 | 120.00 | 1.76 | 0.23 | 126.95 |
| kafka | high_speedup | 1.64 | 1116.16 | 1116.16 | 0.24 | 19.10 | 27.25 | 126.20 | 9.00 | 240.00 | 1.82 | 0.23 | 126.20 |
| kafka | long_delay | 2.58 | 1117.18 | 1116.37 | 0.24 | 18.82 | 25.51 | 128.26 | 10.50 | 120.00 | 17.44 | 0.23 | 128.30 |
| kafka | low_frequency | 1.65 | 1116.16 | 1116.16 | 0.27 | 18.13 | 22.39 | 127.75 | 9.50 | 120.00 | 1.91 | 0.23 | 127.75 |
| redis | baseline | 1.54 | 1102.84 | 1102.84 | 0.26 | 17.77 | 18.87 | 126.03 | 8.00 | 120.00 | 1.66 | 0.23 | 126.15 |
| redis | fast_corrections | 1.50 | 1104.90 | 1104.64 | 0.25 | 17.90 | 18.57 | 131.90 | 3.50 | 120.00 | 1.59 | 0.24 | 131.90 |
| redis | high_frequency | 1.50 | 1103.36 | 1103.36 | 0.26 | 19.17 | 22.69 | 127.80 | 8.50 | 120.00 | 1.59 | 0.24 | 127.80 |
| redis | high_speedup | 1.45 | 1103.88 | 1103.44 | 0.26 | 16.74 | 18.49 | 127.00 | 7.50 | 240.00 | 1.59 | 0.25 | 127.00 |
| redis | long_delay | 1.50 | 1103.88 | 1103.88 | 0.26 | 15.98 | 18.07 | 129.85 | 4.00 | 120.00 | 1.63 | 0.24 | 129.85 |
| redis | low_frequency | 1.55 | 1103.88 | 1103.88 | 0.25 | 16.33 | 16.84 | 131.30 | 3.50 | 120.00 | 1.69 | 0.25 | 131.30 |

## Figures

Generated figures in `docs/results/s5_figures/`:
- `tti_p50_by_config_backend.png` - TTI p50 comparison
- `tti_p95_by_config_backend.png` - TTI p95 comparison
- `event_counts_by_config_backend.png` - Event count comparison

