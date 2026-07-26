#!/usr/bin/env python3
"""
trace_table_numbers.py
Ask, of every numeric cell in every manuscript table: does this value exist in the artefact that
table is supposed to come from?

The consistency tests check the numbers we thought to check. This asks the complementary
question -- which numbers is nobody checking -- and that question found E-A9 and the tail index
quoted in the abstract and reported nowhere in the body, and a 76x that should have been 80x.

**Why each table is scoped to its own artefact.** The first version of this script searched every
committed CSV for each value. It reported all 237 cells traced, and it was vacuous: the corpus
holds thousands of per-run utilisation figures, so essentially any plausible four-decimal value
between 0 and 1 matches something by coincidence. Planting a wrong rho into tab:ea6 was not
caught. Scoped to that table's own artefact, it is. A check that cannot fail is not a check.

Tables with no declared source are reported as UNMAPPED rather than passing, because "we did not
look" and "we looked and it was fine" must not print the same way.

**What this tool cannot establish, stated plainly.** A cell only traces if the analysis script
wrote that exact value to the artefact. Most manuscript tables print *derived* quantities --
medians over runs, ratios between arms, two-proportion z scores -- which are computed from the
artefact and never stored in it. For those, "untraced" means "not verifiable by string matching",
not "wrong". So this script cannot be a build gate, and it is not wired into one. Its output is a
worklist: every cell it cannot trace is a cell whose correctness rests on a test that recomputes
it from source, and the useful question is whether such a test exists. Those tests live in
tests/unit/test_paper_consistency.py; this script exists to keep the set of numbers relying on
them visible rather than assumed.

CLI:
    python scripts/trace_table_numbers.py
    python scripts/trace_table_numbers.py --paper paper.tex --results docs/results
"""
import argparse
import csv
import glob
import os
import re

# Which artefact each table's numbers must come from. Several tables draw on more than one file
# (a summary plus its test output), so the value is a list.
SOURCES = {
    "tab:ea5":      ["model/stamping_priority.csv", "model/stamping_priority_ea5b.csv",
                     "model/stamping_priority_ea7.csv"],
    "tab:ea6":      ["model/ea6/knee_resolution.csv"],
    "tab:ea9":      ["model/runq_tail.csv"],
    "tab:ea10":     ["model/ttrue_sweep.csv"],
    "tab:mixture":  ["model/collapse_points.csv", "model/collapse_conditions.csv",
                     "model/separability.csv", "model/two_state_fit.csv"],
    "tab:h2":       ["model/knee_resolution.csv", "model/knee_points.csv"],
    "tab:h3":       ["model/ec3_stamping.csv", "depth_rep2/model/ec3_stamping.csv"],
    "tab:window":   ["window/window_sweep.csv"],
    "tab:e1":       ["e1/e1_transport_kafka_vs_redis_by_n.csv", "e1/e1_by_run_gated.csv",
                     "e1/e1_transport_kruskal_across_n.csv"],
    "tab:e1rep":    ["transport_rt/transport_realtime_summary.csv",
                     "transport_rt/transport_realtime_tost.csv",
                     "transport_rt2/transport_realtime_tost.csv"],
    "tab:transport": ["transport_rt/transport_realtime_summary.csv",
                      "transport_rt/transport_realtime_tost.csv"],
    "tab:retention": ["e1/e1_retention_bias.csv"],
    "tab:audit":    ["integrity_windows/clock_integrity_by_condition.csv",
                     "e1/e1_clock_integrity.csv"],
    "tab:workload": ["football/feed/feed_summary.csv",
                     "football/concurrency/concurrency_summary.csv"],
    "tab:netem":    ["model/clean_effect_size.csv"],
    "tab:eb2":      ["model/clean_effect_size.csv"],
}

# Cells that are structure rather than measurement: column indices, N levels, run counts.
STRUCTURAL = re.compile(r"^\d{1,3}$")
# Values the text defines rather than measures.
DECLARED = {"0.05", "0.01", "1.0", "40", "0.5", "0.001", "0.003", "0.004"}


