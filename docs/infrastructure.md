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

**1j. Know the venue's norms, not just its rules.** The rules are on the Author Information
page and the suite gates all of them. The *norms* are only visible in accepted papers, and
`docs/reference_tc/` now keeps two --- Scavenger+ and AXI-REALM, both accepted TC papers,
both software-systems work with heavy evaluation. What they showed:

- **Both are 14 pages.** TC allows 12 before overlength charges and 14 as the maximum, so both
  pay for two. Our 12-page target is stricter than the venue norm. That is a legitimate
  choice, but it should be made knowingly: round 26 spent about two hundred and thirty words
  of prose trying to stay at 12 before discovering the freed words were landing on float pages
  where nothing could use them, and the page came back only by shrinking the addition instead.
- **Figures: 13 and 17. Ours: 7.** TC publishes no limit, so "75% of the limit" has nothing to
  divide; against the observed norm of about fifteen it would mean roughly eleven. The paper
  is figure-light for its venue and the constraint is the page target, not the journal.
- **Scavenger+ carries exactly 45 references**, so sitting at the cap is ordinary.

**1k. When cutting prose stops moving the page count, stop cutting prose.** Round 26's cuts
freed about 150 words on one figure page and 100 more on two others, and the page count did
not move: text cannot flow forward past a float. The lever that worked was shrinking the
insertion that caused the overflow. **Check where the slack landed before cutting again** ---
per-page word counts take one command and would have saved four rounds of shaving, including
a trim to the author's own biography that turned out to be unnecessary and was reverted.

**1l. Every cross-document gate in this suite worked at section granularity.** Three did:
`TestPaperPointsAtRealSupplementSections` parsed `Supplement~S(\d+)`,
`TestEveryTargetedRelocationIsReachable` counted sections, `TestSupplementNumbering` ordered
them. Round 26 inserted a subsection in the middle of S52, renumbered the one below it, missed
the one below that, and left two subsections both called **S52.3** printed one under the other
in the contents list. Nothing failed, because S52 existed and was unique. The same edit left
Section II-A citing S52.2 for a claim that had moved to S52.3 --- a pointer that *resolves*
and lands on the wrong content, which no resolution check can see.

`tests/unit/test_supplement_subsections.py` now holds four rules: every subsection carries an
`SNN.M` number, the number agrees with its section and is unique and gap-free, every
`Supplement~SNN.M` in the paper names a subsection that exists, and **the sentence making the
pointer shares a content word with the subsection it names**. The last is the one that catches
a right address with a wrong destination. Two things about it, both learned the hard way:

- *Match against the target's heading **and body**.* A claim about "its measurement section"
  correctly points at a subsection titled "A framework that does not have the problem"; only
  the body knows they are about the same thing.
- *Scope the claim to the clause, not the paragraph.* The first version took everything back
  to the previous full stop, which on the one genuinely misdirected pointer reached across two
  semicolons into a sentence about the gray literature --- and passed on the defect it was
  written for. The window now starts at the nearest boundary and steps back only while it
  holds too little to judge.

Written to fail first: all four failed on the tree before anything was repaired, and one of
them found a defect nobody had reported --- three subsections under S8 and S19 carrying no
number at all, printing as bare titles in a contents list where twenty-seven of thirty were
numbered.

**1m. A gate with a threshold is not a substitute for looking.** The collision checker caught
two real defects in the new figure --- a tick rule through its own label, a translucent band
under a row label --- and then passed a third: once the figure was compressed to fit the page,
the "crosses the boundary" bracket cut through the row label beneath it, at a coverage just
under the threshold. It was obvious at a glance. Compression changes the data-to-pixel ratio
while the fonts stay at 8 pt, so **a figure that passed at one height has not passed at
another**; re-read it, do not just re-run the gate.

**1n. A gate that polices values cannot police an ordering.** Every check in this suite asks
whether a number is emitted, whether the prose reads it from its macro, whether a caption
reaches it. None of them could see the introduction calling the run-queue stall distribution's
`\baseSliceMs` mode the *largest* when Figure 8 prints the three modes at 20.0, 13.5 and 10.5
and that one is the 10.5. "Largest" is not a value; it is a claim about the order of several
values, and the ledger had never been asked to compute an order. The ledger sweep could not
have helped either: it skips bare integers by design, and a rank is exactly that.

The emitter now publishes `\tracedModeRank` and `\tracedModeTopShare`, and
`tests/unit/test_ordinal_claims.py` reads the rank rather than hard-coding the answer --- so a
recomputation that ever makes this mode the largest relaxes the rule by itself. **When a
sentence ranks something, ask whether anything computes the ranking.**

**1o. "Correct" and "derived" are different properties.** Round 29 checked
`4`--`7`~ms and `12`~ms in Section VI-D against the committed `chronyc tracking` captures and
found all three right --- 3.91/4.77/4.93/7.40 per host, worst pair 12.32. They were still
typed by hand, in both documents, while `scripts/clock_offset_report.py` already had
`pair_bound_ms` and the data sat committed beside it. Being right is a property of today's
tree; being derived is a property of every future one. They are `\chronyHostBoundLo`,
`\chronyHostBoundHi` and `\chronyPairBound` now.

The same check found the presentation fault behind them: a reader given "4 to 7 ms per host"
who wants the pair adds the endpoints and gets **14**. The 12 is the sum of the two *worst*
hosts, which neither document said. Say which hosts a sum is over.

