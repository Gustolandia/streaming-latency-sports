# Referee response plan

A demanding referee recommended **reject in present form** for the TOMPECS submission. This
document is the response plan: every issue raised, what we are doing about it, and the current
state. It supersedes the earlier "Phase 5" plan item, which described a manuscript rebuild that
has since happened.

The referee's decisive objection is not any single number. It is that a paper prescribing a
method to a field must show the method matters to somebody other than its authors. Everything
below is ordered by how much it moves that objection.

---

## M1 — The generalisation rests on n=1, and that n is us (DECISIVE)

**Referee:** "Nowhere is the check applied to anyone else's data... The honest reading is: this
team's harness had a defect that took six correction rounds to find. That may be a cautionary
tale; it is not yet a demonstration that the field has a problem."

**Accepted in full.** This is the correct criticism and it is the one that decides the paper.

**Action:** apply `clock_integrity.py` to a benchmark harness we did not write. Candidates, in
order of evidential strength:

1. **OpenMessaging Benchmark** — the canonical broker benchmark, already cited in §2.1. Requires
   a JDK and Maven on the driver. Produces per-message publish and end-to-end latency.
2. **Kafka's own `EndToEndLatency` tool** — ships with the distribution, so genuinely
   third-party, but runs producer and consumer in one process. That is itself a reportable
   result: a same-process harness *cannot* violate causality, which sharpens the scope of our
   claim rather than supporting it.
3. A published artefact from the streaming-benchmark literature, re-run.

**Reportable either way.** If an external harness fails the check, the paper's central claim is
established. If it passes, that is also publishable and materially changes the framing: the
check would then be a guard against a failure mode that careful harnesses already avoid, and we
would say so.

**Status: PARTIAL, and the gap matters.** The source audit (§6.7) establishes that OMB computes
the same cross-process difference and discards non-positive samples uncounted. That is real
evidence and it is checkable, but it is a *code audit*, not the *measurement* the referee asked
for.

**Why the obvious experiment is impossible.** You cannot apply the check to OMB's output, because
the violations never reach the output — the guard drops them inside the harness. This is a
consequence of the finding itself, not an excuse. The only empirical route is to make the
discards observable and then run the real benchmark.

**Queued (E-X, `omb_discard_count.sh`):** add ONE counter to `WorkerStats.java`, in the `else`
branch of the existing guard, and log it. The latency computation, the guard's condition and
every reported statistic are untouched — we only surface a quantity OMB already computes and
throws away. The patch is recorded as a diff alongside the result so a reader can see exactly what
changed. Then run OMB against our broker and report how many end-to-end samples it discarded in a
run whose reported distribution looks healthy.

**Both outcomes stated in advance.** A non-zero count is the strongest form of the M1 evidence:
the failure occurs in a harness we did not write, on real hardware, invisibly. A zero count is a
real negative that bounds the claim to the conditions where it happens, and we report it as such
rather than quietly dropping the run.

Queued behind the latency campaigns: Maven and a 500 msg/s benchmark are both CPU-heavy, and E-B2
is measuring load-sensitive inversion rates, so they must not overlap.

---

## M2 — Two withdrawals and one unresolved contradiction

**Referee:** "given two withdrawn headlines and one open contradiction, what is my posterior
that Table 10's numbers are final?"

**Accepted.** §8.5 currently *flags* that a small replication does not match E1's transport
figures. Flagging is not resolving.

**Hypothesis under test:** the two campaigns measured different *events*, not different systems.
E1 matched a median of seven events per run, and those seven are the opening burst — released
together once Kafka's blocking first send resolves. Transport over a batch-released burst need
not resemble transport over 127 events in steady state.

**Action (E1-REP campaign):** replay E1's exact configuration (600 s window) at a verified rate,
retain every event, and compute transport two ways — over all matched events, and over only the
first seven of each run. The prediction is sharp: all-events reproduces the powered result
(≈0.41 ms shift), first-seven reproduces E1's near-equality.

**If the prediction fails**, we have a second unexplained instability and must withdraw E1's
transport row rather than re-label it.

**Status: RESOLVED.** The prediction held, on both the shift and the absolute level — the latter
was not forced by the former, so it is a second independent check.

