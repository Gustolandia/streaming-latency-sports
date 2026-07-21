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
> 4. **Concurrency-vs-throughput confound (our own design).** The first "fair" sweep replayed the
>    *same merged ten-match plan* on every feed, so its "N=5" applied ~10× the load of five real
>    matches — a concurrency axis that was secretly a throughput axis. Fixed by giving each feed a
>    **distinct real match** (`--plans-dir`), which reversed the concurrency finding. See §1.5.
>
> **Current finding (artifact-free) — and it is *conditional*:**
> **Co-located** (broker and consumer on one host): Kafka and Redis are **statistically
> equivalent** (TOST, one-frame margin) at every concurrency level, with no concurrency effect;
> Redis's single-thread serialization only appears at ~2,100 events/s (~4,800 simultaneous
> matches), far beyond any football deployment.
> **Networked:** injecting delay equally at both brokers breaks that equivalence. Redis Streams
> consumption is **round-trip bound**, so it amplifies delay 500–1,500× (75 s of TTI at 50 ms
> injected) while Kafka tracks it (94 ms). By 20 ms, Redis imposes **275× more decision-staleness**
> — decision-corrupting. **A loopback benchmark cannot see this.** See §1.5.

| Area | Status | Notes |
|------|--------|-------|
| Measurement fixes (clock, saturation, Kafka pipelining, concurrency/throughput confound) | ✅ **Fixed & validated** | `time.time_ns()`; non-blocking dispatch; `--max-inflight`; `--plans-dir` distinct matches |
| **Original contribution** (WP proxy + AoI decision-staleness) | ✅ **Built & tested** | `win_probability.py` + `decision_staleness.py`; calibrated (ECE 0.054) |
| Distinct-match concurrency corpus | ✅ **Complete** | N∈{1,5,10}, 18/15/30 runs per backend, full match, all goals |
| Throughput sweep (locates the knee) | ✅ **Complete** | one config, speed varied → `docs/results/throughput/` |
| Equivalence (TOST) + model sensitivity | ✅ **Complete** | equivalence 3/3 levels; difference invariant to the WP model |
| True 1× real-time validation | ✅ **Complete** | `--speedup 0.008333` cancels the plan's baked 120× |
| **Network realism (`tc netem`)** | ✅ **Complete** | 0/5/20/50 ms injected equally → `docs/results/netem/`; **breaks equivalence ≥20 ms** |
| Plan generation salvaged into main | ✅ **Complete** | `make_replay_plan.py` reproduces committed plans byte-for-byte |
| Red cards as decisive events | ✅ **Complete** | dismissals move the WP model, so they now count |
| Cluster claims | ⛔ **Withheld** | single-host co-location confounds them; not reported |
| Test suite | ✅ **≥95% branch coverage** | every script in `scripts/` + root health checks |
| Persistence H31/H32 (acks / AOF) | ✅ Complete | 12 runs; both hypotheses supported |
| Manuscript reframe around decision-degradation | ✅ **Complete** | 11 pp, compiles clean |
| All pre-fix runs (S1–S5, old concurrency, 120 matrix, `batch9`) | ❌ **Invalidated** | superseded by the fair, distinct-match corpus |

### 1.2 Primary objective

> **Establish, on open data, whether streaming-infrastructure latency degrades in-play
> football decisions — and if so, at what load — then submit to the *Journal of Sports
> Analytics*.** The broker comparison is the independent variable; the decision quantity
> (win-probability staleness) is the result.

**Experimental strategy.** One protocol answers it, with each design choice closing a
specific way the measurement could lie:

| Design choice | What it rules out |
|---|---|
| `time.time_ns()` shared epoch | cross-process clock offset |
| Non-saturating replay speed | load generator, not broker, being measured |
| Both producers pipelined (`--max-inflight`) | asymmetric client configuration |
| **Distinct match per feed** (`--plans-dir`) | concurrency secretly being throughput |
| Throughput sweep (fix N, vary speed) | conflating the two axes when locating the knee |
| TOST vs a pre-specified margin | mistaking "not detected" for "not there" |
| WP scoring-rate sweep | the conclusion depending on the proxy model |
| True 1× replay | the "real-time" claim resting on compressed time |
| **Injected network delay** (`tc netem`) | a loopback testbed hiding a round-trip-bound design |

