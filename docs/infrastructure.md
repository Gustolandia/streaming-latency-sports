# Infrastructure & Reproducibility (Issue 6)

> **Status: this describes Testbed A, whose results the paper withdraws in full.** The hardware
> in §3 is the single Windows host every S-era run was produced on, and the paper's audit rejects
> that entire arm (§7 "What we withdraw"). Every result the paper *reports* comes from Testbed B
> — four Oracle Cloud VMs on a real inter-VM network — which is documented in
> [`cloud/README.md`](../cloud/README.md), not here. The software stack in §1 and the
> reproducibility chain in §4 still apply to both; the host in §3 does not.

This document specifies the software environment and the reproducibility chain
for the benchmark suite. It complements the per-run provenance recorded in every
`runs/<run_id>/meta.json` and the automated checker
`scripts/verify_reproducibility.py`.

> Hardware note: host hardware is not auto-captured in `meta.json`; the values in §3
> below were measured on the benchmarking host (June 17 2026). All runs in the corrected
> corpus were produced on this single machine.

---

## 1. Software stack

| Component | Version | Source |
|-----------|---------|--------|
| Apache Kafka | 4.1.1 (KRaft mode) | `apache/kafka:4.1.1` (see `docker-compose*.yml`) |
| Redis | 7.2.4 | `redis:7.2.4` (see `docker-compose-redis-cluster.yml`) |
| Python | 3.9.13 | local interpreter |
| Docker | 29.5.3 (Docker Desktop) | host |
| OS | Windows 11 Home (build 26200) | host |
| Python deps | pinned | `requirements.txt` |

## 2. Deployment topologies

| Config | Kafka | Redis |
|--------|-------|-------|
| Single | 1 broker, `localhost:19092` (`docker-compose.yml`) | 1 node, `localhost:16379`, no persistence |
| Cluster | 3 brokers, KRaft, RF=3, ports 9092/9093/9094 (`docker-compose-multibroker.yml`) | 3 nodes, cluster mode, AOF `everysec`, ports 7000–7002 (`docker-compose-redis-cluster.yml`) |

The single and cluster stacks use disjoint host ports, so they run concurrently.

## 3. Host hardware (measured, June 17 2026)

| Property | Value |
|----------|-------|
| CPU | AMD Ryzen 9 6900HX, 8 cores / 16 threads @ 3.3 GHz |
| RAM | 31.2 GB |
| OS | Windows 11 Home, build 26200 |
| Docker resources | 16 vCPUs, 15.2 GB memory allocated to Docker Desktop |
| Storage | local SSD |

## 4. Reproducibility chain (the "no-guessing" principle)

```
Paper number → committed CSV → build/analysis script → canonical run list
            → run directory → meta.json (git SHA + code SHA-256 + config + env)
```

Every run directory contains:

| File | Provenance role |
|------|-----------------|
| `meta.json` | git `head`, per-file `code_sha256`, env capture, topic/stream, config |
| `producer.csv` / `consumer.csv` | raw emit / receive timestamps |
| `tti_summary.json` | computed TTI metrics + `missed_window_rate` |
| `producer.log` / `consumer.log` | process logs |

**Automated verification:**

```bash
python scripts/verify_reproducibility.py --pattern 'batch*' --verbose   # provenance chain
python verify_all_runs.py --pattern 'batch*'                            # file completeness
python deep_health_check_final.py --pattern 'batch*'                    # deep integrity
```

As of the 120-run multi-broker matrix (batches 1–3), all 120 runs pass the
provenance check (`120/120 runs fully reproducible`).

## 5. Reproducing the corrected corpus and analysis

The full, current step-by-step procedure (infra bring-up, the corrected
`regenerate_corpus.ps1` / `run_persistence.ps1` / `run_s3_corrected.ps1` orchestrators, the
concurrency runs, and all analyses) lives in
[reproducibility/README.md](../reproducibility/README.md), with the exact pinned commit and
per-file code checksums in `reproducibility/MANIFEST.json`.

Analyses run on existing `runs/` without Docker, e.g.:

```bash
python scripts/statistical_analysis.py      --pattern 'batch9_20260617_*'
python scripts/analyze_protocol_overhead.py --pattern 'batch9_20260617_*'
python scripts/analyze_actionability.py     --pattern 'batch9_20260617_*'
python scripts/power_analysis.py --n 15
```

## 6. Permanent archive (Zenodo) — checklist

