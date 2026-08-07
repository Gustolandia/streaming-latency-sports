# Response to Reviewer — TPDS round 1

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths* (title shortened per your minor 1).

We thank the reviewer for a report that improved not only the manuscript but the
analysis behind it: two of your requests (M4b, M5) sent us back to the pipeline and
surfaced things we are glad to have found. Every point is addressed below. The revised
paper remains 16 pages with the three requested exhibits now in the main text; the entire
revision is artefact-verified (2,120 tests, all green).

## Major points

**M1 — exhibits in the main text.** Done, all three: the two-panel model figure now sits
beside Eqs. (1)–(2) (`fig:model`); a compact mechanism table covering the real-time-priority
collapse (39×/54× at utilisation matched to 0.001) and the geometry contrast (2.07×/2.05×
at ρ = 0.7531 in all four arms) sits in §VIII-C (`tab:mechanism`); and the payload
on/off-vertex figure now illustrates the campaign's confirmed prediction in §VII-F
(`fig:payloadflip`). The compensating prose cuts are the ones you named — §VII-B's
corroboration paragraph (to S7), §IX-A's rules (tightened by roughly a third), and parts
of §II — plus stub-and-move compressions recorded in `docs/supplement_index.md`. The
paper stays at 16 pages.

**M2 — fit to TPDS.** A remit paragraph now closes the introduction's opening run, in
substantially your words: cross-process and cross-host timestamping is the measurement
substrate of every distributed-systems latency claim, and we show that substrate failing
structurally at the scales the field now publishes, on the community's shared benchmark
and across two disciplined hosts.

**M3 — self-containedness.** The fit ladder now names its rivals in the main text
(two-state 0.9905 against 0.9811 and 0.8863 at equal parameters, 0.9982 with σ frozen)
and has one home (S32). The double pointers you flagged (S33/S18, S12/S25) are split so
each claim has exactly one home. Every "Supported"/"withdrawn" verdict was audited for
its deciding numbers; with `tab:mechanism` promoted, the two verdicts that leaned
hardest on S25 now lean on a main-text table.

**M4 — the tail index.** We did (b) and (c), and (b) turned out to matter more than we
expected. A new committed script (`scripts/traced_tail_slope.py`) computes the traced
per-wakeup survival's log–log slope from the E-A9 bpftrace histogram: over the co-located
decade (0.25–2 ms) the windowed index is **0.332 — indistinguishable from the fitted
0.339** — and it **rises past 4 beyond 4 ms**. The traced distribution is therefore not
scale-free, so the manuscript now states that Eq. (6) is an *effective law of the payload
span, fitted, not derived, and not a constant of the machine*, and we withdraw the
earlier draft's unconditional infinite-moment reading — your (c), which our own new
evidence made mandatory rather than merely prudent. The steepening also explains the
1.66× level over-prediction in direction (a span-calibrated power law must sit above a
steepening curve), and the text notes the length-bias caveat: the traced quantity is
per-wakeup delay, the residual the model's S denotes is one power heavier, so the
comparison is a consistency check, not an identity. (a) was not pursued: the testbed was
decommissioned and imaged after the campaigns closed, and (b)+(c) answer the concern
without new hardware.

**M5 — the shift's selection bound.** Your instinct here was better than you knew.
Rebuilding the analysis exposed that the powered transport aggregates had been computed
*before* the audit verdicts were wired into the cloud index — the TOST had consumed all
629 runs, condemned included, and the paper's "every run is audit-surviving" sentence in
S6 was false for that aggregation. We have repaired this end to end: a committed script
(`scripts/powered_gate_sensitivity.py`) applies the gate, and the gated artefacts are now
the primary ones everywhere (paper, supplement tables, tests). The findings: (i) the gate
moves the Hodges–Lehmann shift by at most **0.003 ms** (0.017 ms in the replication), so
0.41 ms stands; (ii) Redis retention is 8/15, 59/135, 61/165 per cell — **below one half
in two cells**, where the E1-style imputation defence cannot bind; unlike E1 the
condemned values survive, so observation replaces bounding, and §VIII-D now says so;
(iii) flipping the shift's sign would require essentially every condemned Redis run to
have measured ≥ 0.55 ms, five times the 0.10–0.12 ms their observed medians centre on.
§VIII-D states the campaign's retention (your general rule, which this section had been
violating), and the per-cell sensitivity table is S34. The powered sample-size figure
changed from 127 to 125 matched events per run under the gate.