**1p. A schematic borrows the paper's vocabulary whether you mean it to or not.** Figure 3(b)
drew its "incommensurate" row as twenty evenly spaced phases --- which is a commensurate
producer with q = 20, the exact thing the row below it is contrasted against. The prose is
careful here ("889 msg/s sits 0.00014 from 9/8 and behaves as fully continuous"); the figure
was quietly spending that care. It is a golden-ratio rotation now, and the fix was checked
rather than assumed: an offset of 0.5 gives 6 of 20 in the crossing region and would have made
the panel illustrate the wrong number.

**1q. Three gates read every figure. None read a table.** `figure_collisions`,
`figure_legibility` and `figure_vocabulary` run before any figure is written. Both tables in
the manuscript are hand-authored LaTeX rather than generated, and nothing had ever been asked
to look at them --- so Table II's caption promised "Wilson 95% intervals in brackets" for
thirty-one rounds while the intervals sat in a column headed `95% CI` and the only bracketed
quantity in the table was *z*. A reader following the caption looked at the wrong statistic.

`tests/unit/test_table_captions.py` checks the one class of caption claim that is machine
checkable: a promise about *marks* --- brackets, parentheses, italics, bold --- must be kept by
the table body. Two things it taught, both found by its own self-tests rather than by review:

- **The body is the `tabular`, not the float.** A first version took the whole float minus the
  caption and every table passed for free, because `\begin{table}[tb]` is square brackets.
- **Optional arguments are markup, not data.** `\addlinespace[2pt]` supplied the brackets the
  second version accepted. Strip `\cmd[...]` before looking for a data delimiter.

**1r. A correction reaches the file you edited, not the claim.** Round 30 fixed "largest mode"
in `paper.tex`. The same false ranking sat in `scripts/make_result_figures.py`'s module
docstring --- "trimodal, with the largest of the three modes sitting on the scheduler's base
slice" --- for two rounds afterwards, because the ordinal gate read only the two `.tex` files
and because the phrase was wrapped across two lines where a line-oriented `grep` could not see
it. The gate now reads the figure scripts too, on whitespace-normalized text.

Two lessons at once: **a claim about the data is a claim wherever it is written**, docstrings
included; and **normalize whitespace before searching for a phrase**, or the wrap decides what
you find.

Narrowing it was as instructive as writing it. Anchored on "base slice" the rule fired on
`_slice_bucket`'s docstring --- "the largest bucket start at or below it" --- which ranks no
mode and is simply true. The rule is about which mode is biggest, so it keys on the modes.

**1s. Seventeen correct copies is still one source too many.** The payload sweep's three
endpoint quantities were typed in six places in the manuscript and eleven in the supplement,
and `make_result_figures` recomputed the transport ratio a seventeenth time for Figure 7's
annotation. **Every copy was correct**, which is exactly why it lasted thirty-three rounds:
nothing was wrong, so nothing failed. The ledger sweep could not help --- `77` is an integer
and that sweep skips integers by design, and `76.9` was not emitted, so there was no macro to
compare it against.

The tell was in the code. `\tailSlope`, the *other* number in the same figure annotation, had
been emitted rounds earlier with a comment reading "the ledger emits it so they cannot drift
apart again". Its neighbour on the same line went on recomputing. **A repair reaches the
number you were looking at, not the claim.** When fixing one quantity, look at what is printed
beside it.

`stat_intervals.payload_span()` is the single source now; the emitter and the figure both call
it, and `tests/unit/test_figure_ledger_agreement.py` asserts the figure's annotation equals the
macro the prose reads. Two further things it settled:

- **Two precisions is allowed; two sources is not.** The paper wants `76.9` in the result
  sentence and `77` in three summary sentences. Both are emitted, and a pin asserts the second
  is the rounding of the first, so the split is a decision rather than an artefact.
- **Finish the sentence you started.** Substituting the primary campaign's numbers left S25's
  two-campaign comparison caption reading half macro, half literal --- visibly worse than
  uniform. The replication phase is emitted too.

**1t. Read the comment before you change the line.** Round 33's referee asked for uniform
case in the Index Terms. Four lines of comment directly above the block already answered it:
the one capitalised entry is a taxonomy string quoted verbatim from the IEEE Computer Society
subject list, the capital is the quotation mark, and lower-casing it stops the term matching
the taxonomy. The change was made, the ordering gate failed, and it was reverted --- a
round-trip that reading the file would have saved. **When a line looks wrong and the project
is this old, assume it was argued about.**

The attempt left two things worth keeping. `test_index_terms_are_alphabetical` split the
keywords block on semicolons without masking comments, so a two-line note *inside* the block
was read as two more index terms and the failure named the note instead of the terms; it masks
comments now. And a declined referee item is recorded in the source beside the thing it
declines, so the next round does not raise it a third time.

**1u. A figure is published output, so its cells are published numbers.** The experiment map
is drawn into supplement S21, and four of its cells carried results typed by hand: the E-A10
transport span, the priority collapse range, the two geometry factors with the utilisation
both arms reached, and the tail index. Every one duplicated a quantity the ledger already
emits. Round 34 fixed the first and recorded the rest; this closes them.

The pattern each helper follows is `_base_slice_ms`'s: derive from the campaign, fall back to
the literal that was published, and **assert in a test that the two agree**. That last part is
the one worth keeping --- a fallback nobody checks is a second source wearing a disguise, which
is exactly the defect the helper was written to remove. `test_the_fallback_equals_the_derivation`
runs over all four.

`stat_intervals.geometry_rho()` is new because `geometry_cells` drops the column the interval
arithmetic does not need and the map does. It raises if the two k=6 arms disagree, since a
pair that did not reach the same utilisation is not the comparison the figure claims.

**Proof of no-op:** extract the figure's text before and after and diff it. A ledger
substitution that changes a printed character is not a substitution, it is an edit.

