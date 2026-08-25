# Release v2.6.0 — Zenodo, then arXiv

Everything is built and verified. What is left is the two irreversible steps, which are yours:
pressing **Publish** on Zenodo and **Submit** on arXiv.

Tag: `v2.6.0`, pushed. Both archives are built from that tag, not from the working tree. The
tag was moved during this release, so no commit id is quoted here; `git rev-parse v2.6.0^{}`
gives the current one.

---

## 0. What is on disk

| file | goes to |
|---|---|
| `dist/streaming-latency-sports-v2.6.0.zip` | Zenodo **code** record |
| `dist/SHA256SUMS-code-v2.6.0.txt` | Zenodo **code** record |
| `dist/streaming-latency-sports-data-v2.6.0.zip` | Zenodo **data** record |
| `dist/SHA256SUMS-data-v2.6.0.txt` | Zenodo **data** record |
| `dist/streaming-latency-arxiv-v2.6.zip` | arXiv |
| `dist/arxiv_v2.6_metadata.md` | the arXiv form, to paste |

Sizes and per-file digests are not repeated here: this file ships inside the code archive, so any
size it quoted would be a size it changed. Both `SHA256SUMS` manifests carry the archive's own
digest on line 3 and one line per file inside it.

The code archive contains `paper.pdf`, `paper.tex`, `supplement.pdf` and `supplement.tex`, as
well as the scripts, tests and campaign ledgers. It does **not** contain
`data/processed/replay_plans` (CC BY-NC, derived from StatsBomb) or `docs/reference_tc`
(sixteen third-party TC papers, 34.8 MB, nobody's to redistribute). Both exclusions are
enforced by git pathspec in `scripts/zenodo_deposit.py`, so a file added under either path
later is excluded automatically.

---

## 1. Zenodo — new version, same concept DOI

**The point of this step.** A Zenodo *concept* DOI is stable across every version and always
resolves to the newest one. A *version* DOI pins one release. The paper now cites the concept
DOIs, so this deposit must be a **new version of the existing records**, not new records. A new
record would mint a new concept DOI and break the citation in the PDF.

| record | concept DOI (cited in the paper) | latest version id, to pass on the command line |
|---|---|---|
| code / analysis / manuscript | `10.5281/zenodo.21650031` | **22044877** |
| measurement dataset | `10.5281/zenodo.21650064` | **22044891** |

### Already done, in the browser

Both new-version drafts exist and their metadata is filled and saved. Neither is published; a
draft is private, editable and discardable.

| record | draft | concept DOI it keeps |
|---|---|---|
| code / analysis / manuscript | <https://zenodo.org/uploads/22102716> | `10.5281/zenodo.21650031` |
| measurement dataset | <https://zenodo.org/uploads/22102832> | `10.5281/zenodo.21650064` |

Each of these was checked after a page reload rather than assumed, because the form's fields do
not all commit the same way:

- version `2.6.0`, publication date `2026-08-25`
- the description carries the v2.6 changelog and the licence carve-out
- related works point at the sibling record's **concept** DOI, not last release's version DOI
- title, authors, affiliation, keywords, licence and visibility inherited unchanged
- no files were inherited, so there is nothing stale to delete

**Do not run the deposit script now.** `--new-version` would open a *second* draft beside these
two. The command line remains available if you would rather discard both drafts and start over:

```bash
$env:ZENODO_API_TOKEN = "<your token>"
```

Rehearse on the sandbox if you want — it is a separate site with its own account and token:

```bash
python scripts/zenodo_deposit.py --sandbox --new-version 22044877 --ref v2.6.0 --zip dist/streaming-latency-sports-v2.6.0.zip
```

Then the real thing, code record first:

```bash
python scripts/zenodo_deposit.py --new-version 22044877 --ref v2.6.0 --zip dist/streaming-latency-sports-v2.6.0.zip
```

and the data record:

```bash
python scripts/zenodo_deposit.py --new-version 22044891 --ref v2.6.0 --metadata .zenodo-data.json --zip dist/streaming-latency-sports-data-v2.6.0.zip --paths docs/results reproducibility
```

Each command opens a **draft** and stops. It does not publish — a published Zenodo record cannot
be deleted, only superseded, so the last click stays human.

### What is left for you

Attach two files to each draft, then press **Publish**:

| draft | attach |
|---|---|
| code <https://zenodo.org/uploads/22102716> | `dist/streaming-latency-sports-v2.6.0.zip` and `dist/SHA256SUMS-code-v2.6.0.txt` |
| data <https://zenodo.org/uploads/22102832> | `dist/streaming-latency-sports-data-v2.6.0.zip` and `dist/SHA256SUMS-data-v2.6.0.txt` |

Worth a glance before the click, since publishing is irreversible:

1. **Exactly two files** on each record. Four would mean a stale zip from v2.5.0 is still
   attached and the record would ship two archives.
2. **The licence carve-out is in the description**: MIT for the code, CC BY 4.0 for the data
   compilation and documentation, and the manuscript files (c) the author and expressly *not*
   CC BY, included as a data complement pending journal publication. This is what keeps the
   IEEE copyright transfer clean.
3. **The version reads 2.6.0** and the changelog paragraph is the v2.6 one.

---

## 2. arXiv — replace in place

Only after Zenodo is published, so the DOIs in the announced PDF resolve to v2.6.0.

Submission `submit/7871792` is on hold and was never announced, so this replaces in place.
Upload `dist/streaming-latency-arxiv-v2.6.zip` and paste the metadata from
`dist/arxiv_v2.6_metadata.md`.

The bundle was unzipped into an empty directory and compiled with `pdflatex` twice, no BibTeX
pass: 0 errors, 0 undefined references, 0 overfull boxes, 0 Type 3 fonts, 12 pages.

---

## 3. Afterwards

- Send me the two new version DOIs and the arXiv identifier and I will add each as a related
  identifier on the other, and put the arXiv link in the README.
- The paper needs no edit for any of this: it cites concept DOIs, which already point at
  whatever you publish.

---

## One thing worth deciding separately

`docs/reference_tc/` holds sixteen third-party TC papers and is committed to a **public** GitHub
repository. They are excluded from the Zenodo archive, but that does not address the repo
itself: publisher PDFs and author preprints are readable under the terms each grants and
redistributable under almost none of them.

They have served their purpose — the referee corpus was declared settled two rounds ago and
nothing in the analysis reads them. My suggestion is to `git rm` the directory and keep a short
`README.md` in its place listing the sixteen papers by title, arXiv id and DOI, so the record of
what informed the judgement survives without redistributing the files. That is a one-commit
change and I have not made it, because removing published files from a public repository is
your call, not mine.
