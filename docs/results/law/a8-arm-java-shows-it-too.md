# A8 on Arm: the Java client shows it too, four times more weakly

**22 September 2026, Arm pair, campaign `arm_20260921T182140Z`, judged against freeze 14.**
144 runs, 24 setups at 6 rounds, **no run with a problem** in the quality report. This is the
first of A8's two campaigns to finish; the x86 one is running.

**Words used here.** *Negative rate* — the share of messages whose measured trip comes out
impossible, arriving before they were sent. *Plateau* — the level that rate sits at for trips
shorter than the scheduler's slice. *Floor* — the level it falls to past the cliff. *Go-first* —
giving the timestamping helper real-time priority. *p09s, c05h, f15h* — the trip at 0.9 of the
slice (on the plateau), the middle of the cliff, and one and a half cliff-widths past it.

## What it measured

Mean negative rate, 12 runs behind every number:

| trip | client | ordinary | go-first |
|---|---|---|---|
| **p09s** — the plateau | Java | **0.0236** | 0.0001 |
| | Python | **0.1025** | 0.0000 |
| **c05h** — the cliff's middle | Java | 0.0119 | 0.0001 |
| | Python | 0.0643 | 0.0000 |
| **f15h** — past the cliff | Java | 0.0013 | 0.0000 |
| | Python | 0.0311 | 0.0000 |

## P8 is not confirmed on this pair, and the clause that fails is the one about size

P8 asks three things. Two hold and one does not.

**The cliff is there in Java.** Its rate falls 0.0236 → 0.0119 → 0.0013 across the plateau, the
middle and the floor: the middle lies between the other two, in every one of 2000 resamplings.
That is the clause that matters most for what this block exists to ask. **The phenomenon is not
an artifact of our Python client** — Kafka's own official Java client, on the same machine, at
the same trips, shows the same shape.

**Go-first removes it in Java too**, and not marginally. The plan asks for a cut of at least 5
times; on the plateau Java's rate falls from 0.0236 to 0.0001, a cut of about **470 times**, and
Python's falls to zero. (This clause is stated in the plan and is *not* implemented in the judge
— see below. The figures here are computed from the campaign's own runs, not by the rule.)

**The sizes are four times apart.** Python's plateau rate is 0.1025 against Java's 0.0236: a
ratio of **4.33**, 95% interval 4.07 to 4.66, p = 0.0005. The plan allows at most **1.5**. So
P8, which requires all three clauses at the 95% level on each machine pair, is **not confirmed**
on the Arm pair.

That is a result, not a fault. Reported as it stands: the law's shape survives the change of
client, and the law's tolerance for how much the client may matter does not.

## What holds this up

**One matched plateau point.** The ratio is taken at `p09s` alone. Each client is calibrated on
its own, because the delay's effect on the trip belongs to the client (D8-1), so their zero-delay
floors differ and `p05s` was in reach for one and not the other. The runs that were made are
still reported — a trip one client reached is a measurement of that client — but a ratio between
a trip one took and a trip the other never did is not a comparison of clients. So the 4.33 rests
on one trip, with 12 runs of each client behind it.

**One pair.** P8 must hold on each pair, and only one has reported. The x86 campaign is running
and will say whether 4.33 is the Arm machine or the clients.

**The judge does not test the priority clause.** `scripts/law_predictions.py` states in its own
docstring that it tests "the cliff and the priority effect", and its rule string and its code
carry only the cliff and the ratio. The go-first figures above were computed from the runs by
hand. This is the same family as the two faults found on 21 September — a judge that reports on
less than it says it does — and it is listed with them. It does not change this verdict: the
clause it omits is one the campaign passes by a wide margin, so testing it could only have left
P8 not confirmed for the same reason it already is.