**M6 — the distributed-mode gap.** We took your scoping branch: the abstract's deletion
claims now read "instrumented embedded-mode runs", and §VII's opening scopes the audit
("in embedded mode throughout") with a pointer to the section that bounds what that
leaves open. The upstream report is drafted (text below); the author will file it, and we
will cite the issue number in the final files. We did not attempt the vendor forks: the
testbed is decommissioned, and the scoping branch you offered covers the claim.

**M7 — preprints marked, neighbourhood anchored.** All four (Sharma, Chandrasekar &
Kramberger, Swami & Chougule, Mohammad) are marked as preprints at first citation. All
five of your suggested anchors are now engaged: Treadmill (§II-A, as the closest
peer-reviewed methodology kin), DTP and Sundial (§IX-B's better-clock ordering), Uta et
al. (the run-to-run instability bracket), and Bailey (same bracket, as the tradition's
ancestor).

## Minor points

1. **Title** shortened to end at "…Sub-Millisecond Paths."
2. **Kernel/scheduler**: §IV-A now states Ubuntu 22.04 on kernel `6.8.0-1057-oracle`
   (EEVDF) — recorded in every run's committed metadata — and Threats notes the constants
   are those of one EEVDF-era kernel, with Lozi et al. scoped to CFS. Your CFS presumption
   was reasonable and wrong in an interesting way; see Q1.
3. "(Mann–Whitney)" added at the first p-value.
4. "boring" → "predetermined."
5. "In plain terms:" reduced to exactly the two instances you endorsed (§VII-B, §VII-G(c));
   a test now pins the count at two.
6. Eq. (3)'s label is now "(uniform phases)", defined at point of use.
7. Eq. (4)'s arrow replaced by "=" with "as runs lengthen" in the sentence.
8. KIP-489 cited beside the WorkerStats guard, with its "reported as NaN" wording — we
   verified the exact sentence against the KIP during this revision.
9. AWS ClockBound and Meta's PTP deployment now close §IX-B as the industrial form of
   "publish the synchronisation state."
10. "Attractors" unpacked in §VII-F ("replicates pin near the grid's vertices rather than
    scattering").
11. StatsBomb licence clause added to Artefact Availability.
12. Wayback snapshots recorded for the two grey links that have them (the GitHub
    repository has no snapshot; its name and pinned commit are its durable identifiers).
13. An Acknowledgments section names the compute substrate (Oracle Cloud Infrastructure);
    biography, photo, and any funding statement will accompany the final files.

## Typography

Eq. (6)'s overflow was repaired on receipt of the report; the S29 double-pointer is
varied; "artefact gate" is now "a check in the released analysis code"; the abstract
names the mode of the instrumented runs; the Testbed A/B run-in labels are italic as
paragraph labels with in-text mentions roman throughout.

## Questions

**Q1.** Kernel `6.8.0-1057-oracle` (Ubuntu 22.04 HWE), EEVDF scheduler — recorded in
every run's `host_platform` metadata. Real-time priority was applied as `chrt -f 80`
wrapping only the stamping (producer/consumer Python) processes; the manipulation was
verified live during the elevated arm by sampling scheduling classes: 20 python3
processes at `SCHED_FIFO`, their sudo/bash parents at `SCHED_OTHER`
(`docs/results/depth/ea5/sched_verification.txt`).

**Q2.** OMB's coordinated-omission correction (issue #247, PR #248) was merged on
2022-04-07, four years before the audited commit `5b1fa70`. It instruments the
*generator* side (a scheduling-aware rate limiter and a producer-delay metric) and leaves
the receive-side end-to-end subtraction and positivity guard untouched, so it does not
interact with retention: retention is decided entirely at the recording guard. Our
harness additionally measures the pacer's own per-send jitter directly (67–69 µs at p90),
bounding coordinated-omission exposure in our runs independently of upstream fixes.

**Q3.** Not recorded, and we say so rather than guess: the per-run metadata captures
kernel, chrony state (per-minute, residual 0.000 ppm on the run in question) and host
platform, but not `/sys/.../current_clocksource`. The VM boot volumes are archived, so
the check is recoverable; until then the virtualised-clock account remains flagged as
candidate, not conclusion — which is how the manuscript already stated it.

**Q4.** Yes, and it is now shown rather than asserted: gate on/off moves the shift by at
most 0.003 ms (0.017 ms in the replication), and the sign flips only if essentially every
condemned Redis run measured ≥ 0.55 ms against observed condemned medians of
0.10–0.12 ms (max 0.72 ms). Artefact: `docs/results/transport_rt*/gate_sensitivity.csv`;
see M5 for the pipeline defect this question exposed.

**Q5.** Confirmed, and now at condition level with a committed artefact
(`scripts/threshold_condition_sweep.py` →
`docs/results/integrity_windows/first_result_threshold_sweep.csv`): across thresholds
0–20%, none of the six first-result cells becomes fully usable at any point; even at the
permissive 20% extreme the best cell passes 23 of 30 runs. §VI-B now cites this artefact,
and a test fails the build if any threshold in the range ever resurrects a first-result
cell.

## Draft upstream report (to be filed by the author against openmessaging/benchmark)

> **Title:** WorkerStats positivity guard silently discards samples with no counter;
> retention is unrecoverable from a completed run
>
> At commit 5b1fa70, `WorkerStats.java:95` admits a sample to the end-to-end histogram
> only `if (endToEndLatencyMicros > 0)`. The message is still counted as received, but a
> non-positive latency is dropped and no counter records how many. Because
> `System.currentTimeMillis()` has millisecond resolution, any delivery faster than 1 ms
> differences to exactly zero and is dropped by the same branch: on co-located paths this
> is a large share of all samples, and across 223 instrumented embedded-mode runs we
> measured the reported distribution being computed from between 0.36% and 100% of the
> samples taken — same reported median either way. Suggested minimal fix: count and
> report discards (zero/negative separately, since a negative difference is evidence of
> clock trouble that this guard currently hides — cf. KIP-489's NaN convention). We are
> happy to contribute the counter patch we used for instrumentation; measurement write-up
> and per-run data: [Zenodo DOI 10.5281/zenodo.21650032].

---
*Every change above is enforced by the repository's consistency suite (new class
`TestRefereeRoundOne` plus `tests/unit/test_referee_pipeline.py`), so none of these
answers can silently rot: the sensitivity numbers, the traced slopes, the threshold
sweep, the exhibit placement, the preprint markers and the register count are all
recomputed from committed artefacts on every run.*

---

# Round-2 addendum: the eleven welcomed minors

1. **Page-15 whitespace** — gone: the flush-bottom stretch before the Conclusion is
   absorbed; both columns of p.15 now fill evenly (verified visually on the final build).
2. **Reference [3] URL typography** — a `UrlBreaks` declaration now lets bibliography
   URLs break at slashes, hyphens and dots; [3] wraps inside the margins and the archived
   snapshot is recorded by timestamp and ID only.
3. **Figure legibility** — Figure 1 was *regenerated* at 1.5x internal font sizes (a new
   `--font-scale` option in the committed figure script, with a test) and is shown at
   0.8 column width; Figure 2 is restored to full column width, per the option you
   offered. Both are comfortably legible at print size on the final build.
4. **Table I** — the column heads now name the arms per block ("ordinary / real-time";
   "concentrated / spread").
5. **§IX-A citation placement** — reads "Better instruments exist [19]; whatever the
   instrument, check its output against causality…".
6. **§IX-D** — comma added after "network."
7. **§II-D** — the forward reference now reads "Table I, Section VIII-C."
8. **Traced-slope scope** — §VIII-C(g) now states "one traced arm of one campaign — the
   replication kept no raw histogram."
9. **Two-regime symmetry** — §VI-B closes its imputation bound with "where rejected
   values survive, observation replaces this bound (Section VIII-D)."
10. **Artefact Availability** — the block flows as one paragraph; the URL-wrap artefact
    is resolved by the same `UrlBreaks` fix as item 2.
11. **Final files** — biography, photo, funding statement and the filed upstream issue
    number remain with the author, as you noted.

The paper remains exactly 16 pages; the full suite (2,121 tests including the new
figure-script test) is green.
