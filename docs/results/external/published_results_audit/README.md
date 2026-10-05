# Registered audit of published OpenMessaging Benchmark results

The audit registered in `freezes/29-published-results-audit/` (committed 3b82667b, before any
report was read) asked whether published OMB end-to-end results sit in the deletion regime of
the paper's Section IV. It ran on 28 September 2026 under that registration, unchanged.

| File | What it is |
|---|---|
| `configurations.csv` | The coding: one row per configuration an included report prints, one per excluded report, each with the quote its numbers were copied from and, for exclusions, the reason. |
| `summary.md` | The four registered outcomes, the sensitivity readings and the cases the rules did not foresee. |
| `search_log.md` | Every query as run, where it was run, what it returned, and what could not be searched. |
| `code/` | The audit's own scripts: `rows_*.py` hold the coding report by report, and `build.py` writes `configurations.csv` from them, checking every quote against a saved copy of its source. |

The manuscript does not read `summary.md`. Its counts are recomputed from `configurations.csv`
by `reach_macros()` in `scripts/emit_paper_numbers.py`, and `tests/unit/test_emit_paper_numbers.py`
holds the rule on a hand-counted coding.

**The saved sources are not in this repository.** `search_log.md` and `build.py` refer to a
`raw/` folder: 3,759 files, 229 MB, of third-party web pages, PDFs, result files and API
responses, saved so that every quote could be checked mechanically. They are other people's
pages and are not ours to republish; the authors keep them, and `build.py` re-verifies the
coding against them on request. Every row of the coding carries its source URL.
