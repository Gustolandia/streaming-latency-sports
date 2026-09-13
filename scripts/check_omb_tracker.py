#!/usr/bin/env python3
"""
check_omb_tracker.py
Has anyone upstream ever questioned the admission condition? A dated, checkable answer.

Why this exists. Round 77's referee searched the OpenMessaging Benchmark's issue tracker for
the variable its filter tests, `endToEndLatencyMicros`, and found one item in eight years: pull
request #56, March 2018 -- the change that added `if (endToEndLatencyMicros > 0)`. Nothing
since had returned to it, including the coordinated-omission report Section VIII-B says the
project accepted. That is a sharper form of "neither failure is detected" than any count of
benchmarks, and it is also the kind of sentence that goes stale without anyone noticing.

So it is a ledger row, not a remembered search. `docs/results/external/omb_tracker_search.csv`
records the query, the date it was run, how many items matched, and the first of them;
`emit_paper_numbers.py` reads that row, so the supplement's sentence is emitted from the date
and the count rather than typed; and this script re-runs the search and reports whether the
recorded answer still holds.

Like `check_upstream_lines.py`, it talks to the network and is not part of the test suite: a
red build caused by a stranger opening an issue would be news about them, not about this
repository. Its logic is tested offline, with the network call replaced.

CLI:
    python scripts/check_omb_tracker.py            # compare the live search with the ledger
    python scripts/check_omb_tracker.py --write    # record today's result in the ledger
"""
import argparse
import csv
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

REPO = "openmessaging/benchmark"
QUERY = "endToEndLatencyMicros"
LEDGER = os.path.join("docs", "results", "external", "omb_tracker_search.csv")
FIELDS = ("repository", "query", "checked", "total_items", "first_item",
          "first_item_created", "first_item_title")
#: The fields whose change means the recorded sentence is no longer true. `checked` moves on
#: every run and the title can be edited upstream without the fact changing.
MATERIAL = ("total_items", "first_item", "first_item_created")


def fetch(repo=REPO, query=QUERY, opener=urllib.request.urlopen):
    """The GitHub issue-search result for `query` in `repo`, oldest first, as parsed JSON."""
    url = ("https://api.github.com/search/issues?q="
           + urllib.parse.quote("repo:%s %s" % (repo, query))
           + "&sort=created&order=asc&per_page=5")
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "streaming-latency-sports/check_omb_tracker"})
    with opener(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def summarise(payload, checked, repo=REPO, query=QUERY):
    """One ledger row from a search payload. The first item is the oldest match."""
    items = payload.get("items") or []
    first = items[0] if items else {}
    return {"repository": repo, "query": query, "checked": checked,
            "total_items": int(payload.get("total_count", len(items))),
            "first_item": first.get("number", ""),
            "first_item_created": (first.get("created_at") or "")[:10],
            "first_item_title": first.get("title", "")}


def read_ledger(path=LEDGER):
    """The single recorded row. More or fewer than one is a malformed ledger, not a result."""
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if len(rows) != 1:
        raise ValueError("%s must hold exactly one row; it holds %d" % (path, len(rows)))
    return rows[0]


def write_ledger(row, path=LEDGER):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerow({k: row[k] for k in FIELDS})


def compare(recorded, live):
    """The material fields on which the live search no longer matches the ledger."""
    return [k for k in MATERIAL if str(recorded[k]) != str(live[k])]


def main(argv=None, fetcher=fetch, today=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--write", action="store_true", help="record today's result")
    ap.add_argument("--ledger", default=LEDGER)
    args = ap.parse_args(argv)
    checked = today or datetime.date.today().isoformat()
    live = summarise(fetcher(), checked)
    if args.write:
        write_ledger(live, args.ledger)
        print("wrote %s: %d item(s), first #%s (%s)"
              % (args.ledger, live["total_items"], live["first_item"],
                 live["first_item_created"]))
        return 0
    recorded = read_ledger(args.ledger)
    moved = compare(recorded, live)
    if moved:
        print("the tracker has moved since %s: %s"
              % (recorded["checked"],
                 ", ".join("%s %s -> %s" % (k, recorded[k], live[k]) for k in moved)))
        return 1
    print("unchanged since %s: %s item(s), the first #%s of %s"
          % (recorded["checked"], recorded["total_items"], recorded["first_item"],
             recorded["first_item_created"]))
    return 0


if __name__ == "__main__":  # pragma: no cover - dispatch only; main() is tested directly
    sys.exit(main())
