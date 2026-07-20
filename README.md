# Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Target Journal: JSA](https://img.shields.io/badge/Target_Journal-Journal_of_Sports_Analytics-orange.svg)](https://www.degruyter.com/journal/key/jsa/html)
[![Tests](https://img.shields.io/badge/tests-895_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/branch_coverage-%E2%89%A595%25-brightgreen.svg)]()
[![StatsBomb Data](https://img.shields.io/badge/StatsBomb_Data-CC_BY--NC_4.0-blue.svg)](https://github.com/statsbomb/open-data)

> ## 🎯 Current target — the original contribution
>
> **Latency-induced decision degradation in real-time football analytics.**
> Couple *measured* Redis-vs-Kafka event-delivery latency (single vs. cluster, concurrent
> live matches, near-real-time replay) to an **in-play win-probability model** through the
> **Age-of-Information (AoI)** lens, and quantify the **win-probability error / actionable-edge
> loss** that each streaming architecture and configuration imposes. To our knowledge this is
> the **first infrastructure → decision-quality analysis on open StatsBomb data**.
>
> *Why this is publishable (Journal of Sports Analytics), not just a benchmark:* it yields a
> **sports quantity** (degraded win-probability), bridges two literatures, and rests on citable
> foundations — Robberechts et al. (SIGKDD 2021) for in-play soccer win-probability, and the
> Age-of-Information line of work for staleness → decision error. The broker comparison is the
> *independent variable*, not the point. **Honest scope:** an applied contribution; the WP model
> is a transparent, calibrated proxy for the (unreleased) SOTA model; single-host infrastructure.

> **This README is the single source of truth for the project.** It consolidates what
> were previously ~18 separate planning, methodology, and status documents. Section 1
> below is the live snapshot — start there. Everything else is reference material that
> rarely changes.

---

## Table of Contents

1. [Current State & Objectives](#1-current-state--objectives) ← **start here**
2. [Abstract](#2-abstract)
3. [Research Questions & Hypotheses](#3-research-questions--hypotheses)
4. [Dataset](#4-dataset)
5. [Architecture](#5-architecture)
6. [Methodology & Metrics](#6-methodology--metrics)
7. [Experimental Phases & Results](#7-experimental-phases--results)
8. [Repository Structure](#8-repository-structure)
9. [Quick Start & Running Benchmarks](#9-quick-start--running-benchmarks)
10. [Testing & Quality](#10-testing--quality)
11. [Reproducibility](#11-reproducibility)
12. [Manuscript & Paper Preparation](#12-manuscript--paper-preparation)
13. [Contributing](#13-contributing)
14. [Citation](#14-citation)
15. [License](#15-license)
16. [Changelog](#16-changelog)
17. [Appendix: Acronyms & File Types](#17-appendix-acronyms--file-types)

---

## 1. Current State & Objectives

**Last updated:** June 17, 2026 · **Branch:** `feat/s3-state-staleness-corrections` · **Target:** *Journal of Sports Analytics*, Q1 2026

### 1.1 Where things stand

> ⚠️ **Measurement corrections (June 17 2026) — read this first.** *Three* distinct
> measurement bugs were found and fixed; each had distorted prior "winner" results, so **no
> pre-fix latency number is treated as a finding.**
>
> 1. **Cross-process clock bug.** Producer and consumer stamped timestamps with
>    process-relative `perf_counter_ns`, so cross-process TTI/transport were inflated by each
>    run's consumer launch offset (~2 s). Fixed with `time.time_ns()` (shared epoch); transport
>    dropped to ~1 ms.
> 2. **Producer saturation at 120×.** The synchronous emit loop fell tens of seconds behind
>    schedule. Mitigated by non-blocking dispatch and a non-saturating replay speed.
> 3. **Kafka load-generator asymmetry.** The Kafka producer ran `--max-inflight 1, --acks all`
>    — blocking on a broker round-trip *per event* — while the Redis producer dispatched
>    asynchronously. This inflated Kafka's *producer scheduling lag* (not its broker latency):
>    e.g. N=1 at 10× went from **TTI 1644 ms → 16 ms** once the Kafka producer was pipelined
>    (`--max-inflight 64`). All earlier cross-backend comparisons (incl. the 60-run `batch9`
>    matrix and the old 120× concurrency runs) are confounded by this and are being **regenerated
>    under a fair, pipelined, non-saturating protocol** (`speedup=10`).
>
> **Fair-config finding (artifact-free, single-host, in progress):** for a *single* live feed
> Kafka ≈ Redis (~17 ms); under **concurrency**, single-node Redis (single-threaded) serializes
> concurrent streams and degrades sharply (~975 ms at N=5) while Kafka's partitioned broker stays
> flat (~18 ms). Cluster sweep + decision-staleness recompute next. See §1.5.

| Area | Status | Notes |
|------|--------|-------|
| Measurement fixes (clock + saturation + Kafka pipelining) | ✅ **Fixed, committed, validated** | `time.time_ns()`; non-blocking dispatch; `--max-inflight`; robust cluster remap |
| **Original contribution** (WP proxy + AoI decision-staleness) | ✅ **Built & tested** | `win_probability.py` (RPS/ECE calibrated, 34 matches) + `decision_staleness.py`; see 🎯 target above |
| Fair real-time concurrency sweep (`speedup=10`) | 🔄 **In progress** | single infra N∈{1,5,10,20} done; cluster sweep + recompute pending |
| Test suite | ✅ **≥95% branch coverage** | every script in `scripts/` + root health checks |
| Persistence H31/H32 (acks / AOF) | ✅ Complete | 12 runs; both hypotheses supported |
| S3 corrections | ✅ Complete | 30 runs regenerated; propagation p50 = 1,461 ms |
| Manuscript reframe around decision-degradation | 🔄 **In progress** | pending the fair corpus + recompute |
| All pre-fix runs (S1–S5, old concurrency, 120 matrix, `batch9`) | ❌ **Invalidated** | confounded by the clock and/or Kafka-pipelining artifacts; superseded |

### 1.2 Primary objective

> **Address all six referee criticisms with dedicated, isolated solutions, then resubmit
> to the *Journal of Sports Analytics*.** Each issue is solved separately (no combined
> fixes) to keep variables clean and validation easy.

**Core strategy — one experiment matrix solves four issues at once.** A single set of
**120 new multi-broker runs** simultaneously feeds Issues 2, 3, 4 and 5, cutting
experimental work by ~75% versus solving them independently:

```
120 runs = 2 backends × 2 configs × 5 scenarios × 3 concurrency × 2 reps
            (Kafka,      (single,    (S1–S5)      (N=5,10,20)   (rep1,
             Redis)       cluster)                               rep2)
```

Every run additionally captures throughput, message sizes, protocol overhead, resource
usage and actionability metrics, which is what lets one matrix answer multiple referee
concerns.

### 1.3 The six referee issues

| # | Criticism (paraphrased) | Severity | Solution status |
|---|-------------------------|----------|-----------------|
| **1** | No formal research questions or testable hypotheses; intro reads like a product description | High | ✅ **Done** — RQ1–RQ4, full hypothesis set, and stats framework already in `manuscript.tex` (§Introduction/Methods) |
| **2** | Single-broker comparison is unfair to Kafka (a distributed system) | **Critical** | ✅ **Done** — 120-run single+cluster matrix executed & analyzed; `config_comparison` shows cluster vs single (cluster slower → replication overhead) |
| **3** | No message-size / throughput / protocol-overhead controls → fairness unclear | High | ✅ Throughput + message size via `analyze_batches_1_2_3.py`; true serialized size + (de)serialization timing via `analyze_protocol_overhead.py` |
| **4** | Inadequate stats: 15 t-tests, no correction, no effect sizes, no CIs, no power | **Critical** | ✅ `statistical_analysis.py` (Holm-Bonferroni, Cohen's *d* / Hedges' *g*, 95% CIs, assumption checks) + `power_analysis.py` — note: study is **underpowered for small/medium effects** (n≥64 needed for *d*=0.5) |
| **5** | Sports angle feels post-hoc; no sports-specific latency requirements | High | ✅ `analyze_actionability.py` computes real actionability from `missed_window_rate` + production-system comparison (Redis 64% vs Kafka 29% of events under 5 s) |
| **6** | Reproducibility claimed but infrastructure under-documented; no permanent archive | Medium | ✅ `docs/infrastructure.md` + `verify_reproducibility.py` (120/120 runs have complete provenance); Zenodo archive still to mint |

### 1.4 Immediate next actions

The six issues are now substantively addressed in code/data. What remains is mostly
manuscript integration:

1. **Fold the new analysis outputs into `manuscript.tex`** — the corrected statistics
   (`docs/results/statistical_analysis/`), the underpowered-for-small-effects caveat from
   `power_analysis.py`, the real actionability + production comparison
   (`docs/results/actionability/`), and the single-vs-cluster result.
2. **Fix `manuscript.tex` LaTeX errors** and regenerate the PDF.
3. **Issue 6 finalize:** fill in host hardware in `docs/infrastructure.md` and mint the
   Zenodo DOI.

### 1.5 Main claims (fair, artifact-free corpus)

All numbers below come from the **fair** sweep — both producers pipelined, replay at a
non-saturating 10× — on the **single host, single node** (the regime we can measure cleanly).
Latency is median (p50) over feeds × 3 reps; `transport` = broker delivery, `TTI` = end-to-end
(identical definition for both backends). See [[measurement-artifacts]] for why every pre-fix
number is excluded.

**Claim 1 — At a single live feed, Kafka and Redis are equivalent (~17 ms).** The folk belief
(and our own contaminated "Redis 71× faster" headline) that one backend is simply faster is
wrong: for one match they are statistically indistinguishable and both excellent for real time.

**Claim 2 — Under concurrency, single-node Redis serializes and degrades; Kafka stays flat.**
Single-threaded Redis Streams cannot parallelize concurrent streams, so broker delivery grows
~linearly with the number of concurrent matches, while Kafka's partitioned broker is flat:

| N (concurrent matches) | Kafka transport p50 | Redis transport p50 | Kafka TTI p50 | Redis TTI p50 |
|---:|---:|---:|---:|---:|
| 1  | 2 ms  | 4 ms     | 17 ms     | 17 ms      |
| 5  | 2 ms  | 774 ms   | 18 ms     | 801 ms     |
| 10 | 4 ms  | 4,627 ms | 29 ms     | 5,206 ms   |
| 20 | 10 ms | 9,732 ms | 1,682 ms† | 13,006 ms  |

† Kafka's N=20 *TTI* is inflated by the **single host** saturating (40+ load-gen processes →
585 ms scheduling lag); its *transport* stays 10 ms, so the broker is fine. Transport is the
trustworthy cross-N metric.

**Claim 3 (the contribution) — This latency only matters for *decisions* in a specific regime.**
Decision-staleness (probability-seconds per match) via the Age-of-Information integral over the
**full match** (all 40 decisive events per run, not the ~3 in a 10-min window):

| N | Kafka-single | Redis-single |
|---:|---:|---:|
| 1  | 0.28  | 0.18 |
| 5  | 1.16  | 17.5 |
| 10 | 50.3† | 271  |
| 20 | —‡    | 1012 |

At a single feed both leave a match's win-probability stale by only ~0.2 prob·s (mean ~20 ms per
goal — **decision-irrelevant**, pushing back on the industry "2-second edge" framing). By **5
concurrent matches** single-node Redis already imposes **~15× more** decision-staleness than
Kafka (17.5 vs 1.16); by 10 a goal's win-prob arrives **~24 s stale**. **The first measured
answer to "when does streaming-infrastructure latency actually degrade an in-play football
decision?"** — irrelevant for one feed, Redis-dominated and decision-corrupting under concurrency.

**Formal tests** ([`docs/results/fair_statistics/`](docs/results/fair_statistics)) confirm it:
Holm–Bonferroni-corrected Mann–Whitney finds **no** significant Kafka–Redis difference at N=1
(latency *p*=0.69, decision-staleness *p*=0.40) but a **highly significant** difference at every
N≥5 (*p*<10⁻⁵, rank-biserial=1.0 — complete separation), and Kruskal–Wallis confirms an N-effect
for both backends. († host-saturated — single-host load-gen lag, not broker; ‡ Kafka N=20
full-match runs unreliable under host strain, omitted. N≥10 magnitudes are bounded by our single
host, not the broker.)

**Supporting results.** Durability costs latency for both (Kafka `acks=all` > `acks=1`; Redis
`appendfsync always` ≫ `everysec`). TTI decomposes into producer scheduling lag + transport +
output; keeping scheduling lag small is what validates TTI as a latency.

**Honest limitation — cluster.** On a single host the 3-node experiments are **confounded** and
are *not* a main claim: Kafka-cluster transport stays clean (~3 ms, broker scales) but TTI is
swamped by topic-creation/metadata blocking + 6 co-located broker containers saturating the host;
Redis-cluster client redirection inflates even N=1. We report cluster *transport* only and flag
true multi-host as future work.

---

## 2. Abstract

> **Title:** *Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds*
> **Target journal:** *Journal of Sports Analytics* (planned submission Q1 2026)
> **Keywords:** streaming systems, real-time analytics, sports data, Kafka, Redis Streams, latency benchmarking, Time-to-Insight, actionability windows, reproducible research

We ask a question the streaming and sports-analytics literatures leave open: **does the
choice of streaming infrastructure actually degrade an in-play football decision, and if so,
when?** Using the **StatsBomb open dataset** (1. Bundesliga 2023/24, 34 matches), we replay
real event feeds through Apache Kafka and Redis Streams and couple the *measured* delivery
latency to an in-play **win-probability** model through the **Age-of-Information** lens,
quantifying the win-probability staleness each architecture imposes. To our knowledge this is
the first infrastructure → decision-quality analysis on open sports data.

Methodologically, the study is also a cautionary tale in measurement validity: three distinct
instrumentation defects — a process-relative cross-process clock, a saturating replay speed,
and an asymmetric load generator (synchronous per-event Kafka sends vs. asynchronous Redis
dispatch) — each *reversed* the apparent winner before correction. We report the
**Time-to-Insight (TTI)** metric decomposed into producer scheduling lag and transport, and
fix all three before drawing any conclusion.

On the corrected, fair corpus we find: (1) for a **single feed**, Kafka and Redis are
**equivalent** (~17 ms median TTI); (2) under **concurrency**, single-node Redis serializes
concurrent streams and its broker latency grows roughly linearly (to ~9.7 s at 20 concurrent
matches) while Kafka's partitioned broker stays flat (~10 ms); and (3) translated into
decisions, infrastructure latency is **decision-irrelevant for a single feed** (~0.01
probability-seconds of staleness) but becomes **material under concurrent under-provisioning**
(single-node Redis: ~12 probability-seconds — a goal's win-probability arriving ~15 s stale).
The practical guidance: infrastructure choice does not affect decision quality for one live
match, but provisioning for concurrency does.

---

## 3. Research Questions & Hypotheses

### 3.1 Research questions

- **RQ1** — How does streaming architecture choice (Kafka vs Redis Streams) impact
  Time-to-Insight (TTI) for real-time sports data processing?
- **RQ2** — How does concurrency level (N = 5, 10, 20) affect TTI for each architecture
  under realistic sports workloads?
- **RQ3** — What is the trade-off between latency (TTI) and data consistency (match rate,
  throughput) across architectures and configurations?
- **RQ4** — How do performance characteristics vary across sports event scenarios (S1–S5)
  and deployment configurations (single vs cluster)?

### 3.2 Hypotheses (16 total)

**RQ1 — Architecture impact**
- H₀₁: μ(TTI_Kafka) = μ(TTI_Redis) · H₁₁: Kafka > Redis (expected) · H₂₁: Kafka < Redis
- Test: Mann-Whitney U (data violates normality). Expected effect size: large (*d* > 0.8).

**RQ2 — Concurrency scaling**
- H₀₂: TTI independent of N · H₁₂: TTI increases with N · H₂₂: TTI constant across N (expected)
- Test: Kruskal-Wallis. ⚠️ Power ≈ 0.30 for small effects — sample expansion may be needed.

**RQ3 — Latency / consistency trade-off**
- H₀₃/H₁₃/H₂₃ on match rate (expected: all configs > 99.9%) — Test: Chi-square / Fisher's exact.
- H₃₁: Kafka acks=all > acks=1 · H₃₂: Redis AOF=always > AOF=1s — Test: Wilcoxon signed-rank.

**RQ4 — Sports-specific performance**
- H₀₄/H₁₄: TTI distribution differs by scenario (expected) — Test: Kolmogorov-Smirnov.
- H₄₁: TTI(S5) > TTI(S1) · H₄₂: variance(S5) > variance(S1) — Test: Kruskal-Wallis (queueing theory).

### 3.3 Statistical framework (planned, Issue 4)

- **Multiple comparisons:** Holm-Bonferroni (FWER control at α = 0.05).
- **Effect sizes:** Cohen's *d* (0.2 small / 0.5 medium / 0.8 large).
- **Confidence intervals:** 95% CIs (t-distribution).
- **Power analysis:** a priori + post hoc.
- **Assumption checks:** Shapiro-Wilk (normality), Levene's (variance), Q-Q plots.
- **Non-parametric fallbacks:** Mann-Whitney U, Kruskal-Wallis, Wilcoxon.

---

## 4. Dataset

| Property | Value |
|----------|-------|
| Source | [StatsBomb Open Data](https://github.com/statsbomb/open-data) (CC BY-NC-4.0) |
| Coverage | 20 years of professional football (2003–2023) |
| Subset used | 11 matches, **40,660 events** (commit `3bfbffe1`) |
| Peak event rate | ~10–20 events/second |
| Format | JSON (events, matches, competitions) → preprocessed to CSV replay plans |

### Preprocessing & replay plans

Raw StatsBomb JSON is extracted into CSV **replay plans** under
`data/processed/replay_plans/`:

| Plan | Description |
|------|-------------|
| `s1/` | Simple baseline scenarios |
| `s2/` | Full replay |
| `s2full/` | Extended full replay |
| `s2sf12/` | Event subset (used for concurrency tests) |
| `s2sf12j2/` | Alternative subset |

**Replay plan CSV schema:** `event_id` (str), `match_id` (str), `t_sim_seconds` (float),
`t_emit_offset_s` (float), plus match-specific metadata columns.

**Ethics:** open data, no PII; all scripts MIT-licensed; full provenance tracked per run.

---

## 5. Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                          BENCHMARK SYSTEM                               │
│                                                                         │
│   ┌────────────┐    ┌────────────┐    ┌────────────┐                    │
│   │ Replay Plan│───▶│  Producer  │───▶│   Broker   │                    │
│   │  (CSV)     │    │  (Python)  │    │  Kafka  /  │                    │
│   └────────────┘    └────────────┘    │  Redis     │                    │
│                                       └─────▲──────┘                    │
│                                             │                           │
│                                       ┌─────▼──────┐                    │
│                                       │  Consumer  │                    │
│                                       │  (Python)  │                    │
│                                       └─────▲──────┘                    │
│                                             │                           │
│                                       ┌─────▼──────┐                    │
│                                       │ TTI / S3 / │   → runs/<id>/*.csv │
│                                       │ S5 metrics │   → docs/results/*  │
│                                       └────────────┘                    │
└───────────────────────────────────────────────────────────────────────┘
```

**Data flow:** replay plan → producer (adds metadata, sends on schedule) → broker
(Kafka topic or Redis stream) → consumer (logs receive timestamps) → metric scripts
(match events, compute TTI/S3/S5). Each run is isolated via a unique topic/stream and
consumer group.

**Backend equivalence (single-broker S2):** both backends use speedup 120×, max sim time
600 s, `localhost`, unique topic/stream + group per run, identical plan CSV, 30 s idle
timeout. The only differences are transport-layer specifics (Kafka brokers vs Redis
streams) — the intended comparison.

**Multi-broker (Issue 2, built):**
- `docker-compose-multibroker.yml` — 3 Kafka brokers, KRaft mode, `apache/kafka:4.1.1`,
  replication factor 3, ports 9092/9093/9094.
- `docker-compose-redis-cluster.yml` — 3 Redis nodes, cluster mode, `redis:7.2.4`, AOF
  `everysec`, ports 7000–7002 (cluster ports 17000–17002).
- Producers/consumers select bootstrap servers / startup nodes via `--broker-count 3` /
  `--cluster-mode`; PowerShell runners create topics with RF=3 and clean cluster streams.

---

## 6. Methodology & Metrics

### 6.1 Primary metric — Time-to-Insight (TTI)

```
TTI = t_consume_ns − t_prod_sched_ns
```

- `t_prod_sched_ns` — when the producer schedules the event (`perf_counter_ns`)
- `t_consume_ns` — when the consumer receives it (`perf_counter_ns`)

### 6.2 Metric definitions

| Metric | Formula | Meaning |
|--------|---------|---------|
| TTI | `t_consume_ns − t_prod_sched_ns` | End-to-end time-to-insight |
| Transport latency | `t_cons_recv_ns − t_broker_ack_ns` | Network + broker overhead |
| Producer scheduling lag | `t_prod_send_ns − t_prod_sched_ns` | Producer-side delay |
| TTI p50 / p95 / p99 | percentiles of TTI | Median, 95th, 99th |
| Missed-window rate | `count(TTI > W) / count(TTI)` | Fraction exceeding window *W* |
| **S3** Correction propagation | `t_correction_consume − t_base_consume` | Time for a correction to land |
| **S3** Inconsistency duration | same as above | How long state is stale |
| **S3** Planned-to-consume | `t_correction_consume − t_emit_planned` | Total correction latency |

**Actionability windows:** 100 ms (tactical/betting), 250/500 ms (alerts/broadcast),
1000 ms (analysis). The revision adds sports-specific thresholds (Issue 5): betting
< 100 ms, coaching < 500 ms, broadcast < 1 s, fan apps < 5 s, post-match < 10 s.

### 6.3 Experimental procedure

**Single trial (S1–S2):** create a unique topic/stream → start consumer → run producer on
schedule → wait for completion → compute TTI → save CSVs + metadata. ~30–60 s per trial.

**Concurrency trial:** for each of N feeds, create an isolated topic/stream
(`sb-events-n{N}-feed{F}-rep{R}` / `sb:events:n{N}:feed{F}:rep{R}`), start all 2N
producer+consumer tasks via a `ThreadPoolExecutor(max_workers=N×2)`, 5-minute per-trial
timeout, then compute TTI per feed and aggregate with full provenance.

**Parameter sweep (S4):** vary speedup (60/120/240×), correction frequency (every
5/10/20 events), and correction delay (0/1/5/10 s) independently.

**Resource analysis (S5):** monitor CPU, memory, network and disk during runs.

### 6.4 S3 correction injection

S3 mode injects state-staleness corrections identically across both backends:
`--s3-mode corrections`, `--corrections-every-k 50`, `--correction-delay-s 2.0`, with a
`s3_uid` / `s3_rev` / `s3_is_correction` envelope. Config: `configs/s3_injections.yaml`
(`seed=12345`, every-kth selection, k=50).

### 6.5 Decision-staleness — the latency → decision bridge (primary contribution)

We translate delivery latency into in-play **decision error** in two steps:

1. **Win-probability proxy** (`scripts/win_probability.py`) — a transparent, calibrated in-play
   model on StatsBomb-derivable game state (score differential, fraction of match remaining,
   red-card differential), built on a Skellam (difference-of-Poissons) goal model. It cites
   Robberechts et al. (SIGKDD 2021) as the established model (their code is unreleased) and is
   validated by ranked probability score / calibration on held-out matches (RPS ≈ 0.24 over 34
   matches).
2. **Age-of-Information decision-staleness** (`scripts/decision_staleness.py`) — for each
   decisive event (goal), the consumer's win-probability is stale for the event's delivery
   latency *L* by the magnitude of the probability shift it caused. We define a run's
   **decision-staleness cost** = Σ over decisive events of `TV_shift × L` (units:
   probability-seconds per match), where `TV_shift = ½·(|ΔP_win| + |ΔP_draw| + |ΔP_loss|)`.

This is the metric behind §1.5 Claim 3 and the paper's contribution: it converts an
infrastructure quantity (latency) into a sports quantity (degraded win-probability).

---

## 7. Experimental Phases & Results

The **main results are in §1.5** (fair corpus). This section gives the supporting detail and
records the superseded phases for transparency.

### 7.1 Primary — fair concurrency sweep + decision-staleness

**Protocol:** both producers pipelined (Kafka `--max-inflight 64`; Redis async worker pool),
replay at a non-saturating **10×**, N ∈ {1, 5, 10, 20} concurrent feeds, single + cluster, 3
reps. The single-host result is the headline (§1.5, Claims 1–3). Outputs:
`docs/results/realtime_concurrency/` (latency by backend/config/N) and
`docs/results/decision_staleness_fair/` (decision-staleness by backend/config/N).

- **Latency** — Kafka transport flat (2–10 ms) across all N; single-node Redis transport grows
  4 → 774 → 4,627 → 9,732 ms. At N=1, TTI parity (~17 ms).
- **Decision-staleness** — negligible at N=1 (~0.01 prob·s, both); single-node Redis climbs to
  ~12.5 prob·s at N=20 (~800×); Kafka stays ~0 (the N=20 value is a single-host load-gen
  artifact, see §1.5†).
- **Cluster** — reported as *transport only* + an explicit limitation; single-host co-location
  confounds cluster TTI (§1.5).

### 7.2 Supporting — durability and corrections

| Phase | Result |
|-------|--------|
| Persistence H31/H32 (acks, AOF) | ✅ Stronger durability costs latency for both (Kafka `acks=all` > `acks=1`; Redis `appendfsync always` ≫ `everysec`) |
| S3 state-staleness corrections | ✅ 30 runs; correction propagation p50 ≈ 1,461 ms |
| Scenario sensitivity (S1–S5) | ✅ Replay speed / correction frequency sweeps, supportive |

### 7.3 Superseded / invalidated phases (kept for transparency)

All three were *reversed* by the measurement fixes in §1.1 — retained only to document the
methodology lesson, **not** as findings:

- ~~S2 frozen "Redis ≈71× faster"~~ — the ~2,008 ms "transport" was the cross-process clock
  offset. **Invalid (clock bug).**
- ~~Old concurrency sweep "Redis 40–55% faster" / 120× matrix~~ — clock offset + 120× producer
  saturation. **Invalid.**
- ~~`batch9` 60-run matrix "Kafka faster, d=−1.18"~~ — confounded by the Kafka load-generator
  asymmetry (`max_inflight=1`). **Superseded by the fair sweep (§7.1).**

---

## 8. Repository Structure

```
streaming-latency-sports/
├── README.md                       # ← this file (single source of truth)
├── LICENSE · CITATION.cff          # MIT + citation metadata
├── requirements.txt                # Python dependencies
├── .env                            # local environment (SB_COMMIT, etc.) — not committed
│
├── manuscript.tex                  # SAGE LaTeX manuscript (draft)
├── manuscript_references.bib       # bibliography (15 references)
├── sagej.cls · SageH.bst · SageV.bst   # SAGE journal template assets
├── temp_manuscript_template/       # SAGE template working copies
│
├── docker-compose.yml              # single-broker Kafka + Redis
├── docker-compose-multibroker.yml  # 3 Kafka brokers (KRaft)        — Issue 2
├── docker-compose-redis-cluster.yml# 3 Redis nodes (cluster)        — Issue 2
│
├── configs/
│   └── s3_injections.yaml          # S3 correction config
│
├── scripts/                        # producers, consumers, metrics, analysis (see §10)
│   ├── kafka_producer.py · kafka_consumer.py
│   ├── redis_producer.py · redis_consumer.py
│   ├── compute_tti.py · compute_s3_metrics.py · compute_s4_metrics.py
│   ├── analyze_s3_results.py · analyze_s4_results*.py · analyze_s5_*.py
│   ├── analyze_concurrency_sweep.py · run_concurrency_test.py
│   ├── verify_run_quality.py · check_concurrency_health.py
│   ├── validate_s3_outputs.py · validate_s4_outputs.py
│   ├── compare_plans.py · compare_experiments.py · make_results_table.py
│   ├── generate_manuscript_analysis.py
│   └── run_*_trial.ps1 · build_*_outputs.ps1   # Windows/PowerShell runners
│
├── data/
│   ├── raw/statsbomb/3bfbffe1.../  # source JSON (40,660 events)
│   └── processed/
│       ├── replay_plans/{s1,s2,s2full,s2sf12,s2sf12j2}/combined_plan.csv
│       └── results/                # aggregated result CSVs (paper_*.csv)
│
├── docs/
│   ├── infrastructure.md · literature_and_originality.md   # supporting docs
│   └── results/                    # GENERATED analysis outputs (CSV/PNG/PDF)
│       ├── realtime_concurrency/   # PRIMARY: fair sweep latency by backend/config/N
│       ├── decision_staleness_fair/# PRIMARY: AoI decision-staleness by backend/config/N
│       └── win_probability/ · actionability/ · ...         # supporting
│
├── runs/                           # per-run outputs + canonical run lists
│   ├── _paper_s2_official_runs.txt # canonical S2 list (frozen)
│   ├── _paper_s3_official_runs.txt # canonical S3 list
│   └── <run_id>/{meta.json, producer.csv, consumer.csv, tti_summary.json, *.log}
│
└── tests/
    ├── conftest.py                 # fixtures + kafka/redis mocks
    └── unit/                       # one test module per script (≥95% each)
```

> **Note:** `docs/results/**` holds **script-generated** tables and figures. They are
> regenerated whenever the analysis scripts run and are intentionally *not* folded into
> this README. `runs/`, `data/`, and `kafka_data/` (Kafka broker runtime state) hold large
> generated artifacts.

---

## 9. Quick Start & Running Benchmarks

### Setup

```bash
git clone https://github.com/<your-org>/streaming-latency-sports.git
cd streaming-latency-sports
python -m venv .venv && source .venv/bin/activate    # or .venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d                                  # single-broker Kafka + Redis
```

### Single trial

```bash
# Kafka
python scripts/kafka_producer.py --run-id my_run --plan-csv data/processed/replay_plans/s2sf12/combined_plan.csv --out runs/my_run
python scripts/kafka_consumer.py --run-id my_run --out runs/my_run

# Redis
python scripts/redis_producer.py --run-id my_run --plan-csv data/processed/replay_plans/s2sf12/combined_plan.csv --out runs/my_run
python scripts/redis_consumer.py --run-id my_run --out runs/my_run
```

### Windows / PowerShell runners (with timestamped debug output)

```powershell
./scripts/run_kafka_trial.ps1 my_run_001 data/processed/replay_plans/s2sf12/combined_plan.csv
./scripts/run_redis_trial.ps1 my_run_001 data/processed/replay_plans/s2sf12/combined_plan.csv
```

### Concurrency test

```bash
python scripts/run_concurrency_test.py 5 data/processed/replay_plans/s2sf12/combined_plan.csv 3
```

### Multi-broker (Issue 2)

```bash
docker compose -f docker-compose-multibroker.yml up -d        # 3 Kafka brokers
docker compose -f docker-compose-redis-cluster.yml up -d      # 3 Redis nodes
python scripts/kafka_producer.py  --broker-count 3 --run-id k_cluster_run ...
python scripts/redis_producer.py  --cluster-mode --node-count 3 --run-id r_cluster_run ...
```

### S3 corrections

```bash
python scripts/kafka_producer.py --run-id s3_test --plan-csv .../combined_plan.csv \
    --s3-mode corrections --corrections-every-k 50 --correction-delay-s 2.0
```

---

## 10. Testing & Quality

**Current state (June 17 2026): 830 tests passing, 99% total coverage, every script ≥95%.**
This includes the Issue 3–6 gap-filler scripts (`statistical_analysis.py`,
`power_analysis.py`, `analyze_protocol_overhead.py`, `analyze_actionability.py`,
`verify_reproducibility.py`) and the root health-check scripts (`verify_all_runs.py`,
`deep_health_check_final.py`).

```bash
python -m pytest tests/ -q                               # run all tests
python -m pytest tests/ --cov=scripts --cov-report=term-missing   # with coverage
python -m pytest tests/ --cov=scripts --cov-report=html  # HTML report → htmlcov/
```

### Per-script coverage

| Script | Coverage | Script | Coverage |
|--------|----------|--------|----------|
| analyze_batches_1_2_3.py | 99% | redis_consumer.py | 98% |
| analyze_concurrency_sweep.py | 99% | redis_producer.py | 99% |
| analyze_s3_results.py | 99% | run_concurrency_test.py | 99% |
| analyze_s4_results.py | 99% | validate_s3_outputs.py | 99% |
| analyze_s4_results_simple.py | 99% | validate_s4_outputs.py | 99% |
| analyze_s5_complete.py | 99% | verify_run_quality.py | 97% |
| analyze_s5_results.py | 98% | compare_plans.py | 99% |
| check_concurrency_health.py | 99% | compute_s3_metrics.py | 99% |
| compare_experiments.py | 97% | compute_s4_metrics.py | 97% |
| compute_tti.py | 99% | generate_manuscript_analysis.py | 99% |
| kafka_consumer.py | 97% | make_results_table.py | 98% |
| kafka_producer.py | 96% | | |

Remaining uncovered lines are `if __name__ == "__main__"` guards and a few hard-to-reach
error branches. External brokers are mocked in `tests/conftest.py`, so the suite runs
without Docker.

### Standards

- ≥95% line coverage for every script in `scripts/`.
- Each test isolates its own temp directory; happy paths *and* error paths covered.
- Cross-platform path handling (Windows + Unix); UTF-8-sig used for Windows-generated files.

### Run quality verification

`scripts/verify_run_quality.py` validates run outputs: required files present, producer/
consumer counts within tolerance, TTI physically reasonable (no negative medians, max
< 5 min), logs free of error patterns, and valid `meta.json`. `validate_s3_outputs.py`
and `validate_s4_outputs.py` validate phase-specific outputs.

---

## 11. Reproducibility

**No-guessing principle:** every paper number traces back through a committed CSV → build
script → canonical run list → committed code → environment snapshot.

Each run directory contains full provenance:

| File | Contents |
|------|----------|
| `meta.json` | git SHA, code hashes, config, timestamps, environment |
| `producer.csv` / `consumer.csv` | emit / receive timestamps |
| `tti_summary.json` | computed metrics (p50/p95/p99/max/mean/std/min, missed windows) |
| `consumer_events.csv` | S3 consumer event detail |
| `producer.log` / `consumer.log` | process logs |

**Canonical run lists:** `runs/_paper_s2_official_runs.txt`,
`runs/_paper_s3_official_runs.txt`, and the concurrency-sweep lists.

**Environment (reference):** Docker Desktop, Apache Kafka 4.1.1, Redis 7.2.4,
Python 3.9.13, dependencies pinned in `requirements.txt`. A full hardware/software
specification and a Zenodo archive are planned under Issue 6.

---

## 12. Manuscript & Paper Preparation

The manuscript targets the *Journal of Sports Analytics* using the SAGE LaTeX template.

| Asset | Purpose |
|-------|---------|
| `manuscript.tex` | Main manuscript (Intro, Lit Review, Methodology, Results, Discussion, Conclusion) |
| `manuscript_references.bib` | Bibliography (15 references) |
| `sagej.cls` | SAGE journal class |
| `SageH.bst` / `SageV.bst` | SAGE Harvard / Vancouver bibliography styles |
| `temp_manuscript_template/` | SAGE template working copies |

**Build:**

```bash
pdflatex -interaction=nonstopmode manuscript.tex
bibtex manuscript.aux
pdflatex -interaction=nonstopmode manuscript.tex
pdflatex -interaction=nonstopmode manuscript.tex
```

**Status:** a draft PDF exists (~4 pages). `manuscript.tex` currently has LaTeX
compilation errors that must be fixed before regeneration. Revision work to land in the
manuscript: RQs + hypotheses (Issue 1), sports thresholds + production comparison
(Issue 5), multi-broker methodology + corrected statistics (Issues 2/4), and reproducibility
details (Issue 6).

**Data Availability Statement:** all benchmark results, configs, and scripts are in this
repository; the StatsBomb dataset is public under CC BY-NC-4.0. Reproduction needs only
Docker, Python 3.9+, and Git.

---

## 13. Contributing

- **Branch naming:** `feat/`, `fix/`, `docs/`.
- **Python:** PEP 8, type hints, Google-style docstrings.
- **Shell:** `set -euo pipefail`, quote variables.
- **Research integrity:** follow the no-guessing principle — every number traceable to
  committed data and code; no hardcoded paths or credentials.

**Pull-request checklist:** style ✓ · docstrings + type hints ✓ · docs updated (this
README) ✓ · reproducibility preserved ✓ · **all tests pass and changed scripts stay
≥95% covered** ✓.

```bash
python -m pytest tests/ --cov=scripts --cov-report=term-missing
```

---

## 14. Citation

```bibtex
@article{streaming_latency_sports_2026,
  title   = {Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds},
  author  = {[To be completed]},
  journal = {Journal of Sports Analytics},
  year    = {2026}
}
```

**StatsBomb data (required):**

```bibtex
@misc{statsbomb_open_data,
  author       = {{StatsBomb}},
  title        = {StatsBomb Open Data},
  year         = {2018--2023},
  howpublished = {\url{https://github.com/statsbomb/open-data}}
}
```

---

## 15. License

**MIT License** — see [LICENSE](LICENSE).

| Component | License |
|-----------|---------|
| Custom code, docs, results | MIT |
| StatsBomb data | CC BY-NC-4.0 |
| Third-party libraries | Various (see `requirements.txt`) |

---

## 16. Changelog

### Unreleased — June 2026 (revision phase)
- **Jun 17** — Test suite brought to **715 passing / 99% coverage**, every script ≥95%;
  fixed 4 failing `analyze_s5_complete` tests; fixed a Windows UTF-8 crash in
  `analyze_s5_complete.py`; made `validate_s3_outputs.py` CLI testable. Consolidated ~18
  documentation files into this single README.
- **Jun 15** — **Issue 2 multi-broker infrastructure** built & verified:
  `docker-compose-multibroker.yml` (3 Kafka brokers, KRaft) and
  `docker-compose-redis-cluster.yml` (3 Redis nodes); multi-broker / cluster support in
  all producers/consumers and PowerShell runners. S2 audit confirmed the 120-run matrix
  cannot be compacted.
- **Jun 13** — Concurrency sweep complete (250 runs, S1–S5 × N=5,10,20).
- **Jun 12** — S3/S4/S5 analyses and methodology documentation completed; SAGE manuscript
  draft + bibliography created.

### 0.2.0 — 2025-12-31 — S2 Freeze Final
S2 paper-official block frozen (250 runs): canonical run list, build script, paper result
CSVs, plan-comparison tools. Tags: `paper-s2-freeze`, `paper-s2-freeze-final`.

### 0.1.0 — 2025-12-30 — S2 Initial Freeze
First S2 freeze: core producer/consumer/`compute_tti` scripts, runner scripts, S1 baseline
results.

### 0.0.1 — 2025-12-28 — Project Inception
Repository structure, `.gitignore`, StatsBomb integration, initial fetch/plan scripts.

---

## 17. Appendix: Acronyms & File Types

**Acronyms:** JSA = Journal of Sports Analytics · TTI = Time-to-Insight · SLO = Service
Level Objective · S1–S5 = experimental phases · AOF = Append-Only File (Redis) · KRaft =
Kafka Raft metadata mode · RF = replication factor · FWER = family-wise error rate ·
xG = expected goals.

**File types:** `.csv` data/results · `.json` metadata/metrics · `.parquet` efficient
storage · `.py` scripts · `.ps1` PowerShell runners · `.sh` bash scripts · `.yaml` config ·
`.tex`/`.bib`/`.bst`/`.cls` manuscript · `.txt` run lists/logs.

---

*Single-source README · last updated June 17, 2026 · target: Journal of Sports Analytics, Q1 2026.*
