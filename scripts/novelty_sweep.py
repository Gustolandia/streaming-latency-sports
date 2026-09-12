#!/usr/bin/env python3
"""Search the literature for this paper's two mechanisms, in the words other people use.

Why this file exists, and it is worth saying plainly. Round 73's referee reported that
`all:"negative latency"` returns four papers, three of them gravitational-wave astronomy, and
offered the emptiness as evidence of originality. A contributor asked whether that was really
the ideal search word. It was not, and the objection is the important kind: **an empty search
is evidence about a phrase, not about a field.** "Negative latency" is not even this paper's
own term -- Section III-B takes *negative span* from Sharma et al. -- so its absence from the
literature measured nothing except that nobody else had coined it either.

The right question is what a competitor would have called the thing, and the answer is not one
phrase but a vocabulary, because the two mechanisms live in different communities:

  * Mode A -- an interval that comes out negative because of the instrument -- is discussed in
    distributed tracing ("out-of-order timestamps", "clock skew adjustment"), in network
    measurement (Paxson's "physically impossible" transit times) and, once, under Sharma et
    al.'s "negative timing spans".
  * Mode B -- a filter that deletes a population and does not count it -- is discussed in
    benchmarking ("timer resolution", "clock granularity") and in metrology ("quantization
    error"), and almost nowhere as a deletion with a denominator.

So the terms are written down here, by mechanism, with the community each belongs to, and the
sweep is re-runnable. What that buys is the difference between "we searched" and "these are the
terms we searched, and here is what each returned". A reader can disagree with a term. A reader
cannot disagree with a recollection.

The counts are written to `docs/results/external/novelty_sweep.csv`. The supplement does NOT
quote them: the first runs of this script showed the index is approximate under load -- three
for one phrase in a batch, one on each of three consecutive calls a minute later, the same
single work listed every time -- so each term is sampled three times, a count that moved is
written as a band with the verdict `unstable: ask again`, and the ledger is not written at all
unless every term came back stable. What the supplement quotes is the term list, which is in
the repository and does not move. The file is the record of a run, and it is absent until a run
succeeds; it is not something to write by hand.

It is NOT part of the test suite, for the reason `check_upstream_lines.py` is not: it talks to
somebody else's server, and a red build caused by an indexing change is news about OpenAlex.
Run it by hand before a submission:

    python scripts/novelty_sweep.py --write

`--write` updates the committed ledger; without it the sweep prints and changes nothing.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "docs", "results", "external", "novelty_sweep.csv")

#: (mechanism, community, query, what a hit would have to be to threaten the claim).
#: Quoted phrases are exact-phrase searches; the rest are conjunctions.
#:
#: `negative timing spans` is the sharpest of these and the one to read first. It is Sharma et
#: al.'s own term, adopted by this paper, and it is the term a competitor working on Mode A
#: would most plausibly have used. It returns one work, and the work is Sharma et al.
TERMS = [
    ("A", "distributed tracing", '"negative timing spans"',
     "another measurement of a span that computes negative"),
    ("A", "distributed tracing", '"out-of-order timestamps" tracing',
     "a tracer that reports the order failure rather than repairing it"),
    ("A", "distributed tracing", '"clock skew" "distributed tracing" span correction',
     "a skew corrector that publishes how much it moved"),
    ("A", "operating systems", '"scheduling delay" "timestamp" benchmark bias',
     "the scheduling delay treated as another tool's error term"),
    ("B", "benchmarking", '"timestamp resolution" benchmark',
     "a benchmark that places its own path against its resolution"),
    ("B", "benchmarking", '"clock granularity" latency benchmark',
     "the same, in the other community's word for it"),
    ("B", "benchmarking", '"discarded samples" latency benchmark counter',
     "a harness that counts what its filter removed"),
    ("B", "benchmarking", '"positive latencies" filter histogram',
     "the admission condition, named by somebody else"),
    ("B", "metrology", '"retained fraction" latency measurement',
     "the retention identity applied to a deleting filter"),
    ("both", "message systems", '"message broker" "timestamp resolution"',
     "a broker comparison that states the resolution it measured at"),
    ("both", "message systems", '"message broker" benchmark "clock synchronization"',
     "a broker comparison that states its synchronization state"),
]

FIELDS = ("mechanism", "community", "query", "threat_would_be", "hits", "verdict")
API = "https://api.openalex.org/works"

#: Retries per sample when a request is refused. OpenAlex answers a burst with
#: HTTP 429, and a 429 is a request to wait rather than an answer about the field.
BACKOFF_TRIES = 3


def fetch_once(query, opener=None):
    """Result count for one OpenAlex query, or None if it could not be read.

    The opener is a parameter rather than something a test monkeypatches, so that every branch
    here runs in the suite against a fake and this file needs no coverage exclusion.
    """
    url = API + "?" + urllib.parse.urlencode(
        {"search": query, "per-page": "1", "select": "id"})
    if opener is None:
        opener = urllib.request.urlopen
    try:
        fh = opener(urllib.request.Request(
            url, headers={"User-Agent": "mailto:pedrorig@tcd.ie"}), timeout=45)
    except Exception:  # noqa: BLE001 - not read is not read
        return None
    try:
        return json.loads(fh.read().decode("utf-8", "replace"))["meta"]["count"]
    except Exception:  # noqa: BLE001
        return None
    finally:
        getattr(fh, "close", lambda: None)()


def fetch(query, opener=None, samples=3, pause=2.5, sleep=None):
    """The count, asked for more than once, because it is not stable to the unit.

    This is not defensive programming; it is a measurement the first run of this script forced.
    A batch sweep returned 3 for `"negative timing spans"`; three consecutive interactive calls
    a minute later returned 1, 1 and 1, and the single work was Sharma et al. both times.
    OpenAlex's `meta.count` is approximate under load, so a number taken once is a number whose
    value depends on when it was asked.

    That is this paper's own thesis pointed at its own bibliography, and the honest response is
    the one the manuscript recommends to everybody else: do not print a figure without the
    spread. Returns `(lo, hi)` over the samples, equal when the count is stable, and `None` if
    no sample could be read.
    """
    sleep = sleep or time.sleep
    seen = []
    for i in range(max(1, samples)):
        if i:
            sleep(pause)
        n = fetch_once(query, opener=opener)
        # A refusal is usually a rate limit rather than an answer, and the first build of this
        # script treated the two the same: one 429 and the term was recorded unread, which
        # correctly stopped the whole ledger being written. Backing off is what a client owes a
        # server it is asking eleven questions three times each. Three tries, doubling.
        backoff = pause
        for _ in range(BACKOFF_TRIES):
            if n is not None:
                break
            sleep(backoff)
            backoff *= 2
            n = fetch_once(query, opener=opener)
        if n is not None:
            seen.append(n)
    if not seen:
        return None
    return (min(seen), max(seen))


def verdict(query, band):
    """What a count means, in words, so the ledger is readable without the code.

    Zero is not the good answer and a large number is not the bad one. A term that returns
    nothing may simply be a phrase nobody uses; a term that returns thousands is too broad to
    have tested anything. What matters is the middle: a handful of hits, each of which can be
    opened and placed. A term whose count moved between samples gets its own verdict, because
    the right response to it is to ask again rather than to quote it.
    """
    if band is None:
        return "unread"
    lo, hi = band
    if lo != hi:
        return "unstable: ask again"
    if hi == 0:
        return "no such phrase"
    if hi <= 20:
        return "readable: open each"
    if hi <= 500:
        return "broad: sample the top"
    return "too broad to test a claim"


def sweep(terms=TERMS, fetcher=None):
    """One row per term. `fetcher` returns (lo, hi) or None; a plain int is accepted too, so a
    test can hand over a constant without knowing this file's sampling."""
    fetcher = fetcher or fetch
    rows = []
    for n, (mech, community, query, threat) in enumerate(terms):
        if n and fetcher is fetch:
            # Between terms as well as between samples. Eleven terms at three samples is
            # thirty-three requests, and the first run of this at full speed came back
            # throttled on eight of them -- which the ledger correctly refused to write.
            time.sleep(2.5)
        band = fetcher(query)
        if isinstance(band, int):
            band = (band, band)
        rows.append({"mechanism": mech, "community": community, "query": query,
                     "threat_would_be": threat,
                     "hits": "" if band is None else
                             (str(band[0]) if band[0] == band[1]
                              else "%d-%d" % band),
                     "verdict": verdict(query, band)})
    return rows


def write(rows, path=None):
    """Default resolved at call time, not bound at def time, so the module attribute is what
    a caller sees when it points this somewhere else."""
    with open(path or LEDGER, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None, fetcher=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="update docs/results/external/novelty_sweep.csv")
    args = ap.parse_args(argv)
    rows = sweep(fetcher=fetcher)
    for r in rows:
        print("  %-4s %-22s %-52s %8s  %s"
              % (r["mechanism"], r["community"], r["query"][:52],
                 r["hits"] or "-", r["verdict"]))
    unread = [r for r in rows if r["verdict"] in ("unread", "unstable: ask again")]
    if args.write and not unread:
        write(rows)
        print("\nwrote %s" % os.path.relpath(LEDGER, ROOT))
    if unread:
        print("\n%d term(s) could not be read; the ledger is unchanged." % len(unread))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
