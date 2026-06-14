# OBJECTIVES: Streaming Latency Benchmarks Revision

**Manuscript:** Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds  
**Target Journal:** Journal of Sports Analytics (Q1 2026)  
**Document Version:** 2.0  
**Last Updated:** June 15, 2026  
**Status:** ACTIVE - Individual Solution Strategy

**IMPORTANT: We are NOT uniting solutions.** Each issue will be addressed with separate, distinct configurations and solutions. No combined approaches that attempt to solve multiple issues simultaneously. This ensures clarity, isolation of variables, and easier validation.

---

## PRIMARY OBJECTIVE

**Address all 6 referee criticisms individually with dedicated solutions for each issue.** Each issue receives focused attention with room for jiggle (20% buffer) and hyper-documentation. Solutions go beyond basic requirements where appropriate.

### Core Strategy
- **Individual Solutions:** Each issue (1-6) receives its own dedicated configuration, experiments, and analysis
- **Isolated Variables:** No attempt to combine or unite solutions - each issue is addressed separately
- **Sequential Execution:** Issues addressed one at a time, with Issue 1 starting first
- **Room for Jiggle:** 20% buffer time built into all estimates for flexibility

---

## SUCCESS CRITERIA

### Must Achieve (Non-Negotiable)
- [ ] All 6 referee criticisms fully addressed
- [ ] 120 new multi-broker runs completed and validated
- [ ] Statistical analysis with Holm-Bonferroni correction, effect sizes, CIs
- [ ] Sports-specific latency thresholds defined and validated
- [ ] Complete reproducibility package archived on Zenodo
- [ ] Manuscript updated with all findings
- [ ] Final PDF generated and validated

### Should Achieve (Enhanced)
- [ ] 20% buffer time built into all estimates (room for jiggle)
- [ ] Solutions go beyond basic requirements (see below)
- [ ] Hyper-documentation of all decisions and configurations
- [ ] All assumptions explicitly stated and verified
- [ ] Edge cases tested and documented
- [ ] Production-grade quality on all deliverables

---

## ISSUE 1: RESEARCH QUESTIONS & HYPOTHESES (CURRENT FOCUS)

### Approach
Start with broad, comprehensive research covering multiple perspectives:
- Academic theory (CAP, PACELC, design patterns)
- Industry benchmarks (Kafka vs Redis comparisons)
- Sports domain (latency requirements by use case)
- Technical dimensions (throughput vs latency, consistency trade-offs)
- Economic perspectives (cost of latency, TCO)
- Multi-sport comparison

### Research Phase
- **Broad Research:** Consult 50+ sources from Google Scholar and other academic databases
- **Multiple Perspectives:** Document findings from theoretical, empirical, industry, and domain-specific viewpoints
- **Comprehensive Compilation:** Create detailed research compilation with all perspectives

### Deliverables
1. Comprehensive research compilation document
2. Enhanced RQs and hypotheses in manuscript.tex
3. Hyper-documentation of all research decisions
4. Updated bibliography with all relevant sources

---

## ENHANCED SOLUTIONS (Beyond Basic Requirements)

### Issue 1: Research Questions & Hypotheses - ENHANCED

**Basic:** Add 4 RQs and 4 hypotheses to Introduction

**Enhanced:** 
- Add **statistical test justification** for each hypothesis
- Include **effect size thresholds** for practical significance
- Map hypotheses to **specific figures/tables** in Results
- Add **null hypothesis testing framework** section
- Include **power analysis preview** in Methodology

**Deliverables:**
- Manuscript Section 1.1: Research Questions (4 RQs with sports context)
- Manuscript Section 1.2: Hypotheses (4 H with statistical tests)
- Manuscript Section 3.5: Statistical Methods (test selection justification)
- `scripts/hypothesis_testing.py` - Reusable hypothesis testing utilities

---

### Issue 2: Multi-Broker Configuration - ENHANCED

**Basic:** 3 Kafka brokers + 3 Redis nodes, run 120 configurations

