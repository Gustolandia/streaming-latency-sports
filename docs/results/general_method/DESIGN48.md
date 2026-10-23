# Freeze 45 (plan version 48): block C's placement, amended before any of its judged runs

Version 47 (freeze 44, [`DESIGN47.md`](DESIGN47.md)) stands, with one block amended. Pilot round a ran
block C's three arms as version 47 placed them, and showed that this placement cannot hold on this
testbed. This version moves the card's interrupts, and the consumer's other threads, off the vCPU
where the consumer polls. It keeps C-a, its margin and the arms' loads, and it runs block C's own
pilot before any judged run of block C. No judged run of block C had begun.

## What pilot round a found in block C

- **The testbed.**
  - The driver has an AMD EPYC 9V74 with 8 vCPUs, which are 4 cores of 2 hardware threads each.
  - It runs kernel 6.8.0-1064-azure with voluntary preemption. Time in interrupts is not counted
    apart from the task it interrupts (`CONFIG_IRQ_TIME_ACCOUNTING` is unset). The real-time
    throttle allows 950 ms in each second.
  - One card, an mlx5 virtual function with 8 queues, carries both clients' traffic and the three
    captures.
- **Where the interrupts went.** Version 47 put "the receiver's interrupts on the isolated vCPU".
  With one card, that means every network interrupt of the machine. In all three arms, every mlx5
  interrupt and every NET_RX softirq ran on vCPU 6: 186,702 to 430,424 interrupts in a run.
- **What happened to the consumer that keeps the core.** At real-time priority, alone on vCPU 6,
  the consumer ran at 0.95 of that vCPU. That is the throttle's ceiling, and the figure includes the
  receive path's work, which this kernel charges to the task it interrupts.
  - In one run, the producer's acknowledgements, received on that same vCPU, came late enough that
    the producer fell 388 ms behind.
  - In the other run, the consumer read no message. Its heartbeat thread, at the same priority on
    the same vCPU, never ran, and the broker removed the consumer from its group 10 s after it
    joined.
  - The sibling-loaded arm passed its integrity rule at the same ceiling. Its `W` had a tail near
    46 ms in both load states.
- **The baseline arm.** Its consumer, at real-time priority and not pinned, used 0.58 of a CPU
  under the same interrupt placement.

## What changes (D48-1)

In all three arms of block C, the card's interrupts go to the chosen core's other hardware thread
(`irq_cpus: sibling`). irqbalance stays off and receive packet steering stays off, as before.

In the two arms that keep the core:
- the consumer's main thread, the one that polls, stays alone on the core's first thread;
- every other thread of the consumer moves onto the core's other thread as soon as it appears
  (`threads_apart`, by `scripts/thread_apart.py`). kafka-python's heartbeat thread is among them;
- every other process of the run stays off both threads of the core;
- the load runs on the six other vCPUs, and in the sibling-loaded arm on the core's other thread as
  well.

The baseline arm keeps its consumer unpinned, with the interrupts placed as in the other two arms.

Why this placement:
- The core stays whole for the consumer's polling thread.
- The consumer's own vCPU no longer carries the machine's receive path.
- The receive path and the consumer's other threads sit on the core's other thread. Their work there
  is the same in the on-blocks and the off-blocks, so it cancels in the residual that C-a reads
  within each run.

Placements considered and not taken:
- **The interrupts on a loaded vCPU.** This adds a term driven by the load, of a different size in
  each arm.
- **The receive path raised above the consumer.** The consumer would no longer be alone on its
  vCPU, and its heartbeat thread would still starve.
- **The consumer below real-time priority.** That is another question.

Unchanged: C-a, its margin (the residual with the sibling idle at most a third of the baseline
arm's), and the arms' loads (70%, 53% and 61% of the machine).

## Block C's pilot (D48-2)

After this version is public, and before any judged run of block C, one run of each arm is made at
the starting duty of 75 ([`gpilot_c48_design.json`](gpilot_c48_design.json)). Before the judged
runs, the record states each arm's frozen duty, corrected as D47-11 corrects it, and C-a's power by
the rule of version 45. It also states, for each arm:
- **The interrupts.** At least 99.9% of each card interrupt's count, and at least 99% of the NET_RX
  softirqs, ran on the core's other thread. Receive steering was off on every queue. irqbalance was
  stopped during the run and restored after it.
- **The threads.** In the arms that keep the core:
  - the main thread was seen only on its own vCPU;
  - every other consumer thread ended on the core's other thread (`thread_apart.json`);
  - both clients ran at SCHED_FIFO 80;
  - every other process of the run stayed off the core.
- **The consumer's main thread** stayed below the throttle: at most 0.70 of its vCPU over the run's
  middle half.
- **The broker's log** shows no member removed from the group, and no rebalance, after the first
  send.
- **The integrity rule and its lateness rule** hold, and the on-blocks' load is within 3 points of
  the arm's.

An arm that still fails one of these once its duty is found is left out, with the reason, before
any judged run (as D47-11 leaves a setup out). C-a is then out of reach.

## The order (D48-3)

Block C's pilot and judged runs come after blocks V, N, P, K and S on the x86 pair. Version 47 ran
block C before block S.

## What was read before this version (D48-4)

- Pilot round a's block C runs, read for their interrupt counts, their consumers' scheduler counters
  and their brokers' logs ([`README.md`](README.md), the pilot's record).
- The placement, read against how the kernel runs real-time tasks and its receive path.

No judged run of block C had begun.
