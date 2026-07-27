#!/usr/bin/env python3
"""
check_paper_omb_numbers.py
Do the numbers Section 6.7 quotes still match the campaign ledger?

The manuscript states, in its artefact section, that a consistency suite recomputes its quoted
quantities from committed CSVs and fails if the two disagree. That was true of the original
results and not of the external-benchmark section, which quotes a run count in eight places and a
discard total in four. Those counts move every time a campaign lands, and a number updated in
seven places out of eight is worse than one that was never checked -- it looks verified.

This recomputes each quoted quantity from `external_campaigns_index.csv` and compares. It does not
edit the manuscript: a mismatch is reported for a human to resolve, because the right fix is
sometimes to change the prose rather than the number.

Exit status is non-zero when any check fails, so it can gate a build.

CLI:
    python scripts/check_paper_omb_numbers.py
    python scripts/check_paper_omb_numbers.py --ledger docs/results/external_campaigns_index.csv
"""
import argparse
import csv
import os
import re
import sys

# Campaigns that constitute "the external campaign" as the paper describes it. The early
# smoke/idem cells predate the shutdown hook and are excluded from every analysis by rule, so
# quoting a run count that included them would misdescribe what the section reports.
PAPER_CAMPAIGNS = {
    "load_sweep", "load_sweep_p2", "load_sweep_nowarmup", "resolution",
    "rate_phase", "rate_phase2", "bimodality", "tprobe",
}

# A cell only carries a claim if its counts came from the shutdown hook; the periodic lines are
# quantised to 10,000 (see index_external_campaigns.py).
def load_cells(path):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows
            if r.get("campaign") in PAPER_CAMPAIGNS
            and r.get("valid") == "1"
            and r.get("count_source") == "shutdown_hook"]


