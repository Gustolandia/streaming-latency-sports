# Release v2.6.0 — Zenodo, then arXiv

Everything is built and verified. What is left is the two irreversible steps, which are yours:
pressing **Publish** on Zenodo and **Submit** on arXiv.

Tag: `v2.6.0` (`bdf7207`), pushed. Both archives are built from that tag, not from the working
tree.

---

## 0. What is on disk

| file | size | goes to |
|---|---|---|
| `dist/streaming-latency-sports-v2.6.0.zip` | 7.71 MB | Zenodo **code** record |
| `dist/SHA256SUMS-code-v2.6.0.txt` | 787 files | Zenodo **code** record |
| `dist/streaming-latency-sports-data-v2.6.0.zip` | 4.79 MB | Zenodo **data** record |
| `dist/SHA256SUMS-data-v2.6.0.txt` | 469 files | Zenodo **data** record |
| `dist/streaming-latency-arxiv-v2.6.zip` | 1.06 MB | arXiv |
| `dist/arxiv_v2.6_metadata.md` | — | the arXiv form, to paste |

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

### Do it

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

Each command opens a **draft** and stops. It prints a URL. It does not publish — a published
Zenodo record cannot be deleted, only superseded, so the last click stays human.

### Before you press Publish, check three things in the browser

1. **The version field reads 2.6.0** and the description's changelog is the v2.6 one.
2. **Exactly two files are attached** to each record — the zip and its `SHA256SUMS`. The script
   deletes the files a new-version draft inherits from v2.5.0, and prints what it deleted; if
   you see four files, something did not delete and the record would ship two zips.
3. **The licence carve-out is in the description**: MIT for the code, CC BY 4.0 for the data
   compilation and documentation, and the manuscript files © the author and expressly *not*
   CC BY, included as a data complement pending journal publication. This is what keeps the
   IEEE copyright transfer clean.

Then upload each `SHA256SUMS-*.txt` alongside its zip (the script uploads the zip only) and
press **Publish**.

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