**Enhanced:**
- Test **two Kafka acks modes**: acks=1 (default) and acks=all (full durability)
- Test **two Redis persistence modes**: AOF every 1s and AOF always
- Include **warm-up runs** before official measurements (10 per config)
- Add **health checks** before each run (broker cluster status)
- Document **network topology** and **resource isolation**
- Add **baseline runs** (single-node) for direct comparison

**Matrix Expansion (Still 120 official runs):**
```
Additional Test Runs (Not in official count):
├─ Warm-up: 10 runs per config (240 runs) - discarded
├─ Health check: 1 run per config (24 runs) - validation only
└─ Baseline: Existing 250 S2 runs - reused

Official Runs: 120 (as planned)
Total Runs: 394 (including warm-up and validation)
```

**Docker Configurations:**
1. `docker-compose-kafka-single.yml` - Existing, reused
2. `docker-compose-kafka-cluster-acks1.yml` - NEW, RF=3, acks=1
3. `docker-compose-kafka-cluster-acksall.yml` - NEW, RF=3, acks=all
4. `docker-compose-redis-single.yml` - Existing, reused
5. `docker-compose-redis-cluster-aof1s.yml` - NEW, 3 nodes, AOF every 1s
6. `docker-compose-redis-cluster-aofalways.yml` - NEW, 3 nodes, AOF always

**Enhanced Scripts:**
- `scripts/validate_cluster_health.py` - NEW, pre-run validation
- `scripts/warmup_runner.py` - NEW, execute warm-up runs
- `scripts/baseline_comparison.py` - NEW, compare to existing S2 runs

---

### Issue 3: Baseline & Fairness - ENHANCED

**Basic:** Measure message sizes, throughput, protocol overhead

**Enhanced:**
- **Message size bins**: Analyze performance by size categories (<1KB, 1-10KB, 10-100KB)
- **Throughput vs latency trade-off**: Plot throughput on x-axis, TTI on y-axis
- **Protocol overhead decomposition**: Separate serialization, network, deserialization
- **Persistence overhead**: Compare acks=1 vs acks=all impact on TTI
- **Memory-mapped vs heap**: Document Redis memory allocation strategy
- **Batch size analysis**: Test with different Kafka batch sizes

**Enhanced Metrics:**
```python
# In addition to basic metrics:
latency_breakdown = {
    'serialization_ns': t_serialize_end - t_serialize_start,
    'network_ns': t_receive - t_send,  # If measurable
    'deserialization_ns': t_deserialize_end - t_deserialize_start,
    'broker_processing_ns': t_consume - t_produce,  # Approximate
    'total_ns': tti_ns
}
```

**Deliverables:**
- `docs/results/latency_breakdown/` - Per-component latency analysis
- `docs/results/throughput_tradeoff/` - Throughput vs TTI scatter plots
- `scripts/analyze_latency_components.py` - NEW
- `scripts/analyze_throughput_tradeoff.py` - NEW

---

### Issue 4: Statistical Analysis - ENHANCED

**Basic:** Holm-Bonferroni correction, Cohen's d, 95% CIs, power analysis

**Enhanced:**
- **Multiple correction methods**: Bonferroni, Holm-Bonferroni, Benjamini-Hochberg (FDR)
- **Multiple effect sizes**: Cohen's d, Hedges' g, eta-squared, omega-squared
- **Bayesian analysis**: Bayesian t-tests with BF10 calculation
- **Robust statistics**: Median, IQD, robust Cohen's d
- **Distribution analysis**: Q-Q plots, skewness, kurtosis
- **Subgroup analysis**: Per-scenario, per-concurrency, per-configuration
- **Interaction effects**: Two-way ANOVA for backend×config interactions

