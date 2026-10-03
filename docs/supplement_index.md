# Supplement index

What moved out of the main manuscript, where it lives now, and where it came from. Nothing is
deleted: every block is either in the journal supplement `supplement.tex`, in the postmortem
`postmortem.tex` (both compiled separately; only the first is submitted with the paper), or
recoverable at the named commit.

## Journal supplement and postmortem

**Split on 2026-09-29.** An outside editor read the 74-page single-author supplement as an
undecided paper and asked for 25--30 pages organized by the paper's sections, under its byline,
with at most fifteen pointers from the paper. The old supplement was renamed `postmortem.tex`
and corrected where the fidelity audit of 29 Sep, and a later editorial audit, found errors.
It is the complete record, archived with the data, single-author as the second author asked
on 2026-09-08, and not part of the submission. Its sections keep their numbers, and
**every S-number below this section is a postmortem number**. Its thirteen self-references that
read "supplementary material S<n>" now read "Section~S<n>", because that phrase names the other
document now.

The journal supplement `supplement.tex` is new. It has nine sections in the paper's order, and
points into the postmortem as "postmortem, S<n>". Each row gives the postmortem sections it
draws on; `tests/unit/test_cross_document_refs.py` reads this table to check that every passage
once moved out of the paper is still reachable from it.

| Supp. section | Title | Draws on (postmortem sections) |
|---|---|---|
| S1 | The setup in full | S9, S16.1, S16.2, S16.8, S18, S19, S20, S21, S24.3, S34 |
| S2 | The sign check, and what it selects | S18, S18.1, S19, S26.2 |
| S3 | Failure 1: the full evidence | S7, S8, S9, S12, S15, S16.3, S16.4, S16.6, S16.8, S16.9, S19, S26.1 |
| S4 | Failure 2: the full evidence | S10, S11, S14, S16.7, S17, S22, S22.1, S24.1, S25 |
| S5 | The tool registry | S25, S25.1, S30 |
| S6 | The registered law campaign | S16.10, S16.11, S34, S35, S36, S37 |
| S7 | The broker comparison, gated | S2, S13, S18.1 |
| S8 | Results we withdrew | S1, S3, S4, S5, S6 |
| S9 | Related work in full | S27, S28, S29, S31, S32, S33 |

The paper's pointers were remapped with it: 21 into the old numbering became 15 into the new,
and every journal-supplement section is pointed at (`tests/unit/test_journal_supplement.py`).

