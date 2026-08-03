# Grey literature review — practitioner sources on latency-measurement failure

Surveyed August 2026 (web search; items marked *not fetched in full* were identified from
search results and should be re-read before being cited in the manuscript). Scope: talks,
engineering blogs, vendor documentation, GitHub issues, and design documents — the
non-peer-reviewed record where benchmarking practice actually lives. Purpose: (1) map what
practitioners already know against the paper's two failure modes; (2) identify grey items
worth citing in v2/journal §2; (3) sharpen the gap claim ("the accuracy problem is
recognised... what appears to be missing is the practice").

**Bottom line.** The grey literature is rich on *coordinated omission* (samples never
generated because the load generator stalls) and on *clock infrastructure* (μs-accurate
cloud time is an active product race). It is, as far as this survey found, **silent on both
of the paper's modes**: no source counts or reports samples discarded *after* measurement,
none derives the millisecond-quantum retention arithmetic, and none reads the sign of
discarded differences as an audit channel. The closest upstream artefacts (KIP-489,
HdrHistogram's range contract) *institutionalise* the deletion rather than examine it.

---

## A. The canonical practitioner critique: coordinated omission and timer trust

1. **Gil Tene, "How NOT to Measure Latency"** — talk, QCon SF 2015 (InfoQ recording +
   slides). The founding grey-literature text of latency-measurement scepticism:
   coordinated omission, percentile misuse, the "your monitoring is lying" framing.
   https://www.infoq.com/presentations/latency-response-time /
   https://www.infoq.com/presentations/latency-pitfalls/
   *Relation:* CO is a **third failure mode, distinct from both of ours**: it deletes
   samples *before they are sent* (the generator back-pressures), while Mode B deletes
   *after they are measured* (the recorder guards). The paper should state this distinction
   explicitly — reviewers steeped in Tene will pattern-match our deletion onto CO.

2. **Tyler Treat, "Everything You Know About Latency Is Wrong"** — blog, Dec 2015
   (bravenewgeek.com). The widely-circulated distillation of Tene's talk; the 95th-percentile
   session arithmetic. https://bravenewgeek.com/everything-you-know-about-latency-is-wrong/
   *Relation:* evidence the critique diffused into practice a decade ago — yet the guard
   audited in §7 postdates it. Awareness of one deletion mode did not immunise against another.

3. **Aleksey Shipilev, "Nanotrusting the Nanotime"** — blog, 2014 (shipilev.net) +
   timers-bench (github.com/shipilev/timers-bench). Measured timer latency and granularity;
   `currentTimeMillis` scales well *at the cost of much coarser granularity*; nothing under
   ~30 ns is directly measurable; "prove the timer latency and granularity problems are out"
   before trusting time-based benchmarks. https://shipilev.net/blog/2014/nanotrusting-nanotime/
   *Relation:* the practitioner-canonical source for exactly the τ-vs-T_true concern, twelve
   years before v1 — for the *same-process* case. The paper's contribution is the
   cross-process/cross-clock case plus the retention arithmetic; cite to show the
   single-process half was long known.

4. **Gernot Heiser, "Systems Benchmarking Crimes"** — webpage, maintained since ~2010
   (gernot-heiser.org/benchmarking-crimes.html); extended by van der Kouwe et al.
   (arXiv:1801.02381). Checklist of misleading benchmark practice; closest crime:
   "no indication of significance of data".
   *Relation:* none of the listed crimes covers silent sample deletion by the harness —
   worth one sentence: the crime list assumes the instrument reports what it measured.

## B. The audited instrument in the wild: OMB as industry battleground

5. **OMB repository and vendor forks** — github.com/openmessaging/benchmark, with active
   forks by Confluent (confluentinc/openmessaging-benchmark), Redpanda
   (redpanda-data/openmessaging-benchmark), StreamNative, DataStax.
   *Relation:* establishes stakes — the audited code path is the de-facto industry
   instrument for cross-broker latency claims.

6. **OMB Issue #247 + PR #248, "The load generation need to fix Coordinated Omission"**
   — github.com/openmessaging/benchmark/issues/247. Reports that `LocalWorker`'s
   load generation did not record publish delay (actual vs intended send time); fixed via
   intended-send-time accounting. *Not fetched in full.*
   *Relation:* the project's own maintainers fixed the *known* deletion mode (CO) in the
   same file our audit targets — while `WorkerStats.java:95`'s guard remained. Strongest
   single grey item for the "awareness is mode-specific" argument. Also directly adjacent
   to our pacer-jitter instrumentation (the harness measures exactly the quantity #247
   says should be recorded).

7. **The Redpanda–Confluent benchmark dispute (2022–23)** — Redpanda's published
   OMB-based comparison and benchmarking guide
   (redpanda.com/blog/self-hosted-redpanda-benchmarking), answered by Jack Vanlightly
   (Confluent), "Kafka vs Redpanda Performance — Do the claims add up?", May 2023
   (jack-vanlightly.com), with a custom OMB fork (github.com/Vanlightly/openmessaging-benchmark-custom).
   *Relation:* the highest-stakes public use of the audited instrument: two vendors
   litigating sub-10ms latency claims through OMB, with methodology disputed at the level
   of hardware, partitions and configs — and, in everything surveyed, **no discussion of
   the millisecond stamp quantum or of what the guard discards**. If retention obeys the
   grid law on their co-located setups, both sides' tail claims rest partly on which grid
   vertex their configs landed on. Prime motivation anecdote for §1/§2.

8. **Practitioner OMB guides** — e.g. jeqo.dev "Benchmarking Apache Kafka: intro to OMB";
   platformatory.io on Kafka client metrics (*claims about OMB's e2e coverage in this one
   look doubtful — verify before any use*).
   *Relation:* documents how OMB output is consumed uncritically downstream.

## C. Upstream artefacts that institutionalise the deletion

9. **KIP-489: Kafka Consumer Record Latency Metric** — Apache Kafka design wiki.
   Specifies that when computed record latency is negative, "the metric value will be
   reported as NaN". https://cwiki.apache.org/confluence/display/KAFKA/489
   *Relation:* an upstream sibling of the OMB guard, in a design document — negative
   spans are defined out of existence at specification time, with clock skew named as the
   cause and no counter specified. The suppression is not a bug but a convention.

10. **HdrHistogram documentation** (Recorder/AbstractHistogram JavaDoc + README) —
    values must lie in a positive dynamic range (`lowestDiscernibleValue >= 1`);
    out-of-range recording throws (or requires `auto_resize`/clamping by the caller).
    https://hdrhistogram.github.io/HdrHistogram/JavaDoc/org/HdrHistogram/Recorder.html
    *Relation:* confirms the paper's §7 reading of *why* the guard exists (the reasonable
    local fix for a recorder that rejects negatives) — the deletion is the composition of
    two individually-defensible contracts. Cite beside `WorkerStats.java:95`.

11. **KIP-32 (record timestamps, CreateTime semantics)** — Apache wiki. Already cited in
    v1 (\cite{kafka2015kip32}); listed here for completeness as grey literature.

## D. Clock infrastructure: the industry direction of travel

12. **AWS: microsecond-accurate Amazon Time Sync + ClockBound** — AWS Compute Blog
    "It's About Time" (Nov 2023) and subsequent expansion notes (2024–2026): GPS-disciplined
    reference clocks on Nitro, PTP hardware clock device, ClockBound daemon exposing
    *bounded* clock error to applications.
    https://aws.amazon.com/blogs/compute/its-about-time-microsecond-accurate-clocks-on-amazon-ec2-instances/
    *Relation:* for §Discussion "a better clock does not reach the failure" — the better
    clock exists and is provider-gated (our provider lacks it); ClockBound's
    *error-bound-as-API* is the industrial cousin of our "publish the sync state beside
    the retention rate" recommendation.

13. **Meta: PTP/SPTP deployment** — engineering.fb.com series (Nov 2022 "PTP at Meta",
    Feb 2024 "Simple Precision Time Protocol"): NTP's millisecond precision declared
    insufficient; nanosecond-class sync at datacenter scale, with custom Time Appliances.
    https://engineering.fb.com/2022/11/21/production-engineering/precision-time-protocol-at-meta/
    *Relation:* same section — hyperscalers are re-plumbing time while the field's standard
    benchmark stamps in whole milliseconds; the mismatch *is* the paper's opening ratio.

14. **Redis "Diagnosing latency issues" documentation** — redis.io/docs (intrinsic-latency
    tool; scheduling and VM-induced latency named as first-class causes).
    https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/latency/
    *Relation:* vendor documentation already tells operators that the *environment*
    (scheduler, virtualisation) injects latency at the scales we measure — supporting
    Mode A's plausibility to practitioners; no mention of measurement-side inversion.

---

## E. The gap, stated for §2

Across all of the above: practitioners have (a) a decade-old, well-diffused critique of
samples *never generated* (CO), (b) upstream conventions that *silently suppress* negative
spans (KIP-489, HdrHistogram-motivated guards), and (c) an active industrial race toward
μs/ns clock sync. What no surveyed source does: **count what the instrument discards,
report retention, examine the sign of discarded differences, or notice that a millisecond
quantum turns sub-millisecond truth into rational-grid retention.** The paper's §2 claim
("the practice is missing") survives the grey literature and is strengthened by it: the
practice is missing *even where the awareness is oldest* (OMB fixed CO in the same file).

## F. Actions for v2 / journal version

- Add to §2 (short paragraph or footnotes): Tene talk [1], Shipilev [3], Heiser [4],
  OMB #247 [6], KIP-489 [9], HdrHistogram contract [10] — each one sentence.
- §1 or §2 motivation: the Redpanda–Confluent dispute [7] as the stakes anecdote
  (neutral wording; both sides' posts cited, no adjudication).
- §Discussion (better-clock subsection, v2_plan A8): AWS Time Sync/ClockBound [12] and
  Meta PTP [13] as the industry direction; ClockBound as precedent for publishing error
  bounds alongside measurements.
- Explicitly distinguish CO from Mode B deletion (one sentence, likely §2 near Tene).
- Before citing: re-read [6], [7], [9], [10] in full (this survey verified their existence
  and gist from search results, not their exact wording).
