# Response to simulated referee report — IEEE Transactions on Computers, round 2

> **Internal QA artefact — simulated review.** The referee report answered below was an
> adversarial review generated inside the project, before any journal submission, to
> stress-test the manuscript against IEEE TC's standards (source report:
> `REFEREE_REPORT_TC_R2_SIMULATED.md`, kept untracked). The paper has not been submitted to
> IEEE Transactions on Computers; no text here originates from, or is addressed to, any
> real reviewer or journal.

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths*.

Verdict returned: **needs major revisions**, with acceptance expected on resubmission. All
ten round-1 items were verified closed in the rendered PDF. Nineteen new items (R1–R19),
all addressed below.

The most useful thing this round did was find that **four of its nineteen items were
introduced by round 1's own fixes** — a denominator borrowed from one population and
printed against another, a NIST paraphrase that inverted the source's own uncertainty
budget, an over-read of Villain et al., and a bibliography entry with the wrong author
names. We had corrected those areas and not gated the corrections. Everything in this round
that could be gated now is.

Build after revision: 11 pages against TC's 10–12, exactly 45 references against a cap of
45, a 195-word abstract against 100–200, 0 errors, 0 undefined references, 0 overfull
boxes, and a 41-page supplement. Four gates green; 2,275 tests pass, 35 skipped with
written reasons, 0 failing; 97% branch coverage on the changed scripts.

## The item that changed a result

**R15 — the tail section.** You asked for the goodness-of-fit test that "not a power law"
actually requires, and for the estimators to be credited. Doing both turned a negative
result into the paper's most direct mechanistic evidence, which we had been sitting on
without seeing it.

The bootstrap rejects the power law decisively: *p* < 0.0004 over 2,500 replicates drawn
from the fitted model itself. But the more useful question was the one you asked next —
what shape *do* the data have. The bucket counts are not monotone, so no power law can
describe them. There are three local maxima: a jitter core, a hump in the hundreds of
microseconds, and a **mode at 2–4 ms carrying 10.5% of all wakeups, standing 4.5× above its
lower neighbour**. Above it the survival is light and ordinary — grouped maximum likelihood
gives α = 2.04 (2.00–2.07), a finite variance.

That mode is not arbitrary. On an eight-vCPU instance the EEVDF base slice is
0.75 ms × (1 + ⌊log₂ 8⌋) = 3 ms; run-to-parity holds a woken thread off the CPU until the
incumbent exhausts that slice, and with the high-resolution tick disabled the expiry is
seen at the ordinary tick. **It is the two-state model's preempted state, observed directly
in the trace, at the constant the scheduler is configured with.** We have rewritten
Section V-G around it, retired "heavy tail" from the text and from Figure 1(b), and cited
Virkar & Clauset — whose grouped estimator on log-spaced bins is what we had implemented
without knowing it is theirs, and is the Hill estimator for binned data. As you suggest,
the supplement states that the constants should be read off the image under test rather
than assumed from the kernel version, and reports them as the explanation the mode's
location supports rather than as an independently measured cause.

## Internal correctness

**R1 — the abstract's denominator.** Correct, and this is the worst of them because it is
the most-read sentence. 0.36% is the minimum over the 71 cells whose own summary we
captured; over all 223 runs the minimum is 0.0044%, four samples kept of 90,490. The
abstract now quotes the range against the population it came from, and Section IV-B gives
both figures with the ledger-wide one spelled out.

**R2 — "1.5 million".** A hand-typed round number appearing twice, matching neither
topology. The artefact holds 905,040 one-clock and 905,040 cross-host samples, zero
negatives in each. Both are macros now. In a paper about benchmarks that miscount their own
samples this was the least affordable defect in the manuscript, and we are glad it is gone.

**R3 — the saturation claim.** You are right that a rate ceiling is not an occupancy. The
inversion rate's ceiling is 0.37; the preempted-state probability at saturation is
0.68–0.89. Under Equation 6 an event can be stamped by a preempted thread and still not
invert, whenever the stall is shorter than the interval. The sentence now says that.

**R4 — idle-to-knee growth.** The artefact holds an inversion rate, not a mass beyond one
millisecond. Reworded and macro-backed (×5 core width, ×61 inversion rate).

**R5, R6, R7** — both estimator windows now stated; one offset figure (0.067 ms) used
throughout with the other two sites cross-referencing it; the abstract says "a median on
the millisecond grid" rather than "the same median", since there are two.

## Source characterisation

**R8 — NIST.** Corrected, in the text and in the bibliography note, which was still
carrying the wrong paraphrase after the text was fixed. NIST's worked budget has reaction
time at 230 ms against display resolution at ≈3 ms; reaction time dominates. Their
short-interval remark is that resolution becomes significant against the instrument's
*rated accuracy*, which is what we now say. The pairing itself — both of our failure modes
in one budget — survives and is still the point.

