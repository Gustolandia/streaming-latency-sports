# §6.7 rewrite — working draft (revision 2, 2026-07-26 18:30Z)

**Status: draft. Not applied to `paper.tex`.** Revision 1 of this file was written before most of
the evidence existed and asserted several things since withdrawn. Those are listed at the bottom
under "must not appear" so they cannot creep back in.

## What is settled

Each of these rests on completed measurements and has survived every cell that has landed since.

**S1 — Zero negative samples.** Roughly 420,000 discarded end-to-end samples across 15 load-sweep
cells, 8 message-size cells and the replication pass so far. Not one is negative. The most
negative end-to-end latency observed at any load, at any message size, is 0 µs. *This is what
carries the withdrawal, and it is a statement about sign that no mechanism argument can touch.*

**S2 — Retention spans the full range.** The share of samples surviving OMB's
`if (endToEndLatencyMicros > 0)` guard ranges from **0.36% to 100%** across cells. Nine of the
first 21 lie between 5% and 95%; it is a continuous range, not two modes.

**S3 — The reported median does not track it.** Across the 16-cell join, reported p50 takes two
values — 1.0 and 2.0 ms. One cell computed its summary from 998 samples and another from 120,425;
both report 1.0 ms. Nothing in OMB's output distinguishes them.

**S4 — The reported average moves the wrong way.** Spearman(retention, reported average) = −0.54.
Discarding everything below one tick removes the *fast* samples, so the mean is taken over the
surviving slow tail. The benchmark reports a higher latency the more data it discards.

**S5 — The instability has a location.** Message sizes whose latency sits far above one tick
reproduce tightly (64 KB: 35.92% vs 34.42%; 256 KB: 100% vs 100%). Sizes whose reported median is
exactly 1.0 ms swing across nearly the whole range (200 B: 100% vs 0.36%; 4 KB: 10.94% vs 100%).
The irreproducibility is a property of the near-tick regime, not of the benchmark generally.

**S6 — Path speed does not explain it.** OMB's own publish latency — measured within one process
and *not* quantised to the millisecond grid — sits at 0.3–0.4 ms across all 19 unsaturated cells
while retention over those same cells ranges from 0.36% to 100%. A predictor with a 0.1 ms spread
cannot explain a 275-fold swing.

**S7 — Replicates that agree are not a reproducible measurement.** *(Level 0 only so far; four
levels pending.)* The identical sweep run twice gave a three-replicate median of 1.51% in pass A
and 99.98% in pass B. Pass B's three replicates agree to 3.58 points. An experimenter running only
pass B would report a tight, confident measurement 98 points away from what the same configuration
produced an hour earlier.

## The claim the section should make

> An instrumented OpenMessaging Benchmark, run against our broker on a sub-millisecond path,
> computes its reported latency distribution from between 0.36% and 100% of the samples it takes,
> depending on the run, and reports the same median either way. It counts nothing that it drops.
> The fraction that survives is not reproducible between passes of an identical configuration, and
> replicates within a pass can agree closely while the pass itself is 98 points from its
> predecessor — so the usual defence of averaging replicates and quoting their spread does not
> detect it and actively misleads.

That is stronger than the claim it replaces, and it is about the number a reader actually sees
rather than about a counter only we can read.

## What we withdraw, and why the section must say so

Section 6.7 reported that an instrumented OMB "discarded 6,000 end-to-end samples" and read those
as the same causality violation this paper reports. **The reading is withdrawn.** The counter
behind it was a single unsigned total; both a causality violation and a sub-millisecond delivery
fail `> 0`, and it counted them together.

The refutation was in our own artefact from the day it was committed. All eleven counter lines in
`external/omb/omb_discard_evidence.txt` read `sample_micros=0`, and the Pub-rate lines beside them
show a median publish latency of 0.4–0.5 ms. What was missing was not data but a reason to look at
the sign, because the statistic we chose to report did not have one. That belongs in the section:
it is the paper's own subject, one level up.

**The source audit is unaffected** and never depended on the run — the guard admits only positive
samples, nothing counts the drops, the reported distribution is conditioned on being positive, and
the retention rate is unrecoverable from a completed run.

## Still open — do not write these until they land

- **Cross-host negatives** (chain5). The clock bound on this testbed is 12.3 ms against a 1 ms
  timestamp, so a negative is possible. Single-host cannot settle it.
- **Mechanism** (chain8). Phase against the millisecond grid is the candidate: the producer is
  paced at exactly 2.000 ms. Predictions are filed; if all three rates behave alike it is wrong.
- **Retention variance at n=15** (chain7).
- **S7 at levels 50–95** (chain3 step 2, running).

## Must not appear — withdrawn during this work

1. *"The zero share falls with load."* Five levels are 98.49, 23.68, 4.41, 4.78, 22.63 — not
   monotone. Read from three levels before the other two existed.
2. *"Retention is bimodal / a threshold with nothing between."* Nine of 21 cells lie between 5%
   and 95%. Read from five observations at one configuration.
3. *"64 KB is the clean discriminator."* It is saturated: p50 = 519 ms, p99 = 1097 ms.
4. *"Retention = P(true latency ≥ one tick)."* Refuted by S6 — the path is flat while retention
   swings.
5. *Anything treating the message-size sweep as discriminating resolution from causality.* It
   never could; both predict no zeros at high latency. It shows a dose-response, nothing more.

## Sites to update together

| site | line | change |
|---|---|---|
| abstract | 70 | replace the 6,000 with the retention finding |
| contributions | 202 | same, plus the sweep |
| related work | 243 | check wording survives |
| limitations | 2525 | **rebuild** — the run no longer establishes the failure outside our harness; the source audit does |
| conclusion | 2631 | replace the 6,000 |
| §7 requirements | 2332–2342 | unaffected, and strengthened |
| `docs/laws.md` | 241 | **done** |
| status board | 236 | **done** |
| `external/omb/README.md` | 4 | **done** |
| `external/omb/omb_discard_evidence.txt` | — | **keep byte-for-byte** — it is the primary record of the refutation |