| N | runs | all-events shift | prologue shift | E1's reported shifts |
|---|---|---|---|---|
| 1 | 5 | +0.381 | +0.088 | 0.021 |
| 9 | 45 | +0.417 | +0.129 | 0.116 |
| 12 | 55 | +0.414 | +0.248 | 0.053 |

All-events reproduces the powered 0.41 ms. The prologue reproduces E1's near-equality, and its
absolute medians land on E1's too — Kafka 0.83–1.02 against E1's 0.79–1.00, Redis 0.74–0.81
against 0.72–0.86. One set of runs, two windows, both published answers.

So E1 was measuring the opening burst, during which both systems pay the start-up cost of §7.5
and a 0.41 ms difference is swamped. The campaigns never contradicted each other. §7.4 now carries
the reconciliation (Table `tab:e1rep`) and §8.5's limitation is replaced by it — E1's transport row
is **re-labelled as a prologue measurement, not withdrawn**.

*What this does not establish:* the window is shown to be sufficient to produce the disagreement,
not to be the only difference between the campaigns. E1's replay rate remains inferred. The
limitation says so.

---

## M3 — H1's quantitative support is confounded (KEYSTONE)

**Referee:** "the paper's most consequential generalisation is supported by n=2 conditions...
It should not be future work; it is the paper's keystone."

**Accepted.** We identified the confound ourselves (§8.4) and then deferred the fix. That was the
wrong call.

**The fix is an operating point, not a mechanism.** The confound came from offered load, not from
netem: a per-delivery delay only queues when arrivals outpace the drain. At the workload's true
rate the feed is sparse (0.415 ev/s), so a 50 ms one-way delay occupies ~2% of the delay pipe and
cannot build backlog. The instrument that was confounded at 10× should be clean at 1×.

**Action (E-B2 campaign):** delays {0, 1, 5, 20, 50} ms at a verified true real-time rate, N=5,
5 replicates, with **variance flatness as the manipulation check**. If measured transport
variance climbs across the sweep the way it did at 10×, the sweep is confounded again and H1's
slope stays unreported. We would rather publish "still confounded" than a slope we cannot defend.

**Status:** running (1/2 in the referee chain, started 2026-07-25 00:22 UTC).

---

## M4 — H2's M/G/1 evidence is close to unfalsifiable

**Referee:** "Fitting ρ/(1−ρ) against a linear alternative on data that necessarily blows up near
saturation will favour the former almost regardless of the underlying mechanism."

**Accepted.** Three of nine points sit at ρ = 1.0, which we ourselves call a degenerate
coordinate. Six informative points, and the comparison is against the weakest possible
alternative.

**Action (analysis only, no new runs):** refit against additional convex alternatives — a power
law `ρ^k` and an exponential — and report all R² values. Then downgrade the claim to what the
data supports. The defensible statement is "superlinear growth with a knee near saturation",
not "the M/G/1 form specifically". Re-run the fit on pre-saturation points only.

**Status: form withdrawn; knee sweep running to see whether measurement can restore it.**
The refit found an exponential fits the published Table 7 *better* than M/G/1 (0.961 against
0.945), so the functional form is withdrawn and only the shape — superlinear with a knee — is
retained. The pre-registered criterion is reported unchanged rather than quietly restated.

**A second finding the referee did not ask for, but which bears on the same complaint.** Chasing
the replacement model exposed the same unfalsifiability one level down. The two-state model's
stated form `P(inv) = p(ρ)·S` has *no content* on the ρ axis: with `p` free, any monotone rate
curve can be written that way. Constraining `p` to a power law makes it testable and it fits
poorly (R² 0.65). The variant that does fit —
`p(ρ)·S(T_true/σ(ρ))`, R² 0.9905 against 0.9811 for a fitted exponential — wins only because it
reads σ and μ, and **freezing σ improves the fit to 0.9982**. On our ladder σ rises monotonically
with ρ, so the two are collinear and no fit can separate them.

That is a limit of the *design*, not the analysis. `scripts/fit_two_state.py` reports it and
declines to claim the model; §7.3 now states the load axis as untested rather than supported.

**E-A5 (queued):** break the collinearity by experiment. `SCHED_FIFO` on the stamping processes
cuts occupancy while leaving utilisation untouched — occupancy predicts the inversion rate
collapses ~50×, utilisation-only models predict no change because ρ does not move. This is the
manipulation netem should have been: netem cancelled in the subtraction, scheduling priority acts
on the stamping threads themselves. `analyze_stamping_priority.py` runs the manipulation check
first and withholds the comparison if ρ differs between arms, which is the E-B2 lesson applied in
advance rather than after.