**1v. Code may not cite the manuscript by number.** The manuscript writes
`
ef{eq:negspan}` and LaTeX resolves it. Scripts have no such mechanism and wrote the numbers
anyway: eight equation citations and seventeen section citations across thirteen files. Two of
the equation numbers were wrong --- `make_result_figures` told its reader that Figure 7
illustrates the *definition* of the measured span when the caption that same function emits
says the rate law --- and **every one of the seventeen section numbers was arabic**, from the
numbering the paper used before the TC restructure. They did not point at the wrong section;
they pointed at a document that has not existed for many rounds, including a "Section 8.3" of
a paper whose last section is VII.

Five of the eight equation citations were right at the time. That is the argument for the
rule rather than against it: nothing kept them right and nobody had reason to look.

`tests/unit/test_code_cites_no_numbers.py` forbids `Equation N`, `Eq. N` and `Section N` in
`scripts/`, with an allow-list for citations into someone else's numbered document, where the
number is the stable identifier. **Name the thing or describe it** --- "the two-state model",
"the rate as a function of T_true", "the external-campaign section" all survive a
renumbering.

**1w. A range is unambiguous where a single integer is not.** `test_ledger_coverage`
skips bare integers deliberately: an exhaustive count in round 37 found 151 numerals in the
main text, 54 of which coincidentally equalled some macro's value and almost all of which were
noise --- "$1$~ms stamp", "$q = 1$", a "$0.5$~ms path". Policing singletons would drown the
signal. But **two emitted values in order, joined by a dash or by "to", is not a coincidence,
it is the quantity.** Section VI-B typed "$7$ to $80	imes$" while eight sibling sites read
`
tFactorLow`--`
tFactorHigh`.

`tests/unit/test_macro_ranges.py` derives the pairs it polices *from the documents* --- a pair
counts only once the prose already writes it as `\A--\B` somewhere, which is the evidence
that the two macros belong together. Nothing is hard-coded and nothing needs maintaining. It
found the site the referee named **and a second one nobody had**: `supplement.tex` typed
"$39$--$54$" against `
tLowFactor`/`
tHighFactor`.

**1x. The Feynman rule applies to exhibits, and nobody had checked.** `test_section_openings`
has enforced "a section opens on a claim" for many rounds. The same convention runs through
the captions --- and held in eight of ten. Figure 5's lead was a real claim that simply was not
bold; **Figure 1 had no claim at all**, opening directly on "(a)". That is the first figure, the
anchor for both modes, the exhibit a reader meets before any result.

It survived thirty-six rounds because no round had put the ten captions side by side.
`tests/unit/test_caption_leads.py` does it on every build, and asks two things: the caption
starts with `	extbf{...}`, and that lead reads as a sentence rather than a label --- because
"(a)" in bold would satisfy the first rule and nothing a reader wants.

**When a convention holds in most places, count the places.** Both of this round's findings
were conventions at 8/10 and 8/9, invisible to anyone reading linearly.

**1y. An average over a label hides a strike on one letter.** Round 55 rendered Figure 1 at
print size and found the arrowhead of the end-to-end span printed on the "T" of "end-to-end
TTI". The ink check had passed it for every round the label existed, and the reason is
arithmetic rather than tolerance: it scored dark ink as a fraction of the label's whole
bounding box, so an arrowhead sitting on one letter of a fourteen-character label scored
0.0058 against a threshold of 0.012 --- a ninth of the 0.0508 it scores in the cell it
actually landed in. The longer the label, the more ink it can absorb before the gate notices,
which is exactly backwards: a long label is a label with more places to be struck.

`text_struck_by_ink` now also slides a character-cell-wide window along each label and scores
the worst cell. The threshold is 0.03 because the defect scores 0.0508 there and all 331
labels the submission builds score 0.0000 --- a figure that is clean is clean everywhere, so
the two populations are separated by any cut in (0.0, 0.05). **A gate that averages over
the object it protects gets weaker as the object gets bigger.**

**1z. The test existed, in the same file, and had never been pointed at the number.**
Round 56 found Section VI-E quoting a fitted power-law index with a 95% interval and the words
"a finite variance", six lines after using a bootstrap goodness-of-fit to justify *withdrawing*
a different index. `estimate()` in `tail_index_traced.py` ran `gof_pvalue` on the
256--2048 microsecond window and on no other, so the tail fit above 4 ms had never been judged.
Pointed at it, the same test rejects it: **p < 0.0004, 0 of 2,500 replicates**. The interval's
lower limit was 2.00 against a boundary of 2 for a finite variance, and the last populated
bucket falls 357x where the fit implies about four.

Three consecutive rounds have now found the same shape --- round 54's uncited claims about
named artefacts, round 55's remedy quoted by its median and called a bound, round 56's index
quoted past its own test. Each was a rule the paper states and the paper broke, and each
survived because the gates check whether a number *matches its artefact*, never whether the
sentence around it is *allowed to conclude what it concludes*.

`tests/unit/test_the_paper_meets_its_own_rules.py` is the answer, and it is deliberately a
different file from `test_paper_consistency.py`: one asks whether a number is right, the other
whether it may be said. It carries five rules so far --- a moment claim must clear the interval
it depends on; a published fit travels with its goodness of fit, and `estimate()` must judge
every window it fits; a derived constant may not give a measured mode its position; a defined
symbol keeps one meaning; a percentage under one keeps its significant figure.

**When a rule is worth stating in a paper, it is worth running against the paper.**

