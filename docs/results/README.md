# What the Azure campaigns have found so far

**Current to 22 September 2026.** One page. Every claim below links to the note that carries its
numbers, and every note says which freeze it was judged against. If this page and a note
disagree, the note is right and this page is stale.

The plan itself is not here. It lives in [`freezes/`](../../freezes/), one folder per version,
never edited — see that folder's README for the rules. The kit that runs the campaigns is
documented in [`cloud/azure/README.md`](../../cloud/azure/README.md).

**Words used here.** *Trip* — the real time from a message being sent to it arriving. *Slice* —
how long the scheduler lets a helper run before switching. *Plateau, cliff, floor* — the three
parts of the curve the law predicts: a high rate of bad readings at short trips, a sharp fall,
then almost none. *Out of reach* — a condition the instrument cannot test, reported as that
rather than as a negative result.

## The state of play

| Block | What it asks | Where it stands |
|---|---|---|
| A1 | does the cliff follow the slice | run, sound at 4 rounds |
| A2 | does the cliff's width follow the tick | **one session of fifteen done; the other fourteen are queued on matched-b and run unattended.** All three kernels were built, booted and checked on 21 Sep, each within 1.4% of its tick. The first session (HZ=1000, Kafka) is complete: 10 of 16 setups reachable, 40 runs. An earlier attempt stopped at 28 of 40 on the got-it brake and prompted freeze 14; the 28 are kept. The six Redis sessions run first, then A5's two, then the six Kafka ones and the two stock bridges — Kafka was blocked until 22 Sep because its calibration cannot meet a flat 0.30 ms precision bound on a 4 or 10 ms tick, and that bound now follows the tick. **Rounds cannot be simulated** (D14-5), so every session runs at the floor of 4 |
| A3 | does load move the cliff, and raise the plateau | **Kafka's second campaign finished clean on 21 Sep: 216 runs counted, 1 repeated, all 12 rounds, no stop** — the first stopped at 286 of 288 on the got-it brake. Judged, and re-judged on 22 Sep from the fingerprinted copy with identical figures: **P3b confirmed** (the plateau rises 0.081 with load, interval 0.078 to 0.083), **P3a unresolved** — its interval is about five times the band it must sit inside, which is what 38% power does. **Redis will not run.** Simulated at its own levels, P3b reaches 35.5% power at the plan's ceiling of 40 rounds, so there is no round count at which that campaign answers anything — see below. Redis now carries no A3 prediction. First Kafka campaign reported below |
| A4 | does it hold on Arm | **complete, four of four, and P9 is not confirmed on it.** The fourth campaign — Kafka at slices 1.5 and 3 ms — had never been started at all: two campaigns were put on the pair at once on 18 September, both stopped within a second of each other, and in restarting them one at a time the one that had never run was left out. The block read "run, sound at 4 rounds" for four days. It ran on 22 September, 44 of 44 runs with no run carrying a problem, and P9 could be judged for the first time on all 232 runs that carry numbers. **Read the way the plan asks, every halfway point the pair can reach sits inside its band and the slope against the slice sits inside 0.8–1.2 on both backends — 0.830 for Kafka, 1.153 for Redis. What fails is the fitted summary of the same curves**, whose halfway points barely rise with the slice and on Kafka fall. P9 is judged on both summaries, so it is not confirmed. The first reading of this block judged the four campaigns out of one folder, which silently skipped the anchor correction and put both free slopes just outside the band; and it called the disagreement a measurement too loose to decide, which the power figures below do not support — see below |
| A5 | does the default slice follow the core count | **one session of three; the other two are queued on matched-b and start when the A2 session running now finishes.** Its 8-CPU campaign finished 20 Sep and is clean (60 runs counted, 1 repeated). The machine refuses to offline a CPU, so the count is asked for at boot instead — demonstrated at 2 and 4 CPUs on 21 Sep, see below. The two sessions still have to run |
| A7 | does go-first priority remove the plateau | run; its Kafka half checked sound at 4 rounds |
| A8 | does the client language change it | **complete, both pairs, and P8 is not confirmed on either — the same two clauses hold and the same one fails.** The cliff is there in Kafka's own official Java client on both processors, and go-first removes it there too (1227× on x86, 470× on Arm, where the plan asks for 5×). Python's plateau rate is **3.25 times Java's on x86 and 4.33 times on Arm**, where the plan allows 1.5, and the two intervals do not overlap. 288 runs, 288 counted, no run with a problem on either pair. The x86 campaign stopped itself five times before its final resume, four of them instrument faults since fixed; the fifth was the brake stopping it at 86 of 144 on a move of 0.134 ms where it allowed 0.132. Its 6 rounds were chosen from the Arm pair's levels because the x86 pair has no A8 pilot — recomputed at its own, 6 rounds gives 87% and 4 would have given 78% — see below |
| T1–T4 | what ten benchmarking tools report | **queued on matched, behind A8, and its install step exists for the first time** — it had never fetched or built a single tool. Harness built and checked against made-up tools. All ten go on one pair rather than five each: the plan requires only that each tool runs entirely on one pair, and the load is no longer the shape the five-and-five split was balanced for. Three tools wait on their version pins being resolved and written down — see below |
| T5 | do the tools' own documents admit it | done, frozen in freeze 08 |

