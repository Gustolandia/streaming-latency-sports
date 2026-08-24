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


## Figure inventory

`docs/results/figures/` holds fifteen PDFs. Twelve are included by a document; three are not,
and are kept deliberately rather than by oversight. Referee round 13 asked which was which, so
the answer lives here instead of in anyone's memory. A test
(`test_every_figure_is_used_or_declared`) fails if a figure appears in the directory without
appearing in this table.

| Figure | Where it appears |
|---|---|
| `pipeline_schematic` | main text, Fig. 1 |
| `measurement_model` | main text, Fig. 2 |
| `deletion` | main text, Fig. 3 |
| `grid_membership` | main text, Fig. 4 |
| `payload_flip` | main text, Fig. 5 |
| `mechanism_forest` | main text, Fig. 6 |
| `ttrue_law` | main text, Fig. 7 |
| `stall_spectrum` | main text, Fig. 8 |
| `experiment_map` | supplement |
| `integrity_audit` | supplement |
| `window_sweep` | supplement |
| `e1_end_to_end_lag` | supplement |
| `kickoff_concurrency` | **retained, unused.** The kickoff-window concurrency view from the withdrawn first result set. Kept because the campaign it draws is still in the archive and the withdrawal is part of the record; no current claim rests on it. |
| `network_delay` | **retained, unused.** The injected-delay view superseded by the netem table in Section VI, which reports the same runs numerically. |
| `workload_profile` | **retained, unused.** The StatsBomb replay profile from the 16-page version; the workload is now described in prose in Section III. |
