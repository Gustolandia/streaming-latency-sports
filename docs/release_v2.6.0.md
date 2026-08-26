# Release v2.6.0 — Zenodo published, arXiv submitted

**Status, 2026-08-26.** Both Zenodo records are published. The paper is submitted to arXiv and
in moderation. The journal submission is the only step left, and it waits on replies from the
people the acknowledgment names.

Tag: `v2.6.0`, pushed. Both archives are built from that tag, not from the working tree. The
tag was moved during this release, so no commit id is quoted here; `git rev-parse v2.6.0^{}`
gives the current one.

---

## 0. What was deposited

| file | went to |
|---|---|
| `dist/streaming-latency-sports-v2.6.0.zip` | Zenodo **code** record |
| `dist/SHA256SUMS-code-v2.6.0.txt` | Zenodo **code** record |
| `dist/streaming-latency-sports-data-v2.6.0.zip` | Zenodo **data** record |
| `dist/SHA256SUMS-data-v2.6.0.txt` | Zenodo **data** record |
| `dist/streaming-latency-arxiv-v2.6.zip` | arXiv |
| `dist/arxiv_v2.6_metadata.md` | the arXiv form |

Sizes and per-file digests are not repeated here: this file ships inside the code archive, so any
size it quoted would be a size it changed. Both `SHA256SUMS` manifests carry the archive's own
digest on line 3 and one line per file inside it.

The code archive contains `paper.pdf`, `paper.tex`, `supplement.pdf` and `supplement.tex`, as
well as the scripts, tests and campaign ledgers. It does **not** contain
`data/processed/replay_plans` (CC BY-NC, derived from StatsBomb) or `docs/reference_tc`
(sixteen third-party TC papers, nobody's to redistribute). Both exclusions are
enforced by git pathspec in `scripts/zenodo_deposit.py`, so a file added under either path
later is excluded automatically.

---

## 1. Zenodo — new versions, same concept DOIs

**Why it had to be a new version.** A Zenodo *concept* DOI is stable across every version and
always resolves to the newest one; a *version* DOI pins one release. The paper cites the concept
DOIs, so a new *record* would have minted a new concept DOI and broken the citation in the PDF.

| record | concept DOI (cited in the paper) | v2.6.0 version DOI |
|---|---|---|
| code / analysis / manuscript | `10.5281/zenodo.21650031` | `10.5281/zenodo.22102716` |
| measurement dataset | `10.5281/zenodo.21650064` | `10.5281/zenodo.22102832` |

Checked after publication rather than assumed:

- both concept DOIs resolve to the v2.6.0 records;
- each record carries exactly two files, and the md5 Zenodo reports for each matches the local
  archive — which is what proves the corrected rebuild was uploaded rather than the first one;
- version reads `2.6.0`, publication date `2026-08-25`;
- related works point at the sibling record's **concept** DOI, not the previous release's
  version DOI;
- the licence carve-out is in both descriptions: MIT for the code, CC BY 4.0 for the data
  compilation and documentation, and the manuscript files © the author and expressly *not*
  CC BY, included as a data complement pending journal publication. This is what keeps the
  IEEE copyright transfer clean.

### Metadata corrected after publication (2026-08-26)

Record metadata stays editable after publication and the version DOI does not change. Both
descriptions still opened Mode A with "cross-process latency is a two-clock difference and
cannot be negative" — a claim the paper retracted, since Section III now presents the
acknowledgment-referenced span as a proxy rather than a chain, and justifies the sign check by
the reference stamp being unusable as an origin rather than by the value being forbidden. The
same sentence said "two-clock" where the binding arm is one clock by construction, and quoted
the real-time collapse as 39x and 54x where the ledger emits 7 and 80.

All of it is corrected; "inversion" is "negative span" in both records, matching the paper; and
every figure in the rewritten paragraph is one the ledger emits. The archives were not rebuilt
for this, so the published `.zenodo.json` inside the code archive still carries the old wording.
The record itself is the corrected statement.

### If it has to be done again

`python scripts/zenodo_deposit.py --new-version <latest version id> --ref <tag> --zip <archive>`
opens a draft and stops. It does not publish: a published Zenodo record cannot be deleted, only
superseded, so the last click stays human. `--sandbox` rehearses on the separate sandbox site,
which has its own account and token. The token is read from `ZENODO_API_TOKEN` and never written
to disk.

The web flow was used this time. Two things about it: the deposit form does not commit every
field the same way, and an edit that looks saved can revert, so reload and re-read every field
after saving. And the edit form for a *published* record is reachable only by clicking **Edit**
on the record page — navigating straight to `/uploads/<id>` redirects back to the record.

---

## 2. arXiv

`submit/7871792` was replaced in place with `dist/streaming-latency-arxiv-v2.6.zip` and
resubmitted on 2026-08-25. The receipt confirms what was registered: 12 pages, 8 figures,
2 tables, 46-page supplement as an ancillary file, `cs.PF` primary with `cs.DC` cross-list,
ACM class `C.4; C.2.4`, the arXiv non-exclusive licence, and the concept DOIs in the comments
field.

The bundle was unzipped into an empty directory and compiled with `pdflatex` twice, no BibTeX
pass: 0 errors, 0 undefined references, 0 overfull boxes, 0 Type 3 fonts, 12 pages.

Two things worth knowing next time. Editing a submission that is on hold moves it out of
moderation back to *incomplete*, which is the expected cost of changing it rather than a
failure. And the account is capped at three in-process submissions; that cap produced a refusal
at one point during the edit and cleared on its own.

---

## 3. What is still open

- **arXiv identifier.** When the submission is announced, add it as a related identifier on both
  Zenodo records and put the link in the README.
- **Journal submission** via the IEEE Author Portal, once the author list settles.
- **The paper needs no edit for any of this**: it cites concept DOIs, which already resolve to
  what is published.

---

## One thing worth deciding separately

`docs/reference_tc/` holds sixteen third-party TC papers and is committed to a **public** GitHub
repository. They are excluded from the Zenodo archives, but that does not address the repo
itself: publisher PDFs and author preprints are readable under the terms each grants and
redistributable under almost none of them.

They have served their purpose — the referee corpus was declared settled and nothing in the
analysis reads them. The suggestion is to `git rm` the directory and keep a short `README.md` in
its place listing the sixteen papers by title, arXiv id and DOI, so the record of what informed
the judgement survives without redistributing the files. That is a one-commit change and it has
not been made, because removing published files from a public repository is the author's call.
