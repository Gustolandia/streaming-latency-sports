# What the measurements support

The state of the mechanism after E-A3 through E-A10, the OMB replication, and the campaigns that
preceded them. This supersedes the load-axis parts of [two_state_model.md](two_state_model.md),
which were written before the manipulations that decided them.

Every entry says what would falsify it and what is still open. The failures are listed with the
successes because several of them are more informative.

---

## The mechanism

```
P(inversion)  =  P( scheduling stall > T_true )
```

An inversion is recorded when measured transport is negative: the consumer's receipt stamp
precedes the broker's acknowledgement stamp. Both stamps are taken on the same host, so no
cross-host clock offset is involved. What produces one is a stall between the event becoming
ready and the thread reading the clock, longer than the interval being measured.

Both sides of that inequality have now been manipulated independently, which is the reason it is
stated as a mechanism rather than a correlation.

---

## Established

### The rate follows scheduling, not utilisation

Raising the stamping threads to `SCHED_FIFO` at **fixed** utilisation collapses the inversion
rate. Eight matched ordinary/real-time pairs across three campaigns (E-A5, E-A5b, E-A7), spanning
five load levels, utilisation matched to 0.003 or better in every cell. One pair per level is
shown; the range over all eight is **7.2× to 79.7×**:

| load | ρ ordinary | ρ real-time | ordinary | real-time | fall |
|---|---|---|---|---|---|
| 60% | 0.6055 | 0.6035 | 0.0459 | 0.0017 | 28× |
| 70% | 0.7032 | 0.7025 | 0.1032 | 0.0144 | 7× |
| 75% | 0.7531 | 0.7525 | 0.1320 | 0.0034 | 39× |
| 88% | 0.8809 | 0.8812 | 0.2214 | 0.0034 | 66× |
| 95% | 0.9501 | 0.9501 | 0.2938 | 0.0037 | 80× |

*Falsified by:* the rate not moving when only priority changes. It moved every time.

*Baseline variation is real and reported:* the 88% ordinary arm ranges 0.221–0.305 across four
campaigns. The **effect** reproduces; the **level** drifts day to day.

### L3 — utilisation does not determine the rate; core availability does

E-A6 ran both load geometries in one campaign at matched utilisation.

| k/8 | ρ concentrated | ρ spread | concentrated | spread | ratio | z |
|---|---|---|---|---|---|---|
| 5 | 0.6284 | 0.6250 | 0.0201 | 0.0379 | 1.88× | 4.09 |
| 6 | **0.7531** | **0.7531** | 0.0824 | 0.1709 | **2.07×** | **10.27** |
| 7 | 0.8778 | 0.8809 | 0.2281 | 0.2415 | 1.06× | 1.22 |

Every cell: 2,985 matched events over 25 runs. `z` is a two-proportion test between that row's
two arms.

At k=6 the utilisation is identical to four decimals and the rates differ twofold. A function of
ρ returns one value for one input, so ρ cannot be the variable. Spread load (every core
duty-cycled, none free) starves the stamping thread more than concentrated load (k cores flat
out, C−k genuinely free); the two converge at k=7, where one free core out of eight is nearly as
useless as none — which is the mechanism showing itself, not a weaker result.

**Replicated (E-A6b), and it corrects one reading.** The whole campaign was run again:

| k/8 | ratio E-A6 | z | ratio E-A6b | z |
|---|---|---|---|---|
| 5 | 1.88× | 4.09 | 4.61× | 8.89 |
| 6 | **2.07×** | **10.27** | **2.05×** | **8.44** |
| 7 | 1.06× | 1.22 | 1.19× | 3.46 |

The load-bearing cell replicates almost exactly: at k=6 both arms sit at ρ=0.7531 in *both*
campaigns — identical to four decimals across all four arms — and the ratio is 2.07× against
2.05×.