**1aa. A backslash the shell ate compiles cleanly and prints a word.** The same round found
the built supplement printing **"k/ho"** on page 17 and **"a function of ho"** on page 18: two
`\rho` whose backslash-r had been consumed by a heredoc, leaving a newline and the letters
`ho`. LaTeX typesets `ho` in math mode without complaint, so the compiler passed it, and so did
every gate --- references, vocabulary, collisions, legibility --- because none of them asks
whether a math span is what its author meant. This is the project's own documented shell trap
(write Python with the Write tool, run it with Bash) arriving in the manuscript and staying
there.

`TestNoControlWordLostItsBackslash` checks both the source and the built PDF for a Greek name's
orphaned tail. The companion check is narrower than the one the round-56 referee asked for, and
the difference is worth recording. They asked that no inline `$...$` span be broken across a
line, "since that is the exact signature". It is not: the supplement legitimately wraps
`$\approx` before `0.54$` and `$D = t_{\mathrm{recv}} -` before `t_{\mathrm{send}}$`. What is
exact is that a *wrapped span may not resume on bare letters* --- `ho$` does, `0.54$` and
`t_{\mathrm{send}}$` do not. **A gate that would force correct text to change is a gate someone
turns off**, so the rule that ships is the true one, and the referee's version is recorded here
as the thing it was narrowed from.

The third finding of the round was typographic and had the same shape: `IEEEtran` ends a
`\paragraph` run-in heading with its own colon, and 74 of the supplement's 101 headings already
ended in a full stop, printing `.:`. The main document had none, so the convention was right
and only the longer document drifted --- **a rule held in most places is invisible to anyone
reading linearly**, which is lesson 1x again in a different costume.

**1ab. A submission is two documents, and both were numbering from one.** Round 57 counted
four colliding spaces: the paper's Fig. 1--5 against the supplement's Fig. 1--12, Table I--II
against Table I--XXVII, equations (1)--(6) against (1)--(2), and references [1]--[45] against
[1]--[90]. The paper sends a reader into the supplement thirty-two times, so none of these was
theoretical. The supplement's **Table I is the withdrawn first result set** and the paper's is
the span table. The supplement's **Equation 1 is a power-law fit we withdrew** and the paper's
is `S = D - A`, the identity the whole argument turns on. **`[12]`** is Karimov et al. in one
document and a practitioner blog post in the other.

The fix is the IEEE convention --- the S prefix --- and it is a preamble edit, because nothing
in either document types an exhibit number by hand: every one goes through `\ref` or `\cite`.
Three `\renewcommand`s plus `cite.sty`'s `\citeform` and `\@biblabel`, and no prose moved.
`TestTheTwoDocumentsDoNotShareANumberingSpace` pins it in the **built PDFs**, because a
preamble that silently stops applying is exactly what the prefix guards against.

**One collision the fix created, and how it was closed.** The supplement's sections are already
named S1--S52, so S-numbered equations gave "(S1)" two meanings inside one document. No live
instance existed --- the five parenthetical section references were S3, S18, S37, S52 and
S52.3 --- but the five now read "(Section~S37)", which is what the paper already writes and is
clearer anyway. **A namespace fix can create a namespace collision; check the document you
fixed, not only the pair.**

**1ac. Measure the venue before quoting the rule at the authors.** The IEEE Editorial Style
Manual says "In general, do not use A, An, or The at the beginning of a figure or table
caption", and 19 of this submission's 46 captions did. The right response to a style rule is
not to obey it on sight but to ask whether the venue keeps it: across 26 TC papers in
`docs/reference_tc`, **443 captions, 62 open on an article --- 14%**. The paper was at 57% and
the supplement at 38%, so the rule is real, mostly kept, and this submission was the outlier.

The cause was a convention worth keeping. `test_caption_leads.py` requires every caption to
open on its *claim* rather than on a label --- the Feynman rule applied to exhibits --- and
claims start with "The". The two rules are compatible, and the published, IEEE-copy-edited TC
paper fetched that round proves it: its captions are claim sentences with no article. "The
traced run-queue stall distribution is trimodal" became "Traced run-queue stalls are trimodal",
which is shorter, still a claim, still bold, still first. **When two conventions collide, look
for the wording that satisfies both before giving either one up.**

**1ad. The machinery was loaded and then bypassed.** The supplement loads `xr` and pulls
`paper.aux`, and its own preamble says why: "the numbers shown here are the numbers the reader
sees there". Twenty pointers into the main text were nevertheless typed constants ---
`\newcommand{\mainAuthors}{VII-B}`, used thirteen times, and nineteen more. All twenty were
correct when round 57 checked them, which is the finding rather than a reprieve: nothing would
have said otherwise. Round 56 rewrote Section VI-E and compressed Section VII-A; one added or
reordered section and thirteen pointers name something else.

They now resolve through `\ref`, so `paper.aux` is the source. **A repository whose rule is
that no number is typed had thirty-eight typed section numbers, in the file that explains why
they should not be.**

**1ae. "Never cited" is a claim about the submission, not about one file.** Round 57 asked
whether Equation 2 should keep its number, having found no reference to it anywhere in
`paper.tex`. It should: `supplement.tex` cites it, through the same `xr` link, and the
submission is both documents. The gate that came out of it checks the union rather than the
file --- `TestANumberedEquationIsReferencedSomewhereInTheSubmission` --- and the manuscript did
not change. **Check the scope of a claim before acting on it; the answer moved the gate instead
of the paper.**

**1af. Every PDF that leaves the repository leaves without a byline.** Instructed
2026-09-09, for the Zenodo record's files and for anything sent as an attachment. The author
list is not settled, and a circulated PDF is a durable public statement of authorship that a
later correction does not catch up with. `paper.pdf` and `supplement.pdf` are unchanged --- a
journal submission must name its authors --- and `scripts/build_without_authors.py` writes the
circulating pair into `build/no_authors/`.