- [ ] Fill in §3 host hardware.
- [ ] Freeze the branch and tag a release.
- [ ] Bundle: `scripts/`, `tests/`, `configs/`, `docker-compose*.yml`,
      `requirements.txt`, `runs/` (or a documented subset), `data/processed/`,
      `paper.tex` + assets, this `docs/` tree.
- [ ] Upload to Zenodo, mint a DOI, add the DOI badge to `README.md`.


## Release checklist

The suite covers everything that can be decided by reading a file. Seven things cannot, and
each has cost a referee round, so they are written down rather than remembered.

TC's own limits, for reference, from the journal's author page: a regular paper is **10-12
double-column pages** before mandatory overlength page charges, hard-capped at 14 with them
and 16 with the editor's prior approval; **45 references**; **145 words** of biography per
author. Page counts include text and figures. **There is no limit on the number of figures**
-- they are constrained only by the pages they consume, and by having to be "reasonably sized
(readable)". Supplemental files have no page limit at all, which is the whole argument for
moving anything that will fit there.

**1. Look at every figure, at the size it prints.** Rasterise the figure directory to a contact
sheet and read it. Four defects reached referees this way, none visible to any gate at the
time, because all were layout rather than content:

- Figure 5(b): the `32 KB` label was struck through by the half-cell rule (round 12).
- `window_sweep`: `set_xticks` replaces a log axis's *major* ticks and leaves the minor decade
  formatter running, so "180" printed underneath "2 x 10^2" on both panels (round 13).
- Figure 2(b): the density curve was drawn through a two-line annotation, and Figure 8's
  leader arrow through the `10.5%` label above its own bar (round 15).
- Figures 4 and 6: a data point at zero drawn centred on the spine, clipped to half a
  marker, which reads as a rendering fault rather than as data (round 15).

Font, Type 3, family and text-layer gates passed all of them: they ask which font and which
glyph, and a collision is a fact about geometry.

`scripts/figure_collisions.py` now gates that geometry, from inside the `_save` of every
figure script, so a figure added later is covered without anyone remembering to add it. It
makes three checks, each pinned by a defect that got past the eye or past the gates:

- *text struck by ink* -- the figure is rasterised with the glyphs painted transparent, and
  any dark ink inside a label's core is ink the reader must read through;
- *labels printed over each other* -- round 13's defect, which no ink check can see because
  neither label is struck by anything drawn;
- *markers clipped by a spine* -- a question about points and pixels that the data cannot
  answer.

Run `python scripts/show_figure_collisions.py` when it fails: it writes the ink-only raster
with the flagged labels outlined, which is the picture the gate saw.

**The eye is still on the list.** The gate found three collisions the visual pass missed --
the grid lines through `1/3`, `2/3` and `3/3` -- and the visual pass is what found the two the
gate was then written from. They fail differently: the gate cannot tell whether a figure is
*right*, only whether it is legible.

**1b. Ask whether the data can be seen, not whether the type can be read.** Round 19: a
co-author could "hardly read" Figure 5 on a 37-inch monitor. Every gate passed it. The type
printed at exactly 8 pt, nothing was struck by ink, nothing was clipped, and the vocabulary
was current -- and the figure was still unreadable, because ten rows of categorical labels
("Geometry, replication, concentrated") take about an inch and a half whatever the panel is,
so in a 3.50 in column the intervals the figure exists to show were drawn in the 1.7 in left
over.

The gates measure the type. Nobody measures the fraction of the panel the type occupies, and
that fraction is what legibility actually is. The fix was width: at `\textwidth` the label
column costs the same inch and a half and the data gets five inches. The general rule is
cheaper than a new gate -- **when a figure's labels are long, check what share of the panel
is left for the data before checking the point size** -- and the round's own visual pass,
made only after the co-author's mail, then found two more in the same sitting:

- The stall spectrum's "1 ms tick" printed as "ms tick". The label is rotated and anchored at
  `y = 0`, and matplotlib's default rotation mode aligns the box and *then* swings it about
  the anchor, which put the first glyph below the axis where the frame clipped it. Any
  rotated label anchored on a spine is a candidate; `rotation_mode="anchor"` is the fix.
- The same rule was drawn through the centre of the 512 bucket, which reads as "1 ms is at
  512 us". The bucket spans [512, 1024) and 1 ms sits at its top edge. A categorical axis
  invites this: the bar has an index, the value does not, and drawing the value at the index
  is wrong by up to half a bucket.
