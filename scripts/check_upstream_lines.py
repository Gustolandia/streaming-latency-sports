#!/usr/bin/env python3
"""Check that the audited upstream lines still say what the manuscript says they say.

Section VI-A cites two lines by number --- `LocalWorker.java:294` and `WorkerStats.java:95`
--- and eighteen more rows of `harness_registry.csv` quote a line of source without one.
The bibliography records a read date, which is honest and is not the same claim: a read date
says the line was there once, and the sentence built on it asserts the line is there now.

This script turns the read date into a check. For every row of the two ledgers it fetches the
file from the repository the row names and asks whether the quoted evidence is still present,
and for the line-numbered ledger, whether it is still on the line the paper prints.

Three outcomes, and only the first is silent:

  OK      the evidence is present, at the cited line where a line is cited
  MOVED   the evidence is present at a different line --- the quote is sound and the paper's
          line number is stale, which is a one-digit manuscript fix
  GONE    the evidence is not in the file at all --- upstream changed the behaviour the
          audit reports, which is a finding and not a typo

It is not part of the test suite and must not become part of it. The suite runs offline and
deterministically; a check whose answer depends on what a stranger pushed this morning would
turn an unrelated upstream commit into a red build on this repository. What the suite covers
is this file's parsing, URL derivation and fetching, against injected stubs
(`tests/unit/test_round71_findings.py`). Run this one by hand, before a submission:

    python scripts/check_upstream_lines.py

Exit status is 1 if any row is MOVED or GONE, or if any fetch failed, so it can be wired into
a release checklist without being read by a person every time.
"""
import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTERNAL = os.path.join(ROOT, "docs", "results", "external")

#: (ledger, whether the row carries a line number the manuscript prints).
#: The audit ledger is the one Section VI-A quotes with line numbers, so a drift there is a
#: defect in the paper. The registry quotes evidence without a line, so only GONE applies.
LEDGERS = [("harness_audit.csv", True), ("harness_registry.csv", False)]

#: Raw-content host for the only forge these ledgers cite. `HEAD` resolves to the repository's
#: default branch whatever it is called, which matters because this corpus spans repositories
#: on `master` and on `main`.
RAW = "https://raw.githubusercontent.com/%s/HEAD/%s"


def raw_url(source_url, path):
    """The raw-content URL for a file in a GitHub repository, or None if it is not one.

    A row this returns None for is reported as unsupported rather than skipped: silently
    dropping a row is the failure mode this whole project is about, and a ledger that gains
    a GitLab entry should say so out loud on the next run.
    """
    marker = "github.com/"
    if marker not in source_url:
        return None
    repo = source_url.split(marker, 1)[1].strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if repo.count("/") != 1 or not all(repo.split("/")):
        return None
    return RAW % (repo, path.lstrip("/"))


def fetch(url, opener=None):
    """The file at `url` as text, or None if it could not be read.

    The opener is a parameter rather than something a test monkeypatches, and the pragma that
    would otherwise sit on this function is the reason. The exclusions in `scripts/` hide code
    that cannot run on this machine, and `test_coverage_exclusions.py` caps how many there may
    be, on the ground that the standard stops meaning anything once it can be bought. This
    one would have been the first past that cap. Behind an injected opener it costs no
    exclusion at all: every branch runs in the suite, against a fake and against a URL the
    default opener rejects before it opens a socket.

    Every failure is one outcome here -- a timeout, a 404, a certificate, a forge that moved
    -- because the caller's question is whether we read the file, and the answer is no.
    """
    if opener is None:
        import urllib.request
        opener = urllib.request.urlopen
    try:
        fh = opener(url, timeout=30)
    except Exception:  # noqa: BLE001 - see above: not read is not read
        return None
    try:
        return fh.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None
    finally:
        getattr(fh, "close", lambda: None)()


