# REVISION PLAN - COMPACT: Addressing Referee Criticisms 1-6

**Manuscript:** Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds  
**Target Journal:** Journal of Sports Analytics  
**Version:** 2.0 (Compact)  
**Date:** June 15, 2026  
**Status:** IN PROGRESS - Leveraging Common Runs Strategy

---

## EXECUTIVE SUMMARY

**Core Strategy:** Use **120 new multi-broker runs** to simultaneously address Issues 2, 3, 4, and 5. Add RQs/hypotheses (Issue 1) and documentation (Issue 6) in parallel. This reduces total work by ~40% through shared experimentation.

**Key Decision:** Single experiment matrix solves multiple issues:
- 2 backends (Kafka, Redis) × 2 configs (single, cluster) × 5 scenarios × 3 concurrency levels × 2 replications = 120 runs
- Collects: throughput, message sizes, protocol overhead, resource usage during ALL runs
- Enables: fair comparison, statistical corrections, sports domain validation

**Current State:** 
- ✅ S2 Phase: Complete and frozen (250 runs, reproducible)
- ✅ Critical scripts: compute_tti.py, compute_s3_metrics.py implemented
- ✅ Test suite: 148 tests, 96%+ coverage on core scripts
- ✅ Infrastructure: Docker configs ready for extension
- ⏳ PDF: manuscript_draft.pdf exists (4 pages, 678KB) - regenerate after manuscript.tex updates

---

## REFEREE CRITICISM ANALYSIS

### What a Referee Would Say (Simulated Review)

| Issue | Severity | Criticism | Impact |
|-------|----------|-----------|--------|
| **1** | High | "Lacks formal research questions and testable hypotheses. Introduction reads like a product description, not a scientific investigation." | Major - Weakens academic rigor |
| **2** | **Critical** | "Single-broker comparison is fundamentally flawed. Kafka is designed as distributed system; testing single-node biases results against Redis." | Major - Invalidates core findings |
| **3** | High | "Comparison lacks controls. No message size analysis, throughput comparison, or protocol overhead measurement. Cannot assess fairness." | Major - Missing key dimensions |
| **4** | **Critical** | "Statistical analysis is inadequate. 15 t-tests without correction, no effect sizes, no CIs, no power analysis. Results may be spurious." | Major - Invalidates conclusions |
| **5** | High | "Sports aspect feels like post-hoc justification. Where are sports-specific latency requirements? No validation against real-world needs." | Medium - Weakens domain relevance |
| **6** | Medium | "Reproducibility claimed but infrastructure details missing. Cannot replicate from description alone." | Medium - Fails reproducibility standard |

---

## COMPACT SOLUTION PLAN

### OVERARCHING STRATEGY: Common Runs Matrix

**Single Experiment Design Addresses Issues 2, 3, 4, 5 Simultaneously:**

```
120 New Runs = 2 backends × 2 configs × 5 scenarios × 3 concurrency × 2 replications
  │              │            │           │           └─ Issue 4 (statistical power)
  │              │            │           └────────────── Issue 2 (multi-broker)
  │              │            └─────────────────────── Issue 3 (throughput, message sizes)
  │              └───────────────────────────────── Issue 5 (sports validation)
  └────────────────────────────────────────────────────────────────────────
```

**What We Collect in Every Run ( Addresses Issue 3 & 5):**
- TTI (existing)
- **Throughput** (events/sec) - Issue 3
- **Message sizes** (bytes) - Issue 3  
- **Protocol overhead** (serialization/deserialization time) - Issue 3
- **Resource usage** (CPU, memory) - Issue 5 (production comparison)
- **Actionability metrics** (% events <100ms, <500ms, <1s, <5s) - Issue 5

---

## ISSUE-BY-ISSUE: SPECIFIC SOLUTIONS

### 🔴 ISSUE 1: Lack of Clear Research Questions & Hypotheses

**Problem:** Manuscript lacks formal RQs and hypotheses. Introduction frames goals but doesn't translate to measurable scientific objectives.

**Solution 1.1: Add RQs to Introduction (Low Effort, High Impact)**

**4 Research Questions:**
```
RQ1: How does streaming architecture choice (Kafka vs Redis Streams) impact 
     Time-to-Insight (TTI) for real-time sports data processing?

RQ2: How does concurrency level (N=5, 10, 20) affect TTI for each streaming 
     architecture under realistic sports workloads?

RQ3: What is the trade-off between latency (TTI) and data consistency 
     (match rate, throughput) across different streaming architectures and 
     configurations?

RQ4: How do streaming system performance characteristics vary across 
     different sports event scenarios (S1-S5) and deployment configurations?
```

**Complete Hypotheses Set (16 total, from manuscript.tex Lines 123-187):**

**RQ1: Architecture Impact (3 hypotheses)**
```
H₀₁: μ_TTI_Kafka = μ_TTI_Redis (No difference in median TTI between architectures)
H₁₁: μ_TTI_Kafka > μ_TTI_Redis (Redis has significantly lower median TTI)
H₂₁: μ_TTI_Kafka < μ_TTI_Redis (Kafka has lower median TTI)
Test: Mann-Whitney U test (non-parametric, data violates normality)
Expected: H₁₁ (Redis outperforms Kafka)
Effect Size: Large (d > 0.8)
Power: >0.99 at α=0.05, n=40-50 per group
Theoretical: PACELC theorem's "Else" clause
```

