# Grey literature review — practitioner sources on latency-measurement failure

Surveyed 2026-08-03; **verification pass 2026-08-07** fetched the four items previously
marked *not fetched in full* ([6], [7], [9], [10]) and re-swept for 2025–26 material
(none found that touches discarded-after-measurement samples — the gap claim survives a
second look). Changes from the pass are marked **[verified 08-07]** below. Scope: talks,
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
   — github.com/openmessaging/benchmark/issues/247. **[verified 08-07]** The issue states
   `LocalWorker::submitProducersToExecutor` is "not recording any 'publish delay' computed
   by checking the actual send time vs the expected schedule", that "inability to keep-up
   with the expected load will pass unnoticed", and that "a proper fix should fix both
   `endToEnd` and `publish` latencies using the intended send time vs the real one";
   closed by PR #248. The thread contains **no mention** of negative latencies, discarded
   samples, or the positivity guard.
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
   **[verified 08-07]** Disputes cover fsync settings (`log.flush.interval.messages=1`),
   hardcoded async offset commits in the Redpanda driver, Java 11 vs 17, producer/consumer
   counts, record keys, partition counts, TLS, and NVMe degradation under sustained load
   — and the post **nowhere discusses timestamp resolution, negative latencies, or sample
   retention**. New sub-finding from the fetch: Vanlightly reports an OMB bug in which
   histogram collection errors trigger a retry against a recorder that **resets itself on
   read** ("the original histogram returns a copy but resets itself"), so high-percentile
   latencies are silently under-reported — a *third* silent-data-loss mode in the same
   tool, distinct from CO and from the positivity guard, and further evidence that OMB's
   reported distribution can be conditioned on instrument state without a trace in the
   output.
   *Relation:* the highest-stakes public use of the audited instrument: two vendors
   litigating sub-10ms latency claims through OMB, with methodology disputed at the level
   of hardware, partitions and configs — and no discussion of the millisecond stamp
   quantum or of what the guard discards. If retention obeys the grid law on their
   co-located setups, both sides' tail claims rest partly on which grid vertex their
   configs landed on. Prime motivation anecdote for §1/§2.

8. **Practitioner OMB guides** — e.g. jeqo.dev "Benchmarking Apache Kafka: intro to OMB";
   platformatory.io on Kafka client metrics (*claims about OMB's e2e coverage in this one
   look doubtful — verify before any use*).
   *Relation:* documents how OMB output is consumed uncritically downstream.

## C. Upstream artefacts that institutionalise the deletion

9. **KIP-489: Kafka Consumer Record Latency Metric** — Apache Kafka design wiki.
   **[verified 08-07]** Exact wording confirmed: "When latency is calculated as negative
   then the metric value will be reported as NaN"; latency is defined as wall-clock time
   minus the fetched record's timestamp, clock synchronisation is named as the dependency,
   and **no counter for negative occurrences is specified**. Working URL:
   https://cwiki.apache.org/confluence/display/KAFKA/489:+Kafka+Consumer+Record+Latency+Metric
   *Relation:* an upstream sibling of the OMB guard, in a design document — negative
   spans are defined out of existence at specification time, with clock skew named as the
   cause and no counter specified. The suppression is not a bug but a convention.

10. **HdrHistogram documentation** (Recorder/AbstractHistogram JavaDoc + README) —
    **[verified 08-07, and weaker than previously stated.]** Neither the README nor the
    Recorder JavaDoc contains an explicit "negative values are rejected" sentence. What
    the contract actually states: a configurable **non-negative integer range** ("integer
    values between 0 and 3,600,000,000" in the README's example; `lowestDiscernibleValue`
    defaulting to 1, values "distinguished from 0"), with exceptions documented for values
    exceeding `highestTrackableValue`. Rejection of negatives is real in practice (a
    negative long indexes out of the counts array) but it is *behaviour*, not documented
    contract. **Citation guidance:** cite the range contract ("records values in a
    non-negative integer range"), not a rejection sentence; the manuscript's current §7
    wording ("sound rejection of negative values") is defensible as a description of
    behaviour but would be safer as "a recorder whose value range excludes negatives".
    https://hdrhistogram.github.io/HdrHistogram/JavaDoc/org/HdrHistogram/Recorder.html
    *Relation:* still confirms the paper's §7 reading of *why* the guard exists (the
    reasonable local fix for a recorder that cannot store negatives) — the deletion is
    the composition of two individually-defensible contracts. Cite beside
    `WorkerStats.java:95`.

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

## F. Status after the v2 restructure (2026-08-07, commit 90d1136)

The v2 manuscript is frozen at the 16-page TPDS ceiling, so A10 was applied selectively
rather than in full. What v2 actually carries from this survey:

- **Cited in v2:** Tene talk [1] (`tene2015latency`, §2.4 CO-mirror-image paragraph, with
  the CO-vs-Mode-B distinction stated in-line); HdrHistogram [10]
  (`tene2015hdrhistogram`, §2.4 and the §7 guard discussion); KIP-32 [11]
  (`kafka2015kip32`); the three practitioner comparisons (`medium_benchmark_2025`,
  `github_benchmark_2025`, `jusdb2025`); Heiser's extension [4] via `vanderkouwe2019sok`
  and `hoefler2015scientific` (§2.4 run-to-run instability paragraph).
- **Not cited in v2 (page budget), queued for the journal revision if a referee opens the
  door or a page is recovered:** Shipilev [3] (single-process τ-vs-T half of the ratio,
  known since 2014); OMB #247 [6] (awareness-is-mode-specific, now verified verbatim);
  KIP-489 [9] (suppression-as-convention, verified verbatim); the Redpanda–Confluent
  dispute [7] (stakes anecdote + the newly found histogram-reset loss mode); AWS
  ClockBound [12] / Meta PTP [13] (better-clock subsection support). Each is one
  sentence; S18/S33 in the supplement can absorb them without touching the main text.
- **Wording check against [10]:** §7's "sound rejection of negative values" is behaviour,
  not documented contract — if revised, prefer "a recorder whose value range excludes
  negatives" (see item 10).

## G. Verification log

- 2026-08-03: initial survey (search results only for [6], [7], [9], [10]).
- 2026-08-07: fetched [6], [7], [9], [10] in full; KIP-489 wording and URL corrected;
  HdrHistogram claim tempered; Vanlightly histogram-reset loss mode added to [7];
  re-sweep for 2025–26 items found nothing on discarded-after-measurement samples —
  the §E gap statement stands verified.