## What has actually been found

**Load raises the plateau. Whether it moves the cliff still cannot be shown — now on two
campaigns.** A3's Kafka block has run twice on the first pair: 15 complete rounds judged against
freeze 05, and a second campaign of 12 complete rounds judged against freeze 12 on 21 September.
Both confirm P3b, the second at 0.081 with a 95% interval of 0.078 to 0.083. Neither can confirm
P3a: the second campaign puts the cliff's move at +0.13 ms by one summary and −0.33 by the
other, with intervals about five times the 0.25 ms band the rule allows.
→ [`law/a3-kafka.md`](law/a3-kafka.md)

The reason the second half could not be shown is worth more than the result. At 50% load the
negative rate is 0.15%, and a cliff cannot be located in a curve that shallow — not for want of
running, which was checked against that campaign's own data by holding 5, 8, 11 and 15 rounds
and watching the answer refuse to settle. Freeze 10 judges that prediction only where the
plateau reaches 2%.

The second campaign sharpens that, and then overturns the reading. Recomputing the rounds
rule on 21 September, at A3's own design and the levels its own note quotes, P3a confirms in
**38.3%** of 1000 simulated campaigns at 12 rounds and 54.6% at 16 — where the campaign's note
claims 84%. So both Kafka campaigns were underpowered for P3a, and two null results are what
that design does, not two pieces of evidence about load and the cliff. The same check on A1, A4
and A7 reproduces their notes — 100.0%, 99.5% and 100.0% at 4 rounds against 99%, 92–100% and
100% — so this is
particular to P3a, the one equivalence test among them, and not the plan's arithmetic in
general. Why the stated figure and the recomputed one differ is open.

**Every client has the cliff, and they are not in the same place.** Redis at its own natural
speed is the noisiest thing in the experiment — 63% of readings negative at 50% load — and falls
to 0.08% with one millisecond added. Kafka's cliff sits further right. Read off the calibration
of 20 September, 30 runs, both backends, three loads.
→ [`law/cliff-position-by-client.md`](law/cliff-position-by-client.md)

This is what is really behind "P3a and P4 cannot be tested on Redis". It is not that Redis is
well behaved. It is that a 3 ms slice asks for trips of 2.7 ms and up, and Redis is already past
its own cliff by then. The same happens to Kafka at 50% load.

**A campaign's got-it sits a constant eighth of a millisecond below its calibration's, and the
brake judges that against an allowance proportional to the delay.** So it can only ever fail at
the short end of the ladder, which is where A8 stopped. Two lines of A8's own table carry it: the
largest move in the campaign, −0.273 ms, **passed** where the allowance was 0.674, while a
smaller −0.252 **stopped the campaign** where the allowance was 0.221 — and the same setup came
in at +0.001 the other time it ran. The delay is not the cause: the shift's slope against the
delay is +0.004 ms per ms over a ladder from 0.88 to 3.46 ms, and four calibration sweeps agree.
→ [`law/gotit-falls-when-the-delay-is-added.md`](law/gotit-falls-when-the-delay-is-added.md)

Two earlier versions of that note were wrong — one read the baseline off the calibration from
before the pair was restarted, the other said the failing run was re-queued three times when it
was never re-queued at all. Both errors are kept visible at the top of the note.

**A2's three kernels boot, and each runs at the tick it was built for.** 999.958, 251.231 and
101.367 Hz against 1000, 250 and 100, all inside the plan's 5%; HRTICK off on all three; tickless
settings identical, which is what holds them to differing in the tick alone. Finding that out took
fixing two faults in the check itself, either of which would have reported all three kernels as
broken: it counted a timer Azure does not use, and nothing was keeping a CPU busy for it to count
on.
→ [`law/a2-three-kernels-boot-and-tick.md`](law/a2-three-kernels-boot-and-tick.md)