What comes out is the byline, its affiliation footnotes and the author biographies. What stays
is the acknowledgment, because it thanks people for specific help, which is true whoever the
authors turn out to be: **removing a byline withdraws a claim that is open; removing a credit
would erase a debt that is not.** Two in-body names stay for the same reason and are listed in
the script with their justification --- "Brendan Gregg", who is cited work rather than the
co-author of that surname, and "N. Herbst raised the comparison".

`--check` runs `pdftotext` over both outputs and reports any surname that survived, and it
reports "not verified" rather than "clean" when `pdftotext` is missing, because a promise
nobody could check must not print as a promise kept.

**The tests caught a real defect in the script.** `build` cleaned up after itself by
enumerating extensions --- `.tex`, `.aux`, `.log`, `.out`, `.bbl`, `.blg` --- and the
supplement has a table of contents, so `_noauth_supplement.toc` survived in the repository
root and appeared in `git status`. It cleans by prefix now. **A cleanup that lists what it
expects will always miss the one it did not.**

**1ag. The paper contradicted its own concession, in the two places a referee reads first.**
Section III-C has said for many rounds: *"Our contribution is not the law --- we derived it,
then found it in a counter manual --- but its consequence under deletion."* The abstract
promised *"a law for the retained fraction"* and contribution 1 was headed *"A law for what a
positivity filter discards"*.

The second author read the abstract and the contributions cold on 2026-09-09 and reacted to
exactly that: *"not a great idea to try to force the paper around a single grand law,
especially I am not sure your work does contain a single such law."* Fifty-seven simulated
rounds had not seen it, and the reason is worth recording: **each round inherited the framing
instead of meeting it.** Round 6 had already found the grid arithmetic standardised in ADC
metrology (IEEE Std 1241, coherent sampling, `f_in/f_s = M/N` coprime giving N phases) and
told the paper to concede it; round 54 quoted the concession back approvingly. Neither then
checked whether the abstract still claimed what Section III-C gives away.

Contribution 1 is now *"What a positivity filter costs a reported distribution"*, the
arithmetic is credited to the 1970 counter manual in the contribution itself, and the three
other places that called it "the deletion law" or "the grid law" say *arithmetic*. **A
concession buried in Section III-C is not a concession if the abstract still makes the
claim.**

Two smaller things fell out of the same pass. Contribution 1 described the ratio as *"its
send interval to its timestamp resolution"* --- which is the commensurability, not the
retention law it was introducing; the retention law is the delivery over the resolution. And
the grid refinement, the spread rule and the grid-membership inference went to Supplements
S22 and S23, where all three already existed in full: the paper's Equation 5 and the
supplement's Equation S2 were **the same rule stated twice**, in two documents, one of them
the document that also derives it.

**1ah. Nothing in the paper computed with Equation 6.** The two-state form
`Pr[S < 0 | T_true] = p G(T_true)` was the centre of Section VI-B. Asked whether it should
stay, the answer came from counting what used it: **all three references named the two-state
picture, not the formula** --- "the preempted state of Equation 6", "the state Equation 6
depends on", and the originality claim against Villain et al. Not one step computed `p G`.
Its three tested consequences are attributable without it: the direction under payload is
what the *identity* predicts and the paper says so, the floor `C_0` is the `p -> 0` limit of
the picture, and the traced check compares two probabilities.

Nor has the form ever been tested as a form. There is no measurement of `p` independent of
the rate it explains, so it cannot be falsified as a model --- only its consequences can, and
they survive without it. It was wrong once for exactly that kind of reason: round 49 found it
written `p(rho) G` while Table II demonstrates the rate is not a function of rho, and it was
repaired by weakening it.

It is in Supplement S16 now, stated in full with that reasoning attached, and Section VI-B
keeps the mechanism in prose. **A model that cannot be falsified as a model belongs where a
reader can weigh it, not where the argument appears to rest on it.**

**1ai. Six of nine was not nine, and a loose probe said it was.** The second author's note
carries a nine-item checklist of benchmark-design rules. Asked whether Section VII-B had them,
a first pass searched the whole paper for a word from each and reported all nine present. It
was wrong on three: "validate" matched a sentence in Section IV, "co-locat" matched Section
VII-A, and "physical events" matched nothing at all. Searching *the section that is supposed
to contain the rule* found six.

The three that were missing are now rules: say which physical event each timestamp marks,
exercise the timestamping path at the load you will report from, and do not assume
co-location makes the measurement safer. **A probe that searches the wrong scope reports the
answer you hoped for**, which is the same failure the paper is about, in a checklist about it.

**1aj. The archaeology left the reader's path.** "Much less archaeology for the reader" was
the note's last line, and the paper carried eight retrospective passages: a closing flourish
about the check destroying our first result, a threshold sweep framed as a withdrawal, a
post-mortem paragraph on two rejected results, a testbed introduced by what it had produced,
and the whole payload-sweep slope with its two disagreeing estimators and its bootstrap.

All of it is in the supplement now, and **every finding and every limitation it carried
stayed**: the threshold's insensitivity is still reported, the check's incompleteness is still
stated ("causal consistency is necessary, not sufficient"), and the audit still publishes what
applying the rule to ourselves cost. Three self-references survive on purpose --- the audit
rejecting every run behind our own first result, twice, and one registered prediction that
failed --- because those are results and correct reporting, not history.

