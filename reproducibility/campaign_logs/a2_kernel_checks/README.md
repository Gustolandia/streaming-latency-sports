# A2's three kernels: what each one showed at its first boot

Written by `cloud/azure/kernels.sh check <hz>` on the matched-b driver, 21 September 2026, one
file per kernel, each taken on the boot it describes and before any run.

| file | what it holds |
|---|---|
| `check-hz1000.json` | the control kernel's reading and verdict; also the reference the other two are held to |
| `check-hz250.json` | the same for HZ=250 |
| `check-hz100.json` | the same for HZ=100 |
| `built.txt` | every package the build produced, including the `-dbg` symbol packages that are not kernels |
| `source_version.txt` | the source tree the three were built from |

Each reading carries the tick counted from `/proc/interrupts` over about ten seconds with one CPU
held busy, whether HRTICK was on, the tickless settings, and the release actually running. The
`problems` list is empty in all three, which is what let A2 start.

The numbers and what they mean are in
[`docs/results/law/a2-three-kernels-boot-and-tick.md`](../../../docs/results/law/a2-three-kernels-boot-and-tick.md),
which also records the two faults in the check that had to be fixed before any of this could be
read — it counted a timer Azure does not use, and it had no busy CPU to count on.
