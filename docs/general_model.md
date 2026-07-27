# The general model: rotation-orbit occupancy

*2026-07-27. Status: stated, checked against all existing arms, pre-registered for chain17
(the comprehensive run). This document is the model's record; `docs/laws.md` holds the laws it
unifies; `scripts/analyze_phase_quantisation.py` implements its verdicts.*

## The model in one paragraph

Let a producer send at a fixed interval Δ against a timestamp quantum τ, and let the true
delivery latency be T_true < τ, written θ = T_true/τ. The i-th send occurs at phase
φ_i = (φ₀ + iΔ) mod τ within the quantum. A sample survives the benchmark's `> 0` guard exactly
when its delivery crosses a tick boundary, i.e. when φ_i ∈ [τ − T_true, τ). Retention is therefore
the **occupancy of an arc of width θ by the orbit of a circle rotation** — nothing about brokers,
Java, or load appears in it. Every Family-B law is a regime of this one object.

## The regimes, and which law each one is

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

## What the existing arms say (all of it, 2026-07-27 ledger, 148 cells)

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

## Where it sits in the literature

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

## Pre-registered predictions for chain17 (the comprehensive run)

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
