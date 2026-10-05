# Super-Precise Latency: How CPU Threading Affects High-Precision Latency, and an Industry-Wide Audit

*How a thread's wait for a processor core distorts sub-millisecond broker latencies, the laws that govern it, what the industry's benchmark tools do with the result, and how to fix it.*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Target: TC](https://img.shields.io/badge/Target-IEEE%20Transactions%20on%20Computers-orange.svg)]()
[![Tests](https://img.shields.io/badge/tests-8214_passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/branch_coverage-100%25-brightgreen.svg)]()
[![StatsBomb Data](https://img.shields.io/badge/StatsBomb_Data-CC_BY--NC_4.0-blue.svg)](https://github.com/statsbomb/open-data)
[![DOI (code)](https://img.shields.io/badge/DOI_code-10.5281%2Fzenodo.21650031-blue.svg)](https://doi.org/10.5281/zenodo.21650031)
[![DOI (data)](https://img.shields.io/badge/DOI_data-10.5281%2Fzenodo.21650064-blue.svg)](https://doi.org/10.5281/zenodo.21650064)

> **Archived versions (Zenodo).** Code and analysis:
> [10.5281/zenodo.21650031](https://doi.org/10.5281/zenodo.21650031) · measurement dataset:
> [10.5281/zenodo.21650064](https://doi.org/10.5281/zenodo.21650064). These are the **concept
> DOIs**: they never change and always resolve to the newest version, which is what the paper
> cites. They currently resolve to **v3.0.0**, the four-author release, whose version DOIs are
> code [10.5281/zenodo.22307766](https://doi.org/10.5281/zenodo.22307766), data
> [10.5281/zenodo.22307882](https://doi.org/10.5281/zenodo.22307882); v2.7.0 was code
> [10.5281/zenodo.22215274](https://doi.org/10.5281/zenodo.22215274), data
> [10.5281/zenodo.22215330](https://doi.org/10.5281/zenodo.22215330); v2.6.0 was code
> [10.5281/zenodo.22102716](https://doi.org/10.5281/zenodo.22102716), data
> [10.5281/zenodo.22102832](https://doi.org/10.5281/zenodo.22102832); v2.5.0 was code
> [10.5281/zenodo.22044877](https://doi.org/10.5281/zenodo.22044877), data
> [10.5281/zenodo.22044891](https://doi.org/10.5281/zenodo.22044891).
> v1.0.0 was the arXiv-submission state: code
> [10.5281/zenodo.21650032](https://doi.org/10.5281/zenodo.21650032), data
> [10.5281/zenodo.21650065](https://doi.org/10.5281/zenodo.21650065).
> Version 4.0.0, the one this README and the paper's Artifact Availability section describe,
> was prepared on 29 Sep 2026 and is not yet deposited (§16).

> **Frozen vs. living.** The Zenodo records above are the immutable version of record: the
> current ones were built from git tag `v3.0.0`, with SHA256 manifests of every file. This
> repository is the living copy and moves ahead of them. To verify the paper's claims against
> the exact data behind them, use the Zenodo zips or check out the tag of the version the paper
> names (`v4.0.0` for the current paper, cut when that version is deposited); the concept DOIs
> always resolve to the newest archived version.

> ## 🎯 Current target — the contribution
>
> **Paper:** [`paper.tex`](paper.tex) — *Super-Precise Latency: How CPU Threading Affects
> High-Precision Latency, and an Industry-Wide Audit*. IEEE format (`IEEEtran`, journal),
> targeting **IEEE Transactions on Computers**, with its supplementary material in
> [`supplement.tex`](supplement.tex) and the complete record of how the results were obtained in
> [`postmortem.tex`](postmortem.tex), which is archived with the data and not submitted. Since
> 5 October 2026 it is built around four bottom lines:
>
> 1. **The distribution.** After a broker writes a message it acknowledges it to the producer
>    and delivers it to the consumer; on one machine and one clock the two readings should
>    coincide. Their difference *S* = *t*_recv − *t*_ack spreads over milliseconds and falls
>    below zero for 62,264 of 738,730 messages (8.43%), while no latency timed from the publish
>    call ever does.
> 2. **The mechanism and its laws.** A thread waits for a core before it reads the clock, its
>    scheduling delay. *S* < 0 exactly when the publish latency exceeds the end-to-end latency;
>    to leading order the rate is the timestamping thread's waiting probability times the chance
>    that its residual wait outlasts the end-to-end latency; and the scheduler's base slice, 3 ms
>    on our eight-CPU hosts, sets the timescale. Real-time priority cut the rate 7–80× at
>    unchanged utilization, two placements of one load at the same utilization differ 2.07×, a
>    longer path lowers the rate 4.1×, and a kernel trace predicts the rate with nothing fitted.
> 3. **The industry-wide audit.** Sixteen tools: seven of the ten read at source dispose of a
>    latency at or below zero without counting it, and ten of the eleven run take both
>    timestamps in one process, so they cannot measure a one-way latency. A positivity filter on
>    a millisecond clock printed a median of exactly 1.0 or 2.0 ms in 71 of 75 settings, computed
>    from as little as 0.36% of the samples. None of 43 public reports states how many samples it
>    kept.
> 4. **What to do.** Time from the publish call or add the publish latency back, sign-check
>    every run, give the threads that read the clock a core, print the retention and the
>    discards by sign, and randomize the publish instants. A better-synchronized clock fixes
>    neither problem.
>
> **The original question** was: *compare end-to-end lag between Redis Streams and Apache Kafka
> for real-time sports data feeds, under varying concurrency, using the StatsBomb open dataset
> (2003–2023).* We answered it, found that the measurement could not carry the answer, and the
> paper became about the measurement. The paper and supplement as they stood before the rebuild,
> with the withdrawn results and the broker comparison, are kept in
> [`docs/archive/2026-10-05-before-cleanup/`](docs/archive/2026-10-05-before-cleanup/README.md),
> and what is known in the literature about each bottom line is in
> [`docs/literature_review_2026-10-05.md`](docs/literature_review_2026-10-05.md).

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

**Last updated:** October 1, 2026 · **Branch:** `main` · **Target:** *IEEE Transactions on Computers* (systems venue; the JSA, TOMPECS and TPDS framings were retired — see the header)

### 1.1 Where things stand

> ## ⚠️ Read this first: two headline results were withdrawn
>
> The transport proxy *S* is computed as *consumer receipt − acknowledgment*, two timestamps
> written by two threads in two processes that read one clock. A negative value is not noise:
> it shows that the acknowledgment cannot serve as the origin of that message's latency (paper
> Section IV-A). We applied the sign check to **every** run rather than only to the ones whose
> results looked wrong, and the result reshaped the paper:
>
> | Corpus | Runs | Rejected | Conditions | Usable |
> |---|---:|---:|---:|---:|
> | Workstation (Testbed A: one Windows host, brokers in Docker under WSL2) | 1,382 | **862** (62.4%) | 76 | 8 |
> | Cloud (Testbed B: four Oracle Cloud VMs) | 884 | **459** (51.9%) | 40 | 13 |
> | **Total** | **2,266** | **1,321** (58.3%) | 116 | 21 |
>
> The rule is in [`scripts/clock_integrity.py`](scripts/clock_integrity.py): a run is rejected
> if more than 1% of its events carry a negative value in any latency component, or if the
> median of any component is negative, and a condition is usable only if all of its runs
> survive (paper Section II-C). It exits non-zero so campaigns can gate on it.
>
> **What this cost us.** Our headline result had been *"Redis transport rises 34% with
> concurrency (p=9.0×10⁻¹¹, complete rank separation) while Kafka stays flat"*, measured on the
> workstation testbed at ten times real speed, matching the textbook prediction that a
> single-threaded server serialises concurrent streams, and surviving six prior corrections, a
> fairness audit and a full battery of rank tests, effect sizes and multiplicity correction.
> **The sign check rejects 109 of the 126 runs behind it, and none of its six conditions is
> usable.** The negative spans are invisible in aggregate: only 5–14% of individual events
> invert, enough to bias a 0.34 ms effect and far too little to disturb any median or interval
> a reader would inspect.
>
> **Why it generalises.** The sign check is a test against zero, so it rejects a measurement in
> proportion to how close that measurement sits to zero. Our network-delay arm, where the effect
> is *tens of seconds*, passes 15/15 on the same hardware minutes apart from conditions that fail
> outright. **The sign check binds hardest exactly where the scientific question is most delicate** —
> which inverts the intuition that large, clean, highly significant effects are the trustworthy
> ones.

### 1.2 The answer, inside the gate

All numbers below are from **Testbed B**, the cloud testbed (four Oracle Cloud VMs, real
inter-VM network; producer and consumer on one host, reading one clock), true real-time
replay, after the sign check. Concurrency levels are **derived from real kick-off schedules**
(§1.4), not chosen by hand.

**Claim 1 — On the transport proxy the brokers sit within 1 ms, but they are *not*
indistinguishable: Redis is about 0.41 ms faster.** The original E1 corpus reported them
near-equal, but its transport medians rest on the same **median of seven events per run** as
the withdrawn publish delay (the opening burst), so it is under-powered. A **powered campaign** at a
replay rate derived from the plan and verified against wall time, over a median of **125
events per run** (N∈{1,9,12}, 15 replicates each), resolves what E1 could not. Over the runs
the sign check keeps (postmortem S2):

| N | Events/run | Kafka *S* | Redis *S* | HL shift [90% CI] |
|---:|---:|---:|---:|---:|
| 1  | 148 | 0.512 ms | 0.102 ms | +0.408 [0.389, 0.419] |
| 9  | 112 | 0.542 ms | 0.120 ms | +0.416 [0.408, 0.423] |
| 12 | 121 | 0.540 ms | 0.114 ms | +0.417 [0.408, 0.424] |

TOST at a 1 ms margin passes at every N by all three estimators (Welch, bootstrap,
Hodges–Lehmann; Welch TOST *p*<10⁻²⁶ at each N), so the brokers are **equivalent within the
margin**; yet the shift's 90% interval lies far from zero at every N, Kafka slower, and the
shift is flat across concurrency, so they are **not a statistical tie**. On the end-to-end
latency *E*, which is a causal chain, they are equivalent against a 40 ms margin (one broadcast
frame, fixed three days before the campaign): Hodges–Lehmann shifts of 0.682–0.859 ms, Kafka
slower, with no 90% upper bound above 0.906 ms (supplement S7).

A second powered campaign, run about ten hours later with the same protocol and eight
replicates per level, reproduces the shift (0.381, 0.414 and 0.416 ms over the runs the check
keeps) but **fails the criterion registered for it**, that its shift fall inside the first
campaign's 90% interval at every level: at one feed it falls 0.008 ms below. We saw only after
the result that the criterion was a poor test, since even identical shifts would satisfy it at
all three levels only about 38% of the time. Against a seconds-scale annotation budget, 0.41 ms
is parts in 100,000, noise for choosing a broker, but it runs in the direction the
gray-literature comparisons report. Part of it is our harness: timestamping Kafka's
acknowledgment on the sending thread, as Redis's already is, shrinks the gap by 0.071 ms
(0.039 ms in a replication; H3), leaving a broker difference of 0.34–0.37 ms. This *refines* E1
and sharpens the reversal of the withdrawn accelerated result, which had had Redis
**degrading** with N.

> ### ⚠️ Claim 2 — WITHDRAWN: the 20× end-to-end gap was a start-up cost
>
> We previously reported a median end-to-end latency (*E*, the harness's TTI) of 105.5 ms for
> Kafka against about 5 ms for Redis, with 102.9 ms of Kafka's being publish delay, described as
> *constant — every event pays it*. **That does not reproduce.**
>
> A controlled re-run (N=1, verified true real time, same driver and broker) gives Kafka a median
> publish delay of **1.59 ms** with a **103.5 ms maximum**. Two independent instrumentation
> paths agree (per-event loop trace and per-run summary).
>
> **The discriminator is a count, not an average.** A median cannot separate a per-run cost from
> a per-event one, because how much of it the median sees depends on how many events the run
> holds — which is precisely what misled us. Sweeping the observation window at a verified
> real-time rate:
>
> | Window | Events emitted | Publish delay p50 | max | Events >50 ms late | Blocking publishes |
> |---|---|---|---|---|---|
> | 60 s | 57 | 1.56 ms | 103.4 ms | **4** | **1** |
> | 180 s | 148 | 1.61 ms | 103.5 ms | **4** | **1** |
> | 600 s | 507 | 1.58 ms | 103.5 ms | **4** | **1** |
>
> These are the Kafka rows of the window-sweep table in supplement S8.2 (counts are medians over
> three replicates from the per-event trace; the publish-delay percentiles come from the per-run
> summary). Redis, run in the same sweep with the same loop trace, has no event more than 50 ms
> late and no blocking send at any window. Events grow **8.9×**; the count does not move. The
> share of events paying the cost falls from 7.0% to 0.8%. A per-event constant would have grown
> the count and held the median at 103 ms.
>
> **The cause is in our own data, and the argument is arithmetic.** E1 matched a **median of
> seven** events per run; its campaign script, recovered later, replayed two seconds of match
> time per run (postmortem S4). A median of seven values at 102.93 ms requires **at least four
> of the seven** to be that high. The loop trace says exactly how many events per run are ever
> that late: four, always the same four, those due while the first send blocks. So the matched
> set is almost entirely the prologue, and the argument holds at every replay rate E1 could have
> used.
>
> The mechanism, straight off the trace and identical in every run: event 0's first `produce()`
> blocks **102.6 ms**; the replay loop is single-threaded, so the four events due meanwhile wake
> about 103 ms late and then send in tens of microseconds; from event 5 it is steady state at
> about 1 ms. A Kafka producer fetches metadata before its first send to a topic it has not yet
> cached, and the shape matches, but we did not isolate the call: the sweep fixes the cost's
> shape, not its origin (supplement S8.2, postmortem S3). That the burst is five is the data,
> not the harness. Every one of the eleven replayed plans opens with at least five events at
> `t_sim=0`, all at second zero: two lineup records, two half-start markers and the kick-off
> pass (supplement S1.2 and S8.2). A football feed delivers its densest burst precisely when the
> producer is coldest. Redis's `XADD` creates the stream in the same round trip and shows no
> prologue.
>
> It also retro-explains the three properties we offered as evidence, each of which a per-run
> cost predicts equally well: *constant* within a run, *concurrency-invariant* (one per run
> regardless of N), and *rate-dependent* (acceleration packs in more events and dilutes it).
>
> **The sign check does not catch this.** Every one of those runs passes it, nothing is
> negative, and the four cells' medians agree within half a millisecond, 105.3 to 105.7 ms,
> across a hundred runs: the artefact is deterministic, so it reproduces beautifully. Passing the
> sign check is necessary and not sufficient. A percentile over single-digit samples describes
> the harness, not the system.

**Claim 3 — The measurement-failure model's rules, measured.** Four rules were derived from the
model (`docs/measurement_model.md`) and pre-registered with falsification criteria before the
data existed. The journal supplement labels H1, H2 and H3; H4 is claimed only in the
postmortem (S18):

| | Rule | Result |
|---|---|---|
| **H1** | negative spans fall as the measured delivery grows | ❌ **Withdrawn as evidence.** The injected-delay sweep behind the ρ = −0.80 we reported failed its manipulation check: the delay is common-mode and cancels in the transport proxy *S* (re-run at one feed, the end-to-end latency tracked it, 3.72 to 23.61 ms over 0–20 ms, while *S* stayed flat), so the sweep is a negative result only (supplement S8, postmortem S3.1). The direction is shown instead by the payload sweep, which lengthened transport 77× and lowered the rate 4.1× (paper Section III-B) |
| **H2** | negative spans follow M/G/1 waiting in utilisation | ❌ **refuted.** The early ladder stopped at ρ=0.878 and could not separate the forms. Extending it to ρ=0.990, where they diverge, M/G/1 fits *worse than the mean* (R² −0.05 vs a fitted exponential's 0.93), and the bracket we registered before that sweep also missed (2.45–3.07× growth predicted, 1.44× measured; supplement S8) |
| **H4** | negative spans rise with concurrent process count | ✅ ρ = **+0.80** (E-A2, 15 runs per level); claimed only in the postmortem, not in the paper or the journal supplement |
| **H3** | asymmetric stamping biases the comparison | ✅ **replicated in direction** (E-C3, then E-C4). Gap **+0.286 → +0.215 ms** (−25%), moving entirely on the asymmetric side: Kafka 0.392 → 0.322, Redis holds ≈0.106. The shrinkage is 0.071 ms [95% bootstrap 0.039–0.113] in E-C3 and 0.039 ms [0.008–0.059] in the 30-runs-per-cell replication E-C4, leaving a broker difference of 0.34–0.37 ms (supplement S7) |

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
brokers (`tc netem`), N=5. The Redis arm passes the sign check 15/15 at every non-zero delay,
precisely because the effect dwarfs the instrument's floor. The zero-delay row is rejected
under both brokers, so there is no usable baseline (supplement S7).

| Injected delay | Kafka *E* | Kafka *S* | Redis *E* | Redis *S* | Runs passing (K / R) |
|---:|---:|---:|---:|---:|:--|
| 0 ms | *rejected* | — | *rejected* | — | 0/15 · 0/15 |
| 5 ms | 12.4 ms | 5.6 ms | 4,651 ms | 4,645 ms | 14/15 · 15/15 |
| 20 ms | 77.8 ms | 20.8 ms | **31,401 ms** | 31,268 ms | 12/15 · 15/15 |
| 50 ms | 336.6 ms | 44.9 ms | **103,143 ms** | 102,460 ms | 15/15 · 15/15 |

*E* is the median end-to-end latency and *S* the median transport proxy. Kafka's *S* *tracks*
the delay almost additively; Redis's grows about 930 to 2,050 times the delay applied. No run
was truncated, so this is amplification, not loss.

**Claim 5 — The mechanism is round-trip-bound acknowledgement, demonstrated by intervention at
realistic load and unexplained at 5× that load.**

| Condition | Per-message ack | Batched (200) | Improvement |
|---|---:|---:|:--|
| N=1, real-time, 20 ms delay | 4,138 ms | **103 ms** | **40.2×** |
| N=5, 10×, 20 ms delay | 68,960 ms | 73,598 ms | none (0.94×) |
| N=5, 10×, 50 ms delay | 87,624 ms | 92,386 ms | none (0.95×) |

At N=1 read-loop instrumentation shows the mechanism directly, and corrects it: each
`XREADGROUP` returns every waiting entry (a median of 106 messages) in ~32 ms, so the consumer
is **not** read-bound. The ceiling is entirely in the ack path — 200 × 20 ms = 4 s per batch,
during which it issues no reads at all (13 reads per run, 4 non-empty; batched: 37 reads, 25
non-empty).

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
| Entire Testbed A (single host) — concurrency, throughput sweep, synthetic netem, ack batching, decision-staleness aggregates | ❌ **Withdrawn** (8 of its 76 conditions survive the sign check, none of the first result's six; the workstation enters the paper only through the audit) |
| Testbed B 10× concurrency sweep | ❌ Withdrawn (0–2 of 15–30 runs pass) |
| Connection sweep above N=10 | ❌ Withdrawn (at N=100 Kafka's median transport proxy is **−6.4 ms**) |
| 3-node cluster arm | ❌ Withdrawn (0/15 runs, both backends) |
| Durability H31/H32 quantification | ⚠️ Direction only; magnitudes were Testbed A |
| Injected-delay sweep (H1) | ❌ Withdrawn: the delay cancels in the transport proxy, so it is a negative result only (Claim 3) |
| E1 concurrency (real-time, gated) | ⚠️ **Historical.** Its concurrency result stands (neither broker degrades with N); its end-to-end and send-lag columns are withdrawn (Claim 2), and its transport medians rest on seven events per run |
| Powered transport campaign and its replication | ✅ **Reported** (Claim 1; supplement S7) |
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

> **The current objective, in the paper's own terms:** show two ways a message-broker benchmark
> misreports on sub-millisecond paths, where the time being measured is shorter than the
> clock's resolution and than a busy thread's wait for a processor (Failure 1, late timestamps
> invert the acknowledgment-timed span; Failure 2, a millisecond clock and a positivity
> filter delete samples without counting them), establish each by manipulation, test how widely
> published results reach the second, and give benchmark authors checks that cost nothing.
>
> **The original question**, kept as the setting that produced the finding: benchmark Redis
> Streams against Apache Kafka for real-time football feeds on open StatsBomb data, at
> concurrency derived from the sport. What survives of that comparison is small (§1.2, Claim 1).

**Experimental strategy.** Each design choice closes a specific way the measurement could lie:

| Design choice | What it rules out |
|---|---|
| **Sign check** (`clock_integrity.py`) | an origin timestamp written late under load (Failure 1) |
| `time.time_ns()` shared epoch | cross-process clock offset |
| **True real-time replay** | a saturated driver being measured instead of the broker |
| Both producers pipelined (`--max-inflight`) | asymmetric client configuration |
| **Distinct match per feed** (`--plans-dir`) | concurrency secretly being throughput |
| **Concurrency derived from kick-off times** | an invented independent variable |
| Hodges–Lehmann + bootstrap | a heavy producer tail contaminating mean-based tests |
| Margins proportionate to the metric (1 ms on the transport proxy, 40 ms on the end-to-end latency) | a margin so wide it cannot fail |
| **Manipulation check per intervention** | a null produced by a treatment that never applied |
| Multi-host testbed with real network + `tc netem` | a loopback path pricing round trips at zero |

---

## 2. Abstract

> **Title:** *Super-Precise Latency: How CPU Threading Affects High-Precision Latency, and an Industry-Wide Audit*
> **Target:** IEEE Transactions on Computers (`IEEEtran`, journal, `paper.tex`)
> **Keywords:** Apache Kafka; benchmark auditing; CPU scheduling; latency benchmarking; message brokers; multithreading; Redis Streams; timestamp resolution.

The paper's abstract, which by the authors' rule carries no numbers and names no tool:

> Engineers choose message brokers, which carry data between programs, partly by latency
> benchmarks that now report latencies below a millisecond. At that scale, when a program reads the
> clock matters. After a broker writes a message, it acknowledges it to the producer and delivers it
> to the consumer. On one machine and one clock, the two readings should coincide. Measured, their
> difference spreads over milliseconds, and part of it falls below zero. The cause is scheduling. A
> thread must wait for a processor core before it can read the clock, and the thread that reads the
> acknowledgment can wait longer than the message takes to reach the consumer. How often this
> happens obeys laws we derive and test by manipulation. It rises with load and with how the load
> is placed, and falls when the clock-reading threads run at real-time priority and as the timed
> path outgrows the scheduler's slice, which the processor count sets. An industry-wide audit finds
> such values discarded uncounted or never measured, and a filter on millisecond clocks that
> deletes the fastest messages too. We give checks, and measure what each buys.

The numbers behind it are in the summary at the top of this README and in the paper's
introduction, one contribution per bottom line; the evidence in full is in the supplement, S1 to
S6.

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

### 6.1 Primary metric — event-time latency E (TTI in the harness)

```
E = t_out − t_sched = (t_pub − t_sched) + A + S + (t_out − t_recv)     (paper, Equation 2)
```

In the harness's own columns:

```
TTI = t_output_ns − t_prod_sched_ns
```

- `t_prod_sched_ns` (*t*_sched): when the event fell due, the run's wall-clock start plus the
  plan's emission offset scaled by the speed-up flag
- `t_output_ns` (*t*_out): when the consumer has handled the record

The paper calls this quantity the **event-time latency E**, Karimov et al.'s name for it; the harness's columns,
`compute_tti.py` and `tti_summary.json` call it TTI (Time-to-Insight) for historical reasons.
Every timestamp is read from one wall clock, `CLOCK_REALTIME`, through `time.time_ns()`, by
producer and consumer processes on one host, so a difference of a producer timestamp and a
consumer timestamp is a valid span (the Java client of the law campaign reads the same clock
through `Instant.now()`, `harness/java/src/LawClock.java`). A process-relative clock (`perf_counter_ns`, whose origin
is per process) carried each run's consumer start-up offset into every measurement; replacing
it was one of the early corrections (supplement S8.1).

### 6.2 Metric definitions

| Metric | Formula (harness columns) | Meaning |
|--------|---------|---------|
| Event-time latency *E* (TTI in the harness) | `t_output_ns − t_prod_sched_ns` | *t*_out − *t*_sched: from the event falling due to the consumer having handled it; a causal chain (paper Equation 2) |
| Transport proxy *S* ("transport" in the harness) | `t_cons_recv_ns − t_broker_ack_ns` | *t*_recv − *t*_ack = *D* − *A*: a message timed from the acknowledgment. Not a causal chain, and the only span that turns negative (paper Section II-A and Table I). `compute_tti.py` falls back to `t_prod_send_ns` for a run with no acknowledgment timestamp |
| Publish latency *A* | `t_broker_ack_ns − t_prod_send_ns` | *t*_ack − *t*_pub: from the publish call to the producer observing the broker's acknowledgment (`acklag` in `recount_spans.py`) |
| End-to-end latency *D* | `t_cons_recv_ns − t_prod_send_ns` | *t*_recv − *t*_pub: from the publish call to the consumer holding the record; a causal chain |
| Publish delay ("producer scheduling lag" in the harness) | `t_prod_send_ns − t_prod_sched_ns` | *t*_pub − *t*_sched: how late the publish call ran after the event was due |
| Processing-time latency | `t_output_ns − t_cons_recv_ns` | *t*_out − *t*_recv: the consumer's own work on the record. Added round 43, and the reason it is listed here is that the two clients do not take these two stamps in the same place: Kafka's parses the payload inside `poll()`, before `t_cons_recv_ns`; Redis's parses it between the two stamps. Median 281 ns and 19,480 ns respectively, so every span referenced to `t_cons_recv_ns` carries one client's parse and not the other's, while *E*, which runs to `t_output_ns`, contains both. Disclosed and bounded in supplement S1.5; pinned by `tests/unit/test_consumer_stamp_placement.py` |
| E (TTI) p50 / p95 / p99 | percentiles of E | Median, 95th, 99th |
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
directories were deleted in commit `bacd9df`, along with 28 other obsolete scripts.

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
├── paper.tex                       # IEEE paper (Trans. Computers target, IEEEtran) + supplement.tex + postmortem.tex
├── manuscript_references.bib       # bibliography (170 entries; cited: 42 in the paper, 58 in the supplement, 112 in the postmortem)
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
│   │                                                    #   shared-stamp contrast, over
│   │                                                    #   five spans since round 43:
│   │                                                    #   the fifth joins the consumer's
│   │                                                    #   two stamps to each other
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
│   ├── README.md                                                # what each doc is, and which are current
│   ├── infrastructure.md · laws.md · measurement_model.md        # environment + the model
│   ├── earlier_models.md · grey_literature_review.md             # models tried, sources gathered
│   ├── preregistration_depth.md · omb_distributed_issue.md · supplement_index.md
│   ├── paper_revisions.md                                       # the plans behind the paper's shape
│   ├── reviews_and_responses.md · releases.md                   # reviews answered, versions deposited
│   └── results/                    # GENERATED analysis outputs (CSV/PNG/PDF)
│       ├── realtime_concurrency/   # PRIMARY: fair sweep latency by backend/config/N
│
├── freezes/                        # experiment plans frozen before their runs (freezes/README.md)
│   └── 01-experiment-plan/         # the Azure law campaign: plan source, PDF, SHA256SUMS
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

### On Windows and on Linux, with nothing skipped

Since 27 September 2026 every test runs on both platforms, in CI on every push (Ubuntu with
Python 3.9 and 3.11, Windows with 3.11), and **nothing in the suite may skip**: a skip fails,
with its own reason (`tests/no_skips.py`). Until then the tests of the kit's shell scripts
skipped on Windows and a dozen paper gates skipped wherever the paper had not been built by
hand, so a failure could live on one platform unseen from the other.

What a machine needs for the whole suite to run there:

- **A TeX distribution** with `pdflatex` and `bibtex` (MiKTeX or TeX Live). The session builds
  the paper and the supplement itself when what a build leaves (`.aux`, `.bbl`, `.blg`, `.log`)
  is missing or older than its sources, in a scratch folder, and never touches the committed
  PDFs (`tests/paper_build.py`).
- **xpdf's `pdftotext` and `pdffonts` 4.06**, which the rendered-page gates read with.
- **On Windows, Git for Windows**, whose bash runs the kit's shell scripts, and **WSL with
  `Ubuntu-22.04`**, the drivers' own release, for the two tests of what the Linux kernel does
  with the queue's lock (`tests/posix_shell.py`).

Two checks read what only the author's machine holds -- the reference corpus, other people's
papers, which git ignores -- and are left out of the default run rather than skipped. Run
them there before a submission:

```bash
python -m pytest tests/ -m author_machine
```

*Plain words:* a *skip* is a test that reports neither pass nor fail; *WSL* is Windows' own
Linux; *Git Bash* is the Linux-style shell that comes with Git for Windows.

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
(latest version: see the header).

---

## 12. Manuscript & Paper Preparation

The paper targets **IEEE Transactions on Computers** using the IEEE `IEEEtran` class
(`journal`, 10pt). The earlier SAGE / Journal of Sports Analytics, ACM TOMPECS and IEEE TPDS
framings were retired; see the header for why. TC allows regular papers 10-12 double-column
pages *including references and biography*, and caps references at 45, so the manuscript is
held inside that budget by test gates. The evidence behind each section lives in the journal
supplement and the complete record in the postmortem, both compiled from the same commit.

| Asset | Purpose |
|-------|---------|
| `paper.tex` | The paper (`IEEEtran`, journal; Introduction, How a Message Is Timed, The Distribution of S, The Mechanism and Its Laws, An Industry-Wide Audit, What to Do, Related Work, Limitations, Conclusion) |
| `supplement.tex` | The supplementary material, S1–S6 in the paper's order, under the paper's byline (`docs/supplement_index.md` maps each section to the postmortem sections it draws on) |
| `postmortem.tex` | The complete record, a single-author postmortem in five parts, S1–S37: the chronology, every withdrawn result and the law campaign run by run. Archived with the data; not part of the submission. Written against the paper as it stood before 5 Oct 2026, whose labels it reads from `docs/archive/2026-10-05-before-cleanup/paper.aux` |
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

Then the supplement and the postmortem, **in that order and not before**:

```bash
pdflatex -interaction=nonstopmode supplement.tex
bibtex supplement
pdflatex -interaction=nonstopmode supplement.tex
pdflatex -interaction=nonstopmode supplement.tex
pdflatex -interaction=nonstopmode postmortem.tex
bibtex postmortem
pdflatex -interaction=nonstopmode postmortem.tex
pdflatex -interaction=nonstopmode postmortem.tex
```

The order is a real constraint, not a convention. The supplement refers to the main text's
sections, tables and equations by label, and `\usepackage{xr}` resolves them by reading
`paper.aux` — so a supplement built before the paper silently renders those references as the
literal `??`. Six of them reached the built PDF before round 42, in the one document the main
text sends a reader to when they want the evidence. The postmortem reads the frozen labels of
the paper it was written against, in `docs/archive/2026-10-05-before-cleanup/paper.aux`, so it
does not depend on the order. `TestNoCrossReferenceDangles` fails on any
`??` in either rendered PDF, so a build in the wrong order is caught on the artefact rather
than trusted to the procedure.

That check, like the one above it, reads the *rendered* PDF rather than the source. A dropped backslash turns
`\ref{tab:ea6}` into the literal text `ef{tab:ea6}` and `\texttt{x}` into `exttt{x}`; LaTeX
reports no error, the source still looks plausible, and the defect appears only in the output.
That failure reached the manuscript three times here, twice past a full source-level check, which
is why the check now runs on the artefact a reader actually receives.

**Status (the PDFs built on 5 Oct 2026):** compiles clean, with 0 errors and 0 undefined
references or citations. The paper is 8 pages, its text ending on page 7 and the last page
holding five references and the two biographies, with 37 references, three figures, one table
and five numbered equations. The journal supplement, S1–S6 under the paper's byline, is 16
pages; the postmortem, the complete single-author record that is not submitted, is 76 pages.
Formatted with `IEEEtran` (journal, 10pt) for IEEE Transactions on Computers.

Sentence length is gated too, since round 43. A co-author reported that average sentence
length ran higher than he would have set it, and asked for the claim to be measured rather
than judged by ear: the main text was at a median of 28 words against 19–22 across five TC
papers extracted the same way. `tests/unit/test_sentence_length.py` now caps the median at
the top of that venue range, caps the share of sentences over forty words, and caps the
longest. The build sits at a median of 21, a mean of 21.5, and a longest sentence of 78.

Two of the four gates write as well as check. `scripts/emit_paper_numbers.py` generates
`docs/generated/paper_numbers.tex` (the macros the manuscript quotes) and six tables —
`grid_table.tex`, `spread_table.tex`, `interval_table.tex`, `registry_table.tex`,
`priority_table.tex` and `exposure_table.tex` — and `--check` fails the build if any of them
disagrees with the artefacts. The first table was generated because the transcribed version drifted from the
correction its own caption claimed: it printed raw permutation p-values under a caption
promising Holm correction, and one arm changed verdict between the two. A number that reaches
the page without passing through a script is the one that goes wrong.

`spread_table.tex` was added in round 45 for a different reason, worth stating because it is
the failure this repository is least protected against. The quantisation table it replaces was
typed but *not* wrong: the suite recomputed every column of it from the campaign index on
every run, and it never drifted. What no gate covered was the ledger *underneath* it.
`docs/results/external/phase_quantisation.csv` was built before chain17's `ultimate` campaign
joined `RATE_CAMPAIGNS`, and was never rebuilt, so for five rounds the manuscript's strongest
sentence about the spread law described a nine-arm corpus the analyser no longer produces —
while the grid-membership analysis beside it already used the full twelve. The second route
that should have caught it was itself carrying a hard-coded copy of the campaign list, made
before the change and never updated, so both routes agreed by being stale in the same way.
Rebuilt, the corpus is twelve arms and ten match; the two that miss are reported in
supplementary material S31 along with the reason the spread statistic was superseded. Two
lessons went into the suite: a test that recomputes independently must still *import* the
declarations it recomputes against (`tests/unit/test_paper_consistency.py`), and a claim
written as an English word is still a claim about a number and is gated as one
(`tests/unit/test_shared_statements.py`).

Round 47 added `tests/unit/test_supplement_hygiene.py`, and the reason is a measurement rather
than an incident. Counting every non-structural numeral each document prints, **78% of the main
text's arrive through a generated macro and 15% of the supplement's do** -- and the supplement
carries roughly four fifths of the paper's evidence. Three rounds running, the defect had the
same shape: a generated layer moved and a typed layer beside it did not. Round 45 rebuilt the
phase ledger; the generated tables followed and four narrative paragraphs in S13 and S23 did
not, still describing a nine-arm corpus with a 46.6% median where the rebuilt one has ten
replicates and 51.04. `arm_macros()` now emits, per narrated arm, exactly the fields that arm's
paragraph quotes -- the replicate list, the median, the miss against a registered prediction,
the branch counts -- and the new gate fails if a retired value reappears or an emitted one goes
unread. The same file holds two smaller rules found the same round: a cited web source that
quotes a measured figure must carry a URL or an identifier, and a reference list must be the
last thing in its document.

Round 45 also added `tests/unit/test_prose_pointers.py`, because both documents point at
supplement sections in running text — "Supplement~S23", "supplementary material S27" — more
than sixty times, and LaTeX cannot check a cross-reference written as prose. It found four
dead ones: three in the main text naming S53 where the registry is S36, and one chain where
S31 pointed at S27, S27 said the table had gone back to the main text, and the main text did
not have it.

**A reference can resolve and still print nothing.** The supplement sets `secnumdepth` to 0
on purpose — its S-numbers are written into the heading text, and a counter beside them would
make the contents page read "I S36." — so `\section` steps no *printed* counter and a
`\label` on one stores the empty string. Two `Section~\ref{sec:registry}` calls had therefore
been typesetting as `Section  found in shipping software`, in the prose and the caption of the
supplement's deletion-histogram figure, since round 43. Every existing check passed: the label
is defined, so LaTeX warns nothing and no `??` reaches the page, the undefined-reference count
stays zero, the stranded-pointer rule sees a `\ref` after the tilde, and the resolve-check asks
whether the label can be *found*, which it can. None of them asked whether it printed anything.
`TestNoReferenceResolvesToNothing` in `tests/unit/test_cross_document_refs.py` reads the `.aux`
each document actually produced and fails any `\ref` whose target comes back blank; both
pointers are now written the way the rest of the supplement writes them, as `Section~S36`.

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
final click was the author's.

**Internal review.** Before submission, the manuscript went through internal review rounds held
to journal standards
([`docs/reviews_and_responses.md`](docs/reviews_and_responses.md)). The paper has not yet
been submitted to a journal, and no document in this repository contains journal
correspondence.

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
  author  = {Ricou, Gustavo Pedro and Duvignau, Romaric},
  title   = {{Super-Precise Latency}: How CPU Threading Affects High-Precision Latency, and an Industry-Wide Audit},
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
| Manuscript files (`paper.tex`/`.pdf`, `supplement.tex`/`.pdf`, `postmortem.tex`/`.pdf`) | © the author, **not** MIT — pending journal publication |
| Replay plans (`data/processed/replay_plans/`, StatsBomb-derived) | CC BY-NC 4.0 |
| StatsBomb data | CC BY-NC-4.0 |
| Third-party libraries | Various (see `requirements.txt`) |

---

## 16. Changelog

### 5 Oct 2026 — the paper rebuilt around four bottom lines (not yet deposited)
**Paper v8** is titled *Super-Precise Latency: How CPU Threading Affects High-Precision Latency, and an Industry-Wide Audit* and has one section per bottom line: the distribution of
*S* = *t*_recv − *t*_ack, which would be zero in the ideal case; the mechanism of a thread's wait for
a core and the laws that govern it; the industry-wide audit; and what to do. The 12-page paper was
cut twice, independently, and the shorter version of every part was kept: 7 pages of text.
Everything cut moved to the supplement, which was then cut from 33 pages to 16 (S1–S6), keeping
the tables, figures and experimental detail a referee needs for the machines whose results the
paper presents. Both documents as they stood before are in
[`docs/archive/2026-10-05-before-cleanup/`](docs/archive/2026-10-05-before-cleanup/README.md). A
literature and grey-literature review ([`docs/literature_review_2026-10-05.md`](docs/literature_review_2026-10-05.md))
checked what is new and brought the vocabulary into line with the field's: *waiting probability*
for occupancy, *residual wait* for residual stall, *randomize the publish instants (Poisson
sampling)* for dither, and the positivity filter named for what it does statistically, a
truncation at zero. Treadmill, Skyloft, timerlat, ShuffleBench and SPEC's methodological
principles are now cited. Fig. 2 is the distribution of *S* alone, drawn at column width, and
Fig. 1's red notes say what they mark instead of numbering failures. Every term is defined where
a reader first meets it, the experimental vocabulary included. The postmortem was written against
the paper as it stood before, so its pointers now read that version's labels, kept beside it in
the archive. The tests follow the rebuilt documents: 8,214 pass, none skip, every script's
branches are covered, and the mutation check catches all six of the claims it breaks. Of the
39 generated numbers the rebuild left unread, 28 left the ledger, 4 are read again and 11 stay
with a reason each, written beside the ceiling in `tests/unit/test_rendered_prose.py`.

### 4.0.0 — prepared 29 Sep 2026, not yet deposited — the editorial revision
An outside editor's review of v3, taken whole. **Paper v5** is retitled *Faster than Light: Latency
Measurement Errors in Message-Broker Benchmarks* and gives both failures equal space. **Paper v6**
(2 Oct) organizes it around its three parts, the finding (latencies that come out negative on one
clock), the mechanism (a timestamp taken late, with its small laws as Equations 3 to 5) and the
industry (what the tools do with a latency at or below zero, which on a millisecond clock is the
second failure), and adds Practical Implications, which the abstract and the introduction now lead
with; 12 pages, 43 references. **Paper v6.1** (3 Oct) rewrites the prose of the paper and the
journal supplement to one idea per sentence, the way Tipler and Mosca's *Physics for Scientists
and Engineers* writes: each term is defined where it first appears, colons and semicolons that
joined two ideas became full stops, long paragraphs were split, and the supplement's second sense
of "grid" is now the *q*-lattice; no claim and no number changed. **Section VI-B now sizes the
receiving thread's own wait** that a latency timed from the publish call keeps: measured three ways in 51
runs after the registered campaign (R1), it added 0.41–0.94 ms to the mean latency, while the median
message waited 18–46 µs; Supplement S3.10 gives the design, the four predictions and what each
found ([`docs/results/recv_wait`](docs/results/recv_wait/README.md)). **The vocabulary is the
industry's** (writing standard A10, in all three documents and the figures): the producer
*publishes*; *A* is the publish latency, the old send lag the publish delay and *D* the end-to-end
latency, the names the OpenMessaging Benchmark reports them under; *E* is the event-time latency
and the consumer's own span the processing-time latency, after Karimov et al.; Linux's real-time
and normal priority replace go-first and ordinary; and the campaign's brake is its stopping rule. **Every term in the paper is defined where a reader first meets it** (4 Oct), the way Tipler
and Mosca build a quantity: the producer and the consumer by what they do, the publish call as
the moment the producer hands the message over, real-time priority as running ahead of every
thread at the default normal priority, and the one-way latency, the industry's name for what
was the one-way delivery, as the time from one process to another, which ten of the eleven
tools run cannot measure because each takes both timestamps in one process. **Paper v7** (4 Oct) answers the author's seventeen points on reach and clarity: the title names the stakes (*Faster than Light: Silent Errors in the Latency Benchmarks Used to Choose Message Brokers*); the abstract and the introduction open on what a team choosing a broker risks, and a list says what the work means in practice; Fig. 1 draws the whole system, which machine runs what, the two legs a message travels, where each failure enters, and every timestamp and latency of the model, the event-time latency and the clock's step included; Fig. 4 shows what the remedies buy, measured; Section VI says what decides whether a printed latency can be trusted; the first half states each result for exactly the cases it holds in, and Section VIII states every limit whole (writing standards B26 and B27); two references from PNAS and Nature, checked against Crossref, ground the registration and the void result. The traced stall spectrum and the two tool tables moved to the journal supplement; the paper stays at 12 pages with 45 references.
**The supplement is now two documents:** the journal supplement S1–S9, in the paper's
order under both authors' names, and the single-author postmortem S1–S37, the complete record, not
submitted. **A registered audit of 43 published reports** found the signature in eight configurations
of two and a stated retention in none. **The fidelity audit corrected:** 109 of the 126 runs behind
our first result fail the sign check, not every run; *E* is defined to *t*_out, as computed; the
transport replication fails its registered criterion; E-A7's occupancy fall, when the grid test was
built, the workstation's hypervisor, the kickoff burst. 8,073 tests; the unreleased entries below ship too.

### Unreleased — 2026-09-10 — the byline goes from four names to two
**Two authors withdrew and the named acknowledgements were cut.** The last author had
asked on 8 September to be removed, on his own standard for taking public responsibility
for a deposited record he has not audited in the detail he requires; that request was
actioned today. A third author asked on 10 September for his name to come off the work,
Zenodo and this repository included, three days after reading the manuscript and passing
it — his objection is to how the work was produced, not to what it reports, and he is not
named here because that is what he asked for. The four correspondents thanked by name in
the acknowledgement had each replied once in August and none since, and were cut.

**No number, figure, table or claim moved.** What the departing authors contributed stays,
because it was right: the load generator is verified rather than assumed and that rule
still closes the paper, the timer-characterisation citation stays in Section III, the
ComBench comparison stays in supplement S52 without its credit line, and Figure 1, the
thread drawing and the deletion histogram stay with the gates that pin them. Removing a
byline withdraws a claim about who vouches for the work; deleting correct work to finish
the job would be a second wrong.

The paper is now bylined **G. P. Ricou and R. Duvignau**, with two affiliation footnotes,
two biographies and a running head that names both rather than `et al.`, which IEEEtran
reserves for three or more. `tests/unit/test_author_withdrawals.py` pins the byline at two
positively rather than by forbidding the departed names, since a gate that spelled out a
name someone asked to have removed would defeat its own purpose. **Still outstanding** when
this entry was written: the deposited Zenodo records and the arXiv submission carried the
four-author byline. Since then the published v3.0.0 records' metadata has been edited to list
only the lead author; the manuscript PDFs archived with v3.0.0 still carry four names, because a
published record's files cannot be replaced, only superseded by a new version; and arXiv removed
the submission on 14 Sep 2026, before it was announced.

### Unreleased — round 44 — the exposure curve has a width
**No measured result changes.** One published curve gains the dispersion it always had.

Section VI-B's fifth rule is the only place the paper tells a reader to do arithmetic about
their own system — *"know where your own path sits on the exposure curve"* — and every number
in it came from **one** quantity: the median acknowledgment lag over 70 conditions, 725 µs.
That lag runs **500 to 1,900 µs** between the tenth and ninetieth percentiles. A reader with a
10 ms path read 7% and stopped; at the ninetieth percentile it is 19%, and the crossover
below which the displacement exceeds the path moves from 0.72 ms to 1.90 ms.

The paper's own §V-D is the argument against what it was doing: "a mean over this distribution
is dominated by a mode the operator never sees." A median offered as practical advice is the
same mistake one level up. `_exposure_lags()` now returns the percentiles beside the median,
every row of Table S48 carries a p10–p90 band, and the main text quotes the lag it rests on
and the crossover as a range. `\ackLagMedianUs` had been emitted and printed nowhere.

Three defects that existed only in the rendered PDF, all invisible to gates that read `.tex`:

- **Two cross-references printed section numbers that do not exist** — "Section III-A0a" and
  "Section IV-B0a", because both labels sat on a `\paragraph`. One had been created by the
  round-43 edit that fixed a *different* dangling pointer.
- **Three sentences began with a lowercase word.** `\harnessSilentWord` expands to "five" and
  round 43's sentence-splitting moved it to the head of a sentence. The capitalised twin
  `\harnessSilentWordCap` already existed and had never been used anywhere.
- **Sixty-six of 275 generated macros were read by neither document.** Most are deliberate
  `Word`/`WordCap` pairs; `\ackLagMedianUs` was not.

`tests/unit/test_rendered_prose.py` now fails on all three classes, reading the built PDF.

Also: §VI-A says *whose* delivery the 2.4% is a share of (Redis's); the dither result in S51 is
restated as the one-sided condition its source gives rather than a two-sided bound; S39 records
that TimeWeaver's precedent extends to publishing a rejection rate (3,631 of 8,804 clients);
Figure 4's null bars are dodged off the arms they belong to; and S52.3 gains a 2026 tutorial
whose §14 enumerates "latency-specific pitfalls" and never mentions the instrument's clock.

### Unreleased — round 43 — the consumer's stamps, audited at last
**No measured result changes.** One quantity is disclosed that was never measured before, and
three published numbers are corrected in their last digit.

The finding is a gap in an audit. Supplement S43.1 is titled *"Where each stamp is actually
taken"* and audited three stamps, all producer-side — while every span the paper reports
*ends* at a consumer stamp, and the two consumers do not take theirs in the same place.
Kafka's client is given a `value_deserializer`, so the payload is parsed inside `poll()`,
before `t_cons_recv_ns`; the Redis consumer stamps first and parses afterwards. Measured by
adding a fifth span to `recount_spans.py`: a median handling span of **281 ns under Kafka
against 19,480 ns under Redis**, a factor of 69, on a stamp neither document had named. It is
now named in §III-A, bounded in §VI-A at 2.4% of the delivery it sits inside, set out in full
in S43.1, and pinned by `tests/unit/test_consumer_stamp_placement.py`. The direction is
stated in both places: it cannot move the S48 equivalence, and it runs *against* the
per-broker gap in Table I rather than producing it.

Three corrections found while fixing it, none of which changes a claim:

- The grid figure's x-axis held the distance of θ from its vertex with no replicate noise,
  while the test simulates noisy replicates — the distance of the expectation against the
  expectation of the distance. The supplement's caption asserted it *was* that expectation.
  Now the simulated mean, with the null's central 90% drawn per arm, and a gate that the
  centre lies inside its own band. No p-value or verdict moved.
- `grid_membership_test.py` defaulted to 20,000 Monte Carlo draws while the committed CSV had
  been written at 4,000, so running it with its own default moved every p-value at the floor.
- Two typed numbers had drifted: cross-host retention runs 13.4 to **26.9**%, not 27.0, and
  its one-clock twin holds to **0.98** points, not 0.8. Both now read from the ledger.

Also: the inter-host offset resolves from one macro instead of being typed three times in two
roundings; Figure 3 separates markers its own legend counts (two 256 KB replicates 1.4% apart
had rendered as one); Figure 5(a) is a swarm rather than a sorted staircase on an axis with
no variable; the payload-flip figure moved to supplement S31; and the main text's median
sentence fell from 28 words to 22, inside the range measured across five TC papers.

### 3.0.0 — 2026-09-04 — four authors, and the model became an identity
**A major bump because the creator list changed**: a record's authors are part of its
identity, and this one goes from two names to four. **R. Duvignau** (Chalmers) joins as
second author, with **D. Gregg** last in the senior slot and a third author in between;
each joined on a correction that changed the work rather than the wording, and each left
the acknowledgements on the way in. Two of the four have since withdrawn — see the entry
at the top of this changelog. The record also takes the manuscript's current
title, which it had wrong.

What is new since v2.7.0, in order of how far it reached: Section III's model is now the
identity *S = D − A* per event, stated assuming no ordering, with both sides recounted from
the committed corpus on every build; the Time-to-Insight residual is named as the
acknowledgment lag the harness stamps rather than an append-to-deliver delay nothing
measures; the two-broker gap is measured on workloads that match (paired 1.7×, a fifth of
the pairs running the other way); a fifth timestamp is named and bounded, because the two
clients deserialize on opposite sides of the receive stamp; and the source audit grows from
five instrumentation tools to ten, recording that a search for any stated defence of the
positivity guard came back empty.

Seven new gates, each demonstrated failing on the defect it guards before that defect was
repaired — claim-to-equation agreement, float labelling, figure reading rules, cross-sentence
dependency, per-corpus denominators, front matter checked against the **built PDF**, and a
cross-reference rule that fails any pointer resolving to an empty number. Paper 12 pp,
5 figures, 2 tables, 44/45 references; supplement 49 → 54 pp, whose title page now carries
the paper's title and the four-author byline rather than one author under a title the paper
does not have. 4,175 tests at 100% branch coverage, up from 3,866 at v2.7.0. Zenodo v3.0.0
archived from tag `v3.0.0`: code
[10.5281/zenodo.22307766](https://doi.org/10.5281/zenodo.22307766), data
[10.5281/zenodo.22307882](https://doi.org/10.5281/zenodo.22307882).

### 2.7.0 — 2026-08-31 — a co-author, a title, and the system explained first
**D. Gregg joins as an author** and the records take the manuscript's current title, both of
which they had carried wrong. The system is drawn before any claim is made about it, and the
companion figure that had shown a single producer lane for eight rounds — contradicting the
project's own pre-registration — now separates the two stamping threads. The word *interval*
is retired for the timing sense and *flight* defined ahead of its first use. Mode B is
generalised from one benchmark's positivity guard to a quantum destroying a sample, behind a
source audit of five harnesses practitioners actually run. The 1/D law is stated where it is
argued rather than left to be inferred. **One estimate moved**, unlike v2.6: ρ(D, A) was
computed from a variance identity on three separately binned, edge-truncated margins, did not
conserve, and returned |ρ| > 1 on five of seventy conditions; it is now a windowed Pearson
correlation on paired co-moments with excluded pairs counted rather than dropped in silence.
Zenodo v2.7.0 archived from tag `v2.7.0`: code
[10.5281/zenodo.22215274](https://doi.org/10.5281/zenodo.22215274), data
[10.5281/zenodo.22215330](https://doi.org/10.5281/zenodo.22215330). Paper 12 pp, supplement
49 pp. 3,866 tests at 100% branch coverage.

### 2.6.0 — 2026-08-25 — Transactions on Computers submission package
Fourteen further rounds of internal review, all of them on presentation and
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
this release: the acknowledgment-timed span is a **proxy, not a causal chain**, so a
negative value is a late reference stamp rather than impossible physics — the sign check is
justified by the reference stamp being unusable as an origin. Mode B's arithmetic conceded to
its prior art in counter metrology (HP Application Note 162-1, 1970). Zenodo v2.5.0: code
[10.5281/zenodo.22044877](https://doi.org/10.5281/zenodo.22044877), data
[10.5281/zenodo.22044891](https://doi.org/10.5281/zenodo.22044891). 2,501 tests green.

### 2.0.0 — 2026-08-07 — TPDS restructure + Zenodo deposit
Manuscript restructured for **IEEE TPDS** (`IEEEtran` journal, 16-page ceiling test-enforced,
39-page companion supplement); the OMB silent-deletion arm (the paper's second failure mode)
integrated. Zenodo v2.0.0 archived from tag `v2.0.0` (commit `1d57d65`) with SHA256 manifests:
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

*Single-source README · last updated October 1, 2026 · target: IEEE Transactions on Computers.*
