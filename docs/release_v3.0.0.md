# Release v3.0.0 — four authors, prepared for deposit

**Status, 2026-09-04.** Prepared, not yet published. Everything below is built and verified;
the two remaining steps are a human's: publish the Zenodo drafts, and replace the arXiv
submission. A published Zenodo record cannot be deleted, only superseded, so the last click
stays a decision rather than a script.

Tag: `v3.0.0`. Both archives are built from that tag, not from the working tree.

---

## 0. Why a major bump

A Zenodo record's **creators are part of its identity**, and this one goes from two names to
four. That is the whole argument; nothing else here would have justified more than a minor
bump.

| | v2.6.0 (deposited 2026-08-25) | v3.0.0 |
|---|---|---|
| authors | Ricou, Gregg | Ricou, **Duvignau**, **Herbst**, Gregg |
| title on the record | the old one | the manuscript's current one |
| paper | 12 pp, 8 figures, 45 refs | 12 pp, 5 figures, 44 refs |
| supplement | 46 pp | 54 pp |
| tests | 3,650 | 4,175 |

**v2.7.0 was tagged and bundled but never deposited.** There is no v2.7.0 Zenodo record and no
v2.7 arXiv replacement; `dist/` holds its artifacts and the git tag exists. This release
therefore carries v2.7's content as well as its own, which is why the changelog entry covers
both, and why `isNewVersionOf` in each metadata file still points at the **v2.6.0** version
DOI. Left deliberately: it names the previous *published* version, not the previous tag.

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
| code / analysis / manuscript | `10.5281/zenodo.21650031` | `10.5281/zenodo.22102716` (v2.6.0) | *minted on publish* |
| measurement dataset | `10.5281/zenodo.21650064` | `10.5281/zenodo.22102832` (v2.6.0) | *minted on publish* |

**The paper needs no edit for any of this.** It cites the concept DOIs and prints the version
from `.zenodo.json` through `\artifactVersion`, so the PDF inside the v3.0.0 archive says
`v3.0.0` without anyone typing it. That mechanism exists because it once said v2.6.0 from
inside the v2.7.0 archive.

### The command

```
python scripts/zenodo_deposit.py --new-version 22102716 --ref v3.0.0 \
    --zip dist/streaming-latency-sports-v3.0.0.zip
```

and for the dataset, whose archive is restricted to the two data paths:

```
python scripts/zenodo_deposit.py --new-version 22102832 --ref v3.0.0 \
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

## 3. arXiv

`submit/7871792` is the standing submission. It has been sitting with a **one-author list and
the old title** since August, which is the single most wrong thing in the public record right
now, and it is what this replacement fixes.

Replace in place with `dist/streaming-latency-arxiv-v3.0.zip` and resubmit. The metadata to
paste is in `dist/arxiv_v3.0_metadata.md`, with every changed field marked.

Two things worth knowing before starting. Editing a submission that is on hold moves it out of
moderation back to *incomplete* — that is the expected cost of changing it, not a failure, and
it re-enters the queue on resubmit. And the account is capped at three in-process submissions;
that cap produced a spurious refusal mid-edit once before and cleared on its own.

---

## 4. What is still open after this

- **Gregg's biography is unconfirmed.** He was sent a skeleton on 31 August and the full draft
  on 4 September and has replied to neither. His entry is drafted from his own public pages,
  and one fact inside it is genuinely uncertain: the Trinity research profile says
  **Professor**, the School staff page body text still says *"a lecturer in the Department of
  Computer Science"*. Professor stands because it is what the maintained page says. If he
  corrects it, correct `paper.tex` and cut v3.0.1 — a Zenodo version and an arXiv replacement
  each cost nothing, which is what makes publishing now the right call rather than a gamble.
- **arXiv identifier.** When the submission is announced, add it as a related identifier on
  both Zenodo records and put the link in the README.
- **Duvignau's complete pass** is scheduled for Tuesday 8 September. If it produces an
  objection of the kind his first one did, it lands as v3.1.0.
- **Journal submission** via the IEEE Author Portal, after the preprint is up.