### 1.3 How the original referee concerns are addressed

The paper is now framed around the decision-degradation contribution (🎯 target) rather than
"answering six criticisms," but each original concern is still handled — on the *fair*,
artifact-free corpus:

| Referee concern | How it is addressed now |
|---|---|
| Intro reads like a product description; no RQs/hypotheses | RQ1–RQ4 + hypotheses + stats framework in `manuscript.tex` |
| Single-broker comparison unfair to distributed Kafka | Single **and** cluster measured; cluster treated as a stated single-host limitation (a true multi-host test needs separate machines — §1.5) |
| No message-size / protocol-overhead controls | Payload ~170 B and (de)serialization ~µs are near-identical across backends (`analyze_protocol_overhead.py`) |
| Weak statistics | Holm–Bonferroni Mann–Whitney + Kruskal–Wallis + effect sizes on the fair corpus (`fair_statistics.py`); power caveat retained |
| Sports angle feels post-hoc | The contribution **is** a sports quantity — win-probability decision-staleness (`win_probability.py` + `decision_staleness.py`), calibrated (ECE 0.054) |
| Reproducibility under-documented | `docs/infrastructure.md`, per-run provenance (`verify_reproducibility.py`), and a regenerable `reproducibility/MANIFEST.json` (`generate_manifest.py`); Zenodo DOI still to mint |

### 1.5 Main claims (fair, artifact-free corpus)

All numbers below come from the **fair** sweep — both producers pipelined, replay at a
non-saturating 10× — on the **single host, single node** (the regime we can measure cleanly).
Latency is median (p50) over feeds × 3 reps; `transport` = broker delivery, `TTI` = end-to-end
(identical definition for both backends). See [[measurement-artifacts]] for why every pre-fix
number is excluded.

**Claim 1 — At a single live feed, Kafka and Redis are equivalent (~17 ms).** The folk belief
(and our own contaminated "Redis 71× faster" headline) that one backend is simply faster is
wrong: for one match they are statistically indistinguishable and both excellent for real time.

**Claim 2 — Across the entire *realistic* range, neither backend degrades, and they are
statistically indistinguishable.** With each feed carrying a **different real match** at true
per-match event rates, latency is flat and backend choice is undetectable:

| N (distinct concurrent matches) | Kafka transport p50 | Redis transport p50 | Kafka TTI p50 | Redis TTI p50 | Kafka vs Redis |
|---:|---:|---:|---:|---:|---|
| 1  | 1.00 ms | 1.01 ms | 11.4 ms | 10.3 ms | n.s. (*p*=0.68) |
| 5  | 1.00 ms | 1.20 ms | 14.7 ms | 8.4 ms  | n.s. (*p*=0.60) |
| 10 | 1.00 ms | 1.35 ms | 9.2 ms  | 11.7 ms | n.s. (*p*=0.68) |

Kruskal–Wallis finds **no concurrency effect for either backend** (Kafka *p*=0.70, Redis *p*=0.20).
N=1 is powered at *n*=18 per backend.

**Claim 2b — Redis *does* serialize, but only far outside realistic load.** Football event data
is intrinsically low-rate: **0.44 events/second/match**. Expressing every tested load in
*simultaneous real-time match equivalents* locates the boundary:

Measured by a **dedicated throughput sweep** (10 distinct matches, varying only replay speed, so
aggregate event rate is the sole variable — `docs/results/throughput/`):

| Aggregate load | ≈ real-time matches | Kafka transport | Redis transport |
|---:|---:|---:|---:|
| 531 ev/s | ~1,200 | 1.1 ms | 1.5 ms |
| 1,062 ev/s | ~2,400 | 1.7 ms | 2.5 ms |
| 2,124 ev/s | ~4,800 | 93 ms | **492 ms** |
| 4,248 ev/s | ~9,600 | 4,598 ms† | 3,775 ms† |
| 8,496 ev/s | ~19,200 | 4,442 ms† | 5,793 ms† |

