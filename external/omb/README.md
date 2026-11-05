# The OpenMessaging Benchmark audit

> **Superseded, 2026-07-26.** This directory holds the *original* single run, in which an
> instrumented OpenMessaging Benchmark discarded 6,000 end-to-end samples — about 6.7% of three
> minutes at 500 msg/s under 88% load. Section 6.7 of the paper of July 2026 read those 6,000 as
> the same causality violation that paper reported. **That reading is withdrawn.** A
> sign-separated sweep across 15 cells found **zero negative samples in roughly 420,000
> discards**, with a discard share that falls as load rises. Every discard was a
> millisecond-tick collision, not a causality violation.
>
> The files here are kept unchanged, and `omb_discard_evidence.txt` deliberately so: every one of
> its eleven counter lines reads `sample_micros=0`, and the Pub-rate lines beside them show a
> median publish latency of 0.4–0.5 ms. The refutation and its mechanism were both in this
> directory from the day it was committed. What was missing was not data but a reason to look at
> the sign, because the statistic we chose to report — one unsigned total — did not have one.
> Regenerating this file would replace the primary record of the withdrawal with a file edited
> after the fact.
>
> Current evidence: `docs/results/external/` (the sweeps), `docs/results/external/omb_retention.csv`
> (what the benchmark reported against how much data survived), and `reviews_and_responses.md`, R1.

The source-level audit is unaffected and never depended on the run: the guard admits only positive
samples, nothing counts the drops, the reported distribution is conditioned on being positive, and
the retention rate is unrecoverable from a completed run.

Everything needed to check the original claim is in this directory. Until it was collected here,
the source modification behind it existed only in a working tree on a cloud VM.

| file | what it is |
|---|---|
| `workerstats_discard_counter.patch` | the modification, as `git diff` against upstream `5b1fa70` |
| `omb_discard_evidence.txt` | the counter's output, the Pub-rate lines, and the summary OMB printed |
| `omb_stdout.log.gz` | the full 28 MB run log the evidence was extracted from |
| `omb_result_kafka_20260725.json` | OMB's own result file for the run |
| `omb_workload.yaml`, `omb_driver.yaml` | the workload and driver as run |
| `omb_workload_dist.yaml`, `omb_driver_dist.yaml` | the distributed variant that never produced a usable run |
| `omb_worker_driver.log`, `omb_worker_client.log` | worker-side logs from the distributed attempts |

## What the patch does, and what it does not

It adds one `AtomicLong` and one `else` branch to `WorkerStats.recordMessageReceived`. The guard
itself — `if (endToEndLatencyMicros > 0)` — is untouched, so the histogram, the reported
percentiles and every number OMB prints are exactly what an unmodified build would produce. The
only new behaviour is a line on stderr when a sample is dropped.

That matters for the claim. If the patch had changed the guard, the 6,000 would be an artefact of
our own edit. It does not, so the discards were always happening; they were simply never counted.

## Reading the evidence

`omb_discard_evidence.txt` shows the counter reaching `total=6000`, interleaved with the run's own
progress lines:

```
Pub rate   498.2 msg/s | Pub err     0.0 err/s | Cons rate   498.3 msg/s
   Pub Latency (ms) avg:  0.9 - 50%:  0.5 - 99%:  4.3 - Max: 18.3
```

Zero publish errors, a stable rate, and a latency distribution nothing would flag — while one
sample in fifteen was being dropped before it reached the histogram. That is the whole point of
the section: the harness cannot report what it discards, and its output gives a reader no way to
tell.

## The distributed variant

`*_dist.yaml` and the worker logs are from five attempts to run OMB in distributed mode, each of
which failed for a different reason in the benchmark's own worker protocol. None produced a
usable run and none is reported as a result. The postmortem's S22.1 counts eleven attempts in
all, none of which completed a run, and S24.1 gives their diagnostics. They are kept because the
supplement's S4.5 says that on the cloud testbed the benchmark's distributed mode could not be
measured, so its exposure to the deletion there rests on reading its source. A reader is
entitled to see that the attempts happened rather than take that sentence on trust.

## Provenance

Upstream is `openmessaging/openmessaging-benchmark` at `5b1fa70`, 7 April 2026. The campaign that
produced all of this is [`../../cloud/campaigns/omb_discard_count.sh`](../../cloud/campaigns/omb_discard_count.sh),
which regenerates the patch, rebuilds, runs, and refuses to write a count unless the run produced
publish output — a guard added after an earlier version reported a zero from a run that had died
four seconds in.

`docs/results/external/omb_patch.diff` (zero bytes) is empty because at capture time the
workspace `WorkerStats.java` was identical to `.orig` — the patch had not been applied in that
workspace; the actual instrumentation patch is tracked here as `workerstats_discard_counter.patch`
(1,629 bytes), and the empty file stays tracked rather than deleted, because a capture that
failed is part of the record.

## Corrections to this README

A number or a pointer in this README that does not match the paper, the supplement, the
postmortem or a record is corrected here, in the open. Each correction gives the date, the old and
the new text, and the reason. The records themselves are unchanged.
- **4 November 2026. Section 6.7 is the paper's of July 2026.** The rebuilt paper has no such
  section; the postmortem's S22 holds this run and its withdrawal. The first paragraph now says
  that that paper reported a causality violation; the rebuilt paper reports none.
- **4 November 2026. The distributed variant.** The postmortem's S22.1 counts eleven attempts
  in all, the five whose files are here among them. The paper no longer bounds the cross-host
  channel at about 0.067 ms: the supplement's S1.1 reports that offset and claims no cross-host
  bound, since chrony bounds its own error at more than the offset. The reason for keeping the
  files now cites S4.5. The supplement never said that the cross-host channel was left
  untested, and S4.5 reports that the distributed mode ran later, on the registered
  campaign's machines.

