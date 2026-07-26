# Campaign logs

The stdout of every chain run on the cloud driver, pulled off the VM before it is released.
101 KB for the lot.

These are not results. They are the record of *what ran, in what order, and what happened while it
ran* — which is the thing that becomes unrecoverable the moment the machine goes away, and the
thing a run index cannot capture. A row in `runs_index_cloud.csv` says a run exists; these say why
it was started, what it was waiting for, and whether the step before it failed.

| log | chain |
|---|---|
| `round2.log` … `round5.log` | the numbered replication rounds; round 5 is E-A6b, E-A10b, E-A9b |
| `collapse_chain.log` | E-A3, the dense utilisation sweep |
| `ea5_chain.log`, `post_ea5.log` | E-A5 stamping priority and its follow-ups |
| `ea7_chain.log` | E-A7, the measured-occupancy campaign |
| `ea8_chain.log` | E-A8 co-location — the campaign whose result is withheld |
| `ea9b.log`, `ea9c.log` | the traced run-queue tail, including the two aborted attempts |
| `knee_chain.log` | E-A4, extending the ladder past ρ=0.90 |
| `h3.log` | H3, the stamping-asymmetry test |
| `omb_chain.log`, `omb_chain2.log`, `omb4.log` | the OpenMessaging Benchmark attempts |
| `transport_rt.log`, `window.log`, `window_redis.log` | the powered transport and window sweeps |
| `referee_chain.log`, `followup.log`, `rerun.log`, `resume.log`, `run_all.log`, `round3.log` | orchestration, reruns, and the resume after the 2026-07-23 wedge |

## Why the failures are kept

`ea9b.log` records the campaign aborting on `$!: unbound variable` — a guard that failed closed
before a single cell ran. `omb4.log` is empty because that attempt died before writing anything.
`resume.log` exists because the depth suite wedged and had to be restarted.

Those are in the paper. Section 7.3 reports the traced tail resting on a campaign that took three
attempts; Section 6.7 reports five distinct faults in OMB's worker protocol. A reader who wants to
check that those attempts happened, and failed the way we say they failed, can read the logs
rather than take the count on trust.
