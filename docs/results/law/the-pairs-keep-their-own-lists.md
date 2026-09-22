# The pairs keep their own lists now, and one of A4's campaigns was missing

**22 September 2026.** Not a test of any prediction. Two things: how the remaining work was put
on the machines so that nothing outside them has to stay awake, and what looking at the machines
to do it turned up.

**Words used here.** *Driver* — the machine that runs the client and the campaign scripts.
*Broker* — the other machine of a pair, which runs Kafka and Redis. *Session* — one sitting: a
boot, a calibration measured on that boot, and a campaign placed from it. *Deallocate* — give an
Azure machine back so it stops billing; its disk stays.

## The fault that kept costing nights

A campaign survives anything that happens to whoever started it: `chain.sh` runs on the driver
under `nohup` and keeps going. A *session* does not, and cannot, because a session begins by
booting a different kernel or a different core count and a machine cannot ssh into itself to
reboot itself and carry on. So A2's twelve sessions and A5's two were driven from outside, by a
loop on a laptop.

On 21 September that loop died twice — once when the process that held it exited, once when the
session it lived in ended. Each time the pair finished what it was doing and went quiet, and the
quiet lasted until somebody noticed. The two worst faults of that day have the same shape: a
waiter that read a completion line another campaign had left hours earlier, and started a
calibration on a busy pair the first time and rebooted under a running one the second.

The answer is not a better loop somewhere else. It is for the machine to leave itself a note
before it goes down and read it when it comes back.

## What is on each machine

`cloud/azure/queue.sh` keeps a job list, the phase the current job is in, and an `@reboot` line
in the driver's own crontab. The driver already has what it needs to do this: `session.sh` left
it the testbed key and its own `hosts.env`, so it can reach its broker and rebuild the receiver's
namespace that a reboot takes with it.

| | what it is working through | about |
|---|---|---|
| **arm** | the A4 Kafka campaign that was missing, behind a fresh calibration | 5 hours, then nothing |
| **matched** | A8's x86 campaign, then the whole tools block, T1 to T4 | 8 + 38 hours |
| **matched-b** | the A2 session running now, then A5 at 2 and 4 CPUs, then A2's twelve | 46 hours |

Three rules it follows, each of them something that went wrong first:

- **It waits for a campaign folder that did not exist when the job started**, never the last line
  of a log another campaign wrote. That is the 21 September fault, and the only reliable way to
  tell this campaign's ending from the previous one's.
- **It does not halt the list when one job stops itself.** That was the rule when the loop ran
  from outside, and it is the wrong one here: the next job is a different kernel asking a
  different question, and a campaign that tripped a brake has still measured everything up to
  the trip. The job is recorded, put back on the end **once**, and the queue goes on. It never
  retries in place, which is how one bad session becomes a hundred.
- **It gives up on a job that has rebooted twice** without the machine coming up the way it was
  asked, because a machine that will not comply reboots for ever and bills the whole time.

The watch had to be taught about it. A queue is idle by design between jobs — it has just
rebooted the machine, or it is a minute from looking again — and both look exactly like a pair
with nothing to do, which the watch deallocates after half an hour. It is now counted with the
chain and the rounds rule as work in hand.

## A4 was a campaign short, and had been since 18 September

A4 is four campaigns on the Arm pair: two per backend, at slices of 1.5 and 3 ms and of 3 and
4.5 ms (D4-8). Reading what the Arm driver actually holds, before giving it new work:

| campaign | backend | slices | ended |
|---|---|---|---|
| `arm_20260918T211544Z` | kafka | 3, 4.5 | stopped itself |
| `arm_20260918T211825Z` | kafka | 1.5, 3 | **stopped itself** |
| `arm_20260918T213410Z` | kafka | 3, 4.5 | complete |
| `arm_20260919T001708Z` | redis | 1.5, 3 | complete |
| `arm_20260919T031017Z` | redis | 3, 4.5 | complete |

Three complete, not four. The Kafka campaign at 1.5 and 3 ms stopped itself on the evening of 18
September, the one beside it was started again, and this one never was. Nothing said so: the
block's line in the results has read "run, sound at 4 rounds" ever since, because the campaigns
that did finish were sound and nobody counted them against the design.

It is running now, at **4 rounds**. That is what its three siblings ran, and it is also what the
rule gives when simulated again at this pair's own corrected levels — P9 confirms in **98%** of
1000 campaigns under the law and 0% where it is false, at the Kafka spread, plateau and floor the
Arm spread pilot measured (0.2562, 0.0568 and 0.0123 at the 3 ms anchor, D14-1), at A4's own
design, seed 20260922. The three that ran were sized under the levels in force before that
correction and got the same number, so the four are comparable.

## A simulation run beside a measurement

Worth recording because it is the same fault the chain is written to avoid, committed by hand.

The rounds simulation above was started on the Arm driver at 01:39Z. The session calibration was
started on the same driver at 01:50Z, and its first run began at 01:51:53Z with the simulation
still going — it did not finish until about 01:54Z. `chain.sh` waits for the machine to be idle
before it simulates, for exactly this reason. Starting the calibration without first looking at
what was already on the machine was an operator's mistake, not the instrument's.

The run is recorded in `runs/azure/stage0/arm_20260922T015016Z/ABANDONED.txt` and no run in that
folder counts. The calibration was restarted from nothing at 01:55Z, on an idle machine, and the
simulation was re-run off the driver entirely. Cost: four minutes.

## All ten tools on one pair rather than five each

The plan's schedule gives five tool campaigns to each x86 pair (Section "Which pair runs what").
What it *requires* is narrower — that each tool runs entirely on one pair, so that nothing about
a tool's reading depends on which machine it ran on (Section "One pair per test") — and the
five-and-five split is how it balanced the load when it was written. The load is no longer that
shape. matched-b has A5 and all of A2 in front of it, about 46 hours; the tools are 47. Ten on
matched and none on matched-b has both pairs finishing within a few hours of each other, where
five and five would leave matched idle from tomorrow morning and matched-b running into Thursday.

Three tools are not queued yet. `wrk2`, `rabbitmq-perftest` and `nats-latency` are pinned
`resolve` in `tools.sh`, and the plan says the resolved commit is written into that table and
committed **before any T1 run**, because a tool's behaviour is what this block reports. `install`
records what it actually fetched; those three are queued once it has and the pins are written
down.
