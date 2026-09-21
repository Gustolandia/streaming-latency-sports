# How the paper reached version 4

The plans and drafts behind the paper's present shape, in the order they were written.
Superseded as instructions; live as the record of why the paper looks the way it does, and
of what was decided before its evidence existed.

The five-tier stratification policy is in *The v2 plan* below, and
`tests/unit/test_paper_consistency.py` enforces it. The mapping from writing rules to
sections is in *The v4 restructure*, behind `tests/unit/test_writing_standards.py`.

*Fused on 2026-09-21 from 3 documents, each carried over unchanged below.*

> **Two documents that belong in this file are missing.** They were fused here on 21 September
> 2026 and lost in the same operation. Both were working files that had never been committed, so
> when that operation was rolled back, git could only restore what it held; nothing of these two
> survives. What each was:
>
> - `docs/v3_plan.md`, 1,496 lines, started 2026-08-14 — the post-correspondence revision plan,
>   accumulating through the feedback window.
> - `docs/v2_execution_log.md`, 3,676 lines — the working log of the TPDS conversion, including
>   the four references added to the bibliography and the retargeting of the test suite.
>
> Their outcome is not lost, only their reasoning: the v4 restructure below, the deposited
> releases, and the paper itself record what they produced. The script that fused this file now
> refuses to touch any group containing a document git does not hold.

## Contents

