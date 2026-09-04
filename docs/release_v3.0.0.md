# Release v3.0.0 — four authors, prepared for deposit

**Status, 2026-09-04. RELEASED.** Both Zenodo records are published and the concept DOIs now
resolve to v3.0.0; the arXiv replacement is submitted and back in moderation. Nothing is
outstanding on this release except other people's answers — Gregg's biography, and the arXiv
identifier when it is announced.

| record | concept DOI (cited in the paper) | v3.0.0 version DOI |
|---|---|---|
| code / analysis / manuscript | `10.5281/zenodo.21650031` | **`10.5281/zenodo.22307766`** |
| measurement dataset | `10.5281/zenodo.21650064` | **`10.5281/zenodo.22307882`** |

**Read back after publication, from the API rather than the rendered page** — every item on
the checklist in section 2 below, and all of it passes:

- both concept DOIs resolve to the v3.0.0 records;
- version `3.0.0`, publication date `2026-09-04`, two files each;
- **all four creators present and in byline order** — Ricou, Duvignau, Herbst, Gregg — with
  ORCIDs on Ricou (`0009-0001-4196-7213`) and Herbst (`0000-0003-3462-6426`) and none guessed
  for the other two. This is the field the release existed to change, so it was read first;
- the md5 Zenodo reports for all four files matches the local archive byte for byte:
  `18db1e13…` and `99bcf621…` for the code pair, `4e7ca32e…` and `5c7b3169…` for the data pair;
- related works point at the sibling record's **concept** DOI, not a version DOI;
- the licence carve-out is in both descriptions, reading "© the authors".

**One thing to know when reading the archived copies.** This file and the README ship *inside*
the code archive, and the copies in there were written before the deposit: they say v3.0.0 is
"built and awaiting deposit" and give no version DOI, because at build time there was none. The
statements are dated, not wrong. The repository is corrected; a record cannot contain its own
DOI, which is exactly why the paper cites the concept DOIs instead.

Tag: `v3.0.0`, commit `894dbcc`, pushed. All three archives are built from that tag, not from
the working tree. Verified before hand-over:

| check | result |
|---|---|
| code archive | 842 files, 9.19 MB; `replay_plans` and `reference_tc` absent |
| `.zenodo.json` **inside** the archive | version `3.0.0`, four creators in byline order |
| `paper.pdf` inside the archive | 12 pages, byline reads all four names |
| `supplement.pdf` inside the archive | 54 pages |
| data archive | 491 files, 5.92 MB |
| arXiv bundle | 9 files, 1.18 MB; unzipped into an empty directory and compiled with `pdflatex` twice and **no BibTeX pass**: 0 errors, 0 undefined references, 0 unresolved citations, 0 overfull boxes, 12 pages |
| test suite at this commit | 4,175 passed, 35 skipped, 100.00% branch coverage |

`paper.bbl` is the one file in the arXiv bundle not taken from the tag, because it is a build
product and gitignored. The build refuses to run unless the working tree is clean and `HEAD`
is the tag, so it cannot smuggle uncommitted bytes into an archive that claims to be `v3.0.0`.

---

## 0. Why a major bump

A Zenodo record's **creators are part of its identity**, and this one goes from two names to
four. That is the whole argument; nothing else here would have justified more than a minor
bump.

| | v2.7.0 (deposited 2026-08-31) | v3.0.0 |
|---|---|---|
| authors | Ricou, Gregg | Ricou, **Duvignau**, **Herbst**, Gregg |
| paper | 12 pp, 7 figures | 12 pp, 5 figures, 44/45 refs |
| supplement | 49 pp | 54 pp |
| tools audited | 5 | 10 |
| tests | 3,866 | 4,175 |

### A correction, recorded rather than quietly fixed

