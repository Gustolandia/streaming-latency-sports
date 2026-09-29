# Summary: published OMB end-to-end results with a 1 ms median

Registration: `freezes/29-published-results-audit/` at 8865e0a1 (fingerprints checked before any
report was read). Coding is in `configurations.csv` (1,251 rows: one per configuration, one per
excluded report). Sources and queries are in `search_log.md`. Row ids (R0001...) refer to
`configurations.csv`. The counts below were recomputed from the CSV by
`scripts/published_results_audit.py`, which is what the manuscript reads.

## The four registered outcomes

**1. Included: 43 reports, 1,100 configurations** (177 examined; 31 unreadable, each with its
reason).

| Source | Reports | Configurations |
|---|---|---|
| Google Scholar (Semantic Scholar has none) | 5 | 53 |
| Web (Google, WebSearch) | 6 | 18 |
| Vendor blogs | 10 | 63 |
| already_read.txt (Vanlightly 2023) | 1 | 1 |
| GitHub text (issue logs, notebook, docs) | 9 | 137 |
| GitHub raw OMB result JSON (default and other branches) | 12 | 828 |

868 configurations print a median (three of them approximate, a range or cut off at an image
edge). Most blog and paper tables print p99, p99.9 or p99.99 without p50.

**2. Median exactly 1 ms: 8 configurations in 2 reports, both GitHub repository text.**

| Rows | Report | Configuration | p50 | p99 |
|---|---|---|---|---|
| R0166, R0169, R0172, R0175, R0178 | rokinmaharjan/openmessaging (GitHub fork of OMB), `bin/scripts/LatencyGraph.ipynb` notebook output, 2023-04-02 | Redis 7.0.9 at 1, 3, 6, 10, 15 MBps, 32 KB | 1.0 | 2.0 |
| R0643, R0650, R0729 | snxmlx/openmessaging-benchmark (GitHub fork of confluentinc's copy), result JSON, 2021-09-20 | NATS max-rate 100 B run 2; NATS max-rate 1 KB run 3; Pulsar ephemeral-10k latency-1 | 1.0 | 49.0; 61.0; 302.001 |

The notebook data underlie Maharjan et al., Telecom 2023, which shows these medians only in its
Figure 4 (a chart). Kopiyka's 2024 thesis reprints that study's p99 table (Redis 2.0) without the
median.

**3. p99 also exactly 1 ms: 0.**

**4. Retained fraction or discard count: stated by none.**
- Some result JSON files carry `totalMessagesReceived` or `consumed`, but none counts the
  end-to-end samples kept or dropped.
- The nearest statements: Vanlightly 2023 on a different OMB bug that "caused the majority of
  the latency data to be lost", and Confluent 2020's "TimeSync workflow".

## Sensitivity (reported only, no rule changed)

- Without the 12 raw-result-file reports: 31 reports, 272 configurations; primary 5 in 1 report;
  strong 0.
- Duplicates: 8 included reports reprint numbers coded elsewhere (51cto and congdonglinux
  reposts, two Confluent pages, and the Souza, Petrov, Kopiyka and Normelli theses). None has a
  1 ms median.
- Narrow reading of "fork" (GitHub forks of openmessaging/benchmark only): snxmlx drops out, so
  the primary is 5 configurations in 1 report.

## Cases the rules did not foresee (in `notes`)

1. p99 of 1 ms with no printed median.
   - dao-jun/benchmark, branch `dev/asp_perf`, `doc/performance_test.md` (2024), Pulsar without
     journal at 100k msg/s: average 1.01-1.03, P95 1.0, P99 1.0, and P999 1.0 in two rows (R1170,
     R1171, R1186, R1187, R1194, R1195). Values are whole milliseconds; there is no median column.
   - Confluent 2020 "1 ms*" for RabbitMQ (R0003) and its 51cto repost (R0105). The linked
     `mirrored-30k.json` prints p99 1.006 and p50 0.482, so this is a rounding.
2. Medians of 0.0 (empty histogram): Pravega fork issue 18 (R0158; consuming 20.8 msg/s), snxmlx
   R0765, and BewareMyPower R0921 and R0922.
3. Forks without whole-millisecond values: Confluent, Redpanda, StreamNative (`blog` branch),
   AutoMQ (after "fix E2E latency precision problem", June 2023), duyvu1109, KaimingWan and part
   of snxmlx print sub-millisecond percentiles. In snxmlx, the 1.0 medians sit in
   whole-millisecond max-rate files; its low-rate NATS latency workloads print 0.34-0.61 ms
   medians, different workloads, so not a like-for-like pair. Upstream OMB computes
   `MILLISECONDS.toMicros(now - publishTimestamp)`.
4. Pre-August-2019 files write aggregated end-to-end values in microseconds (fixed by OMB PR 150).
   rdhabalia's 38 files are flagged, and none is 1000.0.
5. Detached forks. confluentinc, redpanda-data, pravega and AutoMQ are not GitHub forks. Copies of
   OMB's code found by repository search were included, with their fork networks: 404
   repositories.
6. Raw result files with no prose. Criterion (a) was read as met by their location in a named
   fork. Each repository (or repository and branch) is one report; each file is one
   configuration.
7. Tables printed as images were read as printed numbers, not charts. Two cells cut off at the
   image edge are marked "[cut]".
8. Bounds were not treated as values ("sub-5ms", "under two seconds"). Approximate or verbal
   values were coded as printed.
9. Ambiguous metric or tool: Katta 2022 does not say whether its p99 is end-to-end (excluded);
   Aiven's deep dive credits "Kafka performance tools and" OMB (included, flagged); AutoMQ's own
   perf tool was not treated as OMB; StreamNative's 2020 full report never names OMB, though its
   summary post does (excluded).
10. Result archives were not opened (e.g. rokinmaharjan's `results/*.zip`).
11. Sources not fully searchable: Google Scholar was blocked for about an hour, then searched in
    full (51 and 32 results); Semantic Scholar's full-text snippet API stayed rate-limited and
    its title/abstract index has no "openmessaging" paper; web engines returned fewer than 50
    results (Google 23 and 2, WebSearch 9 and 9); the Maharjan thesis was not examined, because it
    needs a browser download.

## Basis for the paper's reach sentence

- Primary: 8 configurations in 2 reports, both public GitHub repository text; none in a blog,
  vendor page or paper.
- Strong: 0.
- Discard statements: none.
