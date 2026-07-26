#!/usr/bin/env python3
"""
mutation_check.py
Break the manuscript on purpose, one claim at a time, and check the consistency suite notices.

The suite in tests/unit/test_paper_consistency.py exists to stop the paper drifting from its
artefacts. Nothing was checking the suite itself. Running this the first time found three tests
that passed on a manuscript where the thing they claimed to guard had been deleted:

  * the k=7 withdrawal test looked for the word "withdraw" anywhere in an eight-page section,
    and that word also appears in the M/G/1 paragraph;
  * the geometry-ratio test looked for "2.07" anywhere in the section, and the prose carries it
    as well as the table, so the table could say anything;
  * the uniform-denominator test checked the CSVs and never checked that the sentence quoting
    them says the same number.

Each mutation below is a defect the suite claims to catch. A mutation that leaves the suite green
is a test that is not testing, which is the same failure this paper is about: a check that cannot
fail tells you nothing when it passes.

The manuscript is restored from a backup in a finally block, so an interrupted run does not leave
a mutated paper.tex behind.

CLI:
    python scripts/mutation_check.py
    python scripts/mutation_check.py --paper paper.tex --tests tests/unit/test_paper_consistency.py

Exit status is 1 if any mutation went undetected.
"""
import argparse
import os
import shutil
import subprocess
import sys

# (name, original fragment, mutated fragment). Anchors are chosen to be single occurrences.
MUTATIONS = [
    ("drop the k=7 withdrawal",
     "we withdraw the\nstronger reading", "we accept the\nstronger reading"),
    ("wrong geometry ratio in the table",
     "$2.07\\times$, $2.05\\times$", "$2.77\\times$, $2.05\\times$"),
    ("understate the priority range",
     "cuts the inversion rate $7$ to $80\\times$", "cuts the inversion rate $7$ to $76\\times$"),
    ("wrong shared denominator",
     "is a proportion over $2{,}985$ matched", "is a proportion over $1{,}985$ matched"),
    ("re-conflate the two corpora",
     "We characterise the workload across $3{,}315$", "We drove the benchmark with $3{,}315$"),
    ("drop the mitigation's floor caveat",
     "The floor is not zero", "The floor is zero"),
    ("break a cross-reference",
     "Figure~\\ref{fig:window}", "Figure~\\ref{fig:nosuch}"),
    ("wrong traced-tail agreement",
     "they agree to $22\\%$", "they agree to $52\\%$"),
]


def run(paper, tests):
    backup = paper + ".mutbak"
    shutil.copy(paper, backup)
    src = open(paper, encoding="utf-8").read()
    undetected, skipped = [], []
    try:
        for name, old, new in MUTATIONS:
            if old not in src:
                skipped.append(name)
                print(f"  SKIP    {name} (anchor absent -- the claim may have been reworded)")
                continue
            open(paper, "w", encoding="utf-8", newline="").write(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "pytest", tests, "-q", "--no-header", "-x"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  CAUGHT  {name}")
            else:
                print(f"  MISSED  {name}")
                undetected.append(name)
    finally:
        shutil.copy(backup, paper)
        os.remove(backup)
    return undetected, skipped


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mutation-test the manuscript consistency suite")
    ap.add_argument("--paper", default="paper.tex")
    ap.add_argument("--tests", default="tests/unit/test_paper_consistency.py")
    args = ap.parse_args(argv)

    if not os.path.exists(args.paper):
        print(f"no such paper: {args.paper}")
        return 1

    print(f"== mutating {args.paper}, {len(MUTATIONS)} claims ==\n")
    undetected, skipped = run(args.paper, args.tests)
    print()
    if undetected:
        print(f"FAIL {len(undetected)} mutation(s) undetected:")
        for n in undetected:
            print(f"  - {n}")
        print("\nA test that passes on a broken manuscript is not guarding that claim.")
        return 1
    print(f"OK every mutation was caught"
          + (f" ({len(skipped)} skipped: anchors absent)" if skipped else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
