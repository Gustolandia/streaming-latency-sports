# Response to simulated referee report — IEEE Transactions on Computers round 1

> **Internal QA artefact — simulated review.** The referee report answered below was an
> adversarial review generated inside the project, before any journal submission, to
> stress-test the manuscript against IEEE TC's standards (source report:
> `REFEREE_REPORT_TC_SIMULATED.md`, kept untracked). The paper has not been submitted to
> IEEE Transactions on Computers; no text here originates from, or is addressed to, any
> real reviewer or journal.

Manuscript: *When the Interval Is Smaller Than the Instrument: Two Ways Streaming Latency
Benchmarks Fail on Sub-Millisecond Paths*.

Verdict returned: **needs major revisions**, with acceptance expected on resubmission.

The report's most useful demand was M8, and it did not do what either side expected. Asked
to replace an eyeballed slope with an estimate carrying an interval, we found the estimate
refuted the claim it was meant to support. That withdrawal is the largest change in this
revision. Three of the ten items (M2, M3, M8) were fixed in the analysis pipeline rather
than in prose, on the principle that a number which reaches the page without passing
through a script is the one that goes wrong — which is, after all, this paper's subject.

Build after revision: 10 pages against TC's 10–12 budget, exactly 45 references against a
cap of 45, a 195-word abstract against a 100–200 range, 0 errors, 0 undefined references,
0 overfull boxes, and a 41-page supplement. All four gates green; 2,239 tests pass, 35
skipped with written reasons, 0 failing.

## Major points

**M1 — Sharma et al. mischaracterised.** Corrected. We had written that they "see
violations from 3 ms"; their abstract says no violations are observed up to 3 ms, with
clear violations by 5 ms. The sentence now reports their null result as a null result, and
"a threshold below which skew may be ignored" — a paraphrase they did not write — is now
"a threshold in skew". A new pin, `test_their_skew_result_is_reported_as_they_reported_it`,
fails if either drifts back.

**M1-bis — the point we were leaving on the table.** Taken, and we are grateful for it.
Sharma et al. state that "queueing alone cannot produce negative timing spans or cause
timestamps to imply reversed causal orderings". Mode A is a direct empirical
counter-example to that sentence, and describing our result as merely *qualifying* their
reading undersold it. The paragraph now quotes the premise and answers it: inversion rates
near 23% at 88% utilisation with no skew available to blame, and a fiftyfold move in that
rate without touching a clock. We are careful to contradict the premise and not their
measurements, and the test now enforces that scoping.

**M2 — Table II printed uncorrected p-values under a caption claiming correction.** This
was the most embarrassing finding and the fix is structural. You are right on every count:
all ten powered arms reject at raw *p*; the two arms we named as exceptions are the
*unpowered* ones; and the arm that actually fails the Holm correction, 900 msg/s, was
printed as a rejection (raw 0.044, adjusted 0.131).

Rather than retype the table, we removed the opportunity. `stat_intervals.py` gained a
tested `holm()` and a `grid_cells()` reader that derives each verdict from the *corrected*
value, and Table II is now generated into `docs/generated/grid_table.tex` and gated by
`emit_paper_numbers.py --check`. A third verdict, "not resolved", was added because the
data needed one: 900 msg/s is now reported as neither support nor refutation. Your
observation that the suite had no pin on the grid inference was also correct; it has eleven
now.

**M3 — "the 49 runs on an unsaturated path".** You could not reconstruct that denominator
because it does not exist. Replaced with what the artefact supports, which is the stronger
sentence: of 75 instrumented cells whose own summary we captured, 71 report a median of 1.0
or 2.0 ms, and across those the retained fraction runs from 0.36% to 100%. The illustrative
example is better too — two replicates of a *single* cell, same payload, same rate, same
host, kept 431 and 120,434 samples and both reported a median of 1.0 ms. All of it is now
macro-driven from `retention_cells()`.

**M4 — the Redis negatives are not a "candidate" mechanism.** Correct, and thank you for
reading the driver. `RedisBenchmarkConsumer.java` line 72 takes the publish timestamp from
`entry.getID().getTime()`, the stream-entry identifier the Redis *server* assigns on
`XADD`, while the Kafka driver uses a producer-set stamp. The Redis span is therefore a
difference between two millisecond-floored clocks on two hosts, and −1000 µs is the only
negative value that construction can express — which is exactly what the corpus contains,
and also why the Kafka-driver span, floored inside one JVM, never goes negative at all. The
hedge is gone, the driver is cited, and the threats section no longer offers cross-host
skew as the explanation. As you say, this makes the claim stronger rather than weaker.

**M5 — Villain et al. (ISPCS 2012).** Cited, and scoped against explicitly rather than
mentioned. Their finding — that a socket timestamp taken under load "does not respect
causality", with process scheduling named as the cause, measured against a DAG hardware
reference — is Mode A's physical primitive, published in 2012 and measured more precisely
than we measure it. The paper now says so in those words and states what we add: a span
whose endpoints are written by two different threads, a probability law relating the
inversion rate to the interval being measured, and manipulations separating scheduling from
its rivals.

