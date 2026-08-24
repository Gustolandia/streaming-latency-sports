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

The suite covers everything that can be decided by reading a file. Four things cannot, and
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

**4. Confirm an unexpected test result before explaining it.** Three times now the failure mode
has been to reason about an unexpected result from the apparatus instead of opening the file:
a `sed` mutation that silently matched nothing and made a live gate look inert (twice), and a
new gate that fired on a real defect and was narrowed on the assumption of a false positive
(round 12, corrected in round 13). Verify the mutation applied. Open the file the gate names.
An unexpected result from the apparatus deserves the scrutiny this paper asks for an unexpected
measurement.
