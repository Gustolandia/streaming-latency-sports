# When the Interval Is Smaller Than the Instrument

*Two ways streaming latency benchmarks fail on sub-millisecond paths, and what they left of a Kafka-versus-Redis comparison.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Target: TC](https://img.shields.io/badge/Target-IEEE%20Transactions%20on%20Computers-orange.svg)]()
[![Tests](https://img.shields.io/badge/tests-3650_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/branch_coverage-100%25-brightgreen.svg)]()
[![StatsBomb Data](https://img.shields.io/badge/StatsBomb_Data-CC_BY--NC_4.0-blue.svg)](https://github.com/statsbomb/open-data)
[![DOI (code)](https://img.shields.io/badge/DOI_code-10.5281%2Fzenodo.21650031-blue.svg)](https://doi.org/10.5281/zenodo.21650031)
[![DOI (data)](https://img.shields.io/badge/DOI_data-10.5281%2Fzenodo.21650064-blue.svg)](https://doi.org/10.5281/zenodo.21650064)

> **Archived versions (Zenodo).** Code and analysis:
> [10.5281/zenodo.21650031](https://doi.org/10.5281/zenodo.21650031) · measurement dataset:
> [10.5281/zenodo.21650064](https://doi.org/10.5281/zenodo.21650064). These are the **concept
> DOIs**: they never change and always resolve to the newest version, which is what the paper
> cites. They currently resolve to v2.6.0, whose version DOIs are code
> [10.5281/zenodo.22102716](https://doi.org/10.5281/zenodo.22102716), data
> [10.5281/zenodo.22102832](https://doi.org/10.5281/zenodo.22102832); v2.5.0 was code
> [10.5281/zenodo.22044877](https://doi.org/10.5281/zenodo.22044877), data
> [10.5281/zenodo.22044891](https://doi.org/10.5281/zenodo.22044891).
> v1.0.0 was the arXiv-submission state: code
> [10.5281/zenodo.21650032](https://doi.org/10.5281/zenodo.21650032), data
> [10.5281/zenodo.21650065](https://doi.org/10.5281/zenodo.21650065).

> **Frozen vs. living.** The Zenodo records above are the immutable version of record: built
> from git tag `v2.6.0`, with SHA256 manifests of every file. This repository
> is the living copy and moves ahead of them. To verify the paper's claims against the exact
> data behind them, use the Zenodo zips or `git checkout v2.6.0`; the concept DOIs always
> resolve to the newest archived version.

> ## 🎯 Current target — the contribution
>
> **Paper:** [`paper.tex`](paper.tex) — *When the Interval Is Smaller Than the Instrument:
> Two Ways Streaming Latency Benchmarks Fail on Sub-Millisecond Paths*. IEEE format
> (`IEEEtran`, journal), targeting **IEEE Transactions on Computers**, with a companion `supplement.tex`. This is a
> **systems paper**; the football workload is the setting that produced the finding, not the
> contribution.
>
> **The original question** was: *compare end-to-end lag between Redis Streams and Apache Kafka
> for real-time sports data feeds, under varying concurrency, using the StatsBomb open dataset
> (2003–2023).* We answered it, and then had to withdraw the answer.
>
> Broker delay subtracts a timestamp taken in the producer process from one taken in the
> consumer process, so it admits a check no statistic supplies: **the sign**. A negative value
> is not physically impossible here — the acknowledgment stamp is a late, producer-side
> observation of a broker-side event, so that component is a proxy, not a causal chain. What a
> negative does prove is that the reference stamp cannot serve as the origin of that event's
> interval, and a run whose reference is unusable on more than one event in a hundred cannot
> report a latency, whatever the cause.
> Applying that check to every run — not just the ones that looked wrong — rejected **1,321 of
> 2,266 runs (58%)**, including every run behind a large, significant, theory-confirming result
> we were about to publish.
>
> **Then a second headline failed too, and we withdrew it.** A twentyfold end-to-end gap we had
> reported turned out to be a per-run **start-up cost** read as a per-event constant: the runs
> behind it matched a *median of seven events each*. The integrity check does **not** catch that
> one — those runs are all causally consistent. Causal consistency is necessary, not sufficient.
>
> **The title's second failure mode is not that withdrawal — it lives in software we did not
> write: silent sample deletion.** The OpenMessaging Benchmark admits a sample only if a
> millisecond-quantised difference is positive, and counts nothing it drops. Across **223
> instrumented runs** it computed its distribution from **0.36% to 100%** of the samples it
> took, with the same reported median either way; retention follows the grid arithmetic of the
> send-interval-to-quantum ratio, not chance. The audit deciding whether the discards are benign
> is a sign bit: the Kafka-driver corpus's discards contain not one negative, while the
> Redis-driver replication caught **41,403 genuine one-tick negatives**, absorbed without trace.
> Artifacts: [`external/omb/`](external/omb/) and the measurement data record
> [10.5281/zenodo.21650064](https://doi.org/10.5281/zenodo.21650064).
>
> **What survives:**
> 1. The brokers are **equivalent within 1 ms** and neither degrades with concurrency — robust
>    to the audit's own unequal retention (bounded in [`retention_bias.py`](scripts/retention_bias.py)).
> 2. The mechanism is **established by manipulation, on both sides of the inequality**:
>    `P(inversion) = P(scheduling stall > T_true)`. Raising the stamping threads to `SCHED_FIFO`
>    at *fixed* utilisation collapses the rate 7–80× across eight matched pairs; two load geometries
>    at **identical ρ to four decimals** differ 2.07× (z=10.3), so utilisation cannot be the
>    variable; lengthening true transport 77× *lowers* the rate 4.1×, which no stress-based
>    account predicts; and a `sched_switch` trace predicts the measured rate to within 30%,
>    unfitted. The stall distribution's **effective span exponent is ≈0.33–0.34** over the
>    measured 0.25–2 ms span, steepening beyond ~4 ms; across that span the sample mean is
>    dominated by the largest stalls observed, which is why mean-based counters are structurally
>    blind to this failure. An earlier draft's unconditional infinite-moment ("no finite mean or
>    variance") reading is withdrawn.
>    *Withdrawn:* the M/G/1 functional form. Once the sweep reached ρ where the candidate forms
>    diverge, M/G/1 fit **worse than the mean** (R² −0.05 vs a fitted exponential's 0.93). An
>    earlier revision of this README advertised it as a surviving rule; it is refuted, not merely
>    unsupported.
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

**Last updated:** August 26, 2026 · **Branch:** `main` · **Target:** *IEEE Transactions on Computers* (systems venue; the JSA, TOMPECS and TPDS framings were retired — see the header)

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
> concurrency (p=9.0×10⁻¹¹, complete rank separation) while Kafka stays flat"* — internally
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
| **H2** | inversions follow M/G/1 waiting in utilisation | ❌ **refuted.** The early ladder stopped at ρ=0.878 and could not separate the forms. Extending it to ρ=0.990, where they diverge, M/G/1 fits *worse than the mean* (R² −0.05 vs a fitted exponential's 0.93) |
| **H4** | inversions rise with concurrent process count | ✅ ρ = **+0.80** |
| **H3** | asymmetric stamping biases the comparison | ✅ **replicated** (E-C3, then E-C4). Gap **+0.286 → +0.215 ms** (−25%), moving entirely on the asymmetric side: Kafka 0.392 → 0.322, Redis holds ≈0.106 |

The *monotone* dependence on utilisation is measured and survives the refutation above — it is
only the M/G/1 functional form that fails. The rate is flat (0.007–0.022) to ρ=0.5, then climbs
to 0.047 / 0.132 / 0.207 at ρ = 0.63 / 0.75 / 0.88, reaching 0.21–0.26 at saturation. Later
campaigns show why the curve was never the mechanism: at **identical ρ** two load geometries
differ 2.07×, so ρ cannot be the variable, and a function of ρ cannot return two values for one
input. See [`docs/laws.md`](docs/laws.md).

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

> **Title:** *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
> Benchmarks Fail on Sub-Millisecond Paths*
> **Target:** IEEE Transactions on Computers (`IEEEtran`, journal, `paper.tex`)
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

The Zenodo code archive ([10.5281/zenodo.21650031](https://doi.org/10.5281/zenodo.21650031))
**excludes** `data/processed/replay_plans/` — the plans are CC BY-NC 4.0 derivatives of
StatsBomb data and cannot ship inside the MIT-licensed record. Regenerate them byte-for-byte
with `scripts/make_replay_plan.py` against the pinned upstream commit.

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
`s3_uid` / `s3_rev` / `s3_is_correction` envelope. The flags are the whole interface — an
accompanying `configs/s3_injections.yaml` existed but no code ever read it, and it was removed
with the rest of the S-era scaffolding. The producers still support the mode; every S3 *result*
belongs to Testbed A and is withdrawn (§1.1).

### 6.5 Decision-staleness — removed with the sports framing

**This analysis is no longer part of the work.** It translated delivery latency into in-play
decision error through a calibrated win-probability proxy and an age-of-information staleness
cost, and it belonged to the Journal of Sports Analytics framing described in the header. When
that framing was retired the five scripts behind it (`win_probability.py`, `wp_calibration.py`,
`wp_sensitivity.py`, `decision_staleness.py`, `make_worked_example.py`) and their result
directories were deleted in commit `67efbfa`, along with 28 other obsolete scripts.

They are recoverable from git history if anyone wants them, and the reason they went is worth
recording rather than hiding: the conversion was a *weighted rescaling of measured latency*.
Both backends were scored against the identical model, so the ordering under the staleness
metric was the ordering under latency. It added interpretation and units, not inferential power
— and once the paper became a systems paper about measurement validity, interpretation in
football units was no longer what the results needed.

What survives from that line of work is the observation that makes the sports setting worth
mentioning at all: football event feeds are sparse (0.415 ev/s, at most ~12 concurrent matches)
and their end-to-end budget is dominated by human annotation measured in seconds, so a
sub-millisecond broker difference cannot matter to the domain. That is stated in the paper as
the reason the original question has a boring answer, and it needs no win-probability model.

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
- ~~"Redis transport rises 34% with concurrency, *p*=9.0×10⁻¹¹, complete rank separation"~~ —
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
├── paper.tex                       # IEEE paper (Trans. Computers target, IEEEtran) + supplement.tex
├── manuscript_references.bib       # bibliography (123 entries; 45 cited in the paper, at TC's cap)
│
├── docker-compose.yml              # single-broker Kafka + Redis
├── docker-compose-multibroker.yml  # 3 Kafka brokers (KRaft)        — Issue 2
├── docker-compose-redis-cluster.yml# 3 Redis nodes (cluster)        — Issue 2
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
│   ├── audit_external_harness.py · harness_registry.py   # third-party harness audit
│   ├── emit_paper_numbers.py · kernel_constants.py       # the macro ledger
│   ├── clocksource_bound.py                             # which clocksource,
│   │                                                    #   bounded from a measurement
│   ├── make_paper_figures.py · make_result_figures.py    # figures, from artefacts
│   ├── recount_spans.py                                 # per-span negatives + the
│   │                                                    #   shared-stamp contrast
│   ├── generate_manuscript_analysis.py
│   └── run_*_trial.ps1 · build_*_outputs.ps1   # Windows/PowerShell runners
│
├── data/
│   ├── raw/statsbomb/3bfbffe1.../  # source JSON (40,660 events)
│   └── processed/
│       ├── replay_plans/3bfbffe1.../match_<id>/replay_plan.csv   # eleven plans, one dir per match
│       └── results/                # aggregated result CSVs (paper_*.csv)
│
├── docs/
│   ├── infrastructure.md · laws.md · measurement_model.md        # environment + the model
│   ├── general_model.md · two_state_model.md · grey_literature_review.md
│   ├── preregistration_depth.md · omb_distributed_issue.md · supplement_index.md
│   ├── section67_rewrite_draft.md · v2_plan.md                   # working drafts
│   ├── referee_response_plan.md · response_to_referee_tpds.md · referee_response_letter.md
│   └── results/                    # GENERATED analysis outputs (CSV/PNG/PDF)
│       ├── realtime_concurrency/   # PRIMARY: fair sweep latency by backend/config/N
│
├── runs/                           # per-run outputs + canonical run lists
│   ├── _paper_s2_official_runs.txt # canonical S2 list (frozen)
│   ├── _paper_s3_official_runs.txt # canonical S3 list
│   └── <run_id>/{meta.json, producer.csv, consumer.csv, tti_summary.json, *.log}
│
└── tests/
    ├── conftest.py                 # fixtures + kafka/redis mocks
    └── unit/                       # one test module per script (100% each)
```

> **Note:** `docs/results/**` holds **script-generated** tables and figures. They are
> regenerated whenever the analysis scripts run and are intentionally *not* folded into
> this README. `runs/`, `data/`, and `kafka_data/` (Kafka broker runtime state) hold large
> generated artifacts.

---

## 9. Quick Start & Running Benchmarks

### Setup

```bash
git clone https://github.com/Gustolandia/streaming-latency-sports.git
cd streaming-latency-sports
python -m venv .venv && source .venv/bin/activate    # or .venv\Scripts\Activate.ps1
pip install -r requirements.txt
docker compose up -d                                  # single-broker Kafka + Redis
```

For a faster clone use `git clone --filter=blob:none <url>` — the history carries superseded
run outputs.

### Single trial

```bash
SHA=3bfbffe1de5750ebd47d770be0bb924a10cde54f
PLAN=data/processed/replay_plans/$SHA/match_3895052/replay_plan.csv

# Kafka
python scripts/kafka_producer.py --run-id my_run --plan-csv "$PLAN" --out runs/my_run
python scripts/kafka_consumer.py --run-id my_run --out runs/my_run

# Redis
python scripts/redis_producer.py --run-id my_run --plan-csv "$PLAN" --out runs/my_run
python scripts/redis_consumer.py --run-id my_run --out runs/my_run
```

### Windows / PowerShell runners (with timestamped debug output)

```powershell
./scripts/run_kafka_trial.ps1 my_run_001 data/processed/replay_plans/3bfbffe1de5750ebd47d770be0bb924a10cde54f/match_3895052/replay_plan.csv
./scripts/run_redis_trial.ps1 my_run_001 data/processed/replay_plans/3bfbffe1de5750ebd47d770be0bb924a10cde54f/match_3895052/replay_plan.csv
```

### Concurrency test

```bash
# --plans-dir hands each feed a distinct real match (the positional plan is only a fallback);
# see reproducibility/README.md §4 for the full Testbed B invocation (rate, pipelining, gate).
python scripts/run_concurrency_test.py 5 "$PLAN" 3 \
    --plans-dir data/processed/replay_plans/$SHA
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
python scripts/kafka_producer.py --run-id s3_test --plan-csv "$PLAN" \
    --s3-mode corrections --corrections-every-k 50 --correction-delay-s 2.0
```

---

## 10. Testing & Quality

**Current state (August 2026): every script in `scripts/` at 100% branch coverage.**
The June 17 2026 snapshot (830 tests, 99% total coverage) included the Issue 3–6 gap-filler
scripts (`statistical_analysis.py`, `power_analysis.py`, `analyze_protocol_overhead.py`,
`analyze_actionability.py`, `verify_reproducibility.py`) and the root health-check scripts
(`verify_all_runs.py`, `deep_health_check_final.py`); the v2 campaign-analysis scripts are
held to the same standard.

```bash
python -m pytest tests/ -q                               # run all tests
python -m pytest tests/ --cov=scripts --cov-report=term-missing   # with coverage
python -m pytest tests/ --cov=scripts --cov-report=html  # HTML report → htmlcov/
```

### Per-script coverage (June 2026 snapshot; later scripts meet the same gate)

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

- **100% branch coverage** for every script in `scripts/`, enforced by CI.
  What may be excluded from that number is enumerated and justified in
  `tests/unit/test_coverage_exclusions.py`: a `__main__` dispatch may hold only calls
  and imports, and every other exclusion needs a written reason. 100% bought with
  pragmas would be worse than an honest 95%, so the exclusions are gated too.
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
Python 3.9.13 (development now also runs on 3.12), dependencies pinned in
`requirements.txt`. The full hardware/software specification is in
[`docs/infrastructure.md`](docs/infrastructure.md), and the Zenodo archive exists
(v2.0.0, 2026-08-07: code [10.5281/zenodo.21836305](https://doi.org/10.5281/zenodo.21836305),
data [10.5281/zenodo.21836326](https://doi.org/10.5281/zenodo.21836326)).

---

## 12. Manuscript & Paper Preparation

The paper targets **IEEE Transactions on Computers** using the IEEE `IEEEtran` class
(`journal`, 10pt). The earlier SAGE / Journal of Sports Analytics, ACM TOMPECS and IEEE TPDS
framings were retired; see the header for why. TC allows regular papers 10-12 double-column
pages *including references and biography*, and caps references at 45, so the manuscript is
held inside that budget by test gates and the overflow lives in a companion supplement
compiled from the same commit.

| Asset | Purpose |
|-------|---------|
| `paper.tex` | The paper (`IEEEtran`, journal; Intro, Related Work, Setting, Method, First Answer, Audit, Second Failure Mode, What Survives, Discussion, Conclusion) |
| `supplement.tex` | Companion supplement S1–S35 (`docs/supplement_index.md` maps what moved where) |
| `manuscript_references.bib` | Bibliography |
| `IEEEtran.cls` | IEEE article class (from TeX Live/MiKTeX) |

**Build:**

```bash
pdflatex -interaction=nonstopmode paper.tex
bibtex paper
pdflatex -interaction=nonstopmode paper.tex
pdflatex -interaction=nonstopmode paper.tex
python scripts/check_rendered_pdf.py paper.pdf
```

Then the supplement, **in that order and not before**:

```bash
pdflatex -interaction=nonstopmode supplement.tex
bibtex supplement
pdflatex -interaction=nonstopmode supplement.tex
pdflatex -interaction=nonstopmode supplement.tex
```

The order is a real constraint, not a convention. The supplement refers to the main text's
sections, tables and equations by label, and `\usepackage{xr}` resolves them by reading
`paper.aux` — so a supplement built before the paper silently renders those references as the
literal `??`. Six of them reached the built PDF before round 42, in the one document the main
text sends a reader to when they want the evidence. `TestNoCrossReferenceDangles` fails on any
`??` in either rendered PDF, so a build in the wrong order is caught on the artefact rather
than trusted to the procedure.

That check, like the one above it, reads the *rendered* PDF rather than the source. A dropped backslash turns
`\ref{tab:ea6}` into the literal text `ef{tab:ea6}` and `\texttt{x}` into `exttt{x}`; LaTeX
reports no error, the source still looks plausible, and the defect appears only in the output.
That failure reached the manuscript three times here, twice past a full source-level check, which
is why the check now runs on the artefact a reader actually receives.

**Status:** compiles clean — 0 errors, 0 undefined references or citations, 0 overfull boxes,
11 pages against TC's 10–12 budget, exactly 45 references against TC's cap of 45, and a
195-word abstract against TC's 100–200 range, with a 41-page supplement. Title: *When the
Interval Is Smaller Than the Instrument: Two Ways Streaming Latency Benchmarks Fail on
Sub-Millisecond Paths*. Formatted with `IEEEtran` (journal, 10pt) for IEEE Transactions on
Computers.

Two of the four gates write as well as check. `scripts/emit_paper_numbers.py` generates both
`docs/generated/paper_numbers.tex` (the macros the manuscript quotes) and
`docs/generated/grid_table.tex` (Table II in full), and `--check` fails the build if either
disagrees with the artefacts. The table is generated because the transcribed version drifted
from the correction its own caption claimed: it printed raw permutation p-values under a
caption promising Holm correction, and one arm changed verdict between the two. A number that
reaches the page without passing through a script is the one that goes wrong.

**Every headline number is pinned to its artefact** by
`tests/unit/test_paper_consistency.py`, which recomputes the figures from the committed
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

**Archival (done 2026-08-07):** the Zenodo records are minted and published — v2.0.0 code
[10.5281/zenodo.21836305](https://doi.org/10.5281/zenodo.21836305) and data
[10.5281/zenodo.21836326](https://doi.org/10.5281/zenodo.21836326). `scripts/zenodo_deposit.py`
stops at an unpublished draft by design — publishing is an irreversible public action, and the
final click was a human one.

**Adversarial review rehearsal.** Before submission, the manuscript was stress-tested through
simulated adversarial referee rounds authored inside the project
([`docs/referee_response_plan.md`](docs/referee_response_plan.md),
[`docs/response_to_referee_tpds.md`](docs/response_to_referee_tpds.md),
[`docs/referee_response_letter.md`](docs/referee_response_letter.md)). These are internal QA
artefacts written to journal standards; the paper has not yet been submitted to any venue, and
no document in this repository contains real journal correspondence.

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
100% covered** ✓.

```bash
python -m pytest tests/ --cov=scripts --cov-report=term-missing
```

---

## 14. Citation

```bibtex
@article{ricou2026interval,
  author  = {Ricou, Gustavo Pedro and Gregg, David},
  title   = {Faster Than Light, According to the Arithmetic: Two Ways a Streaming Benchmark Fails on Sub-Millisecond Paths},
  year    = {2026},
  note    = {Manuscript targeting IEEE Transactions on Computers;
             code and data archived at \url{https://doi.org/10.5281/zenodo.21650031}}
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
| Manuscript files (`paper.tex`/`.pdf`, `supplement.tex`/`.pdf`) | © the author, **not** MIT — pending journal publication |
| Replay plans (`data/processed/replay_plans/`, StatsBomb-derived) | CC BY-NC 4.0 |
| StatsBomb data | CC BY-NC-4.0 |
| Third-party libraries | Various (see `requirements.txt`) |

---

## 16. Changelog

### 2.6.0 — 2026-08-25 — Transactions on Computers submission package
Fourteen further rounds of adversarial internal review, all of them on presentation and
provenance: **no result, estimate or interval differs from v2.5**. A figure for Mode B's
mechanism (8 figures, not 7); every printed quantity emitted from the committed artefacts
rather than typed; eight new gates, each demonstrated failing on the defect it guards before
that defect was repaired; and *retention* defined where the paper defines its other terms.
The artifact line now cites the **concept** DOIs, which never change and always resolve to the
newest version. Zenodo v2.6.0 archived from tag `v2.6.0`: code
[10.5281/zenodo.22102716](https://doi.org/10.5281/zenodo.22102716), data
[10.5281/zenodo.22102832](https://doi.org/10.5281/zenodo.22102832). Paper 12 pp, supplement
46 pp, 45/45 references. 3,650 tests pass at 100% branch coverage.

### 2.5.0 — 2026-08-21 — retarget to IEEE Transactions on Computers
Manuscript rebuilt for **TC** (10–12 pp, 45-reference cap) and reorganised around what the
evidence supports rather than the chronology of finding mistakes. The central correction of
this release: the acknowledgment-referenced span is a **proxy, not a causal chain**, so a
negative value is a late reference stamp rather than impossible physics — the sign check is
justified by the reference stamp being unusable as an origin. Mode B's arithmetic conceded to
its prior art in counter metrology (HP Application Note 162-1, 1970). Zenodo v2.5.0: code
[10.5281/zenodo.22044877](https://doi.org/10.5281/zenodo.22044877), data
[10.5281/zenodo.22044891](https://doi.org/10.5281/zenodo.22044891). 2,501 tests green.

### 2.0.0 — 2026-08-07 — TPDS restructure + Zenodo deposit
Manuscript restructured for **IEEE TPDS** (`IEEEtran` journal, 16-page ceiling test-enforced,
39-page companion supplement); the OMB silent-deletion arm (the paper's second failure mode)
integrated. Zenodo v2.0.0 archived from tag `v2.0.0` (commit `bebabec`) with SHA256 manifests:
code [10.5281/zenodo.21836305](https://doi.org/10.5281/zenodo.21836305), data
[10.5281/zenodo.21836326](https://doi.org/10.5281/zenodo.21836326). 2,275 tests green.

### 1.0.1 — 2026-07-28 — Zenodo DOIs wired in
The minted v1 Zenodo DOIs wired into `CITATION.cff`, README badges and the paper; software and
dataset records cross-linked.

### 1.0.0 — 2026-07-28 — arXiv-submission state, first Zenodo archive
The arXiv-submission state of the manuscript; first Zenodo records (code
[10.5281/zenodo.21650032](https://doi.org/10.5281/zenodo.21650032), data
[10.5281/zenodo.21650065](https://doi.org/10.5281/zenodo.21650065)).

### July 2026 (revision phase; released in v1.0.0)
- **Jul 22** — **Manuscript rebuilt around the clock-integrity finding.** Retitled; the audit
  is now Sections 5–6 rather than a caveat. Every result section rewritten against gated data
  only; the withdrawn arm is presented as evidence for RQ5 instead of as an apology. Added
  `tests/unit/test_paper_consistency.py` (21 tests) pinning every headline number to its
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

**Acronyms:** TTI = Time-to-Insight · TC = IEEE Transactions on Computers · TPDS = IEEE Transactions on Parallel and Distributed Systems · OMB = OpenMessaging Benchmark · SLO = Service
Level Objective · S1–S5 = experimental phases · AOF = Append-Only File (Redis) · KRaft =
Kafka Raft metadata mode · RF = replication factor · FWER = family-wise error rate ·
xG = expected goals.

**File types:** `.csv` data/results · `.json` metadata/metrics · `.parquet` efficient
storage · `.py` scripts · `.ps1` PowerShell runners · `.sh` bash scripts · `.yaml` config ·
`.tex`/`.bib`/`.bst`/`.cls` manuscript · `.txt` run lists/logs.

---

*Single-source README · last updated August 26, 2026 · target: IEEE Transactions on Computers.*
