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
   how far the trip moves per millisecond of delay and checks the gate. It has to be measured:
   on the first pilot, 2.03 ms added moved Kafka's trip by 1.80 ms and Redis's by 2.51 ms.
4. **Spread pilot (P0)**: 16 setups over 5 rounds, placed from the calibration.
5. **Repeats**: `rounds` turns the pilot's run-to-run spread into runs per setup (15 to 40).
6. **Main blocks**: A1 (slice doses), A3 (load) and A7 (go-first) on this machine; A5 (core
   count) in its own queue, because it switches CPUs off; A4 on the arm profile. A2 (the tick)
   needs three kernels built with 1, 4 and 10 ms ticks, which are not built yet.

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
  or the tick changed during the run; the delay ping measured more than 0.25 ms plus 5% away from
  the one set; the clock's offset not logged before and after. The run keeps its files, and the
  queue runs a copy later, three attempts at most. What a run measured never makes it a repeat.
- **It stops the campaign** when the instrument is in doubt: a message arrived before it was sent,
  or the "got it" median moved from the session's zero-delay median by more than a quarter of the
  added delay (this needs `CALIBRATION`).

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
start to end: the pilot (a new pair's shakedown, or the first pair's retest), which must pass
`pilot_checks.py shakedown`; the session's delay calibration (C0) and its fit; the baseline trips
(B0); and the spread pilot (P0), placed from the calibration and only if its gate passed. On the
first pair C0 is the staircase S0-1, up to 16 ms over 4 rounds. It takes about 6 to 10 hours,
depending on how many P0 points the machine can reach. On each driver, after `session.sh`:

```bash
nohup bash cloud/azure/stage0.sh first > stage0.log 2>&1 &
```

with `new` in place of `first` on the second x86 pair and on the Arm pair. Its last line is
`CAMPAIGN_COMPLETE`, or `STOP_RULE:` with the reason.

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

## What each file does

| File | What it does |
|---|---|
| `cloud/azure/testbed.json` | the machines: sizes, fixed private addresses, profiles (each with its own region where it names one), planning prices |
| `cloud/azure/cloud-init.yaml` | the setup every machine runs on first boot (packages, Python libraries, the checkout) |
| `scripts/azure_testbed.py` | plans, checks, creates, stops, starts and deletes the machines, one profile at a time; nothing costly without `--yes` |
| `cloud/azure/session.sh` | starts a working session from your computer |
| `scripts/sched_settings.py` | reads, sets and checks the base slice and the tick on a machine |
| `scripts/receiver_delay.py` | builds the receiver's namespace, delays traffic to it alone, and checks that with ping |
| `cloud/azure/pilot.sh` | the five pilot checks, with a verdict for each |
| `scripts/pilot_checks.py` | reads run files: never-negative trips, the receiver-only check, the go-first cut, and whether a pilot passed a new pair's shakedown |
| `cloud/azure/replicate_oracle.sh` | runs the Oracle mechanism campaigns unchanged, in shuffled order |
| `scripts/run_queue.py` | the randomised run queue and its ledger (every run recorded, failures included) |
| `scripts/testbed_watch.py` | watches every machine pair from your computer and flags idle, stuck, failed or impossible runs, repeated and stopping verdicts, low load, full disks and clock drift; can deallocate idle pairs |
| `scripts/law_design.py` | builds each law block's run list from the machine's tick and slice constant, the session's delay calibration (or the baseline trips) and the repeat rule |
| `scripts/delay_calibration.py` | measures, from a calibration queue, how far the trip moves per millisecond of receiver-only delay, checks the gate, and gives the delay each planned trip needs |
| `cloud/azure/campaign.sh` | the law campaign's runner: sets each run's CPUs, slice, delay and load, runs one trial, checks it, records it, and stops itself on a stop rule |
| `cloud/azure/stage0.sh` | the plan's first stage on one pair, unattended: the pilot and its shakedown, the calibration and its fit, the baseline trips, the spread pilot |
| `scripts/run_integrity.py` | judges each run as it ends (it counts, is repeated, or stops its campaign), and stops a campaign whose attempts keep failing |
| `scripts/collect_runs.py` | copies a finished campaign home and checks a fingerprint for every file |

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
to the receiver go there. The pilot proves it twice: with ping from both sides at every delay
step, and again from the run files, where the "got it" delay must stay put while arrival minus
sending grows by the delay.

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