**A5's core counts have to be asked for at boot, and the slice follows them exactly.** The
machine refuses to switch a CPU off, so the count goes on the kernel command line instead:
`nr_cpus=2` gives a 1,400,000 ns default slice and `nr_cpus=4` gives 2,100,000, against 2,800,000
at eight — every one of them exactly `700000 × (1 + ilog2(n))`. Not `maxcpus`, which looks like
the same parameter and leaves the machine back at eight CPUs within a second.
→ [`law/a5-core-count-must-be-asked-for-at-boot.md`](law/a5-core-count-must-be-asked-for-at-boot.md)

**The pairs keep their own lists now, and A4 turned out to be a campaign short.** A session cannot survive the thing driving it, because it begins with a reboot; driving the twelve A2 sessions from outside cost two quiet nights in one day. Each driver now holds its own job list and an `@reboot` line to pick it up again, so nothing outside the pair has to stay awake. Counting the Arm driver's campaigns against the design before giving it new work found that A4's Kafka campaign at 1.5 and 3 ms had never been started at all, four days after the block was recorded as run.
→ [`law/the-pairs-keep-their-own-lists.md`](law/the-pairs-keep-their-own-lists.md)

**The tools block's version table held five hashes that were not commits, and the audit it should have copied had the real ones.** Every hash in `cloud/azure/tools.sh` was asked of its own repository on 22 September — the first time any had been, because the install step had never fetched anything. Five came back 422 and GitHub's commit search finds them in zero repositories. They are mangled transcriptions: each shares its first 28 to 34 characters with the value in `data/tools_audit/`, T5's own records, whose hashes are all real. Nothing frozen or published rests on the table; T1–T4 had not run. The table is now the audit's.
→ [`tools/the-version-table-held-hashes-that-were-not-commits.md`](tools/the-version-table-held-hashes-that-were-not-commits.md)

**On Arm the cliff follows the slice exactly, and the fitted summary of the same curves does not.** A4's four campaigns, 232 runs that carry numbers, judged once its missing fourth campaign ran. Lined up through the 3 ms anchor the way the plan asks, every reachable halfway point is inside its band — all three slices for Redis, both reachable ones for Kafka — and the slope against the slice is inside 0.8 to 1.2 on both backends, 0.830 and 1.153. The fitted shape's halfway points barely rise with the slice and on Kafka fall: 3.90 ms at a 3 ms slice and 3.77 at a 4.5 ms one. P9 asks both summaries, so it is not confirmed — and this is not the scatter, because the same rule confirms P9 in 97 to 100 of a hundred simulated campaigns at this pair's own noise. The first reading of this block reported the uncorrected slopes as though they were the corrected ones, and read the disagreement as imprecision; both are corrected in the note.
→ [`law/a4-arm-p9-the-cliff-follows-the-slice-and-the-fitted-shape-does-not.md`](law/a4-arm-p9-the-cliff-follows-the-slice-and-the-fitted-shape-does-not.md)

**The Java client shows the cliff too, four times more weakly.** A8's Arm campaign is the first to finish. Kafka's own official Java client, on the same machine and the same trips, shows the same fall — 0.0236 on the plateau to 0.0013 past the cliff — so the phenomenon is not an artifact of our Python client, and go-first removes it in Java as well, by about 470 times. But Python's plateau rate is 0.1025 against Java's 0.0236, a ratio of 4.33 where P8 allows 1.5, so P8 is not confirmed on that pair. The law's shape survives the change of client; its tolerance for how much the client may matter does not.
→ [`law/a8-arm-java-shows-it-too.md`](law/a8-arm-java-shows-it-too.md)

**A8 is complete, and P8 fails on both processors for the same reason.** The x86 campaign finished on 22 September: 145 runs, 144 counted, no run with a problem. The cliff is in Kafka's own Java client on x86 as it is on Arm — 0.0206 on the plateau falling to 0.0016 past it — and go-first cuts Java's plateau by 1227 times where the plan asks for 5. Python's plateau rate is 3.25 times Java's (2.81 to 3.91) against 4.33 on Arm (4.07 to 4.67): both far above the 1.5 the plan allows, and two intervals that do not overlap, so how much the client matters is itself a property of the machine. The x86 pair has no A8 spread pilot, so its 6 rounds were sized from the Arm pair's levels; recomputed at its own, shallower levels 6 rounds gives 87% power and 4 would have given 78%.
→ [`law/a8-x86-the-block-is-complete-and-p8-fails-on-both-pairs.md`](law/a8-x86-the-block-is-complete-and-p8-fails-on-both-pairs.md)