- Figure 6 carried an arrowhead with no tail, resting on a data point. The annotation
  describes a slope through all four points, and its text box had drifted close enough to the
  second one that only the head was drawn. **An arrowhead is ink, not text**, so the collision
  gate has nothing to say about it unless it happens to cover a glyph, and it covered none.

**1d. Ask the question the check does not ask.** Round 19's lesson was that the gates measure
type size and nobody measures how much of the panel the type occupies. Round 20 is the same
shape twice more, and both came from a referee reading a rendered page:

- **A long line through a label.** `text_struck_by_ink` insets a label to its *core*, on
  purpose, so a gridline grazing a descender does not fail a figure. One glyph out of sixteen
  is a few per cent of that core, which is why the diagonal of Figure 3 struck the last letter
  of its own label through *two* attempted moves and two rounds of review. The answer was not
  a wider band --- round 17 was right that chasing the last percent produces false alarms ---
  but a different question: does a line long enough to be a reference line cross a label's
  **full** extent? `reference_lines_through_text` asks it, and found two more defects on its
  first run, in a figure nobody had opened: a series drawn under a legend at matplotlib's
  default `framealpha` of 0.8, and a dotted reference through a two-line callout.

- **A label's background erasing what is drawn.** The inverse, and the one the last two rounds
  made likely: an opaque patch behind a label is the standard fix for a rule crossing a
  number, and it is used freely here. Anchor one on the axis limit and the patch paints over
  the spine; Figure 5's factor column printed the right frame with four gaps in it, visible at
  400 dpi and invisible to every check that asks about ink landing on text.
  `label_patches_over_spines` asks the reverse and found all four.

**The general rule, since a third instance of this is likely:** when a device is adopted to
fix one class of defect --- an inset, an opaque patch, a zorder --- ask what the device itself
can break, and measure that too.

**1e. A check that reports clean must be able to prove it looked.** This is Section IV of the
manuscript turned on the manuscript's own tooling, and round 21 found it: a guard that drops
samples and records no count cannot be told from a guard that never fires, and neither can a
check that reports no collisions be told from a check that measured nothing.

`reference_lines_through_text` reported clean on every shipped figure for a whole round. It
was not clean; it was blind, twice over. It transformed every `Line2D` with `ax.transData`,
but `axhline` and `axvline` carry a **blended** transform --- data in one axis,
axes-fraction in the other --- so an `axvline`'s coordinates are `[[x, 0], [x, 1]]` and
`transData` measured 4.8 px of a rule 135 px long. And it qualified a line at half the axes
*diagonal*, which on a 282 x 135 px panel is 156 px: a rule spanning the entire height is
disqualified by geometry before anything else is asked. Meanwhile Figure 7's tick rule was
printed through the second line of its own callout.

Two things came out of it, and the second matters more than the first:

- The check uses `line.get_transform()` and qualifies against each axis separately --- width
  for a horizontal run, height for a vertical one.
- **Every check now counts the candidates it examined**, and `report()` returns those counts
  beside the verdicts. A test asserts, *per figure*, that the reference-line check saw the
  rule that figure carries, against a written list of which figures carry one and what draws
  it; and that each other check saw something on a figure that certainly contains its
  subject.

Per figure, not summed. The first version of that test summed the counts over five figures
and passed under the very bug it was written for, because the grid's `y = x` is an ordinary
data-space line and kept the total up by itself. **An aggregate is where a blind instrument
hides.** That is the same sentence as Section IV's, about a different instrument.

**1g. A framed legend must be opaque.** Twice in two rounds a data series was visible through
a legend at matplotlib's default `framealpha` of 0.8 -- `network_delay` in round 20,
`window_sweep` in round 22, where the emitted series and its first marker showed as pale
ghosts behind the entries. `translucent_legends` now reports any legend drawn with a frame
that is not opaque. The rule is unconditional rather than conditional on something passing
underneath, because the conditional form already exists and already failed: a line can cross
a legend's handle column and the gap before its text without touching a glyph box, so the
reference-line check sees nothing. A figure that wants to see through its legend says
`frameon=False`, and then its text is policed like any other label.

Both fixes have a second half worth remembering: making a legend opaque in place hid a data
point in both figures, so the legend has to move as well. Opaque and in the wrong place is not
better than translucent.

**1f. Move the pointer with the content.** Round 20 lifted two passages into new supplement
sections and left both pointers on the sections the content had left, so Section IV-C cited
S46 for a construction S46 does not contain. Every pointer still resolved, which is what the
existing check asks. What it did not ask was whether the new sections could be reached at
all. `TestEveryTargetedRelocationIsReachable` now requires every section from S45 onward ---
the range where relocation became targeted rather than bulk --- to be pointed at from the
paper. A relocation without a pointer is a deletion with extra steps.

