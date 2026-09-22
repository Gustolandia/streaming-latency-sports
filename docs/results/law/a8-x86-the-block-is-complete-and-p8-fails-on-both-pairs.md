# A8 on x86: the block is complete, and P8 fails on both pairs for the same reason

**22 September 2026, first x86 pair, campaign `matched_20260922T010403Z`, judged against
freeze 16.** 145 runs, 144 of them counted, 24 setups at 6 rounds, **no run with a problem** in
the quality report. With the Arm campaign of 21 September, A8 is finished: both pairs, 288 runs
of which 288 count, and the same verdict on each.

**Words used here.** *Negative rate* — the share of messages whose measured trip comes out
impossible, arriving before they were sent. *Plateau* — the level that rate sits at for trips
shorter than the scheduler's slice. *Floor* — the level it falls to past the cliff. *Go-first* —
giving the timestamping helper real-time priority. *p09s, c05h, f15h* — the trip at 0.9 of the
slice (on the plateau), the middle of the cliff, and one and a half cliff-widths past it.

## What it measured

Mean negative rate, 12 counted runs behind every number. Kafka, 3 ms slice, 75% load, 1 ms tick.

| trip | client | ordinary | go-first |
|---|---|---|---|
| **p09s** — the plateau | Java | **0.0206** | 0.000017 |
| | Python | **0.0668** | 0.000017 |
| **c05h** — the cliff's middle | Java | 0.0139 | 0.000000 |
| | Python | 0.0435 | 0.000000 |
| **f15h** — past the cliff | Java | 0.0016 | 0.000000 |
| | Python | 0.0206 | 0.000000 |

## P8 is not confirmed here either, and the clause that fails is the same one

**The cliff is there in Java.** Its rate falls 0.0206 → 0.0139 → 0.0016 across the plateau, the
middle and the floor: the middle lies between the other two, in every one of 2000 resamplings.
Kafka's own official Java client, on an x86 machine this time, shows the same shape the Python
client shows. Two processors, two clients, one shape.

**Go-first removes it in Java too**, and more completely than on Arm: the plateau falls from
0.0206 to 0.000017, a cut of **1227 times** where the plan asks for at least 5. Past the cliff and
in its middle, and for Python everywhere, go-first takes the rate to exactly zero.

**The sizes are three times apart.** Python's plateau rate is 0.0668 against Java's 0.0206, a
ratio of **3.25**, 95% interval 2.81 to 3.91, p = 0.0005. The plan allows at most **1.5**. So P8,
which requires all three clauses at the 95% level on each machine pair, is **not confirmed** on
this pair, exactly as on the Arm one.

## What the two pairs together say

| | x86 | Arm |
|---|---|---|
| Java's plateau | 0.0206 | 0.0236 |
| Python's plateau | 0.0668 | 0.1025 |
| ratio, with its interval | **3.25** (2.81 to 3.91) | **4.33** (4.07 to 4.67) |
| go-first's cut on Java's plateau | 1227× | 470× |
| cliff present in Java | yes, 2000 of 2000 | yes, 2000 of 2000 |
| P8 | not confirmed | not confirmed |

Two things are worth saying about that table. The first is that the law's *shape* survives
everything this block varied — the client, the processor, and where the acknowledgement is
stamped — and its *tolerance* survives neither pair. The second is that the two ratios' intervals
do not overlap: 2.81 to 3.91 against 4.07 to 4.67. How much the client matters is itself a
property of the machine, not a constant, which is one more reason a fixed ceiling of 1.5 was the
wrong shape of claim to make.

## The rounds were enough, and were nearly chosen from the wrong machine

Both campaigns ran 6 rounds, and both recorded before starting that 6 gives 86% power under the
law and 0% where P8 is false. The Arm campaign's note names the world it was simulated in: that
pair's own spread pilot, 0.2562 spread with a 0.0568 plateau and a 0.0123 floor. **The x86 pair
has no A8 pilot at all** — no `levels_A8.json` was ever written on it — so its 6 rounds were
chosen at the Arm pair's levels, which is not what the plan asks.

Recomputed at the x86 pair's own measured levels, read at the same 3 ms anchor from its own
spread pilot (spread 0.2500, plateau 0.0346, floor 0.0093 — a shallower cliff, and a shallower
cliff is harder to find), **6 rounds gives 87%** and 4 rounds gives 78%. So the number was right
by luck rather than by procedure: the campaign had the power the rule asks for, at its own noise,
and 4 rounds would not have. Recorded here because the next block to be sized from another
machine's pilot may not be so lucky.

None of this changes the verdict. P8 fails on the ratio clause, and the interval sits well clear
of the bound it must be under; more rounds would narrow it around 3.25, further from 1.5, not
closer.

## The one run that does not count, and the judge that used to read it

The campaign has 145 runs and 144 of them count. Run `r004-...-p09s-rt-python-callback` stopped
on the got-it brake: its median moved 0.134 ms from the campaign's three earlier runs of that
setup where the brake allowed 0.132. That is the overshoot of two microseconds that raised the
brake's floor to 0.25 ms and had the campaign resumed from run 87; the run is on disk, it is
reported, and it decides nothing. Its replacement ran, so the design is complete at 24 setups by
6 rounds.

Until today it did decide something. The reader that feeds every judge kept any run that had a
trip and a negative rate, whatever the integrity rule had said about it, so this run was in the
curve. Read with it, the ratio is 3.1206 (2.68 to 3.84); read without it, 3.2506 (2.81 to 3.91).
The verdict is the same and every other judgement in the project moves by nothing at all — across
all 3,179 collected runs only five carry a verdict other than `count`, and re-judging the two
campaigns that hold them reproduces A3's P3a and P3b to four decimal places. The reader now keeps
only the runs the integrity rule passed, and both command lines name what they left out before
they answer.
