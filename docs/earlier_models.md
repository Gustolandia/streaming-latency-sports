# The models that came before the law

Two models written before the campaigns that settled the mechanism. Both are partly
superseded by `laws.md`, and both say so where they are wrong. They are kept because a
model that was tried and found wanting is part of the record, and because
`scripts/fit_two_state.py` and `scripts/analyze_separability.py` still implement the first
of them.

*Fused on 2026-09-21 from 2 documents, each carried over unchanged below.*

## Contents

- [A model that fits: two-state stamping](#a-model-that-fits-two-state-stamping) — was `docs/two_state_model.md`, last changed 2026-07-26
- [The general model: rotation-orbit occupancy](#the-general-model-rotation-orbit-occupancy) — was `docs/general_model.md`, last changed 2026-07-28

## A model that fits: two-state stamping

> Was `docs/two_state_model.md`.

> **Status: partly superseded.** Written before the campaigns that decided the mechanism. Its
> load-axis reasoning is replaced by [laws.md](laws.md), which reports the manipulations: at
> identical utilisation two load geometries differ 2.07x and 2.05x, so no function of `rho` --
> including the ones argued for below -- can be the mechanism. The two-state framing itself
> survives and is what the paper reports; the parts that parameterise it in `rho` do not.


The paper's model treats the stamping asymmetry `Δ` as one distribution. Three results have now
falsified or undermined parts of that picture, and this document states the replacement, the
evidence for it, and — because the replacement was found by looking at data — exactly which part
of it is confirmatory and which part still needs a fresh test.

---

### 1. What failed

| Claim | Status | Evidence |
|---|---|---|
| `Δ` is a scale family (one shape, load sets the width) | **falsified** | tail mass spreads 23× across load at matched standardised distance (H9) |
| The M/G/1 form specifically | **withdrawn** | a fitted exponential matches or beats it; two campaigns disagree on which wins |
| netem delay manipulates `T_true` | **false** | TTI tracks the injected delay (3.7→23.6 ms) while transport stays flat (0.535→0.480 ms) |

The third is new and it is the sharpest. Injecting delay at the broker delays the acknowledgement
path *and* the delivery path by the same amount, so it **cancels in the subtraction**
`t_consume − t_ack`. The delay sweep was never an effect-size manipulation. That is why H1's
intermediate points are being dropped, leaving the co-located-versus-network contrast — which
needs no manipulation, because the two regimes genuinely differ by five orders of magnitude.

What survives from the old model is the part that was never about shape: `T_measured = T_true + Δ`,
and an inversion occurs exactly when `Δ < −T_true`. That is arithmetic and it stands.

---

### 2. The observation the old model cannot produce

Inversions **cluster in time**. Wald–Wolfowitz runs-test `z` is −4.3 to −6.9 across every load
level, including idle. Inversions arrive in bursts of consecutive events, not as independent
draws.

No single distribution — of any shape, however heavy-tailed — predicts this. A distribution
describes *how large* a delay is, and says nothing about *which events* get one. Clustering is a
statement about time, and it is the clue the old model had no way to use.

---

### 3. The model

The stamping thread is in one of two states.

- **RUNNING.** It reads the clock promptly. The delay is ordinary jitter: a narrow core of width
  `σ_c`.
- **PREEMPTED.** It is off-CPU. Every event that becomes ready during this interval inherits the
  *residual* time until the thread is rescheduled.

Writing `p` for the fraction of time spent preempted and `R` for the residual:

```
Δ  ~  (1 − p) · Core(σ_c)   +   p · Residual(R)

P(inversion | T_true)  =  p(ρ) · S(T_true)        where S(t) = P(R > t)
```

The failure is therefore **not a wide distribution but a rare state**. Load does not mainly
stretch the delay; it changes how often the stamping thread is not running.

### 4. What this explains that the old model could not

**Clustering (H8).** PREEMPTED is an *interval*, not a point event. Every event arriving inside it
is affected together, which produces runs of consecutive inversions. This is a prediction, not an
accommodation — a two-state process cannot help but cluster.

**Weight moves faster than width (H10).** From idle to the knee, the core widens 5× while the
inversion rate grows 60×. Under the model these are different parameters: `σ_c` is a property of
the RUNNING state, `p` of the scheduler. A 12:1 ratio is what "load changes `p`, not `σ_c`" looks
like.

**Why the scale family failed (H9).** A scale family requires one parameter. Here two move, at
very different rates, so no rescaling of a single shape can align the conditions.

**Why M/G/1 and exponential are indistinguishable.** The `ρ` dependence lives in `p(ρ)`, a busy
fraction bounded in [0,1]. Over the sampled range both forms approximate it, and neither is the
mechanism — the mechanism is occupancy.

### 5. The new prediction, and it already has support

The two structures make *opposite* geometric predictions for how the tail curve moves with load:

| model | prediction on a log tail-mass plot |
|---|---|
| scale family | curves **rescale horizontally** (σ changes) |
| two-state | curves **shift vertically and stay parallel** (p changes) |

Tested on the E-A3 data, restricted to tail estimates backed by ≥20 events (the far-tail points
with 5–8 events are pure noise and were excluded):

```
condition    log-ratio vs reference, per threshold    spread
bg8          +0.16  +0.15  +0.07  +0.09              0.09   separable
bg12         -0.19  -0.20  -0.09  +0.07              0.26   separable
bg5          -2.56  -2.68  -2.85                     0.29   separable
bg7          -0.35  -0.35  -0.67  -0.94              0.60   partial
bg6          -1.42  -1.44  -2.34                     0.91   partial

median spread 0.29  (a factor of 1.34)
```

Against the scale family's 23× failure, a median 1.34× departure from a pure vertical shift is
strong support. The two "partial" conditions sit at intermediate load, where the residual
distribution itself is plausibly still shifting — so the honest form of the model is

```
P(inversion | c, ρ) = p(ρ) · S(c ; ρ)
```

with `p` varying fast and `S` slowly. Separability is a good first-order approximation, not an
exact law, and we should say so.

### 5a. Correction: the load axis, and what the ladder cannot decide

§3 writes `P(inversion | T_true) = p(rho) * S(T_true)`. Read as a model of how the rate depends on
load, **that equation has no content**, and it should not have been written without saying so:
with `p` left free, any monotone rate curve can be expressed as `p(rho) * S` by setting
`p = rate/S`. Its content is on the *threshold* axis, which is where §5 tests it and where it
passed. The paper has already withdrawn one functional form for being unfalsifiable; the
replacement must not repeat it.

Given a *parametric* `p` the form becomes testable, and `scripts/fit_two_state.py` tests it:

| model (3 free parameters each) | R² in log space | inputs |
|---|---|---|
| two-state, `S` fixed, `p = rho^C` | 0.6534 | rho |
| two-state, `S(mu/(a*sigma))` | **0.9905** | rho, sigma, mu |
| `floor + exp(k rho)` | 0.9811 | rho |
| `floor + (rho/(1-rho))^k` | 0.8863 | rho |

The corrected form comes from restoring what the separability test divided out. That test works on
*standardised* thresholds `z = c/sigma`. An inversion needs the residual to exceed `T_true`, so in
standardised units the threshold is `T_true/sigma(rho)` — and `sigma` grows 5× across the ladder,
so the threshold slides toward zero as load rises. Both factors climb with load:

```
P(inversion | rho) = p(rho) * S( T_true / sigma(rho) )
```

**But the lead is not evidence, and the script says so.** Freeze `sigma` at its mean and refit:
R² *improves* to 0.9982, a residual ratio of 0.19. On this ladder `sigma` rises monotonically with
`rho`, so the two move together and no fit can credit one over the other. The corrected form's
higher R² is bought with two extra columns, not with mechanism.

That is a limit of the **experimental design**, not of the analysis, and no further work on these
data can lift it. Which is what E-A5 is for.

### 5b. E-A5: the decisive experiment (queued, not yet run)

Break the collinearity by moving occupancy while holding utilisation fixed. Raising the stamping
processes to `SCHED_FIFO` makes them preempt the background load instead of queueing behind it;
`p` falls sharply, `rho` does not move, because the same stressor does the same work.

This is also the manipulation netem should have been. Injecting delay at the broker failed because
it delayed the acknowledgement and delivery paths equally and cancelled in the subtraction (§1).
Scheduling priority has no such symmetry — it acts on the stamping threads themselves.

| mechanism | prediction |
|---|---|
| occupancy (two-state) | rate collapses toward `C0 ≈ 0.004`, order 50× at high load, `rho` unchanged |
| utilisation (M/G/1, `exp(k rho)`) | rate is a function of `rho`; `rho` is unchanged, so **no change** |

An order of magnitude apart, so it is decisive either way. `scripts/analyze_stamping_priority.py`
runs the manipulation check first and **withholds the comparison** if `rho` differs between arms
by more than 5 points — the lesson E-B2 taught at the cost of a campaign.

### 6. Merits

**It is mechanistic rather than descriptive.** "Inversion risk rises with utilisation" is a
correlation. "The stamping thread is preempted a `p(ρ)` fraction of the time, and every event
arriving in that window is corrupted together" is a mechanism that names the moving part.

**It unifies four separate findings** — the clustering, the mixture, the failed collapse, and the
un-discriminable functional form — under one cause, and it was not built to do that: three of the
four were already published results the model had to accommodate.

**It is actionable.** If the failure is *occupancy*, the mitigation is not a faster clock but
keeping the stamping thread runnable: dedicate a core, raise its priority, or stamp on a thread
that cannot be preempted by the workload. A model that says "widen your error bars" gives no such
advice.

**It connects to established work.** Li et al. (SoCC'14) trace tail latency to background-process
interference and show measured tails exceed queueing predictions; the two-state picture is that
mechanism observed in the *instrument* rather than the system.

### 7. Weaknesses, stated plainly

**It was found by looking at the data.** The separability test in §5 is exploratory. It must be
repeated on data collected afterwards before it can be reported as confirmed, and the
pre-registration below exists for that reason.

**On the load axis it is currently unidentified.** §5a: the simplified equation is a tautology,
and the corrected one cannot be separated from a plain exponential in `rho` because `sigma` and
`rho` are collinear on our ladder. Until E-A5 reports, the model's standing on this axis is *not
yet tested*, which is weaker than "supported" and must be written that way.

**`p` and `S` are not separately observed.** Both are inferred from the same tail. Measuring `p`
independently — from scheduler statistics, run-queue occupancy, or `sched_switch` tracing —
would make the model far harder to fit to a wrong answer.

**Two states is a simplification.** Real schedulers have priorities, migrations, interrupts and
NUMA effects. Two states is the smallest model consistent with what we observe, not a claim about
what the kernel does.

**The `T_true` axis is now hard to manipulate.** §1 shows netem cannot move it for this span. The
separability prediction is therefore tested by varying the *threshold* analytically rather than
by varying the true latency experimentally, which is weaker: it probes the shape of the measured
distribution, not the response to a real change in the quantity measured.

### 8. Pre-registered confirmatory test

**Prediction.** On a campaign run after this document is committed, tail-mass curves at different
loads, restricted to estimates with ≥20 supporting events, are parallel on a log scale: the
pairwise log-ratio between any two conditions is constant across thresholds.

**Supported if** the median spread across conditions is below 0.5 in log units (a factor of 1.65),
and no condition with three or more well-supported thresholds exceeds 1.0.

**Falsified if** the median spread exceeds 1.0, or the spreads vary systematically with load in a
way a fixed `S(c)` cannot produce.

**If falsified**, the separable form is dropped and we report the mixture (H10) without it — the
mixture is independently supported and does not depend on separability.

**Independent measurement of `p` (proposed, not yet run).** Sample `/proc/<pid>/schedstat` field 2
(time spent waiting on a run queue) for the producer during a run. The model predicts that the
directly measured runnable-but-not-running fraction tracks the `p(ρ)` inferred from tail mass. If
those two disagree, the model is wrong in a way no amount of curve-fitting would reveal.


---

## The general model: rotation-orbit occupancy

> Was `docs/general_model.md`.

*2026-07-27. Status: stated, checked against all existing arms, pre-registered for chain17
(the comprehensive run). This document is the model's record; `docs/laws.md` holds the laws it
unifies; `scripts/analyze_phase_quantisation.py` implements its verdicts.*

### The model in one paragraph

Let a producer send at a fixed interval Δ against a timestamp quantum τ, and let the true
delivery latency be T_true < τ, written θ = T_true/τ. The i-th send occurs at phase
φ_i = (φ₀ + iΔ) mod τ within the quantum. A sample survives the benchmark's `> 0` guard exactly
when its delivery crosses a tick boundary, i.e. when φ_i ∈ [τ − T_true, τ). Retention is therefore
the **occupancy of an arc of width θ by the orbit of a circle rotation** — nothing about brokers,
Java, or load appears in it. Every Family-B law is a regime of this one object.

### The regimes, and which law each one is

**Rational Δ/τ = p/q (lowest terms): the quantised regime.**
The orbit is exactly q points spaced τ/q apart, at an offset set by φ₀. The number of orbit points
inside an arc of width θ is ⌊qθ⌋ or ⌈qθ⌉ — never anything else — so a run retains one of two
fractions:

    retention ∈ { ⌊qθ⌋/q , ⌈qθ⌉/q }        (the two grid points bracketing θ)

and if φ₀ is uniform over the quantum,

    P(upper branch) = frac(qθ).

- **B2** is the q=1 corner: branches {0, 1} — all-or-nothing.
- **B5** is the general statement. Replicate spread reaches the cell width 100/q only when θ sits
  mid-cell (frac(qθ) ≈ ½) and collapses when θ sits on a grid point (frac(qθ) ≈ 0 or 1). The
  flat/full classification in the analyser is this: "position > 0.5" ⇔ frac(qθ) ∈ (¼, ¾).
- **B4** (non-convergence) follows: within the quantised regime the retention has no central
  value, so a k-replicate median estimates a Bernoulli mixture, not a location.

**Irrational (or astronomically large q): the continuous regime.**
By Weyl equidistribution the orbit fills the circle uniformly, so every run retains θ:

    retention → θ = T_true/τ        (B1)

with run-to-run variance → 0. This is the "classical limit" of the quantised regime, reached two
ways: q → ∞, or (see drift, below) the *realised* orbit filling in even when the nominal one is
sparse.

**The bridge: B1 is the expectation of B5 at every q.**
Averaging over the initial phase, E[retention] = θ **exactly, at every q** — the mean of
⌊qθ⌋/q and ⌈qθ⌉/q under P(upper) = frac(qθ) is θ identically. B1 is not just the large-q limit;
it is what the quantised regime already averages to. *Checked against all 39 replicates across the
nine commensurate arms: pooled mean retention 49.9% against a replicate-weighted θ of 49.0%.*

**Drift: the idealisation's edge, and the third regime.**
A nominal rate gives q only if the pacing is exact for the whole run. With relative pacing error ε
the phase comb migrates by NεΔ over N sends, and a branch change occurs mid-run once that exceeds
the distance to the next grid boundary. The threshold is

    ε* ≈ 1/(pN)     (cross once) ,     realised orbit fills a cell when ε ≫ ε*

For our three-minute runs, ε* is a few parts per million at q=1 — which no software pacer holds —
so the q=1 arms show mid-run crossings: 41.39 at 250/s, 18.02 at 500/s, the 58.6-point spread
where the cell width is 100. Large drift interpolates retention between branches and, taken far
enough, recovers the continuous regime: the realised grid governs, not the nominal one. The
intermediates are not exceptions to the model; they are its third regime, entered when NεΔ spans
a cell.

### What the existing arms say (all of it, 2026-07-27 ledger, 148 cells)

| rate | q | θ_local | qθ | branches | P(upper) | observed upper/n | mean ret. |
|---|---|---|---|---|---|---|---|
| 1000/s | 1 | .459 | .459 | {0,100} | .459 | 2/3 | 66.9 |
| 875/s | 7 | .469 | 3.281 | {42.9,57.1} | .281 | 3/5 | 48.7 |
| 800/s | 4 | .474 | 1.897 | {25,50} | .897 | 5/5 | 47.7 |
| 625/s | 5 | .487 | 2.437 | {40,60} | .437 | 2/5 | 48.7 |
| 600/s | 3 | .489 | 1.468 | {33.3,66.7} | .468 | 1/4 | 42.5 |
| 500/s | 1 | .497 | .497 | {0,100} | .497 | 1/4 | 30.0 |
| 400/s | 2 | .504 | 1.008 | {50,100} | .008 | 0/5 | 54.7 |
| 300/s | 3 | .512 | 1.535 | {33.3,66.7} | .535 | 1/5 | 43.5 |
| 250/s | 1 | .515 | .515 | {0,100} | .515 | 2/3 | 80.3 |

No arm rejects P(upper) = frac(qθ) (exact binomial, all one-sided tail probabilities in
0.15–0.98). The branch counts lean low of prediction in the q=3 arms (2 upper of 9 pooled against
p ≈ 0.5); chain17's P1 gives this the n to decide. θ_local is the rate-local continuous value from
the incommensurate trend (51.2% at 333/s to 47.5% at 889/s), itself consistent with a small
rate-dependent component of T_true.

### Where it sits in the literature

- **Weyl equidistribution (1916)** gives the continuous regime; the **three-distance theorem**
  (Steinhaus; proved by Sós 1958) governs the finite-orbit structure between our regimes. Neither
  appears in any benchmarking context we can find.
- **Dither theory** (Schuchman 1964; Wannamaker, Lipshitz & Vanderkooy's non-subtractive dither
  treatments) supplies the design condition our recommendation reduces to: dither uniform over one
  quantum satisfies Schuchman's condition, making the deletion probability independent of the
  pacing arithmetic. "Choose an incommensurate rate" is an ad-hoc approximation to it; "dither the
  send instant" is the theorem.
- **Coordinated omission** (Tene) remains the benchmarking literature's nearest object: it loses
  the slow tail by not sampling; this mechanism loses the fast bulk by sampling and discarding.
  The two are complementary failures of the same instrument, and HdrHistogram ships a correction
  for the first while its positivity convention motivates the second.
- The application of orbit occupancy to benchmark sample retention — and the quantitative form,
  branches at ⌊qθ⌋/q with P(upper) = frac(qθ) — appears to be new.

### Pre-registered predictions for chain17 (the comprehensive run)

Recorded before any chain17 cell has run. Falsifiers stated inline; the analysis that will judge
them is committed (`analyze_phase_quantisation.py`, plus the branch-count binomial below).

- **P1 (branch probabilities).** Pooling q=3 arms to n≈20 (300/s and 600/s at 10 and 5+ reps),
  upper-branch count ~ Binomial(n, frac(3·θ_local)). *Falsified if the exact binomial two-sided
  p < 0.01.*
- **P2 (second rate for q=5).** 1250/s (Δ = 0.8 ms = 4/5) is the first arm with Δ < τ and p < q:
  predicted full, spread ≈ 20, branches {40, 60}, same set as 625/s. *Falsified if flat or off the
  fifths grid.*
- **P3 (second rate for q=7).** 700/s (10/7): predicted full, spread ≈ 14.3, branches
  {42.9, 57.1}, same set as 875/s. *Falsified if flat.*
- **P4 (q=9 discriminates under the class test).** 900/s (10/9): predicted full, spread ≈ 11.1,
  branches {44.4, 55.6}. The superseded median test called q≥9 unable to discriminate; the
  corrected class test says it can — this is the model revision's own novel prediction.
  *Falsified if spread is at the incommensurate level (≲3) — i.e. flat.*
- **P5 (drift crossover).** At 500/s, 1-minute runs should show *purer* branches than 3-minute
  runs, and 10-minute runs *more* mid-run crossings (replicates > 5 pts from both branches),
  because cumulative drift NεΔ scales with N. *Falsified if intermediates do not increase with
  duration.*
- **P6 (payload × q interaction — the model's sharpest test).** θ moves with payload
  (B1 manipulation, measured at 457/s: θ(32 KB) = 0.685, θ(64 KB) = 0.853). At 300/s (q=3):
  - 32 KB: qθ = 2.055, frac = 0.055 → **flat arm pinned at 66.7%** (P(3/3) = 0.055);
  - 64 KB: qθ = 2.56, frac = 0.56 → **full arm again, branches {66.7, 100}**.
  One manipulation, both directions: onto a grid point and off it. *Falsified if 32 KB spreads
  fully or centres off 66.7, or if 64 KB pins.* (Serialisation at 32 KB ≈ 0.16 ms ≪ the 3.33 ms
  interval, so no queueing confound; the rate-local θ trend of ±0.01 does not change either
  classification.)

**Scope note.** P1–P4 test the quantised regime, P5 the drift regime, P6 the coupling of the
regimes to the one physical parameter (T_true). A model failure in any single prediction is
reported as such; P6 failing while P1–P4 hold would indicate θ is not payload-portable across
rates, which is itself a finding about the θ_local trend.

---

### chain17 outcomes (recorded 2026-07-28, 01:06Z ALL DONE; 55/55 cells valid, 0 negatives)

Judged by the falsifiers stated above, with every interim reading timestamped in
`docs/referee_response_plan.md` before the next block ran.

| prediction | outcome |
|---|---|
| **P1** branch binomial | **not evaluable as registered** — mid-cell replicates (the evening 300/s arm: 51.03–55.93 in a {33.3, 66.7} grid) have no branch to be counted in; the classification the test presupposes does not exist for smeared arms |
| **P2** 1250/s full {40, 60} | **falsifier fired** (flat: 40.66–42.00 + 48.26, pinned on the 2/5 vertex) — interpretation pends chain17b's θ probe, running now |
| **P3** 700/s full {42.9, 57.1} | **falsifier fired** (flat at 6.5, smeared mid-cell toward θ) |
| **P4** 900/s full ≈11.1 | letter of the class test passed (6.9 > 5.56) with its substance absent — the 55.6 branch never appeared; the three-way pre-registration (20:35Z) showed no account clean |
| **P5** intermediates rise with duration | **falsified** — 1-min / 3-min / 10-min at 500/s gave 1 / 1 / 0 intermediates; duration does nothing |
| **P6** payload×q: 32 KB pins flat, 64 KB frees full | **confirmed** — spread 13.6 (tri-cluster 69.17–69.23) → 26.7 (upper vertex hit at 99.78); frac(qθ) 0.055 → 0.56 flipped the class exactly as registered, at fixed rate and q, through the noisiest pacing of the campaign. The one letter-miss: the 32 KB pin sits 2.4 above the vertex, displaced toward θ |

#### What chain17 adds to the model (v3)

Two regularities emerged mid-run, each pre-registered before the block that then tested it:

1. **Displacement toward θ is universal.** Every commensurate arm's replicates sit off their grid
   points *toward* θ, from +0.7 (1250/s) to full mid-cell smear. Grid occupancy is convolved with
   a jitter kernel; the vertices survive as attractors, not as the values themselves.
2. **The kernel width tracks p, not q, and not duration.** All three arms that smeared have
   p = 10 (300 = 10/3, 700 = 10/7, 900 = 10/9); no arm with p ≤ 8 smeared; and the duration sweep
   was flat (P5's falsification). Mechanism consistent with per-send pacer jitter proportional to
   the sleep interval: jitter in cell units = slop × p, since Δ/(τ/q) = p identically. Registered
   23:11Z, confirmed in direction by Block E. The cells-crossed-∝-q walk account of 20:35Z is
   dead: it cannot explain 625/s (q=5) holding cleanly while 300/s (q=3) smeared the same
   evening, and its duration dependence failed.
3. **The regime is mobile between passes at fixed configuration** (300/s branch-adjacent in the
   morning, mid-cell in the evening), which folds B4's irreproducibility one level deeper: not
   only does a phase-locked run have no central value, the *kind* of distribution it draws from
   moves on a timescale of hours. The chrony record (from 22:02Z) exonerates the disciplined
   clock; the pacer itself is unmeasured and is the right target for a dedicated instrument.

**The statement that survives everything measured so far:** retention is the occupancy of an arc
of width θ by a q-point grid convolved with a pacing-jitter kernel; the kernel's width in cell
units grows with p and varies between runs; E[retention] = θ at every q; and θ's position within
the grid cell decides flat or full — the one lever an experimenter controls (payload → θ) moved
it both ways on command (P6).

**The θ probe resolved (chain17b, ALL DONE 02:14Z).** θ(1053) = 47.15%, θ(1219) = 48.18% — the
linear trend's extrapolation (44.3 at 1219) is refuted; θ plateaus at ≈48% above 700/s. By the
reading recorded in the chain's header before it ran, **P2 stands as a genuine miss**: with
θ ≈ 0.48, the model predicted a full arm at 1250/s with P(upper) = 0.40 and got zero upper values
in five (probability ≈ 0.08). The same arm is strong evidence *against* the continuum — four
replicates pinned on the 2/5 vertex, 6–7 points below the measured local θ. The reconciling
observation, flagged as post-hoc: a jitter kernel narrower than the half-cell does not merely
displace values, it suppresses realisation of the minority branch, so P(upper) < frac(qθ)
systematically. That would also explain the upper-branch deficits at q=3 pooled and at 875/s. It
is a prediction for a future campaign, not a claim.

**Still open:** a per-run pacer-jitter instrument; the branch-suppression form of the kernel; and
the branch-probability law, untestable until arms can be conditioned on a quiet pacing regime.
