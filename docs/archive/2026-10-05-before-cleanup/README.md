# The paper and supplement before the cleanup of 5 October 2026

The paper was rebuilt around its four bottom lines on 5 October 2026: the distribution of
S = t_recv - t_ack, the mechanism and its laws, the industry-wide audit, and what to do. Most of
its text moved to the supplement, and the supplement was then cut to what those four points need.

This folder keeps both documents as they stood before, so nothing that was cut is lost:

| File | What it is |
|---|---|
| `paper.tex`, `paper.pdf` | the 12-page paper, "Faster than Light: Silent Errors in the Latency Benchmarks Used to Choose Message Brokers" (commit 5c69edcf) |
| `supplement.tex`, `supplement.pdf` | its 33-page supplement, sections S1 to S9 |

The sources are kept as a record and are not built: they read the generated numbers and figures
of the repository as it was at that commit, which `git show 5c69edcf:<path>` recovers.
