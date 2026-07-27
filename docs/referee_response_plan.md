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
| M1 external validation | decisive | audit | **CLOSED** — OMB source audited at a named commit, §6.7 |
| M1 empirical closure | decisive | run | **REOPENED then RE-CLOSED on different evidence** (2026-07-26). The 6,000 were not causality violations: 0 negatives in ~420k discards. Closed instead on retention — OMB reports a latency summary from 0.83–100% of its samples with no indication which, and its reported average *rises* as retention falls (Spearman −0.644). See R1 below. |
| M3 clean effect size | keystone | run | **DONE** — manipulation check FAILED; H1's intermediate points withdrawn. Superseded by E-A10, which moves *T*ₜᵣᵤₑ 77× without perturbing the scheduler |
| M2 E1 discrepancy | major | run | **RESOLVED** — same runs give both answers; E1 measured the prologue |
| M4 M/G/1 downgrade | major | analysis | **DONE** — form withdrawn |
| M4 knee resolution | major | run | **DONE** — 5 points at rho 0.88–0.99; M/G/1 REFUTED (R² −0.05 vs exponential 0.93) |
| M4 replacement model | major | analysis | **DONE** — unidentifiable on our ladder; §7.3 says untested |
| M4 occupancy manipulation | major | run | **DONE, EXTENDED** — 8 matched pairs across E-A5/A5b/A7, rho held to 0.003, rate falls **7–80×** |
| M5 provenance reliance | major | writing | **DONE** — §7.3 inverted |
| M6 sample sizes | major | writing | **DONE** — Table 5, plus a uniform 2,985-event denominator stated once |
| M7 workload justification | major | writing | **DONE** — §3 rewritten |
| Minor: figure `\%` | minor | local | **DONE** |
| Minor: dangling `\ref`s | minor | local | **DONE** — 3 invented labels fixed, then 5 more found in the *rendered* PDF; test added |
| Minor: length, caption, "sound" | minor | local | **DONE** |

### Beyond the referee's list

The response ran past the issues raised. Recorded here because the board is the project's index
of what was settled and by what:

| Question | Campaign | Outcome |
|---|---|---|
| Is it scheduling or utilisation? | E-A5/A5b/A7 | scheduling — 7–80× at fixed rho, 8 pairs |
| Does *where* the load sits matter? | E-A6, E-A6b | yes — 2.07× and 2.05× at rho identical to 4 dp |
| What happens if *T*ₜᵣᵤₑ grows? | E-A10, E-A10b | rate **falls** 4.1× and 4.3× over a 77× span |
| What is the stall distribution's shape? | E-A10 fit | tail index α ≈ 0.339, 0.344 — **no finite mean** |
| Does a kernel trace predict the rate? | E-A9, E-A9b | yes, to within a third across three arms, unfitted |
| Can the broker be moved closer? | E-A8 | no — co-location *lengthened* transport; withheld |

**Run queue: empty.** Every chain listed here has finished. The replications (E-A6b, E-A10b,
E-A9b) completed 2026-07-26; see [`../docs/laws.md`](laws.md) for what each settled and what
each would have to show to be falsified.

---

# Round 2 — internal referee review, 2026-07-26

The first round closed. Before resubmitting, the manuscript was reviewed again from the position
of a rigorous TOMPECS referee specialising in performance measurement. That review is recorded
here in full, followed by the response plan.

**Recommendation received: MAJOR REVISION**, reject if M1–M3 cannot be met.

## The review

### M1 — The headline contribution may be a lint rule, not a research result

The central artefact is: a duration computed from two timestamps cannot be negative; check it.
The paper calls the check "elementary" (§5), says it "costs nothing" (§8.1), and concedes "better
instruments exist… our point is orthogonal to instrument quality" (§8.1). If the check is
elementary, costs nothing, and is orthogonal to instrument quality, the contribution reduces to
*we observed that practitioners do not do an obvious thing.* That is a community-service note,
not obviously a TOMPECS paper.

§6.5's property is the actual intellectual contribution and it sits in half a page: measurement
validity degrades precisely as the measured effect approaches the instrument's noise floor, so
the most delicate comparisons are the least trustworthy, and significance offers no protection
because the artefact is systematic. **Restructure the paper around that, not around the check.**

### M2 — Every mechanism result rests on one machine

§7.3 — priority at fixed ρ (7–80×, 8 pairs), two geometries at ρ identical to four decimals
(2.07×, 2.05×), the payload sweep, the kernel trace — all from four VMs of one shape
(`VM.Standard.E5.Flex`), one kernel (`6.8.0-1057-oracle`), one CPython. The paper nonetheless
reports α ≈ 0.34 and "no finite mean" as though characterising Linux scheduling. It characterises
one kernel on one instance type under stress-ng. The tail index is four points per campaign at a
single load level; two campaigns agreeing to 1.5% shows reproducibility, not generality.

**Replicate the geometry contrast and the payload sweep on a materially different machine, or
systematically downgrade the language.**

### M3 — External validity rests on a single 3-minute run

`omb_loaded_result.csv` records one run: embedded mode, 88% load, 3 minutes, 6,000 discards. That
single run answers "is anyone but you exposed?", the objection the authors call decisive. The
source audit is solid; the empirical claim is n=1, one load, one mode, distributed unreported.
**A load sweep with replication, both brokers. The discard count as a function of load is the
interesting result and is missing.**

### S1 — The 58% is partly an artefact of a poor rig

Testbed A is Windows + Docker Desktop + WSL2, 15.6 ms timer quantum, 5.6–9.9 ms TCP connect.
Sub-millisecond transport cannot be measured there at all, so "58% rejected" substantially reports
*we built an unsuitable rig*. Testbed B's 51.9% is the defensible figure. **Lead with it.**

### S2 — The instrument perturbs the measurement, and this is under-weighted

All three traced real-time arms recorded zero inversions where the untraced twin recorded 15/2985.
The authors found their own instrument changing what it observes, report it honestly, then set the
consequences aside. The ordinary arm is also affected — the two traced 88% values are the lowest
of six — and the instrument check cannot resolve an effect below ~15%. **An untraced control in
the same session as each traced arm.**

### S3 — The mechanism does not predict, and the paper knows it

