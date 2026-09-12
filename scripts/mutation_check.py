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
#
# Round 72 rebuilt this list, and the reason is the point of the file. Nine of the ten
# anchors below had gone stale -- the manuscript had been reworded around them over some
# thirty rounds -- and a stale anchor printed SKIP and returned 0, so the check reported
# success while guarding one claim. It said so in its own output every time and nobody read
# past "OK".
#
# Two rules came out of that, and both are enforced rather than written down:
#
#   1. A skipped mutation now fails. See main().
#   2. Anchor on a MACRO NAME or on prose, never on a rendered digit. Every number in this
#      manuscript is emitted from a ledger, so an anchor containing "$2{,}985$" dies the
#      first time the corpus grows -- and dies silently, which is worse than the drift it
#      was installed to catch. Mutating \GeomOrigFactor to \GeomReplFactor is a better test
#      anyway: it is the swap a careless edit actually makes, and it survives recomputation.
MUTATIONS = [
    # Round 72's required item, and the one anchor that was still live when the list was
    # rebuilt -- because it had just been re-anchored to fix the defect it failed to catch.
    ("re-conflate the two corpora",
     r"We characterize the full $\corpusMatches$-match corpus", "We replay $3{,}315$ matches"),
    # Round 72's other required item: the delivery and the transport proxy are four hundred
    # microseconds apart and Section II-A exists to keep them apart.
    ("print the proxy's range where the delivery's belongs",
     r"$\condDeliveryLoMs$--$\condDeliveryHiMs$~ms",
     r"$\condProxyLoMs$--$\condProxyHiMs$~ms"),
    # Round 71's required item: a measured range typed back into the sentence that claims
    # the schedule was measured.
    ("type the pacer jitter instead of emitting it",
     r"$\pacerJitterLo$--$\pacerJitterHi\,\mu$s", r"$67$--$69\,\mu$s"),
    # The two geometry factors are the same shape and one line apart, which is exactly the
    # swap a hurried edit makes and exactly the swap a reader cannot see.
    ("swap the two geometry factors in the table",
     r"$\GeomOrigFactor\times$ ($\GeomOrigZ$)",
     r"$\GeomReplFactor\times$ ($\GeomReplZ$)"),
    # Table I's margin: "zero negatives" is a fact about a threshold and the floor is the
    # fact about distance from it. Round 70 bought that clause; this keeps it bought.
    ("drop Table I's margin and leave only the zero",
     r"smallest run minimum $\spanAckLagFloorUs\,\mu$s clear of zero",
     "smallest run minimum clear of zero"),
    ("understate the priority range",
     r"the negative rate $\rtFactorLow$--$\rtFactorHigh\times$ at unchanged utilization",
     r"the negative rate $\rtFactorLow\times$ at unchanged utilization"),
    ("drop the mitigation's floor caveat",
     "the floor is not zero, so the check stays", "the floor is zero, so the check stays"),
    ("break a cross-reference",
     r"Figure~\ref{fig:spectrum} is the histogram", r"Figure~\ref{fig:nosuch} is the histogram"),
    # The tracer's three ratios bracket the observed rate rather than under-predicting it,
    # which is what makes the interpreter-lock rival bounded rather than waved away.
    ("type the traced ratios instead of emitting them",
     r"$\tracedRatios$, no consistent sign", "$0.78$, $1.06$ and $3.32$, no consistent sign"),
    # The equivalence is stated on the chain as well as on the proxy (round 72, W1), because
    # the proxy is the quantity Section II-A spends a subsection discrediting.
    ("state the broker equivalence on the proxy alone",
     r"and on \tti{}, which is a causal chain, against a wider margin over" + "\n"
     + r"the same levels (Supplement~S13). So it is not a purchasing argument.",
     "so it is not a purchasing argument."),
]


#: The files a mutation has to be caught by. One file was the default for thirty rounds, and
#: the claims this list guards have since spread across the round-by-round gates: a mutation
#: the consistency suite cannot see is not thereby harmless, it is guarded somewhere else.
DEFAULT_TESTS = (
    "tests/unit/test_paper_consistency.py",
    "tests/unit/test_printed_ranges.py",
    "tests/unit/test_round68_findings.py",
    "tests/unit/test_round70_findings.py",
    "tests/unit/test_round71_findings.py",
    "tests/unit/test_round72_findings.py",
)


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
            r = subprocess.run([sys.executable, "-m", "pytest", *tests,
                                "-q", "--no-header", "-x"],
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
    ap.add_argument("--tests", default=",".join(DEFAULT_TESTS),
                    help="comma-separated test paths the mutations must be caught by")
    args = ap.parse_args(argv)
    tests = [t for t in args.tests.split(",") if t]

    if not os.path.exists(args.paper):
        print(f"no such paper: {args.paper}")
        return 1

    print(f"== mutating {args.paper}, {len(MUTATIONS)} claims, "
          f"against {len(tests)} test file(s) ==\n")
    undetected, skipped = run(args.paper, tests)
    print()
    if undetected:
        print(f"FAIL {len(undetected)} mutation(s) undetected:")
        for n in undetected:
            print(f"  - {n}")
        print("\nA test that passes on a broken manuscript is not guarding that claim.")
        return 1
    if skipped:
        # A skip used to print and pass. It is the same outcome as an undetected mutation and
        # a quieter one: the claim this mutation exists to guard is no longer anchored to any
        # sentence, so nothing is testing it, and the run says OK.
        #
        # Round 72 paid for that. The anchor "We characterise the workload across 3,315" went
        # stale when the manuscript was reworded, this check printed SKIP and returned 0, and
        # the next pass wrote "We replay 3,315 matches" -- which is, within a synonym, the
        # mutated text this entry was written to detect. A referee found it by reading the
        # artefact, two months after the project had found it once already.
        print(f"FAIL {len(skipped)} mutation(s) skipped; their anchors are gone:")
        for n in skipped:
            print(f"  - {n}")
        print("\nA mutation whose anchor has vanished is an unguarded claim, not a pass. "
              "Re-anchor it to the sentence that carries the claim now, or delete the entry "
              "and say in the commit why the claim no longer needs guarding.")
        return 1
    print("OK every mutation was caught")
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
