# A constant offset judged by a proportional allowance: why A8 stopped at its shortest trip

**21 September 2026. Read off A8's campaign on the Arm pair (`arm_20260921T025629Z`) — 31 runs,
28 counted, 2 repeated, 1 stop — and off the delay sweeps in four calibrations.** Not a test of
any prediction: the instrument reporting on itself, which is what P5(c) is for.

> **Two earlier versions of this note were wrong, and both errors are worth naming.** The first
> reported offsets of −0.138 ms (Java) and −0.252 (Python) as systematic and about a fifth of each
> client's got-it. Those came from reconstructing a baseline out of the calibration taken *before*
> the pair was restarted, instead of reading the shifts the judge itself computed; and the −0.252
> was not a typical value at all but the single worst run in the campaign. The second said the
> failing run was re-queued and failed three times over. It was not re-queued once: every run in
> the campaign is attempt `a1`, and a `stop` verdict ends the session by itself.

**Words used here.** *Got-it* — the time from a message being sent to the broker's acknowledgement
reaching the sender. *The brake* — the rule that stops a session when the added delay appears to
have moved the got-it (P5c, tightened by D8-2). Its allowance is the larger of a quarter of the
added delay and the session's own got-it scatter.

## Every comparison the judge made

Fifteen of the 31 runs were compared; the other sixteen are the inline half, which has no
like-for-like baseline, and the runs with no added delay. Sorted by the allowance each was given.

| run | added | move | allowance | |
|---|---|---|---|---|
| p09s python callback | 0.88 | **+0.001** | 0.221 | |
| p09s python callback | 0.89 | **−0.252** | 0.221 | **stop** |
| p09s rt python callback | 0.89 | −0.199 | 0.222 | |
| p09s rt java callback | 1.66 | −0.043 | 0.416 | |
| c05h python callback | 1.69 | −0.088 | 0.423 | |
| c05h rt python callback | 1.69 | −0.118 | 0.423 | |
| c05h java callback | 2.46 | −0.068 | 0.616 | |
| c05h rt java callback | 2.46 | −0.119 | 0.616 | |
| f15h python callback | 2.69 | −0.109 | 0.674 | |
| f15h rt python callback | 2.69 | −0.141 | 0.674 | |
| f15h python callback | 2.70 | **−0.273** | 0.674 | largest move in the campaign — **passed** |
| f15h java callback | 3.46 | −0.069 | 0.865 | |
| f15h rt java callback | 3.46 | −0.123 | 0.865 | |
| f15h rt java callback | 3.46 | −0.125 | 0.866 | |

All in milliseconds. (A fifteenth, `p09s java callback`, was repeated for an unrelated fault and
is left out of the arithmetic below.)

Two lines carry the whole result. **The largest move in the campaign, −0.273, passed**, because it
sat where the allowance was 0.674. A smaller move, −0.252, **stopped the campaign**, because it sat
where the allowance was 0.221. And the same setup — `p09s python callback`, same client, same
delay, same allowance — came in at **+0.001 one time and −0.252 the other**.

## The offset is constant; the allowance is proportional

Across the fourteen judged comparisons the move does not grow with the delay:

> slope **+0.004 ms of shift per ms of added delay** over a delay ladder from 0.88 to 3.46 ms —
> flat, and if anything the wrong sign for a delay effect. Mean shift **−0.124 ms**, and 13 of 14
> are negative.

So there *is* a real offset in this campaign — its got-it sits about an eighth of a millisecond
below its calibration's — and it is **a fixed amount, not a fraction of the delay**. (How much a
campaign drifts from its calibration is not itself a constant: A3's 216 comparisons on the first
pair give −0.022 ms. See below.) The
brake's allowance is a quarter of the delay. A constant offset divided by a proportional allowance
can only ever fail at the short end of the ladder, which is exactly where it failed.

Scatter finishes the job. Python's judged moves have a standard deviation of 0.091 ms; at `p09s`
the allowance is 0.221 and the session's own measured got-it scatter is 0.199 — the allowance and
the noise are the same size. The rule at that rung is asking a question its own noise can answer
either way, which is why one run cleared it and its twin did not.

## What it is not

**Not the delay reaching the acknowledgement.** A calibration sweeps the delay from nothing to
eight milliseconds at one load with everything else fixed, which is the clean version of this
experiment. Four of them agree with the campaign:

| calibration | slope, ms of got-it per ms of delay | spread across the sweep |
|---|---|---|
| matched, Kafka, 50 / 75 / 88% load | −0.0042 / −0.0108 / **+0.0031** | −8% to +3% |
| matched, Redis, 50 / 75% load | −0.0040 / −0.0038 | −4% to +6% |
| arm, Kafka, Python client | −0.0060 | −3% to +10% |
| arm, Kafka, Java client | −0.0026 | −4% to +3% |

The sign is not even consistent between loads on one pair.

**Not the change of slice between calibration and campaign.** A8 calibrates at
`base_slice_ns = 2800000` and runs at `3000000`. A3 on the matched pair makes exactly the same
change and its got-it sits 1.5% from its calibration's across 59 runs.

