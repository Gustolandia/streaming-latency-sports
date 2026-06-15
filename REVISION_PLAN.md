# 📋 Revision Plan: Addressing Referee Criticisms

**Manuscript:** Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds  
**Target Journal:** Journal of Sports Analytics  
**Current Status:** Major Revisions Required  
**Document Version:** 1.0  
**Last Updated:** June 13, 2026  
**Owner:** Research Team

---

## 📌 Executive Summary

This document outlines a **comprehensive, actionable plan** to address all **6 major criticisms** from the referee report. Each issue is analyzed with:
- **Problem Statement** (what the referee flagged)
- **Root Cause** (why it exists)
- **Practical Solutions** (concrete steps to fix)
- **Success Criteria** (how we know it's solved)
- **Resources Required** (what we need)
- **Estimated Effort** (time/complexity)
- **Status** (Not Started / In Progress / Completed)

---

## 🎯 Issue Priority Matrix

| Issue | Severity | Effort | Impact | Priority |
|-------|----------|--------|--------|----------|
| 2. Single Broker Limitation | Critical | High | High | **P0** |
| 4. Statistical Analysis Issues | Critical | Medium | High | **P0** |
| 1. Research Questions & Hypotheses | High | Low | High | **P1** |
| 3. Baseline & Fairness | High | Medium | High | **P1** |
| 5. Sports Domain Relevance | High | Medium | High | **P1** |
| 6. Reproducibility | Medium | Medium | Medium | **P2** |

---

## 📝 Issue-by-Issue Breakdown

---

## 🔴 ISSUE 1: Lack of Clear Research Questions & Hypotheses

### Problem Statement
The referee flagged that the manuscript **lacks formal research questions and testable hypotheses**. The introduction frames general goals but doesn't translate them into measurable, scientific research objectives.

### Root Cause
- Initial focus was on "building the benchmark suite" rather than "answering specific research questions"
- Sports domain connection was added as justification rather than driving the research design
- No formal hypothesis testing framework established

### Success Criteria
✅ Clear research questions (RQ1-RQ4) stated in Introduction  
✅ Testable hypotheses (H₀, H₁, H₂, H₃₁-H₃₂, H₄₁-H₄₂) for all comparisons  
✅ Hypotheses linked to specific scenarios (S1-S5) and configurations  
✅ All hypotheses include: direction, variables, measurement method, and test type  
✅ Statistical framework defined: Holm-Bonferroni, effect sizes, CIs, power analysis  
✅ Expected outcomes and theoretical context specified for each hypothesis  

### Practical Solutions

#### Solution 1.1: Define Core Research Questions

**Action Items:**
- [ ] Draft 3-5 core research questions in Introduction section
- [ ] Each RQ must follow the pattern: "How does [X] affect [Y] under [conditions]?"
- [ ] Map each RQ to specific scenarios (S1-S5)
- [ ] Ensure all RQs are answerable with the collected data

**Proposed Research Questions:**
```
RQ1: How does streaming architecture choice (Kafka vs Redis Streams) 
     impact Time-to-Insight (TTI) for real-time sports data processing?
     
RQ2: How does concurrency level (N=5, 10, 20) affect TTI for each 
     streaming architecture under realistic sports workloads?
     
RQ3: What is the trade-off between latency (TTI) and data consistency 
     (match rate) across different streaming architectures?
     
RQ4: How do streaming system performance characteristics vary across 
     different sports event scenarios (S1-S5)?
```

**Files to Modify:**
- `manuscript.tex` - Section 1 (Introduction)
- `MANUSCRIPT_SUMMARY.md` - Update with RQs

**Effort:** 2-4 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

#### Solution 1.2: Formulate Testable Hypotheses

**Action Items:**
- [ ] For each RQ, define null hypothesis (H₀), alternative hypotheses (H₁, H₂), and consistency trade-off hypotheses
- [ ] Specify statistical test for each hypothesis
- [ ] Define effect size thresholds for "practical significance"
- [ ] Map hypotheses to specific tables/figures in Results section
- [ ] Document expected effect sizes and power for each hypothesis

**Proposed Hypotheses (Complete Set from manuscript.tex):**

**RQ1: Architecture Impact**
```
H₀₁: μ_TTI_Kafka = μ_TTI_Redis (No difference in median TTI between architectures)
H₁₁: μ_TTI_Kafka > μ_TTI_Redis (Redis has significantly lower median TTI)
H₂₁: μ_TTI_Kafka < μ_TTI_Redis (Kafka has lower median TTI)
Test: Mann-Whitney U test (non-parametric, data violates normality)
Expected: H₁₁ (Redis significantly outperforms Kafka on TTI)
Effect Size: Large (Cohen's d > 0.8 based on S2 data)
Power: >0.99 at α=0.05 with current sample size (40-50 runs per group)
Theoretical: Tests PACELC theorem's "Else" clause
```

**RQ2: Concurrency Scaling**
```
H₀₂: TTI is independent of concurrency level N
H₁₂: TTI increases monotonically with concurrency level N
H₂₂: TTI remains constant across N=5, 10, 20 (excellent scaling)
Test: Kruskal-Wallis test (non-parametric one-way ANOVA)
Expected: H₂₂ (Excellent scaling with constant TTI)
Effect Size: Small (d < 0.2 expected)
Power: ≈0.30 for detecting d=0.2 (sample size may need expansion) ⚠️
Theoretical: Little's Law (L = λ × W)
```

**RQ3: Latency-Consistency Trade-off**
```
H₀₃: Match rate = 100% for all configurations
H₁₃: Match rate > 99.9% for all configurations
H₂₃: Match rate varies by configuration
Test: Chi-square test or Fisher's exact test
Expected: H₁₃ (All configurations achieve >99.9% match rate)

Additionally, consistency-latency trade-off hypotheses:
H₃₁: μ_TTI_acks=all > μ_TTI_acks=1 (Kafka: strong consistency costs latency)
H₃₂: μ_TTI_AOF=always > μ_TTI_AOF=1s (Redis: durability costs latency)
Test: Paired t-test or Wilcoxon signed-rank test
Expected: Both true (stronger guarantees = higher latency)
```

**RQ4: Sports-Specific Performance**
```
H₀₄: TTI distribution is the same across all scenarios
H₁₄: TTI distribution differs by scenario
Test: Kolmogorov-Smirnov test
Expected: H₁₄ (TTI differs by scenario)

Additionally, scenario-specific hypotheses:
H₄₁: μ_TTI_S5 > μ_TTI_S1 (Higher event frequency → higher latency)
H₄₂: σ_TTI_S5 > σ_TTI_S1 (Higher burstiness → higher variance)
Test: One-way ANOVA or Kruskal-Wallis test
Expected: Both true (scenario characteristics affect performance)
Theoretical: Queueing theory
```

**Statistical Framework (matches manuscript.tex Section 2.5):**
- Multiple Comparisons: Holm-Bonferroni correction (controls FWER at α=0.05)
- Effect Sizes: Cohen's d (interpretation: 0.2=small, 0.5=medium, 0.8=large)
- Confidence Intervals: 95% CIs for all mean differences (t-distribution based)
- Power Analysis: A priori and post hoc (current n=40-50 detects d=0.58 at power=0.8)
- Assumption Verification: Shapiro-Wilk (normality), Levene's/F-test (equal variance), Q-Q plots
- Non-Parametric: Mann-Whitney U, Kruskal-Wallis, Wilcoxon signed-rank as alternatives
- Testing Matrix: See manuscript.tex Table ~\ref{tab:stat_tests}

**Statistical Power Considerations:**
- Current sample: 250 runs total (S2 phase)
- Per group (e.g., Kafka S1): ~40-50 runs
- **RQ1 (H₁₁):** Power >0.99 for d > 0.8 (Excellent)
- **RQ2 (H₂₂):** Power ≈0.30 for d=0.2 (May need sample expansion)
- **RQ3 (H₁₃):** Power >0.99 for match rate >99.9% (Excellent)
- **RQ4 (H₁₄, H₄₁, H₄₂):** Power >0.80 with current sample (Good)
- **Action:** Verify sufficient power for all hypotheses, add runs if needed for small effects

**Files to Modify:**
- `manuscript.tex` - Section 1 (Introduction)
- `scripts/analyze_concurrency_sweep.py` - Add hypothesis testing code

**Effort:** 3-5 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

### Resources Required
- Access to methodology documentation
- Statistical software (Python/R)
- Research design expertise

### Estimated Timeline
- **Week 1:** Define RQs and hypotheses (2 days)
- **Week 1:** Integrate into manuscript (1 day)

---

---

## 🔴 ISSUE 2: Methodological Limitations - Single Broker Configuration

### Problem Statement
**CRITICAL FLAW:** All experiments use **single-broker deployments** for both Kafka and Redis. This is not a fair comparison because:
- Kafka is designed as a **distributed** system
- Single-broker Kafka does not demonstrate its actual capabilities
- Biases results toward Redis (which performs well in single-node configs)

### Root Cause
- Initial focus on quick benchmarking rather than rigorous comparison
- Resource constraints (single machine testing)
- Docker compose configured for single instances

### Success Criteria
✅ Multi-broker Kafka tests (minimum 3 brokers) completed  
✅ Redis cluster configuration tested  
✅ Fair comparison between distributed Kafka and single-node Redis  
✅ Results show performance across different configurations  
✅ Discussion addresses configuration limitations

### Practical Solutions

#### Solution 2.1: Set Up Multi-Broker Kafka Cluster

**Action Items:**
- [ ] Modify `docker-compose.yml` to include 3 Kafka brokers
- [ ] Configure Kafka with proper replication factor (RF=3)
- [ ] Set up appropriate `acks` settings (test both acks=1 and acks=all)
- [ ] Verify cluster health before running experiments
- [ ] Document broker configuration parameters

**Docker Compose Modification:**
```yaml
version: '3'
services:
  kafka1:
    image: apache/kafka:4.1.1
    hostname: kafka1
    ports:
      - "9092:9092"
    environment:
      - KAFKA_BROKER_ID=1
      - KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT
      - KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka1:29092,PLAINTEXT_HOST://localhost:9092
      - KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181
      - KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=3
      - KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=3
      - KAFKA_TRANSACTION_STATE_LOG_MIN_ISR=2
      - KAFKA_DEFAULT_REPLICATION_FACTOR=3
      - KAFKA_UNCLEAN_LEADER_ELECTION_ENABLE=false
    depends_on:
      - zookeeper

  kafka2:
    image: apache/kafka:4.1.1
    hostname: kafka2
    ports:
      - "9093:9092"
    environment:
      - KAFKA_BROKER_ID=2
      - KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT
      - KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka2:29092,PLAINTEXT_HOST://localhost:9093
      - KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181
      - KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=3
      - KAFKA_DEFAULT_REPLICATION_FACTOR=3
    depends_on:
      - zookeeper

  kafka3:
    image: apache/kafka:4.1.1
    hostname: kafka3
    ports:
      - "9094:9092"
    environment:
      - KAFKA_BROKER_ID=3
      - KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=PLAINTEXT:PLAINTEXT
      - KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka3:29092,PLAINTEXT_HOST://localhost:9094
      - KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181
      - KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=3
      - KAFKA_DEFAULT_REPLICATION_FACTOR=3
    depends_on:
      - zookeeper

  zookeeper:
    image: zookeeper:3.8
    hostname: zookeeper
    ports:
      - "2181:2181"
    environment:
      - ZOO_MY_ID=1
      - ZOO_SERVERS=server.1=zookeeper:2888:3888;2181
```

**Configuration Parameters to Document:**
| Parameter | Kafka (Single) | Kafka (3-broker) | Redis (Single) | Redis (Cluster) |
|-----------|----------------|------------------|-----------------|------------------|
| Replication | N/A | RF=3 | N/A | 3 nodes |
| Persistence | Disk | Disk | AOF+RDB | AOF+RDB |
| acks | 1 | 1, all | N/A | N/A |
| Min ISR | N/A | 2 | N/A | N/A |

**Files to Modify:**
- `docker-compose.yml` - Add multi-broker Kafka
- `docker-compose-multibroker.yml` - New file for multi-broker config
- `scripts/kafka_producer.py` - Update to support multiple brokers
- `scripts/kafka_consumer.py` - Update to support multiple brokers

**Effort:** 4-6 hours  
**Complexity:** High  
**Status:** ⬜ Not Started

---

#### Solution 2.2: Set Up Redis Cluster

**Action Items:**
- [ ] Configure Redis cluster with 3 nodes
- [ ] Test Redis Streams in cluster mode
- [ ] Compare single-node vs cluster performance
- [ ] Document cluster configuration

**Redis Cluster Configuration:**
```bash
# Start 3 Redis instances
redis-server --port 7000 --cluster-enabled yes --cluster-config-file nodes-7000.conf
redis-server --port 7001 --cluster-enabled yes --cluster-config-file nodes-7001.conf
redis-server --port 7002 --cluster-enabled yes --cluster-config-file nodes-7002.conf

# Create cluster
redis-cli --cluster create 127.0.0.1:7000 127.0.0.1:7001 127.0.0.1:7002 \
  --cluster-replicas 0
```

**Note:** Redis Streams in cluster mode has different characteristics than single-node. Need to test both.

**Files to Modify:**
- `docker-compose-redis-cluster.yml` - New file
- `scripts/redis_producer.py` - Support cluster mode
- `scripts/redis_consumer.py` - Support cluster mode

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 2.3: Design Fair Comparison Experiment

**Experimental Design Matrix:**

| Configuration | Kafka (1 broker) | Kafka (3 brokers) | Redis (1 node) | Redis (3 nodes) |
|---------------|-----------------|-------------------|----------------|------------------|
| S1 (Baseline) | ✅ Already done | ⬜ To do | ✅ Already done | ⬜ To do |
| S2 (Full) | ✅ Already done | ⬜ To do | ✅ Already done | ⬜ To do |
| S3 (Staleness) | ✅ Already done | ⬜ To do | ✅ Already done | ⬜ To do |
| Concurrency N=5 | ✅ Already done | ⬜ To do | ✅ Already done | ⬜ To do |
| Concurrency N=10 | ✅ Already done | ⬜ To do | ✅ Already done | ⬜ To do |
| Concurrency N=20 | ⚠️ Partial | ⬜ To do | ⚠️ Partial | ⬜ To do |

**Action Items:**
- [ ] Run full matrix of experiments (12 new configurations)
- [ ] Ensure same hardware resources for all tests
- [ ] Use identical replay plans for each configuration
- [ ] Run sufficient replications (minimum 10 per config)
- [ ] Document all configuration parameters

**Total New Runs Required:**
- 12 configurations × 10 replications = **120 new runs**
- Current: 250 runs
- Total after: **370 runs**

**Files to Modify:**
- `run_all_concurrency_tests.py` - Add multi-broker support
- `scripts/run_concurrency_test.py` - Parameterize broker count
- New run directories for multi-broker tests

**Effort:** 6-8 hours (including execution time)  
**Complexity:** High  
**Status:** ⬜ Not Started

---

#### Solution 2.4: Analyze Configuration Impact

**Action Items:**
- [ ] Compare single vs multi-broker results
- [ ] Analyze overhead of replication
- [ ] Measure network latency impact
- [ ] Document scalability characteristics

**New Analysis Metrics:**
- **Replication overhead:** TTI difference between RF=1 and RF=3
- **Network hops:** Count of network round-trips per message
- **Cluster coordination time:** Time spent on ZooKeeper operations (Kafka)
- **Redirection overhead:** Redis cluster slot redirection time

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add configuration comparison
- `docs/results/concurrency_analysis/` - New analysis directory

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

### Resources Required
- Docker with sufficient resources (16+ GB RAM for 3 Kafka brokers + Redis cluster)
- Time to execute 120+ new runs (estimated 2-3 hours)
- Access to modify Docker configurations

### Estimated Timeline
- **Week 1:** Set up multi-broker Kafka (2 days)
- **Week 1:** Set up Redis cluster (1 day)
- **Week 2:** Execute full experiment matrix (2 days including runtime)
- **Week 2:** Analyze configuration impact (1 day)

---

---

## 🔴 ISSUE 3: Inadequate Baseline & Fairness of Comparison

### Problem Statement
The referee noted that the comparison **lacks controls for fundamental system differences**:
- No message size analysis
- No throughput comparison
- Different protocol overheads not analyzed
- No persistence/durability settings comparison

### Root Cause
- Focus on latency (TTI) as primary metric
- Missing key streaming system dimensions
- No baseline measurements of system capabilities

### Success Criteria
✅ Message size distribution analyzed  
✅ Throughput (events/sec) measured for all configurations  
✅ Protocol overhead quantified  
✅ Persistence settings documented and compared  
✅ Baseline system capabilities established

### Practical Solutions

#### Solution 3.1: Measure Message Size Distribution

**Action Items:**
- [ ] Analyze actual message sizes in StatsBomb dataset
- [ ] Report min, max, mean, median message sizes
- [ ] Test with different message size bins (<1KB, 1-10KB, 10-100KB)
- [ ] Document message format and payload structure

**Message Size Analysis:**
```python
# Pseudocode for message size analysis
def analyze_message_sizes(plan_csv):
    sizes = []
    for event in plan_csv:
        # Calculate approximate message size
        message = json.dumps(event.to_dict())
        sizes.append(len(message.encode('utf-8')))
    
    stats = {
        'min': min(sizes),
        'max': max(sizes),
        'mean': np.mean(sizes),
        'median': np.median(sizes),
        'p95': np.percentile(sizes, 95)
    }
    return stats
```

**Expected Message Sizes:**
- StatsBomb events: ~500-2000 bytes per event
- Need to verify and document

**Files to Modify:**
- `scripts/analyze_message_sizes.py` - New script
- `docs/results/message_size_analysis/` - New directory

**Effort:** 2-3 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

#### Solution 3.2: Add Throughput Measurements

**Action Items:**
- [ ] Measure events/second for producer
- [ ] Measure events/second for consumer
- [ ] Calculate end-to-end throughput
- [ ] Report throughput alongside TTI in all tables

**Throughput Metrics to Add:**
```
Producer Throughput = Total Events / Producer Runtime
Consumer Throughput = Total Events / Consumer Runtime
End-to-End Throughput = Total Events / (Consumer Finish - Producer Start)
```

**Files to Modify:**
- `scripts/compute_tti.py` - Add throughput calculation
- `scripts/generate_manuscript_analysis.py` - Include throughput in outputs
- All results tables - Add throughput columns

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 3.3: Quantify Protocol Overhead

**Action Items:**
- [ ] Measure protocol-level latency components
- [ ] Compare Kafka binary protocol vs Redis RESP protocol
- [ ] Document serialization/deserialization times
- [ ] Analyze network packet sizes

**Protocol Overhead Breakdown:**
```
Total Latency = Protocol Overhead + Network Latency + Processing Latency

Where:
- Protocol Overhead = Serialization + Deserialization + Framing
- Network Latency = Time on the wire
- Processing Latency = Broker processing time
```

**Measurement Approach:**
1. Instrument producer and consumer to timestamp each stage
2. Calculate time spent in serialization (before send)
3. Calculate time spent in deserialization (after receive)
4. Estimate network latency (if separated containers)

**Files to Modify:**
- `scripts/kafka_producer.py` - Add instrumentation
- `scripts/redis_producer.py` - Add instrumentation
- `scripts/kafka_consumer.py` - Add instrumentation
- `scripts/redis_consumer.py` - Add instrumentation

**Effort:** 4-5 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 3.4: Document and Compare Persistence Settings

**Action Items:**
- [ ] Document Kafka persistence settings (log.flush, etc.)
- [ ] Document Redis persistence settings (AOF, RDB)
- [ ] Test with different durability levels
- [ ] Compare impact on TTI

**Persistence Configurations to Test:**

**Kafka:**
- `acks=0` (Fire and forget) - Fastest, no durability
- `acks=1` (Leader ack) - Default, moderate durability
- `acks=all` (Full ISR ack) - Slowest, full durability

**Redis:**
- No persistence - Fastest, no durability
- RDB only - Periodic snapshots
- AOF every second - Moderate durability
- AOF always - Full durability, slowest

**Files to Modify:**
- `configs/kafka_*.yml` - Different persistence configs
- `configs/redis_*.conf` - Different persistence configs
- `run_all_concurrency_tests.py` - Parameterize persistence settings

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 3.5: Establish Baseline System Capabilities

**Action Items:**
- [ ] Run baseline tests without any streaming (null test)
- [ ] Measure system overhead (OS, Docker, Python)
- [ ] Document baseline latency distribution
- [ ] Establish theoretical minimum TTI

**Baseline Tests:**
1. **Null test:** Producer writes to file, consumer reads from file (no broker)
2. **Loopback test:** Producer sends to localhost, consumer receives (minimal network)
3. **Memory test:** In-process message passing (theoretical minimum)

**Expected Baseline Results:**
- Null test: ~0.1-1ms (file I/O)
- Loopback: ~0.01-0.1ms (local network)
- Memory: ~0.001-0.01ms (in-process)

**Files to Create:**
- `scripts/run_baseline_tests.py` - New script
- `docs/results/baseline/` - New directory

**Effort:** 2-3 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

### Resources Required
- Access to modify streaming configurations
- Time to execute additional test runs
- Storage for new results data

### Estimated Timeline
- **Week 2:** Message size analysis (1 day)
- **Week 2:** Throughput measurements (1 day)
- **Week 3:** Protocol overhead (2 days)
- **Week 3:** Persistence settings (1 day)
- **Week 3:** Baseline tests (1 day)

---

---

## 🔴 ISSUE 4: Statistical Analysis Issues

### Problem Statement
**CRITICAL:** The statistical analysis has **major flaws**:
- 15 t-tests without multiple comparisons correction
- No effect size reporting
- No confidence intervals
- No power analysis
- Assumption violations not checked

### Root Cause
- Lack of statistical expertise in initial analysis
- Focus on descriptive statistics over inferential
- No peer review of statistical methods

### Success Criteria
✅ Multiple comparisons correction applied (Bonferroni/Holm/BH)  
✅ Effect sizes reported for all significant findings  
✅ Confidence intervals for all mean differences  
✅ Power analysis conducted and documented  
✅ Statistical assumptions verified (normality, equal variance)  
✅ Non-parametric alternatives used where appropriate

### Practical Solutions

#### Solution 4.1: Apply Multiple Comparisons Correction

**Action Items:**
- [ ] Identify all hypothesis tests (currently 15: 5 scenarios × 3 percentiles)
- [ ] Apply **Bonferroni correction** (most conservative): α' = α / m = 0.05 / 15 = 0.0033
- [ ] Alternatively, apply **Holm-Bonferroni** (less conservative, more powerful)
- [ ] Alternatively, apply **Benjamini-Hochberg** (controls FDR, not FWER)
- [ ] Report both uncorrected and corrected p-values
- [ ] Mark which findings remain significant after correction

**Correction Methods Comparison:**

| Method | Controls | Assumptions | Power | Use Case |
|--------|----------|-------------|-------|----------|
| Bonferroni | FWER | None | Low | Strict control |
| Holm-Bonferroni | FWER | None | Medium | Step-down procedure |
| Benjamini-Hochberg | FDR | Independent tests | High | Discovery-focused |

**Recommendation:** Use **Holm-Bonferroni** for balance between control and power.

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add multiple comparisons correction
- `scripts/statistical_analysis.py` - New script for advanced stats
- All results tables - Report corrected p-values

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 4.2: Report Effect Sizes

**Action Items:**
- [ ] Calculate **Cohen's d** for all mean differences
- [ ] Calculate **eta-squared (η²)** for ANOVA comparisons
- [ ] Calculate **Hedges' g** (Cohen's d with small sample correction)
- [ ] Report effect sizes alongside p-values in all tables

