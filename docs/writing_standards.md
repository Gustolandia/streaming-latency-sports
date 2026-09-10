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

### A1b. The figures obey A1, A3 and A5 too — GATED

Rules A1, A3 and A5 were enforced on the `.tex` sources and on the figures built by two of
the seven figure-building scripts. `scripts/figure_vocabulary.py` runs inside
`make_paper_figures` and `make_result_figures`; `make_deletion_histogram`, `make_e1_figure`,
`make_method_figure`, `make_thread_figure` and `make_window_figure` never called it. The
round-54 image review found the consequence in the exhibit a reader is most likely to look
at first: the deletion histogram titled *"as measured, one clock, nanosecond stamps"*, a
legend reading *"nanosecond stamps"* against *"millisecond stamps"*, a panel titled *"as a
millisecond instrument holds it"*, and the experiment map holding fixed a *"priority arm"*.

Rule: a figure is prose the reader meets first, so its text layer is held to the same
vocabulary. The gate reads the **built PDFs** of every figure either document includes,
rather than the scripts, because that is the only formulation a new script cannot escape.
In a figure the bare word *arm* is banned outright — the prose gate cannot do that, because
the ledger emits macros named `\armSixHundredRate` and the revision history discusses the
retirement, but a figure has neither.

### A1c. A caption opens on its claim, and not on an article --- GATED

Two rules that looked like one problem. A1b makes the figures obey the vocabulary standard;
`test_caption_leads.py` makes every caption open on its *claim* rather than on a label. The
IEEE Editorial Style Manual adds a third: "In general, do not use A, An, or The at the
beginning of a figure or table caption."

Round 57 found 19 of the submission's 46 captions opening on an article, against a venue rate
of 14% measured over 443 captions in 26 TC papers. The cause was the claim rule --- claims
start with "The" --- and the resolution is that both hold at once:

| was | is |
|---|---|
| **The** traced run-queue stall distribution is trimodal. | **Traced run-queue stalls are trimodal.** |
| **A** late timestamp, not an early record. | **Late timestamp, not an early record.** |
| **The** mechanism, by manipulation | **Mechanism, by manipulation** |
| **The** same runs reproduce both published answers. | **One set of runs reproduces both published answers.** |

Rule: the bold lead of every caption in either document states a claim and begins with
something other than `A`, `An` or `The`. Gated by `TestACaptionDoesNotOpenOnAnArticle` in
`tests/unit/test_rendered_prose.py`, which reads the bold lead only --- a caption *body* may
open a sentence however it likes.

### A1d. One multiplication sign, one microsecond, one capital --- GATED

A1b and A1c hold each figure to the manuscript. This one holds the figures to *each*
*other*, which is a reading nothing had done: round 59's triple image review put the
seventeen included figures side by side rather than each beside its own caption, and the
submission turned out to be printing the same things three different ways.

| | was | is |
|---|---|---|
| the multiplication sign | `39x` (Fig. S8, literal), `39 x` (Fig. S7, mathtext), `77x` (Fig. S10, the letter) | `39×` everywhere |
| the microsecond | `µs` (Fig. 3), `us` (Fig. S12) | `µs` |
| panel titles | ten opening on a capital, eight not | a capital, unless the title opens on a count or continues panel (a) |
| the E-A5 arms | blue was `real-time` in Fig. S7 and `ordinary` in Fig. S8 | `ordinary` blue, `real-time` green, in both |

The mathtext row is worth its own sentence, because the cause is not carelessness:
`$39\times$` sets the sign as a *binary operator*, and matplotlib pads binary operators.
With no right operand the padding lands anyway. The two forms are a keystroke apart in
the source and a visible space apart on the page.

Rule: figures print `×` and `µ` as characters, panel titles open on a capital, and a
condition keeps one colour across every figure that draws it. Gated by
`tests/unit/test_figure_typography.py`, which reads the **built figure PDFs** for what a
text layer preserves --- the letter x and the micro sign are characters and survive
extraction --- and the **scripts** for what it does not: mathtext's padding is glyph
positioning, so no extractor can see it.

The same review found Fig. S2(b) drawing grouped bars on a log axis. A bar states its
value as a length measured from zero; a log axis has no zero, so those lengths were
`log(v) - log(floor)` and would all have changed if the limit moved, while no number did.
The panel now draws the segment between the two components, because a distance on a log
axis *is* a ratio, and the ratio is what the panel claims. Gated in the same file.

### A1e. A number states its unit, its denominator and its spread --- GATED

