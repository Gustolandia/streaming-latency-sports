# S4 Parameter Sweep Analysis Report

**Date:** 2026-06-12 16:48:47

## Overview

- **Total Runs:** 32
- **Scenarios:** s2sf12, s2sf12j2
- **Configurations:** 8
- **Backends:** kafka, redis

## Parameter Space

| Parameter | Values |
|-----------|--------|
| speedup | 60, 120, 240 |
| corrections_every_k | 10, 50, 100 |
| correction_delay_s | 0.5, 2.0, 5.0 |

## Configurations

| Config | Speedup | Corrections Every K | Delay (s) |
|--------|---------|---------------------|----------|
| baseline | 120 | 50 | 2.0 |
| fast_corrections | 120 | 10 | 0.5 |
| high_frequency | 120 | 10 | 2.0 |
| high_speedup | 240 | 50 | 2.0 |
| long_delay | 120 | 50 | 5.0 |
| low_frequency | 120 | 100 | 2.0 |
| low_speedup | 60 | 50 | 2.0 |
| short_delay | 120 | 50 | 0.5 |

## Key Findings

### Backend Performance

- **Kafka Median TTI:** 5079.54 ms
- **Redis Median TTI:** 3066.19 ms
- **Redis is 1.7x faster** for median TTI

### Best Configurations

- **Kafka:** low_speedup (Median TTI = 4925.33 ms)
- **Redis:** low_speedup (Median TTI = 2909.50 ms)

### Parameter Sensitivity

- **Speedup:** Redis: 60=2910.1ms, 120=3074.2ms, 240=3174.6ms
- **Correction Frequency:** Redis: 10=3057.5ms, 50=3063.4ms, 100=3097.3ms
- **Correction Delay:** Redis: 0.5=3089.6ms, 2.0=3053.5ms, 5.0=3083.0ms

## Tables

See `tables/` directory for CSV files:
- `s4_backend_comparison.csv` - Overall Kafka vs Redis
- `s4_config_comparison.csv` - By configuration
- `s4_by_speedup.csv` - Speedup effect
- `s4_by_corrections_every_k.csv` - Correction frequency effect
- `s4_by_correction_delay_s.csv` - Correction delay effect
- `s4_all_data.csv` - Complete dataset

## Figures

See `figures/` directory for PNG files:
- `s4_tti_backend_boxplot.png` - TTI distribution by backend
- `s4_tti_by_config.png` - TTI by configuration
- `s4_speedup_impact.png` - Speedup effect
- `s4_correction_freq_impact.png` - Correction frequency effect
- `s4_correction_delay_impact.png` - Correction delay effect
- `s4_missed_window_rates.png` - Missed window rates