*Withdrawn:* an earlier reading of k=7 as *convergence to a null*. The first campaign could not
separate the geometries there (z=1.22, intervals overlapping); the replication separates them
(z=3.46, intervals disjoint). One campaign finding nothing and another finding something is an
unsettled cell, not a null. What both agree on is the shape — a twofold separation at k=6
collapsing to near-parity at k=7. Whether it closes to exactly zero is not established, and the
mechanism does not require it: seven busy cores out of eight leave a little slack, not none.

*Also unsettled:* k=5 reproduces in direction but not magnitude (1.88× then 4.61×), consistent
with the day-to-day level drift documented for the 88% baseline.

*Falsified by:* the geometries agreeing at every level. They agreed only where predicted.

### T_true dependence, on the sign nothing else predicts

E-A10 padded the payload, lengthening true transport without touching the scheduler.

| pad (B) | ρ | transport | inversion |
|---|---|---|---|
| 0 | 0.8809 | 0.701 ms | 0.2603 |
| 4 096 | 0.8822 | 2.381 ms | 0.1906 |
| 65 536 | 0.8847 | 14.638 ms | 0.0888 |
| 262 144 | 0.8930 | 53.898 ms | 0.0637 |

Transport rose 76.9×, the rate fell 4.1×, monotone in both, intervals disjoint, ρ held to a 0.012
spread. **A slower path is a more reliable measurement.** Any account in which inversions track
system stress predicts the opposite, since larger payloads are strictly more work — and the
serialisation confound pushes ρ *up*, against the result.

**Replicated (E-A10b).** The whole sweep ran again on a different day:

| pad (B) | transport E-A10 | inversion | transport E-A10b | inversion |
|---|---|---|---|---|
| 0 | 0.701 ms | 0.2603 | 0.761 ms | 0.2338 |
| 4 096 | 2.381 ms | 0.1906 | 2.474 ms | 0.1652 |
| 65 536 | 14.638 ms | 0.0888 | 16.059 ms | 0.0784 |
| 262 144 | 53.898 ms | 0.0637 | 58.482 ms | 0.0549 |

Transport spans 76.9× and 76.8×; the rate falls 4.09× and 4.26×. Monotone in both directions in
both campaigns. The levels sit slightly lower in the replication, the shape does not move.

*Falsified by:* the rate rising, or not moving, as T_true grew.

### The traced tail predicts the rate

E-A9 traced `sched_wakeup`/`sched_switch` and computed P(run-queue delay > T_true) directly.
E-A9b repeated it at two load levels.

| campaign | arm | load | traced events | P(stall>0.5ms) | inversion | ratio |
|---|---|---|---|---|---|---|
| E-A9  | ordinary  | 88% | 551,956 | 0.1807 | 0.2315 | **0.78** |
| E-A9  | real-time | 88% | 570,591 | 0.0185 | 0.0000 | — |
| E-A9b | ordinary  | 75% | 709,819 | 0.1681 | 0.1276 | **1.32** |
| E-A9b | real-time | 75% | 641,308 | 0.0162 | 0.0000 | — |
| E-A9b | ordinary  | 88% | 687,986 | 0.2069 | 0.1956 | *1.06*† |
| E-A9b | real-time | 88% | 649,788 | 0.0159 | 0.0000 | — |

† withheld by the instrument check (28% drift against a 25% rule fixed in advance); shown, not
used.

A traced scheduler quantity predicts the measured inversion rate to **within a third** across
three ordinary arms — 0.78, 1.06, 1.32 — unfitted.

**The residual has no consistent sign, and we withdraw the reading that it did.** On one arm the
traced probability sat 22% *below* the rate, and we called that the opposite of what the simplest
account predicts. With three arms it is 22% low, 6% high and 32% high. That was scatter, not a
direction.

### The real-time zero is a tracing artefact — settled

All **three** traced real-time arms recorded exactly zero inversions in 2,985 events. The
untraced twin of one of them (`ea9_notrace`, the first E-A9 attempt whose probe never attached)
recorded **15**. At that rate, P(zero in one arm) = 3e-7; in all three, ~1e-20.

