# What is in `docs/`, and which of it is current

Thirty-odd files, and their names do not say which are live. This page does. It exists because
the alternative offered was deleting some of them, and on inspection every candidate turned out
to be carrying something: a policy the tests enforce, the provenance of a decision, or research
material that took real work to gather.

**Nothing here is deleted when it goes out of date.** A superseded document says so at the top
and points at what replaced it. That is deliberate — several of these files are the evidence
that something was written down *before* the data existed, and a deleted file cannot be that.

## Where the current answers live

These are the pages to read first. Everything else is background or history.

| | |
|---|---|
| [`results/README.md`](results/README.md) | **where every campaign stands, what has been found, what is out of reach.** Start here |
| [`../freezes/`](../freezes/) | the experiment plan, one folder per version, never edited |
| [`../cloud/azure/README.md`](../cloud/azure/README.md) | the kit that runs the campaigns, and how to drive it |
| [`infrastructure.md`](infrastructure.md) | the paper's reproducibility chain, hosts, and the Zenodo checklist |
| [`writing_standards.md`](writing_standards.md) | the prose rules, gated by `tests/unit/test_writing_standards.py` |
| [`supplement_index.md`](supplement_index.md) | what is in the supplement, section by section |

## Documents the tests read from

Change these and a test changes with them. They are not historical.

| | |
|---|---|
| [`v2_plan.md`](v2_plan.md) | holds the five-tier stratification policy; `test_paper_consistency.py` enforces it |
| [`v4_restructure_plan.md`](v4_restructure_plan.md) | the mapping from writing rules to sections, behind `test_writing_standards.py` |
| [`campaign_ledger_schema.md`](campaign_ledger_schema.md) | the schema of `results/external_campaigns_index.csv` |
| [`laws.md`](laws.md), [`measurement_model.md`](measurement_model.md), [`tc_plan.md`](tc_plan.md) | cited by `paper.tex` itself |

## Research material

Gathered evidence, not process. Slow to rebuild if lost.

| | |
|---|---|
| [`grey_literature_review.md`](grey_literature_review.md) | practitioner sources on latency-measurement failure, surveyed and verified |
| [`reference_tc/README.md`](reference_tc/README.md) | the reference material behind the TC submission |
| [`outreach_candidates.md`](outreach_candidates.md) | fifty shortlisted researchers, with reasons |
| [`omb_distributed_issue.md`](omb_distributed_issue.md) | the OpenMessaging finding |
| [`results/external/INVALID/`](results/external/INVALID/) | results found invalid, kept with the reason |

## Provenance — why things are the way they are

Each records a decision or a review. They are what lets a reader check that a claim was made
before its evidence, or see what a reviewer actually asked for.

| | |
|---|---|
| [`preregistration_depth.md`](preregistration_depth.md) | the depth-suite analysis plan, committed before the data existed |
| [`referee_response_plan.md`](referee_response_plan.md), [`referee_response_letter.md`](referee_response_letter.md) | how the review was answered |
| `response_to_referee_tc.md`, `response_to_referee_tc_r2.md`, `response_to_referee_tpds.md` | internal review rounds, each labelled as internal |
| [`release_v2.6.0.md`](release_v2.6.0.md), [`release_v3.0.0.md`](release_v3.0.0.md) | what each deposited version contained |

## Superseded, kept for the record

Still readable, no longer the answer. Each says so at its own top.

| | |
|---|---|
| [`v3_plan.md`](v3_plan.md), [`v2_execution_log.md`](v2_execution_log.md) | how versions 2 and 3 were planned and executed |
| [`section67_rewrite_draft.md`](section67_rewrite_draft.md) | a draft never applied; its checklist records which sites were updated instead |
| [`two_state_model.md`](two_state_model.md), [`general_model.md`](general_model.md) | earlier models, partly replaced by `laws.md` |

## Not in the repository

`humour_candidates.md`, `humour_prompt.md` and `v5_supplement_plan.md` are on the author's
machine only, excluded through `.git/info/exclude`. The last of those quotes private mail. They
are listed here so that their absence from a clone is not mistaken for a missing file.
