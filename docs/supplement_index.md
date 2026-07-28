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

The compiled supplement states on its first page that it is not part of the main submission.
Referee report that drove this split: `REFEREE_REPORT_SIMULATED.md` (untracked).
