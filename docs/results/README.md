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
| A2 | does the cliff's width follow the tick | kernels building; **rounds cannot be simulated** (D14-5), runs at the floor of 4 |
| A3 | does load move the cliff, and raise the plateau | Kafka run once (below); Redis not run |
| A4 | does it hold on Arm | run, sound at 4 rounds |
| A5 | does the default slice follow the core count | **one session of three.** Its 8-CPU campaign finished 20 Sep and is clean (60 runs counted, 1 repeated); P7 needs 2 and 4 CPUs as well, and neither has run |
| A7 | does go-first priority remove the plateau | run; its Kafka half checked sound at 4 rounds |
| A8 | does the client language change it | running on Arm, 6 rounds |
| T1–T4 | what ten benchmarking tools report | harness built and checked against made-up tools; no machine run yet |
| T5 | do the tools' own documents admit it | done, frozen in freeze 08 |

## What has actually been found

**Load raises the plateau, and does not move the cliff — but the second half could not be
shown.** A3's Kafka campaign, 15 complete rounds, judged against freeze 05.
→ [`law/a3-kafka.md`](law/a3-kafka.md)

The reason the second half could not be shown is worth more than the result. At 50% load the
negative rate is 0.15%, and a cliff cannot be located in a curve that shallow — not for want of
running, which was checked against that campaign's own data by holding 5, 8, 11 and 15 rounds
and watching the answer refuse to settle. Freeze 10 judges that prediction only where the
plateau reaches 2%.

**Every client has the cliff, and they are not in the same place.** Redis at its own natural
speed is the noisiest thing in the experiment — 63% of readings negative at 50% load — and falls
to 0.08% with one millisecond added. Kafka's cliff sits further right. Read off the calibration
of 20 September, 30 runs, both backends, three loads.
→ [`law/cliff-position-by-client.md`](law/cliff-position-by-client.md)

This is what is really behind "P3a and P4 cannot be tested on Redis". It is not that Redis is
well behaved. It is that a 3 ms slice asks for trips of 2.7 ms and up, and Redis is already past
its own cliff by then. The same happens to Kafka at 50% load.

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

- **P3a and P4 on Redis**, on every pair: its plateau at the anchor slice is 0.55–1.15%, under
  the 2% guard. Not a property of Redis — see the cliff note above.
- **P3a at 50% load on Kafka**: 0.33–0.41%, same guard, same reason.
- **A2's round count**: the rounds rule simulates one kernel at a time and the tick predictions
  compare two, so A2 runs at the floor of 4 rounds with its power unknown. The largest block in
  the plan and the largest open risk.
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
| P7 could not be judged at all: it compared the machine's reported slice against a designed one, and A5 is the one block that sets none | reading A5's finished campaign instead of waiting for the rest of it | none — but the two remaining A5 sessions, about eight hours, would have run first |
| P8 could not see which client sent a run: the reader never extracted the language, so it reported that A8 had not tested P8 at all | asking the same question of every other judge after P7 | none — caught while A8 was still running |

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