**Two ABI builds of one kernel version give two different default slices, and the version number
predicts only one of them.** The first x86 pair now runs `6.8.0-1065-azure` and the second
`6.8.0-1064-azure` — same VM size, same eight CPUs, same log scaling, same 1000 Hz tick — and
their kernel-chosen base slices are **3,000,000 ns and 2,800,000 ns**. That is a per-step constant
of 750,000 against 700,000. Asked from the release string alone, this kit's own rule says
3,000,000 for both: right for 1065, wrong for 1064, which is why it recovers the constant from the
machine instead of trusting the version.

The pairs drifted apart on 16 September, when unattended-upgrades installed 1065 on the first pair
during the incident that also cost that day's pilot; it was booted into on 20 September. Nothing
measured so far is invalidated — every block that compares slices sets its slice explicitly, and
P7, the one block that reads the kernel's default, runs on the second pair. A2's three kernels are
built from one source tree and all three report 2,800,000, so they still differ in the tick and
nothing else. What it does mean is that A3's two Kafka campaigns sit on different kernel builds,
and anyone pooling them has to say so.

**T1 works as designed. T2, as first frozen, could not have answered anything.** Run against
made-up tools built from their clocks and their arithmetic, then re-run on 19,952 trips A3
actually measured. At the 2 ms offset the plan froze, **not one trip of 3,000 goes below zero** —
the shortest trip we have ever recorded is 2.035 ms.
→ [`tools/t1-t2-synthetic.md`](tools/t1-t2-synthetic.md)

Corrected in freeze 11: the offsets come from the measured trip, the prediction passes through
the step T1 measures, and the verdict names what survives rather than what is nearest. Five of
six tool classes are then named on real trips, and none wrongly.

## What is out of reach, and why

Reported as out of reach rather than as a negative result, which is the distinction the plan
insists on throughout.

- **The whole of A3 on Redis, P3b included.** P3a and P4 were already out: its plateau at the
  anchor slice is 0.55–1.15%, under the 2% guard. P3b, the one prediction Redis still carried,
  was simulated on 21 September at this pair's own measured Redis levels — spread 0.4232,
  plateau 0.0057, floor 0.0005 — against A3's real design of 18 setups a round:

  | rounds | 4 | 8 | 16 | 24 | 32 | 40 |
  |---|---|---|---|---|---|---|
  | confirms under the law | 12.5% | 16.0% | 20.0% | 26.0% | 33.5% | **35.5%** |

  It never approaches the 80% the plan asks, and at 4 rounds it confirms where the law is false
  8% of the time, over that bar as well. Forty rounds is the plan's ceiling, so there is no
  number of rounds at which this campaign answers P3b on this pair, and **Redis now carries no
  A3 prediction at all**.

  Worth saying plainly what was avoided: the rounds rule returns the ceiling flagged
  underpowered, which is not the same as the "never confirms" the chain refuses, so the chain
  would have started a **720-run campaign of about 34 hours** with a one-in-three chance of
  confirming. The simulation that showed this ran on a laptop in 20 minutes.
- **P3a at 50% load on Kafka**: 0.33–0.41%, same guard, same reason.
- **A2's round count**: the rounds rule simulates one kernel at a time and the tick predictions
  compare two, so A2 runs at the floor of 4 rounds with its power unknown. The largest block in
  the plan and the largest open risk.
- ~~**A5 at 2 and 4 CPUs, and therefore P7 as a whole.**~~ **No longer out of reach, as of 21
  September.** The machine still refuses to switch a CPU off, so the count is asked for at boot
  with `nr_cpus=N` instead, and both 2 and 4 CPUs have been reached and measured. The two sessions
  have still to run. See the note above.
- **T2 on the tool that reads a millisecond clock twice**: its error depends on where in the
  tick each message was sent, and that variance is the size of the difference T2 looks for. T-P2
  is judged by T1 instead, which separates it cleanly.

## Faults found and what they cost

Kept because a reader should be able to see what the instrument did wrong, not only what it
measured.

