#!/usr/bin/env python3
"""
h3_stamping_runs.py
Per-run medians behind Table S26, read straight from the archived runs (round 81, W1).

Table S26 printed four medians over ten runs each, and a change row with no interval, and S2
built a sentence on that change. `analyze_depth.py` already computes a median per run before it
takes the median over runs, but it wrote only the second. This script writes the first, for both
H3 campaigns: E-C3, the table's ten runs per cell, and E-C4, the replication at thirty that the
experiment map lists and no table printed. `stat_intervals.h3_stamping_intervals` then
recomputes the interval from a committed file, with no archive needed.

Which runs belong to a cell is not guessed from run names. Each campaign's condition directory
in the results archive carries the run-id timestamp its trials share, which is how
`analyze_depth.condition_timestamp` reads it on disk.

CLI:
    python scripts/h3_stamping_runs.py --runs-archive cloud_archive/sbl_runs.tgz \
        --docs-archive cloud_archive/sbl_docs_results.tgz \
        --out docs/results/model/ec3_stamping_runs.csv
"""
import argparse
import csv
import io
import os
import re
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze_depth import transport_median_from_rows  # noqa: E402

#: The results tree each campaign lives under, and the name the supplement gives it.
CAMPAIGNS = {"depth": "E-C3", "depth_rep2": "E-C4"}
STAMPS = ("callback", "inline")
BACKENDS = ("kafka", "redis")
FIELDS = ["campaign", "stamp", "backend", "run", "median_ms"]

_CONDITION = re.compile(r"docs/results/(depth|depth_rep2)/ec3/(callback|inline)/"
                        r"concurrency_concurrency_(n\d+_\d{8}_\d{6})(?:/|$)")
_RUN_FILE = re.compile(r"(?:^|/)runs/(concurrency_(n\d+_\d{8}_\d{6})_(kafka|redis)_[^/]+)/"
                       r"(producer|consumer_events)\.csv$")


def campaign_timestamps(names):
    """{run-id timestamp: (campaign, stamp)} from the member names of the results archive."""
    out = {}
    for name in names:
        m = _CONDITION.search(name)
        if m:
            out[m.group(3)] = (CAMPAIGNS[m.group(1)], m.group(2))
    return out


def run_key(name, stamps):
    """(timestamp, backend, run, table) for a file of a wanted run, else None."""
    m = _RUN_FILE.search(name)
    if not m or m.group(2) not in stamps:
        return None
    return m.group(2), m.group(3), m.group(1), m.group(4)


def run_medians(members, stamps):
    """Rows of FIELDS from (member name, bytes) pairs.

    A run missing either table, or whose tables do not join into a single transport value, is
    left out rather than written as a default: the same rule `condition_transport_by_backend`
    applies, so the per-run file and the committed summary count the same runs.
    """
    tables = {}
    for name, data in members:
        key = run_key(name, stamps)
        if key is None:
            continue
        ts, backend, run, table = key
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        tables.setdefault((ts, backend, run), {})[table] = rows
    out = []
    for (ts, backend, run), t in tables.items():
        if "producer" not in t or "consumer_events" not in t:
            continue
        try:
            med = transport_median_from_rows(t["producer"], t["consumer_events"])
        except (ValueError, KeyError):
            med = None
        if med is None:
            continue
        campaign, stamp = stamps[ts]
        out.append({"campaign": campaign, "stamp": stamp, "backend": backend, "run": run,
                    "median_ms": "%.6f" % med})
    out.sort(key=lambda r: (r["campaign"], STAMPS.index(r["stamp"]),
                            BACKENDS.index(r["backend"]), r["run"]))
    return out


def archive_members(archive, wanted):
    """(name, bytes) for each regular file in a tar archive whose name `wanted` accepts."""
    with tarfile.open(archive, "r:*") as tar:
        for member in tar:
            if member.isfile() and wanted(member.name):
                yield member.name, tar.extractfile(member).read()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Per-run medians behind Table S26")
    ap.add_argument("--runs-archive", default=os.path.join("cloud_archive", "sbl_runs.tgz"))
    ap.add_argument("--docs-archive",
                    default=os.path.join("cloud_archive", "sbl_docs_results.tgz"))
    ap.add_argument("--out",
                    default=os.path.join("docs", "results", "model", "ec3_stamping_runs.csv"))
    args = ap.parse_args(argv)

    with tarfile.open(args.docs_archive, "r:*") as tar:
        stamps = campaign_timestamps(tar.getnames())
    if not stamps:
        print("no H3 condition directories in %s" % args.docs_archive)
        return 1
    rows = run_medians(archive_members(args.runs_archive,
                                       lambda n: run_key(n, stamps) is not None), stamps)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for campaign in sorted({r["campaign"] for r in rows}):
        print("%s: %d runs" % (campaign, sum(1 for r in rows if r["campaign"] == campaign)))
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
