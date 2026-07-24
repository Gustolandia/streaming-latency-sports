# A model of cross-process latency measurement failure, and the experiments that test it

This document is the design record for the depth experiments (campaign `D`). It states the
model, derives falsifiable rules from it, and specifies the experiment that tests each. It was
written **before** the experiments ran; results go elsewhere.

Motivation: the paper currently *narrates* a measurement failure. TOMPECS asks for work that
"defines, develops, and assesses" a methodology. That means we need a model that predicts when
the failure occurs and how much it biases a comparison — not just a report that it happened to
us.

---

## 1. The model

Broker transport is computed as

```
T_measured = t_recv − t_ack
```

where `t_ack` is read in the **producer** process and `t_recv` in the **consumer** process. Each
timestamp is taken by software some time *after* the physical event it claims to mark, because
the thread that reads the clock must first be scheduled. Write those stamping delays as
`δ_ack` and `δ_recv`. Then

```
T_measured = T_true + (δ_recv − δ_ack)
          = T_true + Δ ,        where Δ ≡ δ_recv − δ_ack
```

An inversion — a negative measured transport — occurs exactly when

```
Δ < −T_true      i.e.    δ_ack − δ_recv > T_true
```

Everything below follows from this one line. Note what it says: **inversion is not a property of
the system under test at all.** It is a race between the true quantity being measured and the
asymmetry of the instrument's own scheduling delay.

### Why δ should follow a queueing law

`δ` is the waiting time of a runnable thread before the scheduler runs it. Treating the CPU as a
server and runnable threads as customers, the Pollaczek–Khinchine result for an M/G/1 queue gives
mean waiting time growing as `ρ / (1 − ρ)` in utilisation `ρ`. We therefore expect `δ` — and
hence the spread of `Δ` — to be small and flat at low utilisation and to grow sharply as `ρ → 1`.
This predicts a **knee**, not a linear ramp.

Chandrasekar and Kramberger \[arXiv:2605.24217] use exactly this M/G/1 framing to explain
client-side measurement bias in LLM inference benchmarks, where a single-process asyncio client
cannot keep up and inflates latency. Our failure is in the same family but differs in one
respect that matters for practice: **their bias is a one-sided inflation that requires a better
instrument to detect, whereas ours violates causality and is therefore detectable from the
measurement itself, with no reference and no ground truth.** That detectability is the property
we build on.

---

## 2. Rule hypotheses

Each is stated so that a single experiment can falsify it.

### H1 — Effect-size rule (the central claim)

> `P(inversion) = P(Δ < −T_true) = F_Δ(−T_true)`, so inversion probability is **monotonically
> decreasing in the true latency being measured.** A benchmark measuring a small quantity is
> more likely to be invalid than one measuring a large quantity **on identical hardware under
> identical load**.

This formalises the property we observed but could not explain: our network-delay arm, where
true transport is tens of seconds, passed the check on every run, while same-hardware arms
measuring ~1 ms failed wholesale.

*Test:* **E-B**. Hold utilisation fixed; use `tc netem` to set `T_true` across
{0.2, 1, 5, 20, 50} ms; measure inversion rate at each. H1 predicts a decreasing curve that
traces `F_Δ`. Falsified if inversion rate is flat in `T_true`.

*Strong form:* the curve should let us **recover `F_Δ`** from inversion rates alone, and that
recovered distribution should match `Δ` measured directly (E-C instrumentation). If it does, we
have an estimator for instrument quality that needs no reference clock.

### H2 — Utilisation rule

> Inversion rate is negligible below a utilisation threshold and rises sharply as `ρ → 1`,
> following the `ρ/(1−ρ)` shape of scheduler waiting time rather than growing linearly.

*Test:* **E-A**. Pin the driver to `K ∈ {1, 2, 4}` cores with `taskset` and add graded
background load, giving a controlled `ρ` axis. Measure inversion rate and bias at each level.
Falsified if the relationship is linear, or if inversions appear at low `ρ`.

### H3 — Asymmetry rule (why it manufactures differences)

> The **mean** of `Δ` is what biases a comparison, and it is non-zero only when the two endpoints
> stamp differently. Symmetric instrumentation yields `E[Δ] ≈ 0` — noise, no systematic bias.
> Asymmetric instrumentation yields `E[Δ] ≠ 0`, and if two systems under comparison have
> *different* asymmetries, the instrument manufactures a difference between them.

This is the hypothesis that explains our original false result. Kafka's producer stamps the
acknowledgement in an **asynchronous callback**; Redis stamps it on **return from a blocking
command**. Different stamping paths, different `E[Δ]`, and therefore a spurious between-system
difference that no amount of statistical care removes.

