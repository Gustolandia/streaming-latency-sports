# Azure testbed

This folder, together with the programs in `scripts/` listed at the end, runs the experiments on
Azure. It creates the machines, sets them up, checks them and every run on them, and removes them
at the end.

**In one paragraph.** Every earlier cloud result came from one Oracle machine type with one
kernel. These files rebuild that layout on Azure with the same AMD chip generation (profile
*matched*), and the same layout on Azure's Arm chip (profile *arm*, the "materially different
machine"). Before any result counts, a *pilot* checks the machine. The scheduler settings must
read back. A delay added on the receiver's path must reach the receiver and nothing else. And the
old go-first test must still work. Then the old Oracle campaigns run unchanged (the
*replication*), and the new campaign runs from a randomised queue. Every run is judged the moment
it ends, a watch on your computer looks at every machine pair every 5 minutes, and each finished
campaign is copied home with a fingerprint for every file.

## Pocket dictionary

| Word | Plain meaning |
|---|---|
| Resource group | Azure's folder for everything we create; deleting it deletes everything |
| Deallocate | stop a machine so its CPUs stop costing money; its disk stays |
| Driver | the machine that runs the sender and the receiver |
| Broker | the machine that runs Kafka and Redis |
| Profile | a named set of machines in `cloud/azure/testbed.json` |
| Receiver-only delay | extra delay on the traffic going to the receiver, and only there |
| Namespace | a private corner of one machine's network, with its own address |
| Base slice | how long the scheduler lets a task run before it may switch to another |
| Tick | the kernel's heartbeat: 1 ms when HZ=1000 |
| Pilot | the checks a machine must pass before its runs count |
| Queue | the shuffled list of runs, which also records what happened to each (the ledger) |
| Lane | one machine pair, a driver and its broker, with its own hosts file, queues and logs |
| Verdict | what a run's checks decide as it ends: it counts, it is repeated, or it stops its campaign |
| Stop rule | a reason for a campaign to stop itself and wait for a person |
| Fingerprint | a SHA-256 code computed from a file; change one byte and the code changes |

## Before the first session (only you can do these)

1. **Open the Azure account** at azure.microsoft.com/free. It asks for your card and your phone,
   which is why nobody else can do it. The credit (\$200 at the time of writing) lasts 30 days from
   sign-up, so sign up when the scripts are ready, not before.
2. **Install the Azure command-line tool** (`az`, Microsoft's program for driving Azure from a
   terminal) and sign in with `az login`, which opens a browser.
3. **Make the testbed key**, a key pair used for these machines and nothing else:
   `ssh-keygen -t ed25519 -f ~/.ssh/azure_sbl -N ""`
4. **Push the repository.** The machines download the code from GitHub, so what is not pushed
   does not run.
5. **Find your public address** (the address the internet sees your computer at), for example with
   `curl -s https://checkip.amazonaws.com`. Only that address will be allowed to reach the
   machines.

## The order of work

On your computer, from the repository folder:

```bash
python scripts/azure_testbed.py plan --profile matched --ssh-source YOUR.ADDRESS/32
python scripts/azure_testbed.py preflight --profile matched
python scripts/azure_testbed.py up --profile matched --ssh-source YOUR.ADDRESS/32 --yes
python scripts/azure_testbed.py hosts --profile matched --write cloud/hosts.env
bash cloud/azure/session.sh
```

- `plan` prints every command and runs none (a dry run).
- `preflight` reads the account's real CPU limits and says whether the profile fits. It changes
  nothing.
- `up` creates the machines. Without `--yes` it only shows what it would do.
- `hosts` writes the machines' addresses into `cloud/hosts.env` (not committed; it is ours only).
- `session.sh` starts a session (a working period on the machines): it waits for the setup,
  switches automatic package upgrades off (one restarted the network in the middle of a pilot),
  starts the brokers, builds the receiver's namespace and records the scheduler settings.

Then, on the driver (`ssh -i ~/.ssh/azure_sbl ubuntu@<DRIVER_PUBLIC>`, then `cd sbl`):

```bash
nohup bash cloud/azure/pilot.sh > pilot.log 2>&1 &
nohup bash cloud/azure/replicate_oracle.sh > replicate.log 2>&1 &
```

