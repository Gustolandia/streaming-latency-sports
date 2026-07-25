# Streaming Latency Benchmarks: Redis Streams vs Apache Kafka for Real-Time Sports Data Feeds

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Target: TOMPECS](https://img.shields.io/badge/Target-ACM%20TOMPECS-orange.svg)]()
[![Tests](https://img.shields.io/badge/tests-1262_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/branch_coverage-%E2%89%A595%25-brightgreen.svg)]()
[![StatsBomb Data](https://img.shields.io/badge/StatsBomb_Data-CC_BY--NC_4.0-blue.svg)](https://github.com/statsbomb/open-data)

> ## 🎯 Current target — the contribution
>
> **Paper:** [`paper.tex`](paper.tex) — *A Message Cannot Arrive Before It Is Sent:
> Physical-Consistency Auditing for Streaming Latency Benchmarks*. ACM format, targeting
> **ACM TOMPECS**. This is a **systems paper**; the football workload is the setting that
> produced the finding, not the contribution.
>
> **The original question** was: *compare end-to-end lag between Redis Streams and Apache Kafka
> for real-time sports data feeds, under varying concurrency, using the StatsBomb open dataset
> (2003–2023).* We answered it, and the answer was physically impossible.
>
> Broker delay subtracts a timestamp taken in the producer process from one taken in the
> consumer process, so it admits a check no statistic supplies: **it cannot be negative**.
> Applying that check to every run — not just the ones that looked wrong — rejected **1,321 of
> 2,266 runs (58%)**, including every run behind a large, significant, theory-confirming result
> we were about to publish.
>
> **Then a second headline failed too, and we withdrew it.** A twentyfold end-to-end gap we had
> reported turned out to be a per-run **start-up cost** read as a per-event constant: the runs
> behind it matched a *median of seven events each*. The integrity check does **not** catch that
> one — those runs are all causally consistent. Causal consistency is necessary, not sufficient.
>
> **What survives:**
> 1. The brokers are **equivalent within 1 ms** and neither degrades with concurrency — robust
>    to the audit's own unequal retention (bounded in [`retention_bias.py`](scripts/retention_bias.py)).
> 2. The failure model's four rules are **measured, not just derived**: inversions fall as the
>    measured quantity grows (ρ=−0.80), rise with process count (ρ=+0.80), follow M/G/1 waiting
>    in utilisation (ρ=0.98, R² 0.945 vs 0.640 linear) with the predicted knee, and — the rule
>    that bears on our own first result — a symmetric instrument shrinks the residual
>    between-system gap by 25% (+0.286→+0.215 ms), entirely on the asymmetric side. A construct
>    check confirms the mechanism is scheduling, not clock quantisation: inversions cluster in
>    time (runs-test z≈−6), even at idle.
> 3. Each system has **one client setting worth 1–2 orders of magnitude**, both free on a
>    co-located testbed and therefore invisible to how such settings are normally evaluated.
>
> **Why the JSA framing was retired.** Football is sparse (0.415 ev/s, ≤12 concurrent matches) —
> four orders of magnitude below where either broker strains. Every latency question aimed at
> this domain returns "doesn't matter", and it is right to. The work is a systems contribution;
> a sports-analytics paper would need a football question, not a latency one.

> **This README is the single source of truth for the project.** It consolidates what
> were previously ~18 separate planning, methodology, and status documents. Section 1
> below is the live snapshot — start there. Everything else is reference material that
> rarely changes.

---

## Table of Contents

1. [Current State & Objectives](#1-current-state--objectives) ← **start here**
2. [Abstract](#2-abstract)
3. [Research Questions](#3-research-questions)
4. [Dataset](#4-dataset)
5. [Architecture](#5-architecture)
6. [Methodology & Metrics](#6-methodology--metrics)
7. [Experimental Phases & Results](#7-experimental-phases--results)
8. [Repository Structure](#8-repository-structure)
9. [Quick Start & Running Benchmarks](#9-quick-start--running-benchmarks)
10. [Testing & Quality](#10-testing--quality)
11. [Reproducibility](#11-reproducibility)
12. [Paper Preparation](#12-manuscript--paper-preparation)
13. [Contributing](#13-contributing)
14. [Citation](#14-citation)
15. [License](#15-license)
16. [Changelog](#16-changelog)
17. [Appendix: Acronyms & File Types](#17-appendix-acronyms--file-types)

---

## 1. Current State & Objectives

**Last updated:** July 24, 2026 · **Branch:** `main` · **Target:** *ACM TOMPECS* (systems venue; the JSA framing was retired — see the header)

### 1.1 Where things stand

> ## ⚠️ Read this first: two headline results were withdrawn
>
> Broker transport is computed as *consumer receipt − broker acknowledgement*, two timestamps
> taken in two processes. A negative value is not noise — it is proof that the instrument
> failed. We audited **every** run against that constraint rather than only the ones whose
> results looked wrong, and the result reshaped the paper:
>
> | Corpus | Runs | Condemned | Conditions | Usable |
> |---|---:|---:|---:|---:|
> | Testbed A (single host, Windows) | 1,382 | **862** (62.4%) | 76 | 8 |
> | Testbed B (multi-host, Oracle Cloud) | 884 | **459** (51.9%) | 40 | 13 |
> | **Total** | **2,266** | **1,321** (58.3%) | 116 | 21 |
>
> The rule is in [`scripts/clock_integrity.py`](scripts/clock_integrity.py): a run is condemned
> if >1% of its events carry negative transport, or if any component median is negative. It
> exits non-zero so campaigns can gate on it.
>
> **What this cost us.** Our headline result had been *"Redis transport rises 34% with
> concurrency (p=6.7e-12, complete rank separation) while Kafka stays flat"* — internally
> consistent across 1,382 runs, matching the textbook prediction that a single-threaded server
> serialises concurrent streams, and surviving six prior rounds of correction. **Every condition
> behind it fails the gate.** The inversions are invisible in aggregate: only 5–14% of individual
> events invert, enough to bias a 0.34 ms effect and far too little to disturb any median or
> interval a reader would inspect.
>
> **Why it generalises.** The gate is a test against zero, so it condemns a measurement in
> proportion to how close that measurement sits to zero. Our network-delay arm, where the effect
> is *tens of seconds*, passes 15/15 on the same hardware minutes apart from conditions that fail
> outright. **The gate binds hardest exactly where the scientific question is most delicate** —
> which inverts the intuition that large, clean, highly significant effects are the trustworthy
> ones.

### 1.2 The answer, inside the gate

All numbers below are from **Testbed B** (four Oracle Cloud VMs, real inter-VM network), true
real-time replay, after gating. Concurrency levels are **derived from real kick-off schedules**
(§1.4), not chosen by hand.

**Claim 1 — The brokers are equivalent within 1 ms, but *not* indistinguishable — Redis is
reproducibly ~0.41 ms faster on transport.** The original E1 corpus reported them near-equal, but
its transport medians rest on the same **median of seven events per run** as the withdrawn
scheduling lag (the opening burst), so it is under-powered. A **powered replication** at a
verified real-time rate over a median of **127 events per run** (N∈{1,9,12}, 15 reps) resolves
what E1 could not:

| N | Kafka transport | Redis transport | HL shift [90% CI] |
|---:|---:|---:|---:|
| 1  | 0.512 ms | 0.099 ms | +0.409 [0.394, 0.421] |
| 9  | 0.539 ms | 0.115 ms | +0.418 [0.412, 0.424] |
| 12 | 0.540 ms | 0.114 ms | +0.420 [0.414, 0.425] |

TOST at a 1 ms margin passes at every N by all three estimators (Welch, bootstrap,
Hodges–Lehmann), so the brokers are **equivalent within the margin**; yet the HL shift is a
tight, reproducible **+0.41 ms** (Kafka slower, *p*<10⁻²⁶), flat across concurrency, so they are
**not a statistical tie**. Against a seconds-scale annotation budget, 0.41 ms is parts in 100,000
— noise for choosing a broker — but Redis's in-memory `XADD` really is several times faster per
operation than Kafka's replicated-log append (the grey-lit direction), and ~0.07 ms of the gap is
the callback instrument (H3), leaving a true broker difference near 0.34 ms. This *refines* E1 and
sharpens the reversal of the withdrawn accelerated result, which had had Redis **degrading** with N.

> ### ⚠️ Claim 2 — WITHDRAWN: the 20× end-to-end gap was a start-up cost
>
> We previously reported Kafka TTI 105.5 ms vs Redis 5.2 ms, with 102.9 ms of it producer
> scheduling lag, described as *constant — every event pays it*. **That does not reproduce.**
>
> A controlled re-run (N=1, verified true real time, same driver and broker) gives Kafka a median
> scheduling lag of **1.59 ms** with a **103.5 ms maximum**. Two independent instrumentation
> paths agree (per-event loop trace and per-run summary).
>
> **The discriminator is a count, not an average.** A median cannot separate a per-run cost from
> a per-event one, because how much of it the median sees depends on how many events the run
> holds — which is precisely what misled us. Sweeping the observation window at a verified
> real-time rate:
>
> | Window | Events emitted | Sched. lag p50 | max | Events >50 ms late | Blocking sends |
> |---|---|---|---|---|---|
> | 60 s | 57 | 1.57 ms | 103.5 ms | **4** | **1** |
> | 180 s | 148 | 1.60 ms | 103.4 ms | **4** | **1** |
> | 600 s | 507 | 1.59 ms | 103.5 ms | **4** | **1** |
>
> Events grow **8.9×**; the count does not move. The share of events paying the cost falls from
> 7.0% to 0.8%. A per-event constant would have grown the count and held the median at 103 ms.
>
> **The cause is in our own data, and the argument is arithmetic.** E1 replayed the first 600 s
> of match time, which in that plan holds **507 events**. It matched a **median of seven** — a
> match rate near one percent, so the window was never the problem, the join was. And a median of
> seven values at 102.93 ms requires **at least four of the seven** to be that high. The loop
> trace says exactly how many events per run are ever that late: four, always the same four,
> those due while the first send blocks. So the matched set is almost entirely the prologue.
>
> The mechanism, straight off the trace and identical in every run: event 0's first `produce()`
> blocks **102.6 ms** on metadata fetch and topic creation; the replay loop is single-threaded, so
> the four events due meanwhile wake ~103 ms late and then send in tens of microseconds; from
> event 5 it is steady state at ~1 ms. That the burst is exactly five is the sport, not the
> harness — every one of the eleven plans opens with at least five events at `t_sim=0`, because a
> kickoff is a pass, a ball receipt and a carry inside one second. A football feed delivers its
> densest burst precisely when the producer is coldest. Redis's `XADD` creates the stream in the
> same round trip and shows no prologue.
>
> It also retro-explains the three properties we offered as evidence, each of which a per-run
> cost predicts equally well: *constant* within a run, *concurrency-invariant* (one per run
> regardless of N), and *rate-dependent* (acceleration packs in more events and dilutes it).
>
> **The integrity gate does not catch this.** Every one of those runs is causally consistent,
> nothing is negative, and the medians are stable to three significant figures across a hundred
> runs — the artefact is deterministic, so it reproduces beautifully. Causal consistency is
> necessary and not sufficient. A percentile over single-digit samples describes the harness,
> not the system.

**Claim 3 — The measurement-failure model's rules, measured.** Four rules were derived from the
model (`docs/measurement_model.md`) and pre-registered with falsification criteria before the
data existed:

| | Rule | Result |
|---|---|---|
| **H1** | inversions fall as the measured quantity grows | ✅ ρ = **−0.80** |
| **H2** | inversions follow M/G/1 waiting in utilisation | ✅ ρ = **0.98**, R² **0.945** vs 0.640 linear |
| **H4** | inversions rise with concurrent process count | ✅ ρ = **+0.80** |
| **H3** | asymmetric stamping biases the comparison | ⚠️ **untested** — both clients stamp in callbacks |

H2's knee is measured, not just derived: inversion rate is flat (0.007–0.022) to ρ=0.5, then
climbs to 0.047 / 0.132 / 0.207 at ρ = 0.63 / 0.75 / 0.88, reaching 0.21–0.26 at saturation.

> **The methodological consequence:** a benchmark driven by a dense synthetic publisher measures
> the regime in which this difference is *absent*. Realistic arrival rate is not a nicety here —
> it is the condition under which the effect exists at all.

**Claim 4 — A network hop reverses the ordering.** Injecting one-way delay identically at both
brokers (`tc netem`), N=5. The Redis arm passes the gate 15/15 at every delay, precisely because
the effect dwarfs the instrument's floor.

| Injected delay | Kafka TTI | Kafka transport | Redis TTI | Redis transport | Gate (K / R) |
|---:|---:|---:|---:|---:|:--|
| 0 ms | *condemned* | — | *condemned* | — | 0/15 · 0/15 |
| 5 ms | 12.4 ms | 5.6 ms | 4,651 ms | 4,645 ms | 14/15 · 15/15 |
| 20 ms | 77.8 ms | 20.8 ms | **31,401 ms** | 31,268 ms | 12/15 · 15/15 |
| 50 ms | 336.6 ms | 44.9 ms | **103,143 ms** | 102,460 ms | 15/15 · 15/15 |

Kafka *tracks* the delay; Redis *amplifies* it ~900–2,050×. No run was truncated, so this is
amplification, not loss.

**Claim 5 — The mechanism is round-trip-bound acknowledgement, demonstrated by intervention at
realistic load and unexplained at 5× that load.**

| Condition | Per-message ack | Batched (200) | Improvement |
|---|---:|---:|:--|
| N=1, real-time, 20 ms delay | 4,138 ms | **103 ms** | **40.2×** |
| N=5, 10×, 20 ms delay | 68,960 ms | 73,598 ms | none (0.94×) |
| N=5, 10×, 50 ms delay | 87,624 ms | 92,386 ms | none (0.95×) |

At N=1 read-loop instrumentation shows the mechanism directly, and corrects it: each
`XREADGROUP` returns a *full* batch (median 106 messages) in ~32 ms, so the consumer is **not**
read-bound. The ceiling is entirely in the ack path — 200 × 20 ms = 4 s per batch, during which
it issues no reads at all (13 reads per run, 4 non-empty; batched: 37 reads, 25 non-empty).

> **⚠️ Open question we do not resolve.** The N=5 null is *not* explained by a gate failure — an
> earlier version of this README said it was, and that was wrong. The Redis arm passes 15/15; the
> manipulation check passed (the campaign script aborts otherwise); Kafka in the same runs sits at
> 78 ms. We claim the mechanism **at realistic football load**, where we have both the
> intervention and the read-loop evidence, and state plainly that its behaviour at 5× that load is
> unexplained.

**Claim 6 — Each system has exactly one client-side setting worth 1–2 orders of magnitude, and
in each case the idiomatic tutorial uses the slow value.**

| System | Setting | Slow (idiomatic) | Fast | Factor |
|---|---|---:|---:|---:|
| Kafka | producer `max.in.flight` | 1,644 ms (=1, sync send) | 16 ms (=64) | **103×** |
| Redis | consumer ack batching | 4,138 ms (per message) | 103 ms (200) | **40.2×** |

Both are **free on a local testbed** — pipelining and ack batching are irrelevant when the round
trip is 0.2 ms. A loopback benchmark prices both at zero and certifies as equivalent two clients
that differ by two orders of magnitude in deployment.

### 1.3 What we withdraw

| Arm | Status |
|---|---|
| Entire Testbed A (single host) — concurrency, throughput sweep, synthetic netem, ack batching, decision-staleness aggregates | ❌ **Withdrawn** (0/76 reported conditions pass) |
| Testbed B 10× concurrency sweep | ❌ Withdrawn (0–2 of 15–30 runs pass) |
| Connection sweep above N=10 | ❌ Withdrawn (at N=100 Kafka's median transport is **−6.4 ms**) |
| 3-node cluster arm | ❌ Withdrawn (0/15 runs, both backends) |
| Durability H31/H32 quantification | ⚠️ Direction only; magnitudes were Testbed A |
| E1 concurrency (real-time, gated) | ✅ **Reported** |
| Network delay arm (Redis 15/15) | ✅ **Reported** |
| E5 ack batching at N=1 (4 replications) | ✅ **Reported** |
| Workload characterisation (3,315 matches) | ✅ **Reported** (derived from event data, not from our instrument) |

### 1.4 The workload, and why it sets the parameters

From 3,315 StatsBomb matches across 52 competition-seasons (2003–2023), via
`characterize_feed.py` and `kickoff_concurrency.py`:

- **0.415 events/second** mean, **2.70/s** peak over a sliding 10 s window — a peak-to-mean ratio
  of **6.45**. Stable across all 15 competitions (0.35–0.44 ev/s, ratio 6.2–7.9) and between the
  men's and women's game (<7% apart). Sparsest competitions are the burstiest.
- **12 simultaneous kick-offs** at most, **21 matches in play** at once, across 2,346 kick-off
  instants — because leagues synchronise the final matchday by rule. This gives the benchmark's
  **N ∈ {1, 9, 10, 12}** instead of an invented sweep.
- ⚠️ Two caveats we restate wherever the number is used: StatsBomb open data *samples* matches, so
  observed simultaneity is a **lower bound**; and the bound is **per league** — a multi-league feed
  platform faces their sum. Our N ≤ 12 result characterises a single-competition consumer.

### 1.5 Primary objective

> **Benchmark Redis Streams against Apache Kafka for real-time football feeds on open StatsBomb
> data, at concurrency derived from the sport — and report honestly what survives a
> physical-consistency audit of our own instrument.** The gate is the paper's principal
> contribution; the benchmark is what it was applied to.

**Experimental strategy.** Each design choice closes a specific way the measurement could lie:

| Design choice | What it rules out |
|---|---|
| **Clock-integrity gate** (`clock_integrity.py`) | timestamps that violate causality under load |
| `time.time_ns()` shared epoch | cross-process clock offset |
| **True real-time replay** | a saturated driver being measured instead of the broker |
| Both producers pipelined (`--max-inflight`) | asymmetric client configuration |
| **Distinct match per feed** (`--plans-dir`) | concurrency secretly being throughput |
| **Concurrency derived from kick-off times** | an invented independent variable |
| Hodges–Lehmann + bootstrap | a heavy producer tail contaminating mean-based tests |
| Margins proportionate to the metric (1 ms transport, 40 ms TTI) | a margin so wide it cannot fail |
| **Manipulation check per intervention** | a null produced by a treatment that never applied |
| Multi-host testbed with real network + `tc netem` | a loopback path pricing round trips at zero |

---

## 2. Abstract

> **Title:** *A Message Cannot Arrive Before It Is Sent: Physical-Consistency Auditing for
> Streaming Latency Benchmarks, and What It Left of a Kafka-versus-Redis Comparison*
> **Target:** ICPE / DEBS (ACM sigconf, `paper.tex`)
> **Keywords:** streaming systems, latency benchmarking, measurement validity, Apache Kafka,
> Redis Streams, reproducibility

We set out to answer an ordinary question: for a real-time sports data feed, does the choice
between Apache Kafka and Redis Streams affect end-to-end delay, and how does that change with
the number of concurrent feeds? We built the benchmark, drove it with 3,315 real football
matches on their recorded event schedule, and obtained a clean answer — Redis broker delay rising
monotonically with concurrency while Kafka stayed flat, *p*=9.0×10⁻¹¹, no overlap between the
two systems' run distributions, exactly as a single-threaded server should behave.

It was an artefact. Broker delay subtracts a timestamp taken in the producer process from one
taken in the consumer process, so it admits a check no statistic supplies: the result cannot be
negative. Applying that check to every run rejected **1,321 of 2,266 runs**, including every run
behind the finding above. The rejected data is invisible to conventional inspection: medians
stay positive, intervals stay narrow, effect sizes stay large, and the direction agrees with
theory.

What survives is narrower than what we set out to find, and one more claim fell after the audit.
The two brokers are statistically equivalent within 1 ms on broker transport and neither degrades
across the concurrency range, robustly to the unequal retention the check itself introduces. Each
system has exactly one client setting worth one to two orders of magnitude in delay, both free on
a co-located testbed.

**Withdrawn.** An earlier version reported a twentyfold end-to-end gap, attributed it to client
code, and built a recommendation on it. It does not reproduce. The runs behind it matched a
median of seven events each, and a one-off producer start-up cost was being read as a per-event
constant — Kafka's first `produce()` blocks ~103 ms on metadata fetch and topic creation, and the
four kickoff events due while it blocks inherit that wait. A window sweep settles it by counting
rather than averaging: emitted events per run grow 8.9× while the number waking more than 50 ms
late stays at exactly four. The integrity check does **not** catch this one, which is the point.

**Also disclosed:** we cannot state the replay rate of the earliest cloud corpus. Plans carry a
baked-in 120× compression, so `--speedup 1` means 120×, not real time; the flag's semantics were
corrected 21 hours after those runs were made, and no surviving artefact records an achieved
rate. Both arms met the same rate, so the comparison is internally valid, but "at football's true
event rate" is not a claim the artefacts support. See §6.5 of the paper.

---

## 3. Research Questions

- **RQ1 (end-to-end lag)** — Replaying real match feeds on their recorded event schedule, what
  end-to-end lag do Kafka and Redis Streams deliver, and do they differ?
- **RQ2 (concurrency)** — Does that lag change across the concurrency levels football actually
  produces, and does either backend degrade faster?
- **RQ3 (attribution)** — Where does any difference live — broker transport, or the client path
  either side of it?
- **RQ4 (deployment conditions)** — Does the answer survive a network hop, and what mechanism
  governs the failure when it does not?
- **RQ5 (measurement validity)** — How much of a conventionally conducted benchmark survives an
  explicit physical-consistency check, and what does the condemned portion look like beforehand?

RQ5 is answered *first*, because its answer determines which evidence RQ1–RQ4 may draw on.

### 3.1 Statistical framework

- **Estimator:** Hodges–Lehmann shift with percentile-bootstrap CI (the Kafka producer's tail
  makes mean-based comparison a contrast of two differently contaminated estimators). Where
  Welch, bootstrap and HL disagree, the disagreement is reported.
- **Difference tests:** Mann–Whitney U per condition, Kruskal–Wallis across N, rank-biserial
  effect sizes. Latency distributions are non-normal throughout.
- **Equivalence:** TOST against margins fixed before testing and proportionate to the metric —
  **1 ms** for broker transport, **40 ms** (one broadcast frame) for end-to-end TTI.
- **Multiple comparisons:** Holm–Bonferroni at α=0.05, families declared over the design actually
  executed (four per-N comparisons on transport; the network arm separately; omnibus KW tests
  uncorrected; TOST outside all families).
- **Power:** per-cell *n* ranges 8–35. The N=1 cell (*n*=8) is treated as descriptive and said to
  be so wherever it appears.


---

## 4. Dataset

| Property | Value |
|----------|-------|
| Source | [StatsBomb Open Data](https://github.com/statsbomb/open-data) (CC BY-NC-4.0), pinned to commit `3bfbffe1de5750ebd47d770be0bb924a10cde54f` |
| Coverage | 2003–2023: **52 competition-seasons, 15 competitions, 3,315 matches** (2,806 men's, 509 women's) |
| Used for | *characterisation* — arrival rate, burstiness, kick-off concurrency (all 3,315 matches) |
| Used for | *benchmarking* — one distinct real match per concurrent feed, drawn from the corpus |
| Mean event rate | **0.415 events/second**; peak over a sliding 10 s window **2.70/s** (ratio 6.45) |
| Format | JSON (events, matches, competitions) → preprocessed to CSV replay plans |

Fetch with `scripts/fetch_statsbomb_corpus.py` (resumable, integrity-checked). Raw JSON is
**not** redistributed here; it is re-fetchable exactly from the pinned commit, and
`make_replay_plan.py` regenerates the committed plans byte-for-byte.

### Preprocessing & replay plans

Raw StatsBomb JSON is extracted into CSV **replay plans** under
`data/processed/replay_plans/<commit-sha>/match_<id>/replay_plan.csv` — one directory per
match, so a concurrency sweep can hand each feed a different real match (`--plans-dir`).
The earlier hand-curated plan sets (`s1/`, `s2/`, `s2sf12/`, …) have been removed: they were
subsets of a single 34-match season, and merging matches into one feed is what produced the
concurrency/throughput confound recorded in §7.3.

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

### 6.5 Decision-staleness — expressing milliseconds on a decision scale

⚠️ **Status: a lens, not a second measurement.** For a fixed corpus of decisive events this
metric is a *weighted rescaling of measured latency* — both backends are scored against the
identical model, so the ordering under it is the ordering under latency. It adds interpretation
and units, not inferential power, and the manuscript says so. The single-host decision-staleness
**aggregates are withdrawn** with the rest of Testbed A (§1.3); what the manuscript retains is
the per-event conversion applied to the gated numbers.

We translate delivery latency into in-play **decision error** in two steps:

1. **Win-probability proxy** (`scripts/win_probability.py`) — a transparent, calibrated in-play
   model on StatsBomb-derivable game state (score differential, fraction of match remaining,
   red-card differential), built on a Skellam (difference-of-Poissons) goal model. It cites
   Robberechts et al. (SIGKDD 2021) as the established model (their code is unreleased) and is
   validated by ranked probability score and a reliability diagram: **RPS = 0.142** and
   **ECE = 0.054** over 28,240 game states (`scripts/wp_calibration.py` →
   `docs/results/win_probability/wp_calibration.png`) — predicted win-probabilities track
   observed frequencies to within a few percentage points.
2. **Age-of-Information decision-staleness** (`scripts/decision_staleness.py`) — for each
   decisive event (goal), the consumer's win-probability is stale for the event's delivery
   latency *L* by the magnitude of the probability shift it caused. We define a run's
   **decision-staleness cost** = Σ over decisive events of `TV_shift × L` (units:
   probability-seconds per match), where `TV_shift = ½·(|ΔP_win| + |ΔP_draw| + |ΔP_loss|)`.

Worked on the gated numbers: the largest forecast move in the corpus is a 95th-minute equaliser
shifting the outcome distribution by 0.955 in total variation. At the ~0.8 ms broker transport
both systems deliver, that event costs under 0.001 probability-seconds; at the 31.4 s a
round-trip-bound consumer suffers behind a 20 ms hop, **30 probability-seconds**. The first is
decision-irrelevant and the second is not. (The earlier version of this worked example used the
105.5 ms / 5.2 ms end-to-end figures, which are **withdrawn** — see §1.2 Claim 2.)

The proxy is calibrated (ECE 0.054 over 28,240 game states) but **modest**: its skill over a
lookup table conditioned on nothing but the current goal difference is **+0.026**. It is a
calibrated yardstick, not a model of in-play win probability in any stronger sense, and the
manuscript describes it that way.

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
| `make_multimatch_plan.py` | a merged multi-match plan (note: merging N matches into one feed multiplies that feed's event rate — the concurrency/throughput confound described in §7.3) |

---

## 7. Experimental Phases & Results

The **reported results are in §1.2**, and **§1.3 lists what is withdrawn**. This section gives
the supporting detail and records the superseded phases for transparency.

### 7.1 Reported — the gated arms

Every arm below is on **Testbed B** (four Oracle Cloud VMs) and passes
`clock_integrity.py`. Retention is stated per arm because partial retention is selection.

| Arm | Protocol | Output | Retention |
|---|---|---|---|
| **E1 concurrency** | true real-time, distinct match per feed, N ∈ {1,9,10,12} | `docs/results/e1/` | 164/201 |
| **Network delay** | `tc netem` 5/20/50 ms applied identically to both, N=5 | `docs/results/cloud/net_d*/` | Redis 15/15; Kafka 12–15/15 |
| **E5 ack batching** | N=1 real-time, 20 ms delay, read-loop instrumented, 4 reps | `docs/results/e5/` | full |
| **Connections** | real-time, N=10 only | `docs/results/cloud/conn_n10/` | Kafka 10/10; Redis 7/10 |
| **Workload** | 3,315 matches, derived from event data not from our instrument | `docs/results/football/` | n/a |
| **Audit** | every run in the study | `docs/results/integrity_*.csv` | n/a |

### 7.2 Supporting — durability

| Phase | Result |
|-------|--------|
| Persistence H31/H32 (acks, AOF) | ⚠️ **Direction only.** Stronger durability costs latency for both (Kafka `acks=all` > `acks=1`; Redis `appendfsync always` ≫ `everysec`), but the magnitudes were measured on Testbed A and are withdrawn. A Testbed B replication is the most obvious extension. |
| S3 state-staleness corrections | ⚠️ Testbed A; withdrawn |
| Scenario sensitivity (S1–S5) | ⚠️ Testbed A; withdrawn |

### 7.3 Superseded / invalidated phases (kept for transparency)

Retained to document the methodology lesson, **not** as findings. The first three were reversed
by ordinary debugging; the fourth is the one this paper is about, because nothing in its output
revealed the problem.

- ~~S2 frozen "Redis ≈71× faster"~~ — the ~2,008 ms "transport" was a cross-process clock
  offset (`perf_counter_ns` is process-relative). **Invalid.**
- ~~Old concurrency sweep / 120× matrix~~ — clock offset plus producer saturation. **Invalid.**
- ~~`batch9` 60-run matrix "Kafka faster, d=−1.18"~~ — Kafka load-generator asymmetry
  (`max_inflight=1` blocking per event). **Invalid.**
- ~~"Redis transport rises 34% with concurrency, *p*=6.7e-12, complete rank separation"~~ —
  **condemned by the clock-integrity gate.** This one passed every check above, agreed with
  architectural theory, and was the intended headline. See §1.1.

---

## 8. Repository Structure

```
streaming-latency-sports/
├── README.md                       # ← this file (single source of truth)
├── LICENSE · CITATION.cff          # MIT + citation metadata
├── requirements.txt                # Python dependencies
├── .env                            # local environment (SB_COMMIT, etc.) — not committed
│
├── paper.tex                       # ACM paper (ICPE/DEBS target)
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

The paper targets **ACM TOMPECS** using the ACM `acmart` class (`sigconf`). The earlier SAGE / Journal of Sports Analytics framing was retired; see the header for why.

| Asset | Purpose |
|-------|---------|
| `paper.tex` | The paper (ACM sigconf; Intro, Related Work, Setting, Method, First Answer, Audit, Results, Discussion) |
| `manuscript_references.bib` | Bibliography |
| `acmart.cls` | ACM article class (from TeX Live/MiKTeX) |
| `SageH.bst` / `SageV.bst` | SAGE Harvard / Vancouver bibliography styles |
| `temp_manuscript_template/` | SAGE template working copies |

**Build:**

```bash
pdflatex -interaction=nonstopmode paper.tex
bibtex paper
pdflatex -interaction=nonstopmode paper.tex
pdflatex -interaction=nonstopmode paper.tex
```

**Status:** compiles clean — 0 errors, 0 undefined references or citations, no overfull boxes,
14 pages. Title: *Streaming Latency Benchmarks for Real-Time Football Feeds: Redis Streams
versus Apache Kafka, and the Physical-Consistency Gate That Invalidated Our First Answer*.

**Every headline number is pinned to its artefact** by
`tests/unit/test_manuscript_consistency.py`, which recomputes the figures from the committed
CSVs and fails if the manuscript and the data disagree. That test exists because an earlier
revision withdrew an entire measurement arm as invalid and then kept quoting one of its
figures (1.35 ms) in the abstract, while the conclusion quoted a different value for the same
quantity. Source-level proofreading missed it three times. The suite also asserts that no
condemned figure appears anywhere without being marked as condemned, and that the abstract and
conclusion agree on the headline.

**⚠️ Bibliography audit (July 2026).** Ten entries in `manuscript_references.bib` could not be
located in any publisher, arXiv or index record when checked — among them `pappas2020real`,
`opta2023`, `zhang2021tti`, `pandey2021comparative`, `zhang2022redis`, `he2020performance`,
`gai2020kafka`, `carbone2015benchmark`, `wright2022machine` and `link2021deep`, plus several
philosophy-of-computing entries that were never load-bearing. **The manuscript no longer cites
any of them.** Twelve verified references were added in their place (Lamport 1978; Mills 1991;
Corbett et al. 2013; Jain 1991; Schuirmann 1987; Lakens 2017; Hodges & Lehmann 1963; Efron 1979;
Mann & Whitney 1947; Kruskal & Wallis 1952; Pappalardo et al. 2019; Mohammad 2025), and two
existing entries were corrected — `redis2017streams` had the author misspelled, and
`kafka_analysis_2025` was attributed to "Anonymous" when the arXiv record names Muzeeb Mohammad.
The stale entries are left in the `.bib` rather than deleted so the removal is auditable; they
are simply uncited. **Verify every remaining citation before submission.**

**Remaining before submission:** mint the Zenodo DOI (`scripts/zenodo_deposit.py` stops at an
unpublished draft by design — publishing is an irreversible public action and is left to a
human).

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
  note    = {Preprint; targeting ICPE/DEBS},
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

### Unreleased — July 2026 (revision phase)
- **Jul 22** — **Manuscript rebuilt around the clock-integrity finding.** Retitled; the audit
  is now Sections 5–6 rather than a caveat. Every result section rewritten against gated data
  only; the withdrawn arm is presented as evidence for RQ5 instead of as an apology. Added
  `tests/unit/test_manuscript_consistency.py` (21 tests) pinning every headline number to its
  CSV, plus `scripts/make_e1_figure.py` (+13 tests). Corrected a claim we had got wrong: the
  N=5 acknowledgement-batching null is **not** a gate failure — that arm passes 15/15 — so it
  is now reported as an unexplained open question. Recomputed the staleness budget from gated
  data (it had been computed from a withdrawn figure). README brought into line throughout.
- **Jul 21** — Clock-integrity gate applied uniformly to all 2,266 runs; 1,321 condemned.
  Entire single-host arm withdrawn. E1 re-measured at true real-time on the multi-host testbed.
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

**Acronyms:** TTI = Time-to-Insight · ICPE = Int. Conf. on Performance Engineering · DEBS = Distributed and Event-Based Systems · SLO = Service
Level Objective · S1–S5 = experimental phases · AOF = Append-Only File (Redis) · KRaft =
Kafka Raft metadata mode · RF = replication factor · FWER = family-wise error rate ·
xG = expected goals.

**File types:** `.csv` data/results · `.json` metadata/metrics · `.parquet` efficient
storage · `.py` scripts · `.ps1` PowerShell runners · `.sh` bash scripts · `.yaml` config ·
`.tex`/`.bib`/`.bst`/`.cls` manuscript · `.txt` run lists/logs.

---

*Single-source README · last updated July 22, 2026 · target: ICPE / DEBS.*