Attaching BPF to `sched_switch` **suppresses the inversions in the real-time arm**. Previously
listed as open ("either that arm genuinely differed or tracing perturbed it"); three arms
separate the two.

The same direction appears in the ordinary arm — the two traced 88% values are the lower two of
the six we have — but the between-campaign spread there (0.196–0.305) is too wide to conclude it.

*This is the paper's own thesis arriving uninvited:* we attached an instrument to measure why an
instrument was failing, and it changed what it came to observe, in the arm where the quantity was
smallest. Nothing rests on that arm's level, so it costs nothing — but a kernel tracer is not a
free observer.

*The instrument check is weaker than we first reported.* The campaign's own untraced twin exists
— the first attempt, whose probe never attached, kept as `ea9_notrace` and run ~2h earlier. It
measures **0.2717** against the traced run's 0.2315: the traced rate is **14.8% lower**. An
earlier version compared against a *different* campaign's 88% arm (0.2214) and called the 4.6%
gap a clean bill of health. Honest reading: the 88% ordinary arm spans 0.221–0.305 across five
campaigns (1.38×), and both the traced value and its twin sit inside that spread — so tracing did
not move the rate by more than the drift already there, and **a tracing effect below ~15% is not
resolvable with this control**.

That limits the *level*, which nothing rests on. The 0.181-vs-0.231 comparison is between two
quantities measured in the **same run**, so a common perturbation moves both and leaves their
agreement intact.

*Open:* the real-time arm recorded exactly zero inversions. Under the usual floor (~0.004) the
chance of that in 2985 events is 6.4 × 10⁻⁶, so either that arm genuinely differed or tracing
affected it — and the instrument check covered only the ordinary arm. The traced tail did fall
9.8×, so the direction holds; the level in that arm does not.

### The distribution is extraordinarily heavy-tailed

A 77× increase in threshold (E-A10) bought only a 4.1× reduction in rate, and P(stall > 0.5 ms)
is 0.18 (E-A9). **Inversions come from rare, very long stalls, not typical ones.** This is why
mean-based counters could not account for the effect, and it was predicted from E-A10 before
E-A9 measured it.

### A rule, not only a mechanism: the tail index

E-A10 varies `T_true` at fixed load, so it probes the stall distribution's shape directly. If
run-queue delay has a heavy tail with index `alpha`, then `P(stall > t) ~ C·t^-alpha`, and the
inversion rate is a power law in `T_true` with no free load parameter:

```
P(inversion) = 0.238 · T_true^(-0.339)      [T_true in ms]      R² = 0.9898, 4 points, 77× span
```

**`alpha = 0.34` is below 1, so the stall distribution has no finite mean and no finite
variance.** That is the useful part. It does not merely restate that the mean-based counters in
E-A7 failed to explain the effect — it explains *why* they could not: the sample mean of such a
distribution wanders with sample size instead of converging, so an instrument built on averages
is **structurally** blind to this failure rather than unluckily insensitive to it.

*Independent check.* The rule predicts `P(stall > 0.5 ms) = 0.301`. E-A9's kernel trace measures
**0.181**. Ratio 1.66 — same order, from a fitted payload sweep and a `sched_switch` trace that
share no data, no instrument and no estimator. The rule over-predicts, which is the expected
direction: not every stall lands on a stamping instant, so the observed rate should sit below the
probability that a sufficiently long stall occurred at all.

**The exponent replicates.** Fitting E-A10b's four points independently:

| campaign | alpha | C | R² | predicted P(stall>0.5ms) | vs traced 0.181 |
|---|---|---|---|---|---|
| E-A10 | 0.3387 | 0.2377 | 0.9898 | 0.301 | 1.66× |
| E-A10b | 0.3437 | 0.2159 | 0.9951 | 0.274 | 1.52× |

