# Every review, and what was done about it

One internal review held to IEEE TPDS's standards, two held to IEEE TC's, and the plan and
letter that answered them. The reports themselves are not public; what is here is what was
asked and what changed because of it.

*Fused on 2026-09-21 from 5 documents, each carried over unchanged below.*

## Contents

- [Referee response plan](#referee-response-plan) — was `docs/referee_response_plan.md`, last changed 2026-09-15
- [Response to the referee report (internal TPDS/TC-standard review)](#response-to-the-referee-report-internal-tpds-tc-standard-review) — was `docs/referee_response_letter.md`, last changed 2026-09-15
- [Response to internal review — TPDS standard, round 1](#response-to-internal-review-tpds-standard-round-1) — was `docs/response_to_referee_tpds.md`, last changed 2026-09-15
- [Response to internal review — IEEE Transactions on Computers standard, round 1](#response-to-internal-review-ieee-transactions-on-computers-standard-round-1) — was `docs/response_to_referee_tc.md`, last changed 2026-09-15
- [Response to internal review — IEEE Transactions on Computers standard, round 2](#response-to-internal-review-ieee-transactions-on-computers-standard-round-2) — was `docs/response_to_referee_tc_r2.md`, last changed 2026-09-15

## Referee response plan

> Was `docs/referee_response_plan.md`.

> All referee reports referenced in this document are internal reviews, held within the
> project before any journal submission. The manuscript has never been submitted to TOMPECS,
> TPDS, or any other journal; no verdict below was issued by a journal's reviewer.

A demanding internal review recommended **reject in present form** for the
then-TOMPECS-targeted draft. This
document is the response plan: every issue raised, what we are doing about it, and the current
state. It supersedes the earlier "Phase 5" plan item, which described a manuscript rebuild that
has since happened.

The referee's decisive objection is not any single number. It is that a paper prescribing a
method to a field must show the method matters to somebody other than its authors. Everything
below is ordered by how much it moves that objection.

---

### M1 — The generalisation rests on n=1, and that n is us (DECISIVE)

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

### M2 — Two withdrawals and one unresolved contradiction

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

### M3 — H1's quantitative support is confounded (KEYSTONE)

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

### M4 — H2's M/G/1 evidence is close to unfalsifiable

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

### M5 — The provenance gap is treated too lightly

**Referee:** "not being able to state the independent variable of the primary corpus is close to
disqualifying... §7.3 is currently defended by an inference the authors themselves distrust."

**Partially accepted.** The recovery argument is sound and we stand behind it, but the referee is
right that a headline table should not *rest* on it.

**Action (writing only):** restructure §7.3 so the load-bearing evidence is the powered
replication at a verified rate — where the rate is documented, not inferred — and E1 is reported
as the historical corpus it is. The recovery stays in §6.5 as a methodological episode, which is
where it belongs, rather than as the foundation of a claim.

---

### M6 — Statistical fragility

**Referee:** per-cell samples 8–35; retention bound needs >50% and the tightest cell is 52.8%.

**Accepted as a limitation, mitigated by design.** The powered replications (15 and 8 reps) and
E-A3 (25 runs per condition) already raise per-cell counts substantially for every claim added
since. The 52.8% cell belongs to the E1 corpus, which under M5 stops being load-bearing.

**Action:** state explicitly which claims rest on which sample sizes, and make clear that the
retention-bound argument applies only to the historical corpus.

---

### M7 — The workload is vestigial

**Referee:** "If the sports workload no longer does work in the argument, the title's promise and
§3's presence need justifying."

**Partially accepted.** The workload *does* still do work — it supplies the sparse bursty arrival
process that makes the failure visible, the kickoff burst that produces the start-up cost, and
the real concurrency levels. But the paper does not say so clearly enough.

**Action (writing):** make §3 earn its place by stating, at each point, which later result depends
on which workload property. Do not cut it; justify it.

---

### Minor

- **Figure 5 renders `\%` literally.** matplotlib without `usetex`; the escape is a LaTeX habit.
  Fix the label strings. *(local, quick)*
- **30 pages is long.** Consolidate §4 (eight subsections) and §6 (seven).
- **Table 9 retains withdrawn columns.** Keep, but make the caption unmissable.
- **"Sound" used in a narrow sense.** Already defined in §4.7; check every other use.

---

### What would flip the recommendation

The referee named three: **M1** (external validation), **M3** (clean effect-size manipulation),
**M2** (resolve the discrepancy). M1 is the one that matters most and the one we had not
attempted. M4 and M5 need honest downgrading rather than new experiments.

### Status board

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

#### Beyond the referee's list

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

## Round 2 — internal referee review, 2026-07-26

The first round closed. Before resubmitting, the manuscript was reviewed again from the position
of a rigorous TOMPECS referee specialising in performance measurement. That review is recorded
here in full, followed by the response plan.

**Recommendation received: MAJOR REVISION**, reject if M1–M3 cannot be met.

### The review

#### M1 — The headline contribution may be a lint rule, not a research result

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

#### M2 — Every mechanism result rests on one machine

§7.3 — priority at fixed ρ (7–80×, 8 pairs), two geometries at ρ identical to four decimals
(2.07×, 2.05×), the payload sweep, the kernel trace — all from four VMs of one shape
(`VM.Standard.E5.Flex`), one kernel (`6.8.0-1057-oracle`), one CPython. The paper nonetheless
reports α ≈ 0.34 and "no finite mean" as though characterising Linux scheduling. It characterises
one kernel on one instance type under stress-ng. The tail index is four points per campaign at a
single load level; two campaigns agreeing to 1.5% shows reproducibility, not generality.

**Replicate the geometry contrast and the payload sweep on a materially different machine, or
systematically downgrade the language.**

#### M3 — External validity rests on a single 3-minute run

`omb_loaded_result.csv` records one run: embedded mode, 88% load, 3 minutes, 6,000 discards. That
single run answers "is anyone but you exposed?", the objection the authors call decisive. The
source audit is solid; the empirical claim is n=1, one load, one mode, distributed unreported.
**A load sweep with replication, both brokers. The discard count as a function of load is the
interesting result and is missing.**

#### S1 — The 58% is partly an artefact of a poor rig

Testbed A is Windows + Docker Desktop + WSL2, 15.6 ms timer quantum, 5.6–9.9 ms TCP connect.
Sub-millisecond transport cannot be measured there at all, so "58% rejected" substantially reports
*we built an unsuitable rig*. Testbed B's 51.9% is the defensible figure. **Lead with it.**

#### S2 — The instrument perturbs the measurement, and this is under-weighted

All three traced real-time arms recorded zero inversions where the untraced twin recorded 15/2985.
The authors found their own instrument changing what it observes, report it honestly, then set the
consequences aside. The ordinary arm is also affected — the two traced 88% values are the lowest
of six — and the instrument check cannot resolve an effect below ~15%. **An untraced control in
the same session as each traced arm.**

#### S3 — The mechanism does not predict, and the paper knows it

Two attempts failed (M/G/1 at R²=−0.05; the authors' own bracket 2.45–3.07× against 1.44×). With
M1, a reader may ask what is left. The T_true dependence is the answer — a slower path is a more
reliable measurement, directly actionable and counter-intuitive — and it is one subsection among
many. **Promote it.**

#### S4 — The residual sign flips and the explanation was withdrawn

Ratios 0.78, 1.06, 1.32. "Agreement to within a third, unfitted" is weaker than §7.3's framing
implies, on three arms.

#### S5 — Churn

Two headline withdrawals, M/G/1 refuted, the authors' own bracket failed, co-location withheld, a
k=7 null withdrawn, a directional argument withdrawn. Each correction is creditable; collectively
they invite the question of what survives the next replication. **State which claims are settled
and which are expected to move.**

#### S6 — The football workload is vestigial

Conceded in §3. It contributes sparsity and a dense kickoff burst, both obtainable synthetically.
3,315 matches characterised to justify replaying eleven is disproportionate.

#### Minor

0.41 ms reported as "real and negligible" — develop it or cut it to a sentence; `not-assessed` vs
`condemned` still invites comparing 366 to 862; no Holm family declared for the §7.3 campaigns;
§7.3 is ~9 pages and should split established from exploratory; ρ to four decimals implies
precision the day-to-day drift (0.221–0.305) does not have.

#### What the referee credits

The §7.3 manipulation design; the T_true sweep as the best experiment in the paper; reporting the
withheld arm; the OMB source audit; reproducibility infrastructure above field norm.

---

### Response plan

Ordered so the machines are working while the prose is rewritten. Runs first, corrections during.

#### Phase R — runs and machines (start immediately)

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

#### Phase C — corrections, in parallel with Phase R

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

#### Sequencing

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

## R1 outcome — the OMB claim does not survive its own sweep (2026-07-26)

Phase R's first run was the sign-separated discard sweep, queued to settle referee **M3**
("external validity rests on a single 3-minute run"). It settled more than that. The claim it
was meant to strengthen is not supported, and the paper must change before anything else in
Phase C is worth doing.

### What was run

`cloud/campaigns/omb_load_sweep.sh` — five background-load levels (0, 50, 75, 88, 95%), three
replicates each, three minutes per cell, against Kafka on `sbl-b1`. The counter that produced
the manuscript's $6{,}000$ was a single total with no sign. It is now four counters — zero,
negative, most-negative, kept — printed exactly by a JVM shutdown hook rather than sampled from
progress lines that quantise to 10,000.

### What it found

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

### What survives, what falls, what gets stronger

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

### Still to land before §6.7 is rewritten

- `omb_resolution_test.sh` — message size 200 B → 256 KB, the decisive discriminator. Resolution
  predicts the zero-share collapses once latency clears one tick; causality is indifferent to
  message size. **Chained, fires on sweep exit.**
- Reps 4–6 per load level → `load_sweep_p2`. At 0% load the three reps gave 98.5%, 99.2% and
  0.003%; that bimodality is what a tick boundary looks like, but three reps cannot establish
  it. **Chained.**
- `index_external_campaigns.py` over every cell, so the campaign is in a ledger like our own runs.

### Consequence for the referee's M3

M3 asked for more than one 3-minute run. It now has 15, and will have 38. The answer to M3 is
no longer "here is more of the same evidence" but "the additional evidence overturned the
reading, and we corrected it" — which is the better answer to give, and the one this paper is
in a poor position to refuse.

### R1 addendum — the discard rate is a threshold, not a rate (2026-07-26)

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

#### Correction to the R1 trend statement

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

#### Caveat on the message-size sweep's largest cell

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

#### Correction to the bimodality addendum

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

#### The simple resolution model is insufficient, and the 64 KB pre-registration was wrong

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

#### An accidental positive control for the phase hypothesis

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

#### The completed size sweep: a dose-response, but not a discrimination

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

#### Size sweep complete: instability is confined to the near-tick regime

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

#### Replicates that agree with each other are not a reproducible measurement

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

#### The replication pass, complete: a three-replicate median is a coin flip

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

#### Prediction for the no-warmup sweep, recorded before it finishes

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

#### No-warmup sweep: the prediction holds, and the warmup concern is closed

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

#### Three passes, 45 cells: one level of five reproduces

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

#### The cross-host run failed for the sixth time, and the gate held

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

#### Settled headline figures for §6.7 (53 cells joined, 49 unsaturated)

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

#### The bimodality question, settled at n=18

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

#### The mechanism, established by manipulation: phase, not speed

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

#### Rate-phase experiment complete: three arms, and the two dephased arms agree

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

#### Correction: the retention/average correlation is not a headline number

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

#### The cross-host question is not answerable with this benchmark, and that is the finding

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

### Literature position for the resolution failure mode (2026-07-27)

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

## Campaign status, 2026-07-27 03:00Z

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

### What the paper is waiting on

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

### Manuscript state

Rewritten and committed: title, abstract, introduction, contributions, related work (including the
coordinated-omission and dithering placement), the external-instrumentation methodology, §6.7 in
full, the phase table, and the two new recommendations.

Not yet written, because they depend on the above: the retention-law figure, the conclusion, and
the final build with the rendered-PDF check. Equation~\ref{eq:retention} is currently in the paper
labelled a *derived prediction*, and stays that way unless chain12 confirms it.

### What is the rule? A quantisation prediction, recorded before the run (2026-07-27)

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

#### B2 complete: seven rates, a 30-fold separation, and one anomaly worth keeping

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

#### The quantisation prediction was wrong in its observable, and the correction is sharper

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

#### q=3 decides it: retention is quantised to the 1/q grid

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

#### Only odd `q` can discriminate — a design fault in our own sweep

`q=4` (800 msg/s) returned **44.7, 49.9, 50.4, 50.4**: sitting at $50\%$, deviation $0.4$ from the
quarters grid. That is not a failure of quantisation. With `T_true ≈ 0.5` ms and phases at
$0, \tfrac14, \tfrac12, \tfrac34$, exactly two deliver past a boundary, so retention $= 2/4 = 0.5$
--- which is *also* the continuous prediction `T_true/τ`.

**Every even `q` is degenerate at this operating point**, because $0.5$ lies on every even grid:
$1/2$, $2/4$ and $4/8$ are all the continuous value. Our sweep chose `q` = 2, 3, 4, 8 — three of
them even. **`q=3` was the only discriminating arm in the entire sweep**, and `q=8` will be
degenerate as well when it lands.

This is a design fault of ours and it is the same one as the payload sweep, where the first
attempt used sizes entirely inside the noise-dominated regime. In both cases the manipulation was
chosen without checking whether it could separate the hypotheses at the operating point we were
measuring at.

`q=3` did decide it — five of five outside the incommensurate range — but one discriminating point
is thin for a law. Two more exist at integer rates, and **chain15 runs both**:

| rate | interval | q | phases crossing | predicted retention |
|---|---|---|---|---|
| 625/s | $1.600$ ms $= 8/5$ | **5** | $2$ of $5$ | $\approx 40\%$ |
| 875/s | $1.143$ ms $= 8/7$ | **7** | $3$ of $7$ | $\approx 43\%$ |

Both predictions are recorded before the runs, and both are clear of the incommensurate range
($46.5$–$53.8$). **If either lands at $\approx 50\%$, the `q=3` result was a coincidence and
quantisation is withdrawn.**

#### `q=5` landed: the rule survived and my stated grid point did not

Five replicates at $625$/s: $40.71$, $42.11$, $46.58$, $55.50$, $58.60$. **The median is $46.6\%$,
which is inside the incommensurate range and $6.6$ points off the $40\%$ I recorded above. That
specific prediction failed and I am not going to describe it as anything else.**

What failed was the grid point, not the grid. The error is in the phrase "$2$ of $5$": with
$T_{\mathrm{true}}/\tau$ measured at $0.495$ — indistinguishable from a half — the number of phases
that cross a tick boundary is $2$ *or* $3$ depending on where the run's initial phase falls, so a
replicate is predicted at $40\%$ **or** $60\%$, averaging near $50$. I wrote down one of the two
branches and called it the prediction. The five replicates are $40.7, 42.1$ (the $2/5$ branch),
$55.5, 58.6$ (the $3/5$ branch), and one crossing at $46.6$ — bimodal about the grid, which is what
the rule actually says.

The statistic that does test the rule without needing to know which branch a run takes is replicate
spread, and it was pre-registered independently, in the header of
`scripts/analyze_phase_quantisation.py`: *"retention takes one of $(q+1)$ values, and replicate
spread falls roughly as $100/q$."* Against that:

| rate | q | measured spread | $100/q$ | |
|---|---|---|---|---|
| 1000/s | 1 | $99.3$ | $100.0$ | ✓ |
| 500/s | 1 | $99.5$ | $100.0$ | ✓ |
| 300/s | **3** | $30.5$ | $33.3$ | ✓ |
| 625/s | **5** | $17.9$ | $20.0$ | ✓ |
| 400/s | 2 | $17.6$ | $50.0$ | degenerate |
| 800/s | 4 | $7.2$ | $25.0$ | degenerate |
| incommensurate | $>64$ | $1.7$–$3.1$ | $\approx 0$ | ✓ |

Four discriminating denominators, each within $3$ points of $100/q$ across a range of $100$ points.

**The degeneracy exclusion is load-bearing, so its timing matters.** It was derived from the $q=4$
arm and committed in `f4b5eec` at 14:09Z on 2026-07-27; the first $q=5$ cell was measured at 15:06Z,
$57$ minutes later. The odd-$q$ arms exist *because* the rule predicted they would discriminate. It
is now encoded in the analyser as the general statement rather than as "skip even $q$" — an arm is
degenerate when the *measured* continuous value passes within *measured* replicate noise of its
grid. At this operating point that selects the even $q$; at $T_{\mathrm{true}}/\tau = 1/3$ it would
select $q=3$ instead and leave $q=2$ discriminating, which is the behaviour a test asserts.

The margins are not close. The degenerate grids pass $0.5$ points from the continuous value against
a noise floor of $1.6$; the discriminating ones sit at $16.2$ ($q=3$), $9.5$ ($q=5$) and $6.6$
($q=7$). No arm is near the threshold, so the verdict does not depend on where it was set.

**Still open.** $q=7$ has one replicate ($42.95\%$, against a $3/7 = 42.86\%$ grid point — close
enough to be worth nothing at $n=1$); its test is spread $\approx 14.3$. And chain16 repeats $q=3$
at $600$/s, half the interval of $300$/s, to separate the denominator from the rate carrying it.
**If $600$/s does not reproduce the $300$/s spread of $\approx 33$, then $q$ is not the governing
variable and this generalises no further than the rate it was found at.**

#### The prediction was an upper bound, and stating it as a point prediction cost us the even arms

Checking whether the degeneracy classification survives using a *rate-local* continuous value rather
than the pooled median turned up something larger. The continuous value is not constant across rate:
it runs $51.2\%$ at $333$/s down to $47.5\%$ at $889$/s, a linear trend of $4.15$ points across the
range against a replicate noise of $1.55$ ($R^2 = 0.78$). Under the pooled value $q=4$ is degenerate;
under the rate-local one it is not, and it would then be a *failure*. A result that flips on that
choice is not a result.

Working out why exposed the real error. **`spread = 100/q` is not what the model predicts.** A
replicate lands on one of the two grid points bracketing $T_{\mathrm{true}}/\tau$, so $100/q$ is the
*cell width* — an upper bound, attained only when the continuous value sits midway between two grid
points and both get realised. When it sits *on* a grid point, one point takes nearly every run and
the spread collapses toward zero.

That single correction removes the need for the exclusion entirely:

| rate | q | width | position in cell | predicted | observed | |
|---|---|---|---|---|---|---|
| 1000/s | 1 | 100.0 | mid (0.99) | full | 99.3 | ✓ |
| 500/s | 1 | 100.0 | mid (0.99) | full | 99.5 | ✓ |
| 250/s | 1 | 100.0 | mid (0.99) | full | 58.6 | ✓ |
| 400/s | 2 | 50.0 | **on grid (0.02)** | **flat** | 17.6 | ✓ |
| 300/s | 3 | 33.3 | mid (0.97) | full | 30.5 | ✓ |
| 800/s | 4 | 25.0 | **on grid (0.04)** | **flat** | 7.2 | ✓ |
| 625/s | 5 | 20.0 | mid (0.95) | full | 17.9 | ✓ |
| 875/s | 7 | 14.3 | mid (0.93) | full | 10.7 | ✓ |

**All eight arms match, six predicting full spread and two predicting flat.** The verdict is now a
classification with no tolerance to choose: an arm shows the full cell width or it collapses, and
"spread above half the cell width" separates them. Because the position is measured against the cell
*half-width* rather than a fixed noise floor, every call is identical under the pooled and the
rate-local continuous value — the sensitivity that started this is gone.

The earlier framing was defensible and is still in the git history: the exclusion was derived from
$q=4$ and committed before the first odd-$q$ cell was measured. But it was weaker than the evidence
warranted. **An on-grid arm is a prediction of a flat arm, so $q=2$ and $q=4$ are evidence for the
model, not cases to be excused.** We had a law that excluded its exceptions where one that explains
them was available, and we only found it because we went looking for whether a classification would
survive re-estimating one of its inputs.

*Recorded as a caveat rather than smoothed over:* $q=2$'s spread of $17.6$ is driven by a single
replicate at $68.0$; the other four span $3.1$ points, which is the incommensurate noise level and
exactly what an on-grid arm should show. And $250$/s ($q=1$) gives $58.6$ where the width is $100$,
with $500$/s showing one replicate at $18.0$ — a run at a single phase cannot produce either. A
nominal exact multiple is only $q=1$ if the pacing is exact for the whole run, and over three minutes
it is not.

#### chain18 block C interim (12:38Z): the sign channel catches its first genuine negatives

The OMB **Redis-driver** arm produced the campaign's first negative samples: six, across two
cells (`r300_rep1`: 5, `r500_rep3`: 1), **every one exactly $-1000\,\mu$s** — one tick, the
minimum the quantum can express, never more. The driver-side clock record over the affected
windows is smooth (residual $0.000$ ppm, offset gliding $1.7\,\mu$s/min), so a per-minute
chrony event does not explain them. Both stamps are framework-side on one host, so the candidate
mechanism is sub-millisecond cross-thread/vCPU realtime-clock skew in the virtualised guest —
micro-scale Mode-A inversions whose apparent magnitude quantisation amplifies to a full tick.

**What this does and does not change.** The withdrawal stands and sharpens: the original claim
was that OMB's $\sim$6,000 discards per run under load were causality violations; the measured
reality is 6 negatives in $\sim$8.6M discards, sub-tick deletion overwhelmingly, genuine
inversion at the parts-per-million level. The "not one negative" sentences must be scoped to the
Kafka-driver corpus (which remains at zero), and the Redis-driver catch becomes a finding: the
guard absorbs real causality violations and sub-tick deletions into one indistinguishable
counter, which no output of the benchmark separates. Numbers and text update when block C's
counts are final; the gate will enforce the scoped claim (Kafka corpus $= 0$; Redis corpus
$=$ the documented count with magnitude $-1000\,\mu$s).

Pre-registered: *"If it lands near 33% the governing variable is q and not the rate. If it lands
near 50% like the incommensurate rates, or anywhere off the thirds grid, then q=3 at 300 msg/s was
a property of that rate and quantisation does not generalise."*

Measured at $600$/s ($1.667$ ms $= 5/3$, the same $q=3$ at half the interval of $300$/s):
$33.97$, $34.29$, $34.90$, $66.67$ — spread $32.7$ against a cell width of $33.3$. Three replicates
on the lower branch of the $\{1/3, 2/3\}$ grid and one at $66.67$, which is $2/3$ to two decimal
places. $300$/s had landed $34.86$–$41.13$ with one at $65.35$. Two rates an octave apart produce
the same two-point set because they share a denominator: **the governing variable is $q$, and the
rate that carries it is irrelevant.** Verdict: QUANTISED, $9$ of $9$ arms.

A fifth replicate ran and is excluded by rule: its JVM ended at the result-JSON write without the
shutdown hook printing the authoritative totals (`valid=0`, `none_in_log` in the ledger). Its
periodic counters sat near $67\%$ mid-run — the upper branch again — but periodic lines are
quantised and non-authoritative, so it contributes nothing. The arm stands at $n=4$ with both
branches realised, above the power threshold the analyser enforces.

#### The general model, and chain17 — pre-registered before any of its cells ran

The Family-B laws are unified in `docs/general_model.md`: retention is the occupancy of an arc of
width $\theta = T_{\mathrm{true}}/\tau$ by the orbit of the rotation
$\varphi \mapsto \varphi + \Delta \bmod \tau$. Rational $\Delta/\tau = p/q$ gives a $q$-point
orbit — a run retains $\lfloor q\theta\rfloor/q$ or $\lceil q\theta\rceil/q$ with
$P(\text{upper}) = \operatorname{frac}(q\theta)$ — and the continuous law B1 is the *expectation*
of that at every $q$, not only its large-$q$ limit. Checked retrospectively against all $39$
commensurate replicates: pooled mean retention $49.9\%$ against a weighted $\theta$ of $49.0\%$,
and no arm rejects the branch binomial. Pacing drift is the third regime: a branch flips mid-run
once $N\varepsilon\Delta$ spans a grid cell ($\varepsilon^* \approx 1/(pN)$, a few ppm at $q=1$),
which is where the $41.4$, $18.0$ and $46.6$ intermediates live.

Literature: Weyl equidistribution and the three-distance theorem carry the mathematics; Schuchman's
condition from dither theory is the design rule our recommendation reduces to; coordinated
omission stays the nearest benchmarking relative. We find no prior application of orbit occupancy
to benchmark sample retention.

**Interim, recorded at arm completion (19:38Z): P2's falsifier fired.** The $1250$/s arm ($q=5$,
the first with $p<q$) came out $40.66$, $40.90$, $41.28$, $42.00$, $48.26$ — spread $7.6$, which
is **flat** where P2 said full with branches $\{40, 60\}$. By the pre-registered letter, P2
failed, and the record keeps it that way. The shape of the failure points at an auxiliary
assumption rather than the grid: four replicates hug the $2/5$ point within $1.3$ points (tighter
than any incommensurate arm's scatter), and P2 was computed from the *pooled* $\theta = 0.495$
while our own measured $\theta$-trend extrapolates to $\approx 0.44$ at $1250$/s — under which
$\operatorname{frac}(q\theta) = 0.20$ predicts exactly the observed pinning. But no incommensurate
arm exists above $889$/s, so that extrapolation is unmeasured. **chain17b** (queued behind
chain17, readings recorded in its header before it runs) measures $\theta$ at $1053$ and $1219$/s:
$\theta \gtrsim 47\%$ means P2 genuinely missed and the model loses the point; $\theta \approx
44\%$ means the trend holds and the miss was the extrapolation; $\theta \approx 41$–$42\%$ makes
the $1250$/s arm degenerate and uninformative either way.

**Interim, recorded at arm completion (20:28Z): P3's falsifier fired too — and its shape names
the missing term.** The $700$/s arm ($q=7$): $44.18$, $45.62$, $48.89$, $49.77$, $50.65$ — spread
$6.5$ against a half-width of $7.15$, flat where P3 said full. Unlike P2's pinning, these values
sit *mid-cell*, smeared toward $\theta$. Looking back across every commensurate arm with this in
hand: **every replicate in the design is displaced from its grid point toward $\theta$, by amounts
that grow with $q$.** The model's own drift term says why: phase walked per run is
$\varepsilon T$ independent of rate, so grid cells crossed per run is
$\varepsilon T q/\tau \propto q$ — at $5$ ppm, $\approx 0.9$ cells at $q{=}1$, $2.7$ at $q{=}3$,
$6.3$ at $q{=}7$. A $q=7$ run averages over $\sim 6$ branch segments and the quantised structure
washes toward the continuum. The quantised and continuous regimes are joined by a drift-set
crossover, and $700$/s sits at it ($875$/s, same $q$, spread $10.7$, is marginal).

**Recorded at 20:35Z, before the $900$/s arm completes (~35 min out): the three accounts predict
three different outcomes for it.**

| account | prediction for $900$/s ($q=9$, $\theta_{\mathrm{local}} = 46.7\%$) |
|---|---|
| class model, pooled $\theta{=}.495$ (the registered P4) | full: spread ${\approx}11.1$, branches $\{44.4, 55.6\}$ |
| class model, rate-local $\theta$ | flat, **pinned on the $4/9 = 44.4$ grid point** |
| drift crossover (this note) | flat-ish, spread $\lesssim 5$, **clustered at $\theta \approx 46.7$, off-grid** |

The discriminator is *where* the cluster sits: $44.4$ versus $46.7$, against replicate noise of
$1$–$3$. Whichever wins is recorded; the other two lose their point.

**Outcome (21:09Z): no account wins cleanly, and the separation is itself the finding.** The arm:
$44.53$, $47.07$, $47.38$, $49.41$, $51.46$ — spread $6.9$, mean $47.97$. The registered P4
passes the binary class test on its letter ($6.9 > 5.56$) while missing its substance: the upper
branch at $55.6$ never appears. Rate-local pinning at $44.4$ is refuted outright (mean $3.5$
away). The drift account is closest — mean $1.29$ from $\theta_{\mathrm{local}}$, no grid
structure — but its spread bound ($\lesssim 5$) was exceeded. We note the binary flat/full test
gave opposite calls to $700$/s ($6.5 <$ half-width $7.15$: flat) and $900$/s ($6.9 >$ half-width
$5.56$: full) on nearly identical spreads: the classification is fragile precisely at the
crossover, which is evidence the crossover is where these arms live.

A further datum against the linear $\theta$ trend: the $700$ and $900$/s means are $47.82$ and
$47.97$ — flat near $48$ where the trend says they should differ by $1.5$. If $\theta$ plateaus
at $\approx 48$ above $700$/s, then $1250$/s's cluster at $41$ is six points *below* continuous
and P2's arm becomes grid evidence after all. chain17b's direct measurement at $1053$ and $1219$/s
decides this without extrapolation.

**Where Block B leaves the model:** the quantised→continuous crossover is real and sits at
$q \approx 5$–$7$ for three-minute runs, matching cells-crossed $\propto q$. Block E's duration
sweep is now the direct manipulation of that crossover — at $1$ minute the $q{=}1$ arms should
purify, at $10$ minutes smear — and it was pre-registered as P5 before any of this was known.

#### Block C interim (21:52Z): the crossover moves between passes, and P1's premise fails with it

The fresh $300$/s arm: $34.12$, $51.03$, $51.44$, $55.53$, $55.93$ — one replicate on the lower
branch, **four mid-cell**, where the morning's pass at the identical configuration put all five
branch-adjacent ($34.86$–$41.13$, $65.35$). Same $q$, same rate, hours apart, different regime:
whatever sets the phase walk varies **between runs and between passes**, not only with $q$.

**Consequence for P1, recorded rather than fudged:** the registered branch-count binomial
presupposes branch-classifiable replicates. A value at $51.44$ in a $\{33.3, 66.7\}$ grid belongs
to no branch, so the classification the test needs does not exist for this arm. P1 is therefore
**not evaluable as registered** on the pooled $q=3$ data. An informal pooled binomial computed
before this was recognised (classifying $>50$ as upper) is discarded, not reported — it would
count mid-cell smear as branch membership.

**And then the fresh $625$/s arm contradicted the global-walk account (22:25Z).** Forty minutes
after $300$/s smeared, $q=5$ at $625$/s came out *cleanly bimodal on its grid*: $41.07$, $41.96$
against the $40$ branch; $57.02$, $59.05$, $60.04$ against the $60$ — spread $19.0$ of a possible
$20$, tighter on the branches than the morning's pass. If the evening's phase walk were a shared
environmental drift, the higher $q$ should smear *more*, not hold. The walk therefore varies
per-run or couples to the arm in a way none of the three accounts predicts. What survives every
observation so far is only the weaker, still-falsifiable statement: **when replicates leave the
grid they move toward $\theta$, and the propensity to leave is not a function of $q$ alone.** The
chrony log covers the $625$/s arm's tail and everything after (from 22:02Z); the smeared $300$/s
arm predates it.

#### Block D first half (23:07Z): P6a partially fired, and the arms lined up name the numerator

$300$/s at $32$ KB: $62.06$, $69.17$, $69.19$, $69.23$, $75.69$. Flat as predicted (spread $13.6$
against a half-width of $16.7$) — but pinned at $69.2$, not $66.67$: three replicates agreeing to
$0.06$ points, $2.5$ off the grid vertex, displaced toward $\theta(32\text{K}) \approx 0.70$. The
registered falsifier ("centres off $66.7$") fires on the letter; the displacement-toward-$\theta$
signature is the same one every arm shows.

**Recorded at 23:15Z, before Block E runs: the smearing tracks $p$, not $q$.** Across all eleven
commensurate arms, every arm that smeared mid-cell has $p = 10$ ($300 = 10/3$, $700 = 10/7$,
$900 = 10/9$) and no arm with $p \le 8$ smeared ($1000, 500, 250, 600, 625, 800, 875, 1250$ all
hold their grids, with displacement growing mildly in $p$). Mechanism: per-send pacer jitter
proportional to the sleep interval gives jitter in grid-cell units $= \text{slop} \times p$,
since $\Delta / (\tau/q) = p$ identically. This **supersedes the cells-crossed-$\propto q$ walk
account** of 20:35Z, which cannot explain $625$/s ($q=5$) holding cleanly while $300$/s ($q=3$)
smeared the same evening.

**Block E is the discriminator, and the two accounts disagree in direction.** At $500$/s
($p=2$, $q=1$):
- *walk account (= registered P5):* $1$-minute runs purify, $10$-minute runs smear
  ($\sim 3$ cells crossed);
- *jitter account (this note):* both durations hold near-pure branches $\{0, 100\}$ — the jitter
  is per-send and duration-independent, and $p=2$ is small.

If duration moves the intermediates, the walk survives and P5 stands; if duration does nothing
and branches stay pure, P5 is falsified and the numerator law takes its place. For the $64$ KB arm
(running now): the class model says full $\{66.7, 100\}$ with $P(\text{upper}) = 0.56$; the jitter
account allows mid-heavy displacement toward $\theta(64\text{K}) \approx 0.85$ — overlapping
ranges, so it discriminates only if cleanly bimodal on the grid points.

**Block D complete (23:49Z): P6's central contrast confirmed.** The $64$ KB arm: $73.06$,
$83.80$, $94.87$, $96.83$, $99.78$ — spread $26.7$ against a half-width of $16.7$, **full**, with
the upper vertex hit at $99.78$. The registered flat$\to$full flip at fixed rate and $q$ —
$\operatorname{frac}(q\theta)$ moving $0.055 \to 0.56$ — landed on both halves: spread $13.6$
pinned at $32$ KB, $26.7$ freed at $64$ KB. Payload moves $\theta$; $\theta$'s position in the
grid cell decides flat or full; nothing else changed. The letter-level residuals (the $2.4$-point
pin displacement at $32$ KB; the $64$ KB lower cluster dressed to $73$–$84$) are the $p=10$
displacement-toward-$\theta$ that every arm shows. P6 stands as the model's cleanest surviving
prediction, delivered through the noisiest pacing regime of the campaign.

**The system clock is exonerated.** `chronyc tracking` on the driver: residual frequency
$+0.013$ ppm, skew $0.039$ ppm — the disciplined clock walks $\sim 7\,\mu$s over a three-minute
run, two orders of magnitude below the $\sim 180\,\mu$s of within-run phase spread the smeared
arm implies. The live suspect for $\varepsilon$ is the producer's pacing loop itself (JVM timer
and GC behaviour), which nothing yet measures per run. From 22:02Z a logger records the chrony
state each minute (`chrony_freq_logger.sh`, output inside the backed-up results tree) so every
remaining cell joins to the clock record; the pacing-loop contribution remains open and is the
right target for a dedicated instrument if the duration sweep does not settle it.

**chain17** (55 cells, launched 17:16Z 2026-07-27) repeats the one defected cell, fills every arm
to $n\ge5$, and tests six pre-registered predictions — P1 branch binomial at pooled $q{=}3$;
P2/P3 second rates for $q{=}5$ (1250/s, the first arm with $p<q$) and $q{=}7$ (700/s); P4 that
$q{=}9$ (900/s) *discriminates* under the class test where the superseded median test said it
could not; P5 the drift crossover under a duration sweep; P6 the payload$\times q$ interaction at
$300$/s — $32$ KB pins the arm flat at $66.7\%$ ($\operatorname{frac}(q\theta)=0.055$), $64$ KB
frees it to the full $\{66.7, 100\}$ spread ($\operatorname{frac}=0.56$). Falsifiers for each are
stated in `docs/general_model.md` before any cell ran.


---

## Response to the referee report (internal TPDS/TC-standard review)

> Was `docs/referee_response_letter.md`.

This review was held internally before submission; the paper had not been submitted to any
journal, and the source report is not public. Every major concern, minor comment and
question, with the action taken and where the evidence lives. Items marked *(chain18)* draw on
the referee campaign `reproducibility/campaign_logs/omb_chain18.sh`.

### Major concerns

**M1 — generality beyond one benchmark/driver/runtime.** Done, both forms the report named.
(a) *Strongest*: `cloud/campaigns/guard_harness.py` — the pattern in ~200 lines of Python, no
JVM, guard verbatim, sign counted, pacer jitter recorded per send. Same-host arms reproduce the
grid: q=1 all-or-nothing with both branches (0.00/0.02/0.02/100.00), q=3 on the {0, 1/3}
vertices as θ_py ≈ 0.30 orders, incommensurate stable. Zero negatives. *(chain18 A)*
(b) *Cheapest*: OMB's Redis driver through the same framework guard (`DRIVER=redis` in
`omb_discard_count.sh`). *(chain18 C)* Manuscript: new `sec:generality`; abstract updated.

**M2 — the distributed case.** Three parts. (a) The cross-host *pattern* is now measured: the
harness with producer and consumer on different hosts spans two disciplined clocks — the first
cross-clock guard data in the study, sign counted. *(chain18 B)* (b) OMB's own distributed mode:
three further attempts with version + full logs + failure signature per attempt, archived in
`docs/results/external/dist_diag/`, summarised in supplement S4. *(chain18 E)* (c) Upstream
issue drafted (`docs/omb_distributed_issue.md`); filing is the author's action and it is marked
not-filed.

**M3 — post-hoc vs confirmed.** The kernel, numerator-census and mobility material moved out of
the results line into `sec:extopen` ("Open questions raised by the campaign"), removed from
contributions; the Q4 residual analysis (which *cuts against* our kernel account: negative
Spearman, upper-branch deficit) is reported there. The pacer is now instrumented in the harness
(M3's option (a)) — per-run jitter percentiles in `harness_results.csv`.

**M4 — the missing inference.** `scripts/grid_membership_test.py`: pre-specified vertex-distance
statistic, Monte-Carlo continuum null from measured θ_local and incommensurate σ, one-sided
p-values; exact Clopper–Pearson branch weights where classifiable; per-arm residuals for Q4.
Result: 9 of 10 powered arms reject the continuum (7 at the MC floor), degenerate arms reported
as undecidable. Manuscript: `sec:extinference`; output `docs/results/external/grid_membership.csv`.

**M5 — tail-index documentation.** `fit_tail_index.uncertainty()`: the estimator named
(four-point log-log OLS, not Hill), parametric bootstrap over per-level binomial error, and
leave-one-out. α = 0.339, 95% CI [0.309, 0.372], LOO [0.330, 0.359]; the no-finite-mean sentence
is gated on the CI staying below 1 (a test enforces the gate on synthetic α above and below 1).
Manuscript: the estimator paragraph follows Eq. (tailindex).

**M6 — length and structure.** The external study is a top-level section; `supplement.tex`
(compiles separately, marked not part of the main submission) holds S1 (provenance episode,
92→14 lines in main), S2 (load-axis post-mortem), S3 (ledger schema), S4 (distributed
diagnostics); `docs/supplement_index.md` records every move. Abstract cut 529→~430 words.
Remaining gap stated honestly: the main text is still above IEEE length and further compression
is scheduled; the mechanism (supplement + index) is in place and the deepest single cuts
(provenance, load-axis, meta-commentary) are made.

**M7 — regime mobility under control.** A/B/A/B interleaving of the two arms chain17 observed
hours apart — (300, 625) × 4 pairs within one session. *(chain18 D)* Until it lands, the
mobility claim is already demoted to `sec:extopen` and flagged epoch-confounded.

### Minor comments

1. Abstract: τ bound at first use; trimmed; "costs one line" → "is one line". Done.
2. Keywords reordered, measurement validity first. Done.
3. Contributions meta-commentary removed. Done.
4. §2.1 already carries "to our knowledge". No change needed.
5. Near-duplicate sentence: single occurrence verified. No change needed.
6. θ-plateau: replicate ranges added; "two arms of four replicates" stated. Done.
7. Duration sweep: the walk account's own quantitative reading gives P ≤ (1/3)³ ≈ 0.04 for the
   observed 0/3; stated in text. Done.
8. Table 9 caption states *why* calls are invariant (half-width scaling). Done.
9. 889/s row marked already-in-lowest-terms (†). Done.
10. Colloquialism replaced. Done.
11. Chrony log window stated in Method ("from 22:02 UTC on the final night"). Done.
12. Ledger schema in supplement S3. Done.
13. Payload-flip two-panel figure (`fig:payloadflip`, `docs/results/figures/payload_flip.pdf`). Done.
14. External study promoted to its own section. Done.

### Questions

**Q1** (non-JVM grid): yes — chain18 A; see M1(a).
**Q2** (distributed versions, upstream): versions + logs archived per attempt (chain18 E);
issue text drafted, not filed — author's action.
**Q3** (quantitative displacement prediction): does not yet exist; stated as such in
`sec:extopen`, with the harness's jitter statistic named as where one would be built.
**Q4** (E[ret]=θ residuals vs p): computed in `grid_membership_test.py`; Spearman −0.8 (sign
driven by q=1 branch sampling); q≥3 residuals uniformly negative → branch suppression, not
displacement scaling. Reported in `sec:extopen`.
**Q5** (0.41 ms on audited runs; own instrument): stated in text — every run audit-surviving,
microsecond single-clock stamps, so neither failure mode touches that instrument.
**Q6** (tail-index CI): see M5.


---

## Response to internal review — TPDS standard, round 1

> Was `docs/response_to_referee_tpds.md`.

> **Internal review.** The reports answered below came from reviews held inside the project,
> before any journal submission, to test the manuscript against TPDS standards. The reports
> themselves are not public. The paper has not been submitted to IEEE TPDS; no text here
> originates from, or is addressed to, any journal or its reviewers.

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths* (title shortened per your minor 1).

We thank the reviewer for a report that improved not only the manuscript but the
analysis behind it: two of your requests (M4b, M5) sent us back to the pipeline and
surfaced things we are glad to have found. Every point is addressed below. The revised
paper remains 16 pages with the three requested exhibits now in the main text; the entire
revision is artefact-verified (2,120 tests, all green).

### Major points

**M1 — exhibits in the main text.** Done, all three: the two-panel model figure now sits
beside Eqs. (1)–(2) (`fig:model`); a compact mechanism table covering the real-time-priority
collapse (39×/54× at utilisation matched to 0.001) and the geometry contrast (2.07×/2.05×
at ρ = 0.7531 in all four arms) sits in §VIII-C (`tab:mechanism`); and the payload
on/off-vertex figure now illustrates the campaign's confirmed prediction in §VII-F
(`fig:payloadflip`). The compensating prose cuts are the ones you named — §VII-B's
corroboration paragraph (to S7), §IX-A's rules (tightened by roughly a third), and parts
of §II — plus stub-and-move compressions recorded in `docs/supplement_index.md`. The
paper stays at 16 pages.

**M2 — fit to TPDS.** A remit paragraph now closes the introduction's opening run, in
substantially your words: cross-process and cross-host timestamping is the measurement
substrate of every distributed-systems latency claim, and we show that substrate failing
structurally at the scales the field now publishes, on the community's shared benchmark
and across two disciplined hosts.

**M3 — self-containedness.** The fit ladder now names its rivals in the main text
(two-state 0.9905 against 0.9811 and 0.8863 at equal parameters, 0.9982 with σ frozen)
and has one home (S32). The double pointers you flagged (S33/S18, S12/S25) are split so
each claim has exactly one home. Every "Supported"/"withdrawn" verdict was audited for
its deciding numbers; with `tab:mechanism` promoted, the two verdicts that leaned
hardest on S25 now lean on a main-text table.

**M4 — the tail index.** We did (b) and (c), and (b) turned out to matter more than we
expected. A new committed script (`scripts/traced_tail_slope.py`) computes the traced
per-wakeup survival's log–log slope from the E-A9 bpftrace histogram: over the co-located
decade (0.25–2 ms) the windowed index is **0.332 — indistinguishable from the fitted
0.339** — and it **rises past 4 beyond 4 ms**. The traced distribution is therefore not
scale-free, so the manuscript now states that Eq. (6) is an *effective law of the payload
span, fitted, not derived, and not a constant of the machine*, and we withdraw the
earlier draft's unconditional infinite-moment reading — your (c), which our own new
evidence made mandatory rather than merely prudent. The steepening also explains the
1.66× level over-prediction in direction (a span-calibrated power law must sit above a
steepening curve), and the text notes the length-bias caveat: the traced quantity is
per-wakeup delay, the residual the model's S denotes is one power heavier, so the
comparison is a consistency check, not an identity. (a) was not pursued: the testbed was
decommissioned and imaged after the campaigns closed, and (b)+(c) answer the concern
without new hardware.

**M5 — the shift's selection bound.** Your instinct here was better than you knew.
Rebuilding the analysis exposed that the powered transport aggregates had been computed
*before* the audit verdicts were wired into the cloud index — the TOST had consumed all
629 runs, condemned included, and the paper's "every run is audit-surviving" sentence in
S6 was false for that aggregation. We have repaired this end to end: a committed script
(`scripts/powered_gate_sensitivity.py`) applies the gate, and the gated artefacts are now
the primary ones everywhere (paper, supplement tables, tests). The findings: (i) the gate
moves the Hodges–Lehmann shift by at most **0.003 ms** (0.017 ms in the replication), so
0.41 ms stands; (ii) Redis retention is 8/15, 59/135, 61/165 per cell — **below one half
in two cells**, where the E1-style imputation defence cannot bind; unlike E1 the
condemned values survive, so observation replaces bounding, and §VIII-D now says so;
(iii) flipping the shift's sign would require essentially every condemned Redis run to
have measured ≥ 0.55 ms, five times the 0.10–0.12 ms their observed medians centre on.
§VIII-D states the campaign's retention (your general rule, which this section had been
violating), and the per-cell sensitivity table is S34. The powered sample-size figure
changed from 127 to 125 matched events per run under the gate.

**M6 — the distributed-mode gap.** We took your scoping branch: the abstract's deletion
claims now read "instrumented embedded-mode runs", and §VII's opening scopes the audit
("in embedded mode throughout") with a pointer to the section that bounds what that
leaves open. The upstream report is drafted (text below); the author will file it, and we
will cite the issue number in the final files. We did not attempt the vendor forks: the
testbed is decommissioned, and the scoping branch you offered covers the claim.

**M7 — preprints marked, neighbourhood anchored.** All four (Sharma, Chandrasekar &
Kramberger, Swami & Chougule, Mohammad) are marked as preprints at first citation. All
five of your suggested anchors are now engaged: Treadmill (§II-A, as the closest
peer-reviewed methodology kin), DTP and Sundial (§IX-B's better-clock ordering), Uta et
al. (the run-to-run instability bracket), and Bailey (same bracket, as the tradition's
ancestor).

### Minor points

1. **Title** shortened to end at "…Sub-Millisecond Paths."
2. **Kernel/scheduler**: §IV-A now states Ubuntu 22.04 on kernel `6.8.0-1057-oracle`
   (EEVDF) — recorded in every run's committed metadata — and Threats notes the constants
   are those of one EEVDF-era kernel, with Lozi et al. scoped to CFS. Your CFS presumption
   was reasonable and wrong in an interesting way; see Q1.
3. "(Mann–Whitney)" added at the first p-value.
4. "boring" → "predetermined."
5. "In plain terms:" reduced to exactly the two instances you endorsed (§VII-B, §VII-G(c));
   a test now pins the count at two.
6. Eq. (3)'s label is now "(uniform phases)", defined at point of use.
7. Eq. (4)'s arrow replaced by "=" with "as runs lengthen" in the sentence.
8. KIP-489 cited beside the WorkerStats guard, with its "reported as NaN" wording — we
   verified the exact sentence against the KIP during this revision.
9. AWS ClockBound and Meta's PTP deployment now close §IX-B as the industrial form of
   "publish the synchronisation state."
10. "Attractors" unpacked in §VII-F ("replicates pin near the grid's vertices rather than
    scattering").
11. StatsBomb licence clause added to Artefact Availability.
12. Wayback snapshots recorded for the two grey links that have them (the GitHub
    repository has no snapshot; its name and pinned commit are its durable identifiers).
13. An Acknowledgments section names the compute substrate (Oracle Cloud Infrastructure);
    biography, photo, and any funding statement will accompany the final files.

### Typography

Eq. (6)'s overflow was repaired on receipt of the report; the S29 double-pointer is
varied; "artefact gate" is now "a check in the released analysis code"; the abstract
names the mode of the instrumented runs; the Testbed A/B run-in labels are italic as
paragraph labels with in-text mentions roman throughout.

### Questions

**Q1.** Kernel `6.8.0-1057-oracle` (Ubuntu 22.04 HWE), EEVDF scheduler — recorded in
every run's `host_platform` metadata. Real-time priority was applied as `chrt -f 80`
wrapping only the stamping (producer/consumer Python) processes; the manipulation was
verified live during the elevated arm by sampling scheduling classes: 20 python3
processes at `SCHED_FIFO`, their sudo/bash parents at `SCHED_OTHER`
(`docs/results/depth/ea5/sched_verification.txt`).

**Q2.** OMB's coordinated-omission correction (issue #247, PR #248) was merged on
2022-04-07, four years before the audited commit `5b1fa70`. It instruments the
*generator* side (a scheduling-aware rate limiter and a producer-delay metric) and leaves
the receive-side end-to-end subtraction and positivity guard untouched, so it does not
interact with retention: retention is decided entirely at the recording guard. Our
harness additionally measures the pacer's own per-send jitter directly (67–69 µs at p90),
bounding coordinated-omission exposure in our runs independently of upstream fixes.

**Q3.** Not recorded, and we say so rather than guess: the per-run metadata captures
kernel, chrony state (per-minute, residual 0.000 ppm on the run in question) and host
platform, but not `/sys/.../current_clocksource`. The VM boot volumes are archived, so
the check is recoverable; until then the virtualised-clock account remains flagged as
candidate, not conclusion — which is how the manuscript already stated it.

**Q4.** Yes, and it is now shown rather than asserted: gate on/off moves the shift by at
most 0.003 ms (0.017 ms in the replication), and the sign flips only if essentially every
condemned Redis run measured ≥ 0.55 ms against observed condemned medians of
0.10–0.12 ms (max 0.72 ms). Artefact: `docs/results/transport_rt*/gate_sensitivity.csv`;
see M5 for the pipeline defect this question exposed.

**Q5.** Confirmed, and now at condition level with a committed artefact
(`scripts/threshold_condition_sweep.py` →
`docs/results/integrity_windows/first_result_threshold_sweep.csv`): across thresholds
0–20%, none of the six first-result cells becomes fully usable at any point; even at the
permissive 20% extreme the best cell passes 23 of 30 runs. §VI-B now cites this artefact,
and a test fails the build if any threshold in the range ever resurrects a first-result
cell.

### Draft upstream report (to be filed by the author against openmessaging/benchmark)

> **Title:** WorkerStats positivity guard silently discards samples with no counter;
> retention is unrecoverable from a completed run
>
> At commit 5b1fa70, `WorkerStats.java:95` admits a sample to the end-to-end histogram
> only `if (endToEndLatencyMicros > 0)`. The message is still counted as received, but a
> non-positive latency is dropped and no counter records how many. Because
> `System.currentTimeMillis()` has millisecond resolution, any delivery faster than 1 ms
> differences to exactly zero and is dropped by the same branch: on co-located paths this
> is a large share of all samples, and across 223 instrumented embedded-mode runs we
> measured the reported distribution being computed from between 0.36% and 100% of the
> samples taken — same reported median either way. Suggested minimal fix: count and
> report discards (zero/negative separately, since a negative difference is evidence of
> clock trouble that this guard currently hides — cf. KIP-489's NaN convention). We are
> happy to contribute the counter patch we used for instrumentation; measurement write-up
> and per-run data: [Zenodo DOI 10.5281/zenodo.21836305 (code and write-up),
> 10.5281/zenodo.21836326 (measurement dataset)].

---
*Every change above is enforced by the repository's consistency suite (new class
`TestRefereeRoundOne` plus `tests/unit/test_referee_pipeline.py`), so none of these
answers can silently rot: the sensitivity numbers, the traced slopes, the threshold
sweep, the exhibit placement, the preprint markers and the register count are all
recomputed from committed artefacts on every run.*

---

## Round-2 addendum: the eleven welcomed minors (simulated round 2, same internal process)

1. **Page-15 whitespace** — gone: the flush-bottom stretch before the Conclusion is
   absorbed; both columns of p.15 now fill evenly (verified visually on the final build).
2. **Reference [3] URL typography** — a `UrlBreaks` declaration now lets bibliography
   URLs break at slashes, hyphens and dots; [3] wraps inside the margins and the archived
   snapshot is recorded by timestamp and ID only.
3. **Figure legibility** — Figure 1 was *regenerated* at 1.5x internal font sizes (a new
   `--font-scale` option in the committed figure script, with a test) and is shown at
   0.8 column width; Figure 2 is restored to full column width, per the option you
   offered. Both are comfortably legible at print size on the final build.
4. **Table I** — the column heads now name the arms per block ("ordinary / real-time";
   "concentrated / spread").
5. **§IX-A citation placement** — reads "Better instruments exist [19]; whatever the
   instrument, check its output against causality…".
6. **§IX-D** — comma added after "network."
7. **§II-D** — the forward reference now reads "Table I, Section VIII-C."
8. **Traced-slope scope** — §VIII-C(g) now states "one traced arm of one campaign — the
   replication kept no raw histogram."
9. **Two-regime symmetry** — §VI-B closes its imputation bound with "where rejected
   values survive, observation replaces this bound (Section VIII-D)."
10. **Artefact Availability** — the block flows as one paragraph; the URL-wrap artefact
    is resolved by the same `UrlBreaks` fix as item 2.
11. **Final files** — biography, photo, funding statement and the filed upstream issue
    number remain with the author, as you noted.

The paper remains exactly 16 pages; the full suite (2,121 tests including the new
figure-script test) is green.


---

## Response to internal review — IEEE Transactions on Computers standard, round 1

> Was `docs/response_to_referee_tc.md`.

> **Internal review.** The report answered below came from a review held inside the project,
> before any journal submission, to test the manuscript against IEEE TC's standards. The
> report itself is not public. The paper has not been submitted to IEEE Transactions on
> Computers; no text here originates from, or is addressed to, any journal or its reviewers.

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths*.

Verdict returned: **needs major revisions**, with acceptance expected on resubmission.

The report's most useful demand was M8, and it did not do what either side expected. Asked
to replace an eyeballed slope with an estimate carrying an interval, we found the estimate
refuted the claim it was meant to support. That withdrawal is the largest change in this
revision. Three of the ten items (M2, M3, M8) were fixed in the analysis pipeline rather
than in prose, on the principle that a number which reaches the page without passing
through a script is the one that goes wrong — which is, after all, this paper's subject.

Build after revision: 10 pages against TC's 10–12 budget, exactly 45 references against a
cap of 45, a 195-word abstract against a 100–200 range, 0 errors, 0 undefined references,
0 overfull boxes, and a 41-page supplement. All four gates green; 2,239 tests pass, 35
skipped with written reasons, 0 failing.

### Major points

**M1 — Sharma et al. mischaracterised.** Corrected. We had written that they "see
violations from 3 ms"; their abstract says no violations are observed up to 3 ms, with
clear violations by 5 ms. The sentence now reports their null result as a null result, and
"a threshold below which skew may be ignored" — a paraphrase they did not write — is now
"a threshold in skew". A new pin, `test_their_skew_result_is_reported_as_they_reported_it`,
fails if either drifts back.

**M1-bis — the point we were leaving on the table.** Taken, and we are grateful for it.
Sharma et al. state that "queueing alone cannot produce negative timing spans or cause
timestamps to imply reversed causal orderings". Mode A is a direct empirical
counter-example to that sentence, and describing our result as merely *qualifying* their
reading undersold it. The paragraph now quotes the premise and answers it: inversion rates
near 23% at 88% utilisation with no skew available to blame, and a fiftyfold move in that
rate without touching a clock. We are careful to contradict the premise and not their
measurements, and the test now enforces that scoping.

**M2 — Table II printed uncorrected p-values under a caption claiming correction.** This
was the most embarrassing finding and the fix is structural. You are right on every count:
all ten powered arms reject at raw *p*; the two arms we named as exceptions are the
*unpowered* ones; and the arm that actually fails the Holm correction, 900 msg/s, was
printed as a rejection (raw 0.044, adjusted 0.131).

Rather than retype the table, we removed the opportunity. `stat_intervals.py` gained a
tested `holm()` and a `grid_cells()` reader that derives each verdict from the *corrected*
value, and Table II is now generated into `docs/generated/grid_table.tex` and gated by
`emit_paper_numbers.py --check`. A third verdict, "not resolved", was added because the
data needed one: 900 msg/s is now reported as neither support nor refutation. Your
observation that the suite had no pin on the grid inference was also correct; it has eleven
now.

**M3 — "the 49 runs on an unsaturated path".** You could not reconstruct that denominator
because it does not exist. Replaced with what the artefact supports, which is the stronger
sentence: of 75 instrumented cells whose own summary we captured, 71 report a median of 1.0
or 2.0 ms, and across those the retained fraction runs from 0.36% to 100%. The illustrative
example is better too — two replicates of a *single* cell, same payload, same rate, same
host, kept 431 and 120,434 samples and both reported a median of 1.0 ms. All of it is now
macro-driven from `retention_cells()`.

**M4 — the Redis negatives are not a "candidate" mechanism.** Correct, and thank you for
reading the driver. `RedisBenchmarkConsumer.java` line 72 takes the publish timestamp from
`entry.getID().getTime()`, the stream-entry identifier the Redis *server* assigns on
`XADD`, while the Kafka driver uses a producer-set stamp. The Redis span is therefore a
difference between two millisecond-floored clocks on two hosts, and −1000 µs is the only
negative value that construction can express — which is exactly what the corpus contains,
and also why the Kafka-driver span, floored inside one JVM, never goes negative at all. The
hedge is gone, the driver is cited, and the threats section no longer offers cross-host
skew as the explanation. As you say, this makes the claim stronger rather than weaker.

**M5 — Villain et al. (ISPCS 2012).** Cited, and scoped against explicitly rather than
mentioned. Their finding — that a socket timestamp taken under load "does not respect
causality", with process scheduling named as the cause, measured against a DAG hardware
reference — is Mode A's physical primitive, published in 2012 and measured more precisely
than we measure it. The paper now says so in those words and states what we add: a span
whose endpoints are written by two different threads, a probability law relating the
inversion rate to the interval being measured, and manipulations separating scheduling from
its rivals.

**M6 — the geometry over-claim.** Withdrawn in both places it appeared. "Impossible if the
rate were a function of ρ" is true only of the single-parameter form we ourselves adopted
and pre-registered; multi-server queueing is geometry-dependent at fixed ρ in any textbook.
§II-D's companion claim, that the contrast would be flat under exact work conservation, was
wrong for the same reason and is also gone.

**M7 — missing citations.** All added, with ten citations dropped to hold exactly 45:
Hoefler & Belli (SC'15) and Kalibera & Jones (ISMM'13) for the reporting and rigour
literature; Gregg for `runqlat`, which is our own method; NIST SP 960-12, which is the
right canonical anchor for the paper's unifying claim and which we are glad to have been
pointed at — metrology has carried reaction time and display resolution in one uncertainty
budget for a century, and the paper now concedes that the pairing is not ours. Also RFC
3432 and McCanne & Torek for the dither lineage, OMB PR #398 for the second silent-loss
mode in the same harness, the Redis driver source, and Swami & Sonawane for concurrent
pre-registered measurement work. RFC 2679 replaced by RFC 7679, which obsoletes it.

**M8 — the tail exponent. This one changed a result.** We took the first of your two
options and it destroyed the claim, so we ended up taking both.

`scripts/tail_index_traced.py` (new, 46 tests, 98% branch) estimates the index on the same
551,956-wakeup histogram by grouped-data maximum likelihood with a profile-likelihood
interval, and independently by an exceedance ratio on the exact counters with a Wilson
interval. The exceedance index over 0.5–2 ms is 0.21 (0.20–0.21); grouped maximum
likelihood over the same decade returns 1.19 (1.18–1.20). Two estimators of one quantity
cannot differ sixfold unless the model is wrong, and it is: the per-octave indices over
that window run 1.96 and then 0.03, where a power law would give the same value twice.

The 0.332 we had quoted was ordinary least squares through four nested survival points,
which returns a number whether or not the points lie on a line. Its agreement with the
payload exponent was a coincidence of window and estimator, and we should not have offered
it as an independent confirmation. **Withdrawn.** Equation (7) is demoted to the
supplement, as you suggested, since without the cross-check it stands on four points alone;
the main text keeps the model-free exceedance estimate with its interval and the
qualitative conclusion, which needs no exponent and is what the argument actually used.

The withdrawal took a second claim with it. The supplement's "α below one, so the stall
distribution has neither a finite mean nor a finite variance" had been contradicting the
main text's own withdrawal of the infinite-moment reading since the previous revision. Both
are now recorded in S35.5.

**M9 — "Manuscript submitted to ACM" on a supplement bound for IEEE.** Fixed with
`nonacm`; verified absent from all 41 pages. Your framing was the useful part: not a rule
violation, but precisely what a Computer Society prescreener is told to look for.

**M10 — rendering defects.** Four doubled cross-references ("the main text's the main
text's …"), left by an earlier neutralisation pass, repaired. Figure 1(b)'s title no longer
asserts `P(inv) ∝ T^−0.34`; it states only the qualitative claim the text still supports.

### Minor points

All sixteen were taken. The ones that changed a number rather than a word:

- **7 — name the coefficient and *n*.** Doing so revealed that "+0.075" had come from an
  unstated denominator. On the stated one it is +0.31 (Spearman, *n* = 71). We report it,
  and note it is the sign Equation (4) predicts and far too little to explain a 279-fold
  range. Publish latency across those cells takes only two values, 0.3 and 0.4 ms, which
  makes the point better than the correlation did.
- **11 — the netem numbers need *n*.** Added (medians of the transport component, five
  feeds per arm). Checking them surfaced an arithmetic error the report had not caught:
  batching the acknowledgements cuts the median from 4,138 ms to 103 ms, which is a factor
  of **40**, not 103. The supplement had 40.2 all along.
- **15 — reference hygiene.** Kreps et al. was attributed to NSDI; it is NetDB. Lozi et al.
  gained pages, and the OpenMessaging entry gained an access date.

The rest: the abstract's opening now says "larger than the intervals they report"; the
opening register is "Stated plainly" rather than "In plain terms"; the workload names
StatsBomb open data and its licence; the gate section states that the threshold sweep runs
0–20% with no condition usable anywhere in that range; §III-F names the scripts and says
the tables are generated; the guard's line number sits beside the pull request; the Python
harness is described as independent rather than by its line count; "our first result" is
used consistently; the two-state ratios name what they multiply; the TOST now prints its
result (Hodges–Lehmann 0.408 ms, 90% interval 0.389–0.419, both one-sided nulls rejected at
*p* < 0.001, shift stable across three concurrency levels) instead of asserting equivalence
without a test.

### On the artefact statement

You noted that "the test suite fails if the text and the data disagree" was, before this
round, a stronger claim than the suite. It was — the grid inference had no pin at all. It
now has eleven, the traced tail index has forty-six, and Table II is generated rather than
transcribed. We would rather the claim were true than impressive.


---

## Response to internal review — IEEE Transactions on Computers standard, round 2

> Was `docs/response_to_referee_tc_r2.md`.

> **Internal review.** The report answered below came from a review held inside the project,
> before any journal submission, to test the manuscript against IEEE TC's standards. The
> report itself is not public. The paper has not been submitted to IEEE Transactions on
> Computers; no text here originates from, or is addressed to, any journal or its reviewers.

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths*.

Verdict returned: **needs major revisions**, with acceptance expected on resubmission. All
ten round-1 items were verified closed in the rendered PDF. Nineteen new items (R1–R19),
all addressed below.

The most useful thing this round did was find that **four of its nineteen items were
introduced by round 1's own fixes** — a denominator borrowed from one population and
printed against another, a NIST paraphrase that inverted the source's own uncertainty
budget, an over-read of Villain et al., and a bibliography entry with the wrong author
names. We had corrected those areas and not gated the corrections. Everything in this round
that could be gated now is.

Build after revision: 11 pages against TC's 10–12, exactly 45 references against a cap of
45, a 195-word abstract against 100–200, 0 errors, 0 undefined references, 0 overfull
boxes, and a 41-page supplement. Four gates green; 2,275 tests pass, 35 skipped with
written reasons, 0 failing; 97% branch coverage on the changed scripts.

### The item that changed a result

**R15 — the tail section.** You asked for the goodness-of-fit test that "not a power law"
actually requires, and for the estimators to be credited. Doing both turned a negative
result into the paper's most direct mechanistic evidence, which we had been sitting on
without seeing it.

The bootstrap rejects the power law decisively: *p* < 0.0004 over 2,500 replicates drawn
from the fitted model itself. But the more useful question was the one you asked next —
what shape *do* the data have. The bucket counts are not monotone, so no power law can
describe them. There are three local maxima: a jitter core, a hump in the hundreds of
microseconds, and a **mode at 2–4 ms carrying 10.5% of all wakeups, standing 4.5× above its
lower neighbour**. Above it the survival is light and ordinary — grouped maximum likelihood
gives α = 2.04 (2.00–2.07), a finite variance.

That mode is not arbitrary. On an eight-vCPU instance the EEVDF base slice is
0.75 ms × (1 + ⌊log₂ 8⌋) = 3 ms; run-to-parity holds a woken thread off the CPU until the
incumbent exhausts that slice, and with the high-resolution tick disabled the expiry is
seen at the ordinary tick. **It is the two-state model's preempted state, observed directly
in the trace, at the constant the scheduler is configured with.** We have rewritten
Section V-G around it, retired "heavy tail" from the text and from Figure 1(b), and cited
Virkar & Clauset — whose grouped estimator on log-spaced bins is what we had implemented
without knowing it is theirs, and is the Hill estimator for binned data. As you suggest,
the supplement states that the constants should be read off the image under test rather
than assumed from the kernel version, and reports them as the explanation the mode's
location supports rather than as an independently measured cause.

### Internal correctness

**R1 — the abstract's denominator.** Correct, and this is the worst of them because it is
the most-read sentence. 0.36% is the minimum over the 71 cells whose own summary we
captured; over all 223 runs the minimum is 0.0044%, four samples kept of 90,490. The
abstract now quotes the range against the population it came from, and Section IV-B gives
both figures with the ledger-wide one spelled out.

**R2 — "1.5 million".** A hand-typed round number appearing twice, matching neither
topology. The artefact holds 905,040 one-clock and 905,040 cross-host samples, zero
negatives in each. Both are macros now. In a paper about benchmarks that miscount their own
samples this was the least affordable defect in the manuscript, and we are glad it is gone.

**R3 — the saturation claim.** You are right that a rate ceiling is not an occupancy. The
inversion rate's ceiling is 0.37; the preempted-state probability at saturation is
0.68–0.89. Under Equation 6 an event can be stamped by a preempted thread and still not
invert, whenever the stall is shorter than the interval. The sentence now says that.

**R4 — idle-to-knee growth.** The artefact holds an inversion rate, not a mass beyond one
millisecond. Reworded and macro-backed (×5 core width, ×61 inversion rate).

**R5, R6, R7** — both estimator windows now stated; one offset figure (0.067 ms) used
throughout with the other two sites cross-referencing it; the abstract says "a median on
the millisecond grid" rather than "the same median", since there are two.

### Source characterisation

**R8 — NIST.** Corrected, in the text and in the bibliography note, which was still
carrying the wrong paraphrase after the text was fixed. NIST's worked budget has reaction
time at 230 ms against display resolution at ≈3 ms; reaction time dominates. Their
short-interval remark is that resolution becomes significant against the instrument's
*rated accuracy*, which is what we now say. The pairing itself — both of our failure modes
in one budget — survives and is still the point.

**R9 — Villain et al.** Also corrected. The violation is on FreeBSD's *outgoing* socket
path, which is generated by a loopback copy; it is present under every stress pattern
including none; and scheduling is named as a general host-latency source, not as the cause
of the causality violation. The sentence now reports what they found and what cannot be
bounded, then states what we add. This is the second consecutive round in which this
section has needed a source correction, so we re-read every sentence in it against the
cited text before resubmitting.

**R10, R11, R12 — the bibliography.** The Swami & Sonawane entry had the wrong title and
both first names wrong; it is Akul Swami and Dnyaneshwar Sonawane, with the full
Jetson Orin Nano title. YCSB #41 is Mike Wiederhold, fixed by PR #42 in 0.1.4. Kuperberg
et al. ICPE 2011 is pp. 151–156. Kundel now carries Springer Theses and its DOI. The Redis
driver is no longer its own bibitem — the benchmark is cited once and the file and line
appear in the text, where a reader can act on them. Editorial commentary has been stripped
from the notes throughout; that is also where R8's error had survived.

### Positioning

**R13 — OWAMP.** Taken, and it improves the paper. RFC 4656 has attached a synchronisation
flag and an error estimate to every timestamp since 2006, and requires that a packet
stamped in the future be recorded unaltered rather than dropped. Rule 5 now cites it and
says we are asking for no more than that, applied where brokers and language runtimes
report latency and where nobody does it. A rule with a twenty-year-old standard behind it
is a stronger recommendation than one presented as new.

**R14 — the stream-processing benchmark literature.** A fair hit: the section rested on one
DEBS paper and OMB while the manuscript is positioned against streaming benchmarks. Added
Karimov et al. (ICDE 2018), Van Dongen & Van den Poel (TPDS 2020) and Fruth et al. (TPCTC
2021), with the framing you propose: that community already prescribes one-clock,
outside-SUT measurement — at millisecond resolution, and without checking the sample the
instrument keeps. Van Dongen's "a single Kafka broker to ensure correct latency
measurements" is our one-clock rule arrived at independently, and we say so.

**Reference cap.** Five added, five cut (Kreps, Kleinrock, McCanne & Torek, Swami &
Chougule, and the Redis driver as a separate entry), holding exactly 45. McCanne & Torek
moved to the supplement's fuller dither account rather than being lost.

### Disclosure

**R16 — the tracer.** Both omissions were real and both were already in the artefact tree.
The trace filters to the harness processes, which the text now states, and the campaign ran
the same cell untraced: 0.272 untraced against 0.231 traced, z = 3.6. The prediction is
compared against the traced arm's own rate, so the agreement is between two instruments
observing one machine; the untraced rate is the one to quote for the machine. A paper about
instruments that change what they measure should not have needed to be asked for this.

**R17 — the supplement's review labels.** This is the one we are most grateful for. Nine
sections read "TPDS round 1" and three passages referred to "the TC submission" or "the TC
revision". Read cold that says the manuscript was reviewed at two journals. It has been
reviewed at none — those were internal reviews. Every label
now reads "internal review, round N", and the front matter states explicitly that the
manuscript has not been submitted to or reviewed by any journal, and why the rounds are
recorded at all.

**R18, R19** — Section VI now says it compares on the transport proxy and points at the TTI
equivalence; the rank-correlation sentence has been replaced by the argument that actually
holds, which is that a two-valued predictor cannot account for a 279-fold range whatever
its correlation.

### Figure 1

You did not raise it beyond a minor note, but we triple-checked the diagram and found one
real defect. Panel (a)'s arithmetic verifies against Equations 1 and 2 by both routes
(δ_ack = 2.2, δ_recv = 0.6, T_true = 1.0, Δ = −1.6, T_meas = −0.6), and its causal ordering
is sound. But it drew the acknowledgement and the record arrival as a left-to-right sequence
with no common cause — inviting precisely the causal-chain reading Section III-C exists to
refute. The broker's append and its two branches are now drawn, and the caption says
neither arrival precedes the other.

Panel (b) had been wrong twice in opposite directions: a bell curve in the first version, a
monotone heavy tail in the second, each drawn to a shape the data had not been asked about.
It now shows the running core and the preempted lobe at the scheduler slice, and the caption
labels it schematic with the measured mode's position.

### On the pattern

Three rounds, and each has found at least one number that survived internal review and
failed the first time it was estimated or recomputed with its denominator named. We record
that in supplement S35 because it is the paper's own argument turned on its author: a
statistic that carries no uncertainty, and a number that reaches the page without passing
through a script, are not yet measurements. Every correction from this round is gated.