Run the second only after the pilot's `verdicts.csv` has no `no` in it. Results stay on the
driver under `runs/azure/`; copy them back before the machines are deleted.

While anything runs, watch it from your computer. The watch only reads, unless you ask it to stop
idle machines. Every 5 minutes it flags machines that are idle but still billing, a stuck
campaign, failed trials, impossible numbers (a message that arrived before it was sent), load that
is lower than set, full disks, low memory, CPU taken by other tenants (steal), clock drift, and
brokers that are down. It also reads each finished run's verdict, and says when a campaign stopped
itself or finished:

```bash
python scripts/testbed_watch.py
```

Between sessions, and at the very end:

```bash
python scripts/azure_testbed.py stop --profile matched --yes
python scripts/azure_testbed.py start --profile matched --yes
bash cloud/azure/session.sh
python scripts/azure_testbed.py down --confirm sbl-az
```

`stop` deallocates, so the CPUs stop billing; a start after it is a reboot, which is why
`session.sh` runs again. `down` deletes everything and asks for the group's name typed back.

## The law campaign

It runs on the driver after a passing pilot, one queue at a time, and each step uses what the
step before it measured (a queue is the shuffled list of runs, with what happened to each):

1. **Read the machine**: its tick, and the slice constant its kernel really uses. The first
   Azure driver ran a 6.8 kernel whose default slice was 2.8 ms, where its version predicts 3.
2. **Baseline trips (block B0)**: no added delay, each backend at 50, 75 and 88% load, 3 rounds.
3. **Delay calibration (block C0), at the start of every session**: added delays of 0 (twice),
   1, 2, 4 and 8 ms, longer with `--up-to-ms`, 2 rounds. `delay_calibration.py fit` measures
   how far the trip moves per millisecond of delay, at the delay the broker's capture says it
   held, and checks the gate: the slope clearly above
   one half, and the calibration known to within 0.3 ms at every step (its 95% interval). When
   only that precision fails, 2 more rounds run and both are fitted together. The first pilot
   found 2.03 ms moving Kafka's trip by 1.80 ms and Redis's by 2.51 ms, but it replayed the match
   in bursts; on the campaign's steady 50 messages a second both clients track the delay within
   2%, and the calibration is the session's check that they still do.
4. **Spread pilot (P0)**: 16 setups over 5 rounds, placed from the calibration.
5. **Repeats**: `rounds` reports the pilot's run-to-run spread, and `rounds_rule.py` turns it
   into runs per setup by simulating the campaign's own prediction and decision rule a thousand
   times under the law and a thousand times where it is false (at least 4, at most 40).
6. **Main blocks**: A1 (slice doses), A3 (load) and A7 (go-first) on this machine; A5 (core
   count) in its own queue, because it switches CPUs off; A4 on the arm profile. A2 (the tick)
   needs three kernels built with 1, 4 and 10 ms ticks, which are not built yet. A block is not
   one sitting: A1 runs as six campaigns, three per backend, each including the 3 ms slice as the
   anchor they are compared through, and each runs with `cloud/azure/stage1.sh`:

```bash
STAGE0=runs/azure/stage0/matched_20260917T231015Z \
bash cloud/azure/stage1.sh A1 --slices 3,0.75,1.5 --backend kafka --anchor-slice 3 \
  --rounds 4 --rounds-note "P1: 4 rounds, from 1000 simulations at spread 0.18; seed 20260918"
```

For each block: read the machine, make the design, make the queue, run it. B0 is shown. C0
needs nothing more; the later blocks add `--calibration` (or `--baseline`, which assumes the
delay adds one-for-one), and the main blocks also `--rounds`:

```bash
sudo python3 scripts/sched_settings.py read > runs/azure/settings.json
python3 scripts/law_design.py design --block B0 --settings runs/azure/settings.json --seed 20260915 --out runs/azure/queues/b0.json
python3 scripts/run_queue.py make --design runs/azure/queues/b0.json --out runs/azure/queues/b0.csv
nohup bash cloud/azure/campaign.sh runs/azure/queues/b0.csv > campaign_b0.log 2>&1 &
```

After B0, after C0 and after P0:

```bash
python3 scripts/law_design.py baseline --queue runs/azure/queues/b0.csv --out runs/azure/baseline.json
python3 scripts/delay_calibration.py fit --queue runs/azure/queues/c0.csv --out runs/azure/calibration.json
python3 scripts/law_design.py rounds --queue runs/azure/queues/p0.csv --block A1
```

That prints the run-to-run spread the pilot measured, and the command that turns it into a number
of rounds: the campaign is simulated a thousand times under the law and a thousand times in the
world its falsifier names, and the rounds are the smallest number, at least four, that confirms
the prediction in at least 80% of the first and at most 5% of the second (the plan's D4-2).

```bash
python3 scripts/rounds_rule.py for --prediction P1 --slices 1.5,3,4.5,6,7.5,9 --spread 0.18
python3 scripts/rounds_rule.py fixed --campaign B0
```

Every campaign after the session's C0 runs with that calibration, so each run's "got it" delay
can be held against it:

```bash
CALIBRATION=runs/azure/calibration.json nohup bash cloud/azure/campaign.sh runs/azure/queues/a1.csv > campaign_a1.log 2>&1 &
```

`touch runs/azure/STOP` ends a campaign after the run in progress. Starting it again carries on
from the queue, and a run left half-done is recorded as failed and queued again. Each run uses
a constant-rate plan, 50 messages a second for 130 s, which keeps 5,000 messages after the 30 s
warm-up (a warm-up is the stretch thrown away while things settle). The effect is strongest at
sparse rates, so the spread pilot is where to check that the plateau is still measurable at this
rate.

**How each run is judged.** The moment a run ends, `scripts/run_integrity.py` checks it on the
driver and writes every check, with the value found and the limit it was held to, into the run's
`integrity.json`. There are three verdicts:

- **It counts** when every check passes.
- **It is repeated** when a condition it was meant to have did not take: fewer than 99% of the
  planned messages sent after the warm-up, or fewer than 99% of those arrived; the send rate more
  than 2% off; the measured load more than 3 points off, or fewer than 10 load samples; the slice
  or the tick changed during the run; the added delay more than 0.25 ms plus 5% away from the one
  set, measured by ping beyond the same ping taken with no delay just before the run (the two ping
  paths of the second x86 pair differ by 0.4 ms with no delay at all); the clock's offset not
  logged before and after. The run keeps its files, and the
  queue runs a copy later, three attempts at most. What a run measured never makes it a repeat.
- **It stops the campaign** when the instrument is in doubt: a message arrived before it was sent,
  or the "got it" median moved from the session's zero-delay median by more than a quarter of the
  added delay (this needs `CALIBRATION`).

Before each run the machine itself is checked: the receiver's address only in its namespace,
the broker reachable, and no package manager running. A run that fails this is repeated like any
other, so a machine that changed under a campaign soon stops it.

A campaign also stops itself when attempts keep failing: the last three all failed, or more than
a fifth of the last twenty did, once ten have finished. A stopped campaign writes a `STOP_RULE:`
line in its log and waits for a person. Find the cause before starting it again.

## Several pairs at once

Some campaigns can run at the same time, but only on separate machine pairs, never two on one
pair. Each pair is a *lane* (a driver and its broker, with its own hosts file, queues and logs).
Runs on two lanes share no CPU, broker, network link or disk, so neither can disturb the other.
The rules, from the experiment plan in `freezes/`:

1. **One campaign, one pair.** A campaign runs on one lane from its first run to its last, and
   every prediction is tested on runs from one pair. Nothing pools runs across pairs.
2. **A new pair proves itself first.** It passes the pilot's instrument checks, then runs its own
   B0 and P0, and every session its own C0.
3. **The same code everywhere.** Every lane runs the same commit (the saved version of the code);
   the watch warns when they differ. Each run's `lane.json` records its pair, driver and commit.
4. **One queue, one driver.** The watch raises an alert if two lanes run the same queue.
5. **Copy before the next.** A finished campaign's runs are copied home before the next campaign
   starts on that pair.

There are three pairs, all in Sweden Central since that region's CPU limit was raised on
16 September 2026, each in its own resource group and network so that each is created and
deleted on its own: *matched* (group `sbl-az`), *matched-b* (`sbl-azb`) and *arm* (`sbl-azarm`).
Every `azure_testbed.py` command takes `--profile`, and acts on *matched* without it. Each pair
has its own hosts file: `cloud/hosts.env`, `cloud/hosts_b.env` and `cloud/hosts_arm.env`.

```bash
python scripts/azure_testbed.py up --profile matched-b --ssh-source YOUR.ADDRESS/32 --yes
python scripts/azure_testbed.py hosts --profile matched-b --write cloud/hosts_b.env
HOSTS_ENV=cloud/hosts_b.env bash cloud/azure/session.sh
```

The Arm pair is the same with `--profile arm` and `cloud/hosts_arm.env`. `session.sh` copies the
hosts file to that driver as its own `cloud/hosts.env`, so nothing on a driver needs to know which
pair it is. A pair is deleted alone, with its group's name typed back, for example
`python scripts/azure_testbed.py down --profile matched-b --confirm sbl-azb`.

**Stage 0, unattended.** `cloud/azure/stage0.sh` runs the plan's first stage on one pair from
start to end: the pair's shakedown, which must pass `pilot_checks.py shakedown`; the session's
delay calibration (C0), with 2 more rounds when its fit finds it too loosely known and nothing
else wrong; the baseline trips (B0); and the spread pilot (P0), placed from the calibration and
only if its gate passed. A failed gate ends the session, and the pair starts a new one. On the
first pair C0 is the staircase S0-1, up to 16 ms over 4 rounds. It takes about 6 to 10 hours,
depending on how many P0 points the machine can reach. On each driver, after `session.sh`:

```bash
nohup bash cloud/azure/stage0.sh first > stage0.log 2>&1 &
```

with `new` in place of `first` on the second x86 pair and on the Arm pair. Its last line is
`CAMPAIGN_COMPLETE`, or `STOP_RULE:` with the reason. A pair that has already passed its
shakedown skips the long parts of the pilot when the stage-0 folder holding that shakedown is
added: `bash cloud/azure/stage0.sh new runs/azure/stage0/<profile>_<start>`. The network part
(`PARTS=network`) runs in every session all the same: a start after a stop can put a machine on
another physical host, and on 16 and 17 September the gap between the two x86 drivers' paths
moved between +0.06 and -0.44 ms from one start to the next.

**Start one pair first.** After a change to the code, start the first x86 pair alone, and start
the others once its shakedown and its first calibration have passed: on 16 September every
fault reached all three pairs at once.

**Watching every lane.** One watch reads them all: give each lane a name and its hosts file. With
`--stop-idle-min 20` it also deallocates a pair whose machines have been idle for 20 minutes, so a
pair that finished at night does not bill until morning:

```bash
python scripts/testbed_watch.py --lane a=cloud/hosts.env --lane b=cloud/hosts_b.env --lane arm=cloud/hosts_arm.env --stop-idle-min 20
```

Each look is appended to a dated log under `runs/azure_watch/`, and the latest is also in
`runs/azure_watch/status.json`. **ALERT** needs a person now: a campaign that stopped itself, an
impossible number, a machine that does not answer, one queue on two pairs. **WARN** is worth a
look: a repeated run, steal, clock drift, pairs on different commits. **INFO** says what comes
next, such as a finished campaign to copy. **IDLE** means billing for nothing.

**Copying the runs home.** A campaign's runs exist only on its driver until they are copied.
`scripts/collect_runs.py` copies one finished campaign: it fingerprints every file of every
attempt on the driver, packs them, checks the package's fingerprint after the copy, unpacks it
while refusing anything that would land outside the destination, and checks every file again. It
writes `SHA256SUMS` and `COLLECTED.json` (which machine, which commit, when) next to the runs,
under `runs/azure/collected/`, refuses to collect the same campaign twice, and deletes nothing on
the driver except its own temporary folder:

```bash
python scripts/collect_runs.py --hosts cloud/hosts.env --queue runs/azure/queues/a1.csv
python scripts/collect_runs.py --hosts cloud/hosts_b.env --queue runs/azure/queues/a5.csv
```

Some measurements belong to no queue: a pilot's runs, a void session, a probe of the instrument,
a chain's log. `--path` copies folders and files the same way, into a new
`collected/<profile>/snapshot_<UTC time>/` each time, so a later copy of the same folders sits
beside the earlier one. Before a pair is deleted, and whenever a session ends early, its whole
`runs` folder and its logs are copied:

```bash
python scripts/collect_runs.py --hosts cloud/hosts_arm.env --path runs --path stage0.log
```

**Reading the copy while the machines carry on.** `scripts/quality_report.py` says what a
campaign's runs tell us about the instrument: the verdicts and the reasons behind every repeat,
the messages kept, the send rate, the load, the delay the broker held, the clock offset, the CPU
other tenants took, the TCP segments each side sent again, and pauses over 150 ms after the
warm-up. It also makes the *waypoint check*: a setup's repeats run at different times, in a
shuffled order, so one repeat far from its fellows says the machine was in a different state
then. Such a repeat is registered with its numbers and kept, never removed, and nothing here
decides anything. It reads the instrument, not whether a prediction came true:

```bash
python scripts/quality_report.py --runs runs/azure/collected/matched/c0_20260917T231015Z/runs
```

Each look of the watch also says where the queue has got to and when it is due, and raises an
alert when the run in progress passes the time this campaign's runs take. Runs are unusually
even: 197 of them took 160 seconds each, so a late run is not slow, it is wrong.

## Money and limits

- All three pairs live in Sweden Central. On the free-trial subscription, North Europe refused
  these sizes, and Sweden Central was the cheapest region that allows both profiles. Italy North
  and Poland Central also offer the x86 sizes; only Sweden Central offers the Arm ones.
- Each x86 pair is 10 CPUs, about \$0.49 an hour while running, and the Arm pair about \$0.37
  (Sweden Central list prices, dated in `cloud/azure/testbed.json`). `plan` prints the sum.
- A region allows a set number of CPUs, and deallocated machines still count. Sweden Central held
  one pair until 16 September 2026, when the limit was raised on request to 40 CPUs in total, 20
  in the Dav6 family and 10 in the Dpsv6 family, which is room for all three pairs. `preflight`
  reads the real limit.
- Deallocated machines cost only their disks and fixed addresses. Delete the group when the work
  is done.
- Azure's own bill arrives a day or two late, so it cannot say what a run cost while it is
  running. `scripts/spend.py` keeps a second figure that can: every look of the watch adds the
  machine time since the last look, at each pair's list price, to `runs/azure_watch/spend.json`.
  A gap nobody watched is counted at fifteen minutes rather than its whole length, so the
  estimate stays low on purpose and the bill remains the truth it is checked against. Seed it
  once with what has already been billed, and read either figure at any time:

```bash
python scripts/spend.py seed --from-bill --since 2026-09-01
python scripts/spend.py show
python scripts/spend.py billed --since 2026-09-01
```

  Every run's start is a point on that ledger, so each run can be told what had been spent by the
  time it began: the watch says so as a run starts, and `quality_report.py --ledger` writes it
  beside every run of a campaign it reads.

## What each file does

| File | What it does |
|---|---|
| `cloud/azure/testbed.json` | the machines: sizes, fixed private addresses, profiles (each with its own region where it names one), planning prices |
| `cloud/azure/cloud-init.yaml` | the setup every machine runs on first boot (packages, Python libraries, the checkout) |
| `scripts/azure_testbed.py` | plans, checks, creates, stops, starts and deletes the machines, one profile at a time; nothing costly without `--yes` |
| `cloud/azure/session.sh` | starts a working session from your computer |
| `scripts/sched_settings.py` | reads, sets and checks the base slice and the tick on a machine |
| `scripts/receiver_delay.py` | builds the receiver's namespace, delays traffic to it alone, and checks that with ping |
| `cloud/azure/pilot.sh` | the pilot checks, with a verdict for each: settings, the delay the broker holds (its own capture, which decides), the two paths by ping, TCP and UDP (recorded), the harness, go-first; `PARTS=network` for a later session |
| `scripts/pilot_checks.py` | reads run files: never-negative trips, the receiver-only check, the go-first cut, and whether a pilot passed a new pair's shakedown |
| `cloud/azure/replicate_oracle.sh` | runs the Oracle mechanism campaigns unchanged, in shuffled order |
| `scripts/run_queue.py` | the randomised run queue and its ledger (every run recorded, failures included) |
| `scripts/testbed_watch.py` | watches every machine pair from your computer and flags idle, stuck, failed or impossible runs, repeated and stopping verdicts, low load, full disks and clock drift; can deallocate idle pairs |
| `scripts/law_design.py` | builds each law block's run list from the machine's tick and slice constant, the session's delay calibration (or the baseline trips) and the number of rounds it is given |
| `scripts/law_curve.py` | measures one cliff both ways the plan fixes: the fitted plateau, fall and floor, and the curve only required never to rise |
| `scripts/law_predictions.py` | whether a prediction came true, by the sentence the plan wrote beside it; nothing pooled across pairs or backends |
| `scripts/law_world.py` | made-up campaigns, under the law and in the world each falsifier names, for the tests and the rounds rule |
| `scripts/rounds_rule.py` | how many rounds a campaign runs, by simulating its own prediction and decision rule (the plan's D4-2) |
| `scripts/delay_calibration.py` | measures, from a calibration queue, how far the trip moves per millisecond of receiver-only delay, checks the gate, and gives the delay each planned trip needs |
| `cloud/azure/chain.sh` | waits on the driver for this session's calibration to pass and then starts a campaign from it, so a pair does not sit billing between the two; it can simulate the rounds from the pair's own spread pilot first, and starts nothing if the calibration failed its gate. Runs on the driver under `nohup`, so it survives whatever started it |
| `cloud/azure/campaign.sh` | the law campaign's runner: sets each run's CPUs, slice, delay and load, runs one trial, checks it, records it, and stops itself on a stop rule |
| `cloud/azure/machine_facts.sh` | what a machine is, as far as its network and timing go; the pilot keeps it for both machines |
| `cloud/azure/stage0.sh` | the plan's first stage on one pair, unattended: the pilot and its shakedown, the calibration in one or two stages and its fit, the baseline trips, the spread pilot |
| `cloud/azure/tools.sh` | the tools block: puts up the servers the ten tools speak to (`brokers`), installs the tools at the versions the audit read and fingerprints what actually landed, then runs T1 (the delay staircase, in random order), T2 (forced negatives, by moving the clock the tool reads), T3 (idle against 88% load, with and without go-first) and T4 (what each tool can report at all) |
| `cloud/azure/deallocator_role.json` | the custom Azure role each driver's identity holds, *SBL Pair Deallocator*: read a virtual machine, read its instance view, deallocate it. No create, no delete, no start, no restart. Assignable only at the three pairs' resource groups, and assigned to each driver scoped to its own, so a driver can reach its broker and itself and no other machine |
| `cloud/azure/stop_self.sh` | deallocates this pair from the pair itself, once its list of work is finished: every machine in its own resource group, the broker first and this one last. It holds one custom role, *SBL Pair Deallocator*, scoped to that group -- read a machine and deallocate it, nothing else -- so asked to restart itself it is refused, and asked to read another pair's driver it is refused. Deallocated, not shut down: a machine stopped from inside is still allocated and still billed, and deallocation keeps the disks, so every run comes back with the machine. Armed per pair with `queue.sh arm-stop` |
| `cloud/azure/tools_run.sh` | runs one tool once, so T1 to T4 differ in the conditions they set and in nothing else; `SBL_TOOL_WRAP` prefixes the tool's own process, which is how T3 gives it go-first priority and how T2 gives it a moved clock |
| `cloud/azure/kernels.sh` | A2's build campaign: three kernels from the driver's own source and configuration differing in nothing but the tick (HZ=1000, 250 and 100), each booted once while the stock kernel stays the default, and each held to the checks `scripts/kernel_checks.py` makes before any run |
| `cloud/azure/cpus.sh` | A5's core counts, asked for at boot with `nr_cpus=N` because the hypervisor will not let a CPU be switched off on a running machine; one entry built from the running boot's own command line, booted once, and checked before any run |
| `cloud/azure/a2_session.sh` | one of A2's tick sessions end to end, from a deallocated pair to a chained campaign: start the pair, boot and check the kernel, rebuild the session the reboot took with it, measure the calibration on that boot and chain A2 behind its gate. The reboot is why this runs from the machine holding the hosts file rather than on the driver |
| `cloud/azure/queue.sh` | a pair's own list of work, which it keeps going through across its own reboots: the job list, the phase it is in and an `@reboot` line live on the driver, so nothing outside the pair has to stay awake. `a2_session.sh` does one session from outside; this does a list of them from inside, which is what a session driven from a laptop could never do |
| `cloud/azure/stage1.sh` | one campaign of a main block, in a sitting of its own, placed from a stage 0 that passed, with the rounds it is given written into its log before it runs |
| `scripts/run_integrity.py` | judges each run as it ends (it counts, is repeated, or stops its campaign), and stops a campaign whose attempts keep failing |
| `scripts/quality_report.py` | what a campaign's runs say about the instrument, once copied: verdicts, conditions, pauses, and repeats that sit far from their fellows |
| `scripts/collect_runs.py` | copies a finished campaign, or whole folders, home and checks a fingerprint for every file |
| `scripts/spend.py` | what the machines have cost so far, counted look by look, and what Azure has actually billed |

The two trial runners, `scripts/run_kafka_trial.sh` and `scripts/run_redis_trial.sh`, gained one
hook, `SBL_CONSUMER_WRAP`. It is empty unless a campaign sets it, and each run's `meta.json` now
records it.

## How the receiver-only delay works

The sender and the receiver run on the driver, and the broker answers both over the same link.
A delay on that whole link slows the "got it" reply exactly as much as the message, so the two
timestamps move together and nothing changes. That is why the old delay experiment saw nothing.

So the receiver gets its own address. Azure gives the driver's network card a second address, and
the receiver runs inside a namespace that owns it. Azure's first boot also puts that address on
the driver itself, so the setup takes it off the driver first. Left there, the broker's replies to
the driver would go into the namespace, and the driver would lose the broker. On the broker, a
queue with four lanes sends ordinary traffic down the first three. The fourth lane has the delay, and only packets addressed
to the receiver go there. What proves it is the broker's own capture of the pings: it shows the
broker held the receiver's replies for the set delay and the driver's not at all, to a few
microseconds, which is the treatment measured where it is applied. Every run is checked that way
too, and the calibration is fitted at the delay the broker held.

Ping is recorded and judges nothing. On 17 September, measured side by side over nine minutes,
ping read 0.86 and 1.13 ms on the two paths where TCP read 0.45 and 0.61 and UDP 0.44 and 0.70;
ping's 90th percentile was 3.2 to 3.7 ms against TCP's 0.5, with single readings of 9 and 11 ms.
Worse for our purposes, ping put the two paths 0.28 ms apart, steadily, where TCP put them
0.009 ms apart. Microsoft's own guidance says as much: ICMP is treated differently from
application traffic, and it names sockperf instead. So the pilot records both paths by ping, TCP
and UDP, and lets none of them decide; what a pair's runs actually vary by is measured by B0 and
sets how many rounds it needs.

## Safety

- SSH is open to one address only, and it only accepts the testbed key. No broker port is
  reachable from the internet: an unprotected Redis on a public address is taken over within
  minutes.
- Every machine has a public address, but only so that it can reach out, to download packages
  and the code. On this Azure network a machine without one had no way out at all, and Oracle's
  machines all had one too. What comes in is the firewall's decision, and it admits nothing but
  that one SSH rule.
- The programs never handle passwords or cards. `az login` is done by you, in a browser.
- Nothing is created, stopped or deleted without `--yes`, and deleting also needs the group's name.
- The watch deallocates idle machines only when given `--stop-idle-min`, and it never starts,
  creates or deletes anything.

## Not here yet

- **The tool checks:** a millisecond tool and a nanosecond tool measuring a known delay. Each
  tool has to be installed and its output read.
- **The three tick kernels:** the same kernel built at HZ=1000, 250 and 100, with a check at
  every boot that the tick really changed, for the tick experiment.
- **The analysis code** for the frozen predictions, tested on made-up data before any real run.