`alpha` agrees to 1.5%, and is below 1 in both — so both campaigns say the stall distribution has
no finite mean. The prefactor moves more, which is what a drifting level and a fixed shape look
like, and it is the shape that carries the claim.

*Limits, stated plainly.* Four points per campaign, one load level. `alpha` is fitted, not
derived, and the residual factor of ~1.6 between the rule and the kernel trace is unexplained
rather than accounted for. The replication buys that the exponent is a property of the system
rather than of one afternoon; it does not buy a derivation or an account of the gap.

### L1 — the real-time floor is the idle rate

Loaded at real-time priority: 0.0049. Unloaded at ordinary priority: 0.0035. Ratio 1.38. Two
unrelated experiments agree: load with a runnable stamping thread looks like no load at all.

### L2 — the ceiling is physical

The rate saturates at 0.37, not near 1, and three campaigns reaching saturation agree to within
1.11×. Under `P = p·S` with `p` a probability, that ceiling estimates `S` — a measured quantity
rather than a fitted asymptote.

### A benchmark reports a latency summary from a small and unstated fraction of its samples

*Revised 2026-07-26. This entry previously read "The exposure is not ours alone" and reported
6,000 discarded samples as the same causality violation we report. The sign-separated sweep
refutes that: **zero negatives in ~420,000 discards**, and a discard share that FALLS as load
rises. Every discard was a millisecond-tick collision. See `referee_response_plan.md`, R1.*

Across 16 cells of the instrumented OpenMessaging Benchmark, retention — the share of end-to-end
samples surviving its `if (endToEndLatencyMicros > 0)` guard — ranges from **0.83% to 100%**, a
120-fold spread. The reported p50 takes two values, 1.0 and 2.0 ms, and does not track retention:
one cell computed its summary from 998 samples and another from 120,425, and both report a median
of 1.0 ms.

The reported **average** moves, and it moves the wrong way:
**Spearman(retention, reported average) = −0.644**. Discarding everything below one tick removes
the *fast* samples, so the mean is taken over the surviving slow tail. The benchmark reports a
higher latency the more data it discards, and reports nothing about having discarded it.

The source-level finding is unchanged and never depended on the run: the guard admits only
positive samples, nothing counts the drops, the reported distribution is conditioned on being
positive, and the retention rate is unrecoverable from a completed run.

Source: `docs/results/external/omb_retention.csv`, `scripts/omb_retention_table.py`.

---

## Withdrawn or failed

