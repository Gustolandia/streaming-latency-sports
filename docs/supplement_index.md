# Supplement index

What moved out of the main manuscript, where it lives now, and where it came from. Nothing is
deleted: every block is either in `supplement.tex` (compiled separately; NOT part of the main
journal submission) or recoverable at the named commit.

| Supp. section | Content | Moved from | Source revision |
|---|---|---|---|
| S1 | Replay-rate provenance gap, full episode (recovery arithmetic, per-claim exposure, disagreeing records) | main text `sec:rateprovenance` (92 lines -> 14-line summary) | pre-move text at commit 8480957 |
| S2 | Load-axis post-mortem: the failed M/G/1 + registered-bracket detail | main text mixture development (`sec:twostate` area) | pre-move text at commit 8480957 |
| S3 | Campaign ledger schema (column dictionary) | new (referee minor 12) | n/a |
| S4 | OMB distributed-mode failure diagnostics (per-attempt version, logs, signature) | new (referee M2); data in `docs/results/external/dist_diag/` | n/a |
| S5 | The E1 reconciliation in full (windowed re-analysis, tab:e1rep) | main text `sec:e1` (95 lines -> 8-line summary) | pre-move text at commit d5e4d02 |

Sections S6 onward were added in the v2 IEEEtran/TPDS restructure (2026-08), which compressed
the main text from 58 acmsmall pages to 16 IEEEtran pages. Every block below left a compact stub
in the main text carrying its claims, verdicts and strongest numbers; the consistency suite pins
hold on the concatenated package (paper + supplement), so nothing moved out of reach of the
artefact checks. Source revision for all of them: the pre-restructure text at the commit
preceding the "v2: TPDS restructure" commit.

| Supp. section | Content | Main-text stub |
|---|---|---|
| S6 | The broker comparison in full | `sec:e1` |
| S7 | The end-to-end withdrawal in full | `sec:attribution` |
| S8 | The first corpus's prior corrections (the five-then-six list) | `sec:firstanswer` |
| S9 | Open questions from the comprehensive campaign | `sec:extopen` |
| S10 | The distributed-mode attempts in full | `sec:extdist` |
| S11 | The workload in full | `sec:metrics` |
| S12 | Two-state model commentary + tracing instrument checks | `sec:twostate` (file order: after S13) |
| S13 | The commensurability account's corrections in full | `sec:extquant` |
| S15 | Configuration in full | `sec:config_table` |
| S16 | Instrumentation of the external benchmark in full | `sec:extmethod` |
| S17 | The transfer procedure with its incidents (rules 2,3,6,7,9,11) | `sec:protocol` |
| S18 | Related work in full: variability literature + result-by-result map | `sec:related_resolution` / `sec:related_tail` |
| S19 | Provenance-gap episode + co-location withholding (E-A8) | `sec:rateprovenance` / withdraw list |
| S20 | The delay-sweep withdrawal in full (netem manipulation check) | H1, `sec:rules` |
| S21 | Experiment map, claim-evidence table, audit threshold figure | `sec:expmap` / `sec:threshold` |
| S22 | Threats and limitations in full | `sec:threats` / `sec:limitations` |
| S23 | Tables and the pipeline schematic (TTI decomposition, imputation) | `sec:metrics` / `sec:retention` |
| S24 | Tail recovery without a reference clock | discussion |
| S25 | The mechanism campaigns' tables (mixture, E-A5/6/9/10) | `sec:twostate` / `sec:mixture` |
| S26 | Model figure, flip figure, first result set table | `sec:model` / `sec:firstanswer` |
| S27 | The grid table | `sec:extquant` |
| S28 | The mechanism campaign paragraphs in full | `sec:twostate` |
| S29 | Audit, stamping-mode and injected-delay tables | `sec:audit` / H3 / `sec:network` |
| S31 | Spread rule + grid-membership inference in full | `sec:extquant` / `sec:extinference` |
| S32 | The mechanism narrative in full | `sec:twostate` |
| S33 | Resolution/discard/sampling literature engagement in full (CO, Weyl, run-to-run instability) | `sec:related_resolution` |
| S33.1 | Payload sweep's underpowered rows; duration + plateau paragraphs | `sec:extphase` / `sec:extcomp` |

(S14 and S30 were never assigned; the numbering gaps are deliberate, not losses. The supplement
carries its own IEEEtran bibliography for the citations that travelled with the moved text.)

The compiled supplement states on its first page that it is not part of the main submission.
Referee report that drove this split: `REFEREE_REPORT_SIMULATED.md` (untracked).

## TPDS round-1 revision (2026-08-07)