**Statistical Tests Matrix:**
| Comparison | Parametric Test | Non-Parametric Alternative | Correction Method |
|------------|-----------------|----------------------------|------------------|
| 2 groups | t-test | Mann-Whitney U | Holm-Bonferroni |
| >2 groups | ANOVA | Kruskal-Wallis | Holm-Bonferroni |
| Paired | Paired t-test | Wilcoxon signed-rank | Bonferroni |
| Correlations | Pearson | Spearman | FDR (BH) |

**Deliverables:**
- `scripts/statistical_analysis.py` - Comprehensive stats library
- `docs/results/statistical_tests/` - All test results with corrections
- `docs/results/bayesian_analysis/` - Bayesian test results
- `docs/results/distribution_analysis/` - Normality and distribution checks

---

### Issue 5: Sports Domain Relevance - ENHANCED

**Basic:** Define thresholds, calculate actionability, compare to production

**Enhanced:**
- **Threshold validation**: Survey sports industry practitioners for threshold confirmation
- **Real-world comparison**: Reach out to Opta, StatsBomb, Hawk-Eye for actual latency data
- **Multiple sports**: Extend analysis to basketball, tennis, baseball requirements
- **Use case mapping**: Map each result to specific sports stakeholders
- **Economic impact**: Estimate cost of latency for betting platforms
- **Tactical impact**: Model coaching decision quality vs latency

**Sports Requirements Matrix:**
| Sport | Event Freq | Use Case | Max Latency | Source |
|-------|------------|---------|-------------|--------|
| Football | ~1/s | Coaching | <500ms | Opta 2023 |
| Football | ~1/s | Betting | <100ms | Bet365 2023 |
| Football | ~1/s | Broadcast | <1s | BBC 2023 |
| Basketball | ~10/s | Live stats | <200ms | NBA 2023 |
| Tennis | ~0.1/s | Scoring | <500ms | Wimbledon 2023 |
| Baseball | ~3/s | Pitch tracking | <100ms | MLB 2023 |

**Deliverables:**
- `docs/sports_requirements.md` - Comprehensive sports latency requirements
- `docs/production_comparison.md` - Detailed production system analysis
- `scripts/calculate_economic_impact.py` - NEW, latency cost modeling
- `scripts/tactical_impact_analysis.py` - NEW, decision quality modeling

---

### Issue 6: Reproducibility - ENHANCED

**Basic:** Infrastructure docs, Zenodo archive, reproducibility package

**Enhanced:**
- **Complete environment specification**: Exact Docker images, Python versions, OS
- **Automated validation**: Script that verifies environment matches original
- **Data provenance**: Chain of custody for all data files
- **Artifact evaluation**: ACM artifact review badge preparation
- **Containerization**: Docker image for entire benchmark suite
- **CI/CD pipeline**: GitHub Actions for automated testing
- **Version pinning**: All dependencies pinned to exact versions

**Reproducibility Package Contents:**
```
reproducibility_package/
├── README.md                          # Step-by-step guide
├── VERSIONS.md                        # All software versions
├── environment_lock.yml               # Exact environment spec
├── docker-images/                     # All Docker images used
│   ├── kafka-4.1.1.tar
│   ├── redis-7.2.4.tar
│   └── zookeeper-3.8.tar
├── docker-compose/                    # All compose files
│   ├── kafka-single.yml
│   ├── kafka-cluster-acks1.yml
│   ├── kafka-cluster-acksall.yml
│   ├── redis-single.yml
│   ├── redis-cluster-aof1s.yml
│   └── redis-cluster-aofalways.yml
├── scripts/                           # All benchmark scripts
│   ├── producers/
│   ├── consumers/
│   ├── analyzers/
│   └── validators/
├── configs/                          # All configuration files
├── data/                             # Sample data (10% for testing)
│   └── statsbomb_sample_10percent.csv
├── tests/                            # All test scripts
├── validation/                       # Validation scripts
│   ├── environment_validator.py
│   └── data_provenance_checker.py
└── results/                          # Expected outputs (schemas)
    └── expected_schema.csv
```