**The M/G/1 functional form.** With points at ρ = 0.881–0.990, where the candidates diverge,
M/G/1 fits *worse than the mean* (R² −0.05 against a fitted exponential's 0.93). Not merely
unsupported: separated and ruled out.

**Our own bounded load-axis prediction.** Registered 2.45–3.07× over ρ 0.881→0.990; observed
1.44×. Being nearer than M/G/1's 13.8× does not make it a hit.

**Occupancy as the quantitative explanation.** Measured occupancy moves ~2× and mean stall length
3–5× against a 40× change in rate. Both are means; the effect lives in the tail. The *direction*
survives, the *magnitude* does not.

**H1's intermediate effect-size points.** netem at the broker delays the acknowledgement and
delivery paths equally and cancels in the difference. The sweep never manipulated what it claimed
to.

**Co-location as a T_true manipulation.** Removing the network hop made transport *longer*
(0.512 → 0.573 ms): it traded network latency for CPU contention. Two of three attempts on this
axis failed for structurally similar reasons, which is itself a reportable property — this
quantity resists manipulation because every route to shortening it lengthens something else.

---

## Still open

- **What sets the level.** The mechanism predicts the rate to within 22% in one arm. There is no
  formula for the rate at a given load, and two attempts to write one have failed.
- ~~The real-time arm's zero needs an untraced control~~ — **settled**: three traced arms read zero against an untraced twin's 15/2985. It is a tracing artefact.
- **Distributed OMB.** Five attempts, five distinct faults in the benchmark's worker protocol.
  The cross-host clock channel is bounded independently at ~0.067 ms — below OMB's millisecond
  resolution — so the untested channel is the one least able to matter here.

---

# Family B — the resolution failure mode (2026-07-27)

Everything above concerns Mode A: the clock read displaced from the event by a scheduling stall,
governed by `P(inversion) = P(stall > T_true)`. This family concerns a second, independent way the
same class of measurement fails, governed by a different instrument timescale against the same
`T_true`.

## The unifying statement

Both families compare **an instrument timescale against the interval being measured**:

| | instrument timescale | failure when | consequence |
|---|---|---|---|
| **A** | scheduling stall | stall > `T_true` | the difference goes negative — an *impossible* measurement |
| **B** | timestamp quantum τ | τ > `T_true` | the difference computes to zero — a *deleted* measurement |

Both therefore worsen as `T_true` shrinks, which is why both bind hardest on the fast paths and
small differences that broker comparisons exist to resolve. **This is the paper's general claim.**

Within Family B there is a second unification, one level down: B1–B5 are regimes of a single
rotation-orbit model — retention is the occupancy of an arc of width `T_true/τ` by the orbit of
`φ → φ + Δ mod τ`, with B1 the expectation of the branch law at every q, B2 its q=1 corner, and
the drift intermediates its third regime. Stated, checked against all existing arms, and
pre-registered for chain17 in [general_model.md](general_model.md).

## B1 — retention law  *(ESTABLISHED, 2026-07-27)*

Under **dephased** sampling, a sample survives a positivity guard only if its delivery crosses a
tick boundary. With send phases uniform within the tick:

```
retention = min(1, T_true / τ)
```

**Confirmed by moving `T_true` at a fixed incommensurate rate (457 msg/s), n=3 per level:**

| payload | retention | implied `T_true` | ΔT per byte |
|---|---|---|---|
| 200 B | 52.03% | 0.520 ms | baseline |
| 1 KB | 50.32% | 0.503 ms | −2.600 † |
| 2 KB | 53.37% | 0.534 ms | 0.908 † |
| **32 KB** | **68.44%** | 0.684 ms | **0.630** |
| **64 KB** | **85.36%** | 0.854 ms | **0.638** |

† payload delta under 2 KB; predicted change is below replicate noise, so the ratio is scatter
over a small denominator. Reported rather than dropped.

**Retention rises 33.3 points against a largest within-level spread of 2.6** — a 13:1 ratio. The
stronger result is that the implied `T_true` rises **linearly** in payload wherever the
manipulation exceeds the noise: 0.630 and 0.638 per byte, two independent estimates agreeing to
1.3%, implying an effective path near 1.6 Gb/s.

**What this cost and what it did not.** The pre-registered prediction of 78% at 32 KB assumed
exactly 1 Gb/s and was 8.7 points high. The *law* survived; the *assumed link speed* did not, and
is now measured from the data. A first attempt at this sweep used payloads entirely inside the
noise-dominated regime and settled nothing — the design fault was ours, not the law's.

Cross-checks on `T_true ≈ 0.5 ms` at baseline: OMB's own unquantised publish latency (0.3–0.4 ms
plus consumer delivery), this project's transport measurements (0.1–0.5 ms), and the dephased
retention itself. Three routes, one number.

## B2 — commensurability law  *(ESTABLISHED by manipulation)*

If the producer's send interval Δ is an **exact multiple** of the timestamp quantum τ, every
sample in a run shares a phase, and retention becomes bimodal and irreproducible. If Δ is
incommensurate with τ, samples dephase and B1 applies.

| rate | Δ | Δ/τ | retention spread |
|---|---|---|---|
| 500/s | 2.000 ms | **2 exactly** | **99.5 pts** |
| 457/s | 2.188 ms | 2.188 | 2.1 pts |
| 383/s | 2.611 ms | 2.611 | 2.8 pts |