**1h. Sweep the places that have never failed.** Every check in this project was written in
response to a defect, so the apparatus is excellent in the neighbourhood of its last failure
and knows nothing about ground that has never moved. Round 23 found four numbers in
`paper.tex` --- the geometry factor, its `z`, and the replication factor, one of them in
Contribution 2 --- typed out as literals a few centimetres from a table that renders the same
three quantities through their macros. They had been outside the ledger since the ledger
existed. Twenty-two rounds of increasingly sophisticated checking walked past them because the
search always followed the last repair, and no repair had ever touched them.

`tests/unit/test_ledger_coverage.py` asks the question no defect prompted: *which quantities
in this document have a machine-readable source, and are they all reading from it?* It scans
both documents for literals duplicating a macro that document already uses, masking tabular
bodies, `\input`ed files and comments, and ignoring a positive value where a minus sign
precedes it. On the main text it needs no exemptions and a pin says so, because the honest
response to a hit there is to fix the number. On the supplement it carries five, each a
genuine coincidence with a written reason -- a utilization that equals an R-squared, a factor
that equals a tail index.

**The general habit:** when a gate is added, it answers a question someone already knew to
ask. Once a year, ask one nobody asked.

**1i. Some phrases keep dying.** "both of which" has now been deleted by three separate
compression passes --- rounds 19, 20 and 24 --- because it reads as filler. It is the only
thing telling a reader that `\clockAdmitted` names two clocksources rather than one, and a
round-12 referee asked for it. When a content pin fires on the same phrase a third time, the
phrase is not the problem: stop compressing that sentence.

**1c. Compression is where content pins die.** Round 19 cut about nine hundred words to hold
twelve pages while adding a co-author's five requests, and five gates fired on the cuts --
each one a decision some earlier round had fought for: the excluded-phase disclosure a
referee asked for, a plural antecedent for two clocksources, the shared-endpoint contrast
that is the only trace of an abandoned argument, an American spelling, and the retired word
"inversion", which a new paragraph put straight back and thereby disarmed the vocabulary gate
for the figures too. The shortest way to say a thing is almost never the way that carries the
qualification. **Run the consistency suite after a compression pass, not only after a content
pass.** Round 20 proved the point twice over: compressing one paragraph removed the
tracepoint names and the observer-effect numbers that a round-16 referee had asked to be put
in the paper, and the gate holding them caught it within the hour.

**2. Measure the type size a reader actually gets.** Round 16 found every figure in the paper
printing below IEEE's minimum, one of them at 2.7 pt against 9.5 pt body text. The cause was
arithmetic split across two files that never met: the figure script sets the point size and
knows nothing about the include width, the manuscript sets the include width and knows nothing
about the point size, and 0.82\columnwidth on a figure drawn seven inches wide is a 59%
reduction nobody wrote down.

`scripts/figure_legibility.py` closes that gap. It parses the `\includegraphics` directives
out of both documents, so a figure moved between a column and a full-width float is measured
where it actually lands, and it fails anything below 8 pt. The rule that follows from it:
**draw every figure at the width it will print at.** Then authored size is printed size and
there is no arithmetic to get wrong.

Two things learned the hard way while fixing it, both worth not rediscovering:

- `\columnwidth` is **not** redefined inside `figure*`. A figure drawn at 7.16 in and included
  at `\columnwidth` in a starred float still comes out 3.37 in wide. Use `\textwidth`.
- The collision gate's core band was the middle 58% by height and 88% by width. Cap height
  begins inside 58%, so an axes frame drawn through the tops of the letters was outside the
  band; and a frame touching the last glyph was outside the 88%. Both are now 72% and 96%,
  and the case the insets exist for -- a rule flanked by a label above and below -- is still
  pinned as passing.

**3. Read the reference list as a copy editor would.** Round 14 was the first time anyone did,
and it found three defects in a list that is otherwise scrupulous: one entry printing its URL
twice, two venues unabbreviated among forty-three that were not, and the arXiv entries split
across two conventions. `TestReferenceHouseStyle` now catches those classes, and since round 16 also catches an
author outside IEEE initials-and-surname form -- entry [40] read "zihan zhou" through two
rounds spent reading this list, because the gate had never looked at a name. It still does not
catch a mis-spelled author or a wrong page range.