- [v2 plan — living document](#v2-plan-living-document) — was `docs/v2_plan.md`, last changed 2026-09-15
- [v4: the restructure](#v4-the-restructure) — was `docs/v4_restructure_plan.md`, last changed 2026-09-08
- [§6.7 rewrite — working draft (revision 2, 2026-07-26 18:30Z)](#6-7-rewrite-working-draft-revision-2-2026-07-26-18-30z) — was `docs/section67_rewrite_draft.md`, last changed 2026-07-26

## v2 plan — living document

> Was `docs/v2_plan.md`.

Status: **collecting feedback**. v1 is submitted to arXiv (in moderation) and archived
(code 10.5281/zenodo.21650032, data 10.5281/zenodo.21650065). This plan accumulates every
change v2 should make, with its source noted. It will be revised as further feedback arrives
(second reviewer pass pending; arXiv readers after announcement) and only then executed.

Reviewer names are kept to first names here; acknowledgements in v2 with permission.
The "referee rounds" referenced below are the project's internal reviews
(see docs/referee_response_letter.md), not journal correspondence.

---

### Stratification policy (governs every section below)

Author's instruction, 2026-08. Every result is assigned a tier; **space, placement and
emphasis are proportional to tier**. Only tiers 1–3 may appear in the abstract. Tiers 4–5
get exactly one sentence in the results (detail may live in the supplement), and no
subsection may be organised around them.

- **Tier 1 — biggest novel original discoveries.** Own the abstract, the introduction's
  first page, and the largest share of results.
- **Tier 2 — medium original discoveries.** Full subsections, no headline billing.
- **Tier 3 — hyper-surprising nulls and contradictions of other papers.** Abstract-eligible;
  reported with full evidence but framed as audit outcomes, not headline discoveries.
- **Tier 4 — confirmations of others' results.** One sentence in results, cite and move on.
- **Tier 5 — other nulls.** One sentence in results; tables/detail to supplement.

**Tie-break rule (author, 2026-08): demote.** If a result might be a null, it is a null;
if a call is borderline between tiers, take the lower. Cleaner paper beats fuller paper.

#### Tier assignment (v1 results → v2 treatment)

| Result | Tier | v2 treatment |
|---|---|---|
| Grid retention law: retention snaps to the q-grid, E[retention]=θ at every q; causal (payload flip pins/frees classes); stack-independent (no-JVM harness reproduces) | 1 | Largest share of results; abstract beat 2. The grid-membership inference (9/10 powered arms reject the continuum null) is folded here as **evidence**, not billed as a separate result |
| One governing ratio (instrument timescale / measured interval) unifying both failure modes | 1 | Title + abstract framing; intro page 1 |
| Sign channel as audit: 41,403 genuine one-tick negatives caught inside the guard, half of one run, absorbed without trace — the two modes meet in one counter | 1 | Abstract beat 3; full subsection |
| Inversion mechanism law P[inversion]=P[stall>T_true], established by manipulation (SCHED_FIFO 7–80×; equal-ρ 2.07×; transport ×77 → rate ÷4.1; unfitted trace within 30%) | 2 | Full subsection; abstract beat 1 keeps its two strongest numbers only |
| Stall tail index α≈0.34 → no finite mean → mean-based counters structurally blind | 2 | Paragraph inside mechanism subsection; one abstract clause |
| Cross-host: retention coupled to clock-sync state (13.4→27.0% drift under sub-tick offset) | 2 | Subsection (feeds better-clock A8) |
| Cross-host zero negatives in 1.5M two-clock samples (registered prediction, confirmed) | 5 | One sentence as a result; it may still be *used* as elimination evidence inside T2 subsections — billing does not follow evidence use |
| Guard source audit: silent discard, no counter (WorkerStats.java:95); institutionalised upstream (KIP-489, HdrHistogram contract — A10) | 2 | Compact subsection with the grey-lit anchors |
| Fair-config finding, **narrowed**: the original half is the invisibility claim (the setting's cost is free on a co-located testbed, so standard evaluation cannot see it); the "settings matter, 1–2 orders" half confirms vendor-documented behaviour and is T4 on its own | 2 (invisibility claim only) | Short subsection led by the invisibility claim; the known half gets one cited sentence inside it, no space of its own |
| Dither + publish-the-retention-rate remedy | 2 | Closing of results + abstract's final line (kept: it is the paper's actionable output) |
| θ plateau ~48% above 700/s | 5 (demoted from borderline 2 by the tie-break rule) | One sentence |
| Kafka corpus: **zero** negatives in 10,913,263 discards — refutes our own earlier reading | 3 | Abstract-eligible (kept); framed as audit outcome |
| M/G/1 fitted worse than the mean where forms diverge — contradiction of the adopted framing (B2 clause, committed) | 3 | Pointed paragraph in results + the §2 clause; NOT in abstract (currently barred by test — keep barred: contradiction is of a framing we adopted, weakest of the T3 set) |
| Withdrawal of the twentyfold gap (start-up cost misread) + 58% of own corpus rejected incl. every run behind the first result | 3 | Kept in abstract beat 1 (it is the audit's credential); compact in results |
| OMB distributed mode fails identically 11/11 | 5 (demoted from borderline 3 by the tie-break rule) | One sentence; diagnostics stay in supplement S4 and the upstream issue draft |
| Broker equivalence within 1 ms; no degradation with concurrency | 4 | One sentence in results (already out of abstract, test-enforced) |
| Scheduling-induced timestamp error exists (Sharma et al. / Cloudprofiler line) | 4 | One sentence with citations; our law stays T2 |
| Grid law instantiates known mathematics (Weyl, three-distance, Schuchman/Wannamaker) | 4 | One sentence anchoring, in the law's subsection |
| Football workload sparsity → domain latency questions return "doesn't matter" | 5 (refiled from 4: a confirmation requires someone else's result to confirm, and none exists — this is our own null) | One sentence in Setting/results (unchanged) |
| Pre-registration outcomes P1 (not evaluable), P4 (three-way split), P5 (falsified), P2/P3 (falsifiers fired) | 5 | One sentence each in the pre-registration paragraph; table stays in supplement |
| Jitter-kernel conjecture killed by the alternation test | 5 | One sentence (kept: it documents self-correction) |
| Load-axis functional-form details beyond the M/G/1 verdict (exponential R²=0.93 etc.) | 5 | One sentence; curves to supplement |

Consequences to verify at execution: the v1 abstract is already tier-compliant — its four
beats are (T2 mechanism evidence + T3 withdrawal credential) / T1 grid law / T1 sign
channel / T2 remedy, all within tiers 1–3; equivalence and M/G/1 stay barred by test. The
main structural work is **shrinking T4/T5 material currently holding paragraph-or-more
space** and rebalancing §8 so T2 mechanism content does not outweigh T1 grid-law content.
Extend the consistency suite: a tier-policy test asserting the T4/T5 topics above appear
at most once outside the supplement and never in the abstract.

#### Strict verification pass (2026-08-04)

Every row re-audited against the definitions plus the demote rule. Changes made:
football sparsity **refiled T4→T5** (category error — there is no prior result to
confirm; it is our null; treatment unchanged); **cross-host zero negatives added
explicitly as T5** (a predicted-and-confirmed null was implicitly riding inside a T2 row;
made explicit so it cannot hold paragraph space as a "finding"); **grid-membership
inference folded into the T1 grid-law row** (evidence for a discovery, not a second
discovery — no double billing); **fair-config narrowed** (its vendor-documented half is
T4 and loses independent space; only the invisibility claim keeps T2). Examined and
deliberately kept: the sign channel at T1 (not borderline — it is the paper's most
striking empirical event and the abstract's climax) and the governing ratio at T1 (the
demonstrated thesis, not a framing convenience). No T4/T5 item retains more than one
sentence outside the supplement.

### A. From David's quick-read review (2026-07-28)

The single most valuable property of this review: four of his seven factual questions
(which clock? what granularity? processes or threads? where does 1 ms come from?) are
answered in v1 — in §4, §6 and §7 — and he could not find them on a quick read. The
information exists; the *access path* does not. Items A1–A3 fix the access path; A4–A9
fix real gaps the questions exposed.

#### A1. Gentler introduction (his primary request)
A short plain-language opening: the key points stated clearly, briefly, before any
apparatus. Target: a general systems reader gets the two failure modes, the ratio that
governs both, and the remedy inside the first two pages. (His advice "submit the current
version, update later" is exactly the v1/v2 path we are on — validated.)

#### A2. "Measurement setup at a glance" box (new, early)
Half a page, one diagram, answering in one place what a reader needs before the argument:
- Topologies: our harness = two **processes**, one host, one clock (`time.time_ns()`,
  CLOCK_REALTIME — a shared epoch, which is why not perf_counter/TSC); OMB LocalWorker =
  producer/consumer **threads in one JVM**, stamp at `LocalWorker.java:294` is
  `now − publishTimestamp` with publishTimestamp producer-side (Kafka CreateTime);
  OMB distributed = two machines' clocks; Python harness = two processes, same-host and
  cross-host variants.
- Clocks: wall clock throughout; underlying resolution ns-representation/µs-accuracy;
  chrony-disciplined, logged per minute (residual ~0.001 ppm, skew ~0.025 ppm);
  measured inter-host offset ≈0.07 ms.
- The quantum: **1 ms is the representation** (`currentTimeMillis`, Kafka CreateTime),
  not a hardware limit — while true transport is 0.1–0.5 ms. τ vs T_true in one line.

#### A3. Consolidated "alternative explanations, eliminated" panel
His "I don't understand how you eliminated other explanations for the noisy clock times"
— the eliminations exist but are spread across §6 and §8. Add one compact table/paragraph:
skew (same clock by construction; two-clock replication: 0 negatives in 1.5M samples),
utilisation (equal-ρ geometries differ 2.07×, z=10.3), generic noise (SCHED_FIFO at fixed
ρ collapses rate 7–80×), direction (transport ×77 → rate ÷4.1), direct observation
(sched_switch trace within 30%, unfitted). One place to point sceptics to.

#### A4. The mechanism is a *when*, not a *what* — say it plainly
His reading ("delay between a process sampling the clock and getting a time back") is the
natural wrong model. State explicitly: the failure is not latency inside the clock call;
it is the scheduling stall **between the event and the clock read that labels it**
(producer's callback thread descheduled → stamps later than the event → consumer already
recorded receipt). One sentence where the model P[inversion]=P[stall>T_true] is introduced.

#### A5. "Truncation is not even self-consistent" (his sharpening — adopt with credit)
His point: if negatives are discarded as impossible, sub-minimum positives are equally
impossible and should go too; discarding one side only is unprincipled truncation. Add to
§7's guard discussion: the guard is not conservative filtering but *asymmetric, silent*
truncation — and the consistent version of its own logic would also delete a
positive floor, which no one would accept. Strengthens the dither+publish-retention remedy.

#### A6. Mean-vs-median heuristic meets α≈0.34
His workflow ("look at mean and median, investigate if they don't match") is the standard
practitioner diagnostic. Connect it explicitly to the tail result: with tail index ≈0.34
the mean does not exist, so the mean half of the heuristic is structurally uninformative
here — the practitioner's own tool cannot flag this failure. One sentence beside the tail
index result; also acknowledge the standard truncated-left/long-tail-right mental model
and note Mode B violates it from the left (deletion at the floor).

#### A7. Justify wall-clock over TSC in the paper text
The reasoning lives in code comments (kafka_producer.py) but not the manuscript: a
cross-process (a fortiori cross-machine) span has no common cycle counter even in
principle; TSC also varies with power management. Two sentences in Method or §2.

#### A8. New Discussion subsection: **"A better clock does not reach the failure"**
The referee-anticipating section (David's clock questions all point here). Content agreed:
- PTP with hardware timestamps takes two LAN machines from our measured ~70 µs (chrony) to
  sub-µs — but is provider-gated in clouds (AWS Nitro exposes a PTP hardware clock; our
  provider does not), and, decisively: **behind a 1 ms stamp, 70 µs and 70 ns of agreement
  produce byte-identical records** — the guard deletes exactly the same samples, the grid
  law is unchanged.
- Therefore the remedy ordering: (1) record at native resolution, (2) count discards,
  (3) dither the send instant, (4) only then is synchronisation the frontier.
- Our own cross-host fact from the other side: clocks agreeing to well under a tick, yet
  retention wandered 13.4→27.0% with offset drift at the 0.1 ms scale — so the
  synchronisation state belongs in the published record beside the retention rate.
- Design-out alternatives where one-way sync is genuinely needed: round-trip on a single
  clock; offset/skew removal from the delay envelope in post-processing
  (Paxson; Moon–Skelly–Towsley); paired same-window comparisons where offset cancels.
- New references: IEEE 1588 (PTP); Paxson 1998; Moon, Skelly, Towsley 1999; optionally
  Huygens (Geng et al., NSDI 2018) for software-only ~100 ns sync.

#### A9. Small factual guard-rails his misreadings exposed
- Make "producer → broker → consumer" explicit early (he read it as "storing into Redis").
- Distinguish the three negative populations in one sentence wherever one appears:
  our corpus (load-dependent, mechanism-established), Kafka-driver OMB corpus (zero in
  10.9M discards — quantisation zeros, not noise), Redis-driver corpus (41,403, every one
  exactly −1000 µs, candidate mechanism only).

### B. Carried over from referee #3's advisory list (optional, fold into v2)
- B1. Remaining length trims (~4 pp): end-to-end 209→150 lines, rules 142→110,
  Setting 71→50, authors' table 73→50, first-answer checks → list, instrumenting 82→65.
  Aligns with David's readability point; do together with A1.
- B2. M/G/1 one-clause fix: "a framing we adopt as a leading-order account and, on the
  load axis, ultimately refute" (§2 near \cite{chandrasekar2026bias}). **No longer
  optional**: committed to the framing's author.

#### A10. Fold in the grey-literature review — **DONE (2026-08-07, TPDS round-1 revision)**
docs/grey_literature_review.md (surveyed 2026-08-03; verification pass 2026-08-07 fetched
the four starred sources in full — see its §G log). Applied in the revision: Tene and the
CO-vs-Mode-B distinction (§2.4, since v2); HdrHistogram contract (§2.4/§7); **KIP-489**
one sentence beside the WorkerStats guard (`kafka2019kip489`); **AWS ClockBound + Meta
PTP** one sentence in the better-clock subsection (`aws2023clockbound`, `meta2022ptp`);
archived (Wayback) URLs added to the two grey comparisons that have snapshots (the GitHub
repo has none — the repository name is its durable identifier). Deferred with reasons
recorded in the review's §F: Shipilev, OMB #247 (upstream-issue draft in the response
letter instead), the Redpanda–Confluent stakes anecdote (page budget; queued if a referee
opens the door).

#### Tier review — referee round 1 (2026-08-07)
Checked every referee-driven change against the tier table; **no tier reassignments.**
Three notes: (1) the tail-index infinite-moment phrasing is *narrowed within its T2
mechanism row* (traced histogram shows the survival steepens beyond 4 ms, so alpha = 0.34
becomes an effective span exponent — demote-on-doubt applied to the wording, not the
tier); (2) the powered 0.41 ms shift stays T4 (confirmation/secondary) and gains a
selection-robustness defence (gate on/off <= 0.017 ms; flip point >= 0.55 ms vs condemned
observed medians ~0.10-0.12 ms); (3) the threshold-sensitivity sentence is now
condition-level artefact-verified (first_result_threshold_sweep.csv) — the T3 withdrawal
credential strengthens.

### C. Pending inputs before execution
- C1. A second external review has been offered; fold in on arrival.
- C2. arXiv announcement → v1.0.2 metadata pass (arXiv ID into README/CITATION) — separate
  from v2 and can happen first.
- C3. Any second pass from David (invited in reply).
- C4. Settle acknowledgements and authorship before v2 is posted.

### D. Execution checklist (when feedback window closes)
1. Implement A-items, then B-items, keeping every meaning-pin the consistency suite
   enforces (run the full suite + numbers gate + rendered-PDF check after each block).
2. New references added to manuscript_references.bib; rebuild ×3 + bibtex; 0 errors /
   0 undefined refs; check rendered text for macro remnants (the three-times-burned rule).
3. Abstract unchanged unless a finding changes — v2 is presentation + one Discussion
   subsection, not new claims. If the at-a-glance box shifts page count, re-verify the
   "58 pages" comment line for the arXiv replacement.
4. Post as arXiv v2 (replacement), update Zenodo (new version deposit → new DOIs,
   cross-links carry via .zenodo.json), tag v1.1.0.
5. Then the journal reformat fork (TOMPECS vs TPDS/TC decision, folding external advice).

#### Tier review — referee round 2 (2026-08-07)
Eleven welcomed minors, all presentational; **no tier reassignments and no claim
changes.** Registers audited after the edits: one "In plain language" (SS1) and exactly
the two referee-endorsed "In plain terms" instances survive — the Feynman principle
holds. Exhibits: fig:model regenerated at 1.5x internal fonts (new --font-scale option
in make_paper_figures.py) and shown at 0.8\columnwidth; fig:payloadflip restored to full
column width; Table I heads name the arms per block.


---

## v4: the restructure

> Was `docs/v4_restructure_plan.md`.

Decided 2026-09-08. The second author's sequential pass declined to back a journal
submission of v3.0.0 on presentation: paper-specific vocabulary before definition, the order
the work happened in rather than the order a reader needs, and a main text that leans on its
supplement. The lead author's decision: follow that pass exactly, and redesign rather than
patch. The rules are `docs/writing_standards.md`; the gates are
`tests/unit/test_writing_standards.py` (18 of 20 red on v3.0.0, by design — they are the
record of what the pass caught). This file is the mapping from rules to sections.

**Two invariants that do not move:** every number is still emitted from the ledger and
recomputed at build time; twelve pages, 45 references, four biographies. The science is
unchanged. What changes is the order and the words.

---

### 1. The paper: the standard shape

| new section | what goes in it | from where in v3 |
|---|---|---|
| **Abstract** | context → problem/gap → objective → method → quantitative results → implication; no term from section A of the standards before the problem is stated | rewritten |
| **I. Introduction** | why sub-millisecond latency measurement matters and who depends on it; the problem (two ways a benchmark misreports, stated in the field's words); the objective; *We make three contributions: (1) … (2) … (3) …*; one paragraph on the paper's structure | §I minus the Chronology subsection, minus Fig. 2, minus "one number", minus "the claim" |
| **II. System and Measurement Model** | Fig. 1 beside its text; the five timestamps; D, A, S, TTI defined together; *transport proxy*, not chain — with the append-precedes-both-branches argument; the same-host, one-clock assumption; what a negative S does and does not establish (C5 wording) | §III "at a glance" + "proxy, not a chain" + §III-C's identity, moved up |
| **III. Related Work** | argued: what prior work shows → its limits → what we add, per strand; self-contained; Lancet in one clause; Sharma et al. [20] plainly | §II, rewritten; supplement pointers out |
| **IV. Experimental Setup** | testbeds; the **vocabulary paragraph** (`\label{def:vocabulary}`: condition ⊃ cell ⊃ run, replicate); clocks — CLOCK_REALTIME justified on its own, CLOCK_MONOTONIC and TSC (expanded) as separate points; dataset with a real description; load generation verified | §III-A, split |
| **V. Metrics and Validation** | the admission condition (formerly "guard") defined once; the consistency check; statistics | §III-B, §III-D, §IV-A's guard definition |
| **VI. Quantisation and Silent Deletion** | Mode B, under a descriptive title; grid, vertex, quantum defined in plain words at first use; results | §IV |
| **VII. Scheduling and Acknowledgement Bias** | Mode A, descriptive title; Table I; the two-state model with T_true defined (`def:ttrue`) and related to D; C_0, k, ρ defined before Table II; the **distortion result (24% / 4.2× / 1.7×) moves here** with denominator and uncertainty | §V + the headline lifted out of §VI-B |
| **VIII. Discussion** | what the brokers do; the rules for benchmark authors — none of them first revealing a number | §VI, minus the numbers now in VII |
| **IX. Threats and Limitations** | as now, with the C5 wording | §VI-D |
| **X. Conclusion** | as now | §VII |

Cuts that pay for the definitions: the Chronology subsection (to the supplement's spine),
the Houdini and Nobel sentences, the meta-comments, Fig. 2 if the model paragraph makes it
redundant (decide on the page count), and every pointer whose sentence survives its deletion.

### 2. The vocabulary, in one pass

Mechanical, gated, done first so the restructure is written in the right words:

| v3 | v4 |
|---|---|
| stamp / stamps / stamping (bare) | timestamp / timestamps / timestamping |
| flight | the measured interval; delivery (= D) where that is what is meant; T_true only after `def:ttrue` |
| the instrument, instrument timescale | the benchmark tool; timestamp resolution; timestamping delay; the measurement mechanism |
| guard | the admission condition (defined once); "the > 0 filter" thereafter |
| arm | configuration (or treatment, where a manipulation is meant) |
| cell / run / replicate / condition | kept, defined in IV, used consistently |
| Mode A / Mode B | the descriptive section titles; the labels dropped |
| quantum | timestamp resolution where the sentence allows; *quantum* only after definition |
| physical-impossibility criterion; untrustworthy stamp; proves something is wrong; impossible physics | the C5 wording: the proxy cannot be read as a non-negative delivery latency |
| Pr[S<0] = Pr[A>D] | *S < 0 if and only if A > D*, as an equivalence |

### 3. The supplement: a postmortem

The second author's PS: a single-author document, coherent on its own, *"A postmortem of
…"* — a chronological retelling of how the results were obtained, plus the extra experiments.

Today's supplement is 55 sections, 30 of them titled "(moved from the main text)": an
attic. The recast:

- **Spine:** S35 (*How these results were reached: the chronology, and everything
  withdrawn*) becomes Part I, and the "moved from the main text" sections that narrate —
  S6, S7, S8, S9, S10, S19, S20, S26, S28, S32 — are folded into it in the order the work
  happened, each as a chapter of the story rather than a lift-out.
- **Part II, the experiments in full:** the tables and campaigns the paper summarises —
  S23, S25, S29, S31, S46, S47, S48, S55 — kept as evidence chapters the paper points to.
- **Part III, the audits and derivations:** S36 registry, S41–S44, S51, S53, S54.
- **Part IV, the literature in full:** S18, S33, S37–S40, S50, S52.
- Dropped or merged: S27 (a pointer to S23), S34 (round-1 artifacts), S45 (the metric map,
  now in the paper's §II).

Title: *A Postmortem of a Withdrawn Result: how two failure modes of a streaming benchmark
were found, and what was thrown away on the way*. Single author. The paper's pointers into
it are for evidence only; none is a definition.

### 4. The artifact

At the next deposit: one Zenodo record carrying `paper-preprint.pdf`, `supplement.pdf` and
the data zip; distinct archive names; **no `.tex` in the archive** (the replication object
keeps the manuscript as a PDF, which is what the reader checks sentences against). The code
record's `.zenodo.json` and `scripts/zenodo_deposit.py` change accordingly.

### 5. Order of work

1. Corpus to ≥ 150 papers with the journal itself represented (`fetch_vocabulary_corpus.py`,
   both arXiv stages and OpenAlex); `build_vocabulary_table.py`; commit the table.
2. Vocabulary pass over `paper.tex` and `supplement.tex`, gate by gate, until section A of
   the tests is green.
3. Sections II and IV written (model + setup + vocabulary paragraph + `def:` labels).
4. Abstract and Introduction rewritten; Related Work re-argued.
5. Mode sections retitled; the distortion result moved into VII; register gates green.
6. Page budget: cut until twelve; the supplement absorbs the cuts into the postmortem.
7. Supplement recast.
8. Full suite green; a referee-style pass against the standards document; commit; the
   co-authors get the version with a change list keyed to the 42 comments.


---

## §6.7 rewrite — working draft (revision 2, 2026-07-26 18:30Z)

> Was `docs/section67_rewrite_draft.md`.

**Status: draft. Not applied to `paper.tex`.** Revision 1 of this file was written before most of
the evidence existed and asserted several things since withdrawn. Those are listed at the bottom
under "must not appear" so they cannot creep back in.

### What is settled

Each of these rests on completed measurements and has survived every cell that has landed since.

**S1 — Zero negative samples.** Roughly 420,000 discarded end-to-end samples across 15 load-sweep
cells, 8 message-size cells and the replication pass so far. Not one is negative. The most
negative end-to-end latency observed at any load, at any message size, is 0 µs. *This is what
carries the withdrawal, and it is a statement about sign that no mechanism argument can touch.*

**S2 — Retention spans the full range.** The share of samples surviving OMB's
`if (endToEndLatencyMicros > 0)` guard ranges from **0.36% to 100%** across cells. Nine of the
first 21 lie between 5% and 95%; it is a continuous range, not two modes.

**S3 — The reported median does not track it.** Across the 16-cell join, reported p50 takes two
values — 1.0 and 2.0 ms. One cell computed its summary from 998 samples and another from 120,425;
both report 1.0 ms. Nothing in OMB's output distinguishes them.

**S4 — The reported average moves the wrong way.** Spearman(retention, reported average) = −0.54.
Discarding everything below one tick removes the *fast* samples, so the mean is taken over the
surviving slow tail. The benchmark reports a higher latency the more data it discards.

**S5 — The instability has a location.** Message sizes whose latency sits far above one tick
reproduce tightly (64 KB: 35.92% vs 34.42%; 256 KB: 100% vs 100%). Sizes whose reported median is
exactly 1.0 ms swing across nearly the whole range (200 B: 100% vs 0.36%; 4 KB: 10.94% vs 100%).
The irreproducibility is a property of the near-tick regime, not of the benchmark generally.

**S6 — Path speed does not explain it.** OMB's own publish latency — measured within one process
and *not* quantised to the millisecond grid — sits at 0.3–0.4 ms across all 19 unsaturated cells
while retention over those same cells ranges from 0.36% to 100%. A predictor with a 0.1 ms spread
cannot explain a 275-fold swing.

**S7 — Replicates that agree are not a reproducible measurement.** *(Level 0 only so far; four
levels pending.)* The identical sweep run twice gave a three-replicate median of 1.51% in pass A
and 99.98% in pass B. Pass B's three replicates agree to 3.58 points. An experimenter running only
pass B would report a tight, confident measurement 98 points away from what the same configuration
produced an hour earlier.

### The claim the section should make

> An instrumented OpenMessaging Benchmark, run against our broker on a sub-millisecond path,
> computes its reported latency distribution from between 0.36% and 100% of the samples it takes,
> depending on the run, and reports the same median either way. It counts nothing that it drops.
> The fraction that survives is not reproducible between passes of an identical configuration, and
> replicates within a pass can agree closely while the pass itself is 98 points from its
> predecessor — so the usual defence of averaging replicates and quoting their spread does not
> detect it and actively misleads.

That is stronger than the claim it replaces, and it is about the number a reader actually sees
rather than about a counter only we can read.

### What we withdraw, and why the section must say so

Section 6.7 reported that an instrumented OMB "discarded 6,000 end-to-end samples" and read those
as the same causality violation this paper reports. **The reading is withdrawn.** The counter
behind it was a single unsigned total; both a causality violation and a sub-millisecond delivery
fail `> 0`, and it counted them together.

The refutation was in our own artefact from the day it was committed. All eleven counter lines in
`external/omb/omb_discard_evidence.txt` read `sample_micros=0`, and the Pub-rate lines beside them
show a median publish latency of 0.4–0.5 ms. What was missing was not data but a reason to look at
the sign, because the statistic we chose to report did not have one. That belongs in the section:
it is the paper's own subject, one level up.

**The source audit is unaffected** and never depended on the run — the guard admits only positive
samples, nothing counts the drops, the reported distribution is conditioned on being positive, and
the retention rate is unrecoverable from a completed run.

### Still open — do not write these until they land

- **Cross-host negatives** (chain5). The clock bound on this testbed is 12.3 ms against a 1 ms
  timestamp, so a negative is possible. Single-host cannot settle it.
- **Mechanism** (chain8). Phase against the millisecond grid is the candidate: the producer is
  paced at exactly 2.000 ms. Predictions are filed; if all three rates behave alike it is wrong.
- **Retention variance at n=15** (chain7).
- **S7 at levels 50–95** (chain3 step 2, running).

### Must not appear — withdrawn during this work

1. *"The zero share falls with load."* Five levels are 98.49, 23.68, 4.41, 4.78, 22.63 — not
   monotone. Read from three levels before the other two existed.
2. *"Retention is bimodal / a threshold with nothing between."* Nine of 21 cells lie between 5%
   and 95%. Read from five observations at one configuration.
3. *"64 KB is the clean discriminator."* It is saturated: p50 = 519 ms, p99 = 1097 ms.
4. *"Retention = P(true latency ≥ one tick)."* Refuted by S6 — the path is flat while retention
   swings.
5. *Anything treating the message-size sweep as discriminating resolution from causality.* It
   never could; both predict no zeros at high latency. It shows a dose-response, nothing more.

### Sites to update together

| site | line | change |
|---|---|---|
| abstract | 70 | replace the 6,000 with the retention finding |
| contributions | 202 | same, plus the sweep |
| related work | 243 | check wording survives |
| limitations | 2525 | **rebuild** — the run no longer establishes the failure outside our harness; the source audit does |
| conclusion | 2631 | replace the 6,000 |
| §7 requirements | 2332–2342 | unaffected, and strengthened |
| `docs/laws.md` | 241 | **done** |
| status board | 236 | **done** |
| `external/omb/README.md` | 4 | **done** |
| `external/omb/omb_discard_evidence.txt` | — | **keep byte-for-byte** — it is the primary record of the refutation |
