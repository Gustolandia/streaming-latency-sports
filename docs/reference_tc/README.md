# IEEE Transactions on Computers papers, kept for reference

Downloaded 2026-08-25 (rounds 26–35) to settle questions of house *norm* rather than house
*rule*. The rules are on the Author Information page and are already gated in the test suite;
these answer the different question of what accepted TC papers actually look like.

All fourteen are author versions of accepted or published TC papers, chosen because they are the
closest in kind to ours that are retrievable in full — software-systems and evaluation work
rather than the circuit and accelerator papers that dominate TC's arXiv presence.

| file | arXiv | pages | refs | figures | kind |
|---|---|---|---|---|---|
| `scavenger_plus_TC.pdf` | 2508.13935 | 14 | **45** | 17 | LSM-tree design + evaluation |
| `axi_realm_TC.pdf` | 2501.10161 | 14 | 36 | 13 | hardware traffic regulation |
| `bbreorder_TC.pdf` | — | 11 | 38 | 13 | basic-block reordering |
| `hadar_dlcluster_TC.pdf` | — | 14 | 24 | 20 | DL cluster scheduling |
| `partitioned_bloom_TC.pdf` | 2009.11789 | 11 | 40 | **7** | **a reported statistic is systematically wrong** |
| `ssd_erasure_reliability_TC.pdf` | 2112.12575 | 18* | 74 | 16 | prior evaluations overestimate by 10⁶ |
| `timing_channels_TC.pdf` | 2202.12029 | **11** | 39 | 11 | on-core timing channels, `fence.t`, seL4/RISC-V |
| `lfoc_cache_TC.pdf` | 2402.07693 | 16* | 41 | 13 | OS-level cache clustering, heavy empirical evaluation |
| `brownoutserve_TC.pdf` | 2507.17133 | **12** | 43 | **16** | SLO-aware LLM serving; TC 2026 |
| `gpu_perfmodel_TC.pdf` | 2003.11740 | 16* | 37 | 23 | runtime performance-modelling methodology |
| `oaas_serverless_TC.pdf` | 2408.04898 | **12** | 40 | **13** | serverless object abstraction; TC 2026 |
| `dmrlib_malleability_TC.pdf` | 2604.26624 | 15* | 25 | 10 | job malleability, HPC resource management |
| **`roload_kernel_TC.pdf`** | 2608.13287 | **12** | 25 | **8** | **kernel/bare-metal firmware; our exact configuration** |
| `fedrank_TC.pdf` | 2501.14406 | 14 | 39 | 19 | federated parameter-efficient fine-tuning |

\* **Page count not comparable.** These four are author preprints set in a non-IEEEtran
template; their page counts do not correspond to journal pages and must not be quoted as TC
page counts. The ten unstarred rows are IEEEtran two-column and are comparable.

**Ours: 12 pages, 45 references, 8 figures.**

## What they settle

**Page length.** Of the ten comparable rows, four are 14 pages, three are 11 and three are
12; TC allows
10–12 before mandatory overlength page charges and 14 as the hard maximum, so the 14s are
paying MOPC. Our
12-page target is therefore *stricter than the venue norm*, not looser — a deliberate choice,
and one worth re-examining whenever holding 12 starts costing content. Round 28 held 12 while
adding a figure, and paid for it with about two hundred words of prose moved to the supplement
plus one double-column float converted to single-column.

**Reference count.** Scavenger+ carries exactly 45, the cap. Sitting at the cap, as we do, is
normal and not a sign of padding.

**Figure count.** TC publishes *no* limit, so the standing instruction to sit at "75% of the
image limit" has no denominator here. The observed spread is **7 to 20**. Round 27 read the
first four (13–20) and called our paper figure-light; the six added since correct that
reading in both directions — one accepted TC paper carries **7 figures in 11 pages**, another
**11 in 11**, two carry **16 in 12** and **13 in 12**, and ROLoad-PMP carries **8 in 12** ---
this manuscript's configuration exactly. The question is closed: twelve pages is not what
limits the figure count, and a published TC paper sits precisely where this one does.
Figure count tracks the paper's subject, not a quota. Ours is 8, inside the observed range,
and the binding constraint is the self-imposed 12-page target rather than anything the journal
says.

**Figures need not cost pages.** BB-Reorder fits 13 figures into 11 pages — fewer pages than
ours with more than half again the figures. Round 26 concluded from one layout that adding
content necessarily costs pages; that generalisation is wrong, and the checklist item derived
from it should be read as "find where the slack landed", not "adding content is expensive".

**Related work placement.** Most put Related Work second-to-last, immediately before the
conclusion. Ours is Section II. Both arrangements are common at TC and no referee round has
raised it; recorded here only so the difference is a known choice rather than an oversight.

## What they settle that rounds 26–27 got wrong

The earlier version of this file said, of the first two papers: *"Neither is a
measurement-validity paper, and neither audits an instrument… no comparable paper in the
arXiv-visible sample argues from the same position."* That was true of the sample then held
and is **false of the venue**.