Two attempts failed (M/G/1 at R²=−0.05; the authors' own bracket 2.45–3.07× against 1.44×). With
M1, a reader may ask what is left. The T_true dependence is the answer — a slower path is a more
reliable measurement, directly actionable and counter-intuitive — and it is one subsection among
many. **Promote it.**

### S4 — The residual sign flips and the explanation was withdrawn

Ratios 0.78, 1.06, 1.32. "Agreement to within a third, unfitted" is weaker than §7.3's framing
implies, on three arms.

### S5 — Churn

Two headline withdrawals, M/G/1 refuted, the authors' own bracket failed, co-location withheld, a
k=7 null withdrawn, a directional argument withdrawn. Each correction is creditable; collectively
they invite the question of what survives the next replication. **State which claims are settled
and which are expected to move.**

### S6 — The football workload is vestigial

Conceded in §3. It contributes sparsity and a dense kickoff burst, both obtainable synthetically.
3,315 matches characterised to justify replaying eleven is disproportionate.

### Minor

0.41 ms reported as "real and negligible" — develop it or cut it to a sentence; `not-assessed` vs
`condemned` still invites comparing 366 to 862; no Holm family declared for the §7.3 campaigns;
§7.3 is ~9 pages and should split established from exploratory; ρ to four decimals implies
precision the day-to-day drift (0.221–0.305) does not have.

### What the referee credits

The §7.3 manipulation design; the T_true sweep as the best experiment in the paper; reporting the
withheld arm; the OMB source audit; reproducibility infrastructure above field norm.

---

## Response plan

Ordered so the machines are working while the prose is rewritten. Runs first, corrections during.

### Phase R — runs and machines (start immediately)

**VM actions.**

| instance | role | action | why |
|---|---|---|---|
| `sbl-drv` | driver | **keep** | runs R1, R2 |
| `sbl-b1` (10.0.1.221) | Kafka + Redis | **keep** | the only broker every reported campaign uses |
| `sbl-b2` (10.0.1.242) | cluster node 2 | **stop** | used only by `cluster.sh`; that arm is withdrawn (§7 "fails on every run in both systems") |
| `sbl-b3` (10.0.1.140) | cluster node 3 | **stop** | same |
| *new* `sbl-arm-drv` | ARM driver | **provision** | M2 |
| *new* `sbl-arm-b1` | ARM broker | **provision** | M2 |

Stopping b2/b3 is reversible and halves the running compute. The cluster arm is withdrawn, so
nothing current needs them; if the arm is ever revived they can be restarted.

For M2 the second platform must be *materially* different or it does not answer the objection.
`VM.Standard.A1.Flex` (Ampere Altra, aarch64) is the right choice: different ISA, different
scheduler tuning, different core count — and Always Free eligible, so likely no additional cost.
`E4.Flex` would be a weaker contrast (same architecture, same family). Capacity for A1 was
unavailable in `uk-london-1` at first provisioning; retry, and if it is still out, try another
home-region AD before falling back to E4.

**R1 — OMB load sweep (answers M3).** `omb_discard_count.sh` already parameterises `LOAD_PCT`.
Sweep 0/50/75/88/95, three repetitions each, both Kafka and Redis drivers. Records discard count,
publish rate and the reported latency summary per cell. The deliverable is *discards as a function
of load*, which is a result rather than an existence proof. Runs on `sbl-drv`; ~4 h.

**R2 — untraced controls (answers S2).** For every traced arm, an identical untraced arm in the
same session, interleaved rather than run days apart. Both load levels, both priority arms:
8 cells. This is what makes the traced/observed comparison defensible and settles whether the
ordinary arm is perturbed as well as the real-time one. Runs on `sbl-drv` after R1; ~3 h.

**R3 — second-platform replication (answers M2).** On the ARM pair, repeat exactly two campaigns:
the load-geometry contrast (`load_geometry.sh`) and the payload sweep (`ttrue_sweep.sh`). These
two carry the claims that most outrun their support — "ρ is not the variable" and "α < 1, no
finite mean". Everything else in §7.3 can stay scoped to one platform if these transfer.

*Falsification stated in advance:* if the geometry contrast is flat on ARM, "utilisation is not
the variable" is a property of one kernel's scheduler and must be said that way. If α comes back
materially different — say above 1 — the no-finite-mean claim does not generalise and becomes a
platform-specific observation. Either outcome is reportable and neither invalidates the check.

### Phase C — corrections, in parallel with Phase R

**C1 — restructure around §6.5 (M1).** Promote the noise-floor property from a subsection to the
paper's organising claim. The check becomes the instrument that demonstrates it, not the
contribution. Retitle and rewrite the abstract's third beat accordingly.

**C2 — promote the T_true dependence (S3).** It is the actionable finding and the only one that is
counter-intuitive. Lift it out of the §7.3 sequence and give it its own subsection adjacent to
§6.5, since it is the same property viewed from the other side.

**C3 — lead the audit with Testbed B (S1).** Report 51.9% as the headline rate and Testbed A's
62.4% as an illustration of platform unsuitability, with the 15.6 ms quantum stated at the point
of first use rather than in §4.1 only.

**C4 — scope §7.3 explicitly (M2).** Until R3 reports, every mechanism claim carries the platform.
If R3 transfers, replace with the two-platform statement; if it does not, the scoping stays and
the abstract says so.

**C5 — split §7.3 (minor).** Established-by-manipulation in one subsection; the exploratory
two-state model in another, clearly marked.

**C6 — declare a Holm family for §7.3 (minor).** The mechanism campaigns involve many implicit
comparisons with no family currently declared.

**C7 — settle the 0.41 ms (minor).** Either develop the architectural reading (in-memory append vs
replicated log) or reduce it to one sentence. Currently it is given a table and called negligible.

**C8 — a settled/unsettled register (S5).** A short table stating which claims we regard as
closed, which are one-campaign, and which we expect to move. This answers the churn objection
directly rather than hoping the reader does not count.

**C9 — the football question (S6).** Keep the workload, cut §3 to the two properties that matter —
sparsity and the kickoff burst — and say plainly that a synthetic generator would serve, retaining
the real corpus only because the concurrency levels are derived from real kickoff schedules.

**C10 — ρ precision (minor).** Report ρ to the precision the matching supports within a campaign,
and state the between-campaign drift alongside, so four decimals cannot be read as absolute
accuracy.

### Sequencing

```
now         stop sbl-b2, sbl-b3          (console; reversible)
now         start R1 on sbl-drv          (~4 h)
now         C1, C2, C3 in parallel       (prose; no machine needed)
+4 h        start R2 on sbl-drv          (~3 h)
+4 h        C5, C6, C7, C8, C9, C10
on ARM      provision, then R3           (~6 h once the pair is up)
after R3    C4 resolves either way; rebuild; full verification
```

C1–C3 are the ones that change the paper's shape and do not depend on any run. They should be
done while R1 is going, not after.

---

# R1 outcome — the OMB claim does not survive its own sweep (2026-07-26)

Phase R's first run was the sign-separated discard sweep, queued to settle referee **M3**
("external validity rests on a single 3-minute run"). It settled more than that. The claim it
was meant to strengthen is not supported, and the paper must change before anything else in
Phase C is worth doing.

## What was run

`cloud/campaigns/omb_load_sweep.sh` — five background-load levels (0, 50, 75, 88, 95%), three
replicates each, three minutes per cell, against Kafka on `sbl-b1`. The counter that produced
the manuscript's $6{,}000$ was a single total with no sign. It is now four counters — zero,
negative, most-negative, kept — printed exactly by a JVM shutdown hook rather than sampled from
progress lines that quantise to 10,000.

## What it found

| background load | kept | discarded zero | discarded negative |
|---|---|---|---|
| 0%  |  1.51% | 98.49% | **0.000%** |
| 50% | 76.32% | 23.68% | **0.000%** |
| 75% | 95.59% |  4.41% | **0.000%** |

**Zero negative samples in roughly 420,000 discards.** And the zero-share *falls* as load rises.
Both point the same way, and it is not our way: our own mechanism predicts inversions become
*more* common under load, because that is what Section~\ref{sec:twostate} establishes. A discard
population that thins out as the machine gets busier is a tick collision — the arithmetic
consequence the manuscript already describes at §6.7, lines 1125–1130 — not a causality
violation.

Corroborating, from `check_omb_quantisation.py`: 36 of the 40 reported latency values across
eight runs are whole milliseconds. Split by column the result is sharper than that aggregate.
**Every one of the 32 percentile values — p50, p95, p99 and max — is a whole millisecond.** The
only four fractional values are the averages, and a mean of integers is expected to be
fractional; it is the one statistic that can be. Three runs report p50 = p95 = p99 = max = 1.0.
That is not a narrow distribution. It is a distribution with one value in it, reported to three
decimal places.

State the 32-of-32 form in the paper rather than the 36-of-40 form. The aggregate dilutes the
finding with the one column that could not have shown it.

## What survives, what falls, what gets stronger

**Survives — the entire source audit.** None of it depends on the sweep:

- end-to-end latency is a cross-process (in a distributed deployment, cross-host) timestamp
  difference, at the named commit, file and line;
- `if (endToEndLatencyMicros > 0)` admits only positive samples and nothing counts the drops;
- the reported distribution is therefore *conditioned on being positive*, so a causality
  violation cannot appear in its output even in principle;
- the retention rate is not merely unpublished but unrecoverable from a completed run.

**Falls — the empirical attribution, and only that.** "It discarded $6{,}000$ samples" is true;
"those were our failure mode" is not. Four sites inherit the bad inference and must change
together: abstract (l. 70), contributions (l. 202), limitations (l. 2525), conclusion (l. 2631).

**Gets stronger — the resolution finding.** §6.7 already predicted this consequence and called
it "a large share of the samples". It is now measured, swept, and worse than predicted: at idle,
OMB computed a latency summary from **1.5%** of its samples and reported nothing about the other
98.5%. That is a better claim than the one it replaces — more defensible, more damning, and
squarely the paper's own §6.5 thesis that instruments conceal their own failures. It also lands
on the harness rather than on us.

## Still to land before §6.7 is rewritten

- `omb_resolution_test.sh` — message size 200 B → 256 KB, the decisive discriminator. Resolution
  predicts the zero-share collapses once latency clears one tick; causality is indifferent to
  message size. **Chained, fires on sweep exit.**
- Reps 4–6 per load level → `load_sweep_p2`. At 0% load the three reps gave 98.5%, 99.2% and
  0.003%; that bimodality is what a tick boundary looks like, but three reps cannot establish
  it. **Chained.**
- `index_external_campaigns.py` over every cell, so the campaign is in a ledger like our own runs.

## Consequence for the referee's M3

M3 asked for more than one 3-minute run. It now has 15, and will have 38. The answer to M3 is
no longer "here is more of the same evidence" but "the additional evidence overturned the
reading, and we corrected it" — which is the better answer to give, and the one this paper is
in a poor position to refuse.

## R1 addendum — the discard rate is a threshold, not a rate (2026-07-26)

The message-size sweep's first two cells changed what the finding is. Both ran at 200 B and 0%
background load, three minutes each, identical in every configured respect. `s200_rep1` discarded
**nothing** — 120,434 samples kept. `s200_rep2` discarded **99.64%** — 431 kept.

With the three load-sweep cells at the same configuration, five observations of retention at one
fixed setting:

| run | retention |
|---|---|
| l0_rep1 | 1.51% |
| l0_rep2 | 0.83% |
| l0_rep3 | 100% |
| s200_rep1 | 100% |
| s200_rep2 | 0.36% |

Two modes, nothing between them. That is not a noisy rate; it is a **threshold**. Either the
median latency falls below one millisecond tick, and nearly every sample computes to zero and is
discarded, or it reaches one tick and nearly none are. Which side a run lands on is decided by
system state finer than anything the workload controls.

**What this does to the claim.** It makes it stronger and simpler. The statement is no longer
"OMB discards a large share of its samples under some conditions", which invites a question about
which conditions. It is: *at a fixed configuration, this benchmark's reported latency summary is a
coin flip between being computed from essentially all of its samples and essentially none of them,
and its output does not say which.* Both outcomes print a healthy-looking summary with a median of
1.0 ms.

**What it does to the message-size test.** It weakens its power at the small end without touching
the conclusion. Large messages should clear one tick deterministically and retain everything; the
200 B baseline is a coin flip, so a two-rep comparison against it is underpowered. The size sweep
still discriminates -- it just cannot rest on the baseline cell alone.

**Queued as chain7:** ten more reps at the identical configuration, fifteen in total, with nothing
else varying. The variable under study is the run-to-run variation itself, so the design holds
everything else fixed on purpose.

### Correction to the R1 trend statement

R1 above reports the zero share as falling with load, on the three levels available when it was
written: 98.49% → 23.68% → 4.41%. With all five levels indexed, the medians are:

| load | 0% | 50% | 75% | 88% | 95% |
|---|---|---|---|---|---|
| zero share | 98.49% | 23.68% | 4.41% | 4.78% | 22.63% |

**That is not monotone.** It falls to a minimum around 75–88% and rises again at 95%. The
first-to-last comparison the classifier uses is still a fall, and the verdict is unchanged and
unambiguous — RESOLUTION, zero negatives across every level — but "the zero share falls with load"
overstates what these numbers show, and the paper must not say it.

The bimodality addendum explains why. Each level is the median of three cells, and each cell is
drawn from a two-point distribution — near 0% retention or near 100%. A median of three such
draws is itself close to bimodal, so the level-to-level pattern reflects how many of three cells
happened to land above the tick, not a smooth response to load. Reading a trend into it would be
fitting a curve to coin flips.

**The defensible statements**, in order of strength:

1. Zero negative samples in ~420,000 discards, at every load level. *(Decisive for the withdrawal;
   independent of the bimodality.)*
2. Retention at a fixed configuration is bimodal, near 0% or near 100%, with nothing between.
   *(chain7 establishes this properly at n=15.)*
3. The reported p50 does not move with retention; the reported average moves inversely with it
   (Spearman −0.644). *(Both from the 16-cell join, and both robust to the bimodality — indeed
   the bimodality is what gives the correlation its range.)*

Load is best presented as one of the things that moves the median latency across the tick, not as
a variable with a smooth effect on the discard rate.

### Caveat on the message-size sweep's largest cell

Offered load at 500 msg/s, by message size:

| size | offered | note |
|---|---|---|
| 200 B | 0.8 Mb/s | |
| 4 KB | 16.4 Mb/s | |
| 64 KB | 262.1 Mb/s | clean discriminator |
| 256 KB | **1048.6 Mb/s** | at or near link capacity |

The 256 KB cell is a different regime, not a larger point on the same curve. If it retains
everything, that is consistent with resolution but also with queueing under a saturated link:
latency would balloon because the pipe is full, not because serialising a larger message crosses
the tick. The two are indistinguishable in that cell, so it cannot carry the discrimination.

**64 KB is the cell to read.** At 262 Mb/s there is no saturation, and serialisation alone adds
enough latency to clear a millisecond on a 1 Gb/s path. If retention there is consistently high
across reps while 200 B remains bimodal, resolution is supported without a confound.

Recorded before the cell ran, so the reading is not chosen after seeing it.

### Correction to the bimodality addendum

The addendum above calls the discard rate "a threshold, not a rate" and says retention has "two
modes, nothing between them". **That is withdrawn.** It rested on five observations at one
configuration. Across all 21 measured cells retention is spread across the full range:

| retention | <5% | 5–25% | 25–75% | 75–95% | ≥95% |
|---|---|---|---|---|---|
| cells | 4 | 3 | 3 | 3 | 8 |

Values in order: 0.36, 0.83, 1.51, 1.81, 10.94, 20.21, 23.13, 26.52, 35.92, 66.21, 76.32, 77.37,
94.72, 95.22, 95.36, 95.59, 95.67, 99.40, 100.00, 100.00, 100.00. Nine of 21 lie between 5% and
95%. The message-size cells that prompted the correction — 4 KB at 10.94% and 64 KB at 35.92% —
are squarely intermediate.

**The right model is simpler and was available all along.** Retention is just
`P(true latency ≥ one tick)`. As the latency distribution moves relative to the 1 ms grid, that
probability sweeps continuously from 0 to 1. Near the boundary it is exquisitely sensitive, which
is why five runs at 200 B and 0% load — a configuration sitting almost exactly on the tick — gave
0.36%, 0.83%, 1.51%, 100% and 100% and looked like two modes. With five samples, wide-and-
continuous is not distinguishable from bimodal, and I should not have claimed it was.

**What is unaffected.** Every load-bearing statement survives, because none of them depended on
the shape:

1. Zero negatives in ~420,000 discards, at every level. The withdrawal rests on the sign.
2. Retention ranges from 0.36% to 100% across cells — the *range* is the finding, not its shape.
3. Reported p50 does not track retention; reported average moves inversely with it
   (Spearman −0.644).

**What chain7 now settles.** Fifteen reps at one configuration was queued to establish bimodality.
It instead measures the run-to-run distribution of retention at a fixed setting, which is the
honest version of the same question and is worth having either way: how much does the fraction of
data behind OMB's headline number vary when nothing is changed?

### The simple resolution model is insufficient, and the 64 KB pre-registration was wrong

Two corrections and a new experiment.

**64 KB is not a clean discriminator.** It was pre-registered above as the cell to read, on the
grounds that 262 Mb/s offers no saturation. `s65536_rep1` reports p50 = 519 ms and p99 = 1097 ms:
the path is badly backed up. Saturation begins at 64 KB, not 256 KB, so the message-size sweep has
**no** uncontaminated cell — 200 B and 4 KB sit on the tick, and everything above is queue-limited.
That cell also retains only 35.92% despite half-second latency, which a resolution model cannot
produce; it is the queue building during the run. The size sweep cannot carry the discrimination
and will not be used for it.

**Retention is not explained by path speed.** OMB's own publish latency — measured in one process
and *not* quantised to the millisecond grid — sits at **0.3 to 0.4 ms across all 19 unsaturated
cells**, while retention over those same cells ranges from 0.36% to 100%. Spearman is +0.415,
which on a predictor with a 0.1 ms spread is not a mechanism. So `retention = P(true latency ≥ one
tick)`, filed above as the corrected model, does not survive either. A constant path cannot
produce a 275-fold swing in what survives a threshold on that path.

**Candidate mechanism: phase, not speed.** The producer is paced at 500 msg/s — one send every
**2.000 ms**, an exact integer number of millisecond ticks. If sends are phase-locked to the clock
grid, every sample in a run sits at the same offset within its millisecond, so either nearly all
of them cross a tick boundary before delivery or nearly none do. That produces all-or-nothing
retention at a fixed configuration, which is what the data show, and it produces it *without*
requiring the latency to change.

**chain8 tests it, with predictions recorded before the run:**

| rate | interval | commensurate? | prediction |
|---|---|---|---|
| 500 msg/s | 2.000 ms | yes | retention near 0% or near 100%, unstable across reps |
| 457 msg/s | 2.188 ms | no | intermediate and **stable** across reps |
| 383 msg/s | 2.611 ms | no | intermediate and **stable** across reps |

Four reps each, warmup disabled so the counter and OMB's percentiles share a denominator. If all
three rates behave alike, the phase hypothesis is wrong and this section will say so.

**None of this touches the withdrawal.** Zero negatives in ~420,000 discards is a statement about
sign, and no mechanism debate reaches it. Nor does it touch the retention/reported-average
relationship, which is −0.541 with the saturated cell excluded and −0.540 with it included.

### An accidental positive control for the phase hypothesis

The 64 KB cells were written off above as saturated and uninterpretable. They are saturated, but
they are not uninformative, and what they show arrived before chain8 was built to look for it.

| size | rep 1 | rep 2 | spread | reported e2e p50 | pub p50 |
|---|---|---|---|---|---|
| 200 B | 100% | 0.36% | **99.6 pts** | 1.0 ms both | 0.4 / 0.3 ms |
| 4 KB | 10.94% | 100% | **89.1 pts** | 1.0 ms both | 0.4 / 0.4 ms |
| 64 KB | 35.92% | 34.42% | **1.5 pts** | 519 / 235 ms | 0.6 / 0.6 ms |

Retention is **stable to 1.5 points** at 64 KB even though the two runs' reported end-to-end
medians differ by 2.2× — 519 ms against 235 ms. At 200 B and 4 KB, where the reported median is
identical at 1.0 ms in all four runs, retention spans nearly the whole range.

That is backwards for any model in which retention tracks latency, and it is what the phase
hypothesis predicts. Queueing at 64 KB makes delivery times large and irregular, which dephases
samples relative to the millisecond grid; a dephased population crosses tick boundaries at a rate
set by the *distribution*, so retention becomes a stable intermediate fraction. At 200 B the path
is fast and the producer is paced on an exact 2.000 ms interval, so samples stay phase-locked and
the whole run falls on one side of a boundary or the other.

**This is support, not proof.** Saturation and dephasing are confounded here: the 64 KB runs
differ from the small-message runs in both, and this pair was not designed to separate them.
chain8 does separate them — it holds message size and load fixed and varies only whether the
producer's interval is commensurate with the millisecond grid. If retention there is unstable at
500 msg/s and stable at 457 and 383, the mechanism is phase and saturation was never needed. If it
is unstable at all three, the phase hypothesis is wrong and this table is a coincidence.

Recorded now, with the prediction already filed, so that the reading of chain8 cannot be chosen
after seeing it.

### The completed size sweep: a dose-response, but not a discrimination

| size | retention | reported e2e p50 | achieved rate | regime |
|---|---|---|---|---|
| 200 B | 100% / 0.36% | 1.0 ms | 500 msg/s | on the tick |
| 4 KB | 10.94% / 100% | 1.0 ms | 500 msg/s | on the tick |
| 64 KB | 35.92% / 34.42% | 519 / 235 ms | 556 / 510 msg/s | queue building |
| 256 KB | 100% | 42,973 ms | **113 msg/s** | saturated |

At 256 KB the producer achieves 113 msg/s against 500 requested and latency reaches 43 seconds.
Retention is exactly 100%.

**This softens the earlier dismissal.** The 256 KB cell was written off above as uninterpretable.
It is uninterpretable *for the discrimination* — resolution and causality both predict no zero-
valued samples when latency is enormous, so it separates nothing. But it does confirm the
resolution mechanism's dose-response: when latency unambiguously clears one tick, the guard
discards nothing. Combined with the near-tick cells, where retention swings across the full range,
the sweep shows retention going to 100% as latency leaves the tick behind, which is what the
mechanism requires.

The 64 KB pair sits between and is now explicable: those runs contain a fast opening phase, before
the queue builds, whose samples fall below the tick and are discarded, followed by a slow phase
whose samples are kept. About a third of each run is the slow phase, and that ratio is set by how
long the queue takes to build — deterministic, hence the 1.5-point agreement between reps.

**The discrimination itself still rests where it always did: on the sign.** Zero negative samples
in roughly 420,000 discards, at every load level and every message size. No dose-response argument
is needed for that, and none of this changes it.

### Size sweep complete: instability is confined to the near-tick regime

All eight cells, exit 0.

| size | rep 1 | rep 2 | spread | reported e2e p50 | regime |
|---|---|---|---|---|---|
| 200 B | 100% | 0.36% | **99.6 pts** | 1.0 ms | on the tick |
| 4 KB | 10.94% | 100% | **89.1 pts** | 1.0 ms | on the tick |
| 64 KB | 35.92% | 34.42% | 1.5 pts | 519 / 235 ms | above |
| 256 KB | 100% | 100% | **0.0 pts** | 42,973 ms | far above |

Zero negative samples at every size.

Both sizes whose latency sits far above one tick reproduce to within 1.5 points. Both sizes whose
reported median is exactly 1.0 ms swing across nearly the entire range. **The irreproducibility is
a property of the near-tick regime, not of the benchmark generally** — which is worth stating
precisely, because "OMB is unreliable" would be too strong and "OMB discards samples" too weak.

The accurate claim: *when the measured path is fast enough that its true latency lands near the
resolution of the timestamp being subtracted, the fraction of samples surviving the guard is not
reproducible between runs of an identical configuration, and the reported summary does not
indicate which case obtained.* That is the regime every co-located broker benchmark runs in, and
it is the regime this paper's own transport measurements occupy at 0.1–0.5 ms.

This also retires the message-size sweep as a discrimination instrument, which it never managed to
be, and repurposes it as what it turned out to be good for: a demonstration that the instability
has a location.

### Replicates that agree with each other are not a reproducible measurement

`load_sweep_p2` re-runs the identical sweep. Level 0 has now completed in both passes and the
first comparison is available (the other four levels are still running).

| load | pass A median | pass A spread | pass B median | pass B spread | \|delta\| |
|---|---|---|---|---|---|
| 0% | 1.51% | 99.17 pts | **99.98%** | **3.58 pts** | **98.47 pts** |

The three-replicate median moved from 1.51% to 99.98% between two passes of a configuration
identical in every respect we control.

**The spreads are the important column.** Pass A's three replicates span nearly the whole range,
so an experimenter would see the instability immediately. Pass B's three replicates agree to
**3.58 points**. Someone who ran only pass B would report "retention 99.98%, n=3, spread 3.6%" —
a tight, confident, entirely reasonable-looking measurement — and it sits 98 points from what the
same configuration produced an hour earlier.

So the usual defence does not work here. **Replicates agreeing with one another is not evidence
that the measurement is reproducible**, because the quantity is not noisy around a stable value:
it is stable *within* a pass and different *between* passes. Averaging more replicates inside a
pass buys nothing, and reporting their spread as an uncertainty actively misleads — it is a
measure of within-pass agreement being read as between-pass reproducibility.

**This lands on our own first sweep.** The per-level discard shares in R1 above are three draws
from a quantity that does not settle, and must be reported as such rather than as a response
curve against load. It is also the cleanest instance of this paper's own thesis so far: an
instrument that looks precise, reports a confident summary, and is not measuring a stable
quantity — with nothing in its output to say so.

**Caveat, stated because only one level is in.** This is one level of five; the remaining twelve
cells are running. If levels 50–95 reproduce closely, the effect is specific to the near-tick
configuration at idle and must be scoped that way. The threshold for the verdict (10 points) was
fixed before any of this pass existed.

### The replication pass, complete: a three-replicate median is a coin flip

Fifteen cells, identical configuration to the first sweep, run three to five hours later.

| load | median A | spread A | median B | spread B | \|delta\| |
|---|---|---|---|---|---|
| 0% | 1.51% | 99.17 | 99.98% | 3.58 | **98.47** |
| 50% | 76.32% | 33.19 | 4.79% | 95.59 | **71.52** |
| 75% | 95.59% | 75.46 | 94.70% | 49.93 | 0.89 |
| 88% | 95.22% | 72.23 | 94.53% | 43.12 | 0.69 |
| 95% | 77.37% | 68.21 | 23.71% | 73.05 | **53.66** |

30 cells, retention from 0.83% to 100%, **zero negative samples throughout**.

**Three of five levels fail to reproduce, by 54 to 98 points. Two agree within one point.** That
mixture is the result, and it is worse than uniform failure would be: uniform failure is at least
detectable. Here, a practitioner running one pass has a 40% chance of a per-level median that
would reproduce and a 60% chance of one that would move by half the scale — **with nothing
available inside that pass to say which they have.**

The within-pass spreads say why. Four of the ten level-passes span 43 to 99 points; the individual
cells are close to unpredictable. A median of three such draws is not an estimate of a stable
quantity, and when two such medians happen to agree — as at 75% and 88%, where both passes landed
high — that is coincidence rather than convergence.

**Correction to an earlier reading in this document.** At n=2 in pass B, level 50's replicates
agreed to 1.06 points, and this was briefly read as "replicates agree tightly within a pass while
passes differ" — an attractive and much sharper claim. The third replicate took that spread to
95.59 points. The sharper claim is withdrawn; the plain one survives.

**What the paper should say.** Not "OMB's discard rate varies", which understates it, and not
"replicates agree while passes do not", which is false. The claim is: *the fraction of samples
behind this benchmark's reported latency summary is not reproducible at three replicates, agreeing
between passes at some conditions and moving by half the available range at others, with no signal
in the output distinguishing the two.* And it applies to our own first sweep, whose per-level
numbers must therefore be reported as draws rather than as a curve.

**Unaffected, again:** zero negatives across all 30 cells. The withdrawal of the causality reading
has not moved through any of this.

### Prediction for the no-warmup sweep, recorded before it finishes

chain4 repeats the load sweep with `warmupDurationMinutes: 0`, so the discard counter and OMB's
reported percentiles finally cover the same samples.

The first instinct is that removing the warmup should lower retention: warmup runs before the JIT
settles, its samples are slower, and slower samples clear the tick and survive. **That is wrong on
this data.** `l0_rep1` kept 1,821 samples out of 120,429 — far fewer than the ~30,000 the warmup
minute alone contributes at 500 msg/s. If warmup samples had survived preferentially, retention
could not have been that low. They were discarded too, so warmup latency was also sub-tick.

**Prediction: total samples per cell fall from ~120,000 to ~90,000, and the retention fraction is
roughly unchanged.** If retention instead shifts systematically, the warmup phase was contributing
differently from the test phase and every retention figure computed with warmup included needs
restating against the test phase alone.

Recorded now so the reading is not chosen after the fact — the same discipline that made the
64 KB pre-registration falsifiable, and it duly falsified.

### No-warmup sweep: the prediction holds, and the warmup concern is closed

Level 0 complete in all three passes of the identical configuration, differing only in warmup:

| pass | warmup | retention | samples/cell |
|---|---|---|---|
| A | 1 min | 1.51%, 0.83%, 100.00% | 120,423 |
| B | 1 min | 100.00%, 96.42%, 99.98% | 120,456 |
| no-warmup | 0 | 100.00%, 0.38%, 100.00% | 90,259 |

**Both halves of the prediction hold.** Samples per cell fall to ~90,000, exactly the 30,000 the
warmup minute contributed, and the retention fraction is not systematically shifted — the
no-warmup cells span the same range as the warmup ones.

**This closes a concern raised earlier in this document.** The commit that added `WARMUP_MIN`
argued the headline was "conservative by accident": that pre-JIT warmup samples, being slower,
would clear the tick more often, inflate retention and understate the discard rate. **That was
wrong.** Warmup samples were sub-tick too, so including them changed the denominator and not the
fraction. Every retention figure computed with warmup included stands as reported, and nothing
needs restating.

Worth recording that the worry did not pan out, rather than quietly dropping it. The fix was still
right — the counter and OMB's percentiles should cover the same samples — but it corrected a
bookkeeping mismatch, not a bias.

**A local bimodality is now visible and is not yet claimed.** The nine runs above, sorted, are
0.38, 0.83, 1.51, 96.42, 99.98, 100, 100, 100, 100 — four below 2%, five above 96%, nothing
between. The *general* bimodality claim was withdrawn earlier and stays withdrawn: across 21 cells
spanning many configurations, nine lie between 5% and 95%. What is emerging is the *local* version
at this one near-tick configuration, which the withdrawal note explicitly left open. chain7 takes
it to n=19 at exactly this configuration, which is what would settle it. Not claimed until then.

### Three passes, 45 cells: one level of five reproduces

| load | pass A (warmup 1) | pass B (warmup 1) | pass C (warmup 0) | range |
|---|---|---|---|---|
| 0% | 1.51% | 99.98% | 100.00% | **98.5** |
| 50% | 76.32% | 4.79% | 99.31% | **94.5** |
| 75% | 95.59% | 94.70% | 75.82% | **19.8** |
| 88% | 95.22% | 94.53% | 95.18% | 0.7 |
| 95% | 77.37% | 23.71% | 94.99% | **71.3** |

45 cells. **Zero negative samples.**

**The third pass falsified an agreement.** At two passes, levels 75 and 88 agreed within a point,
and this document recorded that as coincidence rather than convergence "where both passes landed
high". Pass C moved level 75 by 19.8 points. Only level 88 survives all three. Adding a pass
turning a reproducible level into an unreproducible one is what coincidence does; convergence does
the opposite.

So the two-pass result understated it. **One per-level median in five reproduces across three
passes**, and four move by 19.8 to 98.5 points.

**Caveat on pass C.** It differs from A and B in one respect: warmup is disabled. That was shown
not to shift the retention fraction — the level-0 cells span the same range with and without it,
and only the sample count changes — so it is treated as a third pass. A referee is entitled to
discount it to a two-pass comparison, which still gives 98.5 and 71.5 point movements at two of
five levels.

**What this settles for the paper.** No per-level retention figure from this benchmark is
publishable at three replicates, and the appearance of reproducibility at one or two levels is not
evidence against that — it is what a quantity spanning 0.83% to 100% does occasionally. Our own
first sweep's per-level table must be reported as draws, not as a response curve. That was already
the conclusion at two passes; the third makes it unarguable.

### The cross-host run failed for the sixth time, and the gate held

`omb_distributed.sh` ran at 22:11Z and did not produce a measurement. The result row reads:

```
OpenMessaging Benchmark,distributed+loaded,0,,"benchmark produced no latency output (pub=3 agg=0 failures=1)",5,88
```

`IllegalArgumentException` at `HttpWorkerClient.java:194`, inside `Preconditions.checkArgument` —
the coordinator failing on a worker's HTTP response.

**Three things to record separately.**

*The defences worked.* Both workers answered before the benchmark started, so the classpath fault
that invalidated the 2026-07-25 attempt is genuinely fixed by shipping the packaged tarball. When
the run died, the output-validation gate refused to write a count and marked the row `valid=0`
with the reason. **No number was fabricated.** That gate exists because the first attempt wrote a
vacuous zero that reached a draft of this paper.

*It got further than before.* Earlier attempts died at worker startup. This one ran about thirty
seconds and emitted three publish-rate lines before the coordinator failed parsing a worker
response.

*A testable hypothesis.* Both hosts are pinned at 88% CPU by the campaign's own background load,
and the failure is in a worker HTTP response. Starved worker threads would explain it.

**chain9 tests it, and the test is worth running regardless.** Removing the background load does
not make a cross-host run useless. The load exists to provoke *scheduling* stalls — the occupancy
channel. The cross-host question is about the *clock* channel, and the measured bound between
these hosts (8.709 ms immediately before this run, against a 1 ms timestamp) does not depend on
CPU load. An unloaded distributed run still tests whether cross-host subtraction produces negative
samples. chain9 runs unloaded, then at 50%; if unloaded succeeds and 50% fails, the cause is load
and the paper can say so instead of only that the attempts failed.

**The manuscript's count needs updating either way.** §8 currently says the distributed run was
attempted five times and abandoned after five faults in the benchmark's own worker protocol. It is
now six, across two months of the campaign and two different fault modes. That is a reportable
observation about OMB rather than an embarrassment: its distributed mode did not survive six
attempts by someone reading its source.

### Settled headline figures for §6.7 (53 cells joined, 49 unsaturated)

Four cells ran with the link saturated (reported p50 of 235 ms to 43 s) and are excluded: they are
a different regime and their inclusion only dilutes the result. The remaining 49 are the regime
every co-located broker benchmark occupies, and the one this paper's own transport measurements
sit in.

| quantity | across 49 unsaturated cells |
|---|---|
| retention | **0.36% to 100.00%** — a 278-fold range |
| reported p50 | **exactly two values: 1.0 and 2.0 ms** |
| reported average | 1.000 to 11.503 ms |
| publish latency p50 (unquantised) | **0.3 to 0.4 ms** |
| Spearman(retention, reported average) | **−0.681** |
| Spearman(publish latency, retention) | **+0.075** |
| negative samples | **0** |

**Excluding the saturated cells strengthens the finding**, from −0.505 to −0.681. They were
diluting it, which is the opposite of the usual worry about dropping inconvenient data, and is
worth saying explicitly since dropping cells always invites the question.

**The mechanism question is settled negatively.** Publish latency is measured inside one process
and is not quantised to the millisecond grid, so it is a clean probe of how fast the path actually
was. It spans 0.1 ms while retention spans 278-fold, and their rank correlation is **+0.075**. The
path did not change. Whatever decides how much of its data OMB keeps, it is not how fast the
messages were.

**The three numbers to print together**, because each is weak alone and they are damning jointly:
retention ranges 278-fold; the reported median takes two values; the reported average moves
*inversely* with the amount of data behind it. An instrument whose headline is insensitive to a
278-fold change in its evidence, and whose secondary statistic moves the wrong way, is not
reporting the quantity its users think it is.

### The bimodality question, settled at n=18

Eighteen runs at a strictly identical configuration — 200 B, 0% background load, 3 minutes,
1 minute warmup — drawn from four campaigns run across nine hours. Retention, sorted:

```
0.36  0.41  0.44  0.83  1.00  1.51  2.62  2.91  7.34
39.39  96.42  99.98  99.99  99.99  100.00  100.00  100.00  100.00
```

| band | <2% | 2–10% | 10–90% | ≥90% |
|---|---|---|---|---|
| runs | 6 | 3 | 1 | 8 |

**Both earlier positions were partly wrong, and the resolution is specific.** "Two modes with
nothing between them" is false — four runs land between 2% and 90%. But the general claim that
retention is simply continuous understates what happens *at this configuration*: **14 of 18 runs
(78%) land within two points of an extreme.** The distribution is strongly bimodal with a sparse
middle, and the two statements are compatible because they are about different things — across
configurations retention sweeps continuously; at a configuration sitting on the tick it piles up
at the ends.

**The median of these 18 runs is 23.4%.** Only one run in eighteen landed between 10% and 90%. The
central summary describes a region where almost nothing occurs, which is the sharpest single fact
here: reporting a median retention for this benchmark names a value it essentially never produces.

**What this means for §6.7.** The claim is not that OMB's discard rate is noisy. It is that at a
sub-millisecond path the benchmark tends to keep either nearly all of its samples or nearly none,
that which one it does is not determined by anything the operator sets, and that its reported
summary is the same either way. Adding replicates does not converge on a usable central value
because there is no central value to converge on.

Consistent with the three-pass result: a three-replicate median of a distribution like this is a
draw from the ends, which is why per-level medians moved 54–98 points between passes.

### The mechanism, established by manipulation: phase, not speed

chain8 held message size, load, duration and host fixed and varied only the producer's send
interval relative to the millisecond grid. Predictions were filed before the run.

| rate | interval | commensurate with 1 ms? | retention per replicate | spread |
|---|---|---|---|---|
| 500/s | 2.000 ms | **yes** | 0.47, 1.51, 18.02, 99.99 | **99.5 pts** |
| 457/s | 2.188 ms | no | 48.77, 49.69, 50.87 | **2.1 pts** |

*(383/s pending.)* Zero negatives in both arms.

**The prediction held.** A producer paced on an exact multiple of the timestamp resolution
produces retention spanning almost the whole range; the same benchmark, same path, same load, at a
rate incommensurate with that resolution produces retention stable to two points.

**And the stable value is the one the model requires.** If samples are uniform in phase, the
fraction whose delivery crosses a tick boundary — and therefore computes to a non-zero
millisecond difference and survives the guard — is `latency / tick`. The 457 arm sits at
**≈50%**, implying a true end-to-end latency near **0.5 ms**. That is where the independent,
unquantised publish-latency probe put it: 0.3–0.4 ms publish, plus consumer-side delivery. The
quantitative agreement was not predicted in advance and is the strongest part of this result.

**What it explains.** Everything anomalous in this section falls out of it:

- why retention at a fixed configuration is strongly bimodal (phase-locked samples move together,
  so a run lands at one end or the other);
- why a three-replicate median moved 54–98 points between passes (each pass draws from the ends);
- why publish latency predicts retention at ρ = +0.075 (the path speed genuinely does not change);
- why the 64 KB cells were stable at ~35% (queueing dephases the samples, exactly as an
  incommensurate rate does deliberately).

**This is the standard the paper applies elsewhere** — §7.3 establishes its own mechanism by
manipulating both sides rather than by fitting. The same standard is now met here, and by a
manipulation nobody would run by accident.

**What it does not do:** it does not resurrect the causality reading. Zero negatives, across every
cell in every campaign. The mechanism explains which samples OMB *discards*, not any sample
arriving before it was sent.

### Rate-phase experiment complete: three arms, and the two dephased arms agree

| rate | interval | exact multiple of 1 ms? | retention per replicate | spread |
|---|---|---|---|---|
| 500/s | 2.000 ms | **EXACT** | 0.47, 1.51, 18.02, 99.99 | **99.5 pts** |
| 457/s | 2.188 ms | no | 48.77, 49.50, 49.69, 50.87 | 2.1 pts |
| 383/s | 2.611 ms | no | 50.28, 51.46, 53.13 | 2.8 pts |

Zero negatives in all twelve cells.

**Only the commensurate rate is unstable.** That was the prediction, filed before the run, and it
holds with a 35-fold difference in spread.

**The stronger test is that the two dephased arms agree with each other.** Their intervals differ
by 19% — 2.188 ms against 2.611 ms — and their retention medians differ by under two points
(49.60 and 51.46). If retention were a function of the pacing interval, those arms would separate.
Under the phase model it is a function of `latency / tick` alone, and the interval only determines
*whether* the samples dephase, not *what* the dephased fraction is. The arms had to agree, and
they do.

**Both land at ≈50%, which fixes the latency.** `latency / tick ≈ 0.5` with a 1 ms tick implies a
true end-to-end latency near 0.5 ms — independently consistent with the unquantised publish-latency
probe (0.3–0.4 ms plus consumer-side delivery). Three separate routes to the same number:
the dephased retention fraction, the publish-latency probe, and this project's own transport
measurements at 0.1–0.5 ms.

**The mechanism is therefore established, not inferred:**

> The OpenMessaging Benchmark's end-to-end guard discards samples whose millisecond-grained
> timestamp difference is zero. Whether a given sample crosses a tick boundary depends on its
> phase within the millisecond, and OMB paces its producer at a fixed interval. When that interval
> is an exact multiple of the timestamp resolution — as it is at the common rate of 500 msg/s —
> every sample in a run holds the same phase, so a run discards nearly all of its samples or
> nearly none, unpredictably. When the interval is incommensurate, samples dephase and a stable
> `latency / tick` fraction survives. The reported latency summary is the same in all cases.

**Not the causality claim.** Zero negatives, every cell, every campaign. This governs which samples
are discarded, not any sample arriving before it was sent.

### Correction: the retention/average correlation is not a headline number

Filed earlier today as a settled headline: *Spearman(retention, reported average) = −0.681 across
49 unsaturated cells.* With the bimodality and rate-phase campaigns indexed, the same statistic
reads:

| subset | n | ρ |
|---|---|---|
| all joined | 75 | −0.160 |
| unsaturated | 71 | −0.236 |
| phase-locked only | 63 | **−0.350** |
| dephased arms only | 8 | +0.152 |

**−0.681 is withdrawn as a quotable figure.** It was computed on 49 cells whose configurations
happened to favour it; adding 14 more at a single configuration halved it. A rank correlation that
moves from −0.68 to −0.35 on a change of sample composition is not measuring a stable relationship,
and printing the most favourable of those numbers would be precisely the selective reporting this
paper objects to.

**What survives.** The direction is negative in every aggregate subset, and the *mechanism* for it
is sound — discarding sub-tick samples removes fast ones and lifts the mean. So the qualitative
statement stands: *the reported average rises as retention falls, which is the opposite of what a
reader would infer from a "samples were dropped" caveat.* The magnitude does not, and no ρ should
be printed as a headline.

**A prediction I will not claim as confirmed.** I expected the dephased arms to show no
truncation bias, because there whether a sample survives depends on phase, which is independent of
its latency — a speed-neutral filter. Their ρ is +0.152, which is the right side of zero. But those
eight cells have reported averages spanning 1.0000 to 1.0058 ms: there is essentially no variance
to correlate. The result is uninformative, not supportive, and reading it as support would be
finding a prediction in noise.

**The three claims that carry §6.7 do not depend on any of this**: retention spans 0.36% to 100%;
the reported p50 takes two values across that range; and zero negative samples in every cell of
every campaign. Those are counts and ranges, not correlations, which is why they have not moved
all day.

### The cross-host question is not answerable with this benchmark, and that is the finding

The load-starvation hypothesis is **refuted**. OMB's distributed mode fails identically with no
background load at all.

| attempt | load | outcome |
|---|---|---|
| 1–5 (July) | 88% | five separate faults in the worker protocol |
| 6 (chain5) | 88% | `IllegalArgumentException` at `HttpWorkerClient:194`, pub=3 agg=0 |
| 7 (chain9) | **0%** | identical fault, pub=2 agg=0 |
| 8 (chain9) | 50% | identical fault, pub=2 agg=0 |

Eight attempts, three load levels including none at all, and the same failure inside OMB's own
coordinator-to-worker HTTP protocol. The hypothesis that 88% CPU was starving the worker threads
was reasonable and is wrong.

**What was fixed and stayed fixed.** The classpath fault that invalidated the first attempt is
genuinely gone — the packaged tarball ships its own dependencies, and both workers answered their
health check before every one of the last three runs. These are not failures to launch. The
benchmark starts, publishes for a few seconds, and then its coordinator fails parsing a worker
response.

**The gate held eight times out of eight.** Every failed attempt wrote `valid=0` with the pub,
aggregate and failure counts that justified it. No count was ever reported from a run that did not
produce latency. That gate exists because the very first attempt wrote a vacuous `discarded=0`
that reached a draft of this paper as "a second null under hard conditions".

**How the paper should state it.** Not as a gap in our diligence and not as an aside:

> The cross-host case is the one in which OMB's end-to-end subtraction spans two clocks, and it is
> therefore the case in which its guard could discard a genuine causality violation. We cannot
> report a measurement of it. Across eight attempts at three background-load levels, the
> benchmark's distributed mode did not complete a run on our testbed, failing each time inside its
> own coordinator-to-worker protocol rather than in our instrumentation or configuration. The
> exposure in that mode is established by source audit — the timestamp is written on the producer
> host and read on the consumer host, and the guard drops what the difference produces — but not by
> observation, and we distinguish the two.

That is a stronger position than a single successful distributed run would have given us, because
it is checkable: the campaign script, the eight invalid rows and their reasons are in the artefact.

**Also worth one line in §6.7:** a benchmark whose distributed mode does not survive eight attempts
by readers of its source is itself a data point about the state of measurement practice this paper
is describing.

## Literature position for the resolution failure mode (2026-07-27)

Searched for prior work on the second failure mode. Three bodies of work are close; none reports
it, and the relationship to each should be stated rather than left for a referee to raise.

**Coordinated omission (Tene, ~2013) — the closest, and a different mechanism.** CO is the
canonical "your load generator is lying to you" result: a synchronous measurement thread blocks
while the system under test stalls, so the worst samples are *never taken*, and reported
percentiles are optimistic by orders of magnitude. Ours is the mirror image: the samples *are*
taken, computed, and then **discarded by a guard** because a quantised subtraction returned zero.
CO loses the slow tail; this loses the fast bulk. Both end in a confident summary computed from a
biased subset, which is why they belong in the same paragraph — and why conflating them would be
wrong.

The sharpest connection: **OMB records into an HdrHistogram**, and HdrHistogram ships explicit
machinery for CO (`recordSingleValueWithExpectedInterval`). The ecosystem has a correction for the
known sampling bias and none for this one — and it is HdrHistogram's rejection of negative values
that motivates the `> 0` guard in the first place. A defence against one measurement artefact
created the conditions for another.

**Dithering (signal processing, decades old) — the fix already exists elsewhere.** Breaking
periodic sampling artefacts by randomising or offsetting the sampling instant is standard
practice; the literature explicitly uses dithered measurement rates to distinguish true signal
components from aliasing products. Our incommensurate-rate arms *are* dithering, arrived at as a
diagnostic. The recommendation to benchmark authors is therefore not novel technology but a known
technique never applied here: **do not pace a load generator at a rate commensurate with your
timestamp resolution, and if you must, dither it.**

**Clock granularity vs. pulse rate.** The relationship between a send interval and tick
granularity is noted in the timing literature in terms of *staleness* (a 3 ms pulse on a 1 ms tick
can be 2 ms stale). What is not reported is the consequence when a positivity guard sits
downstream: staleness becomes *deletion*, and because the phase is locked, deletion is
all-or-nothing across a whole run.

**The novelty claim, stated narrowly.** Not "quantisation is unknown" — it is elementary. The
contribution is the *interaction*: quantised timestamps, plus a producer paced at a commensurate
interval, plus a positivity guard, together produce sample retention that is bimodal, run-to-run
irreproducible, and invisible in the reported summary. We have found no report of that
combination, and it occurs at 500 msg/s — a rate a benchmark user would choose for being round.

---

# Campaign status, 2026-07-27 03:00Z

**Ledger: 90 cells, 88 valid, 0 negative samples.** The negative count has not moved from zero
across every campaign, which is what the withdrawal rests on and the only number that would change
the paper's conclusion if it did.

| campaign | cells | what it settles |
|---|---|---|
| `load_sweep` | 15 | the load axis; zero negatives |
| `load_sweep_p2` | 15 | replication pass 2 — medians reproduce at 1 level in 5 |
| `load_sweep_nowarmup` | 15 | matched denominators; warmup is bookkeeping, not bias |
| `resolution` | 8 | instability is confined to the near-tick regime |
| `rate_phase` | 12 | **B2 established** — commensurate pacing is the variable |
| `bimodality` | 10 | n=18 at one configuration; median 23.4% occurs once in 18 |
| `tprobe` | 10/24 | **B1 under test** — retention vs `T_true` at a dephased rate |
| `rate_phase2` | 0/12 | B2 confirmation at two more exact multiples |
| smoke/idem/exact | 5 | pre-hook cells, excluded from analysis by rule |

## What the paper is waiting on

**B1 (`retention = min(1, T_true/τ)`)** is the one open quantitative claim. The three payload
levels so far are consistent but uninformative --- predicted spread 1.5 points against ~2 points
of replicate noise, because 200 B to 2 KB moves `T_true` by only microseconds:

| payload | observed | predicted |
|---|---|---|
| 200 B | 52.03% | 52.0% (anchor) |
| 1 KB | 50.32% | 52.7% |
| 2 KB | 53.37% | 53.5% |

chain12's cells are the discriminating ones: **32 KB predicts 78%, 64 KB predicts 100%.** If
retention stays near 50% while the path demonstrably slows, B1 is refuted and the agreement of
three dephased arms at ~50% was coincidence.

**B2 confirmation** needs `rate_phase2`: 1000 msg/s (1.000 ms) and 250 msg/s (4.000 ms) predicted
bimodal, 333 and 611 predicted stable. If the new exact multiples are stable, B2 is wrong.

## Manuscript state

Rewritten and committed: title, abstract, introduction, contributions, related work (including the
coordinated-omission and dithering placement), the external-instrumentation methodology, §6.7 in
full, the phase table, and the two new recommendations.

Not yet written, because they depend on the above: the retention-law figure, the conclusion, and
the final build with the rendered-PDF check. Equation~\ref{eq:retention} is currently in the paper
labelled a *derived prediction*, and stays that way unless chain12 confirms it.

## What is the rule? A quantisation prediction, recorded before the run (2026-07-27)

Commensurability is established: two exact multiples give replicate spreads near 99 points
(500 msg/s at 99.5, 1000 msg/s at 99.3), two incommensurate rates give 2.1 and 2.8. But that only
shows *that* commensurability matters, not *what the rule is* — everything measured sits at one
extreme or the other.

**The phase account predicts something sharper.** Write the producer's interval over the tick as a
fraction `p/q` in lowest terms. A producer paced at that interval visits exactly **`q` distinct
phases** within the tick, because after `q` sends the phase returns to where it started. So
retention should be **quantised into `q+1` possible levels**, and the replicate spread should fall
roughly as `100/q`:

| interval/tick | fraction | q | predicted retention levels | predicted spread |
|---|---|---|---|---|
| 2.000 | 2/1 | 1 | 0 or 100 | ~99 *(measured 99.5)* |
| 1.000 | 1/1 | 1 | 0 or 100 | ~99 *(measured 99.3)* |
| 2.500 | 5/2 | 2 | 0, 50, 100 | ~50 |
| 3.333 | 10/3 | 3 | 0, 33, 67, 100 | ~33 |
| 1.250 | 5/4 | 4 | 0, 25, 50, 75, 100 | ~25 |
| 1.125 | 9/8 | 8 | eight levels | ~12 |
| 2.188 | large `q` | — | continuous at `T/τ` | ~2 *(measured 2.1)* |

**chain14 tests it** at 400, 300, 800 and 889 msg/s — `q` = 2, 3, 4, 8 — with **five replicates
each** rather than three, because distinguishing `q+1` discrete levels from a continuum requires
enough draws to see the gaps and three cannot show a gap.

**Both falsifying outcomes are stated in advance.** If the spread stays near 99 for every rational
rate regardless of `q`, the rule is simply "integer or not" and the quantisation prediction is
wrong. If it stays near 2 for everything except exact integers, likewise. Either would leave B2
standing as a binary distinction and this refinement withdrawn.

If it holds, the rule is considerably more useful than "avoid round rates": it says the damage is
governed by the *arithmetic* relationship between pacing and clock, that a rate need not be an
integer multiple to be dangerous, and that safety comes from a large denominator rather than from
any particular rate.

### B2 complete: seven rates, a 30-fold separation, and one anomaly worth keeping

| group | rate | interval | q | n | spread |
|---|---|---|---|---|---|
| commensurate | 1000/s | 1.000 ms | 1 | 3 | **99.3** |
| commensurate | 500/s | 2.000 ms | 1 | 4 | **99.5** |
| commensurate | 250/s | 4.000 ms | 1 | 3 | **58.6** |
| incommensurate | 611/s | 1.637 ms | >64 | 2 | 3.1 |
| incommensurate | 457/s | 2.188 ms | >64 | 4 | 2.1 |
| incommensurate | 383/s | 2.611 ms | >64 | 4 | 2.8 |
| incommensurate | 333/s | 3.003 ms | >64 | 3 | 3.1 |

**The incommensurate group is the stronger half of this result.** Four rates, four different
intervals, spreads of 2.1 to 3.1, and all four sitting at $46$--$54\%$ retention. That is the
`T_true/τ` prediction holding across a group rather than at one point, and it is what a
dependence on the *interval* could not produce.

**The 250 msg/s anomaly is reported, not averaged away.** Its three replicates are 41.39, 99.53
and 99.99 — two at the top and one intermediate, giving 58.6 rather than the ~99 of the other two
exact multiples. Under a strict one-phase model an intermediate value should not occur. The likely
causes are OMB's rate limiter jittering slightly off exactly 4.000 ms, or the phase drifting over
the longer interval; we have not separated them. The paper should state this rather than quote a
mean of the three commensurate spreads, because a model that predicts all-or-nothing and delivers
one intermediate in nine is a model with a stated exception rather than a clean one.

**Still UNDECIDED, correctly.** Every rate measured is either `q=1` or `q>64`. The quantisation
refinement — spread ~ `100/q` — remains untested until chain14 supplies `q` = 2, 3, 4, 8.

### The quantisation prediction was wrong in its observable, and the correction is sharper

`q=2` (400 msg/s, 2.500 ms) returned **50.42, 50.45, 50.88, 53.53** — a spread of 3.1,
indistinguishable from the incommensurate rates. **The prediction that spread falls as `100/q` is
refuted**, and the analyser returns BINARY on the evidence.

**Why it was wrong, from the same model.** A 2.500 ms interval against a 1 ms tick puts sends at
phases 0 and 0.5 alternately. A three-minute run at 400 msg/s makes ~72,000 sends, so *every run
visits both phases in equal proportion*. Retention is therefore the average over the `q` phases,
which is the same in every run — stable, not spread. The instability at `q=1` arises for the
opposite reason: a single phase is fixed for the whole run and varies *between* runs with the
start offset.

So the phase account survives; our derived observable did not. Restated:

> With `q` phases visited, retention is the fraction of those `q` phases whose delivery crosses a
> tick boundary — hence a **multiple of `1/q`**, stable across runs. Only `q=1` makes retention a
> single phase's outcome, and therefore a coin flip between 0 and 1.

**`q=2` cannot discriminate between this and the binary account.** Quantised-to-halves gives
$0.5$; the continuous prediction `T_true/τ` also gives $0.5$, since `T_true ≈ 0.5` ms. Both predict
what we measured, which is why the arm was uninformative and would have been whichever way it fell.

**`q=3` discriminates, and is recorded before it lands.** At 300 msg/s (3.333 ms):

| account | predicted retention |
|---|---|
| binary / continuous | $\approx 50\%$, matching every incommensurate rate |
| quantised to $1/q$ | $\approx 33\%$ or $\approx 67\%$ — a third or two thirds, **not** a half |

A result near $50\%$ refutes quantisation and leaves the rule binary: only exact multiples matter.
A result near $33$ or $67\%$ establishes it. `q=4` (800 msg/s) and `q=8` (889 msg/s) follow, where
quantisation predicts values on the $1/4$ and $1/8$ grids.

This is a correction to our own prediction, made before the discriminating data and stated as
such. The first version was falsified by `q=2`; we are not rescuing it but replacing the observable
with the one the model actually implies, and naming the measurement that decides between them.

### q=3 decides it: retention is quantised to the 1/q grid

The measurement named in advance as discriminating has landed. At 300 msg/s (3.333 ms, `q=3`),
five replicates gave **34.9, 36.7, 39.4, 41.1, 65.4**.

| | values | vs the incommensurate range |
|---|---|---|
| `q=3` | 34.9, 36.7, 39.4, 41.1, 65.4 | **all five fall outside 46.5–53.8** |
| incommensurate (4 rates, 14 cells) | pooled median $50.46\%$ | range $46.5$–$53.8$ |

**Four of five sit entirely below the incommensurate range and the fifth entirely above it, with
no overlap.** The binary account predicts `q=3` behaves like any other non-integer rate, at
$\approx 50\%$. It does not.

**The mechanism works out arithmetically.** With phases at $0$, $1/3$, $2/3$ and
`T_true ≈ 0.5` ms against a $1$ ms tick: phase $0$ delivers at $0.5$ (no crossing), phase $1/3$ at
$0.833$ (no crossing), phase $2/3$ at $1.167$ (**crosses**). Retention $= 1/3$ — where four of five
landed. The fifth, at $65.4\%$, is $2/3$, which requires two of three phases to cross and
therefore `T_true` slightly above $0.667$. So a small between-run drift in `T_true` moves a run
between grid points, which is the same between-run mechanism as `q=1` with three landing places
instead of two.

**Deviation from the nearest grid point grows with `q`:** $0.0$ at `q=1`, $0.9$ at `q=2`, $3.4$ at
`q=3`. Finer grids are harder to hit against fixed jitter, which is the expected direction.

**Scorecard for this prediction.** The observable we first published — spread falling as `100/q` —
was **refuted by `q=2`**. Re-derived from the same model, the observable is retention on the `1/q`
grid, and `q=2` was identified *in advance* as unable to discriminate, since $1/2$ and
`T_true/τ ≈ 0.5` coincide. `q=3` was named as the deciding case before it ran, with both outcomes
stated. It supports quantisation.

`q=4` (800 msg/s) and `q=8` (889 msg/s) remain: quantisation predicts values on the quarters and
eighths grids and, in particular, still away from $50\%$ for `q=4` unless the run lands on $2/4$.
