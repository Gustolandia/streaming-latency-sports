#!/usr/bin/env python3
"""
uncertainty_audit.py
Every number the paper quotes, and whether it carries an uncertainty interval.

Why this exists. A co-author asked for intervals of uncertainty on everything. The paper's
quantitative claims are emitted as macros in docs/generated/paper_numbers.tex, so the audit
can be systematic rather than impressionistic: enumerate the macros, say for each whether an
interval exists, is inapplicable, or is missing -- and compute the missing ones here where the
committed run-level data suffices.

Two statistical points the computations respect:

    Clustering. Events are clustered within runs, and a run shares one machine state, so a
    binomial interval on 62,264/738,730 would be absurdly tight. Event-level rates get a
    cluster bootstrap over runs (resample runs with replacement, recompute the pooled rate).

    Units. Where the run is the unit of analysis (the audit gate rejects RUNS), a Wilson
    interval on the run count is the right object, and clustering is not an issue.

Classification used in the output CSV:

    has-interval        the ledger already emits a CI alongside the value
    added-here          interval computed by this script from committed data
    range-not-CI        the printed range is a min-max across arms, not a confidence interval;
                        per-arm CIs exist in the ledger
    exact               a count or a definition; sampling uncertainty does not apply
    population          a complete-enumeration fact about a finite corpus (e.g. a retention
                        rate of one specific run); no sampling model, so no interval
    needs-data          an interval is meaningful but the committed artefacts cannot support
                        it; the row says what data would

Output: docs/results/uncertainty_audit.csv, and a printed summary of the gaps.

CLI:
    python scripts/uncertainty_audit.py
"""
import csv
import math
import os
import random
import re

NUMBERS_TEX = os.path.join("docs", "generated", "paper_numbers.tex")
RUN_RECOUNT = os.path.join("docs", "results", "span_recount.csv")
RUN_LEVEL = os.path.join("docs", "results", "span_run_level.csv")
OUT = os.path.join("docs", "results", "uncertainty_audit.csv")

BOOT_REPS = 2000
SEED = 7


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def cluster_boot_rate(pairs, reps=BOOT_REPS, seed=SEED):
    """pairs = [(numerator, denominator)] per run. Returns (rate, lo, hi) as percentages."""
    rng = random.Random(seed)
    n = len(pairs)
    total_k = sum(k for k, _ in pairs)
    total_n = sum(m for _, m in pairs)
    stats = []
    for _ in range(reps):
        k = m = 0
        for _ in range(n):
            a, b = pairs[rng.randrange(n)]
            k += a
            m += b
        if m:
            stats.append(100.0 * k / m)
    stats.sort()
    return (100.0 * total_k / total_n,
            stats[int(0.025 * len(stats))],
            stats[min(int(0.975 * len(stats)), len(stats) - 1)])


def load_macros():
    macros = {}
    pat = re.compile(r'\\newcommand\{\\(\w+)\}\{(.+)\}\s*$')
    with open(NUMBERS_TEX, encoding="utf-8") as fh:
        for line in fh:
            m = pat.match(line.strip())
            if m:
                macros[m.group(1)] = m.group(2)
    return macros