**Zenodo Archive Structure:**
```
zenodo_upload/
├── README.md                          # Archive description
├── manuscript/                        # Final manuscript
│   ├── manuscript.tex
│   ├── manuscript.pdf
│   ├── manuscript_references.bib
│   └── figures/
├── code/                             # All code
│   ├── scripts/
│   ├── docker-compose/
│   └── tests/
├── data/                             # All raw data
│   ├── runs/
│   │   ├── paper_s2_official/
│   │   ├── paper_s3_official/
│   │   └── paper_s4_multibroker/
│   └── processed/
└── documentation/                    # All docs
    ├── REVISION_PLAN_COMPACT.md
    ├── OBJECTIVES.md
    └── infrastructure.md
```

**Deliverables:**
- `docs/infrastructure_complete.md` - Hyper-detailed infrastructure
- `docs/reproducibility_guide.md` - Complete reproduction guide
- `scripts/validate_environment.py` - NEW, environment validator
- `scripts/verify_reproducibility.py` - NEW, reproducibility checker
- Zenodo DOI with complete archive
- GitHub Actions CI/CD workflow

---

## TIMELINE WITH BUFFER (20% Jiggle Room)

### Week 1: Foundation (June 15-21) - 24 hours allocated (20h work + 4h buffer)
| Day | Task | Base Effort | Buffer | Total |
|-----|------|-------------|--------|-------|
| Mon | Issue 1: Add RQs to manuscript.tex | 2h | 0.4h | 2.4h |
| Mon | Issue 1: Add hypotheses to manuscript.tex | 2h | 0.4h | 2.4h |
| Mon | Issue 2: Create docker-compose-kafka-cluster-acks1.yml | 2h | 0.4h | 2.4h |
| Mon | Issue 2: Create docker-compose-kafka-cluster-acksall.yml | 2h | 0.4h | 2.4h |
| Tue | Issue 2: Create docker-compose-redis-cluster-aof1s.yml | 2h | 0.4h | 2.4h |
| Tue | Issue 2: Create docker-compose-redis-cluster-aofalways.yml | 2h | 0.4h | 2.4h |
| Tue | Issue 2: Update kafka_producer.py | 2h | 0.4h | 2.4h |
| Wed | Issue 2: Update kafka_consumer.py | 2h | 0.4h | 2.4h |
| Wed | Issue 2: Update redis_producer.py | 2h | 0.4h | 2.4h |
| Thu | Issue 2: Update redis_consumer.py | 2h | 0.4h | 2.4h |
| Thu | Issue 2: Update run_concurrency_test.py | 2h | 0.4h | 2.4h |
| Fri | Validate all Docker configs | 4h | 0.8h | 4.8h |
| Sat | Test end-to-end with single config | 4h | 0.8h | 4.8h |
| Sun | Buffer / catch-up | 0h | 4h | 4h |

### Week 2: Execution (June 22-28) - 48 hours allocated (40h runtime + 8h buffer)
| Day | Task | Base Effort | Buffer | Total |
|-----|------|-------------|--------|-------|
| Mon | Warm-up runs (24 configs × 10 = 240) | 6h | 1.2h | 7.2h |
| Tue | Kafka single, all scenarios, all concurrency | 6h | 1.2h | 7.2h |
| Wed | Kafka cluster (acks=1), all scenarios | 6h | 1.2h | 7.2h |
| Thu | Kafka cluster (acks=all), all scenarios | 6h | 1.2h | 7.2h |
| Fri | Redis single, all scenarios | 6h | 1.2h | 7.2h |
| Sat | Redis cluster (AOF 1s), all scenarios | 6h | 1.2h | 7.2h |
| Sun | Redis cluster (AOF always), all scenarios + Buffer | 8h | 2.4h | 8.4h |

