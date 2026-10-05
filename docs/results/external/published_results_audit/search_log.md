# Search log: registered audit of published OMB end-to-end results

Registration: `freezes/29-published-results-audit/audit_plan.md` and `already_read.txt`, commit 3b82667b
(branch fix/editorial-revision). Both files were checked against the folder's `SHA256SUMS` before any search
(audit_plan.md 8449a0ad…67b9, already_read.txt 30eb215c…deb; both match). Nothing in the repository was modified.

Work ran 2026-09-28 from 21:59 to about 23:50 UTC (22:59 to 00:50 Irish time); every retrieval date in
`configurations.csv` is 2026-09-28 (UTC). All raw material (saved pages, text renderings,
PDFs, API dumps, scan logs, scripts) is in `reach_audit/raw/`.

Tools. WebSearch and WebFetch as instructed; `curl` for raw copies used to verify quotes mechanically and for
the Semantic Scholar API; the `gh` CLI for GitHub; the built-in browser only where a page would not fetch
(Google and Google Scholar result pages, Semantic Scholar's JavaScript site, MDPI, Medium, 51cto, pipecode,
Baylor, ACM). No CAPTCHA or bot check was solved or bypassed; no file was downloaded through the browser; one
cookie banner (ACM) was answered with "Use necessary cookies only".

Every quote in `configurations.csv` was checked by `raw/build.py`: for text sources the quote (whitespace-
normalised) must occur in the saved source text and every number coded in the p50/p99 columns must occur in the
quote (0 failures in the final build). JSON quotes are asserted against the saved result file. Rows marked as
image or browser sources were read twice by eye (table images at 2x zoom).

---

## Source 1: Google Scholar and Semantic Scholar ("every result")

### Semantic Scholar

| Query (as run) | Where | Result |
|---|---|---|
| `"OpenMessaging Benchmark"` | Graph API `/paper/search/bulk` (phrase syntax; title+abstract index), 21:59 UTC | total 0 |
| `openmessaging + "end-to-end latency"` | same | total 0 |
| `OpenMessaging`, `openmessaging`, `"OpenMessaging"`, `OpenMessaging Benchmark` | same (checks) | 0 each; control `Apache Kafka` returns 1,456 and `"Apache Kafka"` 1,267, so the endpoint works |
| `OpenMessaging Benchmark` | Graph API `/paper/search` (relevance) | HTTP 429 (shared unauthenticated pool), 6 tries 20 s apart at 22:00 UTC, retried 23:00 UTC: 429 |
| `"OpenMessaging Benchmark"`, `openmessaging "end-to-end latency"` | Graph API `/snippet/search` (full-text snippets) | HTTP 429 on every try (4 + 3); **not run** |
| `"OpenMessaging Benchmark"` | website (browser) | "Sorry, we couldn't find any papers about ." then an automatic fallback "Results for OpenMessaging Benchmark (without quotes)" listing unrelated benchmarks (not coded) |
| `openmessaging "end-to-end latency"` | website (browser) | "About 7,830 results": the site treats `openmessaging` as optional and lists generic end-to-end-latency papers |
| `openmessaging` | website (browser) | "No Papers Found. Sorry, there are no results for openmessaging" |

Conclusion: in Semantic Scholar's title/abstract index no paper contains "openmessaging", so both registered
queries return zero relevant results there. Its full-text snippet search could not be run (rate limit).

### Google Scholar

First attempts (22:04 UTC) were blocked on all routes: browser "Our systems have detected unusual traffic from
your computer network" page; WebFetch and curl redirected to google.com/sorry. Not bypassed. A retry in the
browser at about 23:00 UTC succeeded without any challenge, and both queries were paged to the end
(`hl=en`, 10 per page).