def rows(ledger):
    path = os.path.join(EXTERNAL, ledger)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def locate(text, evidence):
    """1-based (first, last) line spans carrying the evidence. Empty if it is not there.

    Equality after stripping, not containment. Containment would match a line that merely
    quotes the guard inside a longer expression, and the audit's claim is about the statement
    itself. Upstream re-indentation is not a change to the statement, so the strip stays.

    A quotation may span a line break, and one in this corpus does: the OpenMessaging
    producer constructor is one statement over two lines upstream and one string in the
    ledger. Line-by-line equality called that GONE on the first run of this script, which is
    the wrong word for a quotation that is present and wrapped. So a second pass joins the
    file on single spaces and looks for the evidence joined the same way, and reports the
    span of lines the hit covers. Multi-line hits are found only if no single line matches,
    so the cheap answer stays the one that is given.
    """
    want = " ".join(evidence.split())
    if not want:
        return []
    lines = text.splitlines()
    exact = [(i, i) for i, line in enumerate(lines, 1) if " ".join(line.split()) == want]
    if exact:
        return exact
    # Offsets into the joined text, so a hit can be mapped back to the lines it covers.
    starts, joined = [], []
    at = 0
    for line in lines:
        flat = " ".join(line.split())
        starts.append(at)
        joined.append(flat)
        at += len(flat) + 1
    blob = " ".join(joined)
    out, pos = [], blob.find(want)
    while pos >= 0:
        end = pos + len(want)
        first = max(i for i, s in enumerate(starts) if s <= pos)
        last = max(i for i, s in enumerate(starts) if s < end)
        out.append((first + 1, last + 1))
        pos = blob.find(want, pos + 1)
    return out


def _span(hit):
    return "line %d" % hit[0] if hit[0] == hit[1] else "lines %d-%d" % hit


def repo_index():
    """file path -> repository URL, taken from the registry.

    The audit ledger carries no `source_url` of its own; its five columns are the ones
    Section VI-A quotes. Rather than widen that ledger to satisfy this script, the repository
    is looked up by the file path it shares with the registry, which is the same fact stated
    once. A path the registry does not carry is reported UNSUPPORTED, not guessed.
    """
    return dict((r["file"], r["source_url"]) for r in rows("harness_registry.csv")
                if r.get("file") and r.get("source_url"))


def check_row(row, line_numbered, fetcher, repos=None):
    """One row's verdict as (status, detail)."""
    source = row.get("source_url") or (repos or {}).get(row.get("file", ""), "")
    url = raw_url(source, row.get("file", ""))
    if url is None:
        return "UNSUPPORTED", "no GitHub repository for %r" % row.get("file", "")
    text = fetcher(url)
    if text is None:
        return "UNREAD", url
    hits = locate(text, row.get("evidence", ""))
    if not hits:
        return "GONE", url
    if not line_numbered:
        return "OK", _span(hits[0])
    try:
        cited = int(row["line"])
    except (KeyError, TypeError, ValueError):
        return "MOVED", "row carries no usable line number; found at %s" % (
            ", ".join(_span(h) for h in hits))
    if any(h[0] <= cited <= h[1] for h in hits):
        return "OK", "line %d" % cited
    return "MOVED", "cited %d, found at %s" % (
        cited, ", ".join(_span(h) for h in hits))


def main(argv=None, fetcher=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true",
                    help="print only rows that are not OK")
    args = ap.parse_args(argv)
    fetcher = fetcher or fetch
    bad = 0
    # The registry repeats files the audit already names, and each fetch is a request to
    # somebody else's server. One read per URL, shared across both ledgers.
    cache = {}

    def cached(url):
        if url not in cache:
            cache[url] = fetcher(url)
        return cache[url]

    repos = repo_index()
    for ledger, line_numbered in LEDGERS:
        entries = rows(ledger)
        print("== %s: %d row(s)" % (ledger, len(entries)))
        for row in entries:
            status, detail = check_row(row, line_numbered, cached, repos)
            if status != "OK":
                bad += 1
            if status != "OK" or not args.quiet:
                print("   %-11s %s  %s  (%s)"
                      % (status, row.get("harness", "?"),
                         os.path.basename(row.get("file", "?")), detail))
    if bad:
        print("\n%d row(s) no longer match upstream. A MOVED row is a line number to correct "
              "in Section VI-A; a GONE row is a finding." % bad)
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