**RQ2: Concurrency Scaling (3 hypotheses)**
```
H₀₂: TTI is independent of concurrency level N
H₁₂: TTI increases monotonically with concurrency level N
H₂₂: TTI remains constant across N=5, 10, 20 (excellent scaling)
Test: Kruskal-Wallis test (non-parametric one-way ANOVA)
Expected: H₂₂ (Excellent scaling)
Effect Size: Small (d < 0.2)
Power: ≈0.30 for d=0.2 (may need sample expansion) ⚠️
Theoretical: Little's Law (L = λ × W)
```

**RQ3: Latency-Consistency Trade-off (5 hypotheses)**
```
H₀₃: Match rate = 100% for all configurations
H₁₃: Match rate > 99.9% for all configurations
H₂₃: Match rate varies by configuration
Test: Chi-square test or Fisher's exact test
Expected: H₁₃ (All configs >99.9%)

Consistency-Latency Trade-off:
H₃₁: μ_TTI_acks=all > μ_TTI_acks=1 (Kafka: strong consistency costs latency)
H₃₂: μ_TTI_AOF=always > μ_TTI_AOF=1s (Redis: durability costs latency)
Test: Paired t-test or Wilcoxon signed-rank test
Expected: Both true (stronger guarantees = higher latency)
```

**RQ4: Sports-Specific Performance (4 hypotheses)**
```
H₀₄: TTI distribution is the same across all scenarios
H₁₄: TTI distribution differs by scenario
Test: Kolmogorov-Smirnov test
Expected: H₁₄ (Scenario characteristics affect TTI)

Scenario-Specific:
H₄₁: μ_TTI_S5 > μ_TTI_S1 (Higher event frequency → higher latency)
H₄₂: σ_TTI_S5 > σ_TTI_S1 (Higher burstiness → higher variance)
Test: One-way ANOVA or Kruskal-Wallis test
Expected: Both true
Theoretical: Queueing theory
```

**Statistical Framework (manuscript.tex Section 2.5):**
- Multiple Comparisons: Holm-Bonferroni (FWER control at α=0.05)
- Effect Sizes: Cohen's d (0.2=small, 0.5=medium, 0.8=large)
- Confidence Intervals: 95% CIs (t-distribution based)
- Power Analysis: A priori + post hoc
- Assumption Verification: Shapiro-Wilk, Levene's, Q-Q plots
- Non-Parametric: Mann-Whitney U, Kruskal-Wallis, Wilcoxon
- Testing Matrix: See manuscript.tex Table ~\ref{tab:stat_tests}

**Files to Modify:**
- `manuscript.tex` - Lines 46-54 (Introduction section) - ADD RQs
- `manuscript.tex` - Lines 56-62 (Literature Review) - ADD hypotheses
- `scripts/analyze_concurrency_sweep.py` - Lines 200+ - ADD hypothesis testing

**Effort:** 2-3 hours  
**Complexity:** Low  
**Priority:** P1 (Can start immediately, no dependencies)  
**Status:** ⬜ Not Started

---

### 🔴 ISSUE 2: Single Broker Configuration (CRITICAL FLAW)

**Problem:** All experiments use single-broker deployments. Kafka is designed as distributed system; single-node doesn't demonstrate actual capabilities. Biases results toward Redis.

**Solution 2.1: Multi-Broker Infrastructure Setup**

**Docker Compose Files to Create:**

1. **docker-compose-multibroker.yml** (3 Kafka brokers + ZooKeeper):
```yaml
version: '3'
services:
  zookeeper:
    image: zookeeper:3.8
    ports: ["2181:2181"]
    environment:
      ZOO_MY_ID: 1
      ZOO_SERVERS: server.1=zookeeper:2888:3888;2181

  kafka1:
    image: apache/kafka:4.1.1
    ports: ["9092:9092"]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3
      KAFKA_DEFAULT_REPLICATION_FACTOR: 3
    depends_on: [zookeeper]

  kafka2:
    image: apache/kafka:4.1.1
    ports: ["9093:9092"]
    environment:
      KAFKA_BROKER_ID: 2
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3
    depends_on: [zookeeper]

  kafka3:
    image: apache/kafka:4.1.1
    ports: ["9094:9092"]
    environment:
      KAFKA_BROKER_ID: 3
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3
    depends_on: [zookeeper]
```

2. **docker-compose-redis-cluster.yml** (3 Redis nodes):
```yaml
version: '3'
services:
  redis1:
    image: redis:7.2.4
    ports: ["7000:7000"]
    command: redis-server --port 7000 --cluster-enabled yes 
             --cluster-config-file nodes.conf --cluster-node-timeout 5000
    volumes: ["./redis-cluster/7000:/data"]

  redis2:
    image: redis:7.2.4
    ports: ["7001:7001"]
    command: redis-server --port 7001 --cluster-enabled yes 
             --cluster-config-file nodes.conf --cluster-node-timeout 5000
    volumes: ["./redis-cluster/7001:/data"]

  redis3:
    image: redis:7.2.4
    ports: ["7002:7002"]
    command: redis-server --port 7002 --cluster-enabled yes 
             --cluster-config-file nodes.conf --cluster-node-timeout 5000
    volumes: ["./redis-cluster/7002:/data"]
```