def table_blocks(tex):
    """(label, tabular body) for every table environment carrying a label."""
    out = []
    for m in re.finditer(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", tex, re.S):
        body = m.group(1)
        lab = re.search(r"\\label\{([^}]*)\}", body)
        if not lab:
            continue
        tab = re.search(r"\\begin\{tabular\}.*?\\end\{tabular\}", body, re.S)
        out.append((lab.group(1), tab.group(0) if tab else body))
    return out


def numbers_in(block):
    """Numeric cells, with LaTeX thousands separators and math markup removed."""
    txt = block.replace("{,}", "").replace("\\,", "").replace("$", "")
    txt = re.sub(r"\\times|\\pm|\\%|\\multicolumn\{[^}]*\}|\\cmidrule[^\n]*", " ", txt)
    txt = re.sub(r"10\^\{-?\d+\}", " ", txt)
    found = re.findall(r"-?\d+\.?\d*", txt)
    return [f for f in found if not STRUCTURAL.match(f) and f not in DECLARED]


def _roundings(v):
    out = set()
    for nd in range(0, 6):
        out.add(f"{v:.{nd}f}")
        out.add(f"{round(v, nd):g}")
    if v:
        for nd in (1, 2, 3):
            out.add(f"{1 / v:.{nd}f}")     # ratios are often the reciprocal of a stored fraction
            out.add(f"{abs(v):.{nd}f}")
    return out


def corpus_for(results_dir, rel_paths):
    """Every numeric token in the named artefacts, at several roundings."""
    corpus = set()
    for rel in rel_paths:
        path = os.path.join(results_dir, rel)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                for cell in (c.strip() for c in row if c):
                    corpus.add(cell)
                    try:
                        corpus |= _roundings(float(cell))
                    except ValueError:
                        # Some cells pack several k=v pairs; harvest the numbers inside.
                        for part in re.findall(r"-?\d+\.?\d+", cell):
                            corpus.add(part)
                            corpus |= _roundings(float(part))
    return corpus


def trace(tex, results_dir, sources=None):
    sources = SOURCES if sources is None else sources
    report = []
    for label, block in table_blocks(tex):
        cells = numbers_in(block)
        if label not in sources:
            report.append({"label": label, "cells": len(cells), "untraced": [],
                           "mapped": False})
            continue
        corpus = corpus_for(results_dir, sources[label])
        report.append({"label": label, "cells": len(cells),
                       "untraced": [n for n in cells if n not in corpus], "mapped": True})
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trace manuscript table numbers to their artefacts")
    ap.add_argument("--paper", default="paper.tex")
    ap.add_argument("--results", default="docs/results")
    args = ap.parse_args(argv)

    tex = open(args.paper, encoding="utf-8").read()
    report = trace(tex, args.results)

    mapped = [r for r in report if r["mapped"]]
    unmapped = [r for r in report if not r["mapped"]]
    bad = [r for r in mapped if r["untraced"]]
    cells = sum(r["cells"] for r in mapped)
    print(f"== {len(mapped)} tables scoped to their artefacts, {cells} measured cells ==\n")
    for r in sorted(mapped, key=lambda r: -len(r["untraced"])):
        mark = "OK  " if not r["untraced"] else "FAIL"
        print(f"  {mark} {r['label']:16s} {r['cells']:3d} cells"
              + (f"  untraced: {r['untraced'][:8]}" if r["untraced"] else ""))
    if unmapped:
        print(f"\n  UNMAPPED (not checked, not passing): "
              f"{', '.join(r['label'] for r in unmapped)}")
    if bad:
        print("\n  Cells above are not necessarily wrong: derived quantities -- medians over")
        print("  runs, ratios between arms, z scores -- are computed from the artefact and are")
        print("  never stored in it. Each one needs a test that recomputes it from source.")
    # Always 0. This is a worklist, not a gate; see the module docstring for why string
    # matching cannot decide a derived cell.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
