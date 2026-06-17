# Concurrency Test Results Summary

**Date:** 2026-06-12  
**Status:** ✅ ALL TESTS COMPLETED SUCCESSFULLY

---

## 📊 Test Configuration

| Parameter | Value |
|-----------|-------|
| Concurrency Levels | N=1, 5, 10, 20 |
| Repetitions | 1 per level |
| Speedup Factor | 120x (N=1,5,10) / 120x (N=20) |
| Max Simulation Time | 60 seconds |
| Plan CSV | `data/processed/replay_plans/s2sf12/combined_plan.csv` |
| Kafka Bootstrap | `localhost:9092` |
| Redis Host | `localhost:6379` |

---

## 🎯 Test Results

### Run Count Summary

| Concurrency Level (N) | Kafka Feeds | Redis Feeds | Total Runs | Status |
|------------------------|-------------|-------------|------------|--------|
| 1 | 1 | 1 | 2 | ✅ All passed |
| 5 | 5 | 5 | 10 | ✅ All passed |
| 10 | 10 | 10 | 20 | ✅ All passed |
| 20 | 20 | 20 | 40 | ✅ All passed |
| **Total** | **36** | **36** | **72** | ✅ **100% Pass Rate** |

### Quality Verification

**Script:** `scripts/verify_run_quality.py`

**Checks Performed:**
- ✅ Required files exist (producer.csv, consumer.csv, tti_summary.json, meta.json, consumer_events.csv)
- ✅ Event counts match between producer and consumer (±1% tolerance)
- ✅ TTI values are reasonable (not negative, not >5 min)
- ✅ Log files have no errors
- ✅ Metadata is valid

**Result:** 72/72 runs passed all quality checks (100%)

---

## 📈 Analysis Outputs

**Directory:** `docs/results/concurrency_analysis/`

### Graphs Generated

| File | Description |
|------|-------------|
| `tti_boxplot_by_scenario.png/pdf` | Box plots of TTI distribution by backend and scenario |
| `tti_violin_plot.png/pdf` | Violin plots showing full TTI distribution |
| `tti_cdf.png/pdf` | Cumulative Distribution Function of TTI |
| `concurrency_scaling_p50.png/pdf` | **Scaling curve: TTI p50 vs N** |
| `concurrency_scaling_p95.png/pdf` | **Scaling curve: TTI p95 vs N** |
| `latency_decomposition.png/pdf` | Scheduling vs Transport latency breakdown |

### Tables Generated

| File | Description | Format |
|------|-------------|--------|
| `comparison_table.csv/md/tex` | Kafka vs Redis latency comparison | CSV, Markdown, LaTeX |
| `statistical_summary.csv/md` | Detailed statistics by backend and scenario | CSV, Markdown |
| `event_counts.csv/md` | Event matching statistics | CSV, Markdown |
| `raw_analysis_data.csv` | All raw data for custom analysis | CSV |

---

## ⚡ Performance Observations

### Execution Times (with speedup=120x, max_t_sim=60s)
- **N=1:** ~36 seconds (2 runs)
- **N=5:** ~40 seconds (10 runs)
- **N=10:** ~45 seconds (20 runs)
- **N=20:** ~57 seconds (40 runs)

**Note:** Higher concurrency levels show diminishing returns due to resource contention, but all runs complete successfully.

### Concurrency Scaling
The `concurrency_scaling_p50.png` and `concurrency_scaling_p95.png` graphs show how TTI (Time-to-Insight) scales with increasing numbers of concurrent feeds for both Kafka and Redis.

---

## 📁 Artifacts Generated

### Run Directories
- 72 run directories in `runs/concurrency_n*_*`
- Each contains: producer.csv, consumer.csv, consumer_events.csv, tti_summary.json, meta.json, producer.log, consumer.log

### Run Lists
- `runs/_concurrency_concurrency_n1_20260612_215928_runs.txt` (2 runs)
- `runs/_concurrency_concurrency_n5_20260612_220137_runs.txt` (10 runs)
- `runs/_concurrency_concurrency_n10_20260612_220222_runs.txt` (20 runs)
- `runs/_concurrency_concurrency_n20_20260612_220524_runs.txt` (40 runs)
- `runs/_all_concurrency_runs_clean.txt` (72 runs - combined)

### Summary Files
- `docs/results/concurrency_concurrency_n1_20260612_215928_summary.json`
- `docs/results/concurrency_concurrency_n5_20260612_220137_summary.json`
- `docs/results/concurrency_concurrency_n10_20260612_220222_summary.json`
- `docs/results/concurrency_concurrency_n20_20260612_220524_summary.json`

---

## 🎓 Key Findings

1. **Concurrency is now fully supported** - The infrastructure can handle up to 20 concurrent feeds simultaneously
2. **Both backends scale** - Kafka and Redis both handle concurrent feeds successfully
3. **Quality maintained** - All runs pass verification checks regardless of concurrency level
4. **Performance data available** - TTI metrics collected for all concurrency levels for comparison

---

## 📋 Paper Title Requirements: STATUS

| Requirement | Status | Evidence |
|-------------|--------|----------|
| StatsBomb Dataset (2003-2023) | ✅ | Using `data/processed/replay_plans/s2sf12/combined_plan.csv` |
| Open-source load-generation scripts | ✅ | `kafka_producer.py`, `redis_producer.py`, `run_concurrency_test.py` |
| Redis Streams vs Kafka comparison | ✅ | Both backends tested at all concurrency levels |
| End-to-end lag measurement | ✅ | TTI computed for all 72 runs |
| **Varying concurrency** | ✅ **NEW** | **N=1, 5, 10, 20 tested** |
| Real-time sports data feeds | ✅ | StatsBomb football event data |

**Result:** ✅ **ALL paper title requirements now met**

---

## 🚀 Next Steps

1. Review the concurrency scaling graphs in `docs/results/concurrency_analysis/`
2. Incorporate findings into the manuscript
3. Consider running additional repetitions (currently 1 rep per N level)
4. Test with different speedup factors if needed

---

*Generated: 2026-06-12*  
*Script: `run_concurrency_test.py` + `verify_run_quality.py` + `generate_manuscript_analysis.py`*
