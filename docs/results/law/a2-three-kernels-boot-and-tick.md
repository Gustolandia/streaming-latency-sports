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

## What this does not show

Nothing about the cliff, the tick's effect on it, or A2's predictions. It says the instrument is
what it claims to be. A2 still runs at the floor of 4 rounds with its power unknown, because the
rounds rule simulates one kernel at a time and the tick predictions compare two — that remains the
largest open risk in the plan and this changes none of it.
