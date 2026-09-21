# A2's three kernels boot, and each runs at the tick it was built for

**21 September 2026, on the matched-b driver (`6.8.12`, Ubuntu's `linux-azure` source).** Not a
test of any prediction. A2 asks whether the cliff's width follows the tick, and that question is
only worth asking if the three kernels really differ in the tick and really run at it. This is the
check the plan puts before the block.

**Words used here.** *Tick* — the regular timer interrupt the kernel wakes on; fixed when the
kernel is compiled. *HRTICK* — a scheduler option that ends a slice on a high-resolution timer
instead of at the tick; if it were on, A2 would measure nothing. *Tickless* — the settings that
let an idle CPU stop its timer.

## What the three show

| built for | release | tick counted | out by | HRTICK | passed |
|---|---|---|---|---|---|
| 1000 Hz | `6.8.12-sbl1000` | 999.958 Hz | 0.00% | off | yes |
| 250 Hz | `6.8.12-sbl250` | 251.231 Hz | 0.49% | off | yes |
| 100 Hz | `6.8.12-sbl100` | 101.367 Hz | 1.37% | off | yes |

Counted over about ten seconds each, with one CPU held busy. The plan allows 5%. The tickless
settings are identical across all three, which is what holds them to differing in the tick alone:

    CONFIG_NO_HZ=y   CONFIG_NO_HZ_COMMON=y   CONFIG_NO_HZ_FULL=y   CONFIG_HIGH_RES_TIMERS=y

All three were built from one source tree on one machine with one compiler, and each was booted
once through `grub-reboot`, so a kernel that had not come up would have been gone on the next
restart with the stock one still the default. None needed that.

The counted tick runs slightly fast at the two lower settings, and more so the lower it goes —
0.00%, 0.49%, 1.37%. Ten seconds at 100 Hz is only a thousand ticks, so the coarser count is the
likelier half of it; the spinner's own scheduling is the rest. Both are far inside the tolerance
and neither is a property of the kernel, but it is the sort of thing that should be written down
before somebody reads a 1.4% into a result.

## Two faults this found, and why they mattered more than the result

Neither is about the kernels. Both are about the check, and both would have stopped A2 dead while
looking exactly like a broken kernel.

**The check counted a timer Azure does not use.** It read the `LOC` row of `/proc/interrupts`,
the local APIC timer. An Azure guest ticks on the Hyper-V synthetic timer, `HVS`; `LOC` is present
and holds zero for the life of the machine. So the count came back 0 Hz, and the check reported a
freshly built and perfectly healthy HZ=1000 kernel as 100% out. It would have said the same of all
three. Measured on the machine, with one CPU pegged: `LOC` flat at zero on all eight CPUs, `HVS`
moving 4004 ticks in four seconds on the busy one — 1001 Hz, against a kernel built for 1000.

**Nothing was keeping a CPU busy.** The tick is counted on the busiest CPU because an idle one
stops its timer, and the check ran on an idle machine, so there was no busy CPU to count on. The
kit now holds one busy for the length of the count, with three independent ways for that loop to
die — the last stray busy loop here sat at 99.7% of a CPU and spoiled A3's measurements until
somebody measured the idle baseline and found it was not idle.

A third, smaller one: whether HRTICK is on is only readable by root, and this kit deliberately
runs its checks without sudo, so the answer was always "could not be read" — a true sentence that
correctly refuses to let A2 run, and that accuses the kernel of what is really a permissions
problem.

## How much of A2 the pair can actually reach

Read off the design before the first session ran, from matched-b's own calibration: a campaign
cannot place a trip shorter than the client's own trip with no delay added, and on this pair that
is **2.32 ms for Kafka** and **0.99 ms for Redis**.

| | slice 1.5 ms | slice 3.0 ms | of 16 |
|---|---|---|---|
| Kafka | `f15h`, `f2sh` only | everything but `p05s` | **9** |
| Redis | everything but `p05s` | everything | **15** |

The two plateau points are `p05s` and `p09s`, at 0.5 and 0.9 of the slice. **They carry no tick
term**, so unlike every other point they do not move when the kernel changes — which means this
table is the same for all three kernels, and knowing it once is knowing it for the block.

What it costs is specific rather than general. On Kafka at the 1.5 ms slice the only survivors are
the two floor points, so that curve has no plateau at all and no cliff can be fitted in it; P2's
width is not available there on any kernel. At the 3.0 ms slice Kafka keeps `p09s` and the four
cliff points, which is a whole curve. Redis keeps a whole curve at both slices. So A2's questions
are answerable on Redis at both slices and on Kafka at the anchor slice, and not on Kafka at 1.5.

This is the same shape as Redis's plateau being too shallow for P3a and P4 in A3: the instrument
reaching a limit, stated as a limit. Nothing here is adjusted to get around it — the slices are
frozen (D3-7), and changing them to suit what this pair can reach would be choosing the
measurement to fit the prediction.

## A correction to freeze 13, which cannot be corrected in freeze 13

Freeze 13 says, of the campaigns running when it was written, that "A2's first session ran under
earlier versions and is reported under them". That was written while it was about to be true and
it is not true. The timestamps:

| | |
|---|---|
| freeze 13 public | 21 September 2026, **14:01:37 UTC** |
| A2's first session started | **14:07:23 UTC**, five minutes and 46 seconds later |

The plan's rule that no run starts before its freeze is public was therefore kept. What was not
kept is the other half: the driver was still carrying the code from before freeze 13, so those
runs were judged by version 16's brake while version 17 was the plan in force.

The session was stopped after **two runs** and started again at **14:17:44 UTC** on the new code.
The reason is not bookkeeping. A2's twelve sessions exist to be compared with one another, and a
first session judged by one brake against eleven judged by another is a block with a seam down
the middle of it. Fifteen minutes was the whole cost.

The two runs of the stopped campaign are kept where they fell, in
`runs/azure/stage1/matched-b_20260921T140723Z`, with the console log beside them; they belong to
no result. A freeze is never edited, so the sentence in freeze 13 stands and this is the
correction.

## The twelve sessions, and the order they run in

The plan asks for twelve sessions of one kernel and one backend each, over four days, with each
kernel running with each backend on two different days and each kernel taking the first, middle
and last slot across the days (D4-7). Two bridge sessions on the stock kernel tie the results
back to A1, A3 and A5, which run on it. Written down here because a counterbalance improvised
session by session is not a counterbalance.

| day | first | middle | last |
|---|---|---|---|
| 1 | **1000 kafka** | 100 redis | 250 redis |
| 2 | 250 kafka | 100 kafka | 1000 redis |
| 3 | 100 redis | 1000 kafka | 250 redis |
| 4 | 1000 redis | 100 kafka | 250 kafka |

Each kernel appears once a day, so four times; each kernel–backend pair twice, on different days.
Slots taken: HZ=1000 first, last, middle, first; HZ=250 middle, first, last, last; HZ=100 last,
middle, first, middle — every kernel first, middle and last at least once. Kafka and Redis take
six sessions each.

Day 1's second and third sessions are swapped from the order first written here, and the reason
is worth keeping rather than tidying away. A waiter meant to start the third session when the
second finished read a completion line the *first* session had left behind, and started the third
while the second was still calibrating — rebooting the machine out from under it. It cost about
two minutes and no runs, because the second session had not started making any. The same fault
had happened once already that afternoon on the other pair, and the lesson is the same: a waiter
must remember what was there when it started and wait for something new, not read the last line
of a log that another campaign wrote.

Each kernel still runs once on day 1, which is what the counterbalance asks; only the order
within the day changed.

The bridge sessions run on the stock kernel, one before day 2 and one after day 4, so that the
tie back to A1 and A3 is measured at both ends of the block rather than once.

Each session is one command, which starts the pair if the watch has deallocated it:

```
HOSTS_ENV=cloud/hosts_b.env bash cloud/azure/a2_session.sh 250 redis
```

The session's calibration reaches further at the longer ticks, because A2's longest point is a
trip of twice the slice plus twice the tick: 8 ms at HZ=1000, 16 at 250 and 32 at 100. That is
computed by `a2_session.sh`, not typed, because a calibration that falls short does not fail —
the design silently drops the setups it cannot reach.

## What this does not show

Nothing about the cliff, the tick's effect on it, or A2's predictions. It says the instrument is
what it claims to be. A2 still runs at the floor of 4 rounds with its power unknown, because the
rounds rule simulates one kernel at a time and the tick predictions compare two — that remains the
largest open risk in the plan and this changes none of it.
