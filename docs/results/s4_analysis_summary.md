# S4 Parameter Sensitivity Analysis

**Date:** 2026-06-12

**Objective:** Determine how speedup, corrections_every_k, and correction_delay_s affect S3 metrics

## Overview

- **Total Runs:** 32
- **Scenarios:** 2 (s2sf12, s2sf12j2)
- **Configurations:** 8
- **Backends:** 2

## Parameter Space

| Parameter | Values Tested |
|-----------|----------------|
| speedup | 60, 120, 240 |
| corrections_every_k | 10, 50, 100 |
| correction_delay_s | 0.5, 2.0, 5.0 |

## Configurations

| Config Name | Speedup | Corrections Every K | Delay (s) |
|-------------|---------|---------------------|----------|
| baseline | 120 | 50 | 2.0 |
| fast_corrections | 120 | 10 | 0.5 |
| high_frequency | 120 | 10 | 2.0 |
| high_speedup | 240 | 50 | 2.0 |
| long_delay | 120 | 50 | 5.0 |
| low_frequency | 120 | 100 | 2.0 |
| low_speedup | 60 | 50 | 2.0 |
| short_delay | 120 | 50 | 0.5 |

## Key Findings

### Effect of speedup

| Metric | Mean | Std | Min | Max | Count |
|--------|------|-----|-----|-----|-------|
| tti_p50 | 3921.74 | 1168.20 | 2909.50 | 4941.49 | 4 |
| tti_p50 | 4079.53 | 1028.00 | 3008.04 | 5154.33 | 24 |
| tti_p50 | 4184.00 | 1166.40 | 3174.34 | 5246.14 | 4 |
| tti_p95 | 5566.40 | 2162.30 | 3689.19 | 7450.07 | 4 |
| tti_p95 | 5947.88 | 1903.39 | 4019.81 | 7927.56 | 24 |
| tti_p95 | 6106.71 | 2147.02 | 4239.36 | 8037.17 | 4 |
| tti_p99 | 5715.03 | 2251.33 | 3762.13 | 7678.27 | 4 |
| tti_p99 | 6118.94 | 1987.35 | 4105.61 | 8171.70 | 24 |
| tti_p99 | 6277.04 | 2236.59 | 4329.73 | 8284.67 | 4 |
| tti_mean | 3918.65 | 1166.47 | 2907.62 | 4933.04 | 4 |
| tti_mean | 4086.64 | 1026.18 | 3044.47 | 5160.78 | 24 |
| tti_mean | 4188.00 | 1164.22 | 3177.99 | 5241.51 | 4 |

### Effect of corrections_every_k

| Metric | Mean | Std | Min | Max | Count |
|--------|------|-----|-----|-----|-------|
| tti_p50 | 4057.59 | 1070.88 | 3008.04 | 5137.74 | 8 |
| tti_p50 | 4075.27 | 1042.24 | 2909.50 | 5246.14 | 20 |
| tti_p50 | 4091.45 | 1147.98 | 3093.71 | 5093.00 | 4 |
| tti_p95 | 5995.60 | 1963.73 | 4081.75 | 7889.89 | 8 |
| tti_p95 | 5893.99 | 1936.06 | 3689.19 | 8037.17 | 20 |
| tti_p95 | 5899.26 | 2126.59 | 4056.30 | 7758.52 | 4 |
| tti_p99 | 6178.76 | 2058.55 | 4175.01 | 8167.27 | 8 |
| tti_p99 | 6056.55 | 2016.00 | 3762.13 | 8284.67 | 20 |
| tti_p99 | 6065.45 | 2221.31 | 4141.15 | 8001.83 | 4 |
| tti_mean | 4071.59 | 1064.99 | 3044.47 | 5119.65 | 8 |
| tti_mean | 4077.66 | 1041.48 | 2907.62 | 5241.51 | 20 |
| tti_mean | 4095.00 | 1150.35 | 3097.58 | 5097.86 | 4 |

### Effect of correction_delay_s

| Metric | Mean | Std | Min | Max | Count |
|--------|------|-----|-----|-----|-------|
| tti_p50 | 4111.11 | 1092.20 | 3069.06 | 5154.33 | 8 |
| tti_p50 | 4059.14 | 1036.15 | 2909.50 | 5246.14 | 20 |
| tti_p50 | 4065.02 | 1134.13 | 3081.25 | 5068.28 | 4 |
| tti_p95 | 5932.74 | 2005.21 | 4019.81 | 7840.40 | 8 |
| tti_p95 | 5913.50 | 1916.10 | 3689.19 | 8037.17 | 20 |
| tti_p95 | 5927.38 | 2155.18 | 4048.01 | 7829.47 | 4 |
| tti_p99 | 6105.64 | 2092.32 | 4105.61 | 8081.82 | 8 |
| tti_p99 | 6080.44 | 2000.67 | 3762.13 | 8284.67 | 20 |
| tti_p99 | 6092.20 | 2241.69 | 4141.07 | 8073.23 | 4 |
| tti_mean | 4108.11 | 1087.82 | 3077.53 | 5152.35 | 8 |
| tti_mean | 4068.14 | 1035.17 | 2907.62 | 5241.51 | 20 |
| tti_mean | 4069.59 | 1135.34 | 3081.13 | 5071.06 | 4 |

## Figures

Generated figures in `docs/results/s4_figures/`:
- `*_vs_speedup.png` - Effect of speedup factor
- `*_vs_corrections_every_k.png` - Effect of correction frequency
- `*_vs_correction_delay_s.png` - Effect of correction delay
- `*_interactions.png` - Parameter interaction plots

## Recommendations

Based on S4 analysis, optimal parameter settings for:

- **Lowest correction propagation latency:** [TO BE FILLED AFTER RUN]
- **Lowest state staleness:** [TO BE FILLED AFTER RUN]
- **Best trade-off:** [TO BE FILLED AFTER RUN]

