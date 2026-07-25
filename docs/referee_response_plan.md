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

**Status:** in progress. Blocked on JDK install; not blocking the other campaigns.

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

**Status:** campaign queued (2/2 in the referee chain).

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

**Status:** local work, in progress.

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
| M1 external validation | decisive | run/audit | **DONE** — OMB audited, §6.7 |
| M3 clean effect size | keystone | run | running (E-B2, d1 of 5) |
| M2 E1 discrepancy | major | run | queued behind E-B2 |
| M4 M/G/1 downgrade | major | analysis | **DONE** — form withdrawn |
| M5 provenance reliance | major | writing | **DONE** — §7.3 inverted |
| M6 sample sizes | major | writing | **DONE** — Table 5 |
| M7 workload justification | major | writing | **DONE** — §3 rewritten |
| Minor: figure `\%` | minor | local | **DONE** |
| Minor: length, caption, "sound" | minor | local | pending |
