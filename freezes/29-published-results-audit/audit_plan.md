# A registered audit of published OpenMessaging Benchmark latency results

Frozen before any report is read for this audit. This folder is a separate, small study, not a
version of the law campaign's plan (freezes 01 to 28). Its rule is the rule of every freeze here:
committed and public before the work it covers, never edited, fingerprinted in `SHA256SUMS`.

## The question

The paper shows that the OpenMessaging Benchmark (OMB) computes its end-to-end latency from two
millisecond timestamps and keeps a sample only when the difference is strictly positive. On a
path faster than a millisecond most samples compute to zero and are deleted; every sample that
survives computes to exactly 1 ms. The paper can say what this does to a run. It cannot yet say
whether any *published* result sits in that regime. This audit counts them.

## The signature, fixed now

Every end-to-end sample OMB records is a whole number of milliseconds, so every end-to-end
percentile it prints is a whole number of milliseconds whatever the path length. Grid membership
alone therefore identifies nothing. What identifies the deletion regime is the *value*:

- **Primary signature.** A printed end-to-end **median of exactly 1 ms** (1, 1.0, 1.00 ...).
  One millisecond is the smallest end-to-end value OMB can print, and it is the value every
  retained sample takes when the true delivery is shorter than the resolution. A result with
  this median was computed from a retained fraction the report does not state.
- **Strong signature.** A printed end-to-end **p99 of exactly 1 ms** as well: the distribution
  has collapsed onto the grid, as in the paper's own uninstrumented runs.

Neither signature says a published number is wrong. It says the number came from an unstated
fraction of the samples taken.

## Where reports are sought (fixed now)

1. Google Scholar and Semantic Scholar: the exact phrase "OpenMessaging Benchmark", and
   "openmessaging" together with "end-to-end latency"; every result.
2. The web: the exact phrases "OpenMessaging Benchmark" "end-to-end latency", and
   "openmessaging benchmark results"; the first 50 results of each query.
3. The engineering blogs of the vendors whose products OMB drivers exist for and who publish
   broker benchmarks: Confluent, StreamNative, Redpanda, AutoMQ, WarpStream, Aiven,
   Instaclustr, Ververica, and the OpenMessaging project's own pages.
4. GitHub: repositories and issues of `openmessaging/benchmark` and its public forks whose text
   prints OMB result numbers.

Reports dated up to 28 September 2026 are in scope. Reports this project had already read for
other reasons (listed in `already_read.txt` beside this file) are coded by the same rule; the
registration fixes the rule, not the reader's ignorance of the sources.

## Inclusion

A report is included if it (a) states that its results were produced by OMB or a named fork of
it, and (b) prints at least one numeric **end-to-end** latency percentile for at least one
configuration. Publish latency is excluded: OMB records it in microseconds and it is not subject
to the positivity filter. A figure read off a chart is excluded; only printed numbers count.

## Coding (one row per configuration a report prints)

`report_url, report_date, retrieved, tool (OMB or fork), broker, configuration, e2e_p50_ms,
e2e_p99_ms, other_e2e_percentiles, quote` -- the quote is the text or table cell the numbers
were copied from. A report's own rounding is recorded as printed.

## Outcomes, fixed now

- Number of included reports and configurations.
- Primary: configurations, and reports, with a printed end-to-end median of exactly 1 ms.
- Strong: of those, configurations whose printed end-to-end p99 is also exactly 1 ms.
- Whether any included report states a retained fraction or a discard count (the paper's own
  source reading predicts none).

The counts are reported as they fall, including zero. The paper's sentence on reach is written
from them after the audit, and says which of the three outcomes it rests on.