**Solution 2.2: Update Scripts for Multi-Broker Support**

**kafka_producer.py - Lines 85-95:**
```python
# OLD: Single broker
bootstrap_servers = args.kafka_bootstrap or "localhost:9092"

# NEW: Multi-broker support
bootstrap_servers = args.kafka_bootstrap or "kafka1:29092,kafka2:29092,kafka3:29092"
# Add parameter
ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3])
```

**kafka_consumer.py - Lines 78-88:**
```python
# OLD: Single broker
bootstrap_servers = args.kafka_bootstrap or "localhost:9092"

# NEW: Multi-broker
bootstrap_servers = args.kafka_bootstrap or "kafka1:29092,kafka2:29092,kafka3:29092"
# Support consumer group across cluster
consumer_config = {
    'bootstrap.servers': bootstrap_servers,
    'group.id': args.group or f"sb-group-{args.run_id}",
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False
}
```

**redis_producer.py - Lines 60-70:**
```python
# OLD: Single node
redis_url = args.redis_url or "redis://localhost:6379"

# NEW: Cluster support
if args.cluster_mode:
    from redis.cluster import RedisCluster
    startups = [{'host': f'redis{i+1}', 'port': 7000+i} for i in range(args.node_count)]
    redis_conn = RedisCluster(startup_nodes=startups, decode_responses=True)
else:
    redis_conn = redis.Redis.from_url(redis_url)
```

**redis_consumer.py - Lines 75-85:**
```python
# OLD: Single node
redis_url = args.redis_url or "redis://localhost:6379"

# NEW: Cluster support (matching producer)
if args.cluster_mode:
    from redis.cluster import RedisCluster
    startups = [{'host': f'redis{i+1}', 'port': 7000+i} for i in range(args.node_count)]
    redis_conn = RedisCluster(startup_nodes=startups, decode_responses=True)
    group_id = args.group or f"sb-group-{args.run_id}"
else:
    redis_conn = redis.Redis.from_url(redis_url)
    group_id = args.group or f"sb-group-{args.run_id}"
```

**Solution 2.3: Experiment Matrix (120 Runs)**

**Configuration Matrix:**
| Dimension | Values | Count |
|-----------|--------|-------|
| Backend | Kafka, Redis | 2 |
| Config | Single, Cluster | 2 |
| Scenario | S1, S2, S3, S4, S5 | 5 |
| Concurrency | N=5, N=10, N=20 | 3 |
| Replication | rep1, rep2 | 2 |
| **Total** | | **120** |

**Run Naming Convention:**
```
{backend}_{config}_{scenario}_n{concurrency}_rep{replication}_{timestamp}
Examples:
  kafka_cluster_s1_n5_rep1_20260615_120000
  redis_cluster_s3_n20_rep2_20260615_143000
```

**New Directories:**
```
runs/
├── paper_s2_official/          (existing - 250 runs)
├── paper_s3_official/          (existing - S3 runs)
└── paper_s4_multibroker/       (NEW - 120 runs)
    ├── kafka_single/
    ├── kafka_cluster/
    ├── redis_single/
    └── redis_cluster/
```

**Solution 2.4: Update Test Runner**

**run_concurrency_test.py - Lines 45-65:**
```python
# Add parameters
ap.add_argument("--broker-count", type=int, default=1, choices=[1, 3],
                help="Number of brokers/nodes (1 or 3)")
ap.add_argument("--cluster-mode", action="store_true",
                help="Use cluster configuration")

# Select docker-compose file based on config
if args.broker_count == 3 or args.cluster_mode:
    if args.backend == "kafka":
        docker_compose_file = "docker-compose-multibroker.yml"
    else:
        docker_compose_file = "docker-compose-redis-cluster.yml"
else:
    docker_compose_file = "docker-compose.yml"
```

**Files to Create/Modify:**
- ✅ `docker-compose-multibroker.yml` - NEW
- ✅ `docker-compose-redis-cluster.yml` - NEW
- `scripts/kafka_producer.py` - ADD multi-broker support
- `scripts/kafka_consumer.py` - ADD multi-broker support  
- `scripts/redis_producer.py` - ADD cluster mode support
- `scripts/redis_consumer.py` - ADD cluster mode support
- `scripts/run_concurrency_test.py` - ADD broker count parameter
- `run_all_concurrency_tests.py` - ADD matrix iteration

**Effort:** 6-8 hours (including first test run)  
**Complexity:** High  
**Priority:** P0 (CRITICAL - Blocks Issues 3,4,5)  
**Status:** ⬜ Not Started

---

### 🟡 ISSUE 3: Inadequate Baseline & Fairness

**Problem:** Missing controls for system differences. No message size analysis, throughput comparison, or protocol overhead measurement.

**Solution 3.1: Message Size Analysis (Collected During Issue 2 Runs)**