**Effect Size Interpretation:**

| Cohen's d | Interpretation |
|-----------|----------------|
| 0.2 | Small |
| 0.5 | Medium |
| 0.8 | Large |

| η² | Interpretation |
|-----|----------------|
| 0.01 | Small |
| 0.06 | Medium |
| 0.14 | Large |

**Example Reporting:**
```
Redis showed significantly lower TTI than Kafka for S1 
(p = 0.0001, p_adj = 0.0005, Cohen's d = 1.23, 95% CI [0.89, 1.57])
```

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add effect size calculations
- `scripts/statistical_analysis.py` - Implement effect size functions
- All results tables - Add effect size columns

**Effort:** 2-3 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 4.3: Add Confidence Intervals

**Action Items:**
- [ ] Calculate 95% CIs for all mean differences
- [ ] Report CIs in tables and text
- [ ] Create forest plots showing effect sizes with CIs
- [ ] Verify CI calculation method (t-distribution for small samples)

**Confidence Interval Formula:**
```
CI = mean_diff ± t_critical * (std_error)
where std_error = sqrt((s1²/n1) + (s2²/n2))
t_critical = t-distribution quantile for df = n1 + n2 - 2
```

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add CI calculations
- `scripts/statistical_analysis.py` - Implement CI functions
- All results tables - Add CI columns