**Paper v6, 2026-10-02.** The paper's body was reorganized around its three parts: the finding
(Section III, latencies that come out negative on one clock), the mechanism (Section IV, a
timestamp taken late, with its laws as Equations 3 to 5) and the industry (Section V, what the
tools do with a latency at or below zero; v5's "How Widespread" is now its last two
subsections), followed by Practical Implications (Section VI: v5's "What Benchmark Authors
Should Do" is VI-C, and the transport proxy's cost and repair, v5's III-D, is VI-B). No
supplement section moved or was renumbered and every pointer lands where it did; the
supplement's table mapping paper sections to its own was rewritten for the new sections.

**Paper and supplement v6.1, 2026-10-03.** A prose revision of both documents: one idea per
sentence, each term defined where it first appears, long paragraphs split. No section moved or
was renumbered, and no pointer changed. In the supplement the retentions $0, 1/q, \ldots, 1$ are
now the *q*-lattice (S4.2, and a row of the glossary), so that "grid" keeps one meaning, the
instants at which a timestamp changes value; Figure S6's label says "lattice" to match.

## The postmortem (the supplement until 2026-09-29)

**Renumbered on 2026-09-08 (v4).** At the second author's request the supplement became a
single-author postmortem in four parts — I. the chronology, II. the experiments in full,
III. the audits and derivations, IV. the literature — and its sections were reordered into
that shape and renumbered contiguously S1–S52 in the new order. The numbers in this file are
the **new** ones. Earlier correspondence, plans and commit messages cite the old numbers;
the concordance, old→new, is: S1→S6, S2→S13, S3→S33, S4→S34, S5→S9, S6→S3, S7→S4, S8→S5,
S9→S10, S10→S11, S11→S29, S12→S16, S13→S12, S15→S30, S16→S31, S17→S32, S18→S45, S19→S7,
S20→S8, S21→S27, S22→S28, S23→S19, S24→S17, S25→S20, S26→S2, S28→S14, S29→S21, S31→S22,
S32→S15, S33→S46, S34→S18, S35→S1, S36→S37, S37→S47, S38→S48, S39→S49, S40→S50, S41→S38,
S42→S39, S43→S40, S44→S41, S45→S36, S46→S23, S47→S24, S48→S25, S49→S35, S50→S51, S51→S42,
S52→S52, S53→S43, S54→S44, S55→S26; the old S27 (a forwarding note) was withdrawn, and
S14 and S30 had been withdrawn earlier.

**Reorganized on 2026-09-10 (v5).** Fifty-two sections became thirty-three: eighteen titles that read "... in full" were replaced by ones stating what the section found, sixteen sections under 350 words were folded into the section they belong beside, the three table dumps became one, and the four parts were rebuilt around the question each answers. **The numbers in this file are the v5 ones.** The concordance from the 2026-09-08 numbering is:

S1->S1; S2->S1; S3->S2; S4->S3; S5->S1; S6->S4; S7->S4; S8->S3; S9->S5; S10->S1; S11->S22; S12->S6; S13->S5; S14->S7; S15->S8; S16->S9; S17->S8; S18->S18; S19->S26; S20->S26; S21->S26; S22->S10; S23->S11; S24->S12; S25->S13; S26->S7; S27->S18; S28->S19; S29->S20; S30->S21; S31->S22; S32->S23; S33->S24; S34->S24; S35->S24; S36->S24; S37->S25; S38->S14; S39->S15; S40->S16; S41->S16; S42->S17; S43->S14; S44->S14; S45->S27; S46->S28; S47->S29; S48->S30; S49->S31; S50->S32; S51->S33; S52->S33.

**Part V added on 2026-09-28.** Sections S34 to S37 report the pre-registered law campaign run on three Azure pairs (plan version 32, `freezes/28-experiment-plan`): what was registered and run, every verdict, every aberrant run marked with its reason, and what was read after the verdicts. It was appended after Part IV so that no existing section number moved; S16.10 and S16.11 carry two of its findings in depth. Its numbers are pinned by `tests/unit/test_supplement_part_v.py`.

It was built by matching section titles between the two documents rather than by composing the two rewriting passes. Composing is what corrupted the paragraph above the first time: a remapper was run over this file and rewrote *both sides* of the 2026-09-08 concordance, so S1 came to map to three different sections at once. A concordance is a record of the past and no rewriting pass may touch it.

| Supp. section | Content | Moved from | Source revision |
|---|---|---|---|
| S4 | Replay-rate provenance gap, full episode (recovery arithmetic, per-claim exposure, disagreeing records) | main text `sec:rateprovenance` (92 lines -> 14-line summary) | pre-move text at commit 8480957 |
| S5 | Load-axis post-mortem: the failed M/G/1 + registered-bracket detail | main text mixture development (`sec:twostate` area) | pre-move text at commit 8480957 |
| S24 | Campaign ledger schema (column dictionary) | new (internal review, minor item 12) | n/a |
| S24 | OMB distributed-mode failure diagnostics (per-attempt version, logs, signature) | new (internal review, item M2); outcomes in `docs/results/external/omb_distributed_result.csv`, `dist_load0/` and `dist_load50/`; the coordinator logs were not retained (postmortem S24.1) | n/a |
| S5 | The E1 reconciliation in full (windowed re-analysis, tab:e1rep) | main text `sec:e1` (95 lines -> 8-line summary) | pre-move text at commit 6251050 |

Sections S2 onward were added in the v2 IEEEtran/TPDS restructure (2026-08), which compressed
the main text from 58 acmsmall pages to 16 IEEEtran pages. Every block below left a compact stub
in the main text carrying its claims, verdicts and strongest numbers; the consistency suite pins
hold on the concatenated package (paper + supplement), so nothing moved out of reach of the
artefact checks. Source revision for all of them: the pre-restructure text at the commit
preceding the "v2: TPDS restructure" commit.

| Supp. section | Content | Main-text stub |
|---|---|---|
| S2 | The broker comparison in full | `sec:e1` |
| S3 | The end-to-end withdrawal in full | `sec:attribution` |
| S1 | The first corpus's prior corrections (the five-then-six list) | `sec:firstanswer` |
| S1 | Open questions from the comprehensive campaign | `sec:extopen` |
| S22 | The distributed-mode attempts in full | `sec:extdist` |
| S20 | The workload in full | `sec:metrics` |
| S9 | Two-state model commentary + tracing instrument checks | `sec:twostate` (file order: after S6) |
| S6 | The commensurability account's corrections in full | `sec:extquant` |
| S21 | Configuration in full | `sec:config_table` |
| S22 | Instrumentation of the external benchmark in full | `sec:extmethod` |
| S23 | The transfer procedure with its incidents (rules 2,3,6,7,9,11) | `sec:protocol` |
| S27 | Related work in full: variability literature + result-by-result map | `sec:related_resolution` / `sec:related_tail` |
| S4 | Provenance-gap episode + co-location withholding (E-A8) | `sec:rateprovenance` / withdraw list |
| S3 | The delay-sweep withdrawal in full (netem manipulation check) | H1, `sec:rules` |
| S18 | Experiment map, claim-evidence table, audit threshold figure | `sec:expmap` / `sec:threshold` |
| S19 | Threats and limitations in full | `sec:threats` / `sec:limitations` |
| S26 | Tables and the pipeline schematic (TTI decomposition, imputation) | `sec:metrics` / `sec:retention` |
| S8 | Tail recovery without a reference clock | discussion |
| S26 | The mechanism campaigns' tables (mixture, E-A5/6/9/10) | `sec:twostate` / `sec:mixture` |
| S1 | Model figure, flip figure, first result set table | `sec:model` / `sec:firstanswer` |
| — (was S18; withdrawn in v4) | The grid table: a forwarding note only, the table itself being in S26 | `sec:extquant` |
| S7 | The mechanism campaign paragraphs in full | `sec:twostate` |
| S26 | Audit, stamping-mode and injected-delay tables | `sec:audit` / H3 / `sec:network` |
| S10 | Spread rule + grid-membership inference in full | `sec:extquant` / `sec:extinference` |
| S8 | The mechanism narrative in full | `sec:twostate` |
| S28 | Resolution/discard/sampling literature engagement in full (CO, Weyl, run-to-run instability) | `sec:related_resolution` |
| S28.1 | Payload sweep's underpowered rows; duration + plateau paragraphs | `sec:extphase` / `sec:extcomp` |

(S7 and S21 were never assigned; the numbering gaps are deliberate, not losses. The supplement
carries its own IEEEtran bibliography for the citations that travelled with the moved text.)

The compiled postmortem states on its first page that it is archived with the data and is not
part of the submission. The internal review that drove this split is not public.

## Internal review, TPDS standard, round 1 (2026-08-07)

Three exhibits moved **out of** the supplement into the main text at that internal review's
request (item M1): the two-panel model figure and the payload flip figure (formerly S1) and a compact
mechanism table digesting the S26 occupancy/geometry tables (`tab:mechanism`, new). In the
other direction, compact stubs in the main text now point at full paragraphs appended to
S24 (distributed-mode body), S3 (benchmark-output corroboration), S22 (gate/warmup/ledger
detail), S23 (transfer-procedure rules), S27 (Lozi/Li literature engagement), S26
(reversal account + falsification), S10 (grid-membership inference), each marked at the
time as moved from the main text in this round. **S18** (new) holds the sensitivity
artefacts this review asked for: the audit gate applied to the powered transport campaigns
(`gate_sensitivity.csv`, `transport_realtime_*_gated.csv`), the condition-level threshold
sweep (`first_result_threshold_sweep.csv`), and the traced survival slopes
(`traced_tail_slope.csv`). The powered-transport S5/S2 tables now carry the **gated**
numbers; the ungated originals remain in the artefact tree as the historical record.

## Internal review, IEEE TC standard, round 1 (2026-08-19)

The manuscript was retargeted to IEEE Transactions on Computers and then reviewed internally
against that journal's standards. Ten items were raised; the ones that moved material are recorded
here so the provenance chain stays unbroken.

**Into the supplement.**

- **S8** gained the four-point payload-sweep fit (`eq:tailindex`, the effective exponent
  with its Student-*t* interval), demoted out of the main text. Four points do not earn a
  displayed equation in a 10-page journal article; the direction of the effect, which is
  what the mechanism argument uses, stays in the main text.
- **S8** also gained the two withdrawals attached to that fit. The infinite-moment reading
  ("alpha below one, so no finite mean") is withdrawn: a slope through four
  application-level points does not license a statement about the moments of the stall
  distribution. The traced cross-check is withdrawn: re-estimated properly on the same
  histogram, an exceedance index and a grouped-likelihood index differ sixfold because the
  survival is not a power law over that window, and the previously quoted agreement was a
  coincidence of window and estimator.
- **S1.5** (new) records that withdrawal in the chronology. The subsections that followed
  renumbered by one (provenance gap 35.6 → 35.7, distributed mode 35.7 → 35.8).
- **S1.2** gained the Redis-driver mechanism. The negatives were previously hedged as a
  "candidate" clock artefact; the driver settles it, and the hedge is gone.
- **S18** now marks `traced_tail_slope.csv` as *superseded* rather than as supporting
  evidence, and names the script that replaces it.

**Corrected in place.**

- **S10**'s grid-membership counts now come from the corrected p-values. One arm (900 msg/s)
  had been counted as a rejection under a caption claiming Holm correction; corrected, it
  does not reject, and it is now reported as unresolved. The main-text table is generated
  from the artefact (`docs/generated/grid_table.tex`) so the two cannot diverge again.
- Four doubled cross-references left by an earlier neutralisation pass ("the main text's the
  main text's ...") were repaired.

**Format.** The document class gained `nonacm`. The supplement had been carrying
"Manuscript submitted to ACM" on all forty pages while being prepared for an IEEE journal,
which is not a rule violation but is exactly what a Computer Society prescreener looks for.

## Internal review round 2 (2026-08-19)

Nineteen items (R1–R19). Those that moved or relabelled supplement material:

- **S8** gained the reinterpretation that replaced the withdrawn tail index. The traced
  histogram is not heavy-tailed and not merely "not a power law": it is multi-modal, with a
  mode at 2–4 ms carrying about a tenth of all wakeups and a *light* tail (α ≈ 2) beyond it.
  The mode sits at the EEVDF base slice for an eight-vCPU instance, which makes it the
  two-state model's preempted state observed directly. A bootstrap goodness-of-fit
  (p < 0.0004 over 2,500 replicates) replaces "two estimators disagree" as the evidence
  that the power law is wrong.
- **Every review-history label was relabelled.** Nine sections read "TPDS round 1" and three
  passages referred to "the TC submission" or "the TC revision". Read cold, that implies
  the manuscript was reviewed at two journals. It has been reviewed at none: those were
  internal reviews held before submission. The front matter now says so explicitly, and the
  labels read "internal review, round N".
- **S10** and the S1 chronology are unchanged in substance; only the round labels moved.
- The dither lineage in S27 gained McCanne & Torek, cut from the main text to hold the
  45-reference cap.

Nothing was moved *into* the supplement in this round. The four-point payload fit stays in
S8 where round 1 put it.


## Round 19 (2026-08-24): the co-author round

A co-author's review added five explanations to the main text and one full-width figure. Both
were paid for out of the main text, into four new sections. Everything below left a stub
carrying its claim; nothing lost a number or a citation.

| Supp. section | Content | Moved from |
|---|---|---|
| S24 | The statistical inventory: pooled-variance z, Hodges–Lehmann, TOST, the continuum null, the bootstrap, and the interval-censored tail estimators | main text III-D, which keeps only the three choices a reader might contest |
| S33 | The dispute with the concurrent negative-span report in full --- which queue each account means, and why a millisecond skew threshold does not transfer to a loaded machine | main text II-B (about 140 words) |
| S17 | The 1970 counter note mapped line by line: retention identity, class, the ceiling on averaging, the symptom, the cure | main text II-C (about 100 words) |
| S33 | Two literatures the paper stands against: production tracing's skew adjusters, and where scheduling delay comes from | main text II-B and II-C (about 250 words) |

Three citations moved with S33 and so left the paper's reference list, which is now 42 of the
45 TC allows: the two Jaeger sources and the tail-latency study. They are cited in the
supplement, which carries its own bibliography.

**Not moved, and worth recording why.** The mechanism table (Table II) stayed in the main text
even though the enlarged Figure 5 now does most of its work, because the first internal
review, held to TPDS's standards, asked for it there (item M1) and a gate holds it. Float
packing was tried first --- two pages were three hundred words short each --- and adjusting
`\topfraction` and its neighbours
changed the layout by nothing at all: those pages were not float-starved, the floats were the
content.

## Round 20 (2026-08-24): the internal reviewer's three substantive items

Three defects, three minors and three recommendations, plus the reference cap. Everything the
main text gave up is below; nothing lost a number or a citation.

| Supp. section | Content | Moved from |
|---|---|---|
| S14 | Why the two drivers differ, and how a difference of two floored clocks admits exactly one negative value | main text IV-D (about 130 words) |
| S14 | The continuum null, constructed: replicates drawn Normal around the rate-local value with the incommensurate configurations' pooled SD, 4,000 Monte Carlo draws per test (`MC_ARMS`), one-sided p, and why it has no power where the predictions coincide (described as a permutation null with 10^4 permutations until 29 Sep 2026, which the script never did) | main text IV-C |
| S7 | The overnight campaign prediction by prediction --- the duration-invariance counts that killed the drift account, and the linear extrapolation that failed | main text IV-B |

**The reference cap decided two placements.** Round 20 added five citations to a list of
forty-two and 45 is the cap, so two came back out. `wrk2_src` keeps its entry in S25's
generated table, which cites every audited tool by construction, and loses its per-tool
citation in the main text; the library-refusal class is still counted from the registry and
still described. `swami2026observability` moved to S33.1, beside the Villain argument it
supports, rather than into Section II-B.

**KAFKA-19888 moved the other way**, up from S25 into Section IV-D. The reason it was held
back --- that its mechanism is wall-clock non-monotonicity and would invite confusion with
Mode A --- is right about Mode A and does not apply to Mode B, where the finding is that a
first-party vendor chose the substitution class this paper says is worse than filtering. The
main text names the mechanism so the two cannot be confused.

## Round 22 (2026-08-24): pointers, and a check that could not see

No new sections. Two corrections to round 20's relocations and one to the prose:

- **S14** is now cited by Section IV-C for the permutation null's construction. It had been
  citing S11, which is the per-arm table and does not contain the construction.
- **S14** is now cited by Section IV-D for the two-floored-clocks explanation. It had been
  citing S16, which contains none of that material.
- Section IV-D said the five disposing tools fall "in four classes". The taxonomy has three
  --- `DISPOSAL_KINDS` is `positive_only_filter`, `silent_suppression`, `library_refusal` ---
  and the sentence itself enumerates three. It was the one count in that paragraph still
  typed by hand. `harnessDisposalClasses` is emitted now.

`TestEveryTargetedRelocationIsReachable` holds the first two: every section from S24 onward
must be pointed at from the paper. Sections below S24 are exempt by design --- they are the
TPDS-era bulk moves, documented here rather than pointed at individually.

## Round 24 (2026-08-25): the sweep, and the pointer that costs money

No new sections. Six numbers moved from prose into the ledger, two of them in the supplement:

- `supplement.tex` quoted the payload exponent as `0.339` against a second-day repeat and the
  Hodges--Lehmann shift as `0.408` heading a list of three. Both now read `\tailExponent` and
  `\tostHL`.
- S15 gained a one-paragraph lead saying what Section VI-D now states in a sentence, because
  VI-D gave up the two-part derivation to bring Threats back under the section that carries
  Contribution 2's decisive experiments.

`tests/unit/test_ledger_coverage.py` is the sweep behind the first of those, and
`tests/unit/test_citation_surface.py` gained the page-count check --- the last journal limit
with no gate, and the only one that costs $220 a page.

## Round 26 (2026-08-25): a framework that does not have the problem

- **S33.2 is new**: the reading behind Section VI-B's claim that the reporting rules are
  practical. mq-bench (arXiv:2603.21600, March 2026) stamps in nanoseconds, subtracts a
  send-referenced span on one host, applies no positivity guard, and reports sub-millisecond
  medians --- both of our recommended choices, made independently and argued for nowhere. The
  section quotes its measurement text and notes the one thing it does not do: say why its span
  is safe.
- **S33.3** is the old S33.2, the field-size synthesis, moved down. Its citation left the main
  text so the reference cap could pay for mq-bench; the claim is unchanged and Section II-A
  now points here for it. *(Corrected in round 28: it did not. The pointer was still on S33.2
  when this was written, and this line recorded a repair that had not been made — which is why
  `test_supplement_subsections.py` now checks that a pointer lands on its subject.)*
- The fitted prefactor is `\tailPrefactor` in both places it appears. It was the one quantity
  in `tail_index.csv` with a committed source and no macro, and therefore invisible to the
  round-24 sweep, which asks whether a macro'd value is read from its macro and not whether a
  sourced value has one.

## Round 28 (2026-08-25): subsection numbering, and a figure for the mechanism

- **S33.4 is the old second S33.3.** Round 26 renumbered the field-size synthesis to S33.3 and
  left the scheduling-delay subsection, already S33.3, where it was. Both printed. The
  scheduling-delay subsection is now S33.4 and Section II-C points at it by number.
- **S1.1, S1.2 and S4.1 are newly numbered**, not new. They were the only subsections in the
  document with no `SNN.M` prefix and printed as bare titles in the contents list.
- **Section II-A now really does point at S33.3** for the field-size claim. Round 26's entry
  here said it did; the source said S33.2, which is the mq-bench reading and sizes nothing.
- **S25 keeps the Kafka coordinator fix, and now the main text agrees.** S25 said the case was
  recorded "here rather than in the main text"; the main text carried it in full anyway.
  Section IV-E keeps the claim and the citation in one sentence and sends the reader here.
- **S33, S33.1 and S14** absorbed the reasoning trimmed from Sections II-B, II-C and IV-C to
  pay for Figure 3. No claim left the paper; the arguments behind three of them did.

## Round 30 (2026-08-25): an adjective, and three numbers that were right but typed

- **S15's chrony bounds now come from the ledger.** `\chronyHostBoundLo`,
  `\chronyHostBoundHi`, `\chronyPairBound` and `\chronyHosts` are emitted from the committed
  `chronyc tracking` captures by the function that already computed them. The sentence also
  now says the 12 ms is the sum of the two *worst* hosts, because adding the printed endpoints
  gives 14 and a reader was entitled to try.
- Nothing else in the supplement changed. Section I's "largest mode" was the round's headline
  defect and it is main-text only; S33.4 already said "the last".

## Round 32 (2026-08-25): the tables, and a word that meant something else

- **S15's chrony sentence names its noun and sums the right thing**: "across the
  `\chronyHosts` hosts captured, and the two worst of *those bounds* sum to
  `\chronyPairBound` ms". The hosts do not sum; their bounds do.
- Nothing else in the supplement changed. The round's substantive finding --- that *retention*
  is never defined and collides with Kafka's `log.retention.*` --- is answered in the main
  text's Method section, which is where the paper defines its other terms.

## Round 34 (2026-08-25): the payload sweep joins the ledger

- **Eleven typed copies left the supplement.** `$76.9\times$`, `$77\times$` and
  `$4.1\times$` are `\payloadTransportFactor`, `\payloadTransportFactorRound` and
  `\payloadRateFall`; S26's two-campaign caption reads `\payloadReplTransportFactor`,
  `\payloadRateFallExact` and `\payloadReplRateFall`. Every printed value is unchanged ---
  the macros emit exactly what was typed, which is the point.
- Nothing else in the supplement changed.

## Figure inventory

`docs/results/figures/` holds thirty-one PDFs. Twenty-five are included by at least one
document: five by the main text, nine by the journal supplement and twenty by the postmortem.
Six are included by none and are kept deliberately rather than by oversight: three are listed
below as retained, and three are the candidates of the next section. An internal review round
(13) asked which was which, so the answer lives here instead of in anyone's memory. A test
(`test_every_figure_is_used_or_declared`) fails if a figure appears in the directory without
appearing in this table, and another holds every "main text, Fig. N" below to the number the
paper prints. Supplement and postmortem numbers are those of the 1 October 2026 build, with the
section that carries the figure; both documents number their figures S1, S2, and so on.

| Figure | Where it appears |
|---|---|
| `two_ways` | main text, Fig. 1 (added 28 Sep 2026, the editorial revision: panels (a) and (b) of `deletion_histogram` side by side, so page 1 shows both failures on one population; `scripts/make_deletion_histogram.py --two`) |
| `measurement_model` | main text, Fig. 2 (panel (b) split off round 52) |
| `stall_spectrum` | main text, Fig. 3 |
| `deletion_phases` | main text, Fig. 4 (added 28 Sep 2026: the four-phase drawing of one millisecond beside the retention of every captured setting, mechanism beside consequence; its panel (b) is the former single-panel `deletion` figure, whose file and builder were retired with it; Fig. 5 until v6 put the industry's section before the practical implications) |
| `exposure_curve_column` | main text, Fig. 5 (added 28 Sep 2026: the exposure curve redrawn at column width, because the main text's advice to authors turns on where a path sits on it; Fig. 4 until v6 moved the proxy's cost into Practical Implications) |
| `pipeline_schematic` | supplement, Fig. S1 (S1.5); postmortem, Fig. S16 (S24). The v5 main text defines the timestamps in prose and gives its drawing to the inversion itself, Fig. 2 |
| `integrity_audit` | supplement, Fig. S2 (S2.1); postmortem, Fig. S15 (S18) |
| `delta_schematic` | supplement, Fig. S3 (S3.4); postmortem, Fig. S4 (S9). Redrawn 28 Sep 2026: the waiting state is a shelf to the slice and a tick, the rest of a slice, read after the law campaign's verdicts |
| `recovery_populations` | supplement, Fig. S4 (S3.8); postmortem, Fig. S11 (S16) |
| `quantum_geometry` | supplement, Fig. S5 (S4.2); postmortem, Fig. S13 (S17): a constructed illustration of the retention law, beside the 1970 counter note that carries the same identity |
| `grid_membership` | supplement, Fig. S6 (S4.3); postmortem, Fig. S6 (S11) |
| `payload_flip` | supplement, Fig. S7 (S4.3); postmortem, Fig. S5 (S10) |
| `deletion_histogram` | supplement, Fig. S8 (S4.4); postmortem, Fig. S10 (S14). Asked for by a co-author on 26 Aug 2026; its panels (a) and (b) are also the main text's Fig. 1 |
| `law_slice` | supplement, Fig. S9 (S6.3); postmortem, Fig. S17 (S36): every run of L1 and L4 with every aberrant run marked (`scripts/make_law_figures.py`, marks by `scripts/law_runs.py`) |
| `law_tick` | postmortem, Fig. S18 (S36): L2, L5 and L7, marked the same way |
| `law_load` | postmortem, Fig. S19 (S36): L3 and L8, marked the same way |
| `law_a9` | postmortem, Fig. S20 (S36): L9, with its traced half ringed |
| `wait_shape` | postmortem, Fig. S12 (S16): each acknowledgment's wait against the whole-slice and rest-of-a-slice shapes (`scripts/make_wait_shape_figure.py`) |
| `window_sweep` | postmortem, Fig. S1 (S3). Left the journal supplement on 1 Oct 2026: it re-plotted the table beside it |
| `e1_end_to_end_lag` | postmortem, Fig. S2 (S3) |
| `ttrue_law` | postmortem, Fig. S3 (S8). Left the journal supplement on 1 Oct 2026: Table S10 and Equation S1 carry the same four points and fit |
| `priority_ladder` | postmortem, Fig. S7 (S12). Left the journal supplement on 1 Oct 2026: it re-plotted the priority table beside it |
| `mechanism_forest` | postmortem, Fig. S8 (S12): it plots the matched pairs of the main text's Table II, so it left the main text in round 57 |
| `exposure_curve` | postmortem, Fig. S9 (S12) |
| `experiment_map` | postmortem, Fig. S14 (S18). Left the journal supplement on 1 Oct 2026: its table of claims, campaigns and runs carries the same map |
| `kickoff_concurrency` | **retained, unused.** The kickoff-window concurrency view from the withdrawn first result set. Kept because the campaign it draws is still in the archive and the withdrawal is part of the record; no current claim rests on it. |
| `network_delay` | **retained, unused.** The injected-delay view superseded by the netem table, which reports the same runs numerically. |
| `workload_profile` | **retained, unused.** The StatsBomb replay profile from the 16-page version; the workload is now described in prose. |

## Figures awaiting placement (v3 candidates, 2026-08-30)

Four exhibits built for and after the 28 August co-author call, committed with their scripts
and data but not yet included by any document; the v3 insertion points are recorded in the
local plan. Each also ships a `_talk` PNG variant for slides.

| Figure | Source script | Where it is headed |
|---|---|---|
| `deletion_histogram` | `scripts/make_deletion_histogram.py` | Section IV (Mode B): what the guard deletes, and the five dispositions |
| `thread_architecture` | `scripts/make_thread_figure.py` | Section I or III: which threads take the two stamps, and why |
| `axis_comparison` | `scripts/make_axis_comparison.py` | supplement: the benchmark's published data and ours on identical axes |
| `omb_axes_explained` | `scripts/make_axis_comparison.py` | supplement: why the published chart's own axes cannot show the deletion |