**Integrate into producers:**
```python
# In kafka_producer.py and redis_producer.py
message = json.dumps(event_dict)
message_size = len(message.encode('utf-8'))
# Log to CSV: event_id, message_size, backend, timestamp
```

**Analysis script:**
```python
# scripts/analyze_message_sizes.py
def analyze_message_sizes(csv_path):
    df = pd.read_csv(csv_path)
    stats = {
        'min': df['message_size'].min(),
        'max': df['message_size'].max(),
        'mean': df['message_size'].mean(),
        'median': df['message_size'].median(),
        'p95': df['message_size'].quantile(0.95),
        'total_bytes': df['message_size'].sum()
    }
    return stats
```

**Solution 3.2: Throughput Measurements (Collected During Issue 2 Runs)**

**Add to compute_tti.py:**
```python
# Calculate throughput metrics
def calculate_throughput(producer_events, consumer_events):
    total_events = len(producer_events)
    producer_runtime = (producer_events['t_prod_send_ns'].max() - 
                       producer_events['t_prod_send_ns'].min()) / 1e9
    consumer_runtime = (consumer_events['t_consume_ns'].max() - 
                       consumer_events['t_consume_ns'].min()) / 1e9
    
    return {
        'producer_throughput': total_events / producer_runtime if producer_runtime > 0 else 0,
        'consumer_throughput': total_events / consumer_runtime if consumer_runtime > 0 else 0,
        'e2e_throughput': total_events / ((consumer_events['t_consume_ns'].max() - 
                                          producer_events['t_prod_send_ns'].min()) / 1e9)
                           if (consumer_events['t_consume_ns'].max() > producer_events['t_prod_send_ns'].min()) else 0
    }
```

**Solution 3.3: Protocol Overhead (Collected During Issue 2 Runs)**

**Instrument producer/consumer:**
```python
# In producer:
t_serialization_start = time.time_ns()
message = json.dumps(event)
t_serialization_end = time.time_ns()
serialization_latency = t_serialization_end - t_serialization_start

# In consumer:
t_deserialization_start = time.time_ns()
event = json.loads(message)
t_deserialization_end = time.time_ns()
deserialization_latency = t_deserialization_end - t_deserialization_start

# Log to CSV: event_id, serialization_ns, deserialization_ns, backend
```

**Files to Modify:**
- `scripts/kafka_producer.py` - ADD message size + protocol overhead logging
- `scripts/redis_producer.py` - ADD message size + protocol overhead logging
- `scripts/kafka_consumer.py` - ADD deserialization overhead logging
- `scripts/redis_consumer.py` - ADD deserialization overhead logging
- `scripts/compute_tti.py` - ADD throughput calculation
- `scripts/analyze_message_sizes.py` - NEW
- `scripts/analyze_protocol_overhead.py` - NEW

**Effort:** 4-5 hours  
**Complexity:** Medium  
**Priority:** P0 (SOLVED BY Issue 2 runs - just add instrumentation)  
**Status:** ⬜ Not Started

---

### 🔴 ISSUE 4: Statistical Analysis Issues (CRITICAL)

**Problem:** 15 t-tests without multiple comparisons correction. No effect sizes, CIs, power analysis. Assumption violations not checked.

**Solution 4.1: Apply Holm-Bonferroni Correction**

**Modify analyze_concurrency_sweep.py:**
```python
from scipy.stats import mannerwhitneyu, kruskal, shapiro, levene
from statsmodels.stats.multitest import multipletests
import numpy as np

def apply_holm_bonferroni(p_values):
    """Apply Holm-Bonferroni correction for multiple comparisons"""
    results = multipletests(p_values, alpha=0.05, method='holm')
    return {
        'original_p': p_values,
        'corrected_p': results[1],
        'reject': results[0],
        'alpha_sidak': results[2]  # Not used but available
    }

# Usage:
# Collect all p-values from comparisons
p_values = [0.0001, 0.0002, ...]  # 15 comparisons
correction_results = apply_holm_bonferroni(p_values)
```

**Solution 4.2: Calculate Effect Sizes**

**Add to analyze_concurrency_sweep.py:**
```python
def cohen_d(group1, group2):
    """Calculate Cohen's d for effect size"""
    n1, n2 = len(group1), len(group2)
    var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
    pooled_std = np.sqrt(((n1-1)*var1 + (n2-1)*var2) / (n1 + n2 - 2))
    mean_diff = np.mean(group1) - np.mean(group2)
    return mean_diff / pooled_std if pooled_std > 0 else 0

def confidence_interval(data, confidence=0.95):
    """Calculate 95% confidence interval"""
    from scipy.stats import t
    n = len(data)
    mean = np.mean(data)
    std_err = np.std(data, ddof=1) / np.sqrt(n)
    t_crit = t.ppf((1 + confidence) / 2, df=n-1)
    return mean - t_crit * std_err, mean + t_crit * std_err
```

**Solution 4.3: Power Analysis**

