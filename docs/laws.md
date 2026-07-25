# What the measurements support

The state of the mechanism after E-A3 through E-A10, the OMB replication, and the campaigns that
preceded them. This supersedes the load-axis parts of [two_state_model.md](two_state_model.md),
which were written before the manipulations that decided them.

Every entry says what would falsify it and what is still open. The failures are listed with the
successes because several of them are more informative.

---

## The mechanism

```
P(inversion)  =  P( scheduling stall > T_true )
```

An inversion is recorded when measured transport is negative: the consumer's receipt stamp
precedes the broker's acknowledgement stamp. Both stamps are taken on the same host, so no
cross-host clock offset is involved. What produces one is a stall between the event becoming
ready and the thread reading the clock, longer than the interval being measured.

Both sides of that inequality have now been manipulated independently, which is the reason it is
stated as a mechanism rather than a correlation.

---

## Established

### The rate follows scheduling, not utilisation

Raising the stamping threads to `SCHED_FIFO` at **fixed** utilisation collapses the inversion
rate. Five campaigns, utilisation matched to 0.003 or better in every cell:

| load | ρ ordinary | ρ real-time | ordinary | real-time | fall |
|---|---|---|---|---|---|
| 60% | 0.6055 | 0.6035 | 0.0459 | 0.0017 | 28× |
| 70% | 0.7032 | 0.7025 | 0.1032 | 0.0144 | 7× |
| 75% | 0.7531 | 0.7525 | 0.1320 | 0.0034 | 39× |
| 88% | 0.8809 | 0.8812 | 0.2214 | 0.0034 | 66× |
| 95% | 0.9501 | 0.9501 | 0.2938 | 0.0037 | 76× |

*Falsified by:* the rate not moving when only priority changes. It moved every time.

*Baseline variation is real and reported:* the 88% ordinary arm ranges 0.221–0.305 across four
campaigns. The **effect** reproduces; the **level** drifts day to day.

### L3 — utilisation does not determine the rate; core availability does

E-A6 ran both load geometries in one campaign at matched utilisation.

| k/8 | ρ concentrated | ρ spread | concentrated | spread | ratio |
|---|---|---|---|---|---|
| 5 | 0.6284 | 0.6250 | 0.0201 | 0.0379 | 1.88× |
| 6 | **0.7531** | **0.7531** | 0.0824 | 0.1709 | **2.07×** |
| 7 | 0.8778 | 0.8809 | 0.2281 | 0.2415 | 1.06× |

At k=6 the utilisation is identical to four decimals and the rates differ twofold. A function of
ρ returns one value for one input, so ρ cannot be the variable. Spread load (every core
duty-cycled, none free) starves the stamping thread more than concentrated load (k cores flat
out, C−k genuinely free); the two converge at k=7, where one free core out of eight is nearly as
useless as none — which is the mechanism showing itself, not a weaker result.

*Falsified by:* the geometries agreeing at every level. They agreed only where predicted.

### T_true dependence, on the sign nothing else predicts

E-A10 padded the payload, lengthening true transport without touching the scheduler.

| pad (B) | ρ | transport | inversion |
|---|---|---|---|
| 0 | 0.8809 | 0.701 ms | 0.2603 |
| 4 096 | 0.8822 | 2.381 ms | 0.1906 |
| 65 536 | 0.8847 | 14.638 ms | 0.0888 |
| 262 144 | 0.8930 | 53.898 ms | 0.0637 |

Transport rose 76.9×, the rate fell 4.1×, monotone in both, intervals disjoint, ρ held to a 0.012
spread. **A slower path is a more reliable measurement.** Any account in which inversions track
system stress predicts the opposite, since larger payloads are strictly more work — and the
serialisation confound pushes ρ *up*, against the result.

*Falsified by:* the rate rising, or not moving, as T_true grew.

### The traced tail predicts the rate

E-A9 traced `sched_wakeup`/`sched_switch` and computed P(run-queue delay > T_true) directly.

| arm | traced events | P(stall > 0.5 ms) | inversion rate | ratio |
|---|---|---|---|---|
| ordinary | 551,956 | 0.1807 | 0.2315 | **0.78** |
| real-time | 570,591 | 0.0185 | 0.0000 | — |

A traced scheduler quantity predicts the measured inversion rate to within 30%, unfitted. The
instrument check passed first: the traced baseline differs from the untraced measurement of the
same cell by 4.6%, so BPF did not move what it measured.

*Open:* the real-time arm recorded exactly zero inversions. Under the usual floor (~0.004) the
chance of that in 2985 events is 6.4 × 10⁻⁶, so either that arm genuinely differed or tracing
affected it — and the instrument check covered only the ordinary arm. The traced tail did fall
9.8×, so the direction holds; the level in that arm does not.

### The distribution is extraordinarily heavy-tailed

A 77× increase in threshold (E-A10) bought only a 4.1× reduction in rate, and P(stall > 0.5 ms)
is 0.18 (E-A9). **Inversions come from rare, very long stalls, not typical ones.** This is why
mean-based counters could not account for the effect, and it was predicted from E-A10 before
E-A9 measured it.

### L1 — the real-time floor is the idle rate

Loaded at real-time priority: 0.0049. Unloaded at ordinary priority: 0.0035. Ratio 1.38. Two
unrelated experiments agree: load with a runnable stamping thread looks like no load at all.

### L2 — the ceiling is physical

The rate saturates at 0.37, not near 1, and three campaigns reaching saturation agree to within
1.11×. Under `P = p·S` with `p` a probability, that ceiling estimates `S` — a measured quantity
rather than a fitted asymptote.

### The exposure is not ours alone

The instrumented OpenMessaging Benchmark discarded **6,000** end-to-end samples (~6.7%) in three
minutes at 500 msg/s under 88% load, with no counter and a healthy-looking latency summary.

---

## Withdrawn or failed

**The M/G/1 functional form.** With points at ρ = 0.881–0.990, where the candidates diverge,
M/G/1 fits *worse than the mean* (R² −0.05 against a fitted exponential's 0.93). Not merely
unsupported: separated and ruled out.

**Our own bounded load-axis prediction.** Registered 2.45–3.07× over ρ 0.881→0.990; observed
1.44×. Being nearer than M/G/1's 13.8× does not make it a hit.

**Occupancy as the quantitative explanation.** Measured occupancy moves ~2× and mean stall length
3–5× against a 40× change in rate. Both are means; the effect lives in the tail. The *direction*
survives, the *magnitude* does not.

**H1's intermediate effect-size points.** netem at the broker delays the acknowledgement and
delivery paths equally and cancels in the difference. The sweep never manipulated what it claimed
to.

**Co-location as a T_true manipulation.** Removing the network hop made transport *longer*
(0.512 → 0.573 ms): it traded network latency for CPU contention. Two of three attempts on this
axis failed for structurally similar reasons, which is itself a reportable property — this
quantity resists manipulation because every route to shortening it lengthens something else.

---

## Still open

- **What sets the level.** The mechanism predicts the rate to within 30% in one arm. There is no
  formula for the rate at a given load, and two attempts to write one have failed.
- **The real-time arm's zero** (above) needs an untraced control before its level is trusted.
- **Distributed OMB.** Five attempts, five distinct faults in the benchmark's worker protocol.
  The cross-host clock channel is bounded independently at ~0.067 ms — below OMB's millisecond
  resolution — so the untested channel is the one least able to matter here.
