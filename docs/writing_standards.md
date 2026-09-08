# Writing standards for the manuscript

Adopted 2026-09-08 from a co-author's sequential pass on v3.0.0, generalised into rules, and
checked against the field's own usage in a corpus of **775 papers, 616 of them from IEEE
Transactions on Computers** (the rest from the systems-measurement venues the paper cites),
fetched by `scripts/fetch_vocabulary_corpus.py` into `docs/reference_corpus/` (gitignored)
and tabulated by `scripts/build_vocabulary_table.py` into
`docs/generated/corpus_vocabulary.json` (committed). The first draft of this document used
the 45 hand-collected papers in `docs/reference_tc/`; the counts below are from the full
corpus, and where the larger corpus changed a count the text says so. Where a rule says
*the corpus*, that is the evidence. Each rule is written so that a test can hold it; the
ones that are gated say so.

The one-sentence version, which the rest only unpacks: **the paper must be readable in
sequential order, by a stranger, without the supplement, with every non-universal term
defined before it is used, and in the order a new reader needs rather than the order the
work happened in.**

---

## A. Vocabulary: use the field's words, and define the rest before use

### A1. `timestamp`, never `stamp`; `timestamping` for the act — GATED

*timestamp* occurs 2,545 times across 161 papers in the corpus (642 times across 85 of the
journal's own) and *timestamping* 189 times across 28; bare *stamp* (the noun and the verb,
outside *time stamp*) occurs 55 times across 23 papers, so the field says *timestamp* some
forty-six times for every bare *stamp*. (In the 45-paper draft corpus bare *stamp* did not
occur at all.) The manuscript used bare *stamp* 65 times and the supplement 102. It is
colloquial, and the field does not use it for this.

Rule: every *stamp* becomes *timestamp*; every *stamping* becomes *timestamping*; a thread
that *stamps* now *records a timestamp* or *timestamps*. The gate fails on any bare `stamp`
in prose outside code identifiers.

### A2. No `flight` — GATED

In the corpus bare *flight* occurs 131 times across 25 of 775 papers, and a read of every
context shows what it means there: aviation workloads (flight data, flight controllers),
a clock-calibration system named Flight, Lévy flights, pre-flight checks, and time-of-flight
sensors; *in-flight* (requests or packets in flight) accounts for another 86 hits. It never
names a measured interval. Ours was a coinage.

Rule: say what is meant — *send-to-receive latency*, *the measured interval*, *delivery*
(where the quantity is D). If one word is needed for the true duration, use `T_true` only
after defining it (see A7). The gate fails on `\bflight`.

### A3. No `instrument` as the name of the measuring apparatus — GATED

The corpus uses *instrument* almost only as a verb or as *instrumentation* (the act of adding
probes: 132 hits across 54 papers); *the instrument* as a noun occurs 6 times across 5
papers. "The instrument's timescale" is a metaphor the field does not share.

Rule: name the concrete quantity every time: *timestamp resolution*, *timestamping delay*,
*the benchmark tool*, *the measurement mechanism*. The gate fails on `the instrument`,
`instrument timescale`, `an instrument` in prose; `instrumented`/`instrumentation` are fine.

### A4. `guard` is implementation jargon: define once, then say the condition

The corpus has *guard* only as bus guard, guard band, or the verb. Rule: define the thing
once — *the admission condition that keeps a sample only when the millisecond-quantized
difference is strictly positive* — give it a short name at that point if one is needed, and
thereafter prefer the concrete condition ("the > 0 filter") to the jargon.

### A5. Experimental vocabulary is defined once, in the Experimental Setup, and used consistently — GATED

`run`, `replicate`, `cell`, `arm`, `condition` were used as if interchangeable or self-evident.
The corpus: *run* (617 of 775 papers) and *condition* (513) are universal; *replicate*
appears in 99 papers; *cell* has precedent in 133 papers, *per-cell* in 7, and may stay **if
defined**; *arm* in the corpus is overwhelmingly the ARM architecture, and *experimental
arm* occurs in exactly one paper — prefer *configuration* or *treatment*, and if *arm* is
kept, define it. The manuscript now uses *configuration* and never *arm*.

