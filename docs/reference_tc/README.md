# Six IEEE Transactions on Computers papers, kept for reference

Downloaded 2026-08-25 (rounds 26–28) to settle questions of house *norm* rather than house
*rule*. The rules are on the Author Information page and are already gated in the test suite;
these answer the different question of what accepted TC papers actually look like.

All six are author versions of accepted or published TC papers, chosen because they are the
closest in kind to ours that are retrievable in full — software-systems and evaluation work
rather than the circuit and accelerator papers that dominate TC's arXiv presence.

| file | arXiv | pages | refs | figures | kind |
|---|---|---|---|---|---|
| `scavenger_plus_TC.pdf` | 2508.13935 | 14 | **45** | 17 | LSM-tree design + evaluation |
| `axi_realm_TC.pdf` | 2501.10161 | 14 | 36 | 13 | hardware traffic regulation |
| `bbreorder_TC.pdf` | — | 11 | 38 | 13 | basic-block reordering |
| `hadar_dlcluster_TC.pdf` | — | 14 | 24 | 20 | DL cluster scheduling |
| `partitioned_bloom_TC.pdf` | 2009.11789 | 11 | 40 | **7** | **a reported statistic is systematically wrong** |
| `ssd_erasure_reliability_TC.pdf` | 2112.12575 | 18 | 74 | 16 | prior evaluations overestimate by 10⁶ |

**Ours: 12 pages, 45 references, 8 figures.**

## What they settle

**Page length.** Three of six are 14 pages and one is 18; TC allows 10–12 before mandatory
overlength page charges and 14 as the hard maximum, so those are paying MOPC. Two are 11. Our
12-page target is therefore *stricter than the venue norm*, not looser — a deliberate choice,
and one worth re-examining whenever holding 12 starts costing content. Round 28 held 12 while
adding a figure, and paid for it with about two hundred words of prose moved to the supplement
plus one double-column float converted to single-column.

**Reference count.** Scavenger+ carries exactly 45, the cap. Sitting at the cap, as we do, is
normal and not a sign of padding.

**Figure count.** TC publishes *no* limit, so the standing instruction to sit at "75% of the
image limit" has no denominator here. The observed spread is **7 to 20**. Round 27 read the
first four (13–20) and called our paper figure-light; the two added in round 28 correct that
reading — an accepted TC paper carries **7 figures in 11 pages**, and another carries 16 in 18.
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
six are therefore useful for form, and the two above are useful for precedent, but none is a
template for the argument.