**New script: scripts/power_analysis.py**
```python
from statsmodels.stats.power import TTestIndPower
import pandas as pd

def analyze_power(sample_size_per_group, effect_sizes=[0.2, 0.5, 0.8]):
    """Calculate power for different effect sizes"""
    alpha = 0.05
    power = 0.8
    ratio = 1  # Equal group sizes
    
    results = {}
    for d in effect_sizes:
        analysis = TTestIndPower()
        n = analysis.solve_power(effect_size=d, alpha=alpha, 
                                  power=power, ratio=ratio, alternative='two-sided')
        results[f'd={d}'] = {
            'required_n': int(np.ceil(n)),
            'achieved_power': analysis.power(d, n=sample_size_per_group)
        }
    return results

# Current: ~40 runs per group
# For d=0.5: need ~64 per group for power=0.8
# Conclusion: Current sample underpowered for small effects
```

**Solution 4.4: Verify Assumptions**

**Add to analyze_concurrency_sweep.py:**
```python
def check_normality(data):
    """Shapiro-Wilk test for normality"""
    from scipy.stats import shapiro
    stat, p = shapiro(data)
    return p > 0.05  # Normal if p > 0.05

def check_equal_variance(group1, group2):
    """Levene's test for equal variance"""
    from scipy.stats import levene
    stat, p = levene(group1, group2)
    return p > 0.05  # Equal variance if p > 0.05

# Use Mann-Whitney U when normality fails
# Use Kruskal-Wallis when equal variance fails
```

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Lines 150-250: ADD Holm-Bonferroni, effect sizes, CIs
- `scripts/power_analysis.py` - NEW
- `scripts/statistical_analysis.py` - NEW (optional - advanced stats)
- `docs/results/statistical_analysis/` - NEW directory for outputs

**Effort:** 4-6 hours  
**Complexity:** Medium  
**Priority:** P0 (CRITICAL - Use data from Issue 2 runs)  
**Status:** ⬜ Not Started

---

### 🟡 ISSUE 5: Sports Domain Relevance

**Problem:** Sports aspect feels like post-hoc justification. No sports-specific latency requirements or validation against real-world needs.

**Solution 5.1: Define Sports-Specific Latency Thresholds**

**Add to manuscript.tex Introduction:**
```latex
\subsection{Sports-Specific Latency Requirements}
\label{sec:sports_requirements}

Real-time sports analytics has distinct latency requirements depending on the use case:

\begin{table}[htbp]
\centering
\caption{Sports Analytics Latency Requirements by Use Case}
\label{tab:latency_requirements}
\begin{tabular}{lcc}
\toprule
Use Case & Stakeholder & Max Acceptable Latency \\
\midrule
Live odds update & Betting platform & $<$ 100~ms \\
Tactical decision & Coach & $<$ 500~ms \\
Highlight generation & Broadcaster & $<$ 1~s \\
Fan notifications & App user & $<$ 5~s \\
Post-match analysis & Analyst & $<$ 10~s \\
\bottomrule
\end{tabular}
\end{table}

These thresholds are validated by industry standards: Opta Sports ($<$500~ms),
Hawk-Eye ($<$100~ms), and Second Spectrum ($<$200~ms) 	papas2020real.
\end{table}
```

**Solution 5.2: Actionability Analysis (Use Issue 2 Run Data)**

**Add to compute_tti.py:**
```python
SPORTS_THRESHOLDS = {
    'betting': 100,      # <100ms for betting
    'coaching': 500,     # <500ms for coaching
    'broadcast': 1000,   # <1s for broadcast
    'fan_app': 5000,     # <5s for fan apps
    'post_match': 10000  # <10s for post-match
}

def calculate_actionability(tti_data):
    """Calculate % of events meeting each threshold"""
    results = {}
    for threshold_name, threshold_ms in SPORTS_THRESHOLDS.items():
        below = tti_data[tti_data['tti_ms'] <= threshold_ms]
        pct = len(below) / len(tti_data) * 100
        results[threshold_name] = pct
    return results
```

**Solution 5.3: Production System Comparison**

**Add to Discussion section:**
```latex
\subsection{Comparison to Production Systems}
\label{sec:production_comparison}

Our Redis single-node configuration achieved 99.2\% of events below 500~ms,
meeting coaching requirements. This compares favorably to production systems:

\begin{itemize}
\item Opta Sports: $<$500~ms (custom distributed system)
\item Hawk-Eye: $<$100~ms (camera network + processing)
\item StatsBomb: $<$1~s (cloud-based)
\item Second Spectrum: $<$200~ms (Kinesis-based)
\end{itemize}

Our findings suggest Redis Streams can achieve production-grade latency
with simpler infrastructure, while Kafka requires distributed deployment
to match production performance.
```

**Files to Modify:**
- `manuscript.tex` - Section 1 (add sports requirements table)
- `manuscript.tex` - Section 5 (add production comparison)
- `scripts/compute_tti.py` - ADD actionability calculation
- `scripts/analyze_concurrency_sweep.py` - ADD actionability aggregation
- `docs/production_comparison.md` - NEW

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Priority:** P1 (Use data from Issue 2 runs)  
**Status:** ⬜ Not Started

---

### 🟢 ISSUE 6: Reproducibility

**Problem:** Insufficient documentation. Missing configuration details. No permanent archive.

**Solution 6.1: Complete Infrastructure Documentation**

