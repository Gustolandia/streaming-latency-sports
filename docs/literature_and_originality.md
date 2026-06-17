# Literature Context & Originality Assessment

**Date:** 2026-06-17 · **Purpose:** decide whether this work has a publishable original
contribution (per the corrected results), before investing in a full submission.

## 1. What the literature already covers

**Kafka vs Redis latency — heavily covered, mostly grey literature.** Numerous engineering
benchmarks compare the two. A recurring finding mirrors ours: Redis wins on throughput /
average latency (in-memory), while **Kafka wins on tail-latency consistency** (batching,
log architecture). Peer-reviewed work exists for *message brokers generally* (e.g. arXiv
surveys of distributed broker queues; IoT-edge broker benchmarking) but Kafka-vs-Redis-
Streams specifically is dominated by vendor/Medium posts, not journals.

**Cluster vs single, throughput/latency trade-offs** — well studied (e.g. Kafka clustering
trades ~3× latency for negligible throughput penalty; LinkedIn's classic numbers).

**Sports-data latency requirements** — exist only as *industry* guidance (Dolby, Sportmonks,
betting-platform blogs): betting <500 ms (micro-betting even tighter), broadcast 5–10 s,
etc. Not academically formalized.

**Cross-process clock pitfalls** — a known measurement hazard (clock drift, wall-clock vs
monotonic, MPI-benchmarking-reproducibility literature), but rarely presented as a concrete
"a subtle clock choice silently reversed our headline result" case study.

## 2. Honest originality verdict

| Framing | Original? | Why |
|---|---|---|
| "Kafka vs Redis: which is faster?" | ❌ No | Saturated; mostly non-academic; our absolute numbers are single-machine, compressed-replay artifacts with limited external validity |
| "Sports-specific streaming benchmark (StatsBomb replay + actionability windows)" | 🟡 Modest | The sports framing + open-data replay harness is relatively unexplored academically, but the thresholds come from grey literature and the setup is a single host |
| "Reproducibility/measurement-validity case study" | 🟢 Best angle | We have a *documented, before/after* example where a process-relative clock + a saturating load generator produced a confident but **wrong** conclusion ("Redis 71× faster"), and correcting it **reversed/nuanced** the finding. That is a genuine, teachable methodological contribution with real data |

**Bottom line:** As a head-to-head latency paper, there is little novel here. The defensible
contribution — if any — is **methodological**: a reproducible, open harness plus a worked
cautionary tale on cross-process timing and load-generator saturation in streaming
benchmarks, demonstrated on a sports workload, with the corrected (regime-dependent)
result: Kafka faster for isolated feeds, Redis better under high concurrency.

## 3. Honest caveats that limit any claim

- **Single commodity host**, Docker, compressed 120× replay — not a production/distributed
  deployment; absolute latencies are not directly transferable.
- **Single feed per run** in the core matrix; "concurrency" is the separate RQ2 set.
- **Sports thresholds are not our own** (industry sources); the sports angle is framing.
- Underpowered for small effects (only large effects are reliably detected).

## 4. Recommendation

Before writing a full submission, decide the framing:
1. **Methodology / reproducibility venue** (e.g. a benchmarking or reproducibility track) —
   lead with the clock/saturation cautionary tale + open harness. Most honest fit.
2. **Sports-analytics venue (JSA)** — lead with the open StatsBomb replay harness and
   actionability mapping; the broker comparison is secondary. Needs the sports thresholds
   properly sourced/justified and ideally validated against a real deployment.
3. **Do not submit as a generic "Kafka vs Redis" benchmark** — it would not clear novelty.

## Sources
- [Kafka vs Redis benchmark (Medium)](https://medium.com/@praneeth.yerrapragada/kafka-vs-redis-i-benchmarked-both-and-the-results-surprised-me-6ae0e304031b)
- [A Survey of Distributed Message Broker Queues (arXiv)](https://arxiv.org/pdf/1704.00411)
- [Benchmarking Message Brokers for IoT Edge Computing (arXiv)](https://arxiv.org/pdf/2603.21600)
- [MPI Benchmarking Revisited: Experimental Design and Reproducibility (arXiv)](https://arxiv.org/pdf/1505.07734)
- [Clock sources in Linux — measuring latency](http://btorpey.github.io/blog/2014/02/18/clock-sources-in-linux/)
- [The Latency Debate in Live Sports (Dolby)](https://optiview.dolby.com/resources/blog/sports/the-latency-debate-in-live-sports-consistency-vs-speed/)
- [Low-latency sports betting streaming (Ververica)](https://www.ververica.com/blog/modernizing-sports-betting-technology-to-empower-live-odds)
- [StatsBomb Open Data](https://github.com/statsbomb/open-data)
