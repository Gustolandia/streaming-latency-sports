# The campaign ledger schema

One row per cell of every instrumented-benchmark campaign, in
`docs/results/external_campaigns_index.csv`.

This lived in the supplement until it was moved here, beside the file it describes: a
column dictionary is reference material, and it carried the highest overlap with the
manuscript of any section in that document. The supplement keeps a one-paragraph summary
and points here.

One row per cell of every instrumented-benchmark campaign,
`docs/results/external_campaigns_index.csv`:

- `campaign`, `cell` -- sub-campaign directory and cell name; the cell name
  encodes the swept axis (`l` load percent, `s` message size, `r` producer
  rate) and replicate number, e.g.\ `r625_rep3`.

- `level` -- the numeric value of the swept axis.

- `valid` -- 1 if the cell's counts are usable under the pre-stated rule; 0 rows are
  retained with a reason, never deleted.

- `count_source` -- `shutdown_hook` for exact end-of-run counters;
  `periodic_quantised` for in-run lines (quantized to 10^4, excluded from analysis);
  `none_in_log` when no counters were written.

- `kept`, `discarded_zero`, `discarded_negative` -- the instrumented
  guard's three counters, separated by sign.

- `log_bytes`, `log_sha256` -- size and hash of the run log the row was
  built from, so any row can be re-derived and checked against its source.

The Python-harness campaigns (no JVM, Section on generality in the main text) use the same cell
naming and publish `docs/results/external/harness_results.csv` with per-cell counts,
sign-separated discards, and pacer-jitter percentiles.