| What | Found by | Cost |
|---|---|---|
| P8 read a trip A8 never runs | the rounds rule answering 0% at every round count | none — caught before running |
| A8's calibration read as though it were not keyed by client | the campaign stopping itself | 4 runs |
| the got-it brake compared an inline run to a callback calibration | the campaign stopping itself again | 3 runs, one restart (freeze 12) |
| three tool parsers wrong against real output | checking them against the tools' own source | none — caught before running |
| T2's offsets could not make a negative | running the block against made-up tools first | none — caught before running |
| four faults in the kernel build | running it | three would each have cost a six-hour build |
| the tick check counted the local APIC timer, which on Azure is present and always zero | booting the first kernel and being told it was 100% out | none — it would have failed all three |
| the tick check had no busy CPU to count on, and an idle CPU stops its timer | the same run | none |
| installing A2's built kernels made one of them grub's default, so every restart of that driver came up on the HZ=1000 kernel | reading which kernel a restart actually came back on | none — no block had run since |
| the chain simulated a campaign's rounds at the backend named in its environment, not the one named on its command line | reading the chain's own log in the minute before the campaign started | none — stopped before it ran |
| the chain sized every campaign against a generic nine-point design, so A8's P8 was simulated in a world with no clients and could not confirm at any round count | A8's chain refusing to start, and reading why | none — the refusal was correct; A8 started once the design was its own |
| a waiter for one campaign read a completion line left by another hours earlier and opened a second calibration on a pair already running one | the process list, two minutes later | 2 runs, both caught by their own timeout and re-queued; no counted run was judged during the overlap |
| the same fault again, on the other pair: a waiter read the line the previous session left and rebooted the machine under a calibration that was still running | the kernel it came back on | about two minutes; the session it interrupted had made no runs yet, and is owed |
| the watch counted a pair with a campaign chained behind a calibration as idle, and would have deallocated it | reading the watch's own log while A3's Redis chain simulated | none — it survived only on one core of eight being 12.5%, just over the 10% called busy |
| fixing that made a long simulation look like a stalled campaign, alerting every five minutes | the first alert it produced | none — caught in one cycle |
| a run measured the previous rung's delay, with the load still flat out at 99.8% | the repeat rule, on two of A8's 31 runs | 2 runs |
| P7 could not be judged at all: it compared the machine's reported slice against a designed one, and A5 is the one block that sets none | reading A5's finished campaign instead of waiting for the rest of it | none — but the two remaining A5 sessions, about eight hours, would have run first |
| P8 could not see which client sent a run: the reader never extracted the language, so it reported that A8 had not tested P8 at all | asking the same question of every other judge after P7 | none — caught while A8 was still running |
| a session driven from outside dies with whatever is driving it, and the pair goes quiet until somebody notices | it happening twice on 21 September | the pairs now keep their own lists, across their own reboots |
| A4 ran three of its four campaigns: two were put on the pair at once, both stopped, and restarting them one at a time left out the one that had never run | counting the Arm driver's campaigns against the design before giving it new work | four days of the block reading as finished when it was not |
| a rounds simulation was started by hand on a driver, and a calibration started on the same driver eleven minutes later, overlapping it | the process list, while checking why the machine was busy | 4 minutes; one run abandoned and recorded, the calibration restarted clean |
| the watch would have called a pair with a queue on it idle and deallocated it, because a queue between jobs looks like nothing at all | adding the queue and asking what the watch would make of it | none — caught before the watch was started |
| the P8 judge said in its own docstring that it tests the cliff **and the priority effect**, and tested only the cliff and the language ratio | judging A8's finished Arm campaign and reading the rule it printed against the plan's | none — fixed the same day, and the campaign re-judged under all three clauses gives the same verdict and the same cut, 469.7 |
| the watch called a run impossible for a trip above a flat 50 ms, when the run itself had been asked to add 32 | two sound calibration runs flagged within minutes of an HZ=100 session starting | none — the ceiling is now measured from the run's own delay |
| a campaign was refused unless **every** backend's calibration passed, whichever backend it actually ran | three A2 and A5 sessions refused in a row, each after about two and a half hours of calibrating | about 7.5 hours of one pair; no runs, because none were placed |
| the calibration's precision bound was a flat 0.30 ms, set on a 1 ms tick, while A2 boots kernels whose tick is 4 and 10 ms | Kafka missing it at 0.410 and 0.387 where Redis made 0.128 to 0.237 on the same boots, and four rounds not mending it | it blocked six of A2's twelve sessions until the bound was made to follow the tick |
| the got-it brake's allowance came from the campaign's own scatter with a floor below the drift a sound campaign shows | A8's x86 campaign stopping at 86 of 144 on a move of 0.134 ms where it allowed 0.132 | an eight-hour campaign stopped on an overshoot of two microseconds; resumed from run 87, nothing re-run |
| the tools block's install step installed nothing: it fetched the build dependencies, listed the pins and only reported what was present | running it on a machine for the first time -- it finished in under a second and said MISSING eleven times | the whole block, which had never been run because T1 and T2 were checked against made-up tools |
| five of the six pinned tool versions were not commits in those repositories, and three more said "not pinned yet" although the audit had a real commit for each | asking every hash of its own repository, once the install step fetched anything at all | none frozen or published — but five T3/T4 runs made against a HEAD build are quarantined |
| a cited reference gave the right title and authors with the wrong volume, issue, pages, year and a DOI that resolves to nothing | checking every cited reference's numbers against Crossref, not just its title | none — the supplement cites it; corrected |
| the broker has no hosts.env -- session.sh leaves one on the driver only -- so every script that loads common.sh refused before it started | sixty-four tool jobs failing in fifteen seconds | none; the pair was idle rather than wrong |
| a server the tools block starts was called dead in the same second it logged "Server is ready" | reading its own log next to the check's timestamp | none -- but it stopped the block at its first job twice, once for this and once for a download that 404'd |
| `queue.sh start` reported "running" without looking, so a lock left by a killed loop silently started nothing | a pair sitting idle through its whole tools block until the watch stopped it | about half an hour of one pair |
| `cpus.sh` counts the CPUs the running kernel knows about, so a 2-CPU boot cannot then ask for 4 | A5's 4-CPU session failing its boot check straight after the 2-CPU one | none -- the check caught it; the jobs are ordered 4 before 2 |
| every judge read the runs the integrity rule had stopped: the reader kept anything with a trip and a negative rate, and run_integrity.py's own refusal to compare against them was not carried into the judges | counting A8's runs by design point and finding thirteen where the design has twelve | none — five runs in 3,179 carry a verdict other than count; A3's two answers reproduce to four decimals and A8's ratio moves from 3.12 to 3.25 with the same verdict |
| A4's P9 was judged with its four campaigns copied into one folder, so every run carried that folder's name, the anchor correction found one campaign and silently moved everything by zero, and the answer still printed that each campaign had been moved by its own offset | re-reading the block campaign by campaign while recomputing its power | a published note whose central claim was wrong: both free slopes sit inside the band once the correction is applied, not outside it |
| A8's x86 campaign was sized from the other pair's spread pilot, because that pair has no A8 pilot of its own | looking for the levels file its rounds note names | none — at its own measured levels 6 rounds gives 87%, above the 80% the rule asks; 4 rounds would have given 78% |
| the got-it gate called a gross departure a shift of more than a quarter of the delay added, step by step, so a note that drifts by a fixed amount fails at every step below four times the drift and passes above it | the second x86 pair's HZ=1000 Redis calibration ending on +0.342 ms at 1 ms added while the Kafka half of the same sitting passed on -0.315 at 4 ms and -0.282 at 8 | about an hour of one pair; the session is re-run. Regressed on the delay the two staircases give slopes of -0.010 and -0.038, so nothing was leaking in either |
| rdkafka_performance's consumer was started after the producer it measures, and its latency mode needs the two running together; it starts at the end of the topic, so it waited for messages that had already been sent | a tools job that had run for twenty-eight minutes where the others take one | twenty-eight minutes of one pair -- the only limit above it was the queue's twelve hours, and the runner now re-execs itself under six times the run's own length |

Those last two are one fault with two faces, and both survived a suite at 100% branch coverage.
Every test of a judge builds its runs from the made-up world, and that world is not shaped like a
run off a driver: it sets a slice on every run where A5 sets none, and it carries a language that
the reader of real runs never extracted. So the shapes real campaigns produce had never once
reached the judges. Coverage said the branch ran; it said nothing about whether the input could
occur.

P7 announced itself by raising. P8 would not have: it would have reported that A8's campaign did
not test P8, which reads exactly like a result. `tests/unit/test_law_curve.py` now holds the
contract directly — every field a judge asks a run for must be one the reader gives it — and that
test fails if either fix is removed.