Five pins followed the material. Four required the words "we withdraw the claim" *in the main
text*, on the principle that a withdrawal stays withdrawn only if the sentence that withdraws
it keeps saying so; they now require it in the supplement and forbid the slope's return to the
paper, which is the stronger form of the same rule. The fifth was the CLAIMS entry in
`test_claim_equation_binding.py` --- a file that exists because round 48 caught the paper
claiming "a law relating the negative-span rate to the delivery" while pointing at an equation
that contained no delivery. **The sentence it guarded is gone, and the guard's own docstring
told us what to do: retire it deliberately, and check the abstract still matches.** Its
companion now asserts the delta over Villain et al. in the wording that replaced it, and
asserts both halves, because the dependence without the manipulations is what Villain already
had.

**1ak. A sentence can be right where it was and wrong where it is.** Round 58 found three
of these in one read, all made by the restructure that moved material between sections, and
all invisible to every gate the repository owns, because each sentence is individually true
and individually well formed.

*A section that states its claim, then states it again.* The new Section VII opened on
"Neither failure is one project's oversight ... five of the ten we read dispose of a sample
without counting it", and sixty words later its own third paragraph said "Five of the ten
dispose of the sample without counting it, in three classes --- a pattern rather than one
project's oversight". A fifth of a 315-word section, twice. The opening had been written
*from* the paragraph it introduces, which is how it happened.

*A connective whose antecedent moved.* "Nor is the admission condition confined to the tool we
measured" was the second of two paired "Nor is..." continuations; the first went to another
section in the split, and the survivor was left negating a positive claim.

*A pointer that did not follow its definition.* Section V-E said "not the timestamp resolution
of Section VI" after the reorder moved that definition to Section II --- sending a reader
forward for something they were given three sections earlier, which is rule A7 inverted.

`tests/unit/test_prose_logic.py` is the new class of gate, and **it found a fourth on its
first run**: the co-location rule added in round 60 repeated Section VIII-A's "the standard
evaluation environment hides" almost word for word, two pages apart.

**What the shingle width had to be, and how the test itself corrected me.** The first version
matched seven raw words and its own self-test failed, because the defect was a *near*
repetition: "dispose of **a** sample" against "dispose of **the** sample". Stopwords carry
the difference and not the meaning, so the rule now matches four consecutive *content* words
with articles and prepositions dropped. **A repetition check that keeps the articles is
checking the wording, not the claim.**

**The rule runs on the article only, and that is a decision rather than an omission.** The
supplement is a postmortem whose form is restatement --- it records what an earlier version
said and then what replaced it, and several of those pairs are labelled "in the round-2
restatement" in the text. Running the rule there would flag the document doing its job.
Tables come out first for the same kind of reason: a tabular's rows repeat each other's column
separators by construction, and left in, every table reports itself.

**1al. The abstract's colon is a promise.** It read "derive checks their authors can apply: an
exact identity for the negative span, a pre-registered manipulation, and an audit of ten
tools". None of the three is a check --- they are how the paper *establishes* the two failure
modes, and the checks are the sign check and the retention report, which the sentence never
named. The same sentence said "their authors" of two failure modes, which have none.

Both survived because the abstract is the one paragraph a body gate never reads, and both are
now pinned: the evidence must be listed before the word "checks", and the checks must name the
audience they are for. **An abstract is the only part of a paper that is read by everyone and
checked by nothing.**

**1am. A rule you cannot build is worth more measured than guessed.** Round 59 found four
supplement sentences sending a reader to Section V-A for material round 60 had taken out
of it, and asked for the obvious gate: a sentence naming a main-text section must share
distinctive vocabulary with the section it names. Before writing it, we measured it over
all 67 pointer sentences. Legitimate ones miss as many as **10 of 24** content words
against the *whole* article --- a supplement's job is to say more than the article does ---
while the four defects missed 2 to 4 of 4 to 8. Worse, the fifth pointer, the one round 59
checked and found *correct*, missed 1 of 6, and the word it missed was "withdrawal", which
round 60 had deleted from the article in the same pass. No threshold separates those
populations, and tuning one until the corpus passes produces a gate that tests nothing.

What shipped is the half that does separate them. Each of the four leaned on a phrase the
article does not contain anywhere, so `tests/unit/test_pointer_sense.py` carries a
hand-maintained inventory of the phrases the supplement attributes to the article, and
requires the article to still hold them --- an allow-list, like `test_ledger_coverage`'s,
for the same reason: what a sentence leans on is not a judgement a regular expression makes
well. All six rows were mutation-tested; removing any one from `paper.tex` fires the gate,
and reintroducing round 59's own defect fires the regression half. **A measured refusal to
build a check is a result; an unmeasured check that passes is not.**

**1an. The referee's diagnosis and the referee's wording are two different things.** R2 was
right that Section III-B's colon promised "its consequence" and then delivered a
consequence and a method, and it supplied a replacement "at no cost". The replacement cost
the clause "separate scheduling from its rival explanations", and
`test_claim_equation_binding` failed on it within the minute: round 60 had already fixed
the delta over Villain et al. as two things, the dependence *and* what the manipulations
do, because a claim keeping only the dependence is a claim Villain et al. made in 2012. A
full stop does what the em-dash pair was for and keeps both. **A gate is how an earlier
round argues with a later one, and it is the only party in the argument that cannot be
talked round.**

