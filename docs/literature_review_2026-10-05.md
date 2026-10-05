# Literature and grey-literature review for the rebuilt paper (5 October 2026)

The paper was rebuilt on 5 October around four bottom lines: the distribution of
S = t_recv - t_ack, the mechanism and its laws, an industry-wide audit, and what to do. This
review asks, for each, what is already known, so that the paper claims only what is new and
uses the field's own words. It extends [`grey_literature_review.md`](grey_literature_review.md)
(August 2026), which covered coordinated omission, timer granularity, the benchmark's forks and
vendor disputes, KIP-489, HdrHistogram and the industry's move to finer clocks, and is not
repeated here.

**Method.** Google Scholar and Google, searched in a browser on 5 October 2026, about twenty-five
queries, each read result by result; bibliographic details checked on DBLP; claims about a
paper's method checked against its text where it was open (ShuffleBench, the SPEC methodology
paper). *Plain words:* "grey literature" is what practitioners publish outside journals:
manuals, blogs, issue trackers, vendor reports.

---

## 1. The distribution of S

*Plain words:* S is the gap between the moment the producer reads the broker's acknowledgment
and the moment the consumer reads the message. Ideally zero; measured, spread over
milliseconds, with 8.43% below zero.

- **No prior report of this distribution on one clock was found.** Searches for negative
  latencies on one host, timestamp inversion and causality violations returned only work on
  other subjects (parallel discrete-event simulation uses "causality violation" for something
  else, so the paper should not borrow the term).
- **Closest observations, all blamed on clocks:**
  - Van Dongen and Van den Poel (IEEE TPDS 2020) "clocked negative latencies of up to 55 ms for
    up to ten percent of the events" when timestamps came from different brokers, and moved
    both timestamps to one broker. Cited; the paper now says what they saw.
  - The benchmark's maintainers told users negative latencies were clock skew (issue 216; cited).
  - Sharma et al. (2026) read negative timing spans in inference systems as skew (cited).
- **Verdict: new.** What is new is the distribution read on one clock, where clock skew cannot
  be the cause, and the control that no publish-timed latency goes below zero.

## 2. The mechanism and its laws

*Plain words:* a thread must wait for a processor core before it can read the clock; the laws
say when that wait puts S below zero, how often, and on what timescale.

- **The wait itself is well documented, under three names:**
  - "scheduling latency" in real-time Linux (cyclictest; the timerlat tracer, IEEE TC 2025;
    the osnoise tracer, IEEE TC 2022; Red Hat's tuning guides);
  - "wakeup latency" in scheduler research (schbench; Skyloft, SOSP 2024; Enoki, EuroSys 2024);
  - "run-queue latency" in Gregg's runqlat (cited), and "scheduling delay" in Linux's own perf
    tool ("sch delay: time between runnable and actually running"). The paper's term is
    therefore standard; it now also names the real-time term.
- **The slice sets the wait's scale: shown before for wakeup latency.** Skyloft (SOSP 2024)
  reports wakeup latency in schbench "roughly proportional to the time slice". The paper's new
  step is the base slice of EEVDF as the timescale of a *measurement error*. Now cited.
- **Client bias in load testing.** Treadmill (ISCA 2016) and Lancet (USENIX ATC 2019) correct
  for the bias a load tester's own queueing and scheduling add to the latencies it reports;
  Lancet busy-polls to reduce it, which is the paper's busy-polling fix. Mutilate preceded both.
  Tales of the Tail (SoCC 2014) traced server tail latency to background processes and
  scheduling. *Plain words:* "client bias" is the error a benchmark's own client adds. Treadmill
  is now cited beside Lancet; their bias lengthens a latency, while the paper's mechanism turns a
  difference between two client threads negative.
- **Verdict: partly known, the combination new.** The wait, its dependence on load and on the
  slice, and client bias are all known. New: that the wait inverts a difference read by two
  processes of one client; the identity S < 0 iff A > D; the rate law p G(T); and the
  manipulations that separate scheduling from its rivals.

## 3. The industry-wide audit

- **Academic users of the benchmark.** Benchmarking studies in MDPI *Telecom* (2023) and
  *Electronics* (2023) report its latencies; the registered audit already examined both and set
  them aside because they print figures only. Many systems papers (Pravega, 2023-2024) run it
  too.
- **ShuffleBench (ICPE 2024)**, a stream-processing benchmark from the same community, computes
  latency as the difference between two log-append timestamps that Kafka assigns, in
  milliseconds, when a record enters the input topic and when its result enters the output
  topic. Its latencies are mostly far above a millisecond, but the arithmetic of the retention
  law applies wherever they fall below one. Now named in Related Work, without criticism.
- **No published audit counts what a tool discards.** Consistent with the August survey: the
  practice of reporting retention is absent from both literatures.
- **Verdict: new.**

## 4. What to do

Every check has a precedent, and the paper says so:

- reporting the share of traces rejected (Paxson, 1998; cited);
- keeping a packet timestamped in the future (OWAMP; cited);
- randomized sending instead of a periodic schedule: network measurement calls it **Poisson
  sampling** (RFC 2330), against periodic sampling that can **phase-lock** with a periodic
  process (Baccelli et al., *The role of PASTA in network measurement*, SIGCOMM 2006). The paper
  said "dither the publish instant"; it now says "randomize the publish instants (Poisson
  sampling)";
