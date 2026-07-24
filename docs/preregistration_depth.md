# Pre-registration: depth suite analysis plan

**Committed before any depth-suite data exists.** The git commit timestamp is the evidence.

The paper's threats-to-validity section concedes that the integrity check's threshold was fixed
before the final campaign but *after* earlier campaigns had run — weaker than pre-registration.
This document removes that weakness for everything that follows. If the analysis below is
changed after seeing the data, the change will be reported as a deviation, with its reason.

---

## 1. Hypotheses and decision rules

Stated as they will be evaluated, with the outcome that would falsify each.

### H1 — effect-size rule

**Prediction:** inversion rate decreases monotonically with the true latency being measured.

**Test:** Spearman rank correlation between injected delay (0, 1, 5, 20, 50 ms) and inversion
rate across E-B conditions.

**Supported if:** ρ < 0 with at least three usable points and no increase exceeding 0.02 between
adjacent levels.

**Falsified if:** ρ ≥ 0, or inversion rate is flat within noise across the range.

**If falsified:** the paper's central generalisation is wrong. The claim that "the check bites
hardest where the effect is smallest" is withdrawn to an observation about our two testbeds, and
Section 6.5 is rewritten accordingly.

### H2 — utilisation rule

**Prediction:** inversion rate follows scheduler waiting time, growing as ρ/(1−ρ) rather than
linearly, producing a knee near saturation.

**Test:** fit both forms to (achieved utilisation, inversion rate) from E-A; compare R².

**Supported if:** R²(M/G/1) > R²(linear) and the rank correlation with utilisation is positive.

**Falsified if:** the linear fit is at least as good, or inversion rate does not rise with
utilisation.

**If falsified:** the queueing framing is dropped. H1 can stand without it, as an empirical
regularity rather than a derived one, and the paper is weaker but intact.

### H3 — asymmetry rule

**Prediction:** the *between-system* difference in mean measured transport shrinks toward zero
under symmetric stamping, while within-system variance does not.

**Test:** E-C, comparing the Kafka–Redis Hodges–Lehmann shift under callback stamping versus
inline stamping at matched load.

**Supported if:** |shift| under inline stamping is smaller than under callback stamping, and the
spread of per-run values is not correspondingly reduced.

**Falsified if:** the shift is unchanged, or both shift and spread fall together (which would
indicate the intervention simply reduced load).

#### Amendment (2026-07-24): E-C and E-C2 did not test this; E-C3 does

Recorded before E-C3 was run, and after E-C2's data was in hand.

Both earlier attempts compared `kafka-python` against `confluent-kafka`. **Both of those clients
stamp the acknowledgement in a delivery callback.** The comparison was therefore between two
*asymmetric* implementations, and the symmetric condition the hypothesis requires was never
created. E-C2's result (gap `+0.396` ms against `+0.452` ms) is reported as *untested*, not as
evidence either way. The one thing it does establish is a side-finding: the gap is stable across
two independent client implementations, which argues it is a real difference rather than an
artefact of one stamping path.

The asymmetry that matters is inside our own harness:

| | where `t_broker_ack_ns` is taken | thread |
|---|---|---|
| `redis_producer.py` | immediately after blocking `XADD` returns | the calling thread |
| `kafka_producer.py` | in the delivery callback | the client's I/O thread |

**E-C3** creates the symmetric condition with `kafka_producer.py --ack-stamp inline`, which
stamps on the calling thread the moment the send future resolves — structurally what `XADD`
does. Two arms, `callback` and `inline`, both at `--max-inflight 1` (inline requires it, so the
callback arm must match or the arms differ in two ways), both against Redis, both under identical
background load. Load is deliberately non-zero: the predicted effect is a thread-scheduling
delay, so an idle machine is the condition least likely to show it.

**Quantity:** `d = median(kafka transport) − median(redis transport)`, per arm.

**Supported if:** `|d_inline| < |d_callback|`.

**Falsified if:** `|d_inline| ≥ |d_callback|`.

**Direction is not assumed.** Inline stamping is symmetric with Redis by construction, but
whether it moves Kafka's stamp earlier or later than the callback depends on when the client's
I/O thread runs callbacks relative to resolving the future. The hypothesis is about the *size*
of the between-system gap, not its sign, and the result is reported whichever way it falls.

