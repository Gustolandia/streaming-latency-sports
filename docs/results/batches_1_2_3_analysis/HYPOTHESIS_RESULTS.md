# Hypothesis Test Results

**Date:** 2026-06-16 20:24:03

## RQ1: Architecture Impact

- **Test:** Mann-Whitney U
- **U Statistic:** 2794.00
- **p-value:** 0.0000
- **Cohen's d:** 0.502
- **Kafka mean p50:** 11591.54 ms
- **Redis mean p50:** 7760.07 ms
- **Improvement:** 33.1%
- **Conclusion:** H1: Redis has significantly lower TTI

## RQ2: Concurrency Scaling

- **Test:** Kruskal-Wallis
- **H Statistic:** 0.65
- **p-value:** 0.7237
- **Conclusion:** H2: TTI remains constant across N=5,10,20

  **Pairwise Comparisons:**
  - N=5 vs N=10: U=790.00, p=0.9272, significant=False
  - N=5 vs N=20: U=716.00, p=0.4217, significant=False
  - N=10 vs N=20: U=742.00, p=0.5801, significant=False

## RQ3: Latency-Consistency Trade-off

- **Mean Match Rate:** 100.00%
- **Min Match Rate:** 100.00%
- **All 100%:** True
- **All >99.9%:** True
- **Conclusion:** H1: All configs >99.9%

## RQ4: Sports-Specific Performance

- **H4_1 Test:** Welch t-test
- **t Statistic:** 1.411
- **p-value:** 0.1653
- **Conclusion:** H0: No difference

- **H4_2 Test:** Levene test
- **F Statistic:** 0.889
- **p-value:** 0.3506
- **Conclusion:** H0: No difference in variance

## Issue 3: Throughput and Message Sizes

  **Throughput (events/sec):**
  - kafka: mean=6.98, std=1.72, min=3.81, max=11.76
  - redis: mean=6.91, std=1.60, min=3.81, max=8.39

  **Message Size (bytes):**
  - kafka: mean=198.23, std=25.22, min=12.73, max=213.84
  - redis: mean=216.90, std=6.63, min=207.46, max=230.87

## Issue 5: Actionability Metrics

  **% Events Under Threshold:**
  - kafka:
    - pct_under_100ms: 0.00%
    - pct_under_500ms: 0.00%
    - pct_under_1s: 0.00%
    - pct_under_5s: 0.00%
  - redis:
    - pct_under_100ms: 0.00%
    - pct_under_500ms: 0.00%
    - pct_under_1s: 0.00%
    - pct_under_5s: 0.00%