def _int(row, key):
    try:
        return int(row.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def measured(cells):
    """Everything the paper quotes about the external campaign, recomputed."""
    kept = sum(_int(c, "kept") for c in cells)
    zero = sum(_int(c, "discarded_zero") for c in cells)
    neg = sum(_int(c, "discarded_negative") for c in cells)
    shares = []
    for c in cells:
        k, z, n = _int(c, "kept"), _int(c, "discarded_zero"), _int(c, "discarded_negative")
        seen = k + z + n
        if seen:
            shares.append(100.0 * k / seen)
    return {
        "n_runs": len(cells),
        "discarded_total": zero + neg,
        "negatives": neg,
        "kept_total": kept,
        "retention_min": min(shares) if shares else None,
        "retention_max": max(shares) if shares else None,
    }


# Each claim: a label, a regex over paper.tex, and a function of the measured dict giving the
# value the manuscript ought to be quoting.
CLAIMS = [
    ("run count",
     r"\$(\d+)\$ (?:instrumented )?runs|ran the benchmark \$(\d+)\$ times|across all \$(\d+)\$ runs",
     lambda m: m["n_runs"], 0),
    ("discarded total",
     r"roughly \$(\d{1,3})\{,\}(\d{3})\$ discarded samples",
     lambda m: m["discarded_total"], -3),
    ("negative count",
     r"\\textbf\{not one negative\}|contain \\emph\{not one negative\}",
     lambda m: m["negatives"], None),
]


# The manuscript quotes run counts for several different campaigns -- ours as well as the external
# one -- so a bare "$N$ runs" cannot be assumed to mean this campaign. Matching greedily flagged
# "$25$ runs each" (our mixture sweep) and "$164$ runs" (our producer-offset result) as errors.
# These patterns are the phrasings used specifically for the external benchmark.
OMB_RUN_PATTERNS = [
    r"Across \$(\d+)\$ runs we find",
    r"Across \$(\d+)\$ instrumented runs",
    r"swept it across \$(\d+)\$ runs",
    r"ran it, \$(\d+)\$ times",
    r"\$(\d+)\$ instrumented runs on the co-located path",
    r"across all \$(\d+)\$ runs",
    r"\$(\d+)\$-run campaign",
    r"ran the benchmark \$(\d+)\$ times",
]

# The unsaturated subset is a legitimately smaller number and is checked against its own quantity.
OMB_SUBSET_PATTERNS = [
    r"Across the \$(\d+)\$ runs on an unsaturated path",
]


def find_quoted_run_counts(src, patterns=None):
    """Run counts the manuscript quotes *for the external campaign*, with line numbers."""
    pats = [re.compile(p) for p in (patterns or OMB_RUN_PATTERNS)]
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        for pat in pats:
            for m in pat.finditer(line):
                out.append((int(m.group(1)), i))
    return out


def find_quoted_discard_totals(src):
    """Discard totals quoted near the word 'discarded', in either form the paper uses.

    Two forms must both be recognised, and an earlier version handled only the first:
    a LaTeX-separated integer with any number of groups (`$3{,}538{,}341$`), and a
    rounded figure in millions (`$3.5$ million`). The single-separator pattern silently
    matched nothing once the total passed a million, which is precisely when the number
    needed checking most.
    """
    out = []
    exact = re.compile(r"\$(\d{1,3}(?:\{,\}\d{3})+)\$[^.\n]{0,40}?discarded")
    millions = re.compile(r"\$([\d.]+)\$\s*million[^.\n]{0,40}?discarded")
    for i, line in enumerate(src.splitlines(), 1):
        for m in exact.finditer(line):
            out.append((int(m.group(1).replace("{,}", "")), i))
        for m in millions.finditer(line):
            out.append((int(round(float(m.group(1)) * 1_000_000)), i))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check Section 6.7's numbers against the ledger")
    ap.add_argument("--ledger", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--paper", default="paper.tex")
    ap.add_argument("--tolerance-pct", type=float, default=0.0,
                    help="allowed relative slack on rounded totals, e.g. 2 for 2%%")
    args = ap.parse_args(argv)

    for p in (args.ledger, args.paper):
        if not os.path.exists(p):
            print("missing: %s" % p)
            return 1

    cells = load_cells(args.ledger)
    if not cells:
        print("no admissible cells in %s -- nothing to check against" % args.ledger)
        return 1
    m = measured(cells)
    src = open(args.paper, encoding="utf-8", errors="replace").read()

    print("== measured from the ledger ==")
    print("  admissible runs        : %d" % m["n_runs"])
    print("  discarded (zero+neg)   : %d" % m["discarded_total"])
    print("  negative samples       : %d" % m["negatives"])
    print("  retention range        : %.2f%% to %.2f%%"
          % (m["retention_min"], m["retention_max"]))
    print()

    failures = []

    print("== run counts quoted in %s ==" % args.paper)
    quoted = find_quoted_run_counts(src)
    if not quoted:
        print("  (none found)")
    for val, line in quoted:
        ok = val == m["n_runs"]
        print("  line %-5d quotes %-5d %s" % (line, val, "OK" if ok else
                                              "MISMATCH (ledger: %d)" % m["n_runs"]))
        if not ok:
            failures.append("run count at line %d: paper %d, ledger %d"
                            % (line, val, m["n_runs"]))

    print()
    print("== discard totals quoted ==")
    dq = find_quoted_discard_totals(src)
    if not dq:
        print("  (none found)")
    for val, line in dq:
        # These are quoted as "roughly", so a rounded figure is expected; check the rounding is
        # still honest rather than demanding equality.
        slack = max(args.tolerance_pct / 100.0 * m["discarded_total"], 5000)
        ok = abs(val - m["discarded_total"]) <= slack
        print("  line %-5d quotes %-8d %s" % (line, val, "OK (within rounding)" if ok else
                                              "MISMATCH (ledger: %d)" % m["discarded_total"]))
        if not ok:
            failures.append("discard total at line %d: paper %d, ledger %d"
                            % (line, val, m["discarded_total"]))

    print()
    print("== unsaturated-subset counts (a legitimately smaller number) ==")
    sub = find_quoted_run_counts(src, OMB_SUBSET_PATTERNS)
    if not sub:
        print("  (none found)")
    for val, line in sub:
        if val > m["n_runs"]:
            print("  line %-5d quotes %-5d IMPOSSIBLE (exceeds the %d total)"
                  % (line, val, m["n_runs"]))
            failures.append("unsaturated subset at line %d (%d) exceeds total (%d)"
                            % (line, val, m["n_runs"]))
        else:
            print("  line %-5d quotes %-5d OK (subset of %d; verify separately)"
                  % (line, val, m["n_runs"]))

    print()
    print("== the claim that carries the withdrawal ==")
    if m["negatives"] == 0:
        print("  negative samples = 0 -- 'not one negative' holds")
    else:
        print("  *** NEGATIVE SAMPLES PRESENT: %d ***" % m["negatives"])
        print("  Section 6.7 asserts 'not one negative'. That assertion is now false, and the")
        print("  withdrawal it justifies must be revisited before anything else in this paper.")
        failures.append("ledger contains %d negative samples; paper claims none"
                        % m["negatives"])

    print()
    if failures:
        print("FAILED (%d):" % len(failures))
        for f in failures:
            print("   %s" % f)
        return 1
    print("OK: Section 6.7's quoted numbers match the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