**Effort:** 2-3 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 4.4: Conduct Power Analysis

**Action Items:**
- [ ] Perform **a priori power analysis** for sample size justification
- [ ] Perform **post hoc power analysis** for achieved power
- [ ] Report power for all non-significant findings
- [ ] Document effect sizes detectable with current sample

**Power Analysis:**
```python
# Using statsmodels
from statsmodels.stats.power import TTestIndPower

# Parameters
alpha = 0.05
power = 0.8
effect_size = 0.5  # Medium effect
ratio = 1  # Equal group sizes

# Calculate required sample size
analysis = TTestIndPower()
n = analysis.solve_power(effect_size=effect_size, alpha=alpha, 
                          power=power, ratio=ratio, alternative='two-sided')
# Result: n ≈ 64 per group (total 128)

# Current sample: ~40 per group
# Conclusion: Underpowered for small effects (d < 0.5)
```

**Power Analysis Results:**
- Current n=40 per group can detect d=0.58 at α=0.05, power=0.8
- For d=0.5: power ≈ 0.72
- For d=0.4: power ≈ 0.54
- **Recommendation:** Add more runs to achieve n=64 per group

**Files to Create:**
- `scripts/power_analysis.py` - New script
- `docs/results/power_analysis/` - New directory

**Effort:** 2-3 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 4.5: Verify Statistical Assumptions