- busy-polling the measuring thread (Lancet; cited);
- real-time priority for measuring threads (standard in Red Hat's real-time tuning guides).

SPEC's own **methodological principles** for cloud performance evaluation (Papadopoulos et al.,
IEEE TSE 2021, a SPEC Research Group paper) list eight: repeated experiments, workload and
configuration coverage, setup description, open artifacts, a probabilistic description of
results, statistical evaluation, units and cost. None asks what a tool discarded. The paper's
checks add that item, and now cite the principles. **Verdict: new as a conjunction applied
where a benchmark reports a latency.**

---

## 5. Vocabulary: what the paper said, what the field says, what changed

| Paper's word | The field's words | Decision |
|---|---|---|
| scheduling delay | perf: "scheduling delay"; real-time Linux: "scheduling latency"; scheduler research: "wakeup latency"; runqlat: "run-queue latency" | keep; name "scheduling latency" at the definition, with timerlat |
| occupancy (p) | none for this quantity; in queueing, "occupancy" means utilization, which the paper says p is *not* | **changed to "waiting probability"** |
| residual stall | renewal theory: "residual time"; the paper elsewhere says "wait for a core" | **changed to "residual wait"** |
| positivity filter | statistics: the distribution is **truncated** at zero (removed and uncounted), not censored (counted) | keep the name; add "truncates the distribution at zero" |
| dither the publish instant | network measurement: "Poisson sampling"; the hazard is "phase-locking" | **changed to "randomize the publish instants (Poisson sampling)"**; the phase effect is named phase-locking |
| client's own effect on its timestamps | "client bias" (Lancet), "client-side queueing bias" (Treadmill) | used in Related Work |
| publish latency, end-to-end latency | the benchmark's and the vendors' own terms | keep |
| one-way latency | IETF: "one-way delay" (RFC 7679); industry: "one-way latency" | keep |
| timestamp resolution | "clock resolution", "timer granularity" | keep |
| real-time / normal priority | Linux SCHED_FIFO / SCHED_OTHER | keep |
| busy-polling | Linux SO_BUSY_POLL; Lancet | keep |
| causality violation | parallel simulation's term for something else | not used |

## Sources

- Van Dongen, G., Van den Poel, D.: Evaluation of stream processing frameworks. IEEE TPDS 31(8), 2020.
- Zhang, Y. et al.: Treadmill. ISCA 2016. Kogias, M. et al.: Lancet. USENIX ATC 2019.
- Li, J. et al.: Tales of the tail. SoCC 2014.
- Bristot de Oliveira, D. et al.: Timerlat. IEEE TC 74(8), 2025; Operating system noise in the Linux kernel. IEEE TC 2022.
- Jia, Y. et al.: Skyloft. SOSP 2024, 265-279, doi:10.1145/3694715.3695973.
- perf-sched(1) manual page (`perf sched timehist`, "sch delay").
- Henning, S. et al.: ShuffleBench. ICPE 2024, 2-13, doi:10.1145/3629526.3645036 (Section 4.3.2).
- Papadopoulos, A. V. et al.: Methodological principles for reproducible performance evaluation in cloud computing. IEEE TSE 47(8):1528-1543, 2021, doi:10.1109/TSE.2019.2927908.
- Baccelli, F. et al.: The role of PASTA in network measurement. ACM SIGCOMM 2006. Paxson, V. et al.: RFC 2330, 1998.
- Maharjan, R. et al.: Benchmarking message queues. Telecom 4(2), 2023. Chy, M. S. H. et al.: Comparative evaluation of JVM-based message queue services. Electronics 12, 2023.
- Red Hat: Optimizing RHEL for Real Time for low latency operation (timerlat, scheduling latency).