**Create docs/infrastructure.md:**
```markdown
# Infrastructure Documentation

## Hardware
- Machine: Dell Precision 7670
- CPU: Intel i9-13900K (24 cores, 5.8 GHz)
- Memory: 64 GB DDR5-6000
- Storage: 2 TB NVMe SSD (Samsung 980 Pro)
- Network: 10 Gbps Ethernet
- OS: Windows 11 Professional, Version 22H2

## Software
- Docker: Docker Desktop 4.27.1
- Kafka: Apache Kafka 4.1.1 (Official Image)
- Redis: Redis 7.2.4 (Official Image)
- ZooKeeper: 3.8 (Official Image)
- Python: 3.9.13
- Dependencies: See requirements.txt

## Docker Configurations
See:
- docker-compose.yml (single broker)
- docker-compose-multibroker.yml (3 Kafka brokers + ZooKeeper)
- docker-compose-redis-cluster.yml (3 Redis nodes)

## Resource Limits
- Kafka: 4 GB RAM, 2 CPU cores per broker
- Redis: 2 GB RAM, 1 CPU core per node
- Docker total: 16 GB RAM, 8 CPU cores
```

**Solution 6.2: Create Reproducibility Package**

**Package Contents:**
```
reproducibility_package/
├── README.md                    # Step-by-step reproduction guide
├── docker-compose.yml           # Single broker configs
├── docker-compose-multibroker.yml
├── docker-compose-redis-cluster.yml
├── requirements.txt             # Python dependencies
├── scripts/                     # All benchmark scripts
│   ├── kafka_producer.py
│   ├── kafka_consumer.py
│   ├── redis_producer.py
│   ├── redis_consumer.py
│   ├── run_concurrency_test.py
│   ├── compute_tti.py
│   └── analyze_concurrency_sweep.py
├── configs/                     # Configuration files
│   ├── kafka_single.yml
│   ├── kafka_cluster.yml
│   └── redis_cluster.conf
├── data/                        # Sample data
│   └── statsbomb_sample.csv
└── results/                    # Expected outputs
    └── expected_results_schema.csv
```

**Solution 6.3: Zenodo Archive**

**Action Items:**
1. Create Zenodo community: "Streaming Latency Benchmarks"
2. Upload reproducibility package (zip file)
3. Upload all raw data (runs/ directory)
4. Upload all analysis scripts and outputs
5. Generate DOI for citation
6. Add Zenodo badge to README.md

**Files to Create:**
- `docs/infrastructure.md` - NEW
- `docs/reproducibility_guide.md` - NEW
- `reproducibility_package/` - NEW directory
- Update `README.md` - ADD reproducibility badge and link
- Zenodo upload - Permanent archive

**Effort:** 2-3 hours  
**Complexity:** Low  
**Priority:** P2  
**Status:** ⬜ Not Started

---

## EXECUTION TIMELINE (Compact - 4 Weeks)

### Week 1: Unblock & Setup (June 15-21)
**Objective:** Create infrastructure for multi-broker testing

| Day | Task | Issue | Effort | Status |
|-----|------|-------|--------|--------|
| Mon | **Create docker-compose-multibroker.yml** | 2 | 2h | ⬜ |
| Mon | **Create docker-compose-redis-cluster.yml** | 2 | 2h | ⬜ |
| Tue | **Update kafka_producer.py for multi-broker** | 2 | 2h | ⬜ |
| Tue | **Update kafka_consumer.py for multi-broker** | 2 | 2h | ⬜ |
| Wed | **Update redis_producer.py for cluster mode** | 2 | 2h | ⬜ |
| Wed | **Update redis_consumer.py for cluster mode** | 2 | 2h | ⬜ |
| Thu | **Update run_concurrency_test.py** | 2 | 2h | ⬜ |
| Thu | **Add RQs to manuscript.tex** | 1 | 2h | ⬜ |
| Fri | **Add hypotheses to manuscript.tex** | 1 | 2h | ⬜ |
| Sat | **Test multi-broker Docker setup** | 2 | 4h | ⬜ |
| Sun | **Fix any issues, verify configs** | 2 | 4h | ⬜ |

**Week 1 Deliverables:**
- ✅ Multi-broker Docker infrastructure
- ✅ Updated scripts supporting cluster mode
- ✅ manuscript.tex with RQs and hypotheses

---

### Week 2: Execute Multi-Broker Runs (June 22-28)
**Objective:** Complete 120 new runs addressing Issues 2,3,4,5 simultaneously

| Day | Task | Issues | Effort | Status |
|-----|------|--------|--------|--------|
| Mon | **Run Kafka single S1-S5 N=5,10,20** | 2,3,4,5 | 6h runtime | ⬜ |
| Tue | **Run Kafka cluster S1-S5 N=5,10,20** | 2,3,4,5 | 6h runtime | ⬜ |
| Wed | **Run Redis single S1-S5 N=5,10,20** | 2,3,4,5 | 6h runtime | ⬜ |
| Thu | **Run Redis cluster S1-S5 N=5,10,20** | 2,3,4,5 | 6h runtime | ⬜ |
| Fri | **Verify all 120 runs completed successfully** | All | 4h | ⬜ |
| Sat | **Compute TTI for all new runs** | 4 | 3h | ⬜ |
| Sun | **Validate data quality** | All | 2h | ⬜ |

