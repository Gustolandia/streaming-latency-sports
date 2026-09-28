# Issues register: every fault the Azure campaigns met, what it cost, and what was done

**Kept from 26 September 2026 under plan version 32 (D32-4), reaching back to the first Azure
campaigns.** Every entry is read off the pairs' own disks: each campaign's queue says how many of
its runs were done and how many were left, and the last line of its log says how it ended. The
registry of every run, with the machine and settings it ran under, is in
[`../registry/`](../registry/).

**Words used here.** A *campaign* is the runs that answer one question in one sitting, from its
own shuffled *queue*. The *got-it brake* stops a campaign when a run's "got it" time moves further
from its setup's earlier runs than the added delay allows. A campaign is *finished* (plan version
32, D32-2) by running what is left on its own queue, under its own calibration and on the kernel
it ran on, with the brake recording rather than stopping. A *false start* is a campaign that
stopped before it measured anything worth keeping and was replaced at once.

## Campaigns the got-it brake stopped

*Plain words:* thirteen campaigns stopped part-way because a "got it" time moved more than the
brake allowed. On the x86 pairs the move was between runs of one setup, never something the added
delay did. The Arm pair's three A8 stops of 20 and 21 September came from the brake as it then
stood, which judged each run against the calibration rather than against its own setup's earlier
runs, and which versions 16 and 17 corrected.

| Date | Pair | Campaign | Block, kernel | Done of designed | The move, and what was allowed | What was done |
|---|---|---|---|---|---|---|
| 20 Sep | Arm | `arm_20260920T224009Z` | A8, 6.8.0-1064 | 15 of 144 | −0.163 ms, against 25% of 0.551 ms added and the session's own 0.145 ms | The brake was corrected (D16-1, D17-1) and A8 ran whole on 21 Sep, 144 of 144 (`arm_20260921T182140Z`); the 129 left are finished under version 32 |
| 20 Sep | first x86 | `matched_20260919T171733Z` | A3 Kafka, 6.8.0-1065 | 286 of 288 | −0.193 ms, against 25% of 0.575 ms added | Brake rebuilt in freeze 13; a second campaign ran whole on 21 Sep. The 2 left are finished under version 32 |
| 21 Sep | Arm | `arm_20260921T004923Z` | A8, 6.8.0-1064 | 2 of 144 | −0.175 ms on its first Python run, against 25% of 0.552 ms added and the session's own 0.145 ms (D16-1) | As above; the 142 left are finished under version 32 |
| 21 Sep | Arm | `arm_20260921T025629Z` | A8, 6.8.0-1064 | 28 of 144 | −0.252 ms, against 25% of 0.886 ms added and the session's own 0.199 ms (D17-1) | As above; the 116 left are finished under version 32 |
| 21 Sep | second x86 | `matched-b_20260921T141744Z` | A2 Kafka, HZ=1000 | 28 of 40 | −0.275 ms, against 0.092 ms added | A complete session followed that evening; the 12 left are finished under version 32 |
| 22 Sep | second x86 | `matched-b_20260922T190106Z` | A2 Redis, HZ=100 | 31 of 60 | 0.268 ms, against 0.588 ms added | Two complete HZ=100 days followed; the 29 left are finished under version 32 |
| 24 Sep | second x86 | `matched-b_20260924T100850Z` | A2 Redis, HZ=1000 | 32 of 60 | −0.394 ms, against 0.864 ms added | The day ran again whole on 25 Sep, 60 of 60 (D27-1); the 28 left are finished under version 32 |
| 24–25 Sep | second x86 | `matched-b_20260924T225453Z` | A5, 2 CPUs | stopped twice | 0.505 ms at 0.98 ms added, then 0.660 ms at 0.046 ms added | Its last thirteen runs ran with the brake recording (D26-1); complete |
| 26 Sep | second x86 | `matched-b_20260925T221632Z` | A2 Redis bridge, 6.8.0-1064 | 58 of 60 | 0.508 ms, against 0.522 ms added | Retried whole, and the 2 left are finished under version 32 |
| 26 Sep | first x86 | `matched_20260926T035408Z` | A1 Kafka 3 and 3.75 ms, 6.8.0-1065 | 52 of 56 | 0.380 ms, against 1.174 ms added | Retried whole, and the 4 left are finished under version 32 |
| 26 Sep | Arm | `arm_20260925T231103Z` | A9, 6.8.0-1064 | 64 of 128 | −0.309 ms, against 0.077 ms added | Retried whole; the 64 left are finished under version 32 |
| 26 Sep | first x86 | `matched_20260926T091512Z` | A9, 6.8.0-1065 | 60 of 120 | −0.299 ms, against 0.572 ms added | Retried whole, and the 60 left are finished under version 32 |
| 26 Sep | second x86 | `matched-b_20260926T142851Z` | A2 Redis bridge (its retry), 6.8.0-1064 | 38 of 60 | −0.381 ms, against 0.422 ms added | The 22 left are finished under version 32 |