The −0.124 ms is most likely the ordinary drift of a machine between a calibration and the
campaign that follows it, which is the thing the brake was built to tolerate and, at its shortest
rung, does not.

## It is one rung, and it is predictable which

Sorting the fourteen judged comparisons by how much room each had left — its allowance minus the
size of its move — separates them into two groups with nothing in between.

| | headroom |
|---|---|
| Python at `p09s`, three runs | −0.031, +0.023, +0.220 ms |
| every other comparison, eleven runs | 0.305 to 0.796 ms |

The chain is exact. `p09s` asks for a trip of 0.9 of the slice, 2.7 ms. Python's own trip with no
delay is the longer of the two clients', so it needs only **0.886 ms** of added delay to reach
that trip where Java needs 1.66. The allowance is a quarter of the delay, so Python's is 0.221 ms
where Java's at the same rung is 0.416. And the got-it's own move is about an eighth of a
millisecond whatever the delay. So the one place the allowance falls to the size of the noise is
the shortest delay of the client that needs the least delay — and that is where the campaign
stopped.

**What that means for running A8 again.** The block is 24 setups at 6 rounds, of which two setups
are Python at `p09s` with the note taken the calibration's way: twelve runs that land in this
group. One of the three seen exceeded its limit and a second cleared it by 0.023 ms. Three points
are not a rate, and this is not a prediction — but a campaign needs all twelve to clear, and a
single `stop` verdict ends it. Restarting collects more than the 28 runs already in hand; it is
not likely to collect all 144.

Nothing here says the brake should be loosened. It says where to look: an allowance built only
from the added delay is smallest exactly where the instrument's own noise is unchanged, and that
is a property of its shape, not of the pair.

## The allowance is built from two things, and neither is the thing that moves

The full rule is `max(a quarter of the added delay, max(0.10 ms, three times the session's own
got-it scatter))`. That second term is a floor meant to stop the first from shrinking to nothing
at short delays. Read on the two pairs:

| pair | got-it scatter within a session | its floor | allowance at the shortest rung |
|---|---|---|---|
| Arm, Python on Kafka | 0.0663 ms | 0.199 ms | **0.221** — the delay term wins |
| matched-b, Kafka | 0.1788 ms | **0.536 ms** | 0.536 — the floor wins |

So the brake is **tightest on the steadiest machine**. A pair whose got-it barely varies from run
to run gets a small floor, and at a short delay the quarter-of-the-delay term is smaller still.

The defect is not that the floor is too low. It is that the floor is built from the wrong
quantity. Run-to-run scatter *inside* a session and the drift *between* a calibration and the
campaign that follows it are different numbers, and the brake measures the first to absorb the
second.

And the second is not a constant of the instrument, which is the thing an earlier version of this
note got wrong by having only one campaign to look at. A3's Kafka campaign on the first pair
finished on 21 September with **216 judged comparisons** against A8's fourteen:

| campaign | comparisons | drift, mean | drift, sd | over the allowance | tightest headroom |
|---|---|---|---|---|---|
| A3 Kafka, first pair | 216 | **−0.022 ms** | 0.062 | 0 | 0.079 ms |
| A8, Arm pair | 14 | **−0.124 ms** | 0.091 | 1 | −0.031 ms |

Their noise floors are close — 0.170 ms on the first pair against 0.199 on the Arm — so that is
not what separates them. **The drift is**: A8's session sat six times further from its calibration
than A3's did from its, and A3's campaign ran for ten hours after its calibration where A8's ran
for three. Time is not the cause. Whatever it is belongs to that pair, that client or that
session, and one campaign of fourteen comparisons cannot say which.

**Where that leaves the campaigns now running.** A2 on matched-b sits behind a 0.536 ms floor at
every rung, which is three times the largest drift yet measured anywhere, so this brake is not the
thing to watch there. A8 on the Arm pair sits behind 0.199 to 0.221 at its shortest rung, on the
one pair whose drift has been large.

## The two repeated runs are a separate fault

Both `f15h python inline` and `p09s java callback` were judged `repeat`, and both failed the same
two checks: the broker held the *wrong* delay, and the load came in at 99.7–99.8% instead of 75%.
`f15h` was set 2.691 ms and held 0.886 — which is `p09s`'s delay. `p09s` was set 1.659 and held
2.694 — which is `f15h`'s. Each measured the delay of another rung while the load generator was
still flat out. That is a previous run's state surviving into the next one, and it is not the same
thing as the brake firing. The repeat rule caught both; neither reached the results.

## What this does not show

One campaign, one pair, one load, 28 runs kept, 14 comparisons. It does not settle what the
−0.124 ms is. Reshaping the allowance — giving it a floor, or judging the offset against runs at
several delays rather than against the calibration — is a change to a frozen rule and belongs in a
freeze; nothing here loosens it. Freeze 12 already asks for the comparison the campaign's own data
could support (D16-2), and `law_curve` now carries the fields it needs.
