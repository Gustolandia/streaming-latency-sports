#!/usr/bin/env python3
"""
harness_registry.py
The audited third-party harnesses, and what each one does with an inverted sample.

Why a registry rather than a paragraph. Section II makes a claim about the field: that several
widely used harnesses meet the same inverted interval and each disposes of it in a way that
leaves the reader unable to tell it happened. A paragraph asserting that is worth exactly the
reader's trust in us. What is committed here instead is the *evidence* -- one source line per
finding, with the file, the symbol, the upstream URL and the date it was read -- and the label
on each line is not stored. It is recomputed, every time this module runs and every time the
test suite runs, by `classify()` from audit_external_harness.py: the same function, unmodified,
that classified our own corpus and the OpenMessaging Benchmark.

That is the property worth having. If a reader disagrees with our reading of fio's guard, they
do not have to argue with our prose; they can read the committed line, read the pattern that
matched it, and decide. If we were to overstate a finding, the classifier would have to be bent
to match, and bending it would move the OpenMessaging result too, where the mismatch is visible
against an artefact that predates this file by a month.

The registry deliberately includes a harness with no defect. Rezolus counts its discarded
samples and names the reason in the metric description, which is what Section VII recommends.
A survey that collected only confirmations would be an advertisement.

CLI:
    python scripts/harness_registry.py
    python scripts/harness_registry.py --json
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit_external_harness import DISCARD_COUNTER, classify  # noqa: E402

REGISTRY = os.path.join("docs", "results", "external", "harness_registry.csv")

# The order a reader meets them in: our own subject first, then the independent reimplementation
# that makes it a pattern, then the two suppressors, then the counterexample.
FIELDS = ("harness", "vendor", "language", "path", "clock", "file", "symbol", "evidence",
          "source_url", "retrieved", "note")


def load(path=REGISTRY):
    """The committed rows, in file order."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    missing = [f for f in FIELDS if rows and f not in rows[0]]
    if missing:
        raise ValueError("registry is missing column(s): %s" % ", ".join(missing))
    return rows


def classified(rows):
    """Each row with the classes its evidence line falls into, derived not stored.

    A row whose evidence matches nothing is not an error: the Rezolus row is a counter, not a
    defect, and it should come back with an empty class list.
    """
    out = []
    for r in rows:
        d = dict(r)
        d["kinds"] = classify(r["evidence"])
        d["is_counter"] = bool(DISCARD_COUNTER.search(r["evidence"]))
        out.append(d)
    return out


def by_harness(rows):
    """Fold the per-line findings up to one verdict per harness."""
    out = {}
    for r in classified(rows):
        h = out.setdefault(r["harness"], {
            "vendor": r["vendor"], "language": r["language"],
            "kinds": set(), "counts_discards": False, "lines": 0,
        })
        h["kinds"].update(r["kinds"])
        h["counts_discards"] = h["counts_discards"] or r["is_counter"]
        h["lines"] += 1
    return out


def paths(rows=None):
    """One verdict per (harness, path), because a harness can get one span right and another
    wrong -- and the OpenMessaging Benchmark does exactly that.

    A referee checking the claim "this benchmark filters" against the repository will open
    MessageProducer.java, find a nanosecond clock and no guard, and conclude the claim is
    overstated. It is not overstated, it is scoped: the guard is on the end-to-end path. Folding
    by path rather than by harness makes that scope a computed property of the evidence instead
    of a qualifier we remember to add.
    """
    rows = load() if rows is None else rows
    out = {}
    for r in classified(rows):
        key = (r["harness"], r["path"])
        v = out.setdefault(key, {"clock": r["clock"], "kinds": set(),
                                 "counts_discards": False, "lines": 0})
        v["kinds"].update(r["kinds"])
        v["counts_discards"] = v["counts_discards"] or r["is_counter"]
        v["lines"] += 1
    return out


def within_harness_contrast(rows=None):
    """Harnesses that measure one span behind a guard and another without one.

    Returns, per harness, the guarded and unguarded paths with the clock each uses. The
    contrast is the finding: where a harness treats two spans differently, the coarse clock
    and the filter land on the span that crosses processes -- the one that needed care.
    """
    rows = load() if rows is None else rows
    by_harness = {}
    for (harness, path), v in paths(rows).items():
        guarded = bool(v["kinds"] & {"positive_only_filter", "silent_suppression"})
        by_harness.setdefault(harness, []).append((path, v["clock"], guarded))
    out = {}
    for harness, entries in by_harness.items():
        guarded = [(p, c) for p, c, g in entries if g]
        clean = [(p, c) for p, c, g in entries if not g]
        if guarded and clean:
            out[harness] = {"guarded": sorted(guarded), "unguarded": sorted(clean)}
    return out


def summary(rows=None):
    """The quantities Section II cites, each one a count over the committed evidence."""
    rows = load() if rows is None else rows
    fold = by_harness(rows)
    filters = [h for h, v in fold.items() if "positive_only_filter" in v["kinds"]]
    supp = [h for h, v in fold.items() if "silent_suppression" in v["kinds"]]
    cross = [h for h, v in fold.items() if "cross_process_latency" in v["kinds"]]
    counted = [h for h, v in fold.items() if v["counts_discards"]]
    # A harness is "silent" if it disposes of the sample and does not count the disposal. The
    # parentheses are load-bearing: `-` binds tighter than `|`, so without them a harness that
    # filtered *and* counted would still be reported as silent.
    silent = sorted((set(filters) | set(supp)) - set(counted))
    return {
        "harnesses": len(fold),
        "vendors": len({v["vendor"] for v in fold.values()}),
        "languages": len({v["language"] for v in fold.values()}),
        "evidence_lines": sum(v["lines"] for v in fold.values()),
        "cross_process": sorted(cross),
        "filters": sorted(filters),
        "suppressors": sorted(supp),
        "counts_discards": sorted(counted),
        "silent": silent,
        "n_silent": len(silent),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report the audited-harness registry")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--registry", default=REGISTRY)
    args = ap.parse_args(argv)

    rows = load(args.registry)
    s = summary(rows)
    if args.json:
        print(json.dumps(s, indent=2))
        return 0

    print("%d harnesses, %d vendors, %d languages, %d committed evidence lines"
          % (s["harnesses"], s["vendors"], s["languages"], s["evidence_lines"]))
    for name, v in sorted(by_harness(rows).items()):
        kinds = ", ".join(sorted(v["kinds"])) or "no defect class"
        seen = "counts discards" if v["counts_discards"] else "no counter"
        print("  %-28s %-7s %-18s %s; %s" % (name, v["language"], v["vendor"], kinds, seen))
    print("\nsilent (disposes of the sample, does not count it): %d -- %s"
          % (s["n_silent"], ", ".join(s["silent"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