Three habits, one rule, and the second author asked for all three in annotation #42:
*"must be presented in Results with experiment, denominator and uncertainty"*.

| | was | is |
|---|---|---|
| unit | "spread collapses to 13.6 … the pin sits at 69.2" --- two quantities, two units, neither stated | "13.6 points … pins at 69.2% retention" |
| denominator | Table I's caption quoted 8.67% and 8.19% with no per-broker event count | both counts in the caption |
| spread | "understating it 4.2x" | "a median over 70 conditions whose interquartile range runs 4.0--7.5x and reaches 14x" |

The spread row is the one that matters most, because the median flattered: 4.2x sat at the
bottom of its own interquartile range. Section IV-F already promises *"a count over a
**stated** denominator"*; this extends the promise to the two things a bare median hides.

Rule: a measured quantity in either document states what it is measured in, how many
observations it is over, and how widely those observations spread --- unless a neighbouring
sentence has already fixed all three. Gated by `tests/unit/test_round60_findings.py`.

### A1f. The reference cap is on the article --- GATED by arithmetic, not by a test

TC caps the *article* at 45 references. The supplement is a separate file with no page
limit and its own bibliography, which stands at 90. For sixty rounds the budget was
treated as though the two shared it, and the cost was invisible: evidence *about the
literature* --- which is exactly what a supplement is for --- was being weighed against
the article's cap and declined.

Round 61's survey is the worked example. A 2024 paper reviewing 27 stream-processing
benchmarks across five dimensions, one of them *tracked metrics*, says *latency* 33 times
and *timestamp* never. That converts the manuscript's central gap claim from assertion
into measurement, and it cost the article nothing: it went into S52.3, which is already
titled "How large the literature is that misses this".

Rule: a citation whose job is to characterize the literature belongs in the supplement
unless the article's own sentence cannot be made without it. Before proposing that
anything be displaced from the 45, check whether the claim can be made in the document
that has no cap.

### A1g. A claim about what a paper never says is a measurement --- GATED

Two of these are now in the supplement, and both were typed before round 61:
*"over 31 pages the words timestamp, resolution, quantization and retention do not
occur; clock occurs once"*, and the survey sentence above. A count with only one source is
invisible to `test_ledger_coverage`, which catches a literal colliding with an emitted
macro --- lesson 1aq.

Rule: a count of what a cited work does or does not say is derived by
`scripts/literature_census.py`, committed to `docs/results/external/literature_census.csv`
and emitted like any other number. The extracted character count is recorded beside every
term, because a count of zero means nothing if extraction failed and that is the only way
a reader can tell the two apart. Gated by `tests/unit/test_round61_findings.py`.

### A1h. A count stands next to the population it counts --- GATED

Two macros can both be right and only one can belong. `\harnessAuditedWord` is ten, the
tools the audit read; `\harnessSilentWord` is five, the subset that disposes without
counting. Round 62 found the second in the sentence conceding that the tools are source
readings rather than measured deployments --- a limitation that applies to all ten.

Rule: a count macro is used only where the text to its right names what it counts. The
inventory is in `tests/unit/test_round62_findings.py`, keyed by macro, and it is
maintained by hand for the same reason `test_pointer_sense`'s is: deciding whether a
number fits a sentence is not a judgement a regular expression makes alone.

The corollary is a habit rather than a rule. When a sentence is edited into existence out
of two others --- which is how this one arrived --- the macro it inherited was chosen for
the sentence it came from.

### A1i. Every results section is named by a contribution --- GATED

The contribution list is the paper's own account of what it establishes. A section that
carries results and appears in no contribution is either unclaimed work or a section that
should not be one. Round 62 found Section VII in that position, with the abstract naming
its audit as one of three instruments and the contributions naming four other sections.

Rule: sections labelled as structural --- introduction, model, related work, setup,
discussion, conclusion --- need no contribution; every other `\section` must be reachable
by a `\ref` from inside the contribution list. The structural set is written down rather
than inferred, so an exemption is a decision.

### A1j. A withdrawn estimate may not return in another form --- GATED

S15 withdrew the payload sweep's log--log slope because four points do not earn an
equation. Round 63 reintroduced it as a ratio of two response factors, in a paragraph
that said it was using no fit. It was: the ratio of the logs of those two factors is the
exponent, $0.3243$ against the withdrawn $0.3387$, from two points rather than four.

Rule: where an estimate has been withdrawn, no passage may quote a pair of quantities
whose combination reconstructs it. For this one the pair is the transport rise and the
rate fall over the payload sweep, and `tests/unit/test_round62_findings.py` forbids their
co-appearance in the demonstration that relies on the withdrawal.