**The decisive test is not that the locked arm is unstable — it is that the two dephased arms agree
with each other.** Their intervals differ by 19%; their medians by under 2 points. Retention as a
function of the interval would separate them; retention as `T_true/τ` requires them to agree.

*Confirmation pending:* 1000 msg/s (1.000 ms) and 250 msg/s (4.000 ms) predicted bimodal; 333 and
611 msg/s predicted stable. If the new exact multiples are stable, B2 is wrong.

## B3 — summary insensitivity  *(ESTABLISHED)*

The reported percentiles of a quantised measurement do not track retention. Across 49 unsaturated
cells, retention spans **0.36%–100%** (278-fold) while the reported p50 takes **two values**
(1.0, 2.0 ms). One cell summarised 998 samples, another 120,425; both reported 1.0 ms.

Corollary, and the sharper form: **the benchmark's own output already states the problem.** All 32
percentile values across eight runs are whole milliseconds; three runs report
p50 = p95 = p99 = max = 1.0. A distribution with one value in it, printed to three decimals.

## B4 — non-convergence under phase locking  *(ESTABLISHED)*

Where B2 applies, a k-replicate median does not converge, because the quantity has no central
value. Measured: per-level median retention reproduced at **1 load level in 5** across three passes
of an identical configuration, moving 54–98 points at the others. At one configuration, n=18 gives
6 runs below 2%, 8 above 90%, 4 between — median 23.4%, a value 1 run in 18 produced.

**Practical corollary:** within-pass agreement is not evidence of reproducibility. One pass had
three replicates agreeing to 3.58 points and sitting 98 points from the same configuration hours
earlier.

## B5 — quantisation law  *(ESTABLISHED, 9/9 arms including the rate-independence control)*

B2 is binary and that is not the whole rule. Write the send interval over the quantum as a fraction
in lowest terms, Δ/τ = p/q. After q sends the phase returns to where it started, so the producer
visits exactly **q** distinct phases and retention can take only q+1 values. A replicate therefore
lands on one of the **two grid points bracketing T_true/τ**, and B2 is just the q=1 corner of it.

**The spread that follows is not 100/q.** That is the cell width, and it is an *upper bound*
attained only when T_true/τ sits midway between two grid points, where both bracketing points get
realised across replicates. When T_true/τ sits *on* a grid point, one point takes nearly every run
and the spread collapses toward zero. One formula, two regimes:

> spread → 100/q when T_true/τ is mid-cell &nbsp;•&nbsp; spread → 0 when T_true/τ is on a grid point

Measured T_true/τ = 0.495 here, so odd q put it near mid-cell and even q put it on a grid point.

| rate | Δ/τ | q | cell width | position | predicted | measured |
|---|---|---|---|---|---|---|
| 1000/s | 1/1 | 1 | 100.0 | mid | full | **99.3** ✓ |
| 500/s | 2/1 | 1 | 100.0 | mid | full | **99.5** ✓ |
| 250/s | 4/1 | 1 | 100.0 | mid | full | **58.6** ✓ (weakly) |
| 400/s | 5/2 | 2 | 50.0 | **on grid** | **flat** | **17.6** ✓ (3.1 without one outlier) |
| 300/s | 10/3 | 3 | 33.3 | mid | full | **30.5** ✓ |
| 800/s | 5/4 | 4 | 25.0 | **on grid** | **flat** | **7.2** ✓ |
| 625/s | 8/5 | 5 | 20.0 | mid | full | **17.9** ✓ |
| 875/s | 8/7 | 7 | 14.3 | mid | full | **10.7** ✓ |
| 457, 383, 611, 889, 333/s | — | >64 | — | continuous | ~0 | 1.7–3.1 ✓ |

**All 8 commensurate arms match**, six predicted full and two predicted flat, and the classification
is identical whether the continuous value is estimated pooled (49.5%) or rate-locally (45.9–51.5%),
because it measures distance against the cell half-width rather than a fixed noise floor.