### Week 3: Enhanced Analysis (June 29 - July 5) - 36 hours allocated (30h work + 6h buffer)
| Day | Task | Base Effort | Buffer | Total |
|-----|------|-------------|--------|-------|
| Mon | Issue 4: Multiple correction methods | 3h | 0.6h | 3.6h |
| Mon | Issue 4: Multiple effect sizes | 2h | 0.4h | 2.4h |
| Tue | Issue 4: Bayesian analysis | 3h | 0.6h | 3.6h |
| Tue | Issue 4: Distribution checks | 3h | 0.6h | 3.6h |
| Wed | Issue 3: Latency breakdown analysis | 3h | 0.6h | 3.6h |
| Wed | Issue 3: Throughput trade-off analysis | 3h | 0.6h | 3.6h |
| Thu | Issue 5: Actionability analysis | 3h | 0.6h | 3.6h |
| Thu | Issue 5: Production comparison | 3h | 0.6h | 3.6h |
| Fri | Issue 5: Economic/tactical impact | 3h | 0.6h | 3.6h |
| Sat | Update manuscript Results | 4h | 0.8h | 4.8h |
| Sun | Buffer / catch-up | 0h | 6h | 6h |

### Week 4: Documentation & Finalization (July 6-12) - 30 hours allocated (25h work + 5h buffer)
| Day | Task | Base Effort | Buffer | Total |
|-----|------|-------------|--------|-------|
| Mon | Issue 6: Complete infrastructure docs | 2h | 0.4h | 2.4h |
| Mon | Issue 6: Create reproducibility package | 3h | 0.6h | 3.6h |
| Tue | Issue 6: Upload to Zenodo | 2h | 0.4h | 2.4h |
| Tue | Issue 6: Update manuscript Methodology | 3h | 0.6h | 3.6h |
| Wed | Issue 6: CI/CD pipeline setup | 4h | 0.8h | 4.8h |
| Thu | Final manuscript review | 4h | 0.8h | 4.8h |
| Fri | Peer review (internal) | 4h | 0.8h | 4.8h |
| Sat | Address review comments | 4h | 0.8h | 4.8h |
| Sun | Final PDF generation + Buffer | 1h | 5h | 6h |

### Total Timeline
| Phase | Base Hours | Buffer Hours | Total Hours |
|-------|------------|--------------|-------------|
| Week 1 | 20 | 4 | 24 |
| Week 2 | 40 | 8 | 48 |
| Week 3 | 30 | 6 | 36 |
| Week 4 | 25 | 5 | 30 |
| **Total** | **115** | **23** | **138** |

**Original Estimate:** 94 hours  
**With 20% Buffer:** 138 hours (+44 hours buffer)  
**Work Reduction from Unification:** 75% (120 runs vs ~480)  
**Total with Enhanced Solutions:** ~150 hours (still reasonable)

---

## HYPER-DOCUMENTATION STANDARDS

### Every File Must Have
1. **Header block** with purpose, author, date, version
2. **Configuration parameters** explicitly listed
3. **Dependencies** clearly stated
4. **Input/output schema** documented
5. **Error handling** described
6. **Limitations** acknowledged

### Example Documentation Structure

```markdown
# Script: compute_tti.py

## Purpose
Computes Time-to-Insight (TTI) metrics from producer and consumer event logs.

## Version
- Current: 2.1
- Last Updated: June 15, 2026
- Author: Research Team

## Dependencies
- Python 3.9+
- pandas >= 1.3.0
- numpy >= 1.21.0
- scipy >= 1.7.0

## Inputs
### Required Files
1. `producer_events.csv` - Producer event timestamps
   - Columns: event_id, t_prod_sched_ns, t_prod_send_ns, message_size
2. `consumer_events.csv` - Consumer event timestamps  
   - Columns: event_id, t_consume_ns, t_broker_ack_ns, redis_id

### Expected Schema
```
producer_events.csv:
- event_id (str): Unique event identifier
- t_prod_sched_ns (int): Scheduled production time in nanoseconds
- t_prod_send_ns (int): Actual send time in nanoseconds
- message_size (int): Message size in bytes

