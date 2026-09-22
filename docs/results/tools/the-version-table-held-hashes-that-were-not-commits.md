# The version table held hashes that were not commits, and what else was checked because of it

**22 September 2026.** Not a test of any prediction. An instrument fault, its cause, how far it
reached, and an audit of every other identifier in this repository that could have the same
shape.

**Words used here.** *Pin* — the exact version of a tool a run is made against. *Commit hash* —
the forty hexadecimal characters naming one revision of a repository. *T5* — the desk audit of
what ten benchmarking tools' own documentation and source say, frozen in freeze 08. *T1–T4* —
the machine runs of those tools, which had not started.

## What was found

`cloud/azure/tools.sh` carries a table of the version of each tool the block runs. On 22
September every hash in it was asked of its own repository, the first time any of them had been.
**Five of the six were not commits:**

| tool | the table said | GitHub says |
|---|---|---|
| vegeta | `cf5811269046…9d5b58` | 422 — no commit with that SHA |
| hey | `5626f79b8698…7dbd9e` | 422 |
| memtier_benchmark | `5694a3d61aaf…5de40e` | 422 |
| rdkafka_performance | `6f86c853a131…6c2337` | 422 |
| kafka-end-to-end, kafka-producer-perf | `995cfcf99f79…89d1b2` | 422 |
| k6 | `3fcf5388d78c` | **real** |

GitHub's commit search finds each of the five in **zero repositories anywhere**, so they are not
commits recorded against the wrong project. They are not commits.

## Where they came from

Not from outside. This repository has one author across all 648 of its commits, and the only
other committer is GitHub's web interface on three merges. They entered in `e6870e38` on 20
September, the commit that created `cloud/azure/tools.sh`.

The real versions were in the repository the whole time. `data/tools_audit/batch_*.json` — T5's
own records — carry a dated "version seen" for every one of the ten tools, and **every hash in
them answers 200**. The audit did its work properly.

What went wrong was the copy into the table, and the shape of the damage says so. Each wrong
hash shares its first 28 to 34 characters with the audit's and differs only in the tail:

```
vegeta   audit  cf5811269046c672a604b1eb352204d30f16ae4a
         table  cf5811269046c672a604b1eb352204d30f9d5b58     same through "...204d30f"
hey      audit  5626f79b8698df6daf9b25799c9805c6acc96740
         table  5626f79b8698df6daf9b25799c9805c6ac7dbd9e     same through "...9805c6ac"
```

and the same for memtier, librdkafka and Kafka. These are transcriptions whose tails were
regenerated rather than copied — a narrower fault than "invented from nothing", and worth saying
exactly. Three more tools — wrk2, rabbitmq-perftest and nats-latency — sat in the table as
`resolve`, meaning "not pinned yet", although the audit had a real commit for each.

## Why it survived two days

Nothing read the table. The `install` step that would have fetched those commits fetched nothing:
it installed build dependencies, printed the pins, and reported which binaries happened to be on
the machine already. Every tool came back MISSING and the step called that a complete run.

So the first time any of these hashes was asked of its own repository was two days later, when
`install` was made to actually install. A table nothing reads is a table nothing checks.

It also sat beside a great deal of real and checkable work in the same commit — that
`rdkafka_performance` divides every figure by `1000.0f` before printing, that `memtier_benchmark`
has gained a p99.9 column so counting fields from the left reads a different percentile, that
`valkey-benchmark`'s summary must be read through its headers. All of that was done against the
tools' own source and all of it holds. The version table was not, and it inherited the
credibility of the work next to it.

## How far it reached

**Nothing that has been published or frozen rests on it.**

- T5, the audit frozen in freeze 08, does not cite the table. It has its own records, and those
  are sound.
- T1–T4 had never run on a machine, so no result was produced from a wrong build.
- The hashes appear nowhere else in the repository: no note, no manuscript, no deposit.

The one thing that did reach a machine: on 22 September, before the table was corrected, the
broker built its tools from whatever was HEAD that morning and five T3/T4 runs for vegeta were
made against that build. They are quarantined under `runs/azure/tools_quarantine_20260922/` with
their reason, and the tools were rebuilt at the audit's commits. No run in them counts.

## The table now

Taken from the audit, for all ten tools, and each one re-checked against its own upstream on
22 September:

```
vegeta               cf5811269046c672a604b1eb352204d30f16ae4a   master, 2026-02-16
hey                  5626f79b8698df6daf9b25799c9805c6acc96740   master, 2026-01-10
k6                   3fcf5388d78c                               master, 2026-09-18
valkey-benchmark     9.1.2                                      release, 2026-09-01
memtier_benchmark    5694a3d61aaf0322a62fc44083ba6f2130b16265   master, 2026-09-01
rdkafka_performance  6f86c853a131d66fc2cd2a44aac99e83de859b4e   master, 2026-09-17
kafka-*              995cfcf99f7917403e030428c00b5c51808ddc61   trunk, 2026-09-19
wrk2                 44a94c17d8e6a0bac8559b53da76848e430cb7a7   HEAD, 2019-09-23
rabbitmq-perftest    ba718d2eae542ee5557a676f5454d4492739e714   2026-09-18
nats-latency         cc0a8e3224d564b134a92f6f2c2081452f885549   2026-09-17
```

An earlier fix pinned the table to whatever was HEAD on the day the tools installed. That was
honest and still wrong: the plan says the block runs at the versions the audit read, and HEAD on
an arbitrary morning is a build the audit never looked at.

## Everything else of that shape, checked

A fabricated identifier is a class of fault, not one incident, so the rest of the repository was
asked the same question: is there anything here that looks fetched and was not?

| what | how many | result |
|---|---|---|
| commit hashes in `cloud/azure/tools.sh` | 6 | **5 were not commits** |
| commit hashes in `data/tools_audit/` (T5's records) | 10 | all real |
| every other 40-hex string in the repository | — | all are this project's own commits, the pinned StatsBomb corpus, or vendor build strings in logs |
| DOIs in `manuscript_references.bib` | 16 | 15 resolve; **1 resolved to nothing** |
| numbers of every cited reference, against Crossref | 125 cited | 38 agree, 82 Crossref does not index, **5 flagged** |
| arXiv identifiers cited | 4 | all real, titles match exactly |
| URLs in cited references | 13 | all answer 200 |
| Zenodo DOIs this repository publishes | 14 | all real, titles match |
| authors across the whole git history | 648 commits | one, plus GitHub's web interface on three merges |

**No cited work is fabricated.** Of the five references flagged by their numbers, three are the
checker being naive and two are a style choice:

- `barrett2017warmup` gives pages as `52:1--52:27`, the article-number form PACMPL uses; Crossref
  stores `1-27`. Nothing wrong.
- `lamport1978time` and `rfc7679` carry no DOI, so the checker searched by title and matched, in
  the first case a 2019 ACM anthology reprint of Lamport's 1978 paper, and in the second RFC 2679
  of 1999, which shares its title and which RFC 7679 obsoletes. Both entries are right; the
  checker was matching the wrong thing.
- `fruth2021telltale` and `yue2024streamsurvey` give the conference year where Crossref gives the
  Springer publication year, a year later in both cases. A convention, not an error, and left as
  it is rather than changed quietly.

**One reference was genuinely wrong**, and it is the one that shows why checking a title is not
enough. `tahir2022delayed` named a real paper by its real authors and then gave the wrong volume,
the wrong issue, the wrong pages, the wrong year and a DOI that resolves to nothing:

| | the entry said | the paper is |
|---|---|---|
| volume | 71 | **72** |
| issue | 9 | **6** |
| pages | 1975–1988 | **1610–1622** |
| year | 2022 | **2023** |
| DOI | `10.1109/TC.2021.3131240` — resolves to nothing | `10.1109/TC.2022.3215907` |

Corrected, with a note in the entry recording what it said before. The supplement cites it, so
the key is unchanged.

## What this class of fault looks like

Three things were true of every instance, and any one of them is worth treating as a warning:

1. **The identifier sat beside work that was real and checkable**, and borrowed its credibility.
   The commit that wrote the bad version table also established, correctly and against the tools'
   own source, that `rdkafka_performance` divides by `1000.0f` before printing.
2. **Nothing consumed it.** The version table was never read by anything until the install step
   was made to install; `tahir2022delayed`'s DOI was never resolved. An identifier nothing
   fetches is an identifier nothing can contradict.
3. **It was plausible.** Forty hex characters, a DOI in the right registrant's prefix, a volume
   and page range of the right magnitude. Plausibility is the whole problem: an implausible
   identifier would have been caught on sight.

The practical rule that follows: **write the blank rather than the guess**, and add the step that
consumes a table in the same change that adds the table.