**R9 — Villain et al.** Also corrected. The violation is on FreeBSD's *outgoing* socket
path, which is generated by a loopback copy; it is present under every stress pattern
including none; and scheduling is named as a general host-latency source, not as the cause
of the causality violation. The sentence now reports what they found and what cannot be
bounded, then states what we add. This is the second consecutive round in which this
section has needed a source correction, so we re-read every sentence in it against the
cited text before resubmitting.

**R10, R11, R12 — the bibliography.** The Swami & Sonawane entry had the wrong title and
both first names wrong; it is Akul Swami and Dnyaneshwar Sonawane, with the full
Jetson Orin Nano title. YCSB #41 is Mike Wiederhold, fixed by PR #42 in 0.1.4. Kuperberg
et al. ICPE 2011 is pp. 151–156. Kundel now carries Springer Theses and its DOI. The Redis
driver is no longer its own bibitem — the benchmark is cited once and the file and line
appear in the text, where a reader can act on them. Editorial commentary has been stripped
from the notes throughout; that is also where R8's error had survived.

## Positioning

**R13 — OWAMP.** Taken, and it improves the paper. RFC 4656 has attached a synchronisation
flag and an error estimate to every timestamp since 2006, and requires that a packet
stamped in the future be recorded unaltered rather than dropped. Rule 5 now cites it and
says we are asking for no more than that, applied where brokers and language runtimes
report latency and where nobody does it. A rule with a twenty-year-old standard behind it
is a stronger recommendation than one presented as new.

**R14 — the stream-processing benchmark literature.** A fair hit: the section rested on one
DEBS paper and OMB while the manuscript is positioned against streaming benchmarks. Added
Karimov et al. (ICDE 2018), Van Dongen & Van den Poel (TPDS 2020) and Fruth et al. (TPCTC
2021), with the framing you propose: that community already prescribes one-clock,
outside-SUT measurement — at millisecond resolution, and without checking the sample the
instrument keeps. Van Dongen's "a single Kafka broker to ensure correct latency
measurements" is our one-clock rule arrived at independently, and we say so.

**Reference cap.** Five added, five cut (Kreps, Kleinrock, McCanne & Torek, Swami &
Chougule, and the Redis driver as a separate entry), holding exactly 45. McCanne & Torek
moved to the supplement's fuller dither account rather than being lost.

## Disclosure

**R16 — the tracer.** Both omissions were real and both were already in the artefact tree.
The trace filters to the harness processes, which the text now states, and the campaign ran
the same cell untraced: 0.272 untraced against 0.231 traced, z = 3.6. The prediction is
compared against the traced arm's own rate, so the agreement is between two instruments
observing one machine; the untraced rate is the one to quote for the machine. A paper about
instruments that change what they measure should not have needed to be asked for this.

**R17 — the supplement's review labels.** This is the one we are most grateful for. Nine
sections read "TPDS round 1" and three passages referred to "the TC submission" or "the TC
revision". Read cold that says the manuscript was reviewed at two journals. It has been
reviewed at none — those were adversarial reviews conducted inside the project. Every label
now reads "internal review, round N", and the front matter states explicitly that the
manuscript has not been submitted to or reviewed by any journal, and why the rounds are
recorded at all.

**R18, R19** — Section VI now says it compares on the transport proxy and points at the TTI
equivalence; the rank-correlation sentence has been replaced by the argument that actually
holds, which is that a two-valued predictor cannot account for a 279-fold range whatever
its correlation.

## Figure 1

You did not raise it beyond a minor note, but we triple-checked the diagram and found one
real defect. Panel (a)'s arithmetic verifies against Equations 1 and 2 by both routes
(δ_ack = 2.2, δ_recv = 0.6, T_true = 1.0, Δ = −1.6, T_meas = −0.6), and its causal ordering
is sound. But it drew the acknowledgement and the record arrival as a left-to-right sequence
with no common cause — inviting precisely the causal-chain reading Section III-C exists to
refute. The broker's append and its two branches are now drawn, and the caption says
neither arrival precedes the other.

Panel (b) had been wrong twice in opposite directions: a bell curve in the first version, a
monotone heavy tail in the second, each drawn to a shape the data had not been asked about.
It now shows the running core and the preempted lobe at the scheduler slice, and the caption
labels it schematic with the measured mode's position.

## On the pattern

Three rounds, and each has found at least one number that survived internal review and
failed the first time it was estimated or recomputed with its denominator named. We record
that in supplement S35 because it is the paper's own argument turned on its author: a
statistic that carries no uncertainty, and a number that reaches the page without passing
through a script, are not yet measurements. Every correction from this round is gated.
