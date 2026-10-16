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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audit_external_harness import (  # noqa: E402
    DISCARD_COUNTER, DISPOSAL_KINDS, classify, guards_a_tally)

REGISTRY = os.path.join("docs", "results", "external", "harness_registry.csv")

# The order a reader meets them in: our own subject first, then the independent reimplementation
# that makes it a pattern, then the two suppressors, then the counterexample.
FIELDS = ("harness", "vendor", "language", "path", "clock", "file", "symbol", "evidence",
          "source_url", "retrieved", "note")

#: The spans a message travels: from publish to receipt, from publish to acknowledgment, or a
#: request and its reply, which the registry also files as end-to-end. A tool with none of them
#: times an interval inside one host -- an I/O completion, a block-layer stage, a wakeup.
MESSAGE_SPANS = ("end-to-end", "publish")


#: The vendors that are individual people rather than organizations, each with the reason
#: (15 Oct 2026). The registry names who maintains each tool; the revised paper says how many
#: of them are organizations, and that count is the rest. Where the count is emitted
#: (emit_paper_numbers.registry_macros), a name here that no row carries stops the build, so a
#: renamed vendor cannot leave a person counted as an organization.
INDIVIDUAL_VENDORS = {
    "Alan D. Brunelle": "btt's author, credited by name in blktrace's sources; no company "
                        "publishes it",
    "Alexander Krylovsky": "mqtt-benchmark lives in his personal account, github.com/krylovsk",
    "G. Tene": "wrk2 lives in Gil Tene's personal account, github.com/giltene",
    "Jens Axboe": "fio lives in his personal account, github.com/axboe, where he maintains it",
    "Justin Ross": "Quiver lives in his personal account, github.com/ssorj",
    "Keshava Munegowda": "SBK lives in his personal account, github.com/kmgowda",
}


#: Where `csv.DictReader` files the values of a row that has more fields than the header.
#: It has to be named, because the default is `None` and a `None` key is invisible to every
#: check written over `FIELDS`.
SURPLUS = "__surplus__"


def load(path=REGISTRY):
    """The committed rows, in file order. Raises on a row that is not the shape of the header.

    The surplus check is not hypothetical. One row's `note` contained unquoted commas and so
    had thirteen fields against the header's eleven; `csv.DictReader` put the overflow under
    the key `None` and returned the row, and every reader of this ledger got a note truncated
    at its first comma with nothing said. A silent discard, with no counter, in the artefact
    of a paper about silent discards with no counters. It is quoted now, and a row that ever
    spills again stops the pipeline instead of being summarised short.
    """
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, restkey=SURPLUS))
    missing = [f for f in FIELDS if rows and f not in rows[0]]
    if missing:
        raise ValueError("registry is missing column(s): %s" % ", ".join(missing))
    for i, r in enumerate(rows, 2):
        if SURPLUS in r:
            raise ValueError(
                "registry line %d has %d field(s) more than the header, so a value contains "
                "an unquoted delimiter: %r" % (i, len(r[SURPLUS]), r[SURPLUS]))
        empty = [f for f in FIELDS if r.get(f) is None]
        if empty:
            raise ValueError("registry line %d is missing value(s) for: %s"
                             % (i, ", ".join(empty)))
    return rows


#: A send that waits for its acknowledgment, on the path that times a message to its receipt.
#: The receipt is then read only once the acknowledgment has returned, so a message that reached
#: the consumer first is timed from that later moment: a time that was never measured stands in
#: for its arrival, and its receipt-minus-acknowledgment difference is held at zero. That is a
#: substitution, the class SUPPRESSION in audit_external_harness.py describes, made by the order
#: of two calls rather than by a test of the sign. classify() sees one line and cannot tell a
#: send on a publish path, where waiting is the measurement, from one on the end-to-end path, so
#: the rule is read here, where the row's path is known, and classify() is left as it read our
#: own corpus and the OpenMessaging Benchmark. Kafka's own EndToEndLatency is the specimen, and
#: K1 measured what it hides (docs/results/tools/k1.csv). Read so since 13 Oct 2026; before, the
#: registry filed that tool as one that never meets such a value, true of the value it computes.
BLOCKING_SEND = re.compile(r"\.send\s*\([^;]*\)\s*\.get\s*\(\s*\)\s*;")


def classified(rows):
    """Each row with the classes its evidence line falls into, derived not stored.

    A row whose evidence matches nothing is not an error: the Rezolus row is a counter, not a
    defect, and it should come back with an empty class list. A row on the end-to-end path whose
    evidence is a send that waits for its acknowledgment is also a substitution (BLOCKING_SEND).
    """
    out = []
    for r in rows:
        d = dict(r)
        d["kinds"] = list(classify(r["evidence"]))
        if (r["path"] == "end-to-end" and BLOCKING_SEND.search(r["evidence"])
                and "silent_suppression" not in d["kinds"]):
            d["kinds"].append("silent_suppression")
        d["is_counter"] = bool(DISCARD_COUNTER.search(r["evidence"]))
        d["tally_guard"] = guards_a_tally(r["evidence"])
        out.append(d)
    return out