`partitioned_bloom_TC.pdf` argues from our position. The community compares Bloom filter
variants on aggregate false-positive rate; the paper shows the aggregate both understates the
truth and *conceals* the per-element distribution, where "weak spots" are tested as false
positives far more often than the reported mean implies — and that a widespread implementation
shortcut (naive double hashing, present in Guava among others) manufactures those weak spots.
That is our shape: a reported summary statistic is systematically wrong because of a
convention in how it is computed, and the defect is invisible in the aggregate. It differs in
being analytical rather than an empirical audit, and in ending with a design recommendation
rather than a reporting rule.

`ssd_erasure_reliability_TC.pdf` is the second precedent: its headline is that prior models
*"overestimate the SSD array reliability by up to six orders of magnitude"* because earlier
evaluations used deprecated failure data and modelled only a subset of failure types. Same
move — your evaluation method is wrong, here is how wrong — though the flawed instrument is an
analytical model rather than a measurement pipeline.

**Consequence for the paper.** TC demonstrably publishes work whose contribution is that an
established way of measuring something is wrong. The originality claim does not need to rest
on the venue never having published this kind; it rests on nobody having published it for
*latency measurement in streaming benchmarks*, which remains true.

## What they do not settle

None is a pure benchmarking-methodology paper. A full enumeration of TC's arXiv-visible
corpus (~120 unique preprints, cross-checked across four name spellings in both the API and
the advanced-search UI) found no paper whose subject is measurement methodology itself. These
fourteen are therefore useful for form, and the two precedents above for position, but none is a
template for the argument.

`timing_channels_TC.pdf` is the closest in *subject* anyone has found: what preemption and
microarchitectural residue do to timing on a core, in an OS/kernel setting. It audits no
instrument, so it does not compete — but it settles that TC is a natural home for
kernel-timing arguments.

**The corpus is exhausted.** Four rounds of enumeration over TC's arXiv-visible preprints
(~120 unique) have found everything close. Later rounds should re-read these rather than
hunt for more; the marginal paper adds nothing the twelve do not already settle.

## Added round 40 (2026-08-31)

Four more, fetched when the standing instruction to sample the venue was renewed. Recorded
with what each is worth, so the next reviewer does not re-fetch the ones that are not.

| file | arXiv | pages | figures | worth |
|---|---|---|---|---|
| `microarch_cliffs_TC.pdf` | 2602.11580 | 12 | 10 | **the closest format analogue**: 12 pp, 10 figures, 56 refs, and benchmarking methodology as its subject |
| `temporal_observability_TC.pdf` | 2605.17701 | 13 | 0 | **the closest in stance**, and now cited in Section II-B. An external logic-analyser reference reveals timing failures that one internal source hides. No negative values, no quantization, no harness source read -- so it does not compete |
| `microscaling_fp_TC.pdf` | 2510.01863 | 11 | 6 | genuine TC formatting, marked "UNDER REVIEW, 2025". Useful for house norm only |
| `continuum_measurement_TC.pdf` | 2506.22884 | 6 | 1 | **little value.** A position piece, not TC-formatted. Kept so that nobody fetches it a second time |

**What the corpus says about figure counts.** TC publishes no figure limit -- the page count
simply includes them, alongside references capped at 45 and biographies capped at 145 words.
Among the 12-page papers held here the range is 6 to 10 figures, so this manuscript's seven
sits mid-range rather than at a ceiling.

## Added round 42 (2026-08-31)

The sweep was re-run from scratch rather than from round 40's notes, on the reasoning that a
referee who searches from his own summary finds his own summary.

| file | arXiv | worth |
|---|---|---|
| `tailbench_plusplus.pdf` | 2505.03600 | **the strongest corroboration in the corpus.** 14 pp on benchmarking tail latency across clients and servers. Full-text counts: *latency* 86, *tail* 111, *percentile* 10 -- and *timestamp* 0, *clock* 0, *synchron* 0, *skew* 0, *NTP* 0, *PTP* 0, *resolution* 0, *negative* 0, *discard* 0. A dedicated multi-host latency-benchmarking methodology that never names the clock it measures with. Not TC-formatted, so it calibrates nothing about house style; keep it for the premise, not the format |

Three more were assessed and **not** downloaded, so that a later round does not re-fetch them:

- **arXiv:2605.02835**, per-platform GPIO overhead in edge-ML inference timing. Software clock
  against an on-wire hardware reference at sub-millisecond granularity -- but the bias it
  reports is the *cost of the measuring call*, which the manuscript explicitly distinguishes
  itself from and already cites Kuperberg about. Different mechanism.
- **arXiv:2605.24217**, systemic measurement bias in production LLM inference benchmarks. The
  closest in stance found this round, and a second instance of the queueing account the paper
  already refutes on the load axis (Section II-C, Supplement S52.4). No negatives, no
  quantization, no source audit. Noted, deliberately not cited: the reference list is at
  45/45 and the family is engaged.