**1ao. Every figure was checked against its caption, and none against the others.** Three
gates read the figures --- legibility measures the type, collisions measure what is drawn
through it, vocabulary reads what it says --- and all three take one figure at a time.
Round 59's review put the seventeen side by side instead, and found the submission
printing the multiplication sign three ways, the microsecond two, panel titles capitalised
ten times out of eighteen, and the colour blue meaning `real-time` in Fig. S7 and
`ordinary` in Fig. S8 --- on the same eight experiments, beside the same factors. Not one
of these is visible from inside a single figure, which is why nothing had seen them in
fifty-eight rounds. **A consistency defect lives in the space between two artefacts, and a
gate that loads one artefact at a time is looking through it.**

The same read found Fig. S2(b) drawing grouped bars on a log axis, whose docstring had
already rejected *stacked* bars there for a related reason and stopped one step short.


**1ap. A failed download was left wearing the paper's filename.** Round 60 went looking
for `timerlat_TC.pdf` --- the manuscript's reference [35], and the closest paper at the
target venue --- and found it already on disk: 5.7 KB, one page, *"Enable JavaScript and
cookies to continue"*. Three separate rounds had recorded that retrieval as **failed**, and
each time the failure was also written to disk under the paper's name, after which the
corpus reported the paper as held and every venue statistic counted it. The paper was
retrievable the whole time, from the authors' own preprint page rather than from the
publisher. `scripts/check_reference_corpus.py` now refuses any file that is under three
pages, carries a bot-wall phrase, or has a first page too thin to be a title page; it found
exactly one offender in fifty-six. **A negative result and its artefact must not share a
name: recording "this fetch failed" while leaving the failure on disk records the
opposite.**

**1aq. The ledger gate could only see a typed number that collided with a macro.** Its own
docstring says it was built for the four copies round 23 found, each of which duplicated a
quantity the ledger already emitted. That is also its limit: `13.6`, `26.7`, `69.2` and
`66.67` were typed in *both* documents, in two different units, and none of them was
emitted at all --- so there was nothing for the collision check to collide with. The
referee asked only for the units. Reading the source to add them is what found the rest.
**A gate that checks agreement between two sources is blind to a quantity that has only
one.**

The repair also fixed the gate's opposite failure. Emitting the interquartile bound `4.0`
made it collide with `CC BY-NC-SA 4.0`, and the main text is pinned to need *no*
exemptions --- correctly, so the licence version is masked the way tables and comments
already were, rather than excused. A version is part of a name.

**1ar. A median quoted alone is a bound, in the second number as in the first.** Commit
`987e525` learned this about a remedy. Round 60 found it again in the paper's headline
distortion: *"understating it 4.2x"* is a median over 70 conditions whose interquartile
range runs 4.0x to 7.5x and reaches 14x, so the headline sat at the **bottom** of its own
range and half the conditions were worse. The paragraph two sentences below it already
quoted its own claim at the median *and* the upper quartile. **A lesson learned about one
number does not propagate to its neighbours by itself; nothing sweeps for the pattern
unless somebody writes the sweep.** `tests/unit/test_round60_findings.py` now fails if the
understatement loses its denominator or its spread, and separately if a recomputation ever
moves the median into the middle of its range --- at which point the sentence needs
rewriting rather than the test deleting.

**1as. A fork count is not an adoption count.** Section VII opened on *"40 of the 40 public
forks carry the expression unchanged"*, in the position the Feynman rule reserves for a
section's strongest claim. A fork is a copy: the number bounds how few have diverged, and
most public forks are never edited. It was also the one empirical claim in the paper with
no supplement section behind it. The ten-tool audit below it --- five languages, nine
vendors, a registry in S37 --- is the independent evidence, and it opens the section now.
**The Feynman rule places a section's best claim first; it does not check that the first
claim is the best one.**


**1at. Item 1aa was recorded four rounds ago and kept happening, because nothing looked.**
*"A backslash the shell ate compiles cleanly and prints a word"* has been in this file
since round 40. Round 60 did it again: a patch carrying `\flipVertexTwoThirds` went
through a shell heredoc, which interprets `\f` as a formfeed, and `supplement.tex`
received a control character followed by `lipVertexTwoThirds`. It would have printed as a
word in the middle of a sentence about the grid vertex.

What caught it is the interesting part. Not a macro check, not a rendered-prose check ---
**`test_no_line_is_stretched_to_the_limit`**, a *typesetting* gate, which noticed only that
the paragraph could not be set to an acceptable badness. The cause was four steps upstream
of the symptom, and the gate that fired knew nothing about macros at all. That is luck
wearing the clothes of coverage.

A lesson written down is not a lesson enforced. Tab, newline and carriage return are the
only control characters a LaTeX source has any use for, and
`tests/unit/test_round60_findings.py` now says so about both documents, with the round-60
corruption pinned as its own negative example. **Four rounds of writing "do not use
heredocs for backslashes" prevented nothing; eight lines of test prevent it permanently.**


**1au. A repair moved a paragraph and did not re-read its first sentence.** Round 60 was
right to take the fork count out of Section VII's opening. The paragraph it promoted had
been written to sit *second*, so the section came to open on *"Deletion is not the only
way coarse resolution wins"* --- a sentence about what Section VI was, in the position
this paper reserves for what a section is. The hinge had also been separated from the case
it introduces, which is two sentences further down. **Moving a paragraph changes the
sentence it starts with, and nothing re-reads it.**

The Feynman rule had been a writing standard for fifty rounds and never a test. It is one
now, in the half a regular expression can actually judge: a section may not open on a
sentence *about the previous section*. Section II is exempt by name, because a co-author
put the definitions there and a definitions section opening on a claim would be worse ---
an exemption written down beats a rule loosened until it passes.

**1av. Nine parsers could not read standard LaTeX, and the tenth would not have either.**
Giving the supplement a list of its forty exhibits is only useful if the entries are the
exhibits' claims rather than their whole captions, so each caption gained the short form
`\caption[short]{long}`. Every caption parser in the project looked for the literal
`\caption{`, which that form does not contain --- nine sites across eight files.