def by_harness(rows):
    """Fold the per-line findings up to one verdict per harness."""
    out = {}
    for r in classified(rows):
        h = out.setdefault(r["harness"], {
            "vendor": r["vendor"], "language": r["language"],
            "kinds": set(), "counts_discards": False, "lines": 0,
            "tally_guard": False, "paths": set(),
        })
        h["kinds"].update(r["kinds"])
        h["counts_discards"] = h["counts_discards"] or r["is_counter"]
        h["tally_guard"] = h["tally_guard"] or r["tally_guard"]
        h["paths"].add(r["path"])
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
        # 6 Oct 2026: vendor and language travel with the verdict, so the supplement's table
        # can show the rows behind "five languages and nine vendors".
        v = out.setdefault(key, {"clock": r["clock"], "kinds": set(),
                                 "counts_discards": False, "lines": 0, "tally_guard": False,
                                 "vendor": r.get("vendor", ""), "language": r.get("language", "")})
        v["kinds"].update(r["kinds"])
        v["counts_discards"] = v["counts_discards"] or r["is_counter"]
        v["tally_guard"] = v["tally_guard"] or r["tally_guard"]
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
        guarded = bool(v["kinds"] & set(DISPOSAL_KINDS))
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
    # Round 69: the weaker guard, counted beside the strict one because a tool that
    # drops its inversions silently is still silent, and separately because what may be
    # SAID about it differs -- it keeps the population the strict guard deletes.
    nonneg = [h for h, v in fold.items() if "nonnegative_filter" in v["kinds"]]
    supp = [h for h, v in fold.items() if "silent_suppression" in v["kinds"]]
    refusal = [h for h, v in fold.items() if "library_refusal" in v["kinds"]]
    cross = [h for h, v in fold.items() if "cross_process_latency" in v["kinds"]]
    counted = [h for h, v in fold.items() if v["counts_discards"]]
    # A harness is "silent" if it disposes of the sample and does not count the disposal. The
    # parentheses are load-bearing: `-` binds tighter than `|`, so without them a harness that
    # filtered *and* counted would still be reported as silent. `refusal` joined this union in
    # round 6: a value dropped by the recording library is as gone as one dropped by an `if`,
    # and counted in one place fewer.
    silent = sorted((set(filters) | set(nonneg) | set(supp) | set(refusal)) - set(counted))
    # 11 Oct 2026. The tools that time a message, which the paper counts apart from the three
    # that time an interval inside one host; and of those, the ones that cut a value at or below
    # zero out of what they report without counting it. That is every silent one, and also a
    # tool whose guard keeps the value out of the tally its printed figure is computed from,
    # though the sample itself survives elsewhere -- emqtt-bench, whose histogram keeps it and
    # whose printed average counts it as zero.
    message = sorted(h for h, v in fold.items() if v["paths"] & set(MESSAGE_SPANS))
    tallied = sorted(h for h, v in fold.items() if v["tally_guard"])
    cut = sorted((set(silent) | set(tallied)) - set(counted))
    # Named so a reader can check the union above against the classifier rather than trust it.
    assert set(DISPOSAL_KINDS) == {"positive_only_filter", "nonnegative_filter",
                                   "silent_suppression", "library_refusal"}, DISPOSAL_KINDS
    vendors = {v["vendor"] for v in fold.values()}
    people = vendors & set(INDIVIDUAL_VENDORS)
    return {
        "harnesses": len(fold),
        "vendors": len(vendors),
        # 15 Oct 2026: the vendors that are organizations, every vendor INDIVIDUAL_VENDORS
        # does not name as a person.
        "organizations": len(vendors - people),
        "individuals": sorted(people),
        "languages": len({v["language"] for v in fold.values()}),
        "evidence_lines": sum(v["lines"] for v in fold.values()),
        "cross_process": sorted(cross),
        "filters": sorted(filters),
        "nonnegative_filters": sorted(nonneg),
        "suppressors": sorted(supp),
        "library_refusals": sorted(refusal),
        "counts_discards": sorted(counted),
        "silent": silent,
        "n_silent": len(silent),
        "message_tools": message,
        "tally_guards": tallied,
        "message_cut": sorted(set(cut) & set(message)),
        # 13 Oct 2026: the message tools that cut such a value out of what they report and count
        # it, SBK alone, which the paper counts beside the ones that cut without counting.
        "message_counted": sorted(set(counted) & set(message)),
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


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
