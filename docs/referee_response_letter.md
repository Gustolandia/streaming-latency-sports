# Response to the referee report (simulated TPDS/TC review)

Source report: `REFEREE_REPORT_SIMULATED.md` (untracked). Every major concern, minor comment and
question, with the action taken and where the evidence lives. Items marked *(chain18)* draw on
the referee campaign `reproducibility/campaign_logs/omb_chain18.sh`.

## Major concerns

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

## Minor comments

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

## Questions

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