*Test:* **E-C3**. Add a producer variant that stamps the acknowledgement inline (synchronously)
so both arms are symmetric, and run both variants at the same load. H3 predicts the
between-system difference shrinks toward zero under symmetric stamping while the *noise* does
not. Falsified if the difference persists.

> **Two earlier attempts did not test this.** E-C and E-C2 compared `kafka-python` against
> `confluent-kafka`. **Both of those stamp in a delivery callback**, so the comparison was
> between two *asymmetric* implementations and the symmetric condition was never created. They
> are reported as *untested*, not as evidence either way. The one thing they do establish is a
> side-finding: the gap is stable across two independent client implementations, which argues it
> is a real difference rather than an artefact of one stamping path.
>
> **E-C3** creates the condition properly, using `kafka_producer.py --ack-stamp inline` (added
> for this purpose), which stamps on the *calling thread* the moment the send future resolves —
> structurally what `XADD` does. Both arms run at `--max-inflight 1`, since inline stamping
> requires it and the arms must otherwise be identical. See
> [preregistration_depth.md](preregistration_depth.md) for the amendment recording this before
> the campaign ran.

### H4 — Oversubscription rule

> `ρ` is driven by runnable threads per core, not by offered event rate. At **fixed** aggregate
> event rate, raising the number of concurrent producer/consumer processes raises inversion rate.

*Test:* **E-A2**. Hold aggregate events/second constant while varying feed count `N`
(so per-feed rate falls as `N` rises). Falsified if inversion tracks aggregate rate rather than
process count.

### H5 — Timer-resolution floor

> Where the platform's timer granularity `q` is comparable to `T_true`, quantisation alone
> produces inversions independently of load, placing a floor under the failure rate.

We already have the two-platform contrast: Windows resolves a 1 ms sleep to 15.6 ms, Linux to
1.06 ms. H5 predicts the Windows corpus should fail at lower utilisation than the Linux one for
the same `T_true`, which matches what we observed (62.4% vs 51.9% rejected).

*Test:* **E-D**, re-analysis of existing corpora; no new runs.

### H6 — Mitigation rule

> Removing the asymmetry removes the systematic bias even where noise remains. Same-process
> stamping, or a shared hardware counter (as in Cloudprofiler's TSC calibration), should
> eliminate `E[Δ]` while leaving `Var[Δ]` load-dependent.

*Test:* **E-C3** provides the same-process arm. Falsified if bias persists under symmetric
stamping.

---

## 3. Experiment specifications

| ID | Tests | Manipulation | Holds fixed | Primary outcome |
|---|---|---|---|---|
| **E-A** | H2 | driver cores (`taskset` 1/2/4) × background load (0/25/50/75/95%) | workload, `T_true` | inversion rate, bias vs `ρ` |
| **E-A2** | H4 | feed count `N` at constant aggregate rate | aggregate ev/s | inversion rate vs process count |
| **E-B** | H1 | injected delay 0.2/1/5/20/50 ms (`tc netem`) | `ρ`, workload | inversion rate vs `T_true` |
| **E-C3** | H3, H6 | stamping mode (callback vs inline) × backend | `ρ`, workload | `E[Δ]`, between-system bias |
| **E-D** | H5 | platform (Windows/Linux) | — | re-analysis, no new runs |

**Direct measurement of `Δ`.** E-C also instruments both stamping paths so `δ_ack` and `δ_recv`
can be measured rather than only inferred. This is what turns H1's strong form into a check:
recover `F_Δ` from inversion rates, compare against the measured `Δ`.

**Capacity.** The utilisation axis is obtained by *restricting* cores with `taskset`, not by
adding machines: pinning to one core makes `ρ → 1` reachable with a modest workload and gives a
cleaner sweep than a larger VM would. No additional VMs are required. If E-A2 needs process
counts beyond what four OCPUs can host, a larger driver shape can be provisioned then — but the
design deliberately avoids depending on it.

---

## 4. What each result would mean for the paper

- **H1 confirmed** turns "the check bites hardest where the effect is smallest" from an
  observation into a derived and measured law, with a recoverable `F_Δ`. This is the strongest
  available outcome and would carry the paper.
- **H2 confirmed** gives practitioners an operating rule: below utilisation `ρ*`, cross-process
  latency measurement is sound; above it, it is not.
- **H3 confirmed** explains how an instrument manufactures a difference between two systems, and
  is the direct methodological warning for anyone benchmarking two clients against each other.
- **H6 confirmed** gives the fix, and connects to existing instrument-quality work rather than
  merely criticising practice.

If H1 or H2 is falsified, the paper's central generalisation is wrong and must be withdrawn to a
claim about our own testbed. That outcome is reportable and we will report it.