Three exhibits moved **out of** the supplement into the main text at the referee's request
(M1): the two-panel model figure and the payload flip figure (formerly S26) and a compact
mechanism table digesting the S25 occupancy/geometry tables (`tab:mechanism`, new). In the
other direction, compact stubs in the main text now point at full paragraphs appended to
S4 (distributed-mode body), S7 (benchmark-output corroboration), S16 (gate/warmup/ledger
detail), S17 (transfer-procedure rules), S18 (Lozi/Li literature engagement), S29
(reversal account + falsification), S31 (grid-membership inference), each marked
"Moved from the main text (TPDS round 1)". **S34** (new) holds the referee-round
sensitivity artefacts: the audit gate applied to the powered transport campaigns
(`gate_sensitivity.csv`, `transport_realtime_*_gated.csv`), the condition-level threshold
sweep (`first_result_threshold_sweep.csv`), and the traced survival slopes
(`traced_tail_slope.csv`). The powered-transport S5/S6 tables now carry the **gated**
numbers; the ungated originals remain in the artefact tree as the historical record.

## TC referee round (2026-08-19)

The submission was retargeted to IEEE Transactions on Computers and then reviewed against
that journal's standards. Ten items were raised; the ones that moved material are recorded
here so the provenance chain stays unbroken.

**Into the supplement.**

- **S32** gained the four-point payload-sweep fit (`eq:tailindex`, the effective exponent
  with its Student-*t* interval), demoted out of the main text. Four points do not earn a
  displayed equation in a 10-page journal article; the direction of the effect, which is
  what the mechanism argument uses, stays in the main text.
- **S32** also gained the two withdrawals attached to that fit. The infinite-moment reading
  ("alpha below one, so no finite mean") is withdrawn: a slope through four
  application-level points does not license a statement about the moments of the stall
  distribution. The traced cross-check is withdrawn: re-estimated properly on the same
  histogram, an exceedance index and a grouped-likelihood index differ sixfold because the
  survival is not a power law over that window, and the previously quoted agreement was a
  coincidence of window and estimator.
- **S35.5** (new) records that withdrawal in the chronology. The subsections that followed
  renumbered by one (provenance gap 35.6 → 35.7, distributed mode 35.7 → 35.8).
- **S35.2** gained the Redis-driver mechanism. The negatives were previously hedged as a
  "candidate" clock artefact; the driver settles it, and the hedge is gone.
- **S34** now marks `traced_tail_slope.csv` as *superseded* rather than as supporting
  evidence, and names the script that replaces it.

**Corrected in place.**

- **S31**'s grid-membership counts now come from the corrected p-values. One arm (900 msg/s)
  had been counted as a rejection under a caption claiming Holm correction; corrected, it
  does not reject, and it is now reported as unresolved. The main-text table is generated
  from the artefact (`docs/generated/grid_table.tex`) so the two cannot diverge again.