Both sit near 1–2.5 ms up to ~1,000 ev/s (~2,400 matches). Divergence first appears at
**~2,100 ev/s (~4,800 matches)**, where Redis is ~5× Kafka — the single-thread serialization
penalty. († Past ~4,000 ev/s both collapse into seconds and the ordering *reverses*, so the host
— not the broker — is the constraint; those rows bound the testbed.) For scale, the top five
European leagues field roughly 50 simultaneous matches on a busy weekend.

**Claim 3 (the contribution) — Infrastructure latency does not degrade in-play football
decisions in any realistic deployment.** Decision-staleness (probability-seconds per match),
distinct matches, all decisive events:

| N | Kafka-single | Redis-single | Kafka vs Redis |
|---:|---:|---:|---|
| 1  | 0.014 | 0.012 | n.s. (*p*=0.67) |
| 5  | 0.018 | 0.014 | n.s. (*p*=0.67) |
| 10 | 0.014 | 0.014 | n.s. (*p*=0.65) |

A goal's win-probability is stale by ~0.014 prob·s (~12 ms) regardless of backend or
concurrency — **decision-irrelevant**, and it directly contradicts the industry "2-second edge"
framing across the whole realistic operating envelope. **The first measured answer to "when does
streaming-infrastructure latency actually degrade an in-play football decision?" is: not at any
load a football operator will ever see.** The architectural difference is real but only bites
at ~4,800 match-equivalents. Practical guidance: choose the backend on operational grounds
(durability, ops familiarity, cost), not latency.

**⚠️ The condition that breaks equivalence: network latency**
([`docs/results/netem/`](docs/results/netem)). Everything above co-locates broker and consumer,
so transport is loopback. Injecting one-way delay **identically at both brokers** (`tc netem`)
does *not* affect them equally:

| injected delay | Kafka TTI | Redis TTI | Kafka staleness | Redis staleness | Equivalent? |
|---:|---:|---:|---:|---:|:--|
| 0 ms | 12.1 ms | 10.5 ms | 0.018 | 0.019 prob·s | ✅ |
| 5 ms | 15.5 ms | 42.8 ms | 0.022 | 0.051 prob·s | ✅ (marginal) |
| 20 ms | 44.5 ms | **10,525 ms** | 0.058 | **15.97 prob·s** | ❌ |
| 50 ms | 93.6 ms | **74,962 ms** | 0.119 | **110.1 prob·s** | ❌ |

Kafka **tracks** the delay; single-node Redis **amplifies** it 500–1,500×. No run was truncated
(all delivered the full event set), and the amplification implies an effective batch of ~7
events per round trip at 20 ms and ~2.5 at 50 ms: **Redis Streams consumption is round-trip
bound**, so each added millisecond is multiplied across thousands of sequential cycles, while
Kafka amortises it across batched fetches. **A loopback benchmark cannot see this** — which is
exactly why we ran it.

**So the headline is conditional:** co-locate consumers and the backends are equivalent and
decision-irrelevant; put a network hop in between and Kafka is strongly preferable, because by
20 ms Redis imposes **275× more decision-staleness** — enough to corrupt an in-play decision.

**Validated at true 1× real time** ([`docs/results/realtime_1x/`](docs/results/realtime_1x)).
Everything above replays a compressed clock, so we repeated N=5 at **genuine real time**
(`--speedup 0.008333` cancels the plan's baked 120×; 10 min of match clock took 10 min of wall
clock — verified by elapsed time). Kafka 15.5 ms vs Redis 13.8 ms TTI, against 14.7/8.4 ms
compressed, and **TOST equivalence still holds**. Time compression does not bias the comparison.

**Equivalence, not just "no difference"** ([`docs/results/equivalence/`](docs/results/equivalence)).
A non-significant test doesn't prove equality, so we run **TOST** against a *pre-specified*
margin — one broadcast frame (40 ms; 0.04 prob·s for staleness). **Equivalence is established at
3/3 concurrency levels for both metrics**: the 90% CI of the Kafka−Redis difference is at most
±5 ms against the 40 ms margin, and ±0.01 against the 0.04 prob·s margin. So the claim is
positive — the backends are *equivalent within a frame*, not merely "not shown to differ".

