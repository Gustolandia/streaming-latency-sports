# The registry: every run, the machine it ran on, and the settings it ran under

Kept under plan version 32 (D32-4) by `scripts/run_registry.py`, run on each pair's own disk over
every run folder and every campaign folder it holds, and written again when the last campaigns
are home. The faults the campaigns met are in [`../law/issues-register.md`](../law/issues-register.md).

**Words used here.** A *run* is one trial at one setup, judged by the integrity rule the moment it
ends. A *campaign* is the runs of one question in one sitting, from its own shuffled queue. The
*slice* is how long the scheduler lets a thread run before it may switch; the *tick* is how often
the kernel's timer interrupts. *Recorded half* marks a run in the random half whose scheduling was
traced.

## `runs_<pair>.csv`: one row per run

| Column | What it is |
|---|---|
| `run`, `campaign` | the run's folder, and the campaign its name carries |
| `pair`, `driver`, `driver_size`, `broker_size`, `image` | the machine pair, the driver's name, both machines' Azure sizes and the image they were made from (`cloud/azure/testbed.json`) |
| `commit` | the code the run ran, from the run's own lane note |
| `block`, `setup`, `round`, `attempt` | what the run was for, from its queue row; an attempt above 1 is a run the queue put back after a mechanical failure |
| `backend`, `load_pct`, `slice_set_ns`, `point`, `delay_set_ms`, `ack_batch`, `cpus`, `language`, `priority`, `plan` | the settings the design gave it |
| `delay_held_ms` | the delay the broker actually held, from the broker's own capture of the run's delay pings |
| `recorded_half` | whether the run's scheduling was traced |
| `kernel`, `config_hz`, `tick_ms`, `cpu_model`, `online_cpus`, `slice_in_force_ns`, `clocksource` | the scheduler's own reading just before the run |
| `verdict` | `count`, `repeat` or `stop`, by the integrity rule |
| `trip_median_ms`, `gotit_median_ms`, `measured_negative_rate`, `messages` | what the run measured, after its warm-up |
| `gotit_brake`, `reasons` | what the got-it brake said where it records rather than stops (D26-1, D32-1), and why a run did not count |

## `campaigns_<pair>.csv`: one row per campaign

| Column | What it is |
|---|---|
| `campaign`, `folder`, `block` | the campaign's queue and folder |
| `kernel`, `cpu_model`, `online_cpus` | the machine as the campaign's session read it |
| `designed_runs`, `done`, `left`, `failed_attempts`, `abandoned` | from its queue: every setup once a round, what was done, what was never reached, how many attempts failed and were put back, and what was given up after three |
| `complete` | nothing left and nothing given up |
| `ended` | how its log ends: complete, stopped on a named rule, stopped by hand, or not ended |
| `first_started_utc`, `last_finished_utc` | its first and last runs |

## The three pairs, as collected on 27 September

Each pair's files were written by its last job, after every campaign on its list had run, and came
home with its runs, each checked against the driver's own fingerprint.

| Pair | Files | Driver, broker | Processor | Kernel: runs | Runs | Campaigns, complete |
|---|---|---|---|---|---|---|
| first x86 | `runs_matched.csv`, `campaigns_matched.csv` | Standard_D8as_v6, Standard_D2as_v6 | AMD EPYC 9V74 | 6.8.0-1065-azure: 2,529; HZ=1000: 206; HZ=250: 162; HZ=100: 233; 6.8.0-1064-azure: 65; not read: 3 | 3,198 | 24, 23 |
| second x86 | `runs_matched-b.csv`, `campaigns_matched-b.csv` | Standard_D8as_v6, Standard_D2as_v6 | AMD EPYC 9V74 | 6.8.0-1064-azure: 1,380; HZ=1000: 434; HZ=250: 378; HZ=100: 556; not read: 3 | 2,751 | 22, 21 |
| Arm | `runs_arm.csv`, `campaigns_arm.csv` | Standard_D8ps_v6, Standard_D2ps_v6 | Arm Neoverse N2 (implementer 0x41, part 0xd49) | 6.8.0-1064-azure: 2,159 | 2,159 | 15, 11 |

Every campaign that is not complete is a false start in the
[issues register](../law/issues-register.md), replaced at once by a campaign that ran whole.

A blank `verdict` is a run that ended before the integrity rule could judge it. Of the seventeen,
seven were put back and counted on their next attempt; one is the first run of a false start;
one is the only run of a calibration opened by mistake on top of a running one, void and set
aside; seven are the runs of calibrations that stopped and were run again whole; and one ended a
round of a calibration that kept its other 22 runs. The issues register names each. The six runs
with no kernel reading are among them: three of the seven put back, and the three of one stopped
calibration.

The registries also list the run folders set aside as void, in `runs/azure/quarantine` on each
driver: five on the second x86 pair (16 September, when two calibrations wrote into one folder)
and that one run on the first (21 September). They belong to no campaign and enter no analysis.

## Pocket dictionary

- **Broker**: the machine running Kafka or Redis; the *driver* runs the clients and the load.
- **Calibration**: the session's own measure of how far each added delay moves the trip.
- **Integrity rule**: the checks every run passes before it counts (`scripts/run_integrity.py`).
- **Queue**: a campaign's shuffled list of runs, which also records what happened to each.