This file first said **"v2.7.0 was tagged and bundled but never deposited"**, and repeated it
in the README, in both deposit descriptions and in the release commit. It is false. v2.7.0 was
published to Zenodo on 2026-08-31: code
[22215274](https://doi.org/10.5281/zenodo.22215274), data
[22215330](https://doi.org/10.5281/zenodo.22215330), both bylined to Ricou and Gregg.

The inference came from the repository: there was no v2.7.0 changelog entry, no v2.7 version
DOI written down anywhere, and `isNewVersionOf` still named v2.6.0. Every one of those is a
record we failed to update at the time, and reading their absence as evidence about **Zenodo**
rather than about **us** is the same mistake the paper is about — treating the instrument's
silence as a measurement. It was caught by opening the concept DOI in a browser, which is the
one check that could have caught it.

Three things it would have broken at deposit time, all of them silently:

- `--new-version` would have been handed the **v2.6.0** record id. Zenodo would have accepted
  it and forked the version chain off the wrong parent.
- `isNewVersionOf` in both metadata files named the v2.6.0 version DOI, so the published
  record would have asserted the wrong predecessor.
- Both descriptions and the README told the reader v2.7 does not exist.

All four are corrected, and the missing v2.7.0 changelog entry is now in the README.

---

## 1. What to deposit

| file | goes to |
|---|---|
| `dist/streaming-latency-sports-v3.0.0.zip` | Zenodo **code** record |
| `dist/SHA256SUMS-code-v3.0.0.txt` | Zenodo **code** record |
| `dist/streaming-latency-sports-data-v3.0.0.zip` | Zenodo **data** record |
| `dist/SHA256SUMS-data-v3.0.0.txt` | Zenodo **data** record |
| `dist/streaming-latency-arxiv-v3.0.zip` | arXiv |
| `dist/arxiv_v3.0_metadata.md` | the arXiv form (not uploaded; it is what you paste) |

Sizes and per-file digests are not repeated here, because this file ships inside the code
archive and any size it quoted would be a size it changed. Each `SHA256SUMS` manifest carries
the archive's own digest on line 3 and one line per file inside it.

The code archive contains `paper.pdf`, `paper.tex`, `supplement.pdf` and `supplement.tex` as
well as the scripts, tests and campaign ledgers. It does **not** contain
`data/processed/replay_plans` (CC BY-NC, derived from StatsBomb) or `docs/reference_tc`
(third-party TC papers, nobody's to redistribute). Both exclusions are enforced by git
pathspec in `scripts/zenodo_deposit.py`, so a file added under either path later is excluded
automatically rather than by anyone remembering.

---

## 2. Zenodo — new versions, same concept DOIs

A Zenodo *concept* DOI is stable across every version and always resolves to the newest; a
*version* DOI pins one release. The paper cites the **concept** DOIs, so a new *record* would
mint a new concept DOI and break the citation inside the PDF. It must be a new **version** of
each existing record.

| record | concept DOI (cited in the paper) | latest published version | v3.0.0 version DOI |
|---|---|---|---|
| code / analysis / manuscript | `10.5281/zenodo.21650031` | **22215274** — `10.5281/zenodo.22215274` (v2.7.0) | *minted on publish* |
| measurement dataset | `10.5281/zenodo.21650064` | **22215330** — `10.5281/zenodo.22215330` (v2.7.0) | *minted on publish* |

The bolded numbers are the **record ids** `--new-version` takes. They are the id of the latest
*published version*, never the concept id, and — as the correction above shows — never a guess
at which version that is. Open the concept DOI and read the id off the URL it lands on.

**The paper needs no edit for any of this.** It cites the concept DOIs and prints the version
from `.zenodo.json` through `\artifactVersion`, so the PDF inside the v3.0.0 archive says
`v3.0.0` without anyone typing it. That mechanism exists because it once said v2.6.0 from
inside the v2.7.0 archive.

### The command

```
python scripts/zenodo_deposit.py --new-version 22215274 --ref v3.0.0 \
    --zip dist/streaming-latency-sports-v3.0.0.zip
```

and for the dataset, whose archive is restricted to the two data paths:

```
python scripts/zenodo_deposit.py --new-version 22215330 --ref v3.0.0 \
    --zip dist/streaming-latency-sports-data-v3.0.0.zip \
    --metadata .zenodo-data.json --paths docs/results reproducibility
```

Both open a draft and stop. Upload the matching `SHA256SUMS` file to each draft by hand, then
publish in the browser. `--sandbox` rehearses on the separate sandbox site, which has its own
account and its own token. The token is read from `ZENODO_API_TOKEN` and never written to disk.

### Check after publishing, rather than assuming

- both concept DOIs resolve to the v3.0.0 records;
- each record carries exactly two files, and the md5 Zenodo reports matches the local archive;
- version reads `3.0.0`, publication date `2026-09-04`;
- **all four creators are present and in byline order** — Ricou, Duvignau, Herbst, Gregg — and
  Herbst carries ORCID `0000-0003-3462-6426`. This is the field the release exists to change,
  so it is the field to read back;
- related works point at the sibling record's **concept** DOI, not a previous version DOI;
- the licence carve-out is in both descriptions: MIT for the code, CC BY 4.0 for the data
  compilation and documentation, and the manuscript files © the authors and expressly *not*
  CC BY, included as a data complement pending journal publication. This is what keeps the
  IEEE copyright transfer clean.

**The web form does not commit every field the same way.** An edit that looks saved can
revert, particularly the description and the related-works rows, and only real keystrokes
commit them. Reload the page and re-read every field after saving. The edit form for a
*published* record is reachable only by clicking **Edit** on the record page; navigating
straight to `/uploads/<id>` redirects back to the record.

---

## 3. arXiv — DONE

`submit/7871792` was replaced on 2026-09-04 and **resubmitted**. Status: *processing*, no
expiry, back in the moderation queue it had been sitting in.

What was replaced, in order: every previously uploaded file deleted, then
`dist/streaming-latency-arxiv-v3.0.zip` uploaded. arXiv's own scan selected `pdflatex` and
`paper.tex` as the top level, recognised all nine files as used, tagged `anc/supplement.pdf`
ancillary, and marked nothing for deletion. Its compile **succeeded**: *"Output written on
paper.pdf (12 pages)"*, matching the local build exactly.

Metadata, read off the form before each field was overwritten:

| field | what it held | what it holds now |
|---|---|---|
| Title | already correct | untouched |
| Authors | **Ricou and Gregg only** | all four, in byline order |
| Abstract | the v2.7 wording | the current abstract, 1,313 characters |
| Comments | 12 pp, 7 figures, supplement 49 pp | 12 pp, **5 figures**, supplement **54 pp** |
| Primary / cross-list | cs.PF / cs.DC | untouched |
| ACM class | C.4; C.2.4 | untouched |
| Licence | arXiv non-exclusive | untouched — **never** CC, it would collide with the IEEE transfer |

**arXiv stores accented characters in TeX encoding.** It converted `W\"urzburg` on save and
said so; the preview renders it correctly. This costs a round trip: the metadata form has to be
saved *twice*, because the conversion pass re-displays the form without committing, and the
Preview page bounces back with "Complete earlier submission stages first" until it is saved
again. Not an error, but it looks like one.

**The PDF preview is a gate, not a courtesy.** Submit stays disabled until the article PDF has
actually been opened, and the page must then be reloaded for the button to unlock.

Editing did what the banner warned: it dropped the submission out of *on hold* to *incomplete*,
with a 2026-09-18 expiry, until it was resubmitted. That was the price of fixing the byline and
it was paid deliberately.

## 4. What is still open after this

- **Gregg's biography is unconfirmed.** He was sent a skeleton on 31 August and the full draft
  on 4 September and has replied to neither. His entry is drafted from his own public pages,
  and one fact inside it is genuinely uncertain: the Trinity research profile says
  **Professor**, the School staff page body text still says *"a lecturer in the Department of
  Computer Science"*. Professor stands because it is what the maintained page says. If he
  corrects it, correct `paper.tex` and cut v3.0.1 — a Zenodo version and an arXiv replacement
  each cost nothing, which is what makes publishing now the right call rather than a gamble.
- **arXiv identifier.** The replacement is submitted and in moderation. When it is announced,
  add the identifier as a related identifier on both Zenodo records and put the link in the
  README. Until then the Zenodo records deliberately do not name it.
- **Duvignau's complete pass** is scheduled for Tuesday 8 September. If it produces an
  objection of the kind his first one did, it lands as v3.1.0.
- **Journal submission** via the IEEE Author Portal, after the preprint is up.