**M6 — the geometry over-claim.** Withdrawn in both places it appeared. "Impossible if the
rate were a function of ρ" is true only of the single-parameter form we ourselves adopted
and pre-registered; multi-server queueing is geometry-dependent at fixed ρ in any textbook.
§II-D's companion claim, that the contrast would be flat under exact work conservation, was
wrong for the same reason and is also gone.

**M7 — missing citations.** All added, with ten citations dropped to hold exactly 45:
Hoefler & Belli (SC'15) and Kalibera & Jones (ISMM'13) for the reporting and rigour
literature; Gregg for `runqlat`, which is our own method; NIST SP 960-12, which is the
right canonical anchor for the paper's unifying claim and which we are glad to have been
pointed at — metrology has carried reaction time and display resolution in one uncertainty
budget for a century, and the paper now concedes that the pairing is not ours. Also RFC
3432 and McCanne & Torek for the dither lineage, OMB PR #398 for the second silent-loss
mode in the same harness, the Redis driver source, and Swami & Sonawane for concurrent
pre-registered measurement work. RFC 2679 replaced by RFC 7679, which obsoletes it.

**M8 — the tail exponent. This one changed a result.** We took the first of your two
options and it destroyed the claim, so we ended up taking both.

`scripts/tail_index_traced.py` (new, 46 tests, 98% branch) estimates the index on the same
551,956-wakeup histogram by grouped-data maximum likelihood with a profile-likelihood
interval, and independently by an exceedance ratio on the exact counters with a Wilson
interval. The exceedance index over 0.5–2 ms is 0.21 (0.20–0.21); grouped maximum
likelihood over the same decade returns 1.19 (1.18–1.20). Two estimators of one quantity
cannot differ sixfold unless the model is wrong, and it is: the per-octave indices over
that window run 1.96 and then 0.03, where a power law would give the same value twice.

The 0.332 we had quoted was ordinary least squares through four nested survival points,
which returns a number whether or not the points lie on a line. Its agreement with the
payload exponent was a coincidence of window and estimator, and we should not have offered
it as an independent confirmation. **Withdrawn.** Equation (7) is demoted to the
supplement, as you suggested, since without the cross-check it stands on four points alone;
the main text keeps the model-free exceedance estimate with its interval and the
qualitative conclusion, which needs no exponent and is what the argument actually used.

The withdrawal took a second claim with it. The supplement's "α below one, so the stall
distribution has neither a finite mean nor a finite variance" had been contradicting the
main text's own withdrawal of the infinite-moment reading since the previous revision. Both
are now recorded in S35.5.

**M9 — "Manuscript submitted to ACM" on a supplement bound for IEEE.** Fixed with
`nonacm`; verified absent from all 41 pages. Your framing was the useful part: not a rule
violation, but precisely what a Computer Society prescreener is told to look for.

**M10 — rendering defects.** Four doubled cross-references ("the main text's the main
text's …"), left by an earlier neutralisation pass, repaired. Figure 1(b)'s title no longer
asserts `P(inv) ∝ T^−0.34`; it states only the qualitative claim the text still supports.

## Minor points

All sixteen were taken. The ones that changed a number rather than a word:

- **7 — name the coefficient and *n*.** Doing so revealed that "+0.075" had come from an
  unstated denominator. On the stated one it is +0.31 (Spearman, *n* = 71). We report it,
  and note it is the sign Equation (4) predicts and far too little to explain a 279-fold
  range. Publish latency across those cells takes only two values, 0.3 and 0.4 ms, which
  makes the point better than the correlation did.
- **11 — the netem numbers need *n*.** Added (medians of the transport component, five
  feeds per arm). Checking them surfaced an arithmetic error the report had not caught:
  batching the acknowledgements cuts the median from 4,138 ms to 103 ms, which is a factor
  of **40**, not 103. The supplement had 40.2 all along.
- **15 — reference hygiene.** Kreps et al. was attributed to NSDI; it is NetDB. Lozi et al.
  gained pages, and the OpenMessaging entry gained an access date.

The rest: the abstract's opening now says "larger than the intervals they report"; the
opening register is "Stated plainly" rather than "In plain terms"; the workload names
StatsBomb open data and its licence; the gate section states that the threshold sweep runs
0–20% with no condition usable anywhere in that range; §III-F names the scripts and says
the tables are generated; the guard's line number sits beside the pull request; the Python
harness is described as independent rather than by its line count; "our first result" is
used consistently; the two-state ratios name what they multiply; the TOST now prints its
result (Hodges–Lehmann 0.408 ms, 90% interval 0.389–0.419, both one-sided nulls rejected at
*p* < 0.001, shift stable across three concurrency levels) instead of asserting equivalence
without a test.

## On the artefact statement

You noted that "the test suite fails if the text and the data disagree" was, before this
round, a stronger claim than the suite. It was — the grid inference had no pin at all. It
now has eleven, the traced tail index has forty-six, and Table II is generated rather than
transcribed. We would rather the claim were true than impressive.
