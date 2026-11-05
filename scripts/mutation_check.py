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
    # 5 Oct 2026: the paper was rebuilt around its four bottom lines. Six claims survive and are
    # re-anchored on the sentences that now carry them. Four died with their sentences and are
    # retired: the replayed corpus beside the whole one, the pacer jitter, Table I's margin and
    # the broker equivalence, none of which the paper prints any more.
    #
    # Round 72's other required item: the delivery and S are four hundred microseconds apart, and
    # the slice is compared with the delivery's range, not with S's.
    ("print S's range where the delivery's belongs",
     r"$\condDeliveryLoMs$--$\condDeliveryHiMs$~ms",
     r"$\condProxyLoMs$--$\condProxyHiMs$~ms"),
    # The two placement factors are the same shape and one clause apart, which is exactly the
    # swap a hurried edit makes and exactly the swap a reader cannot see.
    # 6 Oct 2026: the interval beside the first factor resamples whole runs now, not Katz's.
    # 3 Nov 2026: the two factors share one sentence and their intervals follow in the next
    # (no words in brackets); the anchor is the pair of factors, and the swap is the same.
    ("swap the two placement factors",
     r"$\GeomOrigFactor$-fold, and $\GeomReplFactor$-fold",
     r"$\GeomReplFactor$-fold, and $\GeomOrigFactor$-fold"),
    # 15 Oct 2026: the range is Section IV-B's now, where the Computer Society layout breaks the
    # line between its two ends; the mutation prints the low end twice.
    ("understate the priority range",
     r"$\rtFactorHigh$-fold on \kafka{} and",
     r"$\rtFactorLow$-fold on \kafka{} and"),
    # 15 Oct 2026: the caveat reads "settles ... on \redis{}, not at zero" in Section VI.
    # 17 Oct 2026: it reads "... on \redis{} (Supplement~S3.1), so the sign check stays", the
    # ranges themselves the caveat; the mutation sends the rate to zero and drops the check.
    # 3 Nov 2026, the author's rule against invented terms: it reads "... (Supplement~S3.1), so
    # the check stays", the check for values below zero; the swap is the same.
    ("drop the caveat that the rate stays above zero",
     r"(Supplement~S3.1), so the check", r"(Supplement~S3.1), and at zero, so no check"),
    ("break a cross-reference",
     r"(Fig.~\ref{fig:twoways})", r"(Fig.~\ref{fig:nosuch})"),
    # The tracer's ratios bracket the observed rate rather than under-predicting it, which is
    # what makes the interpreter-lock rival bounded rather than waved away. 6 Oct 2026: the
    # sentence quotes the ratios against both brokers' runs, which the trace counts, so the
    # anchor follows it.
    # 15 Oct 2026, referees A (M6(a)) and B (S5) of version 9: the main text quotes the trace's
    # agreement at every threshold, through the threshold table's macros.
    # 3 Nov 2026: moved to Supplement S3.5 by the author's decision, so that the paper fits the
    # journal's 12 free pages. The paper says in words that the trace agreed at every threshold;
    # S3.5 quotes the ratios through the threshold table's macros, and the anchor follows them
    # there. The fourth field names the document the mutation edits, beside the paper.
    ("type the traced ratios instead of emitting them",
     r"$\tracedThresholdRatioLo$--$\tracedThresholdRatioHi$ (Table~\ref{stab:tracethreshold})",
     r"$0.63$--$1.61$ (Table~\ref{stab:tracethreshold})",
     "supplement.tex"),
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


def _target(paper, mutation):
    """The file a mutation edits: the paper, or the document beside it that the entry names.

    3 Nov 2026: a claim whose sentence moved to the supplement takes its anchor with it, so an
    entry may carry a fourth field, the document's name beside the paper."""
    if len(mutation) > 3:
        return os.path.join(os.path.dirname(paper), mutation[3])
    return paper


def run(paper, tests):
    targets = []
    for mutation in MUTATIONS:
        target = _target(paper, mutation)
        if target not in targets and os.path.exists(target):
            targets.append(target)
    sources = {}
    for target in targets:
        shutil.copy(target, target + ".mutbak")
        sources[target] = open(target, encoding="utf-8").read()
    undetected, skipped = [], []
    try:
        for mutation in MUTATIONS:
            name, old, new = mutation[:3]
            target = _target(paper, mutation)
            src = sources.get(target, "")
            if old not in src:
                skipped.append(name)
                print(f"  SKIP    {name} (anchor absent -- the claim may have been reworded)")
                continue
            open(target, "w", encoding="utf-8", newline="").write(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "pytest", *tests,
                                "-q", "--no-header", "-x"],
                               capture_output=True, text=True)
            # Each mutation starts from every document as it was: put this one back before the
            # next mutation edits another.
            open(target, "w", encoding="utf-8", newline="").write(src)
            if r.returncode != 0:
                print(f"  CAUGHT  {name}")
            else:
                print(f"  MISSED  {name}")
                undetected.append(name)
    finally:
        for target in targets:
            shutil.copy(target + ".mutbak", target)
            os.remove(target + ".mutbak")
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