The general lesson is about gates rather than about this fit. A check written over the
*words* an argument uses cannot see what the argument does; the first version of this one
banned three strings and passed the paragraph that was the fit. Forbid the shape.

### A1k. Say which of the two happened: demoted, or withdrawn --- GATED

The project does both, and they are not the same. A result is **demoted** when its
evidence does not earn the place it had --- four points do not earn an equation in a main
text --- and it keeps its equation, its interval and its figure in the supplement. A claim
is **withdrawn** when it does not hold, and it goes.

Round 64 found the payload-sweep fit described three ways: demoted by S15, which owns it;
withdrawn by the experiment map's E-A10 cell; and withdrawn again by a sentence in S16
written to justify a deletion. Only the first is true.

Rule: no passage may say a demoted result was withdrawn, and a cell too small to carry the
distinction says neither --- "not settled" is what a map column headed by what each
campaign settled can honestly print. Gated by `tests/unit/test_round62_findings.py`,
which also pins S15's heading, because the wording everywhere else depends on it.

The corollary is about reasons rather than words. A deletion made for a wrong reason is
still a deletion, but the wrong reason is printed and a reader will check it. Correct the
reason even when the action stands.

### A1l. An author field names people, or names an organization --- GATED

It may not describe them. Round 64 credited a paper to *"Apache Pulsar enterprise
benchmark authors"*; it has one author, named on its title page, and the entry had been
built from a referee's note rather than from the PDF sitting in the corpus. The BibTeX
key named a third party who has nothing to do with the work.

Rule: every entry's author field is a person's name, a list of them, or the name an
organization publishes under. Phrases of the form "the X authors", "the X team", "various"
or "et al." in the author slot are placeholders whatever their intent, and they typeset.
Legitimate corporate authors are listed by name in the gate, so admitting one is a
decision rather than a hole in a pattern.

The habit behind the rule: **a citation is transcribed from the work's own title page.**
Not from a search result, not from a summary, and not from a referee report --- including
one written inside this project. Where the PDF is held in `docs/reference_tc`, open it.

### A1m. A document's summary of itself is checked against the document --- GATED

Any passage that tells a reader what a document contains --- an orientation paragraph, a
part introduction, an abstract of a structure --- is a claim about the document and is
gated like any other claim. Round 66 found the supplement's opening paragraph describing
the four parts as they had been arranged before v5, sitting directly above a contents page
that disagreed with it, with three of its four descriptions wrong.

Rule: the orientation paragraph names every part by the title that part carries, and the
gate reads both. A summary written once and a document rewritten later drift apart in
silence, because nothing but a test links them.

### A1n. A symbol is set the same way in the figures as in the text --- GATED

The body defines $t_{\mathrm{sched}}$, $t_{\mathrm{send}}$, $t_{\mathrm{ack}}$ and
$t_{\mathrm{recv}}$ with roman subscripts. Figure~2 set the same four italic, and a reader
meets the figure and Equation~1 at the same moment. A5b says a defined symbol means one
thing; this says it has to look like one thing.

Rule: no figure script sets a defined subscript in italic. The gate reads the *scripts*,
not the built PDFs, because the notation is matplotlib mathtext inside Python string
literals and no LaTeX check can see it. Where two toolchains set the same symbol, one gate
reads both.

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

### A5b. A defined symbol means one thing, and A5's rule extends to it — GATED

A5 forbids one word for two things. Round 56 found the manuscript doing it with a symbol,
which is worse, because a symbol carries no context to correct the reader.

Section IV-B defines `\rho` as utilization --- "the fraction of CPU time busy on the host,
measured over the run rather than configured" --- and Section VI-B, Table II and Section VII-D
all hold to it. Section VII-B then wrote "(rho = 0.84)" for the correlation between the
delivery and the acknowledgment lag. The emitter had never been confused: it calls the macro
`spanRhoMedian` and computes it from `rho_DA`. Only the prose was, and only in one place,
three sections after the definition.

Rule: a symbol defined in the Terms paragraph appears nowhere in either document meaning
anything else. Where a second quantity needs naming, name it in words --- "median correlation
0.84" --- rather than borrowing a symbol the reader has already been taught. Gated by
`TestADefinedSymbolKeepsItsOneMeaning` in `tests/unit/test_the_paper_meets_its_own_rules.py`,
which fails on any sentence carrying both `\rho` and a correlation word.

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
