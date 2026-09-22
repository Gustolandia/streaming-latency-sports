# What the Azure campaigns have found so far

**Current to 21 September 2026.** One page. Every claim below links to the note that carries its
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
| A2 | does the cliff's width follow the tick | **session 1 of 12 running again.** Its first attempt stopped itself at 28 of 40 on the got-it brake and prompted freeze 14; the 28 are kept. All three kernels boot and run within 1.4% of their tick. All three kernels built, booted and checked 21 Sep, each within 1.4% of its tick. The first of twelve sessions (HZ=1000, Kafka) is running on matched-b: 10 of 16 setups reachable, 40 runs. It was started once at 14:07 UTC, stopped after two runs and started again at 14:17 under freeze 13's code, so that all twelve sessions run one brake — see below. The counterbalanced order for the rest is below too. **Rounds cannot be simulated** (D14-5), so every session runs at the floor of 4 |
| A3 | does load move the cliff, and raise the plateau | **Kafka's second campaign finished clean on 21 Sep: 216 runs counted, 1 repeated, all 12 rounds, no stop** — the first stopped at 286 of 288 on the got-it brake. Judged, and re-judged on 22 Sep from the fingerprinted copy with identical figures: **P3b confirmed** (the plateau rises 0.081 with load, interval 0.078 to 0.083), **P3a unresolved** — its interval is about five times the band it must sit inside, which is what 38% power does. **Redis will not run.** Simulated at its own levels, P3b reaches 35.5% power at the plan's ceiling of 40 rounds, so there is no round count at which that campaign answers anything — see below. Redis now carries no A3 prediction. First Kafka campaign reported below |
| A4 | does it hold on Arm | **three of its four campaigns, not four.** The Kafka campaign at slices 1.5 and 3 ms stopped itself on 18 September and was never started again; the block has read "run, sound at 4 rounds" ever since, because the three that finished were sound and nobody counted them against the design. The fourth is running now at 4 rounds, the number its siblings ran and the number the rule gives again at this pair's corrected levels (98%) — see below |
| A5 | does the default slice follow the core count | **one session of three; the other two are queued on matched-b and start when the A2 session running now finishes.** Its 8-CPU campaign finished 20 Sep and is clean (60 runs counted, 1 repeated). The machine refuses to offline a CPU, so the count is asked for at boot instead — demonstrated at 2 and 4 CPUs on 21 Sep, see below. The two sessions still have to run |
| A7 | does go-first priority remove the plateau | run; its Kafka half checked sound at 4 rounds |
| A8 | does the client language change it | **the Arm campaign finished clean and P8 is not confirmed on it: the cliff is there in Kafka's own Java client, go-first removes it there too, but Python's plateau rate is 4.33 times Java's where the plan allows 1.5** — see below. 144 runs, no run with a problem. The x86 campaign is running. Earlier it stopped itself four times on 21 Sep, three of them instrument faults since fixed.** The fourth is the brake's shape rather than the pair: a constant offset judged by an allowance proportional to the delay, which only ever fails at the shortest trip — see below. 31 runs, 28 counted, 2 repeated, 1 stop |
| T1–T4 | what ten benchmarking tools report | **queued on matched, behind A8.** Harness built and checked against made-up tools. All ten go on one pair rather than five each: the plan requires only that each tool runs entirely on one pair, and the load is no longer the shape the five-and-five split was balanced for. Three tools wait on their version pins being resolved and written down — see below |
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

**The pairs keep their own lists now, and A4 turned out to be a campaign short.** A session cannot survive the thing driving it, because it begins with a reboot; driving the twelve A2 sessions from outside cost two quiet nights in one day. Each driver now holds its own job list and an `@reboot` line to pick it up again, so nothing outside the pair has to stay awake. Counting the Arm driver's campaigns against the design before giving it new work found that A4's Kafka campaign at 1.5 and 3 ms stopped itself on 18 September and was never started again.
→ [`law/the-pairs-keep-their-own-lists.md`](law/the-pairs-keep-their-own-lists.md)

**The Java client shows the cliff too, four times more weakly.** A8's Arm campaign is the first to finish. Kafka's own official Java client, on the same machine and the same trips, shows the same fall — 0.0236 on the plateau to 0.0013 past the cliff — so the phenomenon is not an artifact of our Python client, and go-first removes it in Java as well, by about 470 times. But Python's plateau rate is 0.1025 against Java's 0.0236, a ratio of 4.33 where P8 allows 1.5, so P8 is not confirmed on that pair. The law's shape survives the change of client; its tolerance for how much the client may matter does not.
→ [`law/a8-arm-java-shows-it-too.md`](law/a8-arm-java-shows-it-too.md)

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
| A4 ran three of its four campaigns: one stopped itself on 18 September and was never started again | counting the Arm driver's campaigns against the design before giving it new work | four days of the block reading as finished when it was not |
| a rounds simulation was started by hand on a driver, and a calibration started on the same driver eleven minutes later, overlapping it | the process list, while checking why the machine was busy | 4 minutes; one run abandoned and recorded, the calibration restarted clean |
| the watch would have called a pair with a queue on it idle and deallocated it, because a queue between jobs looks like nothing at all | adding the queue and asking what the watch would make of it | none — caught before the watch was started |
| the P8 judge said in its own docstring that it tests the cliff **and the priority effect**, and tested only the cliff and the language ratio | judging A8's finished Arm campaign and reading the rule it printed against the plan's | none — fixed the same day, and the campaign re-judged under all three clauses gives the same verdict and the same cut, 469.7 |
| the watch called a run impossible for a trip above a flat 50 ms, when the run itself had been asked to add 32 | two sound calibration runs flagged within minutes of an HZ=100 session starting | none — the ceiling is now measured from the run's own delay |

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