**4. Ask of every printed number: could a stranger find the file?**

Not "does it reproduce" -- they all do -- but whether a reader who starts at the claim can
reach the artifact without knowing where things are kept. Two rounds running found a headline
that failed that test while passing every other one.

- Round 16: the audit rate, 1,321 of 2,266. A referee following the only path he could find
  checked it against the campaign inventory rather than the audit's own outputs and published
  a wrong finding. The number was right; the path was not there.
- Round 17: the real-time collapse range, 7--80x. A test had recomputed it from all three
  campaign files since round 2 and would have caught a drift, but six of its eight matched
  pairs appeared in neither document, so a reader could not see the evidence even though the
  build could.

The pattern is not carelessness and it will recur: **a number gets emitted when someone has
had to recompute it, and the ones that never needed recomputing are the ones that stay typed.**
`test_no_gated_headline_is_also_typed` holds the list; extend it when the next one turns up.

**5. Do not let a coverage number be bought.**

The standard is 100% branch coverage across `scripts/`, and CI fails below it. That figure is
only worth stating because what may be excluded from it is itself gated, by
`tests/unit/test_coverage_exclusions.py`: a `__main__` guard may hide only calls and imports,
at most four statements, and every other `# pragma: no cover` needs a written reason and an
entry in that file's inventory. 100% earned by exclusion would be worse than an honest 95%,
because the number stops being a question anyone asks.

Raising it from 95% was not bookkeeping. It found, among others:

- `show_figure_collisions` replaced `_save` on two other modules and never put it back, so any
  figure built later in the same process was silently not saved -- the leak class this project
  has already lost a round to.
- `check_concurrency_health` divided by zero whenever `--run-prefix` selected directories that
  group into no test suite, which is an ordinary invocation.
- `compare_plans` wrote its gap table from an empty list, producing a zero-byte file that
  pandas refuses to parse -- while the neighbouring table deliberately wrote a header for
  exactly that reason.
- `check_fork_exposure._fetch` returned `None` on `tries=0` into a caller that calls
  `.startswith` on the result.
- Seven guards that could not be reached from any caller. Those were deleted rather than
  excluded: dead code in a numerical routine reads as a case someone thought about.
- Two scripts with a report loop parked under a pragma'd `__main__` guard -- found by the
  exclusion gate on its first run, which is the argument for having it.

**The lesson generalises the one above it.** A branch nothing exercises is a claim nothing
checks. Most of the 220 uncovered branches were the *rejecting* side of a filter -- the row
that will not parse, the run that yielded nothing, the campaign that is absent -- and those
are precisely the paths that decide what the corpus contains. A reader who cannot see them
tested has to take the corpus on trust.

**6. When you rename something, the figures do not rename themselves.**

Round 18 renamed the central quantity from "inversion" to "negative span". The rename ran over
`paper.tex` and `supplement.tex`, which is where prose lives, and four axis labels went on
saying "inversion rate" because a generated figure carries its label in a Python string. On
page 8 the two names appeared within centimetres of each other, for the same number, in the
same figure.

Two figure gates were already in place and neither could see it. `figure_legibility` measures
how large the type is; `figure_collisions` measures what is drawn through it. **Neither read
what the type said.** `figure_vocabulary` now does, wired into both `_save` paths beside them.

The rule it enforces is deliberately indirect: a term is policed only once the *manuscript*
has stopped using it. A hand-maintained list of forbidden strings would rot; a list checked
against the prose cannot, because retiring a term in the prose is what arms the check.

**The generalisation, which is the reason this is item 6 rather than a bug fix.** Ask of any
change: *what else says this, in a form the change does not reach?* Prose, figure labels, CSV
column names, macro names, test names and commit messages all say the same things in different
places, and an edit that reaches only one of them leaves the others contradicting it. The
figures were the visible case. The identifiers were left saying "inversion" **on purpose**,
which is a different thing from leaving them by accident, and Supplement S45 records the
mapping so a reader following a number from claim to file is not surprised.

**7. Confirm an unexpected test result before explaining it.** Three times now the failure mode
has been to reason about an unexpected result from the apparatus instead of opening the file:
a `sed` mutation that silently matched nothing and made a live gate look inert (twice), and a
new gate that fired on a real defect and was narrowed on the assumption of a false positive
(round 12, corrected in round 13). Verify the mutation applied. Open the file the gate names.
An unexpected result from the apparatus deserves the scrutiny this paper asks for an unexpected
measurement.
