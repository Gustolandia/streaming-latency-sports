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

    Three defects have been found in this one function, each one a number the check passed over
    in silence:

    1. A single-separator pattern stopped matching once the total passed a million -- exactly
       when it most needed checking. Fixed by allowing repeated groups.
    2. `$3.5$ million` was not recognised at all, so a rounded figure could say anything.
    3. Line-by-line scanning missed every occurrence where LaTeX wrapped between the number and
       the word `discarded`. Two of the paper's four discard totals were written that way, so a
       check that reported "2 sites, both stale" was really "4 sites, and I can only see half".

    The scan is therefore over the whole source with newlines treated as ordinary whitespace,
    and line numbers are recovered from the match offset.
    """
    out = []
    exact = re.compile(r"\$(\d{1,3}(?:\{,\}\d{3})+)\$[^.]{0,40}?discarded", re.S)
    millions = re.compile(r"\$([\d.]+)\$\s*million[^.]{0,40}?discarded", re.S)
    for pat, conv in ((exact, lambda g: int(g.replace("{,}", ""))),
                      (millions, lambda g: int(round(float(g) * 1_000_000)))):
        for m in pat.finditer(src):
            out.append((conv(m.group(1)), src.count("\n", 0, m.start()) + 1))
    return sorted(out, key=lambda t: t[1])


# Once a quantity is derived into a macro, a bare digit reappearing in its place is a regression:
# someone has gone back to typing the number by hand, and it will go stale again. These are the
# macros the manuscript is expected to use for quantities that move with the campaign.
DERIVED_MACROS = ("ombRuns", "ombDiscarded")


def find_undermined_macros(src, macros=DERIVED_MACROS):
    """Macros the paper should be using but no longer does."""
    return [name for name in macros if ("\\" + name) not in src]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check Section 6.7's numbers against the ledger")
    ap.add_argument("--ledger", default="docs/results/external_campaigns_index.csv")
    ap.add_argument("--paper", default="paper.tex")
    ap.add_argument("--generated", default=os.path.join("docs", "generated",
                                                        "paper_numbers.tex"),
                    help="the LaTeX macro file emit_paper_numbers.py writes")
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

    print("== is the manuscript still deriving these numbers? ==")
    absent = find_undermined_macros(src)
    for name in DERIVED_MACROS:
        if name in absent:
            print("  \\%-14s NOT USED -- the manuscript has stopped deriving this" % name)
            failures.append("paper no longer uses \\%s; the number is being typed by hand again"
                            % name)
        else:
            print("  \\%-14s in use" % name)

    print()
    print("== hand-typed run counts (there should be none) ==")
    quoted = find_quoted_run_counts(src)
    if not quoted:
        print("  none -- every run count comes from \\ombRuns")
    for val, line in quoted:
        # A literal here is a regression even when it happens to be correct today: it is correct
        # by coincidence, and the next campaign will make it wrong silently.
        agrees = " (agrees with the ledger today, but will not stay that way)" \
            if val == m["n_runs"] else " (ledger: %d)" % m["n_runs"]
        print("  line %-5d hand-typed %-5d%s" % (line, val, agrees))
        failures.append("run count typed by hand at line %d (%d); use \\ombRuns" % (line, val))

    print()
    print("== hand-typed discard totals (there should be none) ==")
    dq = find_quoted_discard_totals(src)
    if not dq:
        print("  none -- every discard total comes from \\ombDiscarded")
    for val, line in dq:
        agrees = " (agrees with the ledger today, but will not stay that way)" \
            if abs(val - m["discarded_total"]) <= max(
                args.tolerance_pct / 100.0 * m["discarded_total"], 0) \
            else " (ledger: %d)" % m["discarded_total"]
        print("  line %-5d hand-typed %-9d%s" % (line, val, agrees))
        failures.append("discard total typed by hand at line %d (%d); use \\ombDiscarded"
                        % (line, val))

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
    print("== the generated macros against the ledger ==")
    from emit_paper_numbers import render  # noqa: E402
    if not os.path.exists(args.generated):
        print("  missing: %s -- run scripts/emit_paper_numbers.py" % args.generated)
        failures.append("%s does not exist" % args.generated)
    else:
        with open(args.generated, encoding="utf-8") as fh:
            have = fh.read().replace("\r\n", "\n")
        if have != render(m):
            print("  STALE: %s disagrees with the ledger" % args.generated)
            print("  regenerate with: python scripts/emit_paper_numbers.py")
            failures.append("%s is stale" % args.generated)
        else:
            print("  %s matches (%d runs, %d discarded)"
                  % (args.generated, m["n_runs"], m["discarded_total"]))

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