From version 32 no campaign stops on the brake: what it would have said is kept beside every run,
and each prediction a recorded run bears on is judged with and without the runs it would have
stopped (D32-1).

## Faults of the kit

*Plain words:* these are failures of our own machinery, not of what was being measured. Each cost
runs or hours, and each is corrected.

| Date | Pair | What happened | What it cost | What was done |
|---|---|---|---|---|
| 16 Sep | second x86 | A run folder was named by its queue key alone, and the keys repeat from one calibration queue to the next: the calibration restarted at 15:01 UTC wrote its first run into the folder of the attempt aborted at 14:38, mixing two runs | two calibration attempts void (13:16 and 15:01 UTC); five run folders set aside in `runs/azure/quarantine/20260916_run_folder_collision` | From the next commit a run folder carries its queue's name; the five stay in the registry and belong to no campaign |
| 18 Sep | Arm | Two A4 campaigns, `arm_20260918T211544Z` and `arm_20260918T211825Z`, were started three minutes apart and ran at once: from the moment the second began, every run of both measured a load of 99.7 to 99.8% against 75%, and the second's runs found the base slice changed under them | the first campaign's one run, done before the second began, then three failed attempts each | Two false starts: A4's design ran whole from 21:34 that evening and through the night (`arm_20260918T213410Z`, `arm_20260919T001708Z`, `arm_20260919T031017Z`); not rerun (D32-2) |
| 20 Sep | Arm | A8's `arm_20260920T222915Z` was placed from a calibration with no zero-delay got-it median for Kafka at 75%, so every run failed its check | three failed attempts, no run | A false start, replaced eleven minutes later by `arm_20260920T224009Z`; not rerun (D32-2) |
| 21 Sep | Arm | A8's `arm_20260921T025558Z` was started 30 seconds before `arm_20260921T025629Z` and ran beside it for five and a half minutes: its first trial ended (exit 143) a second after the other campaign began, and every later run of both measured a load of 99.7 to 99.8% against 75% | three failed attempts, no run; the twin's two failed attempts were run again | A false start: its twin went on alone; not rerun (D32-2) |
| 21 Sep | first x86 | A3's campaign `matched_20260921T030021Z` failed its load check three times at the start: 95.7% measured against 88% | a false start, no run kept | Replaced 27 minutes later by a campaign that ran whole; not rerun (D32-2) |
| 21 Sep | second x86 | A2's HZ=1000 session `matched-b_20260921T140723Z` was stopped by hand after 2 runs | a false start | A complete session on the same kernel followed that afternoon; not rerun (D32-2) |
| 21 Sep | first x86 | At 18:57 UTC a waiter meant to start A8's x86 campaign read a CAMPAIGN_COMPLETE left in `stage1.log` hours earlier and opened a second calibration, for the Python client, on top of the one running: for about three minutes two sessions measured on one driver against one broker. At 21:51 UTC Java's client calibration stopped after three runs, unjudged, while Python's in that sitting ran whole | the duplicate's one run, void and set aside in `runs/azure/quarantine/20260921_duplicate_calibration`; two runs of the running calibration ran past their timeout and were run again; Java's three runs, none kept | Both clients were calibrated whole that night, Python at 21:51 and both at 23:23 UTC; not rerun |
| 21 Sep | second x86 | The calibration of 03:30 UTC stopped after three runs, none judged and none with a kernel reading | three runs, none kept | A calibration ran whole at 13:00 UTC; not rerun |
| 22 Sep | Arm | The calibration of 01:50 UTC stopped after two runs: one put back, one unjudged | two runs, none kept | Replaced five minutes later by a calibration that ran whole |
| 22 Sep | second x86 | One run of the calibration of 09:42 UTC (Redis, no delay, its second round) ended unjudged and was not put back | one run of 23 | The calibration's other 22 runs were judged and counted |
| 23 Sep | first x86 | `matched_20260923T093827Z`, A2 on HZ=1000: the receiver's network namespace lost its address, and three attempts failed | 25 of 44 runs | The day ran again whole that night; the 19 left are finished under version 32, after booting HZ=1000 |
| 23 Sep | second x86 | `matched-b_20260923T015244Z`, A2 on HZ=250: `stress-ng` did not stop for a polite signal on the load-correction branch, so runs that took that branch stalled for up to an hour each (62.7 minutes on the first x86 pair that day), and the stalls took four of the twelve hours the job was given | 35 of 60 runs | Stopped with `-9` since; a complete HZ=250 day followed; the 25 left are finished under version 32 |
| 24 Sep | Arm | A3's first two sessions could not make a design: `arm_20260924T094711Z` found no Kafka entry at 50% load in its calibration, and `arm_20260924T095143Z` was pointed at a stage 0 that held no calibration | two sessions stopped before any run; A3 began about seven hours later, after a stage 0 that covered 50% load | A3 ran whole from 16:37 that day, 432 of 432 (`arm_20260924T163652Z`), at the loads D25-6 reads it at; nothing to finish |
| 25 Sep | first x86 | Both machines were deallocated at 17:32 UTC by the account's own login, not by the kit, while the queue was held | no run | Recorded; started again that evening |
| 26 Sep | first x86 | M0's receiver capture was stopped through the `sudo` that started it, which does not relay a signal from its own process group, so it never stopped; the second run waited six hours, 13:41 to 19:59 UTC | six hours of the pair | A watcher stopped each capture once its run's results were written; fixed in freeze 28 (D32-3). The run that waited is complete and counts |
| 26 Sep | second x86 | The queue's twelve-hour guard went on while the 16-round A3 `matched-b_20260926T033945Z` was on its last runs, and started A9 beside it | A3 cut at 191 of 192; the A9 stopped within a minute | Fixed in freeze 28 (D32-3): a job still at work is waited on. Both were retried whole; A3's 1 left is finished under version 32 |
| 26–27 Sep | both x86 | At 20:01 UTC both queue loops were stopped by hand and started again, to restart the twelve-hour guard's count while M0 and A3 ran, and neither new loop ran: each running campaign still held the loop's lock, which `flock` hands to the command it starts and so to every process of the campaign, and the start's check that a loop was running was satisfied by the text of the command that had called it. Found at 00:28 UTC | the first x86 pair idle for 14 minutes after its M0 ended at 00:17 UTC; no run | The first x86 pair started again at 00:31 on version 32's code; the second given at 00:34 a loop that waits for the lock and takes over when its A3 ends. The kit fix (the lock held by `flock` alone, the check made on the process it started) waits until the lists are done, so that no pair runs new queue code mid-list |
| 27 Sep | Arm | The final copy's check stopped on `stage0.log`, a link: the driver fingerprinted the file it points to, and the archive kept the link | nothing: the file it points to came home with the listed fingerprint | The check now follows a link to its file inside the archive: 30,439 of 30,439, and the two x86 archives pass again whole |

