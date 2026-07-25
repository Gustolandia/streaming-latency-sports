# A model that fits: two-state stamping

The paper's model treats the stamping asymmetry `Δ` as one distribution. Three results have now
falsified or undermined parts of that picture, and this document states the replacement, the
evidence for it, and — because the replacement was found by looking at data — exactly which part
of it is confirmatory and which part still needs a fresh test.

---

## 1. What failed

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

## 2. The observation the old model cannot produce

Inversions **cluster in time**. Wald–Wolfowitz runs-test `z` is −4.3 to −6.9 across every load
level, including idle. Inversions arrive in bursts of consecutive events, not as independent
draws.

No single distribution — of any shape, however heavy-tailed — predicts this. A distribution
describes *how large* a delay is, and says nothing about *which events* get one. Clustering is a
statement about time, and it is the clue the old model had no way to use.

---

## 3. The model

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

## 4. What this explains that the old model could not

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

## 5. The new prediction, and it already has support

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

## 5a. Correction: the load axis, and what the ladder cannot decide

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

## 5b. E-A5: the decisive experiment (queued, not yet run)

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

## 6. Merits

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

## 7. Weaknesses, stated plainly

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

## 8. Pre-registered confirmatory test

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
