# Azure testbed

This folder, together with four programs in `scripts/`, runs the experiments on Azure. It creates
the machines, sets them up, checks them, and removes them at the end.

**In one paragraph.** Every earlier cloud result came from one Oracle machine type with one
kernel. These files rebuild that layout on Azure with the same AMD chip generation (profile
*matched*), and the same layout on Azure's Arm chip (profile *arm*, the "materially different
machine"). Before any result counts, a *pilot* checks the machine. The scheduler settings must
read back. A delay added on the receiver's path must reach the receiver and nothing else. And the
old go-first test must still work. Then the old Oracle campaigns run unchanged (the
*replication*), and the new campaign runs from a randomised queue.

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
| Queue | the shuffled list of runs, which also records what happened to each |

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

Between sessions, and at the very end:

```bash
python scripts/azure_testbed.py stop --profile matched --yes
python scripts/azure_testbed.py start --profile matched --yes
bash cloud/azure/session.sh
python scripts/azure_testbed.py down --confirm sbl-az
```

`stop` deallocates, so the CPUs stop billing; a start after it is a reboot, which is why
`session.sh` runs again. `down` deletes everything and asks for the group's name typed back.

## Money and limits

- The machines live in Sweden Central. On the free-trial subscription, North Europe refuses these
  sizes, and Sweden Central was the cheapest region that allows both profiles.
- The *matched* profile is 10 CPUs, about \$0.49 an hour while running (Sweden Central list prices,
  dated in `cloud/azure/testbed.json`). `plan` prints the sum.
- The free trial allows 4 CPUs per region, in every region, and a trial cannot raise that.
  `preflight` reads the real limit. Moving the subscription to pay-as-you-go keeps the remaining
  credit and allows a limit request.
- Deallocated machines cost only their disks. Delete the group when the work is done.

## What each file does

| File | What it does |
|---|---|
| `cloud/azure/testbed.json` | the machines: sizes, fixed private addresses, profiles, planning prices |
| `cloud/azure/cloud-init.yaml` | the setup every machine runs on first boot (packages, Python libraries, the checkout) |
| `scripts/azure_testbed.py` | plans, checks, creates, stops, starts and deletes the machines; nothing costly without `--yes` |
| `cloud/azure/session.sh` | starts a working session from your computer |
| `scripts/sched_settings.py` | reads, sets and checks the base slice and the tick on a machine |
| `scripts/receiver_delay.py` | builds the receiver's namespace, delays traffic to it alone, and checks that with ping |
| `cloud/azure/pilot.sh` | the five pilot checks, with a verdict for each |
| `scripts/pilot_checks.py` | reads run files: never-negative trips, the receiver-only check, the go-first cut |
| `cloud/azure/replicate_oracle.sh` | runs the Oracle mechanism campaigns unchanged, in shuffled order |
| `scripts/run_queue.py` | the randomised run queue and its ledger (every run recorded, failures included) |

The two trial runners, `scripts/run_kafka_trial.sh` and `scripts/run_redis_trial.sh`, gained one
hook, `SBL_CONSUMER_WRAP`. It is empty unless a campaign sets it, and each run's `meta.json` now
records it.

## How the receiver-only delay works

The sender and the receiver run on the driver, and the broker answers both over the same link.
A delay on that whole link slows the "got it" reply exactly as much as the message, so the two
timestamps move together and nothing changes. That is why the old delay experiment saw nothing.

So the receiver gets its own address. Azure gives the driver's network card a second address, and
the receiver runs inside a namespace that owns it. On the broker, a queue with four lanes sends
ordinary traffic down the first three. The fourth lane has the delay, and only packets addressed
to the receiver go there. The pilot proves it twice: with ping from both sides at every delay
step, and again from the run files, where the "got it" delay must stay put while arrival minus
sending grows by the delay.

## Safety

- SSH is open to one address only, and it only accepts the testbed key. No broker port is
  reachable from the internet: an unprotected Redis on a public address is taken over within
  minutes.
- The programs never handle passwords or cards. `az login` is done by you, in a browser.
- Nothing is created, stopped or deleted without `--yes`, and deleting also needs the group's name.

## Not here yet

- **The tool checks:** a millisecond tool and a nanosecond tool measuring a known delay. Each
  tool has to be installed and its output read.
- **The two tick kernels:** the same kernel built at HZ=1000 and at HZ=250, for the tick
  experiment.
- **The analysis code** for the frozen predictions, tested on made-up data before any real run.
- **The campaign runner** that takes runs from the queue, sets each run's slice and delay, and
  records the outcome. The queue and its rules are here. The runner comes after the pilot, because
  the delays it applies depend on the baseline trip the pilot measures.