## How the programme ended, 27 September

*Plain words:* every campaign the brake or a fault had stopped was finished on its own queue,
calibration and kernel; each pair then wrote its registry, came home file by file, and switched
itself off.

- Every campaign that is not a false start is complete: 55 of 61 across the three pairs (first
  x86 23 of 24, second x86 21 of 22, Arm 11 of 15). The six false starts are in the table above,
  each replaced at once by a campaign that ran whole.
- The last runs ended at 17:28 UTC on the first x86 pair, 18:18 on the second and 20:53 on Arm.
- Brought home since the 25 September copies, each file checked against the driver's own
  fingerprint: 32,710 files (4.20 GB) from the first x86 pair, 41,798 (5.05 GB) from the second
  and 30,439 (4.67 GB) from Arm. The one file on each pair gone since 25 September is the queue's
  `stop` flag, which the loop removes when it starts again.
- Once its copy was checked, each pair's hold was released and the pair stopped itself
  (`cloud/azure/stop_self.sh`): the first x86 pair at 17:36 UTC, the second at 18:24 and Arm at
  21:03, when its driver stopped answering. The account's own view of the machines could not be
  read that evening; its login had expired.
- The registry of all 8,108 runs and 61 campaigns is in [`../registry/`](../registry/README.md).

## The Arm pair, read on 26 September

