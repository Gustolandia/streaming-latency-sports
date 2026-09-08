# v4: the restructure

Decided 2026-09-08. The second author's sequential pass declined to back a journal
submission of v3.0.0 on presentation: paper-specific vocabulary before definition, the order
the work happened in rather than the order a reader needs, and a main text that leans on its
supplement. The lead author's decision: follow that pass exactly, and redesign rather than
patch. The rules are `docs/writing_standards.md`; the gates are
`tests/unit/test_writing_standards.py` (18 of 20 red on v3.0.0, by design — they are the
record of what the pass caught). This file is the mapping from rules to sections.

**Two invariants that do not move:** every number is still emitted from the ledger and
recomputed at build time; twelve pages, 45 references, four biographies. The science is
unchanged. What changes is the order and the words.

---

## 1. The paper: the standard shape

| new section | what goes in it | from where in v3 |
|---|---|---|
| **Abstract** | context → problem/gap → objective → method → quantitative results → implication; no term from section A of the standards before the problem is stated | rewritten |
| **I. Introduction** | why sub-millisecond latency measurement matters and who depends on it; the problem (two ways a benchmark misreports, stated in the field's words); the objective; *We make three contributions: (1) … (2) … (3) …*; one paragraph on the paper's structure | §I minus the Chronology subsection, minus Fig. 2, minus "one number", minus "the claim" |
| **II. System and Measurement Model** | Fig. 1 beside its text; the five timestamps; D, A, S, TTI defined together; *transport proxy*, not chain — with the append-precedes-both-branches argument; the same-host, one-clock assumption; what a negative S does and does not establish (C5 wording) | §III "at a glance" + "proxy, not a chain" + §III-C's identity, moved up |
| **III. Related Work** | argued: what prior work shows → its limits → what we add, per strand; self-contained; Lancet in one clause; Sharma et al. [20] plainly | §II, rewritten; supplement pointers out |
| **IV. Experimental Setup** | testbeds; the **vocabulary paragraph** (`\label{def:vocabulary}`: condition ⊃ cell ⊃ run, replicate); clocks — CLOCK_REALTIME justified on its own, CLOCK_MONOTONIC and TSC (expanded) as separate points; dataset with a real description; load generation verified | §III-A, split |
| **V. Metrics and Validation** | the admission condition (formerly "guard") defined once; the consistency check; statistics | §III-B, §III-D, §IV-A's guard definition |
| **VI. Quantisation and Silent Deletion** | Mode B, under a descriptive title; grid, vertex, quantum defined in plain words at first use; results | §IV |
| **VII. Scheduling and Acknowledgement Bias** | Mode A, descriptive title; Table I; the two-state model with T_true defined (`def:ttrue`) and related to D; C_0, k, ρ defined before Table II; the **distortion result (24% / 4.2× / 1.7×) moves here** with denominator and uncertainty | §V + the headline lifted out of §VI-B |
| **VIII. Discussion** | what the brokers do; the rules for benchmark authors — none of them first revealing a number | §VI, minus the numbers now in VII |
| **IX. Threats and Limitations** | as now, with the C5 wording | §VI-D |
| **X. Conclusion** | as now | §VII |

Cuts that pay for the definitions: the Chronology subsection (to the supplement's spine),
the Houdini and Nobel sentences, the meta-comments, Fig. 2 if the model paragraph makes it
redundant (decide on the page count), and every pointer whose sentence survives its deletion.

## 2. The vocabulary, in one pass

Mechanical, gated, done first so the restructure is written in the right words:

| v3 | v4 |
|---|---|
| stamp / stamps / stamping (bare) | timestamp / timestamps / timestamping |
| flight | the measured interval; delivery (= D) where that is what is meant; T_true only after `def:ttrue` |
| the instrument, instrument timescale | the benchmark tool; timestamp resolution; timestamping delay; the measurement mechanism |
| guard | the admission condition (defined once); "the > 0 filter" thereafter |
| arm | configuration (or treatment, where a manipulation is meant) |
| cell / run / replicate / condition | kept, defined in IV, used consistently |
| Mode A / Mode B | the descriptive section titles; the labels dropped |
| quantum | timestamp resolution where the sentence allows; *quantum* only after definition |
| physical-impossibility criterion; untrustworthy stamp; proves something is wrong; impossible physics | the C5 wording: the proxy cannot be read as a non-negative delivery latency |
| Pr[S<0] = Pr[A>D] | *S < 0 if and only if A > D*, as an equivalence |

## 3. The supplement: a postmortem

The second author's PS: a single-author document, coherent on its own, *"A postmortem of
…"* — a chronological retelling of how the results were obtained, plus the extra experiments.

Today's supplement is 55 sections, 30 of them titled "(moved from the main text)": an
attic. The recast:

- **Spine:** S35 (*How these results were reached: the chronology, and everything
  withdrawn*) becomes Part I, and the "moved from the main text" sections that narrate —
  S6, S7, S8, S9, S10, S19, S20, S26, S28, S32 — are folded into it in the order the work
  happened, each as a chapter of the story rather than a lift-out.
- **Part II, the experiments in full:** the tables and campaigns the paper summarises —
  S23, S25, S29, S31, S46, S47, S48, S55 — kept as evidence chapters the paper points to.
- **Part III, the audits and derivations:** S36 registry, S41–S44, S51, S53, S54.
- **Part IV, the literature in full:** S18, S33, S37–S40, S50, S52.
- Dropped or merged: S27 (a pointer to S23), S34 (round-1 artifacts), S45 (the metric map,
  now in the paper's §II).

Title: *A Postmortem of a Withdrawn Result: how two failure modes of a streaming benchmark
were found, and what was thrown away on the way*. Single author. The paper's pointers into
it are for evidence only; none is a definition.

## 4. The artifact

At the next deposit: one Zenodo record carrying `paper-preprint.pdf`, `supplement.pdf` and
the data zip; distinct archive names; **no `.tex` in the archive** (the replication object
keeps the manuscript as a PDF, which is what the reader checks sentences against). The code
record's `.zenodo.json` and `scripts/zenodo_deposit.py` change accordingly.

## 5. Order of work

1. Corpus to ≥ 150 papers with the journal itself represented (`fetch_vocabulary_corpus.py`,
   both arXiv stages and OpenAlex); `build_vocabulary_table.py`; commit the table.
2. Vocabulary pass over `paper.tex` and `supplement.tex`, gate by gate, until section A of
   the tests is green.
3. Sections II and IV written (model + setup + vocabulary paragraph + `def:` labels).
4. Abstract and Introduction rewritten; Related Work re-argued.
5. Mode sections retitled; the distortion result moved into VII; register gates green.
6. Page budget: cut until twelve; the supplement absorbs the cuts into the postmortem.
7. Supplement recast.
8. Full suite green; a referee-style pass against the standards document; commit; the
   co-authors get the version with a change list keyed to the 42 comments.