consumer_events.csv:
- event_id (str): Unique event identifier (matches producer)
- t_consume_ns (int): Consumption time in nanoseconds
- t_broker_ack_ns (int): Broker acknowledgment time (Kafka only)
- redis_id (str): Redis stream ID (Redis only)
```

## Outputs
### Generated Files
1. `tti_summary.json` - Per-run TTI statistics
   - Keys: run_id, backend, config, scenario, concurrency
   - Metrics: p50, p95, p99, max, mean, std, min, count

2. `actionability.json` - Threshold analysis
   - Keys: run_id, backend, config
   - Metrics: pct_<100ms, pct_<500ms, pct_<1s, pct_<5s, pct_<10s

## Parameters
```python
--input-dir STR       : Directory containing producer/consumer CSVs (default: ./runs)
--output-dir STR      : Directory for output files (default: ./results)
--scenarios LIST      : Scenarios to process (default: [S1, S2, S3, S4, S5])
--percentiles LIST    : Percentiles to calculate (default: [50, 95, 99])
--thresholds LIST     : Actionability thresholds in ms (default: [100, 500, 1000, 5000, 10000])
--verbose            : Enable verbose logging
```

## Algorithm
1. Load producer_events.csv and consumer_events.csv
2. Match events by event_id
3. Calculate TTI = t_consume_ns - t_prod_sched_ns
4. Calculate Transport Latency = t_consume_ns - t_broker_ack_ns (or t_prod_send_ns)
5. Calculate Producer Lag = t_prod_send_ns - t_prod_sched_ns
6. Aggregate metrics at specified percentiles
7. Calculate actionability percentages
8. Output summary JSON

## Error Handling
- Missing event_id: Log warning, skip event
- Type mismatch: Raise TypeError with details
- Empty input: Raise ValueError
- File not found: Raise FileNotFoundError

## Limitations
- Assumes perfect event matching (100% match rate)
- Network latency not directly measurable (included in TTI)
- Clock synchronization assumed between producer/consumer
- Does not account for system clock drift

## Validation
- Test coverage: 99% (see tests/unit/test_compute_tti.py)
- Validated against: S2 runs (250 runs, June 2026)
- Known issue: None
```

---

## QUALITY GATES

### Before Merging Any Code
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Version bumped
- [ ] Change log entry added
- [ ] Peer review completed
- [ ] Hyper-documentation complete

### Before Starting Experiment
- [ ] Docker configs validated
- [ ] Health checks pass
- [ ] Warm-up runs complete
- [ ] Storage sufficient (200 GB free)
- [ ] Backup complete
- [ ] Monitoring in place

### Before Final Submission
- [ ] All 6 issues addressed
- [ ] Statistical analysis verified
- [ ] Sports validation complete
- [ ] Reproducibility package tested
- [ ] Zenodo archive created
- [ ] Manuscript finalized
- [ ] PDF generated and validated

---

## DECISION LOG

| Date | Decision | Rationale | Impact |
|------|----------|-----------|--------|
| 2026-06-15 | Use 120-run unified matrix | Maximizes data reuse, minimizes redundant work | Solves Issues 2,3,4,5 simultaneously |
| 2026-06-15 | 20% buffer on all estimates | Accounts for unknowns, technical debt | Reduces schedule risk |
| 2026-06-15 | Enhanced solutions beyond basic | Strengthens paper, addresses potential reviewer concerns | Increases acceptance probability |
| 2026-06-15 | Hyper-documentation standard | Ensures reproducibility, future maintainability | Meets journal requirements |

---

## NEXT ACTION

**Start Today (June 15):**
1. Edit `manuscript.tex` - Add RQs and hypotheses (Issue 1)
2. Create enhanced Docker compose files (Issue 2)
3. Begin hyper-documentation of existing scripts

---

*Document Version: 1.0*  
*Last Updated: June 15, 2026*  
*Status: Active Development*  
*Target: Journal of Sports Analytics Q1 2026*  
*Strategy: Unified 120-run matrix with 20% buffer and hyper-documentation*