**If falsified:** H3 is reported as refuted rather than untested, and the paper's claim that
asymmetric instrumentation manufactures a between-system difference is downgraded to a
mechanism we can motivate but not demonstrate. The other three rules stand independently.

#### Outcome (2026-07-24): SUPPORTED

E-C3 ran both arms against Redis at `--max-inflight 1` under matched background load. Median
broker transport (`docs/results/model/ec3_stamping.csv`):

| Stamp | Kafka | Redis | Difference |
|---|---|---|---|
| `callback` (asymmetric) | 0.392 ms | 0.106 ms | **+0.286 ms** |
| `inline` (symmetric) | 0.322 ms | 0.107 ms | **+0.215 ms** |

`|d_inline| = 0.215 < |d_callback| = 0.286`, a 25% reduction, so **H3 is supported**. The
prediction was specific and it held: the shrinkage is entirely on Kafka's side (0.392 → 0.322 ms)
while Redis is unchanged (0.106 → 0.107 ms), which is what removing the callback-thread
scheduling delay from the Kafka stamp — and only the Kafka stamp — must produce. The `+0.215 ms`
residual is the true between-system transport difference; the extra `+0.071 ms` in the callback
arm was the instrument.

### H4 — oversubscription rule

**Prediction:** at constant aggregate event rate, inversion rate rises with process count.

**Test:** E-A2, Spearman between feed count and inversion rate.

**Falsified if:** inversion tracks aggregate event rate rather than process count.

### Construct check (E-G) — is it skew or scheduling?

**Prediction:** if inversions arise from scheduler delay rather than clock skew, the co-located
condition (both processes on one host, one clock, skew impossible by construction) will show
inversion rates comparable to the distributed condition at matched load.

**Supported if:** co-located inversion rate is within a factor of two of distributed.

**Falsified if:** co-located inversions are near zero while distributed are substantial — which
would mean skew, not scheduling, is the dominant cause, and Sections 4.4 and 6.2 must be
rewritten.

---

## 2. Analysis decisions fixed in advance

- **Primary outcome:** fraction of events with negative broker transport, per run.
- **Utilisation:** measured, not nominal, from `util_sampler.py`. Nominal settings (core count,
  stress workers) are reported as manipulations only.
- **Estimator:** Hodges–Lehmann shift with percentile-bootstrap intervals, consistent with the
  paper.
- **Rejection threshold:** 1% of events in any component, or a negative component median —
  unchanged from the existing check. Sensitivity across 0–20% reported as in Section 6.3.
- **Multiplicity:** H1–H4 are four pre-specified hypotheses tested once each. No correction is
  applied across them because each addresses a distinct claim; this is stated rather than
  corrected for, and per-hypothesis p-values are reported unadjusted.
- **Exclusions:** a condition is excluded only if the campaign failed to produce output (process
  crash, timeout). No exclusion on the basis of results.
- **Minimum data:** any hypothesis with fewer than three usable conditions is reported as
  untested rather than as unsupported.

## 3. What more runs will and will not fix

Recorded here because it governs how the suite is sized.

**More runs fix:** the small-sample threat. E-F raises N=1 from 8 surviving runs per system to
approximately 30, which is the cell where the three equivalence procedures currently disagree.

**More runs do not fix:** the unequal-retention selection effect. Retention *rate* is a property
of the condition, not of the sample size — running more at the same load leaves the same
fraction rejected, just with larger absolute counts. What can fix it is stratification: because
`util_sampler.py` now records achieved utilisation continuously, Kafka and Redis runs can be
compared *matched on utilisation* rather than pooled, and matched analysis needs enough runs to
populate the strata. This is the only sense in which extra runs address that threat, and it is
conditional on the covariate being available.

**More runs cannot fix:** attribution (needs E-G's co-location contrast), external validity
across workloads and libraries (needs different workloads and libraries), or pre-specification
(needs this document).

## 4. Deviations

Any departure from the above will be recorded here, dated, with the reason, before the affected
result is reported.

*(none yet)*
