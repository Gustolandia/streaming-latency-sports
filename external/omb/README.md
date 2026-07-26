# The OpenMessaging Benchmark audit

Section 6.7 of the paper claims that an instrumented OpenMessaging Benchmark discarded 6,000
end-to-end samples — about 6.7% of a three-minute run at 500 msg/s under 88% load — while
reporting a healthy latency summary and no counter of any kind.

Everything needed to check that claim is in this directory. Until it was collected here, the
source modification behind it existed only in a working tree on a cloud VM.

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
usable run and none is reported as a result. They are kept because the paper states that the
cross-host clock channel was left untested and bounds it independently at ~0.067 ms, and a reader
is entitled to see that the attempts happened rather than take the sentence on trust.

## Provenance

Upstream is `openmessaging/openmessaging-benchmark` at `5b1fa70`, 7 April 2026. The campaign that
produced all of this is [`../../cloud/campaigns/omb_discard_count.sh`](../../cloud/campaigns/omb_discard_count.sh),
which regenerates the patch, rebuilds, runs, and refuses to write a count unless the run produced
publish output — a guard added after an earlier version reported a zero from a run that had died
four seconds in.