def load_runs():
    with open(RUN_RECOUNT, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_run_level():
    if not os.path.exists(RUN_LEVEL):
        return []
    with open(RUN_LEVEL, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    macros = load_macros()
    runs = load_runs()
    run_level = load_run_level()
    rows = []

    def add(name, value, cls, interval="", method="", note=""):
        rows.append({"quantity": name, "value": value, "class": cls,
                     "interval_95": interval, "method": method, "note": note})

    # ---- 1. macros that already carry intervals ----
    # Naming is not uniform: most CIs are <name>CI, but the traced-tail trio drops the
    # quantity suffix. An alias map is honest about that rather than a cleverer regex.
    ci_alias = {"tracedMleAlpha": "tracedMleCI", "tracedExcAlpha": "tracedExcCI",
                "tracedTailAlpha": "tracedTailCI"}
    has_ci = {m: m + "CI" for m in macros if m + "CI" in macros}
    has_ci.update({m: c for m, c in ci_alias.items() if m in macros and c in macros})
    for m in sorted(has_ci):
        add(m, macros[m], "has-interval", macros[has_ci[m]], "ledger-emitted")

    # ---- 2. event-level rates: cluster bootstrap over runs ----
    pairs_all = [(int(r["neg_ack"]), int(r["n_events"])) for r in runs]
    v, lo, hi = cluster_boot_rate(pairs_all)
    add("spanNegAckPct", "%.2f%%" % v, "added-here", "[%.2f%%, %.2f%%]" % (lo, hi),
        "cluster bootstrap over %d runs" % len(pairs_all))

    for backend, macro in (("kafka", "spanKafkaNegAckPct"), ("redis", "spanRedisNegAckPct")):
        pairs = [(int(r["neg_ack"]), int(r["n_events"])) for r in runs if r["backend"] == backend]
        v, lo, hi = cluster_boot_rate(pairs, seed=SEED + hash(backend) % 97)
        add(macro, "%.2f%%" % v, "added-here", "[%.2f%%, %.2f%%]" % (lo, hi),
            "cluster bootstrap over %d runs" % len(pairs))

    if run_level:
        pairs_ms = [(int(r["ms_deleted"]), int(r["n_events"])) for r in run_level]
        v, lo, hi = cluster_boot_rate(pairs_ms, seed=SEED + 5)
        add("msGuardDeletionPct (fig. deletion_histogram)", "%.1f%%" % v, "added-here",
            "[%.1f%%, %.1f%%]" % (lo, hi),
            "cluster bootstrap over %d runs" % len(pairs_ms),
            "the 45.8%% in the new figure; not yet a paper macro")

    # ---- 3. run-level proportions: Wilson ----
    for name, k, n in (("auditPct", 1321, 2266),
                       ("auditPctWorkstation", 862, 1382),
                       ("auditPctCloud", 459, 884)):
        lo, hi = wilson(k, n)
        add(name, macros.get(name, ""), "added-here",
            "[%.1f%%, %.1f%%]" % (100 * lo, 100 * hi),
            "Wilson on %d/%d runs" % (k, n),
            "run is the unit of analysis; clustering not at issue")

    # ---- 4. ranges that are not confidence intervals ----
    add("rtFactorLow-rtFactorHigh (7-80x)", "7-80", "range-not-CI", "",
        "min-max over 8 matched pairs",
        "per-pair CIs exist (rtLowCI, rtHighCI); print the range AS a range")
    add("tracedRatios (0.78, 1.06, 1.32)", macros.get("tracedRatios", ""), "needs-data", "",
        "", "ratio of a traced rate to an observed rate; needs per-arm event counts on both "
            "sides to bootstrap -- flag for v3, data exists in the depth artefacts")
    add("ombGridRetentionMin/Max (0.36-100%)", "0.36-100", "population", "",
        "", "complete enumeration of the 71 grid cells; each cell's retention is a fact of "
            "that run, not a sample estimate")
    add("ombRetentionMinExact (0.0044%)", macros.get("ombRetentionMinExact", ""),
        "population", "", "", "one run's exact retention")

    # ---- 5. counts and definitions ----
    for m in ("spanRuns", "spanEvents", "spanNegAck", "spanNegSend", "auditRuns",
              "auditRejected", "ombRuns", "ombDiscarded", "ombKept", "harnessAudited",
              "forkChecked", "forkUnchanged", "tracedEvents", "kernelHz", "tickMs",
              "testbedCpus", "baseSliceMs"):
        if m in macros:
            add(m, macros[m], "exact", "", "", "count or configured constant")

    # ---- 6. everything else in the ledger, classified by rule ----
    covered = {r["quantity"] for r in rows}

    # Complete enumerations of THIS corpus: a percentage of all runs, or the extreme of a
    # finite set. Exhaustive, so no sampling interval unless one models a super-population --
    # which is a framing decision for the text, recorded in the note.
    population_macros = {
        "spanRunsAckOnlyPct", "spanKafkaRunsAckInvertsPct", "spanRedisRunsAckInvertsPct",
        "spanDeepestInversionMs", "spanSendFloorUs", "spanSendFloorOtherUs",
        "spanOffsetMargin", "rtResidualMin", "rtResidualMax", "invCeiling",
        "ombKeptLo", "ombKeptHi", "ombPubLatLo", "ombPubLatHi", "ombRetentionFold",
        "ombMedianCells", "gridFlatRates",
    }
    # Not estimates, so not candidates for an interval. Kept as an explicit class rather
    # than dropped, because "no interval" and "interval not computed yet" are different
    # statements and the audit is worthless if it blurs them.
    not_estimates = {
        "chronyHostBoundLo": "instrument bound from chrony's own error estimate, not a sample",
        "chronyHostBoundHi": "same",
        "chronyPairBound": "sum of two instrument bounds; a worst case, not an estimate",
        "cpuEstimateSpread": "a spread across arms; label it as a spread where quoted",
        "tracedGofP": "a p-value; it is already a tail probability and takes no interval",
        "spanRunsOverOnePct": "a count of runs, exact for this campaign (the Pct suffix "
                              "in the macro name is a misnomer worth fixing)",
    }
    # Estimates whose interval is genuinely missing and computable from artefacts that exist
    # but are not committed at the needed granularity. The real decision list.
    decision_macros = {
        "payloadTransportFactor": "needs per-run payload-arm data for a bootstrap",
        "payloadRateFall": "same",
        "payloadReplTransportFactor": "same",
        "payloadReplRateFall": "same",
        "tracedRatios": "needs per-arm event counts on both sides; data in depth artefacts",
        "tracedRate": "traced-arm rate; binomial trivial but clustering unknown -- decide the unit",
        "untracedRate": "same",
        "tracedModeShare": "share of a fitted mode; stall_mixture.json now carries bootstrap CIs",
        "tracedModeTopShare": "same",
        "tracedOctaveA": "fit parameters; bootstrap alongside the mixture",
        "tracedOctaveB": "same",
        "tailPrefactor": "fit parameter without an emitted CI; bootstrap the fit",
    }
    for m in sorted(macros):
        if m in covered or m.endswith("CI") or m in has_ci:
            continue
        if re.search(r'Word|Cap$|Path$|Clock$|Sources$|Admitted', m):
            add(m, macros[m], "exact", "", "", "wording/config macro")
        elif m in population_macros:
            add(m, macros[m], "population", "", "",
                "exhaustive over this corpus; interval only under a super-population reading")
        elif m in not_estimates:
            add(m, macros[m], "not-an-estimate", "", "", not_estimates[m])
        elif m in decision_macros:
            add(m, macros[m], "needs-data", "", "", decision_macros[m])
        elif re.fullmatch(r'[\d,{}\.\$\-\s]+', macros[m]) and not m.endswith("Pct"):
            add(m, macros[m], "exact", "", "", "count, constant, or enumerated value")
        else:
            add(m, macros[m], "needs-data", "", "",
                "unclassified; decide whether an interval applies")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["quantity", "value", "class", "interval_95",
                                           "method", "note"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    counts = Counter(r["class"] for r in rows)
    print("audited quantities: %d" % len(rows))
    for cls in ("has-interval", "added-here", "exact", "population", "range-not-CI",
                "not-an-estimate", "needs-data"):
        print("  %-14s %d" % (cls, counts.get(cls, 0)))
    print("")
    print("intervals computed here:")
    for r in rows:
        if r["class"] == "added-here":
            print("  %-46s %-10s %s" % (r["quantity"], r["value"], r["interval_95"]))
    print("")
    print("still needing data or a decision:")
    for r in rows:
        if r["class"] == "needs-data" and r["note"]:
            print("  %-46s %s" % (r["quantity"], r["note"][:90]))
    print("")
    print("wrote %s" % OUT)


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