- **arXiv:2603.21600**, a 2026 broker benchmarking study. The sweep surfaced it
  independently; the supplement already audits it as "mq-bench" in S52.2, with the same
  verbatim clock-synchronization quote. Evidence about the search rather than about the
  paper: an independent re-sweep converged on a source already found and read more carefully.

**What the round-42 sweep says about originality.** Four candidates, one already cited, none
competing, and the two closest in stance close in *stance* while differing in *mechanism*.
That is the pattern of a field beginning to circle the same problem from other directions,
which is corroboration rather than displacement.

## Added round 43 (2026-09-03)

Two more, fetched under the standing instruction to sample the venue, chosen to answer
questions the twenty-two already held could not.

| file | arXiv | pages | worth |
|---|---|---|---|
| `numerical_reproducibility_TC.pdf` | 1312.3300 | 14 | **a third venue precedent for our position, and the closest in kind.** Revol and Theveny, IEEE TC: whether a computed number can be trusted and reproduced, as the subject rather than as a caveat. `partitioned_bloom` and `ssd_erasure_reliability` show TC publishing "your evaluation is wrong"; this one shows it publishing "can you believe the arithmetic at all", which is nearer to what this paper argues. Different domain (interval algorithms), so it does not compete |
| `stateful_prefetch_stream.pdf` | 2603.19890 | 14 | **corroborates the scoping sentence in Section II-A.** Zapridou and Ailamaki, 2026, the most recent low-latency stateful stream-processing paper found. Its SLOs are 50-250 ms and its percentiles sit far above the quantum, so it is outside this paper's regime -- which is exactly what Section II-A says of most of that literature. Its eighteen occurrences of "clock" are all the Clock cache-eviction policy; it never discusses timestamping. Not TC-formatted; keep it for the premise, not the form |

One more was assessed and **not** downloaded, so a later round does not re-fetch it:

- **arXiv:2509.07199**, George et al., *A Study on Messaging Trade-offs in Data Streaming for
  Scientific Workflows* (WORKS 2025). A RabbitMQ/Redis study for latency-critical DOE
  workflows whose full text contains *timestamp* 0, *clock* 0, *skew* 0. Weaker than
  TailBench++ as an exhibit, because it reports throughput rather than latency, so the
  absence of clock discussion costs it less. Noted, not cited.

**What the round-43 sweep says about originality.** Re-run from scratch across arXiv's API
and general search, on the four criteria that have defined the claim in every round. Three
independent query formulations converged on sources the manuscript already cites (Sharma et
al., Chandrasekar and Kramberger, Swami and Chougule), which is what a saturated search looks
like. One genuinely new item surfaced -- TimeWeaver, ITC 2018 -- and it is a *precedent for
our own recommendation* rather than a competitor: it retains negative one-way delays at lower
accuracy tiers instead of discarding them. It is now cited in supplement S39, where the
bibliography is uncapped and nothing is displaced.

**Ours after round 43: 12 pages, 45 references, 5 figures, 2 tables.**

## Added round 44 (2026-09-03)

Two more, and this round used them for a different question. The corpus already settles page
count, reference count and figure count; what it had never been asked is what the venue's
*prose* looks like, which is the thing round 43 spent a day on.

| file | arXiv | pages | worth |
|---|---|---|---|
| `cled_methodology_TC.pdf` | 2403.16393 | 14 | a TC paper whose subtitle is "a New Methodology". Fetched to see what TC accepts when the contribution is a *method* rather than a system, which is this paper's shape. 231-word abstract, 41 references |
| `qutrefoil_TC.pdf` | 2608.14285 | 16 | the most recent TC preprint found. Quantum FPGA simulation, so worthless for content; kept for current house form only |

**What the corpus says about prose, measured the same way on all 25 documents.**

| | pages | abstract | refs | median sentence | mean |
|---|---|---|---|---|---|
| **ours** | **12** | **200** | **45** | **22** | **22.4** |
| corpus range | 6–18 | 147–406 | 13–74 | 18–26 | 21.5–39.2 |
| corpus median | 14 | ~194 | 41 | 20 | 24.2 |

This is what closed an argument that had run for several rounds on feel. Herbst reported that
sentence length ran higher than he would have set it; the main text was at a median of 28
against a venue range of 18–26. It is now 22, inside the range and below the corpus mean. The
gate is `tests/unit/test_sentence_length.py`.

**Two observations worth keeping.** Six papers in the corpus carry abstracts longer than
TC's stated 200-word cap, up to 406 — which suggests the cap is applied at copy-edit rather
than at submission. We stay inside it regardless. And our five figures is the bottom of the
range the 12-page papers show (6–10), a consequence of round 43 moving the payload-flip figure
to the supplement for the page budget; if a page is ever recovered, that is the exhibit to
bring back first.

**Still exhausted for content.** Five rounds of enumeration over TC's arXiv-visible preprints
have found nothing closer than `partitioned_bloom_TC`, `ssd_erasure_reliability_TC` and
`numerical_reproducibility_TC` for position, and `timing_channels_TC` for subject. Later
rounds should re-read these rather than hunt.