- Four doubled cross-references left by an earlier neutralisation pass ("the main text's the
  main text's ...") were repaired.

**Format.** The document class gained `nonacm`. The supplement had been carrying
"Manuscript submitted to ACM" on all forty pages while being submitted to an IEEE journal,
which is not a rule violation but is exactly what a Computer Society prescreener looks for.

## Internal review round 2 (2026-08-19)

Nineteen items (R1–R19). Those that moved or relabelled supplement material:

- **S32** gained the reinterpretation that replaced the withdrawn tail index. The traced
  histogram is not heavy-tailed and not merely "not a power law": it is multi-modal, with a
  mode at 2–4 ms carrying about a tenth of all wakeups and a *light* tail (α ≈ 2) beyond it.
  The mode sits at the EEVDF base slice for an eight-vCPU instance, which makes it the
  two-state model's preempted state observed directly. A bootstrap goodness-of-fit
  (p < 0.0004 over 2,500 replicates) replaces "two estimators disagree" as the evidence
  that the power law is wrong.
- **Every review-history label was relabelled.** Nine sections read "TPDS round 1" and three
  passages referred to "the TC submission" or "the TC revision". Read cold, that implies
  the manuscript was reviewed at two journals. It has been reviewed at none: those were
  adversarial reviews conducted inside the project before submission. The front matter now
  says so explicitly, and the labels read "internal review, round N".
- **S31** and the S35 chronology are unchanged in substance; only the round labels moved.
- The dither lineage in S18 gained McCanne & Torek, cut from the main text to hold the
  45-reference cap.

Nothing was moved *into* the supplement in this round. The four-point payload fit stays in
S32 where round 1 put it.


## Round 19 (2026-08-24): the co-author round

A co-author's review added five explanations to the main text and one full-width figure. Both
were paid for out of the main text, into four new sections. Everything below left a stub
carrying its claim; nothing lost a number or a citation.

| Supp. section | Content | Moved from |
|---|---|---|
| S49 | The statistical inventory: pooled-variance z, Hodges–Lehmann, TOST, the permutation null, the bootstrap, and the interval-censored tail estimators | main text III-D, which keeps only the three choices a reader might contest |
| S50 | The dispute with the concurrent negative-span report in full --- which queue each account means, and why a millisecond skew threshold does not transfer to a loaded machine | main text II-B (about 140 words) |
| S51 | The 1970 counter note mapped line by line: retention identity, class, the ceiling on averaging, the symptom, the cure | main text II-C (about 100 words) |
| S52 | Two literatures the paper stands against: production tracing's skew adjusters, and where scheduling delay comes from | main text II-B and II-C (about 250 words) |

Three citations moved with S52 and so left the paper's reference list, which is now 42 of the
45 TC allows: the two Jaeger sources and the tail-latency study. They are cited in the
supplement, which carries its own bibliography.

**Not moved, and worth recording why.** The mechanism table (Table II) stayed in the main text
even though the enlarged Figure 5 now does most of its work, because a TPDS round-1 referee
asked for it there (item M1) and a gate holds it. Float packing was tried first --- two pages
were three hundred words short each --- and adjusting `\topfraction` and its neighbours
changed the layout by nothing at all: those pages were not float-starved, the floats were the
content.

## Round 20 (2026-08-24): the referee's three substantive items

Three defects, three minors and three recommendations, plus the reference cap. Everything the
main text gave up is below; nothing lost a number or a citation.

| Supp. section | Content | Moved from |
|---|---|---|
| S53 | Why the two drivers differ, and how a difference of two floored clocks admits exactly one negative value | main text IV-D (about 130 words) |
| S54 | The permutation null, constructed: exchangeability under the continuum, 10^4 permutations, and why it has no power where the predictions coincide | main text IV-C |
| S55 | The overnight campaign prediction by prediction --- the duration-invariance counts that killed the drift account, and the linear extrapolation that failed | main text IV-B |

**The reference cap decided two placements.** Round 20 added five citations to a list of
forty-two and 45 is the cap, so two came back out. `wrk2_src` keeps its entry in S36's
generated table, which cites every audited tool by construction, and loses its per-tool
citation in the main text; the library-refusal class is still counted from the registry and
still described. `swami2026observability` moved to S52.1, beside the Villain argument it
supports, rather than into Section II-B.

**KAFKA-19888 moved the other way**, up from S36 into Section IV-D. The reason it was held
back --- that its mechanism is wall-clock non-monotonicity and would invite confusion with
Mode A --- is right about Mode A and does not apply to Mode B, where the finding is that a
first-party vendor chose the substitution class this paper says is worse than filtering. The
main text names the mechanism so the two cannot be confused.

## Round 22 (2026-08-24): pointers, and a check that could not see

No new sections. Two corrections to round 20's relocations and one to the prose:

- **S54** is now cited by Section IV-C for the permutation null's construction. It had been
  citing S46, which is the per-arm table and does not contain the construction.
- **S53** is now cited by Section IV-D for the two-floored-clocks explanation. It had been
  citing S43, which contains none of that material.
- Section IV-D said the five disposing tools fall "in four classes". The taxonomy has three
  --- `DISPOSAL_KINDS` is `positive_only_filter`, `silent_suppression`, `library_refusal` ---
  and the sentence itself enumerates three. It was the one count in that paragraph still
  typed by hand. `harnessDisposalClasses` is emitted now.

`TestEveryTargetedRelocationIsReachable` holds the first two: every section from S45 onward
must be pointed at from the paper. Sections below S45 are exempt by design --- they are the
TPDS-era bulk moves, documented here rather than pointed at individually.

## Round 24 (2026-08-25): the sweep, and the pointer that costs money

No new sections. Six numbers moved from prose into the ledger, two of them in the supplement:

- `supplement.tex` quoted the payload exponent as `0.339` against a second-day repeat and the
  Hodges--Lehmann shift as `0.408` heading a list of three. Both now read `\tailExponent` and
  `\tostHL`.
- S42 gained a one-paragraph lead saying what Section VI-D now states in a sentence, because
  VI-D gave up the two-part derivation to bring Threats back under the section that carries
  Contribution 2's decisive experiments.

`tests/unit/test_ledger_coverage.py` is the sweep behind the first of those, and
`tests/unit/test_citation_surface.py` gained the page-count check --- the last journal limit
with no gate, and the only one that costs $220 a page.

## Round 26 (2026-08-25): a framework that does not have the problem

- **S52.2 is new**: the reading behind Section VI-B's claim that the reporting rules are
  practical. mq-bench (arXiv:2603.21600, March 2026) stamps in nanoseconds, subtracts a
  send-referenced span on one host, applies no positivity guard, and reports sub-millisecond
  medians --- both of our recommended choices, made independently and argued for nowhere. The
  section quotes its measurement text and notes the one thing it does not do: say why its span
  is safe.
- **S52.3** is the old S52.2, the field-size synthesis, moved down. Its citation left the main
  text so the reference cap could pay for mq-bench; the claim is unchanged and Section II-A
  now points here for it. *(Corrected in round 28: it did not. The pointer was still on S52.2
  when this was written, and this line recorded a repair that had not been made — which is why
  `test_supplement_subsections.py` now checks that a pointer lands on its subject.)*
- The fitted prefactor is `\tailPrefactor` in both places it appears. It was the one quantity
  in `tail_index.csv` with a committed source and no macro, and therefore invisible to the
  round-24 sweep, which asks whether a macro'd value is read from its macro and not whether a
  sourced value has one.

## Round 28 (2026-08-25): subsection numbering, and a figure for the mechanism

- **S52.4 is the old second S52.3.** Round 26 renumbered the field-size synthesis to S52.3 and
  left the scheduling-delay subsection, already S52.3, where it was. Both printed. The
  scheduling-delay subsection is now S52.4 and Section II-C points at it by number.
- **S8.1, S8.2 and S19.1 are newly numbered**, not new. They were the only subsections in the
  document with no `SNN.M` prefix and printed as bare titles in the contents list.
- **Section II-A now really does point at S52.3** for the field-size claim. Round 26's entry
  here said it did; the source said S52.2, which is the mq-bench reading and sizes nothing.
- **S36 keeps the Kafka coordinator fix, and now the main text agrees.** S36 said the case was
  recorded "here rather than in the main text"; the main text carried it in full anyway.
  Section IV-E keeps the claim and the citation in one sentence and sends the reader here.
- **S50, S52.1 and S41** absorbed the reasoning trimmed from Sections II-B, II-C and IV-C to
  pay for Figure 3. No claim left the paper; the arguments behind three of them did.

## Round 30 (2026-08-25): an adjective, and three numbers that were right but typed

- **S42's chrony bounds now come from the ledger.** `\chronyHostBoundLo`,
  `\chronyHostBoundHi`, `\chronyPairBound` and `\chronyHosts` are emitted from the committed
  `chronyc tracking` captures by the function that already computed them. The sentence also
  now says the 12 ms is the sum of the two *worst* hosts, because adding the printed endpoints
  gives 14 and a reader was entitled to try.
- Nothing else in the supplement changed. Section I's "largest mode" was the round's headline
  defect and it is main-text only; S52.4 already said "the last".

## Round 32 (2026-08-25): the tables, and a word that meant something else

- **S42's chrony sentence names its noun and sums the right thing**: "across the
  `\chronyHosts` hosts captured, and the two worst of *those bounds* sum to
  `\chronyPairBound` ms". The hosts do not sum; their bounds do.
- Nothing else in the supplement changed. The round's substantive finding --- that *retention*
  is never defined and collides with Kafka's `log.retention.*` --- is answered in the main
  text's Method section, which is where the paper defines its other terms.

## Figure inventory

`docs/results/figures/` holds fifteen PDFs. Twelve are included by a document; three are not,
and are kept deliberately rather than by oversight. Referee round 13 asked which was which, so
the answer lives here instead of in anyone's memory. A test
(`test_every_figure_is_used_or_declared`) fails if a figure appears in the directory without
appearing in this table.

| Figure | Where it appears |
|---|---|
| `pipeline_schematic` | supplement, S45 |
| `measurement_model` | main text, Fig. 1 |
| `deletion` | main text, Fig. 2 |
| `quantum_geometry` | main text, Fig. 3 (added round 28: the geometry behind the deletion law) |
| `grid_membership` | main text, Fig. 4 |
| `payload_flip` | main text, Fig. 5 (single-column from round 28; was full-width) |
| `mechanism_forest` | main text, Fig. 6 (full-width from round 19) |
| `ttrue_law` | main text, Fig. 7 |
| `stall_spectrum` | main text, Fig. 8 |
| `priority_ladder` | supplement, S47 |
| _(no figure)_ | supplement, S48 --- the broker results, moved from the main text in round 18 |
| `experiment_map` | supplement |
| `integrity_audit` | supplement |
| `window_sweep` | supplement |
| `e1_end_to_end_lag` | supplement |
| `kickoff_concurrency` | **retained, unused.** The kickoff-window concurrency view from the withdrawn first result set. Kept because the campaign it draws is still in the archive and the withdrawal is part of the record; no current claim rests on it. |
| `network_delay` | **retained, unused.** The injected-delay view superseded by the netem table in Section VI, which reports the same runs numerically. |
| `workload_profile` | **retained, unused.** The StatsBomb replay profile from the 16-page version; the workload is now described in prose in Section III. |
