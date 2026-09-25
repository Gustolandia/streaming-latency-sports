# A5's core counts have to be asked for at boot, and `maxcpus` is not the way to ask

**21 September 2026, matched-b driver, stock kernel `6.8.0-1064-azure`, eight vCPUs.** Not a test
of any prediction. A5 gives each core count its own session, and it had never run at anything but
eight CPUs, so this is the first time that path was exercised at all.

**P7, judged under version 30 (25 September).** Held to P1's band alone, as the plan writes it (D30-2): confirmed on Kafka at 8 CPUs, the one core count whose slice Kafka reaches; not confirmed on Redis, where the fitted shape misses at all three. See [`judged-again-under-version-30.md`](judged-again-under-version-30.md).

**Words used here.** *Base slice* — how long the scheduler lets a helper run before switching; the
kernel picks a default. *Offlining* — switching a CPU off on a running machine. *`nr_cpus=N`* — a
boot parameter capping how many CPUs the kernel will ever know about. *`maxcpus=N`* — a boot
parameter bringing only N up at boot, leaving the rest present and addable later.

## The machine will not give up a CPU

The calibration that was to precede A5's two-CPU session stopped itself on its first three runs,
each recording

    ERROR: [Errno 16] Device or resource busy

from the write to `/sys/devices/system/cpu/cpuN/online`. Tried again by hand later the same day,
same machine, idle, stock kernel, every CPU answered `I/O error` instead. Two errno, one refusal,
`CONFIG_HOTPLUG_CPU=y` in the running kernel throughout, nothing in `dmesg`. That is what a
hypervisor holding channels on the CPUs looks like from inside the guest.

## Asking at boot works, and the slice follows

A one-shot grub entry built from the running boot's own `/proc/cmdline` with one parameter added,
selected with `grub-reboot` so it applies to the next boot only:

| CPUs asked for at boot | online | default base slice | `700000 × (1 + ilog2(n))` |
|---|---|---|---|
| `nr_cpus=2` | 0–1 | 1,400,000 ns | 1,400,000 |
| `nr_cpus=4` | 0–3 | 2,100,000 ns | 2,100,000 |
| (none) | 0–7 | 2,800,000 ns | 2,800,000 |

Exact at every point, with no free parameter: the constant is 700,000 ns, recovered from the
machine rather than guessed from the version number, and `tunable_scaling` is 1 (log) throughout.

## `maxcpus` looks like the same thing and is not

The same entry with `maxcpus=2` instead came back with **all eight CPUs online and the eight-CPU
slice**. The parameter was honoured — it is there in `/proc/cmdline`, and the kernel did bring up
two — but Ubuntu ships a udev rule that onlines any CPU that turns up offline, and it had the
other six running before anyone could look.

A session that had reached its core count this way would have run at eight CPUs, at the eight-CPU
slice, under a run directory saying `c2`. It would not have failed. That is the shape of fault
worth naming: `nr_cpus` is the parameter, and not because it is tidier.

## What the original design would have read, if the machine had allowed it

Worth knowing, because "the machine refuses" and "the method was wrong" are different findings and
only the first is true here.

On the `maxcpus=2` boot the extra CPUs were hot-added by udev, which means they could also be
taken away again — so the removal path can be measured on that machine even though it is refused
on a normal one:

| CPUs online | base slice |
|---|---|
| 8 | 2,800,000 ns |
| 4 | 2,100,000 ns |
| 3 | 1,400,000 ns |

The slice tracks the online count at runtime, immediately, in both directions. So A5's original
design would have read the right slice had the machine let it offline anything. The three-CPU row
is the useful one: a true logarithm would give 1,809,500 ns there, and the kernel gives
1,400,000 — the rule rounds down to a whole power of two, which is `ilog2`, and only a count that
is not a power of two can show it.

(CPUs 0 and 1 are the boot CPUs and stay. CPU 2 refused with `I/O error` even there, so six of
eight was as far down as that boot could go.)

## What this does not show

Nothing about the cliff. P7 asks whether the cliff follows the core count; this establishes that
the machine can be put at a core count at all, and that the slice — the mechanism the prediction
rests on — follows it exactly. The two remaining A5 sessions still have to run, and the block's
result is not in hand.

## A fault this turned up, which had nothing to do with A5

Installing A2's three built kernels made one of them grub's default. `GRUB_DEFAULT=0` means the
first menu entry, which is whichever kernel sorts highest, and `6.8.12-sbl1000` sorts above
`6.8.0-1064-azure`. Every restart of that driver then came up on the HZ=1000 kernel, silently,
including restarts with nothing to do with A2.

That matters twice. The kit's safety argument for booting a self-built kernel was that the stock
one stays the default, so a kernel that does not come up is gone on the next restart — which was
no longer true. And A3, A5 and A7 all assume the stock kernel, and would have run on a 1000 Hz
build of a different source tree with nothing saying so.

The default is now pinned to the stock kernel by its own menu id rather than by position. It was
found by reading which kernel a restart actually came back on, which is the only reason it was
found at all.