**Q1 `"OpenMessaging Benchmark"`: 51 results (6 pages).** Rank, title, disposition (row id in
`configurations.csv` via `report_url`; ids below are the coder's ids used in `raw/rows_*.py`):

1 Benchmarking message queues (Maharjan et al., Telecom 2023) - excluded, figures only (web_mdpi_bmq) ·
2 Comparative evaluation of JVM-based message queue services (Chy et al., Electronics 2023) - excluded, figures only ·
3 A review of comparative studies ... microservices (ICCSA 2025) - unavailable (paywall) ·
4 Characterization and Benchmarking of Message-Oriented Middleware (2021) - unavailable (paywall) ·
5 Understanding the Latency-Security Tradeoff ... TEE (2025) - unavailable (IEEE) ·
6 A Capability Maturity Framework ... Kafka and Pulsar (Katta 2022) - excluded, metric not stated as end-to-end ·
7 Pravega: A tiered storage system for data streams (Middleware 2023) - excluded, write latency only (read via Middleware '23 OpenTOC) ·
8 Microservice decomposition and message queues (Maharjan thesis 2023) - not examined (browser download needed) ·
9 Efficiency comparison of message brokers (JCSI 2024) - excluded, no percentile ·
10 "Back to the Byte" (Middleware 2024) - unavailable (ACM) ·
11 Nexus (FAST'27 pre-publication) - excluded ·
12 Evaluation of Message Brokers ... (Schumeth 2024) - excluded, OMB only in related work ·
13 Message-Oriented Middleware Systems: Technology Overview (arXiv 2026) - excluded ·
14 Leveraging Apache Kafka ... (Koney 2025) - excluded ·
15 Benchmarking Message Brokers on Kubernetes (Normelli, KTH 2024) - **included** (sch_normelli2024) ·
16 ОБРАБОТКА ИНФОРМАЦИИ ... (Kargin) - unavailable (no link) ·
17 A Comparative Analysis of Message Brokers ... (CITS 2024) - unavailable (no link) ·
18 OpenMessaging Benchmark Framework (citation entry) - not a report ·
19 Fine-Grained Code Change Collection (Google Books) - unavailable ·
20 A Study of the Capabilities of MOM Systems (Al-Manasrah thesis 2023) - excluded ·
21 A Unified Architecture for Inter-Commit Fine-Grained Code Change Collection (Springer 2026) - unavailable ·
22 A comparative analysis of Apache Kafka and Apache Pulsar (Andström 2024) - unavailable (HTTP 401) ·
23 Towards low-latency big data infrastructure at Sangfor (2022) - unavailable (paywall) ·
24 A Decade of Horizontal Fragmentation Methods in OLAP (2026) - excluded ·
25 Design and implementation of accelerator control monitoring system (2023) - excluded (throughput only) ·
26 Performance analysis between Apache Kafka and RabbitMQ (Souza 2020, UFCG) - **included** (sch_souza2020) ·
27 One-Size-Fits-None: slow-fault tolerance (NSDI 2025) - excluded ·
28 BEYS (Turkish, 2026) - excluded ·
29 Ursa (VLDB 2025) - excluded ·
30 Towards Low-Latency Big Data Infrastructure (Google Books; same as 23) - unavailable ·
31 Design and implementation of storage benchmark kit (Springer 2021) - excluded (SBK results) ·
32 Análise comparativa de soluções de mensageria ... (Nobrega & Borges 2024, UFRJ) - **included** (sch_nobrega2024) ·
33 Porównanie wydajności brokerów wiadomości (Polish version of 9) - excluded ·
34 KafkaDirect (SIGMOD 2022) - unavailable (ACM) ·
35 ByteMQ (SoCC 2024) - unavailable (ACM) ·
36 Prestandaanalys av meddelandesystem ... (Tagesson & Davoust 2024) - excluded ·
37 Empirical Foundations for Energy-Efficient Distributed Streaming Infrastructure (Govind 2026) - unavailable (HAL anti-bot) ·
38 DeepTrends (SSRN) - unavailable (403) ·
39 Apache Kafka Clients Benchmark (Castro, UPM) - excluded (results from Kafka Ducktape tests) ·
40 RocketHA (ASE 2023) - unavailable (IEEE) ·
41 Design of QoS-constrained Dataflows ... (Silva 2020) - excluded ·
42 Distributed streaming storage performance benchmarking: Kafka and Pravega (IJITEE 2019) - excluded (SBK; OMB throughput only) ·
43 ePulsar (2021) - unavailable ·
44 A scalable data pipeline for realtime geofencing using Apache Pulsar (2021) - unavailable (HAL anti-bot, paywall) ·
45 Разработка приложения потоковой передачи ... (Petrov 2024, URFU) - **included** (sch_petrov2024) ·
46 Separation is for better reunion: Data lake storage at Huawei (ICDE 2024) - excluded, figures only ·
47-48 Sistema de orquestación ... (Calvo Rubió TFG, two entries) - excluded ·
49 Virtual log-structured storage for high-performance streaming (KerA, 2021) - unavailable ·
50 Smart Monetization - Telecom Revenue Management (Firmino 2019) - excluded ·
51 Розробка фреймворку для масштабованої ETL-системи (Kopiyka 2024, UKMA) - **included** (sch_kopiyka2024).

**Q2 `openmessaging "end-to-end latency"`: 32 results (4 pages).** Ranks that repeat Q1 items: 1(=Q1 1), 2(=2),
3(=7), 4(=22), 7(=10), 8(=29), 9(=31), 10(=42), 11(=27), 12(=23), 13(=26), 14(=30), 15(=43), 16(=15), 17(=34),
19(=38), 20(=14), 24(=8), 28(=37), 30(=49). New in Q2: 5 EdgeRIC (NSDI 2024) - excluded ("open messaging
standards") · 6 RIO (arXiv 2026) - excluded (no OMB mention) · 18 Quality of service for CAMX middleware (2006) -
not examined in full, predates OMB · 21 Balancing Sensor Communication ... MQTT/CoAP (IEEE 2026) - unavailable ·
22 Open-source publish-subscribe systems: A comparative study (2022) - unavailable · 23 Resilience in edge
computing (2025) - excluded ("Open Messaging Interface") · 25 FEEDEZ (2026) - unavailable · 26 Agents for Data
Streaming Tasks (2026) - excluded (reference only) · 27 SMTP proxy (2024) - excluded ("open messaging system") ·
29 A survey of SSD simulators (2025) - unavailable · 31 Neutrosophic ... MQTT (2025) - unavailable ·
32 A low power sleepy network design ... (2026) - unavailable.

Full texts were read from the links Scholar gives (publisher, repository or author PDF). Where the Scholar entry
had no link, one title lookup was run to find the full text (see "Lookups" below).

---

## Source 2: the web (first 50 results of each exact-phrase query)

| Query | Engine | Results |
|---|---|---|
| `"OpenMessaging Benchmark" "end-to-end latency"` (W1) | WebSearch tool | 9 (no paging available) |
| `"openmessaging benchmark results"` (W2) | WebSearch tool | 9 |
| W1 | Google, browser, `hl=en` (Irish IP) | 22 by default ("omitted some entries very similar to the 22 already displayed"); **23 with omitted entries included (`filter=0`)**; no further pages, so fewer than 50 exist |
| W2 | Google, browser, `hl=en`, `filter=0` | **2** |
| W1 | Bing via WebFetch | unusable (returned an unrelated clothing results page) |
| W1 | Bing in browser | "Aucun résultat" (implausible; not used) |

Google result URLs were resolved from Google's `/goto` tokens with a HEAD request (`raw/resolve_goto.py`), not
followed. Ranks below are those of the `filter=0` list.

W1 Google: 1 confluent.io/es-es/compare/kafka-vs-pulsar (included) · 2 dimster-hq/dimster (excluded) ·
3 ResearchGate figure fig1_371550505 (unavailable) · 4 aklivity Zilla (excluded) · 5 pipecode.ai Redpanda deep
dive (excluded) · 6 LinkedIn repost of AutoMQ x FSx (excluded) · 7 SBK PDF (excluded) · 8 SoftwareMill Kafka vs
Pulsar (excluded) · 9 device.report PDF (Cloudflare; same paper read as Scholar Q1 42, excluded) · 10 McKnight
2024 Redpanda vs Confluent PDF (included) · 11 blog.51cto.com repost of Confluent 2020 (included, duplicate) ·
12 Platformatory/kafka-performance-suite (excluded) · 13 congdonglinux.com repost of Redpanda KRaft 2023
(included, duplicate) · 14 ACM "Back to the Byte" (unavailable) · 15 Scribd KafkaDirect (unavailable) ·
16 ResearchGate figure fig3_371550505 (unavailable; only with filter=0) · 17 LinkedIn Fluss post (excluded) ·
18 Redpanda white paper PDF (included) · 19 ELares/IronBus issue 111 (excluded) · 20 ResearchGate SBK
(unavailable; same work as 7) · 21 Confluent podcast RSS (excluded) · 22 robot-head/crabka bench README
(excluded) · 23 Scribd upload of Souza 2020 (same document coded from UFCG).

W1 WebSearch: Confluent Tier-1 bank (blog; excluded, bound only) · docs.redpanda.com benchmark (excluded) ·
developer.confluent.io/learn/kafka-performance (included, duplicate value) · Redpanda self-hosted benchmarking
(blog; excluded) · ActiveWizards (excluded) · arXiv 2002.07162 AIBench (excluded) · openmessaging.cloud/docs/
benchmarks (excluded) · Platformatory blog (excluded) · jeqo.dev intro to OMB (excluded).

W2 Google: automq.com how-to-perform (blog; excluded, AutoMQ perf tool) · Scribd Souza 2020 (as above).
W2 WebSearch: docs.redpanda.com (as above) · github.com/openmessaging/benchmark, datastax, streamnative and
redpanda-data OMB repositories (examined under the GitHub source) · Redpanda self-hosted (as above) ·
openmessaging.cloud/docs/benchmarks/kafka (excluded) · arXiv 2602.17774 (excluded) · openmessaging.cloud/docs/
benchmarks (as above).

---

## Source 3: the nine engineering blogs

Method: every post URL in each blog's sitemap was fetched (3 requests at a time per site) and scanned for
`openmessaging` (case-insensitive, raw HTML including links) or the word `OMB` (case-sensitive, text); every hit
was read (`raw/scan_blogs.py`, per-site results `raw/scan_*.tsv`).

| Blog | Sitemap | Posts scanned | HTTP errors | Posts mentioning OMB |
|---|---|---|---|---|
| Confluent | confluent.io/sitemap.xml (/blog/*) | 1,399 | 0 | 2 |
| StreamNative | streamnative.io/sitemap.xml (/blog/*) | 356 | 0 | 10 (+1 full report reached by link, not flagged: no OMB mention) |
| Redpanda | redpanda.com/sitemap.xml (/blog/*) | 437 | 1 (404) | 9 |
| AutoMQ | automq.com/sitemap.xml (/blog/*) | 1,524 | 0 | 11 |
| WarpStream | warpstream.com/sitemap.xml (/blog/*) | 63 | 0 | 2 |
| Aiven | aiven.io/sitemap.xml (/blog/*) | 525 | 0 | 2 |
| Instaclustr | post-sitemap.xml | 700 | 0 | 1 |
| Ververica | blog/sitemap-blog.xml | 86 | 0 | 0 |
| OpenMessaging project | no sitemap (404); docs/benchmarks and its 4 sub-pages, /blog and the 10-item news feed read by hand | 16 pages | 0 | 2 news posts, 5 docs pages |

Cross-check: Google `site:` searches for `openmessaging` on confluent.io (9 results), streamnative.io (6),
redpanda.com (3), automq.com (9) and warpstream/aiven/instaclustr/ververica combined (2) found no blog post missing
from the sitemap scan. They did surface non-blog pages outside the registered source (logged, not coded):
Confluent Current session "OpenMessaging Benchmark: Measuring the Performance of ...", Kafka Summit 2023 talk
page, a Confluent forum thread, StreamNative /reports/ and /recordings/ pages, and docs.automq.com benchmark and
"性能报告" pages. Limitation: sitemaps list current posts; a legacy URL (StreamNative /blog/tech/…) was found
dead (404) and its moved copy coded.

---

## Source 4: GitHub (openmessaging/benchmark and its public forks)

- **openmessaging/benchmark**: 459 issues and PRs (114 issues, 345 PRs; numbers 1-465), 402 issue comments and
  163 review comments downloaded and scanned for end-to-end terms with digits; 18 texts matched and were read.
  None prints an OMB end-to-end result: console logs in #141, #171, #275 and a comment on #199 print publish
  latency only (OMB's console never prints end-to-end values); #452's numbers are hypothetical; #216 prints none.
- **Which forks.** GitHub's fork graph of openmessaging/benchmark has 284 repositories (recursive). The main vendor
  forks are *detached* copies, not GitHub forks (confluentinc, redpanda-data, pravega, AutoMQ are `fork=false`;
  streamnative's is a fork of confluentinc's). Detached copies were found with `gh search repos`
  (`openmessaging-benchmark in:name`, `openmessaging benchmark in:name`, `omb in:name openmessaging`,
  `"OpenMessaging Benchmark" in:description`, `"OpenMessaging Benchmark" in:readme`, `openmessaging in:name`) and
  kept when their root contains OMB's code (benchmark-framework, driver-api): 14 seeds (confluentinc,
  redpanda-data, pravega, AutoMQ, Vanlightly custom, hstreamdb, mmaslankaprv, leapsky, lthiede, OrderLab, duyvu1109,
  seolzero, iqbalhanif313, Camjo-AB). Their fork networks were added: **404 repositories** in total. Code search
  (`"package io.openmessaging.benchmark"`) is capped at 100 hits and added nothing.
- **Default branches** (`raw/scan_forks.py`): issues and comments of every repository with issues enabled
  (14 had issues); every text-like file (json, md, txt, html, csv, ipynb, log, …) whose blob differs from
  upstream fetched and scanned for OMB result keys or end-to-end lines with digits. 10 repositories returned an
  empty tree. Hits: result JSON in snxmlx (513 files), Camjo-AB (99), confluentinc (12), duyvu1109 (3),
  seolzero (1), KaimingWan (1); text in 7 repositories (read; 3 coded); issue comments in pravega, redpanda-data,
  jeqo, KaimingWan, AutoMQ, streamnative (read; 5 coded).
- **Non-default branches** (`raw/scan_branches.py`, `scan_branches_resume.py`): every branch of every repository,
  skipping branch heads already seen and files identical to upstream (all branches) or to the repository's own
  default branch. 4,149 branch entries over 404 repositories: 637 distinct branch heads scanned in 179
  repositories, 3,472 skipped as commits already scanned, 40 upstream baseline entries; no truncated tree. The
  run stalled once (a hung call) and was resumed from repository 349 with call timeouts, and payload data
  directories (`payload/`, e.g. 3,601 `.out` files on tonydongkong's `keg_poc` branch) were skipped in the
  resumed part. Hits: result JSON on streamnative `blog` (124 files), rdhabalia `test-single-hdd` (38; aggregated
  end-to-end fields in microseconds, pre-PR #150), chosh31 `benchmark-test` (18), BewareMyPower
  `bewaremypower/deploy-kop` (16), 315157973 `executor` (2), SravanthiAshokKumar `changingSub` (1); text in
  dao-jun `dev/asp_perf` `doc/performance_test.md` (results tables, coded), and 8 other texts without results
  (laserdata x2, s2-streamstore, Denovo1998, ankitk-me, kevinhan88 notebooks without outputs, oleiman,
  Vanlightly `kraft-implementation`).
- Archives (e.g. rokinmaharjan/openmessaging `results/Latency.zip`, a zip attached to jeqo issue 1) were not
  opened: not repository text.

---

## already_read.txt

Vanlightly 2023 (included), Mukkolakkal 2026 Pulsar report (excluded: tool not named), AutoMQ methodology
(excluded: no results), OMB issues/PRs 56, 216, 247, 398, 452 (excluded). All coded by the same rule.

## Lookups outside the registered queries (to reach registered items only)

These were run only to locate the full text of an item already returned by a registered source; their other
results were **not** added to the audit.

- WebSearch `"OpenMessaging Benchmark Framework is utilized in two studies"` (to identify the paper behind the
  ResearchGate figure pages; identity with MDPI "Benchmarking Message Queues" probable, not confirmed).
- WebSearch `"Benchmarking Message Brokers on Kubernetes" Normelli KTH diva` (Scholar Q1 15 had no link).
- WebSearch `"Prestandaanalys av meddelandesystem och databaser för en patientjournal" diva` (Q1 36).
- WebSearch `"Understanding the Latency-Security Tradeoff" ... pdf` (Q1 5; no open copy).
- The project's own bibliography (`manuscript_references.bib`) was read to get the URL of the already_read.txt
  item mukkolakkal2026pulsar.

## Things that could not be searched or read

Google Scholar was blocked for the first hour (retried successfully). Semantic Scholar's full-text snippet search
was rate-limited throughout. Web engines returned fewer than 50 results per query. Unavailable items are listed
with reasons in `configurations.csv` (paywalls, HAL anti-bot pages, Cloudflare checks, ResearchGate, a 401).