**Action Items:**
- [ ] Test **normality** of all distributions (Shapiro-Wilk test)
- [ ] Test **equal variance** (Levene's test, F-test)
- [ ] Create **Q-Q plots** for visual normality check
- [ ] Use **non-parametric tests** where assumptions violated
- [ ] Document all assumption tests and results

**Assumption Tests:**

```python
from scipy.stats import shapiro, levene
import matplotlib.pyplot as plt
import statsmodels.api as sm

# Normality test
def test_normality(data):
    stat, p = shapiro(data)
    return p > 0.05  # Normal if p > 0.05

# Equal variance test
def test_equal_variance(group1, group2):
    stat, p = levene(group1, group2)
    return p > 0.05  # Equal variance if p > 0.05

# Q-Q plot
def plot_qq(data, title):
    sm.qqplot(data, line='s')
    plt.title(title)
    plt.show()
```

**Non-Parametric Alternatives:**

| Parametric Test | Non-Parametric Alternative |
|-----------------|----------------------------|
| t-test | Mann-Whitney U |
| One-way ANOVA | Kruskal-Wallis |
| Paired t-test | Wilcoxon signed-rank |

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add assumption tests
- `scripts/statistical_analysis.py` - Implement assumption checking
- `docs/results/statistical_assumptions/` - New directory for test results

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

### Resources Required
- Statistical software (Python with scipy, statsmodels)
- Statistical expertise (or learning resources)
- Time to re-analyze all data

### Estimated Timeline
- **Week 4:** Multiple comparisons correction (1 day)
- **Week 4:** Effect sizes and CIs (1 day)
- **Week 4:** Power analysis (1 day)
- **Week 5:** Assumption verification and non-parametric tests (2 days)

---

---

## 🔴 ISSUE 5: Sports Domain Relevance

### Problem Statement
The referee stated: *"The 'sports' aspect feels like a post-hoc justification. The benchmarks could be for any domain. Where is the sports-specific insight?"*

### Root Cause
- Benchmarks designed as generic streaming tests
- Sports connection added as context rather than driving research
- No sports-specific metrics or requirements defined
- No validation against real sports analytics needs

### Success Criteria
✅ Clear connection between streaming latency and sports decision-making  
✅ Sports-specific latency thresholds defined and justified  
✅ Validation against real-world sports streaming requirements  
✅ Comparison to production sports analytics systems  
✅ StatsBomb dataset relevance properly explained

### Practical Solutions

#### Solution 5.1: Define Sports-Specific Latency Requirements

**Action Items:**
- [ ] Research and document **actionable latency thresholds** for different sports use cases
- [ ] Define **TTI categories** (real-time, near-real-time, batch)
- [ ] Map thresholds to specific sports stakeholders
- [ ] Justify thresholds with domain literature

**Sports Analytics Latency Requirements:**

| Use Case | Stakeholder | Max Acceptable Latency | Justification |
|----------|------------|------------------------|---------------|
| Live odds update | Betting platform | < 100ms | Real-time betting requires sub-second updates |
| Tactical decision | Coach | < 500ms | Time to react to game events |
| Highlight generation | Broadcaster | < 1s | Near-real-time for TV production |
| Post-match analysis | Analyst | < 10s | Batch processing acceptable |
| Fan notifications | App user | < 5s | Push notification delivery |

**Citation Targets:**
- Pappas et al. (2020) - Real-time football analytics requirements
- Opta Sports white papers
- Hawk-Eye technology specifications
- Sports broadcasting standards (EBU, SMPTE)

**Files to Modify:**
- `manuscript.tex` - Section 1 (Introduction)
- `docs/sports_requirements.md` - New document

**Effort:** 3-4 hours  
**Complexity:** Medium (requires domain research)  
**Status:** ⬜ Not Started

---

#### Solution 5.2: Validate Against Real-World Requirements

**Action Items:**
- [ ] Map benchmark results to sports latency requirements
- [ ] Calculate **percentage of events** meeting each threshold
- [ ] Create **actionability plots** showing % events below threshold
- [ ] Discuss **practical implications** for each use case

**Actionability Analysis:**
```python
def calculate_actionability(data, thresholds):
    """Calculate percentage of events meeting latency thresholds"""
    results = {}
    for threshold_name, threshold_ms in thresholds.items():
        below_threshold = data[data['tti_ms'] <= threshold_ms]
        pct = len(below_threshold) / len(data) * 100
        results[threshold_name] = pct
    return results

# Example thresholds
thresholds = {
    'betting': 100,      # <100ms for betting
    'coaching': 500,     # <500ms for coaching
    'broadcast': 1000,   # <1s for broadcast
    'fan_app': 5000,     # <5s for fan apps
    'post_match': 10000  # <10s for post-match
}
```

**Expected Results:**
- Redis: 99%+ events < 500ms (suitable for coaching)
- Kafka: X% events < 500ms (needs improvement for coaching)

**Files to Modify:**
- `scripts/analyze_concurrency_sweep.py` - Add actionability analysis
- `scripts/compute_tti.py` - Add threshold calculations
- `docs/results/actionability/` - New directory

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 5.3: Compare to Production Sports Systems

**Action Items:**
- [ ] Research **production sports streaming systems**
- [ ] Compare results to **industry benchmarks**
- [ ] Document **real-world deployment patterns**
- [ ] Discuss **how our findings apply to production**

**Production Systems to Research:**

| System | Organization | Known Latency | Architecture |
|--------|--------------|---------------|--------------|
| Opta | Opta Sports | < 500ms | Custom distributed |
| Hawk-Eye | Sony | < 100ms | Camera network + processing |
| StatsBomb | StatsBomb | < 1s | Cloud-based |
| Second Spectrum | AWS | < 200ms | Kinesis-based |
| Chyron | Chyron | < 100ms | On-premise |

**Comparison Framework:**
1. Document known latencies of production systems
2. Compare our benchmark results to these values
3. Discuss architectural differences
4. Identify gaps and opportunities

**Files to Create:**
- `docs/production_comparison.md` - New document
- `scripts/collect_production_data.py` - Data collection script

**Effort:** 4-5 hours  
**Complexity:** Medium (requires external research)  
**Status:** ⬜ Not Started

---

#### Solution 5.4: Explain StatsBomb Dataset Relevance

**Action Items:**
- [ ] Document **StatsBomb dataset characteristics**
- [ ] Explain **why it's representative** of real-time streaming
- [ ] Analyze **event frequency patterns**
- [ ] Compare to **other sports datasets**

**StatsBomb Dataset Analysis:**

```python
def analyze_statsbomb_patterns(plan_csv):
    """Analyze event patterns in StatsBomb data"""
    
    # Event frequency by time
    events_per_second = ...
    
    # Burst characteristics
    burst_size = ...
    inter_event_time = ...
    
    # Event type distribution
    event_types = ...
    
    return {
        'events_per_second': events_per_second,
        'burst_characteristics': burst_size,
        'event_type_distribution': event_types
    }
```

**Dataset Representativeness:**
- **Event frequency:** X events/second (typical for football)
- **Burst patterns:** Matches live play characteristics
- **Event types:** Covers all major football event types
- **Temporal distribution:** Realistic for live matches

**Files to Create:**
- `docs/dataset_analysis.md` - New document
- `scripts/analyze_dataset.py` - New script

**Effort:** 2-3 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

#### Solution 5.5: Strengthen Sports Domain Discussion

**Action Items:**
- [ ] Add **sports-specific discussion** section
- [ ] Map findings to **different sports** (football, basketball, tennis)
- [ ] Discuss **different streaming requirements** by sport
- [ ] Add **case studies** or **vignettes**

**Sports-Specific Discussion Points:**

**Football (Soccer):**
- Lower event frequency (~1 event/second)
- Bursty during active play
- Need for ordered event delivery

**Basketball:**
- Higher event frequency (~5-10 events/second)
- More continuous action
- Need for low-latency updates

**Tennis:**
- Very low event frequency (~0.1 events/second)
- Point-based structure
- Need for high reliability

**Files to Modify:**
- `manuscript.tex` - Section 5 (Discussion)
- `docs/sports_discussion.md` - New document

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

### Resources Required
- Access to sports domain literature
- StatsBomb dataset documentation
- Industry reports on sports analytics
- Time for domain research

### Estimated Timeline
- **Week 5:** Define latency requirements (1 day)
- **Week 5:** Validate against requirements (1 day)
- **Week 6:** Compare to production systems (2 days)
- **Week 6:** Explain dataset relevance (1 day)
- **Week 6:** Strengthen discussion (1 day)

---

---

## 🔴 ISSUE 6: Reproducibility Concerns

### Problem Statement
The referee noted: *"Reproducibility is claimed but critical infrastructure details are missing. I cannot replicate these results from the description."*

### Root Cause
- Insufficient documentation of experimental setup
- Missing configuration details
- No permanent archive for data/code
- No artifact evaluation

### Success Criteria
✅ Complete infrastructure documentation  
✅ All configurations (Docker, scripts, parameters) documented  
✅ Permanent archive (Zenodo, Figshare, or GitHub release)  
✅ Artifact available for review  
✅ Reproducibility checklist completed

### Practical Solutions

#### Solution 6.1: Document Complete Infrastructure

**Action Items:**
- [ ] Create **infrastructure documentation**
- [ ] Document **Docker configurations**
- [ ] Document **hardware specifications**
- [ ] Document **network topology**
- [ ] Document **all software versions**

**Infrastructure Documentation Template:**

```markdown
# Infrastructure Documentation

## Hardware
- **Machine:** [Model]
- **CPU:** [Intel i9-13900K, 24 cores, 5.8 GHz]
- **Memory:** [64 GB DDR5-6000]
- **Storage:** [2 TB NVMe SSD, Samsung 980 Pro]
- **Network:** [10 Gbps Ethernet]
- **OS:** [Windows 11 Professional, Version 22H2]

## Software
- **Docker:** [Docker Desktop 4.27.1]
- **Kafka:** [Apache Kafka 4.1.1, Official Image]
- **Redis:** [Redis 7.2.4, Official Image]
- **Python:** [3.9.13]
- **Dependencies:** [See requirements.txt]

## Docker Configuration
```yaml
# Complete docker-compose.yml with all parameters
```

## Resource Limits
- **Kafka:** [4 GB RAM, 2 CPU cores]
- **Redis:** [2 GB RAM, 1 CPU core]
- **Producers/Consumers:** [1 GB RAM, 0.5 CPU core each]

## Network Topology
- [Description of container networking]
- [Latency between containers: X ms]
- [Bandwidth: Y Gbps]
```

**Files to Create:**
- `docs/infrastructure.md` - Complete infrastructure documentation
- `configs/docker/` - All Docker configuration files

**Effort:** 2-3 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

#### Solution 6.2: Create Reproducibility Package

**Action Items:**
- [ ] Package **all code** in a release
- [ ] Package **all data** (or provide download instructions)
- [ ] Include **complete documentation**
- [ ] Create **reproducibility checklist**
- [ ] Test **reproducibility** on clean system

**Reproducibility Package Structure:**
```
reproducibility_package/
├── README.md                    # Reproduction instructions
├── setup.sh                     # Setup script
├── run_experiments.sh           # Run all experiments
├── configs/                     # All configuration files
│   ├── docker-compose.yml
│   ├── kafka_config/
│   └── redis_config/
├── scripts/                     # All benchmark scripts
│   ├── kafka_producer.py
│   ├── kafka_consumer.py
│   ├── redis_producer.py
│   ├── redis_consumer.py
│   └── analyze_results.py
├── data/                        # Input data
│   └── replay_plans/
├── runs/                        # Example run outputs
├── docs/                        # Documentation
│   ├── infrastructure.md
│   ├── methodology.md
│   └── results.md
└── VERIFICATION.md              # Verification steps
```

**Reproducibility Checklist:**
- [ ] Code compiles without errors
- [ ] Docker containers start successfully
- [ ] Experiments run to completion
- [ ] Results match reported values (+-5% tolerance)
- [ ] All figures can be regenerated
- [ ] All tables can be regenerated

**Files to Create:**
- `REPRODUCIBILITY.md` - Reproducibility guide
- GitHub Release with all artifacts
- Zenodo DOI for permanent archive

**Effort:** 3-4 hours  
**Complexity:** Medium  
**Status:** ⬜ Not Started

---

#### Solution 6.3: Add Artifact to Permanent Archive

**Action Items:**
- [ ] Create **Zenodo deposit** for reproducibility package
- [ ] Obtain **DOI** for citation
- [ ] Link DOI in manuscript
- [ ] Ensure **long-term availability** (10+ years)

**Zenodo Upload Checklist:**
- [ ] All code (GitHub repository archive)
- [ ] All configuration files
- [ ] Sample data (or instructions to obtain)
- [ ] Documentation (README, methodology)
- [ ] Results (sample outputs)
- [ ] License (MIT, as specified)

**Files to Create:**
- Zenodo deposit
- DOI citation in manuscript

**Effort:** 1-2 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

#### Solution 6.4: Document Experimental Protocol in Detail

**Action Items:**
- [ ] Document **step-by-step experimental protocol**
- [ ] Include **timestamps** for all steps
- [ ] Document **randomization** procedures
- [ ] Document **blinding** (if applicable)
- [ ] Document **error handling**

**Experimental Protocol:**

```markdown
# Experimental Protocol

## Setup Phase (Before Each Run)
1. [Time] Start Docker containers
2. [Time] Verify container health
3. [Time] Create unique topic/stream
4. [Time] Initialize producer/consumer

## Execution Phase (During Each Run)
1. [Time] Start consumer process
2. [Time] Wait for consumer readiness
3. [Time] Start producer process
4. [Time] Monitor execution
5. [Time] Wait for completion (5 min timeout)

## Collection Phase (After Each Run)
1. [Time] Verify all events produced
2. [Time] Verify all events consumed
3. [Time] Compute TTI metrics
4. [Time] Save raw data
5. [Time] Shutdown containers

## Quality Checks
1. Event count match (+-1% tolerance)
2. TTI validity checks
3. Log file error scan
4. Metadata validation
```

**Files to Create:**
- `docs/protocol.md` - Detailed protocol
- `scripts/verify_protocol.py` - Protocol verification script

**Effort:** 2-3 hours  
**Complexity:** Low  
**Status:** ⬜ Not Started

---

### Resources Required
- Zenodo account (free)
- GitHub access
- Documentation tools

### Estimated Timeline
- **Week 7:** Document infrastructure (1 day)
- **Week 7:** Create reproducibility package (1 day)
- **Week 7:** Upload to Zenodo (0.5 day)
- **Week 7:** Document protocol (1 day)

---

---

## 📅 Comprehensive Timeline

### Phase 1: Research Design (Week 1)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Define RQs and hypotheses | 2 days | None | All |
| Formulate testable hypotheses | 1 day | RQs defined | All |

### Phase 2: Methodology Improvements (Weeks 2-3)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Set up multi-broker Kafka | 2 days | None | DevOps |
| Set up Redis cluster | 1 day | Kafka setup | DevOps |
| Execute full experiment matrix | 2 days | Clusters ready | All |
| Analyze configuration impact | 1 day | Results available | Analyst |

### Phase 3: Statistical Rigor (Week 4-5)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Multiple comparisons correction | 1 day | Results available | Statistician |
| Effect sizes and CIs | 1 day | Correction done | Statistician |
| Power analysis | 1 day | Effect sizes done | Statistician |
| Assumption verification | 2 days | Power analysis done | Statistician |

### Phase 4: Sports Domain (Week 5-6)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Define latency requirements | 1 day | None | Domain expert |
| Validate against requirements | 1 day | Requirements defined | Analyst |
| Compare to production systems | 2 days | Validation done | Domain expert |
| Explain dataset relevance | 1 day | None | Analyst |
| Strengthen discussion | 1 day | All above done | All |

### Phase 5: Reproducibility (Week 7)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Document infrastructure | 1 day | None | DevOps |
| Create reproducibility package | 1 day | Infrastructure documented | DevOps |
| Upload to Zenodo | 0.5 day | Package ready | All |
| Document protocol | 1 day | None | All |

### Phase 6: Manuscript Revision (Week 8)
| Task | Duration | Dependencies | Owner |
|------|----------|--------------|-------|
| Integrate all changes | 2 days | All above done | Writer |
| Peer review | 1 day | Draft ready | All |
| Final polish | 1 day | Review done | Writer |

---

## 📊 Total Effort Estimate

| Category | Hours | Weeks |
|----------|-------|-------|
| Research Design (Issue 1) | 12-16 | 0.5 |
| Methodology (Issue 2) | 40-52 | 2 |
| Baseline/Fairness (Issue 3) | 32-44 | 2 |
| Statistics (Issue 4) | 24-32 | 1.5 |
| Sports Domain (Issue 5) | 32-44 | 2 |
| Reproducibility (Issue 6) | 16-24 | 1 |
| **Total** | **156-212** | **9-10** |

**Note:** This assumes 1-2 people working full-time. With parallel work, timeline can be compressed to **4-5 weeks**.

---

## ✅ Checklist for Final Submission

### Research Design
- [ ] Research questions clearly stated
- [ ] Hypotheses formally defined
- [ ] Hypotheses mapped to scenarios
- [ ] All hypotheses testable with data

### Methodology
- [ ] Multi-broker Kafka tests completed
- [ ] Redis cluster tests completed
- [ ] Fair comparison established
- [ ] Configuration impact analyzed

### Baseline & Fairness
- [ ] Message sizes analyzed
- [ ] Throughput measured
- [ ] Protocol overhead quantified
- [ ] Persistence settings compared
- [ ] Baseline tests conducted

### Statistics
- [ ] Multiple comparisons correction applied
- [ ] Effect sizes reported
- [ ] Confidence intervals added
- [ ] Power analysis conducted
- [ ] Assumptions verified

### Sports Domain
- [ ] Latency requirements defined
- [ ] Actionability validated
- [ ] Production comparison completed
- [ ] Dataset relevance explained
- [ ] Domain discussion strengthened

### Reproducibility
- [ ] Infrastructure documented
- [ ] Reproducibility package created
- [ ] Zenodo deposit made
- [ ] DOI obtained
- [ ] Protocol documented

---

## 📝 Version Control

| Version | Date | Changes | Owner |
|---------|------|---------|-------|
| 1.0 | 2026-06-13 | Initial plan created | Research Team |
| | | | |

---

## 🎯 Next Steps

1. **Immediate (This Week):**
   - Review and approve this plan
   - Assign owners to each task
   - Set up project management (GitHub Projects, Trello, etc.)

2. **Week 1:**
   - Start with Issue 1 (Research Questions) - Lowest effort, highest impact
   - Begin Issue 2 (Multi-broker setup) - Longest lead time

3. **Ongoing:**
   - Weekly progress meetings
   - Update this document with status
   - Track completion of each solution

---

## 💬 Communication Plan

- **Weekly sync:** Every Monday at 10am
- **Progress updates:** Slack/Teams daily standup
- **Document updates:** Git commits with clear messages
- **Blockers:** Escalate immediately to team lead

---

*This is a living document. Update it as work progresses and new issues are identified.*
