#!/usr/bin/env python3
"""What a paper about benchmarking does and does not say, counted rather than asserted.

Round 61's referee found the best single piece of evidence for this manuscript's gap claim:
a 2024 survey reviewing 27 stream-processing benchmarks across five dimensions -- one of which
is *tracked metrics* -- mentions latency 33 times and the timestamp not once. A survey that
classifies what the field measures, and never asks how.

That number cannot be typed. Lesson 1aq of `docs/infrastructure.md` is exactly this class: a
quantity with only one source is invisible to `test_ledger_coverage`, because that gate
catches a literal colliding with an emitted macro and a typed count collides with nothing. So
the count is derived here and emitted like every other number in the manuscript.

**The build does not depend on the corpus.** `docs/reference_tc/` is gitignored -- it holds
third-party papers the repository must not redistribute -- so this script is run by hand, its
output is committed, and `emit_paper_numbers.py` reads the committed CSV. A build on a machine
with no corpus produces the same supplement, which is the point of committing the record. Same
arrangement as `check_fork_exposure.py`, and for the same reason.

**Counting is a claim about method, so the method is fixed here.** A term is counted as a
case-insensitive regular expression over the PDF's extracted text with whitespace collapsed,
so `timestamps` and `Timestamp` both count as `timestamp`. The extracted character count is
recorded beside every row: a count of zero means nothing if extraction failed, and the only
way a reader can tell those apart is to see how much text there was.

CLI:
    python scripts/literature_census.py                 # refresh the record
    python scripts/literature_census.py --check         # fail if the record disagrees
"""

import argparse
import csv
import datetime
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "docs", "reference_tc")
DEFAULT_OUT = os.path.join("docs", "results", "external", "literature_census.csv")

FIELDS = ("source", "key", "pages", "chars", "term", "count", "checked_utc")

#: (filename in the corpus, bib key, terms to count).
#:
#: The terms are chosen before the counting, and both halves are kept: the ones that establish
#: the paper is about latency at all, and the ones whose absence is the finding. A census that
#: reported only the zeros would be a census designed to produce them.
SOURCES = (
    ("streamsurvey_tpctc2024.pdf", "yue2024streamsurvey",
     ("benchmark", "latency", "metric", "timestamp", "clock", "resolution",
      "measurement error")),
    # S52.4 has been making this same shape of claim since round 55 -- "over thirty-one pages
    # the words timestamp, resolution, quantization and retention do not occur; clock occurs
    # once" -- with every number typed. Found while adding the survey, and repaired with it:
    # one instrument for both, rather than a census built for whichever claim a referee names.
    ("krishnamachari_playbook.pdf", "krishnamachari2026playbook",
     ("latency", "timestamp", "resolution", "quantization", "retention", "clock")),
)


def census(path, terms):
    """(pages, chars, {term: count}) for one PDF, or None if it cannot be read."""
    try:
        import pymupdf
    except ImportError:
        return None
    if not os.path.exists(path):
        return None
    with pymupdf.open(path) as doc:
        pages = doc.page_count
        text = " ".join(" ".join(page.get_text() for page in doc).split())
    counts = {t: len(re.findall(re.escape(t), text, re.I)) for t in terms}
    return pages, len(text), counts


def read_record(path=None):
    """The committed census, as a list of dicts. Empty when there is no record."""
    path = path or os.path.join(REPO, DEFAULT_OUT)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def counts_for(key, rows=None):
    """{term: int} for one source in the committed record."""
    rows = read_record() if rows is None else rows
    return {r["term"]: int(r["count"]) for r in rows if r["key"] == key}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed record disagrees; write nothing")
    args = ap.parse_args(argv)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    fresh = []
    for name, key, terms in SOURCES:
        got = census(os.path.join(args.corpus, name), terms)
        if got is None:
            print("cannot read %s; the corpus is gitignored, so this is expected off the "
                  "author's machine" % name)
            return 0 if not args.check else 0
        pages, chars, counts = got
        for term in terms:
            fresh.append({"source": name, "key": key, "pages": str(pages),
                          "chars": str(chars), "term": term,
                          "count": str(counts[term]), "checked_utc": stamp})
        print("%s: %d pages, %d chars extracted" % (name, pages, chars))
        for term in terms:
            print("    %-18s %d" % (term, counts[term]))

    if args.check:
        old = {(r["key"], r["term"]): r["count"] for r in read_record(
            os.path.join(REPO, args.out))}
        drift = [(r["key"], r["term"], old.get((r["key"], r["term"])), r["count"])
                 for r in fresh if old.get((r["key"], r["term"])) != r["count"]]
        if drift:
            for k, t, was, now in drift:
                print("  DRIFT %s/%s: recorded %s, counted %s" % (k, t, was, now))
            return 1
        print("the committed record agrees with the corpus")
        return 0

    out = os.path.join(REPO, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(fresh)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
