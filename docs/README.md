# What is in `docs/`, and which of it is current

Their names do not say which are live, so this page does.

**Nothing here is deleted when it goes out of date.** A superseded document says so at its top
and points at what replaced it. That is deliberate: several of these files are the evidence that
something was written down *before* the data existed, and a deleted file cannot be that.

Documents that belong together have been fused into one, each section carried over unchanged and
labelled with the file it came from. Fifteen files became four that way on 21 September 2026.

## Where the current answers live

Read these first. Everything else is background or history.

| | |
|---|---|
| [`results/README.md`](results/README.md) | **where every campaign stands, what has been found, what is out of reach.** Start here |
| [`../freezes/`](../freezes/) | the experiment plan, one folder per version, never edited |
| [`../cloud/azure/README.md`](../cloud/azure/README.md) | the kit that runs the campaigns, and how to drive it |
| [`infrastructure.md`](infrastructure.md) | the paper's reproducibility chain, hosts, and the Zenodo checklist |
| [`writing_standards.md`](writing_standards.md) | the prose rules, gated by `tests/unit/test_writing_standards.py` |
| [`supplement_index.md`](supplement_index.md) | what is in the supplement, section by section |

## The tests read from these

Change one and a test changes with it. They are not history.

| | |
|---|---|
| [`paper_revisions.md`](paper_revisions.md) | holds the five-tier stratification policy (`test_paper_consistency.py`) and the mapping from writing rules to sections (`test_writing_standards.py`) |
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

Each records a decision or a review, so a reader can check that a claim was made before its
evidence, or see what a reviewer actually asked for.

| | |
|---|---|
| [`preregistration_depth.md`](preregistration_depth.md) | the depth-suite analysis plan, committed before its data existed |
| [`reviews_and_responses.md`](reviews_and_responses.md) | every internal review (one to TPDS's standards, two to TC's) and the plan and letter that answered them |
| [`releases.md`](releases.md) | what each deposited version contained, one section per Zenodo deposit |
| [`paper_revisions.md`](paper_revisions.md) | the plans and drafts behind the paper's present shape |
| [`earlier_models.md`](earlier_models.md) | two models tried before the campaigns settled the mechanism, partly replaced by `laws.md` |

## Not in the repository

`tc_plan.md`, `outreach_candidates.md`, `humour_candidates.md`, `humour_prompt.md` and
`v5_supplement_plan.md` exist only on the author's machine — the last three excluded through
`.git/info/exclude`, the others simply never committed. They are listed here so their absence
from a clone is not mistaken for a missing file.

**They have no safety net.** Two documents in this position, `v3_plan.md` and
`v2_execution_log.md`, were destroyed on 21 September 2026 by a script that deleted its sources
after merging them; git had nothing to restore. What they were is recorded at the top of
[`paper_revisions.md`](paper_revisions.md). Anything in this list is one careless command from
the same fate.
