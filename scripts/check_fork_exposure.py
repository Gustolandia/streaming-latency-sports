#!/usr/bin/env python3
"""How far the guard has travelled, recorded rather than asserted.

The manuscript said the guard's expression "appears unchanged in more than a dozen public
forks". A referee tried to check it and could not -- GitHub's API was unavailable during the
review -- so the claim sat in the paper unverifiable by anyone but its author. That is the
same defect the paper documents in others: a number with no path to its evidence.

This makes the path. It walks the fork list of the upstream repository, fetches
`WorkerStats.java` from each fork's default branch, and records whether the guard is present,
absent, or unreadable. The result is written to a CSV that ships with the artifact, and the
manuscript's number is emitted from that CSV rather than typed.

**The build does not depend on the network.** This script is run by hand, its output is
committed, and `emit_paper_numbers.py` reads the committed file. A build on a machine with no
GitHub access still produces the same manuscript, which is the point of committing the record.

**A fork whose file cannot be read counts as neither.** It may have deleted the file, renamed
the path, or gone private. Only a fork whose file was actually read can support or refute a
claim about what the file contains.

CLI:
    python scripts/check_fork_exposure.py                # refresh the record
    python scripts/check_fork_exposure.py --limit 40     # stop after N readable forks
"""

import argparse
import csv
import datetime
import json
import os
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join("docs", "results", "external", "fork_exposure.csv")

UPSTREAM = "openmessaging/benchmark"
GUARD_PATH = ("benchmark-framework/src/main/java/io/openmessaging/benchmark/worker/"
              "WorkerStats.java")
#: The expression the manuscript quotes. Matching the whole condition rather than a fragment:
#: "> 0" alone appears in unrelated code.
GUARD = "endToEndLatencyMicros > 0"

HEADERS = {"User-Agent": "streaming-latency-sports/fork-exposure",
           "Accept": "application/vnd.github+json"}

FIELDS = ["fork", "default_branch", "guard", "checked_utc"]


def _fetch(url, raw=False, tries=3, pause=2.0):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8", "replace")
            return body if raw else json.loads(body)
        except Exception as exc:  # noqa: BLE001 - any failure is "could not read"
            if attempt == tries - 1:
                return ("ERROR %s" % exc) if raw else {"error": str(exc)}
            time.sleep(pause)


def fork_names(upstream=UPSTREAM, pages=3):
    out = []
    for page in range(1, pages + 1):
        got = _fetch("https://api.github.com/repos/%s/forks?per_page=100&page=%d"
                     % (upstream, page))
        if isinstance(got, dict):
            break
        out.extend((f.get("full_name"), f.get("default_branch") or "master") for f in got)
        if len(got) < 100:
            break
    return out


def classify(fork, branch):
    """'unchanged', 'absent' or 'unreadable' for one fork."""
    body = _fetch("https://raw.githubusercontent.com/%s/%s/%s" % (fork, branch, GUARD_PATH),
                  raw=True)
    if body.startswith("ERROR") or "<html" in body[:200].lower():
        return "unreadable"
    return "unchanged" if GUARD in body else "absent"


def survey(limit=40, upstream=UPSTREAM):
    """Walk forks until `limit` of them have been read."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    rows, read = [], 0
    for fork, branch in fork_names(upstream):
        verdict = classify(fork, branch)
        rows.append({"fork": fork, "default_branch": branch, "guard": verdict,
                     "checked_utc": stamp})
        if verdict != "unreadable":
            read += 1
        if read >= limit:
            break
    return rows


def totals(rows):
    return {
        "checked": sum(1 for r in rows if r["guard"] != "unreadable"),
        "unchanged": sum(1 for r in rows if r["guard"] == "unchanged"),
        "absent": sum(1 for r in rows if r["guard"] == "absent"),
        "unreadable": sum(1 for r in rows if r["guard"] == "unreadable"),
    }


def read_record(path=DEFAULT_OUT):
    full = path if os.path.isabs(path) else os.path.join(REPO, path)
    if not os.path.exists(full):
        return []
    with open(full, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, default=40)
    args = ap.parse_args(argv)

    rows = survey(args.limit)
    if not rows:
        print("no forks reached; the committed record is left alone")
        return 1
    path = args.out if os.path.isabs(args.out) else os.path.join(REPO, args.out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    t = totals(rows)
    print("wrote %s" % args.out)
    print("  read %d forks: %d carry the guard unchanged, %d do not, %d unreadable"
          % (t["checked"], t["unchanged"], t["absent"], t["unreadable"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
