# R1: the receiver's own wait in the send-timed latency

Written 3 October 2026, before any R1 run. Exploratory: R1 is not part of the registered law
campaign, and whatever it finds is reported as a measurement made after that campaign's verdicts.
The predictions below are written down first only so that the reading cannot bend to the result.

## The question

A latency timed from the send, D = t_recv - t_send, cancels the acknowledging thread's wait for a
core: that wait lengthens the acknowledgment lag A and shortens the transport proxy S by the same
amount, and D = S + A message by message. It does not cancel the receiving thread's wait. The
consumer reads the clock only after its thread is woken and then given a core, so every D carries
that wait, always positive, never seen by a sign check. How large is it?

What is already known, from runs made for other purposes: in the law campaign's traced runs (A9,
303 runs on three pairs, 75 and 88% load, a 3 ms slice), the receiving thread's own wait before
it stamps a message has a median of 11 to 45 us, a mean of 0.44 to 0.98 ms and a 90th percentile
of 2.1 to 3.3 ms. In the law campaign's priority block (A7, first x86 pair, 75% load), go-first
priority for both processes that read the clock lowered D's mean by 0.47 to 0.97 ms and its 90th
percentile by 1.8 to 3.0 ms. Neither isolates the receiver: A7 raised the producer as well, and
A9 measures the wait with a tracer that changes what it records.

## Three measurements, in the same runs

1. **Go-first for the consumer alone.** The consumer process, and nothing else, runs under
   SCHED_FIFO 80 (`consumer_priority`). The fall in D at unchanged load is what priority removes
   from the receiver's side.
2. **The receiving thread's own wait, traced.** In a random half of the runs (`trace_half`,
   `trace_events`), every python3 thread's scheduling events, and the consumer's record of which
   thread stamps the receipt. A message's wait is the time its stamping thread spent waiting for a
   CPU from the later of its last wake and its previous stamp up to this stamp, as
   scripts/helper_waits.py defines it for the acknowledging thread (A9-2b).
3. **The kernel's receive timestamp.** In every run (`recv_capture`), the packets inside the
   receiver's namespace at full length, with the kernel's nanosecond timestamps. A message's
   kernel time is the arrival of the packet that carries the end of its event id in the
   reassembled broker-to-receiver byte stream; its delay is t_recv minus that time, which holds
   the wake-up, the wait for a CPU and the client's own work before it stamps. A message whose id
   is not found is counted and left out.

## Design

The first x86 pair (matched). Both brokers, 75 and 88% load, the base slice set to 3 ms as in
A9, no added delay, 50 messages a second for 130 s with the 30 s warm-up left out. Eight setups
(broker x load x ordinary or go-first consumer), six shuffled rounds, 48 runs
(r1_design.json, seed 20261003). Every run is judged by scripts/run_integrity.py as it ends, and
only runs it passes are read.

## Predictions

- **R1-a (method 2).** In ordinary setups the receiving thread's mean own wait lies between 0.3
  and 1.2 ms, and its 90th percentile above 1.5 ms, on both brokers at both loads. Under go-first
  its mean falls below 0.1 ms.
- **R1-b (method 1).** Go-first for the consumer alone lowers the median over runs of each run's
  90th percentile of D by at least 1 ms, on both brokers at both loads, and moves the median of D
  by less than 0.3 ms.
- **R1-c (method 3).** For at least 95% of the messages that methods 2 and 3 both time, method 3's
  delay is at least method 2's wait; the median of the difference, the client's work after it
  runs, is under 0.3 ms.
- **R1-d (agreement).** Three estimates of the mean inflation, method 1's fall in mean D, method
  2's mean wait in ordinary setups less its mean under go-first, and method 3's mean delay in
  ordinary setups less its mean under go-first, lie within a factor of 1.5 of each other on each
  broker at each load.

Means over messages are taken within a run; a setup's value is the median over its runs. Traced
and untraced runs are reported apart wherever D is compared, since the tracer is not a free
observer.