---

## M5 — The provenance gap is treated too lightly

**Referee:** "not being able to state the independent variable of the primary corpus is close to
disqualifying... §7.3 is currently defended by an inference the authors themselves distrust."

**Partially accepted.** The recovery argument is sound and we stand behind it, but the referee is
right that a headline table should not *rest* on it.

**Action (writing only):** restructure §7.3 so the load-bearing evidence is the powered
replication at a verified rate — where the rate is documented, not inferred — and E1 is reported
as the historical corpus it is. The recovery stays in §6.5 as a methodological episode, which is
where it belongs, rather than as the foundation of a claim.

---

## M6 — Statistical fragility

**Referee:** per-cell samples 8–35; retention bound needs >50% and the tightest cell is 52.8%.

**Accepted as a limitation, mitigated by design.** The powered replications (15 and 8 reps) and
E-A3 (25 runs per condition) already raise per-cell counts substantially for every claim added
since. The 52.8% cell belongs to the E1 corpus, which under M5 stops being load-bearing.

**Action:** state explicitly which claims rest on which sample sizes, and make clear that the
retention-bound argument applies only to the historical corpus.

---

## M7 — The workload is vestigial

**Referee:** "If the sports workload no longer does work in the argument, the title's promise and
§3's presence need justifying."

**Partially accepted.** The workload *does* still do work — it supplies the sparse bursty arrival
process that makes the failure visible, the kickoff burst that produces the start-up cost, and
the real concurrency levels. But the paper does not say so clearly enough.

**Action (writing):** make §3 earn its place by stating, at each point, which later result depends
on which workload property. Do not cut it; justify it.

---

## Minor

- **Figure 5 renders `\%` literally.** matplotlib without `usetex`; the escape is a LaTeX habit.
  Fix the label strings. *(local, quick)*
- **30 pages is long.** Consolidate §4 (eight subsections) and §6 (seven).
- **Table 9 retains withdrawn columns.** Keep, but make the caption unmissable.
- **"Sound" used in a narrow sense.** Already defined in §4.7; check every other use.

---

## What would flip the recommendation

The referee named three: **M1** (external validation), **M3** (clean effect-size manipulation),
**M2** (resolve the discrepancy). M1 is the one that matters most and the one we had not
attempted. M4 and M5 need honest downgrading rather than new experiments.

## Status board

| Issue | Severity | Kind | State |
|---|---|---|---|
| M1 external validation | decisive | audit | **PARTIAL** — OMB source audited, §6.7 |
| M1 empirical closure | decisive | run | **DONE, NULL** — instrumented OMB discarded 0; reported as a bound, not support |
| M3 clean effect size | keystone | run | **DONE** — manipulation check FAILED; H1's intermediate points withdrawn |
| M2 E1 discrepancy | major | run | **RESOLVED** — same runs give both answers; E1 measured the prologue |
| M4 M/G/1 downgrade | major | analysis | **DONE** — form withdrawn |
| M4 knee resolution | major | run | **DONE** — 5 points at rho 0.88–0.99; M/G/1 now REFUTED (R² −0.05 vs exponential 0.93) |
| M4 replacement model | major | analysis | **DONE** — unidentifiable on our ladder; §7.3 says untested |
| M4 occupancy manipulation | major | run | **DONE** — occupancy SUPPORTED: rho held to 0.001, rate fell 39– 54x |
| M5 provenance reliance | major | writing | **DONE** — §7.3 inverted |
| M6 sample sizes | major | writing | **DONE** — Table 5 |
| M7 workload justification | major | writing | **DONE** — §3 rewritten |
| Minor: figure `\%` | minor | local | **DONE** |
| Minor: dangling `\ref`s | minor | local | **DONE** — 3 invented labels fixed; test added |
| Minor: length, caption, "sound" | minor | local | pending |

**Run queue on `sbl-drv`, in order:** E-A4 knee resolution (running) → OMB discard count →
E-A5 stamping priority. Each chain waits on every CPU consumer, not just its predecessor, because
E-A5's design requires utilisation to be equal across its two arms and a stray Maven build inside
one arm would fail the manipulation check.
