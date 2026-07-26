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
