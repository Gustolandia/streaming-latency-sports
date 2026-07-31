# v2 plan — living document

Status: **collecting feedback**. v1 is submitted to arXiv (in moderation) and archived
(code 10.5281/zenodo.21650032, data 10.5281/zenodo.21650065). This plan accumulates every
change v2 should make, with its source noted. It will be revised as further feedback arrives
(second reviewer pass pending; arXiv readers after announcement) and only then executed.

Reviewer names are kept to first names here; acknowledgements in v2 with permission.

---

## A. From David's quick-read review (2026-07-28)

The single most valuable property of this review: four of his seven factual questions
(which clock? what granularity? processes or threads? where does 1 ms come from?) are
answered in v1 — in §4, §6 and §7 — and he could not find them on a quick read. The
information exists; the *access path* does not. Items A1–A3 fix the access path; A4–A9
fix real gaps the questions exposed.

### A1. Gentler introduction (his primary request)
A short plain-language opening: the key points stated clearly, briefly, before any
apparatus. Target: a general systems reader gets the two failure modes, the ratio that
governs both, and the remedy inside the first two pages. (His advice "submit the current
version, update later" is exactly the v1/v2 path we are on — validated.)

### A2. "Measurement setup at a glance" box (new, early)
Half a page, one diagram, answering in one place what a reader needs before the argument:
- Topologies: our harness = two **processes**, one host, one clock (`time.time_ns()`,
  CLOCK_REALTIME — a shared epoch, which is why not perf_counter/TSC); OMB LocalWorker =
  producer/consumer **threads in one JVM**, stamp at `LocalWorker.java:294` is
  `now − publishTimestamp` with publishTimestamp producer-side (Kafka CreateTime);
  OMB distributed = two machines' clocks; Python harness = two processes, same-host and
  cross-host variants.
- Clocks: wall clock throughout; underlying resolution ns-representation/µs-accuracy;
  chrony-disciplined, logged per minute (residual ~0.001 ppm, skew ~0.025 ppm);
  measured inter-host offset ≈0.07 ms.
- The quantum: **1 ms is the representation** (`currentTimeMillis`, Kafka CreateTime),
  not a hardware limit — while true transport is 0.1–0.5 ms. τ vs T_true in one line.

### A3. Consolidated "alternative explanations, eliminated" panel
His "I don't understand how you eliminated other explanations for the noisy clock times"
— the eliminations exist but are spread across §6 and §8. Add one compact table/paragraph:
skew (same clock by construction; two-clock replication: 0 negatives in 1.5M samples),
utilisation (equal-ρ geometries differ 2.07×, z=10.3), generic noise (SCHED_FIFO at fixed
ρ collapses rate 7–80×), direction (transport ×77 → rate ÷4.1), direct observation
(sched_switch trace within 30%, unfitted). One place to point sceptics to.

### A4. The mechanism is a *when*, not a *what* — say it plainly
His reading ("delay between a process sampling the clock and getting a time back") is the
natural wrong model. State explicitly: the failure is not latency inside the clock call;
it is the scheduling stall **between the event and the clock read that labels it**
(producer's callback thread descheduled → stamps later than the event → consumer already
recorded receipt). One sentence where the model P[inversion]=P[stall>T_true] is introduced.

### A5. "Truncation is not even self-consistent" (his sharpening — adopt with credit)
His point: if negatives are discarded as impossible, sub-minimum positives are equally
impossible and should go too; discarding one side only is unprincipled truncation. Add to
§7's guard discussion: the guard is not conservative filtering but *asymmetric, silent*
truncation — and the consistent version of its own logic would also delete a
positive floor, which no one would accept. Strengthens the dither+publish-retention remedy.

### A6. Mean-vs-median heuristic meets α≈0.34
His workflow ("look at mean and median, investigate if they don't match") is the standard
practitioner diagnostic. Connect it explicitly to the tail result: with tail index ≈0.34
the mean does not exist, so the mean half of the heuristic is structurally uninformative
here — the practitioner's own tool cannot flag this failure. One sentence beside the tail
index result; also acknowledge the standard truncated-left/long-tail-right mental model
and note Mode B violates it from the left (deletion at the floor).

### A7. Justify wall-clock over TSC in the paper text
The reasoning lives in code comments (kafka_producer.py) but not the manuscript: a
cross-process (a fortiori cross-machine) span has no common cycle counter even in
principle; TSC also varies with power management. Two sentences in Method or §2.

### A8. New Discussion subsection: **"A better clock does not reach the failure"**
The referee-anticipating section (David's clock questions all point here). Content agreed:
- PTP with hardware timestamps takes two LAN machines from our measured ~70 µs (chrony) to
  sub-µs — but is provider-gated in clouds (AWS Nitro exposes a PTP hardware clock; our
  provider does not), and, decisively: **behind a 1 ms stamp, 70 µs and 70 ns of agreement
  produce byte-identical records** — the guard deletes exactly the same samples, the grid
  law is unchanged.
- Therefore the remedy ordering: (1) record at native resolution, (2) count discards,
  (3) dither the send instant, (4) only then is synchronisation the frontier.
- Our own cross-host fact from the other side: clocks agreeing to well under a tick, yet
  retention wandered 13.4→27.0% with offset drift at the 0.1 ms scale — so the
  synchronisation state belongs in the published record beside the retention rate.
- Design-out alternatives where one-way sync is genuinely needed: round-trip on a single
  clock; offset/skew removal from the delay envelope in post-processing
  (Paxson; Moon–Skelly–Towsley); paired same-window comparisons where offset cancels.
- New references: IEEE 1588 (PTP); Paxson 1998; Moon, Skelly, Towsley 1999; optionally
  Huygens (Geng et al., NSDI 2018) for software-only ~100 ns sync.

### A9. Small factual guard-rails his misreadings exposed
- Make "producer → broker → consumer" explicit early (he read it as "storing into Redis").
- Distinguish the three negative populations in one sentence wherever one appears:
  our corpus (load-dependent, mechanism-established), Kafka-driver OMB corpus (zero in
  10.9M discards — quantisation zeros, not noise), Redis-driver corpus (41,403, every one
  exactly −1000 µs, candidate mechanism only).

## B. Carried over from referee #3's advisory list (optional, fold into v2)
- B1. Remaining length trims (~4 pp): end-to-end 209→150 lines, rules 142→110,
  Setting 71→50, authors' table 73→50, first-answer checks → list, instrumenting 82→65.
  Aligns with David's readability point; do together with A1.
- B2. M/G/1 one-clause fix: "a framing we adopt as a leading-order account and, on the
  load axis, ultimately refute" (§2 near \cite{chandrasekar2026bias}). **No longer
  optional**: promised by email to the framing's author (2026-07-28), who replied with
  interest and asked for the link on announcement.

## C. Pending inputs before execution
- C1. Dinh's review (offered; review-this-week asked). Fold in on arrival.
- C2. arXiv announcement → v1.0.2 metadata pass (arXiv ID into README/CITATION) — separate
  from v2 and can happen first.
- C3. Any second pass from David (invited in reply).
- C4. Decide acknowledgements (permissions) and whether any contribution crosses into
  co-authorship before v2 is posted.

## D. Execution checklist (when feedback window closes)
1. Implement A-items, then B-items, keeping every meaning-pin the consistency suite
   enforces (run the full suite + numbers gate + rendered-PDF check after each block).
2. New references added to manuscript_references.bib; rebuild ×3 + bibtex; 0 errors /
   0 undefined refs; check rendered text for macro remnants (the three-times-burned rule).
3. Abstract unchanged unless a finding changes — v2 is presentation + one Discussion
   subsection, not new claims. If the at-a-glance box shifts page count, re-verify the
   "58 pages" comment line for the arXiv replacement.
4. Post as arXiv v2 (replacement), update Zenodo (new version deposit → new DOIs,
   cross-links carry via .zenodo.json), tag v1.1.0.
5. Then the journal reformat fork (TOMPECS vs TPDS/TC decision with Dinh).
