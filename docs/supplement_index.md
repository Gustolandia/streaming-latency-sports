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