**This corrects an error of ours, and the earlier version is worth keeping visible.** We first wrote
the prediction as `spread ~ 100/q` and treated it as a point prediction. Under that reading the even
q looked like failures, and we introduced a *degeneracy exclusion* to set them aside — defensible,
because it was derived from q=4 and committed at 14:09Z before the first odd-q cell was measured at
15:06Z, but weaker than it needed to be. Stated correctly the exclusion is unnecessary: an on-grid
arm is a **prediction of a flat arm**, so q=2 and q=4 are evidence *for* the model rather than cases
to be excused. A law that explains its exceptions beats a law that excludes them.

**A second prediction of ours failed outright.** We wrote "q=5 → 2 of 5 phases cross → 40%". The
median came out at 46.6%. The error was naming one branch of a two-branch prediction: with T_true/τ
at a half, 2 *or* 3 phases cross depending on the run's initial phase, giving 40% *or* 60%. The
replicates — 40.7, 42.1, 46.6, 55.5, 58.6 — are bimodal about exactly those two. **The grid held;
the point we picked on it did not.**

**Where the account is approximate.** 250/s (q=1) gives a spread of 58.6 where the cell width is
100, and 500/s has one replicate at 18.0 that a single-phase run should not produce. A nominal
exact multiple is only q=1 if the pacing is exact for the whole run; over three minutes a drift of a
few parts per million walks the phase across a boundary mid-run. The grid that governs retention is
the one the pacing *realises*, not the one the nominal rate implies.

**chain17 (2026-07-28) refined this law rather than overturning it.** The grid's vertices are
attractors, not the values themselves: every arm's replicates sit displaced from their grid points
*toward* T_true/τ, by a jitter kernel whose width in cell units tracks the **numerator p** (all
three arms with p=10 smeared mid-cell; no arm with p≤8 did) and is independent of run duration
(1/3/10-minute sweep flat — the walk account died there). The regime is also mobile between passes
at fixed configuration. The law's sharpest confirmation survived all of it: payload moves T_true/τ,
and its position in the grid cell flipped the 300/s arm flat→full on command (spread 13.6 pinned
at 32 KB → 26.7 with the upper vertex hit at 64 KB). Full record: general_model.md, chain17
outcomes.

**The rate-independence control passed, and it is exact.** q=3 repeated at 600/s — half the
interval of 300/s, same denominator — was pre-registered to reproduce a full-cell spread of ≈33,
failing which the governing variable would have been the rate and B5 would shrink back to B2.
Measured (n=4; a fifth run lost its shutdown hook and is excluded by rule, tracked as invalid):

| rate | interval | q | retentions | spread |
|---|---|---|---|---|
| 300/s | 3.333 ms | 3 | 34.86 36.72 39.42 41.13 **65.35** | 30.5 |
| 600/s | 1.667 ms | 3 | 33.97 34.29 34.90 **66.67** | 32.7 |

Not merely the same spread — the same **grid points**. The q=3 grid is {33.3, 66.7}, and 600/s put
three replicates on the lower branch and one at 66.67, which is 2/3 to two decimal places. Two
rates an octave apart land on the same two-point set because they share a denominator. **q is the
governing variable; the rate that carries it is irrelevant.** Verdict: QUANTISED, 9 of 9 arms.

## What follows for practice

1. Do not pace a load generator at a rate commensurate with the timestamp quantum; dither if the
   rate is fixed. *(from B2)*
1a. "Not an exact multiple" is not enough — safety comes from a **large denominator**, and a rate
   like 300/s is nearly as dangerous as 500/s. *(from B5)*
2. Publish the retention rate. *(from B3 — it is unrecoverable from a completed run)*
3. Publish the timestamp resolution beside the measured latency. *(from the unifying statement —
   the failure is governed by their ratio)*
4. Do not let three replicates stand in for reproducibility. *(from B4)*