Rule: one paragraph in Experimental Setup defines, in this order and with the containment
made explicit: **condition** (a point in the design), **cell** (a condition × workload), **run**
(one execution of a cell), **replicate** (a repeated run of the same cell). The gate fails if
any of the five appears in the paper before the paragraph that defines it.

### A6. `grid`, `grid vertex`, `quantum`, `commensurate`, `continuum` are defined in plain language before first use

The grid law only becomes understandable in Section IV, yet *arm*, *grid* and *grid vertex*
appear in the abstract and contributions. In the corpus *quantum* means quantum computing
(3,205 hits concentrated in 56 papers); *quantization* (669 hits across 90 papers) is the
field's word for the effect. *timestamp resolution* itself has no corpus precedent (0 hits;
*clock resolution* 3): it is kept because it is plain English and is defined at first use.
Two neighbouring terms are worth knowing: the corpus prefers *scheduling latency* (12
papers) to *scheduling delay* (4); the manuscript keeps *scheduling delay* for the wait
before the timestamping thread runs, because *latency* is already the measured quantity and
the collision would cost more than the precedent buys. It is therefore **defined at its first
use** (gated by `\label{def:scheddelay}`, rule A7), and the TTI term that used to be called
the *scheduling lag* is now the *send lag* — the send call's lateness after the event was
due — so that two different waits no longer share a name. *System model* (98 papers),
*experimental setup* (196) and *threats to validity* (17) are the field's section names and
are the ones used.

Rule: at first mention, in words a reader can hold onto — the **quantum** is the timestamp
resolution; the **grid** is the finite set of phases the timestamp can take when the send
interval is a rational multiple of it; a **vertex** is one of those phases. Prefer *timestamp
resolution* to *quantum* wherever the sentence allows.

### A7. One measurement model, defined once, canonically, early — GATED

D, A, S and TTI are the model. `T_true` must be defined before Fig. 2 and its relation to D
stated precisely, or it goes; Eq. (6) may not reintroduce a quantity the identity S = D − A
already replaced. `C0`, `k`, `ρ` and the load geometry must be defined in the main text
before the table that uses them. A reader never infers a symbol from the supplement.

The gate: every symbol in a `\newcommand`-emitted or typed equation must have a definition
sentence earlier in the document than its first use.

### A8. Mode A / Mode B: either both introduced explicitly before either is used, or descriptive titles

Mode B currently appears before Mode A. Preferred: descriptive section titles —
*Quantisation and silent deletion*; *Scheduling and acknowledgement bias* — and the labels
dropped.

### A9. Acronyms expanded on first use — GATED

*TSC* → *Time Stamp Counter (TSC)*. The gate fails on any all-caps token of three or more
letters whose expansion does not appear earlier.

---

## B. Structure: the order a new reader needs

### B1. The abstract follows the standard shape, with no paper-specific term before the problem is stated

Context → precise problem/gap → objective → method/novelty → main quantitative results →
implication. Any term from section A that the abstract uses must be one the reader can parse
without the paper.

### B2. The introduction is an extended abstract with a little related work

Context, why the measurement problem matters, the problem, the contributions, the paper's
structure. It is not the start of the experimental story. No research chronology, no
withdrawn claims — those go to Method, Threats, or the supplement.

### B3. Contributions in the standard form

*We make three contributions: (1) … (2) … (3) …* — each stated in words already defined.

### B4. Related work is self-contained and argued, not listed

For each strand: what prior work demonstrates → its assumptions and limitations → exactly
what this paper demonstrates differently. Never rely on the supplement to say what the
literature contains or why it matters. A comparator named as "the nearest existing X" gets
one clause on what it does and why it is comparable.

### B5. Method is split conventionally

*System / measurement model* — *Experimental setup* — *Dataset / workload* — *Metrics* —
*Validation / audit* — *Statistics*. One section that mixes all six is where readers lose the
thread.

### B6. The measurement model lives in the text, beside Fig. 1, not only in a caption

Timestamps, D/A/S/TTI, *transport proxy*, and the same-host assumption are defined in a
paragraph the figure illustrates. Fig. 1 labels S *transport proxy*, never *broker
transport*. The proxy-not-chain distinction appears in the introduction or system model,
because everything later depends on it.

### B7. No forward pointer stands in for a definition — GATED