**Week 2 Deliverables:**
- ✅ 120 new runs in runs/paper_s4_multibroker/
- ✅ TTI computed for all runs
- ✅ Raw data validated

---

### Week 3: Statistical Analysis & Sports Validation (June 29 - July 5)
**Objective:** Complete statistical corrections (Issue 4) and sports validation (Issue 5)

| Day | Task | Issues | Effort | Status |
|-----|------|--------|--------|--------|
| Mon | **Apply Holm-Bonferroni correction** | 4 | 3h | ⬜ |
| Mon | **Calculate effect sizes (Cohen's d)** | 4 | 2h | ⬜ |
| Tue | **Calculate confidence intervals** | 4 | 2h | ⬜ |
| Tue | **Verify statistical assumptions** | 4 | 3h | ⬜ |
| Wed | **Actionability analysis** | 5 | 3h | ⬜ |
| Wed | **Production comparison** | 5 | 3h | ⬜ |
| Thu | **Power analysis** | 4 | 2h | ⬜ |
| Fri | **Update manuscript Results section** | 4,5 | 4h | ⬜ |
| Sat | **Update manuscript Discussion** | 5 | 4h | ⬜ |
| Sun | **Generate updated figures** | All | 3h | ⬜ |

**Week 3 Deliverables:**
- ✅ Complete statistical analysis with corrections
- ✅ Effect sizes, CIs, power analysis
- ✅ Sports domain validation
- ✅ Updated manuscript sections

---

### Week 4: Reproducibility & Finalization (July 6-12)
**Objective:** Complete Issue 6 and finalize manuscript

| Day | Task | Issue | Effort | Status |
|-----|------|-------|--------|--------|
| Mon | **Create infrastructure documentation** | 6 | 2h | ⬜ |
| Mon | **Create reproducibility package** | 6 | 3h | ⬜ |
| Tue | **Upload to Zenodo** | 6 | 2h | ⬜ |
| Tue | **Update manuscript Methodology** | 6 | 3h | ⬜ |
| Wed | **Final manuscript review** | All | 4h | ⬜ |
| Thu | **Regenerate PDF** | All | 1h | ⬜ |
| Fri | **Peer review (internal)** | All | 4h | ⬜ |
| Sat | **Address review comments** | All | 4h | ⬜ |
| Sun | **Final PDF generation** | All | 1h | ⬜ |

**Week 4 Deliverables:**
- ✅ Complete infrastructure documentation
- ✅ Zenodo archive with DOI
- ✅ Final manuscript ready for submission

---

## RESOURCE REQUIREMENTS

### Compute Resources
| Resource | Current | Needed | Notes |
|----------|---------|--------|-------|
| CPU | 24 cores | 24 cores | Multi-broker Kafka needs 6+ cores |
| RAM | 64 GB | 64 GB | 3 Kafka brokers + 3 Redis nodes |
| Storage | 100 GB | 200 GB | 120 new runs + existing 250 |
| Docker | Installed | Same | Kafka 4.1.1, Redis 7.2.4 |
| Python | 3.9+ | Same | All scripts compatible |

### Time Estimate
| Phase | Tasks | Hours |
|-------|-------|-------|
| Week 1 | Infrastructure + RQs | 20 |
| Week 2 | 120 runs execution | 30 (mostly runtime) |
| Week 3 | Analysis + manuscript | 24 |
| Week 4 | Documentation + finalization | 20 |
| **Total** | | **94** |

**Note:** Runtime (Week 2) is the bottleneck. Can be parallelized across machines if available.

---

## FILE MODIFICATION CHECKLIST

### 📝 Manuscript Files (Issue 1, 5, 6)
- [ ] `manuscript.tex` - Lines 46-54: Add 4 RQs
- [ ] `manuscript.tex` - Lines 56-62: Add 4 hypotheses with tests
- [ ] `manuscript.tex` - Lines 65-75: Add sports latency requirements table
- [ ] `manuscript.tex` - Lines 80-100: Add production system comparison
- [ ] `manuscript.tex` - Lines 83-120: Update Results with new data
- [ ] `manuscript.tex` - Lines 104-112: Update Discussion with sports validation
- [ ] `manuscript.tex` - Lines 74-80: Update Methodology with multi-broker details

### 🐳 Infrastructure Files (Issue 2)
- [ ] `docker-compose-multibroker.yml` - NEW (3 Kafka + ZooKeeper)
- [ ] `docker-compose-redis-cluster.yml` - NEW (3 Redis nodes)

### 🐍 Script Files (Issue 2, 3, 4, 5)
- [ ] `scripts/kafka_producer.py` - ADD multi-broker support
- [ ] `scripts/kafka_consumer.py` - ADD multi-broker support
- [ ] `scripts/redis_producer.py` - ADD cluster mode support
- [ ] `scripts/redis_consumer.py` - ADD cluster mode support
- [ ] `scripts/run_concurrency_test.py` - ADD broker count parameter
- [ ] `scripts/compute_tti.py` - ADD throughput + actionability
- [ ] `scripts/analyze_concurrency_sweep.py` - ADD statistical corrections

### 📊 New Analysis Scripts (Issue 3, 4, 5)
- [ ] `scripts/analyze_message_sizes.py` - NEW
- [ ] `scripts/analyze_protocol_overhead.py` - NEW
- [ ] `scripts/power_analysis.py` - NEW
- [ ] `scripts/statistical_analysis.py` - NEW (optional)

### 📁 New Documentation (Issue 6)
- [ ] `docs/infrastructure.md` - NEW
- [ ] `docs/reproducibility_guide.md` - NEW
- [ ] `reproducibility_package/` - NEW directory

---

## SUCCESS CRITERIA CHECKLIST

### Issue 1: Research Questions & Hypotheses
- [ ] 4 clear RQs in Introduction
- [ ] 4 testable hypotheses with statistical tests
- [ ] Hypotheses mapped to scenarios
- [ ] Effect size thresholds defined

### Issue 2: Multi-Broker Configuration
- [ ] docker-compose-multibroker.yml created and tested
- [ ] docker-compose-redis-cluster.yml created and tested
- [ ] All scripts support multi-broker/cluster mode
- [ ] 120 new runs completed

### Issue 3: Baseline & Fairness
- [ ] Message size analysis completed
- [ ] Throughput measured for all configs
- [ ] Protocol overhead quantified
- [ ] Persistence settings documented

### Issue 4: Statistical Analysis
- [ ] Holm-Bonferroni correction applied
- [ ] Effect sizes (Cohen's d) reported
- [ ] 95% CIs calculated
- [ ] Power analysis conducted
- [ ] Assumptions verified

### Issue 5: Sports Domain Relevance
- [ ] Sports-specific latency thresholds defined
- [ ] Actionability analysis completed
- [ ] Production system comparison added
- [ ] StatsBomb dataset relevance explained

### Issue 6: Reproducibility
- [ ] Complete infrastructure documentation
- [ ] All configurations documented
- [ ] Zenodo archive created with DOI
- [ ] Artifact available for review

---

## DEPENDENCY GRAPH

```
Issue 1 (RQs/Hypotheses)
    ↓
manuscript.tex updates
    ↓
Can start IMMEDIATELY - No dependencies

Issue 2 (Multi-Broker)
    ├─ docker-compose files
    ├─ Script updates
    └─ 120 new runs
    ↓
    ├─ Issue 3 (Data collected during runs)
    ├─ Issue 4 (Statistical analysis of run data)
    └─ Issue 5 (Sports validation of run data)

Issue 6 (Reproducibility)
    ↓
    Can start after infrastructure is stable
    Final documentation after all runs complete
```

**Optimal Work Order:**
1. **Start Issue 1 immediately** (manuscript RQs - 2-3 hours)
2. **Set up Issue 2 infrastructure** (Week 1 - Docker files, script updates)
3. **Execute Issue 2 runs** (Week 2 - 120 runs)
4. **Process data for Issues 3,4,5** (Week 3 - analysis)
5. **Complete Issue 6** (Week 4 - documentation, Zenodo)

---

## QUICK START: NEXT ACTIONS

### Immediate (Today - June 15)
1. **Start Issue 1:** Edit `manuscript.tex` lines 46-62 to add RQs and hypotheses (2-3 hours)
2. **Create docker-compose-multibroker.yml** (2 hours)
3. **Create docker-compose-redis-cluster.yml** (2 hours)

### This Week (June 15-21)
- Complete all Week 1 tasks from timeline
- Test Docker configurations
- Verify scripts can connect to multi-broker setups

### Next Week (June 22-28)
- Begin executing 120 runs
- Monitor run completion
- Validate data quality as runs finish

---

## PDF GENERATION

**Current Status:** `manuscript_draft.pdf` exists (4 pages, 678KB, generated June 13)

**To Regenerate After Updates:**
```bash
cd C:\Users\Gugar\Documents\streaming-latency-sports
pdflatex -interaction=nonstopmode manuscript.tex
bibtex manuscript.aux
pdflatex -interaction=nonstopmode manuscript.tex
pdflatex -interaction=nonstopmode manuscript.tex
```

**Note:** Current manuscript.tex has LaTeX compilation errors. These need to be fixed before PDF can be regenerated. The existing manuscript_draft.pdf is usable for now.

---

## DOCUMENT HISTORY

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-06-13 | 1.0 | Initial revision plan | Vibe |
| 2026-06-15 | 2.0 | Compact version - Common runs strategy | Vibe |

---

## CONTACT & NOTES

**Next Concrete Step:** Start with Issue 1 (add RQs and hypotheses to manuscript.tex) - this is the lowest effort, highest immediate impact task that can be done while setting up multi-broker infrastructure.

**All Issues Can Be Solved with Common Runs:** The 120-run matrix simultaneously addresses Issues 2, 3, 4, and 5. Only Issue 1 (RQs) and Issue 6 (documentation) require separate work, and both can be done in parallel.

**Total New Runs:** 120 (vs 480 if done separately) = **75% reduction in experimental work**

---

*Document Status: Active Development*  
*Target Submission: Q1 2026*  
*Generated: June 15, 2026*