*Plain words:* the Arm pair was started for this and its disk read the same way, by
`scripts/run_registry.py`, on the kernel every one of its campaigns ran on (6.8.0-1064-azure).

Of its 17 campaign folders, 15 hold a queue. Seven of those are complete: A4 four times, A8 once,
A3 and A9's retry. Eight have runs left:

- four the brake stopped, put on the pair's list to be finished under version 32, in this order
  from 23:31 UTC on 26 September: A9 (`arm_20260925T231103Z`, 64 left), then A8 three times (116,
  129 and 142 left);
- four false starts, not rerun (D32-2): two A4s with one run between them, which ran at the same
  time on 18 September, and two A8s with none (20 and 21 September), each in the table above.

The other two folders are A3's sessions of 24 September that stopped before a design existed, in
the table above; they hold no runs, so there is nothing to finish.

## Faults found after the programme ended, 28 September

*Plain words:* reading the strange results turned up two places where the programs that judge
depart from the plan's text, one frozen test that could not keep the explanation it named, and
what stopped in the pauses. None of them changes a verdict. Each is read in full in
[the record of 28 September](the-strange-results-read-28-sep.md).

| Where | What happened | What it cost | What was done |
|---|---|---|---|
| P2, P2b and P2c (`law_predictions.width_follows_tick`, `width_against_tick`) | They read A2's two slices, 1.5 and 3 ms, as one curve per kernel; P2d's judge reads one curve per slice and kernel, as A2's design has them | P2 and P2b could not be confirmed even where the plan's formula holds exactly: fed that formula, the P2 judge returns 1.98 on Redis against a band of 2.5 to 5.5 | Recorded, and A2 read slice by slice beside the frozen answers |
| P4 (`priority_removes_the_plateau`) | A backend whose plateau is under the 2% P4 makes its claim on is worded "not confirmed" rather than out of reach | P4 reads "not confirmed", where Kafka, the one backend it makes a claim on, confirms it | Recorded; the frozen answer stands |
| M-H2's replay (`m0_read.py`, D31-2) | It gives every burst leader the same replayed trip, so with the leaders over half the messages its median grows one for one whatever the followers do | M-H2 could not be kept in any M0 run: in all 25 recorded Redis runs its median was the replay's smallest trip | Recorded; the mechanism is read message by message instead |
| Both x86 pairs, 16 to 27 Sep | Pauses of up to 20.6 s: 152 episodes of the drivers' disk writes stalling and 116 of Kafka's broker stalling; one of 0.2 s on the Arm pair | The late messages of 221 runs, every one of them counted | Recorded; what held the disks is not |

## Pocket dictionary

- **Calibration**: the session's own measure of how far each added delay moves the trip, from which
  a campaign's trips are placed.
- **Designed runs**: every setup of a campaign once per round, before any failure.
- **False start**: a campaign that stopped before it measured anything worth keeping and was
  replaced at once by a complete campaign of the same design.
- **Got-it brake**: the stop rule on a run whose "got it" time moved from its setup's earlier runs
  by more than a quarter of the delay added and more than the campaign's own scatter.
- **Kernel**: 6.8.0-1065 and 6.8.0-1064 are the two x86 pairs' stock kernels, and the Arm pair
  runs 6.8.0-1064 built for its processor; HZ=1000, 250 and 100
  are our builds of one source tree that differ in the tick alone.
- **Retried whole**: the queue's own answer to a stopped job, once: the whole campaign again, in a
  new sitting.