The failure was **loud**: seven gates failed or errored at once, because each asserts on
caption *content*, so a parser that walks past a caption finds either nothing or text that
does not match. That is worth recording because the first instinct was to back the change
out, on the theory that a parser reading a neighboring caption would do so in silence. It
would not have. **A gate that asserts on content fails loudly when its input moves; a gate
that asserts on structure fails quietly.** The nine sites were fixed and the tenth is
gated.

**1aw. Three attempts at one convenience, and the third was the cheap one.** The lists were
added, produced four pages of justified prose at badness 10000, and were then dragged
through short captions (backed out), ragged-right (which did not reach the list files), and
short captions again (kept, with the parsers fixed). The route mattered less than the
reason it was long: **these captions carry evidence, not labels**, so they are not
list-shaped, and every fix that left them whole failed on the typesetting. The instrument
was wrong until the captions were given something list-shaped to contribute.


**1ax. Two gates written this round could not have failed, and their own negative
examples said so.** The capitalised-macro rule listed what may stand before a `WordCap`
macro --- a full stop, a colon, an em dash --- and included the empty string, meaning
"start of text". `"anything".endswith(("...", ""))` is **always true**, so the rule
passed everything. The caption-parser rule flagged every caption literal in the project,
including the sample captions that are test *data* rather than parsers, so it failed on
nine innocent lines.

Both were caught in seconds, by the `test_the_rule_can_fail` method each class carries as
a matter of course. That habit --- every rule ships with an example it must reject and an
example it must accept --- has now caught a vacuous rule and an over-broad one in a single
round. **A gate is code, and a gate nobody tested is a gate that passes.**

**1ay. The pair rule and the inventory rule pull in opposite directions, and the pair rule
wins.** Reordering Section VII moved `\harnessSilentWordCap` out of the sentence it opened
and put its lower-case twin after a semicolon, so the capitalised half went idle and the
unread-macro ceiling had to rise to 67. Item 12 is why it stays emitted: the `Word`/
`WordCap` pairs exist so a generated number can open a sentence, and half a pair is not a
pair. The ceiling may rise for a reason written down; this is the reason.


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

**8. When a figure counts something in its legend, count it in the rendering.** Round 43's
deletion figure announced "printed above it (4)" and drew three circles: two 256 KB replicates
printing 42,393 and 42,973 ms sat 1.4% apart on a five-decade log axis and rendered as one
marker. No gate could see it, because every gate was reading the data and the data had four
rows. `spread_coincident()` now separates markers before drawing, and the test asserts that
the four above-grid cells occupy four distinguishable positions.

The general form is worth stating, because it is the third instance in this project: **a
figure can be wrong in the rendering while being right in the data, and the checks all look at
the data.** The other two were the label struck through by a rule (round 12) and the tick
formatter left running underneath a replaced axis (round 13). What the three have in common is
that the defect exists only after the artists have been placed.

**9. An axis with no variable on it must not carry an order.** The same round found the
payload panel laying each arm's replicates out at even spacing in the order they arrived --
and they arrive sorted, because the helper returns `sorted(vals)`. Every arm rendered as a
staircase climbing left to right along an axis whose only labels were the three payloads. The
caption claimed no trend; the picture supplied one. A swarm fixes it: offsets encode local
crowding, symmetric about the arm's centre, so position says only what is true.

**10. A script's default must reproduce the artefact in the repository.** `MC_ARMS` was 20,000
while the committed grid ledger had been written at 4,000, so running the script with its own
default moved every p-value sitting at the Monte Carlo floor. Nothing downstream noticed,
because the floor is far below every threshold the paper uses -- which is exactly why it
survived. A default that does not regenerate the committed file is the defect this project
audits, one layer down.

**11. A `\ref` to a `\paragraph` prints a section number nobody can find.** IEEEtran numbers a
paragraph inside a subsection as "0a", so `\ref{sec:metrics}` renders as "Section III-A0a".
Two were in the round-43 build, and one of them had been created by the round-43 edit that
fixed a *different* dangling pointer. The source looks correct in both cases; only the output
is wrong. `tests/unit/test_rendered_prose.py` now fails on the pattern in either rendered PDF.

**12. A macro at the head of a sentence loses its capital.** `\harnessSilentWord` expands to
"five", and round 43's sentence-splitting pass moved it to the front of a sentence: the built
PDF read "…classified the benchmark. five of the ten dispose…". The project already generates
a capitalised twin for exactly this — eleven `…WordCap` macros exist — and the one place that
needed it was not using it. Two more of the same shape were in the supplement, after run-in
italic headings.

The general form is the one this file keeps rediscovering: **the source can be right while the
output is wrong**, and every gate that reads `.tex` is blind to it. That is now four classes
(a label under a rule, a tick formatter left running, a legend counting markers that overprint,
and these two), which is enough to say the rule out loud: *if a defect can only be seen after
LaTeX has run, the check has to run after LaTeX too.*

**13. Quote what you emit, or stop emitting it.** Sixty-six of two hundred and seventy-five
generated macros were read by neither document when this was counted. Most are deliberate —
the `Word`/`WordCap` pairs exist so a number can open a sentence, and keeping both halves is
right even when one is idle, as item 12 shows. But `\ackLagMedianUs` was not a variant: it is
the median acknowledgment lag, the single number the whole exposure curve of Section VI-B
rests on, and it was computed, carried and shown to nobody. The inventory now has a ceiling
that may fall freely and may not rise without a reason being written down.
