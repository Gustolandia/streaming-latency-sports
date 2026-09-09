#!/usr/bin/env python3
"""Is every file in the reference corpus actually a paper?

Round 60 went looking for `timerlat_TC.pdf`, the manuscript's reference [35] and the closest
paper at the target venue, and found it already on disk: 5.7 KB, one page, and the words
"Enable JavaScript and cookies to continue". Three separate rounds had recorded the retrieval
as *failed*; each time the failure was also written to disk wearing the paper's filename, and
after that the corpus said the paper was held. It was retrievable all along, from the authors'
own preprint page.

The corpus decides venue questions --- figure density, caption openings, abstract length,
whether TC publishes measurement papers at all --- and a block page contributes nothing to any
of them while being counted in every denominator. **A file is evidence about a journal only if
it is the paper it is named after.**

The check is deliberately crude, because the failure mode is crude: a fetch that hits a bot
wall produces one page of boilerplate, and a paper does not. Anything at or below the page
floor, or carrying a known interstitial phrase, is reported.

CLI:
    python scripts/check_reference_corpus.py            # report, exit 1 if anything is not a paper
    python scripts/check_reference_corpus.py --quiet    # exit status only
"""

import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.path.join(REPO, "docs", "reference_tc")

#: A paper at this venue is not shorter than this. The shortest in the corpus is 6 pages.
MIN_PAGES = 3

#: Phrases that appear on a bot wall and never in a paper's first page.
INTERSTITIAL = (
    "enable javascript and cookies",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "access denied",
    "captcha",
)

#: A first page shorter than this is boilerplate: no title, authors and abstract fit in it.
MIN_FIRST_PAGE_CHARS = 400


def inspect(path):
    """None if the file is a paper, else a string saying what it is instead."""
    try:
        import pymupdf
    except ImportError:
        # No verdict is better than a wrong one: without a reader every file would look
        # like a block page. Covered by `test_without_pymupdf_it_declines_to_judge`.
        return None
    try:
        with pymupdf.open(path) as doc:
            pages = doc.page_count
            # No guard on an empty document: a zero-page PDF cannot be written, so a file
            # with no first page is a damaged one and the handler below is where it belongs.
            first = doc[0].get_text()
    except Exception as exc:  # noqa: BLE001 - any parse failure means it is not a paper
        return "unreadable as a PDF (%s)" % type(exc).__name__
    low = " ".join(first.split()).lower()
    for phrase in INTERSTITIAL:
        if phrase in low:
            return "a bot wall, not a paper (%r)" % phrase
    if pages < MIN_PAGES:
        return "%d page(s); the shortest paper at this venue is longer" % pages
    if len(low) < MIN_FIRST_PAGE_CHARS:
        return "first page holds %d characters; a title page holds more" % len(low)
    return None


def survey(corpus=CORPUS):
    """[(filename, what it is instead)] for every file that is not a paper."""
    if not os.path.isdir(corpus):
        return []
    bad = []
    for name in sorted(os.listdir(corpus)):
        if not name.lower().endswith(".pdf"):
            continue
        verdict = inspect(os.path.join(corpus, name))
        if verdict:
            bad.append((name, verdict))
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.corpus):
        if not args.quiet:
            print("no corpus at %s; nothing to check" % args.corpus)
        return 0

    held = [n for n in sorted(os.listdir(args.corpus)) if n.lower().endswith(".pdf")]
    bad = survey(args.corpus)
    if not args.quiet:
        print("%d file(s) in %s" % (len(held), args.corpus))
        for name, why in bad:
            print("  NOT A PAPER  %-34s %s" % (name, why))
        if not bad:
            print("every file is a paper")
        else:
            print("\n%d of %d are not papers. A failed fetch left under a paper's filename "
                  "makes the corpus overcount." % (len(bad), len(held)))
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    raise SystemExit(main())
