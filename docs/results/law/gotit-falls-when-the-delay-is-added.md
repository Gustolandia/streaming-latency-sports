# Adding the receiver-only delay lowers the "got it" time, and the brake cannot pass it

**21 September 2026, 04:20 UTC. Read off A8's campaign on the Arm pair
(`arm_20260921T025629Z`) after it stopped itself, 21 runs in.** Not a test of any prediction: it
is the instrument reporting on itself, which is what P5(c) is for.

**Words used here.** *Got-it* — the time from a message being sent to the broker's
acknowledgement reaching the sender. *Receiver-only delay* — extra delay added on the path to the
receiving program, and nowhere else. *The brake* — the rule that stops a session when the delay
appears to have moved the got-it (P5c, tightened by D8-2).

## What the brake said

> STOP_RULE: the got-it median moved −0.252 ms, more than 25% of the 0.886 ms added and more than
> the 0.199 ms this session's got-it moves by itself

## What the campaign's own runs say

Only the runs that take the note the way the calibration took it are compared (freeze 12, D16-1),
so these are the callback runs.

| | campaign got-it, mean | calibration's zero-delay | offset | as a share |
|---|---|---|---|---|
| Java | 0.540 ms | 0.678 ms | **−0.138 ms** | −20.4% |
| Python | 1.315 ms | 1.567 ms | **−0.252 ms** | −16.1% |

Three things follow, and the third is the one that matters.

**It is not an outlier.** The run that stopped the campaign moved −0.252 ms, which is the
campaign's own average to the millisecond. The brake did not catch a bad run; it caught a typical
one.

**It is not noise.** Every callback run of both clients sits below the calibration's zero-delay
value, none above. The campaign's own scatter is larger than the calibration's — 0.091 against
0.048 for Python, 0.034 against 0.008 for Java — but the offset is far larger than either.

**It is proportional, and the brake's allowance is not.** The offset is about a sixth to a fifth
of each client's own got-it, whatever the delay. The brake allows a quarter of the *added delay*.
So at A8's shortest trip the allowance is small and the offset is not:

| | smallest added delay | brake allows | offset | |
|---|---|---|---|---|
| Java | 1.665 ms | 0.416 ms | 0.138 | passes |
| Python | 0.884 ms | 0.221 ms | 0.252 | **stops** |

Python's runs at `p09s` will therefore stop this campaign every time it is run, on this pair, at
this trip. A8 cannot complete as the rule stands. That is a property of the rule meeting a real
effect, not a fault in either.

## Two readings, and this note does not choose between them

**The effect may be real, and P5(c) may be working.** P5(c) exists to ask whether the added delay
leaves the got-it alone. Here it does not: both clients' acknowledgements come back *faster* when
the receiver is delayed, by a similar share of their own time. A mechanism is easy to name — with
the receiver held back, the consumer competes for less of a machine already at 75% load, and the
producer's acknowledging thread is scheduled sooner — and it is the same kind of coupling M0
exists to study. If that is what is happening, the brake is telling the truth and the plan's own
provision applies: analyse the session with each run's own got-it distribution and report the
departure, rather than treat the runs as spoiled.

**Or the comparison is the wrong one.** The brake holds a run *with* delay against a baseline
*without* it, so any effect of the delay on the got-it registers as a fault of the instrument. A
comparison that could separate the two — the same client and note placement across the delays the
campaign itself ran — is available in the campaign's own data and is what freeze 12 already asks
for on the inline runs (D16-2).

Deciding between them is a change to a frozen rule and belongs in a freeze, with this evidence
attached. Nothing here loosens the brake: a rule relaxed because a campaign kept failing it is
not a rule.

## What was kept

Twenty-one runs counted before the stop and are kept with the campaign. The pair was left to
deallocate rather than restarted, because restarting reproduces the stop: the offset is constant
and the allowance at `p09s` is smaller than it.

## What this does not show

One campaign, one pair, one load, 21 runs. The offset is measured against a calibration taken on
the same boot, which is what makes it comparable at all, but it is still a single session. It
says nothing about whether the law holds, and A8's own prediction (P8) is untouched by it — P8
compares the two clients with each other, and both moved the same way.
