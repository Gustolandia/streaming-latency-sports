# Methodology: Streaming Latency Benchmarks for Sports Data

**Project:** Streaming Latency Benchmarks: Redis Streams vs Kafka for Real-Time Sports Data Feeds  
**Target Journal:** Journal of Sports Analytics (Q1 2026)  
**Last Updated:** June 9, 2026  
**Version:** 0.3.0-s3-scaffolding

---

## 📋 Table of Contents

1. [Research Design](#-research-design)
2. [Experimental Setup](#-experimental-setup)
3. [Data Pipeline](#-data-pipeline)
4. [Benchmarking Protocol](#-benchmarking-protocol)
5. [Metrics Calculation](#-metrics-calculation)
6. [Statistical Analysis](#-statistical-analysis)
7. [Reproducibility Protocol](#-reproducibility-protocol)
8. [Quality Assurance](#-quality-assurance)
9. [Ethical Considerations](#-ethical-considerations)

---

## 🎯 Research Design

### Study Type
- **Design:** Empirical benchmarking study
- **Approach:** Comparative analysis of streaming architectures
- **Method:** Controlled experimentation with synthetic workloads
- **Data:** Real-world football event data (StatsBomb open dataset)

### Research Questions

#### Primary Research Question
> **How do streaming architecture choices (Kafka vs Redis Streams) impact the timeliness and reliability of live match analytics and alerts under realistic football match concurrency?**

#### Secondary Questions
1. **Performance Comparison:** What are the TTI distributions (p50, p95, p99) for each architecture?
2. **Actionability:** How do missed-window rates differ across actionability windows (100ms, 250ms, 500ms, 1000ms)?
3. **Latency Composition:** What is the decomposition between transport latency and scheduling lag?
4. **Concurrency Impact:** How does increasing match concurrency affect latency metrics?
5. **Consistency (S3):** How does correction propagation latency affect state staleness?

### Hypotheses

| Hypothesis | Description | Status |
|-----------|-------------|--------|
| H1 | Redis Streams will have lower TTI than Kafka for 100ms actionability window | ✅ Supported (S2 results) |
| H2 | Kafka's transport latency will dominate its TTI in high-concurrency scenarios | ✅ Supported (S2 results) |
| H3 | Correction propagation latency will be higher in Kafka than Redis | 🔄 Testing (S3) |
| H4 | State staleness duration will be proportional to correction delay | 🔄 Testing (S3) |

---

## 🧪 Experimental Setup

### Independent Variables

| Variable | Levels | Description |
|----------|--------|-------------|
| Streaming Backend | Kafka, Redis | Message streaming system |
| Scenario | s1, s2sf12, s2sf12j2, s2full | Workload configuration |
| Speedup Factor | 1x, 120x | Simulation speed relative to real-time |
| Max Simulation Time | 600s | Maximum simulated match time |
| Match Concurrency | 1-10 | Number of simultaneous matches |
| S3 Mode | none, baseline, corrections | Correction handling mode |
| Correction Frequency | every k-th event | How often corrections are injected |
| Correction Delay | 0-5 seconds | Delay before correction is emitted |

### Dependent Variables (Metrics)

#### Primary Metrics
1. **Time-to-Insight (TTI)** - p50, p95, p99, IQR
2. **Missed-Window Rate** - For W ∈ {100ms, 250ms, 500ms, 1000ms}
3. **Transport Latency** - p50, p95, p99
4. **Scheduling Lag** - p50, p95, p99

#### S3-Specific Metrics
5. **Correction Propagation Latency** - p50, p95, p99
6. **Inconsistency Duration** - p50, p95, p99
7. **State Staleness at Decision Time** - Distribution and percentiles

### Controlled Variables

| Variable | Value | Rationale |
|----------|-------|-----------|
| Hardware | Standard laptop/desktop | Representative of real-world deployment |
| OS | WSL2 (Ubuntu) | Best compatibility for Docker |
| Python Version | 3.9+ | Ensures dependency compatibility |
| Docker Version | 20.10+ | Required for services |
| Network | Localhost | Eliminates network variability |
| Dataset | StatsBomb 3bfbffe1 | Consistent data source |
| Matches | 10 specific matches | Representative workload |

### Experimental Design Matrix

```
┌─────────────┬──────────┬──────────┬─────────┬─────────┐
│ Scenario     │ Backend  │ Speedup  │ Max t   │ Reps    │
├─────────────┼──────────┼──────────┼─────────┼─────────┤
│ s1_baseline  │ Kafka    │ 120x     │ 600s    │ 5       │
│ s1_baseline  │ Redis    │ 120x     │ 600s    │ 5       │
│ s2sf12      │ Kafka    │ 120x     │ 600s    │ 5       │
│ s2sf12      │ Redis    │ 120x     │ 600s    │ 5       │
│ s2sf12j2    │ Kafka    │ 120x     │ 600s    │ 5       │
│ s2sf12j2    │ Redis    │ 120x     │ 600s    │ 5       │
│ s2full      │ Kafka    │ 120x     │ 600s    │ 5       │
│ s2full      │ Redis    │ 120x     │ 600s    │ 5       │
│ s3_baseline │ Kafka    │ 120x     │ 600s    │ TBD     │
│ s3_baseline │ Redis    │ 120x     │ 600s    │ TBD     │
│ s3_corrections │ Kafka  │ 120x     │ 600s    │ TBD     │
│ s3_corrections │ Redis  │ 120x     │ 600s    │ TBD     │
└─────────────┴──────────┴──────────┴─────────┴─────────┘

Total S2 runs: 20 (frozen)
Total S3 runs: TBD (in progress)
```

---

## 📊 Data Pipeline

### Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA PIPELINE                                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐            │
│  │  STATSBOMB   │────▶│  RAW DATA    │────▶│  PROCESSING  │            │
│  │  OPEN DATA   │     │  (JSON)       │     │  SCRIPTS      │            │
│  │  (2003-2023) │     │               │     │              │            │
│  └──────────────┘     └──────────────┘     └──────┬───────┘            │
│                                                        │                   │
│                   ┌────────────────────────────────────┼───────────────┐ │
│                   │            REPLAY PLAN GENERATION                     │ │
│                   │                                                         │ │
│        ┌──────────▼──────────┐            ┌──────────▼──────────┐         │ │
│        │                      │            │                      │         │ │
│        │  make_replay_plan.py │            │ make_multimatch_     │         │ │
│        │  (Single match)       │            │   plan.py            │         │ │
│        │                      │            │ (Multiple matches)   │         │ │
│        └──────────┬──────────┘            └──────────┬──────────┘         │ │
│                   │                              │                   │ │
│                   └──────────────────────────┬───────────────────┘ │
│                                                │                       │
│                     ┌──────────────────────────▼───────────────────┐  │
│                     │                     REPLAY PLAN                             │  │
│                     │  (CSV format: t_emit_offset_s, match_id, event_id, ...)   │  │
│                     └──────────────────────────┬───────────────────┘  │
│                                                  │                       │
│                     ┌────────────────────────────▼────────────────────┐  │
│                     │                        LOAD GENERATION                            │  │
│                     │                                                               │  │
│        ┌────────────▼────────────┐     ┌────────────▼────────────┐        │ │
│        │  kafka_producer.py       │     │  redis_producer.py       │        │ │
│        │  • Reads replay plan     │     │  • Reads replay plan     │        │ │
│        │  • Emits to Kafka topic   │     │  • Emits to Redis stream │        │ │
│        │  • Respects speedup      │     │  • Respects speedup      │        │ │
│        │  • Handles S3 corrections │     │  • Handles S3 corrections │        │ │
│        └────────────┬────────────┘     └────────────┬────────────┘     │ │
│                     │                              │                  │ │
│                     ▼                              ▼                   │ │
│        ┌───────────────────────────────────────────────────────────┐   │ │
│        │                     STREAMING BACKEND                            │   │ │
│        │                                                               │   │ │
│        │  ┌──────────────┐           ┌──────────────┐               │   │ │
│        │  │   KAFKA       │           │   REDIS       │               │   │ │
│        │  │               │           │               │               │   │ │
│        │  │ • Topic: sb-events   │           │ • Stream: sb:events│     │   │ │
│        │  │ • Broker: localhost│           │ • Host: localhost  │     │   │ │
│        │  │ • Port: 9092    │           │ • Port: 6379      │     │   │ │
│        │  └──────────────┘           └──────────────┘               │   │ │
│        └───────────────────────────────────────────────────────────┘   │ │
│                                                                             │ │
│        ┌───────────────────────────────────────────────────────────┐   │ │
│        │                     CONSUMER LAYER                              │   │ │
│        │                                                               │   │ │
│        │  ┌──────────────┐           ┌──────────────┐               │   │ │
│        │  │ kafka_consumer│           │redis_consumer│               │   │ │
│        │  │              │           │              │               │   │ │
│        │  │ • Subscribes  │           │ • XREAD      │               │   │ │
│        │  │ • Processes   │           │ • Processes   │               │   │ │
│        │  │ • Writes events│           │ • Writes events│             │   │ │
│        │  └──────────────┘           └──────────────┘               │   │ │
│        └───────────────────────────────────────────────────────────┘   │ │
│                                                                             │ │
│        ┌───────────────────────────────────────────────────────────┐   │ │
│        │                     METRICS COMPUTATION                         │   │ │
│        │                                                               │   │ │
│        │  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐   │ │
│        │  │ compute_tti  │◄────┤ consumer     │     │ compare_      │   │ │
│        │  │ .py          │     │ _events.csv  │     │ plans.py      │   │ │
│        │  │              │     │              │     │              │   │ │
│        │  │ • TTI        │     │ • Raw events │     │ • Plan diffs  │   │ │
│        │  │ • Decomp     │     │ • Timestamps │     │              │   │ │
│        │  │ • Percentiles│     │              │     │              │   │ │
│        │  └──────────────┘     └──────────────┘     └──────────────┘   │ │
│        └───────────────────────────────────────────────────────────┘   │ │
│                                                                             │ │
│        ┌───────────────────────────────────────────────────────────┐   │ │
│        │                     OUTPUT ARTIFACTS                             │   │ │
│        │                                                               │   │ │
│        │  • runs/<run_id>/meta.json           (Run metadata)          │   │ │
│        │  • runs/<run_id>/tti_summary.json     (Computed metrics)      │   │ │
│        │  • runs/<run_id>/consumer_events.csv  (Raw consumer data)     │   │ │
│        │  • docs/results/*.csv                (Paper tables)           │   │ │
│        │  • data/processed/results/*.csv         (Aggregated results)     │   │ │
│        └───────────────────────────────────────────────────────────┘   │ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Description

1. **Data Ingestion**
   - Source: StatsBomb GitHub repository
   - Commit: `3bfbffe1de5750ebd47d770be0bb924a10cde54f`
   - Format: JSON (events, matches, competitions)
   - Script: `fetch_statsbomb.py`

2. **Data Processing**
   - Convert JSON to structured format
   - Extract relevant fields for replay
   - Filter to specific matches
   - Store in: `data/raw/statsbomb/`

3. **Replay Plan Generation**
   - Single match: `make_replay_plan.py`
   - Multiple matches: `make_multimatch_plan.py`
   - Output: CSV with emission schedule
   - Key columns: `t_emit_offset_s`, `match_id`, `event_id`, `event_type`

4. **Load Generation**
   - Read replay plan CSV
   - Emit events according to schedule
   - Respect speedup factor (120x default)
   - Handle S3 corrections (if enabled)

5. **Streaming**
   - Producer → Broker → Consumer
   - Measure transport latency
   - Track message flow

6. **Metrics Computation**
   - Compute TTI for each event
   - Calculate percentiles and IQR
   - Decompose latency components
   - Aggregate across runs

7. **Output**
   - Per-run artifacts
   - Aggregated results
   - Paper-ready tables

---

## 🚀 Benchmarking Protocol

### Pre-Benchmark Setup

1. **Environment Preparation**
   ```bash
   # Clone repository
   git clone https://github.com/[your-org]/streaming-latency-sports.git
   cd streaming-latency-sports
   
   # Create virtual environment (WSL recommended)
   python -m venv .venv
   source .venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Start services
   docker compose up -d
   
   # Verify services
   docker compose ps
   ```

2. **Data Verification**
   ```bash
   # Check StatsBomb data exists
   ls data/raw/statsbomb/3bfbffe1de5750ebd47d770be0bb924a10cde54f/events/
   
   # Verify event counts
   ls data/raw/statsbomb/3bfbffe1de5750ebd47d770be0bb924a10cde54f/events/ | wc -l
   # Expected: 11 JSON files (10 matches + 1 extra)
   ```

3. **Plan Verification**
   ```bash
   # Check replay plans exist
   ls data/processed/replay_plans/3bfbffe1de5750ebd47d770be0bb924a10cde54f/
   
   # Verify plan row counts
   head -1 data/processed/replay_plans/.../combined_plan.csv
   wc -l data/processed/replay_plans/.../combined_plan.csv
   # Expected: ~40,660 events (10 matches)
   ```

### Benchmark Execution Protocol

#### Single Trial Execution

```bash
# 1. Set run ID (timestamp recommended)
RUN_ID="s2sf12_kafka_rep1_$(date +%Y%m%d_%H%M%S)"

# 2. Start consumer (in separate terminal)
python scripts/kafka_consumer.py \
    --run-id $RUN_ID \
    --out runs/$RUN_ID \
    --topic sb-events \
    --bootstrap localhost:9092

# 3. Start producer (in another terminal)
python scripts/kafka_producer.py \
    --run-id $RUN_ID \
    --plan-csv data/processed/replay_plans/.../combined_plan.csv \
    --out runs/$RUN_ID \
    --speedup 120 \
    --max-t-sim 600

# 4. Wait for completion
# Producer will exit when all events are emitted
# Consumer will exit when all events are processed

# 5. Verify outputs
ls runs/$RUN_ID/
# Expected: meta.json, consumer_events.csv (and tti_summary.json after step 6)
```

#### Metrics Computation

```bash
# Compute TTI metrics
python scripts/compute_tti.py \
    --run-id $RUN_ID \
    --in runs/$RUN_ID \
    --out runs/$RUN_ID

# Verify output
ls runs/$RUN_ID/tti_summary.json
cat runs/$RUN_ID/tti_summary.json | python -m json.tool | head -20
```

#### Batch Execution

```bash
# Run multiple trials (e.g., 5 replications)
SCENARIO="s2sf12"
BACKEND="kafka"
PLAN="data/processed/replay_plans/3bfbffe1de5750ebd47d770be0bb924a10cde54f/s2_multimatch_10_sf12_j0/combined_plan.csv"

for i in {1..5}; do
    RUN_ID="${SCENARIO}_${BACKEND}_rep${i}_$(date +%Y%m%d_%H%M%S)"
    
    # Start consumer in background
    python scripts/kafka_consumer.py \
        --run-id $RUN_ID \
        --out runs/$RUN_ID &
    
    # Start producer
    python scripts/kafka_producer.py \
        --run-id $RUN_ID \
        --plan-csv $PLAN \
        --out runs/$RUN_ID \
        --speedup 120 \
        --max-t-sim 600
    
    # Compute metrics
    python scripts/compute_tti.py \
        --run-id $RUN_ID \
        --in runs/$RUN_ID \
        --out runs/$RUN_ID
    
    # Clean up background processes
    wait
done

# Create run list
ls runs/${SCENARIO}_${BACKEND}_rep*_*/ | sed 's|runs/||' | sed 's|/||' > runs/_${SCENARIO}_${BACKEND}_latest_runs.txt
```

#### Using Runner Scripts

```bash
# S2 scenario runner
bash scripts/run_s2_blocks.sh

# Single trial runners
bash scripts/run_kafka_trial.sh \
    s2sf12_kafka_rep1_$(date +%Y%m%d_%H%M%S) \
    data/processed/replay_plans/.../combined_plan.csv \
    --speedup 120 \
    --max-t-sim 600

bash scripts/run_redis_trial.sh \
    s2sf12_redis_rep1_$(date +%Y%m%d_%H%M%S) \
    data/processed/replay_plans/.../combined_plan.csv \
    --speedup 120 \
    --max-t-sim 600
```

### S3-Specific Protocol

```bash
# S3 with corrections (Kafka)
python scripts/kafka_producer.py \
    --run-id s3_corrections_kafka_001 \
    --plan-csv data/processed/replay_plans/.../combined_plan.csv \
    --out runs/s3_corrections_kafka_001 \
    --s3-mode corrections \
    --corrections-every-k 50 \
    --correction-delay-s 2.0 \
    --speedup 120 \
    --max-t-sim 600

# S3 with corrections (Redis)
python scripts/redis_producer.py \
    --run-id s3_corrections_redis_001 \
    --plan-csv data/processed/replay_plans/.../combined_plan.csv \
    --out runs/s3_corrections_redis_001 \
    --s3-mode corrections \
    --corrections-every-k 50 \
    --correction-delay-s 2.0 \
    --speedup 120 \
    --max-t-sim 600

# Compute S3 metrics (when implemented)
python scripts/compute_s3_metrics.py
```

---

## 📈 Metrics Calculation

### Time-to-Insight (TTI)

#### Definition
> **Time-to-Insight** is the interval from when an event is scheduled to be emitted to when the analytic output is available.

```
TTI = t_analytics_available - t_emit_scheduled
```

Where:
- `t_emit_scheduled`: Planned emission time from replay plan (in simulation seconds)
- `t_analytics_available`: Time when consumer has processed the event and output is ready (in wall clock time, converted to simulation time)

#### Calculation Steps

1. **Producer Side**
   ```python
   # For each event in plan:
   t_emit_scheduled_s = plan_row['t_emit_offset_s']
   t_emit_actual_ns = now_ns()  # When actually emitted
   
   # Store in message envelope:
   message = {
       'event_id': event_id,
       'match_id': match_id,
       't_emit_scheduled_s': t_emit_scheduled_s,
       't_emit_actual_ns': t_emit_actual_ns,
       # ... other event data
   }
   ```

2. **Consumer Side**
   ```python
   # When message is received:
   t_recv_ns = now_ns()
   
   # Process event (simulate analytics)
   t_ready_ns = now_ns()
   
   # Calculate TTI
   tti_ns = t_ready_ns - (t_emit_scheduled_s * 1e9)
   tti_ms = tti_ns / 1e6
   ```

3. **Aggregation**
   ```python
   import numpy as np
   
   tti_values = [...]  # All TTI values for a run
   
   metrics = {
       'tti_p50_ms': float(np.percentile(tti_values, 50)),
       'tti_p95_ms': float(np.percentile(tti_values, 95)),
       'tti_p99_ms': float(np.percentile(tti_values, 99)),
       'tti_iqr_ms': float(np.percentile(tti_values, 75) - np.percentile(tti_values, 25)),
       'tti_mean_ms': float(np.mean(tti_values)),
       'tti_std_ms': float(np.std(tti_values)),
       'tti_min_ms': float(np.min(tti_values)),
       'tti_max_ms': float(np.max(tti_values)),
       'n_events': len(tti_values)
   }
   ```

### Missed-Window Rate

#### Definition
> **Missed-Window Rate** is the fraction of events for which the TTI exceeds a given actionability window W.

```
tti_miss_W = count(TTI > W) / count(TTI)
```

#### Calculation
```python
actionability_windows_ms = [100, 250, 500, 1000]

missed_rates = {}
for W in actionability_windows_ms:
    missed_count = sum(1 for tti in tti_values if tti > W)
    missed_rate = missed_count / len(tti_values) if tti_values else 0.0
    missed_rates[f'tti_miss_{W}ms'] = missed_rate
```

### Latency Decomposition

#### Transport Latency
> Time for message to travel from producer to consumer (excluding processing time)

```
transport_latency_ns = t_recv_ns - t_emit_actual_ns
transport_latency_ms = transport_latency_ns / 1e6
```

#### Scheduling Lag
> Difference between scheduled emission time and actual emission time

```
scheduling_lag_ns = t_emit_actual_ns - (t_emit_scheduled_s * 1e9)
scheduling_lag_ms = scheduling_lag_ns / 1e6
```

#### Verification
```
# Should be approximately equal (within measurement error)
tti_ms ≈ transport_latency_ms + scheduling_lag_ms
```

### S3 Metrics (State Staleness)

#### Correction Propagation Latency
> Time from when a correction is emitted to when the corrected state is available

```python
# For each correction event:
correction_latency_ns = t_state_corrected_ns - t_correction_emit_ns
correction_latency_ms = correction_latency_ns / 1e6
```

#### Inconsistency Duration
> Time window during which the state is stale/inconsistent

```python
# When correction is received:
t_inconsistent_start = t_correction_recv_ns

# When state is updated:
t_consistent_again = t_state_updated_ns

inconsistency_duration_ns = t_consistent_again - t_inconsistent_start
inconsistency_duration_ms = inconsistency_duration_ns / 1e6
```

#### State Staleness at Decision Time
> Age of data at the moment a decision is made

```python
# For each decision point:
staleness_ms = t_decision_ns - t_last_update_ns
```

---

## 📊 Statistical Analysis

### Descriptive Statistics

For each scenario/backend combination:

| Statistic | Formula | Purpose |
|-----------|---------|---------|
| Mean | Σx / n | Central tendency |
| Median (p50) | Middle value | Robust central tendency |
| p95 | 95th percentile | High-latency tail |
| p99 | 99th percentile | Extreme tail |
| IQR | p75 - p25 | Variability measure |
| Std Dev | σ | Dispersion |
| Min | Minimum value | Lower bound |
| Max | Maximum value | Upper bound |

### Comparative Statistics

#### Across-Run Variability

```python
# For N runs of the same scenario/backend:
tti_p50_values = [run1_p50, run2_p50, ..., runN_p50]

# Calculate IQR across runs
across_run_iqr = np.percentile(tti_p50_values, 75) - np.percentile(tti_p50_values, 25)

# Calculate mean and std across runs
across_run_mean = np.mean(tti_p50_values)
across_run_std = np.std(tti_p50_values)
```

#### Statistical Significance

```python
from scipy import stats

# Mann-Whitney U test (non-parametric, for independent samples)
# H0: Kafka and Redis have the same TTI distribution
# H1: Kafka and Redis have different TTI distributions

tti_kafka = [...]  # All TTI values from Kafka runs
tti_redis = [...]  # All TTI values from Redis runs

u_stat, p_value = stats.mannwhitneyu(tti_kafka, tti_redis, alternative='two-sided')

if p_value < 0.05:
    print("Significant difference (p < 0.05)")
else:
    print("No significant difference (p >= 0.05)")
```

#### Effect Size

```python
# Cliff's Delta (non-parametric effect size)
def cliff_delta(x, y):
    """Calculate Cliff's Delta effect size."""
    n = len(x) * len(y)
    greater = sum(a > b for a in x for b in y)
    less = sum(a < b for a in x for b in y)
    return (greater - less) / n

delta = cliff_delta(tti_kafka, tti_redis)
# Interpretation:
# |d| < 0.147: Negligible
# 0.147 ≤ |d| < 0.33: Small
# 0.33 ≤ |d| < 0.474: Medium
# |d| ≥ 0.474: Large
```

### Confidence Intervals

```python
# Bootstrap confidence interval for median TTI
def bootstrap_ci(data, n_bootstraps=1000, ci=95):
    """Calculate bootstrap confidence interval for median."""
    bootstrapped_medians = []
    for _ in range(n_bootstraps):
        sample = np.random.choice(data, size=len(data), replace=True)
        bootstrapped_medians.append(np.median(sample))
    
    lower = np.percentile(bootstrapped_medians, (100 - ci) / 2)
    upper = np.percentile(bootstrapped_medians, 100 - (100 - ci) / 2)
    return lower, upper

lower, upper = bootstrap_ci(tti_values, ci=95)
print(f"95% CI for median TTI: [{lower:.3f}, {upper:.3f}] ms")
```

---

## 🔬 Reproducibility Protocol

### The No-Guessing Principle

**Rule:** Every number in the paper must trace to a committed artifact generated from committed code.

#### Chain of Custody
```
Paper Number
  ↓ (cited in manuscript)
CSV Cell (row, column)
  ↓ (from committed file)
Committed CSV File
  ↓ (generated by)
Build Script
  ↓ (processed)
Source Run(s)
  ↓ (listed in)
Canonical Run List
  ↓ (executed with)
Code Revision (git commit)
  ↓ (environment)
Environment Snapshot
```

### Reproduction Steps

1. **Clone Repository**
   ```bash
   git clone https://github.com/[your-org]/streaming-latency-sports.git
   cd streaming-latency-sports
   ```

2. **Checkout Specific Commit**
   ```bash
   # For S2 results:
   git checkout paper-s2-freeze-final
   
   # For latest development:
   git checkout feat/s3-state-staleness-corrections
   ```

3. **Setup Environment**
   ```bash
   # Create virtual environment
   python -m venv .venv
   source .venv/bin/activate
   
   # Install exact dependencies from snapshot
   pip install $(cat docs/results/paper_env_snapshot.txt | grep -E '^[a-zA-Z]' | head -20)
   ```

4. **Start Services**
   ```bash
   docker compose up -d
   ```

5. **Rebuild Paper Outputs**
   ```bash
   # For S2:
   bash scripts/build_paper_s2_outputs.sh
   
   # For S3 (when ready):
   bash scripts/build_paper_s3_outputs.sh
   ```

6. **Verify Outputs**
   ```bash
   # Check S2 outputs
   md5sum data/processed/results/paper_s2_official.csv
   md5sum docs/results/paper_s2_*_summary.csv
   
   # Compare with committed versions
   git show HEAD:data/processed/results/paper_s2_official.csv > /tmp/expected.csv
   diff /tmp/expected.csv data/processed/results/paper_s2_official.csv
   ```

### Environment Snapshot

Captured at freeze time in `docs/results/paper_env_snapshot.txt`:

```
=== GIT ===
a3f5g7d8e9c0b1a2d3e4f567890abcdef1234567

=== PYTHON ===
Python 3.9.13

=== PIP FREEZE ===
kafka-python==2.0.2
redis==4.3.4
pandas==1.5.3
numpy==1.24.2
...

=== DOCKER ===
Docker version 20.10.21
Docker Compose version v2.16.0

=== OS/WSL ===
Linux-5.15.90.1-microsoft-standard-WSL2-x86_64-with-glibc2.31
```

---

## ✅ Quality Assurance

### Validation Checks

#### Pre-Run Validation
```bash
# Validate replay plan
python - <<'PY'
import pandas as pd

plan = pd.read_csv("data/processed/replay_plans/.../combined_plan.csv")

# Check required columns
required_cols = ['t_emit_offset_s', 'match_id', 'event_id']
missing = [c for c in required_cols if c not in plan.columns]
if missing:
    print(f"MISSING COLUMNS: {missing}")
    exit(1)

# Check for NaN in critical columns
nan_cols = plan[required_cols].isna().any()
if nan_cols.any():
    print(f"NaN VALUES: {nan_cols[nan_cols].index.tolist()}")
    exit(1)

# Check event count
expected_count = 40660  # For 10-match plan
actual_count = len(plan)
if actual_count != expected_count:
    print(f"WARNING: Expected {expected_count} events, got {actual_count}")

print("✓ Replay plan validation passed")
PY
```

#### Post-Run Validation
```bash
# Validate run outputs
python - <<'PY'
import json
from pathlib import Path

run_id = "s2sf12_kafka_rep1_20251230_232006"
run_dir = Path("runs") / run_id

# Check required files
required_files = ['meta.json', 'tti_summary.json']
# For S3: also 'consumer_events.csv'

for f in required_files:
    if not (run_dir / f).exists():
        print(f"MISSING: {f}")
        exit(1)

# Validate meta.json
meta = json.loads((run_dir / 'meta.json').read_text())
required_meta = ['run_id', 'backend', 'scenario', 'git', 'timestamp']
missing_meta = [k for k in required_meta if k not in meta]
if missing_meta:
    print(f"MISSING METADATA: {missing_meta}")
    exit(1)

# Validate tti_summary.json
tti = json.loads((run_dir / 'tti_summary.json').read_text())
required_tti = ['tti_p50_ms', 'tti_p95_ms', 'tti_p99_ms', 'n_events']
missing_tti = [k for k in required_tti if k not in tti]
if missing_tti:
    print(f"MISSING TTI METRICS: {missing_tti}")
    exit(1)

print("✓ Run outputs validation passed")
PY
```

#### Cross-Run Consistency Check
```bash
# Compare metrics across runs of same scenario
python - <<'PY'
import json
from pathlib import Path
import numpy as np

scenario = "s2sf12"
backend = "kafka"

# Get all runs for this scenario/backend
runs = [
    d.name for d in Path("runs").iterdir()
    if d.is_dir() and f"{scenario}_{backend}" in d.name
]

# Load TTI p50 values
tti_p50_values = []
for run_id in runs:
    tti_path = Path("runs") / run_id / "tti_summary.json"
    if tti_path.exists():
        tti = json.loads(tti_path.read_text())
        tti_p50_values.append(tti.get('tti_p50_ms'))

# Calculate coefficient of variation (CV)
mean_p50 = np.mean(tti_p50_values)
std_p50 = np.std(tti_p50_values)
cv = std_p50 / mean_p50 if mean_p50 > 0 else 0

print(f"TTI p50 CV: {cv:.2%}")
if cv > 0.1:  # More than 10% variation
    print("WARNING: High variation across runs")

# Calculate IQR
q75, q25 = np.percentile(tti_p50_values, [75, 25])
iqr = q75 - q25
print(f"TTI p50 IQR: {iqr:.3f} ms")
PY
```

### Sanity Checks

#### TTI Bounds Check
```python
# TTI should be:
# - >= 0 (can't have negative latency)
# - Reasonable upper bound (e.g., < 10 seconds for S2)

invalid_tti = [t for t in tti_values if t < 0 or t > 10000]
if invalid_tti:
    print(f"INVALID TTI VALUES: {invalid_tti}")
    # Investigate: timing issues, clock synchronization, etc.
```

#### Transport Latency Check
```python
# Transport latency should be:
# - >= 0
# - Typically < 100ms for localhost
# - Consistent across events

transport_latencies = [...]  # All transport latency values
mean_transport = np.mean(transport_latencies)

if mean_transport > 50:  # More than 50ms average
    print(f"WARNING: High transport latency: {mean_transport:.2f} ms")
    # Check: network issues, broker overload, etc.
```

#### Scheduling Lag Check
```python
# Scheduling lag should be:
# - Small (typically < 1ms for 120x speedup)
# - Consistent (low variance)

sched_lags = [...]  # All scheduling lag values
mean_lag = np.mean(sched_lags)
std_lag = np.std(sched_lags)

if mean_lag > 10:  # More than 10ms
    print(f"WARNING: High scheduling lag: {mean_lag:.2f} ms")
```

---

## 🤝 Ethical Considerations

### Data Usage

1. **Dataset License Compliance**
   - StatsBomb data: CC BY-NC-4.0 license
   - Non-commercial research use only
   - Proper attribution required

2. **Data Privacy**
   - StatsBomb data is publicly available
   - No personal/identifiable information processed
   - Event data is anonymized by StatsBomb

3. **Reproducibility Ethics**
   - All results are fully reproducible
   - No cherry-picking of results
   - All runs documented and versioned

### Research Integrity

1. **No Data Fabrication**
   - All data comes from real StatsBomb events
   - No synthetic data generation (except for corrections in S3)

2. **No Result Manipulation**
   - All computations are automated
   - No manual adjustment of results
   - All code is open and auditable

3. **Full Disclosure**
   - All methodology documented
   - All code available
   - All configuration specified

### Conflict of Interest

- No financial or personal relationships with streaming system vendors
- No sponsorship from Kafka or Redis vendors
- Independent research conducted at [Your Institution]

---

## 📞 Support

For questions about methodology:
- Open a GitHub issue
- Email: [your-email@example.com]
- Reference: [Cite this methodology document]

---

*Last updated: June 9, 2026*  
*Document version: 0.3.0-s3-scaffolding*  
*Project: Streaming Latency Benchmarks*