"Section VI-B is the rule list" is not a definition of the rules. State the thing briefly at
first mention; later sections and the supplement carry evidence and detail. The gate fails on
a sentence whose only content is a pointer to a later section or to the supplement.

### B8. Headline results appear in Results, with experiment, denominator and uncertainty — GATED

Nothing quantitative is first revealed in Discussion. The gate: every number in Discussion
or Conclusion must already appear in a Results section or table.

### B9. Definitions, hypotheses, observations and conclusions are distinguishable

A reader must be able to say of any sentence which of the four it is. Where the prose blurs
them, split the sentence.

### B10. The supplement holds only what is not necessary to core understanding

Additional experiments, long derivations, the full audit registry, the research chronology.
The paper is complete without it. The supplement is best cast as a coherent document in its
own right — *a postmortem of how the results were obtained* — rather than as an appendix the
paper leans on. Pointers from the paper into the supplement are for evidence, never for
definitions or for the literature (currently 51 such pointers; each must survive the test
"would the sentence still make sense if the pointer were deleted?").

### B11. Dataset described properly

A reference plus: which events, at what scale, selected how, and why the workload is
representative. A licence line is not a description.

---

## C. Register: a journal paper, not a blog post

### C1. No jokes — GATED

The Houdini line and the Nobel Prize line go. The latter is also wrong: S is a proxy between
unordered events, so S < 0 never means a message arrived before it was sent. The gate holds a
short list of banned phrases and fails on any of them.

### C2. No meta-commentary about the text

"the model that says so is two equations long", "one number that governs both", "the claim"
(when no claim has been stated): remove, or replace with the thing itself.

### C3. Cite plainly

"Sharma et al. [20]" — not "In a 2026 preprint". The reference carries the year and status.

### C4. Say exactly what is done

"then subtracting" → "subtracting the two timestamps to obtain the measured latency".

### C5. Describe the failure precisely, not dramatically

A timestamp is not *untrustworthy*: t_ack may record exactly when the producer observed the
acknowledgement. A negative S is not a *physical-impossibility criterion* and does not *prove
something is wrong*. It proves **the proxy cannot be read as a non-negative delivery
latency** — a diagnostic that the reference is unsuitable, not that either timestamp is
wrong. This wording is used everywhere the negativity is discussed.

### C6. Probability notation only where there is a stochastic model

S = D − A exactly, so *S < 0 iff A > D* is an identity; writing Pr[S < 0] = Pr[A > D] dresses
it as a model. State the equivalence; bring in distributions when a distribution is used.

### C7. The framing of the two failures

Scheduling delay is a distribution; timestamp resolution is a fixed quantum. "The two
failures share one number" overstates the unity. Safer, and true: **both become problematic
when the measured interval approaches the timescales of the measurement mechanism.**

---

## D. Technical points that are conditions, not style

- **Clocks.** CLOCK_MONOTONIC is system-wide and comparable across processes on one host; it
  is not a per-core counter, and it is a different issue from the TSC. The choice of
  CLOCK_REALTIME for the same-host experiments needs its own justification, separate from any
  TSC discussion.
- **The 24% / 4.2× / ~1.7× distortion** is a headline Mode A result and moves to Results
  with its experiment, denominator and uncertainty (B8).
- **Lancet** gets one clause on what it does and why it is the comparator (B4).

---

## E. The artifact record

- One archive per record, distinct names, and the paper archive labelled as such.
- Two PDFs alongside the data zip: `paper-preprint.pdf`, `supplement.pdf`.
- Whether to ship LaTeX sources is the lead author's decision; the risk raised is the paper
  reappearing elsewhere under other names. The standing practice in this project (manuscript
  inside the replication record) was adopted so that any sentence could be checked against
  the data behind it; the PDF alone satisfies that. The `.tex` is what is at issue.
- Supplementary material at IEEE Transactions on Computers is submitted as a **separate file
  with no page limit** (verified against the author guidelines in rounds 51–53 and recorded
  in `docs/reference_tc/README.md`). So the supplement can be submitted; the rule in B10
  about what goes in it stands regardless.

---

## F. How these are enforced

Rules marked GATED get a test in `tests/unit/test_writing_standards.py`, each demonstrated
failing on the sentence that motivated it before that sentence is repaired. The others are
editorial and are checked by reading; the round that applies this document records, per
rule, what changed and what was left and why.