**Robust to the win-probability model** ([`docs/results/wp_sensitivity/`](docs/results/wp_sensitivity)).
Sweeping the proxy's scoring rate 1.0→1.6 moves absolute staleness ~12% (ECE stays 0.049–0.062),
but the **Kafka−Redis difference is invariant** (0.00101 → 0.00103 prob·s). Both backends are
scored against the *same* model, so it scales both sides — the comparison is model-independent.

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
   validated by ranked probability score and a reliability diagram: **RPS ≈ 0.24** and
   **ECE = 0.054** over 3,239 game states from the 34 matches (`scripts/wp_calibration.py` →
   `docs/results/win_probability/wp_calibration.png`) — predicted win-probabilities track
   observed frequencies to within a few percentage points.
2. **Age-of-Information decision-staleness** (`scripts/decision_staleness.py`) — for each
   decisive event (goal), the consumer's win-probability is stale for the event's delivery
   latency *L* by the magnitude of the probability shift it caused. We define a run's
   **decision-staleness cost** = Σ over decisive events of `TV_shift × L` (units:
   probability-seconds per match), where `TV_shift = ½·(|ΔP_win| + |ΔP_draw| + |ΔP_loss|)`.

This is the metric behind §1.5 Claim 3 and the paper's contribution: it converts an
infrastructure quantity (latency) into a sports quantity (degraded win-probability).

**Supporting analyses.** Because the headline is a *negative* result, three scripts exist
specifically to keep it honest:

| Script | Question it answers |
|---|---|
| `equivalence_tests.py` | Is this equivalence, or just failure to detect? (TOST vs a pre-specified one-frame margin) |
| `wp_sensitivity.py` | Does the conclusion depend on the win-probability proxy? (sweeps the scoring rate; the between-backend difference is invariant) |
| `wp_calibration.py` | Is the proxy any good? (reliability diagram + ECE) |
| `make_worked_example.py` | What does one goal's staleness actually look like? (Leverkusen's 95' equaliser) |

**Decisive events** are goals (own goals credited to the opponent) **and red cards**. Dismissals
belong in the metric because the win-probability model already conditions on the red-card
differential, so a sending-off moves the forecast exactly as a goal does; excluding them would
under-count the staleness a feed can carry. Events are replayed in match order, so a goal's
shift is evaluated against the game state left by any earlier dismissal.

**Regenerating the corpus from scratch.** The replay plans are shipped as data *and* as code:

| Script | Produces |
|---|---|
| `make_replay_plan.py` | one match's plan from raw StatsBomb events (verified to reproduce the committed plans byte-for-byte) |
| `make_multimatch_plan.py` | a merged multi-match plan (note: merging N matches into one feed multiplies that feed's event rate — the confound described in §1.5) |

---

## 7. Experimental Phases & Results

The **main results are in §1.5** (fair corpus). This section gives the supporting detail and
records the superseded phases for transparency.

### 7.1 Primary — distinct-match concurrency + decision-staleness

**Protocol:** both producers pipelined (Kafka `--max-inflight 64`; Redis async worker pool),
**each feed replaying a different real match** (`--plans-dir`) at its true event rate, full
match so every decisive event lands, N ∈ {1, 5, 10}, 18/15/30 runs per backend.

| Output | Contents |
|---|---|
| `docs/results/realtime_concurrency_distinct/` | latency by backend/N |
| `docs/results/decision_staleness_distinct/` | decision-staleness by backend/N |
| `docs/results/equivalence/` | **TOST** equivalence vs a one-frame margin |
| `docs/results/throughput/` | throughput sweep locating Redis's knee |
| `docs/results/wp_sensitivity/` | conclusion vs the WP model's free parameter |

- **Latency** — both ~1 ms transport / ~10 ms TTI at every N; no significant difference, no
  concurrency effect (§1.5 Claim 2).
- **Decision-staleness** — ~0.014 prob·s everywhere, backend-independent (§1.5 Claim 3).
- **Equivalence** — established 3/3 levels for both metrics (not merely "no difference").
- **Where Redis *does* lose** — only at ~2,100 ev/s (~4,800 real-time matches); past ~4,000 ev/s
  the single host saturates and the ordering reverses, so those points bound the testbed.
- **Cluster** — *transport only* + explicit limitation; single-host co-location confounds it.

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
