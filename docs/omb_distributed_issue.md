# Draft upstream issue: distributed mode fails inside the coordinator-worker protocol

Status: DRAFT -- not filed. Filing is an outward action for the author to take.
Target: https://github.com/openmessaging/benchmark (issue tracker)

## Title
Distributed mode (coordinator + remote workers) fails before producing any measurement

## Body (draft)
Running bin/benchmark with remote workers (bin/benchmark-worker on a second host), the run
fails inside the coordinator-to-worker protocol before any latency is measured. We attempted
this eleven times across two days on a two-VM Oracle Cloud testbed (Ubuntu 24.04, OpenJDK as
packaged, master as of the commit recorded in our artefact), at three background-load levels
including none. Our measurement artefact
(github.com/Gustolandia/streaming-latency-sports) records the outcome of each attempt --
docs/results/external/omb_distributed_result.csv and the dist_load0/ and dist_load50/ rows
beside it -- and carries the classpath failure in full at external/omb/omb_worker_client.log
and external/omb/omb_worker_driver.log. The coordinator-worker signatures of the three
diagnosed attempts were read from the console and not retained; the signature quoted below is
what we have of them, and we would gladly reproduce the failure on request.

Two classes of failure observed:
1. Worker classpath: shipping the built jars without the Maven dependency tree leaves
   bin/benchmark-worker failing with NoClassDefFoundError; the coordinator then aborts with
   "Connection refused". (Documented in our campaign script omb_distributed.sh; arguably an
   operator error the docs could prevent.)
2. With the full dependency tree shipped, the coordinator-worker HTTP protocol still fails
   before the workload starts: java.util.concurrent.CompletionException wrapping
   java.lang.IllegalArgumentException in the coordinator-worker path, before any workload
   begins.

Relevance beyond our study: in embedded mode the end-to-end timestamp difference is same-host;
in distributed mode it spans two clocks. Any user of distributed-mode latency figures is
exposed to cross-clock effects that the positive-difference guard in
WorkerStats/HdrHistogram silently absorbs -- see the paper accompanying the artefact.
